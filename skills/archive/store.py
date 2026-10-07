import sqlite3
from dataclasses import dataclass
from datetime import datetime

from core import database
from core.scheduler import from_db, to_db, utc_now

# ---------------------------------------------------------------------------
# Where each archived copy came from, so it can be restored (even after a
# restart). No Discord in here: plain values in, plain values out.
# ---------------------------------------------------------------------------


def create_items(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE archive_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            original_channel_id INTEGER NOT NULL,
            original_message_id INTEGER NOT NULL,
            archive_channel_id INTEGER NOT NULL,
            archive_message_id INTEGER,
            button_message_id INTEGER,
            author_name TEXT NOT NULL,
            author_avatar_url TEXT,
            original_created_at TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            restored_at TEXT
        )
        """
    )


MIGRATIONS = [
    create_items,
]


@dataclass
class Item:
    id: int
    user_id: int | None
    original_channel_id: int
    original_message_id: int
    archive_channel_id: int
    archive_message_id: int | None
    button_message_id: int | None
    author_name: str
    author_avatar_url: str | None
    original_created_at: datetime


def _db_create(
    conn: sqlite3.Connection,
    user_id: int | None,
    original_channel_id: int,
    original_message_id: int,
    archive_channel_id: int,
    author_name: str,
    author_avatar_url: str | None,
    original_created_at: datetime,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO archive_items (user_id, original_channel_id, original_message_id, archive_channel_id,
                                   author_name, author_avatar_url, original_created_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            original_channel_id,
            original_message_id,
            archive_channel_id,
            author_name,
            author_avatar_url,
            to_db(original_created_at),
            to_db(utc_now()),
        ),
    )
    return cursor.lastrowid


def _db_set_copy(conn: sqlite3.Connection, item_id: int, archive_message_id: int, button_message_id) -> None:
    conn.execute(
        "UPDATE archive_items SET archive_message_id = ?, button_message_id = ? WHERE id = ?",
        (archive_message_id, button_message_id, item_id),
    )


def _db_discard(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM archive_items WHERE id = ?", (item_id,))


def _db_restored(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE archive_items SET restored_at = ? WHERE id = ?", (to_db(utc_now()), item_id))


def _db_get(conn: sqlite3.Connection, item_id: int) -> Item | None:
    row = conn.execute(
        """
        SELECT id, user_id, original_channel_id, original_message_id, archive_channel_id, archive_message_id,
               button_message_id, author_name, author_avatar_url, original_created_at
        FROM archive_items WHERE id = ? AND restored_at IS NULL
        """,
        (item_id,),
    ).fetchone()
    return Item(*row[:9], from_db(row[9])) if row else None


def _db_by_original(conn: sqlite3.Connection, original_message_id: int) -> Item | None:
    row = conn.execute(
        "SELECT id FROM archive_items WHERE original_message_id = ? AND restored_at IS NULL ORDER BY id DESC LIMIT 1",
        (original_message_id,),
    ).fetchone()
    return _db_get(conn, row[0]) if row else None


def _db_describe(conn: sqlite3.Connection, message_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT id, original_channel_id, archive_channel_id, archived_at, restored_at
        FROM archive_items
        WHERE original_message_id = ? OR archive_message_id = ? OR button_message_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (message_id, message_id, message_id),
    ).fetchone()
    if row is None:
        return None
    item_id, original_channel_id, archive_channel_id, archived_at, restored_at = row
    text = (
        f"item {item_id}: from <#{original_channel_id}> to <#{archive_channel_id}>, "
        f"archived <t:{int(from_db(archived_at).timestamp())}:R>"
    )
    if restored_at:
        text += f", restored <t:{int(from_db(restored_at).timestamp())}:R>"
    return text


# ---------------------------------------------------------------------------
# For the rest of the skill (async: each runs in a worker thread)
# ---------------------------------------------------------------------------
async def add(
    user_id: int | None,
    original_channel_id: int,
    original_message_id: int,
    archive_channel_id: int,
    author_name: str,
    author_avatar_url: str | None,
    original_created_at: datetime,
) -> int:
    """Record a message that is about to be archived. Returns the record's id."""
    return await database.run(
        _db_create,
        user_id,
        original_channel_id,
        original_message_id,
        archive_channel_id,
        author_name,
        author_avatar_url,
        original_created_at,
    )


async def set_copy(item_id: int, archive_message_id: int, button_message_id: int | None) -> None:
    """Note where the archived copy (and its Restore button, if separate) ended up."""
    await database.run(_db_set_copy, item_id, archive_message_id, button_message_id)


async def discard(item_id: int) -> None:
    """Forget a record whose copy was never made."""
    await database.run(_db_discard, item_id)


async def mark_restored(item_id: int) -> None:
    await database.run(_db_restored, item_id)


async def get(item_id: int) -> Item | None:
    """A record that can still be restored, or None (unknown, or already restored)."""
    return await database.run(_db_get, item_id)


async def by_original(original_message_id: int) -> Item | None:
    """The record for a message that was archived and can still be restored, by the original's id."""
    return await database.run(_db_by_original, original_message_id)


async def describe_record(message_id: int) -> str | None:
    """The archive record a message belongs to (as the original or as the copy), in a line."""
    return await database.run(_db_describe, message_id)
