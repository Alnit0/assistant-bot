from datetime import datetime, timedelta

from core import scheduler, timeinput
from core.config import TIMEZONE
from core.errors import UserError
from tasks.timers.durations import DurationError, format_duration, parse_duration

# ---------------------------------------------------------------------------
# What was typed after `dev clock`, and how the clock is described. Pure: the
# clock itself is core/clock.py, and the word is in tasks/dev/__init__.py.
# ---------------------------------------------------------------------------
USAGE = "dev clock <time> | +<duration> | reset"
RESET = "reset"


def target(words: list[str], now: datetime) -> datetime | None:
    """Where `dev clock <words>` moves the clock to, or None for "reset".

    A time means the next moment the NZ clock reads it, so the clock only ever
    moves forward: `dev clock 6am` at 3pm is 6am tomorrow, by way of midnight.
    `+2h` is that much later than now. Raises UserError for anything else,
    including a time that could be morning or evening.
    """
    text = " ".join(words).strip().lower()
    if not text:
        raise UserError(f"Usage: `{USAGE}`.")
    if text == RESET:
        return None
    if text.startswith("+"):
        try:
            return now + timedelta(seconds=parse_duration(text[1:]))
        except DurationError as error:
            raise UserError(f"{error} Usage: `dev clock +<duration>`, e.g. `dev clock +2h`.")
    return scheduler.next_run(timeinput.parse_time(text), now)


def describe(now: datetime, ahead: timedelta) -> str:
    """The bot's time in words: "Sat 10 Oct, 6:00 am (14h 2m ahead)", or that it is the real time."""
    local = now.astimezone(TIMEZONE)
    when = f"{local:%a} {local.day} {local:%b}, {timeinput.format_time(local.time())}"
    if not ahead:
        return f"{when} (the real time)"
    # To the second: a move is measured an instant after it was worked out
    return f"{when} ({format_duration(round(ahead.total_seconds()))} ahead)"
