import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time

from core import clock, database
from core.errors import UserError
from core.scheduler import from_db, to_db

# ---------------------------------------------------------------------------
# The occurrence log: things expected on a day, and what became of them.
#
# An occurrence is one expected thing ("dose 2 of item 7 on 9 Oct") belonging
# to a task's item. It starts pending and ends done, skipped or missed, and it
# remembers the plan it came from (planned_time), when it is due today
# (due_at, which a task may move), when it was actually done (actual_at), and
# whether a skip was the bot's own doing and why.
#
# Nothing is ever changed without a trace: every change goes through
# db_change, which writes an event with the values before and after. Changes
# made together (a correction and what it moves) share a change id, so the
# last thing the user did can be found (db_last_change) and taken back as one
# (db_revert).
#
# The db_* functions block and take a connection, so a task can make several
# changes in one transaction (ctx.db.run / database.run). The async
# functions below them are the same, one call each.
#
# Moments are UTC; `day` is the day by core/day.py; planned_time is NZ local.
# ---------------------------------------------------------------------------
PENDING, DONE, SKIPPED, MISSED = "pending", "done", "skipped", "missed"
STATES = (PENDING, DONE, SKIPPED, MISSED)

# What a change is, for the history
CREATED, MARKED_DONE, MARKED_SKIPPED, MARKED_MISSED = "created", "done", "skipped", "missed"
REOPENED, MOVED, CORRECTED, REVERTED = "reopened", "moved", "corrected", "reverted"

# Where a change came from
BUTTON, FORM, MESSAGE, AUTOMATIC = "button", "form", "message", "automatic"

# What a change may touch
FIELDS = ("state", "due_at", "actual_at", "automatic", "reason")


@dataclass(frozen=True)
class Occurrence:
    id: int
    user_id: int
    task: str
    item_id: int
    day: date
    seq: int  # which one of the item's occurrences that day, from 1
    planned_time: time | None  # from the plan; None for one with no time
    due_at: datetime | None  # when it is due today; None while it has no time
    state: str
    actual_at: datetime | None  # when it was really done
    automatic: bool  # the bot's own doing, not the user's
    reason: str | None

    @property
    def is_pending(self) -> bool:
        return self.state == PENDING


@dataclass(frozen=True)
class Event:
    id: int
    occurrence_id: int
    change_id: str
    at: datetime
    kind: str
    source: str
    before: dict  # the fields that changed, as stored
    after: dict
    note: str | None


def new_change_id() -> str:
    """An id for changes that belong together."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, task, item_id, day, seq, planned_time, due_at, state, actual_at, automatic, reason"
_EVENT_COLUMNS = "id, occurrence_id, change_id, at, kind, source, before, after, note"


def _occurrence(row: tuple) -> Occurrence:
    return Occurrence(
        id=row[0],
        user_id=row[1],
        task=row[2],
        item_id=row[3],
        day=date.fromisoformat(row[4]),
        seq=row[5],
        planned_time=time.fromisoformat(row[6]) if row[6] else None,
        due_at=from_db(row[7]) if row[7] else None,
        state=row[8],
        actual_at=from_db(row[9]) if row[9] else None,
        automatic=bool(row[10]),
        reason=row[11],
    )


def _event(row: tuple) -> Event:
    return Event(row[0], row[1], row[2], from_db(row[3]), row[4], row[5], json.loads(row[6]), json.loads(row[7]), row[8])


def _stored(name: str, value):
    """A field's value as it is kept in the table and in an event."""
    if name not in FIELDS:
        raise ValueError(f"{name} is not a field of an occurrence that can be changed")
    if name == "state" and value not in STATES:
        raise ValueError(f"{value!r} is not a state")
    if name in ("due_at", "actual_at"):
        return to_db(value) if value is not None else None
    if name == "automatic":
        return int(bool(value))
    return value


def _add_event(conn, occurrence_id, user_id, change_id, now, kind, source, before: dict, after: dict, note) -> None:
    conn.execute(
        """
        INSERT INTO occurrence_events (occurrence_id, user_id, change_id, at, kind, source, before, after, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (occurrence_id, user_id, change_id, to_db(now), kind, source, json.dumps(before), json.dumps(after), note),
    )


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
def db_get(conn: sqlite3.Connection, occurrence_id: int) -> Occurrence | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    return _occurrence(row) if row else None


def db_ensure(
    conn: sqlite3.Connection,
    user_id: int,
    task: str,
    item_id: int,
    day: date,
    seq: int = 1,
    planned_time: time | None = None,
    due_at: datetime | None = None,
    now: datetime | None = None,
) -> Occurrence:
    """The occurrence for this item, day and number, made pending if it isn't
    there yet. One that exists is returned as it is: asking twice (a restart,
    a late job) never makes a second or resets the first."""
    now = now or clock.now()
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO occurrences
            (user_id, task, item_id, day, seq, planned_time, due_at, state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            task,
            item_id,
            day.isoformat(),
            seq,
            planned_time.strftime("%H:%M") if planned_time else None,
            to_db(due_at) if due_at else None,
            PENDING,
            to_db(now),
            to_db(now),
        ),
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM occurrences WHERE task = ? AND item_id = ? AND day = ? AND seq = ?",
        (task, item_id, day.isoformat(), seq),
    ).fetchone()
    occurrence = _occurrence(row)
    if cursor.rowcount:
        after = {"state": PENDING, "due_at": _stored("due_at", due_at)}
        _add_event(conn, occurrence.id, user_id, new_change_id(), now, CREATED, AUTOMATIC, {}, after, None)
    return occurrence


def db_for_day(
    conn: sqlite3.Connection, user_id: int, task: str, day: date, item_id: int | None = None
) -> list[Occurrence]:
    """A task's occurrences on a day, by item and number; one item's if given."""
    sql = f"SELECT {_COLUMNS} FROM occurrences WHERE user_id = ? AND task = ? AND day = ?"
    values: list = [user_id, task, day.isoformat()]
    if item_id is not None:
        sql += " AND item_id = ?"
        values.append(item_id)
    return [_occurrence(row) for row in conn.execute(sql + " ORDER BY item_id, seq", values).fetchall()]


def db_between(
    conn: sqlite3.Connection, user_id: int, task: str, first: date, last: date, item_id: int | None = None
) -> list[Occurrence]:
    """A task's occurrences from `first` to `last`, both included, oldest first."""
    sql = f"SELECT {_COLUMNS} FROM occurrences WHERE user_id = ? AND task = ? AND day BETWEEN ? AND ?"
    values: list = [user_id, task, first.isoformat(), last.isoformat()]
    if item_id is not None:
        sql += " AND item_id = ?"
        values.append(item_id)
    return [_occurrence(row) for row in conn.execute(sql + " ORDER BY day, item_id, seq", values).fetchall()]


def db_pending_before(conn: sqlite3.Connection, task: str, day: date) -> list[Occurrence]:
    """Occurrences still pending from days before `day`: what a new day finds
    left over, however many days went by."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM occurrences WHERE task = ? AND state = ? AND day < ? ORDER BY day, item_id, seq",
        (task, PENDING, day.isoformat()),
    ).fetchall()
    return [_occurrence(row) for row in rows]


def db_change(
    conn: sqlite3.Connection,
    occurrence_id: int,
    kind: str,
    source: str,
    *,
    change_id: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
    **fields,
) -> Occurrence:
    """Change an occurrence and record it. `fields` are any of FIELDS.

    Only what really differs is written and recorded; a change that changes
    nothing leaves no event. Returns the occurrence as it is afterwards.
    """
    current = db_get(conn, occurrence_id)
    if current is None:
        raise LookupError(f"There is no occurrence {occurrence_id}")
    before, after = {}, {}
    for name, value in fields.items():
        new, old = _stored(name, value), _stored(name, getattr(current, name))
        if new != old:
            before[name], after[name] = old, new
    if not after:
        return current
    now = now or clock.now()
    assignments = ", ".join(f"{name} = ?" for name in after)
    conn.execute(
        f"UPDATE occurrences SET {assignments}, updated_at = ? WHERE id = ?",
        (*after.values(), to_db(now), occurrence_id),
    )
    _add_event(conn, occurrence_id, current.user_id, change_id or new_change_id(), now, kind, source, before, after, note)
    return db_get(conn, occurrence_id)


def db_done(conn, occurrence_id: int, at: datetime, source: str, **options) -> Occurrence:
    """It was done at `at`."""
    return db_change(
        conn, occurrence_id, MARKED_DONE, source, state=DONE, actual_at=at, automatic=False, reason=None, **options
    )


def db_skip(
    conn, occurrence_id: int, source: str, automatic: bool = False, reason: str | None = None, **options
) -> Occurrence:
    """Skipped: by the user, or by the bot with a reason (`automatic`)."""
    return db_change(
        conn, occurrence_id, MARKED_SKIPPED, source,
        state=SKIPPED, actual_at=None, automatic=automatic, reason=reason, **options,
    )


def db_miss(conn, occurrence_id: int, reason: str | None = None, **options) -> Occurrence:
    """Nobody did anything about it. Always the bot's own conclusion."""
    return db_change(
        conn, occurrence_id, MARKED_MISSED, AUTOMATIC,
        state=MISSED, actual_at=None, automatic=True, reason=reason, **options,
    )


def db_reopen(conn, occurrence_id: int, source: str, **options) -> Occurrence:
    """Back to pending, as if nothing had been done about it."""
    return db_change(
        conn, occurrence_id, REOPENED, source,
        state=PENDING, actual_at=None, automatic=False, reason=None, **options,
    )


def db_move(conn, occurrence_id: int, due_at: datetime | None, source: str = AUTOMATIC, **options) -> Occurrence:
    """Today's due time changed. The plan (planned_time) never does."""
    return db_change(conn, occurrence_id, MOVED, source, due_at=due_at, **options)


def db_history(conn: sqlite3.Connection, occurrence_id: int) -> list[Event]:
    """Everything that happened to an occurrence, oldest first."""
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM occurrence_events WHERE occurrence_id = ? ORDER BY id", (occurrence_id,)
    ).fetchall()
    return [_event(row) for row in rows]


def db_last_change(conn: sqlite3.Connection, user_id: int, task: str) -> list[Event]:
    """The events of the last thing the user did to this task's occurrences
    that hasn't been taken back, oldest first. Empty if there is none.

    The bot's own changes count only as part of a change the user made (a
    correction and what it moved); a revert is never what is taken back.
    """
    row = conn.execute(
        """
        SELECT e.change_id FROM occurrence_events e
        JOIN occurrences o ON o.id = e.occurrence_id
        WHERE o.user_id = ? AND o.task = ? AND e.source != ? AND e.kind != ?
          AND e.change_id NOT IN (SELECT note FROM occurrence_events WHERE kind = ? AND note IS NOT NULL)
        ORDER BY e.id DESC LIMIT 1
        """,
        (user_id, task, AUTOMATIC, REVERTED, REVERTED),
    ).fetchone()
    if row is None:
        return []
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM occurrence_events WHERE change_id = ? ORDER BY id", (row[0],)
    ).fetchall()
    return [_event(event) for event in rows]


def db_revert(
    conn: sqlite3.Connection, change_id: str, source: str, now: datetime | None = None
) -> list[Occurrence]:
    """Take back everything one change did, newest first, as one new change.

    Refused (UserError, nothing changed) if any of it has been changed again
    since: putting old values back over newer ones would lose them.
    """
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM occurrence_events WHERE change_id = ? ORDER BY id DESC", (change_id,)
    ).fetchall()
    events = [_event(row) for row in rows]
    if not events:
        raise UserError("There is nothing to take back.")
    # Check everything before changing anything
    values: dict[int, dict] = {}
    for event in events:
        current = db_get(conn, event.occurrence_id)
        if current is None:
            raise UserError("That can't be taken back: it no longer exists.")
        held = values.setdefault(current.id, {name: _stored(name, getattr(current, name)) for name in FIELDS})
        if any(held[name] != value for name, value in event.after.items()):
            raise UserError("That can't be taken back: it has been changed again since.")
        held.update(event.before)

    now = now or clock.now()
    revert_id = new_change_id()
    reverted = []
    for event in events:
        assignments = ", ".join(f"{name} = ?" for name in event.before)
        conn.execute(
            f"UPDATE occurrences SET {assignments}, updated_at = ? WHERE id = ?",
            (*event.before.values(), to_db(now), event.occurrence_id),
        )
        user_id = conn.execute("SELECT user_id FROM occurrences WHERE id = ?", (event.occurrence_id,)).fetchone()[0]
        _add_event(
            conn, event.occurrence_id, user_id, revert_id, now, REVERTED, source, event.after, event.before, change_id
        )
        reverted.append(db_get(conn, event.occurrence_id))
    return reverted


def db_delete_item(conn: sqlite3.Connection, task: str, item_id: int) -> int:
    """Delete an item's occurrences and their history, for good. Returns how many."""
    conn.execute(
        "DELETE FROM occurrence_events WHERE occurrence_id IN (SELECT id FROM occurrences WHERE task = ? AND item_id = ?)",
        (task, item_id),
    )
    return conn.execute("DELETE FROM occurrences WHERE task = ? AND item_id = ?", (task, item_id)).rowcount


# ---------------------------------------------------------------------------
# The same, one call each, for the event loop
# ---------------------------------------------------------------------------
async def get(occurrence_id: int) -> Occurrence | None:
    return await database.run(db_get, occurrence_id)


async def ensure(
    user_id: int,
    task: str,
    item_id: int,
    day: date,
    seq: int = 1,
    planned_time: time | None = None,
    due_at: datetime | None = None,
) -> Occurrence:
    return await database.run(db_ensure, user_id, task, item_id, day, seq, planned_time, due_at)


async def for_day(user_id: int, task: str, day: date, item_id: int | None = None) -> list[Occurrence]:
    return await database.run(db_for_day, user_id, task, day, item_id)


async def history(occurrence_id: int) -> list[Event]:
    return await database.run(db_history, occurrence_id)


async def last_change(user_id: int, task: str) -> list[Event]:
    return await database.run(db_last_change, user_id, task)


async def revert(change_id: str, source: str) -> list[Occurrence]:
    return await database.run(db_revert, change_id, source)
