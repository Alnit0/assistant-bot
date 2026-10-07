import sqlite3
from dataclasses import asdict, dataclass, fields
from datetime import datetime

from core import database
from core.lifecycle import MessageClass
from core.scheduler import from_db, to_db, utc_now
from skills.timers.pomodoro import Plan

# ---------------------------------------------------------------------------
# Everything the timers skill remembers. All of it is in the database, so
# timers and sessions carry on after a restart. Moments are stored in UTC.
# ---------------------------------------------------------------------------
# Timer statuses
RUNNING, PAUSED, FINISHED, CANCELLED, DISMISSED = "running", "paused", "finished", "cancelled", "dismissed"
# Session states (RUNNING and PAUSED as above)
WAITING, STOPPED = "waiting", "stopped"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE timers_timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            discord_user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            notice_message_id INTEGER,
            label TEXT NOT NULL,
            duration_s INTEGER NOT NULL,
            ends_at TEXT,
            remaining_s REAL,
            status TEXT NOT NULL,
            job_id INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE timers_pomodoros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            discord_user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            notice_message_id INTEGER,
            label TEXT NOT NULL,
            focus_s INTEGER NOT NULL,
            short_s INTEGER NOT NULL,
            long_s INTEGER NOT NULL,
            rounds INTEGER NOT NULL,
            auto_continue INTEGER NOT NULL,
            phase TEXT NOT NULL,
            round INTEGER NOT NULL,
            state TEXT NOT NULL,
            ends_at TEXT,
            remaining_s REAL,
            job_id INTEGER,
            focus_rounds INTEGER NOT NULL DEFAULT 0,
            focus_seconds INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE timers_focus_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            pomodoro_id INTEGER REFERENCES timers_pomodoros(id),
            label TEXT NOT NULL,
            duration_s INTEGER NOT NULL,
            completed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE timers_boards (
            channel_id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            user_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        )
        """
    )


def add_speed_events_and_lists(conn: sqlite3.Connection) -> None:
    # The speed a clock is running at (dev mode can start one faster). It was read
    # from dev mode's setting of the moment, so a clock started at one speed and
    # paused at another gained or lost time
    conn.execute("ALTER TABLE timers_timers ADD COLUMN speed REAL NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE timers_pomodoros ADD COLUMN speed REAL NOT NULL DEFAULT 1")
    # What happened to each timer and session, and when: the answer to "what was
    # on it when I paused?"
    conn.execute(
        """
        CREATE TABLE timers_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            event TEXT NOT NULL,
            remaining_s REAL,
            detail TEXT NOT NULL DEFAULT '',
            at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX timers_events_user ON timers_events (user_id, id)")
    # The "Your timers" list: one live message per channel, like the board
    conn.execute(
        """
        CREATE TABLE timers_lists (
            channel_id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        )
        """
    )


MIGRATIONS = [
    create_tables,
    add_speed_events_and_lists,
]

# What a timers_events row is about, and what happened
TIMER, SESSION = "timer", "pomodoro"
STARTED, WAS_PAUSED, RESUMED, EXTENDED, WAS_CANCELLED, WAS_FINISHED = (
    "started", "paused", "resumed", "extended", "cancelled", "finished",
)
RESTARTED, WAS_DISMISSED, PHASE_STARTED, PHASE_FINISHED, SKIPPED, WAS_STOPPED = (
    "restarted", "dismissed", "phase started", "phase finished", "skipped", "stopped",
)


@dataclass
class Timer:
    user_id: int  # our users.id
    discord_user_id: int  # for the @mention
    channel_id: int
    label: str
    duration_s: int
    status: str = RUNNING
    ends_at: datetime | None = None  # while running
    remaining_s: float | None = None  # while paused
    message_id: int | None = None  # the timer's own message
    notice_message_id: int | None = None  # the "it's finished" message, while showing
    job_id: int | None = None
    created_at: datetime | None = None
    id: int | None = None
    speed: float = 1.0  # how fast its clock runs: 1 unless dev mode started it faster

    @property
    def active(self) -> bool:
        return self.status in (RUNNING, PAUSED)

    def left(self, now: datetime) -> float:
        """Seconds left, in the timer's own time: frozen while paused, never negative."""
        if self.status == PAUSED:
            return self.remaining_s or 0.0
        if self.status == RUNNING and self.ends_at is not None:
            return max(0.0, (self.ends_at - now).total_seconds()) * self.speed
        return 0.0


@dataclass
class Session:
    user_id: int
    discord_user_id: int
    channel_id: int
    label: str
    focus_s: int
    short_s: int
    long_s: int
    rounds: int
    auto_continue: bool
    phase: str
    round: int = 1
    state: str = RUNNING
    ends_at: datetime | None = None  # end of the current phase, while running
    remaining_s: float | None = None  # while paused
    message_id: int | None = None  # the session card
    notice_message_id: int | None = None  # the latest phase-change notice
    job_id: int | None = None
    focus_rounds: int = 0  # completed focus phases so far
    focus_seconds: int = 0
    created_at: datetime | None = None
    id: int | None = None
    speed: float = 1.0  # how fast the current phase's clock runs

    @property
    def plan(self) -> Plan:
        return Plan(self.focus_s, self.short_s, self.long_s, self.rounds)

    def left(self, now: datetime) -> float:
        """Seconds left in the current phase, in the session's own time."""
        if self.state == PAUSED:
            return self.remaining_s or 0.0
        if self.state == RUNNING and self.ends_at is not None:
            return max(0.0, (self.ends_at - now).total_seconds()) * self.speed
        return 0.0

    @property
    def active(self) -> bool:
        return self.state in (RUNNING, PAUSED, WAITING)


def message_class_of(record: Timer | Session | None, message_id: int) -> MessageClass | None:
    """What one of a timer's or session's messages is, for the lifecycle rules.

    Its notice is an Alert. Its own message is Live while it is going; once it
    has ended that message is a one-line summary, which is ordinary Kept content.
    """
    if record is None:
        return None
    if message_id == record.notice_message_id:
        return MessageClass.ALERT
    return MessageClass.LIVE if record.active else None


_MOMENTS = {"ends_at", "created_at"}
_FLAGS = {"auto_continue"}


def _names(cls) -> list[str]:
    return [field.name for field in fields(cls)]


def _to_row(record) -> dict:
    row = asdict(record)
    for name in _MOMENTS & row.keys():
        row[name] = to_db(row[name]) if row[name] is not None else None
    for name in _FLAGS & row.keys():
        row[name] = int(row[name])
    return row


def _from_row(cls, row: tuple):
    values = dict(zip(_names(cls), row))
    for name in _MOMENTS & values.keys():
        values[name] = from_db(values[name]) if values[name] is not None else None
    for name in _FLAGS & values.keys():
        values[name] = bool(values[name])
    return cls(**values)


def _insert(conn: sqlite3.Connection, table: str, record) -> int:
    row = _to_row(record)
    del row["id"]
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
        list(row.values()),
    )
    return cursor.lastrowid


def _update(conn: sqlite3.Connection, table: str, record) -> None:
    row = _to_row(record)
    record_id = row.pop("id")
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{name} = ?' for name in row)} WHERE id = ?",
        [*row.values(), record_id],
    )


def _select(conn: sqlite3.Connection, table: str, cls, where: str, values: tuple = ()) -> list:
    rows = conn.execute(
        f"SELECT {', '.join(_names(cls))} FROM {table} WHERE {where} ORDER BY id", values
    ).fetchall()
    return [_from_row(cls, row) for row in rows]


async def _add(table: str, record):
    record.created_at = utc_now()
    record.id = await database.run(_insert, table, record)
    return record


# --- timers -----------------------------------------------------------------
async def add_timer(timer: Timer) -> Timer:
    return await _add("timers_timers", timer)


async def save_timer(timer: Timer) -> None:
    await database.run(_update, "timers_timers", timer)


async def get_timer(timer_id: int) -> Timer | None:
    found = await database.run(_select, "timers_timers", Timer, "id = ?", (timer_id,))
    return found[0] if found else None


async def timer_by_message(message_id: int) -> Timer | None:
    """The timer a message belongs to: its own message, or its "finished" notice."""
    found = await database.run(
        _select, "timers_timers", Timer, "message_id = ? OR notice_message_id = ?", (message_id, message_id)
    )
    return found[-1] if found else None


async def active_timers(user_id: int | None = None, channel_id: int | None = None) -> list[Timer]:
    where, values = "status IN (?, ?)", [RUNNING, PAUSED]
    if user_id is not None:
        where, values = where + " AND user_id = ?", [*values, user_id]
    if channel_id is not None:
        where, values = where + " AND channel_id = ?", [*values, channel_id]
    return await database.run(_select, "timers_timers", Timer, where, tuple(values))


async def ended_timers(user_id: int, since: datetime, limit: int = 5) -> list[Timer]:
    """Timers started since `since` that are over (finished, dismissed or cancelled), newest first."""
    found = await database.run(
        _select,
        "timers_timers",
        Timer,
        "user_id = ? AND status IN (?, ?, ?) AND created_at >= ?",
        (user_id, FINISHED, DISMISSED, CANCELLED, to_db(since)),
    )
    return found[::-1][:limit]


# --- sessions ---------------------------------------------------------------
async def add_session(session: Session) -> Session:
    return await _add("timers_pomodoros", session)


async def save_session(session: Session) -> None:
    await database.run(_update, "timers_pomodoros", session)


async def get_session(session_id: int) -> Session | None:
    found = await database.run(_select, "timers_pomodoros", Session, "id = ?", (session_id,))
    return found[0] if found else None


async def session_by_message(message_id: int) -> Session | None:
    """The session a message belongs to: its card, or its latest notice."""
    found = await database.run(
        _select, "timers_pomodoros", Session, "message_id = ? OR notice_message_id = ?", (message_id, message_id)
    )
    return found[-1] if found else None


async def active_sessions(user_id: int | None = None, channel_id: int | None = None) -> list[Session]:
    where, values = "state IN (?, ?, ?)", [RUNNING, PAUSED, WAITING]
    if user_id is not None:
        where, values = where + " AND user_id = ?", [*values, user_id]
    if channel_id is not None:
        where, values = where + " AND channel_id = ?", [*values, channel_id]
    return await database.run(_select, "timers_pomodoros", Session, where, tuple(values))


# --- events -----------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    kind: str  # TIMER or SESSION
    record_id: int
    label: str
    event: str
    remaining_s: float | None
    detail: str
    at: datetime


def _add_event(conn: sqlite3.Connection, record, kind: str, event: str, remaining_s, detail: str) -> None:
    conn.execute(
        "INSERT INTO timers_events (user_id, kind, record_id, label, event, remaining_s, detail, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (record.user_id, kind, record.id, record.label, event, remaining_s, detail, to_db(utc_now())),
    )


async def log_event(record: Timer | Session, event: str, remaining_s: float | None = None, detail: str = "") -> None:
    """Note something that happened to a timer or session, with the time left on it then."""
    kind = TIMER if isinstance(record, Timer) else SESSION
    await database.run(_add_event, record, kind, event, remaining_s, detail)


def _events(conn: sqlite3.Connection, user_id: int, kind: str | None, record_id: int | None, limit: int) -> list[Event]:
    where, values = "user_id = ?", [user_id]
    if kind is not None:
        where, values = where + " AND kind = ? AND record_id = ?", [*values, kind, record_id]
    rows = conn.execute(
        f"SELECT kind, record_id, label, event, remaining_s, detail, at FROM timers_events WHERE {where} "
        "ORDER BY id DESC LIMIT ?",
        (*values, limit),
    ).fetchall()
    return [Event(*row[:6], from_db(row[6])) for row in rows][::-1]


async def events(user_id: int, kind: str | None = None, record_id: int | None = None, limit: int = 30) -> list[Event]:
    """The latest events, oldest first: for one timer or session, or for all of the user's."""
    return await database.run(_events, user_id, kind, record_id, limit)


# --- focus log --------------------------------------------------------------
def _log_focus(conn: sqlite3.Connection, session: Session, seconds: int) -> None:
    conn.execute(
        "INSERT INTO timers_focus_log (user_id, pomodoro_id, label, duration_s, completed_at) VALUES (?, ?, ?, ?, ?)",
        (session.user_id, session.id, session.label, seconds, to_db(utc_now())),
    )


async def log_focus(session: Session, seconds: int) -> None:
    await database.run(_log_focus, session, seconds)


def _focus_log(conn: sqlite3.Connection, user_id: int, since: datetime) -> list[tuple[datetime, str, int]]:
    rows = conn.execute(
        "SELECT completed_at, label, duration_s FROM timers_focus_log WHERE user_id = ? AND completed_at >= ? ORDER BY id",
        (user_id, to_db(since)),
    ).fetchall()
    return [(from_db(completed_at), label, seconds) for completed_at, label, seconds in rows]


async def focus_log(user_id: int, since: datetime) -> list[tuple[datetime, str, int]]:
    return await database.run(_focus_log, user_id, since)


# --- boards -----------------------------------------------------------------
def _get_board(conn: sqlite3.Connection, channel_id: int) -> int | None:
    row = conn.execute("SELECT message_id FROM timers_boards WHERE channel_id = ?", (channel_id,)).fetchone()
    return row[0] if row else None


def _save_board(conn: sqlite3.Connection, channel_id: int, message_id: int, user_id: int | None) -> None:
    conn.execute(
        """
        INSERT INTO timers_boards (channel_id, message_id, user_id, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET message_id = excluded.message_id
        """,
        (channel_id, message_id, user_id, to_db(utc_now())),
    )


def _is_board(conn: sqlite3.Connection, message_id: int) -> bool:
    return conn.execute("SELECT 1 FROM timers_boards WHERE message_id = ?", (message_id,)).fetchone() is not None


async def get_board(channel_id: int) -> int | None:
    return await database.run(_get_board, channel_id)


async def save_board(channel_id: int, message_id: int, user_id: int | None) -> None:
    await database.run(_save_board, channel_id, message_id, user_id)


async def is_board(message_id: int) -> bool:
    return await database.run(_is_board, message_id)


# --- "Your timers" lists -----------------------------------------------------
def _lists(conn: sqlite3.Connection, user_id: int) -> list[tuple[int, int]]:
    return conn.execute("SELECT channel_id, message_id FROM timers_lists WHERE user_id = ?", (user_id,)).fetchall()


def _save_list(conn: sqlite3.Connection, channel_id: int, message_id: int, user_id: int) -> None:
    conn.execute(
        """
        INSERT INTO timers_lists (channel_id, message_id, user_id, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET message_id = excluded.message_id, user_id = excluded.user_id
        """,
        (channel_id, message_id, user_id, to_db(utc_now())),
    )


def _forget_list(conn: sqlite3.Connection, channel_id: int) -> None:
    conn.execute("DELETE FROM timers_lists WHERE channel_id = ?", (channel_id,))


def _is_list(conn: sqlite3.Connection, message_id: int) -> bool:
    return conn.execute("SELECT 1 FROM timers_lists WHERE message_id = ?", (message_id,)).fetchone() is not None


async def lists(user_id: int) -> list[tuple[int, int]]:
    """The user's live "Your timers" lists, as (channel id, message id)."""
    return await database.run(_lists, user_id)


async def save_list(channel_id: int, message_id: int, user_id: int) -> None:
    await database.run(_save_list, channel_id, message_id, user_id)


async def forget_list(channel_id: int) -> None:
    await database.run(_forget_list, channel_id)


async def is_list(message_id: int) -> bool:
    return await database.run(_is_list, message_id)
