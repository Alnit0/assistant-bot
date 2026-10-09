import re
from datetime import datetime, time

from core import day
from core.config import TIMEZONE
from core.errors import UserError

# ---------------------------------------------------------------------------
# Times the user types, and how times are shown. Pure: no clock, no Discord.
#
# Read:   8pm, 8 pm, 8:30am, 8.30 am      12-hour
#         20:00, 20.00, 08:30, 2030       24-hour
#         noon, midday, midnight          words
# A time that could be morning or evening ("8", "8:30") is never guessed:
# parse_time raises AmbiguousTime, which carries both readings so the caller
# can ask "8am or 8pm?".
#
# Shown:  always 12-hour, "8:30 am", whatever was typed.
#
# Claude works out which words are the time; this works out what time it is.
# ---------------------------------------------------------------------------
_WORDS = {"noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0)}

_TWELVE_HOUR = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\.?")
_WITH_MINUTES = re.compile(r"(\d{1,2})[:.](\d{2})")
_DIGITS = re.compile(r"\d{1,4}")

EXAMPLES = "Try `8pm`, `8:30 am`, `20:00` or `noon`."


class AmbiguousTime(UserError):
    """A time that could be morning or evening. `options` holds both readings,
    morning first; the message is the question to ask."""

    def __init__(self, options: tuple[time, time]):
        self.options = options
        super().__init__(f"{_short(options[0])} or {_short(options[1])}?")


def _short(value: time) -> str:
    """A time as it is asked about: "8am", or "8:30 am" when there are minutes."""
    return format_time(value).replace(":00 ", "") if value.minute == 0 else format_time(value)


def _unreadable(text: str) -> UserError:
    return UserError(f"I can't read “{text}” as a time. {EXAMPLES}")


def _time(text: str, hour: int, minute: int) -> time:
    if hour > 23 or minute > 59:
        raise _unreadable(text)
    return time(hour, minute)


def _either(text: str, hour: int, minute: int) -> AmbiguousTime:
    """Both readings of a 12-hour time with no am or pm."""
    morning = _time(text, hour % 12, minute)
    return AmbiguousTime((morning, morning.replace(hour=morning.hour + 12)))


def parse_time(text: str) -> time:
    """The time of day in `text`.

    Raises AmbiguousTime if it could be morning or evening, and UserError if
    it isn't a time at all.
    """
    typed = text.strip()
    value = re.sub(r"\s+", " ", typed.lower()).removeprefix("at ").strip()
    if value in _WORDS:
        return _WORDS[value]

    if match := _TWELVE_HOUR.fullmatch(value):
        hour, minute = int(match[1]), int(match[2] or 0)
        if not 1 <= hour <= 12:
            raise _unreadable(typed)
        return _time(typed, hour % 12 + (12 if match[3] == "p" else 0), minute)

    if match := _WITH_MINUTES.fullmatch(value):
        hour, minute = int(match[1]), int(match[2])
        # "08:30", "0:15" and "20:00" can only be the 24-hour clock; "8:30" can't be told
        if match[1].startswith("0") or hour == 0 or hour > 12:
            return _time(typed, hour, minute)
        _time(typed, hour, minute)  # refuse 8:75 before asking which 8
        raise _either(typed, hour, minute)

    if _DIGITS.fullmatch(value):
        if len(value) == 4:  # 2030, 0830
            return _time(typed, int(value[:2]), int(value[2:]))
        if len(value) == 3:  # 830: 8:30, morning or evening
            _time(typed, int(value[0]), int(value[1:]))
            raise _either(typed, int(value[0]), int(value[1:]))
        hour = int(value)
        if value.startswith("0") or hour > 12:  # 0, 08, 20
            return _time(typed, hour, 0)
        raise _either(typed, hour, 0)

    raise _unreadable(typed)


# ---------------------------------------------------------------------------
# Showing times
# ---------------------------------------------------------------------------
def format_time(value: time) -> str:
    """A time of day as it is always shown: "8:30 am", "12:00 pm"."""
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'am' if value.hour < 12 else 'pm'}"


def format_moment(moment: datetime) -> str:
    """What the NZ clock read at a moment, as it is always shown."""
    return format_time(moment.astimezone(TIMEZONE).time())


# ---------------------------------------------------------------------------
# A time given for something that has already happened ("taken at 9")
# ---------------------------------------------------------------------------
def check_actual(moment: datetime, now: datetime, not_before: datetime | None = None) -> None:
    """Refuse a moment that can't be when something was done today: raises
    UserError with a short reason, and nothing should be changed.

    It must be today and not in the future. `not_before` is when the one
    before it was done, for things that stay in order.
    """
    if day.day_of(moment) != day.day_of(now):
        raise UserError("That time isn't today.")
    if moment > now:
        raise UserError(f"{format_moment(moment)} hasn't happened yet: it's {format_moment(now)} now.")
    if not_before is not None and moment < not_before:
        raise UserError(
            f"{format_moment(moment)} is before the previous one, at {format_moment(not_before)}."
        )


def actual_moment(text: str, now: datetime, not_before: datetime | None = None) -> datetime:
    """The moment today that the typed time means, checked with check_actual. UTC.

    A time that could be morning or evening is taken as the one reading that
    passes the checks, if only one does ("at 9", said at 2pm, can only be
    9 am): that is not a guess. If both could be meant AmbiguousTime is
    raised, and if neither can, the reason the morning one can't.
    """
    today = day.day_of(now)
    try:
        moment = day.at(today, parse_time(text))
    except AmbiguousTime as unsure:
        possible, refusal = [], None
        for option in unsure.options:
            try:
                check_actual(day.at(today, option), now, not_before)
            except UserError as error:
                refusal = refusal or error
            else:
                possible.append(day.at(today, option))
        if len(possible) == 1:
            return possible[0]
        raise unsure if possible else refusal
    check_actual(moment, now, not_before)
    return moment
