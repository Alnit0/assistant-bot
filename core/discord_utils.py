import logging

import discord

from core.config import BOT_LOG_CHANNEL_ID, DISCORD_LIMIT, EMBED_FIELD_LIMIT, now_nz

log = logging.getLogger("assistant")

COLOUR_INFO = discord.Colour.blurple()
COLOUR_OK = discord.Colour.green()
COLOUR_ERROR = discord.Colour.red()

# The Discord client, set once by main.py so send_log can find #bot-log
client: discord.Client | None = None


def bind_client(discord_client: discord.Client) -> None:
    """Tell this module which Discord client to post through."""
    global client
    client = discord_client


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


def truncate(text: str, limit: int = EMBED_FIELD_LIMIT) -> str:
    """Shorten text for embed fields, which have a character limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def send_log(embed: discord.Embed) -> None:
    """Post an embed to #bot-log, if configured. Never crashes the bot."""
    if BOT_LOG_CHANNEL_ID is None:
        return
    channel = client.get_channel(BOT_LOG_CHANNEL_ID)
    if channel is None:
        log.warning("Could not find the bot-log channel. Check BOT_LOG_CHANNEL_ID.")
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        log.exception("Failed to send to bot-log")


async def log_simple(title: str, description: str | None = None) -> None:
    embed = discord.Embed(title=title, colour=COLOUR_INFO, timestamp=now_nz())
    if description:
        embed.description = truncate(description, 4000)
    await send_log(embed)


async def log_error(title: str, details: str, user_text: str | None = None) -> None:
    embed = discord.Embed(title=f"⚠️ {title}", colour=COLOUR_ERROR, timestamp=now_nz())
    if user_text:
        embed.add_field(name="Input", value=truncate(user_text), inline=False)
    embed.add_field(name="Details", value=truncate(details), inline=False)
    await send_log(embed)
