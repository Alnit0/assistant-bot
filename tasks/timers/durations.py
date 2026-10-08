import re

# ---------------------------------------------------------------------------
# Durations: turning "25m", "1h30" or "2 hours" into seconds, in code.
# Pure functions: no Discord, no database, no clock.
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
    """Seconds for text such as "90s", "25m", "1h30", "1h 30m", "1.5h", "2 hours" or "1:30".

    A bare number is minutes ("25"). A bare number straight after hours is
    minutes ("1h30"), and straight after minutes is seconds ("1m30"). "1:30"
    is hours and minutes; "1:30:00" adds seconds. Raises DurationError.
    """
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
            seconds = parse_duration(" ".join(words[:count]))
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
