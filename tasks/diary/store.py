import sqlite3
from datetime import date, datetime

from core import database
from tasks.diary.rules import Entry

# ---------------------------------------------------------------------------
# The diary in the database: the only place its words are kept. One entry a
# diary day (several messages append to it), each mood with the scale it was
# recorded on. A deleted entry is gone: its words are blanked, not kept.
# One evening ask a day at most (diary_asks). Every row has a user_id.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE diary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            notes INTEGER NOT NULL DEFAULT 0,
            mood_scale TEXT,
            mood TEXT,
            scale_before TEXT,
            mood_before TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX diary_entries_day ON diary_entries (user_id, day)")
    conn.execute(
        """
        CREATE TABLE diary_asks (
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            asked_at TEXT NOT NULL,
            cleared_at TEXT,
            PRIMARY KEY (user_id, day)
        )
        """
    )


def add_undo(conn: sqlite3.Connection) -> None:
    """The entry as it was before the last message was written to it, for undo; NULL with none."""
    for column in ("undo_text TEXT", "undo_notes INTEGER", "undo_scale TEXT", "undo_mood TEXT"):
        conn.execute(f"ALTER TABLE diary_entries ADD COLUMN {column}")


MIGRATIONS = [create_tables, add_undo]

_COLUMNS = "id, user_id, day, text, mood_scale, mood, mood_before, scale_before, notes"


def _entry(row: tuple) -> Entry:
    return Entry(row[0], row[1], date.fromisoformat(row[2]), row[3], row[4], row[5], row[6], row[7], row[8])


def db_get(conn: sqlite3.Connection, user_id: int, day: date) -> Entry | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM diary_entries WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()
    return _entry(row) if row else None


def db_between(conn: sqlite3.Connection, user_id: int, first: date, last: date) -> list[Entry]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM diary_entries WHERE user_id = ? AND day BETWEEN ? AND ? ORDER BY day", (user_id, first.isoformat(), last.isoformat())).fetchall()
    return [_entry(row) for row in rows]


def db_days(conn: sqlite3.Connection, user_id: int) -> set[date]:
    return {date.fromisoformat(row[0]) for row in conn.execute("SELECT day FROM diary_entries WHERE user_id = ?", (user_id,))}


def db_append(conn: sqlite3.Connection, user_id: int, day: date, text: str, now: datetime) -> Entry:
    """Add a message's words to the day's entry, made if there is none. Returns the entry as kept.
    The entry as it was is kept for undo (`db_undo_write`), and a mood's own undo is gone."""
    there = db_get(conn, user_id, day)
    if there is None:
        conn.execute(
            "INSERT INTO diary_entries (user_id, day, text, notes, created_at, updated_at, undo_text, undo_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, day.isoformat(), text, 1 if text else 0, now.isoformat(), now.isoformat(), "" if text else None, 0 if text else None),
        )
    elif text:
        joined = f"{there.text}\n\n{text}" if there.text else text
        conn.execute(
            "UPDATE diary_entries SET undo_text = text, undo_notes = notes, undo_scale = mood_scale, undo_mood = mood, "
            "scale_before = NULL, mood_before = NULL, text = ?, notes = notes + 1, updated_at = ? WHERE id = ?",
            (joined, now.isoformat(), there.id),
        )
    return db_get(conn, user_id, day)


def db_undo_write(conn: sqlite3.Connection, user_id: int, day: date, now: datetime) -> Entry | None | bool:
    """The entry back as it was before the last message was written to it (its mood too): the entry,
    or True when there was none before and it is gone, or None with no write to undo."""
    row = conn.execute("SELECT id, undo_text, undo_notes, undo_scale, undo_mood FROM diary_entries WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()
    if row is None or row[2] is None:
        return None
    if row[2] == 0 and not row[1] and row[4] is None:
        conn.execute("DELETE FROM diary_entries WHERE id = ?", (row[0],))
        return True
    conn.execute(
        "UPDATE diary_entries SET text = undo_text, notes = undo_notes, mood_scale = undo_scale, mood = undo_mood, "
        "undo_text = NULL, undo_notes = NULL, undo_scale = NULL, undo_mood = NULL, scale_before = NULL, mood_before = NULL, updated_at = ? WHERE id = ?",
        (now.isoformat(), row[0]),
    )
    return db_get(conn, user_id, day)


def db_set_mood(conn: sqlite3.Connection, user_id: int, day: date, scale: str, key: str, now: datetime, with_words: bool = False) -> Entry:
    """The day's mood, on a scale; what it was is kept for undo. An entry is made if there is none (a mood only).
    `with_words`: said in the message just written, so undoing that write takes the mood back too."""
    there = db_get(conn, user_id, day) or db_append(conn, user_id, day, "", now)
    if not with_words:
        conn.execute("UPDATE diary_entries SET undo_text = NULL, undo_notes = NULL, undo_scale = NULL, undo_mood = NULL WHERE id = ?", (there.id,))
    if there.mood != key or there.mood_scale != scale:
        conn.execute(
            "UPDATE diary_entries SET scale_before = mood_scale, mood_before = mood, mood_scale = ?, mood = ?, updated_at = ? WHERE id = ?",
            (scale, key, now.isoformat(), there.id),
        )
    return db_get(conn, user_id, day)


def db_undo_mood(conn: sqlite3.Connection, user_id: int, day: date, now: datetime) -> Entry | None:
    """The mood back as it was before the last change. None with nothing to undo."""
    there = db_get(conn, user_id, day)
    if there is None or (there.mood_before is None and there.mood is None):
        return None
    conn.execute(
        "UPDATE diary_entries SET mood_scale = scale_before, mood = mood_before, scale_before = NULL, mood_before = NULL, updated_at = ? WHERE id = ?",
        (now.isoformat(), there.id),
    )
    return db_get(conn, user_id, day)


def db_delete(conn: sqlite3.Connection, user_id: int, day: date) -> bool:
    """The day's entry is gone, words and all. True if there was one."""
    return conn.execute("DELETE FROM diary_entries WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).rowcount > 0


def db_ask(conn: sqlite3.Connection, user_id: int, day: date) -> tuple | None:
    """(channel, message, cleared) of the day's evening ask, or None if it was not asked."""
    return conn.execute("SELECT channel_id, message_id, cleared_at FROM diary_asks WHERE user_id = ? AND day = ?", (user_id, day.isoformat())).fetchone()


def db_claim_ask(conn: sqlite3.Connection, user_id: int, day: date, now: datetime) -> bool:
    """Claim the day's one ask before it is posted: False if it was claimed already."""
    return conn.execute("INSERT OR IGNORE INTO diary_asks (user_id, day, asked_at) VALUES (?, ?, ?)", (user_id, day.isoformat(), now.isoformat())).rowcount > 0


def db_asked(conn: sqlite3.Connection, user_id: int, day: date, channel_id: int, message_id: int) -> None:
    conn.execute("UPDATE diary_asks SET channel_id = ?, message_id = ? WHERE user_id = ? AND day = ?", (channel_id, message_id, user_id, day.isoformat()))


def db_clear_ask(conn: sqlite3.Connection, user_id: int, day: date, now: datetime) -> tuple | None:
    """The ask is answered: (channel, message) of its message to take away, or None."""
    row = db_ask(conn, user_id, day)
    if row is None or row[2] is not None:
        return None
    conn.execute("UPDATE diary_asks SET cleared_at = ? WHERE user_id = ? AND day = ?", (now.isoformat(), user_id, day.isoformat()))
    return (row[0], row[1]) if row[1] else None


async def entry(user_id: int, day: date) -> Entry | None:
    return await database.run(db_get, user_id, day)
