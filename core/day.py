import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone

from core import clock, scheduler, timetable
from core.config import DAY_BOUNDARY, TIMEZONE
from core.discord_utils import log_error

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The day: when one ends and the next begins, the same for every task.
#
# The boundary is DAY_BOUNDARY on the NZ clock (midnight). A "day" here is a
# date: the one the boundary started. Ask this file which day a moment
# belongs to, when a day starts and ends, and what moment a local time is on a
# given day; never work it out from a datetime's own date, so a change to the
# boundary reaches everything at once.
#
# Moments handed back are UTC, so adding hours to them is real elapsed time
# even across a daylight-saving change.
#
# When a day ends, the scheduler runs one job that tells every listener
# (`on_new_day`), then books itself for the next boundary. Like any job it
# runs late if the bot was off, and several days may have gone by: a
# listener is told the day that ended when the job was due and the day it is
# now, and deals with any days in between.
# ---------------------------------------------------------------------------
JOB_TASK = "core"
JOB_KIND = "day_rollover"
JOB_LABEL = "end of the day"  # what it is called wherever I read it

_OFFSET = timedelta(hours=DAY_BOUNDARY.hour, minutes=DAY_BOUNDARY.minute)


# ---------------------------------------------------------------------------
# Which day, and when (pure)
# ---------------------------------------------------------------------------
def day_of(moment: datetime) -> date:
    """The day a moment belongs to."""
    return (moment.astimezone(TIMEZONE).replace(tzinfo=None) - _OFFSET).date()


def today(now: datetime | None = None) -> date:
    """The day it is now, by the bot's clock."""
    return day_of(now or clock.now())


def at(day: date, local: time) -> datetime:
    """The moment the NZ clock reads `local` during `day`. UTC.

    With the boundary at midnight that is simply the time on that date; a
    time before a later boundary belongs to the next date's small hours.
    """
    on = day if local >= DAY_BOUNDARY else day + timedelta(days=1)
    return datetime.combine(on, local, tzinfo=TIMEZONE).astimezone(timezone.utc)


def start_of(day: date) -> datetime:
    """The moment `day` begins. UTC."""
    return at(day, DAY_BOUNDARY)


def end_of(day: date) -> datetime:
    """The moment `day` ends, which is when the next begins. UTC."""
    return start_of(day + timedelta(days=1))


def local_time(moment: datetime) -> time:
    """What the NZ clock reads at a moment, to the minute."""
    return moment.astimezone(TIMEZONE).time().replace(second=0, microsecond=0)


def seconds_left(now: datetime | None = None) -> float:
    """How long until today ends."""
    now = now or clock.now()
    return (end_of(day_of(now)) - now).total_seconds()


# ---------------------------------------------------------------------------
# The rollover: one scheduler job at a time, which books the next when it runs
# ---------------------------------------------------------------------------
# Told (the day that ended, the day it is now)
Listener = Callable[[date, date], Awaitable[None]]

_listeners: dict[str, Listener] = {}


def on_new_day(name: str, listener: Listener) -> None:
    """Have `listener(ended, started)` called each time a day ends. `name` says
    whose it is, for the log, and registering again replaces it."""
    _listeners[name] = listener


# When it runs is a schedule (core/timetable.py), the bot's own: the day boundary on the NZ
# clock, every day, however late. Locked: it follows the setting, and is not changed by words
DEFAULT = timetable.Default("End of the day", DAY_BOUNDARY, channel="bot-log", locked=True)
scheduler.default_schedule(JOB_TASK, JOB_KIND, DEFAULT)


async def schedule_next() -> None:
    """Make sure the rollover is booked, for the end of today as the clock now
    reads (the engine books every schedule; this is the same call)."""
    await scheduler.book()


async def rollover_job(job: scheduler.Job) -> None:
    """Scheduler handler: a day has ended. Tell every listener. (The engine
    books the next one from the schedule.)

    One listener failing is reported and the others are still told."""
    # The job is due the moment a day ends: the instant before belongs to that day. When it
    # stands in for days the bot was off for, the first of them is the day that ended
    ended, started = day_of((job.first_due or job.due_at) - timedelta(microseconds=1)), today()
    if job.is_late:
        log.info("Day rollover for %s is running %.0f minutes late", ended, job.late_by / 60)
    for name, listener in list(_listeners.items()):
        try:
            await listener(ended, started)
        except Exception as error:
            log.exception("New-day work failed for %s", name)
            await log_error(f"New-day work failed: {name}", repr(error))
    scheduler.note(job, f"{ended.isoformat()} closed; today is {started.isoformat()}")
