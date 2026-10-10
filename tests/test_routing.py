"""The router and extraction: what Claude is sent, and how what it returns is read
(core/routing.py, core/extraction.py). Nothing here goes near the network."""
import asyncio

import pytest

from core import actions, extraction, llm, routing
from core.extraction import OpenCard
from core.routing import Route
from evals import fixtures
from tasks.lab import demo

ENTRIES = demo.ENTRIES
NAMES = [entry.name for entry in ENTRIES]
SHOPPING = demo.SHOPPING


def _every_entry():
    """The demo tasks and the real ones: every fixture file is replayed."""
    from tasks import registry

    registry.load()
    return [*demo.ENTRIES, *[entry for entry in actions.catalogue() if entry.name not in NAMES]]


ALL = _every_entry()
ALL_NAMES = [entry.name for entry in ALL]


@pytest.fixture
def claude(monkeypatch):
    """A stand-in for the one request: gives back what the test scripts, and keeps what it was sent."""
    sent = []

    def install(*answers):
        queue = list(answers)

        async def call_tool(system, user, tools, *, choice, purpose, task="", max_tokens=600):
            sent.append(dict(system=system, user=user, tools=tools, choice=choice, purpose=purpose, task=task))
            return queue.pop(0)

        monkeypatch.setattr(llm, "call_tool", call_tool)
        return sent

    return install


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------
def test_the_catalogue_is_names_only_for_lines_and_examples_and_nothing_else():
    text = routing.catalogue_text(ENTRIES)
    assert text.splitlines()[0] == "The tasks:"
    assert "- shopping: A demo shopping list" in text and "\"add milk to the shopping list\"" in text
    assert "- packing: A demo packing list" in text
    for action in SHOPPING.actions:
        assert action.name not in text, "the router never sees an action or a schema"
    assert "quantity" not in text


def test_the_routers_instructions_and_catalogue_are_one_cached_block():
    (block,) = routing.system_blocks(ENTRIES)
    assert block["cache_control"] == llm.CACHED
    assert block["text"].startswith(routing.RULES) and block["text"].endswith(routing.catalogue_text(ENTRIES))
    assert "by meaning, not by keywords" in block["text"] and "never a switch" in block["text"]
    assert routing.system_blocks(ENTRIES) == routing.system_blocks(ENTRIES), "fixed text, so it can be cached"


def test_the_router_can_only_name_tasks_in_the_catalogue():
    schema = routing.tool(ENTRIES)["input_schema"]
    assert schema["properties"]["tasks"]["items"]["enum"] == ["shopping", "packing"]
    assert schema["properties"]["confidence"]["enum"] == ["high", "tie"]
    assert schema["required"] == ["kind", "tasks", "confidence", "chat_part"] and schema["additionalProperties"] is False


def test_what_changes_goes_in_the_user_turn():
    turn = routing.user_turn("make it three", "a Shopping card", [("a", "b"), ("add milk", "card shown"), ("hm", "ok")])
    assert turn.endswith("The message to route:\nmake it three")
    assert "On screen, waiting for the user: a Shopping card" in turn
    assert "User: add milk\nBot: card shown" in turn and "User: a\n" not in turn, "the last two exchanges only"
    assert routing.user_turn("hello") == "The message to route:\nhello"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"kind": "task", "tasks": ["shopping"], "confidence": "high"}, Route(("shopping",))),
        ({"kind": "task", "tasks": ["shopping", "packing"], "confidence": "high"}, Route(("shopping", "packing"))),
        ({"kind": "task", "tasks": ["shopping", "packing"], "confidence": "tie"}, Route(("shopping", "packing"), tie=True)),
        ({"kind": "task", "tasks": ["shopping"], "confidence": "tie"}, Route(("shopping",))),  # a tie of one is no tie
        ({"kind": "task", "tasks": ["shopping", "shopping"], "confidence": "high"}, Route(("shopping",))),
        ({"kind": "chat", "tasks": [], "confidence": "high"}, Route()),
        ({"kind": "chat", "tasks": ["shopping"], "confidence": "high"}, Route()),  # chat wins
        ({"kind": "task", "tasks": [], "confidence": "high"}, Route()),
    ],
)
def test_what_the_router_returned_is_read_in_code(raw, expected):
    assert routing.parse(raw, NAMES) == expected


def test_a_message_for_a_task_may_also_hold_a_part_for_no_task():
    raw = {"kind": "task", "tasks": ["shopping"], "confidence": "high", "chat_part": " what's the capital of France "}
    route = routing.parse(raw, NAMES)
    assert route.tasks == ("shopping",) and route.chat_part == "what's the capital of France" and not route.chat
    # Left out, empty or not text: there is none
    for aside in ("", "   ", None, 5):
        assert routing.parse({**raw, "chat_part": aside}, NAMES).chat_part == ""
    assert routing.parse({"kind": "task", "tasks": ["shopping"], "confidence": "high"}, NAMES).chat_part == ""
    # A message that is all chat has no "part": the whole of it is answered
    assert routing.parse({"kind": "chat", "tasks": [], "confidence": "high", "chat_part": "hello"}, NAMES) == Route()
    assert "Every part of a message must be dealt with" in routing.RULES


@pytest.mark.parametrize(
    "raw, problem",
    [
        (None, "no tool call"),
        ({"kind": "task", "tasks": "shopping", "confidence": "high"}, "not a list"),
        ({"kind": "task", "tasks": ["pills"], "confidence": "high"}, "unknown task"),
    ],
)
def test_nonsense_from_the_router_is_chat_with_the_reason_kept(raw, problem):
    route = routing.parse(raw, NAMES)
    assert route.chat and problem in route.problem


def test_a_task_the_router_made_up_is_dropped_and_the_real_one_kept():
    route = routing.parse({"kind": "task", "tasks": ["pills", "shopping"], "confidence": "tie"}, NAMES)
    assert route.tasks == ("shopping",) and not route.tie and "pills" in route.problem


def test_routing_is_one_request_forced_to_the_route_tool(claude):
    sent = claude(("route", {"kind": "task", "tasks": ["packing"], "confidence": "high"}))
    route = asyncio.run(routing.route("pack my passport", ENTRIES, on_screen="", exchanges=[]))
    assert route == Route(("packing",))
    (request,) = sent
    assert request["choice"] == {"type": "tool", "name": "route"} and request["purpose"] == "router"
    assert [tool["name"] for tool in request["tools"]] == ["route"]
    assert "demo_pack_change" not in str(request), "no action reaches the router"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def test_extraction_is_given_one_tasks_actions_and_a_way_to_say_none():
    tools = extraction.tools(SHOPPING)
    assert [tool["name"] for tool in tools] == ["demo_shop_change", "demo_shop_list", "demo_shop_tick", "demo_shop_clear", "none"]
    assert tools[-1]["cache_control"] == llm.CACHED, "the definitions are fixed text too"
    assert not [tool for tool in tools if tool.get("strict")], "strict is off until measured as cheap"
    assert [tool["name"] for tool in extraction.tools(SHOPPING, follow_up=True)][-2:] == ["none", "not_this"]
    assert all(tool.get("strict") for tool in extraction.tools(SHOPPING, strict=True)[:4])
    assert "demo_pack_change" not in str(tools), "never another task's"


def test_extraction_is_told_to_guess_and_flag_never_to_ask_and_to_write_nothing():
    text = extraction.system_blocks(SHOPPING)[0]["text"]
    assert "Never ask a question" in text and "best guess" in text and "`guessed`" in text
    assert "Write no text" in text
    assert "takes ALL of them" in text and "Never keep only the first" in text, "several things in one request"
    assert "Nothing may be dropped" in text and "`not_included`" in text
    assert "is NOT a guess" in text and "Never list a default" in text, "a default is not flagged"
    assert "A card is open" not in text
    follow_up = extraction.system_blocks(SHOPPING, follow_up=True)[0]["text"]
    assert "A card is open" in follow_up and "`not_this`" in follow_up
    assert "return ONLY the changes THIS message makes" in follow_up and "Do no sums" in follow_up
    assert "They are KEPT by the bot's code: they are not yours to send back" in follow_up
    assert '"and jam", "also jam", "plus jam", "jam too" and "jam as well" are jam alone' in follow_up
    assert "goes back as it stands on the card" in follow_up, "every field that is not a list of items"
    assert "do NOT work out which thing is meant: put `@that` where its name or id would go" in text, "pronouns are the code's"
    assert "is copied exactly and is never a guess" in text and "it never overrides what they said" in text, "what is stated wins"
    after_list = extraction.system_blocks(SHOPPING, after_list=True)[0]["text"]
    assert "has just been shown this task's list" in after_list and "`not_this`" in after_list and "A card is open" not in after_list
    assert extraction.system_blocks(SHOPPING)[0]["cache_control"] == llm.CACHED


def test_the_state_and_the_open_card_go_in_the_user_turn():
    card = OpenCard("demo_shop_change", {"items": [{"item": "eggs", "quantity": 3}]}, ("items[0].quantity",), "add a few eggs")
    turn = extraction.user_turn("make it 6", "On the list: bread", card)
    assert "The task's state, read just now:\nOn the list: bread" in turn
    assert "- `items`, the lines already on the card (kept by the bot's code: do NOT send them back):\n  1. item: eggs, quantity: 3\n" in turn
    assert "- data:" not in turn and "- still guessed: items[0].quantity" in turn
    assert "- what the user has said about it, oldest first: add a few eggs" in turn
    assert "The message:\nmake it 6\n\nAnswer with the changes this message makes and nothing else." in turn, "said last"
    plain = extraction.user_turn("make it 9pm", card=OpenCard("thing_set", {"name": "alarm", "time": "9:00 am"}))
    assert '- data: {"name": "alarm", "time": "9:00 am"}' in plain and plain.endswith("The message:\nmake it 9pm"), "no list: as before"
    assert extraction.user_turn("add milk") == "The message:\nadd milk"
    redirected = extraction.user_turn("actually the shopping list", earlier="add socks")
    assert "Just before this, the user asked: add socks" in redirected
    assert "never an item, a name or any other value" in redirected and redirected.endswith("The message:\nactually the shopping list")


def test_a_call_that_fits_is_the_action_its_data_and_its_guesses():
    called = ("demo_shop_change", {"items": [{"item": "honey"}, {"item": "eggs", "quantity": 3}], "guessed": ["items[1].quantity"], "not_included": ["and a pony"]})
    found = extraction.read(SHOPPING, called)
    assert found.fitted and found.action.name == "demo_shop_change"
    assert found.data == {"items": [{"item": "honey"}, {"item": "eggs", "quantity": 3}]}
    assert found.guessed == frozenset({"items[1].quantity"}) and found.not_included == ("and a pony",)
    assert found.as_log() == {
        "task": "shopping", "action": "demo_shop_change", "data": found.data, "guessed": ["items[1].quantity"], "not_included": ["and a pony"],
    }


@pytest.mark.parametrize(
    "called, reason",
    [
        (None, "no tool call"),
        (("none", {"reason": "not about shopping"}), "not about shopping"),
        (("demo_pack_change", {"items": [{"item": "socks"}], "guessed": []}), "not an action of shopping"),
        (("demo_shop_change", {"guessed": []}), "`items` is missing"),
        (("demo_shop_change", {"items": [{"quantity": 2}], "guessed": []}), "`items` has no item that can be used"),
        (("demo_shop_change", {"item": "milk", "guessed": []}), "not fields of demo_shop_change: item"),
        (("not_this", {"reason": "x"}), "x"),  # only a follow-up may say so
    ],
)
def test_a_call_that_does_not_fit_is_nothing_fitted_with_the_reason_kept(called, reason):
    found = extraction.read(SHOPPING, called)
    assert not found.fitted and not found.not_this and reason in found.reason
    assert found.as_log()["action"] == "none"


def test_in_a_follow_up_not_this_means_the_message_is_about_something_else():
    found = extraction.read(SHOPPING, ("not_this", {"reason": "a question about the weather"}), follow_up=True)
    assert found.not_this and not found.fitted and found.as_log()["action"] == "not_this"


def test_extraction_is_one_request_that_must_call_a_tool(claude):
    sent = claude(("demo_shop_change", {"items": [{"item": "lemons", "quantity": 3}], "guessed": []}))
    found = asyncio.run(extraction.extract(SHOPPING, "add 3 lemons", state="On the list: bread"))
    assert found.data == {"items": [{"item": "lemons", "quantity": 3}]}
    (request,) = sent
    assert request["choice"] == {"type": "any"} and (request["purpose"], request["task"]) == ("extraction", "shopping")
    assert "On the list: bread" in request["user"]


# ---------------------------------------------------------------------------
# The fixtures, replayed from what the real API last returned
# ---------------------------------------------------------------------------
ROUTERS, EXTRACTIONS = fixtures.load()


def test_there_are_fixtures_for_each_demo_task_and_for_the_traps():
    assert {fixture.file for fixture in ROUTERS} >= {"general", "shopping", "packing"}
    assert {fixture.task for fixture in EXTRACTIONS} >= {"shopping", "packing"}
    assert any(fixture.chat for fixture in ROUTERS) and any(fixture.tie for fixture in ROUTERS)
    mixed = [fixture for fixture in ROUTERS if fixture.also_chat]
    assert any(len(fixture.tasks) == 1 for fixture in mixed), "chat and a task"
    assert any(len(fixture.tasks) == 2 for fixture in mixed), "chat and two tasks"
    assert any(len(fixture.tasks) == 2 and not fixture.also_chat and not fixture.tie for fixture in ROUTERS), "two tasks"
    assert any(fixture.card for fixture in EXTRACTIONS), "a follow-up"
    assert any(fixture.moved for fixture in EXTRACTIONS), "a card moved to another task"
    assert any(fixture.after_list for fixture in EXTRACTIONS), "a message straight after a list"
    assert any(fixture.left_out for fixture in EXTRACTIONS), "something that can't go on the card"
    several = [fixture for fixture in EXTRACTIONS if len(fixture.data.get("items", [])) >= 5]
    assert several and all(fixture.left_out is False or fixture.moved or fixture.card for fixture in several)
    assert any(fixture.action == "none" for fixture in EXTRACTIONS) and any(fixture.action == "not_this" for fixture in EXTRACTIONS)


@pytest.mark.parametrize("fixture", [f for f in ROUTERS if not set(f.tasks) - set(ALL_NAMES)], ids=lambda f: f.name)
def test_router_fixture(fixture):
    if fixture.recorded is None:
        pytest.skip("not recorded yet: python -m evals.live --live --dev --record")
    route = fixtures.settled(fixture, routing.parse(fixture.recorded, ALL_NAMES), ALL)
    problem = fixtures.router_problem(fixture, route)
    # A known miss is replayed (it must still be read without error) but not judged:
    # the model gives it differently from one run to the next
    assert fixture.known_miss or not problem, problem


@pytest.mark.parametrize("fixture", [f for f in EXTRACTIONS if f.task in ALL_NAMES], ids=lambda f: f.name)
def test_extraction_fixture(fixture):
    if fixture.recorded is None:
        pytest.skip("not recorded yet: python -m evals.live --live --dev --record")
    entry = next(entry for entry in ALL if entry.name == fixture.task)
    found = extraction.read(entry, tuple(fixture.recorded), follow_up=fixture.card is not None or fixture.after_list)
    problem = fixtures.extraction_problem(fixture, found)
    # A known miss is replayed (it must still be read without error) but not judged:
    # the model gives it differently from one run to the next
    assert fixture.known_miss or not problem, problem


def test_a_fixture_is_judged_on_the_task_the_action_every_item_and_the_guesses():
    lemons = {"items": [{"item": "Lemons", "quantity": 3}]}
    fixture = fixtures.ExtractionFixture("x", "shopping", "add 3 lemons", "demo_shop_change", lemons, [])

    def read(*items, guessed=(), not_included=()):
        return extraction.read(SHOPPING, ("demo_shop_change", {"items": list(items), "guessed": list(guessed), "not_included": list(not_included)}))

    assert fixtures.extraction_problem(fixture, read({"item": "lemons", "quantity": 3})) == "", "case is not what is being tested"
    assert "expected" in fixtures.extraction_problem(fixture, read({"item": "lemons", "quantity": 2}))
    assert "guessed ['items[0].quantity'], expected []" in fixtures.extraction_problem(
        fixture, read({"item": "lemons", "quantity": 3}, guessed=["items[0].quantity"])
    )
    other = extraction.read(SHOPPING, ("demo_shop_list", {"guessed": []}))
    assert "expected demo_shop_change, got demo_shop_list" in fixtures.extraction_problem(fixture, other)

    # An item dropped, or one too many, is a miss; a default spelled out is not
    two = fixtures.ExtractionFixture("x", "shopping", "add butter and jam", "demo_shop_change", {"items": [{"item": "butter"}, {"item": "jam"}]}, left_out=False)
    assert fixtures.extraction_problem(two, read({"item": "butter"}, {"item": "jam", "quantity": 1})) == ""
    assert "expected" in fixtures.extraction_problem(two, read({"item": "butter"}))
    assert "expected" in fixtures.extraction_problem(two, read({"item": "butter"}, {"item": "jam"}, {"item": "bread"}))
    assert "reported as left out" in fixtures.extraction_problem(two, read({"item": "butter"}, {"item": "jam"}, not_included=["x"]))
    must = fixtures.ExtractionFixture("x", "shopping", "add milk and call mum", "demo_shop_change", {"items": [{"item": "milk"}]}, left_out=True)
    assert "expected something reported as left out" in fixtures.extraction_problem(must, read({"item": "milk"}))
    assert fixtures.extraction_problem(must, read({"item": "milk"}, not_included=["call mum"])) == ""

    # Letter for letter, when the fixture says so
    exact = fixtures.ExtractionFixture("x", "shopping", "add milks", "demo_shop_change", {"items": [{"item": "milks"}]}, exact=True)
    assert fixtures.extraction_problem(exact, read({"item": "milks"})) == "" and fixtures.extraction_problem(exact, read({"item": "Milks"})) != ""

    tie = fixtures.RouterFixture("x", "add socks", ["packing", "shopping"], tie=True)
    assert fixtures.router_problem(tie, Route(("shopping", "packing"), tie=True)) == ""
    assert "got ['packing']" in fixtures.router_problem(tie, Route(("packing",)))
    assert "expected a tie" in fixtures.router_problem(tie, Route(("shopping", "packing")))
    mixed = fixtures.RouterFixture("x", "capital of France, and add milk", ["shopping"], also_chat=True)
    assert fixtures.router_problem(mixed, Route(("shopping",), chat_part="capital of France")) == ""
    assert "expected a chat part as well" in fixtures.router_problem(mixed, Route(("shopping",)))
    plain = fixtures.RouterFixture("x", "hi, add eggs please", ["shopping"])
    assert "expected no chat part, got 'hi'" in fixtures.router_problem(plain, Route(("shopping",), chat_part="hi"))
    chat = fixtures.RouterFixture("x", "hello", chat=True)
    assert fixtures.router_problem(chat, Route()) == "" and "expected chat" in fixtures.router_problem(chat, Route(("shopping",)))


# ---------------------------------------------------------------------------
# Nothing to do, and destinations that are named
# ---------------------------------------------------------------------------
def test_a_message_that_needs_nothing_done_is_read_as_nothing():
    found = routing.parse({"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}, NAMES)
    assert found.nothing and not found.chat and found.tasks == ()
    assert routing.parse({"kind": "chat", "tasks": [], "confidence": "high", "chat_part": ""}, NAMES).chat
    with_task = routing.parse({"kind": "nothing", "tasks": ["shopping"], "confidence": "high", "chat_part": ""}, NAMES)
    assert with_task.tasks == ("shopping",) and not with_task.nothing, "a task named is never nothing"
    assert "kind nothing with no tasks: the bot then says nothing at all" in routing.RULES
    assert routing.tool(ENTRIES)["input_schema"]["properties"]["kind"]["enum"] == ["task", "chat", "nothing"]


@pytest.mark.parametrize(
    "said, expected",
    [
        ("add zinc to my pills", ["pills"]),
        ("put milk on the shopping list", ["shopping"]),
        ("add socks to the packing list", ["packing"]),
        ("take jam off my shopping list", ["shopping"]),
        ("Add eggs  to the Shopping List and a hat to the packing list", ["shopping", "packing"]),
        ("add a pill timer", []),
        ("add shopping bags", []),
        ("my pills are in the cupboard", []),
        ("what is on the list?", []),
    ],
)
def test_a_destination_is_only_what_is_named_as_one(said, expected):
    assert [entry.name for entry in routing.named_destinations(said, ALL)] == [name for name in ALL_NAMES if name in expected]


def test_a_named_destination_overrules_the_router_unless_the_router_agrees_and_adds_more():
    assert routing.with_named(Route(("shopping",)), ["pills"]) == Route(("pills",))
    assert routing.with_named(Route(), ["pills"]) == Route(("pills",)), "never chat"
    assert routing.with_named(Route(nothing=True), ["pills"]) == Route(("pills",)), "never nothing"
    assert routing.with_named(Route(("shopping", "packing"), tie=True), ["shopping"]) == Route(("shopping", "packing")), "never a tie"
    mixed = Route(("shopping", "packing"), chat_part="what is the capital of France?")
    assert routing.with_named(mixed, ["shopping"]) == mixed, "a message with several parts keeps its other parts"
    assert routing.with_named(Route(("timers",)), []) == Route(("timers",))


def test_a_fixture_can_expect_that_nothing_is_said():
    quiet = fixtures.RouterFixture("x", "note one", nothing=True)
    assert fixtures.router_problem(quiet, Route(nothing=True)) == ""
    assert "expected nothing to be said, got chat" in fixtures.router_problem(quiet, Route())
    assert "got nothing to be said" in fixtures.router_problem(fixtures.RouterFixture("x", "hello", chat=True), Route(nothing=True))


def test_every_task_with_fixtures_is_replayed_not_only_the_demo_ones():
    assert {"shopping", "packing", "timers", "bugs", "pills"} <= set(ALL_NAMES)
    assert {fixture.task for fixture in EXTRACTIONS} <= set(ALL_NAMES), "no fixture file is left out of the replay"


def test_the_router_is_told_that_only_questions_and_requests_get_words():
    assert "The bot replies in words only to questions and requests." in routing.RULES
    assert '"shopping is boring"' in routing.RULES and "Do not offer help in return for a remark." in routing.RULES
