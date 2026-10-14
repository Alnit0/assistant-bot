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
    assert any(line.startswith("**Pill A** · dose 2 of 3 · **11:30 am** · <t:") for line in lines), "the next one coming up, in full, no button"
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


# --- one Taken button: the two ways it works --------------------------------------------------------------------
def test_variant_1_taken_opens_a_pop_up_with_now_filled_in(world, r4, monkeypatch):
    monkeypatch.setattr(config, "TAKEN_BUTTON", "ask")
    sheet.register()
    add(world, EVENING)
    at(world, 20, 4)
    (button,) = design.buttons(sheet_of(world))
    assert button.action == sheet.S_ASK and button.style == cards.SUCCESS
    pressed, said = press_sheet(world, sheet.S_ASK, "Evening pill")
    assert said == "asked for the time, with now filled in" and pressed.form.fields[0].value == "8:04 pm"
    pressed, said = press_sheet(world, sheet.S_ASK, "Evening pill", fields={"at": "8:04 pm"})
    assert said == "✅ **Evening pill** · taken 8:04 pm", "sent as it is: taken now"


@pytest.mark.parametrize("typed,wanted", [("8", "8:00 pm"), ("8:01", "8:01 pm"), ("8pm", "8:00 pm"), ("7:45 pm", "7:45 pm")])
def test_variant_1_an_edited_time_is_read_as_a_time_said_in_words(world, r4, monkeypatch, typed, wanted):
    monkeypatch.setattr(config, "TAKEN_BUTTON", "ask")
    sheet.register()
    add(world, EVENING)
    at(world, 20, 4)
    _, said = press_sheet(world, sheet.S_ASK, "Evening pill", fields={"at": typed})
    assert said == f"✅ **Evening pill** · taken {wanted}"


def test_variant_1_a_time_in_the_future_is_refused_and_nothing_is_logged(world, r4, monkeypatch):
    monkeypatch.setattr(config, "TAKEN_BUTTON", "ask")
    sheet.register()
    add(world, EVENING)
    at(world, 20, 4)
    with pytest.raises(UserError):
        press_sheet(world, sheet.S_ASK, "Evening pill", fields={"at": "9:30 pm"})
    assert states(world)[("Evening pill", 1)] == occurrences.PENDING


def test_variant_2_taken_logs_at_once_and_the_line_it_leaves_corrects_by_a_reply(world, r4, monkeypatch):
    monkeypatch.setattr(config, "TAKEN_BUTTON", "now")
    sheet.register()
    add(world, EVENING)
    at(world, 20, 4)
    (button,) = design.buttons(sheet_of(world))
    assert button.action == sheet.S_TAKEN
    sent = len(world.sent)
    _, said = press_sheet(world, sheet.S_TAKEN, "Evening pill")
    line = world.sent[sent]
    assert line.card.text == "✅ **Evening pill** · taken 8:04 pm · reply to this with a time to put it right" and line.silent
    assert run(database.run(store.db_line, line.id)), "recorded as about that dose: a reply means it"
    corrected = log(world, {"pill": "@that", "did": "taken", "at": "8:00 pm"}, replied_to=line.id)
    assert "8:04 pm → 8:00 pm" in corrected, corrected


# --- Skip by words, with undo ---------------------------------------------------------------------------------
def test_skip_is_said_in_words_and_undo_that_puts_it_back(world, r4):
    add(world, EVENING)
    at(world, 19, 0)
    said = log(world, {"pill": "evening pill", "did": "skipped"})
    assert "skipped" in said and states(world)[("Evening pill", 1)] == occurrences.SKIPPED
    undone = log(world, {"pill": "@that", "did": "not_taken"})
    assert states(world)[("Evening pill", 1)] == occurrences.PENDING and "not skipped after all" in undone, undone


# --- the reminder: one Taken and Snooze -------------------------------------------------------------------------
@pytest.mark.parametrize("way,action", [("ask", reminders.P_AT), ("now", reminders.P_TAKEN)])
def test_round_4_a_reminder_has_one_taken_and_snooze(world, r4, monkeypatch, way, action):
    monkeypatch.setattr(config, "TAKEN_BUTTON", way)
    add(world, PILL_A)
    at(world, 8, 0)
    drawn = world.edited[-1][1]
    assert [(button.label, button.action) for button in design.buttons(drawn.layout)] == [("Taken", action), ("Snooze 15m", reminders.P_SNOOZE)]


# --- the to-dos and reminders cards in round 4 ------------------------------------------------------------------
def test_round_4_to_dos_two_done_one_overdue_and_six_for_today(monkeypatch):
    from tasks.todos import rules as todo

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    today = date(2026, 10, 21)
    made = lambda number, text, day=None, done=None: todo.Todo(number, 1, text, day, today - timedelta(days=3), done, today if done else None)  # noqa: E731
    found = todo.on([
        made(1, "Pay the bill", today - timedelta(days=1)),
        *(made(2 + n, f"Thing {n}", today) for n in range(6)),
        made(9, "Done one", today, days.at(today, time(9, 0))), made(10, "Done two", None, days.at(today, time(10, 0))),
    ], today)
    lines, buttons = lines_of(todo.layout(found, today))
    assert lines[0] == "### 📝 To-dos ●●○○○○○○○ 2/9" and buttons == ["Done"] * 7, "every open one for today can be done now"
    assert lines[1:3] == ["**Pay the bill**", "-# from yesterday"] and "-# ✅ 2 done" in lines
    assert not any("Done one" in line for line in lines), "done: a count, no names"


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
    assert set(said) == {"✅ Taken", "⏰ Snooze 15m"} and "pop-up with the time filled in" in said["✅ Taken"] and "skip Pill A" in said["✅ Taken"]
    monkeypatch.setattr(config, "TAKEN_BUTTON", "now")
    assert "reply to the line it leaves with a time" in {note.label: note.description for note in pills_task.buttons()}["✅ Taken"]
