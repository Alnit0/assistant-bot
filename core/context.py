import logging
from dataclasses import dataclass, field

import discord

from core import database, dms, lifecycle, messages, outgoing, tidy
from core.actions import Attachment
from core.config import CHANNELS, real_now_nz
from core.discord_utils import COLOUR_INFO, log_error, log_simple, split_message
from core.lifecycle import MessageClass
from core.users import User

log = logging.getLogger("assistant")


@dataclass
class Context:
    """Everything a task needs to handle one input, without touching discord.Message.

    Groundwork for the gateway layer: tasks talk to this, and only this file
    and main.py know the input came from Discord.
    """

    user: User
    channel_id: int
    message_id: int | None
    text: str  # the raw input, exactly as received
    _channel: discord.abc.Messageable = field(repr=False)
    replies: list[str] = field(default_factory=list)  # what has been sent so far
    args: list[str] = field(default_factory=list)  # words after the keyword, if it takes any
    _message: discord.Message | None = field(default=None, repr=False)
    posted: int = 0  # how many messages this has put in the channel (asides don't count)
    # Set by the registry for a housekeeping word (delete, archive, pin, unpin, channel
    # reset): everything said about it tidies itself away, kept confirmations or not
    housekeeping: bool = False

    # Database access: the async helpers in core/database.py, including run()
    db = database

    @classmethod
    def from_message(cls, message: discord.Message, user: User) -> "Context":
        return cls(
            user=user,
            channel_id=message.channel.id,
            message_id=message.id,
            text=message.content,
            _channel=message.channel,
            _message=message,
        )

    @property
    def channel_name(self) -> str | None:
        """Our name for this channel ("inbox", "gym", ...), or None if it isn't one we know."""
        for name, channel_id in CHANNELS.items():
            if channel_id == self.channel_id:
                return name
        # A direct message of mine is read as #inbox (core/dms.py)
        return "inbox" if dms.is_dm(self.channel_id) else None

    @property
    def parent_channel_id(self) -> int | None:
        """The channel this one hangs off, if it is a thread or a forum post."""
        return getattr(self._channel, "parent_id", None)

    @property
    def attachments(self) -> tuple[Attachment, ...]:
        """The files sent with the input, as plain records: nothing is
        downloaded until a task asks for one's bytes."""
        files = getattr(self._message, "attachments", None) or []
        return tuple(
            Attachment(str(each.filename), int(getattr(each, "size", 0) or 0), str(getattr(each, "content_type", "") or ""), each.read)
            for each in files
        )

    @property
    def is_reply(self) -> bool:
        """True if the input was sent as a reply to another message."""
        return self._message is not None and self._message.reference is not None

    @property
    def reply_target_id(self) -> int | None:
        """The id of the message this input replied to, if it was a reply."""
        if not self.is_reply:
            return None
        return self._message.reference.message_id

    async def reply(self, text: str, *, view: discord.ui.View | None = None, verbatim: bool = False):
        """Send text back to where the input came from. Returns the (last) sent message.

        Text too long for one message is split at line breaks. `verbatim` is
        for a dev tool that shows the bot's workings (`dev why`): the names
        of actions belong in a trace, so nothing is taken out of it.
        """
        text = text if verbatim else outgoing.clean(text)
        if not text:
            log.error("A reply with nothing left to say was not sent")
            return None
        # In a direct message: sent silently, and never with one of my things named in its first line
        quiet = {"silent": True} if dms.is_dm(self.channel_id) else {}
        text = dms.guard(self.channel_id, text)
        self.replies.append(text)
        self.posted += 1
        if isinstance(view, discord.ui.LayoutView):
            # A Components V2 card: all it says is in its components, and it takes no text beside them
            sent = await self._channel.send(view=view, **quiet)
            await messages.record(getattr(sent, "id", None), self.channel_id)
            return sent
        chunks = split_message(text) or [text]
        sent = None
        for at, chunk in enumerate(chunks):
            last = at == len(chunks) - 1
            sent = await self._channel.send(chunk, view=view, **quiet) if last and view is not None else await self._channel.send(chunk, **quiet)
            # With the tidy on, a message in the hub has a lifetime (core/messages.py)
            await messages.record(getattr(sent, "id", None), self.channel_id)
        return sent

    async def reply_card(self, title: str, fields: list[tuple[str, str]]):
        """Send a card with a title and short name/value fields. Returns the sent message."""
        embed = discord.Embed(title=title, colour=COLOUR_INFO, timestamp=real_now_nz())
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        self.replies.append(f"card: {title}")
        self.posted += 1
        return await self._channel.send(embed=embed)

    async def confirm(self, text: str):
        """Say briefly that something was done, e.g. "📦 Archived: <link>".

        For actions with nothing lasting to show (a Transient message): it deletes
        itself after CONFIRMATION_SECONDS, so the channel stays tidy. Anything
        the user will want to read again is Kept: use reply(). Returns the sent
        message (None if nothing was left to say).
        """
        self.replies.append(text)
        self.posted += 1
        return await self._send_transient(text)

    async def _send_transient(self, text: str, seconds: float | None = None):
        text = outgoing.clean(text)
        if not text:
            return None
        """Send a note that deletes itself (unless clean-up is switched off)."""
        quiet = {"silent": True} if dms.is_dm(self.channel_id) else {}
        text = dms.guard(self.channel_id, text)
        if self.housekeeping:
            # No trace in the channel: #bot-log is the record. Deleted by a stored job
            # (core/tidy.py), so it goes even if the bot is restarted meanwhile
            message = await self._channel.send(text, **quiet)
            await tidy.later(self.channel_id, getattr(message, "id", None), lifecycle.tidy_after() if seconds is None else lifecycle.tidy_after(seconds))
        else:
            lifetime = lifecycle.delete_after() if seconds is None else lifecycle.delete_after(seconds)
            message = await self._channel.send(text, delete_after=lifetime, **quiet)
        lifecycle.note_transient(getattr(message, "id", None))
        await messages.record(getattr(message, "id", None), self.channel_id)
        return message

    def shown(self, text: str) -> None:
        """Record that the user has been shown something by other means (a question
        with buttons, say), so no "Done" confirmation is added on top of it."""
        self.replies.append(text)

    async def note(self, text: str, seconds: float | None = None) -> None:
        """Send a small aside that isn't part of the reply (not recorded in the log).

        It deletes itself like a confirmation, or after `seconds` if it needs
        longer to be read.
        """
        await self._send_transient(text, seconds)

    async def mark_failed(self) -> None:
        """Flag the user's message with ⚠️ to show it didn't work. Best effort."""
        if self._message is None:
            return
        try:
            await self._message.add_reaction("⚠️")
        except discord.HTTPException as error:
            log.info("Could not add the failure reaction: %s", error)

    async def log(self, title: str, description: str | None = None) -> None:
        """Post an activity card to #bot-log."""
        await log_simple(title, description)

    async def log_error(self, title: str, details: str, user_text: str | None = None) -> None:
        """Post an error card to #bot-log."""
        await log_error(title, details, user_text)

    # --- Discord-specific escape hatches -------------------------------------
    # For the few tasks allowed to use discord.py directly (lab, archive).
    # Everything here goes away when the gateway layer exists.

    @property
    def channel(self) -> discord.abc.Messageable:
        return self._channel

    @property
    def author(self) -> discord.abc.User | None:
        return self._message.author if self._message is not None else None

    async def fetch_reply_target(self) -> discord.Message | None:
        """The message this input replied to, or None if it can't be found."""
        if not self.is_reply:
            return None
        reference = self._message.reference
        if isinstance(reference.resolved, discord.Message):
            return reference.resolved
        if reference.message_id is None:
            return None
        try:
            return await self._channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None

    async def fetch_message(self, message_id: int) -> discord.Message | None:
        """One message in this channel by its id, or None if it has gone or can't be read."""
        fetch = getattr(self._channel, "fetch_message", None)
        if fetch is None:
            return None
        try:
            return await fetch(message_id)
        except discord.HTTPException:
            return None

    async def recent_messages(self, limit: int) -> list[discord.Message]:
        """The latest messages in this channel before the user's own, newest first.
        Empty if the history can't be read."""
        history = getattr(self._channel, "history", None)
        if history is None:
            return []
        try:
            before = self._message if self._message is not None else None
            return [message async for message in history(limit=limit, before=before)]
        except discord.HTTPException as error:
            log.info("Could not read the channel's recent messages: %s", error)
            return []

    async def delete_command(self) -> bool:
        """Remove the user's own message (the command word). Best effort; True if it went."""
        if self._message is None or not lifecycle.deletes(MessageClass.CONSUMED):
            return False
        try:
            await self._message.delete()
        except discord.HTTPException as error:
            log.info("Could not remove the command message: %s", error)
            return False
        return True

    async def acknowledge(self, emoji: str = "✅") -> None:
        """React to the user's message, to show it was received. Best effort."""
        if self._message is None:
            return
        try:
            await self._message.add_reaction(emoji)
        except discord.HTTPException as error:
            log.info("Could not add a reaction: %s", error)
