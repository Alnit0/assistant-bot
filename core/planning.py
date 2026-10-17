import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from core import actions, config, design, timeinput
from core import day as days

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Plan my day: the day in time order, with what can move put into the free
# time around what can't. Behind PLAN_MY_DAY (off unless set); the words are
# tasks/plan's, the engine is here.
#
#   fixed      every task hands over its day through its contract (`plan`, a
#              `Piece` each): calendar events, pill doses with a time, timed
#              reminders, personal routines at a time or in a window, and what
#              is due that day (an expiry, a birthday: all day, no time).
#              Never moved
#   flexible   open to-dos, overdue first, then the day's, then any day's.
#              Claude says how long each is (15, 30, 60 or 90 minutes, from
#              its words); Python does every sum and places them
#   placing    in the free time between 7:00 am and 10:00 pm (both changed in
#              words), 15 minutes between any two things, never more than 6
#              hours of flexible things, and always one free block of at
#              least 30 minutes left. What does not fit is said, never
#              dropped unseen
#
# Pure, but for `gather`, which asks every task's contract. A plan never pings
# on its own: it is a card, and what is saved is only read.
# ---------------------------------------------------------------------------
ICON = "🗓️"
DAY_START, DAY_END = time(7, 0), time(22, 0)
BUFFER = 15  # minutes between any two things
MOST = 6 * 60  # minutes of flexible things a day, at most
FREE_BLOCK = 30  # minutes: at least one free block of this is always left
SHOWN_GAP = 15  # a free gap shorter than this is not shown
POINT = 5  # minutes a thing with no length takes (a dose, a reminder)
ROUTINE = 30  # minutes a personal routine at a time is given
STEP = 5  # every start is on a 5-minute mark
LENGTHS = (15, 30, 60, 90)  # what Claude may estimate
DEFAULT_LENGTH = 30  # when no estimate came back
LONGEST = 8 * 60  # the most one thing may be said to take
OFFER_FROM = time(20, 0)  # the evening diary ask may offer to plan tomorrow from then
TIME_LIMIT = 2.0  # seconds a task gets to hand over its day

# Parts of the day a thing may be moved to in words ("move laundry to the evening")
PARTS = {"morning": (time(7, 0), time(12, 0)), "afternoon": (time(12, 0), time(17, 0)), "evening": (time(17, 0), time(22, 0))}
OVERDUE, TODAY, ANY_DAY = 0, 1, 2  # a flexible thing's rank

# Why a flexible thing was not placed
NO_ROOM = "no room"
OVER_LIMIT = "over 6 hours"
KEEP_FREE = "keeps a free block"
TIME_TAKEN = "that time is taken"


@dataclass(frozen=True)
class Piece:
    """One thing of a day, as a task hands it over (its contract's `plan`)."""

    task: str  # the task's name
    ref: str  # the task's own id for it ("t12"): what a plan keeps
    icon: str
    text: str  # its name, in the user's words
    at: datetime | None = None  # fixed: when it starts (UTC); None with all_day or flexible
    until: datetime | None = None  # fixed: when it ends; None for a moment (a dose, a reminder)
    all_day: bool = False  # due that day, at no time (an expiry, a birthday)
    flexible: bool = False  # a to-do: placed by the code
    rank: int = ANY_DAY  # flexible: overdue, the day's, any day's
    done: bool = False  # done already: kept, never placed again
    note: str = ""  # a few words after its name ("6:00 pm to 9:00 pm")

    @property
    def end(self) -> datetime | None:
        if self.at is None:
            return None
        return self.until if self.until is not None and self.until > self.at else self.at + timedelta(minutes=POINT)


@dataclass(frozen=True)
class Slot:
    """A flexible thing placed: when, and for how long."""

    piece: Piece
    start: datetime
    minutes: int

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Plan:
    day: date
    start: datetime  # the window planned in
    end: datetime
    fixed: tuple[Piece, ...] = ()  # with a time, in time order
    all_day: tuple[Piece, ...] = ()
    slots: tuple[Slot, ...] = ()
    gaps: tuple[Gap, ...] = ()
    left_out: tuple[tuple[Piece, str], ...] = ()  # flexible things not placed, and why
    done: tuple[Piece, ...] = ()  # flexible things done already
    out: tuple[Gap, ...] = ()  # times said to be taken ("I'm out 2 to 4")

    @property
    def free_minutes(self) -> int:
        return sum(each.minutes for each in self.gaps)

    @property
    def planned_minutes(self) -> int:
        return sum(each.minutes for each in self.slots)


# --- pure: lengths and times -----------------------------------------------------------------------------------------
def estimate(said) -> int:
    """Claude's estimate as one of the lengths: the nearest, or the default when it can't be read."""
    try:
        minutes = int(str(said).strip())
    except (TypeError, ValueError):
        return DEFAULT_LENGTH
    return min(LENGTHS, key=lambda each: (abs(each - minutes), each))


def length(said) -> int | None:
    """A length the user said ("make the essay 2 hours": 120), within reason; None if it can't be read."""
    try:
        minutes = int(said)
    except (TypeError, ValueError):
        return None
    return max(STEP, min(LONGEST, minutes)) if minutes > 0 else None


def minutes_text(minutes: int) -> str:
    """ "45 min", "1h", "2h 15m"."""
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h" + (f" {rest}m" if rest else "")


def free_text(minutes: int) -> str:
    """The free time in the summary line: "2h free", "45 min free", "no free time"."""
    return f"{minutes_text(minutes)} free" if minutes > 0 else "no free time"


def _up(moment: datetime) -> datetime:
    """On the next 5-minute mark (or this one: seconds past it don't count)."""
    moment = moment.replace(second=0, microsecond=0)
    left = moment.minute % STEP
    return moment + timedelta(minutes=(STEP - left) % STEP)


def window(day: date, now: datetime, starts: time | None = None, ends: time | None = None, from_now: bool = False) -> tuple[datetime, datetime]:
    """The time planned in: the day's start and end as said (7:00 am to 10:00 pm otherwise); today, never
    before now. An end said before the start is taken as the evening's (\"till 9\")."""
    start = days.at(day, starts or DAY_START)
    end = days.at(day, ends or DAY_END)
    if end <= start and ends is not None and ends.hour < 12:
        end = days.at(day, time(ends.hour + 12, ends.minute))
    if day == days.day_of(now) or from_now:
        start = max(start, _up(now))
    return start, end


def _merged(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    found: list[list[datetime]] = []
    for begin, finish in sorted(spans):
        if found and begin <= found[-1][1]:
            found[-1][1] = max(found[-1][1], finish)
        else:
            found.append([begin, finish])
    return [(begin, finish) for begin, finish in found]


def free(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> list[Gap]:
    """What is left of the window once the busy times are taken out."""
    gaps, at = [], start
    for begin, finish in _merged([(max(begin, start), min(finish, end)) for begin, finish in busy if finish > start and begin < end]):
        if begin > at:
            gaps.append(Gap(at, begin))
        at = max(at, finish)
    if at < end:
        gaps.append(Gap(at, end))
    return gaps


def _fits(begin: datetime, finish: datetime, start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    """Inside the window, and 15 minutes from anything else (the window's own edges need none)."""
    if begin < start or finish > end:
        return False
    gap = timedelta(minutes=BUFFER)
    return all(finish + gap <= other_start or begin >= other_end + gap for other_start, other_end in busy)


def _first_fit(minutes: int, start: datetime, end: datetime, busy: list[tuple[datetime, datetime]], at: datetime | None = None) -> datetime | None:
    """The earliest start for a thing of that length, or None. With `at`, only that start."""
    length_of = timedelta(minutes=minutes)
    if at is not None:
        return at if _fits(at, at + length_of, start, end, busy) else None
    gap = timedelta(minutes=BUFFER)
    for begin in sorted({start, *(_up(other_end + gap) for _, other_end in busy)}):
        begin = max(begin, start)
        if _fits(begin, begin + length_of, start, end, busy):
            return begin
    return None


def place(
    day: date, pieces: list[Piece], lengths: dict[str, int], start: datetime, end: datetime, *,
    out: list[tuple[datetime, datetime]] = (), parts: dict[str, str] | None = None, at: dict[str, datetime] | None = None,
    dropped: set[str] = frozenset(),
) -> Plan:
    """The day planned: fixed things where they are, flexible ones in order (overdue first, then the day's,
    then any day's; one given a time first) each in the earliest free time that keeps 15 minutes from
    everything else, never more than 6 hours of them, and one free block of 30 minutes always left.
    `parts` puts a thing in a part of the day ("evening"), `at` at a time; `dropped` leaves it out."""
    parts, at = parts or {}, at or {}
    fixed = sorted((each for each in pieces if not each.flexible and not each.all_day and each.at is not None), key=lambda each: (each.at, each.text))
    all_day = tuple(each for each in pieces if each.all_day)
    flexible = [each for each in pieces if each.flexible and each.ref not in dropped]
    done = tuple(each for each in flexible if each.done)
    order = {each.ref: index for index, each in enumerate(flexible)}
    waiting = sorted((each for each in flexible if not each.done), key=lambda each: (each.ref not in at, each.rank, order[each.ref]))
    busy = [(each.at, each.end) for each in fixed] + [(begin, finish) for begin, finish in out]
    slots, left_out, total = [], [], 0
    for each in waiting:
        minutes = lengths.get(each.ref, DEFAULT_LENGTH)
        if total + minutes > MOST:
            left_out.append((each, OVER_LIMIT))
            continue
        lowest, highest = start, end
        if each.ref in parts and parts[each.ref] in PARTS:
            first, last = PARTS[parts[each.ref]]
            lowest, highest = max(start, days.at(day, first)), min(end, days.at(day, last))
        begin = _first_fit(minutes, lowest, highest, busy + [(slot.start, slot.end) for slot in slots], at.get(each.ref))
        if begin is None:
            left_out.append((each, TIME_TAKEN if each.ref in at else NO_ROOM))
            continue
        taken = busy + [(slot.start, slot.end) for slot in slots] + [(begin, begin + timedelta(minutes=minutes))]
        if not any(gap.minutes >= FREE_BLOCK for gap in free(start, end, taken)):
            left_out.append((each, KEEP_FREE))
            continue
        slots.append(Slot(each, begin, minutes))
        total += minutes
    taken = busy + [(slot.start, slot.end) for slot in slots]
    gaps = tuple(gap for gap in free(start, end, taken) if gap.minutes >= SHOWN_GAP)
    shown_out = tuple(Gap(begin, finish) for begin, finish in out)
    return Plan(day, start, end, tuple(fixed), all_day, tuple(sorted(slots, key=lambda slot: slot.start)), gaps, tuple(left_out), done, shown_out)


# --- pure: the card's words -----------------------------------------------------------------------------------------
def day_label(day: date, today: date) -> str:
    said = "Today" if day == today else "Tomorrow" if day == today + timedelta(days=1) else f"{day:%a}"
    return f"{said} · {day:%a} {day.day} {day:%b}" if said in ("Today", "Tomorrow") else f"{day:%a} {day.day} {day:%b}"


def summary_line(plan: Plan, today: date) -> str:
    """The one line at the top: "**Today · Sat 17 Oct** · 5 things planned · 2h free"."""
    count = len(plan.slots)
    planned = f"{count} thing{'' if count == 1 else 's'} planned" if count else "nothing to place"
    return f"**{day_label(plan.day, today)}** · {planned} · {free_text(plan.free_minutes)}"


def _fixed_line(group: list[Piece]) -> str:
    first = group[0]
    names = ", ".join(each.text for each in group)
    note = f" · {first.note}" if first.note and len(group) == 1 else ""
    return f"{timeinput.format_moment(first.at)} · {first.icon} {names}{note} · fixed"


def lines(plan: Plan, today: date) -> tuple[str, ...]:
    """The plan in time order: fixed things marked as fixed, each suggested slot in bold with its length,
    free gaps in small text; what is due all day at the top, what was left out and what is done after."""
    said = [summary_line(plan, today)]
    if plan.all_day:
        said.append(design.small("all day · " + " · ".join(f"{each.icon} {each.text}" for each in plan.all_day)))
    timeline: list[tuple[datetime, int, str]] = []
    grouped: list[list[Piece]] = []
    for each in plan.fixed:
        if grouped and grouped[-1][0].at == each.at and grouped[-1][0].task == each.task:
            grouped[-1].append(each)
        else:
            grouped.append([each])
    for group in grouped:
        timeline.append((group[0].at, 0, _fixed_line(group)))
    for slot in plan.slots:
        timeline.append((slot.start, 1, f"**{timeinput.format_moment(slot.start)} · {slot.piece.icon} {slot.piece.text}** · {minutes_text(slot.minutes)}"))
    for gap in plan.out:
        timeline.append((gap.start, 0, f"{timeinput.format_moment(gap.start)} · out until {timeinput.format_moment(gap.end)} · fixed"))
    for gap in plan.gaps:
        timeline.append((gap.start, 2, design.small(f"free {timeinput.format_moment(gap.start)} to {timeinput.format_moment(gap.end)}")))
    said += [text for _, _, text in sorted(timeline, key=lambda each: (each[0], each[1]))]
    by_why: dict[str, list[str]] = {}
    for piece, why in plan.left_out:
        by_why.setdefault(why, []).append(piece.text)
    for why, names in by_why.items():
        said.append(design.small(f"not placed ({why}): " + ", ".join(names)))
    if plan.done:
        said.append(design.small("✅ done: " + ", ".join(each.text for each in plan.done)))
    return tuple(said)


def nothing_fits(plan: Plan) -> bool:
    """Nothing could be placed: the card has nothing to save."""
    return not plan.slots


def offer_line(now: datetime) -> str:
    """One small line the evening diary ask may carry, from 8:00 pm: planning tomorrow is a word away."""
    if not config.PLAN_MY_DAY or days.local_time(now) < OFFER_FROM:
        return ""
    return design.small("Say “plan tomorrow” to plan it")


# --- gathering: every task's contract ------------------------------------------------------------------------------
async def gather(user_id: int, day: date) -> list[Piece]:
    """Every task's things for a day (its contract's `plan`). One that can't be read is left out and logged."""
    found: list[Piece] = []
    for entry in actions.catalogue():
        if entry.plan is None:
            continue
        try:
            found += list(await asyncio.wait_for(entry.plan(user_id, day), TIME_LIMIT))
        except Exception:
            log.exception("The day of %s could not be read for a plan", entry.name)
    return found
