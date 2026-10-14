import json
import sqlite3
from datetime import date, datetime

from core import database
from tasks.habits.rules import Habit, Step

# ---------------------------------------------------------------------------
# Personal routines in the database: a routine, its steps in order, and each
# step ticked on a day (one row a step a day, so a day starts with nothing
# ticked). Every row has a user_id; a removed routine or step keeps its row.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE habits_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            weekdays TEXT NOT NULL DEFAULT '[]',
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE habits_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            habit_id INTEGER NOT NULL REFERENCES habits_items(id),
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            removed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE habits_ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            step_id INTEGER NOT NULL REFERENCES habits_steps(id),
            day TEXT NOT NULL,
            done_at TEXT NOT NULL,
            UNIQUE (step_id, day)
        )
        """
    )


MIGRATIONS = [create_tables]


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Habit]:
    found = []
    for habit_id, name, weekdays in conn.execute("SELECT id, name, weekdays FROM habits_items WHERE user_id = ? AND removed_at IS NULL ORDER BY id", (user_id,)).fetchall():
        steps = tuple(Step(step_id, text) for step_id, text in conn.execute("SELECT id, text FROM habits_steps WHERE habit_id = ? AND removed_at IS NULL ORDER BY position, id", (habit_id,)).fetchall())
        found.append(Habit(habit_id, user_id, name, tuple(json.loads(weekdays)), steps))
    return found


def db_ticked(conn: sqlite3.Connection, user_id: int, day: date) -> set[int]:
    return {row[0] for row in conn.execute("SELECT step_id FROM habits_ticks WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))}


def db_add(conn: sqlite3.Connection, user_id: int, name: str, weekdays: tuple[int, ...], steps: list[str], now: datetime) -> int:
    habit_id = conn.execute("INSERT INTO habits_items (user_id, name, weekdays, created_at) VALUES (?, ?, ?, ?)", (user_id, name, json.dumps(list(weekdays)), now.isoformat())).lastrowid
    db_set_steps(conn, user_id, habit_id, steps, now)
    return habit_id


def db_set_steps(conn: sqlite3.Connection, user_id: int, habit_id: int, steps: list[str], now: datetime) -> None:
    """The routine's steps are these, in this order: a step kept keeps its row (and what
    is ticked today), one gone is marked removed, one new is added."""
    there = {text.lower(): step_id for step_id, text in conn.execute("SELECT id, text FROM habits_steps WHERE habit_id = ? AND removed_at IS NULL", (habit_id,))}
    kept = set()
    for position, text in enumerate(steps):
        step_id = there.get(text.lower())
        if step_id is None:
            conn.execute("INSERT INTO habits_steps (user_id, habit_id, position, text) VALUES (?, ?, ?, ?)", (user_id, habit_id, position, text))
        else:
            kept.add(step_id)
            conn.execute("UPDATE habits_steps SET position = ?, text = ? WHERE id = ?", (position, text, step_id))
    for step_id in set(there.values()) - kept:
        conn.execute("UPDATE habits_steps SET removed_at = ? WHERE id = ?", (now.isoformat(), step_id))


def db_change(conn: sqlite3.Connection, habit_id: int, name: str, weekdays: tuple[int, ...]) -> None:
    conn.execute("UPDATE habits_items SET name = ?, weekdays = ? WHERE id = ?", (name, json.dumps(list(weekdays)), habit_id))


def db_remove(conn: sqlite3.Connection, habit_id: int, now: datetime) -> None:
    conn.execute("UPDATE habits_items SET removed_at = ? WHERE id = ?", (now.isoformat(), habit_id))


def db_tick(conn: sqlite3.Connection, user_id: int, step_id: int, day: date, now: datetime) -> bool:
    """Tick a step for a day. False if it was ticked already."""
    return conn.execute("INSERT OR IGNORE INTO habits_ticks (user_id, step_id, day, done_at) VALUES (?, ?, ?, ?)", (user_id, step_id, day.isoformat(), now.isoformat())).rowcount == 1


def db_untick(conn: sqlite3.Connection, step_id: int, day: date) -> bool:
    return conn.execute("DELETE FROM habits_ticks WHERE step_id = ? AND day = ?", (step_id, day.isoformat())).rowcount == 1


def db_step(conn: sqlite3.Connection, step_id: int) -> tuple[int, int, str] | None:
    """(the step's user, its routine, its words), or None."""
    return conn.execute("SELECT user_id, habit_id, text FROM habits_steps WHERE id = ? AND removed_at IS NULL", (step_id,)).fetchone()


async def every(user_id: int) -> list[Habit]:
    return await database.run(db_all, user_id)


async def ticked(user_id: int, day: date) -> set[int]:
    return await database.run(db_ticked, user_id, day)
