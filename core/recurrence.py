import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from core import day as days

# ---------------------------------------------------------------------------
# The one repeat engine: when something comes round again. Reminders and
# personal routines use it (and to-dos later); a task keeps a `Repeat` with
# its record and asks this file whether it is on a day, when it is next due,
# and how to say it.
#
#   once         one day (`first`)
#   daily        every day
#   weekdays     Monday to Friday
#   weekends     Saturday and Sunday
#   days         chosen days of the week (`weekdays`, Monday 0)
#   every        every N days from a first day (`every_days`, `first`)
#   monthly      on a date each month (`month_day`); a date a month lacks
#                (the 31st in April) is that month's last day
#   monthly_nth  on the Nth weekday of the month (`nth` 1 to 4, or -1 for
#                the last; `weekday`): the first Monday, the last Friday
#
# Times are local and worked out a day at a time, so daylight saving never
# moves one ("9:00 am" stays 9:00 am). Claude hands over the fields as they
# were said (`from_fields`); this file checks them and does every sum. Pure:
# no Discord, no database.
# ---------------------------------------------------------------------------
ONCE, DAILY, WEEKDAYS, WEEKENDS, DAYS, EVERY, MONTHLY, MONTHLY_NTH = "once", "daily", "weekdays", "weekends", "days", "every", "monthly", "monthly_nth"
KINDS = (ONCE, DAILY, WEEKDAYS, WEEKENDS, DAYS, EVERY, MONTHLY, MONTHLY_NTH)
DAY_WORDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NTH_WORDS = ("first", "second", "third", "fourth", "last")
LOOK_AHEAD = 400  # days searched for the next one: a year and a bit covers every kind


@dataclass(frozen=True)
class Repeat:
    kind: str = DAILY
    first: date | None = None  # the day of a one-off; the first day of "every N days"
    weekdays: tuple[int, ...] = ()  # for DAYS: Monday 0
    every_days: int = 1  # for EVERY
    month_day: int = 1  # for MONTHLY: 1 to 31
    nth: int = 1  # for MONTHLY_NTH: 1 to 4, or -1 for the last
    weekday: int = 0  # for MONTHLY_NTH: Monday 0


EVERY_DAY = Repeat(DAILY)


def last_day(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def on_day(repeat: Repeat, day: date) -> bool:
    """Whether it comes round on a day."""
    kind = repeat.kind
    if kind == ONCE:
        return repeat.first == day
    if repeat.first is not None and day < repeat.first and kind != EVERY:
        return False  # not before it was set to start
    if kind == DAILY:
        return True
    if kind == WEEKDAYS:
        return day.weekday() < 5
    if kind == WEEKENDS:
        return day.weekday() >= 5
    if kind == DAYS:
        return day.weekday() in repeat.weekdays
    if kind == EVERY:
        start = repeat.first or day
        return day >= start and (day - start).days % max(1, repeat.every_days) == 0
    if kind == MONTHLY:
        return day.day == min(max(1, repeat.month_day), last_day(day))
    if kind == MONTHLY_NTH:
        if day.weekday() != repeat.weekday:
            return False
        if repeat.nth == -1:
            return day.day + 7 > last_day(day)
        return (day.day - 1) // 7 + 1 == repeat.nth
    return False


def next_day(repeat: Repeat, start: date) -> date | None:
    """The first day from `start` (itself included) it comes round on, or None."""
    for offset in range(LOOK_AHEAD):
        candidate = start + timedelta(days=offset)
        if repeat.kind == ONCE and repeat.first is not None and candidate > repeat.first:
            return None
        if on_day(repeat, candidate):
            return candidate
    return None


def next_due(repeat: Repeat, at: time, after: datetime) -> datetime | None:
    """The first moment it is due strictly after `after`, at local time `at`, or None
    (a one-off gone by). A day at a time in local time: daylight saving never moves it."""
    day = days.day_of(after)
    for offset in range(LOOK_AHEAD):
        candidate = day + timedelta(days=offset)
        if repeat.kind == ONCE and repeat.first is not None and candidate > repeat.first:
            return None
        if on_day(repeat, candidate):
            moment = days.at(candidate, at)
            if moment > after:
                return moment
    return None


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _joined(names: list[str]) -> str:
    return " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " and " + names[-1]


def text(repeat: Repeat, today: date) -> str:
    """When it comes round, in words: "today", "Fri 16 Oct", "every day", "weekdays",
    "weekends", "every Mon and Thu", "every 3 days", "monthly on the 15th",
    "monthly on the first Monday"."""
    kind = repeat.kind
    if kind == ONCE:
        if repeat.first == today:
            return "today"
        if repeat.first == today + timedelta(days=1):
            return "tomorrow"
        return f"{repeat.first:%a} {repeat.first.day} {repeat.first:%b}" if repeat.first else "once"
    if kind == DAILY:
        return "every day"
    if kind == WEEKDAYS:
        return "weekdays"
    if kind == WEEKENDS:
        return "weekends"
    if kind == DAYS:
        return "every " + _joined([DAY_WORDS[each].capitalize() for each in sorted(repeat.weekdays)])
    if kind == EVERY:
        return f"every {repeat.every_days} days"
    if kind == MONTHLY:
        return f"monthly on the {_ordinal(repeat.month_day)}"
    if kind == MONTHLY_NTH:
        nth = "last" if repeat.nth == -1 else NTH_WORDS[max(1, min(4, repeat.nth)) - 1]
        return f"monthly on the {nth} {calendar.day_name[repeat.weekday]}"
    return kind


# --- kept with a record ---------------------------------------------------------------------------------------
def to_dict(repeat: Repeat) -> dict:
    """What a store keeps (as JSON): only what this kind uses."""
    kept: dict = {"kind": repeat.kind}
    if repeat.first is not None:
        kept["first"] = repeat.first.isoformat()
    if repeat.kind == DAYS:
        kept["weekdays"] = list(repeat.weekdays)
    if repeat.kind == EVERY:
        kept["every_days"] = repeat.every_days
    if repeat.kind == MONTHLY:
        kept["month_day"] = repeat.month_day
    if repeat.kind == MONTHLY_NTH:
        kept["nth"], kept["weekday"] = repeat.nth, repeat.weekday
    return kept


def from_dict(kept: dict | None) -> Repeat:
    if not kept:
        return EVERY_DAY
    return Repeat(
        kept.get("kind") if kept.get("kind") in KINDS else DAILY,
        date.fromisoformat(kept["first"]) if kept.get("first") else None,
        tuple(int(each) for each in kept.get("weekdays") or ()),
        int(kept.get("every_days") or 1),
        int(kept.get("month_day") or 1),
        int(kept.get("nth") or 1),
        int(kept.get("weekday") or 0),
    )


# --- from what Claude hands over --------------------------------------------------------------------------------
def day_numbers(words) -> tuple[int, ...]:
    """Days of the week from their names ("mon", "Thursday"), Monday 0, in order."""
    return tuple(sorted({DAY_WORDS.index(str(each).lower()[:3]) for each in words or [] if str(each).lower()[:3] in DAY_WORDS}))


def from_fields(fields: dict, was: Repeat | None = None, first: date | None = None) -> Repeat:
    """A repeat from the fields extraction filled in (`FIELD_NAMES`), on top of what it
    was. Checked here: chosen days with none named is every day, every N days is
    at least 1, a date of the month is 1 to 31, the Nth weekday is first to fourth or last."""
    was = was or EVERY_DAY
    kind = str(fields.get("repeat") or was.kind)
    kind = kind if kind in KINDS else was.kind
    weekdays = day_numbers(fields.get("weekdays")) or (was.weekdays if kind == was.kind else ())
    every_days = max(1, int(fields.get("every_days") or (was.every_days if kind == was.kind else 1) or 1))
    month_day = int(fields.get("month_day") or (was.month_day if kind == was.kind else 1) or 1)
    month_day = max(1, min(31, month_day))
    nth_word = str(fields.get("nth") or "").lower()
    nth = (-1 if nth_word == "last" else NTH_WORDS.index(nth_word) + 1) if nth_word in NTH_WORDS else (was.nth if kind == was.kind else 1)
    named = day_numbers([fields.get("weekday")] if fields.get("weekday") else [])
    weekday = named[0] if named else (was.weekday if kind == was.kind else 0)
    if kind == DAYS and not weekdays:
        kind = DAILY
    if kind == DAYS and weekdays == (0, 1, 2, 3, 4):
        kind = WEEKDAYS
    if kind == DAYS and weekdays == (5, 6):
        kind = WEEKENDS
    start = first if first is not None else was.first
    return Repeat(kind, start if kind in (ONCE, EVERY) else None, weekdays if kind == DAYS else (), every_days, month_day, nth, weekday)


FIELD_NAMES = ("repeat", "weekdays", "every_days", "month_day", "nth", "weekday")
REPEAT_HELP = (
    "once (one day), daily (every day), weekdays (Monday to Friday), weekends (Saturday and Sunday), "
    "days (chosen days of the week: fill weekdays), every (every N days: fill every_days), "
    "monthly (on a date each month: fill month_day), monthly_nth (the first Monday and the like: fill nth and weekday)."
)


def fields() -> tuple:
    """The fields extraction fills in for a repeat, as `core.actions.Field`s."""
    from core.actions import INTEGER, LIST, STRING, Field  # here, so the engine above stays free of the contract

    field_type, list_type, integer_type = STRING, LIST, INTEGER
    return (
        Field("repeat", REPEAT_HELP + " Leave out when the user said nothing about how often.", field_type, choices=KINDS),
        Field("weekdays", "For days: the days of the week named (\"every Monday and Thursday\" -> mon, thu).", list_type, choices=DAY_WORDS),
        Field("every_days", "For every: N, as in every N days.", integer_type),
        Field("month_day", "For monthly: the date of the month, a number (\"on the 15th\" -> 15).", integer_type),
        Field("nth", "For monthly_nth: which one (\"the first Monday\" -> first; \"the last Friday\" -> last).", field_type, choices=NTH_WORDS),
        Field("weekday", "For monthly_nth: the day of the week (\"the first Monday\" -> mon).", field_type, choices=DAY_WORDS),
    )
