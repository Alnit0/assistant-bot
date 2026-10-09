"""What happened to a message, step by step (core/trace.py), and `dev why`."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from core import costs, database, trace
from core.costs import Call
from core.errors import UserError

HAIKU = "claude-haiku-4-5"


def test_a_note_is_kept_only_while_a_message_is_being_handled():
    trace.note("nobody is listening")  # no message: nothing happens
    notes = trace.start()
    trace.note("sticky check: card 3 sticks")
    trace.note("merge: jam add")
    trace.stop()
    trace.note("too late")
    assert notes == ["sticky check: card 3 sticks", "merge: jam add"]


def test_notes_stop_at_a_limit_so_a_loop_cannot_fill_the_log():
    notes = trace.start()
    for number in range(trace.MAX_NOTES + 10):
        trace.note(f"note {number}")
    trace.stop()
    assert len(notes) == trace.MAX_NOTES


ROW = {
    "id": 41, "received_at": "2026-10-10T21:15:07+13:00", "kind": "chat", "content": "and jam", "route": "follow-up",
    "tasks": "shopping", "reply": "card: shopping · change: butter · 2 → 3 / jam · × 1", "status": "ok", "error": None,
    "duration_s": 1.42, "cost_usd": 0.0036, "claude_calls": 1,
    "extracted": json.dumps([{"task": "shopping", "action": "demo_shop_change", "data": {"items": [{"item": "butter"}, {"item": "jam"}]}, "guessed": [], "not_included": ["a hat"]}]),
    "trace": json.dumps({
        "why": ["card 7 (shopping) is open and the message sticks to it: it is the bot's latest message and under 5 minutes old"],
        "checks": ["sticky check: card 7 sticks", "restatement check: butter came back with the card and the message doesn't name it: not added again"],
        "card": {"before": ["butter 1 add"], "after": ["butter · 2 → 3", "jam · × 1"]},
        "state": {"shopping": {"sent": 20, "total": 143}},
    }),
    "calls": [("extraction", "shopping", 0.0036, 1.31, 3000, 80)],
    "parts": [],
}


def test_a_message_in_lines_has_everything_needed_to_see_why():
    assert trace.lines(ROW) == [
        "#41 · 2026-10-10 21:15:07 · chat · ok",
        "said: and jam",
        "route: follow-up (card 7 (shopping) is open and the message sticks to it: it is the bot's latest message and under 5 minutes old)",
        "tasks: shopping",
        "router: not asked",
        'extraction: shopping · demo_shop_change {"items":[{"item":"butter"},{"item":"jam"}]} · not included: a hat',
        "state sent (shopping): 20 of 143 line(s)",
        "python: sticky check: card 7 sticks",
        "python: restatement check: butter came back with the card and the message doesn't name it: not added again",
        "card before: butter 1 add",
        "card after:  butter · 2 → 3 / jam · × 1",
        "shown: card: shopping · change: butter · 2 → 3 / jam · × 1",
        "cost: US$0.0036 · 1 request(s) · 1.4s in all · extraction/shopping US$0.0036 1.3s",
    ]


def test_the_routers_answer_is_shown_when_it_was_asked():
    row = {**ROW, "route": "router", "trace": json.dumps({"router": {"tasks": ["shopping", "packing"], "tie": True, "chat_part": "what is the capital of France?"}})}
    assert "router: shopping, packing · tie · chat part: what is the capital of France?" in trace.lines(row)
    assert "router: chat" in trace.lines({**ROW, "route": "chat", "trace": json.dumps({"router": {"tasks": [], "chat": True}})})


def test_a_message_from_before_traces_or_on_the_old_way_still_reads():
    old = {
        "id": 3, "received_at": "2026-10-01T09:00:00+13:00", "kind": "chat", "content": "set a timer for 5 minutes", "route": "tools",
        "tasks": "timers", "reply": "Started.", "status": "ok", "error": None, "duration_s": None, "cost_usd": None, "claude_calls": None,
        "extracted": None, "trace": None, "calls": [], "parts": [("tool", "tool: timer 5m", "ok", "timer started")],
    }
    assert trace.lines(old) == [
        "#3 · 2026-10-01 09:00:00 · chat · ok",
        "said: set a timer for 5 minutes",
        "route: tools",
        "tasks: timers",
        "router: not asked",
        "extraction: none",
        "tool: tool: timer 5m · ok · timer started",
        "python: no checks recorded",
        "shown: Started.",
        "cost: US$0.0000 · 0 request(s)",
    ]


def test_a_block_is_one_copyable_code_block_that_fits_a_message():
    block = trace.block(ROW)
    assert block.startswith("```\n#41 · ") and block.endswith("\n```")
    long = trace.block({**ROW, "reply": "x" * 5000, "content": "```nested```"})
    assert len(long) <= 2000 and long.count("```") == 2


# --- the database, and `dev why` ------------------------------------------------------
def log(text, kind="chat", message_id=5, kept=None, user_id=1, cost=True):  # user 1 is the owner the test database starts with
    async def scenario():
        row_id = await database.log_received(text, kind, message_id, 100, user_id=user_id)
        await database.log_result(row_id, reply=f"answer to {text}", status="ok", duration_s=1.0, trace=json.dumps(kept) if kept else None)
        if cost:
            await database.record_cost(row_id, costs.ROUTER, ["shopping"], [Call("router", HAIKU, 1000, 50), Call("extraction", HAIKU, 2000, 80, task="shopping")])
        return row_id

    return asyncio.run(scenario())


def test_the_last_messages_come_back_oldest_first_with_their_requests(db):
    log("add milk", message_id=5, kept={"why": ["nothing on screen claimed it"]})
    log("make it 2", message_id=6)
    log("dev why", kind="command", message_id=7, cost=False)
    log("from nobody", message_id=8, user_id=None)
    rows = asyncio.run(database.run(trace.db_recent, 1, 5, ("chat", "command"), "dev why"))
    assert [row["content"] for row in rows] == ["add milk", "make it 2"], "mine only, and not the asking itself"
    assert [call[0] for call in rows[0]["calls"]] == ["router", "extraction"] and rows[0]["calls"][1][1] == "shopping"
    assert json.loads(rows[0]["trace"]) == {"why": ["nothing on screen claimed it"]}
    assert [row["content"] for row in asyncio.run(database.run(trace.db_recent, 1, 1, ("chat", "command"), "dev why"))] == ["make it 2"]


def test_one_message_is_found_by_its_row(db):
    row_id = log("add milk")
    assert asyncio.run(database.run(trace.db_get, row_id))["content"] == "add milk"
    assert asyncio.run(database.run(trace.db_get, 999)) is None


def why(*args, user_id=1):
    from tasks.dev import tools

    said = []

    async def reply(text):
        said.append(text)

    result = asyncio.run(tools.why(SimpleNamespace(db=database, reply=reply, args=list(args), user=SimpleNamespace(id=user_id))))
    return said, result


def test_dev_why_shows_my_last_message_as_one_block(db):
    log("add milk", message_id=5)
    last = log("and jam", message_id=6, kept={"checks": ["merge: jam add (new to the card)"]})
    log("dev why", kind="command", message_id=7, cost=False)
    said, result = why()
    assert len(said) == 1 and said[0].startswith(f"```\n#{last} · ") and "said: and jam" in said[0]
    assert "python: merge: jam add (new to the card)" in said[0]
    assert "cost: US$" in said[0] and "router US$" in said[0] and "extraction/shopping US$" in said[0]
    assert result == f"showed the trace of message(s) #{last}"


def test_dev_why_n_shows_that_many_a_block_each_oldest_first(db):
    for number in range(4):
        log(f"message {number}", message_id=10 + number)
    said, _ = why("3")
    assert ["said: message 1" in said[0], "said: message 2" in said[1], "said: message 3" in said[2]] == [True, True, True]
    assert len(said) == 3


def test_a_button_i_pressed_counts_as_a_message_from_me(db):
    log("add milk", message_id=5)
    log("confirm.save 3", kind="card", message_id=6, cost=False)
    said, _ = why("2")
    assert "· card · ok" in said[1] and "said: confirm.save 3" in said[1]


@pytest.mark.parametrize("args", [["0"], ["11"], ["x"], ["1", "2"]])
def test_dev_why_refuses_anything_but_a_small_number(db, args):
    with pytest.raises(UserError, match="from 1 to 10"):
        why(*args)


def test_dev_why_with_nothing_logged_says_so(db):
    with pytest.raises(UserError, match="Nothing is logged from you yet"):
        why()


def test_dev_why_is_a_typed_word_and_never_a_tool_of_claudes():
    from tasks import registry

    registry.load()
    assert registry._keyword_router.match("dev why").entry[1].name == "dev why"
    matched = registry._keyword_router.match("dev why 3")
    assert matched.entry[1].name == "dev why" and matched.entry[1].tool is False
