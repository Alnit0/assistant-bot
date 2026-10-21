"""What's on over any span (Alex, 21 Oct): a day, a week ("the week of 28 November"), a month ("in November",
"next month"), a year ("in 2027", "next year") or a range ("from Monday to Friday", "21 to 25 November"). Claude
hands over the span and the words as said (evals/fixtures/calendar.json, s1, as the real API answered); Python
works out the days, reads the copy when it covers them and every calendar when it does not, and lists the
events in date order: by day up to a week, by week up to two months, one list for longer. Made-up events."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import config, timeinput
from core.errors import UserError
from tasks import calendar
from tasks.calendar import plain, rules
from tasks.calendar.rules import Event
from tests.test_calendar_google import BOT_ID, made_up_key, run, world  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "calendar.json").read_text(encoding="utf-8"))
SAID = {each["message"]: each["recorded"][1] for each in FIXTURES["extraction"] if each["action"] == "calendar_show"}
WEDNESDAY = date(2026, 10, 21)
UTC = timezone.utc


def asked(message, today=WEDNESDAY):
    data = SAID[message]
    span = data.get("span") if data.get("span") in rules.SPANS else rules.DAY_SPAN
    return rules.span_of(span, today, plain.read_day, data.get("day"), data.get("until"), data.get("month"), data.get("year"))


# --- the days each one covers, from what the real API handed over ----------------------------------------------------
@pytest.mark.parametrize("message, first, last, heading", [
    ("what's on Friday?", date(2026, 10, 23), date(2026, 10, 23), "Fri 23 Oct"),
    ("what's on 21 November?", date(2026, 11, 21), date(2026, 11, 21), "Sat 21 Nov"),
    ("what's on this week?", date(2026, 10, 21), date(2026, 10, 25), "This week"),
    ("what's on next week?", date(2026, 10, 26), date(2026, 11, 1), "Next week"),
    ("what's on the week of 28 November?", date(2026, 11, 23), date(2026, 11, 29), "The week of Mon 23 Nov"),
    ("what's on in November?", date(2026, 11, 1), date(2026, 11, 30), "November"),
    ("what's on next month?", date(2026, 11, 1), date(2026, 11, 30), "November"),
    ("what's on in December?", date(2026, 12, 1), date(2026, 12, 31), "December"),
    ("what's on in 2027?", date(2027, 1, 1), date(2027, 12, 31), "2027"),
    ("what's on next year?", date(2027, 1, 1), date(2027, 12, 31), "2027"),
    ("what's on from Monday to Friday?", date(2026, 10, 26), date(2026, 10, 30), "Mon 26 Oct to Fri 30 Oct"),
    ("what's on 21 to 25 November?", date(2026, 11, 21), date(2026, 11, 25), "Sat 21 Nov to Wed 25 Nov"),
])
def test_each_span_covers_its_full_days(message, first, last, heading):
    found = asked(message)
    assert (found.first, found.last, found.heading) == (first, last, heading)


def test_a_month_with_no_year_is_this_one_or_the_next_to_come():
    assert timeinput.parse_month("October", WEDNESDAY) == date(2026, 10, 1), "this month counts, all of it"
    assert timeinput.parse_month("january", WEDNESDAY) == date(2027, 1, 1)
    assert timeinput.parse_month("Nov 2028", WEDNESDAY) == date(2028, 11, 1)
    assert timeinput.parse_month("", WEDNESDAY) == date(2026, 10, 1)
    assert rules.span_of(rules.MONTH, WEDNESDAY, plain.read_day, month="January").heading == "January 2027"
    with pytest.raises(UserError):
        timeinput.parse_month("Smarch", WEDNESDAY)
    assert timeinput.parse_year("", WEDNESDAY) == 2026 and timeinput.parse_year("2030", WEDNESDAY) == 2030


def test_a_range_ends_on_or_after_its_first_day():
    found = rules.span_of(rules.DAY_SPAN, WEDNESDAY, plain.read_day, "Friday", "Monday")
    assert (found.first, found.last) == (date(2026, 10, 23), date(2026, 10, 26)), "Monday after Friday"
    with pytest.raises(UserError, match="two years"):
        rules.span_of(rules.DAY_SPAN, WEDNESDAY, plain.read_day, "1 November", "1 November 2029")


# --- the answer: date order, grouped by the span's length -----------------------------------------------------------------
def at(day, hour, minutes=60):
    from core import day as days
    from datetime import time

    start = days.at(day, time(hour, 0))
    return start, start + timedelta(minutes=minutes)


def timed(title, day, hour):
    start, end = at(day, hour)
    return Event(f"{title}@{day}", title, start, end)


def all_day(title, first, last=None):
    return Event(f"{title}@{first}", title, first_day=first, last_day=last or first)


EVENTS = [
    timed("Dentist", date(2026, 11, 6), 15),
    all_day("Hen do", date(2026, 11, 21), date(2026, 11, 22)),
    timed("Lunch with Sam", date(2026, 11, 3), 12),
    all_day("Conference", date(2026, 11, 3)),
    timed("Book club", date(2026, 12, 2), 19),
]


def test_a_range_of_a_week_or_less_is_grouped_by_day_all_day_first():
    said = rules.span_answer(EVENTS, rules.span_of(rules.DAY_SPAN, WEDNESDAY, plain.read_day, "2 November", "6 November"), WEDNESDAY)
    assert said.splitlines() == [
        "🗓️ **Mon 2 Nov to Fri 6 Nov** · 3 events",
        "**Tue 3 Nov**", "all day · **Conference**", "**12:00 pm to 1:00 pm** · **Lunch with Sam**",
        "**Fri 6 Nov**", "**3:00 pm to 4:00 pm** · **Dentist**",
    ]


def test_a_month_is_grouped_by_week_each_event_once_with_its_day():
    said = rules.span_answer(EVENTS, asked("what's on in November?"), WEDNESDAY)
    assert said.splitlines() == [
        "🗓️ **November** · 4 events",
        "**Week of Mon 2 Nov**",
        "Tue 3 Nov · all day · **Conference**",
        "Tue 3 Nov · **12:00 pm to 1:00 pm** · **Lunch with Sam**",
        "Fri 6 Nov · **3:00 pm to 4:00 pm** · **Dentist**",
        "**Week of Mon 16 Nov**",
        "Sat 21 Nov to Sun 22 Nov · all day · **Hen do**",
    ], "the two-day one once, the first line naming no event"


def test_a_year_is_one_list_in_date_order_and_a_long_one_says_how_many_more():
    said = rules.span_answer(EVENTS, rules.span_of(rules.YEAR, WEDNESDAY, plain.read_day), WEDNESDAY).splitlines()
    assert said[0] == "🗓️ **2026** · 5 events" and not any(line.startswith("**Week of") for line in said)
    assert [line.rsplit("**", 2)[-2] for line in said[1:]] == ["Conference", "Lunch with Sam", "Dentist", "Hen do", "Book club"]
    many = [timed(f"Made-up {number}", date(2027, 1, 1) + timedelta(days=number), 9) for number in range(30)]
    long = rules.span_answer(many, asked("what's on in 2027?"), WEDNESDAY).splitlines()
    assert len(long) == 1 + rules.SPAN_SHOWN + 1 and long[-1] == "-# +5 more: ask about a shorter span to see them all"


def test_nothing_on_is_said_for_each_kind_of_span():
    assert rules.span_answer([], asked("what's on in December?"), WEDNESDAY) == "🗓️ Nothing on in December."
    assert rules.span_answer([], asked("what's on in 2027?"), WEDNESDAY) == "🗓️ Nothing on in 2027."
    assert rules.span_answer([], asked("what's on from Monday to Friday?"), WEDNESDAY) == "🗓️ Nothing on from Mon 26 Oct to Fri 30 Oct."
    assert rules.span_answer([], asked("what's on the week of 28 November?"), WEDNESDAY) == "🗓️ Nothing on in the week of Mon 23 Nov."
    assert rules.span_answer([], asked("what's on Friday?"), WEDNESDAY) == "🗓️ Nothing on Fri 23 Oct."


# --- the copy, or every calendar read for the span ----------------------------------------------------------------------
def shown(world, data):
    return run(plain.show(world.request("what's on?"), data, frozenset()))


def test_a_span_the_copy_covers_is_answered_from_it(world):
    run(calendar.update(world.owner.id))
    calls = len(world.fake.calls)
    said = shown(world, {"span": "month", "month": "November"})
    assert said.splitlines()[:2] == ["🗓️ **November** · 3 events", "**Week of Mon 2 Nov**"]
    assert len(world.fake.calls) == calls, "no read: the copy covers November"


def test_a_year_ahead_reads_every_calendar_for_it(world):
    world.fake.calendars[BOT_ID]["w1"] = {"id": "w1", "status": "confirmed", "summary": "Made-up wedding", "start": {"date": "2027-03-13"}, "end": {"date": "2027-03-14"}}
    world.fake.calendars[BOT_ID]["w2"] = {"id": "w2", "status": "confirmed", "summary": "Made-up flight",
                                         "start": {"dateTime": "2027-02-01T08:00:00+13:00"}, "end": {"dateTime": "2027-02-01T11:00:00+13:00"}}
    said = shown(world, {"span": "year", "year": "2027"})
    assert said.splitlines() == ["🗓️ **2027** · 2 events", "Mon 1 Feb · **8:00 am to 11:00 am** · **Made-up flight**", "Sat 13 Mar · all day · **Made-up wedding**"]
    assert ("GET", BOT_ID) in world.fake.calls


def test_a_calendar_that_cannot_be_read_is_said_and_none_read_is_said_instead(world, monkeypatch):
    world.fake.down.add(BOT_ID)
    said = shown(world, {"span": "year", "year": "2027"})
    assert said.endswith("-# ⚠️ One of your calendars couldn't be read just now: this is the rest.")
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(Path(config.CALENDAR_ICS_URL).with_name("gone.ics")))
    with pytest.raises(UserError, match="couldn't read your calendar"):
        shown(world, {"span": "year", "year": "2027"})


def test_a_day_this_week_and_next_week_keep_the_week_view_where_it_is_on(world, monkeypatch):
    run(calendar.update(world.owner.id))
    seen = []

    async def week_view(request, span, data, today):
        seen.append(span)
        return "the week view"

    monkeypatch.setattr(config, "WEEK_VIEW", True)
    monkeypatch.setattr(plain, "_week_view", week_view)
    for data in ({"day": "tomorrow"}, {"span": "week"}, {"span": "next_week"}):
        assert shown(world, data) == "the week view"
    assert shown(world, {"span": "week", "day": "28 November"}).startswith("🗓️ ")
    assert shown(world, {"span": "month", "month": "November"}).startswith("🗓️ **November**")
    assert seen == ["day", "week", "next_week"]


def test_the_hub_s_day_is_today_s_events_and_one_offs_coming_up_in_the_next_week(world):
    """Round 7 (`day_items`): today's events, then one-off events in the next 7 days as coming up."""
    from core import actions

    run(calendar.update(world.owner.id))
    found = run(calendar.day_items(world.owner.id, date(2026, 11, 2)))
    assert [(each.kind, each.text, each.repeats) for each in found] == [
        (actions.EVENT, "Made-up standup", False), (actions.EVENT, "Made-up lunch", False), (actions.EVENT, "Made-up review", False),
    ]
    assert found[0].at is not None and found[0].until > found[0].at
