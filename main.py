import logging
import time

import anthropic
import discord

from core.commands import handle_command
from core.config import (
    CLAUDE_MODEL,
    DB_PATH,
    INBOX_CHANNEL_ID,
    MAX_HISTORY,
    OWNER_ID,
    TOKEN,
    now_nz,
)
from core.database import init_db, log_received, log_result
from core.discord_utils import (
    COLOUR_INFO,
    COLOUR_OK,
    bind_client,
    log_error,
    send_log,
    split_message,
    truncate,
)
from core.llm import ask_claude, estimate_cost, format_cost, history
from core.logging_setup import setup_logging

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Client and state
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
bind_client(client)

# Running totals since the bot started
session_stats = {"messages": 0, "cost": 0.0}


# ---------------------------------------------------------------------------
# Discord events
# ---------------------------------------------------------------------------
@client.event
async def on_ready():
    log.info("Logged in as %s (id %s)", client.user, client.user.id)

    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel:
        await channel.send("👋 Online and ready. Type `help` for commands.")
    else:
        log.warning("Could not find the inbox channel. Check INBOX_CHANNEL_ID.")

    embed = discord.Embed(title="🟢 Bot started", colour=COLOUR_INFO, timestamp=now_nz())
    embed.add_field(name="Model", value=CLAUDE_MODEL, inline=True)
    embed.add_field(name="History limit", value=f"{MAX_HISTORY} messages", inline=True)
    embed.add_field(name="Database", value=DB_PATH.name, inline=True)
    await send_log(embed)


@client.event
async def on_message(message: discord.Message):
    # Ignore bots (including itself), anyone who isn't you, and other channels
    if message.author.bot:
        return
    if message.author.id != OWNER_ID:
        return
    if message.channel.id != INBOX_CHANNEL_ID:
        return

    text = message.content.strip()
    if not text:
        return

    log.info("Received: %s", text)

    # Built-in commands first
    if await handle_command(message, text.lower()):
        return

    # Everything else goes to Claude. Log the raw input before processing.
    row_id = log_received(text, "chat", message.id, message.channel.id)
    started = time.perf_counter()

    async with message.channel.typing():
        try:
            reply, input_tokens, output_tokens = await ask_claude(text)
        except anthropic.APIStatusError as error:
            duration = time.perf_counter() - started
            log.error("Claude API error %s: %s", error.status_code, error.message)
            log_result(
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
            log_result(row_id, status="error", error=repr(error), model=CLAUDE_MODEL, duration_s=duration)
            await message.channel.send("⚠️ Couldn't reach Claude. Check the internet connection.")
            await log_error("Connection error", repr(error), text)
            return
        except Exception as error:
            duration = time.perf_counter() - started
            log.exception("Unexpected error while asking Claude")
            log_result(row_id, status="error", error=repr(error), model=CLAUDE_MODEL, duration_s=duration)
            await message.channel.send("⚠️ Something went wrong. Check #bot-log.")
            await log_error("Unexpected error", repr(error), text)
            return

    duration = time.perf_counter() - started

    for chunk in split_message(reply):
        await message.channel.send(chunk)

    cost = estimate_cost(CLAUDE_MODEL, input_tokens, output_tokens)
    log_result(
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
    embed.add_field(name="History", value=f"{len(history)} messages", inline=True)
    embed.add_field(
        name="Session total",
        value=f"{session_stats['messages']} msgs · {format_cost(session_stats['cost'])}",
        inline=True,
    )
    await send_log(embed)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    setup_logging()
    init_db()
    client.run(TOKEN, log_handler=None)
