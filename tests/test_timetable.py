"""Schedules as rows (core/timetable.py) and the engine that books and runs them (core/scheduler.py)."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core import clock, database, day, scheduler, timetable
from core.timetable import ALL_DAYS, ON, PAUSED, REMOVED, Default, Schedule

NZ = ZoneInfo("Pacific/Auckland")


def run(coroutine):
    return asyncio.run(coroutine)


def schedule(at=time(6, 0), days=ALL_DAYS, state=ON, paused_until=None, missed=timetable.RUN_LATE) -> Schedule:
    return Schedule(1, 1, "Morning", at, timetable.ZONE, tuple(days), timetable.SILENT, "hub", state, paused_until, missed, timetable.MINE, None, False, ("pills.checklist",))


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=NZ)


def local(moment: datetime) -> str:
    return f"{moment.astimezone(NZ):%Y-%m-%d %H:%M}"


# --- pure: the wall clock -------------------------------------------------------------------------------------
def test_a_schedule_is_wall_clock_time_summer_and_winter():
    # In 2026 the clocks go back on 5 April and forward on 27 September
    six = schedule()
    for start in (nz(2026, 4, 3, 12, 0), nz(2026, 9, 25, 12, 0)):
        moment = start
        for _ in range(5):
            coming = timetable.next_occurrence(six, moment)
            assert coming.local.time() == time(6, 0) and local(coming.moment).endswith("06:00"), "6:00 am by the wall clock, every day of both weeks"
            assert coming.moment > moment
            moment = coming.moment
    winter, summer = timetable.moment_of(date(2026, 7, 1), time(6, 0)), timetable.moment_of(date(2026, 1, 1), time(6, 0))
    assert winter.hour == 18 and summer.hour == 17, "the moment differs by the hour the wall clock does not"


def test_a_time_that_does_not_exist_runs_once_at_the_moment_the_clocks_jump_to():
    # 27 September 2026: 2:00 am becomes 3:00 am
    half_past_two = schedule(at=time(2, 30))
    coming = timetable.next_occurrence(half_past_two, nz(2026, 9, 26, 12, 0))
    assert coming.stamp == "2026-09-27T02:30" and local(coming.moment) == "2026-09-27 03:00"
    after = timetable.next_occurrence(half_past_two, coming.moment)
    assert after.stamp == "2026-09-28T02:30" and local(after.moment) == "2026-09-28 02:30", "once that day, and the next day as usual"


def test_a_time_that_happens_twice_runs_once_at_the_first():
    # 5 April 2026: 3:00 am becomes 2:00 am, so 2:30 am happens twice
    half_past_two = schedule(at=time(2, 30))
    coming = timetable.next_occurrence(half_past_two, nz(2026, 4, 4, 12, 0))
    assert coming.stamp == "2026-04-05T02:30" and coming.moment == datetime(2026, 4, 4, 13, 30, tzinfo=timezone.utc), "the first 2:30, still on summer time"
    after = timetable.next_occurrence(half_past_two, coming.moment)
    assert after.stamp == "2026-04-06T02:30", "the second 2:30 that night is the same local time: the same key, so no second run"
    assert timetable.run_key(7, coming.stamp, 1) == "s7@2026-04-05T02:30#1"


def test_days_of_the_week_and_what_is_off():
    weekdays = schedule(days=(0, 1, 2, 3, 4))
    friday_noon = nz(2026, 10, 16, 12, 0)
    assert timetable.next_occurrence(weekdays, friday_noon).stamp == "2026-10-19T06:00", "Friday noon: next is Monday"
    assert timetable.last_occurrence(weekdays, nz(2026, 10, 18, 12, 0)).stamp == "2026-10-16T06:00", "on Sunday the last was Friday"
    assert timetable.next_occurrence(schedule(days=()), friday_noon) is None
    assert timetable.next_occurrence(schedule(state=REMOVED), friday_noon) is None
    assert timetable.next_occurrence(schedule(state=PAUSED), friday_noon) is None, "paused until told: nothing is booked"
    until = schedule(state=PAUSED, paused_until=date(2026, 10, 20))
    assert timetable.next_occurrence(until, friday_noon).stamp == "2026-10-20T06:00", "paused until a day: on again that day"
    assert timetable.next_occurrence(schedule(), nz(2026, 10, 16, 5, 0), skip_day=date(2026, 10, 16)).stamp == "2026-10-17T06:00"
    assert [each.stamp for each in timetable.between(schedule(), nz(2026, 10, 13, 7, 0), nz(2026, 10, 16, 7, 0))] == [
        "2026-10-14T06:00", "2026-10-15T06:00", "2026-10-16T06:00",
    ]


def test_the_words_for_days_and_the_missed_run_rule():
    assert timetable.days_text(ALL_DAYS) == "every day" and timetable.days_text((0, 1, 2, 3, 4)) == "Mon to Fri"
    assert timetable.days_text((5, 6)) == "Sat, Sun" and timetable.days_text((0, 2, 4)) == "Mon, Wed, Fri" and timetable.days_text(()) == "no day"
    assert timetable.skip_limit(timetable.RUN_LATE) is None and timetable.skip_limit(timetable.skip_after(360)) == timedelta(hours=6)


# --- the engine -----------------------------------------------------------------------------------------------
@pytest.fixture
def engine(db, dev_clock, monkeypatch):
    """A database, the dev clock at noon tomorrow, and two handlers that only record what ran."""
    seen = SimpleNamespace(ran=[], fail=set())

    def handler(name):
        async def ran(job):
            seen.ran.append((name, job.local_at, job.passed_over))
            scheduler.note(job, f"{name} ran")
            if name in seen.fail:
                raise RuntimeError("boom")

        return ran

    async def no_log(*args):
        pass

    monkeypatch.setattr(scheduler, "log_error", no_log)
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_labels", {})
    for kind in ("first", "second", "third"):
        scheduler.register_handler("test", kind, handler(kind))
    monkeypatch.setattr(scheduler, "_standing", {("test", "first"): Default("First thing", time(6, 0))})
    seen.day = day.today() + timedelta(days=1)
    clock.advance_to(day.at(seen.day, time(12, 0)))
    return seen


def rows(sql="SELECT kind, local_at, status FROM scheduled_jobs ORDER BY id", values=()):
    conn = database.connect()
    try:
        return conn.execute(sql, values).fetchall()
    finally:
        conn.close()


def schedules():
    conn = database.connect()
    try:
        return timetable.db_all(conn, removed=True)
    finally:
        conn.close()


def change(schedule_id, **changes):
    conn = database.connect()
    try:
        steps = changes.pop("steps", None)
        timetable.db_update(conn, schedule_id, clock.now(), **changes)
        if steps is not None:
            timetable.db_set_steps(conn, schedule_id, steps)
        conn.commit()
    finally:
        conn.close()
    run(scheduler.book())  # as whatever changes a schedule does, and as the loop does at its next look


def stamp(day_, at="06:00"):
    return f"{day_.isoformat()}T{at}"


def to(day_, hour, minute=0, second=0):
    clock.advance_to(day.at(day_, time(hour, minute, second)))
    return run(scheduler.run_all_due())


def test_a_default_becomes_a_row_once_and_its_next_run_is_booked_once(engine):
    run(scheduler.book())
    run(scheduler.book())
    (made,) = schedules()
    assert (made.name, made.at, made.days, made.steps, made.origin, made.default_key) == ("First thing", time(6, 0), ALL_DAYS, ("test.first",), "default", "test.first")
    assert made.user_id == 1 and not made.locked, "one a task supplied is the owner's to change"
    tomorrow = engine.day + timedelta(days=1)
    assert rows() == [("first", stamp(tomorrow), "pending")], "noon: the next 6:00 am is tomorrow's, booked once"
    assert rows("SELECT run_key FROM scheduled_jobs") == [(f"s{made.id}@{stamp(tomorrow)}#1",)]


def test_a_time_i_changed_is_still_mine_after_a_restart_and_one_i_removed_is_not_made_again(engine):
    run(scheduler.book())
    (made,) = schedules()
    change(made.id, at=time(7, 30))
    run(scheduler.book())  # the next start: the default says 6:00, the row says 7:30
    assert schedules()[0].at == time(7, 30)
    tomorrow = engine.day + timedelta(days=1)
    assert rows() == [("first", stamp(tomorrow), "cancelled"), ("first", stamp(tomorrow, "07:30"), "pending")], "the run booked for the old time is taken out"
    change(made.id, state=REMOVED)
    run(scheduler.book())
    assert len(schedules()) == 1 and schedules()[0].state == REMOVED, "still one row, so the default is never made a second time"
    assert [status for _, _, status in rows()] == ["cancelled", "cancelled"], "and nothing is booked for it"


def test_a_locked_one_follows_the_code_and_has_no_owner(engine, monkeypatch):
    monkeypatch.setattr(scheduler, "_standing", {("test", "first"): Default("The bot's own", time(3, 0), locked=True)})
    run(scheduler.book())
    (made,) = schedules()
    assert made.locked and made.user_id is None and made.at == time(3, 0)
    monkeypatch.setattr(scheduler, "_standing", {("test", "first"): Default("The bot's own", time(4, 0), locked=True)})
    run(scheduler.book())
    assert schedules()[0].at == time(4, 0), "the setting changed: the row follows it"


def test_it_runs_at_its_time_once_and_the_next_is_booked(engine):
    run(scheduler.book())
    tomorrow = engine.day + timedelta(days=1)
    assert to(tomorrow, 5, 59) == 0 and engine.ran == []
    assert to(tomorrow, 6, 0, 1) == 1 and engine.ran == [("first", stamp(tomorrow), 0)]
    assert run(scheduler.run_all_due()) == 0 and len(engine.ran) == 1, "asked again: nothing runs twice"
    assert rows()[-1] == ("first", stamp(tomorrow + timedelta(days=1)), "pending")
    assert rows("SELECT status, note FROM scheduled_jobs WHERE status = 'done'") == [("done", "first ran")], "what it decided is kept with the run"


def test_the_same_occurrence_is_never_booked_or_run_twice_even_after_a_restart(engine):
    run(scheduler.book())
    tomorrow = engine.day + timedelta(days=1)
    to(tomorrow, 6, 0, 1)
    # A restart: nothing in memory, the rows as they were; then the engine looks again and again
    for _ in range(3):
        run(scheduler.catch_up())
    assert len(engine.ran) == 1 and len(rows("SELECT 1 FROM scheduled_jobs WHERE local_at = ?", (stamp(tomorrow),))) == 1
    with pytest.raises(Exception):
        rows("INSERT INTO scheduled_jobs (skill, kind, payload, due_at, status, created_at, run_key) SELECT skill, kind, payload, due_at, 'pending', created_at, run_key FROM scheduled_jobs LIMIT 1")


def test_a_routine_runs_its_steps_in_order_each_recorded_and_one_failing_does_not_stop_the_rest(engine):
    # Two handlers join the schedule made for the first, in front of it: a routine
    scheduler.join_routine("test.first", "test.third", order=20, name="Morning routine")
    scheduler.join_routine("test.first", "test.second", order=10, name="Morning routine")
    run(scheduler.book())
    (made,) = schedules()
    assert made.steps == ("test.second", "test.third", "test.first") and made.name == "Morning routine", "in their order, its own handler last"
    engine.fail.add("third")
    tomorrow = engine.day + timedelta(days=1)
    to(tomorrow, 6, 0, 1)
    assert [name for name, _, _ in engine.ran] == ["second", "third", "first"]
    done = rows("SELECT kind, step, status, run_key FROM scheduled_jobs WHERE local_at = ? ORDER BY step", (stamp(tomorrow),))
    assert done == [
        ("second", 1, "done", f"s{made.id}@{stamp(tomorrow)}#1"), ("third", 2, "failed", f"s{made.id}@{stamp(tomorrow)}#2"),
        ("first", 3, "done", f"s{made.id}@{stamp(tomorrow)}#3"),
    ]
    assert run(scheduler.troubled()) == [("test", "third", "failed")]
    # Cut off half way: the steps already done are not done again
    after = tomorrow + timedelta(days=1)
    clock.advance_to(day.at(after, time(6, 0, 1)))
    run(scheduler.book())
    conn = database.connect()
    conn.execute("UPDATE scheduled_jobs SET status = 'done' WHERE local_at = ? AND step = 1", (stamp(after),))
    conn.commit()
    conn.close()
    engine.ran.clear()
    run(scheduler.catch_up())
    assert [name for name, _, _ in engine.ran] == ["third", "first"]


def test_what_joins_a_routine_follows_what_is_switched_on_and_the_rest_stays_mine(engine, monkeypatch):
    run(scheduler.book())
    (made,) = schedules()
    change(made.id, at=time(7, 15), notify=timetable.NOTIFY)
    assert made.steps == ("test.first",) and made.name == "First thing"
    # Switched on: the schedule gains the step in front, and is called a routine
    scheduler.join_routine("test.first", "test.second", order=20, name="Morning routine")
    run(scheduler.book())
    (on,) = schedules()
    assert (on.steps, on.name, on.at, on.notify, on.id) == (("test.second", "test.first"), "Morning routine", time(7, 15), "notify", made.id), "the time and the rest are still mine"
    tomorrow = engine.day + timedelta(days=1)
    assert sorted(kind for kind, local_at, status in rows() if status == "pending") == ["first", "second"], "the run already booked gains the step"
    # Switched off again: its own handler alone, under its own name, and the step's booked run is taken out
    monkeypatch.setattr(scheduler, "_joins", {})  # the name stays known: it is said whether or not anything has joined
    run(scheduler.book())
    (off,) = schedules()
    assert (off.steps, off.name, off.at) == (("test.first",), "First thing", time(7, 15))
    assert [kind for kind, local_at, status in rows() if status == "pending"] == ["first"]
    to(tomorrow, 7, 15, 1)
    assert [name for name, _, _ in engine.ran] == ["first"]
    # A name I gave it is never changed back
    change(made.id, name="My mornings")
    scheduler.join_routine("test.first", "test.second", order=20, name="Morning routine")
    run(scheduler.book())
    assert schedules()[0].name == "My mornings" and schedules()[0].steps == ("test.second", "test.first")


def test_off_for_three_days_only_the_latest_runs_and_is_told_how_many_were_passed_over(engine, monkeypatch):
    run(scheduler.book())
    first = engine.day + timedelta(days=1)
    clock.advance_to(day.at(first + timedelta(days=2), time(9, 0)))  # three 6:00 ams went by
    again, late, skipped = run(scheduler.catch_up())
    assert engine.ran == [("first", stamp(first + timedelta(days=2)), 2)], "one run, the latest, told that two were passed over"
    statuses = rows("SELECT local_at, status FROM scheduled_jobs ORDER BY local_at")
    assert statuses[:3] == [(stamp(first), "missed"), (stamp(first + timedelta(days=1)), "missed"), (stamp(first + timedelta(days=2)), "done")] or statuses[0] == (stamp(first), "missed")
    assert run(scheduler.troubled()) == [], "set aside by the engine is not trouble"
    assert [status for _, status in statuses].count("pending") == 1 and not skipped, "and the next one is booked"


def test_a_schedule_that_says_skip_when_too_late_is_not_run_and_it_is_said(engine, monkeypatch):
    run(scheduler.book())
    (made,) = schedules()
    change(made.id, missed=timetable.skip_after(360))
    tomorrow = engine.day + timedelta(days=1)
    due = day.at(tomorrow, time(6, 0))
    # Seven hours of real time with the bot off: not time the dev clock skipped
    monkeypatch.setattr(clock, "now", lambda: due + timedelta(hours=7))
    monkeypatch.setattr(clock, "skipped_between", lambda start, end: 0.0)
    again, late, skipped = run(scheduler.catch_up())
    assert engine.ran == [] and [job.kind for job in skipped] == ["first"] and not late
    assert rows("SELECT status, note FROM scheduled_jobs WHERE local_at = ?", (stamp(tomorrow),)) == [("missed", "skipped: 420 minutes late, and its limit is 360")]
    # Five hours late is within it: it runs, late
    change(made.id, missed=timetable.skip_after(600))
    monkeypatch.setattr(clock, "now", lambda: due + timedelta(days=1, hours=5))
    again, late, skipped = run(scheduler.catch_up())
    assert [name for name, _, _ in engine.ran] == ["first"] and len(late) == 1 and not skipped


def test_the_dev_clock_moved_ahead_is_not_lateness_and_moved_back_frees_the_real_runs(engine):
    run(scheduler.book())
    tomorrow = engine.day + timedelta(days=1)
    (made,) = schedules()
    change(made.id, missed=timetable.skip_after(60))
    to(tomorrow + timedelta(days=2), 8)  # jumped three days: one run, the latest, and not late
    assert engine.ran == [("first", stamp(tomorrow + timedelta(days=2)), 2)]
    assert rows("SELECT late_by_s < 61 FROM scheduled_jobs WHERE status = 'done'") == [(1,)]
    # Back to the real time: what ran "in three days" must not block the real one
    clock.reset()
    run(scheduler.clock_went_back())
    booked = [each for each in rows() if each[2] == "pending"]
    real_next = timetable.next_occurrence(schedules()[0], clock.now()).stamp
    assert booked == [("first", real_next, "pending")], "booked again for the time it now is"
    engine.ran.clear()
    clock.advance_to(day.at(tomorrow + timedelta(days=2), time(6, 0, 1)))
    run(scheduler.run_all_due())
    assert engine.ran and engine.ran[-1][1] == stamp(tomorrow + timedelta(days=2)), "the same local time runs for real, though it ran once on the moved clock"


def test_moved_after_it_ran_today_it_does_not_run_again_today_and_moved_before_it_runs_at_the_new_time(engine):
    run(scheduler.book())
    (made,) = schedules()
    tomorrow = engine.day + timedelta(days=1)
    to(tomorrow, 5, 0)
    change(made.id, at=time(7, 0))
    assert to(tomorrow, 6, 30) == 0, "moved before it ran: not at the old time"
    assert to(tomorrow, 7, 0, 1) == 1 and engine.ran[-1][1] == stamp(tomorrow, "07:00")
    change(made.id, at=time(9, 0))
    assert to(tomorrow, 9, 30) == 0, "moved after it ran: once a day"
    assert [each for each in rows() if each[2] == "pending"] == [("first", stamp(tomorrow + timedelta(days=1), "09:00"), "pending")]


def test_paused_it_does_not_run_and_it_is_back_on_the_day_it_says(engine):
    run(scheduler.book())
    (made,) = schedules()
    tomorrow = engine.day + timedelta(days=1)
    change(made.id, state=PAUSED, paused_until=tomorrow + timedelta(days=2))
    assert to(tomorrow + timedelta(days=1), 12) == 0 and engine.ran == []
    assert to(tomorrow + timedelta(days=2), 6, 0, 1) == 1 and engine.ran[-1][1] == stamp(tomorrow + timedelta(days=2))
    change(made.id, days=((tomorrow + timedelta(days=4)).weekday(),), state=ON, paused_until=None)
    assert to(tomorrow + timedelta(days=3), 12) == 0, "not one of its days"
    assert to(tomorrow + timedelta(days=4), 6, 0, 1) == 1


def test_a_one_off_with_a_key_is_booked_once_and_never_again_once_it_has_run(engine):
    due = clock.now() + timedelta(minutes=15)
    first = run(scheduler.add_job("test", "second", due, key="test.second@once"))
    assert run(scheduler.add_job("test", "second", due, key="test.second@once")) == first, "asked again while it waits: the same job"
    clock.advance(timedelta(minutes=16))
    run(scheduler.run_all_due())
    assert [name for name, _, _ in engine.ran] == ["second"]
    assert run(scheduler.add_job("test", "second", clock.now(), key="test.second@once")) is None, "it has run: nothing is booked"
    assert run(scheduler.add_job("test", "second", clock.now())) is not None, "one with no key is as it always was"


def test_firing_the_next_run_and_running_a_handler_by_hand_never_block_the_real_one(engine):
    run(scheduler.book())
    tomorrow = engine.day + timedelta(days=1)
    (waiting,) = run(scheduler.all_pending())
    assert run(scheduler.fire(waiting.id))
    run(scheduler.run_all_due())
    assert engine.ran == [("first", None, 0)], "run now, as a run of its own: it stands for no occurrence"
    assert [each for each in rows() if each[2] == "pending"] == [("first", stamp(tomorrow), "pending")], "the real 6:00 am is booked again"
    run(scheduler.run_now("test", "third"))
    assert engine.ran[-1][0] == "third" and rows("SELECT run_key LIKE 'manual:test.third:%' FROM scheduled_jobs WHERE kind = 'third'") == [(1,)]
    to(tomorrow, 6, 0, 1)
    assert engine.ran[-1] == ("first", stamp(tomorrow), 0)


def test_a_job_left_waiting_from_before_there_were_schedules_is_replaced_not_run_beside_them(engine):
    old = day.at(engine.day + timedelta(days=1), time(6, 0))
    run(scheduler.add_job("test", "first", old))  # as the old code booked it: no schedule, no key
    run(scheduler.book())
    assert [(local_at, status) for _, local_at, status in rows()] == [(None, "cancelled"), (stamp(engine.day + timedelta(days=1)), "pending")]
    to(engine.day + timedelta(days=1), 6, 0, 1)
    assert len(engine.ran) == 1, "one run that morning, not two"


def test_an_old_job_that_is_already_overdue_when_schedules_arrive_still_runs_once(engine):
    owed = clock.now() - timedelta(hours=2)
    run(scheduler.add_job("test", "first", owed))  # the bot was off over its time, and comes back on the new code
    run(scheduler.catch_up())
    assert engine.ran == [("first", None, 0)], "it was owed: it runs, as the one-off it was booked as"
    assert [status for _, _, status in rows()] == ["done", "pending"], "and the schedule's own first run is the next occurrence"


def test_the_reminders_one_job_is_a_keyed_one_off():
    from tasks.pills import reminders

    moment = datetime(2026, 10, 14, 1, 5, tzinfo=timezone.utc)
    assert reminders.job_key(moment) == "pills.remind@2026-10-14T01:05:00.000000+00:00"
