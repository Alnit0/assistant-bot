import tests  # noqa: F401  isort: skip  (first: sets safe test settings before core loads)

import asyncio
import unittest
from datetime import datetime, time, timedelta, timezone

from core import backup, scheduler
from core.config import TIMEZONE
from tests.helpers import DatabaseTestCase

UTC = timezone.utc


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


class TimeMathsTest(unittest.TestCase):
    def test_stored_moments_sort_in_time_order(self):
        base = datetime(2026, 10, 7, 9, 59, 59, tzinfo=UTC)
        moments = [base, base + timedelta(microseconds=1), base + timedelta(seconds=1), base + timedelta(hours=14)]
        stored = [scheduler.to_db(moment) for moment in moments]
        self.assertEqual(stored, sorted(stored))
        self.assertEqual(len({len(text) for text in stored}), 1, "fixed width, so text order is time order")
        self.assertEqual([scheduler.from_db(text) for text in stored], moments)

    def test_stored_moments_are_utc_whatever_the_input_zone(self):
        self.assertEqual(scheduler.to_db(nz(2026, 10, 7, 15, 0)), "2026-10-07T02:00:00.000000+00:00")

    def test_seconds_late(self):
        due = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        self.assertEqual(scheduler.seconds_late(due, due + timedelta(seconds=90)), 90)
        self.assertEqual(scheduler.seconds_late(due, due - timedelta(seconds=30)), 0)

    def test_a_job_is_late_after_a_minute(self):
        due = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        on_time = scheduler.Job(1, None, "s", "k", {}, due, late_by=14)
        late = scheduler.Job(1, None, "s", "k", {}, due, late_by=61)
        self.assertFalse(on_time.is_late)
        self.assertTrue(late.is_late)

    def test_sleeps_until_the_next_job_but_never_longer_than_a_tick(self):
        now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        self.assertEqual(scheduler.seconds_until_next_look(now, None), scheduler.TICK_SECONDS)
        self.assertEqual(scheduler.seconds_until_next_look(now, now + timedelta(hours=1)), scheduler.TICK_SECONDS)
        self.assertEqual(scheduler.seconds_until_next_look(now, now + timedelta(seconds=4)), 4)

    def test_an_overdue_job_nobody_handles_does_not_make_the_loop_spin(self):
        now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        self.assertEqual(scheduler.seconds_until_next_look(now, now - timedelta(hours=2)), scheduler.TICK_SECONDS)

    def test_next_run_picks_the_next_3am_in_nz(self):
        three = time(3, 0)
        self.assertEqual(scheduler.next_run(three, nz(2026, 10, 6, 14, 0)), nz(2026, 10, 7, 3, 0))
        self.assertEqual(scheduler.next_run(three, nz(2026, 10, 6, 2, 59)), nz(2026, 10, 6, 3, 0))
        self.assertEqual(scheduler.next_run(three, nz(2026, 10, 6, 3, 0)), nz(2026, 10, 7, 3, 0))

    def test_next_run_across_daylight_saving(self):
        three = time(3, 0)

        def hours_between(start):
            return (scheduler.next_run(three, start).timestamp() - start.timestamp()) / 3600

        # Clocks go forward on 27 Sep 2026 (a 23-hour day) and back on 4 Apr 2027 (25 hours)
        self.assertEqual(hours_between(nz(2026, 9, 26, 3, 0)), 23)
        self.assertEqual(hours_between(nz(2027, 4, 3, 3, 0)), 25)


class SchedulerDatabaseTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.ran: list[scheduler.Job] = []
        self._handlers = dict(scheduler._handlers)

        async def handler(job):
            self.ran.append(job)

        scheduler.register_handler("test", "ping", handler)

    def tearDown(self):
        scheduler._handlers.clear()
        scheduler._handlers.update(self._handlers)
        super().tearDown()

    def statuses(self):
        return self.query("SELECT kind, status FROM scheduled_jobs ORDER BY id")

    async def test_a_job_runs_once_when_due_and_not_before(self):
        now = scheduler.utc_now()
        job_id = await scheduler.add_job("test", "ping", now + timedelta(seconds=30), {"n": 1}, user_id=1)
        self.assertEqual(await scheduler.run_due(now), 0)
        self.assertEqual(self.ran, [])

        self.assertEqual(await scheduler.run_due(now + timedelta(seconds=31)), 1)
        self.assertEqual([(job.id, job.payload, job.user_id) for job in self.ran], [(job_id, {"n": 1}, 1)])
        self.assertFalse(self.ran[0].is_late)

        self.assertEqual(await scheduler.run_due(now + timedelta(minutes=5)), 0, "never runs twice")
        self.assertEqual(self.statuses(), [("ping", "done")])

    async def test_jobs_missed_while_offline_run_late_in_due_order(self):
        now = scheduler.utc_now()
        await scheduler.add_job("test", "ping", now - timedelta(minutes=10), {"which": "second"})
        await scheduler.add_job("test", "ping", now - timedelta(hours=2), {"which": "first"})
        await scheduler.run_due(now)
        self.assertEqual([job.payload["which"] for job in self.ran], ["first", "second"])
        self.assertTrue(all(job.is_late for job in self.ran))
        self.assertAlmostEqual(self.ran[0].late_by, 7200, delta=1)
        late = self.query("SELECT late_by_s FROM scheduled_jobs ORDER BY id")
        self.assertAlmostEqual(late[0][0], 600, delta=1)

    async def test_a_failing_handler_is_recorded_and_does_not_stop_the_rest(self):
        async def broken(job):
            raise RuntimeError("kaboom")

        scheduler.register_handler("test", "broken", broken)
        now = scheduler.utc_now()
        await scheduler.add_job("test", "broken", now - timedelta(seconds=2))
        await scheduler.add_job("test", "ping", now - timedelta(seconds=1))
        self.assertEqual(await scheduler.run_due(now), 2)
        self.assertEqual(self.statuses(), [("broken", "failed"), ("ping", "done")])
        self.assertEqual(self.query("SELECT error FROM scheduled_jobs WHERE kind = 'broken'"), [("RuntimeError('kaboom')",)])
        self.assertEqual(len(self.ran), 1)

    async def test_a_job_for_a_skill_that_is_not_loaded_waits(self):
        now = scheduler.utc_now()
        await scheduler.add_job("absent", "thing", now - timedelta(minutes=1))
        self.assertEqual(await scheduler.run_due(now), 0)
        self.assertEqual(self.statuses(), [("thing", "pending")])

        scheduler.register_handler("absent", "thing", scheduler._handlers[("test", "ping")])
        self.assertEqual(await scheduler.run_due(now), 1)

    async def test_cancel_and_reschedule(self):
        now = scheduler.utc_now()
        cancelled = await scheduler.add_job("test", "ping", now + timedelta(seconds=10), {"job": "cancelled"})
        moved = await scheduler.add_job("test", "ping", now + timedelta(seconds=10), {"job": "moved"})
        self.assertTrue(await scheduler.cancel_job(cancelled))
        self.assertFalse(await scheduler.cancel_job(cancelled), "already cancelled")
        self.assertTrue(await scheduler.reschedule_job(moved, now + timedelta(minutes=30)))

        await scheduler.run_due(now + timedelta(minutes=1))
        self.assertEqual(self.ran, [])
        await scheduler.run_due(now + timedelta(minutes=31))
        self.assertEqual([job.payload["job"] for job in self.ran], ["moved"])
        self.assertFalse(await scheduler.reschedule_job(moved, now), "already ran")
        self.assertFalse(await scheduler.cancel_job(None))

    async def test_a_job_interrupted_by_a_crash_is_retried(self):
        from core import database

        now = scheduler.utc_now()
        job_id = await scheduler.add_job("test", "ping", now - timedelta(seconds=5))
        self.assertTrue(await database.run(scheduler._db_claim, job_id))  # as if it had started...
        self.assertEqual(await scheduler.run_due(now), 0)  # ...and the bot died: nothing picks it up

        self.assertEqual(await database.run(scheduler._db_recover), 1)  # what the loop does at startup
        self.assertEqual(await scheduler.run_due(now), 1)

    async def test_the_loop_wakes_for_a_job_due_sooner_than_the_next_tick(self):
        task, wake = scheduler._task, scheduler._wake
        scheduler._task = None
        scheduler.start()
        try:
            await asyncio.sleep(0.05)  # the loop is now asleep for a whole tick
            await scheduler.add_job("test", "ping", scheduler.utc_now() + timedelta(seconds=0.3))
            await asyncio.sleep(0.8)
            self.assertEqual(len(self.ran), 1, "ran at its due time, not at the next 15-second tick")
        finally:
            scheduler._task.cancel()
            scheduler._task, scheduler._wake = task, wake

    async def test_pending_jobs_lists_only_what_is_still_to_run(self):
        now = scheduler.utc_now()
        first = await scheduler.add_job("test", "ping", now + timedelta(hours=1))
        await scheduler.add_job("test", "other", now + timedelta(hours=2))
        done = await scheduler.add_job("test", "ping", now - timedelta(seconds=1))
        await scheduler.run_due(now)
        self.assertEqual([job.id for job in await scheduler.pending_jobs("test", "ping")], [first])
        self.assertEqual(len(await scheduler.pending_jobs("test")), 2)
        self.assertNotIn(done, [job.id for job in await scheduler.pending_jobs("test")])


class NightlyBackupTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.backups = 0
        self._real_run = backup.run_nightly_backup

        async def fake_backup():
            self.backups += 1

        backup.run_nightly_backup = fake_backup
        scheduler.register_handler(backup.JOB_SKILL, backup.JOB_KIND, backup.nightly_backup_job)

    def tearDown(self):
        backup.run_nightly_backup = self._real_run
        super().tearDown()

    async def test_exactly_one_backup_is_booked_at_3am_nz(self):
        await backup.schedule_next_backup()
        await backup.schedule_next_backup()  # a second start must not book a second one
        jobs = await scheduler.pending_jobs(backup.JOB_SKILL, backup.JOB_KIND)
        self.assertEqual(len(jobs), 1)
        local = jobs[0].due_at.astimezone(TIMEZONE)
        self.assertEqual((local.hour, local.minute), (3, 0))
        self.assertGreater(jobs[0].due_at, scheduler.utc_now())

    async def test_running_the_backup_books_the_next_one(self):
        await backup.schedule_next_backup()
        first = (await scheduler.pending_jobs(backup.JOB_SKILL))[0]
        await scheduler.run_due(first.due_at + timedelta(seconds=1))
        self.assertEqual(self.backups, 1)
        following = await scheduler.pending_jobs(backup.JOB_SKILL)
        self.assertEqual(len(following), 1)
        self.assertNotEqual(following[0].id, first.id)

    async def test_a_backup_missed_while_offline_runs_at_the_next_start(self):
        await scheduler.add_job(backup.JOB_SKILL, backup.JOB_KIND, scheduler.utc_now() - timedelta(hours=9))
        await scheduler.run_due()
        self.assertEqual(self.backups, 1)
        self.assertEqual(self.query("SELECT status, late_by_s > 32000 FROM scheduled_jobs ORDER BY id LIMIT 1"), [("done", 1)])
        self.assertEqual(len(await scheduler.pending_jobs(backup.JOB_SKILL)), 1, "and tomorrow's is booked")

    async def test_the_next_backup_is_booked_even_if_this_one_fails(self):
        async def broken():
            raise OSError("disk full")

        backup.run_nightly_backup = broken
        await scheduler.add_job(backup.JOB_SKILL, backup.JOB_KIND, scheduler.utc_now() - timedelta(seconds=1))
        await scheduler.run_due()
        self.assertEqual(self.query("SELECT status FROM scheduled_jobs ORDER BY id"), [("failed",), ("pending",)])


if __name__ == "__main__":
    unittest.main()
