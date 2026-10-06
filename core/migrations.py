import logging
import sqlite3
from datetime import datetime, timezone

from core.backup import snapshot_before_migration
from core.config import OWNER_ID, TIMEZONE_NAME
from core.database import connect

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Migrations
#
# The database's version is stored in PRAGMA user_version: version N means the
# first N migrations in MIGRATIONS have been applied.
#
# To change the schema, write a new function and add it to the END of the list.
# Never edit, reorder or remove a migration that has already run somewhere, and
# keep each one self-contained (plain SQL, no helpers that may change later).
# ---------------------------------------------------------------------------


def _create_message_log(conn: sqlite3.Connection) -> None:
    # IF NOT EXISTS: databases from before migrations already have this table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            discord_message_id INTEGER,
            channel_id INTEGER,
            reply TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            duration_s REAL,
            status TEXT NOT NULL,
            error TEXT
        )
        """
    )


def _create_users(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            timezone TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _add_user_id_to_message_log(conn: sqlite3.Connection) -> None:
    # Everything logged so far came from the owner, so they must exist first
    conn.execute(
        """
        INSERT OR IGNORE INTO users (discord_id, display_name, timezone, role, created_at)
        VALUES (?, 'Owner', ?, 'owner', ?)
        """,
        (OWNER_ID, TIMEZONE_NAME, datetime.now(timezone.utc).isoformat()),
    )
    owner_user_id = conn.execute(
        "SELECT id FROM users WHERE discord_id = ?", (OWNER_ID,)
    ).fetchone()[0]

    # SQLite can only add a foreign key column as nullable; the code always fills it
    conn.execute("ALTER TABLE message_log ADD COLUMN user_id INTEGER REFERENCES users(id)")
    conn.execute("UPDATE message_log SET user_id = ?", (owner_user_id,))


MIGRATIONS = [
    _create_message_log,
    _create_users,
    _add_user_id_to_message_log,
]


def migrate() -> None:
    """Apply any migrations the database hasn't had yet.

    Blocking: runs at startup, before the event loop.
    """
    conn = connect()
    try:
        # Manage transactions by hand, so schema changes can be rolled back too
        conn.isolation_level = None

        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > len(MIGRATIONS):
            raise RuntimeError(
                f"Database is at version {current} but this code only knows "
                f"{len(MIGRATIONS)} migrations. Is the code out of date?"
            )
        if current == len(MIGRATIONS):
            return

        has_tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if has_tables:
            snapshot = snapshot_before_migration(current)
            log.info("Saved %s before upgrading the database", snapshot.name)

        for version in range(current + 1, len(MIGRATIONS) + 1):
            migration = MIGRATIONS[version - 1]
            conn.execute("BEGIN IMMEDIATE")
            try:
                migration(conn)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            log.info("Applied migration %s: %s", version, migration.__name__.lstrip("_"))
    finally:
        conn.close()
