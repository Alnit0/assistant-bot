"""Logging at the gym on a phone (30 Oct): a box a set with its own note, read by Python; more sets than one form
holds in a second form from the same button; Cancel as an undo of Start; one card edited in place, its buttons
never moving and nothing posted under it; the table of what was logged within a phone's width; last time's
numbers in each box's label and on the card, every box empty. Made-up data only (tests/gym_files.py)."""
from types import SimpleNamespace

import pytest

from core import cards, database, design
from core.errors import UserError
from tasks.gym import plain, rules, session, store
from tasks.gym.rules import DoneSet, Exercise, PlannedSet
from tests.test_gym import GYM, imported, run, world  # noqa: F401


# --- a set's box, read by Python ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("typed, read", [
    ("60 x 8", (60.0, 8, False, "")),
    ("60x8", (60.0, 8, False, "")),
    ("60 X 8", (60.0, 8, False, "")),
    ("60 × 8", (60.0, 8, False, "")),
    ("60*8", (60.0, 8, False, "")),
    ("60kg x 8", (60.0, 8, False, "")),
    ("60 kg × 8 felt heavy", (60.0, 8, False, "felt heavy")),
    ("60 x 8, felt heavy.", (60.0, 8, False, "felt heavy")),
    ("22.5 x 10 reps", (22.5, 10, False, "")),
    ("22,5x10", (22.5, 10, False, "")),
    ("14s for 10", (14.0, 10, True, "")),
])
def test_a_box_is_weight_and_reps_and_what_follows_is_its_note(typed, read):
    said = rules.typed_set(typed, reps_alone=False)
    assert said.readable and (said.weight, said.reps, said.per_hand, said.note) == read


@pytest.mark.parametrize("typed", ["sixty by eight", "x 8", "60 x 0", "60 x", "60 kg", "8"])
def test_a_box_that_cannot_be_read_is_kept_whole_and_no_number_is_made_up(typed):
    said = rules.typed_set(typed, reps_alone=False)
    assert not said.readable and said.weight is None and said.reps is None and said.note == typed


def test_reps_alone_only_for_a_bodyweight_move():
    assert rules.typed_set("12", reps_alone=True) == rules.Typed(None, 12, False, "")
    assert rules.typed_set("12 last two slow", reps_alone=True) == rules.Typed(None, 12, False, "last two slow")
    assert rules.typed_set("12 x 8", reps_alone=True).weight == 12.0, "a weight said is still a weight"
    assert not rules.typed_set("8.5", reps_alone=True).readable
    assert session.reps_alone(Exercise("Pull-up", (), rules.BODYWEIGHT), [])
    assert not session.reps_alone(Exercise("Squat", (), rules.BARBELL), [])
    assert session.reps_alone(Exercise("Hanging thing", ()), []), "a kind not known, never logged with a weight"
    assert not session.reps_alone(Exercise("Hanging thing", ()), [DoneSet("Hanging thing", reps=8, weight=10.0)])


def test_an_empty_box_is_a_set_not_done_and_a_set_note_is_the_set_s():
    exercise = Exercise("Test press", tuple(PlannedSet(rules.WORKING, "", "", 8, 12) for _ in range(3)))
    found, look = session.read_form({"set0": "60 x 8 felt heavy", "set1": "", "set2": "sixty", "note": "a note"}, exercise)
    assert [(each.position, each.weight, each.reps, each.note) for each in found] == [(0, 60.0, 8, "felt heavy"), (2, None, None, "sixty")]
    assert look == [3]


# --- the table ------------------------------------------------------------------------------------------------------------
def test_the_table_is_a_row_an_exercise_a_column_a_set_within_a_phone_s_width():
    rows = [("Test press", ["60x8", "60x8", "-"]), ("A very long made-up exercise name", ["102.5x10", "102.5x9", "95x12", "-"])]
    lines = rules.table(rows)
    assert all(len(line) <= rules.TABLE_WIDTH for line in lines)
    assert lines[0].split() == ["S1", "S2"], "the header over the first line's columns"
    assert lines[1].split() == ["Test", "press", "60x8", "60x8"] and lines[2].split() == ["-"], "the third set on a line of its own"
    assert lines[3].startswith("A very long ma…") and lines[3].split()[-2:] == ["102.5x10", "102.5x9"], "a long name shortened with an ellipsis"
    assert rules.code_block(lines).startswith("```\n") and rules.code_block(lines).endswith("\n```")


def test_sets_that_do_not_fit_go_on_to_a_line_of_their_own():
    lines = rules.table([("Test row", ["102.5x10"] * 6)])
    assert all(len(line) <= rules.TABLE_WIDTH for line in lines)
    assert len(lines) == 4 and lines[1].startswith("Test row") and lines[2].startswith(" ") and lines[2].index("1") == lines[1].index("1"), "the rest under it, in the same columns"
    assert sum(line.count("102.5x10") for line in lines) == 6


# --- the forms --------------------------------------------------------------------------------------------------------------
def test_up_to_four_sets_one_form_and_more_in_forms_of_five_after_it():
    three = Exercise("Test press", tuple(PlannedSet() for _ in range(3)))
    ten = Exercise("Test press", tuple(PlannedSet() for _ in range(10)))
    assert list(session.form_part(three, 0)) == [0, 1, 2]
    assert [list(session.form_part(ten, start)) for start in (0, 4, 9)] == [[0, 1, 2, 3], [4, 5, 6, 7, 8], [9]]
    assert list(session.form_part(Exercise("Done instead", ()), 0)) == [0, 1, 2, 3], "no planned sets: four boxes"


def test_a_label_holds_last_time_when_it_fits():
    last = {0: DoneSet("x", reps=8, weight=60.0), 1: DoneSet("x")}
    assert session.set_label(0, last) == "Set 1 · last 60 x 8"
    assert session.set_label(1, last) == "Set 2 · last not done"
    assert session.set_label(2, last) == "Set 3"
    assert all(len(session.set_label(0, {0: DoneSet("x", reps=100, weight=weight)})) <= cards.MAX_FORM_TITLE for weight in (1000.25, 5.0))


def five_sets(world):
    """Lower 1 with a made-up exercise of five sets added at its end, started."""
    imported(world)
    plan = run(store.plan(world.owner.id))
    lower = next(each for each in plan if each.name == "Lower 1")
    run(database.run(store.db_add_exercise, world.owner.id, lower.id, len(lower.exercises), Exercise("Test row", tuple(PlannedSet(rules.WORKING, "", "", 8, 12) for _ in range(5)), rules.MACHINE)))
    started = run(session.start(world.owner.id))
    return started, next(each for each in run(session.exercises_of(started)) if each.name == "Test row")


def press_on(world, arg: str, fields=None, message_id=None):
    shown = SimpleNamespace(forms=[], updates=[])

    async def open_form(form):
        shown.forms.append(form)

    async def update(card):
        shown.updates.append(card)

    return SimpleNamespace(arg=arg, fields=fields, values=(), db=database, user=world.owner, channel_id=GYM, message_id=message_id, open_form=open_form, update=update, shown=shown)


def card_now(world):
    return world.edited[-1][1] if world.edited else world.sent[-1].card


def test_five_sets_are_two_forms_from_the_same_button(world):
    started, row = five_sets(world)
    log_arg = next(each.arg for each in design.buttons(card_now(world).layout) if each.label == "Test row")
    first = press_on(world, log_arg)
    run(session.on_log(first))
    (form,) = first.shown.forms
    assert [field.label for field in form.fields] == ["Set 1", "Set 2", "Set 3", "Set 4", "Notes"] and form.title == "Test row · sets 1 to 4"
    assert run(session.on_logged(press_on(world, form.arg, {"set0": "50 x 12", "set1": "50 x 11", "set2": "50 x 10", "set3": "50 x 9", "note": ""}))) == "logged 4 sets"
    shown = "\n".join(design.texts(card_now(world).layout))
    assert "tap it again for sets 5 to 5" in shown, "the card says the rest is still to come"
    button = next(each for each in design.buttons(card_now(world).layout) if each.label == "Test row")
    assert button.emoji == "📝", "not logged in full yet"
    second = press_on(world, button.arg)
    run(session.on_log(second))
    (form,) = second.shown.forms
    assert [field.label for field in form.fields] == ["Set 5"] and form.title == "Test row · sets 5 to 5", "the rest, no Notes again"
    run(session.on_logged(press_on(world, form.arg, {"set4": "50 x 8 grind"})))
    logged = [each for each in run(database.run(store.db_sets, started.id)) if each.exercise == "Test row"]
    assert [(each.position, each.reps, each.note) for each in logged] == [(0, 12, ""), (1, 11, ""), (2, 10, ""), (3, 9, ""), (4, 8, "grind")]
    assert next(each for each in design.buttons(card_now(world).layout) if each.label == "Test row").emoji == "✅"
    assert run(database.run(store.db_session, started.id)).pending == ""


def test_a_note_typed_after_a_set_is_kept_on_that_set_and_shown_under_the_table(world):
    imported(world)
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    form = run(session.form_for(started, squat))
    run(session.on_logged(press_on(world, form.arg, {"set0": "40 x 10", "set1": "82.5 x 6 felt heavy", "note": ""})))
    (_, heavy) = run(database.run(store.db_sets, started.id))
    assert heavy.note == "felt heavy"
    shown = "\n".join(design.texts(card_now(world).layout))
    assert "-# Squat · set 2: felt heavy" in shown and "```" in shown


# --- one card, edited in place: one tap every time ------------------------------------------------------------------------
def test_two_logs_in_a_row_edit_the_one_card_and_its_buttons_never_move(world):
    imported(world)
    started = run(session.start(world.owner.id))
    before = [(each.label, each.action, each.arg) for each in design.buttons(card_now(world).layout)]
    for name, typed in (("Squat", {"set0": "40 x 10", "set1": "82.5 x 6", "note": ""}), ("Romanian deadlift", {"set0": "70 x 9", "note": ""})):
        exercise = next(each for each in run(session.exercises_of(started)) if each.name == name)
        run(session.on_logged(press_on(world, run(session.form_for(started, exercise)).arg, typed)))
        drawn = card_now(world)
        assert not design.problem(drawn.layout)
        after = [(each.label, each.action, each.arg) for each in design.buttons(drawn.layout)]
        assert [each[:2] for each in after] == [each[:2] for each in before], "the same buttons, in the same order"
        assert design.buttons(drawn.layout)[-3:][0].label == "Undo" and not design.buttons(drawn.layout)[-3:][0].disabled
    assert len(world.sent) == 1, "the card only: nothing posted under it"
    assert all(message_id == world.sent[0].id for message_id, _ in world.edited)
    shown = "\n".join(design.texts(card_now(world).layout))
    table = shown.split("```\n")[1].split("\n```")[0].splitlines()
    assert all(len(line) <= rules.TABLE_WIDTH for line in table) and [line.split()[0] for line in table[1:]] == ["Squat", "Romanian"]
    assert "-# ✅ Romanian deadlift logged · 1 set" in shown
    assert design.buttons(card_now(world).layout)[0].emoji == "✅", "a logged exercise keeps its button, ticked"


def test_the_card_undo_takes_the_log_back_on_the_card_itself(world):
    imported(world)
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    run(session.on_logged(press_on(world, run(session.form_for(started, squat)).arg, {"set0": "40 x 10", "note": ""})))
    undo = next(each for each in design.buttons(card_now(world).layout) if each.label == "Undo")
    pressed = press_on(world, undo.arg, message_id=world.sent[0].id)
    run(database.run(store.db_placed, started.id, GYM, world.sent[0].id))
    assert run(session.on_undo(pressed)) == "↩️ Taken back: that log"
    assert not pressed.shown.updates, "the card is drawn again, not replaced by the words"
    assert run(database.run(store.db_sets, started.id)) == []
    assert "-# ↩️ Taken back: that log" in "\n".join(design.texts(card_now(world).layout))
    assert next(each for each in design.buttons(card_now(world).layout) if each.label == "Undo").disabled


def test_an_old_undo_message_from_before_is_still_answered_in_place(world):
    imported(world)
    started = run(session.start(world.owner.id))
    undo_id = run(session.log_sets(started, "Squat", [DoneSet("Squat", reps=6, weight=80.0)], None))
    pressed = press_on(world, str(undo_id), message_id=999)
    run(session.on_undo(pressed))
    assert pressed.shown.updates and pressed.shown.updates[0].text == "↩️ Taken back: that log"


def test_a_form_opened_before_30_oct_still_logs(world):
    imported(world)
    started = run(session.start(world.owner.id))
    assert run(session.on_logged(press_on(world, f"{started.id}:squat", {"set0": "40 x 10", "set1": "", "note": ""}))) == "logged 1 sets"


def test_nothing_typed_says_so_on_the_card(world):
    imported(world)
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    assert run(session.on_logged(press_on(world, run(session.form_for(started, squat)).arg, {"set0": "", "set1": "", "note": ""}))) == "nothing typed"
    assert "-# Nothing typed for Squat: nothing logged" in "\n".join(design.texts(card_now(world).layout))


# --- last time, on the card and in the labels -----------------------------------------------------------------------------
def test_first_time_and_last_time_on_the_card(world):
    started, row = five_sets(world)
    shown = "\n".join(design.texts(card_now(world).layout))
    assert "### Test row\n-# 5 working 8-12 at a weight of your choice\n-# First time" in shown
    assert "-# last Thu 8 Oct: 40x10 · 80x6" in shown, "the date and each set of last time"
    form = run(session.form_for(started, row))
    assert [field.label for field in form.fields][:2] == ["Set 1", "Set 2"]


# --- Cancel is an undo of Start ----------------------------------------------------------------------------------------------
def test_cancel_after_one_log_puts_everything_back_and_undo_brings_it_back(world):
    imported(world)
    queue_before = run(database.run(store.db_queue, world.owner.id))
    next_before = run(session.next_workout(world.owner.id)).name
    bests_before = run(database.run(store.db_bests, world.owner.id))
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    run(session.on_logged(press_on(world, run(session.form_for(started, squat)).arg, {"set0": "40 x 10", "set1": "100 x 6", "note": "made-up note"})))
    assert run(session.on_cancel(press_on(world, str(started.id)))) == "workout cancelled"
    assert run(database.run(store.db_queue, world.owner.id)) == queue_before and run(session.next_workout(world.owner.id)).name == next_before, "the same workout still next"
    assert run(database.run(store.db_sets, started.id)) == [] and run(database.run(store.db_notes, started.id)) == []
    assert run(database.run(store.db_bests, world.owner.id)) == bests_before, "the best it made is gone"
    assert started.id not in [each.id for each in run(database.run(store.db_sessions, world.owner.id))], "never counted"
    shown = "\n".join(design.texts(card_now(world).layout))
    assert "Lower 1 · cancelled" in shown and "2 sets taken off: nothing logged · Lower 1 is still next" in shown
    undo = next(each for each in design.buttons(card_now(world).layout) if each.label == "Undo")
    assert not undo.disabled, "Undo, as on other cards"
    assert run(session.undo(int(undo.arg), world.owner.id)) == "↩️ The workout is back, as it was"
    back = run(database.run(store.db_session, started.id))
    assert back.status == store.OPEN and [(each.weight, each.reps) for each in run(database.run(store.db_sets, started.id))] == [(40.0, 10), (100.0, 6)]
    assert [each.text for each in run(database.run(store.db_notes, started.id))] == ["made-up note"]


def test_cancel_with_nothing_logged_has_no_undo_and_the_next_start_has_the_same_number(world):
    imported(world)
    started = run(session.start(world.owner.id))
    said, undo_id = run(session.cancel(started))
    assert undo_id is None and said == "🏋️ **Lower 1** cancelled · nothing logged · Lower 1 is still next"
    assert not any(each.label == "Undo" for each in design.buttons(card_now(world).layout))
    from tasks import gym

    assert "last session today" not in run(gym.summary(world.owner.id, world.today)).overview, "the briefing never counts it"
    again = run(session.start(world.owner.id))
    assert (again.name, again.number) == (started.name, started.number), "as if the first was never started"


def test_cancel_workout_in_words(world):
    imported(world)
    with pytest.raises(UserError, match="No workout is open"):
        run(plain.cancel(world.request("cancel workout"), {}, frozenset()))
    run(session.start(world.owner.id))
    assert run(plain.cancel(world.request("cancel workout"), {}, frozenset())).startswith("🏋️ **Lower 1** cancelled")
    assert run(session.next_workout(world.owner.id)).name == "Lower 1"
    assert "gym_cancel" in [each.name for each in plain.actions()]


def test_finish_turns_the_card_into_the_summary_table_with_undo_and_posts_nothing(world):
    imported(world)
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    run(session.on_logged(press_on(world, run(session.form_for(started, squat)).arg, {"set0": "40 x 10", "set1": "", "note": ""})))
    run(session.on_finish(press_on(world, str(started.id))))
    assert len(world.sent) == 1
    shown = "\n".join(design.texts(card_now(world).layout))
    table = shown.split("```\n")[1].split("\n```")[0].splitlines()
    assert shown.startswith("## 🏁 Lower 1 · session 2")
    assert [line.split()[-1] for line in table[1:]] == ["-", "-", "-"] and table[1].split()[:2] == ["Squat", "40x10"], "a dash for each set not done"
    assert all(len(line) <= rules.TABLE_WIDTH for line in table)
    assert [each.label for each in design.buttons(card_now(world).layout)] == ["Undo"]
    (box,) = card_now(world).layout
    assert box.status == design.PREPARED, "the gym's purple edge"
