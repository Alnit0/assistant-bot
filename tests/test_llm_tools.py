"""The Claude loop, with a scripted stand-in for the API: nothing here goes near the network."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

from core import llm
from core.config import MAX_TOOL_CALLS

CHANNEL = 100
TOOLS = [{"name": "timer", "description": "start a timer", "input_schema": {"type": "object"}}]


def text(words: str):
    return SimpleNamespace(type="text", text=words)


def call(name: str, call_id: str = "t1", **value):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=value)


def response(*blocks, stop="end_turn", tokens=(100, 20), cache=(0, 0)):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            cache_read_input_tokens=cache[0],
            cache_creation_input_tokens=cache[1],
        ),
    )


class FakeClaude:
    """Gives the scripted responses in turn, and remembers what it was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **request):
        # A copy: the loop goes on adding to the same list
        self.requests.append({**request, "messages": copy.deepcopy(request["messages"])})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(llm, "_histories", {})

    def install(*responses) -> FakeClaude:
        fake = FakeClaude(*responses)
        monkeypatch.setattr(llm, "claude", fake)
        return fake

    return install


class Runner:
    """Stands in for the tools: answers every call, and remembers them."""

    def __init__(self, result=("started a 5m timer", False)):
        self.result = result
        self.calls = []

    async def __call__(self, name, value):
        self.calls.append((name, value))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def ask(words="Set a timer for 5 minutes", runner=None, tools=TOOLS):
    return asyncio.run(llm.ask_claude(words, "", CHANNEL, tools=tools, run_tool=runner))


# --- answering without a tool ------------------------------------------------
def test_a_plain_answer_calls_nothing(claude):
    fake, runner = claude(response(text("It's sunny."))), Runner()
    result = ask("How's the weather?", runner)
    assert result.reply == "It's sunny." and result.tool_calls == [] and runner.calls == []
    assert len(fake.requests) == 1
    assert fake.requests[0]["tools"] == TOOLS


def test_with_no_tools_none_are_sent(claude):
    fake = claude(response(text("Hello.")))
    assert ask("Hi", None, tools=None).reply == "Hello."
    assert "tools" not in fake.requests[0]
    assert "You have no tools yet." in fake.requests[0]["system"][0]["text"]


# --- calling tools -----------------------------------------------------------
def test_a_tool_call_is_run_and_its_result_goes_back(claude):
    fake = claude(
        response(text("On it."), call("timer", duration="5m"), stop="tool_use"),
        response(text("Timer started.")),
    )
    runner = Runner()
    result = ask(runner=runner)

    assert runner.calls == [("timer", {"duration": "5m"})]
    assert result.reply == "Timer started."
    assert [(done.name, done.result, done.is_error) for done in result.tool_calls] == [
        ("timer", "started a 5m timer", False)
    ]
    second = fake.requests[1]["messages"]
    assert second[-2]["role"] == "assistant", "Claude's own turn, tool call included, is sent back as it came"
    assert second[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "started a 5m timer"}],
    }


def test_several_calls_in_one_turn_are_answered_in_one_message(claude):
    fake = claude(
        response(call("timer", "t1", duration="5m"), call("pomo", "t2"), stop="tool_use"),
        response(text("Both started.")),
    )
    runner = Runner()
    result = ask(runner=runner)
    assert [name for name, _ in runner.calls] == ["timer", "pomo"]
    results = fake.requests[1]["messages"][-1]["content"]
    assert [entry["tool_use_id"] for entry in results] == ["t1", "t2"]
    assert len(result.tool_calls) == 2


def test_a_failure_goes_back_to_claude_to_explain(claude):
    fake = claude(response(call("timer", duration="banana"), stop="tool_use"), response(text("That isn't a length of time.")))
    result = ask(runner=Runner(("I can't read “banana” as a length of time.", True)))
    assert fake.requests[1]["messages"][-1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": "I can't read “banana” as a length of time.",
        "is_error": True,
    }
    assert result.reply == "That isn't a length of time."
    assert result.tool_calls[0].is_error


def test_a_tool_that_blows_up_is_an_error_result_not_a_crash(claude):
    fake = claude(response(call("timer"), stop="tool_use"), response(text("Something went wrong.")))
    result = ask(runner=Runner(RuntimeError("boom")))
    sent = fake.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True and "boom" in sent["content"]
    assert result.reply == "Something went wrong."


def test_at_most_five_tool_calls_run_for_one_message(claude):
    assert MAX_TOOL_CALLS == 5
    greedy = response(call("timer", "a"), call("timer", "b"), call("timer", "c"), stop="tool_use")
    fake = claude(greedy, greedy, response(text("That's all I can do in one go.")))
    runner = Runner()
    result = ask(runner=runner)

    assert len(runner.calls) == 5 and len(result.tool_calls) == 5
    refused = fake.requests[2]["messages"][-1]["content"][-1]
    assert refused["is_error"] is True and "at most 5 tool calls" in refused["content"]
    assert result.reply == "That's all I can do in one go."


def test_a_claude_that_never_stops_calling_is_stopped(claude):
    fake = claude(response(call("timer"), stop="tool_use"))  # the same answer, for ever
    runner = Runner()
    result = ask(runner=runner)
    assert len(runner.calls) == 5
    assert len(fake.requests) == MAX_TOOL_CALLS + 2
    assert result.reply.startswith("I ran out of steps")


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_a_reply_that_was_cut_short_runs_nothing(claude, stop):
    claude(response(text("I'll just"), call("timer", duration="5"), stop=stop))
    runner = Runner()
    result = ask(runner=runner)
    assert runner.calls == [] and result.tool_calls == []
    assert result.reply == "I'll just"


def test_a_silent_finish_after_a_tool_still_says_something(claude):
    claude(response(call("timer"), stop="tool_use"), response())
    assert ask(runner=Runner()).reply == "✅ Done."


# --- what is counted and remembered ------------------------------------------
def test_usage_is_added_up_over_the_rounds(claude):
    claude(
        response(call("timer"), stop="tool_use", tokens=(100, 20), cache=(0, 3000)),
        response(text("Done."), tokens=(150, 10), cache=(3000, 0)),
    )
    result = ask(runner=Runner())
    assert (result.input_tokens, result.output_tokens) == (250, 30)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (3000, 3000)


def test_the_history_stays_plain_text(claude):
    claude(response(call("timer", duration="5m"), stop="tool_use"), response(text("Timer started.")))
    ask(runner=Runner())
    history = llm.history_for(CHANNEL)
    assert [entry["role"] for entry in history] == ["user", "assistant"]
    assert all(isinstance(entry["content"], str) for entry in history), "no tool blocks to be split by trimming"
    assert history[0]["content"] == "Set a timer for 5 minutes"
    assert history[1]["content"] == "Timer started.", "the reply as it was said: no note of the tool calls"


def test_the_next_message_carries_the_history(claude):
    fake = claude(response(text("Hello.")))
    ask("Hi", Runner())
    ask("And again", Runner())
    assert [entry["content"] for entry in fake.requests[1]["messages"]] == ["Hi", "Hello.", "And again"]


def test_a_failed_request_leaves_the_history_alone(claude, monkeypatch):
    async def broken(**request):
        raise RuntimeError("no connection")

    monkeypatch.setattr(llm, "claude", SimpleNamespace(messages=SimpleNamespace(create=broken)))
    with pytest.raises(RuntimeError):
        ask("Hi", Runner())
    assert llm.history_for(CHANNEL) == []


def test_an_agreed_proposal_is_remembered_without_asking_claude(claude):
    llm.remember(CHANNEL, "ok", "That ran when you said ok: `timer 5m`.")
    assert [entry["role"] for entry in llm.history_for(CHANNEL)] == ["user", "assistant"]


# --- honesty: "done" only when a tool did it ----------------------------------
def test_done_with_no_tool_call_is_sent_back_and_claude_then_acts(claude):
    fake = claude(
        response(text("✅ Done.\n[Tool calls this turn: timer (result: started timer 13: testing, 20m)]")),
        response(call("timer", duration="20m", label="testing"), stop="tool_use"),
        response(text("Your 20-minute testing timer is running.")),
    )
    runner = Runner()
    result = ask("Start a timer for 20 minutes called testing", runner)

    assert runner.calls == [("timer", {"duration": "20m", "label": "testing"})], "the timer really was started"
    assert result.reply == "Your 20-minute testing timer is running."
    assert result.unbacked_claim.startswith("✅ Done."), "kept for the #bot-log card"
    check = fake.requests[1]["messages"][-1]
    assert check == {"role": "user", "content": llm.NOTHING_RAN}
    assert [entry["content"] for entry in llm.history_for(CHANNEL)] == [
        "Start a timer for 20 minutes called testing",
        "Your 20-minute testing timer is running.",
    ], "neither the false reply nor the check is remembered"


def test_done_with_no_tool_call_may_be_corrected_in_words(claude):
    fake = claude(response(text("Done.")), response(text("I can't switch that from here: type `dev on`.")))
    result = ask("dev mode on", Runner())
    assert result.reply == "I can't switch that from here: type `dev on`."
    assert result.unbacked_claim == "Done." and result.tool_calls == []
    assert len(fake.requests) == 2, "sent back once, no more"


def test_a_claude_that_insists_it_is_done_is_overruled(claude):
    fake = claude(response(text("Done.")))  # the same answer, however often it is asked
    result = ask("dev mode off", Runner())
    assert result.reply == llm.NOT_DONE
    assert len(fake.requests) == 2
    assert llm.history_for(CHANNEL)[-1]["content"] == llm.NOT_DONE


def test_done_after_a_tool_that_worked_is_left_alone(claude):
    fake = claude(response(call("timer", duration="5m"), stop="tool_use"), response(text("Done.")))
    result = ask(runner=Runner())
    assert result.reply == "Done." and result.unbacked_claim == ""
    assert len(fake.requests) == 2


def test_done_after_a_tool_that_failed_is_sent_back(claude):
    claude(
        response(call("timer", duration="banana"), stop="tool_use"),
        response(text("Done.")),
        response(text("That isn't a length of time I can read.")),
    )
    result = ask(runner=Runner(("I can't read “banana” as a length of time.", True)))
    assert result.unbacked_claim == "Done."
    assert result.reply == "That isn't a length of time I can read."


def test_looking_something_up_is_not_doing_it(claude):
    # The caller knows which tools only read: here the one call made was a listing
    claude(
        response(call("list_timers"), stop="tool_use"),
        response(text("Done, the tea timer is paused.")),
        response(text("The tea timer is still running; I haven't paused it.")),
    )
    result = asyncio.run(
        llm.ask_claude("Pause the tea timer", "", CHANNEL, tools=TOOLS, run_tool=Runner(), acted=lambda: False)
    )
    assert result.unbacked_claim and result.reply == "The tea timer is still running; I haven't paused it."


def test_an_ordinary_answer_is_never_sent_back(claude):
    fake = claude(response(text("Madrid is the capital of Spain.")))
    result = ask("What's the capital of Spain?", Runner())
    assert result.unbacked_claim == "" and len(fake.requests) == 1


def test_without_tools_there_is_nothing_to_check(claude):
    fake = claude(response(text("Done.")))
    assert ask("Say done", None, tools=None).reply == "Done."
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "reply",
    ["Done.", "✅ Done.", "Done—your tea timer is running.", "All done!", "That's done.", "✅ Timer started.",
     "Sure.\n[Tool calls this turn: (none: this is a built-in shortcut you can type yourself)]"],
)
def test_replies_that_say_it_was_done(reply):
    assert llm.claims_done(reply)


@pytest.mark.parametrize(
    "reply",
    ["How long for this one?", "I can't do that, but you can type `dev on`.", "Waiting for you to confirm with the buttons.",
     "Your last message was “Pin the last message”. Want me to delete it?", "Have you done the washing?"],
)
def test_replies_that_do_not(reply):
    assert not llm.claims_done(reply)


# --- saying a change was made, after only looking ------------------------------
def test_a_change_reported_with_nothing_run_is_sent_back(claude):
    # 22:56:55 on 2026-10-07: "resume my tea timer" -> this reply, and nothing was resumed. The
    # state now comes with the message, so the claim is made without any call at all
    fake = claude(
        response(text("Tea's running again – 9m 21s left.")),
        response(call("timer_control", "t2", id="t3", action="resume"), stop="tool_use"),
        response(text("Tea's running again – 9m 21s left.")),
    )
    runner, did = Runner(), []

    async def run_tool(name, value):
        did.append(name)
        return await runner(name, value)

    result = asyncio.run(
        llm.ask_claude(
            "resume my tea timer", "", CHANNEL, tools=TOOLS, run_tool=run_tool, acted=lambda: "timer_control" in did
        )
    )
    assert did == ["timer_control"], "sent back, it made the call it had skipped"
    assert result.unbacked_claim == "Tea's running again – 9m 21s left."
    assert result.reply == "Tea's running again – 9m 21s left."
    assert fake.requests[1]["messages"][-1] == {"role": "user", "content": llm.NOTHING_RAN}


def test_an_account_given_after_a_successful_read_is_not_questioned(claude):
    # 23:17:46 on 2026-10-07: "what happened with the tea timers" -> timer_history, then a true
    # account ("got paused at 23:14, resumed at 23:15"), which was sent back and cost a request.
    # The wider wording is only questioned when no tool succeeded at all
    fake = claude(
        response(call("timer_history"), stop="tool_use"),
        response(text("t16 was paused at 23:14 and has been resumed since.")),
    )
    result = asyncio.run(
        llm.ask_claude("what happened", "", CHANNEL, tools=TOOLS, run_tool=Runner(), acted=lambda: False)
    )
    assert result.unbacked_claim == "" and len(fake.requests) == 2
    assert result.reply == "t16 was paused at 23:14 and has been resumed since."


def test_a_flat_done_after_only_reading_is_still_sent_back(claude):
    fake = claude(
        response(call("list_timers"), stop="tool_use"),
        response(text("Done.")),
        response(text("Nothing was changed: tea is still paused.")),
    )
    result = asyncio.run(
        llm.ask_claude("resume tea", "", CHANNEL, tools=TOOLS, run_tool=Runner(), acted=lambda: False)
    )
    assert result.unbacked_claim == "Done." and len(fake.requests) == 3


@pytest.mark.parametrize(
    "reply",
    [
        "Tea's running again – 9m 21s left.",
        "All three paused.",
        "I've paused the tea timer.",
        "I paused it for you.",
        "The tea timer is now paused.",
        "Your Pomodoro has been stopped.",
        "Dev mode is switched off again.",
    ],
)
def test_replies_that_say_something_was_changed(reply):
    assert llm.claims_change(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Dinner has 2m 50s left, breakfast has 3m 36s left.",
        "You've got three running:\n- **tea** – paused, 10m 4s left",
        "Your Pomodoro is already running – 22m 28s left in the focus round.",
        "The tea timer is paused with 9m 21s left. Want me to resume it?",
        "Which would you like me to pause first?",
    ],
)
def test_replies_that_only_describe_how_things_are(reply):
    assert not llm.claims_change(reply)


def test_an_account_of_earlier_is_asked_about_once_but_never_overruled(claude):
    # "I paused all three when you asked" is true of an earlier message: checking it costs a
    # request, but the reply must not be replaced by "I haven't done that"
    said = "I paused all three timers when you asked, a minute ago."
    fake = claude(response(text(said)))
    result = ask("I thought my timers were paused?", Runner())
    assert len(fake.requests) == 2 and result.reply == said


# --- no debug text in a reply --------------------------------------------------
@pytest.mark.parametrize(
    "reply, clean",
    [
        ("✅ Done.\n[Tool calls this turn: timer (result: started timer 13: testing, 20m)]", "✅ Done."),
        ("Timer started. [tools: timer]", "Timer started."),
        ("Done.\n[Tool calls this turn: (none: this is a built-in shortcut", "Done."),
        ("One.\n\n[tool: x]\n\nTwo.", "One.\n\nTwo."),
    ],
)
def test_a_bracketed_tool_note_is_taken_out_of_a_reply(reply, clean):
    assert llm.scrub(reply) == (clean, True)


@pytest.mark.parametrize("reply", ["It's sunny.", "Use [square brackets] for a link.", "- [ ] buy milk", "The toolbox is in the shed."])
def test_ordinary_text_is_left_alone(reply):
    assert llm.scrub(reply) == (reply, False)


def test_a_note_claude_writes_never_reaches_the_user_or_the_history(claude):
    claude(
        response(call("timer", duration="5m"), stop="tool_use"),
        response(text("Timer started.\n[Tool calls this turn: timer (result: started a 5m timer)]")),
    )
    assert ask(runner=Runner()).reply == "Timer started."
    assert llm.history_for(CHANNEL)[-1]["content"] == "Timer started."


# --- caching and cost --------------------------------------------------------
def test_the_system_prompt_is_one_cached_block_with_nothing_that_changes(claude):
    fake = claude(response(text("Hello.")))
    ask("Hi", Runner())
    (stable,) = fake.requests[0]["system"]
    assert stable["cache_control"] == {"type": "ephemeral"}
    assert "current date and time" not in stable["text"], "it changes every minute and would spoil the cache"


def test_the_time_and_live_state_go_after_the_users_words_in_the_latest_turn_only(claude):
    fake = claude(response(text("Tea has 3m left.")))
    note = llm.turn_note('t16: "tea" · running, 3m left')
    asyncio.run(llm.ask_claude("how long on tea?", "", CHANNEL, tools=TOOLS, run_tool=Runner(), note=note))
    asyncio.run(llm.ask_claude("thanks", "", CHANNEL, tools=TOOLS, run_tool=Runner(), note=llm.turn_note()))
    first, second = fake.requests
    assert first["messages"][-1]["content"] == [
        {"type": "text", "text": "how long on tea?"},
        {"type": "text", "text": note},
    ]
    assert note.startswith(llm.NOTE_OPENS) and "current date and time in Auckland" in note
    assert note.endswith('Live state, read just now:\nt16: "tea" · running, 3m left')
    # Remembered as plain words: last turn's state would be out of date
    assert second["messages"][:2] == [
        {"role": "user", "content": "how long on tea?"},
        {"role": "assistant", "content": "Tea has 3m left."},
    ]
    assert first["system"] == second["system"] and first["tools"] == second["tools"], "byte for byte: the cache holds"


# --- ending the turn when the tools have already said it -------------------------
def test_a_confirmed_action_ends_the_turn_without_a_second_request(claude):
    fake = claude(response(text("Starting it."), call("timer", duration="5m"), stop="tool_use"), response(text("Started.")))
    result = asyncio.run(
        llm.ask_claude(
            "Set a timer for 5 minutes", "", CHANNEL, tools=TOOLS, run_tool=Runner(),
            closing=lambda: llm.Closing("", "That ran: started timer 1: tea, 5m."),
        )
    )
    assert len(fake.requests) == 1, "one round trip"
    assert result.reply == "" and result.closed_by_tools, "nothing more to send: the tool's message is there"
    assert llm.history_for(CHANNEL)[-1] == {"role": "assistant", "content": "That ran: started timer 1: tea, 5m."}


def test_what_a_tool_confirmed_without_posting_is_the_reply(claude):
    claude(response(call("timer_control", ids="t3", action="pause"), stop="tool_use"))
    said = "⏸️ Paused: tea (3m left)"
    result = asyncio.run(
        llm.ask_claude("pause tea", "", CHANNEL, tools=TOOLS, run_tool=Runner(), closing=lambda: llm.Closing(said, said))
    )
    assert result.reply == said and llm.history_for(CHANNEL)[-1]["content"] == said


def test_a_round_that_is_not_settled_goes_back_to_claude(claude):
    fake = claude(response(call("list_timers"), stop="tool_use"), response(text("Tea has 3m left.")))
    result = asyncio.run(
        llm.ask_claude("how long on tea", "", CHANNEL, tools=TOOLS, run_tool=Runner(), closing=lambda: None)
    )
    assert len(fake.requests) == 2 and result.reply == "Tea has 3m left." and not result.closed_by_tools


def test_the_stable_prompt_does_not_change_between_messages():
    assert llm.build_system_blocks("- stats", True)[0] == llm.build_system_blocks("- stats", True)[0]


def test_cached_tokens_are_priced_differently():
    plain = llm.estimate_cost("claude-haiku-4-5", 1_000_000, 0)
    assert llm.estimate_cost("claude-haiku-4-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(plain * 0.1)
    assert llm.estimate_cost("claude-haiku-4-5", 0, 0, cache_write_tokens=1_000_000) == pytest.approx(plain * 1.25)


def test_tool_tokens_are_counted_once_per_set_of_tools(monkeypatch):
    asked = []

    async def count_tokens(**request):
        asked.append("tools" in request)
        return SimpleNamespace(input_tokens=900 if "tools" in request else 10)

    monkeypatch.setattr(llm, "claude", SimpleNamespace(messages=SimpleNamespace(count_tokens=count_tokens)))
    monkeypatch.setattr(llm, "_tool_tokens", {})
    assert asyncio.run(llm.count_tool_tokens(TOOLS)) == 890
    assert asyncio.run(llm.count_tool_tokens(TOOLS)) == 890
    assert asked == [True, False], "the second time it is remembered"
    assert asyncio.run(llm.count_tool_tokens([])) == 0


def test_tool_tokens_that_cannot_be_counted_are_unknown(monkeypatch):
    async def count_tokens(**request):
        raise RuntimeError("offline")

    monkeypatch.setattr(llm, "claude", SimpleNamespace(messages=SimpleNamespace(count_tokens=count_tokens)))
    monkeypatch.setattr(llm, "_tool_tokens", {})
    assert asyncio.run(llm.count_tool_tokens(TOOLS)) is None
