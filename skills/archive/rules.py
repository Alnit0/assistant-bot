import re

from core.errors import UserError

# ---------------------------------------------------------------------------
# Archive and delete: the decisions, with no Discord calls. Messages are only
# read from (channel, content, attachments, embeds), so tests can pass in
# simple stand-ins.
# ---------------------------------------------------------------------------
DEFAULT_SIZE_LIMIT = 10 * 1024 * 1024  # Discord's upload limit outside a boosted server
DISCORD_LIMIT = 2000
PREVIEW_LENGTH = 80


def safe_username(name: str) -> str:
    """Webhook names can't contain "discord" or "clyde", and must be 1 to 80 characters."""
    name = re.sub(r"discord", "d*scord", name, flags=re.IGNORECASE)
    name = re.sub(r"clyde", "cl*de", name, flags=re.IGNORECASE)
    return name.strip()[:80] or "Unknown"


def check_archivable(
    message,
    archive_channel_id: int | None,
    bot_log_channel_id: int | None,
    size_limit: int = DEFAULT_SIZE_LIMIT,
) -> None:
    """Raise UserError if this message shouldn't or can't be archived."""
    if archive_channel_id is None:
        raise UserError("ARCHIVE_CHANNEL_ID isn't set in .env, so there's nowhere to archive to.")
    if message.channel.id == archive_channel_id:
        raise UserError("That message is already in the archive.")
    if bot_log_channel_id is not None and message.channel.id == bot_log_channel_id:
        raise UserError("Messages in #bot-log stay where they are.")
    if not (message.content or message.attachments or message.embeds):
        raise UserError("There's nothing in that message I can copy (no text, files or embeds).")

    for attachment in message.attachments:
        if attachment.size > size_limit:
            raise UserError(
                f"`{attachment.filename}` is too big for me to re-upload "
                f"({attachment.size / 1_048_576:.1f} MB), so I've left the message where it is."
            )


def check_deletable(message, archive_channel_id: int | None, bot_log_channel_id: int | None) -> None:
    """Raise UserError if this message shouldn't be deleted on request."""
    if archive_channel_id is not None and message.channel.id == archive_channel_id:
        raise UserError("Messages in the archive stay there. Delete it by hand if you're sure.")
    if bot_log_channel_id is not None and message.channel.id == bot_log_channel_id:
        raise UserError("Messages in #bot-log stay where they are.")


def own_embeds(embeds: list, limit: int) -> list:
    """The embeds worth copying: the message's own (not link previews, which Discord rebuilds)."""
    return [embed for embed in embeds if embed.type == "rich"][:limit]


def restored_embeds(copy_embeds: list, note) -> list:
    """The embeds for a restored message: the copy's last one is our "archived from"
    note, which is swapped for the "restored" one."""
    return [embed for embed in copy_embeds if embed.type == "rich"][:-1] + [note]


def fallback_text(author_name: str, content: str | None) -> str:
    """What the bot posts itself when it can't restore through a webhook."""
    return f"**{author_name}** wrote:\n{content or ''}"[:DISCORD_LIMIT]


def delete_preview(content: str | None) -> str:
    """The start of a deleted message, on one line, for the log."""
    return (content or "(no text)").replace("\n", " ")[:PREVIEW_LENGTH]


def confirm_question(reason: str, verb: str) -> str:
    """What to ask before acting on a protected message ("pinned", "marked 📌")."""
    return f"⚠️ That message is {reason}. {verb} it anyway?"
