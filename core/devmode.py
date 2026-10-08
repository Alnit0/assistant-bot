import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from core.config import REACTION_DEBOUNCE_SECONDS
from core.discord_utils import log_simple
from core.errors import UserError

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Dev mode: a switch for testing that shortens the waits and says more in
# #bot-log. This file is only the state and the values the rest of the code
# reads; the words, the panel and the tools are in tasks/dev/.
#
# Held in memory on purpose: a restart always comes back with dev mode off,
# so a forgotten test setting can't outlive the session it was meant for.
# ---------------------------------------------------------------------------
DEFAULT_EXPIRY_SECONDS = 60 * 60
MAX_DEBOUNCE_SECONDS = 600
MAX_SPEED = 3600


@dataclass(frozen=True)
class DevSettings:
    debounce_s: float  # quiet time before reactions are acted on
    speed: float  # timers and Pomodoro run this many times faster
    verbose: bool  # debug cards in #bot-log
    ignore_quiet_hours: bool  # for the notifier, when there is one
    cleanup: bool = True  # messages are tidied away by themselves (core/lifecycle.py)


DEFAULTS = DevSettings(debounce_s=2.0, speed=1.0, verbose=True, ignore_quiet_hours=True, cleanup=True)
NORMAL = DevSettings(
    debounce_s=REACTION_DEBOUNCE_SECONDS, speed=1.0, verbose=False, ignore_quiet_hours=False, cleanup=True
)

enabled = False
settings = DEFAULTS
expires_at: datetime | None = None  # UTC


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# What the rest of the code reads. Each gives the normal value when dev mode is off.
# ---------------------------------------------------------------------------
def current() -> DevSettings:
    return settings if enabled else NORMAL


def reaction_debounce() -> float:
    return current().debounce_s


def speed() -> float:
    return current().speed


def real_seconds(nominal: float) -> float:
    """How long a clock set for `nominal` seconds really runs."""
    return nominal / speed()


def nominal_seconds(real: float) -> float:
    """What `real` seconds left on a clock are worth at normal speed."""
    return real * speed()


def is_verbose() -> bool:
    return current().verbose


def quiet_hours_ignored() -> bool:
    return current().ignore_quiet_hours


def cleanup_enabled() -> bool:
    """False while `dev cleanup off` is in force: nothing is deleted automatically."""
    return current().cleanup


# ---------------------------------------------------------------------------
# Switching it on and off, and changing settings
# ---------------------------------------------------------------------------
def enable(now: datetime | None = None) -> None:
    """Switch dev mode on with the dev defaults, to expire in an hour."""
    global enabled, settings, expires_at
    enabled = True
    settings = DEFAULTS
    expires_at = (now or _now()) + timedelta(seconds=DEFAULT_EXPIRY_SECONDS)


def reset(now: datetime | None = None) -> None:
    """Back to the dev defaults, with a fresh hour. Dev mode stays on."""
    enable(now)


def disable() -> None:
    global enabled, settings, expires_at
    enabled = False
    settings = DEFAULTS
    expires_at = None


def _change(**values) -> None:
    global settings
    settings = replace(settings, **values)


def set_debounce(seconds: float) -> None:
    if not 0 <= seconds <= MAX_DEBOUNCE_SECONDS:
        raise UserError(f"The debounce must be from 0 to {MAX_DEBOUNCE_SECONDS} seconds.")
    _change(debounce_s=float(seconds))


def set_speed(multiplier: float) -> None:
    if not 0 < multiplier <= MAX_SPEED:
        raise UserError(f"The speed must be more than 0 and at most {MAX_SPEED}.")
    _change(speed=float(multiplier))


def set_verbose(on: bool) -> None:
    _change(verbose=on)


def set_ignore_quiet_hours(ignore: bool) -> None:
    _change(ignore_quiet_hours=ignore)


def set_cleanup(on: bool) -> None:
    _change(cleanup=on)


def set_expiry(seconds: float, now: datetime | None = None) -> None:
    """Dev mode ends this long from now."""
    global expires_at
    expires_at = (now or _now()) + timedelta(seconds=seconds)


def extend(seconds: float) -> None:
    """Push the expiry back."""
    global expires_at
    expires_at = (expires_at or _now()) + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Reading what was typed after a setting word
# ---------------------------------------------------------------------------
def parse_number(words: list[str], usage: str) -> float:
    """The one number after a word such as "dev speed": "60", "2.5", "2s" or "60x"."""
    try:
        if len(words) != 1:
            raise ValueError
        return float(words[0].lower().removesuffix("s").removesuffix("x"))
    except ValueError:
        raise UserError(f"Usage: `{usage}`.")


def parse_on_off(words: list[str], usage: str) -> bool:
    """True for "on", False for "off"; anything else is a mistake."""
    word = words[0].lower() if len(words) == 1 else ""
    if word not in ("on", "off"):
        raise UserError(f"Usage: `{usage}`.")
    return word == "on"


# ---------------------------------------------------------------------------
# Debug lines for #bot-log
# ---------------------------------------------------------------------------
async def debug(title: str, lines: list[str]) -> None:
    """Post a debug card to #bot-log, if verbose is on. Otherwise does nothing."""
    if not is_verbose():
        return
    log.info("Dev: %s | %s", title, " | ".join(lines))
    await log_simple(f"🛠️ {title}", "\n".join(lines))


# ---------------------------------------------------------------------------
# Things `dev run <name>` can run. Whatever owns the routine registers it; a name
# listed here with nothing registered is a feature that isn't built yet.
# ---------------------------------------------------------------------------
ROUTINE_NAMES = ("backup", "sweep", "summary")

_routines: dict[str, Callable[[], Awaitable[None]]] = {}


def register_routine(name: str, routine: Callable[[], Awaitable[None]]) -> None:
    _routines[name] = routine


async def run_routine(name: str) -> None:
    if name not in ROUTINE_NAMES:
        raise UserError(f"I don't know “{name}”. Try: {', '.join(ROUTINE_NAMES)}.")
    routine = _routines.get(name)
    if routine is None:
        raise UserError(f"There is nothing to run for “{name}” yet: it isn't built.")
    await routine()
