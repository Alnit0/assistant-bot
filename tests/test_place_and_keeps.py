"""Alex's answers of 15 Oct, late: each task says where it comes; a message only about the day is kept by the
diary (question 85); "remind me ..." is a reminder even when it names the diary.

The order: pills, reminders, personal routines, calendar, diary, to-dos (the gym after routines, later), with
the Today card where it was, under the pills checklist. Said by each task (`Task.place`), no list in the core.
"""
from datetime import date

from core import actions, config, hub, routing
from core.actions import Summary
from core.summaries import Section
from tasks import registry
from tasks.briefing import rules as briefing

ORDER = ["pills", "nudges", "habits", "calendar", "diary", "todos"]


def _loaded(monkeypatch):
    for name in ("TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED", "CALENDAR_ENABLED", "DIARY_ENABLED", "BRIEFING_ENABLED", "WEATHER_ENABLED"):
        monkeypatch.setattr(config, name, True)
    registry.load()


def test_each_task_says_where_it_comes_and_the_order_is_alexs(monkeypatch):
    try:
        _loaded(monkeypatch)
        placed = [entry.name for entry in actions.in_place() if entry.name in ORDER]
        assert placed == ORDER
        assert all(entry.place for entry in actions.catalogue() if entry.name in ORDER), "each says its own place"
    finally:
        monkeypatch.undo()
        registry.load()


def test_a_task_with_no_place_keeps_its_spot():
    given = [("builtin", 0), ("todos", 70), ("bugs", 0), ("pills", 10), ("nudges", 20)]
    assert [name for name, _ in actions.placed(given, lambda each: each[1])] == ["builtin", "pills", "bugs", "nudges", "todos"]


def test_the_hub_cards_follow_the_same_order():
    from tasks import habits, nudges, today, todos

    assert hub.CARDS_ORDER < today.ORDER < nudges.ORDER < habits.ORDER < todos.ORDER
    assert [today.PLACE, nudges.PLACE, habits.PLACE, todos.PLACE] == [15, 20, 30, 70]


def test_help_lists_the_tasks_in_the_same_order(monkeypatch):
    try:
        _loaded(monkeypatch)
        listed = [each.task.name for each in registry.catalogue() if each.task.name in ORDER]
        assert listed == [name for name in ORDER if name in listed] and len(listed) >= 4
    finally:
        monkeypatch.undo()
        registry.load()


def test_the_briefing_overview_follows_the_order_not_the_load_order(monkeypatch):
    try:
        _loaded(monkeypatch)
        given = [Section(name, "•", name.capitalize(), Summary(overview=f"{name} line")) for name in reversed(ORDER)]
        box = briefing._overview_box(given)
        text = str(box)
        assert [text.index(f"{name} line") for name in ORDER] == sorted(text.index(f"{name} line") for name in ORDER)
    finally:
        monkeypatch.undo()
        registry.load()


# --- question 85: a message only about the day goes to the diary ------------------------------------------------
def _entry(name, **how):
    return actions.Entry(name, "•", f"Only for {name}.", ("a", "b"), (), on_repeat="allow_another", **how)


def test_the_router_is_told_of_kept_statements_only_when_a_task_keeps_them():
    plain_entries = [_entry("todos"), _entry("nudges")]
    (block,) = routing.system_blocks(plain_entries)
    assert routing.KEEPS not in block["text"], "with no task keeping, the prompt is as it was"
    keeping = [*plain_entries, _entry("diary", keeps="how the user's day went")]
    (block,) = routing.system_blocks(keeping)
    assert routing.KEEPS in block["text"] and "Keeps: how the user's day went" in block["text"]
    assert routing.system_blocks(keeping) == routing.system_blocks(keeping), "fixed text, so it can be cached"


def test_the_diary_keeps_a_feeling():
    from tasks.diary import plain

    assert plain.KEEPS and "I'm tired" in plain.KEEPS


# --- "remind me ..." is a reminder, even naming the diary ------------------------------------------------------
def test_remind_me_outranks_a_named_destination():
    entries = [_entry("nudges", leads=("remind me",)), _entry("diary"), _entry("pills")]
    assert routing.stated("remind me to write in my diary at 9pm", entries) == ["nudges"]
    assert routing.stated("Please remind me to add to my diary", entries) == ["nudges"]
    assert routing.stated("add this to my diary", entries) == ["diary"], "a destination named still decides"


def test_remind_me_with_no_destination_is_left_to_the_router():
    """A pill's time is the pills' ("remind me to take my zinc at 8pm"): no reminder ever names a pill on the lock screen."""
    entries = [_entry("nudges", leads=("remind me",)), _entry("pills")]
    assert routing.stated("remind me to take my zinc at 8pm", entries) == []


def test_reminders_declare_the_lead():
    from tasks.nudges import NudgesTask

    assert NudgesTask.leads == ("remind me",)


def test_the_hint_says_a_thing_done_is_a_report():
    line = routing.hint_line([("milk", "todos")])
    assert "reports_doing true" in line and "never a remark" in line and "Buy milk" not in line
