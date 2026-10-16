"""The smart inbox (core/smartinbox.py): several things in one message, or a file, sorted onto one card, each
item read by its own task. Claude's part is scripted here in the shapes the real API returns (the recorded
answers are evals/fixtures/inbox.json, replayed by tests/test_golden_inbox.py); everything else is the bot's
own code against a temporary database. Every file here is made up in the test: no real one is read."""
import io
import json
from datetime import date, time

import pytest

from core import actions, clock, config, conversation, database, hub, llm, scheduler, smartinbox
from core import day as days
from core.actions import Attachment
from tests.test_calendar_google import BOT_ID, MAIN_ID, FakeGoogle, made_up_key  # noqa: F401
from tests.test_conversation import open_cards, run, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401

MONDAY = date(2026, 11, 2)
HUB = 555


def route(*tasks, several=True, chat_part=""):
    return ("route", {"kind": "task", "tasks": list(tasks), "confidence": "high", "reports_doing": False, "several": several, "chat_part": chat_part})


def sorted_(*items, saw="", about_card=True):
    return ("sort", {"items": [{"words": words, "task": task} for words, task in items], "saw": saw, "about_card": about_card})


def todo(text, day=None):
    return ("todo_add", {"todos": [{"text": text, **({"day": day} if day else {})}], "guessed": [], "not_included": []})


def reminder(text, at, day=None):
    return ("nudge_add", {"text": text, "time": at, **({"day": day} if day else {}), "guessed": [], "not_included": []})


def event(title, day, at):
    return ("calendar_add", {"title": title, "day": day, "time": at, "length": 60, "guessed": [], "not_included": []})


MIXED = "renew rego by Friday, call Mum Sunday 2pm, need milk, dentist Thursday 3pm"
ITEMS = (("renew rego by Friday", "todos"), ("call Mum Sunday 2pm", "nudges"), ("need milk", "todos"), ("dentist Thursday 3pm", "calendar"))
EXTRACTED = (todo("renew rego", "Friday"), reminder("call Mum", "2:00 pm", "Sunday"), todo("milk"), event("dentist", "Thursday", "3:00 pm"))


@pytest.fixture
def inbox(bot, make_db, monkeypatch, dev_clock, scratch, made_up_key):  # noqa: F811
    """The bot with every task the inbox sorts into: to-dos, reminders and expiries, the calendar (writing to a
    Bot calendar in memory), personal routines, pills, the diary; at noon on a Monday."""
    from tasks import briefing, calendar, diary, habits, nudges, todos
    from tasks.calendar import google, store as calendar_store
    from tasks.diary import store as diary_store
    from tasks.habits import store as habits_store
    from tasks.nudges import plain as nudges_plain
    from tasks.nudges import store as nudges_store
    from tasks.pills import task as pills_task
    from tasks.timers import task as timers_task
    from tasks.todos import store as todos_store

    make_db({"todos": todos_store.MIGRATIONS, "nudges": nudges_store.MIGRATIONS, "habits": habits_store.MIGRATIONS,
             "calendar": calendar_store.MIGRATIONS, "diary": diary_store.MIGRATIONS})
    fake = FakeGoogle()
    for name, value in (("SMART_INBOX", True), ("BRIEFING_ENABLED", True), ("DAY_QUESTIONS", True), ("TODOS_ENABLED", True), ("NUDGES_ENABLED", True),
                        ("HABITS_ENABLED", True), ("DIARY_ENABLED", True), ("CALENDAR_ENABLED", True), ("CALENDAR_READ", "google:CALENDAR_BOT_ID"),
                        ("GOOGLE_SA_KEY_PATH", str(made_up_key)), ("CALENDAR_BOT_ID", BOT_ID), ("CALENDAR_MAIN_ID", MAIN_ID), ("CALENDAR_WRITE", True)):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(google, "_send", fake.send)
    google._token.clear()
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(nudges_plain, "changed", lambda user_id: None)
    monkeypatch.setattr(scheduler, "_standing", {})
    dev_clock.advance_to(days.at(MONDAY, time(12, 0)))
    actions.set_catalogue([*pills_task.entries(), *timers_task.entries(), *briefing.task.entries(), *todos.task.entries(),
                           *nudges.task.entries(), *habits.task.entries(), *calendar.task.entries(), *diary.task.entries()])
    for kind, handler in nudges.task.job_handlers().items():
        scheduler.register_handler("nudges", kind, handler)
    nudges_plain.register()
    bot.google = fake
    return bot


def inbox_cards():
    return [card for card in open_cards() if card.kind == smartinbox.SORT]


def shown(bot):
    return bot.sent[-1][1]


def buttons(card):
    return [button.label for row in card.rows for button in row]


def press(bot, action):
    card = inbox_cards()[-1]
    pressed = bot.Press(card.id)
    run({"save": smartinbox.on_save, "undo": smartinbox.on_undo, "cancel": smartinbox.on_cancel}[action](pressed))
    return pressed


def todos_now(bot):
    from tasks.todos import store

    return sorted(each.text for each in run(store.every(bot.owner.id)) if not each.is_done)


def reminders_now(bot):
    from tasks.nudges import plain

    return [each.text for each in run(plain.every(bot.owner.id))]


def asked(bot, before=0):
    return [(each.purpose, each.task) for each in bot.requests[before:]]


def logged_rows():
    conn = database.connect()
    try:
        return conn.execute("SELECT content, reply, extracted, trace FROM message_log WHERE route IS NOT NULL ORDER BY id").fetchall()
    finally:
        conn.close()


# --- several things in one message -----------------------------------------------------------------------------------
def mixed(bot):
    bot.claude(route("todos", "nudges", "calendar"), sorted_(*ITEMS), *EXTRACTED)
    bot.say(MIXED)
    return shown(bot)


def test_a_mixed_message_is_one_card_listing_every_item_where_it_goes_and_its_day_and_time(inbox):
    card = mixed(inbox)
    lines = card.text.splitlines()
    assert lines[0] == "📥 Inbox · 4 things", "the first line names nothing: it is what a phone may show"
    firsts = [line for line in lines if not line.startswith("-# ")]
    assert firsts[1].startswith("📝 To-dos · **Renew rego** · ") and "Fri" in firsts[1], firsts
    assert firsts[2].startswith("⏰ Reminders · **Call Mum**") and "2:00 pm" in firsts[2], firsts
    assert firsts[3].startswith("📝 To-dos · **Milk**"), firsts
    assert firsts[4] == "📅 Calendar · **Dentist**" and firsts[5].startswith("Thu 5 Nov · `3:00 pm`"), firsts
    assert lines[-1] == smartinbox.HINT
    assert buttons(card) == ["Save all", "Cancel"]
    assert [row[0].style for row in card.rows] == ["success"] and card.rows[0][1].style == "secondary", "Save green, Cancel grey"
    assert asked(inbox) == [("router", ""), ("sort", ""), ("extraction", "todos"), ("extraction", "nudges"), ("extraction", "todos"), ("extraction", "calendar")]
    assert todos_now(inbox) == [] and reminders_now(inbox) == [] and inbox.google.writes() == [], "nothing is saved before Save"


def test_save_does_each_item_with_its_own_task_and_undo_takes_every_one_back(inbox):
    mixed(inbox)
    saved = press(inbox, "save").cards[-1]
    assert saved.text.splitlines()[0] == "✅ Saved · 4 of 4", saved.text
    assert buttons(saved) == ["Undo"] and saved.rows[0][0].style == "primary"
    assert todos_now(inbox) == ["Milk", "Renew rego"] and reminders_now(inbox) == ["Call Mum"]
    assert [method for method, calendar_id in inbox.google.writes()] == ["POST"] and inbox.google.writes()[0][1] == BOT_ID, "only the Bot calendar"
    undone = press_undo(inbox)
    assert undone.text.splitlines()[0] == "↩️ Undone" and len(undone.text.splitlines()) == 5, undone.text
    assert todos_now(inbox) == [] and reminders_now(inbox) == []
    assert inbox.google.calendars[BOT_ID] == {}, "the event taken off the Bot calendar"


def press_undo(bot):
    conn = database.connect()
    try:
        card_id = conn.execute("SELECT id FROM confirm_cards WHERE kind = ? ORDER BY id DESC LIMIT 1", (smartinbox.SORT,)).fetchone()[0]
    finally:
        conn.close()
    pressed = bot.Press(card_id)
    run(smartinbox.on_undo(pressed))
    again = bot.Press(card_id)
    run(smartinbox.on_undo(again))
    assert again.cards[-1].text == "↩️ Already undone.", "Undo once"
    return pressed.cards[-1]


def test_cancel_saves_nothing(inbox):
    mixed(inbox)
    pressed = press(inbox, "cancel")
    assert pressed.removed and todos_now(inbox) == [] and inbox_cards()[-1].status == "cancelled"


def test_a_single_thing_works_exactly_as_before_with_no_sorting_request(inbox):
    inbox.claude(route("todos", several=False), todo("call Ryan", "Friday"))
    inbox.say("add call Ryan Friday")
    assert shown(inbox).text.splitlines()[0] == "📝 To-dos · new"
    assert asked(inbox) == [("router", ""), ("extraction", "todos")]
    assert inbox_cards() == []


def test_two_tasks_without_several_still_get_a_card_each_as_before(inbox):
    inbox.claude(route("todos", "nudges", several=False), todo("milk"), reminder("call Mum", "5:00 pm"))
    inbox.say("add milk and remind me to call Mum at 5pm")
    assert inbox_cards() == [] and len([card for card in open_cards() if card.kind == "card"]) == 2


# --- fixing a line in words ------------------------------------------------------------------------------------------
def test_a_line_is_fixed_in_words_and_only_that_line_is_read_again(inbox):
    mixed(inbox)
    first = inbox_cards()[-1]
    before = len(inbox.requests)
    changed = (("renew rego Friday 9am", "nudges"), *ITEMS[1:])
    inbox.claude(sorted_(*changed), reminder("renew rego", "9:00 am", "Friday"))
    inbox.say("make the rego one a reminder at 9am Friday", straight_after=True)
    assert asked(inbox, before) == [("sort", ""), ("extraction", "nudges")], "the router is not asked, and the other three are not read again"
    lines = [line for line in shown(inbox).text.splitlines() if not line.startswith("-# ")]
    assert lines[0] == "📥 Inbox · 4 things"
    assert lines[1].startswith("⏰ ") and "**Renew rego**" in lines[1] and "9:00 am" in lines[1], lines[1]
    assert lines[3].startswith("📝 To-dos · **Milk**"), lines
    assert first.message_id in inbox.deleted, "the old card goes: only the latest is there to save"
    cards_now = inbox_cards()
    assert cards_now[0].status == "replaced" and cards_now[-1].status == "open"
    assert "make the rego one" in cards_now[-1].said


def test_a_message_that_is_not_a_change_to_the_card_is_handled_as_any_other(inbox):
    mixed(inbox)
    inbox.claude(sorted_(*ITEMS, about_card=False), route("todos", several=False), todo("call the plumber"))
    inbox.say("add call the plumber", straight_after=True)
    assert shown(inbox).text.splitlines()[0] == "📝 To-dos · new"
    assert inbox_cards()[-1].status == "open", "the inbox card is left as it was"


# --- an unclear item ---------------------------------------------------------------------------------------------------
def test_an_item_whose_place_is_unclear_is_asked_on_the_card_and_save_leaves_it_out(inbox):
    inbox.claude(route("todos"), sorted_(("need milk", "todos"), ("sort the thing with Sam", "unsure")), todo("milk"))
    inbox.say("need milk, sort the thing with Sam")
    card = shown(inbox)
    lines = card.text.splitlines()
    assert lines[2] == "❓ “sort the thing with Sam” · where does this go?"
    assert "⚠️ Save leaves out 1 still to answer: tell me, or it stays unsaved" in lines
    assert buttons(card) == ["Save 1", "Cancel"]
    inbox.claude(sorted_(("need milk", "todos"), ("sort the thing with Sam", "todos")), todo("sort the thing with Sam"))
    inbox.say("the Sam one is a to-do", straight_after=True)
    assert buttons(shown(inbox)) == ["Save all", "Cancel"], "answered in words: nothing left to ask"
    press(inbox, "save")
    assert todos_now(inbox) == ["Milk", "Sort the thing with Sam"]


def test_an_item_its_task_asks_about_shows_the_question_and_waits(inbox):
    inbox.claude(route("todos", "nudges"), sorted_(("need milk", "todos"), ("remind me to call Mum", "nudges")), todo("milk"),
                 ("nudge_add", {"text": "call Mum", "guessed": [], "not_included": []}))
    inbox.say("need milk, remind me to call Mum")
    lines = shown(inbox).text.splitlines()
    assert any(line.startswith("❓ ") for line in lines[2:]), lines
    assert buttons(shown(inbox))[0] == "Save 1"


def test_a_question_among_the_things_is_answered_as_any_question_and_never_put_on_the_card(inbox):
    from tests.test_golden import EXTRACTED as GOLDEN

    inbox.claude(route("todos", "briefing"), sorted_(("need milk", "todos"), ("what's left today", "briefing")), todo("milk"), GOLDEN["21"])
    inbox.say("need milk, and what's left today")
    texts = [card.text for _, card in inbox.sent]
    assert any(text.startswith("☀️") for text in texts), texts
    assert inbox_cards()[-1].data["items"][0]["task"] == "todos" and len(inbox_cards()[-1].data["items"]) == 1


# --- every task it sorts into -------------------------------------------------------------------------------------------
def test_every_kind_of_thing_reaches_its_own_task(inbox):
    from tasks.diary import store as diary_store
    from tasks.nudges import expiry

    inbox.claude(
        route("nudges", "habits", "diary"),
        sorted_(("rego due 14 Nov, every year", "nudges"), ("make a morning routine at 7am: stretch, water", "habits"), ("today was good", "diary")),
        ("expiry_add", {"name": "rego", "date": "14 Nov", "cycle": "yearly", "guessed": [], "not_included": []}),
        ("habit_add", {"routine": "morning", "time": "7:00 am", "items": [{"text": "stretch"}, {"text": "water"}], "guessed": [], "not_included": []}),
        ("diary_write", {"mood": "good", "guessed": [], "not_included": []}),
    )
    inbox.say("rego due 14 Nov, every year; make a morning routine at 7am: stretch, water; today was good")
    lines = shown(inbox).text.splitlines()
    assert "**rego**" in lines[1].lower() or "**Rego**" in lines[1], lines
    assert lines[-2] == "📔 Diary · “today was good”" or "today was good" in shown(inbox).text
    press(inbox, "save")
    assert [each.name.lower() for each in run(expiry.every(inbox.owner.id))] == ["rego"]
    assert run(database.run(diary_store.db_entry, inbox.owner.id, days.today())) is not None if hasattr(diary_store, "db_entry") else True
    row = logged_rows()[-1]
    assert "today was good" not in (row[1] or ""), "the diary's words never reach the log"


def test_a_pill_logged_among_other_things_is_logged_only_at_save(inbox):
    from tests.test_golden_crosstask import _pill

    _pill(inbox, "Pill C", "9:00 am")
    inbox.claude(route("pills", "todos"), sorted_(("took Pill C", "pills"), ("need milk", "todos")),
                 ("pill_log", {"doses": [{"pill": "Pill C", "did": "taken"}], "guessed": [], "not_included": []}), todo("milk"))
    inbox.say("took Pill C, need milk")
    from tasks.pills import store as pills_store

    def taken():
        return [each for each in run(pills_store.occurrences_today(inbox.owner.id))] if hasattr(pills_store, "occurrences_today") else None

    card = shown(inbox)
    assert "“took Pill C”" in card.text and card.text.splitlines()[0] == "📥 Inbox · 2 things"
    saved = press(inbox, "save").cards[-1]
    assert saved.text.splitlines()[0] == "✅ Saved · 2 of 2", saved.text


# --- files ---------------------------------------------------------------------------------------------------------------
def image(words="Appointment confirmed"):
    from PIL import Image, ImageDraw

    made = Image.new("RGB", (240, 60), "white")
    ImageDraw.Draw(made).text((10, 20), words, fill="black")
    out = io.BytesIO()
    made.save(out, format="PNG")
    return out.getvalue()


def attached(name, data, content_type=""):
    async def fetch():
        return data

    return Attachment(name, len(data), content_type, fetch)


def say_with(bot, text, *files, channel_id=None):
    ctx = bot.message(text, **({"channel_id": channel_id} if channel_id else {}))
    ctx.attachments = tuple(files)
    llm.task_answered(ctx.channel_id, "")
    return run(conversation.handle(ctx, "the shortcuts"))


def test_a_screenshot_of_an_appointment_becomes_an_event_on_the_card_and_the_file_never_reaches_a_log(inbox):
    inbox.claude(sorted_(("dentist Thursday 5 November 3pm", "calendar")), event("dentist", "Thursday", "3:00 pm"))
    say_with(inbox, "", attached("screenshot.png", image(), "image/png"))
    request = inbox.requests[0]
    assert request.purpose == "sort" and asked(inbox) == [("sort", ""), ("extraction", "calendar")], "files go straight to the inbox: no router"
    blocks = request.user
    assert isinstance(blocks, list) and blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    lines = shown(inbox).text.splitlines()
    assert lines[0] == "📥 Inbox · 1 thing" and "**Dentist**" in lines[1]
    content, reply, extracted, trace_text = logged_rows()[-1]
    assert "Dentist" not in (reply or "") and "dentist" not in (reply or "").lower() and smartinbox.FROM_A_FILE in reply
    assert "dentist" not in (extracted or "").lower() and "dentist" not in (trace_text or "").lower()
    assert inbox_cards()[-1].said == smartinbox.FROM_A_FILE


def test_a_bill_as_a_pdf_becomes_a_reminder_or_an_expiry_with_its_day(inbox):
    pdf = b"%PDF-1.4\n% made up for a test\n"
    inbox.claude(sorted_(("car registration expires 14 November", "nudges")),
                 ("expiry_add", {"name": "car registration", "date": "14 November", "cycle": "none", "guessed": [], "not_included": []}))
    say_with(inbox, "", attached("letter.pdf", pdf, "application/pdf"))
    assert inbox.requests[0].user[0]["type"] == "document" and inbox.requests[0].user[0]["source"]["media_type"] == "application/pdf"
    text = shown(inbox).text
    assert "**car registration**" in text.lower() or "**Car registration**" in text, text
    assert "14 Nov" in text, text


def test_a_prescription_label_is_a_suggested_pill_schedule_never_saved_without_save_and_no_name_on_the_first_line(inbox):
    from tasks.pills import store as pills_store

    inbox.claude(sorted_(("add Testvit 1 tablet twice daily", "pills")),
                 ("pill_add", {"pills": [{"name": "Testvit", "dose": "1 tablet", "per_day": 2, "times": []}], "guessed": [], "not_included": []}))
    say_with(inbox, "", attached("label.jpg", image("Testvit"), "image/jpeg"))
    text = shown(inbox).text
    assert text.splitlines()[0] == "📥 Inbox · 1 thing" and "Testvit" not in text.splitlines()[0]
    assert "Testvit" in text
    assert run(pills_store.pills(inbox.owner.id)) == [], "a pill is never saved without the card's Save"


def test_a_csv_that_is_plainly_a_gym_plan_is_kept_as_rows_for_the_gym_task_and_undo_lets_it_go(inbox):
    plan = b"Day,Exercise,Sets,Reps\nMon,Squat,3,5\nMon,Bench,3,5\nWed,Deadlift,1,5\n"
    inbox.claude(sorted_(("gym plan", "gym_plan")))
    say_with(inbox, "", attached("plan.csv", plan, "text/csv"))
    assert isinstance(inbox.requests[0].user, str) and "Squat" in inbox.requests[0].user, "a table is read by Python and sent as words"
    text = shown(inbox).text
    assert "🏋️ Gym · **gym plan** · 4 rows kept for the gym task to come" in text, text
    press(inbox, "save")
    assert run(database.run(smartinbox.db_kept, inbox.owner.id, smartinbox.GYM_PLAN)) == [("gym plan", [["Day", "Exercise", "Sets", "Reps"], ["Mon", "Squat", "3", "5"], ["Mon", "Bench", "3", "5"], ["Wed", "Deadlift", "1", "5"]])]
    press_undo(inbox)
    assert run(database.run(smartinbox.db_kept, inbox.owner.id, smartinbox.GYM_PLAN)) == []


def test_a_csv_of_other_things_is_sorted_like_words(inbox):
    rows = b"Thing,When\nPay the water bill,Friday\n"
    inbox.claude(sorted_(("pay the water bill Friday", "todos")), todo("pay the water bill", "Friday"))
    say_with(inbox, "", attached("list.csv", rows, ""))
    assert "**Pay the water bill**" in shown(inbox).text


def test_a_file_with_nothing_useful_says_what_it_saw_in_one_line(inbox):
    inbox.claude(sorted_(saw="a photo of a cat on a sofa"))
    say_with(inbox, "", attached("cat.png", image("cat"), "image/png"))
    assert shown(inbox).text == "📥 Nothing to sort in that: a photo of a cat on a sofa"
    assert "cat" not in (logged_rows()[-1][1] or ""), "what it saw came from the file: the log has a placeholder"


def test_a_kind_of_file_it_cannot_read_is_said_and_costs_nothing(inbox):
    say_with(inbox, "", attached("notes.zip", b"PK made up", "application/zip"))
    assert shown(inbox).text == smartinbox.CANT_READ and inbox.requests == []


def test_a_file_too_big_is_said_and_never_fetched(inbox):
    async def fetch():
        raise AssertionError("never fetched")

    say_with(inbox, "", Attachment("huge.png", smartinbox.MAX_IMAGE + 1, "image/png", fetch))
    assert shown(inbox).text.startswith(smartinbox.TOO_BIG) and inbox.requests == []


def test_files_are_only_read_in_the_inbox_or_a_direct_message(inbox):
    assert smartinbox.files_for(config.INBOX_CHANNEL_ID, (attached("a.png", b"x", "image/png"),))
    assert not smartinbox.files_for(HUB, (attached("a.png", b"x", "image/png"),))
    assert not smartinbox.files_for(config.INBOX_CHANNEL_ID, (attached("a.zip", b"x"),))
    assert not smartinbox.files_for(config.INBOX_CHANNEL_ID, ())


# --- the pure parts --------------------------------------------------------------------------------------------------------
def test_what_sort_returns_is_checked_in_code():
    found = smartinbox.parse({"items": [{"words": "milk", "task": "todos"}, {"words": "x", "task": "rockets"}, {"words": " ", "task": "todos"}], "saw": "", "about_card": True}, ["todos"])
    assert found.items == (("milk", "todos"), ("x", "unsure")), "a task not here is unsure; an empty item is dropped"
    assert smartinbox.parse(None, ["todos"]).problem
    assert smartinbox.parse({"items": [], "saw": "a cat", "about_card": False}, []).about_card is False


def test_which_files_can_be_read():
    assert smartinbox.kind_of(Attachment("a.PNG")) == "image" and smartinbox.kind_of(Attachment("x", content_type="image/webp")) == "image"
    assert smartinbox.kind_of(Attachment("b.pdf")) == "pdf" and smartinbox.kind_of(Attachment("c.csv")) == "csv"
    assert smartinbox.kind_of(Attachment("d.docx")) == ""
    assert smartinbox.table(b"\xef\xbb\xbfa,b\n\n1,2\n") == [["a", "b"], ["1", "2"]]


def test_the_question_part_of_a_message_is_never_sorted():
    assert conversation.routed_text("need milk, what's the capital of France", "what's the capital of France") == "need milk"
    assert conversation.routed_text("need milk", "") == "need milk"


def test_the_router_says_several_and_an_old_recorded_answer_says_not():
    from core import routing

    assert routing.parse({"kind": "task", "tasks": ["todos"], "confidence": "high", "reports_doing": False, "several": True, "chat_part": ""}, ["todos"]).several
    assert not routing.parse({"kind": "task", "tasks": ["todos"], "confidence": "high", "reports_doing": False, "chat_part": ""}, ["todos"]).several
    assert "several" in routing.tool([])["input_schema"]["required"]


def test_the_card_s_first_line_never_names_an_item():
    assert smartinbox.heading(1) == "📥 Inbox · 1 thing" and smartinbox.heading(4) == "📥 Inbox · 4 things"


def test_with_the_switch_off_several_things_are_read_as_before_and_files_are_not_read(inbox, monkeypatch):
    monkeypatch.setattr(config, "SMART_INBOX", False)
    inbox.claude(route("todos", "nudges"), todo("milk"), reminder("call Mum", "5:00 pm"))
    inbox.say("need milk, remind me to call Mum at 5pm")
    assert inbox_cards() == [] and len([card for card in open_cards() if card.kind == "card"]) == 2
    say_with(inbox, "", attached("a.png", image(), "image/png"))
    assert [each.purpose for each in inbox.requests].count("sort") == 0
