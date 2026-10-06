import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from core.context import Context
from core.scheduler import DailyJob
from core.users import User


@dataclass(frozen=True)
class Command:
    """A text command. The whole message must equal `name` (case doesn't matter).

    The handler replies through the context. Whatever it returns is recorded as
    the reply in message_log and #bot-log; return None to record what was sent.
    """

    name: str
    description: str  # shown by `help`, e.g. "check the bot is alive"
    handler: Callable[[Context], Awaitable[str | None]]


@dataclass(frozen=True)
class Tool:
    """A tool Claude can call. Not used yet: wired up in the tool-calling stage."""

    definition: dict
    handler: Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class Reaction:
    """An emoji the skill responds to when an allowed user adds it to a message.

    The handler gets Discord's reaction payload and the user who reacted. As
    with commands, what it returns is recorded as the reply in message_log and
    #bot-log.
    """

    emoji: str
    handler: Callable[[discord.RawReactionActionEvent, User], Awaitable[str | None]]


class Skill:
    """Base class for skills. Set name and description, override the hooks you need.

    `name` must match the skill's folder name in skills/.
    """

    name: str = ""
    description: str = ""

    def commands(self) -> list[Command]:
        """Text commands this skill handles."""
        return []

    def tools(self) -> list[Tool]:
        """Claude tool definitions and their handlers."""
        return []

    def jobs(self) -> list[DailyJob]:
        """Scheduled jobs, registered with the core scheduler at startup."""
        return []

    def migrations(self) -> list[Callable[[sqlite3.Connection], None]]:
        """This skill's database migrations, in order. Applied by the core at startup.

        Same rules as core/migrations.py: only ever add to the end. Prefix table
        names with the skill's name.
        """
        return []

    def reactions(self) -> list[Reaction]:
        """Emoji this skill responds to."""
        return []

    def app_commands(self) -> list:
        """Slash command groups and context menus, synced to our server at startup."""
        return []

    def events(self) -> dict[str, Callable[..., Awaitable[None]]]:
        """Discord events this skill wants, by name without the "on_" prefix.

        Available: raw_reaction_add, raw_reaction_remove, guild_channel_pins_update,
        app_command_completion, app_command_error. The handler gets the same
        arguments as discord.py's event.
        """
        return {}

    def setup(self, client: discord.Client) -> None:
        """Runs once just before the bot connects. Register persistent views here
        (client.add_view), so buttons on old messages work from the first moment."""

    async def startup(self, client: discord.Client) -> None:
        """Runs once when the bot is connected and ready."""
