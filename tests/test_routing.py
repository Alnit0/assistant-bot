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
    assert "demo_pack_add" not in str(request), "no action reaches the router"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def test_extraction_is_given_one_tasks_actions_and_a_way_to_say_none():
    tools = extraction.tools(SHOPPING)
    assert [tool["name"] for tool in tools] == ["demo_shop_add", "demo_shop_list", "demo_shop_tick", "demo_shop_clear", "none"]
    assert tools[-1]["cache_control"] == llm.CACHED, "the definitions are fixed text too"
    assert not [tool for tool in tools if tool.get("strict")], "strict is off until measured as cheap"
    assert [tool["name"] for tool in extraction.tools(SHOPPING, follow_up=True)][-2:] == ["none", "not_this"]
    assert all(tool.get("strict") for tool in extraction.tools(SHOPPING, strict=True)[:4])
    assert "demo_pack_add" not in str(tools), "never another task's"


def test_extraction_is_told_to_guess_and_flag_never_to_ask_and_to_write_nothing():
    text = extraction.system_blocks(SHOPPING)[0]["text"]
    assert "Never ask a question" in text and "best guess" in text and "`guessed`" in text
    assert "Write no text" in text
    assert "A card is open" not in text
    follow_up = extraction.system_blocks(SHOPPING, follow_up=True)[0]["text"]
    assert "A card is open" in follow_up and "ALL of its data" in follow_up and "`not_this`" in follow_up
    assert extraction.system_blocks(SHOPPING)[0]["cache_control"] == llm.CACHED


def test_the_state_and_the_open_card_go_in_the_user_turn():
    card = OpenCard("demo_shop_add", {"item": "milk", "quantity": 1}, ("quantity",), "add milk")
    turn = extraction.user_turn("make it 3", "On the list: bread", card)
    assert "The task's state, read just now:\nOn the list: bread" in turn
    assert '- data: {"item": "milk", "quantity": 1}' in turn and "- still guessed: quantity" in turn
    assert "- it came from the user saying: add milk" in turn
    assert turn.endswith("The message:\nmake it 3")
    assert extraction.user_turn("add milk") == "The message:\nadd milk"
    assert "Just before this, the user said: add socks" in extraction.user_turn("no, shopping", earlier="add socks")


def test_a_call_that_fits_is_the_action_its_data_and_its_guesses():
    found = extraction.read(SHOPPING, ("demo_shop_add", {"item": "milk", "quantity": 1, "guessed": ["quantity"]}))
    assert found.fitted and found.action.name == "demo_shop_add"
    assert found.data == {"item": "milk", "quantity": 1} and found.guessed == frozenset({"quantity"})
    assert found.as_log() == {"task": "shopping", "action": "demo_shop_add", "data": {"item": "milk", "quantity": 1}, "guessed": ["quantity"]}


@pytest.mark.parametrize(
    "called, reason",
    [
        (None, "no tool call"),
        (("none", {"reason": "not about shopping"}), "not about shopping"),
        (("demo_pack_add", {"item": "socks", "guessed": []}), "not an action of shopping"),
        (("demo_shop_add", {"quantity": 2, "guessed": []}), "`item` is missing"),
        (("demo_shop_add", {"item": "milk", "quantity": "two", "guessed": []}), "`quantity` must be integer"),
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
    sent = claude(("demo_shop_add", {"item": "lemons", "quantity": 3, "guessed": []}))
    found = asyncio.run(extraction.extract(SHOPPING, "add 3 lemons", state="On the list: bread"))
    assert found.data == {"item": "lemons", "quantity": 3}
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
    assert any(fixture.action == "none" for fixture in EXTRACTIONS) and any(fixture.action == "not_this" for fixture in EXTRACTIONS)


@pytest.mark.parametrize("fixture", [f for f in ROUTERS if not set(f.tasks) - set(NAMES)], ids=lambda f: f.name)
def test_router_fixture(fixture):
    if fixture.recorded is None:
        pytest.skip("not recorded yet: python -m evals.live --live --dev --record")
    problem = fixtures.router_problem(fixture, routing.parse(fixture.recorded, NAMES))
    if fixture.known_miss:
        assert problem, f"no longer a miss ({fixture.known_miss}): take known_miss off this fixture"
    else:
        assert not problem


@pytest.mark.parametrize("fixture", [f for f in EXTRACTIONS if f.task in NAMES], ids=lambda f: f.name)
def test_extraction_fixture(fixture):
    if fixture.recorded is None:
        pytest.skip("not recorded yet: python -m evals.live --live --dev --record")
    entry = next(entry for entry in ENTRIES if entry.name == fixture.task)
    found = extraction.read(entry, tuple(fixture.recorded), follow_up=fixture.card is not None)
    problem = fixtures.extraction_problem(fixture, found)
    if fixture.known_miss:
        assert problem, f"no longer a miss ({fixture.known_miss}): take known_miss off this fixture"
    else:
        assert not problem


def test_a_fixture_is_judged_on_the_task_the_action_the_data_and_the_guesses():
    fixture = fixtures.ExtractionFixture("x", "shopping", "add 3 lemons", "demo_shop_add", {"item": "Lemons", "quantity": 3}, [])
    right = extraction.read(SHOPPING, ("demo_shop_add", {"item": "lemons", "quantity": 3, "guessed": []}))
    assert fixtures.extraction_problem(fixture, right) == "", "case is not what is being tested"
    wrong_count = extraction.read(SHOPPING, ("demo_shop_add", {"item": "lemons", "quantity": 2, "guessed": []}))
    assert "`quantity` is 2, expected 3" in fixtures.extraction_problem(fixture, wrong_count)
    guessed = extraction.read(SHOPPING, ("demo_shop_add", {"item": "lemons", "quantity": 3, "guessed": ["quantity"]}))
    assert "guessed ['quantity'], expected []" in fixtures.extraction_problem(fixture, guessed)
    other = extraction.read(SHOPPING, ("demo_shop_list", {"guessed": []}))
    assert "expected demo_shop_add, got demo_shop_list" in fixtures.extraction_problem(fixture, other)

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
