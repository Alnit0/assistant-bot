"""All-day events in the Bot calendar (live, 21 Oct: "Add an all day event 21 and 22 November, Sam & Jo’s
Hen/Stag" was asked for a time, in a message of its own, and "All day" then went to the router as a new message,
which said "Not included: All day"). Said as an event or all day, it is an all-day event, over one day or several,
never a to-do; with no time said, the card asks "At what time?" with All day a button, and a typed answer is read
against the card. On what the real API answered (evals/fixtures/calendar_write.json, w25 to w27). Made-up events."""
import json
from pathlib import Path

import pytest

from core import design
from core.actions import Request
from core.errors import UserError
from tasks.calendar import plain, rules
from tests.test_calendar_google import BOT_ID, _add, kept, made_up_key, run, world  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "calendar_write.json").read_text(encoding="utf-8"))
ROUTER = {each["golden"]: each["recorded"] for each in FIXTURES["router"] if each.get("golden") in ("w25", "w26")}
EXTRACTED = {(each["golden"], each["message"]): each["recorded"] for each in FIXTURES["extraction"] if each.get("golden") in ("w25", "w26", "w27")}
LIVE = "Add an all day event 21 and 22 November, Sam & Jo’s Hen/Stag"
NO_TIME = "Add an event 21 and 22 November, Sam & Jo’s Hen/Stag"
TITLE = "Sam & Jo’s Hen/Stag"
TWO_DAYS = "Sat 21 Nov to Sun 22 Nov · all day · 2 days"
# The card: each field it will save on a small line of its own (3 Nov)
TWO_DAYS_LINES = (design.small("Dates · Sat 21 Nov to Sun 22 Nov"), design.small("Time · all day"), design.small("Length · 2 days"))
ONE_DAY = "Add an event 21 November, Sam & Jo’s Hen/Stag"


def said(golden, message):
    """What the real API handed over, less the guessed and not_included lists."""
    _, data = EXTRACTED[(golden, message)]
    return {key: value for key, value in data.items() if key not in ("guessed", "not_included")}


# --- the card and the Bot calendar ------------------------------------------------------------------------------------
def test_an_all_day_event_over_two_days_is_a_card_then_in_the_bot_calendar(world):
    proposal = _add(world, LIVE, said("w25", LIVE))
    assert proposal.question is None and proposal.kind == "new"
    assert proposal.lines == (f"**{TITLE}**", *TWO_DAYS_LINES, design.small("on the Bot calendar")), "the user's own title, curly apostrophe kept"
    done = run(plain.add_save(world.request(), proposal.data))
    assert done == f"🗓️ Added · **{TITLE}** · {TWO_DAYS}"
    (made,) = world.fake.calendars[BOT_ID].values()
    assert made["start"] == {"date": "2026-11-21"} and made["end"] == {"date": "2026-11-23"}, "all day: the API's end is the day after"
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    event = next(each for each in kept(world) if each.title == TITLE)
    assert event.all_day and (event.first_day.isoformat(), event.last_day.isoformat()) == ("2026-11-21", "2026-11-22")
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == f"↩️ 🗓️ **{TITLE}** · taken off the calendar"
    assert world.fake.calendars[BOT_ID] == {}


def test_one_all_day_said_with_a_weekday(world):
    proposal = _add(world, "hen do Saturday, all day", said("w26", "hen do Saturday, all day"))
    assert proposal.lines[:3] == ("**Hen do**", design.small("Date · Sat 7 Nov"), design.small("Time · all day")), "one day: no length line"


def test_several_days_with_no_time_said_are_all_day_with_no_question(world):
    proposal = _add(world, NO_TIME, {"title": TITLE, "day": "21 November", "last_day": "22 November"})
    assert proposal.question is None and proposal.lines[1:4] == TWO_DAYS_LINES, "all day unless times are given (3 Nov)"


def test_with_no_time_for_one_day_the_card_asks_with_all_day_a_button(world):
    proposal = _add(world, ONE_DAY, {"title": TITLE, "day": "21 November"})
    assert proposal.question.text == "At what time?" and [each.label for each in proposal.question.choices] == ["All day"]
    assert proposal.lines[:3] == (f"**{TITLE}**", design.small("Date · Sat 21 Nov"), design.small("Time · ❔"))
    pressed = run(plain.add_card(world.request(ONE_DAY), proposal.question.choices[0].data, frozenset()))
    assert pressed.question is None and pressed.lines[1:3] == (design.small("Date · Sat 21 Nov"), design.small("Time · all day"))


def test_all_day_typed_as_the_answer_is_read_against_the_card(world):
    asked = _add(world, ONE_DAY, {"title": TITLE, "day": "21 November"})
    request = Request(world.owner, 100, "All day", previous=asked.data, asked=("time",))
    answered = run(plain.add_card(request, {"all_day": True}, frozenset()))
    assert answered.question is None and answered.lines[:3] == (f"**{TITLE}**", design.small("Date · Sat 21 Nov"), design.small("Time · all day")), "what the card had kept, all day now"


def test_all_day_as_the_real_api_read_it_against_a_card_of_two_days(world):
    """w27 was recorded against the card of 21 Oct, which asked for a time over two days: All day is both days."""
    card = next(each["card"]["data"] for each in FIXTURES["extraction"] if each.get("golden") == "w27" and each["message"] == "All day")
    request = Request(world.owner, 100, "All day", previous=card, asked=("time",))
    answered = run(plain.add_card(request, said("w27", "All day"), frozenset()))
    assert answered.question is None and answered.lines[1:4] == TWO_DAYS_LINES


def test_a_time_typed_as_the_answer_makes_it_a_timed_event(world):
    asked = _add(world, ONE_DAY, {"title": TITLE, "day": "21 November"})
    request = Request(world.owner, 100, "3pm", previous=asked.data, asked=("time",))
    answered = run(plain.add_card(request, {"time": "3:00 pm"}, frozenset()))
    assert answered.lines[1:4] == (design.small("Date · Sat 21 Nov"), design.small("Time · `3:00 pm` to `4:00 pm`"), design.small("Length · 1 hour"))


def test_a_start_time_over_two_days_with_no_end_asks_when_it_ends(world):
    """w27's "3pm" as the real API read it: from 3 pm on the 21st, and no time on the 22nd. Never made up."""
    card = next(each["card"]["data"] for each in FIXTURES["extraction"] if each.get("golden") == "w27" and each["message"] == "3pm")
    request = Request(world.owner, 100, "3pm", previous=card, asked=("time",))
    with pytest.raises(UserError, match="When does it end on Sun 22 Nov"):
        run(plain.add_card(request, said("w27", "3pm"), frozenset()))


def test_days_that_cannot_be_an_all_day_event_are_said(world):
    with pytest.raises(UserError, match="more than 31 days"):
        _add(world, "party 22 November to 21 November all day", {"title": "party", "day": "22 November", "last_day": "21 November", "all_day": True})


def test_a_repeating_all_day_event_is_never_refused(world):
    """ "Never refuse a recurring event" (3 Nov): every Saturday, all day, is a real all-day recurrence."""
    proposal = _add(world, "market day every Saturday all day", {"title": "market day", "day": "Saturday", "repeat": "days", "weekdays": ["sat"], "all_day": True})
    assert proposal.lines[1:4] == (design.small("Starts · Sat 7 Nov"), design.small("Time · all day"), design.small("Repeat · every Sat · no end"))
    run(plain.add_save(world.request(), proposal.data))
    (made,) = world.fake.calendars[BOT_ID].values()
    assert made["start"] == {"date": "2026-11-07"} and made["end"] == {"date": "2026-11-08"} and made["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=SA"]


def test_a_curly_apostrophe_typed_is_the_straight_one_handed_back():
    assert rules.title_from("Sam & Jo's Hen/Stag", LIVE) == TITLE
    assert rules.title_from("Jo's", "drinks at Jo’s Friday") == "Jo’s"


def test_a_follow_up_naming_the_card_s_title_in_other_case_or_quotes_is_about_that_card():
    from core import conversation
    from core.actions import Field

    title = Field("title", "made up", required=True)
    assert conversation._in_common(title, "sam & jo's hen/stag", "Sam & Jo’s  Hen/Stag")
    assert not conversation._in_common(title, "dentist", "Sam & Jo’s Hen/Stag")


# --- moving and deleting one (Alex, 21 Oct: refused before, with the line meant for another calendar) --------------------
MOVED = "Sat 28 Nov to Sun 29 Nov · all day · 2 days"


def hen_do(world):
    proposal = _add(world, "hen do 21 and 22 November all day", {"title": "hen do", "day": "21 November", "last_day": "22 November", "all_day": True})
    run(plain.add_save(world.request(), proposal.data))
    (ref,) = world.fake.calendars[BOT_ID]
    return ref


def recorded(message):
    action, data = next(each["recorded"] for each in FIXTURES["extraction"] if each.get("golden") in ("w28", "w29") and each["message"] == message)
    return action, {key: value for key, value in data.items() if key not in ("guessed", "not_included")}


def test_an_all_day_event_is_moved_on_a_card_keeping_its_days_and_undo_puts_it_back(world):
    ref = hen_do(world)
    action, data = recorded("move the hen do to 28 November")
    assert action == "calendar_move"
    card = run(plain.move_card(world.request("move the hen do to 28 November"), data, frozenset()))
    assert card.kind == "change" and card.lines == ("**Hen do**", design.change(TWO_DAYS, MOVED))
    assert run(plain.move_save(world.request(), card.data)) == f"🗓️ Moved · **Hen do** · {MOVED}"
    assert run(plain.move_check(world.request(), card.data)) == ""
    made = world.fake.calendars[BOT_ID][ref]
    assert made["start"] == {"date": "2026-11-28"} and made["end"] == {"date": "2026-11-30"}
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == f"↩️ 🗓️ **Hen do** · back to {TWO_DAYS}"
    assert world.fake.calendars[BOT_ID][ref]["start"] == {"date": "2026-11-21"} and world.fake.calendars[BOT_ID][ref]["end"] == {"date": "2026-11-23"}
    assert next(each for each in kept(world) if each.title == "Hen do").first_day.isoformat() == "2026-11-21", "the copy too"


def test_a_new_last_day_said_is_used(world):
    hen_do(world)
    _, data = recorded("move the hen do to 28 and 29 November")
    assert data.get("last_day") == "29 November"
    card = run(plain.move_card(world.request("move the hen do to 28 and 29 November"), {**data, "last_day": "28 November"}, frozenset()))
    assert card.lines[1].endswith("**Sat 28 Nov · all day**"), "one day now"


def test_a_time_for_an_all_day_event_or_the_same_days_is_said(world):
    hen_do(world)
    with pytest.raises(UserError, match="is all day"):
        run(plain.move_card(world.request("move the hen do to 4pm"), {"search": "hen do", "time": "4pm"}, frozenset()))
    with pytest.raises(UserError, match="on those days already"):
        run(plain.move_card(world.request(), {"search": "hen do", "day": "21 November"}, frozenset()))


def test_an_all_day_event_is_deleted_on_a_red_card_and_undo_puts_it_back(world):
    hen_do(world)
    action, data = recorded("delete the hen do")
    assert action == "calendar_delete"
    card = run(plain.delete_card(world.request("delete the hen do"), data, frozenset()))
    assert card.destructive and card.confirm_label == "Delete" and card.lines == (f"**Hen do** · {TWO_DAYS}",)
    assert run(plain.delete_save(world.request(), card.data)) == "🗑️ 🗓️ **Hen do** · deleted"
    assert run(plain.delete_check(world.request(), card.data)) == "" and world.fake.calendars[BOT_ID] == {}
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == "↩️ 🗓️ **Hen do** · back on the calendar"
    (again,) = world.fake.calendars[BOT_ID].values()
    assert again["summary"] == "Hen do" and again["start"] == {"date": "2026-11-21"} and again["end"] == {"date": "2026-11-23"}


def test_cancel_a_one_off_all_day_event_is_its_delete(world):
    hen_do(world)
    card = run(plain.cancel_card(world.request("cancel the hen do"), {"search": "hen do"}, frozenset()))
    assert card.destructive and card.data["all_day"]
