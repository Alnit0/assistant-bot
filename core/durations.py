import re

# ---------------------------------------------------------------------------
# Durations: turning "25m", "1h30" or "2 hours" into seconds, in code. Shared
# by every task that reads a length of time (timers, pills, dev).
# Pure functions: no Discord, no database, no clock.
#
# Two ways of reading:
#   the short forms people type      25m, 1h30, 1h 30m, 1.5h, 2 hours, 1:30
#   the way people say them          3 hours apart, 2 and a half hours, an hour
#                                    and a half, half an hour, ninety minutes
# The second is a safety net: where a length comes from Claude it is asked for
# as a whole number (core/actions.py, MINUTES), and this reads what arrives
# as words all the same. Typed words with a label after them (`timer 5m long
# walk`) are only ever read the first way, so no word of a label is taken
# for part of the length.
# ---------------------------------------------------------------------------
MIN_SECONDS = 5
MAX_SECONDS = 24 * 60 * 60

_UNITS = {
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), 3600),
    **dict.fromkeys(("m", "min", "mins", "minute", "minutes"), 60),
    **dict.fromkeys(("s", "sec", "secs", "second", "seconds"), 1),
}
_PART = re.compile(r"(\s*)(\d+(?:\.\d+)?)\s*([a-z]*)")
_CLOCK = re.compile(r"(\d+):(\d{2})(?::(\d{2}))?")


class DurationError(ValueError):
    """The text isn't a duration we understand, or is out of range."""


def _check_range(seconds: float) -> int:
    seconds = round(seconds)
    if seconds < MIN_SECONDS:
        raise DurationError(f"The shortest timer is {MIN_SECONDS} seconds.")
    if seconds > MAX_SECONDS:
        raise DurationError("The longest timer is 24 hours.")
    return seconds


def parse_duration(text: str) -> int:
    """Seconds for a length of time, in its short form or as people say it:
    "90s", "25m", "1h30", "1h 30m", "1.5h", "2 hours", "1:30", and also "3
    hours apart", "2 and a half hours", "an hour and a half".

    A bare number is minutes ("25"). A bare number straight after hours is
    minutes ("1h30"), and straight after minutes is seconds ("1m30"). "1:30"
    is hours and minutes; "1:30:00" adds seconds. Raises DurationError.
    """
    try:
        return _short(text)
    except DurationError as problem:
        said = as_said(text)
        if said == text.strip().lower():
            raise
        try:
            return _short(said)
        except DurationError:
            raise problem  # in the words that were given, not the reworked ones


_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}
_UNIT_WORDS = "|".join(sorted(_UNITS, key=len, reverse=True))
_NUMBER_WORD = re.compile(r"\b(" + "|".join(sorted(_NUMBERS, key=len, reverse=True)) + r")\b(?=\s+(?:and\s+a\s+half\s+)?(?:" + _UNIT_WORDS + r")\b)")
_BEFORE = re.compile(r"^(?:(?:at\s+least|at\s+most|every|for|about|around|roughly|in)\s+)+")
_AFTER = re.compile(r"(?:\s+(?:apart|between\s+(?:doses|each|them)|each\s+time|long|later|or\s+so))+$")
_HALF_OF = re.compile(r"\bhalf\s+an?\s+(" + _UNIT_WORDS + r")\b")
_AND_A_HALF_BEFORE = re.compile(r"(\d+)\s+and\s+a\s+half\s+(" + _UNIT_WORDS + r")\b")
_AND_A_HALF_AFTER = re.compile(r"(\d+)\s+(" + _UNIT_WORDS + r")\s+and\s+a\s+half\b")


def as_said(text: str) -> str:
    """A length as people say it, put into the short form: "an hour and a
    half" -> "1.5 hour", "at least 3 hours apart" -> "3 hours"."""
    said = re.sub(r"\s+", " ", text.strip().lower()).replace(",", " ").strip(" .")
    said = _AFTER.sub("", _BEFORE.sub("", said)).strip()
    said = _HALF_OF.sub(r"0.5 \1", said)
    said = _NUMBER_WORD.sub(lambda found: str(_NUMBERS[found[1]]), said)
    said = _AND_A_HALF_BEFORE.sub(r"\1.5 \2", said)
    said = _AND_A_HALF_AFTER.sub(r"\1.5 \2", said)
    return re.sub(r"\s+and\s+", " ", said)


def _short(text: str) -> int:
    """Seconds for a length in its short form. Raises DurationError."""
    text = text.strip().lower()
    if not text:
        raise DurationError("No duration given.")

    clock = _CLOCK.fullmatch(text)
    if clock:
        hours, minutes, seconds = (int(part or 0) for part in clock.groups())
        if minutes > 59 or seconds > 59:
            raise DurationError(f"“{text}” isn't a valid time.")
        return _check_range(hours * 3600 + minutes * 60 + seconds)

    total = 0.0
    position = 0
    previous_unit = None  # seconds per unit of the part before, to keep them in order
    parts = 0
    while position < len(text):
        part = _PART.match(text, position)
        if part is None:
            raise DurationError(f"I can't read “{text}” as a duration.")
        gap, number, word = part.groups()
        position = part.end()
        parts += 1

        if word:
            unit = _UNITS.get(word)
            if unit is None:
                raise DurationError(f"I can't read “{text}” as a duration.")
        elif previous_unit is None:
            unit = 60  # a number on its own is minutes
            if "." in number or position < len(text):
                raise DurationError(f"I can't read “{text}” as a duration.")
        elif previous_unit > 1 and not gap and "." not in number:
            unit = previous_unit // 60  # "1h30" is minutes, "1m30" is seconds
        else:
            raise DurationError(f"I can't read “{text}” as a duration.")

        if previous_unit is not None and unit >= previous_unit:
            raise DurationError(f"I can't read “{text}” as a duration.")
        total += float(number) * unit
        previous_unit = unit

    if parts == 0:
        raise DurationError(f"I can't read “{text}” as a duration.")
    return _check_range(total)


def split_duration(words: list[str]) -> tuple[int, str]:
    """Split "1h30 laundry" or "2 hours laundry" into (seconds, label).

    The duration is the longest run of words at the start that reads as one.
    Raises DurationError if the words don't start with a duration.
    """
    if not words:
        raise DurationError("No duration given.")
    problem: DurationError | None = None
    for count in range(min(len(words), 6), 0, -1):
        try:
            # The short form only: a word of the label is never part of the length
            seconds = _short(" ".join(words[:count]))
        except DurationError as error:
            # Remember the most specific complaint: the one about the shortest attempt
            problem = error
            continue
        return seconds, " ".join(words[count:])
    raise problem


def format_duration(seconds: float) -> str:
    """A duration for people: "45s", "25m", "1m 30s", "1h 30m"."""
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    # Seconds matter for short timers, and are noise on long ones
    if secs and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts) or "0s"
