import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
import discord
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
INBOX_CHANNEL_ID = os.getenv("INBOX_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

missing = [
    name
    for name, value in {
        "DISCORD_TOKEN": TOKEN,
        "OWNER_ID": OWNER_ID,
        "INBOX_CHANNEL_ID": INBOX_CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }.items()
    if not value
]
if missing:
    sys.exit(f"Missing settings in .env: {', '.join(missing)}")

OWNER_ID = int(OWNER_ID)
INBOX_CHANNEL_ID = int(INBOX_CHANNEL_ID)

TIMEZONE = ZoneInfo("Pacific/Auckland")
MAX_HISTORY = 10  # number of recent messages (yours and the bot's) sent to Claude
MAX_TOKENS = 1024  # maximum length of each Claude reply
DISCORD_LIMIT = 2000  # Discord's maximum message length

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Short-term conversation memory (cleared when the bot restarts)
history: list[dict] = []


def build_system_prompt() -> str:
    now = datetime.now(TIMEZONE).strftime("%A %d %B %Y, %I:%M %p")
    return (
        "You are Hive, a personal assistant for Alex, chatting through Discord. "
        "Alex lives in Auckland, New Zealand. "
        f"The current date and time in Auckland is {now}. "
        "Use UK spelling. Keep replies short and conversational, suited to reading on a phone. "
        "Use simple Discord markdown (bold, short bullet lists) only when it genuinely helps."
    )


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split long replies into chunks Discord will accept, preferring line breaks."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def ask_claude(user_text: str) -> str:
    """Send the message plus recent history to Claude and return the reply."""
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    history.append({"role": "user", "content": user_text})

    try:
        response = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(),
            messages=history,
        )
    except Exception:
        # Remove the failed message so history stays valid
        history.pop()
        raise

    reply = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if not reply:
        reply = "(No reply from Claude.)"

    history.append({"role": "assistant", "content": reply})

    log.info(
        "Claude usage: %s in, %s out (%s)",
        response.usage.input_tokens,
        response.usage.output_tokens,
        CLAUDE_MODEL,
    )
    return reply


# ---------------------------------------------------------------------------
# Discord events
# ---------------------------------------------------------------------------
@client.event
async def on_ready():
    log.info("Logged in as %s (id %s)", client.user, client.user.id)
    channel = client.get_channel(INBOX_CHANNEL_ID)
    if channel:
        await channel.send("👋 Online and ready.")
    else:
        log.warning("Could not find the inbox channel. Check INBOX_CHANNEL_ID.")


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
    command = text.lower()

    # Simple built-in commands that don't need Claude
    if command == "ping":
        await message.channel.send("🏓 Pong!")
        return

    if command == "reset":
        history.clear()
        await message.channel.send("🧹 Conversation memory cleared.")
        return

    # Everything else goes to Claude
    async with message.channel.typing():
        try:
            reply = await ask_claude(text)
        except anthropic.APIStatusError as error:
            log.error("Claude API error %s: %s", error.status_code, error.message)
            await message.channel.send(f"⚠️ Claude API error ({error.status_code}). Check the logs.")
            return
        except anthropic.APIConnectionError:
            log.exception("Could not reach the Claude API")
            await message.channel.send("⚠️ Couldn't reach Claude. Check the internet connection.")
            return
        except Exception:
            log.exception("Unexpected error while asking Claude")
            await message.channel.send("⚠️ Something went wrong. Check the logs.")
            return

    for chunk in split_message(reply):
        await message.channel.send(chunk)


client.run(TOKEN, log_handler=None)