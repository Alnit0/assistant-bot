import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, time

from core import database
from core.scheduler import to_db, utc_now
from tasks.pills.rules import ACTIVE, PAUSED, REMOVED, Pill, Plan, Request

# ---------------------------------------------------------------------------
# What the pills task remembers. No Discord in here: plain values in and out.
#
#   pills_pills    each pill and its plan
#   pills_drafts   a preview waiting for Save: what was asked for, in the
#                  user's words, and the message showing it. Kept in the
#                  database so the buttons work after a restart
#   pills_changes  every change to a plan or a status, with the plan before
#                  and after: the plan never changes without a trace
#
# Doses are not here: they are occurrences (core/occurrences.py) under the
# task name "pills", with the pill's id as the item.
#
# The db_* functions block and take a connection; the async ones below them
# are one call each.
# ---------------------------------------------------------------------------
DRAFT_PREFIX = "d"

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


MIGRATIONS = [
    create_tables,
]


@dataclass(frozen=True)
class Draft:
    id: int
    user_id: int
    pill_id: int | None  # the pill being edited; None for a new one
    request: Request
    channel_id: int | None
    message_id: int | None
    job_id: int | None  # the job that lets it lapse
    created_at: datetime

    @property
    def ref(self) -> str:
        return f"{DRAFT_PREFIX}{self.id}"


def draft_id(ref: str) -> int | None:
    """The id in "d5" (or "5"), or None if it isn't one."""
    text = ref.strip().lower().removeprefix(DRAFT_PREFIX)
    return int(text) if text.isdigit() else None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, name, dose, notes, kind, times, per_day, gap_minutes, start_date, end_date, status, paused_until"
_DRAFT_COLUMNS = "id, user_id, pill_id, request, channel_id, message_id, job_id, created_at"


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _pill(row: tuple) -> Pill:
    plan = Plan(
        name=row[2],
        dose=row[3],
        notes=row[4],
        kind=row[5],
        times=tuple(time.fromisoformat(value) for value in json.loads(row[6])),
        per_day=row[7],
        gap_minutes=row[8],
        start=_day(row[9]),
        end=_day(row[10]),
    )
    return Pill(id=row[0], user_id=row[1], plan=plan, status=row[11], paused_until=_day(row[12]))


def _plan_values(plan: Plan) -> tuple:
    return (
        plan.name,
        plan.dose,
        plan.notes,
        plan.kind,
        json.dumps([value.strftime("%H:%M") for value in plan.times]),
        plan.per_day,
        plan.gap_minutes,
        plan.start.isoformat() if plan.start else None,
        plan.end.isoformat() if plan.end else None,
    )


def plan_json(plan: Plan | None) -> str | None:
    """A plan as kept in pills_changes."""
    if plan is None:
        return None
    names = ("name", "dose", "notes", "kind", "times", "per_day", "gap_minutes", "start", "end")
    return json.dumps(dict(zip(names, _plan_values(plan))))


def _draft(row: tuple) -> Draft:
    return Draft(row[0], row[1], row[2], Request(**json.loads(row[3])), row[4], row[5], row[6], datetime.fromisoformat(row[7]))


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
            (user_id, name, dose, notes, kind, times, per_day, gap_minutes, start_date, end_date,
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
        SET name = ?, dose = ?, notes = ?, kind = ?, times = ?, per_day = ?, gap_minutes = ?,
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
# Drafts (blocking)
# ---------------------------------------------------------------------------
def db_draft(conn: sqlite3.Connection, draft_id: int) -> Draft | None:
    row = conn.execute(f"SELECT {_DRAFT_COLUMNS} FROM pills_drafts WHERE id = ?", (draft_id,)).fetchone()
    return _draft(row) if row else None


def db_drafts(conn: sqlite3.Connection, user_id: int) -> list[Draft]:
    rows = conn.execute(f"SELECT {_DRAFT_COLUMNS} FROM pills_drafts WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    return [_draft(row) for row in rows]


def db_draft_for_pill(conn: sqlite3.Connection, pill_id: int) -> Draft | None:
    row = conn.execute(
        f"SELECT {_DRAFT_COLUMNS} FROM pills_drafts WHERE pill_id = ? ORDER BY id DESC LIMIT 1", (pill_id,)
    ).fetchone()
    return _draft(row) if row else None


def db_draft_by_message(conn: sqlite3.Connection, message_id: int) -> Draft | None:
    row = conn.execute(f"SELECT {_DRAFT_COLUMNS} FROM pills_drafts WHERE message_id = ?", (message_id,)).fetchone()
    return _draft(row) if row else None


def db_add_draft(
    conn: sqlite3.Connection, user_id: int, pill_id: int | None, request: Request, now: datetime | None = None
) -> Draft:
    cursor = conn.execute(
        "INSERT INTO pills_drafts (user_id, pill_id, request, created_at) VALUES (?, ?, ?, ?)",
        (user_id, pill_id, json.dumps(asdict(request)), to_db(now or utc_now())),
    )
    return db_draft(conn, cursor.lastrowid)


def db_update_draft(conn: sqlite3.Connection, draft_id: int, **values) -> Draft | None:
    """Set any of request, channel_id, message_id, job_id on a draft."""
    if "request" in values:
        values["request"] = json.dumps(asdict(values["request"]))
    unknown = set(values) - {"request", "channel_id", "message_id", "job_id"}
    if unknown:
        raise ValueError(f"Not a draft's to set: {sorted(unknown)}")
    assignments = ", ".join(f"{name} = ?" for name in values)
    conn.execute(f"UPDATE pills_drafts SET {assignments} WHERE id = ?", (*values.values(), draft_id))
    return db_draft(conn, draft_id)


def db_discard_draft(conn: sqlite3.Connection, draft_id: int) -> bool:
    return conn.execute("DELETE FROM pills_drafts WHERE id = ?", (draft_id,)).rowcount == 1


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


async def pills(user_id: int) -> list[Pill]:
    return await database.run(db_pills, user_id)


async def pill(pill_id: int) -> Pill | None:
    return await database.run(db_pill, pill_id)


async def set_status(pill_id: int, status: str, paused_until: date | None = None) -> Pill:
    return await database.run(db_set_status, pill_id, status, paused_until)


async def draft(draft_id: int) -> Draft | None:
    return await database.run(db_draft, draft_id)


async def drafts(user_id: int) -> list[Draft]:
    return await database.run(db_drafts, user_id)


async def add_draft(user_id: int, pill_id: int | None, request: Request) -> Draft:
    return await database.run(db_add_draft, user_id, pill_id, request)


async def update_draft(draft_id: int, **values) -> Draft | None:
    return await database.run(lambda conn: db_update_draft(conn, draft_id, **values))


async def discard_draft(draft_id: int) -> bool:
    return await database.run(db_discard_draft, draft_id)
