import sqlite3
from datetime import date, datetime

from core import database
from tasks.calendar.rules import Event

# ---------------------------------------------------------------------------
# The copy of the calendar: each happening from this week's Monday (or yesterday, on a Monday) to two months
# ahead (a title and its times, nothing more), replaced whole on every good
# read, and when the feed was last read and since when it has failed. Every
# row has a user_id.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            key TEXT NOT NULL,
            title TEXT NOT NULL,
            start_at TEXT,
            end_at TEXT,
            first_day TEXT,
            last_day TEXT
        )
        """
    )
    conn.execute("CREATE INDEX calendar_events_user ON calendar_events (user_id)")
    conn.execute(
        """
        CREATE TABLE calendar_reads (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            read_at TEXT,
            tried_at TEXT,
            failing_since TEXT,
            failure TEXT NOT NULL DEFAULT '',
            events INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def add_origins(conn: sqlite3.Connection) -> None:
    """Which calendar each event came from and its id there (the Bot calendar's, to change), and a
    record of each change made, for undo."""
    conn.execute("ALTER TABLE calendar_events ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE calendar_events ADD COLUMN ref TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE calendar_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            ref TEXT NOT NULL,
            title TEXT NOT NULL,
            before_start TEXT,
            before_end TEXT,
            after_start TEXT,
            after_end TEXT,
            at TEXT NOT NULL,
            undone INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def add_series(conn: sqlite3.Connection) -> None:
    """A happening of a repeating event knows its series; a change keeps what undo needs for a series (JSON)."""
    conn.execute("ALTER TABLE calendar_events ADD COLUMN series TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE calendar_changes ADD COLUMN detail TEXT")


MIGRATIONS = [create_tables, add_origins, add_series]
ADDED, MOVED, DELETED = "added", "moved", "deleted"
# A repeating event: one happening cancelled, the series changed (its times, its end, split in two), or the
# whole series deleted (undo makes it again from what `detail` kept)
CANCELLED_ONE, SERIES_CHANGED, SERIES_DELETED = "cancelled_one", "series_changed", "series_deleted"


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def db_events(conn: sqlite3.Connection, user_id: int) -> list[Event]:
    rows = conn.execute("SELECT key, title, start_at, end_at, first_day, last_day, origin, ref, series FROM calendar_events WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    return [Event(key, title, _when(start), _when(end), _day(first), _day(last), origin, ref, series) for key, title, start, end, first, last, origin, ref, series in rows]


def _row(user_id: int, each: Event) -> tuple:
    return (user_id, each.key, each.title, each.start.isoformat() if each.start else None, each.end.isoformat() if each.end else None,
            each.first_day.isoformat() if each.first_day else None, each.last_day.isoformat() if each.last_day else None, each.origin, each.ref, each.series)


_INSERT = "INSERT INTO calendar_events (user_id, key, title, start_at, end_at, first_day, last_day, origin, ref, series) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"


def db_keep_from(conn: sqlite3.Connection, user_id: int, origin: str, events: list[Event]) -> None:
    """One calendar read well: its part of the copy is these events. The link's part takes the place of
    rows from before calendars were told apart (no origin)."""
    gone = (origin, "") if origin == "link" else (origin, origin)
    conn.execute("DELETE FROM calendar_events WHERE user_id = ? AND origin IN (?, ?)", (user_id, *gone))
    conn.executemany(_INSERT, [_row(user_id, each) for each in events])


def db_keep_only(conn: sqlite3.Connection, user_id: int, origins: list[str]) -> None:
    """A calendar no longer read leaves the copy."""
    kept = [*origins, *([""] if "link" in origins else [])]
    marks = ", ".join("?" for _ in kept) or "''"
    conn.execute(f"DELETE FROM calendar_events WHERE user_id = ? AND origin NOT IN ({marks})", (user_id, *kept))


def db_put(conn: sqlite3.Connection, user_id: int, event: Event) -> None:
    """One of the bot's own events into the copy at once (added or moved), in place of what it was."""
    conn.execute("DELETE FROM calendar_events WHERE user_id = ? AND origin = ? AND ref = ?", (user_id, event.origin, event.ref))
    conn.execute(_INSERT, _row(user_id, event))


def db_drop(conn: sqlite3.Connection, user_id: int, origin: str, ref: str) -> None:
    conn.execute("DELETE FROM calendar_events WHERE user_id = ? AND origin = ? AND ref = ?", (user_id, origin, ref))


def db_change(conn: sqlite3.Connection, user_id: int, kind: str, ref: str, title: str, before: tuple, after: tuple, now: datetime, detail: dict | None = None) -> None:
    """A change made to the Bot calendar, kept for undo: what it was and what it became (and for a
    series, what undo needs to put it back, as JSON)."""
    import json

    iso = lambda moment: moment.isoformat() if moment else None  # noqa: E731
    conn.execute(
        "INSERT INTO calendar_changes (user_id, kind, ref, title, before_start, before_end, after_start, after_end, at, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, ref, title, iso(before[0]), iso(before[1]), iso(after[0]), iso(after[1]), now.isoformat(), json.dumps(detail) if detail is not None else None),
    )


def db_last_change(conn: sqlite3.Connection, user_id: int) -> tuple | None:
    """(id, kind, ref, title, before (start, end), after (start, end), detail) of the last change not undone."""
    import json

    row = conn.execute(
        "SELECT id, kind, ref, title, before_start, before_end, after_start, after_end, detail FROM calendar_changes WHERE user_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    return (row[0], row[1], row[2], row[3], (_when(row[4]), _when(row[5])), (_when(row[6]), _when(row[7])), json.loads(row[8]) if row[8] else {}) if row else None


def db_undone(conn: sqlite3.Connection, change_id: int) -> None:
    conn.execute("UPDATE calendar_changes SET undone = 1 WHERE id = ?", (change_id,))


def db_read_ok(conn: sqlite3.Connection, user_id: int, now: datetime) -> None:
    """Every calendar was read: when, and how many events the copy holds."""
    count = conn.execute("SELECT COUNT(*) FROM calendar_events WHERE user_id = ?", (user_id,)).fetchone()[0]
    db_counted(conn, user_id, count, now)


def db_keep(conn: sqlite3.Connection, user_id: int, events: list[Event], now: datetime) -> None:
    """A good read of the link alone: the copy is these events, in place of the ones before."""
    conn.execute("DELETE FROM calendar_events WHERE user_id = ?", (user_id,))
    conn.executemany(_INSERT, [_row(user_id, each) for each in events])
    db_counted(conn, user_id, len(events), now)


def db_counted(conn: sqlite3.Connection, user_id: int, count: int, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO calendar_reads (user_id, read_at, tried_at, failing_since, failure, events) VALUES (?, ?, ?, NULL, '', ?)
        ON CONFLICT(user_id) DO UPDATE SET read_at = excluded.read_at, tried_at = excluded.tried_at, failing_since = NULL, failure = '', events = excluded.events
        """,
        (user_id, now.isoformat(), now.isoformat(), count),
    )


def db_failed(conn: sqlite3.Connection, user_id: int, why: str, now: datetime) -> None:
    """A read that failed: the copy stays as it was; since when it has failed is kept."""
    conn.execute(
        """
        INSERT INTO calendar_reads (user_id, read_at, tried_at, failing_since, failure, events) VALUES (?, NULL, ?, ?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET tried_at = excluded.tried_at, failure = excluded.failure,
            failing_since = COALESCE(calendar_reads.failing_since, excluded.failing_since)
        """,
        (user_id, now.isoformat(), now.isoformat(), why),
    )


def db_read(conn: sqlite3.Connection, user_id: int) -> tuple[datetime | None, datetime | None, str, int] | None:
    """(last good read, failing since, why, how many events were kept), or None if never tried."""
    row = conn.execute("SELECT read_at, failing_since, failure, events FROM calendar_reads WHERE user_id = ?", (user_id,)).fetchone()
    return (_when(row[0]), _when(row[1]), row[2], row[3]) if row else None


async def events(user_id: int) -> list[Event]:
    """Every calendar's events as one, each happening once (rules.merged)."""
    from tasks.calendar import rules

    return rules.merged(await database.run(db_events, user_id))
