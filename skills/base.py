import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import discord

from core.context import Context
from core.lifecycle import MessageClass
from core.scheduler import Job
from core.users import User

# Values for `channels`: where a registration works
INBOX = "inbox"
ANY = "any"


def _as_list(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


@dataclass(frozen=True)
class Param:
    """One argument of a word or reply action, as Claude is told about it.

    Claude can run registered actions as tools (core/tools.py), and a tool
    needs to know its arguments: list them in the order they are typed. Each is
    a string; one that may be left out is `required=False`. The values are
    turned back into the words after the command, so the handler reads
    `ctx.args` exactly as it does for a typed word.
    """

    name: str  # snake_case, e.g. "duration"
    description: str  # what to put here, with an example
    choices: tuple[str, ...] | list[str] = ()  # the only values allowed, if it is a fixed set
    required: bool = True


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
    # For Claude, which can run this as a tool. A word that takes arguments must
    # list them (the registry reports one that doesn't)
    params: list[Param] | tuple = ()
    tool: bool = True  # False keeps this word from Claude; typing it still works
    tool_priority: int = 0  # higher is likelier to be used, and gets a strict schema first
    # Offered to Claude even while the skill is holding its tools back
    # (Skill.tools_available): the dev mode switch, when dev mode is off
    tool_always: bool = False

    def __post_init__(self):
        self.words = _as_list(self.words)
        self.examples = list(self.examples)
        self.params = list(self.params)
        self.permission = self.permission or f"keyword:{self.name}"

    @property
    def destructive(self) -> bool:
        """Destructive words are the exact ones. Claude may only run one after the
        user presses Confirm."""
        return self.exact

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
    # Refuse a message this can't be done to: `(message) -> None`, raising UserError
    # with the reason. Asked before the handler; the user's reply gets ⚠️ and the
    # reason is shown briefly. Must be quick and change nothing
    validate: Callable[[discord.Message], None] | None = None
    # For Claude (see Keyword): its arguments, whether it is offered, and how likely
    params: list[Param] | tuple = ()
    tool: bool = True
    tool_priority: int = 0
    # How to take it back: `async (ctx, message) -> str` (what to show). Set it when
    # the action can be reversed; Claude's confirmation then carries an Undo button
    undo: Callable[[Context, discord.Message], Awaitable[str]] | None = None

    def __post_init__(self):
        self.words = _as_list(self.words)
        self.examples = list(self.examples)
        self.params = list(self.params)
        self.permission = self.permission or f"reply:{self.name}"

    @property
    def destructive(self) -> bool:
        return self.exact

    @property
    def name(self) -> str:
        return self.words[0]

    @property
    def aliases(self) -> list[str]:
        return self.words[1:]


@dataclass
class Reaction:
    """An emoji the skill responds to when an allowed user adds it to a message.

    Reactions are acted on after a quiet period (REACTION_DEBOUNCE in .env), on
    where the user's reactions ended up: adding one and removing it in time
    does nothing. The handler gets Discord's reaction payload and the user.

    Once applied, the message gets ✅, and taking the reaction away later runs
    `undo` and removes the ✅. Set `destructive=True` for an action after which
    the message no longer exists (archive, delete): there is nothing left to
    mark or undo, so it can only be cancelled within the quiet period.

    If the handler fails, the message gets ⚠️ and the details go to #bot-log.
    Don't post notes in the channel about it.

    `validate` is asked the moment the reaction is added, before the quiet
    period: if it raises UserError the message gets ⚠️ and the reason is shown
    briefly, and nothing is waited for. Only valid reactions are debounced.
    """

    emoji: str
    description: str
    handler: Callable[[discord.RawReactionActionEvent, User], Awaitable[str | None]]
    examples: list[str] | tuple = ()
    channels: list[str] | str = ANY
    permission: str = ""  # defaults to "reaction:<emoji>"
    undo: Callable[[discord.RawReactionActionEvent, User], Awaitable[str | None]] | None = None
    destructive: bool = False
    # `(message) -> None`, raising UserError if this can't be done to that message.
    # Must be quick and change nothing
    validate: Callable[[discord.Message], None] | None = None

    def __post_init__(self):
        self.examples = list(self.examples)
        self.permission = self.permission or f"reaction:{self.emoji}"

    @property
    def name(self) -> str:
        return self.emoji


@dataclass
class Tool:
    """A tool for Claude that is not a word the user types: reading live state
    (which timers are running), or acting on a record by its id.

    Most tools are generated from a Keyword or ReplyAction; use this only for
    what has no typed form. The handler gets the context and the input as
    {param name: text} and returns the result for Claude, which does the
    talking: the handler posts nothing in the channel. Raise UserError for a
    problem Claude should explain. It runs through `registry.run_tool`, so it
    is logged and permission-checked like every other tool call.
    """

    name: str  # as Claude sees it: snake_case, unique
    description: str  # written for Claude: what it does, when to use it, examples
    handler: Callable[[Context, dict], Awaitable[str]]
    params: list[Param] | tuple = ()
    channels: list[str] | str = ANY
    permission: str = ""  # defaults to "tool:<name>"
    reads_only: bool = False  # only reports; never counts as having done something
    tool_priority: int = 0

    # What the tool machinery asks of every action; a bespoke tool is none of these
    destructive = False
    undo = None

    def __post_init__(self):
        self.params = list(self.params)
        self.permission = self.permission or f"tool:{self.name}"


class Skill:
    """Base class for skills. Set name and description, override the hooks you need.

    `name` must match the skill's folder name in skills/.
    """

    name: str = ""
    description: str = ""
    # False for a skill whose words are never offered to Claude as tools (the lab)
    exposes_tools: bool = True

    def tools_available(self, channel_name: str | None) -> bool:
        """Whether this skill's words are offered to Claude right now, in this
        channel (our name for it, or None). Channel and permission are checked
        separately; override this for anything else, as dev does."""
        return self.exposes_tools

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
        """Tools for Claude that aren't words: reading state, acting by id (see Tool)."""
        return []

    async def live_state(self, ctx) -> str:
        """What Claude should know about this skill's state right now, in a few
        plain lines with the ids its tools take. Sent with every chat message
        (never kept in the history), so a simple request needs one round trip
        instead of a read first. Empty if there is nothing to say."""
        return ""

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

        One is ours rather than Discord's: "action_finished", sent after every
        word, reply action, reaction and chat with a registry.ActionResult.
        """
        return {}

    async def message_class(self, message_id: int) -> MessageClass | None:
        """What kind of message this is, if it is one of this skill's own and not
        plain content: MessageClass.LIVE for a card edited in place, ALERT for a
        notification waiting to be acknowledged. None for anything else
        (core/lifecycle.py has the classes; `dev inspect` shows the answer)."""
        return None

    def setup(self, client: discord.Client) -> None:
        """Runs once just before the bot connects. Register persistent views here
        (client.add_view), so buttons on old messages work from the first moment."""

    async def startup(self, client: discord.Client) -> None:
        """Runs once when the bot is connected and ready."""
