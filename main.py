import asyncio
import logging

import discord
from discord import app_commands

from core import backup, cards, clock, conversation, database, day, devmode, instance_lock, interactions, lifecycle, live, scheduler, timing
from core.config import (
    CLAUDE_MODEL,
    DB_PATH,
    DEV_DATABASE,
    INBOX_CHANNEL_ID,
    MAX_HISTORY,
    TOKEN,
    now_nz,
    real_now_nz,
)
from core.context import Context
from core.discord_utils import (
    COLOUR_INFO,
    bind_client,
    interaction_gone,
    log_error,
    safe_reply,
    send_log,
    truncate,
)
from core.lifecycle import MessageClass
from core.logging_setup import setup_logging
from core.migrations import migrate
from core.permissions import is_allowed
from core.users import ensure_owner, get_user_by_discord_id
from tasks import registry

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Client and state
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
bind_client(client)

# Slash commands and context menus from tasks, synced to our server at startup
tree = app_commands.CommandTree(client)
slash_status = "not set up yet"

# Seconds a button, select or form handler gets to answer before we step in
# (Discord gives up at 3)
INTERACTION_GRACE = 2.0

# Running totals since the bot started

scheduler.register_handler(backup.JOB_TASK, backup.JOB_KIND, backup.nightly_backup_job)
scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job)
# What `dev run <name>` can run (the sweep and summary register theirs when they exist)
devmode.register_routine("backup", backup.run_nightly_backup)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
async def setup_slash_commands() -> str:
    """Register tasks' slash commands with our server. Returns a line for the start card."""
    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel is None:
        return "not synced (inbox channel not found)"
    guild = channel.guild

    for command in registry.app_commands():
        tree.add_command(command, guild=guild)
    try:
        # Replaces whatever was there before, so commands of disabled tasks disappear
        synced = await tree.sync(guild=guild)
    except discord.HTTPException as error:
        log.exception("Could not sync slash commands")
        await log_error("Slash command sync failed", str(error))
        return "sync failed (see the error card)"
    log.info("Slash commands synced to %s: %s", guild.name, len(synced))
    return f"{len(synced)} synced to {guild.name}"


@tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    # An error handler must never raise: discord.py would only report "Task exception"
    try:
        # A failed check has already told the user why
        if isinstance(error, app_commands.CheckFailure):
            return
        command = interaction.command.qualified_name if interaction.command else "unknown"
        gone = interaction_gone(error)
        if gone:
            # Too late to answer (10062) or something already did (40060): nothing is broken
            log.warning(
                "Slash command %s: the interaction expired or was already answered (%s)",
                command,
                getattr(error, "original", error),
            )
        else:
            log.error("Slash command failed: %s", command, exc_info=error)

        # Close the log row and explain, if the command was a logged one
        explained = await interactions.fail(interaction, error)
        await registry.emit("app_command_error", interaction, error)
        if not explained and not gone and not interaction.response.is_done():
            await safe_reply(interaction, "⚠️ Command failed. Check #bot-log.")
    except Exception:
        log.exception("The slash command error handler itself failed")


# ---------------------------------------------------------------------------
# Discord events
# ---------------------------------------------------------------------------
@client.event
async def setup_hook():
    # Runs once after login, before connecting: persistent buttons get registered here
    cards.setup(client)
    conversation.setup()
    registry.setup(client)


@client.event
async def on_interaction(interaction: discord.Interaction):
    """Catch button, select and form presses that nothing answered.

    Discord shows "interaction failed" after 3 seconds, and discord.py drops a
    press it has no handler for without a word (an expired button, or one from
    before a restart). Slash commands report their own failures.
    """
    if interaction.type not in (
        discord.InteractionType.component,
        discord.InteractionType.modal_submit,
    ):
        return
    await asyncio.sleep(INTERACTION_GRACE)
    if interaction.response.is_done():
        return

    custom_id = (interaction.data or {}).get("custom_id", "unknown")
    message_id = interaction.message.id if interaction.message else None
    log.warning(
        "Interaction not answered within %ss: custom_id=%s user=%s message=%s",
        INTERACTION_GRACE,
        custom_id,
        interaction.user.id,
        message_id,
    )
    await safe_reply(
        interaction,
        "⌛ That button or form no longer works. It expired, or the bot has "
        "restarted since it was posted. Run the command again.",
    )
    await log_error(
        "Interaction not answered",
        f"Nothing handled `{custom_id}` within {INTERACTION_GRACE}s "
        f"(user {interaction.user.id}, message {message_id}).",
    )


@client.event
async def on_ready():
    global slash_status
    log.info("Logged in as %s (id %s)", client.user, client.user.id)

    # on_ready fires again after a reconnect; only set up once
    if slash_status == "not set up yet":
        slash_status = await setup_slash_commands()
        await registry.startup(client)
        await backup.schedule_next_backup()
        await day.schedule_next()
    # After the tasks are ready: jobs that came due while we were off run now
    scheduler.start()

    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel:
        dev_database = " · 🧪 **DEV DATABASE**" if DEV_DATABASE else ""
        await channel.send(f"👋 Online and ready. Type `help` for commands.{dev_database}")
    else:
        log.warning("Could not find the inbox channel. Check INBOX_CHANNEL_ID.")

    embed = discord.Embed(title="🟢 Bot started", colour=COLOUR_INFO, timestamp=real_now_nz())
    embed.add_field(name="Model", value=CLAUDE_MODEL, inline=True)
    embed.add_field(name="History limit", value=f"{MAX_HISTORY} messages", inline=True)
    embed.add_field(
        name="Database", value=f"{DB_PATH.name} (DEV DATABASE)" if DEV_DATABASE else DB_PATH.name, inline=True
    )
    if clock.is_shifted():
        embed.add_field(name="Clock", value=f"{now_nz():%a %d %b, %I:%M %p} (moved ahead)", inline=True)
    embed.add_field(name="Tasks", value=truncate(registry.summary()), inline=False)
    embed.add_field(name="Slash commands", value=truncate(slash_status), inline=False)
    if registry.problems():
        embed.add_field(
            name="⚠️ Skipped", value=truncate("\n".join(registry.problems())), inline=False
        )
    if registry.missing_descriptions():
        embed.add_field(
            name="⚠️ Missing descriptions",
            value=truncate("\n".join(registry.missing_descriptions())),
            inline=False,
        )
    await send_log(embed)


SEEN = "👀"


async def _mark_seen(message: discord.Message) -> None:
    """Show at once that a chat message has arrived and is being worked on."""
    try:
        await message.add_reaction(SEEN)
        await message.channel.typing()
    except discord.HTTPException as error:
        log.info("Could not mark a message as seen: %s", error)


FAILED = "⚠️"


async def _unmark_seen(message: discord.Message, failed: bool = False) -> None:
    """Done with a message: the 👀 comes off, whether or not anything was said
    (one that stays means the bot is stuck). If it went wrong, ⚠️ takes its
    place. Nothing else is left on a message: ✅ is not used to acknowledge."""
    try:
        await message.remove_reaction(SEEN, client.user)
    except discord.HTTPException as error:
        log.info("Could not clear the seen mark: %s", error)
    if failed:
        try:
            await message.add_reaction(FAILED)
        except discord.HTTPException as error:
            log.info("Could not mark a message as failed: %s", error)


@client.event
async def on_message(message: discord.Message):
    # Discord's "X pinned a message" notices are clutter: remove every one
    if message.type is discord.MessageType.pins_add:
        if lifecycle.deletes(MessageClass.TRANSIENT):
            try:
                await message.delete()
            except discord.HTTPException as error:
                log.info("Could not delete a pin notice: %s", error)
        return
    # Ignore bots (including itself) and anyone who isn't allowed
    if message.author.bot:
        return
    user = await get_user_by_discord_id(message.author.id)
    if not is_allowed(user, "message"):
        return

    text = message.content.strip()
    if not text:
        return

    # A reply with an action word acts on the message replied to; a registered
    # word or phrase runs its task. Each decides for itself where it works.
    ctx = Context.from_message(message, user)
    if await registry.dispatch_reply_action(ctx):
        return
    if await registry.dispatch_keyword(ctx):
        return
    # A task may be waiting for this user's next message in this channel
    if await registry.dispatch_expected(ctx):
        return
    # Or take it because of where it was sent (a note in a bug's post)
    if await registry.dispatch_claimed(ctx):
        return

    # Plain words are read in the inbox and the hub
    if not conversation.listens_in(message.channel.id):
        return
    in_inbox = message.channel.id == INBOX_CHANNEL_ID
    log.info("Received: %s", text)

    # Seen: 👀 straight away, and "typing" with it. Neither is waited for
    timing.start()
    live.background(_mark_seen(message))

    # One way for every message that is no shortcut: the router says whether it is
    # for a task, a general question or nothing at all, and the task's own code (or
    # plain chat, which has no tools and no access to my data) does the rest
    failed = False
    try:
        handled = await conversation.handle(ctx, registry.capabilities_text(user, message.channel.id))
        failed = handled.failed
    except Exception as error:
        log.exception("Could not handle a message")
        await log_error("Message failed", repr(error), text)
        failed = True
    finally:
        # The 👀 always comes off: one that stays means the bot is stuck
        live.background(_unmark_seen(message, failed))
        timing.stop()
    await registry.emit(
        "action_finished",
        registry.ActionResult("chat", "chat", "error" if failed else "ok", user.id, message.channel.id),
    )


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # The bot's own reactions are never input
    if payload.user_id == client.user.id:
        return
    await registry.emit("raw_reaction_add", payload)
    # Registered reactions are checked at once, then acted on after a quiet period,
    # so they can be undone
    await registry.reaction_changed(payload, added=True)


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id:
        return
    await registry.emit("raw_reaction_remove", payload)
    await registry.reaction_changed(payload, added=False)


@client.event
async def on_guild_channel_pins_update(channel, last_pin):
    await registry.emit("guild_channel_pins_update", channel, last_pin)


@client.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    await interactions.finish(interaction)
    await registry.emit("app_command_completion", interaction, command)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    setup_logging()
    if DEV_DATABASE:
        log.info("Started with --dev: using the dev database %s", DB_PATH.name)
    # Before anything touches the database or Discord: only one copy may run
    instance_lock.acquire()
    registry.load()
    migrate(registry.task_migrations())
    ensure_owner()
    client.run(TOKEN, log_handler=None)
