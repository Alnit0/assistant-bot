"""The calendar (tasks/calendar), behind CALENDAR_ENABLED: reading a made-up feed (recurring events, an exception, a cancellation, all-day, multi-day, a daylight saving change), the answers in words, the copy kept through a failed read, attention, the Today card and the briefing. No real event is in this file or its fixture."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import attention, clock, config, design
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.calendar import plain, rules, source, store
from tasks.calendar import task as calendar_task

FEED = Path(__file__).parent / "fixtures" / "calendar.ics"
INBOX = 100


def run(coroutine):
    return asyncio.run(coroutine)


def feed(first=date(2026, 9, 15), last=date(2026, 11, 10)):
    return rules.parse(FEED.read_text(encoding="utf-8"), first, last)


def local(event):
    return days.day_of(event.start), days.local_time(event.start)


def at(day, hour, minute=0):
    return days.at(day, time(hour, minute))


# --- reading the feed -------------------------------------------------------------------------------------------
def test_a_weekly_event_keeps_its_local_time_across_the_daylight_saving_change():
    syncs = [local(each) for each in feed() if each.title == "Team sync"]
    assert (date(2026, 9, 24), time(9, 0)) in syncs and (date(2026, 10, 1), time(9, 0)) in syncs, "either side of 27 Sep"


def test_an_exception_is_left_out_and_a_moved_happening_is_at_its_new_time():
    syncs = dict(local(each) for each in feed() if each.title == "Team sync")
    assert date(2026, 10, 8) not in syncs, "the week taken out (EXDATE)"
    assert syncs[date(2026, 10, 15)] == time(11, 0), "the week moved (RECURRENCE-ID)"


def test_a_cancelled_event_is_not_there_and_a_utc_one_is_in_auckland_time():
    titles = [each.title for each in feed()]
    assert "Old plan" not in titles
    (far,) = [each for each in feed() if each.title == "Call with the far office"]
    assert local(far) == (date(2026, 10, 23), time(9, 0))


def test_all_day_and_multi_day_events():
    (holiday,) = [each for each in feed() if each.title == "Public holiday"]
    (camping,) = [each for each in feed() if each.title == "Camping trip"]
    assert holiday.all_day and (holiday.first_day, holiday.last_day) == (date(2026, 10, 26), date(2026, 10, 26))
    assert (camping.first_day, camping.last_day) == (date(2026, 10, 30), date(2026, 11, 1)), "the end date is the day after"
    assert [each.title for each in rules.on_day(feed(), date(2026, 11, 1))] == ["Camping trip"]


def test_an_overnight_event_is_on_both_days_and_says_so():
    events = feed()
    (night,) = [each for each in events if each.title == "Night shift"]
    assert night in rules.on_day(events, date(2026, 10, 21)) and night in rules.on_day(events, date(2026, 10, 22))
    assert rules.when_text(night, date(2026, 10, 21)) == "from 10:00 pm" and rules.when_text(night, date(2026, 10, 22)) == "until 6:00 am"


def test_a_feed_that_is_not_a_calendar_is_refused():
    with pytest.raises(ValueError):
        rules.parse("not a calendar at all", date(2026, 10, 1), date(2026, 10, 2))


# --- answers in words: the first line names no event ---------------------------------------------------------------
TODAY = date(2026, 10, 22)  # a Thursday


def test_a_day_with_events_and_one_with_none():
    said = rules.day_answer(feed(), date(2026, 10, 23), TODAY).splitlines()
    assert said[0] == "🗓️ **Tomorrow** · 2 events", "no event named on the first line"
    assert said[1:] == ["**9:00 am to 9:30 am** · **Call with the far office**", "**3:00 pm to 4:00 pm** · **Dentist check-up**"]
    assert rules.day_answer(feed(), date(2026, 10, 27), TODAY) == "🗓️ Nothing on Tue 27 Oct."
    assert rules.day_answer(feed(), date(2026, 10, 26), TODAY).splitlines()[1] == "all day · **Public holiday**"


def test_a_week_is_a_day_a_heading_each_by_the_list_rule():
    busy = [rules.Event(f"e{n}", f"Thing {n}", at(TODAY, 9 + n), at(TODAY, 9 + n) + timedelta(minutes=30)) for n in range(5)]
    said = rules.week_answer(busy + feed(), rules.span_days(rules.WEEK, TODAY), TODAY, "this week").splitlines()
    assert said[0].startswith("🗓️ **This week** · ")
    assert said[1] == "**Today**" and "-# +4 more" in said, "five today, the Team sync and the end of last night's shift: three in full"
    assert rules.span_days(rules.NEXT_WEEK, TODAY)[0] == date(2026, 10, 26) and len(rules.span_days(rules.NEXT_WEEK, TODAY)) == 7


def test_when_is_finds_the_next_by_its_name_and_never_guesses():
    now = at(TODAY, 12)
    assert rules.when_answer(rules.next_matching(feed(), "dentist", now), TODAY).splitlines() == ["🗓️ Next one · Tomorrow, **3:00 pm**", "**Dentist check-up** · 3:00 pm to 4:00 pm"]
    assert local(rules.next_matching(feed(), "team sync", now)) == (date(2026, 10, 29), time(9, 0)), "today's has been: the next one"
    with pytest.raises(UserError, match="Nothing like"):
        rules.next_matching(feed(), "piano", now)
    two = [rules.Event("a", "Lunch with a friend", at(TODAY, 13), at(TODAY, 14)), rules.Event("b", "Lunch meeting", at(TODAY, 15), at(TODAY, 16))]
    with pytest.raises(UserError, match="could be"):
        rules.next_matching(two, "lunch", now)


def test_am_i_free():
    assert rules.free_answer(feed(), at(date(2026, 10, 23), 15, 30), TODAY).splitlines()[0] == "🗓️ Not free at **3:30 pm** tomorrow"
    assert rules.free_answer(feed(), at(date(2026, 10, 23), 12), TODAY) == "🗓️ You're free at **12:00 pm** tomorrow."
    assert rules.free_answer(feed(), at(date(2026, 10, 26), 12), TODAY).startswith("🗓️ You're free"), "an all-day event is not busy"
    assert rules.read_time("3") == time(15, 0) and rules.read_time("10:30") == time(10, 30)


# --- the task: a made-up feed, the copy, attention, the hub ---------------------------------------------------------
@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner):
    make_db({"calendar": store.MIGRATIONS})
    monkeypatch.setattr(config, "CALENDAR_ENABLED", True)
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(FEED))
    # The real time held before the made-up morning, so the clock can still move forward to it once that day has
    # passed (22 Oct: from 8:50 am that day every test here stopped, the clock refusing to go back)
    monkeypatch.setattr(clock, "real_now", lambda: at(TODAY, 0, 0))
    clock.advance_to(at(TODAY, 8, 50))
    return SimpleNamespace(owner=owner, request=lambda text="said": Request(owner, INBOX, text))


def kept(world):
    return run(store.events(world.owner.id))


def test_off_unless_set_and_not_loaded():
    assert config.CALENDAR_ENABLED is False and config.CALENDAR_ICS_URL == "" and not calendar_task.switched_on()
    registry.load()
    assert "calendar" not in [task.name for task in registry.loaded_tasks()]


def test_switched_on_it_loads_with_no_problem_and_offers_its_three_questions(monkeypatch):
    monkeypatch.setattr(config, "CALENDAR_ENABLED", True)
    registry.load()
    try:
        assert "calendar" in [task.name for task in registry.loaded_tasks()]
        assert not [problem for problem in registry.problems() if "calendar" in problem]
        entry = next(each for each in __import__("core.actions", fromlist=["catalogue"]).catalogue() if each.name == "calendar")
        assert sorted(action.name for action in entry.actions) == ["calendar_free", "calendar_show", "calendar_when"]
    finally:
        monkeypatch.undo()
        registry.load()


def test_a_read_keeps_two_months_and_a_failed_one_keeps_the_last_good_copy(world, monkeypatch):
    from tasks import calendar

    assert run(calendar.update(world.owner.id)) == ""
    count = len(kept(world))
    assert count > 0 and all(each.start is None or each.start >= days.start_of(TODAY - timedelta(days=1)) for each in kept(world))
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(FEED.with_name("no-such-feed.ics")))
    assert "could not be read" in run(calendar.update(world.owner.id))
    assert len(kept(world)) == count, "the last good copy stays"
    _, failing, why, _ = run(store.events.__globals__["database"].run(store.db_read, world.owner.id))
    assert failing is not None and "no-such-feed" not in why


def test_a_failed_read_needs_a_look_only_after_six_hours(world, monkeypatch):
    from tasks import calendar

    run(calendar.update(world.owner.id))
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(FEED.with_name("no-such-feed.ics")))
    run(calendar.update(world.owner.id))
    assert not [each for each in run(calendar.items(world.owner.id, clock.now() + timedelta(hours=5))) if each.urgency == attention.PROBLEM]
    (problem,) = [each for each in run(calendar.items(world.owner.id, clock.now() + timedelta(hours=6))) if each.urgency == attention.PROBLEM]
    assert attention.level(problem, clock.now() + timedelta(hours=6)) == attention.LEVEL_PROBLEM


def test_a_link_never_shows_in_an_error(monkeypatch):
    import urllib.error
    import urllib.request

    secret = "https://calendar.example.test/private-made-up-secret/basic.ics"

    def refuse(*args, **kwargs):
        raise urllib.error.URLError(f"cannot reach {secret}")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(source.FetchFailed) as raised:
        run(source.IcsSource(secret).events(TODAY, TODAY))
    assert "private" not in str(raised.value) and "example" not in str(raised.value)


def test_an_event_in_the_next_30_minutes_is_level_3_with_only_its_time(world):
    from tasks import calendar

    run(calendar.update(world.owner.id))
    now = at(TODAY, 8, 40)
    (soon,) = [each for each in run(calendar.items(world.owner.id, now)) if each.urgency == attention.TIMED]
    assert attention.level(soon, now) == attention.LEVEL_NEXT and soon.short == ("9am",) and "Team" not in soon.what
    assert [each for each in run(calendar.items(world.owner.id, at(TODAY, 8, 0))) if each.urgency == attention.TIMED] == [], "40 minutes off: nothing yet"


def test_the_today_card_and_the_briefing(world):
    from core import today
    from tasks import calendar

    run(calendar.update(world.owner.id))
    lines = run(calendar.today_lines(world.owner.id, at(TODAY, 8, 50)))
    shown = [line for text in design.texts(today.layout(lines, at(TODAY, 8, 50))) for line in text.splitlines()]
    assert shown[0] == "### 🗓️ Today" and "🗓️ **Team sync**" in shown, "the next event in full"
    assert today.layout(lines, at(TODAY, 10, 0)) == (), "every event over and nothing else on: no card"
    said = run(calendar.summary(world.owner.id, TODAY))
    assert said.glance == "2 events · next 9:00 am", "the end of last night's shift is on today too; the Team sync is the next to start"
    assert run(calendar.summary(world.owner.id, date(2026, 10, 27))) is None


def test_an_all_day_event_is_one_small_line_on_top_of_the_today_card():
    from core import today
    from core.today import Line

    lines = [Line("🗓️", "**Public holiday**", all_day=True), Line("🗓️", "**Swim**", at(TODAY, 7), at(TODAY, 8), event=True), Line("📝", "**Buy stamps**")]
    shown = [line for text in design.texts(today.layout(lines, at(TODAY, 9))) for line in text.splitlines()]
    assert shown[:2] == ["### 🗓️ Today ○ 0/1", "-# 🗓️ all day · **Public holiday**"]
    assert "-# 🗓️ 1 earlier today" in shown and "📝 **Buy stamps**" in shown
    now_on = [line for text in design.texts(today.layout(lines, at(TODAY, 7, 30))) for line in text.splitlines()]
    assert "🗓️ **Swim**" in now_on and "-# on now · until 8:00 am" in now_on


# --- questions: the day and the words go to extraction, never an event ------------------------------------------------
def test_questions_are_answered_from_the_copy(world):
    from tasks import calendar

    run(calendar.update(world.owner.id))
    assert run(plain.show(world.request(), {"day": "tomorrow"}, frozenset())).startswith("🗓️ **Tomorrow** · 2 events")
    assert run(plain.show(world.request(), {"span": "next_week"}, frozenset())).startswith("🗓️ **Next week** · ")
    assert "Dentist check-up" in run(plain.when(world.request(), {"search": "dentist"}, frozenset()))
    assert run(plain.free(world.request(), {"day": "tomorrow", "time": "3"}, frozenset())).startswith("🗓️ Not free at **3:00 pm** tomorrow")


def test_extraction_is_told_no_event_name_and_nothing_is_named_to_the_router(world):
    from tasks import calendar

    run(calendar.update(world.owner.id))
    said = run(plain.state(world.request()))
    assert all(each.title not in " ".join(said.lines) + said.heading for each in kept(world))
    # This week's names go to the code's own matching only: a hint to the router says the word typed (15 Oct)
    from core import routing

    names = run(calendar_task.item_names(world.request()))
    hints = routing.name_hints("is the team on tonight", {"calendar": names})
    assert all(each not in routing.hint_line(hints) for each in names if each.lower() != "team") if hints else True
