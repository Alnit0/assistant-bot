import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.errors import UserError

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The clock: the one place the rest of the code asks what time it is.
#
# Normally that is the real time. On the dev database (`python main.py --dev`)
# the clock can be moved ahead with `dev clock`, so a day of reminders can be
# tested in a few minutes: now() is then the real time plus an offset, and it
# goes on ticking from there. Everything time-based reads now() (the
# scheduler, the day boundary, due times); only what records real events
# (log lines, message_log, the instance lock, dev mode's own expiry) reads
# real_now().
#
# The clock only ever moves forward; reset() is the one way back. It can't be
# moved at all on the live database, so real history never gets a made-up time.
# The offset is kept in a file beside the dev database, so the records made
# under it still make sense after a restart.
#
# No imports from the rest of core/ (config.py reads this), and no time zones:
# moments here are UTC.
# ---------------------------------------------------------------------------
_offset = timedelta(0)
_shiftable = False
_store: Path | None = None
# Each move made since the start, as (from, to) on the moved clock: time that
# never happened, which the scheduler doesn't count as a job being late
_jumps: list[tuple[datetime, datetime]] = []


def real_now() -> datetime:
    """The real time, whatever the dev clock says. UTC."""
    return datetime.now(timezone.utc)


def now() -> datetime:
    """The time as the bot sees it. UTC."""
    return real_now() + _offset


def offset() -> timedelta:
    """How far ahead of the real time the clock is."""
    return _offset


def is_shifted() -> bool:
    return bool(_offset)


def shiftable() -> bool:
    """Whether the clock may be moved: only on the dev database."""
    return _shiftable


# ---------------------------------------------------------------------------
# Moving it
# ---------------------------------------------------------------------------
def configure(shiftable: bool, store: Path | None = None) -> None:
    """Say whether the clock may be moved and where its offset is kept, and
    pick up an offset left by the last run. Called once, by config.py."""
    global _shiftable, _store, _offset
    _shiftable, _store, _offset = shiftable, store, timedelta(0)
    _jumps.clear()
    if not shiftable or store is None or not store.exists():
        return
    try:
        _offset = timedelta(seconds=max(0.0, float(json.loads(store.read_text(encoding="utf-8"))["offset_seconds"])))
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("Could not read the dev clock from %s: %s", store, error)


def _save() -> None:
    if _store is None:
        return
    try:
        if _offset:
            _store.write_text(json.dumps({"offset_seconds": _offset.total_seconds()}), encoding="utf-8")
        else:
            _store.unlink(missing_ok=True)
    except OSError as error:
        log.warning("Could not save the dev clock to %s: %s", _store, error)


def advance(by: timedelta) -> datetime:
    """Move the clock ahead by `by`. Returns the new time."""
    global _offset
    if not _shiftable:
        raise UserError(
            "The clock can only be moved on the dev database, so real history is never touched. "
            "Stop the bot and start it with `python main.py --dev`."
        )
    if by <= timedelta(0):
        raise UserError("The clock only moves forward. `dev clock reset` goes back to the real time.")
    before = now()
    _offset += by
    _jumps.append((before, before + by))
    _save()
    return now()


def advance_to(moment: datetime) -> datetime:
    """Move the clock ahead to `moment`, which must be later than now."""
    return advance(moment - now())


def reset() -> None:
    """Back to the real time: the only move backwards."""
    global _offset
    _offset = timedelta(0)
    _jumps.clear()
    _save()


def skipped_between(start: datetime, end: datetime) -> float:
    """Seconds between two moments that the clock jumped over: time nobody
    could have acted in."""
    skipped = 0.0
    for jump_from, jump_to in _jumps:
        overlap = (min(end, jump_to) - max(start, jump_from)).total_seconds()
        if overlap > 0:
            skipped += overlap
    return skipped
