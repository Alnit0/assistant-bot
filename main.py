import asyncio
import logging
import time

import anthropic
import discord
from discord import app_commands

from core import backup, instance_lock, interactions, scheduler
from core.config import (
    CLAUDE_MODEL,
    DB_PATH,
    INBOX_CHANNEL_ID,
    MAX_HISTORY,
    TOKEN,
    now_nz,
)
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import (
    COLOUR_INFO,
    COLOUR_OK,
    bind_client,
    interaction_gone,
    log_error,
    safe_reply,
    send_log,
    split_message,
    truncate,
)
from core.llm import ask_claude, estimate_cost, format_cost, history_for
from core.logging_setup import setup_logging
from core.migrations import migrate
from core.permissions import is_allowed
from core.users import ensure_owner, get_user_by_discord_id
from skills import registry

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Client and state
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
bind_client(client)

# Slash commands and context menus from skills, synced to our server at startup
tree = app_commands.CommandTree(client)
slash_status = "not set up yet"

# Seconds a button, select or form handler gets to answer before we step in
# (Discord gives up at 3)
INTERACTION_GRACE = 2.0

# Running totals since the bot started
session_stats = {"messages": 0, "cost": 0.0}

scheduler.register_handler(backup.JOB_SKILL, backup.JOB_KIND, backup.nightly_backup_job)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------
async def setup_slash_commands() -> str:
    """Register skills' slash commands with our server. Returns a line for the start card."""
    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel is None:
        return "not synced (inbox channel not found)"
    guild = channel.guild

    for command in registry.app_commands():
        tree.add_command(command, guild=guild)
    try:
        # Replaces whatever was there before, so commands of disabled skills disappear
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
    # After the skills are ready: jobs that came due while we were off run now
    scheduler.start()

    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel:
        await channel.send("👋 Online and ready. Type `help` for commands.")
    else:
        log.warning("Could not find the inbox channel. Check INBOX_CHANNEL_ID.")

    embed = discord.Embed(title="🟢 Bot started", colour=COLOUR_INFO, timestamp=now_nz())
    embed.add_field(name="Model", value=CLAUDE_MODEL, inline=True)
    embed.add_field(name="History limit", value=f"{MAX_HISTORY} messages", inline=True)
    embed.add_field(name="Database", value=DB_PATH.name, inline=True)
    embed.add_field(name="Skills", value=truncate(registry.summary()), inline=False)
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


@client.event
async def on_message(message: discord.Message):
    # Discord's "X pinned a message" notices are clutter: remove every one
    if message.type is discord.MessageType.pins_add:
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
    # word or phrase runs its skill. Each decides for itself where it works.
    ctx = Context.from_message(message, user)
    if await registry.dispatch_reply_action(ctx):
        return
    if await registry.dispatch_keyword(ctx):
        return
    # A skill may be waiting for this user's next message in this channel
    if await registry.dispatch_expected(ctx):
        return

    # Chatting with Claude only happens in the inbox
    if message.channel.id != INBOX_CHANNEL_ID:
        return
    log.info("Received: %s", text)

    # Everything else goes to Claude. Log the raw input before processing.
    row_id = await log_received(text, "chat", message.id, message.channel.id, user_id=user.id)
    started = time.perf_counter()

    async with message.channel.typing():
        try:
            # Tell Claude what the bot itself can do here, so it can point the user to it
            capabilities = registry.capabilities_text(user, message.channel.id)
            reply, input_tokens, output_tokens = await ask_claude(
                text, capabilities, channel_id=message.channel.id
            )
        except anthropic.APIStatusError as error:
            duration = time.perf_counter() - started
            log.error("Claude API error %s: %s", error.status_code, error.message)
            await log_result(
                row_id,
                status="error",
                error=f"{error.status_code}: {error.message}",
                model=CLAUDE_MODEL,
                duration_s=duration,
            )
            await message.channel.send(f"⚠️ Claude API error ({error.status_code}). Check #bot-log.")
            await log_error(f"Claude API error {error.status_code}", str(error.message), text)
            return
        except anthropic.APIConnectionError as error:
            duration = time.perf_counter() - started
            log.exception("Could not reach the Claude API")
            await log_result(row_id, status="error", error=repr(error), model=CLAUDE_MODEL, duration_s=duration)
            await message.channel.send("⚠️ Couldn't reach Claude. Check the internet connection.")
            await log_error("Connection error", repr(error), text)
            return
        except Exception as error:
            duration = time.perf_counter() - started
            log.exception("Unexpected error while asking Claude")
            await log_result(row_id, status="error", error=repr(error), model=CLAUDE_MODEL, duration_s=duration)
            await message.channel.send("⚠️ Something went wrong. Check #bot-log.")
            await log_error("Unexpected error", repr(error), text)
            return

    duration = time.perf_counter() - started

    for chunk in split_message(reply):
        await message.channel.send(chunk)

    cost = estimate_cost(CLAUDE_MODEL, input_tokens, output_tokens)
    await log_result(
        row_id,
        reply=reply,
        model=CLAUDE_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        duration_s=duration,
        status="ok",
    )

    session_stats["messages"] += 1
    if cost is not None:
        session_stats["cost"] += cost

    # Log card for #bot-log
    embed = discord.Embed(title="💬 Message handled", colour=COLOUR_OK, timestamp=now_nz())
    embed.add_field(name="Input", value=truncate(text), inline=False)
    embed.add_field(name="Reply", value=truncate(reply), inline=False)
    embed.add_field(name="Model", value=CLAUDE_MODEL, inline=True)
    embed.add_field(name="Tokens", value=f"{input_tokens} in / {output_tokens} out", inline=True)
    embed.add_field(name="Est. cost", value=format_cost(cost), inline=True)
    embed.add_field(name="Time", value=f"{duration:.1f}s", inline=True)
    embed.add_field(
        name="History", value=f"{len(history_for(message.channel.id))} messages", inline=True
    )
    embed.add_field(
        name="Session total",
        value=f"{session_stats['messages']} msgs · {format_cost(session_stats['cost'])}",
        inline=True,
    )
    await send_log(embed)
    await registry.emit(
        "action_finished",
        registry.ActionResult("chat", "chat", "ok", user.id, message.channel.id, reply=reply),
    )


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # The bot's own reactions are never input
    if payload.user_id == client.user.id:
        return
    await registry.emit("raw_reaction_add", payload)
    # Registered reactions are acted on after a quiet period, so they can be undone
    registry.reaction_changed(payload, added=True)


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id:
        return
    await registry.emit("raw_reaction_remove", payload)
    registry.reaction_changed(payload, added=False)


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
    # Before anything touches the database or Discord: only one copy may run
    instance_lock.acquire()
    registry.load()
    migrate(registry.skill_migrations())
    ensure_owner()
    client.run(TOKEN, log_handler=None)
