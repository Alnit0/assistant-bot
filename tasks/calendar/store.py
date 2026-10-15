import sqlite3
from datetime import date, datetime

from core import database
from tasks.calendar.rules import Event

# ---------------------------------------------------------------------------
# The copy of the calendar: each happening from yesterday to two months
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


MIGRATIONS = [create_tables]


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def db_events(conn: sqlite3.Connection, user_id: int) -> list[Event]:
    rows = conn.execute("SELECT key, title, start_at, end_at, first_day, last_day FROM calendar_events WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    return [Event(key, title, _when(start), _when(end), _day(first), _day(last)) for key, title, start, end, first, last in rows]


def db_keep(conn: sqlite3.Connection, user_id: int, events: list[Event], now: datetime) -> None:
    """A good read: the copy is these events, in place of the ones before."""
    conn.execute("DELETE FROM calendar_events WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO calendar_events (user_id, key, title, start_at, end_at, first_day, last_day) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (user_id, each.key, each.title, each.start.isoformat() if each.start else None, each.end.isoformat() if each.end else None,
             each.first_day.isoformat() if each.first_day else None, each.last_day.isoformat() if each.last_day else None)
            for each in events
        ],
    )
    conn.execute(
        """
        INSERT INTO calendar_reads (user_id, read_at, tried_at, failing_since, failure, events) VALUES (?, ?, ?, NULL, '', ?)
        ON CONFLICT(user_id) DO UPDATE SET read_at = excluded.read_at, tried_at = excluded.tried_at, failing_since = NULL, failure = '', events = excluded.events
        """,
        (user_id, now.isoformat(), now.isoformat(), len(events)),
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
    return await database.run(db_events, user_id)
