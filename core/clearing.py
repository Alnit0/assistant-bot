import logging
from dataclasses import dataclass
from datetime import datetime

import discord

from core import channels, discord_utils, lifecycle, outgoing, protection
from core.errors import UserError

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Emptying a channel, for tasks that may not call Discord themselves: read
# every message in it (which ones are pinned or marked 📌), and delete the
# ones asked for. What to delete, and in what way, is decided by the caller
# (tasks/channel/rules.py); this only does it.
#
# Discord deletes messages up to 14 days old a hundred at a time, and older
# ones only singly. The singles go one after another: discord.py waits out
# the rate limit itself, so this is slow rather than refused.
# ---------------------------------------------------------------------------
REASON = "Channel reset"
# What the bot's role needs in the channel, in the order it is needed, with Discord's name for each
NEEDED = (("read_message_history", "Read Message History"), ("manage_messages", "Manage Messages"))


@dataclass(frozen=True)
class Found:
    """One message in a channel."""

    id: int
    created_at: datetime
    protected: bool  # pinned, or marked 📌
    why: str = ""  # which of the two: "pinned", "marked 📌"
    # What it says, for a transcript taken before it is deleted
    author: str = ""
    content: str = ""
    attachments: tuple[str, ...] = ()  # links to its files; the files themselves are not fetched


@dataclass(frozen=True)
class Scan:
    """A channel as it stands: its messages, or the permissions missing to read and delete them."""

    channel_id: int
    mention: str  # how the channel is written in a message: <#id>
    messages: tuple[Found, ...] = ()  # newest first, as Discord gives them
    missing: tuple[str, ...] = ()
    name: str = ""  # the channel's name, as in a file name: "inbox"


def _said(message) -> str:
    """What a message says: its text, and for one that is only an embed (a log
    card) the embed's title and text."""
    parts = [message.content] if getattr(message, "content", "") else []
    for embed in getattr(message, "embeds", None) or []:
        parts += [f"[{part}]" for part in (getattr(embed, "title", None), getattr(embed, "description", None)) if part]
    return "\n".join(parts)


def _found(message) -> Found:
    why = protection.protection(message)
    author = getattr(message, "author", None)
    return Found(
        message.id,
        message.created_at,
        why is not None,
        why or "",
        getattr(author, "display_name", None) or getattr(author, "name", None) or "",
        _said(message),
        tuple(attachment.url for attachment in getattr(message, "attachments", None) or []),
    )


def _channel(channel_id: int):
    client = discord_utils.client
    return client.get_channel(channel_id) if client is not None and channel_id else None


async def scan(channel_id: int) -> Scan:
    """Every message in a channel. If the bot may not read or delete them there
    the scan says which permission is missing, and reads nothing. Raises
    UserError for a place that has no messages to clear (a forum, a DM)."""
    channel = _channel(channel_id)
    if not channels.holds_messages(channel):
        raise UserError("This isn't a channel whose messages I can clear.")
    me = getattr(getattr(channel, "guild", None), "me", None)
    if me is None:
        raise UserError("I can only reset a channel of the server.")
    allowed = channel.permissions_for(me)
    missing = tuple(label for name, label in NEEDED if not getattr(allowed, name, False))
    mention = getattr(channel, "mention", f"<#{channel_id}>")
    name = getattr(channel, "name", None) or str(channel_id)
    if missing:
        return Scan(channel_id, mention, missing=missing, name=name)
    found = [_found(message) async for message in channel.history(limit=None)]
    return Scan(channel_id, mention, tuple(found), name=name)


async def delete(channel_id: int, bulk: list[list[int]], single: list[int]) -> set[int]:
    """Delete messages: each list of `bulk` in one request (up to 100, all under
    14 days old), then `single` one at a time. Returns the ids that are gone
    from the channel now. A batch Discord won't take whole is done singly; a
    message that had already gone counts as gone; one that can't be deleted is
    left and logged."""
    channel = _channel(channel_id)
    if channel is None:
        raise UserError("I can't reach this channel just now.")
    gone: set[int] = set()
    single = list(single)
    for batch in bulk:
        try:
            await channel.delete_messages([discord.Object(id=message_id) for message_id in batch], reason=REASON)
            gone.update(batch)
        except discord.HTTPException as error:
            log.warning("Could not delete %s messages at once in channel %s (%s): one by one instead", len(batch), channel_id, error)
            single += batch
    for message_id in single:
        try:
            await channel.get_partial_message(message_id).delete()
            gone.add(message_id)
        except discord.NotFound:
            gone.add(message_id)
        except discord.HTTPException as error:
            log.warning("Could not delete message %s in channel %s: %s", message_id, channel_id, error)
    return gone


async def note(channel_id: int, text: str, seconds: float) -> None:
    """A short line in the channel that tidies itself away after `seconds`, as
    every Transient message does (it stays while confirmations are kept)."""
    channel = _channel(channel_id)
    if channel is not None:
        await channel.send(outgoing.clean(text) or text, delete_after=lifecycle.delete_after(seconds))
