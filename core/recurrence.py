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
#
# Any kind but once may also have an end and a pace (the calendar's
# repeating events, `end_fields`): every N weeks for the weekly kinds
# (`every_weeks`, counted from `first`), an end day (`until`, itself
# included), or a number of times (`times`, from `first`). `rrule` writes
# one as an iCalendar RRULE, for Google Calendar.
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
    every_weeks: int = 1  # for WEEKDAYS, WEEKENDS and DAYS: every N weeks from the week of `first`
    until: date | None = None  # the last day it may come round on
    times: int | None = None  # how many times in all, from `first`

    @property
    def ends(self) -> bool:
        return self.kind == ONCE or self.until is not None or self.times is not None


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
    if repeat.until is not None and day > repeat.until:
        return False
    if kind in WEEKLY and repeat.every_weeks > 1 and repeat.first is not None:
        weeks = ((day - timedelta(days=day.weekday())) - (repeat.first - timedelta(days=repeat.first.weekday()))).days // 7
        if weeks % repeat.every_weeks:
            return False
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


WEEKLY = (WEEKDAYS, WEEKENDS, DAYS)


# --- every N months: renewals and expiries (tasks/nudges/expiry.py) -------------------------------------------------
CYCLES = ("yearly", "monthly", "months", "none")


def add_months(day: date, months: int, anchor: int | None = None) -> date:
    """`day` moved on `months` months, on its own date of the month (`anchor`, kept from the first), or
    that month's last day when it has fewer: 31 Jan monthly is 28 or 29 Feb, then 31 Mar; 29 Feb yearly
    is 28 Feb, and 29 Feb again in a leap year."""
    wanted = anchor or day.day
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def cycle_months(word: str | None, every_months: int | None = None) -> int | None:
    """A cycle as months, from the words extraction gave: yearly 12, monthly 1, months N; none, None."""
    said = str(word or "").lower()
    if said == "yearly":
        return 12
    if said == "monthly":
        return 1
    if said == "months":
        return max(1, int(every_months or 1))
    return None


def cycle_text(months: int | None) -> str:
    if months is None:
        return "once"
    if months == 12:
        return "yearly"
    if months == 1:
        return "monthly"
    if months % 12 == 0:
        return f"every {months // 12} years"
    return f"every {months} months"


def dates(repeat: Repeat, start: date, count: int) -> list[date]:
    """Up to `count` days it comes round on from `start` (itself included), its end and its
    number of times kept: the times are counted from `first`, so ones before `start` count."""
    found: list[date] = []
    seen = 0
    day = repeat.first if repeat.times is not None and repeat.first is not None and repeat.first < start else start
    for _ in range(LOOK_AHEAD * 3):
        if len(found) >= count or (repeat.until is not None and day > repeat.until):
            break
        if on_day(repeat, day):
            seen += 1
            if repeat.times is not None and seen > repeat.times:
                break
            if day >= start:
                found.append(day)
        if repeat.kind == ONCE and repeat.first is not None and day >= repeat.first:
            break
        day += timedelta(days=1)
    return found


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


def full_text(repeat: Repeat, today: date) -> str:
    """`text`, with its pace and its end: "every 2 weeks on Mon and Thu", "weekdays, until Fri
    5 Aug", "monthly on the 1st, 6 times"."""
    said = text(repeat, today)
    if repeat.kind in WEEKLY and repeat.every_weeks > 1:
        days_said = {WEEKDAYS: "Mon to Fri", WEEKENDS: "Sat and Sun"}.get(repeat.kind) or _joined([DAY_WORDS[each].capitalize() for each in sorted(repeat.weekdays)])
        said = f"every {repeat.every_weeks} weeks on {days_said}"
    if repeat.until is not None:
        said += f", until {repeat.until:%a} {repeat.until.day} {repeat.until:%b}"
    if repeat.times is not None:
        said += f", {repeat.times} time{'' if repeat.times == 1 else 's'}"
    return said


# --- as an iCalendar RRULE (Google Calendar's recurrence) ---------------------------------------------------------
_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def rrule(repeat: Repeat, until_utc: datetime | None = None) -> str:
    """The repeat as one RRULE line, or "" for a one-off. `until_utc` is the moment its end day
    is over, in UTC (the caller knows the time zone): an RRULE's UNTIL is a moment."""
    kind = repeat.kind
    if kind == ONCE:
        return ""
    if kind == DAILY:
        parts = ["FREQ=DAILY"]
    elif kind == EVERY:
        parts = ["FREQ=DAILY", f"INTERVAL={max(1, repeat.every_days)}"]
    elif kind in WEEKLY:
        chosen = {WEEKDAYS: (0, 1, 2, 3, 4), WEEKENDS: (5, 6)}.get(kind) or tuple(sorted(repeat.weekdays))
        parts = ["FREQ=WEEKLY", *([f"INTERVAL={repeat.every_weeks}"] if repeat.every_weeks > 1 else []), "BYDAY=" + ",".join(_BYDAY[each] for each in chosen)]
    elif kind == MONTHLY:
        wanted = max(1, min(31, repeat.month_day))
        # A date a month lacks is that month's last day, as `on_day` says: the last of 28 to N there is
        parts = ["FREQ=MONTHLY", f"BYMONTHDAY={wanted}"] if wanted <= 28 else ["FREQ=MONTHLY", "BYMONTHDAY=" + ",".join(str(each) for each in range(28, wanted + 1)), "BYSETPOS=-1"]
    elif kind == MONTHLY_NTH:
        parts = ["FREQ=MONTHLY", f"BYDAY={repeat.nth}{_BYDAY[repeat.weekday]}"]
    else:
        return ""
    if repeat.times is not None:
        parts.append(f"COUNT={max(1, repeat.times)}")
    elif until_utc is not None:
        parts.append(f"UNTIL={until_utc:%Y%m%dT%H%M%SZ}")
    return "RRULE:" + ";".join(parts)


def from_rrule(line: str, first: date | None, until: date | None = None) -> Repeat:
    """A repeat from an RRULE this file wrote (or one like it): its kind, pace and end. `until` is the
    end day the caller read from UNTIL in its own time zone. Anything it cannot say is every day."""
    found = dict(part.split("=", 1) for part in line.removeprefix("RRULE:").split(";") if "=" in part)
    freq, interval = found.get("FREQ", "DAILY"), int(found.get("INTERVAL", "1") or 1)
    times = int(found["COUNT"]) if found.get("COUNT") else None
    byday = [each for each in found.get("BYDAY", "").split(",") if each]
    if freq == "DAILY":
        base = Repeat(EVERY, first, every_days=interval) if interval > 1 else Repeat(DAILY, first)
    elif freq == "WEEKLY":
        chosen = tuple(sorted(_BYDAY.index(each[-2:]) for each in byday if each[-2:] in _BYDAY)) or ((first.weekday(),) if first else (0,))
        kind = WEEKDAYS if chosen == (0, 1, 2, 3, 4) else WEEKENDS if chosen == (5, 6) else DAYS
        base = Repeat(kind, first, chosen if kind == DAYS else (), every_weeks=interval)
    elif freq == "MONTHLY" and byday:
        nth, word = int(byday[0][:-2] or 1), byday[0][-2:]
        base = Repeat(MONTHLY_NTH, first, nth=nth, weekday=_BYDAY.index(word) if word in _BYDAY else 0)
    elif freq == "MONTHLY":
        numbers = [int(each) for each in found.get("BYMONTHDAY", "").split(",") if each.lstrip("-").isdigit()]
        base = Repeat(MONTHLY, first, month_day=max(numbers) if numbers else (first.day if first else 1))
    else:
        base = Repeat(DAILY, first)
    return Repeat(base.kind, first, base.weekdays, base.every_days, base.month_day, base.nth, base.weekday, base.every_weeks, until, times)


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
    if repeat.every_weeks > 1:
        kept["every_weeks"] = repeat.every_weeks
    if repeat.until is not None:
        kept["until"] = repeat.until.isoformat()
    if repeat.times is not None:
        kept["times"] = repeat.times
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
        int(kept.get("every_weeks") or 1),
        date.fromisoformat(kept["until"]) if kept.get("until") else None,
        int(kept["times"]) if kept.get("times") else None,
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


def with_end(repeat: Repeat, fields: dict, first: date, until: date | None) -> Repeat:
    """A repeat with the pace and the end from `end_fields` (`until` read by the caller from what was
    said), starting on `first`. Every N weeks is for the weekly kinds only; N times is at least 1."""
    weeks = max(1, int(fields.get("every_weeks") or 1)) if repeat.kind in WEEKLY else 1
    times = fields.get("times")
    times = max(1, int(times)) if times not in (None, "") and str(times).lstrip("-").isdigit() else None
    return Repeat(repeat.kind, first if repeat.kind != ONCE or repeat.first is None else repeat.first, repeat.weekdays, repeat.every_days, repeat.month_day, repeat.nth, repeat.weekday, weeks, until if times is None else None, times)


def end_fields() -> tuple:
    """The fields for a pace and an end, beside `fields()`: only where a task offers them (the calendar)."""
    from core.actions import INTEGER, STRING, Field

    return (
        Field("every_weeks", "Every N weeks, for weekdays, weekends or days (\"every 2 weeks on Monday\" -> 2). Leave out for every week.", INTEGER),
        Field("until", "The last day, exactly as the user said it (\"until 5 August\", \"until the end of the year\"). Never work out a date.", STRING),
        Field("times", "How many times in all, when the user says (\"for 6 weeks\" on one day a week -> 6; \"10 times\" -> 10).", INTEGER),
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
