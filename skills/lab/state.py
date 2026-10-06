import json
import sqlite3
from datetime import datetime, timezone

from core import database


# ---------------------------------------------------------------------------
# The lab's own table: small pieces of state that must survive a restart
# ---------------------------------------------------------------------------
def create_lab_state(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE lab_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            updated_at TEXT NOT NULL
        )
        """
    )


MIGRATIONS = [
    create_lab_state,
]


def _get(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT value FROM lab_state WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _put(conn: sqlite3.Connection, key: str, value: dict, user_id: int | None) -> None:
    conn.execute(
        """
        INSERT INTO lab_state (key, value, user_id, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, user_id = excluded.user_id, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value), user_id, datetime.now(timezone.utc).isoformat()),
    )


def _clear(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM lab_state WHERE key = ?", (key,))


async def get(key: str) -> dict | None:
    return await database.run(_get, key)


async def put(key: str, value: dict, user_id: int | None) -> None:
    await database.run(_put, key, value, user_id)


async def clear(key: str) -> None:
    await database.run(_clear, key)
