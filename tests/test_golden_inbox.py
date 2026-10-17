"""The smart inbox's golden conversations (evals/fixtures/inbox.json, i1 to i9 and f1 to f5): each replayed end to
end as Claude really answered it (the router, `sort`, each item's own extraction; recorded with
python -m evals.inbox --live --record), against every task it sorts into. Everything else is the bot's own code
against a temporary database. The files are made up and drawn by evals/inbox_files.py."""
import json
from pathlib import Path

from core import smartinbox
from evals import inbox_files
from tests.test_smartinbox import attached, buttons, inbox, inbox_cards, logged_rows, made_up_key, press, press_undo, reminders_now, say_with, shown, todos_now  # noqa: F401
from tests.test_golden import bot  # noqa: F401
from tests.test_conversation import open_cards, world  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "inbox.json").read_text(encoding="utf-8"))["inbox"]
BY = {each["golden"]: each for each in FIXTURES}


def replay(bot, golden):
    conversation = BY[golden]
    recorded = conversation["recorded"]
    queue = [("route", recorded["route"])] if recorded.get("route") else []
    queue += [("sort", recorded["sort"])] if recorded.get("sort") else []
    queue += [tuple(each[2]) for each in recorded["extract"]]
    bot.claude(*queue)
    if conversation.get("file"):
        say_with(bot, "", attached(*inbox_files.FILES[conversation["file"]]()))
    else:
        bot.say(conversation["message"], straight_after=bool(conversation.get("after")))
    assert bot.left == [], f"{golden}: not every recorded answer was asked for"
    return shown(bot)


def first_lines(card):
    return [line for line in card.text.splitlines() if not line.startswith("-# ")]


def test_every_inbox_conversation_is_recorded_and_judged_right():
    from core import routing
    from evals.inbox import problem

    names = ["briefing", "bugs", "calendar", "channel", "diary", "habits", "nudges", "pills", "schedule", "timers", "todos", "weather", "birthdays"]
    assert len(FIXTURES) >= 15
    for conversation in FIXTURES:
        recorded = conversation.get("recorded")
        assert recorded, f"{conversation['golden']} is not recorded"
        route = routing.parse(recorded["route"], names) if recorded.get("route") else None
        found = smartinbox.parse(recorded["sort"], names) if recorded.get("sort") else None
        assert problem(conversation, route, found, [each[2] for each in recorded["extract"]]) == "", conversation["golden"]


def test_i1_four_things_one_card_and_the_reminder_with_no_time_asks_on_it(inbox):
    card = replay(inbox, "i1")
    lines = first_lines(card)
    assert lines[0] == "📥 Inbox · 4 things"
    assert any(line.startswith("⏰ Reminders · **Renew rego**") for line in lines), lines
    assert any(line.startswith("⏰ Reminders · **Call Mum**") and "2:00 pm" in line for line in lines), lines
    assert any(line.startswith("📝 To-dos · **Need milk**") or line.startswith("📝 To-dos · **Milk**") for line in lines), lines
    assert any(line.startswith("📅 Calendar · **Dentist**") for line in lines), lines
    assert todos_now(inbox) == [] and inbox.google.writes() == []


def test_i2_a_line_fixed_in_words_then_save_and_undo(inbox):
    replay(inbox, "i1")
    card = replay(inbox, "i2")
    lines = first_lines(card)
    assert any(line.startswith("⏰ Reminders · **Renew rego**") and "9:00 am" in line for line in lines), lines
    assert buttons(card) == ["Save all", "Cancel"], "nothing left to ask"
    saved = press(inbox, "save").cards[-1]
    assert saved.text.splitlines()[0] == "✅ Saved · 4 of 4", saved.text
    assert sorted(reminders_now(inbox)) == ["Call Mum", "Renew rego"] and len(todos_now(inbox)) == 1
    assert len(inbox.google.writes()) == 1
    press_undo(inbox)
    assert reminders_now(inbox) == [] and todos_now(inbox) == [] and inbox.google.calendars


def test_i3_what_its_task_cannot_place_is_asked_on_the_card(inbox):
    card = replay(inbox, "i3")
    assert "❓ “sort out the thing with Sam” · I couldn't tell what to do with this" in card.text
    assert buttons(card) == ["Save 1", "Cancel"]


def test_i4_an_expiry_and_a_repeating_reminder(inbox):
    from tasks.nudges import expiry

    card = replay(inbox, "i4")
    assert first_lines(card)[0] == "📥 Inbox · 2 things"
    press(inbox, "save")
    assert [each.name.lower() for each in __import__("tests.test_conversation", fromlist=["run"]).run(expiry.every(inbox.owner.id))] == ["rego"]
    assert reminders_now(inbox) == ["Put the bins out"]


def test_i5_a_pill_taken_the_diary_and_a_routine_step_and_the_diary_s_words_never_reach_the_log(inbox):
    from tests.test_golden_crosstask import _pill

    _pill(inbox, "Testvit", "8:00 am")
    card = replay(inbox, "i5")
    assert first_lines(card)[0] == "📥 Inbox · 3 things"
    assert "💊" in card.text and "📔" in card.text or "Diary" in card.text
    row = logged_rows()[-1]
    assert "good day" not in (row[1] or "") and row[3] is None, "a turn with the diary in it keeps no words and no trace"


def test_i6_a_to_do_and_an_event(inbox):
    card = replay(inbox, "i6")
    lines = first_lines(card)
    assert any(line.startswith("📝 To-dos · **Call the plumber**") for line in lines), lines
    assert any(line.startswith("📅 Calendar · **Lunch with Sam**") for line in lines), lines


def test_i7_to_i9_one_thing_a_list_and_a_question_never_reach_the_inbox(inbox):
    for golden in ("i7", "i8", "i9"):
        assert BY[golden]["recorded"]["route"]["several"] is False and "sort" not in BY[golden]["recorded"], golden


def test_f1_a_booking_screenshot_is_an_event_and_nothing_of_it_is_logged(inbox):
    card = replay(inbox, "f1")
    assert first_lines(card)[0] == "📥 Inbox · 1 thing" and "📅 Calendar ·" in card.text
    assert "Thu 5 Nov" in card.text and "3:00 pm" in card.text and buttons(card) == ["Save all", "Cancel"], card.text
    reply = logged_rows()[-1][1] or ""
    assert "Dental" not in reply and smartinbox.FROM_A_FILE in reply


def test_f2_a_bill_is_a_reminder_on_its_day_whose_card_asks_the_time(inbox):
    card = replay(inbox, "f2")
    assert "⏰ Reminders ·" in card.text and "Power" not in first_lines(card)[0]


def test_f3_a_medicine_label_is_a_suggested_pill_never_named_on_the_first_line(inbox):
    from tasks.pills import store as pills_store
    from tests.test_conversation import run

    card = replay(inbox, "f3")
    assert first_lines(card)[0] == "📥 Inbox · 1 thing" and "Testvit" in card.text
    assert run(pills_store.pills(inbox.owner.id)) == []


def test_f4_a_gym_plan_csv_is_kept_as_rows(inbox):
    card = replay(inbox, "f4")
    assert "🏋️ Gym · **gym plan** · 5 rows kept for the gym task to come" in card.text, card.text


def test_f5_a_file_with_nothing_useful_says_what_it_saw(inbox):
    card = replay(inbox, "f5")
    assert card.text == smartinbox.NOTHING_FOUND + ": an image with a blue circle and a red square" and inbox_cards() == []
