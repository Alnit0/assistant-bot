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


# ---------------------------------------------------------------------------
# Replying to interactions (slash commands, buttons, forms) without ever raising
# ---------------------------------------------------------------------------
# 10062: Unknown interaction (it expired, or was never ours to answer)
# 40060: Interaction has already been acknowledged
INTERACTION_GONE_CODES = {10062, 40060}


def interaction_gone(error: BaseException) -> bool:
    """True if the error only means the interaction can no longer be answered."""
    error = getattr(error, "original", error)
    if isinstance(error, discord.InteractionResponded):
        return True
    return isinstance(error, discord.HTTPException) and error.code in INTERACTION_GONE_CODES


def describe_interaction(interaction: discord.Interaction) -> str:
    """A short name for an interaction, for log lines."""
    command = getattr(interaction, "command", None)
    if command is not None:
        name = command.qualified_name
    else:
        name = (getattr(interaction, "data", None) or {}).get("custom_id", "unknown")
    return f"{name} (user {interaction.user.id})"


async def safe_reply(interaction: discord.Interaction, text: str, ephemeral: bool = True) -> bool:
    """Reply to an interaction whether or not it has been answered already.

    Never raises: if Discord refuses, that is logged as a warning and False is
    returned. Safe to use from error handlers.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=ephemeral)
        else:
            try:
                await interaction.response.send_message(text, ephemeral=ephemeral)
            except discord.InteractionResponded:
                # Something answered between our check and our reply
                await interaction.followup.send(text, ephemeral=ephemeral)
    except discord.HTTPException as error:
        if interaction_gone(error):
            log.warning(
                "Could not reply to %s: the interaction expired or was already answered (code %s)",
                describe_interaction(interaction),
                error.code,
            )
        else:
            log.warning("Could not reply to %s: %s", describe_interaction(interaction), error)
        return False
    return True


async def report_interaction_error(
    interaction: discord.Interaction,
    error: Exception,
    title: str,
    reply: str = "⚠️ That didn't work. Check #bot-log.",
) -> None:
    """A button, select or form handler failed: log it, post a card, tell the user.

    An interaction that merely expired or was already answered gets a warning
    in the log and nothing else. Never raises.
    """
    if interaction_gone(error):
        log.warning(
            "%s: the interaction expired or was already answered (%s)",
            title,
            getattr(error, "original", error),
        )
        return
    log.error("%s", title, exc_info=error)
    await log_error(title, repr(error))
    await safe_reply(interaction, reply)


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
