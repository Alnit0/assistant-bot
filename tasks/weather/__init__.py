import logging
from datetime import date, datetime, time

from core import clock, config, database, design, scheduler, summaries, timeinput, timetable
from core import day as days
from core.actions import Summary
from tasks.base import Task
from tasks.weather import rules, source, store

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Weather: today's forecast as a section of the briefing. Behind
# WEATHER_ENABLED (on unless switched off): off, this task offers nothing.
#
# It has nothing to route to (no plain words, no card) and nothing of
# Discord's: it fetches, keeps what it fetched, and says it through the
# summary contract (core/summaries.py), so the briefing shows it with no
# change there. The briefing only reads what was kept: it never waits on
# the network.
#
# When is the engine's business. Two schedules, both in "my schedule":
#   Weather fetch     5:50 am, before the morning routine. A fetch that
#                     fails here is a failed job: it needs a look.
#   Weather refresh   8:50 am, and from it every three hours until 8:00 pm
#                     (one-off runs with a key each), so the briefing, which
#                     is edited in place, stays current. A refresh that fails
#                     keeps the forecast it had and says so in its line.
# No request to Claude: the words are a template (rules.py).
# ---------------------------------------------------------------------------
TASK = "weather"
ICON = "🌤️"
FETCH, REFRESH, LATER = "fetch", "refresh", "refresh_later"
FETCH_DEFAULT = timetable.Default("Weather fetch", time(5, 50))
REFRESH_DEFAULT = timetable.Default("Weather refresh", time(8, 50))


def enabled() -> bool:
    return bool(config.WEATHER_ENABLED)


async def update(user_id: int) -> str:
    """Fetch today's forecast and keep it. Returns "" if that worked, else why
    not, in words (the forecast it had is left as it was). Never raises."""
    today = days.today()
    try:
        data = await source.fetch()
        rules.read(data)  # one that can't be read is not kept
    except Exception as error:
        why = str(error) if isinstance(error, (source.NoPlace, ValueError)) else type(error).__name__
        log.warning("Weather: the forecast could not be fetched (%s)", why)
        await database.run(store.db_failed, user_id, today, clock.now())
        summaries.changed(TASK, user_id)
        return why
    await database.run(store.db_keep, user_id, today, data, clock.now())
    summaries.changed(TASK, user_id)
    return ""


async def _owner(job: scheduler.Job) -> int | None:
    return job.user_id or await database.run(scheduler._db_owner)


async def fetch_job(job: scheduler.Job) -> None:
    """Scheduler handler: the morning's fetch. A failure is a failed job."""
    user_id = await _owner(job)
    if user_id is None:
        scheduler.note(job, "not fetched: there is no owner yet")
        return
    wrong = await update(user_id)
    if wrong:
        scheduler.report(job, scheduler.FAILED)
        scheduler.note(job, f"not fetched ({wrong}): the briefing says Weather unavailable")
        return
    scheduler.note(job, "fetched: " + await _line(user_id))


async def refresh_job(job: scheduler.Job) -> None:
    """Scheduler handler: the first refresh of the day, and the day's later ones booked from it."""
    user_id = await _owner(job)
    if user_id is None:
        scheduler.note(job, "not refreshed: there is no owner yet")
        return
    wrong = await update(user_id)
    start = datetime.fromisoformat(job.local_at).time() if job.local_at else REFRESH_DEFAULT.at
    today = days.today()
    for hour, minute in rules.later(start.hour, start.minute):
        due = days.at(today, time(hour, minute))
        if due > clock.now():
            await scheduler.add_job(TASK, LATER, due, user_id=user_id, key=f"{TASK}.{LATER}@{today.isoformat()}T{hour:02d}:{minute:02d}")
    scheduler.note(job, (f"not refreshed ({wrong}): the last forecast stays" if wrong else "refreshed: " + await _line(user_id)) + "; again every 3 hours until 8:00 pm")


async def later_job(job: scheduler.Job) -> None:
    """Scheduler handler: one of the day's later refreshes."""
    user_id = await _owner(job)
    if user_id is None:
        return
    wrong = await update(user_id)
    scheduler.note(job, f"not refreshed ({wrong}): the last forecast stays" if wrong else "refreshed: " + await _line(user_id))


async def _line(user_id: int) -> str:
    said = await summary_for(user_id, days.today())
    return " · ".join([said.glance, *said.lines]) if said is not None else "nothing kept"


async def summary_for(user_id: int, day: date) -> Summary | None:
    """Today's weather in one or two lines, from what was kept. None before
    anything was fetched for that day; "Weather unavailable" when a fetch
    failed and there is no forecast to show. Read only."""
    kept = await database.run(store.db_get, user_id, day)
    if kept is None:
        return None
    try:
        forecast = rules.read(kept.data) if kept.data is not None else None
    except ValueError:
        forecast = None
    if forecast is None:
        return Summary("", design.QUIET, (rules.UNAVAILABLE,))
    hint = f"updated {timeinput.format_moment(kept.fetched_at)}" if kept.fetched_at is not None else ""
    return Summary(rules.glance(forecast), design.QUIET, (rules.detail(forecast),), hint)


class WeatherTask(Task):
    """Weather: today's forecast, a section of the briefing."""

    name = TASK
    description = "Weather: today's forecast in the briefing, kept current through the day"
    icon = ICON

    def job_handlers(self) -> dict:
        return {FETCH: fetch_job, REFRESH: refresh_job, LATER: later_job} if enabled() else {}

    def job_labels(self) -> dict:
        return {FETCH: "weather fetch", REFRESH: "weather refresh", LATER: "weather refresh"} if enabled() else {}

    def migrations(self) -> list:
        return store.MIGRATIONS

    def setup(self, client) -> None:
        if not enabled():
            return
        scheduler.default_schedule(TASK, FETCH, FETCH_DEFAULT)
        scheduler.default_schedule(TASK, REFRESH, REFRESH_DEFAULT)

    async def summary(self, user_id: int, day: date):
        return await summary_for(user_id, day) if enabled() else None


task = WeatherTask()
