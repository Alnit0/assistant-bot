"""Adding something that is already there (core/repeats.py): which things are the same,
what a request to add comes to under each `on_repeat`, and the words every task says."""
from types import SimpleNamespace

import pytest

from core import repeats
from tasks.pills import plain as pills_plain

NAME = ("name",)


def thing(name, **more):
    return {"name": name, **more}


# ---------------------------------------------------------------------------
# Which things are the same
# ---------------------------------------------------------------------------
def test_the_same_name_is_the_same_thing_whatever_the_case_or_spacing():
    held = [thing("Vitamin D"), thing("Iron")]
    assert repeats.find(NAME, thing("  vitamin   d "), held) is held[0]
    assert repeats.find(NAME, thing("IRON"), held) is held[1]
    assert repeats.find(NAME, thing("Zinc"), held) is None
    assert repeats.find(NAME, thing("Iro"), held) is None, "exactly the name, never part of it"


def test_with_no_identity_nothing_is_ever_the_same():
    held = [thing("tea")]
    assert repeats.key((), thing("tea")) is None
    assert repeats.find((), thing("tea"), held) is None
    assert repeats.find(NAME, {"label": "tea"}, held) is None, "an item without the field matches nothing"
    assert repeats.find(NAME, thing(""), [thing("")]) is None


def test_an_identity_of_several_fields_needs_all_of_them_to_match():
    held = [thing("Passport", bag="carry-on"), thing("Passport", bag="checked")]
    assert repeats.find(("name", "bag"), thing("passport", bag="Checked"), held) is held[1]
    assert repeats.find(("name", "bag"), thing("passport", bag="hand"), held) is None


def test_a_task_hands_over_its_own_records_and_may_compare_in_its_own_way():
    pills = [SimpleNamespace(plan=SimpleNamespace(name="Iron"))]
    assert repeats.find(NAME, thing("iron"), pills, lambda pill: {"name": pill.plan.name}) is pills[0]
    held = [thing("eggs")]
    assert repeats.find(NAME, thing("egg"), held) is None
    assert repeats.find(NAME, thing("egg"), held, same=lambda one, other: one.rstrip("s") == other.rstrip("s")) is held[0]


# ---------------------------------------------------------------------------
# What a request to add comes to
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "on_repeat, changes, kind",
    [
        (repeats.UPDATE, True, repeats.CHANGE),
        (repeats.UPDATE, False, repeats.SAME),
        (repeats.ADD_TO_AMOUNT, True, repeats.MORE),
        (repeats.ALLOW_ANOTHER, True, repeats.ANOTHER),
        (repeats.ASK, True, repeats.QUESTION),
    ],
)
def test_what_adding_something_that_is_there_comes_to(on_repeat, changes, kind):
    there = thing("Iron")
    assert repeats.decide(on_repeat, there, changes) == repeats.Repeat(kind, there)


@pytest.mark.parametrize("on_repeat", repeats.ON_REPEAT)
def test_something_that_is_not_there_is_new_whatever_the_rule(on_repeat):
    assert repeats.decide(on_repeat, None) == repeats.Repeat(repeats.NEW, None)


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------
def test_the_words_are_the_same_for_every_task():
    assert repeats.already("Iron", "pills") == "**Iron** is already in your pills with these settings"
    assert repeats.there_line("Iron", "pills") == "**Iron** · already in your pills"
    assert repeats.change_line("eggs", 5, 7) == "eggs · 5 → 7"
    assert repeats.change_line("schedule", "daily at `8:00 pm`", "daily at `9:00 pm`") == "schedule · daily at `8:00 pm` → daily at `9:00 pm`"


def test_pills_matches_and_speaks_through_core():
    assert (pills_plain.IDENTITY, pills_plain.ON_REPEAT) == (("name",), repeats.UPDATE)
    pill = SimpleNamespace(plan=SimpleNamespace(name="Vitamin D"), status="active")
    assert pills_plain._already(pill) == "**Vitamin D** is already in your pills with these settings"
