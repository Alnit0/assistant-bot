import json
import sqlite3
from datetime import date, datetime

from core import database
from tasks.reading.rules import Item

# ---------------------------------------------------------------------------
# The daily read in the database. Every row has a user_id.
#   reading_news        the morning news's set a day (its stories as JSON), and whether 👍 said it was good
#   reading_news_spares the stories ranked next that day, for "another one"
#   reading_news_prefs  what Alex said about the news (more, less, more like, a day skipped), as JSON
#   reading_sources     sources added or removed in words, on top of feeds.json
#   reading_fetches     a day's fetch: how many sources, how many failed
#   reading_reads, reading_candidates, reading_profile: the old daily read's (before 21 Oct), kept, no longer written
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


def add_news(conn: sqlite3.Connection) -> None:
    """The morning news (21 Oct): the day's set, the stories ranked next for "another one", and what Alex said."""
    conn.execute(
        """
        CREATE TABLE reading_news (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            stories TEXT NOT NULL,
            liked INTEGER NOT NULL DEFAULT 0,
            shown_at TEXT NOT NULL,
            PRIMARY KEY (user_id, day)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE reading_news_spares (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            rank INTEGER NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            topic TEXT NOT NULL,
            snippet TEXT NOT NULL,
            shown INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day, url)
        )
        """
    )
    conn.execute("CREATE TABLE reading_news_prefs (user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, updated_at TEXT NOT NULL)")


MIGRATIONS = [create_tables, add_ratings, add_news]
ADDED, REMOVED = "added", "removed"


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


# --- the morning news ---------------------------------------------------------------------------------------------
def _stories(text: str) -> list:
    from tasks.reading.news import Story

    return [Story(**each) for each in json.loads(text)]


def db_news(conn: sqlite3.Connection, user_id: int, day: date) -> tuple[list, bool] | None:
    """The day's set and whether he said it was good, or None before it is picked."""
    row = conn.execute("SELECT stories, liked FROM reading_news WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()
    return (_stories(row[0]), bool(row[1])) if row else None


def db_put_news(conn: sqlite3.Connection, user_id: int, day: date, stories: list, now: datetime) -> None:
    from dataclasses import asdict

    conn.execute(
        "INSERT INTO reading_news (user_id, day, stories, shown_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET stories = excluded.stories, shown_at = excluded.shown_at",
        (user_id, day.isoformat(), json.dumps([asdict(each) for each in stories], ensure_ascii=False), now.isoformat()),
    )


def db_like_news(conn: sqlite3.Connection, user_id: int, day: date, liked: bool) -> bool:
    """👍 on the day's set (or taken away). False if there is no set that day."""
    return conn.execute("UPDATE reading_news SET liked = ? WHERE user_id = ? AND day = ?", (int(liked), user_id, day.isoformat())).rowcount > 0


def db_liked_sets(conn: sqlite3.Connection, user_id: int, limit: int = 5) -> list[list[str]]:
    """The headlines of the latest sets he said were good, oldest first: a light signal for the pick."""
    rows = conn.execute("SELECT stories FROM reading_news WHERE user_id = ? AND liked = 1 ORDER BY day DESC LIMIT ?", (user_id, limit)).fetchall()
    return [[each.title for each in _stories(row[0])] for row in reversed(rows)]


def db_news_shown(conn: sqlite3.Connection, user_id: int, since: date) -> set[str]:
    """Every link shown since that day, in a set or as another one: never shown again."""
    found = {each.url for row in conn.execute("SELECT stories FROM reading_news WHERE user_id = ? AND day >= ?", (user_id, since.isoformat())) for each in _stories(row[0])}
    found |= {row[0] for row in conn.execute("SELECT url FROM reading_news_spares WHERE user_id = ? AND day >= ? AND shown = 1", (user_id, since.isoformat()))}
    return found


def db_put_spares(conn: sqlite3.Connection, user_id: int, day: date, items: list) -> None:
    """The stories ranked next, best first, for "another one"; earlier days' go."""
    conn.execute("DELETE FROM reading_news_spares WHERE user_id = ? AND day < ?", (user_id, day.isoformat()))
    conn.executemany(
        "INSERT OR REPLACE INTO reading_news_spares (user_id, day, rank, url, title, source, topic, snippet) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(user_id, day.isoformat(), rank, each.url, each.title, each.source, each.theme, each.snippet) for rank, each in enumerate(items)],
    )


def db_next_spare(conn: sqlite3.Connection, user_id: int, day: date):
    """The best story not shown yet that day, marked shown; None when there are no more."""
    row = conn.execute(
        "SELECT url, title, source, topic, snippet FROM reading_news_spares WHERE user_id = ? AND day = ? AND shown = 0 ORDER BY rank LIMIT 1", (user_id, day.isoformat())
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE reading_news_spares SET shown = 1 WHERE user_id = ? AND day = ? AND url = ?", (user_id, day.isoformat(), row[0]))
    return Item(row[0], row[1], row[2], row[3], snippet=row[4])


def db_unshow_spare(conn: sqlite3.Connection, user_id: int, day: date, url: str) -> None:
    """Another one that could not be written: it may be tried again."""
    conn.execute("UPDATE reading_news_spares SET shown = 0 WHERE user_id = ? AND day = ? AND url = ?", (user_id, day.isoformat(), url))


def db_prefs(conn: sqlite3.Connection, user_id: int):
    from tasks.reading.news import Prefs

    row = conn.execute("SELECT data FROM reading_news_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return Prefs.from_dict(json.loads(row[0]) if row else None)


def db_set_prefs(conn: sqlite3.Connection, user_id: int, prefs, now: datetime) -> None:
    conn.execute(
        "INSERT INTO reading_news_prefs (user_id, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (user_id, json.dumps(prefs.as_dict(), ensure_ascii=False), now.isoformat()),
    )
