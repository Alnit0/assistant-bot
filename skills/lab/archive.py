import logging
import re

import discord
from discord import app_commands

from core.config import ARCHIVE_CHANNEL_ID, BOT_LOG_CHANNEL_ID
from core.users import User
from skills.lab.common import LabError, lab_check, note

log = logging.getLogger("assistant")

ARCHIVE_EMOJI = "📦"
WEBHOOK_NAME = "Hive Archive"
MAX_EMBEDS = 10  # Discord's limit per message; one is used for the "archived from" note

_client: discord.Client | None = None
_webhook: discord.Webhook | None = None


def bind(client: discord.Client) -> None:
    global _client
    _client = client


def safe_username(name: str) -> str:
    """Webhook names can't contain "discord" or "clyde", and must be 1 to 80 characters."""
    name = re.sub(r"discord", "d*scord", name, flags=re.IGNORECASE)
    name = re.sub(r"clyde", "cl*de", name, flags=re.IGNORECASE)
    return name.strip()[:80] or "Unknown"


def check_archivable(message: discord.Message) -> None:
    """Raise LabError if this message shouldn't or can't be archived."""
    if ARCHIVE_CHANNEL_ID is None:
        raise LabError("ARCHIVE_CHANNEL_ID isn't set in .env, so there's nowhere to archive to.")
    if message.channel.id == ARCHIVE_CHANNEL_ID:
        raise LabError("That message is already in the archive.")
    if BOT_LOG_CHANNEL_ID is not None and message.channel.id == BOT_LOG_CHANNEL_ID:
        raise LabError("Messages in #bot-log stay where they are.")
    if not (message.content or message.attachments or message.embeds):
        raise LabError("There's nothing in that message I can copy (no text, files or embeds).")

    limit = message.guild.filesize_limit if message.guild else 10 * 1024 * 1024
    for attachment in message.attachments:
        if attachment.size > limit:
            raise LabError(
                f"`{attachment.filename}` is too big for me to re-upload "
                f"({attachment.size / 1_048_576:.1f} MB), so I've left the message where it is."
            )


def build_info_embed(message: discord.Message) -> discord.Embed:
    """The note under the archived copy: where and when it was originally posted."""
    posted = int(message.created_at.timestamp())
    embed = discord.Embed(
        description=(
            f"{ARCHIVE_EMOJI} Archived from {message.channel.mention} · "
            f"[where it was]({message.jump_url})\n"
            f"Originally posted <t:{posted}:F> (<t:{posted}:R>)"
        ),
        colour=discord.Colour.dark_grey(),
        timestamp=message.created_at,
    )
    embed.set_footer(text="Originally posted")
    return embed


async def _get_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """Our webhook in the archive channel: reuse it if it exists, create it once if not."""
    global _webhook
    if _webhook is not None and _webhook.channel_id == channel.id:
        return _webhook
    try:
        for webhook in await channel.webhooks():
            if webhook.user and webhook.user.id == _client.user.id and webhook.token:
                _webhook = webhook
                return webhook
        _webhook = await channel.create_webhook(name=WEBHOOK_NAME, reason="Archiving messages")
    except discord.Forbidden:
        raise LabError(f"I need the Manage Webhooks permission in {channel.mention} to archive.")
    return _webhook


async def archive_message(message: discord.Message) -> str:
    """Copy a message to the archive channel, then delete the original.

    Returns a one-line summary. Raises LabError, leaving the original alone,
    if the copy can't be made in full.
    """
    global _webhook
    check_archivable(message)
    channel = _client.get_channel(ARCHIVE_CHANNEL_ID)
    if channel is None or not hasattr(channel, "webhooks"):
        raise LabError("I can't find the archive channel. Check ARCHIVE_CHANNEL_ID.")
    webhook = await _get_webhook(channel)

    try:
        files = [
            await attachment.to_file(spoiler=attachment.is_spoiler())
            for attachment in message.attachments
        ]
    except discord.HTTPException as error:
        raise LabError(f"I couldn't download an attachment ({error.status}), so nothing was archived.")

    # Keep the original's own embeds (not link previews, which Discord rebuilds)
    embeds = [embed for embed in message.embeds if embed.type == "rich"][: MAX_EMBEDS - 1]
    embeds.append(build_info_embed(message))

    try:
        copy = await webhook.send(
            content=message.content,
            username=safe_username(message.author.display_name),
            avatar_url=message.author.display_avatar.url,
            files=files,
            embeds=embeds,
            # Don't ping anyone a second time
            allowed_mentions=discord.AllowedMentions.none(),
            wait=True,
        )
    except discord.NotFound:
        # The webhook was deleted by hand: forget it, so the next attempt makes a new one
        _webhook = None
        raise LabError("The archive webhook had been deleted. Try again and I'll create a new one.")
    except discord.Forbidden:
        raise LabError(f"Discord wouldn't let me post in {channel.mention}.")

    # Only now that the copy exists is it safe to remove the original
    summary = (
        f"archived a message by {message.author.display_name} from #{message.channel.name} "
        f"({len(files)} file(s)): {copy.jump_url}"
    )
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        raise LabError(
            f"Archived to {copy.jump_url}, but I couldn't delete the original. "
            "I need Manage Messages in that channel."
        )
    return summary


# ---------------------------------------------------------------------------
# Way in 1: right-click a message > Apps > Archive message
# ---------------------------------------------------------------------------
async def archive_menu_callback(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)
    summary = await archive_message(message)
    note(interaction, summary)
    await interaction.followup.send(f"{ARCHIVE_EMOJI} Done: {summary}.", ephemeral=True)


archive_menu = app_commands.ContextMenu(name="Archive message", callback=archive_menu_callback)
archive_menu.add_check(lab_check)


# ---------------------------------------------------------------------------
# Way in 2: react to a message with 📦
# ---------------------------------------------------------------------------
async def on_archive_reaction(payload: discord.RawReactionActionEvent, user: User) -> str:
    channel = _client.get_channel(payload.channel_id)
    if channel is None:
        raise LabError("I can't see the channel that message is in.")
    message = await channel.fetch_message(payload.message_id)
    try:
        return await archive_message(message)
    except LabError as error:
        # A reaction has nowhere private to reply, so leave a note that tidies itself away
        try:
            await channel.send(f"⚠️ Couldn't archive that: {error}", delete_after=20)
        except discord.HTTPException:
            log.warning("Could not post the archive failure note")
        raise
