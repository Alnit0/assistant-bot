import json
import sqlite3
from datetime import date, datetime

from core import database
from tasks.reading.rules import Candidate, Item, Profile, Read

# ---------------------------------------------------------------------------
# The daily read in the database. Every row has a user_id.
#   reading_reads       what was shown, a row a read (its day, TL;DR, vote, saved)
#   reading_candidates  the day's articles read and fit to pick from (for "another one")
#   reading_profile     what Alex likes to read, as JSON
#   reading_sources     sources added or removed in words, on top of feeds.json
#   reading_fetches     a day's fetch: how many sources, how many failed
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE reading_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            theme TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            tldr TEXT NOT NULL,
            vote INTEGER NOT NULL DEFAULT 0,
            saved INTEGER NOT NULL DEFAULT 0,
            current INTEGER NOT NULL DEFAULT 1,
            shown_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX reading_reads_day ON reading_reads (user_id, day)")
    conn.execute(
        """
        CREATE TABLE reading_candidates (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            theme TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (user_id, day, url)
        )
        """
    )
    conn.execute("CREATE TABLE reading_profile (user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE reading_sources (
            user_id INTEGER NOT NULL REFERENCES users(id),
            url TEXT NOT NULL,
            name TEXT NOT NULL,
            theme TEXT NOT NULL,
            state TEXT NOT NULL,
            at TEXT NOT NULL,
            PRIMARY KEY (user_id, url)
        )
        """
    )
    conn.execute(
        "CREATE TABLE reading_fetches (user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL, sources INTEGER NOT NULL, failed INTEGER NOT NULL, PRIMARY KEY (user_id, day))"
    )


def add_ratings(conn: sqlite3.Connection) -> None:
    """Claude's ratings of the read when it was picked: difficulty and practicality, 1 to 5."""
    conn.execute("ALTER TABLE reading_reads ADD COLUMN difficulty INTEGER")
    conn.execute("ALTER TABLE reading_reads ADD COLUMN practicality INTEGER")


MIGRATIONS = [create_tables, add_ratings]
ADDED, REMOVED = "added", "removed"
_READ = "url, title, source, theme, minutes, tldr, day, vote, saved, difficulty, practicality"


def _read(row) -> Read:
    return Read(row[0], row[1], row[2], row[3], row[4], row[5], date.fromisoformat(row[6]), row[7], bool(row[8]), row[9], row[10])


def db_current(conn: sqlite3.Connection, user_id: int, day: date) -> Read | None:
    """The day's read as shown now (the latest, after "another one")."""
    row = conn.execute(f"SELECT {_READ} FROM reading_reads WHERE user_id = ? AND day = ? AND current = 1 ORDER BY id DESC LIMIT 1", (user_id, day.isoformat())).fetchone()
    return _read(row) if row else None


def db_show(conn: sqlite3.Connection, user_id: int, read: Read, now: datetime) -> None:
    """A read shown for its day: the one shown before it that day is no longer current."""
    conn.execute("UPDATE reading_reads SET current = 0 WHERE user_id = ? AND day = ?", (user_id, read.day.isoformat()))
    conn.execute(
        "INSERT INTO reading_reads (user_id, day, url, title, source, theme, minutes, tldr, shown_at, difficulty, practicality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, read.day.isoformat(), read.url, read.title, read.source, read.theme, read.minutes, read.tldr, now.isoformat(), read.difficulty, read.practicality),
    )


def db_seen(conn: sqlite3.Connection, user_id: int) -> set[str]:
    return {row[0] for row in conn.execute("SELECT url FROM reading_reads WHERE user_id = ?", (user_id,))}


def db_between(conn: sqlite3.Connection, user_id: int, first: date, last: date) -> list[Read]:
    """The reads of those days, the current one of each day."""
    rows = conn.execute(f"SELECT {_READ} FROM reading_reads WHERE user_id = ? AND day BETWEEN ? AND ? AND current = 1 ORDER BY day", (user_id, first.isoformat(), last.isoformat()))
    return [_read(row) for row in rows]


def db_themes_between(conn: sqlite3.Connection, user_id: int, first: date, last: date) -> list[str]:
    return [row[0] for row in conn.execute("SELECT theme FROM reading_reads WHERE user_id = ? AND day BETWEEN ? AND ? AND current = 1", (user_id, first.isoformat(), last.isoformat()))]


def db_vote(conn: sqlite3.Connection, user_id: int, url: str, vote: int) -> Read | None:
    conn.execute("UPDATE reading_reads SET vote = ? WHERE user_id = ? AND url = ?", (vote, user_id, url))
    row = conn.execute(f"SELECT {_READ} FROM reading_reads WHERE user_id = ? AND url = ? ORDER BY id DESC LIMIT 1", (user_id, url)).fetchone()
    return _read(row) if row else None


def db_saved(conn: sqlite3.Connection, user_id: int, url: str) -> None:
    conn.execute("UPDATE reading_reads SET saved = 1 WHERE user_id = ? AND url = ?", (user_id, url))


def db_keep_candidates(conn: sqlite3.Connection, user_id: int, day: date, found: list[Candidate]) -> None:
    conn.execute("DELETE FROM reading_candidates WHERE user_id = ? AND day < ?", (user_id, day.isoformat()))
    conn.executemany(
        "INSERT OR REPLACE INTO reading_candidates (user_id, day, url, title, source, theme, minutes, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(user_id, day.isoformat(), each.item.url, each.item.title, each.item.source, each.item.theme, each.minutes, each.text) for each in found],
    )


def db_candidates(conn: sqlite3.Connection, user_id: int, day: date) -> list[Candidate]:
    rows = conn.execute("SELECT url, title, source, theme, minutes, text FROM reading_candidates WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))
    return [Candidate(Item(row[0], row[1], row[2], row[3]), row[5], row[4]) for row in rows]


def db_profile(conn: sqlite3.Connection, user_id: int) -> Profile:
    row = conn.execute("SELECT data FROM reading_profile WHERE user_id = ?", (user_id,)).fetchone()
    return Profile.from_dict(json.loads(row[0]) if row else None)


def db_set_profile(conn: sqlite3.Connection, user_id: int, profile: Profile, now: datetime) -> None:
    conn.execute(
        "INSERT INTO reading_profile (user_id, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (user_id, json.dumps(profile.as_dict()), now.isoformat()),
    )


def db_source_changes(conn: sqlite3.Connection, user_id: int) -> list[tuple[str, str, str, str]]:
    """(url, name, theme, state) of every source added or removed in words."""
    return list(conn.execute("SELECT url, name, theme, state FROM reading_sources WHERE user_id = ?", (user_id,)))


def db_set_source(conn: sqlite3.Connection, user_id: int, url: str, name: str, theme: str, state: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO reading_sources (user_id, url, name, theme, state, at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, url) DO UPDATE SET name = excluded.name, theme = excluded.theme, state = excluded.state, at = excluded.at",
        (user_id, url, name, theme, state, now.isoformat()),
    )


def db_fetched(conn: sqlite3.Connection, user_id: int, day: date, sources: int, failed: int) -> None:
    conn.execute("INSERT OR REPLACE INTO reading_fetches (user_id, day, sources, failed) VALUES (?, ?, ?, ?)", (user_id, day.isoformat(), sources, failed))


def db_failed_days(conn: sqlite3.Connection, user_id: int, limit: int) -> list[bool]:
    """Newest first: whether every source failed that day."""
    rows = conn.execute("SELECT sources, failed FROM reading_fetches WHERE user_id = ? ORDER BY day DESC LIMIT ?", (user_id, limit))
    return [bool(row[0]) and row[0] == row[1] for row in rows]


async def current(user_id: int, day: date) -> Read | None:
    return await database.run(db_current, user_id, day)
