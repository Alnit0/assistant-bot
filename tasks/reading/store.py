import json
import sqlite3
from datetime import date, datetime

from core import database
from tasks.reading.rules import Item

# ---------------------------------------------------------------------------
# The daily read in the database. Every row has a user_id.
#   reading_news        the morning news's set a day (its stories as JSON); `liked` is the hub's old 👍 (before
#                       the cards), kept, no longer written
#   reading_news_posts  a message in #news (21 Oct, night): the day's (slot 0) and each another one's, the
#                       stories in it, where it went up and whether it is still there
#   reading_news_channel  the #news the bot made beside the hub
#   reading_news_cards  a card a story, for the one night they were planned: dropped, never shipped
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


def add_cards(conn: sqlite3.Connection) -> None:
    """The morning news as a card a story in #news (21 Oct, night): each card, and the channel the bot made."""
    conn.execute(
        """
        CREATE TABLE reading_news_cards (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            url TEXT NOT NULL,
            position INTEGER NOT NULL,
            story TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            state TEXT NOT NULL,
            liked INTEGER NOT NULL DEFAULT 0,
            liked_at TEXT,
            PRIMARY KEY (user_id, day, url)
        )
        """
    )
    conn.execute("CREATE INDEX reading_news_cards_message ON reading_news_cards (message_id)")
    conn.execute("CREATE TABLE reading_news_channel (user_id INTEGER PRIMARY KEY REFERENCES users(id), channel_id INTEGER NOT NULL, made_at TEXT NOT NULL)")


def to_messages(conn: sqlite3.Connection) -> None:
    """The day's news as one message (Alex, 21 Oct, night), and no 👍: the cards' table goes (never shipped), a
    message's takes its place."""
    conn.execute("DROP TABLE reading_news_cards")
    conn.execute(
        """
        CREATE TABLE reading_news_posts (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            slot INTEGER NOT NULL,
            stories TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            state TEXT NOT NULL,
            PRIMARY KEY (user_id, day, slot)
        )
        """
    )
    conn.execute("CREATE INDEX reading_news_posts_message ON reading_news_posts (message_id)")


MIGRATIONS = [create_tables, add_ratings, add_news, add_cards, to_messages]
SENDING, UP, GONE = "sending", "up", "gone"  # a message: being posted (a start cut off then: never posted again), up, deleted
DAY_SLOT = 0  # the day's message; each another one is the next slot
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


# --- the messages in #news ---------------------------------------------------------------------------------------
def db_post_states(conn: sqlite3.Connection, user_id: int, day: date) -> dict[int, str]:
    """The day's messages so far: slot to its state (SENDING, UP or GONE)."""
    return dict(conn.execute("SELECT slot, state FROM reading_news_posts WHERE user_id = ? AND day = ?", (user_id, day.isoformat())))


def db_post_sending(conn: sqlite3.Connection, user_id: int, day: date, slot: int | None, stories: list, channel_id: int) -> int:
    """Noted before it is posted, so a start cut off mid-post finds it and never posts it twice. Its slot (the next
    one when none is said)."""
    from dataclasses import asdict

    if slot is None:
        slot = conn.execute("SELECT COALESCE(MAX(slot) + 1, 1) FROM reading_news_posts WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO reading_news_posts (user_id, day, slot, stories, channel_id, state) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, day.isoformat(), slot, json.dumps([asdict(each) for each in stories], ensure_ascii=False), channel_id, SENDING),
    )
    return slot


def db_post_up(conn: sqlite3.Connection, user_id: int, day: date, slot: int, message_id: int) -> None:
    conn.execute("UPDATE reading_news_posts SET message_id = ?, state = ? WHERE user_id = ? AND day = ? AND slot = ?", (message_id, UP, user_id, day.isoformat(), slot))


def db_post_unsent(conn: sqlite3.Connection, user_id: int, day: date, slot: int) -> None:
    """A post that failed for certain: it may be posted on the next try."""
    conn.execute("DELETE FROM reading_news_posts WHERE user_id = ? AND day = ? AND slot = ? AND state = ?", (user_id, day.isoformat(), slot, SENDING))


def db_posts_before(conn: sqlite3.Connection, user_id: int, day: date) -> list[tuple[str, int, int, int]]:
    """(day, slot, channel_id, message_id) of every message still up from an earlier day."""
    return list(conn.execute(
        "SELECT day, slot, channel_id, message_id FROM reading_news_posts WHERE user_id = ? AND day < ? AND state = ? ORDER BY day, slot", (user_id, day.isoformat(), UP)
    ))


def db_post_gone(conn: sqlite3.Connection, user_id: int, day: str, slot: int) -> None:
    conn.execute("UPDATE reading_news_posts SET state = ? WHERE user_id = ? AND day = ? AND slot = ?", (GONE, user_id, day, slot))


def db_posts_up(conn: sqlite3.Connection, user_id: int, day: date) -> list[tuple[int, int, list]]:
    """(channel_id, message_id, stories) of the day's messages up, the day's first, then each another one."""
    rows = conn.execute("SELECT channel_id, message_id, stories FROM reading_news_posts WHERE user_id = ? AND day = ? AND state = ? ORDER BY slot", (user_id, day.isoformat(), UP))
    return [(row[0], row[1], _stories(row[2])) for row in rows]


def db_post_of(conn: sqlite3.Connection, message_id: int | None) -> tuple[int, date] | None:
    """(user_id, day) of the news message that is, or None."""
    if message_id is None:
        return None
    row = conn.execute("SELECT user_id, day FROM reading_news_posts WHERE message_id = ?", (message_id,)).fetchone()
    return (row[0], date.fromisoformat(row[1])) if row else None


def db_news_channel(conn: sqlite3.Connection, user_id: int) -> int | None:
    row = conn.execute("SELECT channel_id FROM reading_news_channel WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def db_set_news_channel(conn: sqlite3.Connection, user_id: int, channel_id: int, now: datetime) -> None:
    conn.execute(
        "INSERT INTO reading_news_channel (user_id, channel_id, made_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET channel_id = excluded.channel_id, made_at = excluded.made_at",
        (user_id, channel_id, now.isoformat()),
    )


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
