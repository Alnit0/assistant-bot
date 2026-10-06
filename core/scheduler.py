import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from core.config import TIMEZONE, now_nz

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Scheduler
#
# Deliberately small for now: jobs that run once a day at a fixed NZ local
# time, registered in code and held in memory. A job missed while the bot is
# down is not caught up. This will be expanded later (stored schedules,
# recurrence rules, per-user timezones) for reminders and other skills.
# ---------------------------------------------------------------------------
MAX_SLEEP = 300  # seconds; waking regularly keeps us on time if the clock changes


@dataclass(frozen=True)
class DailyJob:
    name: str
    at: time
    func: Callable[[], Awaitable[None]]


_jobs: list[DailyJob] = []
_tasks: list[asyncio.Task] = []


def add_daily_job(name: str, at: time, func: Callable[[], Awaitable[None]]) -> None:
    """Register a job to run every day when the clock in NZ reads `at`."""
    _jobs.append(DailyJob(name, at, func))


def next_run(at: time, now: datetime) -> datetime:
    """The next moment after `now` when the clock in NZ reads `at`."""
    today = now.astimezone(TIMEZONE).date()
    candidate = datetime.combine(today, at, tzinfo=TIMEZONE)
    # Compare as timestamps: these are real moments, whatever daylight saving is doing
    if candidate.timestamp() <= now.timestamp():
        candidate = datetime.combine(today + timedelta(days=1), at, tzinfo=TIMEZONE)
    return candidate


async def _run_daily(job: DailyJob) -> None:
    while True:
        target = next_run(job.at, now_nz())
        log.info("Next %s: %s", job.name, target.isoformat())
        while (remaining := target.timestamp() - now_nz().timestamp()) > 0:
            await asyncio.sleep(min(remaining, MAX_SLEEP))
        try:
            await job.func()
        except Exception:
            log.exception("Scheduled job failed: %s", job.name)


def start() -> None:
    """Start every registered job. Safe to call again (on_ready fires after reconnects)."""
    if _tasks:
        return
    for job in _jobs:
        _tasks.append(asyncio.create_task(_run_daily(job), name=f"daily: {job.name}"))
