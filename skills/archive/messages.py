import logging
import re
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands

from core import confirmations, interactions
from core.config import ARCHIVE_CHANNEL_ID, ASSISTANT_NAME, BOT_LOG_CHANNEL_ID
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import log_simple, report_interaction_error, safe_reply
from core.errors import UserError
from core.permissions import is_allowed
from core.protection import protection
from core.users import User, get_user_by_discord_id
from skills.archive import rules, store

log = logging.getLogger("assistant")

# This skill works with Discord messages directly (webhooks, deleting), like the
# lab. It moves behind the gateway layer when that exists.

ARCHIVE_EMOJI = "📦"
DELETE_EMOJI = "🗑️"
RESTORE_EMOJI = "↩️"
PERMISSION = "reply:archive"
WEBHOOK_NAME = f"{ASSISTANT_NAME} Archive"
MAX_EMBEDS = 10  # Discord's limit per message; one is used for the "archived from" note
ASKED = "asked for confirmation first (the message is protected)"

_client: discord.Client | None = None
_webhooks: dict[int, discord.Webhook] = {}  # ours, by channel


def bind(client: discord.Client) -> None:
    global _client
    _client = client


# ---------------------------------------------------------------------------
# Checks: the rules are in rules.py; these supply the settings
# ---------------------------------------------------------------------------
def check_archivable(message: discord.Message) -> None:
    """Raise UserError if this message shouldn't or can't be archived."""
    limit = message.guild.filesize_limit if message.guild else rules.DEFAULT_SIZE_LIMIT
    rules.check_archivable(message, ARCHIVE_CHANNEL_ID, BOT_LOG_CHANNEL_ID, limit)


def check_deletable(message: discord.Message) -> None:
    """Raise UserError if this message shouldn't be deleted on request."""
    rules.check_deletable(message, ARCHIVE_CHANNEL_ID, BOT_LOG_CHANNEL_ID)


# ---------------------------------------------------------------------------
# Archiving and deleting
# ---------------------------------------------------------------------------
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


async def _get_webhook(channel) -> discord.Webhook:
    """Our webhook in a channel: reuse it if it exists, create it once if not."""
    cached = _webhooks.get(channel.id)
    if cached is not None:
        return cached
    try:
        for webhook in await channel.webhooks():
            if webhook.user and webhook.user.id == _client.user.id and webhook.token:
                _webhooks[channel.id] = webhook
                return webhook
        _webhooks[channel.id] = await channel.create_webhook(name=WEBHOOK_NAME, reason="Archiving messages")
    except discord.Forbidden:
        raise UserError(f"I need the Manage Webhooks permission in {channel.mention}.")
    return _webhooks[channel.id]


async def _download(message: discord.Message) -> list[discord.File]:
    try:
        return [
            await attachment.to_file(spoiler=attachment.is_spoiler())
            for attachment in message.attachments
        ]
    except discord.HTTPException as error:
        raise UserError(f"I couldn't download an attachment ({error.status}), so nothing was moved.")


async def archive_message(message: discord.Message, user_id: int | None = None) -> tuple[str, str]:
    """Copy a message to the archive channel, then delete the original.

    Returns a one-line summary and a link to the archived copy. Raises
    UserError, leaving the original alone, if the copy can't be made in full.
    """
    check_archivable(message)
    channel = _client.get_channel(ARCHIVE_CHANNEL_ID)
    if channel is None or not hasattr(channel, "webhooks"):
        raise UserError("I can't find the archive channel. Check ARCHIVE_CHANNEL_ID.")
    webhook = await _get_webhook(channel)
    files = await _download(message)

    # Keep the original's own embeds (not link previews, which Discord rebuilds)
    embeds = rules.own_embeds(message.embeds, MAX_EMBEDS - 1)
    embeds.append(build_info_embed(message))
    copy_fields = dict(
        content=message.content,
        username=rules.safe_username(message.author.display_name),
        avatar_url=message.author.display_avatar.url,
        embeds=embeds,
        # Don't ping anyone a second time
        allowed_mentions=discord.AllowedMentions.none(),
        wait=True,
    )

    # The record comes first: the Restore button carries its id
    item_id = await store.add(
        user_id,
        message.channel.id,
        message.id,
        channel.id,
        message.author.display_name,
        message.author.display_avatar.url,
        message.created_at,
    )
    try:
        try:
            copy = await webhook.send(files=files, view=restore_view(item_id), **copy_fields)
        except discord.NotFound:
            # The webhook was deleted by hand: forget it, so the next attempt makes a new one
            _webhooks.pop(channel.id, None)
            raise UserError("The archive webhook had been deleted. Try again and I'll create a new one.")
        except discord.Forbidden:
            raise UserError(f"Discord wouldn't let me post in {channel.mention}.")
        except (discord.HTTPException, ValueError, TypeError) as error:
            # Buttons not accepted on this webhook: post the copy plain, button underneath
            log.info("Archive copy sent without a button (%s)", error)
            copy = await webhook.send(files=await _download(message), **copy_fields)
    except BaseException:
        await store.discard(item_id)
        raise

    button_message_id = None
    if not getattr(copy, "components", None):
        try:
            button = await channel.send(
                f"{RESTORE_EMOJI} Restore the message above", view=restore_view(item_id), silent=True
            )
            button_message_id = button.id
        except discord.HTTPException as error:
            log.warning("Could not add a Restore button under the archived copy: %s", error)
    await store.set_copy(item_id, copy.id, button_message_id)

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


async def delete_message(message: discord.Message) -> str:
    """Delete a message for good. Returns a one-line summary."""
    check_deletable(message)
    preview = rules.delete_preview(message.content)
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
# Protected messages (pinned, or marked 📌) are asked about first
# ---------------------------------------------------------------------------
Outcome = tuple[str, str]  # (summary for the log, short text for the user)


async def _archive(message: discord.Message, user: User) -> Outcome:
    summary, link = await archive_message(message, user.id)
    return summary, f"{ARCHIVE_EMOJI} Archived: {link}"


async def _delete(message: discord.Message, user: User) -> Outcome:
    return await delete_message(message), f"{DELETE_EMOJI} Deleted"


async def _run_or_ask(
    message: discord.Message, user: User, verb: str, perform: Callable[[discord.Message, User], Awaitable[Outcome]]
) -> Outcome | None:
    """Do it now, or, if the message is protected, ask first and return None."""
    reason = protection(message)
    if reason is None:
        return await perform(message, user)

    async def confirmed() -> str:
        return (await perform(message, user))[1]

    await confirmations.ask(message.channel, user, rules.confirm_question(reason, verb), confirmed)
    return None


# ---------------------------------------------------------------------------
# Way in 1: reply to a message with "archive" or "delete"
# ---------------------------------------------------------------------------
async def archive_reply(ctx: Context, target: discord.Message) -> str:
    check_archivable(target)
    outcome = await _run_or_ask(target, ctx.user, "Archive", _archive)
    if outcome is None:
        ctx.shown(ASKED)
        return ASKED
    await ctx.confirm(outcome[1])
    return outcome[0]


async def delete_reply(ctx: Context, target: discord.Message) -> str:
    check_deletable(target)
    outcome = await _run_or_ask(target, ctx.user, "Delete", _delete)
    if outcome is None:
        ctx.shown(ASKED)
        return ASKED
    await ctx.confirm(outcome[1])
    return outcome[0]


# ---------------------------------------------------------------------------
# Way in 2: react with 📦 or 🗑️ (acted on after the quiet period; remove the
# reaction in time to cancel). If either fails, the core marks the message ⚠️.
# ---------------------------------------------------------------------------
async def _reacted_message(payload: discord.RawReactionActionEvent) -> discord.Message:
    channel = _client.get_channel(payload.channel_id)
    if channel is None:
        raise UserError("I can't see the channel that message is in.")
    return await channel.fetch_message(payload.message_id)


async def on_archive_reaction(payload: discord.RawReactionActionEvent, user: User) -> str:
    message = await _reacted_message(payload)
    check_archivable(message)
    outcome = await _run_or_ask(message, user, "Archive", _archive)
    return ASKED if outcome is None else outcome[0]


async def on_delete_reaction(payload: discord.RawReactionActionEvent, user: User) -> str:
    message = await _reacted_message(payload)
    check_deletable(message)
    outcome = await _run_or_ask(message, user, "Delete", _delete)
    return ASKED if outcome is None else outcome[0]


# ---------------------------------------------------------------------------
# Way in 3 (fallback): right-click a message > Apps > Archive message
# ---------------------------------------------------------------------------
async def menu_check(interaction: discord.Interaction) -> bool:
    """Runs before the menu action: permission, then log the input."""
    if not await interactions.check_allowed(interaction, PERMISSION, "Archiving isn't for you."):
        return False
    await interactions.begin(interaction, kind="menu", label="Archive", emoji=ARCHIVE_EMOJI)
    return True


async def archive_menu_callback(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)
    check_archivable(message)
    user = await get_user_by_discord_id(interaction.user.id)
    outcome = await _run_or_ask(message, user, "Archive", _archive)
    if outcome is None:
        interactions.note(interaction, ASKED)
        await interaction.followup.send("That message is protected, so I've asked in the channel first.", ephemeral=True)
        return
    interactions.note(interaction, outcome[0])
    await interaction.followup.send(f"{ARCHIVE_EMOJI} Done: {outcome[0]}.", ephemeral=True)


archive_menu = app_commands.ContextMenu(name="Archive message", callback=archive_menu_callback)
archive_menu.add_check(menu_check)


# ---------------------------------------------------------------------------
# Restore: the button on each archived copy puts the message back where it was
# ---------------------------------------------------------------------------
async def restore(item_id: int) -> str:
    """Repost an archived message to its original channel, then remove the archived copy."""
    item = await store.get(item_id)
    if item is None:
        raise UserError("I have no record of where that came from, or it was already restored.")
    archive_channel = _client.get_channel(item.archive_channel_id)
    origin = _client.get_channel(item.original_channel_id)
    if origin is None:
        raise UserError("The channel it came from no longer exists, or I can't see it.")
    try:
        copy = await archive_channel.fetch_message(item.archive_message_id)
    except (discord.NotFound, AttributeError):
        raise UserError("The archived copy has gone, so there is nothing to restore.")

    posted = int(item.original_created_at.timestamp())
    note = discord.Embed(
        description=f"{RESTORE_EMOJI} Restored from the archive\nOriginally posted <t:{posted}:F> (<t:{posted}:R>)",
        colour=discord.Colour.dark_grey(),
        timestamp=item.original_created_at,
    )
    note.set_footer(text="Originally posted")
    embeds = rules.restored_embeds(copy.embeds, note)
    quiet = discord.AllowedMentions.none()

    try:
        webhook = await _get_webhook(origin)
        restored = await webhook.send(
            content=copy.content,
            username=rules.safe_username(item.author_name),
            avatar_url=item.author_avatar_url,
            files=await _download(copy),
            embeds=embeds,
            allowed_mentions=quiet,
            wait=True,
        )
    except (UserError, discord.Forbidden, discord.NotFound):
        # No webhook allowed there: post it ourselves, saying whose it was
        _webhooks.pop(origin.id, None)
        text = rules.fallback_text(item.author_name, copy.content)
        restored = await origin.send(text, files=await _download(copy), embeds=embeds, allowed_mentions=quiet)

    # Only now that it is back is it safe to remove the archived copy
    for message_id in (item.archive_message_id, item.button_message_id):
        if message_id is not None:
            try:
                await archive_channel.get_partial_message(message_id).delete()
            except discord.HTTPException as error:
                log.info("Could not remove archived message %s: %s", message_id, error)
    await store.mark_restored(item.id)
    return f"{RESTORE_EMOJI} Restored to {origin.mention}: {restored.jump_url}"


class RestoreButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"archive:restore:(?P<id>\d+)"
):
    """Its id carries the archive record's id, so it works after a restart."""

    def __init__(self, item_id: int):
        super().__init__(
            discord.ui.Button(
                label="Restore",
                emoji=RESTORE_EMOJI,
                style=discord.ButtonStyle.secondary,
                custom_id=f"archive:restore:{item_id}",
            )
        )
        self.item_id = item_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            user = await get_user_by_discord_id(interaction.user.id)
            if not is_allowed(user, PERMISSION):
                await safe_reply(interaction, "Restoring isn't for you.")
                return
            # Answer first: downloading and reposting can take a few seconds
            await interaction.response.defer(ephemeral=True)
            row_id = await log_received(
                f"restore archived item {self.item_id}", "archive",
                interaction.message.id if interaction.message else None,
                interaction.channel_id, user_id=user.id,
            )
            try:
                outcome = await restore(self.item_id)
            except UserError as error:
                await log_result(row_id, status="error", error=str(error))
                await safe_reply(interaction, f"⚠️ {error}")
                return
            await log_result(row_id, reply=outcome, status="ok")
            await log_simple(f"{RESTORE_EMOJI} Restored from the archive", outcome)
            await safe_reply(interaction, outcome)
        except Exception as error:
            await report_interaction_error(interaction, error, "Restore failed")


def restore_view(item_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(RestoreButton(item_id))
    return view
