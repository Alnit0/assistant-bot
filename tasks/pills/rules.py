import re
from dataclasses import dataclass, replace
from datetime import date, time, timedelta

from core import timeinput
from core.errors import UserError
from core.timeinput import AmbiguousTime
from tasks.timers.durations import DurationError, parse_duration

# ---------------------------------------------------------------------------
# Pills: what a pill's plan is, how one is built from what the user said, and
# how it is put into words. Pure: no Discord, no database, no clock (the day
# it is comes in as `today`).
#
# The plan is what the user configured and only they change it. Three kinds
# of schedule:
#   untimed    so many a day, at no particular time
#   fixed      at these times of day
#   interval   so many a day with a minimum gap between doses; the first may
#              have a time, each later one follows the dose actually taken
# A plan with dates is a course: taken from `start` to `end`, both included.
# Without dates it simply goes on.
#
# Claude decides which of the user's words are the name, the times and the
# dates, and hands them over as they were said; everything here on is code.
# ---------------------------------------------------------------------------
UNTIMED, FIXED, INTERVAL = "untimed", "fixed", "interval"

# What is stored
ACTIVE, PAUSED, REMOVED = "active", "paused", "removed"
# What a pill is on a given day, which also depends on its dates
UPCOMING, ENDED = "upcoming", "ended"

MAX_NAME = 60
MAX_TEXT = 100  # dose and notes
MAX_PER_DAY = 12
DAY_MINUTES = 24 * 60

ID_PREFIX = "pl"
# Said in place of a value, to take it away when editing
CLEAR = frozenset({"none", "no", "clear", "remove", "-"})


@dataclass(frozen=True)
class Plan:
    name: str
    dose: str = ""  # "1 tablet"
    notes: str = ""  # "with food"
    kind: str = UNTIMED
    times: tuple[time, ...] = ()  # fixed: each dose; interval: the first dose, if it has a time
    per_day: int = 1
    gap_minutes: int | None = None  # interval only
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
    start: str = ""  # "tomorrow"
    end: str = ""  # "the 20th"
    days: str = ""  # "7"

    def merged(self, later: "Request") -> "Request":
        """This request with whatever a later one says on top."""
        given = {name: value for name, value in vars(later).items() if value.strip()}
        return replace(self, **given)


class TimeQuestion(UserError):
    """One of the times could be morning or evening. `index` says which of the
    request's times it is and `options` holds both readings; nothing is
    guessed. answer() gives the request with it settled."""

    def __init__(self, index: int, typed: str, options: tuple[time, time]):
        self.index, self.typed, self.options = index, typed, options
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
    parts = split_times(request.times)
    parts[question.index] = chosen.strftime("%H:%M")
    return replace(request, times=", ".join(parts))


def _times(text: str) -> tuple[time, ...]:
    found = []
    for index, part in enumerate(split_times(text)):
        try:
            found.append(timeinput.parse_time(part))
        except AmbiguousTime as unsure:
            raise TimeQuestion(index, part, unsure.options)
    return tuple(found)


def _count(text: str) -> int:
    value = re.sub(r"\s+", " ", text.strip().lower())
    if value in _COUNT_WORDS:
        return _COUNT_WORDS[value]
    match = _COUNT.fullmatch(value)
    if not match or not 1 <= int(match[1]) <= MAX_PER_DAY:
        raise UserError(f"How many times a day is “{text.strip()}”? Give a number from 1 to {MAX_PER_DAY}.")
    return int(match[1])


def _gap(text: str) -> int:
    """A minimum gap in minutes. A bare number isn't guessed to be hours or minutes."""
    value = text.strip().lower()
    if not re.search(r"[a-z:]", value):
        raise UserError(f"Is the gap {value} hours or {value} minutes? Say `{value}h` or `{value}m`.")
    try:
        minutes = round(parse_duration(value) / 60)
    except DurationError:
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
def build(request: Request, today: date, base: Plan | None = None) -> Plan:
    """The plan a request asks for: a new one, or `base` with the changes.

    Raises TimeQuestion if a time could be morning or evening, and UserError
    with a short reason for anything that doesn't make a plan. Nothing is
    guessed and nothing is silently adjusted.
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

    # --- schedule ---
    if not _given(request.times):
        times = base.times if base else ()
    else:
        times = () if _cleared(request.times) else _times(request.times)
    if not _given(request.min_gap):
        gap = base.gap_minutes if base else None
    else:
        gap = None if _cleared(request.min_gap) else _gap(request.min_gap)
    asked = _count(request.per_day) if _given(request.per_day) else None
    if base is not None:
        # Changing the kind of schedule: what belonged to the old kind doesn't carry over
        if _given(request.min_gap) and not _given(request.times) and base.kind != INTERVAL:
            times = ()
        if len(times) > 1 and not _given(request.min_gap) and base.kind == INTERVAL:
            gap = None

    if gap is not None:
        kind = INTERVAL
        if len(times) > 1:
            raise UserError(
                "With a minimum gap only the first dose can have a time: the others follow the dose before."
            )
        per_day = asked or (base.per_day if base and base.kind == INTERVAL else None)
        if per_day is None:
            raise UserError("How many times a day?")
        if per_day < 2:
            raise UserError("A minimum gap needs at least 2 doses a day.")
        if gap * (per_day - 1) >= DAY_MINUTES:
            raise UserError(f"{per_day} doses {gap_text(gap)} apart don't fit in a day.")
    elif times:
        kind = FIXED
        if len(set(times)) != len(times):
            raise UserError("Two of those times are the same.")
        times = tuple(sorted(times))
        if asked is not None and asked != len(times):
            raise UserError(
                f"That is {len(times)} time{'s' if len(times) != 1 else ''} for {asked} doses a day. "
                "Give a time for each dose, or a minimum gap between them instead."
            )
        per_day = len(times)
    else:
        kind = UNTIMED
        per_day = asked or (base.per_day if base and base.kind == UNTIMED else 1)

    # --- dates: a course, or none ---
    start, end = (base.start, base.end) if base else (None, None)
    if any(_cleared(value) for value in (request.start, request.end, request.days)):
        start = end = None
    elif any(_given(value) for value in (request.start, request.end, request.days)):
        if _given(request.end) and _given(request.days):
            raise UserError("Give an end date or a number of days, not both.")
        start = timeinput.parse_date(request.start, today) if _given(request.start) else (start or today)
        if _given(request.days):
            end = start + timedelta(days=_days(request.days) - 1)  # the last day is a day of taking
        elif _given(request.end):
            end = timeinput.parse_date(request.end, max(today, start))
        elif end is None:
            raise UserError("When does it end? Give an end date or a number of days.")
        if end < today:
            raise UserError(f"That course is already over: it ends {timeinput.format_date(end)}.")
        if end < start:
            raise UserError(
                f"It would end ({timeinput.format_date(end)}) before it starts ({timeinput.format_date(start)})."
            )

    return Plan(name, dose, notes, kind, times, per_day, gap, start, end)


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


def schedule_text(plan: Plan) -> str:
    """ "daily, untimed", "daily at `8:00 pm`", "3× daily, ≥3h apart"."""
    if plan.kind == INTERVAL:
        return f"{plan.per_day}× daily, ≥{gap_text(plan.gap_minutes)} apart"
    if plan.kind == FIXED:
        shown = [_clock(value) for value in plan.times]
        joined = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
        return f"daily at {joined}"
    return "daily, untimed" if plan.per_day == 1 else f"{plan.per_day}× daily, untimed"


def describe(plan: Plan, icon: str = "💊") -> str:
    """A plan on one line, as previews and lists show it. A pill that goes on
    indefinitely shows no dates at all."""
    name = f"**{plan.name}**" + (f" ({plan.dose})" if plan.dose else "")
    parts = [f"{icon} {name}", schedule_text(plan)]
    if plan.notes:
        parts.append(f"*{plan.notes}*")
    if plan.is_course:
        parts.append(timeinput.format_dates(plan.start, plan.end))
    if plan.kind == INTERVAL:
        parts.append(f"first dose at {_clock(plan.times[0])}" if plan.times else "first dose when ready")
    return " · ".join(parts)


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

    def first(plan: Plan) -> str:
        if plan.kind != INTERVAL:
            return ""
        return _clock(plan.times[0]) if plan.times else "when ready"

    found = [
        ("name", old.name, new.name),
        ("dose", old.dose or "none", new.dose or "none"),
        ("notes", old.notes or "none", new.notes or "none"),
        ("schedule", schedule_text(old), schedule_text(new)),
        ("dates", dates(old), dates(new)),
    ]
    if first(old) and first(new):
        found.append(("first dose", first(old), first(new)))
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

