import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

import discord

from core.actions import Action, Entry, Request
from core.context import Context
from core.lifecycle import MessageClass
from core.scheduler import Job
from core.users import User

# Values for `channels`: where a registration works
INBOX = "inbox"
ANY = "any"


def _as_list(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


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

    def __post_init__(self):
        self.words = _as_list(self.words)
        self.examples = list(self.examples)
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
    """An emoji the task responds to when an allowed user adds it to a message.

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

    `instant=True` is the exception to the quiet period (🐞): the handler runs
    the moment the reaction is added, nothing is recorded as applied, no ✅ is
    added, and taking the reaction away does nothing. Only for an action that
    is safe to do at once and has its own way of being closed.
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
    instant: bool = False  # act at once, with no quiet period and no undo

    def __post_init__(self):
        self.examples = list(self.examples)
        self.permission = self.permission or f"reaction:{self.emoji}"

    @property
    def name(self) -> str:
        return self.emoji


class Task:
    """Base class for tasks. Set name and description, override the hooks you need.

    `name` must match the task's folder name in tasks/.
    """

    name: str = ""
    description: str = ""

    # --- for the router (core/routing.py). A task that takes plain words sets
    # these three and returns its actions; the registry refuses one that is
    # missing any of them
    icon: str = ""  # "💊"
    # What it is for and what it is not, in a sentence or two. The router reads
    # this, and nothing else about the task but the examples, to choose it
    only_for: str = ""
    examples: tuple[str, ...] = ()  # two or three things one might say to it
    hint: str = ""  # said when nothing fits: how to ask
    show: str = ""  # the action that shows what the task has; the task's name on its own runs it


    def keywords(self) -> list[Keyword]:
        """Words and phrases the user can type."""
        return []

    def reply_actions(self) -> list[ReplyAction]:
        """Words that act on a message when sent as a reply to it."""
        return []

    def reactions(self) -> list[Reaction]:
        """Emoji this task responds to."""
        return []


    def actions(self) -> list[Action]:
        """What this task can be asked to do in plain words (core/actions.py): for
        each, the fields Claude fills in and the code that does it and writes
        the answer. Setup changes need a card; logging and questions don't."""
        return []

    async def action_state(self, request: Request) -> str:
        """What extraction should know about this task's state right now: names
        and ids of what exists, in a few plain lines. Sent with the message to
        this task's extraction only. Empty if there is nothing to say."""
        return ""

    def entries(self) -> list[Entry]:
        """This task as the router knows it. One entry, built from the fields
        above, if it has actions; override only to offer more than one."""
        found = tuple(self.actions())
        if not found:
            return []
        return [Entry(self.name, self.icon, self.only_for, tuple(self.examples), found, self.hint, self.action_state, self.show)]

    def claim(self, ctx: Context) -> Callable[[Context], Awaitable[str | None]] | None:
        """Take a message that is no word, reply action or awaited answer, because
        of where it was sent: return `async (ctx) -> what to record`, or None if
        it isn't this task's. Asked before Claude, so a claimed message never
        costs an API call. The bugs task claims what is written in a bug's post."""
        return None


    def job_handlers(self) -> dict[str, Callable[[Job], Awaitable[None]]]:
        """What to run when one of this task's scheduled jobs comes due, by kind.

        Book a job with `await scheduler.add_job(self.name, kind, due_at, payload,
        user_id)` (core/scheduler.py). Jobs are stored, so they survive restarts;
        one that came due while the bot was off runs at the next start with
        `job.is_late` set.
        """
        return {}

    async def new_day(self, ended: date, started: date) -> None:
        """Runs when a day ends (core/day.py): `ended` is the day that was over
        when the rollover came due, `started` the day it is now. They are a day
        apart unless the bot was off over a boundary, so deal with any days in
        between. Only called if overridden; a failure is reported and the other
        tasks are still told."""

    def migrations(self) -> list[Callable[[sqlite3.Connection], None]]:
        """This task's database migrations, in order. Applied by the core at startup.

        Same rules as core/migrations.py: only ever add to the end. Prefix table
        names with the task's name.
        """
        return []

    def app_commands(self) -> list:
        """Slash command groups and context menus, synced to our server at startup.

        A fallback: prefer keywords, reply actions and reactions.
        """
        return []

    def events(self) -> dict[str, Callable[..., Awaitable[None]]]:
        """Discord events this task wants, by name without the "on_" prefix.

        Available: raw_reaction_add, raw_reaction_remove, guild_channel_pins_update,
        app_command_completion, app_command_error. The handler gets the same
        arguments as discord.py's event.

        One is ours rather than Discord's: "action_finished", sent after every
        word, reply action, reaction and chat with a registry.ActionResult.
        """
        return {}

    async def message_class(self, message_id: int) -> MessageClass | None:
        """What kind of message this is, if it is one of this task's own and not
        plain content: MessageClass.LIVE for a card edited in place, ALERT for a
        notification waiting to be acknowledged. None for anything else
        (core/lifecycle.py has the classes; `dev inspect` shows the answer)."""
        return None

    def setup(self, client: discord.Client) -> None:
        """Runs once just before the bot connects. Register persistent views here
        (client.add_view), so buttons on old messages work from the first moment."""

    async def startup(self, client: discord.Client) -> None:
        """Runs once when the bot is connected and ready."""
