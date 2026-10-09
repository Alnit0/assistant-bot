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


def _add_timing_to_message_log(conn: sqlite3.Connection) -> None:
    # Where the time went while a chat message was answered, as JSON (core/timing.py)
    conn.execute("ALTER TABLE message_log ADD COLUMN timing TEXT")


def _create_occurrences(conn: sqlite3.Connection) -> None:
    # Things expected on a day and what became of them (see core/occurrences.py).
    # Moments are UTC; day is the day by core/day.py; planned_time is NZ local
    conn.execute(
        """
        CREATE TABLE occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            task TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            seq INTEGER NOT NULL DEFAULT 1,
            planned_time TEXT,
            due_at TEXT,
            state TEXT NOT NULL,
            actual_at TEXT,
            automatic INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (task, item_id, day, seq)
        )
        """
    )
    conn.execute("CREATE INDEX occurrences_day ON occurrences (user_id, task, day)")
    # Every change to one, with the values before and after as JSON. Changes made
    # together share a change_id; a revert's note is the change_id it took back
    conn.execute(
        """
        CREATE TABLE occurrence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurrence_id INTEGER NOT NULL REFERENCES occurrences(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            change_id TEXT NOT NULL,
            at TEXT NOT NULL,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            before TEXT NOT NULL DEFAULT '{}',
            after TEXT NOT NULL DEFAULT '{}',
            note TEXT
        )
        """
    )
    conn.execute("CREATE INDEX occurrence_events_occurrence ON occurrence_events (occurrence_id)")
    conn.execute("CREATE INDEX occurrence_events_change ON occurrence_events (change_id)")


def _add_cost_logging(conn: sqlite3.Connection) -> None:
    # How each message was handled and what it cost (see core/costs.py). The
    # token and cost columns were only ever filled for chat; they now hold the
    # total of every request made for the message
    conn.execute("ALTER TABLE message_log ADD COLUMN route TEXT")
    conn.execute("ALTER TABLE message_log ADD COLUMN tasks TEXT")
    conn.execute("ALTER TABLE message_log ADD COLUMN claude_calls INTEGER")
    conn.execute("ALTER TABLE message_log ADD COLUMN cache_read_tokens INTEGER")
    conn.execute("ALTER TABLE message_log ADD COLUMN cache_write_tokens INTEGER")
    conn.execute("CREATE INDEX message_log_received ON message_log (received_at)")
    # One row per request to Claude: what it was for, its tokens, cost and time
    conn.execute(
        """
        CREATE TABLE llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_log_id INTEGER REFERENCES message_log(id),
            at TEXT NOT NULL,
            purpose TEXT NOT NULL,
            task TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL,
            seconds REAL,
            retries INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX llm_calls_at ON llm_calls (at)")

    # What is already logged gets a route too, so "before" can be measured.
    # Chat that ran tools was recorded with "[tools: …]" after its reply
    conn.execute(
        """
        UPDATE message_log SET route = CASE
            WHEN kind IN ('tool', 'undo') THEN NULL
            WHEN kind = 'chat' AND reply LIKE '%[tools:%' THEN 'tools'
            WHEN kind = 'chat' AND status = 'ok' THEN 'tools'
            WHEN kind = 'chat' THEN 'chat'
            WHEN kind IN ('command', 'reply_action', 'expected', 'claimed', 'slash', 'context_menu') THEN 'shortcut'
            WHEN kind = 'reaction' THEN 'reaction'
            ELSE 'button'
        END
        """
    )
    # The requests and cache tokens of each chat message, from its stored timings
    conn.execute(
        """
        UPDATE message_log SET
            claude_calls = json_array_length(timing, '$.claude'),
            cache_read_tokens = (SELECT COALESCE(SUM(json_extract(value, '$.cache_read_tokens')), 0)
                                 FROM json_each(message_log.timing, '$.claude')),
            cache_write_tokens = (SELECT COALESCE(SUM(json_extract(value, '$.cache_write_tokens')), 0)
                                  FROM json_each(message_log.timing, '$.claude'))
        WHERE kind = 'chat' AND timing IS NOT NULL AND json_valid(timing)
        """
    )


def _create_confirm_cards(conn: sqlite3.Connection) -> None:
    # Confirm cards waiting for Save, and the question asked on a tie between
    # tasks (see core/confirm.py). `data` is exactly what Save applies
    conn.execute(
        """
        CREATE TABLE confirm_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            kind TEXT NOT NULL,
            task TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '{}',
            guessed TEXT NOT NULL DEFAULT '[]',
            said TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            job_id INTEGER,
            created_at TEXT NOT NULL,
            closed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX confirm_cards_open ON confirm_cards (user_id, channel_id, status)")
    conn.execute("CREATE INDEX confirm_cards_message ON confirm_cards (message_id)")
    # What extraction made of a message, as JSON: the task, the action, its data and what was guessed
    conn.execute("ALTER TABLE message_log ADD COLUMN extracted TEXT")


def _create_live_lists(conn: sqlite3.Connection) -> None:
    # The latest copy of each list a user asked to see: the one kept up to date
    # in place when its data changes (see core/livelists.py)
    conn.execute(
        """
        CREATE TABLE live_lists (
            user_id INTEGER NOT NULL REFERENCES users(id),
            key TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, key)
        )
        """
    )
    conn.execute("CREATE INDEX live_lists_message ON live_lists (message_id)")


def _add_task_to_live_lists(conn: sqlite3.Connection) -> None:
    # Which task a list belongs to and when it was shown: a message straight
    # after a list is for that list's task (see core/livelists.py)
    conn.execute("ALTER TABLE live_lists ADD COLUMN task TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE live_lists ADD COLUMN shown_at TEXT")


def _add_previous_to_confirm_cards(conn: sqlite3.Connection) -> None:
    # What a card's data was before the change that made this card (JSON), so a
    # "No, …" straight after can undo that change before applying the correction
    conn.execute("ALTER TABLE confirm_cards ADD COLUMN previous TEXT")


MIGRATIONS = [
    _create_message_log,
    _create_users,
    _add_user_id_to_message_log,
    _create_skill_migrations,
    _create_scheduled_jobs,
    _create_reaction_state,
    _add_timing_to_message_log,
    _create_occurrences,
    _add_cost_logging,
    _create_confirm_cards,
    _create_live_lists,
    _add_task_to_live_lists,
    _add_previous_to_confirm_cards,
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
