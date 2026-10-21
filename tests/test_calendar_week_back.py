"""The calendar's copy reaches back to Monday (22 Oct, BACKLOG Soon): the pinned week view's earlier days this week
show their events, faint as designed. Before, it kept yesterday on, so Monday seen on a Thursday was empty. A Monday
still keeps Sunday, for an event that runs past midnight. Made-up events."""
import asyncio
from datetime import date, time, timedelta

import pytest

from core import clock, config
from core import day as days
from tasks.calendar import plain, rules, store

MONDAY = date(2026, 10, 19)


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize("today, first", [
    (MONDAY + timedelta(days=3), MONDAY),  # a Thursday: back to Monday
    (MONDAY, MONDAY - timedelta(days=1)),  # a Monday: yesterday, Sunday, for an event past midnight
    (MONDAY + timedelta(days=6), MONDAY),  # a Sunday: the whole week back to Monday
])
def test_the_copy_starts_at_this_week_s_monday_or_yesterday_if_that_is_earlier(today, first):
    assert rules.first_kept(today) == first


def _feed(tmp_path, *happenings):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//assistant-bot//week back//EN"]
    for number, (on, hour) in enumerate(happenings):
        stamp = f"{on:%Y%m%d}"
        lines += ["BEGIN:VEVENT", f"UID:week-{number}@example.test", f"SUMMARY:Test event {number}", f"DTSTART;TZID=Pacific/Auckland:{stamp}T{hour:02d}0000",
                  f"DTEND;TZID=Pacific/Auckland:{stamp}T{hour + 1:02d}0000", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    feed = tmp_path / "week.ics"
    feed.write_text("".join(line + chr(13) + chr(10) for line in lines), encoding="utf-8")
    return feed


@pytest.mark.parametrize("ahead", [3, 0, 6], ids=["thursday", "monday", "sunday"])
def test_a_read_keeps_this_week_s_earlier_days_and_nothing_before(make_db, dev_clock, monkeypatch, owner, tmp_path, ahead):
    from core import actions
    from tasks import calendar

    # A Monday to come (the clock only moves forward), and a day of its week
    monday = days.today() + timedelta(days=14 - days.today().weekday())
    today = monday + timedelta(days=ahead)
    make_db({"calendar": store.MIGRATIONS})
    actions.set_catalogue([*calendar.task.entries()])
    feed = _feed(tmp_path, (monday - timedelta(days=2), 10), (monday, 10), (monday + timedelta(days=2), 9), (today, 18))
    monkeypatch.setattr(config, "CALENDAR_ENABLED", True)
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(feed))
    clock.advance_to(days.at(today, time(8, 50)))
    assert run(calendar.update(owner.id)) == ""
    kept = {days.day_of(each.start) for each in run(store.events(owner.id))}
    assert monday - timedelta(days=2) not in kept, "the Saturday before is not this week"
    assert monday in kept and today in kept
    assert monday + timedelta(days=2) in kept, "Wednesday is this week, past or to come"
    # The week view reads the copy: Monday's event is in its Monday, whatever day of the week it is
    from core import weekview

    (shown,) = run(weekview.gather(owner.id, [monday], only=rules.TASK))
    assert "Test event 1" in str(shown), shown


def test_a_span_from_this_week_s_monday_is_answered_from_the_copy():
    thursday = MONDAY + timedelta(days=3)
    assert plain._in_copy(rules.Span(MONDAY, MONDAY, "Monday", "on Monday"), thursday)
    assert not plain._in_copy(rules.Span(MONDAY - timedelta(days=1), MONDAY - timedelta(days=1), "Sunday", "on Sunday"), thursday)
