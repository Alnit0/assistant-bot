import sqlite3
from dataclasses import dataclass

from core import database
from core.scheduler import to_db, utc_now
from tasks.bugs import rules

# ---------------------------------------------------------------------------
# The bugs and their notes. A bug's id is the number in "B4". No Discord in
# here: plain values in, plain values out. The functions starting with `_db_`
# block (the command line in cli.py calls them directly); the async ones run
# them in a worker thread.
# ---------------------------------------------------------------------------


def create_items(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bugs_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            source TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            target_message_id INTEGER NOT NULL,
            git_commit TEXT NOT NULL,
            report TEXT NOT NULL,
            thread_id INTEGER,
            post_url TEXT,
            created_at TEXT NOT NULL,
            closed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX bugs_items_thread ON bugs_items (thread_id)")
    conn.execute("CREATE INDEX bugs_items_target ON bugs_items (channel_id, target_message_id)")


def create_notes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bugs_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bug_id INTEGER NOT NULL REFERENCES bugs_items(id),
            user_id INTEGER REFERENCES users(id),
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            discord_message_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX bugs_notes_bug ON bugs_notes (bug_id)")


def create_events(conn: sqlite3.Connection) -> None:
    # A bug's history after it was reported: each closing and re-opening
    conn.execute(
        """
        CREATE TABLE bugs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bug_id INTEGER NOT NULL REFERENCES bugs_items(id),
            user_id INTEGER REFERENCES users(id),
            event TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX bugs_events_bug ON bugs_events (bug_id)")


MIGRATIONS = [
    create_items,
    create_notes,
    create_events,
]


@dataclass
class Item:
    id: int
    user_id: int | None
    status: str
    summary: str
    report: rules.Report
    thread_id: int | None
    post_url: str | None
    created_at: str
    closed_at: str | None
    note_count: int = 0
    fix_ready: bool = False  # Claude Code has left a note since the bug was reported
    changed_at: str | None = None  # when it was last closed or re-opened, if ever


@dataclass(frozen=True)
class Note:
    author: str
    content: str
    created_at: str


@dataclass(frozen=True)
class Event:
    event: str  # rules.FIXED, rules.WONTFIX or rules.REOPENED
    created_at: str


_ITEM = """
    SELECT id, user_id, status, summary, report, thread_id, post_url, created_at, closed_at,
           (SELECT COUNT(*) FROM bugs_notes WHERE bug_id = bugs_items.id),
           EXISTS (SELECT 1 FROM bugs_notes WHERE bug_id = bugs_items.id AND author = ?),
           (SELECT created_at FROM bugs_events WHERE bug_id = bugs_items.id ORDER BY id DESC LIMIT 1)
    FROM bugs_items
"""


def _item(row: tuple | None) -> Item | None:
    if row is None:
        return None
    return Item(
        row[0], row[1], row[2], row[3], rules.Report.from_json(row[4]), row[5], row[6], row[7], row[8], row[9],
        bool(row[10]),
        # A bug closed before the history was kept has only the time it was closed
        row[11] or row[8],
    )


def _db_add(conn: sqlite3.Connection, user_id: int | None, report: rules.Report) -> int:
    cursor = conn.execute(
        """
        INSERT INTO bugs_items (user_id, status, summary, source, channel_id, target_message_id,
                                git_commit, report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            rules.OPEN,
            rules.summary(report.target.content),
            report.source,
            report.channel_id,
            report.target.message_id,
            report.commit,
            report.to_json(),
            to_db(utc_now()),
        ),
    )
    return cursor.lastrowid


def _db_set_post(conn: sqlite3.Connection, bug_id: int, thread_id: int, post_url: str) -> None:
    conn.execute("UPDATE bugs_items SET thread_id = ?, post_url = ? WHERE id = ?", (thread_id, post_url, bug_id))


def _db_get(conn: sqlite3.Connection, bug_id: int) -> Item | None:
    return _item(conn.execute(f"{_ITEM} WHERE id = ?", (rules.CLAUDE_CODE, bug_id)).fetchone())


def _db_by_thread(conn: sqlite3.Connection, thread_id: int) -> Item | None:
    return _item(conn.execute(f"{_ITEM} WHERE thread_id = ?", (rules.CLAUDE_CODE, thread_id)).fetchone())


def _db_open_for(conn: sqlite3.Connection, user_id: int, channel_id: int, message_id: int) -> Item | None:
    row = conn.execute(
        f"{_ITEM} WHERE user_id = ? AND channel_id = ? AND target_message_id = ? AND status = ? ORDER BY id LIMIT 1",
        (rules.CLAUDE_CODE, user_id, channel_id, message_id, rules.OPEN),
    ).fetchone()
    return _item(row)


def _db_open(conn: sqlite3.Connection, user_id: int | None = None) -> list[Item]:
    sql, values = f"{_ITEM} WHERE status = ?", [rules.CLAUDE_CODE, rules.OPEN]
    if user_id is not None:
        sql += " AND user_id = ?"
        values.append(user_id)
    return [_item(row) for row in conn.execute(f"{sql} ORDER BY id", values).fetchall()]


def _db_set_status(conn: sqlite3.Connection, bug_id: int, status: str, user_id: int | None = None) -> None:
    """Close or re-open a bug, and add that to its history."""
    now = to_db(utc_now())
    closed_at = None if status == rules.OPEN else now
    conn.execute("UPDATE bugs_items SET status = ?, closed_at = ? WHERE id = ?", (status, closed_at, bug_id))
    conn.execute(
        "INSERT INTO bugs_events (bug_id, user_id, event, created_at) VALUES (?, ?, ?, ?)",
        (bug_id, user_id, rules.REOPENED if status == rules.OPEN else status, now),
    )


def _db_events(conn: sqlite3.Connection, bug_id: int) -> list[Event]:
    rows = conn.execute(
        "SELECT event, created_at FROM bugs_events WHERE bug_id = ? ORDER BY id", (bug_id,)
    ).fetchall()
    return [Event(*row) for row in rows]


def _db_add_note(
    conn: sqlite3.Connection, bug_id: int, user_id: int | None, author: str, content: str, message_id: int | None = None
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO bugs_notes (bug_id, user_id, author, content, discord_message_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (bug_id, user_id, author, content, message_id, to_db(utc_now())),
    )
    return cursor.lastrowid


def _db_notes(conn: sqlite3.Connection, bug_id: int) -> list[Note]:
    rows = conn.execute(
        "SELECT author, content, created_at FROM bugs_notes WHERE bug_id = ? ORDER BY id", (bug_id,)
    ).fetchall()
    return [Note(*row) for row in rows]


def _db_in_full(conn: sqlite3.Connection, user_id: int | None = None) -> list[tuple[Item, list[Note], list[Event]]]:
    return [(item, _db_notes(conn, item.id), _db_events(conn, item.id)) for item in _db_open(conn, user_id)]


_LOG = ("id", "received_at", "kind", "content", "discord_message_id", "reply", "status", "error", "duration_s", "timing")


def _db_recent_log(conn: sqlite3.Connection, channel_id: int, limit: int = 200) -> list[dict]:
    """The channel's latest message_log rows, newest first, for rules.pick_turn."""
    rows = conn.execute(
        f"SELECT {', '.join(_LOG)} FROM message_log WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
        (channel_id, limit),
    ).fetchall()
    return [dict(zip(_LOG, row)) for row in rows]


async def add(user_id: int | None, report: rules.Report) -> int:
    """Record a new bug. Returns its number."""
    return await database.run(_db_add, user_id, report)


async def set_post(bug_id: int, thread_id: int, post_url: str) -> None:
    await database.run(_db_set_post, bug_id, thread_id, post_url)


async def get(bug_id: int) -> Item | None:
    return await database.run(_db_get, bug_id)


async def by_thread(thread_id: int) -> Item | None:
    """The bug whose forum post this is, if any."""
    return await database.run(_db_by_thread, thread_id)


async def open_for(user_id: int, channel_id: int, message_id: int) -> Item | None:
    """The open bug already reported against this message, if any."""
    return await database.run(_db_open_for, user_id, channel_id, message_id)


async def open_items(user_id: int) -> list[Item]:
    return await database.run(_db_open, user_id)


async def in_full(user_id: int) -> list[tuple[Item, list[Note], list[Event]]]:
    """Every open bug with its notes and history, for the export."""
    return await database.run(_db_in_full, user_id)


async def set_status(bug_id: int, status: str, user_id: int | None = None) -> None:
    await database.run(_db_set_status, bug_id, status, user_id)


async def events(bug_id: int) -> list[Event]:
    return await database.run(_db_events, bug_id)


async def add_note(bug_id: int, user_id: int | None, author: str, content: str, message_id: int | None = None) -> int:
    return await database.run(_db_add_note, bug_id, user_id, author, content, message_id)


async def notes(bug_id: int) -> list[Note]:
    return await database.run(_db_notes, bug_id)


async def recent_log(channel_id: int) -> list[dict]:
    return await database.run(_db_recent_log, channel_id)
