from dataclasses import dataclass, field

import discord

from core import database
from core.config import now_nz
from core.discord_utils import COLOUR_INFO, log_error, log_simple
from core.users import User


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
        )

    async def reply(self, text: str, *, view: discord.ui.View | None = None):
        """Send text back to where the input came from. Returns the sent message."""
        self.replies.append(text)
        if view is None:
            return await self._channel.send(text)
        return await self._channel.send(text, view=view)

    async def reply_card(self, title: str, fields: list[tuple[str, str]]):
        """Send a card with a title and short name/value fields. Returns the sent message."""
        embed = discord.Embed(title=title, colour=COLOUR_INFO, timestamp=now_nz())
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        self.replies.append(f"card: {title}")
        return await self._channel.send(embed=embed)

    async def log(self, title: str, description: str | None = None) -> None:
        """Post an activity card to #bot-log."""
        await log_simple(title, description)

    async def log_error(self, title: str, details: str, user_text: str | None = None) -> None:
        """Post an error card to #bot-log."""
        await log_error(title, details, user_text)
