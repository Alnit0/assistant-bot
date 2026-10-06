import logging
import re

import discord
from discord import app_commands

from core import interactions
from core.config import ARCHIVE_CHANNEL_ID, BOT_LOG_CHANNEL_ID
from core.context import Context
from core.errors import UserError
from core.users import User

# This skill works with Discord messages directly (webhooks, deleting), like the
# lab. It moves behind the gateway layer when that exists.

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
    """Raise UserError if this message shouldn't or can't be archived."""
    if ARCHIVE_CHANNEL_ID is None:
        raise UserError("ARCHIVE_CHANNEL_ID isn't set in .env, so there's nowhere to archive to.")
    if message.channel.id == ARCHIVE_CHANNEL_ID:
        raise UserError("That message is already in the archive.")
    if BOT_LOG_CHANNEL_ID is not None and message.channel.id == BOT_LOG_CHANNEL_ID:
        raise UserError("Messages in #bot-log stay where they are.")
    if not (message.content or message.attachments or message.embeds):
        raise UserError("There's nothing in that message I can copy (no text, files or embeds).")

    limit = message.guild.filesize_limit if message.guild else 10 * 1024 * 1024
    for attachment in message.attachments:
        if attachment.size > limit:
            raise UserError(
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
        raise UserError(f"I need the Manage Webhooks permission in {channel.mention} to archive.")
    return _webhook


async def archive_message(message: discord.Message) -> tuple[str, str]:
    """Copy a message to the archive channel, then delete the original.

    Returns a one-line summary and a link to the archived copy. Raises
    UserError, leaving the original alone, if the copy can't be made in full.
    """
    global _webhook
    check_archivable(message)
    channel = _client.get_channel(ARCHIVE_CHANNEL_ID)
    if channel is None or not hasattr(channel, "webhooks"):
        raise UserError("I can't find the archive channel. Check ARCHIVE_CHANNEL_ID.")
    webhook = await _get_webhook(channel)

    try:
        files = [
            await attachment.to_file(spoiler=attachment.is_spoiler())
            for attachment in message.attachments
        ]
    except discord.HTTPException as error:
        raise UserError(f"I couldn't download an attachment ({error.status}), so nothing was archived.")

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
        raise UserError("The archive webhook had been deleted. Try again and I'll create a new one.")
    except discord.Forbidden:
        raise UserError(f"Discord wouldn't let me post in {channel.mention}.")

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
        raise UserError(
            f"Archived to {copy.jump_url}, but I couldn't delete the original. "
            "I need Manage Messages in that channel."
        )
    return summary, copy.jump_url


def check_deletable(message: discord.Message) -> None:
    """Raise UserError if this message shouldn't be deleted on request."""
    if ARCHIVE_CHANNEL_ID is not None and message.channel.id == ARCHIVE_CHANNEL_ID:
        raise UserError("Messages in the archive stay there. Delete it by hand if you're sure.")
    if BOT_LOG_CHANNEL_ID is not None and message.channel.id == BOT_LOG_CHANNEL_ID:
        raise UserError("Messages in #bot-log stay where they are.")


async def delete_message(message: discord.Message) -> str:
    """Delete a message for good. Returns a one-line summary."""
    check_deletable(message)
    preview = (message.content or "(no text)").replace("\n", " ")[:80]
    summary = (
        f"deleted a message by {message.author.display_name} from #{message.channel.name} "
        f"({len(message.attachments)} file(s)): {preview}"
    )
    try:
        await message.delete()
    except discord.NotFound:
        raise UserError("That message has already gone.")
    except discord.Forbidden:
        raise UserError("I couldn't delete it. I need Manage Messages in that channel.")
    return summary


# ---------------------------------------------------------------------------
# Way in 1: reply to a message with "archive" or "delete"
# ---------------------------------------------------------------------------
async def archive_reply(ctx: Context, target: discord.Message) -> str:
    summary, link = await archive_message(target)
    await ctx.confirm(f"{ARCHIVE_EMOJI} Archived: {link}")
    return summary


async def delete_reply(ctx: Context, target: discord.Message) -> str:
    summary = await delete_message(target)
    await ctx.confirm("🗑️ Deleted")
    return summary


# ---------------------------------------------------------------------------
# Way in 2: react to a message with 📦 (acted on after the quiet period)
# ---------------------------------------------------------------------------
async def on_archive_reaction(payload: discord.RawReactionActionEvent, user: User) -> str:
    channel = _client.get_channel(payload.channel_id)
    if channel is None:
        raise UserError("I can't see the channel that message is in.")
    message = await channel.fetch_message(payload.message_id)
    try:
        summary, _ = await archive_message(message)
        return summary
    except UserError as error:
        # A reaction has nowhere private to reply, so leave a note that tidies itself away
        try:
            await channel.send(f"⚠️ Couldn't archive that: {error}", delete_after=20)
        except discord.HTTPException:
            log.warning("Could not post the archive failure note")
        raise


# ---------------------------------------------------------------------------
# Way in 3 (fallback): right-click a message > Apps > Archive message
# ---------------------------------------------------------------------------
async def menu_check(interaction: discord.Interaction) -> bool:
    """Runs before the menu action: permission, then log the input."""
    if not await interactions.check_allowed(
        interaction, "reply:archive", "Archiving isn't for you."
    ):
        return False
    await interactions.begin(interaction, kind="menu", label="Archive", emoji=ARCHIVE_EMOJI)
    return True


async def archive_menu_callback(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)
    summary, _ = await archive_message(message)
    interactions.note(interaction, summary)
    await interaction.followup.send(f"{ARCHIVE_EMOJI} Done: {summary}.", ephemeral=True)


archive_menu = app_commands.ContextMenu(name="Archive message", callback=archive_menu_callback)
archive_menu.add_check(menu_check)
