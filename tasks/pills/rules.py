import re
from dataclasses import dataclass, replace
from datetime import date, time, timedelta

from core import durations, schedule, timeinput
from core.errors import UserError
from core.schedule import DAY_MINUTES, Schedule
from core.timeinput import AmbiguousTime

# ---------------------------------------------------------------------------
# Pills: what a pill's plan is, how one is built from what the user said, and
# how it is put into words. Pure: no Discord, no database, no clock (the day
# it is comes in as `today`).
#
# The plan is what the user configured and only they change it. Every pill
# has the one shape of schedule (core/schedule.py): doses a day, and
# optionally a planned time for each dose (or for the first only), a minimum
# gap between doses and a latest time of day. What is here is how a schedule
# is read from the user's words and put back into them.
# A plan with dates is a course: taken from `start` to `end`, both included.
# Without dates it simply goes on.
#
# Claude decides which of the user's words are the name, the times and the
# dates. It hands over times in one fixed form (with no am or pm when the
# user gave none) and lengths of time as minutes; dates as they were said.
# Everything here on is code, and it reads other forms of a time or a length
# as well, should one arrive.
# ---------------------------------------------------------------------------
# What is stored
ACTIVE, PAUSED, REMOVED = "active", "paused", "removed"
# What a pill is on a given day, which also depends on its dates
UPCOMING, ENDED = "upcoming", "ended"

MAX_NAME = 60
MAX_TEXT = 100  # dose and notes
MAX_PER_DAY = 12

ID_PREFIX = "pl"
# Said in place of a value, to take it away when editing
CLEAR = frozenset({"none", "no", "clear", "remove", "-"})


@dataclass(frozen=True)
class Plan:
    name: str
    dose: str = ""  # "1 tablet"
    notes: str = ""  # "with food"
    schedule: Schedule = Schedule()
    start: date | None = None  # a course; both or neither
    end: date | None = None

    @property
    def is_course(self) -> bool:
        return self.end is not None


@dataclass(frozen=True)
class Pill:
    id: int
    user_id: int
    plan: Plan
    status: str = ACTIVE
    paused_until: date | None = None  # the day it is taken again; None for until told

    @property
    def ref(self) -> str:
        return f"{ID_PREFIX}{self.id}"


@dataclass(frozen=True)
class Request:
    """What was asked for, in the user's words. An empty value says nothing
    about that part: a new pill gets the default, an edited one keeps what it
    has. One of CLEAR takes it away."""

    name: str = ""
    dose: str = ""
    notes: str = ""
    times: str = ""  # "8am, 8pm"
    per_day: str = ""  # "3"
    min_gap: str = ""  # "3h"
    latest: str = ""  # "4pm"
    start: str = ""  # "tomorrow"
    end: str = ""  # "the 20th"
    days: str = ""  # "7"

    def merged(self, later: "Request") -> "Request":
        """This request with whatever a later one says on top."""
        given = {name: value for name, value in vars(later).items() if value.strip()}
        return replace(self, **given)


class DoesNotFit(UserError):
    """The schedule was read, but its doses can't all be taken in a day. `plan`
    is what was read, so a card can show it with the reason and be put right
    by a reply; it is never saved as it is."""

    def __init__(self, reason: str, plan: "Plan | None" = None):
        self.plan = plan
        super().__init__(reason)


class Unreadable(UserError):
    """One part of the request couldn't be read at all. `field` says which of
    the request's parts; the message says why. The rest can still be shown."""

    def __init__(self, field: str, reason: str):
        self.field = field
        super().__init__(reason)


def _read(field: str, reader, *given):
    """What `reader` makes of one part of the request; if it can't, the
    refusal names the part."""
    try:
        return reader(*given)
    except (TimeQuestion, Unreadable):
        raise
    except UserError as problem:
        raise Unreadable(field, str(problem))


class TimeQuestion(UserError):
    """One of the times could be morning or evening. `field` says whether it
    is one of the request's times (`index` says which) or its latest time,
    and `options` holds both readings; nothing is guessed. answer() gives the
    request with it settled."""

    def __init__(self, index: int, typed: str, options: tuple[time, time], field: str = "times"):
        self.index, self.typed, self.options, self.field = index, typed, options, field
        super().__init__(f"“{typed}”: {timeinput.AmbiguousTime(options)}")


# ---------------------------------------------------------------------------
# Reading the parts
# ---------------------------------------------------------------------------
_TIME_SEPARATOR = re.compile(r"\s*(?:,|;|&|\band\b|\bthen\b)\s*")
_COUNT_WORDS = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COUNT = re.compile(r"(\d{1,2})\s*(?:x|×|times?|doses?)?(?: (?:a|per) day| daily)?")


def _given(value: str) -> bool:
    return bool(value.strip())


def _cleared(value: str) -> bool:
    return value.strip().lower() in CLEAR


def split_times(text: str) -> list[str]:
    """The separate times in "8am, 8pm" or "8 and 20:00", as typed."""
    return [part for part in _TIME_SEPARATOR.split(text.strip()) if part]


def answer(request: Request, question: TimeQuestion, chosen: time) -> Request:
    """The request with the time that was asked about replaced by the answer."""
    if question.field == "latest":
        return replace(request, latest=timeinput.format_time(chosen))
    parts = split_times(request.times)
    parts[question.index] = timeinput.format_time(chosen)
    return replace(request, times=", ".join(parts))


def _times(text: str) -> tuple[time, ...]:
    """The times as said. One that could be morning or evening is settled by
    the times around it when only one reading keeps them in order ("8am,
    11:30 and 3pm" can only mean 11:30 am): that is not a guess. Otherwise it
    is a TimeQuestion."""
    parts = split_times(text)
    read: list[time | AmbiguousTime] = []
    for part in parts:
        try:
            read.append(timeinput.parse_time(part))
        except AmbiguousTime as unsure:
            read.append(unsure)
    found: list[time] = []
    for index, value in enumerate(read):
        if isinstance(value, AmbiguousTime):
            after = found[-1] if found else None
            before = next((later for later in read[index + 1 :] if isinstance(later, time)), None)
            possible = [
                option
                for option in value.options
                if (after is None or option > after) and (before is None or option < before)
            ]
            if len(possible) != 1:
                raise TimeQuestion(index, parts[index], value.options)
            value = possible[0]
        found.append(value)
    return tuple(found)


def _latest(text: str, times: tuple[time, ...]) -> time:
    """The latest time of day. "4" after planned times that end at 3 pm can
    only be 4 pm; with nothing to go by it is a TimeQuestion."""
    try:
        return timeinput.parse_time(text)
    except AmbiguousTime as unsure:
        possible = [option for option in unsure.options if times and option >= max(times)]
        if len(possible) == 1:
            return possible[0]
        raise TimeQuestion(0, text.strip(), unsure.options, field="latest")


def _count(text: str) -> int:
    value = re.sub(r"\s+", " ", text.strip().lower())
    if value in _COUNT_WORDS:
        return _COUNT_WORDS[value]
    match = _COUNT.fullmatch(value)
    if not match or not 1 <= int(match[1]) <= MAX_PER_DAY:
        raise UserError(f"How many times a day is “{text.strip()}”? Give a number from 1 to {MAX_PER_DAY}.")
    return int(match[1])


def _gap(text: str) -> int:
    """A minimum gap in minutes, from a length in any form core/durations.py
    reads ("180m", "3h", "3 hours apart", "an hour and a half"). A bare
    number isn't guessed to be hours or minutes."""
    value = durations.as_said(text)
    if not re.search(r"[a-z:]", value):
        raise UserError(f"Is the gap {value} hours or {value} minutes? Say `{value}h` or `{value}m`.")
    try:
        minutes = round(durations.parse_duration(value) / 60)
    except durations.DurationError:
        raise UserError(f"I can't read “{text.strip()}” as a gap. Try `3h` or `90m`.")
    if minutes < 1:
        raise UserError("The gap between doses must be at least a minute.")
    return minutes


def _days(text: str) -> int:
    match = re.fullmatch(r"(\d{1,3})\s*(?:days?)?", text.strip().lower())
    if not match or int(match[1]) < 1:
        raise UserError(f"For how many days is “{text.strip()}”? Give a number, e.g. 7.")
    return int(match[1])


def _text(value: str, limit: int, what: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if len(cleaned) > limit:
        raise UserError(f"The {what} is too long: keep it under {limit} characters.")
    return cleaned


# ---------------------------------------------------------------------------
# Building a plan
# ---------------------------------------------------------------------------
def build(request: Request, today: date, base: Plan | None = None, moved: list[str] | None = None) -> Plan:
    """The plan a request asks for: a new one, or `base` with the changes.

    Raises TimeQuestion if a time could be morning or evening, and UserError
    with a short reason for anything that doesn't make a plan: Unreadable,
    naming the part, for a time, a length, a number or a date that can't be
    read; DoesNotFit, carrying the plan as read, when it is only that the
    doses can't fit in a day. Nothing is guessed. The one thing adjusted is a planned time closer to the one
    before than the gap allows: it moves later, and `moved` is given a line
    saying so, for the card.
    """
    # --- name, dose, notes ---
    name = _text(request.name, MAX_NAME, "name") if _given(request.name) else (base.name if base else "")
    if not name:
        raise UserError("What is the pill called?")

    def optional(value: str, kept: str, what: str) -> str:
        if not _given(value):
            return kept
        return "" if _cleared(value) else _text(value, MAX_TEXT, what)

    dose = optional(request.dose, base.dose if base else "", "dose")
    notes = optional(request.notes, base.notes if base else "", "note")

    # --- schedule: only what was said changes ---
    old = base.schedule if base else None
    if not _given(request.times):
        times = old.times if old else ()
    else:
        times = () if _cleared(request.times) else _read("times", _times, request.times)
    if not _given(request.min_gap):
        gap = old.gap_minutes if old else None
    else:
        gap = None if _cleared(request.min_gap) else _read("min_gap", _gap, request.min_gap)
    if not _given(request.latest):
        latest = old.latest if old else None
    else:
        latest = None if _cleared(request.latest) else _read("latest", _latest, request.latest, times)
    asked = _read("per_day", _count, request.per_day) if _given(request.per_day) else None
    if len(set(times)) != len(times):
        raise UserError("Two of those times are the same.")
    times = tuple(sorted(times))

    if gap is None:
        if times and asked is not None and asked != len(times):
            raise UserError(
                f"That is {len(times)} time{'s' if len(times) != 1 else ''} for {asked} doses a day. "
                "Give a time for each dose, or a minimum gap between them instead."
            )
        per_day = len(times) or asked or (old.per_day if old else 1)
    else:
        per_day = asked or (len(times) if len(times) > 1 else None) or (old.per_day if old and old.per_day > 1 else None)
        if per_day is None:
            raise UserError("How many times a day?")
        if per_day < 2:
            raise UserError("A minimum gap needs at least 2 doses a day.")
        # Times the pill already had, for another number of doses, don't carry over
        first_only = old is not None and old.gap_minutes is not None and len(times) == 1
        if not _given(request.times) and len(times) != per_day and not first_only:
            times = ()
        if len(times) not in (0, 1, per_day):
            raise UserError(
                f"That is {len(times)} times for {per_day} doses a day. "
                "Give a time for each dose, or for the first one only."
            )

    planned, moves = schedule.spaced(Schedule(per_day, times, gap, latest))
    if moved is not None:
        moved.extend(_move_text(move, gap) for move in moves)

    # --- dates: a course, or none ---
    start, end = (base.start, base.end) if base else (None, None)
    if any(_cleared(value) for value in (request.start, request.end, request.days)):
        start = end = None
    elif any(_given(value) for value in (request.start, request.end, request.days)):
        if _given(request.end) and _given(request.days):
            raise UserError("Give an end date or a number of days, not both.")
        start = _read("start", timeinput.parse_date, request.start, today) if _given(request.start) else (start or today)
        if _given(request.days):
            end = start + timedelta(days=_read("days", _days, request.days) - 1)  # the last day is a day of taking
        elif _given(request.end):
            end = _read("end", timeinput.parse_date, request.end, max(today, start))
        elif end is None:
            raise UserError("When does it end? Give an end date or a number of days.")
        if end < today:
            raise UserError(f"That course is already over: it ends {timeinput.format_date(end)}.")
        if end < start:
            raise UserError(
                f"It would end ({timeinput.format_date(end)}) before it starts ({timeinput.format_date(start)})."
            )

    plan = Plan(name, dose, notes, planned, start, end)
    try:
        _check_fits(planned)
    except DoesNotFit as problem:
        raise DoesNotFit(str(problem), plan)
    return plan


_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth")


def _move_text(move: schedule.Move, gap: int) -> str:
    """ "11:30 am to 2:00 pm is under 3h: the third dose moves to 2:30 pm"."""
    shown = timeinput.format_time
    return (
        f"{shown(move.before)} to {shown(move.was)} is under {gap_text(gap)}: "
        f"the {_ORDINALS[move.index]} dose moves to {shown(move.now)}"
    )


def _check_fits(planned: Schedule) -> None:
    """Refuse a schedule whose doses can't all be taken in a day, even on time."""
    shown = timeinput.format_time
    limit = planned.latest.hour * 60 + planned.latest.minute if planned.latest is not None else None
    for value in planned.times:
        if limit is not None and value.hour * 60 + value.minute > limit:
            raise DoesNotFit(f"A dose at {shown(value)} would be after the latest time, {shown(planned.latest)}.")
    if planned.gap_minutes is None:
        return
    earliest = 0
    for index in range(planned.per_day):
        value = planned.planned(index)
        at = value.hour * 60 + value.minute if value is not None else 0
        earliest = at if index == 0 else max(at, earliest + planned.gap_minutes)
    if earliest >= DAY_MINUTES or (limit is not None and earliest > limit):
        where = "in a day" if limit is None else f"before {shown(planned.latest)}"
        raise DoesNotFit(f"{planned.per_day} doses {gap_text(planned.gap_minutes)} apart don't fit {where}.")


def check_name(plan: Plan, others: list[Pill], own_id: int | None = None) -> None:
    """Two pills in use can't share a name: nobody could say which was meant."""
    for other in others:
        if other.id != own_id and other.status != REMOVED and other.plan.name.lower() == plan.name.lower():
            raise UserError(f"There is already a pill called **{other.plan.name}**. Edit that one, or pick another name.")


# ---------------------------------------------------------------------------
# What a pill is today
# ---------------------------------------------------------------------------
def status_on(pill: Pill, today: date) -> str:
    """REMOVED, ENDED, UPCOMING, PAUSED or ACTIVE, in that order of precedence.

    A course is over the day after its last day. A pause with an end date is
    over on that date, with nothing having to run for it to be so.
    """
    if pill.status == REMOVED:
        return REMOVED
    if pill.plan.end is not None and today > pill.plan.end:
        return ENDED
    if pill.status == PAUSED and (pill.paused_until is None or today < pill.paused_until):
        return PAUSED
    if pill.plan.start is not None and today < pill.plan.start:
        return UPCOMING
    return ACTIVE


def is_taken_on(pill: Pill, day: date) -> bool:
    """Whether doses are expected on that day."""
    return status_on(pill, day) == ACTIVE


# ---------------------------------------------------------------------------
# In words
# ---------------------------------------------------------------------------
def gap_text(minutes: int) -> str:
    """A gap as it is shown: "3h", "90m", "1h 30m"."""
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest}m"
    return f"{hours}h" if not rest else f"{hours}h {rest}m"


def _clock(value: time) -> str:
    return f"`{timeinput.format_time(value)}`"


def _schedule_parts(planned: Schedule) -> tuple[str, list[str]]:
    """A schedule as (how often and when, its conditions): every setting that
    was filled in is written out, and none that wasn't."""
    count = "daily" if planned.per_day == 1 else f"{planned.per_day}× daily"
    times = ", ".join(_clock(value) for value in planned.times)
    conditions = []
    if planned.gap_minutes is None:
        head = f"daily at {times}" if planned.times else f"{count}, any time"
    elif len(planned.times) > 1:
        head = f"{count} · {times}"
        conditions.append(f"at least {gap_text(planned.gap_minutes)} apart")
    else:
        first = f"first dose at {times}" if planned.times else "first dose when ready"
        head = f"{count}, at least {gap_text(planned.gap_minutes)} apart, {first}"
    if planned.latest is not None:
        conditions.append(f"not after {_clock(planned.latest)}")
    return head, conditions


def schedule_text(plan: Plan) -> str:
    """ "daily, any time", "daily at `8:00 pm`", "3× daily, at least 3h apart,
    first dose when ready", "3× daily · `8:00 am`, `11:30 am`, `3:00 pm` · at
    least 3h apart · not after `4:00 pm`"."""
    head, conditions = _schedule_parts(plan.schedule)
    return " · ".join([head, *conditions])


def _name(plan: Plan) -> str:
    return f"**{plan.name}**" + (f" ({plan.dose})" if plan.dose else "")


def _extras(plan: Plan) -> list[str]:
    return ([f"*{plan.notes}*"] if plan.notes else []) + (
        [timeinput.format_dates(plan.start, plan.end)] if plan.is_course else []
    )


def describe(plan: Plan, icon: str = "💊") -> str:
    """A plan on one line, as lists show it. A pill that goes on indefinitely
    shows no dates at all."""
    return " · ".join([f"{icon} {_name(plan)}", schedule_text(plan), *_extras(plan)])


def card_lines(plan: Plan) -> list[str]:
    """A plan as a card shows it: one line, or two for a pill with planned
    times and conditions on them (the gap, the latest time)."""
    head, conditions = _schedule_parts(plan.schedule)
    if not conditions:
        return [" · ".join([_name(plan), head, *_extras(plan)])]
    second = " · ".join([*conditions, *_extras(plan)])
    return [f"{_name(plan)} · {head}", second[0].upper() + second[1:]]


def describe_pill(pill: Pill, today: date) -> str:
    """A pill on one line with what it is today: paused, upcoming, ended."""
    state = status_on(pill, today)
    if state == PAUSED:
        until = f" until {timeinput.format_date(pill.paused_until)}" if pill.paused_until else ""
        return f"{describe(pill.plan, '⏸️')} · paused{until}"
    if state == ENDED:
        return describe(pill.plan, "🏁")
    if state == UPCOMING:
        return f"{describe(pill.plan, '🗓️')} · starts {timeinput.format_date(pill.plan.start)}"
    return describe(pill.plan)


EMPTY_LIST = "No pills yet. Tell me about one, e.g. “add vitamin D, once a day”."


def _by_name(pills: list[Pill]) -> list[Pill]:
    return sorted(pills, key=lambda pill: pill.plan.name.lower())


def list_text(pills: list[Pill], today: date) -> str:
    """Every pill that hasn't been removed: in use first, then paused, then ended."""
    groups = {state: [] for state in (ACTIVE, UPCOMING, PAUSED, ENDED)}
    for pill in _by_name(pills):
        state = status_on(pill, today)
        if state in groups:
            groups[state].append(describe_pill(pill, today))
    lines = ["## 💊 Pills", *groups[ACTIVE], *groups[UPCOMING]]
    if not groups[ACTIVE] and not groups[UPCOMING]:
        lines.append(EMPTY_LIST if not groups[PAUSED] and not groups[ENDED] else "Nothing is being taken at the moment.")
    if groups[PAUSED]:
        lines += ["### ⏸️ Paused", *groups[PAUSED]]
    if groups[ENDED]:
        lines += ["### 🏁 Ended", *groups[ENDED]]
    return "\n".join(lines)


def listed(pills: list[Pill]) -> list[Pill]:
    """The pills the list shows, in its order of names."""
    return [pill for pill in _by_name(pills) if pill.status != REMOVED]


def differences(old: Plan, new: Plan) -> list[tuple[str, str, str]]:
    """What an edit changes, a field at a time: (field, old, new), as a card
    shows it ("schedule · daily at `8:00 pm` → daily at `9:00 pm`"). Empty if
    nothing would change."""

    def dates(plan: Plan) -> str:
        return timeinput.format_dates(plan.start, plan.end) if plan.is_course else "no end date"

    found = [
        ("name", old.name, new.name),
        ("dose", old.dose or "none", new.dose or "none"),
        ("notes", old.notes or "none", new.notes or "none"),
        ("schedule", schedule_text(old), schedule_text(new)),
        ("dates", dates(old), dates(new)),
    ]
    return [(name, before, after) for name, before, after in found if before != after]


# ---------------------------------------------------------------------------
# Which pill is meant
# ---------------------------------------------------------------------------
def find(pills: list[Pill], wanted: str) -> Pill:
    """The pill a name or an id ("pl3") means, among those not removed.

    The whole name wins over part of one. Raises UserError if there is none,
    or if more than one fits: the user is asked, never guessed for.
    """
    candidates = listed(pills)
    text = re.sub(r"\s+", " ", wanted.strip().lower())
    if not text:
        raise UserError("Which pill?")
    match = re.fullmatch(rf"{ID_PREFIX}\s*(\d+)", text)
    if match:
        by_id = [pill for pill in candidates if pill.id == int(match[1])]
        if by_id:
            return by_id[0]
    for found in (
        [pill for pill in candidates if pill.plan.name.lower() == text],
        [pill for pill in candidates if text in pill.plan.name.lower()],
    ):
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            names = " or ".join(f"**{pill.plan.name}**" for pill in found)
            raise UserError(f"Which one: {names}?")
    if not candidates:
        raise UserError("There are no pills yet.")
    names = ", ".join(pill.plan.name for pill in candidates)
    raise UserError(f"I don't have a pill called “{wanted.strip()}”. Yours: {names}.")


# ---------------------------------------------------------------------------
# For Claude: what there is, with the ids its tools take
# ---------------------------------------------------------------------------
def plain(text: str) -> str:
    return re.sub(r"[*`]", "", text)

