"""The contract for what a task can be asked to do, and the checking of what Claude returns (core/actions.py)."""
import pytest

from core import actions
from core.actions import BOOLEAN, INTEGER, ITEMS, LIST, Action, Entry, Field, Invalid, Proposal


async def prepare(request, data, guessed):
    return Proposal(lines=("x",), data=data)


async def apply(request, data):
    return "saved"


async def run(request, data, guessed):
    return "done"


async def verify(request, data):
    return ""


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
    verify=verify,
)
SHOW = Action("thing_show", "Show the things.", needs_card=False, run=run)
ENTRY = Entry("things", "📦", "Only for things.", ("add a thing", "show my things"), (ADD, SHOW))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
def test_an_actions_schema_is_strict_and_always_has_guessed():
    schema = actions.schema(ADD)
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["name", "count", "times", "kind", "days", "urgent", "guessed", "not_included"]
    assert schema["required"] == ["name", "guessed", "not_included"]
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["times"] == {"type": "array", "items": {"type": "string"}, "description": "When."}
    assert schema["properties"]["kind"]["enum"] == ["fixed", "interval"]
    assert schema["properties"]["days"]["items"]["enum"] == ["mon", "tue"]
    assert schema["properties"]["guessed"]["items"] == {"type": "string"}, "a guess may name a place in a list: items[2].quantity"
    assert "not a guess" in schema["properties"]["guessed"]["description"], "a default is never listed"
    assert "word for word" in schema["properties"]["not_included"]["description"]


def test_an_action_with_no_fields_still_has_guessed():
    schema = actions.schema(SHOW)
    assert list(schema["properties"]) == ["guessed", "not_included"] and schema["required"] == ["guessed", "not_included"]


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
    assert tuple(actions.validate(SHOW, {})) == ({}, frozenset())
    assert actions.validate(SHOW, {}).not_included == ()


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
        (entry(actions=(Action("thing_add", "", prepare=prepare, apply=apply, verify=verify),)), "has no description for Claude"),
        (entry(actions=(Action("none", "Nothing.", needs_card=False, run=run),)), "needs a name of its own"),
        (entry(actions=(Action("a", "A.", (Field("x", "X.", "date"),), needs_card=False, run=run),)), "unknown type 'date'"),
        (entry(actions=(Action("a", "A.", (Field("guessed", "G."),), needs_card=False, run=run),)), "a field can't be called that"),
        (entry(actions=(Action("a", "A.", (Field("not_included", "N."),), needs_card=False, run=run),)), "a field can't be called that"),
        (entry(actions=(Action("a", "A.", (Field("items", "I.", "items"),), needs_card=False, run=run),)), "needs `item_fields`"),
        (entry(actions=(Action("a", "A.", (Field("x", "X.", item_fields=(Field("y", "Y."),)),), needs_card=False, run=run),)), "is not a list of items"),
        (entry(actions=(Action("a", "A.", (Field("items", "I.", "items", item_fields=(Field("y", "Y.", "list"),)),), needs_card=False, run=run),)), "must be text, a number or yes/no"),
        (entry(actions=(Action("a", "A.", (Field("x", "X."), Field("x", "X again.")), needs_card=False, run=run),)), "two fields with the same name"),
        (entry(actions=(Action("a", "A.", (Field("n", "N.", INTEGER, choices=("1",)),), needs_card=False, run=run),)), "which only text can have"),
        (entry(actions=(Action("a", "A.", (Field("x", ""),), needs_card=False, run=run),)), "field x has no description"),
    ],
)
def test_what_is_missing_from_the_contract_is_named(broken, problem):
    assert any(problem in found for found in actions.problems([broken])), actions.problems([broken])


def test_two_tasks_cannot_share_an_action_or_a_name():
    other = entry(name="others", actions=(Action("thing_add", "Add.", prepare=prepare, apply=apply, verify=verify),))
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
    names = [found.name for found in actions.catalogue()]
    assert "timers" in names and not {"shopping", "packing"} & set(names), "the real tasks, and never a demo one"
    assert registry.problems() == []


def test_on_the_dev_database_the_two_demo_tasks_are_in_the_catalogue(monkeypatch):
    from core import config
    from tasks import registry

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    registry.load()
    names = [found.name for found in actions.catalogue()]
    assert {"timers", "pills", "bugs"} <= set(names) and not {"shopping", "packing"} & set(names), (
        "the demo lists are test fixtures (tests/demo.py): the bot offers them on neither database"
    )
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
    names = [found.name for found in actions.catalogue()]
    assert "things" in names and "broken" not in names
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


# ---------------------------------------------------------------------------
# Lists of items: one request can hold several things
# ---------------------------------------------------------------------------
BUY = Action(
    "thing_buy",
    "Buy things.",
    (
        Field(
            "items", "Everything to buy.", ITEMS, required=True,
            item_fields=(Field("item", "What.", required=True), Field("quantity", "How many.", INTEGER), Field("shop", "Where.", choices=("a", "b"))),
        ),
    ),
    needs_card=False,
    run=run,
)


def test_a_list_of_items_is_an_array_of_strict_objects():
    items = actions.schema(BUY)["properties"]["items"]
    assert items["type"] == "array" and items["items"]["additionalProperties"] is False
    assert list(items["items"]["properties"]) == ["item", "quantity", "shop"] and items["items"]["required"] == ["item"]
    assert items["items"]["properties"]["shop"]["enum"] == ["a", "b"]


def test_every_item_comes_back_in_order_with_what_was_left_out_left_out():
    checked = actions.validate(BUY, {"items": [{"item": " honey "}, {"item": "jam", "quantity": None}, {"item": "eggs", "quantity": 5}], "guessed": [], "not_included": []})
    assert checked.data == {"items": [{"item": "honey"}, {"item": "jam"}, {"item": "eggs", "quantity": 5}]}
    assert checked.not_included == () and checked.guessed == frozenset()


def test_a_guess_names_its_place_in_the_list():
    checked = actions.validate(BUY, {"items": [{"item": "honey"}, {"item": "eggs", "quantity": 3}], "guessed": ["items[1].quantity", "items[0].quantity", "items[7].item", "nonsense"]})
    assert checked.guessed == frozenset({"items[1].quantity"}), "a guess about what isn't there says nothing"
    assert actions.is_guessed(checked.guessed, "items", 1, "quantity")
    assert not actions.is_guessed(checked.guessed, "items", 0, "quantity") and not actions.is_guessed(checked.guessed, "items", 1, "item")
    assert actions.is_guessed(frozenset({"items[1]"}), "items", 1, "quantity"), "the whole item covers its fields"
    assert actions.is_guessed(frozenset({"times"}), "times", 0) and actions.is_guessed(frozenset({"times[0]"}), "times", 0)
    assert actions.path("items", 2, "quantity") == "items[2].quantity" and actions.path("times", 0) == "times[0]" and actions.path("kind") == "kind"


def test_an_item_that_does_not_fit_is_left_out_and_named_never_dropped_unseen_and_never_sinks_the_rest():
    checked = actions.validate(
        BUY,
        {"items": [{"item": "honey"}, {"quantity": 2}, {"item": "jam", "quantity": "two"}, {"item": "eggs", "shop": "z"}, "bread", {"item": "milk", "colour": "white"}],
         "guessed": ["items[0].quantity", "items[5].item"], "not_included": [" a pony "]},
    )
    assert checked.data == {"items": [{"item": "honey"}]}
    assert checked.not_included == ("a pony", "2", "jam, two", "eggs, z", "bread", "milk, white"), "what the user asked for, in their terms"
    assert checked.guessed == frozenset(), "the places no longer line up, so no guess is pinned on the wrong item"


def test_what_claude_says_it_left_out_is_kept_for_the_user():
    checked = actions.validate(BUY, {"items": [{"item": "milk"}], "guessed": [], "not_included": ["remind me to call mum at 5", "  "]})
    assert checked.not_included == ("remind me to call mum at 5",)


@pytest.mark.parametrize(
    "raw, reason",
    [
        ({"guessed": []}, "`items` is missing"),
        ({"items": [], "guessed": []}, "`items` is empty"),
        ({"items": "honey", "guessed": []}, "`items` must be a list of items"),
        ({"items": [{"quantity": 2}], "guessed": []}, "`items` has no item that can be used"),
        ({"items": [{"item": "honey"}], "guessed": [], "not_included": "x"}, "`not_included` must be a list"),
    ],
)
def test_a_list_with_nothing_usable_in_it_is_refused(raw, reason):
    with pytest.raises(Invalid, match=reason):
        actions.validate(BUY, raw)


def test_a_default_is_not_a_guess_and_is_never_flagged():
    assert "is not a guess and is never flagged" in actions.flag.__doc__
    assert actions.flag("× 1", False) == "× 1"


# ---------------------------------------------------------------------------
# Changes to a list: add, set, remove. Code does the sums
# ---------------------------------------------------------------------------
def item(name, quantity=None, change=None):
    made = {"item": name}
    if quantity is not None:
        made["quantity"] = quantity
    if change:
        made["change"] = change
    return made


def test_the_change_field_is_the_same_for_every_list_and_tells_claude_to_do_no_sums():
    field = actions.change_field()
    assert (field.name, field.choices, field.required) == ("change", ("add", "set", "remove"), False)
    assert "Never work a total out yourself" in field.description


def test_a_first_mention_stands_as_it_is_and_add_is_assumed():
    assert actions.merge_items([], [item("milk", 3), item("eggs", 7, "set")]) == (
        [item("milk", 3, "add"), item("eggs", 7, "set")], [],
    )


def test_adding_to_what_a_card_adds_is_the_sum_and_one_is_assumed_when_no_amount_is_given():
    assert actions.merge_items([item("milk", 2, "add")], [item("milk", 3)])[0] == [item("milk", 5, "add")]
    assert actions.merge_items([item("milk", 2, "add")], [item("milk")])[0] == [item("milk", 3, "add")]


def test_adding_to_what_a_card_sets_is_still_a_set_of_the_sum():
    assert actions.merge_items([item("eggs", 7, "set")], [item("eggs", 2)])[0] == [item("eggs", 9, "set")]


def test_setting_replaces_whatever_was_pending():
    assert actions.merge_items([item("milk", 5, "add"), item("jam", 1, "add")], [item("milk", 2, "set")])[0] == [
        item("milk", 2, "set"), item("jam", 1, "add"),
    ]


def test_removing_what_is_only_on_the_card_takes_it_off_the_card():
    assert actions.merge_items([item("milk", 1, "add"), item("jam", 1, "add")], [item("jam", change="remove")], exists=lambda name: False) == (
        [item("milk", 1, "add")], [],
    )


def test_removing_what_is_saved_is_a_removal_to_confirm_whatever_the_card_was_doing_to_it():
    saved = lambda name: name == "jam"  # noqa: E731
    assert actions.merge_items([], [item("jam", change="remove")], exists=saved) == ([item("jam", change="remove")], [])
    assert actions.merge_items([item("jam", 3, "add")], [item("jam", change="remove")], exists=saved) == ([item("jam", change="remove")], [])


def test_removing_what_is_nowhere_is_reported_and_changes_nothing():
    assert actions.merge_items([item("milk", 1, "add")], [item("tea", change="remove")], exists=lambda name: False) == (
        [item("milk", 1, "add")], ["tea"],
    )


def test_adding_again_after_a_removal_stands_as_a_fresh_add():
    assert actions.merge_items([item("jam", change="remove")], [item("jam", 2)])[0] == [item("jam", 2, "add")]


def test_names_are_matched_by_the_tasks_own_rule_and_kept_as_typed_last():
    same = lambda one, other: one.lower().rstrip("s") == other.lower().rstrip("s")  # noqa: E731
    assert actions.merge_items([item("Eggs", 5, "add")], [item("egg", 1)], same=same)[0] == [item("egg", 6, "add")]


def test_a_list_without_amounts_merges_its_other_fields():
    pending = [{"item": "socks", "bag": "checked", "change": "add"}]
    assert actions.merge_items(pending, [{"item": "socks", "bag": "carry-on", "change": "set"}], amount=None)[0] == [
        {"item": "socks", "bag": "carry-on", "change": "set"},
    ]
    assert actions.merge_items(pending, [{"item": "hat"}], amount=None)[0] == [*pending, {"item": "hat", "change": "add"}]


def test_a_card_sent_back_whole_is_a_restatement_not_one_more_of_each():
    # Seen in the live eval on 2026-10-09: "add milk too" came back as the whole card and milk
    pending = [item("honey", 1, "add"), item("eggs", 5, "add")]
    assert actions.merge_items(pending, [item("honey", 1), item("eggs", 5), item("milk", 1)])[0] == [*pending, item("milk", 1, "add")]
    # ...and with a change in it, what differs is the new amount, never added on top
    assert actions.merge_items(pending, [item("honey", 1), item("eggs", 6)])[0] == [item("honey", 1, "add"), item("eggs", 6, "add")]


def test_one_item_coming_back_is_never_a_restatement():
    assert actions.merge_items([item("milk", 2, "add")], [item("milk", 2)])[0] == [item("milk", 4, "add")]


def test_a_one_line_card_coming_back_beside_something_new_is_a_restatement_too():
    # QA 2026-10-10: a card of butter, "and jam" came back as butter and jam, and butter was added twice
    pending = [item("butter", 1, "add")]
    assert actions.merge_items(pending, [item("butter", 1), item("jam")], said="and jam")[0] == [item("butter", 1, "add"), item("jam", change="add")]
    assert actions.merge_items(pending, [item("butter", 1, "add"), item("jam")])[0] == [item("butter", 1, "add"), item("jam", change="add")], "with no message to go by as well"
    # a total worked out by Claude is the amount it should be, not more on top
    assert actions.merge_items([item("milk", 3, "add")], [item("milk", 3), item("lemons", 2)], said="plus 2 lemons")[0] == [
        item("milk", 3, "add"), item("lemons", 2, "add"),
    ]


def test_what_the_message_names_is_never_taken_as_a_restatement():
    pending = [item("butter", 1, "add")]
    assert actions.merge_items(pending, [item("butter", 1), item("jam")], said="and another butter and jam")[0] == [
        item("butter", 2, "add"), item("jam", change="add"),
    ]
    both = [item("milk", 1, "add"), item("eggs", 5, "add")]
    assert actions.merge_items(both, [item("milk", 3), item("eggs", 2)], said="add 3 milk and 2 more eggs")[0] == [
        item("milk", 4, "add"), item("eggs", 7, "add"),
    ]
    same = lambda one, other: one.rstrip("s") == other.rstrip("s")  # noqa: E731
    assert actions.merge_items([item("eggs", 5, "add")], [item("eggs", 1), item("jam")], same=same, said="another egg, and jam")[0][0] == item("eggs", 6, "add")


def test_a_set_or_a_removal_that_comes_back_with_others_still_counts():
    pending = [item("milk", 1, "add"), item("bread rolls", 1, "add")]
    assert actions.merge_items(pending, [item("milk", 1), item("bread rolls", 2, "set")], said="make it 2")[0] == [
        item("milk", 1, "add"), item("bread rolls", 2, "set"),
    ]
    assert actions.merge_items(pending, [item("milk", change="remove"), item("jam")], said="jam instead of that", exists=lambda name: False)[0] == [
        item("bread rolls", 1, "add"), item("jam", change="add"),
    ]


# ---------------------------------------------------------------------------
# A task's state for extraction is capped
# ---------------------------------------------------------------------------
def test_a_short_state_is_sent_whole_a_line_each():
    state = actions.State("On the shopping list now", ("eggs × 5", "milk × 2"))
    assert actions.shown_state(state, "make the eggs 7") == ("On the shopping list now:\n- eggs × 5\n- milk × 2", 2, 2)


def test_an_empty_state_says_so_in_a_line():
    assert actions.shown_state(actions.State("On the shopping list now"), "add milk") == ("On the shopping list now: nothing", 0, 0)


def test_a_long_state_is_cut_to_the_limit_with_what_the_message_names_first():
    lines = tuple(f"thing {number} × 1" for number in range(60)) + ("eggs × 5", "oat milk × 2")
    text, sent, total = actions.shown_state(actions.State("On the list now", lines), "make the egg 7 and add milk", limit=5)
    assert (sent, total) == (5, 62)
    assert text.splitlines() == [
        "On the list now:", "- thing 0 × 1", "- thing 1 × 1", "- thing 2 × 1", "- eggs × 5", "- oat milk × 2",
        "(and 57 more not shown: what the message names is among the lines above if it is there at all)",
    ], "the two it could mean, singular or plural, then the first of the rest, in the task's order"


def test_the_limit_holds_however_many_lines_match():
    lines = tuple(f"milk {number}" for number in range(50))
    assert actions.shown_state(actions.State("Now", lines), "milk")[1:] == (actions.STATE_LINES, 50)


def test_a_state_given_as_plain_text_is_capped_too():
    assert actions.shown_state("t1: tea · running\nt2: eggs · paused", "stop the tea") == ("t1: tea · running\nt2: eggs · paused", 2, 2)
    text, sent, total = actions.shown_state("Timers:\n" + "\n".join(f"t{number}: x" for number in range(30)), "stop t29", limit=3)
    assert (sent, total) == (3, 30) and text.startswith("Timers:\n- t0: x") and "- t29: x" in text and "(and 27 more not shown" in text


def test_a_guess_named_by_an_items_field_alone_is_put_on_the_item():
    # Seen in the live eval on 2026-10-10: "a few minutes" came back with guessed ["duration"]
    one = actions.validate(BUY, {"items": [{"item": "eggs", "quantity": 3}], "guessed": ["quantity"]})
    assert one.guessed == frozenset({"items[0].quantity"})
    several = actions.validate(BUY, {"items": [{"item": "eggs", "quantity": 3}, {"item": "jam"}, {"item": "milk", "quantity": 2}], "guessed": ["quantity"]})
    assert several.guessed == frozenset({"items[0].quantity", "items[2].quantity"}), "each item that has it: which one is not known"
    assert actions.validate(BUY, {"items": [{"item": "eggs"}], "guessed": ["nonsense"]}).guessed == frozenset()


# ---------------------------------------------------------------------------
# A confirmation needs the change read back; references and stated values are the code's
# ---------------------------------------------------------------------------
def test_an_action_that_saves_must_say_how_the_change_is_read_back():
    unchecked = Action("thing_add", "Add a thing.", prepare=prepare, apply=apply)
    assert actions.problems([entry(actions=(unchecked, SHOW))]) == [
        "things: action thing_add saves with `apply`, so it needs `verify` (the change read back before it is confirmed)"
    ]


@pytest.mark.parametrize("value, expected", [("@that", True), ("@THAT ", True), ("@it", True), ("that", False), ("milk", False), (3, False), (None, False)])
def test_what_counts_as_a_reference(value, expected):
    assert actions.is_reference(value) is expected


def test_a_reference_is_given_the_name_of_what_was_mentioned_last():
    changes = [item("@that", 2, "set"), item("jam")]
    assert actions.point_at(changes, "item", "bread rolls") == [item("bread rolls", 2, "set"), item("jam")]
    assert actions.point_at([item("jam")], "item", None) == [item("jam")], "nothing to resolve: nothing is needed"


def test_a_reference_with_nothing_it_could_mean_is_said_never_guessed():
    from core.errors import UserError

    with pytest.raises(UserError, match="I can't tell what “it” is"):
        actions.point_at([item("@that", 2, "set")], "item", None)


@pytest.mark.parametrize(
    "data, guess, said, still_a_guess",
    [
        ({"items": [{"item": "eggs", "quantity": 3}]}, "items[0].quantity", "add 3 eggs", False),
        ({"items": [{"item": "eggs", "quantity": 3}]}, "items[0].quantity", "add three eggs", False),
        ({"items": [{"item": "eggs", "quantity": 3}]}, "items[0].quantity", "add a few eggs", True),
        ({"items": [{"item": "eggs", "quantity": 3}]}, "items[0].quantity", "add eggs to list 30", True),
        ({"pills": [{"name": "Zinc", "times": "9pm"}]}, "pills[0].times", "add zinc at 9pm", False),
        ({"pills": [{"name": "Zinc", "notes": "with food"}]}, "pills[0].notes", "Add zinc, With Food", False),
        ({"pills": [{"name": "Zinc", "times": "9am"}]}, "pills[0].times", "add zinc in the morning", True),
        ({"which": "t12"}, "which", "pause the tea timer", True),
        ({"items": [{"item": "eggs"}]}, "items[0]", "add eggs", True),
    ],
)
def test_a_value_said_in_so_many_words_is_never_a_guess(data, guess, said, still_a_guess):
    assert (guess in actions.unstated(data, frozenset({guess}), said)) is still_a_guess


# ---------------------------------------------------------------------------
# A name Claude works out for a pronoun is put back for the code (gap G8)
# ---------------------------------------------------------------------------
WHICH = Action(
    "thing_change", "Change a thing.",
    (Field("which", "Which.", required=True), Field("action", "What.", choices=("pause", "cancel"), required=True)),
    needs_card=False, run=run,
)
TIMERS = 'Timers now:\n- t12: "tea" · running, 4m left · in this channel\n- t14: "dinner" · paused with 12m left'


@pytest.mark.parametrize(
    "said, which, expected",
    [
        ("give it 2 more", "t12", "@that"),
        ("pause that one", "t14", "@that"),
        ("pause the tea timer, it is boiling over", "t12", "t12"),
        ("pause dinner", "t14", "t14"),
        ("pause t14, I need it later", "t14", "t14"),
        ("cancel them", "all", "all"),
        ("cancel it", "@that", "@that"),
        ("cancel tea and dinner, both of them", "t12 t14", "t12 t14"),
    ],
)
def test_an_id_is_kept_only_if_the_message_names_what_it_is(said, which, expected):
    data, back = actions.as_references(WHICH, {"which": which, "action": "pause"}, said, TIMERS)
    assert data["which"] == expected and data["action"] == "pause"
    assert back == ([which] if expected != which else [])


def test_in_a_list_the_one_item_the_message_does_not_name_is_the_pronoun():
    bread = {"items": [{"item": "bread rolls", "quantity": 2, "change": "set"}]}
    assert actions.as_references(BUY, bread, "make it 2")[0] == {"items": [{"item": "@that", "quantity": 2, "change": "set"}]}
    both = {"items": [{"item": "bread rolls", "quantity": 2}, {"item": "jam"}]}
    assert actions.as_references(BUY, both, "make it 2 and add jam")[0]["items"] == [{"item": "@that", "quantity": 2}, {"item": "jam"}]
    assert actions.as_references(BUY, both, "make the bread rolls 2 and add jam, I like it")[0] == both, "everything is named"
    assert actions.as_references(BUY, bread, "make the bread roll 2") == (bread, []), "no pronoun: nothing to put back"
    two = {"items": [{"item": "milk"}, {"item": "eggs"}]}
    assert actions.as_references(BUY, two, "add those") == (two, []), "two unnamed things: not plain which, so neither is touched"


def test_a_cards_kind_is_one_of_three_words_for_every_task():
    assert actions.KINDS == ("new", "change", "remove")


# ---------------------------------------------------------------------------
# Connecting and filler words are never "not included" (QA 2026-10-10)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("part", ["and", "And", "also", "plus", "too", "then", "please", "and also", "as well", "and then please", "thanks", "&", " , "])
def test_a_leftover_of_only_joining_words_is_not_worth_reporting(part):
    assert actions.is_filler(part)


@pytest.mark.parametrize("part", ["remind me to call mum at 5", "and book the dentist", "pack a hat", "socks", "please call mum"])
def test_a_leftover_that_is_a_request_or_content_is_reported(part):
    assert not actions.is_filler(part)


def test_what_claude_says_it_left_out_loses_its_filler_before_anyone_is_told():
    # Seen: "and socks to the packing list" gave "⚠️ Not included: and"
    raw = {"items": [{"item": "socks"}], "guessed": [], "not_included": ["and", "book the dentist", "please"]}
    assert actions.validate(BUY, raw).not_included == ("book the dentist",)
    assert actions.validate(BUY, {"items": [{"item": "socks"}], "guessed": [], "not_included": ["and"]}).not_included == ()
