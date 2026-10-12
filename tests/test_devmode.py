import tests  # noqa: F401  isort: skip  (first: sets safe test settings before core loads)

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from core import devmode
from core.debounce import Debouncer
from core.errors import UserError

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class DevModeTest(unittest.TestCase):
    def setUp(self):
        devmode.disable()
        self.addCleanup(devmode.disable)

    def test_off_gives_the_normal_values(self):
        self.assertFalse(devmode.enabled)
        self.assertEqual(devmode.current(), devmode.NORMAL)
        self.assertEqual(devmode.reaction_debounce(), devmode.NORMAL.debounce_s)
        self.assertEqual(devmode.speed(), 1)
        self.assertFalse(devmode.is_verbose())
        self.assertFalse(devmode.quiet_hours_ignored())
        self.assertIsNone(devmode.expires_at)

    def test_on_uses_the_dev_defaults_for_an_hour(self):
        devmode.enable(NOW)
        self.assertEqual(devmode.reaction_debounce(), 2)
        self.assertEqual(devmode.speed(), 1)
        self.assertTrue(devmode.is_verbose())
        self.assertTrue(devmode.quiet_hours_ignored())
        self.assertEqual(devmode.expires_at, NOW + timedelta(hours=1))

    def test_settings_only_count_while_on(self):
        devmode.enable(NOW)
        devmode.set_debounce(0)
        devmode.set_speed(60)
        devmode.set_verbose(False)
        devmode.set_ignore_quiet_hours(False)
        self.assertEqual(devmode.reaction_debounce(), 0)
        self.assertEqual(devmode.speed(), 60)
        self.assertFalse(devmode.is_verbose())
        self.assertFalse(devmode.quiet_hours_ignored())

        devmode.disable()
        self.assertEqual(devmode.current(), devmode.NORMAL)

    def test_cleanup_is_on_by_default_and_only_off_while_dev_mode_says_so(self):
        self.assertTrue(devmode.cleanup_enabled())
        devmode.enable(NOW)
        self.assertTrue(devmode.cleanup_enabled())
        devmode.set_cleanup(False)
        self.assertFalse(devmode.cleanup_enabled())
        devmode.set_cleanup(True)
        self.assertTrue(devmode.cleanup_enabled())
        devmode.set_cleanup(False)
        devmode.disable()
        self.assertTrue(devmode.cleanup_enabled())

    def test_switching_on_again_starts_from_the_defaults(self):
        devmode.enable(NOW)
        devmode.set_speed(60)
        devmode.disable()
        devmode.enable(NOW)
        self.assertEqual(devmode.settings, devmode.DEFAULTS)

    def test_reset_restores_defaults_and_the_hour(self):
        devmode.enable(NOW)
        devmode.set_speed(10)
        devmode.set_expiry(60, NOW)
        devmode.reset(NOW)
        self.assertTrue(devmode.enabled)
        self.assertEqual(devmode.settings, devmode.DEFAULTS)
        self.assertEqual(devmode.expires_at, NOW + timedelta(hours=1))

    def test_expiry_can_be_set_and_extended(self):
        devmode.enable(NOW)
        devmode.set_expiry(600, NOW)
        self.assertEqual(devmode.expires_at, NOW + timedelta(minutes=10))
        devmode.extend(3600)
        self.assertEqual(devmode.expires_at, NOW + timedelta(minutes=70))

    def test_bad_values_are_refused_and_change_nothing(self):
        devmode.enable(NOW)
        for change in (
            lambda: devmode.set_debounce(-1),
            lambda: devmode.set_debounce(devmode.MAX_DEBOUNCE_SECONDS + 1),
            lambda: devmode.set_speed(0),
            lambda: devmode.set_speed(-2),
            lambda: devmode.set_speed(devmode.MAX_SPEED + 1),
        ):
            with self.assertRaises(UserError):
                change()
        self.assertEqual(devmode.settings, devmode.DEFAULTS)

    def test_speed_shortens_the_real_wait_and_back(self):
        self.assertEqual(devmode.real_seconds(1500), 1500)
        devmode.enable(NOW)
        devmode.set_speed(60)
        self.assertEqual(devmode.real_seconds(1500), 25)
        self.assertEqual(devmode.nominal_seconds(25), 1500)


class HandlersForDevRunTest(unittest.TestCase):
    """`dev run <handler>`: what used to be a list of "routines" here is the
    scheduler's own handlers, by name. A routine is now only a schedule with
    several steps."""

    def setUp(self):
        from core import scheduler

        saved = (dict(scheduler._handlers), dict(scheduler._labels))
        self.addCleanup(lambda: (scheduler._handlers.clear(), scheduler._handlers.update(saved[0]), scheduler._labels.clear(), scheduler._labels.update(saved[1])))
        scheduler._handlers.clear()
        scheduler._labels.clear()

        async def handler(job):
            pass

        scheduler.register_handler("core", "nightly_backup", handler, "nightly backup")
        scheduler.register_handler("pills", "checklist", handler, "pills checklist")
        scheduler.register_handler("pills", "remind", handler, "pill reminder")

    def test_a_handler_is_found_by_its_name_its_kind_a_word_of_it_or_its_name_in_words(self):
        from tasks.dev import tools

        self.assertEqual(tools.handler_for("backup"), ("core", "nightly_backup"))
        self.assertEqual(tools.handler_for("core.nightly_backup"), ("core", "nightly_backup"))
        self.assertEqual(tools.handler_for("Checklist"), ("pills", "checklist"))
        self.assertEqual(tools.handler_for("pill-reminder"), ("pills", "remind"))

    def test_one_that_is_unknown_is_refused_with_the_names_there_are(self):
        from tasks.dev import tools

        with self.assertRaisesRegex(UserError, "I don't know a handler called “sweep”. Try: core.nightly_backup, pills.checklist, pills.remind."):
            tools.handler_for("sweep")
        self.assertFalse(hasattr(devmode, "run_routine") or hasattr(devmode, "ROUTINE_NAMES"), "the dev meaning of routine is gone")


class DebouncerDelayTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_fixed_delay_still_works(self):
        self.assertEqual(Debouncer(15, None).delay, 15)

    async def test_a_delay_function_is_asked_each_time(self):
        delays = [0.0]
        batches = []

        async def collect(events):
            batches.append(events)

        debouncer = Debouncer(lambda: delays[0], collect)
        debouncer.trigger("a")
        await asyncio.sleep(0.05)
        self.assertEqual(batches, [["a"]])

        delays[0] = 30
        self.assertEqual(debouncer.delay, 30)
        debouncer.trigger("b")
        await asyncio.sleep(0.05)
        self.assertEqual(batches, [["a"]], "still waiting out the longer delay")
        debouncer.cancel()


if __name__ == "__main__":
    unittest.main()
