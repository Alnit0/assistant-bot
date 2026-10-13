import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

# ---------------------------------------------------------------------------
# What was fetched, kept: the briefing only ever reads this, and never waits
# on the network. One row a user and a day: the latest forecast that could be
# read, and when a fetch last failed.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE weather_forecasts (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            data TEXT,
            fetched_at TEXT,
            failed_at TEXT,
            PRIMARY KEY (user_id, day)
        )
        """
    )


MIGRATIONS = [create_tables]


@dataclass(frozen=True)
class Kept:
    data: dict | None  # the forecast as the source gave it; None if none could be fetched that day
    fetched_at: datetime | None
    failed_at: datetime | None  # when a fetch last failed, if one has since the last that worked


def db_keep(conn: sqlite3.Connection, user_id: int, day: date, data: dict, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO weather_forecasts (user_id, day, data, fetched_at, failed_at) VALUES (?, ?, ?, ?, NULL)
        ON CONFLICT(user_id, day) DO UPDATE SET data = excluded.data, fetched_at = excluded.fetched_at, failed_at = NULL
        """,
        (user_id, day.isoformat(), json.dumps(data), now.isoformat()),
    )


def db_failed(conn: sqlite3.Connection, user_id: int, day: date, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO weather_forecasts (user_id, day, failed_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id, day) DO UPDATE SET failed_at = excluded.failed_at
        """,
        (user_id, day.isoformat(), now.isoformat()),
    )


def db_get(conn: sqlite3.Connection, user_id: int, day: date) -> Kept | None:
    row = conn.execute("SELECT data, fetched_at, failed_at FROM weather_forecasts WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()
    if row is None:
        return None
    return Kept(json.loads(row[0]) if row[0] else None, datetime.fromisoformat(row[1]) if row[1] else None, datetime.fromisoformat(row[2]) if row[2] else None)
