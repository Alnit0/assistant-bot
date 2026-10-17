import json
import sqlite3
from datetime import date, datetime, time

from core import database
from tasks.nudges.rules import Fired, Nudge

# ---------------------------------------------------------------------------
# Reminders in the database: what I set (`nudges_items`) and each time one
# went off (`nudges_fired`, one row an occurrence: it is what stops one ever
# being posted twice). Every row has a user_id; a removed reminder keeps its
# row. Times of day and days are NZ local; moments are UTC.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE nudges_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            text TEXT NOT NULL,
            at TEXT NOT NULL,
            repeat TEXT NOT NULL,
            first_day TEXT,
            weekdays TEXT NOT NULL DEFAULT '[]',
            every_days INTEGER NOT NULL DEFAULT 1,
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nudges_fired (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            nudge_id INTEGER NOT NULL REFERENCES nudges_items(id),
            local TEXT NOT NULL,
            due_at TEXT NOT NULL,
            message_id INTEGER,
            channel_id INTEGER,
            done_at TEXT,
            snoozed_until TEXT,
            late INTEGER NOT NULL DEFAULT 0,
            UNIQUE (nudge_id, local)
        )
        """
    )


def add_expiries(conn: sqlite3.Connection) -> None:
    """Expiries and renewals (tasks/nudges/expiry.py): the day, its cycle in months (none: once), the days
    before to be told; the 1-day nudge posted once a due day; and each renewal, for undo."""
    conn.execute(
        """
        CREATE TABLE nudges_expiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            due TEXT NOT NULL,
            anchor INTEGER NOT NULL,
            cycle_months INTEGER,
            before TEXT NOT NULL DEFAULT '[30, 7, 1]',
            done_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nudges_renewal_posts (
            expiry_id INTEGER NOT NULL REFERENCES nudges_expiries(id),
            due TEXT NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            done INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (expiry_id, due)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nudges_renewals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expiry_id INTEGER NOT NULL REFERENCES nudges_expiries(id),
            was_due TEXT NOT NULL,
            was_done TEXT,
            at TEXT NOT NULL,
            undone INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def add_birthdays(conn: sqlite3.Connection) -> None:
    """Birthdays (tasks/nudges/birthdays.py): appended, never in between."""
    from tasks.nudges import birthdays

    birthdays.add_tables(conn)


MIGRATIONS = [create_tables, add_expiries, add_birthdays]

_ITEM = "id, user_id, text, at, repeat, first_day, weekdays, every_days"
_FIRED = "id, nudge_id, local, due_at, message_id, done_at, snoozed_until, late"


def _nudge(row: tuple) -> Nudge:
    hour, minute = (int(part) for part in row[3].split(":"))
    return Nudge(row[0], row[1], row[2], time(hour, minute), row[4], date.fromisoformat(row[5]) if row[5] else None, tuple(json.loads(row[6])), row[7])


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _fired(row: tuple) -> Fired:
    return Fired(row[0], row[1], row[2], datetime.fromisoformat(row[3]), row[4], _moment(row[5]), _moment(row[6]), bool(row[7]))


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Nudge]:
    rows = conn.execute(f"SELECT {_ITEM} FROM nudges_items WHERE user_id = ? AND removed_at IS NULL ORDER BY at, id", (user_id,)).fetchall()
    return [_nudge(row) for row in rows]


def db_get(conn: sqlite3.Connection, nudge_id: int) -> Nudge | None:
    row = conn.execute(f"SELECT {_ITEM} FROM nudges_items WHERE id = ? AND removed_at IS NULL", (nudge_id,)).fetchone()
    return _nudge(row) if row else None


def _values(nudge: Nudge) -> tuple:
    return (nudge.text, f"{nudge.at:%H:%M}", nudge.repeat, nudge.first.isoformat() if nudge.first else None, json.dumps(list(nudge.weekdays)), nudge.every_days)


def db_add(conn: sqlite3.Connection, nudge: Nudge, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO nudges_items (user_id, text, at, repeat, first_day, weekdays, every_days, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (nudge.user_id, *_values(nudge), now.isoformat()),
    )
    return cursor.lastrowid


def db_change(conn: sqlite3.Connection, nudge: Nudge) -> None:
    conn.execute("UPDATE nudges_items SET text = ?, at = ?, repeat = ?, first_day = ?, weekdays = ?, every_days = ? WHERE id = ?", (*_values(nudge), nudge.id))


def db_remove(conn: sqlite3.Connection, nudge_id: int, now: datetime) -> None:
    conn.execute("UPDATE nudges_items SET removed_at = ? WHERE id = ?", (now.isoformat(), nudge_id))


def db_fired(conn: sqlite3.Connection, nudge_id: int, local: str) -> Fired | None:
    row = conn.execute(f"SELECT {_FIRED} FROM nudges_fired WHERE nudge_id = ? AND local = ?", (nudge_id, local)).fetchone()
    return _fired(row) if row else None


def db_fired_by_id(conn: sqlite3.Connection, fired_id: int) -> Fired | None:
    row = conn.execute(f"SELECT {_FIRED} FROM nudges_fired WHERE id = ?", (fired_id,)).fetchone()
    return _fired(row) if row else None


def db_open(conn: sqlite3.Connection, user_id: int) -> list[Fired]:
    """What went off and is not dealt with (not done, not snoozed), the latest first."""
    rows = conn.execute(f"SELECT {_FIRED} FROM nudges_fired WHERE user_id = ? AND done_at IS NULL AND snoozed_until IS NULL ORDER BY due_at DESC, id DESC", (user_id,)).fetchall()
    return [_fired(row) for row in rows]


def db_latest(conn: sqlite3.Connection, user_id: int) -> Fired | None:
    row = conn.execute(f"SELECT {_FIRED} FROM nudges_fired WHERE user_id = ? ORDER BY due_at DESC, id DESC LIMIT 1", (user_id,)).fetchone()
    return _fired(row) if row else None


def db_went_off(conn: sqlite3.Connection, user_id: int, nudge_id: int, local: str, due_at: datetime, late: bool) -> int | None:
    """Claim an occurrence before it is posted: the id of its row, or None if it
    was claimed already (it is never posted twice). One snoozed is claimed again."""
    there = db_fired(conn, nudge_id, local)
    if there is not None:
        if there.snoozed_until is None:
            return None
        conn.execute("UPDATE nudges_fired SET snoozed_until = NULL, due_at = ?, message_id = NULL WHERE id = ?", (due_at.isoformat(), there.id))
        return there.id
    cursor = conn.execute(
        "INSERT INTO nudges_fired (user_id, nudge_id, local, due_at, late) VALUES (?, ?, ?, ?, ?)",
        (user_id, nudge_id, local, due_at.isoformat(), int(late)),
    )
    return cursor.lastrowid


def db_posted(conn: sqlite3.Connection, fired_id: int, channel_id: int, message_id: int) -> None:
    conn.execute("UPDATE nudges_fired SET message_id = ?, channel_id = ? WHERE id = ?", (message_id, channel_id, fired_id))


def db_unclaim(conn: sqlite3.Connection, fired_id: int) -> None:
    """It could not be posted: let the next try claim it again."""
    conn.execute("DELETE FROM nudges_fired WHERE id = ? AND message_id IS NULL", (fired_id,))


def db_done(conn: sqlite3.Connection, fired_id: int, now: datetime) -> None:
    conn.execute("UPDATE nudges_fired SET done_at = ?, snoozed_until = NULL WHERE id = ?", (now.isoformat(), fired_id))


def db_snoozed(conn: sqlite3.Connection, fired_id: int, until: datetime) -> None:
    conn.execute("UPDATE nudges_fired SET snoozed_until = ? WHERE id = ?", (until.isoformat(), fired_id))


def db_message(conn: sqlite3.Connection, message_id: int) -> Fired | None:
    row = conn.execute(f"SELECT {_FIRED} FROM nudges_fired WHERE message_id = ?", (message_id,)).fetchone()
    return _fired(row) if row else None


async def every(user_id: int) -> list[Nudge]:
    return await database.run(db_all, user_id)
