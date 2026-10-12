"""Streaks from the occurrence log (core/streaks.py): only a missed one breaks it."""
from datetime import date, timedelta

import pytest

from core import streaks
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from core.streaks import Streak

TODAY = date(2026, 10, 12)


def on(days_ago: int, state: str, item: int = 1, seq: int = 1, automatic: bool = False, cause: str | None = None) -> Occurrence:
    day = TODAY - timedelta(days=days_ago)
    return Occurrence(seq + 10 * days_ago + 1000 * item, 1, "pills", item, day, seq, None, None, state, None, automatic, None, cause)


def test_nothing_logged_is_no_streak():
    assert streaks.streak([], TODAY) == Streak()


def test_days_in_a_row_with_something_done_and_nothing_missed_count():
    found = [on(3, DONE), on(2, DONE), on(1, DONE), on(0, DONE)]
    assert streaks.streak(found, TODAY) == Streak(4, 4, TODAY - timedelta(days=3), 4, None)


def test_only_a_missed_dose_breaks_it_and_the_day_it_was_missed_does_not_count():
    found = [on(4, DONE), on(3, DONE), on(2, MISSED), on(1, DONE), on(0, DONE)]
    got = streaks.streak(found, TODAY)
    assert (got.days, got.since, got.broken_on, got.longest) == (2, TODAY - timedelta(days=1), TODAY - timedelta(days=2), 2)
    # A dose taken on the day another was missed doesn't save that day
    mixed = [on(1, DONE), on(0, DONE, seq=1), on(0, MISSED, seq=2)]
    assert streaks.streak(mixed, TODAY).days == 0 and streaks.streak(mixed, TODAY).broken_on == TODAY


@pytest.mark.parametrize("cause", [None, "no_room", "not_in_plan", "ignored"])
def test_a_skip_never_breaks_it_by_hand_or_by_the_bot_whatever_its_cause(cause):
    found = [on(2, DONE), on(1, SKIPPED, automatic=cause is not None, cause=cause), on(0, DONE)]
    got = streaks.streak(found, TODAY)
    assert got.days == 2 and got.since == TODAY - timedelta(days=2) and got.broken_on is None
    assert not streaks.breaks(found[1])


def test_a_skipped_day_and_a_day_with_nothing_expected_neither_break_nor_add():
    # Day 3 done, day 2 skipped, day 1 paused (nothing expected), today done
    found = [on(3, DONE), on(2, SKIPPED), on(0, DONE)]
    assert streaks.streak(found, TODAY).days == 2
    # A day with one skipped and one done still counts once, for what was done
    found = [on(1, DONE), on(1, SKIPPED, seq=2), on(0, DONE)]
    assert (streaks.streak(found, TODAY).days, streaks.streak(found, TODAY).done) == (2, 2)


def test_what_is_still_waiting_today_changes_nothing():
    found = [on(2, DONE), on(1, DONE), on(0, PENDING)]
    assert streaks.streak(found, TODAY).days == 2, "today is not over: it has neither added nor broken"
    found.append(on(0, DONE, seq=2))
    assert streaks.streak(found, TODAY).days == 3


def test_done_counts_every_dose_of_the_streak_and_longest_remembers_an_earlier_run():
    found = [on(9, DONE), on(8, DONE), on(7, DONE), on(6, MISSED), on(1, DONE), on(1, DONE, seq=2), on(0, DONE)]
    got = streaks.streak(found, TODAY)
    assert (got.days, got.done, got.longest, got.broken_on) == (2, 3, 3, TODAY - timedelta(days=6))


def test_a_day_after_today_is_not_looked_at():
    found = [on(0, DONE), on(-1, MISSED), on(-2, DONE)]
    assert streaks.streak(found, TODAY) == Streak(1, 1, TODAY, 1, None)


def test_each_pill_has_its_own_streak_and_one_missing_does_not_break_the_other_s():
    found = [on(2, DONE, item=1), on(1, DONE, item=1), on(0, DONE, item=1), on(2, DONE, item=2), on(1, MISSED, item=2), on(0, DONE, item=2)]
    each = streaks.by_item(found, TODAY)
    assert (each[1].days, each[2].days) == (3, 1) and each[2].broken_on == TODAY - timedelta(days=1)
    assert streaks.streak(found, TODAY).days == 1, "taken together, the day one was missed breaks the streak of the whole task"


def test_the_order_the_rows_come_in_does_not_matter():
    found = [on(0, DONE), on(2, MISSED), on(1, DONE), on(3, DONE)]
    assert streaks.streak(found, TODAY) == streaks.streak(list(reversed(found)), TODAY)


def test_only_missed_breaks():
    assert streaks.breaks(on(0, MISSED)) and not any(streaks.breaks(on(0, state)) for state in (DONE, SKIPPED, PENDING))
