"""Logging at the gym on a phone, a set at a time (30 Oct, reworked after Alex's look): a header and a card an
exercise, each its own message edited in place and nothing else posted; a button a set opening a pop-up for that
one set (Weight (kg), Reps, a Note of several lines, every box empty, last time's numbers in the labels), read by
Python, a logged set's button ticked ("✅ 2") and notes on sets only; a card that
never grows as sets are logged, purple until every set is in and then green; Undo, Finish and Cancel on the
header; the same in words. Made-up data only (tests/gym_files.py)."""
from types import SimpleNamespace

import pytest

from core import actions, cards, database, design
from core.errors import UserError
from tasks.gym import plain, rules, session, store
from tasks.gym.rules import DoneSet, Exercise, PlannedSet
from tests.test_gym import GYM, imported, run, world  # noqa: F401


@pytest.fixture
def gym(world, monkeypatch):
    """The world, with messages deleted as well as posted and edited."""
    world.deleted = []

    async def delete(channel_id, message_id):
        world.deleted.append(message_id)
        return True

    monkeypatch.setattr(cards, "delete", delete)
    imported(world)
    return world


def now(world, message_id):
    """A message as it stands: its last edit, else as it was posted."""
    edits = [card for each, card in world.edited if each == message_id]
    return edits[-1] if edits else next(each.card for each in world.sent if each.id == message_id)


def shown(card) -> str:
    return "\n".join(design.texts(card.layout))


def labels(card) -> list[str]:
    return [each.label for each in design.buttons(card.layout)]


def press_on(world, arg: str, fields=None, message_id=None):
    seen = SimpleNamespace(forms=[], updates=[])

    async def open_form(form):
        seen.forms.append(form)

    async def update(card):
        seen.updates.append(card)

    return SimpleNamespace(arg=arg, fields=fields, values=(), db=database, user=world.owner, channel_id=GYM, message_id=message_id, open_form=open_form, update=update, shown=seen)


def started_with_messages(world):
    started = run(session.start(world.owner.id))
    started = run(database.run(store.db_session, started.id))
    return started, started.cards["exercises"]


def tap(world, started, index, position, fields):
    """A set's button pressed (its pop-up opened), then the pop-up sent with `fields`."""
    exercise = run(session.exercises_of(started))[index]
    opened = press_on(world, f"{started.id}:{index}:{position}")
    run(session.on_log(opened))
    (form,) = opened.shown.forms
    return form, run(session.on_logged(press_on(world, form.arg, fields))), exercise


# --- the boxes, read by Python ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("typed, read", [("60", (60.0, False, True)), ("60kg", (60.0, False, True)), ("22.5", (22.5, False, True)), ("22,5 kg", (22.5, False, True)),
                                         ("14s", (14.0, True, True)), ("", (None, False, True)), ("sixty", (None, False, False)), ("60 x 8", (None, False, False))])
def test_the_weight_box(typed, read):
    assert rules.typed_weight(typed) == read


@pytest.mark.parametrize("typed, read", [("8", (8, True)), ("8 reps", (8, True)), ("", (None, True)), ("eight", (None, False)), ("0", (None, False)), ("8.5", (None, False))])
def test_the_reps_box(typed, read):
    assert rules.typed_reps(typed) == read


def test_a_set_is_read_and_a_box_that_cannot_be_read_is_kept_as_its_note_with_no_number_made_up():
    planned = DoneSet("Test press", position=1)
    assert session.read_set({"weight": "", "reps": "", "note": ""}, planned) is None, "every box empty: nothing"
    good = session.read_set({"weight": "60", "reps": "8", "note": "felt heavy"}, planned)
    assert (good.weight, good.reps, good.note, good.look, good.position) == (60.0, 8, "felt heavy", False, 1)
    assert session.read_set({"weight": "", "reps": "12", "note": ""}, planned).weight is None, "bodyweight: the weight left empty"
    bad = session.read_set({"weight": "sixty", "reps": "8", "note": "grip"}, planned)
    assert (bad.weight, bad.reps, bad.note, bad.look) == (None, 8, "sixty · grip", True)
    no_reps = session.read_set({"weight": "60", "reps": "", "note": ""}, planned)
    assert (no_reps.weight, no_reps.reps, no_reps.look) == (60.0, None, True)


def test_a_card_s_table_is_a_row_a_set_within_a_phone_s_width():
    cells = [rules.set_cell(DoneSet("x", reps=8, weight=102.5)), rules.set_cell(DoneSet("x", reps=10, weight=14.0, per_hand=True)), rules.set_cell(None),
             rules.set_cell(DoneSet("x", weight=60.0, look=True)), rules.set_cell(DoneSet("x", reps=12))]
    assert cells == ["102.5 x 8", "14 x 10 each", "-", "60 x ?", "12"]
    lines = rules.sets_table(cells)
    assert lines[0] == "1  102.5 x 8" and lines[2] == "3  -" and all(len(line) <= rules.TABLE_WIDTH for line in lines)
    assert rules.sets_table(["-"] * 12)[0] == " 1  -", "numbers line up past nine"


# --- start: a header, then a card an exercise, nothing else -----------------------------------------------------------------------
def test_start_posts_a_header_then_a_card_an_exercise_in_plan_order_and_nothing_else(gym):
    started, ids = started_with_messages(gym)
    exercises = run(session.exercises_of(started))
    assert [each.id for each in gym.sent] == [started.message_id, *ids] and len(ids) == len(exercises) == 3
    header = now(gym, started.message_id)
    assert "## 🏋️ Lower 1 · session 2" in shown(header) and "0 of 3 exercises done" in shown(header)
    assert labels(header) == ["Undo", "Finish", "Cancel"] and design.buttons(header.layout)[0].disabled, "Undo greyed: nothing to undo"
    squat = now(gym, ids[0])
    assert shown(squat).startswith("### Squat\n-# 1 warm-up 8-10 · 1 working 4-6 reps\n-# Last · Thu 8 Oct · 40 x 10, 80 x 6\n```\n1  -\n2  -\n```")
    assert labels(squat) == ["1", "2"], "a button a set, no word Set, and no Note: notes go on sets"
    assert all(box.status == design.PREPARED for each in ids for box in now(gym, each).layout), "purple, not started"
    assert all(not design.problem(now(gym, each).layout) for each in [started.message_id, *ids])


def test_first_time_on_a_card_and_six_sets_wrap_to_a_second_row(gym):
    plan = run(store.plan(gym.owner.id))
    lower = next(each for each in plan if each.name == "Lower 1")
    run(database.run(store.db_add_exercise, gym.owner.id, lower.id, len(lower.exercises), Exercise("Test row", tuple(PlannedSet(rules.WORKING, "", "", 8, 12) for _ in range(6)), rules.MACHINE)))
    started, ids = started_with_messages(gym)
    row = now(gym, ids[-1])
    assert "### Test row\n-# 6 sets · 8-12 reps\n-# First time" in shown(row)
    assert [len(each.buttons) for each in row.layout[0].children if isinstance(each, design.Row)] == [5, 1], "1 to 5, then 6"
    form, _, _ = tap(gym, started, 3, 0, {"weight": "", "reps": "", "note": ""})
    assert [field.label for field in form.fields] == ["Weight (kg)", "Reps", "Note"], "no last time: plain labels"
    tap(gym, started, 3, 5, {"weight": "30", "reps": "12", "note": ""})
    rows = [[button.label for button in each.buttons] for each in now(gym, ids[-1]).layout[0].children if isinstance(each, design.Row)]
    assert rows == [["1", "2", "3", "4", "5"], ["6"]], "set 6 logged: no button moved"


# --- a set's pop-up -------------------------------------------------------------------------------------------------------------------
def test_a_set_s_pop_up_is_that_set_alone_every_box_empty_last_time_in_the_labels(gym):
    started, _ = started_with_messages(gym)
    opened = press_on(gym, f"{started.id}:0:1")
    assert run(session.on_log(opened)) == "set 2 pop-up opened"
    (form,) = opened.shown.forms
    cards.check_form(form)
    assert form.title == "Squat · set 2"
    assert [field.label for field in form.fields] == ["Weight (kg) · last 80", "Reps · last 6", "Note"]
    assert all(not field.value and not field.placeholder and not field.required for field in form.fields), "nothing to delete before typing"
    assert [field.long for field in form.fields] == [False, False, True], "the Note box takes several lines; Weight and Reps one"


def test_log_set_1_then_set_2_edits_only_that_card_and_the_header_and_its_height_never_changes(gym):
    started, ids = started_with_messages(gym)
    before = shown(now(gym, ids[0]))
    posted = len(gym.sent)
    gym.edited.clear()
    _, said, _ = tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    assert said == "set 1 logged: 40 x 10"
    assert {message_id for message_id, _ in gym.edited} == {ids[0], started.message_id}, "only that exercise's card and the header"
    first = now(gym, ids[0])
    assert labels(first) == ["1", "2"] and design.buttons(first.layout)[0].emoji == "✅", "a tick, the numbers are in the table"
    assert len(shown(first).splitlines()) == len(before.splitlines()), "the card's height never changes"
    tap(gym, started, 0, 1, {"weight": "82.5", "reps": "6", "note": ""})
    both = now(gym, ids[0])
    assert "```\n1  40 x 10\n2  82.5 x 6\n```" in shown(both) and len(shown(both).splitlines()) == len(before.splitlines())
    assert both.layout[0].status == design.DONE, "green: every planned set logged"
    assert "1 of 3 exercises done" in shown(now(gym, started.message_id))
    assert len(gym.sent) == posted, "nothing posted"
    logged = run(database.run(store.db_set_logged_at, started.id))
    assert [(name, position) for name, position, _ in logged] == [("Squat", 0), ("Squat", 1)] and all(when for _, _, when in logged), "each set its own record, with its time"


def test_correcting_a_set_puts_that_set_right_and_nothing_else(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    tap(gym, started, 0, 1, {"weight": "80", "reps": "6", "note": ""})
    form, said, _ = tap(gym, started, 0, 0, {"weight": "42.5", "reps": "9", "note": "better"})
    assert [field.label for field in form.fields][:2] == ["Weight (kg) · now 40 · last 40", "Reps · now 10 · last 10"]
    assert said == "set 1 logged: 42.5 x 9"
    assert [(each.position, each.weight, each.reps, each.note) for each in run(database.run(store.db_sets, started.id))] == [(0, 42.5, 9, "better"), (1, 80.0, 6, "")]
    assert "-# set 1: better" in shown(now(gym, ids[0]))


def test_a_set_on_another_exercise_has_its_own_card(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    edits = len(gym.edited)
    tap(gym, started, 2, 0, {"weight": "70", "reps": "9", "note": ""})
    assert {message_id for message_id, _ in gym.edited[edits:]} == {ids[2], started.message_id}
    assert "1  40 x 10" in shown(now(gym, ids[0])) and "1  70 x 9" in shown(now(gym, ids[2]))
    assert design.buttons(now(gym, ids[2]).layout)[0].emoji == "✅" and design.buttons(now(gym, ids[1]).layout)[0].emoji is None


def test_a_box_that_cannot_be_read_says_on_its_card_which_set_needs_a_look(gym):
    started, ids = started_with_messages(gym)
    _, said, _ = tap(gym, started, 0, 1, {"weight": "eighty", "reps": "6", "note": ""})
    assert said == "set 2 kept to look at"
    card = now(gym, ids[0])
    assert "-# ⚠️ set 2 needs a look: “eighty”" in shown(card) and design.buttons(card.layout)[1].emoji == "⚠️" and labels(card)[1] == "2"
    (kept,) = run(database.run(store.db_sets, started.id))
    assert (kept.weight, kept.reps, kept.note, kept.look) == (None, 6, "eighty", True), "nothing made up"


def test_every_box_empty_logs_nothing_and_clears_a_set_that_was_there(gym):
    started, _ = started_with_messages(gym)
    assert tap(gym, started, 0, 0, {"weight": "", "reps": "", "note": ""})[1] == "nothing typed"
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    assert tap(gym, started, 0, 0, {"weight": "", "reps": "", "note": ""})[1] == "set 1 cleared"
    assert run(database.run(store.db_sets, started.id)) == []


def test_an_old_card_s_note_button_still_works_and_an_exercise_note_still_shows_under_its_table(gym):
    started, ids = started_with_messages(gym)
    opened = press_on(gym, f"{started.id}:2")
    run(session.on_note(opened))
    (form,) = opened.shown.forms
    cards.check_form(form)
    assert form.title == "Romanian deadlift · note" and [field.label for field in form.fields] == ["Note"]
    assert run(session.on_noted(press_on(gym, form.arg, {"note": "knee hurt a bit"}))) == "note kept"
    assert "-# ⚠️ “knee hurt a bit”" in shown(now(gym, ids[2])), "read for pain, nothing deleted"


def test_a_note_said_in_words_goes_on_the_set_of_that_exercise_logged_most_recently(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 1, {"weight": "80", "reps": "6", "note": "grip"})
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    request = actions.Request(gym.owner, GYM)
    proposal = run(plain.describe_card(request, {"sets": [{"exercise": "squat", "note": "last set felt heavy"}]}, frozenset()))
    assert proposal.lines == ("**Lower 1** · today", "**Squat** · set 1", "-# note: “last set felt heavy”"), "set 1 was logged last"
    posted = len(gym.sent)
    assert run(plain.describe_save(request, proposal.data)) == "🏋️ Note kept · **Squat** set 1"
    assert run(plain.describe_check(request, proposal.data)) == ""
    assert [(each.position, each.weight, each.reps, each.note) for each in run(database.run(store.db_sets, started.id))] == [(0, 40.0, 10, "last set felt heavy"), (1, 80.0, 6, "grip")]
    assert "-# set 1: last set felt heavy" in shown(now(gym, ids[0])) and len(gym.sent) == posted
    tap(gym, started, 0, 1, {"weight": "80", "reps": "6", "note": "grip"})
    again = run(plain.describe_card(request, {"sets": [{"exercise": "squat", "note": "slow"}]}, frozenset()))
    run(plain.describe_save(request, again.data))
    assert run(database.run(store.db_sets, started.id))[1].note == "grip · slow", "put after the note it had"


def test_a_note_in_words_with_no_set_logged_asks_for_a_set_first(gym):
    started_with_messages(gym)
    with pytest.raises(UserError, match="No set of \\*\\*Romanian deadlift\\*\\* logged yet"):
        run(plain.describe_card(actions.Request(gym.owner, GYM), {"sets": [{"exercise": "romanian deadlift", "note": "felt good"}]}, frozenset()))


# --- the header: Undo -------------------------------------------------------------------------------------------------------------
def test_the_header_undo_takes_back_the_last_set_one_a_press(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    tap(gym, started, 0, 1, {"weight": "80", "reps": "6", "note": ""})
    undo = design.buttons(now(gym, started.message_id).layout)[0]
    assert not undo.disabled and undo.action == session.UNDO_LAST
    pressed = press_on(gym, undo.arg, message_id=started.message_id)
    assert run(session.on_undo_last(pressed)) == "↩️ Taken back: that log" and not pressed.shown.updates
    assert [each.emoji for each in design.buttons(now(gym, ids[0]).layout)] == ["✅", None]
    run(session.on_undo_last(pressed))
    assert [each.emoji for each in design.buttons(now(gym, ids[0]).layout)] == [None, None] and design.buttons(now(gym, started.message_id).layout)[0].disabled


def test_an_old_undo_message_from_before_is_still_answered_in_place(gym):
    started, _ = started_with_messages(gym)
    undo_id = run(session.log_sets(started, "Squat", [DoneSet("Squat", reps=6, weight=80.0)], None))
    pressed = press_on(gym, str(undo_id), message_id=999)
    run(session.on_undo(pressed))
    assert pressed.shown.updates and pressed.shown.updates[0].text == "↩️ Taken back: that log"


def test_buttons_and_pop_ups_from_the_one_card_before_still_work(gym):
    started, _ = started_with_messages(gym)
    old_log = press_on(gym, f"{started.id}:squat")
    run(session.on_log(old_log))
    assert old_log.shown.forms[0].title == "Squat · set 1", "an old Log button: the first set not logged"
    assert run(session.on_logged(press_on(gym, f"{started.id}:0:squat", {"set0": "40 x 10", "set1": "", "note": ""}))) == "logged 1 sets"
    assert [(each.position, each.reps) for each in run(database.run(store.db_sets, started.id))] == [(0, 10)]


# --- Cancel and Finish --------------------------------------------------------------------------------------------------------------
def test_cancel_after_two_sets_puts_everything_back_deletes_the_cards_and_undo_brings_them_back(gym):
    queue_before = run(database.run(store.db_queue, gym.owner.id))
    bests_before = run(database.run(store.db_bests, gym.owner.id))
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    tap(gym, started, 0, 1, {"weight": "100", "reps": "6", "note": ""})
    assert run(session.on_cancel(press_on(gym, str(started.id)))) == "workout cancelled"
    assert run(database.run(store.db_queue, gym.owner.id)) == queue_before and run(session.next_workout(gym.owner.id)).name == "Lower 1", "the rotation unchanged"
    assert run(database.run(store.db_sets, started.id)) == [] and run(database.run(store.db_bests, gym.owner.id)) == bests_before
    assert started.id not in [each.id for each in run(database.run(store.db_sessions, gym.owner.id))], "never counted"
    assert sorted(gym.deleted) == sorted([started.message_id, *ids]), "the header and every card gone"
    line = gym.sent[-1].card
    assert line.text == "🏋️ **Lower 1** cancelled · 2 sets taken off, nothing logged · Lower 1 is still next" and [each.label for row in line.rows for each in row] == ["Undo"]
    undo, line_id = line.rows[0][0], gym.sent[-1].id
    pressed = press_on(gym, undo.arg, message_id=line_id)
    assert run(session.on_undo(pressed)) == "↩️ The workout is back, as it was"
    assert not pressed.shown.updates, "the line is deleted, never edited"
    back = run(database.run(store.db_session, started.id))
    assert back.status == store.OPEN and line_id in gym.deleted, "the line gone"
    assert len(back.cards["exercises"]) == 3 and back.message_id not in (None, started.message_id), "posted again"
    assert "1  40 x 10\n2  100 x 6" in shown(now(gym, back.cards["exercises"][0])) and labels(now(gym, back.cards["exercises"][0])) == ["1", "2"]


def test_cancel_with_nothing_logged_and_the_next_start_has_the_same_number(gym):
    started, _ = started_with_messages(gym)
    said, undo_id = run(session.cancel(started))
    assert said == "🏋️ **Lower 1** cancelled · nothing logged · Lower 1 is still next" and undo_id
    from tasks import gym as gym_task

    assert "last session today" not in run(gym_task.summary(gym.owner.id, gym.today)).overview, "the briefing never counts it"
    again = run(session.start(gym.owner.id))
    assert (again.name, again.number) == (started.name, started.number), "as if the first was never started"


def test_finish_takes_the_buttons_off_and_posts_the_summary_under_the_cards(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    posted = len(gym.sent)
    assert run(session.on_finish(press_on(gym, str(started.id)))) == "workout finished"
    assert all(not design.buttons(now(gym, each).layout) for each in [started.message_id, *ids]), "no buttons left"
    assert len(gym.sent) == posted + 1, "the summary, one new message"
    summary = gym.sent[-1].card
    table = shown(summary).split("```\n")[1].split("\n```")[0].splitlines()
    assert shown(summary).startswith("## 🏁 Lower 1 · session 2") and [line.split()[0] for line in table[1:]] == ["Squat", "Leg", "Romanian"], "every exercise"
    assert table[1].split()[1:] == ["40x10", "-"] and all(len(line) <= rules.TABLE_WIDTH for line in table)
    assert labels(summary) == ["Undo"]
    assert run(session.next_workout(gym.owner.id)).name != "Lower 1", "done in the rotation"
    pressed = press_on(gym, design.buttons(summary.layout)[0].arg, message_id=gym.sent[-1].id)
    run(session.on_undo(pressed))
    assert not pressed.shown.updates, "the summary is deleted, never edited"
    assert gym.sent[-1].id in gym.deleted and labels(now(gym, started.message_id)) == ["Undo", "Finish", "Cancel"], "open again, its buttons back"


# --- words ------------------------------------------------------------------------------------------------------------------------
def test_a_numbered_set_in_words_is_that_set_and_leaves_the_others(gym):
    started, ids = started_with_messages(gym)
    tap(gym, started, 0, 0, {"weight": "40", "reps": "10", "note": ""})
    proposal = run(plain.describe_card(gym.request("squat 2 82.5 x 6"), {"sets": [{"exercise": "squat", "set": 2, "reps": 6, "weight": 82.5}]}, frozenset()))
    run(plain.describe_save(gym.request(), proposal.data))
    assert [(each.position, each.weight, each.reps) for each in run(database.run(store.db_sets, started.id))] == [(0, 40.0, 10), (1, 82.5, 6)]
    assert "1  40 x 10\n2  82.5 x 6" in shown(now(gym, ids[0])) and [each.emoji for each in design.buttons(now(gym, ids[0]).layout)][:2] == ["✅", "✅"]
    assert "set" in [each.name for each in next(action for action in plain.actions() if action.name == "gym_log").fields[2].item_fields]


def test_finish_and_cancel_said_in_gym_post_nothing_more_there(gym):
    run(session.start(gym.owner.id))
    in_gym = actions.Request(gym.owner, GYM, "cancel workout")
    assert isinstance(run(plain.cancel(in_gym, {}, frozenset())), actions.Shown)
    with pytest.raises(UserError, match="No workout is open"):
        run(plain.finish(in_gym, {}, frozenset()))
    run(session.start(gym.owner.id))
    assert run(plain.finish(gym.request("finish"), {}, frozenset())).startswith("🏁 **Lower 1**"), "said elsewhere, it answers there"
