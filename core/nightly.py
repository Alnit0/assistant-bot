import asyncio
import logging
import sys
from datetime import datetime, time

from core import config, scheduler, timetable
from core.discord_utils import log_error

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The nightly self-test (behind NIGHTLY_SELFTEST, off unless switched on).
#
# At 3:00 am live starts `python -m selftest --nightly` as a process of its
# own: the dev bot runs it, and live carries on. What is run is the stages
# touched since each last passed, and everything on a Sunday. The run says
# what happened itself: its summary in the self-test's log channel, a bug a
# failing step, a line of history, and a ping on my phone only if a step
# failed (selftest/notify.py).
#
# Live only starts it and looks at how it ended: a run that could not start
# (no dev bot, too little memory, a channel gone) is a real problem and is
# said in #bot-log. Steps that failed are not live's to report: the run did.
#
# Only live has this job. The dev bot never starts a self-test of itself.
# When it runs is a schedule like any other: `my schedule` moves it. A night
# the bot was off for is skipped once it is three hours late: a self-test in
# the middle of the morning is nobody's wish.
# ---------------------------------------------------------------------------
JOB_TASK, JOB_KIND = "core", "nightly_selftest"
JOB_LABEL = "nightly self-test"
AT = time(3, 0)
DEFAULT = timetable.Default("Nightly self-test", AT, channel="bot-log", missed=timetable.skip_after(180))
LOG_NAME = "selftest-nightly.log"
SUNDAY = 6
# How the run ends when it could not start at all (selftest/__main__.py), in words for #bot-log
NOT_STARTED = {
    2: "it was asked for a stage that does not exist",
    3: "the dev bot was already running, or there is no dev bot (.env.dev has no token of its own) and live is running",
    4: "too little memory was free",
    5: "one of the self-test's channels is not set in .env.dev, or has gone",
}

_running: asyncio.subprocess.Process | None = None
_watching: asyncio.Task | None = None


def enabled() -> bool:
    """Switched on, and this is live: the dev bot never tests itself."""
    return config.NIGHTLY_SELFTEST and not config.DEV_DATABASE


def is_full(local_at: str | None, now: datetime) -> bool:
    """Everything on a Sunday: by the day the run stands for, not the moment it happens to start."""
    try:
        day = datetime.fromisoformat(local_at) if local_at else now.astimezone(config.TIMEZONE)
    except ValueError:
        day = now.astimezone(config.TIMEZONE)
    return day.weekday() == SUNDAY


def command(full: bool) -> list[str]:
    """What is started. Recorded answers only: a nightly run costs nothing."""
    return [sys.executable, "-m", "selftest", "--nightly", *(["--full"] if full else [])]


def how_it_ended(code: int | None) -> str:
    """"" for a run that ran (steps passing or failing is its own to report), else why it did not."""
    if code in (0, 1):
        return ""
    return NOT_STARTED.get(code, f"it ended with code {code}")


async def _watch(process, full: bool) -> None:
    code = await process.wait()
    wrong = how_it_ended(code)
    if wrong:
        log.error("Nightly self-test did not run: %s (exit code %s; logs/%s)", wrong, code, LOG_NAME)
        await log_error("Nightly self-test did not run", f"{wrong.capitalize()}. Its own words are in `logs/{LOG_NAME}`.")
    else:
        log.info("Nightly self-test (%s) ended: %s", "full" if full else "touched stages", "every step passed, or nothing to run" if code == 0 else "a step failed: see its summary and its bug")


async def start(full: bool):
    """Start the run as a process of its own, with nothing of live's in its
    environment (it must read the dev bot's settings for itself)."""
    out = open(config.LOG_DIR / LOG_NAME, "ab")  # noqa: SIM115 (the process keeps it)
    try:
        return await asyncio.create_subprocess_exec(
            *command(full), cwd=str(config.BASE_DIR), env=config.environment_for_child(), stdout=out, stderr=asyncio.subprocess.STDOUT,
        )
    finally:
        out.close()  # the child has its own handle


async def nightly_job(job: scheduler.Job) -> None:
    """Scheduler handler. It only starts the run and returns: a self-test
    takes a quarter of an hour, and the engine must not wait for it."""
    global _running, _watching
    if not enabled():
        scheduler.note(job, "off (NIGHTLY_SELFTEST)")
        log.info("Nightly self-test: off (NIGHTLY_SELFTEST), nothing started")
        return
    if _running is not None and _running.returncode is None:
        scheduler.report(job, scheduler.SKIPPED)
        scheduler.note(job, "the last one is still running")
        await log_error("Nightly self-test not started", "The last one is still running.")
        return
    full = is_full(job.local_at, scheduler.utc_now())
    try:
        _running = await start(full)
    except OSError as error:
        scheduler.report(job, scheduler.FAILED)
        scheduler.note(job, f"could not be started: {error}")
        await log_error("Nightly self-test could not be started", repr(error))
        return
    _watching = asyncio.create_task(_watch(_running, full), name="nightly self-test")
    what = "everything (Sunday)" if full else "the stages touched since each last passed"
    scheduler.note(job, f"started as the dev bot: {what}; the result is in the self-test's log channel")
    log.info("Nightly self-test started (PID %s): %s", _running.pid, what)


def setup() -> None:
    """Live's own: the handler always (so a run booked before the switch went
    off says "off" and does nothing), the schedule only while it is on."""
    if config.DEV_DATABASE:
        return
    scheduler.register_handler(JOB_TASK, JOB_KIND, nightly_job, JOB_LABEL)
    if enabled():
        scheduler.default_schedule(JOB_TASK, JOB_KIND, DEFAULT)
