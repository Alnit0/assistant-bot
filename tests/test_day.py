"""The day boundary (core/day.py): which day a moment belongs to, and the rollover job."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone

import pytest

from core import clock, day, scheduler
from core.config import TIMEZONE

UTC = timezone.utc


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


# ---------------------------------------------------------------------------
# Which day, and when
# ---------------------------------------------------------------------------
def test_the_day_changes_at_midnight_in_nz():
    assert day.day_of(nz(2026, 10, 9, 23, 59, 59)) == date(2026, 10, 9)
    assert day.day_of(nz(2026, 10, 10, 0, 0)) == date(2026, 10, 10)
    # 11:30 on the 9th in UTC is already half past midnight on the 10th in NZ
    assert day.day_of(datetime(2026, 10, 9, 11, 30, tzinfo=UTC)) == date(2026, 10, 10)


def test_today_follows_the_clock(dev_clock):
    assert day.today() == day.day_of(clock.real_now())
    clock.advance(timedelta(days=2))
    assert day.today() == day.day_of(clock.real_now()) + timedelta(days=2)


def test_a_local_time_on_a_day_is_a_moment_in_utc():
    moment = day.at(date(2026, 10, 9), time(20, 0))
    assert moment == nz(2026, 10, 9, 20, 0)
    assert moment.tzinfo is UTC, "so adding hours is real elapsed time"
    assert day.local_time(moment) == time(20, 0)


def test_a_day_runs_from_its_start_to_the_next_ones():
    assert day.start_of(date(2026, 10, 9)) == nz(2026, 10, 9, 0, 0)
    assert day.end_of(date(2026, 10, 9)) == nz(2026, 10, 10, 0, 0) == day.start_of(date(2026, 10, 10))


@pytest.mark.parametrize("when, hours", [(date(2026, 10, 9), 24), (date(2026, 9, 27), 23), (date(2027, 4, 4), 25)])
def test_days_are_23_or_25_hours_long_when_the_clocks_change(when, hours):
    assert (day.end_of(when) - day.start_of(when)) / timedelta(hours=1) == hours


def test_seconds_left_today():
    assert day.seconds_left(nz(2026, 10, 9, 21, 50)) == 130 * 60
    # The clocks go forward at 2am on 27 Sep 2026: from 1am there are 22 hours left, not 23
    assert day.seconds_left(nz(2026, 9, 27, 1, 0)) == 22 * 3600


# ---------------------------------------------------------------------------
# The rollover job
# ---------------------------------------------------------------------------
@pytest.fixture
def rollover(db, monkeypatch):
    """A database, the rollover's handler registered, and no listeners but the test's."""
    monkeypatch.setattr(day, "_listeners", {})
    monkeypatch.setattr(scheduler, "_handlers", dict(scheduler._handlers))
    scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job)
    errors = []

    async def log_error(title, text):
        errors.append(title)

    monkeypatch.setattr(day, "log_error", log_error)
    return errors


def test_exactly_one_rollover_is_booked_for_the_end_of_today(rollover):
    async def scenario():
        await day.schedule_next()
        await day.schedule_next()  # a second start must not book a second one
        return await scheduler.pending_jobs(day.JOB_TASK, day.JOB_KIND)

    jobs = asyncio.run(scenario())
    assert [job.due_at for job in jobs] == [day.end_of(day.today())]


def test_listeners_are_told_which_day_ended_and_the_next_is_booked(rollover):
    told = []

    async def listener(ended, started):
        told.append((ended, started))

    async def scenario():
        day.on_new_day("test", listener)
        await day.schedule_next()
        midnight = day.end_of(day.today())
        ran = await scheduler.run_due(midnight + timedelta(seconds=1))
        return ran, await scheduler.pending_jobs(day.JOB_TASK, day.JOB_KIND)

    today = day.today()
    ran, following = asyncio.run(scenario())
    assert ran == 1
    assert told == [(today, today)], "the clock itself has not moved in this test, only the scheduler's look"
    assert len(following) == 1, "the next one is booked"


def test_after_days_away_the_listener_gets_the_gap(rollover, dev_clock):
    told = []

    async def listener(ended, started):
        told.append((ended, started))

    async def scenario():
        day.on_new_day("test", listener)
        await day.schedule_next()
        clock.advance(timedelta(days=3))
        await scheduler.run_all_due()
        return await scheduler.pending_jobs(day.JOB_TASK, day.JOB_KIND)

    began = day.today()
    following = asyncio.run(scenario())
    assert told == [(began, began + timedelta(days=3))], "one call, with the days in between for the listener to handle"
    assert [job.due_at for job in following] == [day.end_of(began + timedelta(days=3))]


def test_one_listener_failing_does_not_stop_the_others_or_the_next_booking(rollover):
    told = []

    async def broken(ended, started):
        raise RuntimeError("boom")

    async def fine(ended, started):
        told.append(started)

    async def scenario():
        day.on_new_day("broken", broken)
        day.on_new_day("fine", fine)
        await day.schedule_next()
        await scheduler.run_due(day.end_of(day.today()) + timedelta(seconds=1))
        return await scheduler.pending_jobs(day.JOB_TASK, day.JOB_KIND)

    following = asyncio.run(scenario())
    assert len(told) == 1
    assert rollover == ["New-day work failed: broken"]
    assert len(following) == 1


def test_a_task_that_overrides_new_day_is_a_listener(monkeypatch):
    from tasks import registry
    from tasks.base import Task

    class Plain(Task):
        name = "plain"

    class Daily(Task):
        name = "daily"

        async def new_day(self, ended, started):
            pass

    assert type(Plain()).new_day is Task.new_day
    assert type(Daily()).new_day is not Task.new_day
    # No task in the repository listens yet: loading registers none
    monkeypatch.setattr(day, "_listeners", {})
    registry.load()
    assert day._listeners == {}
