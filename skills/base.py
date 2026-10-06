import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core.context import Context
from core.scheduler import DailyJob


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
    """An emoji reaction the skill responds to. Not used yet."""

    emoji: str
    handler: Callable[..., Awaitable[None]]


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
