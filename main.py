import asyncio
import logging

import discord
from discord import app_commands

from core import account, backup, cards, clock, conversation, database, day, devmode, health, identity, instance_lock, interactions, lifecycle, live, messages, missed, nightly, restart, scheduler, tidy, timing
from core.config import SEPARATE_BOT
from core.config import mine as my_channel
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

scheduler.register_handler(backup.JOB_TASK, backup.JOB_KIND, backup.nightly_backup_job, backup.JOB_LABEL)
scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job, day.JOB_LABEL)
nightly.setup()  # live's own: the self-test the dev bot runs at night, behind NIGHTLY_SELFTEST
health.setup()  # the core's own attention items: what is wrong with the bot itself, and the next morning
tidy.setup()
messages.setup()


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
async def setup_slash_commands() -> str:
    """Register tasks' slash commands with our server. Returns a line for the start card."""
    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel is None:
        return "not synced (inbox channel not found)"
    guild = channel.guild

    # The dev bot registers none: the server shows only live's. Its empty list is still
    # sent, so any it registered on an earlier start go
    for command in slash_commands_for(SEPARATE_BOT, registry.app_commands()):
        tree.add_command(command, guild=guild)
    try:
        # Replaces whatever was there before, so commands of disabled tasks disappear
        synced = await tree.sync(guild=guild)
    except discord.HTTPException as error:
        log.exception("Could not sync slash commands")
        await log_error("Slash command sync failed", str(error))
        return "sync failed (see the error card)"
    if SEPARATE_BOT:
        log.info("Slash commands: none registered (the dev bot has none; any it had in %s are removed)", guild.name)
        return "none: the dev bot registers no slash commands"
    log.info("Slash commands synced to %s: %s", guild.name, len(synced))
    return f"{len(synced)} synced to {guild.name}"


def slash_commands_for(dev_bot: bool, commands: list) -> list:
    """The slash commands and context menus this bot registers with the server:
    the tasks' own for live, none for the dev bot."""
    return [] if dev_bot else list(commands)


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
    # Before the first thing it does: is this the account it is meant to be? If not it
    # disconnects and exits here, having posted, renamed and touched nothing
    if not await account.still_right(client):
        return

    # on_ready fires again after a reconnect; only set up once
    if slash_status == "not set up yet":
        slash_status = await setup_slash_commands()
        await registry.startup(client)
        # Every schedule's next run (the backup, the end of the day, a task's morning post)
        await scheduler.book()
        # After the tasks are ready: what was cut off by the stop is put right, the jobs
        # that came due while we were off run now, and all of it is said once in #bot-log
        await restart.catch_up()
        # And what I said meanwhile: each message gets a card that asks, never an answer
        await missed.look()
    scheduler.start()
    missed.start()
    health.start()  # the bot's own memory use, looked at and logged every hour
    # Which bot this is, for anyone looking: the nickname and the status line
    await identity.start()

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


def _mine(channel) -> bool:
    """Whether a channel is this bot's to act in. With a dev bot in the server
    there are two bots that see everything: each keeps to its own channels
    (core/config.py, `mine`)."""
    return my_channel(getattr(channel, "id", None), getattr(channel, "parent_id", None))


async def _sender(message: discord.Message):
    """Who sent a message, if it is one the bot acts on: not a bot's (its own
    included), in a channel that is this bot's, from someone allowed, with
    words in it. None otherwise."""
    if message.author.bot or not _mine(message.channel):
        return None
    user = await get_user_by_discord_id(message.author.id)
    if not is_allowed(user, "message") or not message.content.strip():
        return None
    return user


@client.event
async def on_message(message: discord.Message):
    # Discord's "X pinned a message" notices are clutter: remove every one
    if message.type is discord.MessageType.pins_add:
        if _mine(message.channel) and lifecycle.deletes(MessageClass.TRANSIENT):
            try:
                await message.delete()
            except discord.HTTPException as error:
                log.info("Could not delete a pin notice: %s", error)
        return
    user = await _sender(message)
    if user is None:
        return
    missed.saw(message.id)  # it arrived: never asked about after a restart
    await _take(message, user)


async def _take(message: discord.Message, user) -> None:
    """Take a message of mine: one that has just arrived, or one sent while
    the bot was off that I have said to handle now (core/missed.py)."""
    text = message.content.strip()
    # Said in the hub with the tidy on: it is recorded, and it and the reply go once it is
    # handled (core/messages.py). Anywhere else, and with the tidy off, this does nothing
    await messages.begin(message.id, message.channel.id, user.id)
    failed = False
    try:
        failed = await _handle(message, user, text)
    finally:
        await messages.handled(message.id, failed)


async def _handle(message: discord.Message, user, text: str) -> bool:
    """Handle one message of the owner's. Returns whether it failed."""
    # A reply with an action word acts on the message replied to; a registered
    # word or phrase runs its task. Each decides for itself where it works.
    ctx = Context.from_message(message, user)
    if await registry.dispatch_reply_action(ctx):
        return False
    if await registry.dispatch_keyword(ctx):
        return False
    # A task may be waiting for this user's next message in this channel
    if await registry.dispatch_expected(ctx):
        return False
    # Or take it because of where it was sent (a note in a bug's post)
    if await registry.dispatch_claimed(ctx):
        return False

    # Plain words are read in the inbox and the hub
    if not conversation.listens_in(message.channel.id):
        return False
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
    return failed


def _mine_id(channel_id: int) -> bool:
    """`_mine` for an event that only brings the channel's id (a thread is its parent's)."""
    channel = client.get_channel(channel_id)
    return _mine(channel) if channel is not None else my_channel(channel_id)


missed.setup(_sender, _take)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # The bot's own reactions are never input, nor is one in the other bot's channels
    if payload.user_id == client.user.id or not _mine_id(payload.channel_id):
        return
    await registry.emit("raw_reaction_add", payload)
    # Registered reactions are checked at once, then acted on after a quiet period,
    # so they can be undone
    await registry.reaction_changed(payload, added=True)


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id or not _mine_id(payload.channel_id):
        return
    await registry.emit("raw_reaction_remove", payload)
    await registry.reaction_changed(payload, added=False)


@client.event
async def on_guild_channel_pins_update(channel, last_pin):
    if _mine(channel):
        await registry.emit("guild_channel_pins_update", channel, last_pin)


@client.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    await interactions.finish(interaction)
    await registry.emit("app_command_completion", interaction, command)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
def start() -> None:
    setup_logging()
    if DEV_DATABASE:
        log.info("Started with --dev: using the dev database %s", DB_PATH.name)
    # First of all: the token logs in as the account this start is meant to be (live or
    # the dev bot). Asked over HTTP; a wrong account exits here with nothing touched
    account.check(TOKEN)
    # Then, before anything touches the database or the gateway: only one copy may run
    instance_lock.acquire()
    registry.load()
    migrate(registry.task_migrations())
    ensure_owner()
    client.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    start()
