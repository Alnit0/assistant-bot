import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
from time import perf_counter

from core import clock, database, devmode, timetable
from core.config import TIMEZONE
from core.discord_utils import log_error

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Scheduler: the one part of the bot that knows when things happen.
#
#   Handlers   A task says what to do for a kind of job ("pills", "checklist"),
#              never when. Each has a name in words for wherever it is shown.
#   Schedules  Rows saying when a handler runs: a time on the wall clock, the
#              days, silent or notify, the channel, on or off
#              (core/timetable.py). A task supplies a default the first time;
#              after that the row is the user's.
#   Engine     One loop. Each look it makes sure every schedule's next
#              occurrence is booked, runs what is due, and records how each
#              run ended. Nothing else works out a time.
#   Run log    The scheduled_jobs table: one row a run, pending until it runs.
#              A one-off job ("in 15 minutes, look at that dose again") is a
#              row with no schedule.
#
# One run, one key. A scheduled run's key is its schedule, the local date and
# time it stands for and its step, so the same occurrence is never booked or
# run twice, whatever restarts in between. A one-off may be given a key by
# whoever books it.
#
# Jobs that came due while the bot was off run at the next start, with
# job.late_by saying how overdue they are. Of several occurrences of one
# schedule that were missed, only the latest runs (the others are recorded
# as passed over), and a schedule may say that one too late is not run at
# all (its missed-run rule).
#
# The time is the clock's (core/clock.py), so everything follows the dev
# clock. When that is moved ahead, what came due on the way runs at once, in
# due order, and the time jumped over doesn't count as lateness: a job is
# late when the bot wasn't there to run it, not when time was skipped.
#
# Moments are stored in UTC; a schedule is local time and its zone.
# ---------------------------------------------------------------------------
TICK_SECONDS = 15
LATE_AFTER_SECONDS = 60  # a job this overdue counts as late

PENDING, RUNNING, DONE, FAILED, CANCELLED = "pending", "running", "done", "failed", "cancelled"
# A job that ran and decided not to do its work, having said why (`report`)
SKIPPED = "skipped"
# An occurrence the engine itself set aside: passed over for a later one, or too late under
# its schedule's rule. Nothing went wrong, so this is never trouble
MISSED = "missed"
# How a job that ran can have ended: the last of these, for each kind of job, says whether
# that kind is in trouble (`troubled`)
_ENDED = (DONE, FAILED, SKIPPED, MISSED)


@dataclass(frozen=True)
class Job:
    id: int
    user_id: int | None
    task: str
    kind: str
    payload: dict
    due_at: datetime  # UTC
    late_by: float = 0.0  # seconds overdue when it ran
    key: str | None = None  # what makes this run one run
    schedule_id: int | None = None  # the schedule it is an occurrence of; None for a one-off
    step: int | None = None  # which of the schedule's steps
    local_at: str | None = None  # the local date and time it stands for ("2026-10-14T06:00")
    # For an occurrence that stands in for earlier ones the bot was off for: when the earliest
    # of them was due, and how many were passed over
    first_due: datetime | None = None
    passed_over: int = 0
    notify: str = timetable.SILENT  # from the schedule
    channel: str = "hub"  # from the schedule: a channel by its role

    @property
    def is_late(self) -> bool:
        return self.late_by > LATE_AFTER_SECONDS


JobHandler = Callable[[Job], Awaitable[None]]

_handlers: dict[tuple[str, str], JobHandler] = {}
# What each kind of job is called wherever the user reads it (the status line, the start's
# message, an error card): never its kind, which is the code's own word
_labels: dict[tuple[str, str], str] = {}
# The schedule each handler gets the first time, by (task, kind)
_standing: dict[tuple[str, str], timetable.Default] = {}
# What else runs with a handler's default schedule, in front of it: {the handler the schedule
# was made for: [(order, a handler that joins it)]}, and what the schedule is then called
_joins: dict[str, list[tuple[int, str]]] = {}
_routine_names: dict[str, str] = {}
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
    """The next moment after `now` when the clock in NZ reads `at`. (For words
    such as `dev clock 6am`; a schedule's occurrences are core/timetable.py's.)"""
    today = now.astimezone(TIMEZONE).date()
    candidate = datetime.combine(today, at, tzinfo=TIMEZONE)
    # Compare as timestamps: these are real moments, whatever daylight saving is doing
    if candidate.timestamp() <= now.timestamp():
        candidate = datetime.combine(today + timedelta(days=1), at, tzinfo=TIMEZONE)
    return candidate


def handler_name(task: str, kind: str) -> str:
    """A handler as a schedule's step names it: "pills.checklist"."""
    return f"{task}.{kind}"


def handler_parts(name: str) -> tuple[str, str]:
    task, _, kind = name.partition(".")
    return task, kind


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, skill, kind, payload, due_at, run_key, schedule_id, step, local_at"


def _job(row: tuple, now: datetime | None = None) -> Job:
    due_at = from_db(row[5])
    late_by = seconds_late(due_at, now) if now is not None else 0.0
    payload = json.loads(row[4])
    first = payload.get("_first_due") if isinstance(payload, dict) else None
    return Job(
        row[0], row[1], row[2], row[3], payload, due_at, late_by, row[6], row[7], row[8], row[9],
        first_due=from_db(first) if first else None, passed_over=int(payload.get("_passed_over", 0)) if isinstance(payload, dict) else 0,
    )


def _db_add(
    conn: sqlite3.Connection, user_id, task: str, kind: str, payload: dict, due_at: datetime, key: str | None = None,
    schedule_id: int | None = None, step: int | None = None, local_at: str | None = None,
) -> int | None:
    """Book a job. With a key that is already there: its id if it is still
    waiting (nothing is booked twice), None if that run is over."""
    if key is not None:
        there = conn.execute("SELECT id, status FROM scheduled_jobs WHERE run_key = ?", (key,)).fetchone()
        if there is not None:
            return there[0] if there[1] == PENDING else None
    cursor = conn.execute(
        """
        INSERT INTO scheduled_jobs (user_id, skill, kind, payload, due_at, status, created_at, run_key, schedule_id, step, local_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, task, kind, json.dumps(payload), to_db(due_at), PENDING, to_db(utc_now()), key, schedule_id, step, local_at),
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


def _db_finish(conn: sqlite3.Connection, job_id: int, status: str, late_by: float, error: str | None, note: str | None = None) -> None:
    conn.execute(
        "UPDATE scheduled_jobs SET status = ?, late_by_s = ?, error = ?, finished_at = ?, note = COALESCE(?, note) WHERE id = ?",
        (status, late_by, error, to_db(utc_now()), note, job_id),
    )


def _db_cancel(conn: sqlite3.Connection, job_id: int) -> bool:
    # Its key goes with it: what was cancelled may be booked again
    cursor = conn.execute(
        "UPDATE scheduled_jobs SET status = ?, finished_at = ?, run_key = run_key || '~cancelled' || id WHERE id = ? AND status = ?",
        (CANCELLED, to_db(utc_now()), job_id, PENDING),
    )
    return cursor.rowcount == 1


def _db_reschedule(conn: sqlite3.Connection, job_id: int, due_at: datetime, key: str | None = None) -> bool:
    if key is not None and conn.execute("SELECT 1 FROM scheduled_jobs WHERE run_key = ? AND id != ?", (key, job_id)).fetchone():
        key = f"{key}+{job_id}"  # that moment has had a run already: this one is still its own
    if key is not None:
        cursor = conn.execute(
            "UPDATE scheduled_jobs SET due_at = ?, run_key = ? WHERE id = ? AND status = ?", (to_db(due_at), key, job_id, PENDING)
        )
    else:
        cursor = conn.execute("UPDATE scheduled_jobs SET due_at = ? WHERE id = ? AND status = ?", (to_db(due_at), job_id, PENDING))
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
# For tasks and the core: handlers, and their names in words
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


def default_schedule(task: str, kind: str, default: timetable.Default) -> None:
    """Say when a handler runs unless the user says otherwise. The first time
    the engine looks it becomes a row (core/timetable.py), and from then on
    the row is what counts: this is only what a fresh database gets, except
    for one that is `locked`, which always follows the code."""
    _standing[(task, kind)] = default


def defaults() -> dict[tuple[str, str], timetable.Default]:
    """The default schedule of every handler that has one, by (task, kind)."""
    return dict(_standing)


def join_routine(of: str, step: str, order: int, name: str) -> None:
    """Have `step` (a handler's name) run with the schedule made for the handler
    `of`, in front of it: together they are a routine, called `name`. Steps
    run in the order of `order`, the schedule's own handler last. Said when a
    task that is switched on sets itself up; one that is switched off says
    nothing, and the schedule is its own handler alone again."""
    joined = [each for each in _joins.get(of, []) if each[1] != step]
    _joins[of] = sorted([*joined, (order, step)])
    _routine_names[of] = name


def name_routine(of: str, name: str) -> None:
    """What the schedule made for a handler is called once something has joined
    it. Said whether or not anything has: the name must be known to be the
    code's own when what joined is switched off again and it is taken back."""
    _routine_names[of] = name


def routine_steps(of: str) -> tuple[str, ...]:
    """The steps of the schedule made for a handler, as the code now says."""
    return (*(step for _, step in _joins.get(of, [])), of)


def label(task: str, kind: str) -> str:
    """A job in words: "nightly backup", "pill reminder"."""
    given = _labels.get((task, kind))
    if given:
        return given
    words = kind.replace("_", " ")
    return words if task == "core" else f"{task} {words}"


def handlers() -> list[tuple[str, str]]:
    """Every (task, kind) that has a handler, in name order."""
    return sorted(_handlers)


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


# ---------------------------------------------------------------------------
# One-off jobs
# ---------------------------------------------------------------------------
async def add_job(
    task: str, kind: str, due_at: datetime, payload: dict | None = None, user_id: int | None = None, key: str | None = None
) -> int | None:
    """Ask for `kind` to be handled at `due_at`. Returns the job's id.

    With a `key`, the run is booked once: asking again while it waits returns
    the same job, and asking after it has run books nothing and returns None."""
    job_id = await database.run(_db_add, user_id, task, kind, payload or {}, due_at, key)
    if _wake is not None:
        _wake.set()  # it might be due before the loop's next look
    return job_id


async def ensure(task: str, kind: str, due_at: datetime, user_id: int | None = None) -> None:
    """Make sure exactly this one-off is booked: one pending job of this kind,
    due no later than `due_at`. None pending: it is booked. One booked for a
    later moment (it was booked before the clock went back): it is moved.
    One due earlier is left alone: it is overdue and must still run."""
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


async def reschedule_job(job_id: int | None, due_at: datetime, key: str | None = None) -> bool:
    """Move a job that hasn't run yet (and give it a new key, if its key says
    when). False if it already ran or doesn't exist."""
    if job_id is None:
        return False
    moved = await database.run(_db_reschedule, job_id, due_at, key)
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
# Schedules: the rows, and booking their occurrences
# ---------------------------------------------------------------------------
def _db_owner(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE role = 'owner' ORDER BY id LIMIT 1").fetchone()
    return row[0] if row else None


def _db_defaults(conn: sqlite3.Connection, now: datetime, standing: dict) -> list[str]:
    """Each handler's default as a row, made once. One the user removed is
    still a row and is not made again. A locked one follows the code."""
    said = []
    for (task, kind), default in standing.items():
        name = handler_name(task, kind)
        there = timetable.db_for_default(conn, name)
        if there is None:
            timetable.db_add(
                conn, now, user_id=None if default.locked else _db_owner(conn), name=default.name, at=default.at, steps=(name,),
                days=default.days, notify=default.notify, channel=default.channel, missed=default.missed,
                origin=timetable.FROM_A_TASK, default_key=name, locked=default.locked,
            )
            said.append(f"schedule made for {name}: {default.name}, {timetable.days_text(default.days)} at {default.at:%H:%M}")
            # A job of this kind left waiting from before there were schedules would run beside
            # the schedule's own: it goes in the same change, so there is never a moment with two.
            # One that is already overdue is left to run: it is owed, and the schedule's first
            # run is a later occurrence
            for (job_id,) in conn.execute(
                "SELECT id FROM scheduled_jobs WHERE skill = ? AND kind = ? AND status = ? AND schedule_id IS NULL AND due_at > ?",
                (task, kind, PENDING, to_db(now)),
            ).fetchall():
                _db_cancel(conn, job_id)
                said.append(f"the job that was waiting for {name} is replaced by its schedule")
        elif default.locked and (there.at, there.days) != (default.at.replace(tzinfo=None, second=0, microsecond=0), tuple(default.days)):
            timetable.db_update(conn, there.id, now, at=default.at, days=default.days)
            said.append(f"schedule for {name} follows the code again: {default.at:%H:%M}")
        # What runs with it (the briefing, the tidy) follows what is switched on. Its time,
        # days and the rest stay the user's; so does a name they gave it
        there = timetable.db_for_default(conn, name)
        steps = routine_steps(name)
        if there is not None and there.steps != steps:
            timetable.db_set_steps(conn, there.id, steps)
            said.append(f"{there.name}: its steps are now {', '.join(steps)}")
            ours = {default.name, *_routine_names.values()}
            wanted = _routine_names.get(name, default.name) if len(steps) > 1 else default.name
            if there.name in ours and there.name != wanted:
                timetable.db_update(conn, there.id, now, name=wanted)
                said.append(f"{there.name} is now called {wanted}")
    return said


def _db_ran_on(conn: sqlite3.Connection, schedule_id: int, day: str, but_not: str) -> bool:
    """Whether the schedule has already run on this local day, at another time
    than `but_not` (it was moved after it ran)."""
    row = conn.execute(
        "SELECT 1 FROM scheduled_jobs WHERE schedule_id = ? AND substr(local_at, 1, 10) = ? AND local_at != ? AND status IN (?, ?, ?) LIMIT 1",
        (schedule_id, day, but_not, DONE, FAILED, SKIPPED),
    ).fetchone()
    return row is not None


def _db_coming(conn: sqlite3.Connection, schedule: timetable.Schedule, now: datetime) -> timetable.Occurrence | None:
    """When a schedule next runs, as it stands (or as it would stand, for one
    not saved yet): its next occurrence, passing over today if it has
    already run today at another time. A schedule runs once a day."""
    coming = timetable.next_occurrence(schedule, now)
    if coming is not None and schedule.id and _db_ran_on(conn, schedule.id, coming.stamp[:10], coming.stamp):
        # It ran today at its old time: once a day, so the new time starts tomorrow
        coming = timetable.next_occurrence(schedule, now, skip_day=coming.local.date())
    return coming


async def coming(schedule: timetable.Schedule) -> timetable.Occurrence | None:
    """When this schedule next runs, as the engine would book it: for the list,
    and for a card that says when a change would take effect."""
    return await database.run(_db_coming, schedule, utc_now())


def _db_last_of(conn: sqlite3.Connection, schedule_id: int) -> tuple[str, str] | None:
    """How a schedule's last run ended and the local time it stood for; the
    worst of its steps, so a routine with a failed step says so."""
    row = conn.execute(
        "SELECT local_at FROM scheduled_jobs WHERE schedule_id = ? AND local_at IS NOT NULL AND status IN (?, ?, ?) ORDER BY local_at DESC LIMIT 1",
        (schedule_id, DONE, FAILED, SKIPPED),
    ).fetchone()
    if row is None:
        return None
    ended = {status for (status,) in conn.execute("SELECT status FROM scheduled_jobs WHERE schedule_id = ? AND local_at = ?", (schedule_id, row[0]))}
    return (FAILED if FAILED in ended else SKIPPED if SKIPPED in ended else DONE), row[0]


async def last_of(schedule_id: int) -> tuple[str, str] | None:
    return await database.run(_db_last_of, schedule_id)


def _db_book(conn: sqlite3.Connection, now: datetime, standing: dict) -> list[str]:
    """Make sure every schedule that is on has its next occurrence booked,
    a run for each step, by its key. Booked again, nothing changes. A run
    booked for a time the schedule no longer says (it was moved, paused, or
    the clock went back) is taken out. An overdue run is never touched: it
    must still run. Returns what was done, for the log."""
    said = _db_defaults(conn, now, standing)
    for schedule in timetable.db_all(conn, removed=True):
        coming = _db_coming(conn, schedule, now)
        waiting = conn.execute(
            "SELECT id, local_at, due_at, step, skill, kind FROM scheduled_jobs WHERE schedule_id = ? AND status = ? AND local_at IS NOT NULL",
            (schedule.id, PENDING),
        ).fetchall()
        for job_id, local_at, due_at, step, task, kind in waiting:
            if from_db(due_at) <= now:
                continue
            # Its time, or the step it was booked for, is no longer what the schedule says
            still_a_step = step is not None and 1 <= step <= len(schedule.steps) and schedule.steps[step - 1] == handler_name(task, kind)
            if coming is None or local_at != coming.stamp or not still_a_step:
                _db_cancel(conn, job_id)
                said.append(f"{schedule.name}: the run of {handler_name(task, kind)} booked for {local_at} is no longer what the schedule says; taken out")
        if coming is None:
            continue
        for step, name in enumerate(schedule.steps, start=1):
            task, kind = handler_parts(name)
            key = timetable.run_key(schedule.id, coming.stamp, step)
            if conn.execute("SELECT 1 FROM scheduled_jobs WHERE run_key = ?", (key,)).fetchone() is None:
                _db_add(conn, schedule.user_id, task, kind, {}, coming.moment, key, schedule.id, step, coming.stamp)
                said.append(f"{schedule.name}: {name} booked for {coming.stamp}")
    return said


async def book() -> None:
    """Bring the booked runs in line with the schedules, as the clock now
    reads. Safe to call at any time and as often as wanted."""
    for line in await database.run(_db_book, utc_now(), dict(_standing)):
        log.info("Scheduler: %s", line)


def _db_prepare(conn: sqlite3.Connection, job: Job, now: datetime) -> tuple[Job | None, str, bool]:
    """What to do with a due run of a schedule: (the job to run, or None if it
    is set aside; why; whether that is worth saying after a restart).

    Of several occurrences the bot was off for, only the latest runs: an
    earlier one is set aside and the latest is booked in its place, told
    when the first was due and how many were passed over. One that is later
    than its schedule's rule allows is set aside too."""
    schedule = timetable.db_get(conn, job.schedule_id)
    on_day = datetime.fromisoformat(job.local_at).date()
    if schedule is None or schedule.state == timetable.REMOVED or not schedule.is_on(on_day) or on_day.weekday() not in schedule.days:
        return None, "its schedule is off that day, or gone", False
    latest = timetable.last_occurrence(schedule, now)
    if latest is None:
        return None, "its schedule has no occurrence to run", False
    if latest.stamp > job.local_at:
        between = timetable.between(schedule, job.due_at, now)
        first = job.first_due or job.due_at
        payload = {**job.payload, "_first_due": to_db(first), "_passed_over": job.passed_over + max(1, len(between))}
        _db_add(conn, job.user_id, job.task, job.kind, payload, latest.moment, timetable.run_key(schedule.id, latest.stamp, job.step or 1), schedule.id, job.step, latest.stamp)
        return None, f"passed over: the occurrence of {latest.stamp} runs in its place", False
    limit = timetable.skip_limit(schedule.missed)
    if limit is not None and job.late_by > limit.total_seconds():
        return None, f"skipped: {job.late_by / 60:.0f} minutes late, and its limit is {limit.total_seconds() / 60:.0f}", True
    return replace(job, notify=schedule.notify, channel=schedule.channel), "", False


def _db_fire(conn: sqlite3.Connection, job_id: int, now: datetime) -> bool:
    """Make a waiting job due now, as a run of its own: it no longer stands for
    an occurrence, so the real one is still booked and still runs."""
    cursor = conn.execute(
        "UPDATE scheduled_jobs SET due_at = ?, run_key = 'fired:' || id, local_at = NULL WHERE id = ? AND status = ?", (to_db(now), job_id, PENDING)
    )
    return cursor.rowcount == 1


async def fire(job_id: int) -> bool:
    """`dev fire next`: run a waiting job now. False if it already ran."""
    fired = await database.run(_db_fire, job_id, utc_now())
    wake()
    return fired


async def run_now(task: str, kind: str) -> int | None:
    """`dev run`: run a handler now, outside any schedule, as a job of its own
    in the run log. Returns the job's id."""
    job_id = await add_job(task, kind, utc_now(), {"manual": True}, key=f"manual:{handler_name(task, kind)}:{to_db(clock.real_now())}")
    await run_all_due()
    return job_id


def _db_clock_went_back(conn: sqlite3.Connection, now: datetime) -> int:
    """Runs recorded for moments that are now in the future (the dev clock was
    moved ahead, and is back) would block the real ones by their keys: their
    keys are freed. They stay in the log, marked."""
    cursor = conn.execute(
        """
        UPDATE scheduled_jobs SET run_key = run_key || '~moved' || id, note = COALESCE(note || ' · ', '') || 'ran on a clock that was then moved back'
        WHERE run_key IS NOT NULL AND status NOT IN (?, ?) AND due_at > ?
        """,
        (PENDING, RUNNING, to_db(now)),
    )
    return cursor.rowcount


async def clock_went_back() -> None:
    """The dev clock has gone back (or the jobs were wiped): free the keys of
    runs that are now in the future, and book every schedule again for the
    time it now is. One booked for a later day is taken out by `book`."""
    freed = await database.run(_db_clock_went_back, utc_now())
    if freed:
        log.info("Scheduler: the clock went back; %s run(s) from the time ahead no longer block the real ones", freed)
    await book()
    wake()


def _db_last_runs(conn: sqlite3.Connection, limit: int = 50) -> list[tuple]:
    """The latest finished run of each kind of job: (task, kind, status, when it was due, late by, note)."""
    marks = ", ".join("?" for _ in _ENDED)
    return conn.execute(
        f"""
        SELECT skill, kind, status, due_at, late_by_s, note FROM scheduled_jobs AS job
        WHERE status IN ({marks}) AND id = (
            SELECT id FROM scheduled_jobs WHERE skill = job.skill AND kind = job.kind AND status IN ({marks}) ORDER BY finished_at DESC, id DESC LIMIT 1
        )
        ORDER BY finished_at DESC, id DESC LIMIT ?
        """,
        (*_ENDED, *_ENDED, limit),
    ).fetchall()


async def last_runs() -> list[tuple]:
    return await database.run(_db_last_runs)


# ---------------------------------------------------------------------------
# How a job ended. One that raises has failed. A handler that catches its own
# failure, or decides not to do its work, says so with `report`: the job is
# then recorded as failed or skipped instead of done, and that kind of job
# counts as in trouble until one of its runs works (the bot's status says so:
# core/identity.py). The handler still says why itself, in the log and #bot-log.
# What it decided, in a line, is kept with the run (`note`).
# ---------------------------------------------------------------------------
_reported: dict[int, str] = {}
_notes: dict[int, str] = {}


def report(job: Job, ended: str) -> None:
    """Called by a job's handler while it runs: this run is to be recorded as
    FAILED or SKIPPED, not as done."""
    if ended not in (FAILED, SKIPPED):
        raise ValueError(f"A job reports itself as failed or skipped, not {ended!r}")
    _reported[job.id] = ended


def note(job: Job, said: str) -> None:
    """Called by a job's handler while it runs: what it decided and why, in a
    line, kept in the run log ("posted, 6 doses"; "nothing to take today")."""
    _notes[job.id] = said[:300]


async def troubled() -> list[tuple[str, str, str]]:
    """(task, kind, "failed" or "skipped") for each kind of job whose latest run
    did not work, the most recent first. Read from the jobs table, so a restart
    doesn't forget it."""
    return await database.run(_db_troubled)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
async def run_due(now: datetime | None = None, done: list | None = None, set_aside: list | None = None) -> int:
    """Run every job that is due. Returns how many were dealt with; each that
    ran is added to `done`, and each the engine set aside under its
    schedule's missed-run rule to `set_aside`, if given."""
    now = now or utc_now()
    dealt = 0
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
        if job.schedule_id is not None and job.local_at is not None:
            ready, why, worth_saying = await database.run(_db_prepare, job, now)
            if ready is None:
                await database.run(_db_finish, job.id, MISSED, job.late_by, None, why)
                log.info("Scheduler: %s (%s) %s", label(job.task, job.kind), job.local_at, why)
                if worth_saying and set_aside is not None:
                    set_aside.append(job)
                dealt += 1
                continue
            job = ready
        if job.is_late:
            log.info("Running %s/%s job %s late by %.0fs", job.task, job.kind, job.id, job.late_by)
        started = perf_counter()
        try:
            await handler(job)
        except Exception as error:
            _reported.pop(job.id, None)
            log.exception("Scheduled job %s (%s/%s) failed", job.id, job.task, job.kind)
            await database.run(_db_finish, job.id, FAILED, job.late_by, repr(error), _notes.pop(job.id, None))
            await log_error(f"Scheduled job failed: {label(job.task, job.kind)}", repr(error))
            outcome = "failed"
        else:
            # Done, unless the handler said this run failed or was skipped (`report`)
            outcome = _reported.pop(job.id, DONE)
            await database.run(_db_finish, job.id, outcome, job.late_by, None, _notes.pop(job.id, None))
        await devmode.debug(
            f"Job {job.id}: {job.task}/{job.kind}",
            [
                f"Outcome: {outcome} in {perf_counter() - started:.2f}s",
                f"Due: {job.due_at.isoformat(timespec='seconds')} · late by {job.late_by:.1f}s",
                f"Payload: {job.payload}",
            ],
        )
        dealt += 1
        if done is not None:
            done.append(job)
    return dealt


_one_at_a_time: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _turn() -> asyncio.Lock:
    """One pass at a time (a lock of the running loop's own). The loop is not
    the only caller: `dev run`, a moved clock and the self-test ask too, and
    two passes at once would each take what the other had not claimed yet,
    so a routine's steps could finish out of order (the checklist posted
    before the briefing: found 2026-10-13)."""
    global _one_at_a_time
    loop = asyncio.get_running_loop()
    if _one_at_a_time is None or _one_at_a_time[0] is not loop:
        _one_at_a_time = (loop, asyncio.Lock())
    return _one_at_a_time[1]


async def run_all_due(done: list | None = None, set_aside: list | None = None) -> int:
    """Book what the schedules say and run due jobs until none is left: a job
    may book another that is already due (the clock was moved ahead, or the
    bot was off for a while). A job nobody handles is left waiting and
    doesn't keep this going. One pass at a time: a second caller waits for
    the first, and then finds little or nothing left to do."""
    total = 0
    async with _turn():
        await book()
        while ran := await run_due(done=done, set_aside=set_aside):
            total += ran
            await book()
    return total


async def catch_up() -> tuple[int, list[Job], list[Job]]:
    """When the bot starts, before the loop: jobs a crash left running go back
    in the queue, and everything that came due while the bot was off runs
    now. Returns how many were put back, the jobs that ran late and those
    that were skipped as too late, for the start's message (core/restart.py)."""
    again = await database.run(_db_recover)
    if again:
        log.info("Scheduler: %s interrupted job(s) put back in the queue", again)
    done: list[Job] = []
    skipped: list[Job] = []
    await run_all_due(done, skipped)
    return again, [job for job in done if job.is_late], skipped


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
