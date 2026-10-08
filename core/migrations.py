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
#
# Tasks have their own lists (Task.migrations()), tracked separately per task
# in the skill_migrations table and applied after the core ones.
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


def _create_skill_migrations(conn: sqlite3.Connection) -> None:
    # How many of each task's own migrations have been applied
    conn.execute(
        """
        CREATE TABLE skill_migrations (
            skill TEXT PRIMARY KEY,
            version INTEGER NOT NULL
        )
        """
    )


def _create_scheduled_jobs(conn: sqlite3.Connection) -> None:
    # Things to do at a moment in the future (see core/scheduler.py). Moments are UTC.
    conn.execute(
        """
        CREATE TABLE scheduled_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            skill TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            due_at TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            late_by_s REAL,
            error TEXT
        )
        """
    )
    conn.execute("CREATE INDEX scheduled_jobs_due ON scheduled_jobs (status, due_at)")


def _create_reaction_state(conn: sqlite3.Connection) -> None:
    # Which reaction actions are currently applied, so removing the reaction can undo them
    conn.execute(
        """
        CREATE TABLE reaction_state (
            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            applied_at TEXT NOT NULL,
            PRIMARY KEY (message_id, emoji, user_id)
        )
        """
    )


MIGRATIONS = [
    _create_message_log,
    _create_users,
    _add_user_id_to_message_log,
    _create_skill_migrations,
    _create_scheduled_jobs,
    _create_reaction_state,
]


def _apply(conn: sqlite3.Connection, migration, record_sql: str, record_values: tuple = ()) -> None:
    """Run one migration and record its new version, together or not at all."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        migration(conn)
        conn.execute(record_sql, record_values)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _task_versions(conn: sqlite3.Connection) -> dict[str, int]:
    # The table itself arrives with core migration 4
    exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'skill_migrations'"
    ).fetchone()[0]
    if not exists:
        return {}
    return dict(conn.execute("SELECT skill, version FROM skill_migrations").fetchall())


def migrate(task_migrations: dict[str, list] | None = None) -> None:
    """Apply any core and task migrations the database hasn't had yet.

    task_migrations maps each loaded task's name to its ordered list of
    migrations. Blocking: runs at startup, before the event loop.
    """
    task_migrations = task_migrations or {}
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
        task_versions = _task_versions(conn)
        for name, migrations in task_migrations.items():
            if task_versions.get(name, 0) > len(migrations):
                raise RuntimeError(
                    f"Task {name} is at version {task_versions[name]} in the database but "
                    f"its code only has {len(migrations)} migrations. Is the code out of date?"
                )

        pending = current < len(MIGRATIONS) or any(
            task_versions.get(name, 0) < len(migrations)
            for name, migrations in task_migrations.items()
        )
        if not pending:
            return

        has_tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if has_tables:
            snapshot = snapshot_before_migration(current)
            log.info("Saved %s before upgrading the database", snapshot.name)

        for version in range(current + 1, len(MIGRATIONS) + 1):
            migration = MIGRATIONS[version - 1]
            _apply(conn, migration, f"PRAGMA user_version = {version}")
            log.info("Applied migration %s: %s", version, migration.__name__.lstrip("_"))

        for name, migrations in task_migrations.items():
            for version in range(task_versions.get(name, 0) + 1, len(migrations) + 1):
                migration = migrations[version - 1]
                _apply(
                    conn,
                    migration,
                    """
                    INSERT INTO skill_migrations (skill, version) VALUES (?, ?)
                    ON CONFLICT(skill) DO UPDATE SET version = excluded.version
                    """,
                    (name, version),
                )
                log.info(
                    "Applied %s migration %s: %s", name, version, migration.__name__.lstrip("_")
                )
    finally:
        conn.close()
