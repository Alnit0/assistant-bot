"""Calendar events as Alex asked for them after two weeks of use (3 Nov): an event with where it is and a
description, one over several days, and repeating ones (weekly, on chosen days, every N weeks, with an end or
none), cancelled one occurrence at a time or stopped from today; the card shows every field it will save, a
line each; and a message that could be an event or a personal routine is asked about with two buttons.

Google is the fake in memory of tests/test_calendar_repeating.py, which expands a series as the API does. Every
event, place and calendar here is made up.
"""
from datetime import date, time, timedelta

import pytest

from core import confirm, config, design
from core import day as days
from core.errors import UserError
from tasks.calendar import plain, rules
from tests.test_calendar_repeating import BOT_ID, DAY, card, kept, made_up_key, run, save, world  # noqa: F401

S = design.small


def add(world, said, data):
    proposal = card(world, plain.add_card, data, said)
    save(world, plain.add_save, plain.add_check, proposal, said)
    return proposal


def made(world):
    return list(world.fake.calendars[BOT_ID].values())


# --- 1. where it is, and a description ---------------------------------------------------------------------------------
QUIZ = "quiz night Friday at 7pm for 2 hours at the community hall, notes: bring the forms"
QUIZ_DATA = {"title": "quiz night", "day": "Friday", "time": "7pm", "length": 120, "location": "community hall", "description": "bring the forms"}


def test_a_location_and_a_description_are_on_the_card_a_line_each_and_saved_to_google(world):
    proposal = card(world, plain.add_card, QUIZ_DATA, QUIZ)
    assert proposal.lines == (
        "**Quiz night**", S("Date · Fri 6 Nov"), S("Time · `7:00 pm` to `9:00 pm`"), S("Length · 2 hours"),
        S("Location · Community hall"), S("Description · Bring the forms"), S("on the Bot calendar"),
    ), "every field it will save, each on a small line of its own"
    said = save(world, plain.add_save, plain.add_check, proposal, QUIZ)
    assert said.endswith("· 📍 Community hall")
    (event,) = made(world)
    assert event["location"] == "Community hall" and event["description"] == "Bring the forms", "Google's own fields"
    assert world.fake.writes() == {BOT_ID}, "the Bot calendar only"


def test_only_the_lines_that_have_a_value_are_shown(world):
    proposal = card(world, plain.add_card, {"title": "dentist", "day": "Friday", "time": "3pm"}, "dentist Friday 3pm")
    assert not any("Location" in line or "Description" in line or "Repeat" in line for line in proposal.lines)


def test_the_answers_say_where_an_event_is(world):
    add(world, QUIZ, QUIZ_DATA)
    friday = DAY + timedelta(days=4)
    assert "`7:00 pm to 9:00 pm` · **Quiz night** · 📍 Community hall" in rules.day_answer(kept(world), friday, DAY).replace("**7:00 pm to 9:00 pm**", "`7:00 pm to 9:00 pm`")
    assert rules.when_answer(rules.next_matching(kept(world), "quiz", days.at(DAY, time(8, 0))), DAY).endswith("· 📍 Community hall")


def test_the_week_view_s_one_day_answer_says_where_too_and_its_week_does_not(world):
    from tasks.calendar import piece

    add(world, QUIZ, QUIZ_DATA)
    friday = DAY + timedelta(days=4)
    (event,) = rules.on_day(kept(world), friday)
    shown = piece(event, friday)
    assert shown.text == "Quiz night" and shown.place == "📍 Community hall", "the week's lines are as they were"
    from core import weekview

    one = plain._with_places(weekview.of(friday, [shown]))
    assert one.notable[0].text == "Quiz night · 📍 Community hall"


def test_a_deleted_event_comes_back_with_undo_with_its_place_and_notes(world):
    add(world, QUIZ, QUIZ_DATA)
    proposal = card(world, plain.delete_card, {"search": "quiz night"}, "delete the quiz night")
    save(world, plain.delete_save, plain.delete_check, proposal)
    assert made(world) == []
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    (again,) = made(world)
    assert again["location"] == "Community hall" and again["description"] == "Bring the forms"


# --- 2. over several days ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("said, data, first, last", [
    ("camping from Friday to Sunday", {"title": "camping", "day": "Friday", "last_day": "Sunday"}, date(2026, 11, 6), date(2026, 11, 8)),
    ("conference 12 to 14 November", {"title": "conference", "day": "12 November", "last_day": "14 November"}, date(2026, 11, 12), date(2026, 11, 14)),
    ("retreat 3 days from Thursday", {"title": "retreat", "day": "Thursday", "days": 3}, date(2026, 11, 5), date(2026, 11, 7)),
])
def test_several_days_are_one_all_day_event_unless_times_are_said(world, said, data, first, last):
    proposal = card(world, plain.add_card, data, said)
    assert proposal.question is None and S("Time · all day") in proposal.lines and S("Length · 3 days") in proposal.lines
    save(world, plain.add_save, plain.add_check, proposal, said)
    (event,) = made(world)
    assert event["start"] == {"date": first.isoformat()} and event["end"] == {"date": (last + timedelta(days=1)).isoformat()}, "one event over the days"


def test_from_a_time_on_the_first_day_to_a_time_on_the_last(world):
    said = "the bach Friday 6pm to Sunday 2pm"
    proposal = card(world, plain.add_card, {"title": "the bach", "day": "Friday", "time": "6pm", "last_day": "Sunday", "ends_at": "2pm"}, said)
    assert proposal.lines[1:4] == (S("Date · Fri 6 Nov to Sun 8 Nov"), S("Time · `6:00 pm` Fri 6 Nov to `2:00 pm` Sun 8 Nov"), S("Length · 1 day 20 hours"))
    save(world, plain.add_save, plain.add_check, proposal, said)
    (event,) = made(world)
    assert rules.Event("k", "x", plain._moment(event["start"]["dateTime"])).start == days.at(date(2026, 11, 6), time(18, 0))
    assert plain._moment(event["end"]["dateTime"]) == days.at(date(2026, 11, 8), time(14, 0))


def test_a_start_time_over_several_days_with_no_end_is_asked_never_made_up(world):
    with pytest.raises(UserError, match="When does it end on Sun 8 Nov"):
        card(world, plain.add_card, {"title": "the bach", "day": "Friday", "time": "6pm", "last_day": "Sunday"}, "the bach Friday 6pm to Sunday")


def test_each_day_of_one_says_which_day_of_how_many(world):
    from tasks.calendar import piece

    add(world, "camping from Friday to Sunday", {"title": "camping", "day": "Friday", "last_day": "Sunday"})
    saturday = DAY + timedelta(days=5)
    assert rules.day_answer(kept(world), saturday, DAY).splitlines()[1] == "all day · **Camping** · day 2 of 3"
    week = rules.week_answer(kept(world), [DAY + timedelta(days=ahead) for ahead in range(7)], DAY, "this week")
    assert [line for line in week.splitlines() if "Camping" in line] == [f"all day · **Camping** · day {n} of 3" for n in (1, 2, 3)]
    (event,) = rules.on_day(kept(world), saturday)
    assert piece(event, saturday).text == "Camping · day 2 of 3", "the week view's day too"


def test_a_timed_one_over_days_is_at_its_time_on_its_first_day_and_all_day_after(world):
    from tasks.calendar import piece

    add(world, "the bach Friday 6pm to Sunday 2pm", {"title": "the bach", "day": "Friday", "time": "6pm", "last_day": "Sunday", "ends_at": "2pm"})
    friday, saturday, sunday = (DAY + timedelta(days=ahead) for ahead in (4, 5, 6))
    (event,) = rules.on_day(kept(world), friday)
    assert (piece(event, friday).text, piece(event, friday).all_day) == ("The bach · day 1 of 3", False)
    assert (piece(event, saturday).text, piece(event, saturday).all_day) == ("The bach · day 2 of 3", True)
    assert piece(event, sunday).text == "The bach · day 3 of 3 · until 2:00 pm"


def test_a_late_night_is_one_day_not_two():
    start = days.at(date(2026, 11, 6), time(20, 0))
    late = rules.Event("k", "Party", start, start + timedelta(hours=6))
    assert rules.part_of(late, date(2026, 11, 6)) is None and rules.part_of(late, date(2026, 11, 7)) is None


# --- 3. repeating, weekly -----------------------------------------------------------------------------------------------
GYM = "create an event called the gym every Tuesday at 4 pm for one hour"
GYM_DATA = {"title": "the gym", "repeat": "days", "weekdays": ["tue"], "time": "4 pm", "length": 60}


def test_the_gym_every_tuesday_at_4_pm_for_one_hour_is_a_weekly_series_never_refused(world):
    proposal = card(world, plain.add_card, GYM_DATA, GYM)
    assert proposal.lines[:5] == ("**The gym**", S("Starts · Tue 3 Nov"), S("Time · `4:00 pm` to `5:00 pm`"), S("Length · 1 hour"), S("Repeat · every Tue · no end"))
    save(world, plain.add_save, plain.add_check, proposal, GYM)
    (series,) = world.fake.series()
    assert series["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"], "no end: it repeats until stopped"
    tuesdays = [DAY + timedelta(days=1 + 7 * week) for week in range(3)]
    assert all(len([each for each in rules.on_day(kept(world), day) if each.title == "The gym"]) == 1 for day in tuesdays)


def test_two_weekdays(world):
    said = "swimming every Monday and Thursday at 7 am"
    proposal = card(world, plain.add_card, {"title": "swimming", "repeat": "days", "weekdays": ["mon", "thu"], "time": "7 am"}, said)
    assert S("Repeat · every Mon and Thu · no end") in proposal.lines
    assert proposal.data["rrule"] == "RRULE:FREQ=WEEKLY;BYDAY=MO,TH"


def test_every_second_week_with_an_end_date(world):
    said = "book club every second Wednesday at 6pm until 16 December at the library"
    proposal = card(world, plain.add_card, {"title": "book club", "repeat": "days", "weekdays": ["wed"], "every_weeks": 2, "time": "6pm", "until": "16 December", "location": "the library"}, said)
    assert S("Repeat · every 2 weeks on Wed · until Wed 16 Dec") in proposal.lines and S("Location · The library") in proposal.lines
    assert proposal.data["rrule"] == "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;UNTIL=20261216T105959Z"
    save(world, plain.add_save, plain.add_check, proposal, said)
    assert world.fake.series()[0]["location"] == "The library"
    dates = sorted({days.day_of(each.start) for each in kept(world) if each.title == "Book club"})
    assert dates == [date(2026, 11, 4), date(2026, 11, 18), date(2026, 12, 2), date(2026, 12, 16)]


def test_a_number_of_times(world):
    proposal = card(world, plain.add_card, {"title": "lessons", "repeat": "days", "weekdays": ["fri"], "time": "5pm", "times": 6}, "lessons every Friday at 5pm, 6 times")
    assert S("Repeat · every Fri · 6 times") in proposal.lines and proposal.data["rrule"].endswith("COUNT=6")


def test_until_a_month_alone_is_asked_on_the_card_its_first_day_or_its_last(world):
    proposal = card(world, plain.add_card, {"title": "choir", "repeat": "days", "weekdays": ["fri"], "time": "6pm", "until": "December"}, "choir Fridays at 6 until December")
    assert proposal.question.text == "Until which day in December?" and [each.label for each in proposal.question.choices] == ["Until 1 Dec", "Until 31 Dec"]
    pressed = run(plain.add_card(world.request("choir Fridays at 6 until December"), proposal.question.choices[1].data, frozenset()))
    assert S("Repeat · every Fri · until Thu 31 Dec") in pressed.lines


# --- changing one or all -----------------------------------------------------------------------------------------------
def test_cancel_the_gym_next_tuesday_is_that_occurrence_only_and_says_so(world):
    add(world, GYM, GYM_DATA)
    proposal = card(world, plain.cancel_card, {"search": "gym", "day": "10 November", "scope": "one"}, "cancel the gym on the 10th")
    assert proposal.lines[1] == S("One occurrence only: the rest stay as they are")
    save(world, plain.cancel_save, plain.cancel_check, proposal)
    gym_days = sorted({days.day_of(each.start) for each in kept(world) if each.title == "The gym"})
    assert date(2026, 11, 10) not in gym_days and date(2026, 11, 3) in gym_days and date(2026, 11, 17) in gym_days
    assert run(plain.add_undo(world.request("undo"), {})) == "↩️ 🗓️ **The gym** · on again that day", "Undo on its line"


def test_stop_the_weekly_gym_ends_the_whole_series_from_today_and_says_so(world):
    add(world, GYM, GYM_DATA)
    world_now = days.at(date(2026, 11, 11), time(9, 0))
    from core import clock

    clock.advance_to(world_now)
    proposal = card(world, plain.cancel_card, {"search": "gym", "scope": "following"}, "stop the weekly gym")
    assert proposal.lines[1:] == ("Ends · the last one Tue 10 Nov", S("The whole series: none from Tue 17 Nov; past ones kept"))
    save(world, plain.cancel_save, plain.cancel_check, proposal)
    assert sorted({days.day_of(each.start) for each in kept(world) if each.title == "The gym"}) == [date(2026, 11, 10)], "the copy from this Monday on: 10 Nov kept, none after"
    assert world.fake.series()[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261110T105959Z"], "past ones kept: the series ends, it is not deleted"


def test_delete_all_of_them_ends_the_series_from_today_too_and_completely_takes_every_time(world):
    from core import clock

    add(world, GYM, GYM_DATA)
    clock.advance_to(days.at(date(2026, 11, 11), time(9, 0)))
    proposal = card(world, plain.delete_card, {"search": "gym"}, "delete all of them")
    assert proposal.kind == "change" and not proposal.destructive and proposal.data["op"] == "stop", "past ones kept"
    whole = card(world, plain.delete_card, {"search": "gym", "scope": "all"}, "delete the gym completely")
    assert whole.destructive and whole.lines[1] == S("The whole series: every time, past ones too")


def test_delete_a_series_none_of_which_has_come_yet_is_deleting_it(world):
    add(world, GYM, GYM_DATA)
    proposal = card(world, plain.delete_card, {"search": "gym"}, "delete the gym")
    assert proposal.destructive and proposal.data["op"] == "series_delete", "ending it before its first one is deleting it"


def test_move_tuesday_s_gym_to_5_pm_moves_that_one_only(world):
    add(world, GYM, GYM_DATA)
    proposal = card(world, plain.move_card, {"search": "gym", "day": "Tuesday", "time": "5 pm", "scope": "one"}, "move Tuesday's gym to 5 pm")
    assert proposal.lines[2] == S("One occurrence only: the rest stay as they are")
    save(world, plain.move_save, plain.move_check, proposal)
    starts = {days.day_of(each.start): days.local_time(each.start) for each in kept(world) if each.title == "The gym"}
    assert starts[date(2026, 11, 3)] == time(17, 0) and starts[date(2026, 11, 10)] == time(16, 0)


def test_every_change_to_the_calendar_has_undo_on_its_line():
    from core import actions

    actions.set_catalogue([])
    for name in ("calendar_add", "calendar_move", "calendar_delete", "calendar_cancel"):
        found = next(each for each in plain.writing_actions() if each.name == name)
        assert found.undo is plain.add_undo, name


# --- an event or a personal routine -----------------------------------------------------------------------------------------
def test_a_tie_between_an_event_and_a_routine_has_two_buttons_calendar_event_and_routine(monkeypatch):
    from tasks.calendar import task as calendar_task
    from tasks.habits import task as habits_task

    for name, value in (("CALENDAR_ENABLED", True), ("CALENDAR_WRITE", True), ("CALENDAR_BOT_ID", BOT_ID), ("HABITS_ENABLED", True)):
        monkeypatch.setattr(config, name, value)
    entries = [*calendar_task.entries(), *habits_task.entries()]
    drawn = confirm.render_tie(entries, 7, "yoga every Thursday at 6pm")
    labels = [button.label for button in drawn.rows[0]]
    assert labels[:2] == ["Calendar event", "Routine"] and len(labels) == 3, "two answers, and Cancel (Neither)"
    assert drawn.rows[0][0].style == drawn.rows[0][1].style == "primary"


def test_the_routines_line_says_what_repeats_and_is_an_event_is_the_calendar_s_only_while_it_adds_events(monkeypatch):
    from tasks.habits import task as habits_task

    monkeypatch.setattr(config, "CALENDAR_ENABLED", True)
    monkeypatch.setattr(config, "CALENDAR_BOT_ID", BOT_ID)
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    assert "calendar event" not in habits_task.only_for
    monkeypatch.setattr(config, "CALENDAR_WRITE", True)
    assert "is a calendar event, not a personal routine" in habits_task.only_for and "genuine tie" in habits_task.only_for


# --- the dev bot's made-up Google (GOOGLE_CALENDAR_FAKE, the self-test's): a series as the API keeps it -------------------
def test_the_dev_bots_made_up_google_expands_a_series_and_the_self_test_leaves_nothing_behind(world, monkeypatch, scratch):
    from tasks.calendar import google

    fake = scratch / "dev-bot-calendar.json"
    monkeypatch.setattr(config, "GOOGLE_CALENDAR_FAKE", str(fake))
    monkeypatch.setattr(google, "_send", lambda method, url, body, headers: google._fake(method, url, body))
    add(world, GYM, GYM_DATA)
    tuesdays = sorted({days.day_of(each.start) for each in kept(world) if each.title == "The gym"})
    assert tuesdays[:3] == [date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 17)], "read back a happening at a time"
    proposal = card(world, plain.cancel_card, {"search": "gym", "day": "10 November", "scope": "one"}, "cancel the gym on the 10th")
    save(world, plain.cancel_save, plain.cancel_check, proposal)
    assert date(2026, 11, 10) not in {days.day_of(each.start) for each in kept(world) if each.title == "The gym"}
    import json

    from core import clock

    clock.advance_to(days.at(date(2026, 11, 18), time(9, 0)))
    proposal = card(world, plain.cancel_card, {"search": "gym", "scope": "following"}, "stop the weekly gym")
    save(world, plain.cancel_save, plain.cancel_check, proposal)
    assert sorted({days.day_of(each.start) for each in kept(world) if each.title == "The gym"}) == [date(2026, 11, 17)]
    from tasks.calendar import series, source

    # The self-test's own clean-up: every event it made deleted from the Bot calendar, not in words (an ended series is found no more)
    for made_ref in list(json.loads(fake.read_text(encoding="utf-8"))["calendars"][BOT_ID]):
        run(source.bot().delete(made_ref))
    run(series.refresh(world.owner.id, source.bot()))
    assert not [each for each in kept(world) if each.title == "The gym"]

    left = json.loads(fake.read_text(encoding="utf-8"))
    assert left["calendars"][BOT_ID] == {} and left["exceptions"][BOT_ID] == {}, "nothing of it is left in the file"
