import logging
from dataclasses import dataclass, field

import discord

from core import database, lifecycle
from core.config import CHANNELS, now_nz
from core.discord_utils import COLOUR_INFO, log_error, log_simple, split_message
from core.lifecycle import MessageClass
from core.users import User

log = logging.getLogger("assistant")


@dataclass
class Context:
    """Everything a skill needs to handle one input, without touching discord.Message.

    Groundwork for the gateway layer: skills talk to this, and only this file
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
        return None

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

    async def reply(self, text: str, *, view: discord.ui.View | None = None):
        """Send text back to where the input came from. Returns the (last) sent message.

        Text too long for one message is split at line breaks.
        """
        self.replies.append(text)
        chunks = split_message(text) or [text]
        for chunk in chunks[:-1]:
            await self._channel.send(chunk)
        if view is None:
            return await self._channel.send(chunks[-1])
        return await self._channel.send(chunks[-1], view=view)

    async def reply_card(self, title: str, fields: list[tuple[str, str]]):
        """Send a card with a title and short name/value fields. Returns the sent message."""
        embed = discord.Embed(title=title, colour=COLOUR_INFO, timestamp=now_nz())
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        self.replies.append(f"card: {title}")
        return await self._channel.send(embed=embed)

    async def confirm(self, text: str) -> None:
        """Say briefly that something was done, e.g. "📦 Archived: <link>".

        For actions with nothing lasting to show (a Transient message): it deletes
        itself after CONFIRMATION_SECONDS, so the channel stays tidy. Anything
        the user will want to read again is Kept: use reply().
        """
        self.replies.append(text)
        await self._send_transient(text)

    async def _send_transient(self, text: str) -> None:
        """Send a note that deletes itself (unless clean-up is switched off)."""
        message = await self._channel.send(text, delete_after=lifecycle.delete_after())
        lifecycle.note_transient(getattr(message, "id", None))

    def shown(self, text: str) -> None:
        """Record that the user has been shown something by other means (a question
        with buttons, say), so no "Done" confirmation is added on top of it."""
        self.replies.append(text)

    async def note(self, text: str) -> None:
        """Send a small aside that isn't part of the reply (not recorded in the log).

        It deletes itself like a confirmation.
        """
        await self._send_transient(text)

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
    # For the few skills allowed to use discord.py directly (lab, archive).
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
