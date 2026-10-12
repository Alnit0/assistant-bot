import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# The timetable: when the bot does things by itself, as rows that are the
# user's to change. (Called "timetable" in the code because core/schedule.py
# is taken: that is how often a thing is done within a day. To the user both
# are "my schedule".)
#
# A schedule is a time of day on the wall clock in a zone, the days of the
# week it applies on, and one or more steps: the handlers it runs, in order.
# Nothing here stores a moment: the next occurrence is worked out each time
# from the local date and time and the zone, so daylight saving never shifts
# one. The engine that books and runs occurrences is core/scheduler.py.
#
# The top half is pure. The bottom half reads and writes the rows (blocking;
# called through database.run).
# ---------------------------------------------------------------------------
ZONE = "Pacific/Auckland"
ALL_DAYS = (0, 1, 2, 3, 4, 5, 6)  # Monday is 0
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SILENT, NOTIFY = "silent", "notify"
ON, PAUSED, REMOVED = "on", "paused", "removed"
FROM_A_TASK, MINE = "default", "mine"
# What becomes of an occurrence that came due while the bot was off: run it
# however late, or skip it once it is more than a number of minutes late
RUN_LATE = "late"
SKIP_AFTER = "skip:"
MINUTE = timedelta(minutes=1)


def skip_after(minutes: int) -> str:
    return f"{SKIP_AFTER}{int(minutes)}"


def skip_limit(rule: str) -> timedelta | None:
    """How late is too late under this rule; None for "run late"."""
    if rule.startswith(SKIP_AFTER) and rule[len(SKIP_AFTER):].isdigit():
        return timedelta(minutes=int(rule[len(SKIP_AFTER):]))
    return None


@dataclass(frozen=True)
class Default:
    """The schedule a handler gets the first time, from the task that owns it.
    After that the row is the user's, unless it is `locked` (the bot's own:
    the backup, the end of the day), which follows the code."""

    name: str
    at: time
    days: tuple[int, ...] = ALL_DAYS
    notify: str = SILENT
    channel: str = "hub"
    missed: str = RUN_LATE
    locked: bool = False


@dataclass(frozen=True)
class Schedule:
    id: int
    user_id: int | None  # None: the bot's own
    name: str
    at: time
    zone: str
    days: tuple[int, ...]
    notify: str
    channel: str
    state: str
    paused_until: date | None  # with PAUSED: the day it is on again; None until told
    missed: str
    origin: str
    default_key: str | None  # the handler it was made for, for one a task supplied
    locked: bool
    steps: tuple[str, ...] = ()  # handler names ("pills.checklist"), in order

    def is_on(self, day: date) -> bool:
        """Whether it runs on this local day as far as its state goes."""
        if self.state == ON:
            return True
        return self.state == PAUSED and self.paused_until is not None and day >= self.paused_until


@dataclass(frozen=True)
class Occurrence:
    local: datetime  # the wall-clock date and time it stands for, with no zone
    moment: datetime  # when that is, UTC

    @property
    def stamp(self) -> str:
        """The local date and time as kept and as used in a run's key."""
        return self.local.strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# Pure: wall-clock times as moments
# ---------------------------------------------------------------------------
def moment_of(day: date, at: time, zone: str = ZONE) -> datetime:
    """The moment the wall clock in `zone` reads `at` on `day`, UTC.

    A time that happens twice (the clocks go back) is the first of the two.
    A time that doesn't exist (the clocks go forward over it) is the moment
    the clocks jump to: the first that does exist after it."""
    tz = ZoneInfo(zone)
    wall = datetime.combine(day, at.replace(tzinfo=None))
    found = wall.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    if found.astimezone(tz).replace(tzinfo=None) == wall:
        return found
    # The wall clock never read this: walk back to where the new offset began
    offset = found.astimezone(tz).utcoffset()
    while (found - MINUTE).astimezone(tz).utcoffset() == offset:
        found -= MINUTE
    return found


def _occurrence(day: date, at: time, zone: str) -> Occurrence:
    return Occurrence(datetime.combine(day, at.replace(tzinfo=None, second=0, microsecond=0)), moment_of(day, at, zone))


def next_occurrence(schedule: Schedule, after: datetime, skip_day: date | None = None) -> Occurrence | None:
    """The first occurrence strictly after `after`: the next day of its days,
    from the day it is on, when the wall clock reads its time. `skip_day` is
    a local day it has already run on, which is passed over (a schedule runs
    once a day). None if it never runs (removed, paused with no end, no days)."""
    if schedule.state == REMOVED or not schedule.days:
        return None
    if schedule.state == PAUSED and schedule.paused_until is None:
        return None
    start = after.astimezone(ZoneInfo(schedule.zone)).date()
    for ahead in range(0, 15):
        day = start + timedelta(days=ahead)
        if day.weekday() not in schedule.days or not schedule.is_on(day) or day == skip_day:
            continue
        found = _occurrence(day, schedule.at, schedule.zone)
        if found.moment > after:
            return found
    return None


def last_occurrence(schedule: Schedule, at_or_before: datetime) -> Occurrence | None:
    """The latest occurrence at or before a moment, looking back two weeks."""
    if schedule.state == REMOVED or not schedule.days:
        return None
    start = at_or_before.astimezone(ZoneInfo(schedule.zone)).date()
    for back in range(0, 15):
        day = start - timedelta(days=back)
        if day.weekday() not in schedule.days or not schedule.is_on(day):
            continue
        found = _occurrence(day, schedule.at, schedule.zone)
        if found.moment <= at_or_before:
            return found
    return None


def between(schedule: Schedule, after: datetime, until: datetime) -> list[Occurrence]:
    """Every occurrence after `after` and at or before `until`, oldest first (at most a month of them)."""
    found: list[Occurrence] = []
    moment = after
    for _ in range(31):
        coming = next_occurrence(schedule, moment)
        if coming is None or coming.moment > until:
            break
        found.append(coming)
        moment = coming.moment
    return found


def run_key(schedule_id: int, stamp: str, step: int) -> str:
    """What makes a run one run: the schedule, the local date and time it
    stands for (not the moment: an hour that happens twice is one run), and
    which of the schedule's steps it is."""
    return f"s{schedule_id}@{stamp}#{step}"


def days_text(days: tuple[int, ...]) -> str:
    """ "every day", "Mon to Fri", "Sat, Sun", "Mon, Wed, Fri"."""
    days = tuple(sorted(set(days)))
    if days == ALL_DAYS:
        return "every day"
    if len(days) >= 3 and days == tuple(range(days[0], days[-1] + 1)):
        return f"{DAY_NAMES[days[0]]} to {DAY_NAMES[days[-1]]}"
    return ", ".join(DAY_NAMES[day] for day in days) or "no day"


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, name, at, zone, days, notify, channel, state, paused_until, missed, origin, default_key, locked"


def _days(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(",") if part.strip().isdigit())


def _schedule(row: tuple, steps: tuple[str, ...]) -> Schedule:
    hour, _, minute = row[3].partition(":")
    return Schedule(
        id=row[0], user_id=row[1], name=row[2], at=time(int(hour), int(minute)), zone=row[4], days=_days(row[5]),
        notify=row[6], channel=row[7], state=row[8], paused_until=date.fromisoformat(row[9]) if row[9] else None,
        missed=row[10], origin=row[11], default_key=row[12], locked=bool(row[13]), steps=steps,
    )


def _stored_days(days) -> str:
    return ",".join(str(day) for day in sorted(set(days)))


def _stored_time(at: time) -> str:
    return f"{at.hour:02d}:{at.minute:02d}"


def db_steps(conn: sqlite3.Connection, schedule_id: int) -> tuple[str, ...]:
    rows = conn.execute("SELECT handler FROM schedule_steps WHERE schedule_id = ? ORDER BY position", (schedule_id,)).fetchall()
    return tuple(row[0] for row in rows)


def db_all(conn: sqlite3.Connection, removed: bool = False) -> list[Schedule]:
    """Every schedule, in the order of the time of day; those removed only if asked for."""
    sql = f"SELECT {_COLUMNS} FROM schedules" + ("" if removed else " WHERE state != ?") + " ORDER BY at, id"
    rows = conn.execute(sql, () if removed else (REMOVED,)).fetchall()
    return [_schedule(row, db_steps(conn, row[0])) for row in rows]


def db_get(conn: sqlite3.Connection, schedule_id: int) -> Schedule | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    return _schedule(row, db_steps(conn, row[0])) if row else None


def db_for_default(conn: sqlite3.Connection, default_key: str) -> Schedule | None:
    """The row a task's default was made into, whatever its state: one that
    was removed is still there, so that it is never made a second time."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM schedules WHERE default_key = ? ORDER BY id LIMIT 1", (default_key,)).fetchone()
    return _schedule(row, db_steps(conn, row[0])) if row else None


def db_add(
    conn: sqlite3.Connection, now: datetime, *, user_id: int | None, name: str, at: time, steps, days=ALL_DAYS, notify: str = SILENT,
    channel: str = "hub", missed: str = RUN_LATE, origin: str = MINE, default_key: str | None = None, locked: bool = False, zone: str = ZONE,
) -> int:
    stamp = now.astimezone(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO schedules (user_id, name, at, zone, days, notify, channel, state, paused_until, missed, origin, default_key, locked, created_at, changed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, name, _stored_time(at), zone, _stored_days(days), notify, channel, ON, missed, origin, default_key, int(locked), stamp, stamp),
    )
    db_set_steps(conn, cursor.lastrowid, steps)
    return cursor.lastrowid


def db_set_steps(conn: sqlite3.Connection, schedule_id: int, steps) -> None:
    conn.execute("DELETE FROM schedule_steps WHERE schedule_id = ?", (schedule_id,))
    conn.executemany(
        "INSERT INTO schedule_steps (schedule_id, position, handler) VALUES (?, ?, ?)",
        [(schedule_id, position, handler) for position, handler in enumerate(steps, start=1)],
    )


def db_update(conn: sqlite3.Connection, schedule_id: int, now: datetime, **changes) -> None:
    """Change some of a schedule's settings: name, at, days, notify, channel,
    state, paused_until, missed. Steps are set with `db_set_steps`."""
    stored = {
        "at": _stored_time, "days": _stored_days,
        "paused_until": lambda day: day.isoformat() if day else None,
    }
    allowed = ("name", "at", "days", "notify", "channel", "state", "paused_until", "missed")
    sets, values = [], []
    for name, value in changes.items():
        if name not in allowed:
            raise ValueError(f"{name} is not a setting of a schedule")
        sets.append(f"{name} = ?")
        values.append(stored[name](value) if name in stored else value)
    if not sets:
        return
    conn.execute(f"UPDATE schedules SET {', '.join(sets)}, changed_at = ? WHERE id = ?", (*values, now.astimezone(timezone.utc).isoformat(), schedule_id))


def as_changed(schedule: Schedule, **changes) -> Schedule:
    """The schedule as it would be with these settings: for saying when it would next run, before anything is saved."""
    return replace(schedule, **changes)
