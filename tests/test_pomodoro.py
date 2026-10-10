import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.durations import DurationError
from tasks.timers.pomodoro import (
    DEFAULT_LABEL,
    FOCUS,
    LONG_BREAK,
    SHORT_BREAK,
    Plan,
    counts_as_focus,
    next_phase,
    parse_session,
    phase_length,
    remaining_seconds,
    resumed_end,
    summarise_focus,
    week_start,
)

UTC = timezone.utc
NZ = ZoneInfo("Pacific/Auckland")


def walk(plan: Plan, steps: int) -> list[tuple[str, int]]:
    """The first `steps` phases of a session, as (phase, round)."""
    phase, round_number = FOCUS, 1
    seen = [(phase, round_number)]
    for _ in range(steps - 1):
        phase, round_number = next_phase(plan, phase, round_number)
        seen.append((phase, round_number))
    return seen


class PhaseOrderTest(unittest.TestCase):
    def test_default_plan(self):
        plan = Plan()
        self.assertEqual((plan.focus_s, plan.short_s, plan.long_s, plan.rounds), (1500, 300, 900, 4))
        self.assertEqual(phase_length(plan, FOCUS), 1500)
        self.assertEqual(phase_length(plan, SHORT_BREAK), 300)
        self.assertEqual(phase_length(plan, LONG_BREAK), 900)

    def test_four_rounds_then_a_long_break(self):
        self.assertEqual(
            walk(Plan(), 8),
            [(FOCUS, 1), (SHORT_BREAK, 1), (FOCUS, 2), (SHORT_BREAK, 2),
             (FOCUS, 3), (SHORT_BREAK, 3), (FOCUS, 4), (LONG_BREAK, 4)],
        )

    def test_after_the_long_break_a_new_set_starts_at_round_one(self):
        phases = walk(Plan(), 17)
        self.assertEqual(phases[8], (FOCUS, 1))
        self.assertEqual(phases[15], (LONG_BREAK, 4))
        self.assertEqual(phases[16], (FOCUS, 1))
        self.assertEqual([p for p, _ in phases].count(LONG_BREAK), 2)
        self.assertEqual([p for p, _ in phases].count(FOCUS), 9)

    def test_a_different_number_of_rounds(self):
        phases = walk(Plan(rounds=2), 5)
        self.assertEqual(phases, [(FOCUS, 1), (SHORT_BREAK, 1), (FOCUS, 2), (LONG_BREAK, 2), (FOCUS, 1)])

    def test_skipping_follows_the_same_order(self):
        # Skipping a phase just moves on: the order never depends on how a phase ended
        self.assertEqual(next_phase(Plan(), FOCUS, 2), (SHORT_BREAK, 2))
        self.assertEqual(next_phase(Plan(), SHORT_BREAK, 2), (FOCUS, 3))
        self.assertEqual(next_phase(Plan(), FOCUS, 4), (LONG_BREAK, 4))
        self.assertEqual(next_phase(Plan(), LONG_BREAK, 4), (FOCUS, 1))

    def test_only_a_completed_focus_phase_is_logged(self):
        self.assertTrue(counts_as_focus(FOCUS, completed=True))
        self.assertFalse(counts_as_focus(FOCUS, completed=False), "a skipped focus doesn't count")
        self.assertFalse(counts_as_focus(SHORT_BREAK, completed=True))
        self.assertFalse(counts_as_focus(LONG_BREAK, completed=True))


class ParseSessionTest(unittest.TestCase):
    def parse(self, text):
        return parse_session(text.split())

    def test_plain(self):
        self.assertEqual(self.parse(""), (Plan(), DEFAULT_LABEL, None))

    def test_custom_lengths(self):
        self.assertEqual(self.parse("50/10"), (Plan(3000, 600, 900), DEFAULT_LABEL, None))
        self.assertEqual(self.parse("50/10/30"), (Plan(3000, 600, 1800), DEFAULT_LABEL, None))
        self.assertEqual(self.parse("45m/15m"), (Plan(2700, 900, 900), DEFAULT_LABEL, None))
        self.assertEqual(self.parse("30s/10s/20s")[0], Plan(30, 10, 20), "seconds, for quick testing")
        self.assertEqual(self.parse("1h/15")[0], Plan(3600, 900, 900))

    def test_label(self):
        self.assertEqual(self.parse("deep work"), (Plan(), "deep work", None))
        self.assertEqual(self.parse("50/10 Thesis chapter 2"), (Plan(3000, 600, 900), "Thesis chapter 2", None))

    def test_auto_and_manual(self):
        self.assertEqual(self.parse("auto"), (Plan(), DEFAULT_LABEL, True))
        self.assertEqual(self.parse("manual writing"), (Plan(), "writing", False))
        self.assertEqual(self.parse("50/10 AUTO emails"), (Plan(3000, 600, 900), "emails", True))
        # Only the first one is the switch; after that it is part of the label
        self.assertEqual(self.parse("auto manual")[1:], ("manual", True))

    def test_a_slash_later_on_is_part_of_the_label(self):
        self.assertEqual(self.parse("read/write practice"), (Plan(), "read/write practice", None))
        self.assertEqual(self.parse("notes w/e"), (Plan(), "notes w/e", None))
        self.assertEqual(self.parse("a/b testing"), (Plan(), "a/b testing", None))
        # Once the lengths are set, a second slash word is label
        self.assertEqual(self.parse("50/10 24/7 support"), (Plan(3000, 600, 900), "24/7 support", None))

    def test_bad_lengths(self):
        for text in ("50/", "50/x", "50/10/30/5", "0/5", "50/1s", "5/"):
            with self.assertRaises(DurationError, msg=text):
                self.parse(text)


class PauseMathsTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
        self.ends = self.start + timedelta(minutes=25)

    def test_remaining(self):
        self.assertEqual(remaining_seconds(self.ends, self.start), 1500)
        self.assertEqual(remaining_seconds(self.ends, self.start + timedelta(minutes=10)), 900)
        self.assertEqual(remaining_seconds(self.ends, self.ends + timedelta(minutes=3)), 0, "never negative")

    def test_pause_then_resume_keeps_the_time_left(self):
        paused_at = self.start + timedelta(minutes=10)
        left = remaining_seconds(self.ends, paused_at)
        resumed_at = paused_at + timedelta(hours=2)  # a long lunch
        new_end = resumed_end(resumed_at, left)
        self.assertEqual(new_end, resumed_at + timedelta(minutes=15))
        self.assertEqual(remaining_seconds(new_end, resumed_at), left)

    def test_several_pauses_add_up(self):
        now, ends = self.start, self.ends
        worked = timedelta()
        for work, rest in ((5, 30), (7, 1), (3, 600)):
            now += timedelta(minutes=work)
            worked += timedelta(minutes=work)
            left = remaining_seconds(ends, now)
            now += timedelta(minutes=rest)
            ends = resumed_end(now, left)
        self.assertEqual(remaining_seconds(ends, now), (timedelta(minutes=25) - worked).total_seconds())

    def test_extending_a_paused_clock(self):
        left = remaining_seconds(self.ends, self.start + timedelta(minutes=20)) + 600  # "+10m" while paused
        self.assertEqual(left, 900)

    def test_times_in_different_zones_compare_correctly(self):
        ends_nz = self.ends.astimezone(NZ)
        self.assertEqual(remaining_seconds(ends_nz, self.start), 1500)


class StatsTest(unittest.TestCase):
    def test_week_starts_on_monday(self):
        self.assertEqual(week_start(date(2026, 10, 7)), date(2026, 10, 5))  # a Wednesday
        self.assertEqual(week_start(date(2026, 10, 5)), date(2026, 10, 5))
        self.assertEqual(week_start(date(2026, 10, 11)), date(2026, 10, 5))  # Sunday

    def test_today_and_this_week(self):
        def at(day, hour, minute=0):
            return datetime(2026, 10, day, hour, minute, tzinfo=NZ).astimezone(UTC)

        log = [
            (at(7, 9), "Thesis", 1500),
            (at(7, 10), "Thesis", 1500),
            (at(7, 14), "Email", 3000),
            (at(6, 16), "Thesis", 1500),   # yesterday
            (at(5, 0, 5), "Email", 600),   # just after midnight on Monday: this week
            (at(4, 23, 55), "Email", 900),  # Sunday night: last week
        ]
        today, week = summarise_focus(log, date(2026, 10, 7), NZ)
        self.assertEqual((today.sessions, today.seconds), (3, 6000))
        self.assertEqual(today.by_label, (("Email", 3000), ("Thesis", 3000)))
        self.assertEqual((week.sessions, week.seconds), (5, 8100))
        self.assertEqual(week.by_label, (("Thesis", 4500), ("Email", 3600)))

    def test_days_are_nz_days_not_utc_days(self):
        # 8am on the 7th in Auckland is still the 6th in UTC
        early = datetime(2026, 10, 7, 8, 0, tzinfo=NZ).astimezone(UTC)
        self.assertEqual(early.date(), date(2026, 10, 6))
        today, _ = summarise_focus([(early, "Reading", 1500)], date(2026, 10, 7), NZ)
        self.assertEqual(today.sessions, 1)

    def test_nothing_logged(self):
        today, week = summarise_focus([], date(2026, 10, 7), NZ)
        self.assertEqual((today.sessions, today.seconds, today.by_label), (0, 0, ()))
        self.assertEqual(week.sessions, 0)


if __name__ == "__main__":
    unittest.main()


class AlreadyGoingTest(unittest.TestCase):
    def test_in_its_own_channel_the_card_is_shown_again(self):
        from tasks.timers.pomodoro import RESHOW, where_to_show

        self.assertEqual(where_to_show(100, 100), RESHOW)

    def test_from_another_channel_it_is_pointed_to(self):
        from tasks.timers.pomodoro import POINT, where_to_show

        self.assertEqual(where_to_show(100, 300), POINT)
