import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from core import database

# ---------------------------------------------------------------------------
# A saved plan (tasks/plan): one row a thing placed on a day (`plan_slots`),
# replaced whole when the day is planned again, with the Bot calendar's block
# for it when one was added; and how long each to-do takes (`plan_lengths`),
# Claude's estimate or what the user said, so a replan keeps the same lengths.
# Every row has a user_id. Days are NZ local; moments are UTC.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE plan_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            task TEXT NOT NULL,
            ref TEXT NOT NULL,
            icon TEXT NOT NULL,
            text TEXT NOT NULL,
            start TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            calendar_ref TEXT,
            saved_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX plan_slots_day ON plan_slots (user_id, day)")
    conn.execute(
        """
        CREATE TABLE plan_lengths (
            user_id INTEGER NOT NULL REFERENCES users(id),
            ref TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            said INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, ref)
        )
        """
    )


MIGRATIONS = [create_tables]


@dataclass(frozen=True)
class Saved:
    """One thing of a saved plan."""

    task: str
    ref: str
    icon: str
    text: str
    start: datetime
    minutes: int
    calendar_ref: str | None = None


_COLUMNS = "task, ref, icon, text, start, minutes, calendar_ref"


def _saved(row: tuple) -> Saved:
    return Saved(row[0], row[1], row[2], row[3], datetime.fromisoformat(row[4]), row[5], row[6])


def db_day(conn: sqlite3.Connection, user_id: int, day: date) -> list[Saved]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM plan_slots WHERE user_id = ? AND day = ? ORDER BY start, id", (user_id, day.isoformat())).fetchall()
    return [_saved(row) for row in rows]


def db_save(conn: sqlite3.Connection, user_id: int, day: date, slots: list[Saved], now: datetime) -> None:
    """The day's plan, in place of the one before."""
    conn.execute("DELETE FROM plan_slots WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))
    conn.executemany(
        "INSERT INTO plan_slots (user_id, day, task, ref, icon, text, start, minutes, calendar_ref, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(user_id, day.isoformat(), each.task, each.ref, each.icon, each.text, each.start.isoformat(), each.minutes, each.calendar_ref, now.isoformat()) for each in slots],
    )


def db_calendar_refs(conn: sqlite3.Connection, user_id: int) -> set[str]:
    """Every Bot calendar block a plan added: the calendar's own copy of them is never planned around."""
    return {row[0] for row in conn.execute("SELECT calendar_ref FROM plan_slots WHERE user_id = ? AND calendar_ref IS NOT NULL", (user_id,))}


def db_lengths(conn: sqlite3.Connection, user_id: int) -> dict[str, tuple[int, bool]]:
    """{ref: (minutes, whether the user said it)}."""
    return {row[0]: (row[1], bool(row[2])) for row in conn.execute("SELECT ref, minutes, said FROM plan_lengths WHERE user_id = ?", (user_id,))}


def db_set_lengths(conn: sqlite3.Connection, user_id: int, lengths: dict[str, tuple[int, bool]], now: datetime) -> None:
    conn.executemany(
        "INSERT INTO plan_lengths (user_id, ref, minutes, said, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, ref) DO UPDATE SET minutes = excluded.minutes, said = excluded.said, updated_at = excluded.updated_at",
        [(user_id, ref, minutes, int(said), now.isoformat()) for ref, (minutes, said) in lengths.items()],
    )


async def day(user_id: int, on: date) -> list[Saved]:
    return await database.run(db_day, user_id, on)
