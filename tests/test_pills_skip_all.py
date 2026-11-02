"""Pills, "skip all": every dose still to take today, of one pill or of every pill,
on one confirm card; Save skips them, Undo brings them back with their reminders.
And one dose skipped by its time ("skip the 2 pm one"). Made-up pills only."""
from datetime import time

import pytest

from core import cards, day
from core.errors import UserError
from core.occurrences import DONE, PENDING, SKIPPED
from tasks.pills import plain, skipping
from tests.test_pills_reminders import EVENING, PILL_A, Press, add, at, log, notices, prompts, run, states, world  # noqa: F401

PILL_B = {"name": "Pill B", "times": ["11:30 am", "6:00 pm"]}


@pytest.fixture
def skipping_world(world):  # noqa: F811
    skipping.register()
    return world


def ask(world, *pills):
    data = {"pills": [{"pill": each} for each in pills]} if pills else {}
    request = world.request()
    if not run(skipping.asks(request, data)):
        return None, run(skipping.said(request, data, frozenset()))
    return run(skipping.card(request, data, frozenset())), None


def save(world, proposal):
    answer = run(skipping.save(world.request(), proposal.data))
    assert run(skipping.check(world.request(), proposal.data)) == "", "read back: every dose on the card is skipped"
    message_id = 5000
    run(answer.placed(message_id))
    edits = [card for at_, card in world.edited if at_ == message_id]
    return answer.text, edits[-1] if edits else None


def undo(world, shown):
    (button,) = [button for row in shown.rows for button in row]
    pressed = Press(world, 5000, 0)
    pressed.arg = button.arg
    return run(cards._actions[("pills", skipping.UNDO)].handler(pressed)), pressed


def test_skip_all_of_one_pill_with_three_doses_left_lists_each_by_time_and_save_skips_them_all(skipping_world):
    world = skipping_world
    add(world, PILL_A, EVENING)
    at(world, 7, 0)
    proposal, _ = ask(world, "Pill A")
    assert proposal.kind == "change" and proposal.question is None
    assert proposal.lines == (
        "Skip these 3 doses today:",
        "⏭️ `8:00 am` · **Pill A** (dose 1 of 3)",
        "⏭️ `11:30 am` · **Pill A** (dose 2 of 3)",
        "⏭️ `3:00 pm` · **Pill A** (dose 3 of 3)",
    )
    assert states(world)[("Pill A", 1)] == PENDING, "nothing is skipped by asking"
    said, shown = save(world, proposal)
    assert said.splitlines()[0] == "⏭️ Skipped 3 doses today"
    assert [states(world)[("Pill A", number)] for number in (1, 2, 3)] == [SKIPPED] * 3
    assert states(world)[("Evening pill", 1)] == PENDING, "another pill is left alone"
    assert [button.label for row in shown.rows for button in row] == ["Undo"]
    at(world, 8, 0)
    assert notices(world) == [], "no reminder for a skipped dose"


def test_undo_brings_every_dose_back_and_their_reminders_with_them(skipping_world):
    world = skipping_world
    add(world, PILL_A)
    at(world, 7, 0)
    proposal, _ = ask(world, "Pill A")
    _, shown = save(world, proposal)
    said, pressed = undo(world, shown)
    assert said.splitlines()[0] == "↩️ Not skipped after all: 3 doses to take again"
    assert [states(world)[("Pill A", number)] for number in (1, 2, 3)] == [PENDING] * 3
    assert pressed.shown[-1].rows == (), "the button goes"
    at(world, 8, 0)
    assert notices(world) == ["💊 Dose due · 8:00 am"], "its reminders come back"
    again, _ = undo(world, shown)
    assert again == "nothing to undo"


def test_skip_all_with_two_pills_is_every_dose_of_both_in_the_order_of_the_day(skipping_world):
    world = skipping_world
    add(world, PILL_A, PILL_B)
    at(world, 7, 0)
    proposal, _ = ask(world)
    assert proposal.lines == (
        "Skip these 5 doses today:",
        "⏭️ `8:00 am` · **Pill A** (dose 1 of 3)",
        "⏭️ `11:30 am` · **Pill A** (dose 2 of 3)",
        "⏭️ `11:30 am` · **Pill B** (dose 1 of 2)",
        "⏭️ `3:00 pm` · **Pill A** (dose 3 of 3)",
        "⏭️ `6:00 pm` · **Pill B** (dose 2 of 2)",
    )
    save(world, proposal)
    assert set(states(world).values()) == {SKIPPED}


def test_skip_all_after_one_dose_was_taken_leaves_that_one_alone(skipping_world):
    world = skipping_world
    add(world, PILL_A)
    at(world, 8, 0)
    log(world, {"pill": "Pill A", "did": "taken"})
    at(world, 9, 0)
    proposal, _ = ask(world, "Pill A")
    assert proposal.lines[0] == "Skip these 2 doses today:" and len(proposal.lines) == 3
    save(world, proposal)
    assert [states(world)[("Pill A", number)] for number in (1, 2, 3)] == [DONE, SKIPPED, SKIPPED]


def test_nothing_left_to_skip_is_said_in_one_line(skipping_world):
    world = skipping_world
    add(world, EVENING)
    at(world, 7, 0)
    log(world, {"pill": "Evening pill", "did": "skipped"})
    proposal, said = ask(world, "Evening pill")
    assert proposal is None and said == "💊 **Evening pill** has nothing left to take today: there is nothing to skip."
    proposal, said = ask(world)
    assert proposal is None and said == skipping.NOTHING and "\n" not in said


def test_a_dose_taken_after_the_card_was_made_is_left_as_it_is_on_save(skipping_world):
    world = skipping_world
    add(world, PILL_A)
    at(world, 8, 0)
    proposal, _ = ask(world, "Pill A")
    log(world, {"pill": "Pill A", "did": "taken"})
    said, _ = save(world, proposal)
    assert said.splitlines()[0] == "⏭️ Skipped 2 doses today" and states(world)[("Pill A", 1)] == DONE


def test_skip_one_dose_by_its_time_finds_the_dose_due_then(skipping_world):
    world = skipping_world
    add(world, PILL_A, EVENING)
    at(world, 7, 0)
    said = log(world, {"pill": "@that", "did": "skipped", "at": "3:00 pm"})
    assert said.startswith("⏭️ **Pill A** (dose 3 of 3) · skipped"), said
    assert [states(world)[("Pill A", number)] for number in (1, 2, 3)] == [PENDING, PENDING, SKIPPED]
    assert log(world, {"pill": "@that", "did": "skipped", "at": "8:00 pm"}).startswith("⏭️ **Evening pill** · skipped")


def test_two_pills_due_at_the_time_said_are_asked_about_on_the_card(skipping_world):
    world = skipping_world
    add(world, PILL_A, PILL_B)
    at(world, 7, 0)
    item = {"pill": "@that", "did": "skipped", "at": "11:30 am"}
    assert run(plain.log_asks(world.request(), {"doses": [item]}))
    proposal = run(plain.log_card(world.request(), {"doses": [item]}, frozenset()))
    assert [choice.label for choice in proposal.question.choices] == ["Pill A", "Pill B"]
    assert log(world, {"pill": "Pill B", "did": "skipped", "at": "11:30 am"}).startswith("⏭️ **Pill B** (dose 1 of 2) · skipped")


def test_a_time_with_nothing_due_says_so(skipping_world):
    world = skipping_world
    add(world, PILL_A)
    at(world, 7, 0)
    assert log(world, {"pill": "@that", "did": "skipped", "at": "9:00 pm"}) == "💊 Nothing is left to take at 9:00 pm today."


def test_the_undo_button_holds_a_day_of_doses():
    ids = list(range(10450, 10465))
    button = skipping.undo_button(ids)
    assert button is not None and skipping.from_undo_arg(button.arg) == ids
    assert skipping.from_undo_arg("zz.!") == []


def test_at_time_is_python_s_from_the_schedule(skipping_world):
    world = skipping_world
    add(world, PILL_A)
    at(world, 7, 0)
    listed = run(__import__("tasks.pills.checklist", fromlist=["view"]).view(world.owner.id))[1]
    assert [dose.number for dose in plain.at_time(listed, (time(11, 0),))] == [2], "the nearest within an hour"
    assert plain.at_time(listed, (time(18, 0),)) == []
    assert day.today() == world.day
    with pytest.raises(UserError):
        run(skipping.card(world.request(), {"pills": [{"pill": "Pill Z"}]}, frozenset()))
