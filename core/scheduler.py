import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from time import perf_counter

from core import clock, database, devmode
from core.config import TIMEZONE
from core.discord_utils import log_error

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Scheduler
#
# Jobs live in the scheduled_jobs table, so they survive a restart. A task
# adds a job ("call my handler for kind X at this moment, with this payload")
# and registers a handler for each kind it uses. One loop looks for due jobs
# every TICK_SECONDS, and also wakes at the exact moment of the next due job
# when that is sooner, so short timers fire on time.
#
# Jobs that came due while the bot was off run at the next start, with
# job.late_by saying how overdue they are.
#
# The time is the clock's (core/clock.py), so jobs follow the dev clock. When
# that is moved ahead, everything that came due on the way runs at once, in
# due order, and the time jumped over doesn't count as lateness: a job is
# late when the bot wasn't there to run it, not when time was skipped.
#
# Moments are stored in UTC. Anything on a local-time schedule (the nightly
# backup) works out its next moment in code with next_run().
# ---------------------------------------------------------------------------
TICK_SECONDS = 15
LATE_AFTER_SECONDS = 60  # a job this overdue counts as late

PENDING, RUNNING, DONE, FAILED, CANCELLED = "pending", "running", "done", "failed", "cancelled"
# A job that ran and decided not to do its work, having said why (`report`)
SKIPPED = "skipped"
# How a job that ran can have ended: the last of these, for each kind of job, says whether
# that kind is in trouble (`troubled`)
_ENDED = (DONE, FAILED, SKIPPED)


@dataclass(frozen=True)
class Job:
    id: int
    user_id: int | None
    task: str
    kind: str
    payload: dict
    due_at: datetime  # UTC
    late_by: float = 0.0  # seconds overdue when it ran

    @property
    def is_late(self) -> bool:
        return self.late_by > LATE_AFTER_SECONDS


JobHandler = Callable[[Job], Awaitable[None]]

_handlers: dict[tuple[str, str], JobHandler] = {}
# What each kind of job is called wherever the user reads it (the status line, the start's
# message, an error card): never its kind, which is the code's own word
_labels: dict[tuple[str, str], str] = {}
_ticker: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_warned_unhandled: set[tuple[str, str]] = set()


# ---------------------------------------------------------------------------
# Time helpers (pure)
# ---------------------------------------------------------------------------
def utc_now() -> datetime:
    """Now, as the bot sees it: the real time unless the dev clock has been moved."""
    return clock.now()


def to_db(moment: datetime) -> str:
    """A moment as stored: UTC, fixed width, so text order is time order."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def from_db(text: str) -> datetime:
    return datetime.fromisoformat(text)


def seconds_late(due_at: datetime, now: datetime) -> float:
    """How overdue a job is, never negative. Time the dev clock jumped over
    isn't counted."""
    return max(0.0, (now - due_at).total_seconds() - clock.skipped_between(due_at, now))


def seconds_until_next_look(now: datetime, next_due: datetime | None) -> float:
    """How long the loop should sleep: until the next job is due, at most one tick.

    A job that is already due and still pending (its task isn't loaded) must
    not make the loop spin, so that waits a full tick too.
    """
    if next_due is None or next_due <= now:
        return TICK_SECONDS
    return min(TICK_SECONDS, (next_due - now).total_seconds())


def next_run(at: time, now: datetime) -> datetime:
    """The next moment after `now` when the clock in NZ reads `at`."""
    today = now.astimezone(TIMEZONE).date()
    candidate = datetime.combine(today, at, tzinfo=TIMEZONE)
    # Compare as timestamps: these are real moments, whatever daylight saving is doing
    if candidate.timestamp() <= now.timestamp():
        candidate = datetime.combine(today + timedelta(days=1), at, tzinfo=TIMEZONE)
    return candidate


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, skill, kind, payload, due_at"


def _job(row: tuple, now: datetime | None = None) -> Job:
    due_at = from_db(row[5])
    late_by = seconds_late(due_at, now) if now is not None else 0.0
    return Job(row[0], row[1], row[2], row[3], json.loads(row[4]), due_at, late_by)


def _db_add(conn: sqlite3.Connection, user_id, task: str, kind: str, payload: dict, due_at: datetime) -> int:
    cursor = conn.execute(
        """
        INSERT INTO scheduled_jobs (user_id, skill, kind, payload, due_at, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, task, kind, json.dumps(payload), to_db(due_at), PENDING, to_db(utc_now())),
    )
    return cursor.lastrowid


def _db_due(conn: sqlite3.Connection, now: datetime) -> list[Job]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM scheduled_jobs WHERE status = ? AND due_at <= ? ORDER BY due_at, id",
        (PENDING, to_db(now)),
    ).fetchall()
    return [_job(row, now) for row in rows]


def _db_next_due(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT MIN(due_at) FROM scheduled_jobs WHERE status = ?", (PENDING,)
    ).fetchone()
    return from_db(row[0]) if row and row[0] else None


def _db_claim(conn: sqlite3.Connection, job_id: int) -> bool:
    """Mark a job as running. False if something else got there first, or it was cancelled."""
    cursor = conn.execute(
        "UPDATE scheduled_jobs SET status = ? WHERE id = ? AND status = ?", (RUNNING, job_id, PENDING)
    )
    return cursor.rowcount == 1


def _db_finish(conn: sqlite3.Connection, job_id: int, status: str, late_by: float, error: str | None) -> None:
    conn.execute(
        "UPDATE scheduled_jobs SET status = ?, late_by_s = ?, error = ?, finished_at = ? WHERE id = ?",
        (status, late_by, error, to_db(utc_now()), job_id),
    )


def _db_cancel(conn: sqlite3.Connection, job_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE scheduled_jobs SET status = ?, finished_at = ? WHERE id = ? AND status = ?",
        (CANCELLED, to_db(utc_now()), job_id, PENDING),
    )
    return cursor.rowcount == 1


def _db_reschedule(conn: sqlite3.Connection, job_id: int, due_at: datetime) -> bool:
    cursor = conn.execute(
        "UPDATE scheduled_jobs SET due_at = ? WHERE id = ? AND status = ?",
        (to_db(due_at), job_id, PENDING),
    )
    return cursor.rowcount == 1


def _db_recover(conn: sqlite3.Connection) -> int:
    """Jobs left running by a crash go back in the queue."""
    cursor = conn.execute("UPDATE scheduled_jobs SET status = ? WHERE status = ?", (PENDING, RUNNING))
    return cursor.rowcount


def _db_pending(conn: sqlite3.Connection, task: str, kind: str | None) -> list[Job]:
    sql = f"SELECT {_COLUMNS} FROM scheduled_jobs WHERE status = ? AND skill = ?"
    values: list = [PENDING, task]
    if kind is not None:
        sql += " AND kind = ?"
        values.append(kind)
    return [_job(row) for row in conn.execute(sql + " ORDER BY due_at, id", values).fetchall()]


def _db_all_pending(conn: sqlite3.Connection) -> list[Job]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM scheduled_jobs WHERE status = ? ORDER BY due_at, id", (PENDING,)
    ).fetchall()
    return [_job(row) for row in rows]


def _db_troubled(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(task, kind, how it ended) for each kind of job whose latest run failed or
    was skipped, the most recent first. A later run that worked clears it."""
    marks = ", ".join("?" for _ in _ENDED)
    rows = conn.execute(
        f"""
        SELECT skill, kind, status FROM scheduled_jobs AS job
        WHERE status IN (?, ?) AND id = (
            SELECT id FROM scheduled_jobs
            WHERE skill = job.skill AND kind = job.kind AND status IN ({marks})
            ORDER BY finished_at DESC, id DESC LIMIT 1
        )
        ORDER BY finished_at DESC, id DESC
        """,
        (FAILED, SKIPPED, *_ENDED),
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


# ---------------------------------------------------------------------------
# For tasks and the core
# ---------------------------------------------------------------------------
def register_handler(task: str, kind: str, handler: JobHandler, label: str = "") -> None:
    """Say which function runs jobs of this kind for this task, and what the
    job is called in words ("nightly backup"): `label` is what the user reads
    wherever a job is named. Without one the kind is made readable, which is
    only good enough for a job nobody is shown."""
    _handlers[(task, kind)] = handler
    if label:
        _labels[(task, kind)] = label
    else:
        _labels.pop((task, kind), None)


def label(task: str, kind: str) -> str:
    """A job in words: "nightly backup", "pill reminder"."""
    given = _labels.get((task, kind))
    if given:
        return given
    words = kind.replace("_", " ")
    return words if task == "core" else f"{task} {words}"


def internal_names() -> dict[str, str]:
    """Each way a job is written in the code ("pills/remind", "pills remind",
    "day_rollover"), with the words it should have been said in: for the
    check on what the user is shown (`in_words`)."""
    found: dict[str, str] = {}
    for (task, kind), said in _labels.items():
        found[f"{task}/{kind}"] = said
        plain = kind.replace("_", " ") if task == "core" else f"{task} {kind.replace('_', ' ')}"
        if plain != said and " " in plain:  # one plain word ("tidy") is a word anyone may write
            found[plain] = said
        if "_" in kind:
            found[kind] = said
    return found


def in_words(text: str) -> str:
    """A text the user will read, with any job named the code's way put in
    words. One found is a bug in whatever wrote the text: it is logged."""
    for internal, said in sorted(internal_names().items(), key=lambda each: -len(each[0])):
        if re.search(rf"(?<![\w/]){re.escape(internal)}(?![\w/])", text):
            log.error("A job's internal name was about to be shown to the user: %s in %r", internal, text[:200])
            text = re.sub(rf"(?<![\w/]){re.escape(internal)}(?![\w/])", said, text)
    return text


async def add_job(
    task: str, kind: str, due_at: datetime, payload: dict | None = None, user_id: int | None = None
) -> int:
    """Ask for `kind` to be handled at `due_at`. Returns the job's id."""
    job_id = await database.run(_db_add, user_id, task, kind, payload or {}, due_at)
    if _wake is not None:
        _wake.set()  # it might be due before the loop's next look
    return job_id


# ---------------------------------------------------------------------------
# Standing jobs: the ones that book themselves for "the next time the clock
# reads X" (the day rollover, the nightly backup, a task's morning post). When
# one is due depends on what time it is, so it has to be worked out again
# whenever the clock goes back (`dev clock reset`) or the jobs are gone (`dev
# reset-db`): a job left booked from a later time would simply never come.
# ---------------------------------------------------------------------------
_standing: dict[str, Callable[[], Awaitable[None]]] = {}


def keep_booked(name: str, book: Callable[[], Awaitable[None]]) -> None:
    """Register a standing job. `book` makes sure it is booked for the right
    moment as the clock now reads (with `ensure`), and is safe to call at any
    time. `name` says whose it is; registering again replaces it."""
    _standing[name] = book


async def rebook_standing() -> None:
    """Book every standing job again for the time it now is. Called when the
    clock has gone back or the jobs were wiped. One failing is logged and the
    others are still booked."""
    for name, book in list(_standing.items()):
        try:
            await book()
        except Exception:
            log.exception("Could not book the standing job %s", name)
    wake()


async def ensure(task: str, kind: str, due_at: datetime, user_id: int | None = None) -> None:
    """Make sure exactly this is booked: one pending job of this kind, due no
    later than `due_at`. None pending: it is booked. One booked for a later
    moment (it was booked before the clock went back): it is moved. One due
    earlier is left alone: it is overdue and must still run."""
    pending = await pending_jobs(task, kind)
    if not pending:
        await add_job(task, kind, due_at, user_id=user_id)
    elif pending[0].due_at > due_at:
        log.info("%s/%s was booked for %s, later than it is due now: moved to %s", task, kind, pending[0].due_at.isoformat(), due_at.isoformat())
        await reschedule_job(pending[0].id, due_at)


async def cancel_job(job_id: int | None) -> bool:
    """Stop a job that hasn't run yet. False if it already ran or doesn't exist."""
    if job_id is None:
        return False
    return await database.run(_db_cancel, job_id)


async def reschedule_job(job_id: int | None, due_at: datetime) -> bool:
    """Move a job that hasn't run yet. False if it already ran or doesn't exist."""
    if job_id is None:
        return False
    moved = await database.run(_db_reschedule, job_id, due_at)
    if moved and _wake is not None:
        _wake.set()
    return moved


async def pending_jobs(task: str, kind: str | None = None) -> list[Job]:
    return await database.run(_db_pending, task, kind)


async def all_pending() -> list[Job]:
    """Every job still waiting to run, soonest first."""
    return await database.run(_db_all_pending)


def wake() -> None:
    """Have the loop look for due jobs now: the clock has just been moved."""
    if _wake is not None:
        _wake.set()


# ---------------------------------------------------------------------------
# How a job ended. One that raises has failed. A handler that catches its own
# failure, or decides not to do its work, says so with `report`: the job is
# then recorded as failed or skipped instead of done, and that kind of job
# counts as in trouble until one of its runs works (the bot's status says so:
# core/identity.py). The handler still says why itself, in the log and #bot-log.
# ---------------------------------------------------------------------------
_reported: dict[int, str] = {}


def report(job: Job, ended: str) -> None:
    """Called by a job's handler while it runs: this run is to be recorded as
    FAILED or SKIPPED, not as done."""
    if ended not in (FAILED, SKIPPED):
        raise ValueError(f"A job reports itself as failed or skipped, not {ended!r}")
    _reported[job.id] = ended


async def troubled() -> list[tuple[str, str, str]]:
    """(task, kind, "failed" or "skipped") for each kind of job whose latest run
    did not work, the most recent first. Read from the jobs table, so a restart
    doesn't forget it."""
    return await database.run(_db_troubled)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
async def run_due(now: datetime | None = None, done: list | None = None) -> int:
    """Run every job that is due. Returns how many ran; each is added to
    `done`, if given."""
    now = now or utc_now()
    ran = 0
    for job in await database.run(_db_due, now):
        handler = _handlers.get((job.task, job.kind))
        if handler is None:
            # Its task isn't loaded: leave it for when it is
            if (job.task, job.kind) not in _warned_unhandled:
                _warned_unhandled.add((job.task, job.kind))
                log.warning("No handler for %s/%s jobs; they will wait", job.task, job.kind)
            continue
        if not await database.run(_db_claim, job.id):
            continue
        if job.is_late:
            log.info("Running %s/%s job %s late by %.0fs", job.task, job.kind, job.id, job.late_by)
        started = perf_counter()
        try:
            await handler(job)
        except Exception as error:
            _reported.pop(job.id, None)
            log.exception("Scheduled job %s (%s/%s) failed", job.id, job.task, job.kind)
            await database.run(_db_finish, job.id, FAILED, job.late_by, repr(error))
            await log_error(f"Scheduled job failed: {label(job.task, job.kind)}", repr(error))
            outcome = "failed"
        else:
            # Done, unless the handler said this run failed or was skipped (`report`)
            outcome = _reported.pop(job.id, DONE)
            await database.run(_db_finish, job.id, outcome, job.late_by, None)
        await devmode.debug(
            f"Job {job.id}: {job.task}/{job.kind}",
            [
                f"Outcome: {outcome} in {perf_counter() - started:.2f}s",
                f"Due: {job.due_at.isoformat(timespec='seconds')} · late by {job.late_by:.1f}s",
                f"Payload: {job.payload}",
            ],
        )
        ran += 1
        if done is not None:
            done.append(job)
    return ran


async def run_all_due(done: list | None = None) -> int:
    """Run due jobs until none is left: a job may book another that is already
    due (the clock was moved ahead, or the bot was off for a while). A job
    nobody handles is left waiting and doesn't keep this going."""
    total = 0
    while ran := await run_due(done=done):
        total += ran
    return total


async def catch_up() -> tuple[int, list[Job]]:
    """When the bot starts, before the loop: jobs a crash left running go back
    in the queue, and everything that came due while the bot was off runs
    now. Returns how many were put back and the jobs that ran late, for the
    start's message (core/restart.py)."""
    again = await database.run(_db_recover)
    if again:
        log.info("Scheduler: %s interrupted job(s) put back in the queue", again)
    done: list[Job] = []
    await run_all_due(done)
    return again, [job for job in done if job.is_late]


async def _loop() -> None:
    recovered = await database.run(_db_recover)
    if recovered:
        log.info("Scheduler: %s interrupted job(s) put back in the queue", recovered)
    while True:
        try:
            await run_all_due()
            next_due = await database.run(_db_next_due)
            wait = seconds_until_next_look(utc_now(), next_due)
        except Exception:
            log.exception("Scheduler tick failed")
            wait = TICK_SECONDS
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), wait)
        except asyncio.TimeoutError:
            pass


def start() -> None:
    """Start the loop. Safe to call again (on_ready fires after reconnects)."""
    global _ticker, _wake
    if _ticker is not None and not _ticker.done():
        return
    _wake = asyncio.Event()
    _ticker = asyncio.create_task(_loop(), name="scheduler")
