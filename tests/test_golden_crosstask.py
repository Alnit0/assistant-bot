"""The cross-task golden conversations (15 Oct): a message that could fit more than one task, end to end.

Each fixture of evals/fixtures/crosstask.json (x1 to x44) is replayed by tests/test_routing.py as
Claude really answered it. These hold the conversations whose outcome is the bot's own code's to
decide, once Claude has read the message: "done" straight after a reminder went off, "undo that"
after a to-do was ticked off, a question about the day straight after a task answered (it never
sticks), and the rest of today by part ("what's on tonight?", "what's next?"). Claude's part is
the recorded answer; everything else is the bot's own code against a temporary database.
"""
import json
from datetime import time
from pathlib import Path

import pytest

from core import actions, clock, config, database, hub, llm, scheduler
from core import day as days
from core.actions import Request
from tasks.pills import checklist
from tests.test_conversation import route, run, world  # noqa: F401
from tests.test_golden import EXTRACTED as GOLDEN_EXTRACTED
from tests.test_golden import bot, press  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "crosstask.json").read_text(encoding="utf-8"))
ROUTED = {entry["golden"]: ("route", entry["recorded"]) for entry in FIXTURES["router"]}
EXTRACTED = {(entry["golden"], entry["task"]): tuple(entry["recorded"]) for entry in FIXTURES["extraction"]}
HUB = 555


@pytest.fixture
def hub_day(bot, monkeypatch, make_db, dev_clock):  # noqa: F811
    """The bot with every hub task on (to-dos, reminders, personal routines, the briefing answering
    questions about the day), at noon, the hub being channel 555."""
    from tasks import briefing, habits, nudges, todos
    from tasks.habits import store as habits_store
    from tasks.nudges import plain as nudges_plain
    from tasks.nudges import store as nudges_store
    from tasks.pills import task as pills_task
    from tasks.timers import task as timers_task
    from tasks.todos import plain as todos_plain
    from tasks.todos import store as todos_store

    make_db({"todos": todos_store.MIGRATIONS, "nudges": nudges_store.MIGRATIONS, "habits": habits_store.MIGRATIONS})
    for name in ("BRIEFING_ENABLED", "DAY_QUESTIONS", "DAY_PROGRESS", "TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED"):
        monkeypatch.setattr(config, name, True)
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(nudges_plain, "changed", lambda user_id: None)
    monkeypatch.setattr(todos_plain, "changed", lambda user_id: None, raising=False)
    monkeypatch.setattr(scheduler, "_standing", {})
    actions.set_catalogue([*pills_task.entries(), *timers_task.entries(), *briefing.task.entries(), *todos.task.entries(), *nudges.task.entries(), *habits.task.entries()])
    for kind, handler in nudges.task.job_handlers().items():
        scheduler.register_handler("nudges", kind, handler)
    nudges_plain.register()
    return bot


def _said(bot):
    return bot.sent[-1][1].text


def _asked(bot, before):
    return [(asked.purpose, asked.task) for asked in bot.requests[before:]]


def _reminder(bot, text, at):
    from tasks.nudges import plain

    request = Request(bot.owner, 100, "said")
    proposal = run(plain.add_card(request, {"text": text, "time": at}, frozenset()))
    run(plain.add_save(request, proposal.data))


def _todo(bot, text, today=True):
    from tasks.todos import store

    run(database.run(store.db_add, bot.owner.id, text, days.today() if today else None, days.today(), clock.now()))


def _pill(bot, name, at):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": name, "per_day": 1, "times": [at]}], "guessed": [], "not_included": []}))
    bot.say(f"add {name} to my pills at {at}")
    press(bot)


def test_x18_done_straight_after_a_reminder_went_off_ticks_that_one_off_with_no_router(hub_day, dev_clock):
    from tasks.nudges import store

    bot = hub_day
    _reminder(bot, "call the bank", "12:30 pm")
    dev_clock.advance_to(days.at(days.today(), time(12, 30, 5)))
    run(scheduler.run_all_due())
    assert llm.answering_task(HUB) == "nudges", "the reminder that just went off is the bot's latest word in the hub"
    before = len(bot.requests)
    bot.claude(EXTRACTED[("x18", "nudges")])
    bot.say("done", straight_after=True, channel_id=HUB)
    assert _said(bot) == "✅ Call the bank · done"
    assert _asked(bot, before) == [("extraction", "nudges")], "the reminder's task reads it first: no router"
    assert run(database.run(store.db_open, bot.owner.id)) == []


def _milk_bought(bot):
    _todo(bot, "Buy milk")
    bot.claude(route("todos"), ("todo_done", {"todos": [{"todo": "milk"}], "guessed": [], "not_included": []}))
    bot.say("bought the milk")
    assert _said(bot).startswith("✅ **Buy milk** · done"), _said(bot)


def test_x21_undo_that_straight_after_a_to_do_was_ticked_off_puts_it_back(hub_day):
    from tasks.todos import store

    bot = hub_day
    _milk_bought(bot)
    before = len(bot.requests)
    bot.claude(EXTRACTED[("x21", "todos")])
    bot.say("undo that", straight_after=True)
    assert "Buy milk" in _said(bot) and "not done" in _said(bot), _said(bot)
    assert _asked(bot, before) == [("extraction", "todos")]
    assert [each.text for each in run(store.every(bot.owner.id)) if not each.is_done] == ["Buy milk"]


def test_x30_what_s_left_today_straight_after_a_to_do_is_the_day_s_own_answer_never_the_list(hub_day):
    bot = hub_day
    _milk_bought(bot)
    _todo(bot, "Call the plumber")
    before = len(bot.requests)
    # The to-dos task read it first, as a question of its own; a question never sticks: the router is asked
    bot.claude(EXTRACTED[("x30", "todos")], ROUTED["x30"], GOLDEN_EXTRACTED["21"])
    bot.say("what's left today?", straight_after=True)
    assert _said(bot).startswith("☀️ **Left today** · ●○ 1/2") and "📝 Call the plumber" in _said(bot), _said(bot)
    assert _asked(bot, before) == [("extraction", "todos"), ("router", ""), ("extraction", "briefing")]
    assert bot.chats == []


def _evening(bot):
    """Pill C at 9 pm, a reminder at 5 pm and a to-do with no time, at noon."""
    _pill(bot, "Pill C", "9:00 pm")
    run(checklist.post(bot.owner.id, 100))
    _reminder(bot, "put the bins out", "5:00 pm")
    _todo(bot, "Book a haircut")


def test_x31_what_s_on_tonight_is_tonight_across_every_task_in_time_order(hub_day):
    bot = hub_day
    _evening(bot)
    bot.claude(ROUTED["x31"], EXTRACTED[("x31", "briefing")])
    bot.say("what's on tonight?")
    assert _said(bot).splitlines() == [
        "☀️ **Left tonight** · ○○ 0/2", "⏰ Put the bins out `5:00 pm`", "💊 Pill C `9:00 pm`", "-# and 1 with no time, any time today",
    ], _said(bot)
    assert bot.chats == [], "never from chat"


def test_x37_what_s_next_is_the_first_thing_still_to_come(hub_day):
    bot = hub_day
    _evening(bot)
    bot.claude(ROUTED["x37"], EXTRACTED[("x37", "briefing")])
    bot.say("what's next?")
    assert _said(bot).splitlines() == ["☀️ **Next** · ○○ 0/2", "⏰ Put the bins out `5:00 pm`", "-# then 2 more today"], _said(bot)


def test_every_cross_task_conversation_is_recorded_and_there_are_at_least_40():
    goldens = {entry["golden"] for kind in ("router", "extraction") for entry in FIXTURES[kind]}
    assert len(goldens) >= 40
    missing = [entry["message"] for kind in ("router", "extraction") for entry in FIXTURES[kind] if entry.get("recorded") is None]
    assert missing == [], f"not recorded: {missing}"


def test_the_self_test_reads_every_recorded_answer_back_right_with_no_request():
    from selftest import understanding
    from tests.test_routing import ALL

    ran, bad = understanding.judged(ALL)
    assert ran >= 55 and bad == [], bad
    step = understanding.step(ran, bad)
    assert step["status"] == "pass" and step["key"] == "u.01" and step["claude"] == "recorded answer"


def test_a_wrong_answer_or_a_replay_that_breaks_is_a_failed_step_that_says_which():
    from selftest import understanding

    failed = understanding.step(58, ["x9: gym at 6 (expected ['nudges'], got ['todos'])"])
    assert failed["status"] == "fail" and failed["saw"] == "x9: gym at 6 (expected ['nudges'], got ['todos'])"
    assert understanding.step(0, [])["status"] == "fail", "nothing read back is not a pass"
    assert understanding.step(0, [], "the replay could not be run: OSError")["status"] == "error"
