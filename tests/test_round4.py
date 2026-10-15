"""Round 4 of the design (docs/DESIGN-LOG.md): the relevance rule on every card, and one Taken button a dose (two ways it can work)."""
from datetime import date, datetime, time, timedelta

import pytest

from core import cards, clock, config, database, design, occurrences
from core import day as days
from core.errors import UserError
from tasks.pills import checklist, plain, reminders, sheet, store
from tests.test_design import press_sheet, sheet_of, topic
from tests.test_pills_reminders import EVENING, PILL_A, add, at, log, miss, prompts, run, states, world  # noqa: F401


@pytest.fixture
def r4(monkeypatch):
    monkeypatch.setattr(config, "CARDS_V2", True)
    monkeypatch.setattr(config, "DESIGN_ROUND", 4)


def lines_of(pieces):
    """Every line of a layout's text, and every button's label."""
    return [line for text in design.texts(pieces) for line in text.splitlines()], [button.label for button in design.buttons(pieces)]


# --- the relevance rule (pure) -------------------------------------------------------------------------------
def test_the_relevance_rule_shows_now_in_full_the_next_in_full_and_the_rest_small():
    noon = days.at(date(2026, 10, 21), time(12, 0))
    things = [
        design.Thing("A due", design.NOW, row=("button",)),
        design.Thing("B at 5", design.COMING, noon + timedelta(hours=5), "5:00 pm"),
        design.Thing("C at 2", design.COMING, noon + timedelta(hours=2), "2:00 pm"),
        design.Thing("D at 8", design.COMING, noon + timedelta(hours=8), "8:00 pm"),
        design.Thing("E", design.FINISHED), design.Thing("F", design.FINISHED),
        design.Thing("G", design.GONE_BY, noon - timedelta(hours=3), "9:00 am"),
        design.Thing("H", design.PAUSED),
    ]
    shown = design.relevant(things)
    assert [entry.text for entry in shown.entries] == ["A due", "C at 2"], "what can be done now, then the next coming up"
    assert shown.entries[0].row == ("button",) and shown.entries[1].row == (), "a button only on what can be done now"
    assert shown.small == ("later today · 5:00 pm, 8:00 pm", "✅ 2 done", "✕ 1 missed · 9:00 am")
    assert (shown.done, shown.missed, shown.later, shown.hidden) == (2, 1, 2, 1), "paused: not on the card at all"
    assert design.relevant([]).entries == () and design.relevant([]).small == ()


# --- the pills card in round 4 ---------------------------------------------------------------------------------
def test_round_4_morning_with_nothing_taken_the_due_dose_in_full_with_one_button(world, r4):
    add(world, PILL_A, EVENING, {"name": "Any"})
    at(world, 8, 5)
    pieces = sheet_of(world)
    lines, buttons = lines_of(pieces)
    assert lines[0] == "### 💊 Pills ○○○○○ 0/5"
    assert "**Pill A** · dose 1 of 3 · due **8:00 am**" in lines and "**Any** · any time" in lines
    assert buttons == ["Taken", "Taken"], "one button a dose that can be taken now: no Taken at…, no Skip"
    assert "**Pill A** · dose 2 of 3 · **11:30 am**" in lines, "the next one coming up, in full, no button, its exact time only"
    assert "-# later today · 3:00 pm, 8:00 pm" in lines, "the rest of the day: one small line of times"


def test_round_4_midday_two_taken_one_missed_one_paused_one_due_and_two_later(world, r4):
    add(world, PILL_A, EVENING, {"name": "Done"}, {"name": "Early", "times": ["9:00 am"]}, {"name": "Off"}, {"name": "Late", "times": ["9:00 pm"]})
    run(plain.pause_save(world.request(), run(plain.pause_card(world.request(), {"pills": [{"pill": "off"}]}, frozenset())).data))
    at(world, 8, 0)
    log(world, {"pill": "pill a", "did": "taken"}, {"pill": "done", "did": "taken"})
    at(world, 12, 0)
    miss(world, "Early", 1)
    pieces = sheet_of(world)
    lines, buttons = lines_of(pieces)
    assert "**Pill A** · dose 2 of 3 · due **11:30 am**" in lines and buttons == ["Taken"], "the one dose due now"
    assert any(line.startswith("**Pill A** · dose 3 of 3 · **3:00 pm**") for line in lines), "the next, in full"
    assert "-# later today · 8:00 pm, 9:00 pm" in lines and "-# ✅ 2 done" in lines and "-# ✕ 1 missed · 9:00 am" in lines
    assert not any("Off" in line for line in lines), "paused: not on the card"
    assert not any("Early" in line for line in lines), "missed: a count and its time, no name"


def test_round_4_all_done_is_one_small_line_and_green(world, r4):
    add(world, EVENING)
    at(world, 20, 5)
    log(world, {"pill": "evening pill", "did": "taken"})
    status, title, items = topic(sheet_of(world))
    assert status == design.DONE and title == "### 💊 Pills ● 1/1" and items == [(["-# ✅ 1 done"], [])]


def test_round_4_has_fewer_lines_and_buttons_than_round_3_for_the_same_day(world, monkeypatch):
    add(world, PILL_A, EVENING, {"name": "Any"})
    at(world, 8, 5)
    monkeypatch.setattr(config, "CARDS_V2", True)
    three = lines_of(sheet_of(world))
    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    four = lines_of(sheet_of(world))
    assert len(four[1]) < len(three[1]) and len(four[0]) <= len(three[0])


# --- one Taken button, at once (question 67: variant 2) ------------------------------------------------------
def test_taken_logs_at_once_and_the_line_it_leaves_corrects_by_a_reply(world, r4):
    sheet.register()
    add(world, EVENING)
    at(world, 20, 4)
    (button,) = design.buttons(sheet_of(world))
    assert button.action == sheet.S_TAKEN and button.style == cards.SUCCESS
    sent = len(world.sent)
    _, said = press_sheet(world, sheet.S_TAKEN, "Evening pill")
    line = world.sent[sent]
    assert line.card.text == "✅ **Evening pill** · taken 8:04 pm · reply to this with a time to put it right" and line.silent
    assert run(database.run(store.db_line, line.id)), "recorded as about that dose: a reply means it"
    corrected = log(world, {"pill": "@that", "did": "taken", "at": "8:00 pm"}, replied_to=line.id)
    assert "8:04 pm → 8:00 pm" in corrected, corrected


def test_the_pop_up_variant_is_gone():
    assert not hasattr(sheet, "S_ASK") and not hasattr(sheet, "on_ask") and not hasattr(config, "TAKEN_BUTTON")


# --- Skip by words, with undo ---------------------------------------------------------------------------------
def test_skip_is_said_in_words_and_undo_that_puts_it_back(world, r4):
    add(world, EVENING)
    at(world, 19, 0)
    said = log(world, {"pill": "evening pill", "did": "skipped"})
    assert "skipped" in said and states(world)[("Evening pill", 1)] == occurrences.SKIPPED
    undone = log(world, {"pill": "@that", "did": "not_taken"})
    assert states(world)[("Evening pill", 1)] == occurrences.PENDING and "not skipped after all" in undone, undone


# --- the reminder: one Taken and Snooze -------------------------------------------------------------------------
def test_round_4_a_reminder_has_one_taken_and_snooze(world, r4):
    add(world, PILL_A)
    at(world, 8, 0)
    drawn = world.edited[-1][1]
    assert [(button.label, button.action) for button in design.buttons(drawn.layout)] == [("Taken", reminders.P_TAKEN), ("Snooze 15m", reminders.P_SNOOZE)]


def test_round_4_taken_on_a_reminder_leaves_a_line_a_reply_corrects(world, r4):
    from tests.test_pills_reminders import press

    add(world, PILL_A)
    at(world, 8, 10)
    sent = len(world.sent)
    pressed, said = press(world, reminders.P_TAKEN)
    line = world.sent[sent]
    assert pressed.removed and line.card.text == f"{said} · reply to this with a time to put it right"
    corrected = log(world, {"pill": "@that", "did": "taken", "at": "8:00 am"}, replied_to=line.id)
    assert "8:10 am → 8:00 am" in corrected, corrected


# --- the to-dos and reminders cards in round 4 ------------------------------------------------------------------
TODAY = date(2026, 10, 21)


def todo_made(number, text, day=None, done=None):
    from tasks.todos import rules as todo

    return todo.Todo(number, 1, text, day, TODAY - timedelta(days=3), done, TODAY if done else None)


def test_round_4_to_dos_the_first_three_in_full_the_rest_one_line_and_one_done_dropdown(monkeypatch):
    from tasks.todos import rules as todo

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    found = todo.on([
        todo_made(1, "Pay the bill", TODAY - timedelta(days=1)),
        todo_made(2, "Any day one"),
        *(todo_made(3 + n, f"Thing {n}", TODAY) for n in range(5)),
        todo_made(8, "Next week one", TODAY + timedelta(days=7)),
        todo_made(9, "Done one", TODAY, days.at(TODAY, time(9, 0))), todo_made(10, "Done two", None, days.at(TODAY, time(10, 0))),
    ], TODAY)
    pieces = todo.layout(found, TODAY)
    lines, buttons = lines_of(pieces)
    assert lines[0] == "### 📝 To-dos ●●○○○○○○○ 2/9" and buttons == [], "no Done button under each"
    shown = [line for line in lines if line.startswith("**")]
    assert shown == ["**Pay the bill**", "**Thing 0**", "**Thing 1**"], "overdue first, then today's, then any day's: three"
    assert "-# from yesterday" in lines and "-# +4 more" in lines and "-# ✅ 2 done" in lines
    assert not any("Done one" in line for line in lines), "done: a count, no names"
    (menu,) = design.menus(pieces)
    assert menu.action == todo.PICKED_ACTION and menu.placeholder == "✅ Done: pick one"
    assert [option.label for option in menu.options] == ["Pay the bill", *(f"Thing {n}" for n in range(5)), "Any day one", "Next week one"], "every open one, the most pressing first, a later day's too"
    assert menu.options[0].description == "from yesterday" and menu.options[-1].description == "Wed 28 Oct"
    cards.check_layout(pieces)


def test_round_4_to_dos_more_than_a_dropdown_holds_the_most_pressing_and_a_note_to_use_words(monkeypatch):
    from tasks.todos import rules as todo

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    found = todo.on([todo_made(1 + n, f"Thing {n}", TODAY) for n in range(30)], TODAY)
    pieces = todo.layout(found, TODAY)
    (menu,) = design.menus(pieces)
    assert len(menu.options) == 25 and menu.options[0].label == "Thing 0" and menu.options[-1].label == "Thing 24"
    lines, _ = lines_of(pieces)
    assert "-# +27 more" in lines and "-# the list holds 25: say “done” and its words for the others" in lines
    cards.check_layout(pieces)


def test_round_4_to_dos_all_done_has_no_dropdown(monkeypatch):
    from tasks.todos import rules as todo

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    found = todo.on([todo_made(1, "Done one", TODAY, days.at(TODAY, time(9, 0)))], TODAY)
    assert design.menus(todo.layout(found, TODAY)) == []


def test_the_list_rule_is_one_for_every_list_card():
    shown = design.listed(range(10), in_menu=range(40))
    assert shown.shown == (0, 1, 2) and shown.more == 7 and len(shown.menu) == 25 and shown.left_out == 15
    assert design.more_line(0) == "" and design.more_line(4) == "+4 more"
    assert design.listed([1]).more == 0 and design.listed([1]).menu == (1,)


def test_round_4_reminders_card_the_next_in_full_and_the_rest_small(monkeypatch):
    from tasks.nudges import rules as nudge

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    today = date(2026, 10, 21)
    now = days.at(today, time(9, 0))
    set_up = [nudge.Nudge(1, 1, "Call Mum", time(17, 0), nudge.ONCE, today), nudge.Nudge(2, 1, "Stretch", time(11, 0), nudge.DAILY), nudge.Nudge(3, 1, "Bins", time(19, 30), nudge.DAILY)]
    lines, buttons = lines_of(nudge.card_layout(nudge.coming(set_up, now), now))
    assert lines[1] == "**Stretch**" and lines[2].startswith("**11:00 am** · <t:") and "-# later today · 5:00 pm, 7:30 pm" in lines and buttons == []


# --- #commands -------------------------------------------------------------------------------------------------
def test_round_4_commands_says_one_taken_and_skip_in_words(monkeypatch):
    from tasks.pills import task as pills_task

    monkeypatch.setattr(config, "CARDS_V2", True)
    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    said = {note.label: note.description for note in pills_task.buttons()}
    assert set(said) == {"✅ Taken", "⏰ Snooze 15m"} and "skip Pill A" in said["✅ Taken"]
    assert "reply to the line it leaves with a time" in said["✅ Taken"]
