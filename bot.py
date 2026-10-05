import logging
import os
import sys

import discord
from dotenv import load_dotenv

# Load settings from .env
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
INBOX_CHANNEL_ID = os.getenv("INBOX_CHANNEL_ID")

if not TOKEN or not OWNER_ID or not INBOX_CHANNEL_ID:
    sys.exit("Missing settings: check DISCORD_TOKEN, OWNER_ID and INBOX_CHANNEL_ID in .env")

OWNER_ID = int(OWNER_ID)
INBOX_CHANNEL_ID = int(INBOX_CHANNEL_ID)

# Logging to the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("assistant")

# Intents: what the bot is allowed to receive from Discord
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


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

    log.info("Received: %s", message.content)

    text = message.content.strip().lower()

    if text == "ping":
        await message.channel.send("🏓 Pong!")
        return

    await message.channel.send(f"Got it: {message.content}")


client.run(TOKEN, log_handler=None)