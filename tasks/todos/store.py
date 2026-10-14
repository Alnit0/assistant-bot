import sqlite3
from datetime import date, datetime

from core import database
from tasks.todos.rules import Todo

# ---------------------------------------------------------------------------
# To-dos in the database. Every row has a user_id; the table is prefixed with
# the task's name. A removed to-do keeps its row (removed_at), so nothing is
# lost by a slip of the hand. Days are NZ local; moments are UTC.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE todos_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            text TEXT NOT NULL,
            day TEXT,
            added_on TEXT NOT NULL,
            done_at TEXT,
            done_on TEXT,
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX todos_items_user ON todos_items (user_id, removed_at)")


MIGRATIONS = [create_tables]

_COLUMNS = "id, user_id, text, day, added_on, done_at, done_on"


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _todo(row: tuple) -> Todo:
    return Todo(row[0], row[1], row[2], _day(row[3]), date.fromisoformat(row[4]), datetime.fromisoformat(row[5]) if row[5] else None, _day(row[6]))


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Todo]:
    """Every to-do that is not removed, done or not."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM todos_items WHERE user_id = ? AND removed_at IS NULL ORDER BY id", (user_id,)).fetchall()
    return [_todo(row) for row in rows]


def db_get(conn: sqlite3.Connection, todo_id: int) -> Todo | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM todos_items WHERE id = ? AND removed_at IS NULL", (todo_id,)).fetchone()
    return _todo(row) if row else None


def db_add(conn: sqlite3.Connection, user_id: int, text: str, day: date | None, today: date, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO todos_items (user_id, text, day, added_on, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, text, day.isoformat() if day else None, today.isoformat(), now.isoformat()),
    )
    return cursor.lastrowid


def db_change(conn: sqlite3.Connection, todo_id: int, text: str, day: date | None) -> None:
    conn.execute("UPDATE todos_items SET text = ?, day = ? WHERE id = ?", (text, day.isoformat() if day else None, todo_id))


def db_done(conn: sqlite3.Connection, todo_id: int, at: datetime | None, on: date | None) -> None:
    """Ticked off at that moment, or (with None) back to not done."""
    conn.execute("UPDATE todos_items SET done_at = ?, done_on = ? WHERE id = ?", (at.isoformat() if at else None, on.isoformat() if on else None, todo_id))


def db_remove(conn: sqlite3.Connection, todo_id: int, now: datetime) -> None:
    conn.execute("UPDATE todos_items SET removed_at = ? WHERE id = ?", (now.isoformat(), todo_id))


async def every(user_id: int) -> list[Todo]:
    return await database.run(db_all, user_id)
