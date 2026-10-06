import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from core.context import Context
from core.scheduler import Job
from core.users import User

# Values for `channels`: where a registration works
INBOX = "inbox"
ANY = "any"


def _as_list(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


# ---------------------------------------------------------------------------
# The three things a user can do to reach a skill. Each describes itself, so
# `help` and Claude's knowledge of what the bot can do are generated from
# these and never drift from the code. Always fill in `description`; a missing
# one is reported at startup.
# ---------------------------------------------------------------------------
@dataclass
class Keyword:
    """A word or phrase the user types on its own, e.g. "stats".

    `words` is the main word followed by any aliases. Small typos are
    forgiven unless `exact` is set (use that for anything destructive). The
    handler replies through the context; what it returns is recorded as the
    reply in message_log and #bot-log (None records what was sent).

    When the handler succeeds, the core deletes the user's command message
    (unless `keep_command` is set). An action with nothing lasting to show
    should call ctx.confirm("📦 Archived: ..."), which deletes itself after a
    few seconds; if the handler shows nothing at all, the core posts a plain
    "Done" confirmation. When it fails, the command message stays and gets a
    ⚠️ reaction, with the details in #bot-log.
    """

    words: list[str] | str
    description: str
    handler: Callable[[Context], Awaitable[str | None]]
    examples: list[str] | tuple = ()
    channels: list[str] | str = INBOX  # channel names from config.CHANNELS, or ANY
    permission: str = ""  # passed to is_allowed; defaults to "keyword:<word>"
    takes_args: bool = False  # accept extra words after the phrase, as ctx.args
    usage: str = ""  # the arguments, for help, e.g. "[days]"
    exact: bool = False  # never match by typo
    accepts: Callable[[list[str]], bool] | None = None  # say no to arguments that aren't ours
    keep_command: bool = False  # leave the user's message in place after it works

    def __post_init__(self):
        self.words = _as_list(self.words)
        self.examples = list(self.examples)
        self.permission = self.permission or f"keyword:{self.name}"

    @property
    def name(self) -> str:
        return self.words[0]

    @property
    def aliases(self) -> list[str]:
        return self.words[1:]


@dataclass
class ReplyAction:
    """A word the user sends as a reply to a message, to act on that message.

    The handler gets the context and the message that was replied to. It ends
    the same way a keyword does (see Keyword).
    """

    words: list[str] | str
    description: str
    handler: Callable[[Context, discord.Message], Awaitable[str | None]]
    examples: list[str] | tuple = ()
    channels: list[str] | str = ANY
    permission: str = ""  # defaults to "reply:<word>"
    takes_args: bool = False
    usage: str = ""
    exact: bool = False
    keep_command: bool = False  # leave the user's reply in place after it works
    # A regular expression for replies that aren't fixed words, e.g. r"\+\s*(.+)" for
    # "+10m". Its groups become ctx.args
    pattern: str | None = None
    # Say whether this reply is ours: `async (ctx) -> bool`, asked before anything is
    # logged or done. Use ctx.reply_target_id. If it says no, the message is treated
    # as if it weren't a reply action at all (so it can still reach Claude)
    applies_to: Callable[[Context], Awaitable[bool]] | None = None

    def __post_init__(self):
        self.words = _as_list(self.words)
        self.examples = list(self.examples)
        self.permission = self.permission or f"reply:{self.name}"

    @property
    def name(self) -> str:
        return self.words[0]

    @property
    def aliases(self) -> list[str]:
        return self.words[1:]


@dataclass
class Reaction:
    """An emoji the skill responds to when an allowed user adds it to a message.

    Reactions are acted on after a short quiet period (see
    REACTION_DEBOUNCE_SECONDS), so removing one in time cancels it. The handler
    gets Discord's reaction payload and the user who reacted.
    """

    emoji: str
    description: str
    handler: Callable[[discord.RawReactionActionEvent, User], Awaitable[str | None]]
    examples: list[str] | tuple = ()
    channels: list[str] | str = ANY
    permission: str = ""  # defaults to "reaction:<emoji>"

    def __post_init__(self):
        self.examples = list(self.examples)
        self.permission = self.permission or f"reaction:{self.emoji}"

    @property
    def name(self) -> str:
        return self.emoji


@dataclass(frozen=True)
class Tool:
    """A tool Claude can call. Not used yet: wired up in the tool-calling stage."""

    definition: dict
    handler: Callable[..., Awaitable[str]]


class Skill:
    """Base class for skills. Set name and description, override the hooks you need.

    `name` must match the skill's folder name in skills/.
    """

    name: str = ""
    description: str = ""

    def keywords(self) -> list[Keyword]:
        """Words and phrases the user can type."""
        return []

    def reply_actions(self) -> list[ReplyAction]:
        """Words that act on a message when sent as a reply to it."""
        return []

    def reactions(self) -> list[Reaction]:
        """Emoji this skill responds to."""
        return []

    def tools(self) -> list[Tool]:
        """Claude tool definitions and their handlers."""
        return []

    def job_handlers(self) -> dict[str, Callable[[Job], Awaitable[None]]]:
        """What to run when one of this skill's scheduled jobs comes due, by kind.

        Book a job with `await scheduler.add_job(self.name, kind, due_at, payload,
        user_id)` (core/scheduler.py). Jobs are stored, so they survive restarts;
        one that came due while the bot was off runs at the next start with
        `job.is_late` set.
        """
        return {}

    def migrations(self) -> list[Callable[[sqlite3.Connection], None]]:
        """This skill's database migrations, in order. Applied by the core at startup.

        Same rules as core/migrations.py: only ever add to the end. Prefix table
        names with the skill's name.
        """
        return []

    def app_commands(self) -> list:
        """Slash command groups and context menus, synced to our server at startup.

        A fallback: prefer keywords, reply actions and reactions.
        """
        return []

    def events(self) -> dict[str, Callable[..., Awaitable[None]]]:
        """Discord events this skill wants, by name without the "on_" prefix.

        Available: raw_reaction_add, raw_reaction_remove, guild_channel_pins_update,
        app_command_completion, app_command_error. The handler gets the same
        arguments as discord.py's event.

        Two are ours rather than Discord's: "action_finished", sent after every
        word, reply action, reaction and chat with a registry.ActionResult; and
        "pin_notice", sent with Discord's "X pinned a message" system message.
        """
        return {}

    def setup(self, client: discord.Client) -> None:
        """Runs once just before the bot connects. Register persistent views here
        (client.add_view), so buttons on old messages work from the first moment."""

    async def startup(self, client: discord.Client) -> None:
        """Runs once when the bot is connected and ready."""
