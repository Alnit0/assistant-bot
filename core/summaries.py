import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from core import actions
from core.actions import Summary
from core.discord_utils import log_error

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A summary from each task that has one (the task contract's `summary`,
# core/actions.py), gathered for whatever shows them: the briefing today, a
# weekly summary or a glance card later. Nothing here knows who is asking.
#
# A summary only reads: it changes nothing, posts nothing, books nothing and
# makes no request to Claude. One failing or taking too long does not stop
# the others: its section says it couldn't be read, and #bot-log has why.
#
# A task says when its summary may have changed (`changed`): after anything
# of its own is saved, and at the moments its own looks already run. Whoever
# shows summaries is told (`on_change`) and brings its message up to date.
# ---------------------------------------------------------------------------
MAX_LINES = 3
MAX_LINE = 160  # characters of one line; a longer one is cut
TIME_LIMIT = 2.0  # seconds a task gets to say its summary
UNREAD = "couldn't be read"


@dataclass(frozen=True)
class Section:
    """One task's part: its icon and name (from its entry, the same
    everywhere) and what it said, or that it couldn't be read."""

    task: str
    icon: str
    title: str
    summary: Summary | None = None
    problem: str = ""


def _cut(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[: MAX_LINE - 1].rstrip() + "…"


def trimmed(summary: Summary) -> Summary:
    """A summary kept short: at most three lines, each within the length; what
    is left out is counted, never dropped unsaid."""
    lines = [_cut(line) for line in summary.lines if line and line.strip()]
    if len(lines) > MAX_LINES:
        more = len(lines) - (MAX_LINES - 1)
        lines = [*lines[: MAX_LINES - 1], f"…and {more} more"]
    return replace(summary, glance=_cut(summary.glance), lines=tuple(lines), hint=_cut(summary.hint), before=_cut(summary.before))


@dataclass(frozen=True)
class Source:
    """A task that has a summary and nothing to route to (weather): what the
    gathering needs of an entry, and no more."""

    name: str
    icon: str
    title: str
    summary: Callable


_sources: list[Source] = []


def provide(name: str, icon: str, summary: Callable, title: str = "") -> None:
    """A task with nothing to route to hands its summary in (the registry does
    this for it). A task with actions does it through its entry instead."""
    _sources[:] = [each for each in _sources if each.name != name]
    _sources.append(Source(name, icon, title or name.capitalize(), summary))


def forget_sources() -> None:
    _sources.clear()


async def gather(user_id: int, day: date) -> list[Section]:
    """Every task's summary for this user and day: the catalogue's, in its
    order, then those of tasks with nothing to route to. A task with nothing
    to say is left out."""
    found: list[Section] = []
    for entry in (*actions.catalogue(), *_sources):
        if entry.summary is None:
            continue
        try:
            said = await asyncio.wait_for(entry.summary(user_id, day), TIME_LIMIT)
        except Exception as error:
            log.exception("The summary of %s could not be read", entry.name)
            await log_error(f"Summary could not be read: {entry.name}", repr(error))
            found.append(Section(entry.name, entry.icon, entry.title, problem=UNREAD))
            continue
        if said is not None:
            found.append(Section(entry.name, entry.icon, entry.title, trimmed(said)))
    return found


@dataclass(frozen=True)
class Tally:
    """What one task had done of what there was to do on a day, from its record."""

    task: str
    icon: str
    done: int
    total: int


async def tallies(user_id: int, day: date) -> list[Tally]:
    """Every task's tally for a day (the contract's `tally`), in the catalogue's
    order: for looking back over days. A task with nothing that day is left
    out, and so is one that fails or takes too long (it is logged): a number
    that could not be read is never made up."""
    found: list[Tally] = []
    for entry in actions.catalogue():
        if entry.tally is None:
            continue
        try:
            said = await asyncio.wait_for(entry.tally(user_id, day), TIME_LIMIT)
        except Exception:
            log.exception("The tally of %s for %s could not be read", entry.name, day)
            continue
        if said is not None and said[1] > 0:
            found.append(Tally(entry.name, entry.icon, int(said[0]), int(said[1])))
    return found


# `(task, user_id) -> None`: called, not awaited; it schedules its own work
Listener = Callable[[str, int], None]
_listeners: list[Listener] = []


def on_change(listener: Listener) -> None:
    """Be told when a task's summary may have changed. Registering the same
    function again changes nothing."""
    if listener not in _listeners:
        _listeners.append(listener)


def changed(task: str, user_id: int) -> None:
    """A task says its summary may have changed for this user. Never raises:
    the task's own work is done, and this is only telling."""
    for listener in list(_listeners):
        try:
            listener(task, user_id)
        except Exception:
            log.exception("Could not tell a listener that the summary of %s changed", task)
