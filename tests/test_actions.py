"""The contract for what a task can be asked to do, and the checking of what Claude returns (core/actions.py)."""
import pytest

from core import actions
from core.actions import BOOLEAN, INTEGER, LIST, Action, Entry, Field, Invalid, Proposal


async def prepare(request, data, guessed):
    return Proposal(lines=("x",), data=data)


async def apply(request, data):
    return "saved"


async def run(request, data, guessed):
    return "done"


ADD = Action(
    "thing_add",
    "Add a thing.",
    (
        Field("name", "Its name.", required=True),
        Field("count", "How many.", INTEGER),
        Field("times", "When.", LIST),
        Field("kind", "Which kind.", choices=("fixed", "interval")),
        Field("days", "Which days.", LIST, choices=("mon", "tue")),
        Field("urgent", "Whether it is urgent.", BOOLEAN),
    ),
    prepare=prepare,
    apply=apply,
)
SHOW = Action("thing_show", "Show the things.", needs_card=False, run=run)
ENTRY = Entry("things", "📦", "Only for things.", ("add a thing", "show my things"), (ADD, SHOW))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
def test_an_actions_schema_is_strict_and_always_has_guessed():
    schema = actions.schema(ADD)
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["name", "count", "times", "kind", "days", "urgent", "guessed"]
    assert schema["required"] == ["name", "guessed"]
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["times"] == {"type": "array", "items": {"type": "string"}, "description": "When."}
    assert schema["properties"]["kind"]["enum"] == ["fixed", "interval"]
    assert schema["properties"]["days"]["items"]["enum"] == ["mon", "tue"]
    assert schema["properties"]["guessed"]["items"]["enum"] == ["name", "count", "times", "kind", "days", "urgent"]


def test_an_action_with_no_fields_still_has_guessed():
    schema = actions.schema(SHOW)
    assert list(schema["properties"]) == ["guessed"] and schema["required"] == ["guessed"]


def test_an_action_as_a_tool_is_strict_only_when_asked():
    assert "strict" not in actions.tool(ADD)
    assert actions.tool(ADD, strict=True)["strict"] is True
    assert actions.tool(ADD)["name"] == "thing_add" and actions.tool(ADD)["description"] == "Add a thing."


# ---------------------------------------------------------------------------
# Checking what Claude returned
# ---------------------------------------------------------------------------
def test_what_fits_comes_back_as_data_and_the_guesses():
    data, guessed = actions.validate(ADD, {"name": " G ", "count": 10, "times": ["08:00"], "kind": "fixed", "guessed": ["times", "kind"]})
    assert data == {"name": "G", "count": 10, "times": ["08:00"], "kind": "fixed"}
    assert guessed == frozenset({"times", "kind"})


def test_an_optional_field_left_empty_is_left_out_so_not_said_differs_from_said():
    data, guessed = actions.validate(ADD, {"name": "G", "kind": "", "times": [], "count": None, "guessed": []})
    assert data == {"name": "G"} and guessed == frozenset()


def test_a_guess_about_a_field_that_is_not_there_says_nothing():
    _, guessed = actions.validate(ADD, {"name": "G", "guessed": ["times", "name", "nonsense"]})
    assert guessed == frozenset({"name"})


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("add G", "not an object"),
        ({"guessed": []}, "`name` is missing"),
        ({"name": "", "guessed": []}, "`name` is empty"),
        ({"name": "G", "colour": "red", "guessed": []}, "not fields of thing_add: colour"),
        ({"name": 5, "guessed": []}, "`name` must be string"),
        ({"name": "G", "count": "10", "guessed": []}, "`count` must be integer"),
        ({"name": "G", "count": True, "guessed": []}, "`count` must be integer"),
        ({"name": "G", "times": "08:00", "guessed": []}, "`times` must be a list of strings"),
        ({"name": "G", "times": [8], "guessed": []}, "`times` must be a list of strings"),
        ({"name": "G", "kind": "weekly", "guessed": []}, "which is not one of fixed, interval"),
        ({"name": "G", "days": ["mon", "sun"], "guessed": []}, "'sun', which is not one of mon, tue"),
        ({"name": "G", "urgent": "yes", "guessed": []}, "`urgent` must be boolean"),
        ({"name": "G", "guessed": "times"}, "`guessed` must be a list"),
    ],
)
def test_what_does_not_fit_the_schema_is_refused_whatever_the_api_promised(raw, reason):
    with pytest.raises(Invalid, match=reason):
        actions.validate(ADD, raw)


def test_guessed_may_be_left_out_altogether():
    assert actions.validate(SHOW, {}) == ({}, frozenset())


def test_a_guess_is_flagged_with_a_question_mark():
    assert actions.flag("`8:00 am`", True) == "`8:00 am` ❓"
    assert actions.flag("`8:00 am`", False) == "`8:00 am`"


# ---------------------------------------------------------------------------
# The contract every task must meet
# ---------------------------------------------------------------------------
def test_a_complete_entry_has_no_problems():
    assert actions.problems([ENTRY]) == []


def entry(**changes):
    values = dict(name="things", icon="📦", only_for="Only for things.", examples=("add a thing", "show my things"), actions=(ADD, SHOW))
    values.update(changes)
    return Entry(**values)


@pytest.mark.parametrize(
    "broken, problem",
    [
        (entry(icon=""), "things: needs an icon"),
        (entry(only_for=" "), "things: needs an \"only for\" line"),
        (entry(examples=("one",)), "things: needs 2 to 3 example phrases, not 1"),
        (entry(examples=("a", "b", "c", "d")), "things: needs 2 to 3 example phrases, not 4"),
        (entry(actions=()), "things: has no actions"),
        (entry(name="My Things"), "an entry's name is one lower-case word"),
        (entry(actions=(Action("thing_add", "Add.", prepare=prepare),)), "needs both `prepare` (the card) and `apply` (Save)"),
        (entry(actions=(Action("thing_show", "Show.", needs_card=False),)), "needs `run` (which writes the reply)"),
        (entry(actions=(Action("thing_add", "", prepare=prepare, apply=apply),)), "has no description for Claude"),
        (entry(actions=(Action("none", "Nothing.", needs_card=False, run=run),)), "needs a name of its own"),
        (entry(actions=(Action("a", "A.", (Field("x", "X.", "date"),), needs_card=False, run=run),)), "unknown type 'date'"),
        (entry(actions=(Action("a", "A.", (Field("guessed", "G."),), needs_card=False, run=run),)), "a field can't be called that"),
        (entry(actions=(Action("a", "A.", (Field("x", "X."), Field("x", "X again.")), needs_card=False, run=run),)), "two fields with the same name"),
        (entry(actions=(Action("a", "A.", (Field("n", "N.", INTEGER, choices=("1",)),), needs_card=False, run=run),)), "which only text can have"),
        (entry(actions=(Action("a", "A.", (Field("x", ""),), needs_card=False, run=run),)), "field x has no description"),
    ],
)
def test_what_is_missing_from_the_contract_is_named(broken, problem):
    assert any(problem in found for found in actions.problems([broken])), actions.problems([broken])


def test_two_tasks_cannot_share_an_action_or_a_name():
    other = entry(name="others", actions=(Action("thing_add", "Add.", prepare=prepare, apply=apply),))
    assert "others: action thing_add is also an action of things" in actions.problems([ENTRY, other])
    assert "things: two entries share this name" in actions.problems([ENTRY, ENTRY])


def test_the_catalogue_is_whatever_the_registry_set(monkeypatch):
    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue([ENTRY])
    assert actions.catalogue() == [ENTRY] and actions.entry("things") is ENTRY and actions.entry("pills") is None
    assert ENTRY.action("thing_show") is SHOW and ENTRY.action("nope") is None and ENTRY.title == "Things"
    assert ADD.field("count").type == INTEGER and ADD.field("nope") is None


# ---------------------------------------------------------------------------
# The registry builds the catalogue from the tasks
# ---------------------------------------------------------------------------
def test_on_the_live_database_the_router_is_offered_no_demo_task(monkeypatch):
    from core import config
    from tasks import registry

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    registry.load()
    assert actions.catalogue() == [], "no real task has moved to the router yet"
    assert registry.problems() == []


def test_on_the_dev_database_the_two_demo_tasks_are_in_the_catalogue(monkeypatch):
    from core import config
    from tasks import registry

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    registry.load()
    assert [found.name for found in actions.catalogue()] == ["shopping", "packing"]
    assert registry.problems() == []
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    registry.load()


def test_a_task_that_breaks_the_contract_is_reported_and_not_routed_to(monkeypatch):
    from tasks import registry
    from tasks.lab import task as lab

    broken = Entry("broken", "", "", (), (Action("x", "X.", needs_card=False),))
    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(type(lab), "entries", lambda self: [ENTRY, broken])
    registry.load()
    assert [found.name for found in actions.catalogue()] == ["things"]
    assert any(problem.startswith("routing: broken: needs an icon") for problem in registry.problems())
    monkeypatch.undo()
    registry.load()
    assert registry.problems() == []


def test_a_task_with_actions_is_one_entry_built_from_its_own_fields():
    from tasks.base import Task

    class Things(Task):
        name = "things"
        icon = "📦"
        only_for = "Only for things."
        examples = ("add a thing", "show my things")
        hint = "Try “add a thing”."

        def actions(self):
            return [SHOW]

    (found,) = Things().entries()
    assert (found.name, found.icon, found.only_for, found.examples, found.hint) == (
        "things", "📦", "Only for things.", ("add a thing", "show my things"), "Try “add a thing”.",
    )
    assert found.actions == (SHOW,) and found.live_state is not None
    assert Task().entries() == [], "a task with no actions is not offered to the router"
