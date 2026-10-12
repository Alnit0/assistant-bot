"""Which of my things a name means (core/names.py), the decimal number of the
contract, and the files sent with a message."""
import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from core import actions, names, routing
from core.actions import ITEMS, NUMBER, Action, Attachment, Field, Invalid, Request
from core.context import Context
from tasks.pills import rules


@dataclass
class Thing:
    id: int
    name: str


THINGS = [Thing(1, "Bench press"), Thing(2, "Overhead press"), Thing(3, "Squat"), Thing(4, "Press")]


def find(wanted, things=THINGS):
    return names.find(things, wanted, lambda thing: thing.name, "ex", lambda thing: thing.id)


# --- name matching --------------------------------------------------------------------------------------------
def test_the_whole_name_wins_over_part_of_one():
    assert find("press").id == 4 and find("  PRESS ").id == 4
    assert find("squat").id == 3 and find("bench").id == 1 and find("overhead   press").id == 2


def test_a_name_that_fits_more_than_one_is_never_guessed():
    with pytest.raises(names.Ambiguous) as which:
        find("press", THINGS[:3])
    assert [thing.id for thing in which.value.candidates] == [1, 2] and which.value.said == "press"
    assert which.value.labels == ["Bench press", "Overhead press"]
    assert str(which.value) == "Which one: **Bench press** or **Overhead press**?"


def test_an_id_is_read_when_the_task_has_them_and_a_name_is_tried_when_it_is_no_id_of_mine():
    assert find("ex3").id == 3 and find("EX 2").id == 2
    with pytest.raises(names.Unknown):
        find("ex9")
    assert names.find(THINGS, "squat", lambda thing: thing.name).id == 3, "a task with no ids gives no prefix"
    with pytest.raises(names.Unknown):
        names.find(THINGS, "ex3", lambda thing: thing.name)


def test_nothing_named_and_no_such_thing_are_told_apart():
    with pytest.raises(names.Unnamed):
        find("   ")
    with pytest.raises(names.Unknown) as none:
        find(" deadlift ")
    assert none.value.said == "deadlift"
    with pytest.raises(names.Unknown):
        find("squat", [])


def test_pills_ask_the_core_and_keep_their_own_words():
    pills = [rules.Pill(1, 1, rules.Plan("Iron")), rules.Pill(2, 1, rules.Plan("Iron forte")), rules.Pill(3, 1, rules.Plan("Zinc"))]
    assert rules.find(pills, "iron").id == 1 and rules.find(pills, "forte").id == 2 and rules.find(pills, "pl3").id == 3
    with pytest.raises(names.Ambiguous, match=r"Which one: \*\*Iron\*\* or \*\*Iron forte\*\*\?"):
        rules.find(pills, "ir")
    assert rules.Ambiguous is names.Ambiguous
    with pytest.raises(rules.UserError, match="I don't have a pill called “magnesium”. Yours: Iron, Iron forte, Zinc."):
        rules.find(pills, "magnesium")
    with pytest.raises(rules.UserError, match="Which pill?"):
        rules.find(pills, "")
    with pytest.raises(rules.UserError, match="There are no pills yet."):
        rules.find([], "iron")


# --- a decimal number -----------------------------------------------------------------------------------------
async def _run(request, data, guessed):
    return "done"


LOG = Action(
    "thing_log",
    "Log a weight.",
    (
        Field("weight", "The weight lifted.", NUMBER, required=True),
        Field("sets", "Each set.", ITEMS, item_fields=(Field("weight", "Its weight.", NUMBER), Field("reps", "How many.", actions.INTEGER))),
    ),
    run=_run,
)


def test_a_decimal_is_a_number_in_the_schema_and_never_text():
    properties = actions.schema(LOG)["properties"]
    assert properties["weight"]["type"] == "number" and properties["weight"]["description"].endswith("(62.5), and no unit.")
    assert properties["sets"]["items"]["properties"]["weight"]["type"] == "number"
    assert NUMBER in actions.TYPES and NUMBER in actions.IN_AN_ITEM


@pytest.mark.parametrize(
    "given, kept",
    [(62.5, 62.5), (60, 60), (60.0, 60), (0, 0), ("62.5", 62.5), ("62,5", 62.5), (" 80 ", 80), (-2.5, -2.5)],
)
def test_a_number_is_kept_as_it_was_meant(given, kept):
    data, _ = actions.validate(LOG, {"weight": given, "guessed": []})
    assert data["weight"] == kept and type(data["weight"]) is type(kept)


@pytest.mark.parametrize("given", [True, "heavy", "62.5 kg", [62.5], float("nan"), float("inf"), ""])
def test_what_is_not_a_number_is_refused(given):
    with pytest.raises(Invalid, match="weight"):
        actions.validate(LOG, {"weight": given, "guessed": []})


def test_a_number_inside_an_item_is_checked_the_same_way():
    data, _ = actions.validate(LOG, {"weight": 60, "sets": [{"weight": "62,5", "reps": 7}, {"reps": 8}], "guessed": []})
    assert data["sets"] == [{"weight": 62.5, "reps": 7}, {"reps": 8}]
    # One that can't be read is left out and said so, like any item that can't be used
    checked = actions.validate(LOG, {"weight": 60, "sets": [{"weight": "lots"}, {"reps": 8}], "guessed": []})
    assert checked.data["sets"] == [{"reps": 8}] and checked.not_included == ("lots",)


# --- attachments ----------------------------------------------------------------------------------------------
def test_a_request_carries_the_files_and_none_by_default():
    assert Request(None, 1, "hello").attachments == ()

    async def fetch():
        return b"Day,Exercise"

    plan = Attachment("Plan.CSV", 12, "text/csv", fetch)
    request = Request(None, 1, "here is my plan", attachments=(plan,))
    assert request.attachments[0].name == "Plan.CSV" and plan.extension == "csv" and plan.size == 12
    assert asyncio.run(plan.read()) == b"Day,Exercise"
    assert Attachment("notes").extension == "" and Attachment(".env").extension == ""
    with pytest.raises(actions.UserError, match="I can't read notes."):
        asyncio.run(Attachment("notes").read())


def test_the_context_hands_over_a_message_s_files_as_plain_records():
    async def read():
        return b"x"

    message = SimpleNamespace(
        id=5, content="my plan", channel=SimpleNamespace(id=9), reference=None,
        attachments=[SimpleNamespace(filename="plan.xlsx", size=2048, content_type=None, read=read)],
    )
    ctx = Context.from_message(message, None)
    assert [(each.name, each.size, each.content_type) for each in ctx.attachments] == [("plan.xlsx", 2048, "")]
    assert asyncio.run(ctx.attachments[0].read()) == b"x"
    message.attachments = []
    assert Context.from_message(message, None).attachments == ()


def test_the_router_is_told_a_file_is_attached_by_its_name_only_and_nothing_when_there_is_none():
    assert routing.user_turn("hello") == "The message to route:\nhello"
    turn = routing.user_turn("here is my plan", attached=("plan.csv", "notes.txt"))
    assert turn == "Sent with the message, as a file: plan.csv, notes.txt\n\nThe message to route:\nhere is my plan"
