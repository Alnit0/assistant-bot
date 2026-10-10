import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time

from core import database
from core.schedule import Schedule
from core.scheduler import to_db, utc_now
from tasks.pills.rules import ACTIVE, PAUSED, REMOVED, Pill, Plan


CREATED, EDITED, WAS_PAUSED, RESUMED, WAS_REMOVED = "created", "edited", "paused", "resumed", "removed"


def create_tables(conn: sqlite3.Connection) -> None:
    # Dates and times are NZ local, as the user gave them; moments are UTC
    conn.execute(
        """
        CREATE TABLE pills_pills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            dose TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            times TEXT NOT NULL DEFAULT '[]',
            per_day INTEGER NOT NULL DEFAULT 1,
            gap_minutes INTEGER,
            start_date TEXT,
            end_date TEXT,
            status TEXT NOT NULL,
            paused_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX pills_pills_user ON pills_pills (user_id, status)")
    conn.execute(
        """
        CREATE TABLE pills_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            pill_id INTEGER REFERENCES pills_pills(id),
            request TEXT NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            job_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pills_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            pill_id INTEGER NOT NULL,
            at TEXT NOT NULL,
            kind TEXT NOT NULL,
            before TEXT,
            after TEXT
        )
        """
    )


def one_schedule_model(conn: sqlite3.Connection) -> None:
    # One shape of schedule for every pill (core/schedule.py): the kind of
    # schedule is no longer a thing of its own, and a pill may have a latest
    # time of day (NZ local, HH:MM). The other columns mean what they did
    conn.execute("ALTER TABLE pills_pills ADD COLUMN latest_time TEXT")
    conn.execute("ALTER TABLE pills_pills DROP COLUMN kind")


def checklist_messages(conn: sqlite3.Connection) -> None:
    # Where today's checklist is, and the message of its own that each dose
    # with no time has under it, so both are found again after a restart
    conn.execute(
        """
        CREATE TABLE pills_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            kind TEXT NOT NULL,
            occurrence_id INTEGER,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX pills_messages_day ON pills_messages (user_id, day)")


MIGRATIONS = [
    create_tables,
    one_schedule_model,
    checklist_messages,
]


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, name, dose, notes, times, per_day, gap_minutes, latest_time, start_date, end_date, status, paused_until"


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _pill(row: tuple) -> Pill:
    plan = Plan(
        name=row[2],
        dose=row[3],
        notes=row[4],
        schedule=Schedule(
            per_day=row[6],
            times=tuple(time.fromisoformat(value) for value in json.loads(row[5])),
            gap_minutes=row[7],
            latest=time.fromisoformat(row[8]) if row[8] else None,
        ),
        start=_day(row[9]),
        end=_day(row[10]),
    )
    return Pill(id=row[0], user_id=row[1], plan=plan, status=row[11], paused_until=_day(row[12]))


def _plan_values(plan: Plan) -> tuple:
    return (
        plan.name,
        plan.dose,
        plan.notes,
        json.dumps([value.strftime("%H:%M") for value in plan.schedule.times]),
        plan.schedule.per_day,
        plan.schedule.gap_minutes,
        plan.schedule.latest.strftime("%H:%M") if plan.schedule.latest else None,
        plan.start.isoformat() if plan.start else None,
        plan.end.isoformat() if plan.end else None,
    )


def plan_json(plan: Plan | None) -> str | None:
    """A plan as kept in pills_changes."""
    if plan is None:
        return None
    names = ("name", "dose", "notes", "times", "per_day", "gap_minutes", "latest", "start", "end")
    return json.dumps(dict(zip(names, _plan_values(plan))))


def _record(conn, user_id: int, pill_id: int, kind: str, before: Plan | None, after: Plan | None, now: datetime) -> None:
    conn.execute(
        "INSERT INTO pills_changes (user_id, pill_id, at, kind, before, after) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, pill_id, to_db(now), kind, plan_json(before), plan_json(after)),
    )


# ---------------------------------------------------------------------------
# Pills (blocking)
# ---------------------------------------------------------------------------
def db_pills(conn: sqlite3.Connection, user_id: int, include_removed: bool = False) -> list[Pill]:
    sql = f"SELECT {_COLUMNS} FROM pills_pills WHERE user_id = ?"
    if not include_removed:
        sql += f" AND status != '{REMOVED}'"
    return [_pill(row) for row in conn.execute(sql + " ORDER BY id", (user_id,)).fetchall()]


def db_all_pills(conn: sqlite3.Connection) -> list[Pill]:
    """Every user's pills that haven't been removed, for work nobody asked for (jobs)."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM pills_pills WHERE status != ? ORDER BY id", (REMOVED,)).fetchall()
    return [_pill(row) for row in rows]


def db_pill(conn: sqlite3.Connection, pill_id: int) -> Pill | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM pills_pills WHERE id = ?", (pill_id,)).fetchone()
    return _pill(row) if row else None


def db_add(conn: sqlite3.Connection, user_id: int, plan: Plan, now: datetime | None = None) -> Pill:
    now = now or utc_now()
    cursor = conn.execute(
        """
        INSERT INTO pills_pills
            (user_id, name, dose, notes, times, per_day, gap_minutes, latest_time, start_date, end_date,
             status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, *_plan_values(plan), ACTIVE, to_db(now), to_db(now)),
    )
    _record(conn, user_id, cursor.lastrowid, CREATED, None, plan, now)
    return db_pill(conn, cursor.lastrowid)


def db_edit(conn: sqlite3.Connection, pill_id: int, plan: Plan, now: datetime | None = None) -> Pill:
    """Replace a pill's plan. What has been recorded about past doses is not touched."""
    now = now or utc_now()
    old = db_pill(conn, pill_id)
    conn.execute(
        """
        UPDATE pills_pills
        SET name = ?, dose = ?, notes = ?, times = ?, per_day = ?, gap_minutes = ?, latest_time = ?,
            start_date = ?, end_date = ?, updated_at = ?
        WHERE id = ?
        """,
        (*_plan_values(plan), to_db(now), pill_id),
    )
    _record(conn, old.user_id, pill_id, EDITED, old.plan, plan, now)
    return db_pill(conn, pill_id)


def db_set_status(
    conn: sqlite3.Connection, pill_id: int, status: str, paused_until: date | None = None, now: datetime | None = None
) -> Pill:
    """Pause (optionally until a day), resume or remove a pill. Its history is kept."""
    now = now or utc_now()
    old = db_pill(conn, pill_id)
    conn.execute(
        "UPDATE pills_pills SET status = ?, paused_until = ?, updated_at = ? WHERE id = ?",
        (status, paused_until.isoformat() if status == PAUSED and paused_until else None, to_db(now), pill_id),
    )
    kind = {PAUSED: WAS_PAUSED, ACTIVE: RESUMED, REMOVED: WAS_REMOVED}[status]
    _record(conn, old.user_id, pill_id, kind, old.plan, old.plan, now)
    return db_pill(conn, pill_id)


# ---------------------------------------------------------------------------
# The checklist's messages (blocking)
# ---------------------------------------------------------------------------
CHECKLIST, DOSE = "checklist", "dose"


@dataclass(frozen=True)
class Message:
    user_id: int
    day: date
    kind: str  # CHECKLIST, or DOSE for the message of one dose with no time
    occurrence_id: int | None  # the dose, for a DOSE message
    channel_id: int
    message_id: int


_MESSAGE_COLUMNS = "user_id, day, kind, occurrence_id, channel_id, message_id"


def _message(row: tuple) -> Message:
    return Message(row[0], date.fromisoformat(row[1]), row[2], row[3], row[4], row[5])


def db_messages(conn: sqlite3.Connection, user_id: int, day: date) -> list[Message]:
    rows = conn.execute(
        f"SELECT {_MESSAGE_COLUMNS} FROM pills_messages WHERE user_id = ? AND day = ? ORDER BY id", (user_id, day.isoformat())
    ).fetchall()
    return [_message(row) for row in rows]


def db_messages_before(conn: sqlite3.Connection, day: date) -> list[Message]:
    """Every user's messages from days before `day`, oldest first."""
    rows = conn.execute(f"SELECT {_MESSAGE_COLUMNS} FROM pills_messages WHERE day < ? ORDER BY id", (day.isoformat(),)).fetchall()
    return [_message(row) for row in rows]


def db_add_message(
    conn: sqlite3.Connection, user_id: int, day: date, kind: str, occurrence_id: int | None, channel_id: int, message_id: int
) -> None:
    conn.execute(
        "INSERT INTO pills_messages (user_id, day, kind, occurrence_id, channel_id, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, day.isoformat(), kind, occurrence_id, channel_id, message_id, to_db(utc_now())),
    )


def db_drop_message(conn: sqlite3.Connection, message_id: int) -> None:
    conn.execute("DELETE FROM pills_messages WHERE message_id = ?", (message_id,))


def db_users(conn: sqlite3.Connection) -> list[int]:
    """The users who have a pill that hasn't been removed."""
    return [row[0] for row in conn.execute("SELECT DISTINCT user_id FROM pills_pills WHERE status != ? ORDER BY user_id", (REMOVED,))]


def db_delete(conn: sqlite3.Connection, pill_id: int) -> None:
    """Delete a pill and the record of its changes, for good. Its doses are the
    occurrence log's to delete (occurrences.db_delete_item), in the same transaction."""
    conn.execute("DELETE FROM pills_drafts WHERE pill_id = ?", (pill_id,))
    conn.execute("DELETE FROM pills_changes WHERE pill_id = ?", (pill_id,))
    conn.execute("DELETE FROM pills_pills WHERE id = ?", (pill_id,))


def db_changes(conn: sqlite3.Connection, pill_id: int) -> list[tuple[str, str, str | None, str | None]]:
    """(when, kind, plan before, plan after) for a pill, oldest first."""
    return conn.execute(
        "SELECT at, kind, before, after FROM pills_changes WHERE pill_id = ? ORDER BY id", (pill_id,)
    ).fetchall()


# ---------------------------------------------------------------------------
# The same, one call each, for the event loop
# ---------------------------------------------------------------------------
def db_last_changed(conn: sqlite3.Connection, user_id: int) -> int | None:
    """The pill the user changed last (added, edited, paused…), if it is still there."""
    found = conn.execute(
        """
        SELECT c.pill_id FROM pills_changes c JOIN pills_pills p ON p.id = c.pill_id
        WHERE c.user_id = ? AND p.status != 'removed' ORDER BY c.id DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return found[0] if found else None


def db_message_kind(conn: sqlite3.Connection, message_id: int) -> str | None:
    found = conn.execute("SELECT kind FROM pills_messages WHERE message_id = ?", (message_id,)).fetchone()
    return found[0] if found else None


async def message_kind(message_id: int) -> str | None:
    """CHECKLIST or DOSE if this is one of the checklist's messages, else None."""
    return await database.run(db_message_kind, message_id)


async def pills(user_id: int) -> list[Pill]:
    return await database.run(db_pills, user_id)


async def pill(pill_id: int) -> Pill | None:
    return await database.run(db_pill, pill_id)


async def set_status(pill_id: int, status: str, paused_until: date | None = None) -> Pill:
    return await database.run(db_set_status, pill_id, status, paused_until)

