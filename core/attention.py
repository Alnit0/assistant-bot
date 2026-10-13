import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime

from core import actions
from core import day as days
from core.config import TIMEZONE

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The attention model: what deserves to be looked at first.
#
# Tasks, and the core's own parts, hand over attention items: what, when,
# how urgent, whether I can act on it, and a link or a bug's id if there is
# one. The core ranks them once (`ranked`), and every surface shows a slice
# of that one ranking: the status line its top item, the briefing today's
# items, a ping the urgent ones. No surface ranks anything by itself.
#
# The pecking order:
#   1  something wrong that needs me (a problem)      ⚠️ B14 · backup failed
#   2  due now or overdue (a timed item whose time has come)   💊 due 12pm
#   3  the next timed thing today                              💊 2/5 · 12pm
#   4  something useful that isn't timed, if a task offers one 🌅 6am
#   5  nothing: a blank status line
# Within a level, soonest first. A timed item for another day is not ranked.
#
# A task says an item's urgency and its time; it never says a rank and never
# looks at another task's items. Gathering only reads, and asks Claude
# nothing. Whoever knows an item may have changed says so (`changed`), and
# the surfaces look again: nothing here runs on a timer.
#
# Built on it so far: the status line (core/identity.py). The briefing and
# pings move onto it later (docs/BACKLOG.md).
# ---------------------------------------------------------------------------
PROBLEM, TIMED, USEFUL = "problem", "timed", "useful"
URGENCIES = (PROBLEM, TIMED, USEFUL)
LEVEL_PROBLEM, LEVEL_DUE, LEVEL_NEXT, LEVEL_USEFUL = 1, 2, 3, 4
PROBLEM_ICON = "⚠️"
TIME_LIMIT = 2.0  # seconds a provider gets
MAX_LINE = 128  # Discord's limit for a status line


@dataclass(frozen=True)
class Item:
    """One thing that may deserve to be looked at now."""

    what: str  # a few words for a person: "backup failed", "dose due"
    urgency: str  # PROBLEM, TIMED or USEFUL
    when: datetime | None = None  # when it is due, or happened; None with no time
    can_act: bool = False  # whether I can do something about it now
    link: str = ""  # where to go, if there is somewhere
    bug: str = ""  # the bug's id, if one was filed ("B14")
    # What the status line shows for it: numbers and short times only ("2/5", "12pm"). Never a name
    short: tuple[str, ...] = ()
    icon: str = ""  # the task's own unless said; ⚠️ for a problem
    task: str = ""  # who handed it in: filled in when it is gathered
    until: datetime | None = None  # the moment it stops being worth saying ("all 5 taken", until the evening)


def level(item: Item, now: datetime) -> int | None:
    """Where an item stands in the pecking order now, or None for one that is
    not ranked: a timed item with no time, or for another day, or one whose
    time to be said is over."""
    if item.until is not None and now >= item.until:
        return None
    if item.urgency == PROBLEM:
        return LEVEL_PROBLEM
    if item.urgency == USEFUL:
        return LEVEL_USEFUL
    if item.when is None or days.day_of(item.when) != days.day_of(now):
        return None
    return LEVEL_DUE if item.when <= now else LEVEL_NEXT


def ranked(items: list[Item], now: datetime) -> list[tuple[int, Item]]:
    """The items in the order they deserve attention: (level, item). The one
    ranking, used by every surface."""
    found = [(level(item, now), index, item) for index, item in enumerate(items)]

    def order(entry):
        rank, index, item = entry
        if rank == LEVEL_PROBLEM:
            # The most recent problem first; one with no time after those, in the order given
            return (rank, 0 if item.when is not None else 1, -(item.when.timestamp()) if item.when is not None else 0, index)
        if rank in (LEVEL_DUE, LEVEL_NEXT):
            return (rank, 0, item.when.timestamp(), index)
        return (rank, 0, 0, index)

    return [(rank, item) for rank, _, item in sorted((entry for entry in found if entry[0] is not None), key=order)]


def top(items: list[Item], now: datetime) -> Item | None:
    """The one item to look at first, or None: nothing."""
    order = ranked(items, now)
    return order[0][1] if order else None


def next_change(items: list[Item], now: datetime) -> datetime | None:
    """The next moment the ranking changes by the clock alone: a timed item
    still to come falls due. (The day ending is the caller's to add.)"""
    coming = [item.when for item in items if item.urgency == TIMED and item.when is not None and item.when > now]
    coming += [item.until for item in items if item.until is not None and item.until > now]
    return min(coming) if coming else None


def short_time(moment: datetime) -> str:
    """A time as the status line writes it: "12pm", "6am", "8:30am"."""
    local = moment.astimezone(TIMEZONE)
    hour = local.hour % 12 or 12
    return f"{hour}{'' if local.minute == 0 else f':{local.minute:02d}'}{'am' if local.hour < 12 else 'pm'}"


def status_line(item: Item | None) -> str:
    """The status line for the top item: its icon, then its short pieces joined
    by " · ". A problem points at its bug first, if one was filed. "" for
    nothing: the status line is blank."""
    if item is None:
        return ""
    icon = item.icon or (PROBLEM_ICON if item.urgency == PROBLEM else "")
    pieces = [*([item.bug] if item.bug else []), *(item.short or ((item.what,) if item.urgency == PROBLEM else ()))]
    if not pieces:
        return ""
    return f"{icon} {' · '.join(pieces)}".strip()[:MAX_LINE]


# --- gathering --------------------------------------------------------------------------------------------------------
# `async (user_id, now) -> list[Item]`
Provider = Callable[[int, datetime], Awaitable[list[Item]]]
_providers: dict[str, tuple[str, Provider]] = {}  # the core's own parts: {name: (icon, provider)}


def provide(name: str, icon: str, provider: Provider) -> None:
    """A part of the core hands in items (the run log's problems, the next
    morning routine). A task does it through its contract instead."""
    _providers[name] = (icon, provider)


async def _ask(name: str, icon: str, provider: Provider, user_id: int, now: datetime) -> list[Item]:
    try:
        found = await asyncio.wait_for(provider(user_id, now), TIME_LIMIT)
    except Exception:
        # A part that can't say is left out, and said in the log: it never takes the others with it
        log.exception("The attention items of %s could not be read", name)
        return []
    return [replace(item, task=name, icon=item.icon or (PROBLEM_ICON if item.urgency == PROBLEM else icon)) for item in found or [] if item.urgency in URGENCIES]


async def gather(user_id: int, now: datetime) -> list[Item]:
    """Every item there is now: each task's in the catalogue's order, then the
    core's own (so that among useful things a task's comes before "the day
    starts again at 6am"). Unranked: `ranked` does that."""
    found: list[Item] = []
    for entry in actions.catalogue():
        if entry.attention is not None:
            found += await _ask(entry.name, entry.icon, entry.attention, user_id, now)
    for name, (icon, provider) in list(_providers.items()):
        found += await _ask(name, icon, provider, user_id, now)
    return found


# --- telling the surfaces to look again -------------------------------------------------------------------------------
Listener = Callable[[], None]
_listeners: list[Listener] = []


def on_change(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def changed() -> None:
    """Something that hands in items says they may be different now. Called,
    not awaited: a surface schedules its own work. Never raises."""
    for listener in list(_listeners):
        try:
            listener()
        except Exception:
            log.exception("Could not tell a surface that the attention items changed")
