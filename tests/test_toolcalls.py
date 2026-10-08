"""What becomes of a tool call from Claude: run, proposed, confirmed with buttons, or refused.
The registry's runner and the button helpers are replaced by stand-ins that record."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import discord
import pytest

from core import confirmations, llm, pending, tools
from core.context import Context
from core.database import log_received
from skills import registry, toolcalls

INBOX = 100
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


class FakeChannel:
    def __init__(self, messages=(), older=()):
        self.id = INBOX
        self.sent = []
        self._messages = list(messages)
        self._by_id = {message.id: message for message in (*messages, *older)}

    async def fetch_message(self, message_id):
        if message_id not in self._by_id:
            raise discord.HTTPException(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self._by_id[message_id]

    async def send(self, text, **options):
        self.sent.append(text)
        return SimpleNamespace(id=5000 + len(self.sent))

    def history(self, limit, before=None):
        async def messages():
            for message in self._messages[:limit]:
                yield message

        return messages()


def a_message(message_id: int, content: str):
    return SimpleNamespace(
        id=message_id,
        content=content,
        created_at=NOW,
        author=SimpleNamespace(display_name="Alex"),
        jump_url=f"https://discord.com/channels/1/{INBOX}/{message_id}",
        channel=SimpleNamespace(id=INBOX),
        pinned=False,
        reactions=[],
        attachments=[],
    )


RENT, MILK, TEA = a_message(11, "Rent is due on the 1st"), a_message(12, "Buy oat milk"), a_message(13, "Tea with Sam")


@pytest.fixture
def world(db, dev_off, owner, monkeypatch):
    """A chat message in #inbox, with everything a tool call can touch standing by."""
    seen = SimpleNamespace(ran=[], undone=[], asked=[], choices=[], undo_offers=[], outcome=("ok", "done", ["📌 Pinned"]))
    # The messages are dated NOW: "just now" must not depend on the day the tests are run
    monkeypatch.setattr(toolcalls, "utc_now", lambda: NOW)

    async def run_tool(ctx, spec, value, target=None, *, collect=False):
        seen.ran.append((spec.name, value, getattr(target, "id", None), collect))
        status, text, confirmations_ = seen.outcome
        return registry.ToolOutcome(status, text, list(confirmations_) if collect else [])

    async def run_undo(ctx, spec, target):
        seen.undone.append((spec.name, target.id))
        return registry.ToolOutcome("ok", "📌 Unpinned again", [])

    async def ask(channel, user, question, on_confirm):
        seen.asked.append((question, on_confirm))

    async def choose(channel, user, question, options):
        seen.choices.append((question, options))

    async def offer_undo(channel, user, text, on_undo, seconds=30):
        seen.undo_offers.append((text, on_undo))

    async def no_class(message_id):
        return None

    monkeypatch.setattr(registry, "run_tool", run_tool)
    monkeypatch.setattr(registry, "run_undo", run_undo)
    monkeypatch.setattr(registry, "declared_class", no_class)
    monkeypatch.setattr(confirmations, "ask", ask)
    monkeypatch.setattr(confirmations, "choose", choose)
    monkeypatch.setattr(confirmations, "offer_undo", offer_undo)
    monkeypatch.setattr(llm, "_histories", {})
    monkeypatch.setattr(toolcalls, "_warned", set())
    pending.clear()

    def make(text="Set a timer", reply_to=None, recent=(RENT, MILK, TEA), older=()):
        seen.channel = FakeChannel(recent, older)
        reference = None if reply_to is None else SimpleNamespace(resolved=None, message_id=reply_to.id)
        message = SimpleNamespace(id=99, reference=reference, author=SimpleNamespace(id=1))
        seen.ctx = Context(owner, INBOX, 99, text, seen.channel, _message=message)
        if reply_to is not None:

            async def fetch():
                return reply_to

            monkeypatch.setattr(seen.ctx, "fetch_reply_target", fetch, raising=False)
        seen.turn = asyncio.run(toolcalls.prepare(seen.ctx))
        return seen

    yield make
    pending.clear()


def execute(seen, name, **value):
    return asyncio.run(toolcalls.execute(seen.turn, name, value))


# --- what Claude is given ----------------------------------------------------
def test_no_tool_is_sent_as_strict(world):
    # Measured 2026-10-07: strict added about 2s to every request, and about 40s after any change of tools
    turn = world().turn
    assert turn.strict == set() and not [definition for definition in turn.definitions if "strict" in definition]
    assert turn.definitions[-1]["cache_control"] == {"type": "ephemeral"}


def test_the_tools_are_ready_for_the_api(world, monkeypatch):
    monkeypatch.setattr(toolcalls, "STRICT_TOOLS", True)
    turn = asyncio.run(toolcalls.prepare(world().ctx))
    names = [definition["name"] for definition in turn.definitions]
    assert names == turn.names and names[-2:] == [toolcalls.SEARCH, toolcalls.RECENT]
    assert {"timer", "pomo", "reply_archive", "reply_pin", "reset", "list_timers", "timer_control"} <= set(names)
    assert not [name for name in names if name.startswith("lab")], "never the lab"
    assert [name for name in names if name.startswith("dev")] == ["dev_mode"], "of dev, only the switch while it is off"
    assert turn.strict == {
        "timer", "pomo", "help", "dev_mode", "timer_control", "pomodoro_control", toolcalls.SEARCH,
        "pause_all", "resume_all", "timer_history",
    }
    for definition in turn.definitions:
        assert bool(definition.get("strict")) == (definition["name"] in turn.strict)
    assert turn.definitions[-1]["cache_control"] == {"type": "ephemeral"}, "the cache covers every tool"
    assert all("cache_control" not in definition for definition in turn.definitions[:-1])


def test_someone_with_no_tools_gets_none(world, stranger):
    seen = world()
    turn = asyncio.run(toolcalls.prepare(Context(stranger, INBOX, 99, "hi", seen.channel)))
    assert turn.definitions == [] and turn.names == []


def test_too_many_strict_tools_is_warned_about_once(world, monkeypatch):
    seen, warnings = world(), []

    async def log_error(title, details, user_text=None):
        warnings.append((title, details))

    monkeypatch.setattr(toolcalls, "log_error", log_error)
    monkeypatch.setattr(toolcalls, "STRICT_TOOLS", True)
    monkeypatch.setattr(tools, "STRICT_LIMIT", 2)
    monkeypatch.setattr(tools.choose_strict, "__defaults__", (2,))
    for _ in range(2):
        turn = asyncio.run(toolcalls.prepare(seen.ctx))
    assert len(turn.strict) == 2
    assert len(warnings) == 1 and warnings[0][0] == "Too many strict tools"
    assert "help" in warnings[0][1] or "dev_mode" in warnings[0][1]


# --- a clear request runs at once --------------------------------------------
def test_a_word_runs_straight_away(world):
    seen = world()
    assert execute(seen, "timer", duration="5m", label="tea", propose=False) == ("done", False)
    assert seen.ran == [("timer", {"duration": "5m", "label": "tea", "propose": False}, None, False)]
    assert seen.asked == [] and seen.channel.sent == []


def test_a_failure_is_handed_back_for_claude_to_explain(world):
    seen = world()
    seen.outcome = ("error", "I can't read “banana” as a length of time.", [])
    assert execute(seen, "timer", duration="banana", label="", propose=False) == (
        "I can't read “banana” as a length of time.", True
    )


# --- calls that can't run at all ---------------------------------------------
def test_an_unknown_tool_is_refused(world):
    seen = world()
    text, is_error = execute(seen, "lab_chart")
    assert is_error and "no tool called `lab_chart`" in text
    assert seen.ran == []


def test_a_bad_input_is_refused_even_though_the_tool_is_strict(world):
    seen = world()
    text, is_error = execute(seen, "timer", duration=5, label="", propose=False)
    assert is_error and text == "Invalid input: `duration` must be a string."
    text, is_error = execute(seen, "ping", propose=False, extra="x")
    assert is_error and "`extra` is not an argument" in text
    assert seen.ran == []


def test_refused_calls_are_logged(world, monkeypatch):
    seen, logged = world(), []

    async def log_received(content, kind, *rest, **more):
        logged.append((kind, content))
        return 1

    async def log_result(row_id, **fields):
        logged.append(("result", fields))

    monkeypatch.setattr(toolcalls, "log_received", log_received)
    monkeypatch.setattr(toolcalls, "log_result", log_result)
    execute(seen, "nonsense")
    assert logged[0] == ("tool", "tool: nonsense {}")
    assert logged[1][1]["status"] == "error"


# --- proposals ---------------------------------------------------------------
def test_a_proposal_waits_for_ok(world):
    seen = world()
    text, is_error = execute(seen, "pomo", lengths="", mode="", label="writing", propose=True)
    assert not is_error and text.startswith("Proposed, not done: `pomo writing`.")
    assert seen.ran == [], "nothing happens until the user agrees"

    seen.ctx.text = "ok"
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is True
    assert [name for name, *_ in seen.ran] == ["pomo"]
    assert llm.history_for(INBOX)[-1]["content"] == "That ran when you said ok: `pomo writing`."


def test_no_drops_the_proposal(world):
    seen = world()
    execute(seen, "pomo", lengths="", mode="", label="", propose=True)
    seen.ctx.text = "no"
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is True
    assert seen.ran == []
    assert seen.channel.sent == ["👌 Left it: `pomo`"]
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is False, "it is gone"


def test_anything_else_drops_it_and_is_ordinary_chat(world):
    seen = world()
    execute(seen, "pomo", lengths="", mode="", label="", propose=True)
    seen.ctx.text = "actually what's the weather like"
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is False
    seen.ctx.text = "ok"
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is False, "the user moved on, so ok means nothing now"
    assert seen.ran == []


def test_ok_with_nothing_proposed_is_ordinary_chat(world):
    seen = world("ok")
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is False


def test_an_agreed_proposal_that_fails_says_why(world):
    seen = world()
    execute(seen, "timer", duration="banana", label="", propose=True)
    seen.outcome = ("error", "I can't read “banana” as a length of time.", [])
    seen.ctx.text = "yes"
    assert asyncio.run(toolcalls.answer_pending(seen.ctx)) is True
    assert seen.channel.sent == ["⚠️ I can't read “banana” as a length of time."]


# --- destructive actions always ask ------------------------------------------
def test_a_destructive_word_asks_with_buttons(world):
    seen = world("clear our chat")
    text, is_error = execute(seen, "reset")
    assert (text, is_error) == (toolcalls.WAITING_FOR_CONFIRM, False)
    assert seen.ran == []
    question, on_confirm = seen.asked[0]
    assert question == "⚠️ Hive wants to run `reset` (clear conversation memory). Go ahead?"

    assert asyncio.run(on_confirm()) == "✅ Done: `reset`"
    assert [name for name, *_ in seen.ran] == ["reset"]


def test_a_destructive_message_action_quotes_what_it_would_destroy(world):
    seen = world("delete this", reply_to=RENT)
    assert execute(seen, "reply_delete", targets=[]) == (toolcalls.WAITING_FOR_CONFIRM, False)
    question = seen.asked[0][0]
    assert "> Rent is due on the 1st" in question and RENT.jump_url in question
    assert seen.ran == []


# --- which message -----------------------------------------------------------
def test_a_reply_always_wins(world):
    seen = world("pin this", reply_to=MILK)
    execute(seen, toolcalls.RECENT)
    assert execute(seen, "reply_pin", targets=["m1"], propose=False) == ("done", False)
    assert seen.ran == [("reply_pin", {"targets": ["m1"], "propose": False}, MILK.id, False)]
    assert seen.undo_offers == [] and seen.channel.sent == [], "the user pointed at it: the ordinary confirmation will do"


def test_recent_messages_lists_the_channel_with_refs(world):
    seen = world("pin the one about rent")
    text, is_error = execute(seen, toolcalls.RECENT)
    assert not is_error
    assert text.splitlines()[1] == "m1: Alex, just now: Rent is due on the 1st"
    assert set(seen.turn.listing) == {"m1", "m2", "m3"}


def test_a_described_message_is_shown_quoted_with_undo(world):
    seen = world("pin the one about rent")
    execute(seen, toolcalls.RECENT)
    assert execute(seen, "reply_pin", targets=["m1"], propose=False) == ("done", False)
    assert seen.ran == [("reply_pin", {"targets": ["m1"], "propose": False}, RENT.id, True)]
    shown, on_undo = seen.undo_offers[0]
    assert shown == f"📌 Pinned\n> Rent is due on the 1st\n-# {RENT.jump_url}"

    assert asyncio.run(on_undo()) == "📌 Unpinned again"
    assert seen.undone == [("reply_pin", RENT.id)]


def test_an_action_that_cannot_be_undone_is_still_shown_quoted(world):
    seen = world("dismiss that tea alert")
    seen.outcome = ("ok", "done", ["👍 Noted"])
    execute(seen, toolcalls.RECENT)
    execute(seen, "reply_ok", targets=["m3"], propose=False)
    assert seen.undo_offers == []
    assert seen.channel.sent == [f"👍 Noted\n> Tea with Sam\n-# {TEA.jump_url}"]


def test_several_possible_messages_are_offered_not_guessed(world):
    seen = world("archive that note")
    execute(seen, toolcalls.RECENT)
    assert execute(seen, "reply_archive", targets=["m1", "m2"], propose=False) == (toolcalls.WAITING_FOR_CHOICE, False)
    assert seen.ran == []
    question, options = seen.choices[0]
    assert question.splitlines()[0] == "Which message should I `archive`?"
    assert "**1.** > Rent is due on the 1st" in question and "**2.** > Buy oat milk" in question
    assert [label for label, _ in options] == ["1", "2"]

    assert asyncio.run(options[1][1]()) == "✅ Done: `archive` that message"
    assert seen.ran == [("reply_archive", {"targets": ["m1", "m2"], "propose": False}, MILK.id, True)]


def test_picking_a_message_to_delete_still_asks_to_confirm(world):
    seen = world("delete that note")
    execute(seen, toolcalls.RECENT)
    execute(seen, "reply_delete", targets=["m1", "m2"])
    assert asyncio.run(seen.choices[0][1][0][1]()) == "Asked you to confirm below."
    assert seen.ran == [] and len(seen.asked) == 1


def test_no_target_or_an_unlisted_one_is_an_error_for_claude(world):
    seen = world("pin it")
    text, is_error = execute(seen, "reply_pin", targets=[], propose=False)
    assert is_error and "Call recent_messages" in text
    text, is_error = execute(seen, "reply_pin", targets=["m1"], propose=False)
    assert is_error and "Unknown message ref: m1" in text, "nothing is listed until recent_messages is called"
    assert seen.ran == []


def test_only_the_last_twenty_messages_can_be_reached(world):
    many = [a_message(100 + number, f"note {number}") for number in range(40)]
    seen = world("pin an old one", recent=many)
    execute(seen, toolcalls.RECENT)
    assert len(seen.turn.listing) == tools.LISTING_LIMIT == 20


# --- looking further back ----------------------------------------------------
SPAIN = a_message(21, "What's the capital of Spain")


def log_chat(message_id: int, content: str) -> None:
    asyncio.run(log_received(content, "chat", message_id, INBOX, user_id=1))


def test_search_finds_an_older_message_of_the_users_that_still_exists(world):
    seen = world("look further back", older=[SPAIN])
    log_chat(SPAIN.id, SPAIN.content)
    log_chat(22, "Spain trip: book flights")  # logged, but archived since: not in the channel any more
    log_chat(99, "Archive the message about the capital of Spain")  # the message doing the asking
    text, is_error = execute(seen, toolcalls.SEARCH, query="capital Spain")
    assert not is_error
    assert text.splitlines()[1:] == ["s1: Alex, just now: What's the capital of Spain"]
    assert seen.turn.listing["s1"] is SPAIN and seen.turn.older == {"s1"}


def test_search_that_finds_nothing_says_so(world):
    seen = world("look further back")
    text, is_error = execute(seen, toolcalls.SEARCH, query="capital Spain")
    assert not is_error and text.startswith("Nothing the user sent in this channel in the last 30 days fits")
    assert seen.turn.older == set()


def test_an_older_match_is_shown_quoted_and_asked_about_first(world):
    seen = world("pin the one about Spain", older=[SPAIN])
    log_chat(SPAIN.id, SPAIN.content)
    execute(seen, toolcalls.SEARCH, query="capital Spain")
    assert execute(seen, "reply_pin", targets=["s1"], propose=False) == (toolcalls.WAITING_FOR_CONFIRM, False)
    assert seen.ran == [] and not seen.turn.acted, "nothing happens until Confirm"
    question, on_confirm = seen.asked[0]
    assert question.startswith("⚠️ Found further back. Hive wants to run `pin` that message")
    assert "> What's the capital of Spain" in question and SPAIN.jump_url in question

    assert asyncio.run(on_confirm()) == "✅ Done: `pin` that message"
    assert seen.ran == [("reply_pin", {"targets": ["s1"], "propose": False}, SPAIN.id, True)]


def test_a_recent_message_is_still_acted_on_at_once(world):
    seen = world("pin the one about rent", older=[SPAIN])
    log_chat(SPAIN.id, SPAIN.content)
    execute(seen, toolcalls.SEARCH, query="capital Spain")
    execute(seen, toolcalls.RECENT)
    assert set(seen.turn.listing) == {"m1", "m2", "m3", "s1"}, "listing the recent ones keeps what was found further back"
    assert execute(seen, "reply_pin", targets=["m1"], propose=False) == ("done", False)
    assert seen.asked == [] and len(seen.undo_offers) == 1


# --- has anything been done? (what the "done" check goes by) -------------------
def test_running_an_action_counts_as_acting(world):
    seen = world()
    assert not seen.turn.acted
    execute(seen, "timer", duration="5m", label="", propose=False)
    assert seen.turn.acted


def test_reading_proposing_asking_and_failing_do_not(world):
    seen = world("clear our chat")
    execute(seen, toolcalls.RECENT)
    execute(seen, "list_timers")
    execute(seen, "pomo", lengths="", mode="", label="", propose=True)
    execute(seen, "reset")
    seen.outcome = ("error", "I can't read “banana” as a length of time.", [])
    execute(seen, "timer", duration="banana", label="", propose=False)
    assert not seen.turn.acted
    assert [name for name, *_ in seen.ran] == ["list_timers", "timer"]


# --- typed words never reach Claude ------------------------------------------
def test_a_typed_word_runs_directly_without_calling_claude(owner, monkeypatch):
    import main

    dispatched, asked = [], []

    async def user(discord_id):
        return owner

    async def dispatch_keyword(ctx):
        dispatched.append(ctx.text)
        return registry._keyword_router.match(ctx.text) is not None

    async def ask_claude(*args, **kwargs):
        asked.append(args)
        raise AssertionError("a typed word must not be sent to Claude")

    monkeypatch.setattr(main, "get_user_by_discord_id", user)
    monkeypatch.setattr(main.registry, "dispatch_keyword", dispatch_keyword)
    monkeypatch.setattr(main, "ask_claude", ask_claude)
    message = SimpleNamespace(
        type=None, author=SimpleNamespace(bot=False, id=1), content="timer 5m tea", id=1,
        channel=SimpleNamespace(id=INBOX), reference=None,
    )
    asyncio.run(main.on_message(message))
    assert dispatched == ["timer 5m tea"] and asked == []


# --- the real runner: a tool call goes down the same path as a typed word -----
class UserMessage:
    """The user's chat message, noticing anything done to it."""

    def __init__(self):
        self.id, self.reference, self.author = 99, None, SimpleNamespace(id=1)
        self.deleted, self.reactions_added = False, []

    async def delete(self):
        self.deleted = True

    async def add_reaction(self, emoji):
        self.reactions_added.append(emoji)


@pytest.fixture
def real(make_db, dev_off, owner):
    make_db(registry.skill_migrations())
    channel, message = FakeChannel(), UserMessage()
    ctx = Context(owner, INBOX, 99, "is the bot alive?", channel, _message=message)
    specs = {spec.name: spec for spec in registry.tools_for(owner, INBOX)}
    return SimpleNamespace(ctx=ctx, channel=channel, message=message, specs=specs)


def logged_tools():
    def read(conn):
        return conn.execute("SELECT content, status, reply, error FROM message_log WHERE kind = 'tool' ORDER BY id").fetchall()

    from core import database

    return asyncio.run(database.run(read))


def test_a_tool_call_runs_the_handler_and_is_logged(real):
    outcome = asyncio.run(registry.run_tool(real.ctx, real.specs["ping"], {"propose": False}))
    assert (outcome.status, outcome.text) == ("ok", "🏓 Pong!")
    assert real.channel.sent == ["🏓 Pong!"]
    assert logged_tools() == [('tool: ping {"propose": false}', "ok", "🏓 Pong!", None)]


def test_the_users_chat_message_is_left_alone(real):
    asyncio.run(registry.run_tool(real.ctx, real.specs["ping"], {"propose": False}))
    asyncio.run(registry.run_tool(real.ctx, real.specs["timer"], {"duration": "banana", "label": "", "propose": False}))
    assert not real.message.deleted, "it was chat with Claude, not a command to tidy away"
    assert real.message.reactions_added == [], "a failed tool is Claude's to explain, not a ⚠️ on the message"


def test_a_failed_tool_call_is_logged_with_the_reason(real):
    value = {"duration": "banana", "label": "", "propose": False}
    outcome = asyncio.run(registry.run_tool(real.ctx, real.specs["timer"], value))
    assert outcome.status == "error" and "banana" in outcome.text
    content, status, _, error = logged_tools()[0]
    assert content == 'tool: timer {"duration": "banana", "label": "", "propose": false}'
    assert status == "error" and "banana" in error


def test_someone_not_allowed_cannot_run_a_tool(real, monkeypatch):
    # The permission check is made again when the call runs, not only when the tools are chosen
    monkeypatch.setattr(registry, "is_allowed", lambda user, action: False)
    outcome = asyncio.run(registry.run_tool(real.ctx, real.specs["ping"], {"propose": False}))
    assert outcome.status == "denied" and real.channel.sent == []
    assert logged_tools()[0][1] == "denied"


# --- the real runner: timers by id, from the live state ------------------------
def run(real, name, **value):
    return asyncio.run(registry.run_tool(real.ctx, real.specs[name], value))


ONLY_READ = "(This only read the state. Nothing was changed by this call.)"


def read(real, name) -> str:
    """What a read tool reports, having checked it says that reading changed nothing."""
    *lines, last = run(real, name).text.splitlines()
    assert last == ONLY_READ
    return "\n".join(lines)


def test_claude_reads_the_timers_and_acts_on_one_by_its_id(real):
    assert read(real, "list_timers") == "No timers are running or paused."
    started = run(real, "timer", duration="5m", label="tea", propose=False)
    assert started.text == "started timer 1: tea, 5m"
    sent_before = list(real.channel.sent)

    listed = run(real, "list_timers").text.splitlines()
    assert listed[0] == "Timers going now. Use the id with timer_control:"
    assert listed[1].startswith('t1: "tea" · running, ') and listed[1].endswith("left · <#100> (this channel)")

    paused = run(real, "timer_control", ids="t1", action="pause", duration="", propose=False)
    assert paused.status == "ok" and paused.text.startswith("⏸️ Paused: tea (")
    assert 't1: "tea" · paused with ' in run(real, "list_timers").text
    assert run(real, "timer_control", ids="t1", action="resume", duration="", propose=False).text.startswith("▶️ Resumed: tea")
    extended = run(real, "timer_control", ids="t1", action="extend", duration="10m", propose=False).text.splitlines()
    assert extended[0] == "➕ Added 10m to tea" and extended[1].startswith('Now saved as: t1: "tea" · running, ')
    cancelled = run(real, "timer_control", ids="t1", action="cancel", duration="", propose=False).text.splitlines()
    assert cancelled == ["🚫 Cancelled: tea", 'Now saved as: t1: "tea" · cancelled']
    assert 't1: "tea" · cancelled' in run(real, "list_timers").text
    assert real.channel.sent == sent_before, "reading and controlling post nothing: Claude does the talking"


def test_a_timer_id_that_is_wrong_or_in_the_wrong_state_is_explained(real):
    missing = run(real, "timer_control", ids="t99", action="pause", duration="", propose=False)
    assert missing.status == "error" and "There is no timer `t99`" in missing.text
    run(real, "timer", duration="5m", label="tea", propose=False)
    assert run(real, "timer_control", ids="t1", action="resume", duration="", propose=False).text == "**tea** isn't paused."
    no_length = run(real, "timer_control", ids="t1", action="extend", duration="", propose=False)
    assert no_length.status == "error" and "how much time to add" in no_length.text


def test_tool_calls_that_read_are_logged_like_any_other(real):
    run(real, "list_timers")
    assert logged_tools() == [("tool: list_timers {}", "ok", f"No timers are running or paused.\n{ONLY_READ}", None)]


def test_claude_reads_and_controls_the_pomodoro_by_its_id(real):
    assert read(real, "get_pomodoro_status") == "No Pomodoro session is going."
    assert run(real, "pomo", lengths="50/10/30", mode="", label="writing", propose=False).status == "ok"
    status_text = run(real, "get_pomodoro_status").text
    assert status_text.startswith('p1: "writing" · Focus, round 1 of 4 · running, ')
    assert "lengths 50m/10m/30m (focus/break/long break) · each phase waits for Start" in status_text

    assert run(real, "pomodoro_control", id="p1", action="pause", duration="", propose=False).text.startswith("⏸️ Paused: writing")
    assert "paused with " in run(real, "get_pomodoro_status").text
    resumed = run(real, "pomodoro_control", id="p1", action="resume", duration="", propose=False).text.splitlines()
    assert resumed[0].startswith("▶️ Resumed: writing (") and resumed[1].startswith('Now saved as: p1: "writing" · Focus')
    assert run(real, "pomodoro_control", id="p1", action="skip", duration="", propose=False).status == "ok"
    assert "Short break, round 1 of 4" in run(real, "get_pomodoro_status").text
    assert run(real, "pomodoro_control", id="p1", action="stop", duration="", propose=False).text == "⏹️ Stopped: writing"
    assert read(real, "get_pomodoro_status") == "No Pomodoro session is going."
    assert run(real, "pomodoro_control", id="t1", action="pause", duration="", propose=False).status == "error"


def test_asking_for_a_pomodoro_while_one_is_going_posts_nothing_new(real):
    run(real, "pomo", lengths="50/10/30", mode="", label="writing", propose=False)
    sent_before = list(real.channel.sent)

    again = run(real, "pomo", lengths="", mode="", label="", propose=False)
    assert again.status == "error", "nothing was started, so it is not a success for Claude to report"
    assert again.text.startswith("Not started: a Pomodoro session is already going")
    assert 'p1: "writing" · Focus, round 1 of 4 · running' in again.text
    assert "offer to restart" not in again.text
    assert real.channel.sent == sent_before, "no second card, no note: Claude's one reply says it"

    other = run(real, "pomo", lengths="25/5", mode="", label="", propose=False)
    assert "The user asked for 25/5" in other.text and "offer to restart it with those lengths" in other.text
    assert "pomodoro_control with action stop for p1" in other.text
    assert real.channel.sent == sent_before
    assert 'p1: "writing"' in run(real, "get_pomodoro_status").text, "still the same session"


def test_typing_pomo_with_other_lengths_offers_to_restart_with_them(real, monkeypatch):
    from skills.timers import sessions, store

    asked = []

    async def ask(channel, user, question, on_confirm):
        asked.append((question, on_confirm))

    monkeypatch.setattr(confirmations, "ask", ask)

    def typed(*words):
        ctx = Context(real.ctx.user, INBOX, 99, "pomo " + " ".join(words), real.channel, args=list(words), _message=real.message)
        return asyncio.run(sessions.start(ctx))

    typed("50/10/30", "writing")
    assert "card shown again" in typed() and asked == [], "the same again just shows it"
    assert "asked whether to restart as 25/5" in typed("25/5")
    question, on_confirm = asked[0]
    assert question == "🍅 **writing** is already going at 50m/10m/30m. Restart it as `25/5`?"
    assert "Already going" not in real.channel.sent[-1], "the question stands in for the note: one message, not two"

    assert asyncio.run(on_confirm()) == "🍅 Restarted as 25/5"
    going = asyncio.run(store.active_sessions(user_id=real.ctx.user.id))
    assert [(s.label, s.focus_s, s.short_s) for s in going] == [("writing", 1500, 300)], "one session, new lengths, same label"


def test_confirmations_can_be_collected_instead_of_posted(real):
    outcome = asyncio.run(registry.run_tool(real.ctx, real.specs["reset"], {}, collect=True))
    assert outcome.confirmations == ["🧹 Conversation memory cleared."]
    assert real.channel.sent == []


def test_a_message_action_with_no_message_fails_cleanly(real):
    outcome = asyncio.run(registry.run_tool(real.ctx, real.specs["reply_pin"], {"targets": [], "propose": False}))
    assert outcome.status == "error" and "can't find the message" in outcome.text


def test_a_message_action_is_checked_before_it_runs(real):
    in_archive = SimpleNamespace(id=5, channel=SimpleNamespace(id=200), content="x", attachments=[], embeds=[], guild=None)
    outcome = asyncio.run(
        registry.run_tool(real.ctx, real.specs["reply_archive"], {"targets": [], "propose": False}, in_archive)
    )
    assert (outcome.status, outcome.text) == ("error", "That message is already in the archive.")


# --- can the turn end with the tools' own confirmations? --------------------------
def a_round(real, *calls) -> tuple[toolcalls.Turn, object]:
    """Run one round of calls as Claude would make them; what closing() then says."""
    turn = asyncio.run(toolcalls.prepare(real.ctx))
    return turn, next_round(turn, *calls)


def next_round(turn, *calls):
    async def go():
        for name, value in calls:
            await toolcalls.execute(turn, name, value)
        return toolcalls.closing(turn)

    return asyncio.run(go())


START_TEA = ("timer", {"duration": "5m", "label": "tea", "propose": False})


def pause_call(ids="t1", **value):
    return ("timer_control", {"ids": ids, "action": "pause", "duration": "", "label": "", "propose": False, **value})


def test_a_word_that_showed_its_own_message_ends_the_turn_with_nothing_more_to_say(real):
    turn, closed = a_round(real, START_TEA)
    assert closed == llm.Closing("", "That ran: started timer 1: tea, 5m.")
    assert turn.acted and len(real.channel.sent) == 1, "the timer's own message, and no second one"


def test_a_control_tool_posts_nothing_so_what_it_confirmed_is_the_reply(real):
    turn, _ = a_round(real, START_TEA)
    sent = list(real.channel.sent)
    closed = next_round(turn, pause_call())
    assert closed.say.startswith("⏸️ Paused: tea (") and closed.remember == closed.say
    assert real.channel.sent == sent, "the chat path sends it, once"


def test_two_actions_side_by_side_end_the_turn_together(real):
    _, closed = a_round(real, START_TEA, ("timer", {"duration": "3m", "label": "toast", "propose": False}))
    assert closed.say == "" and closed.remember.splitlines() == [
        "That ran: started timer 1: tea, 5m.",
        "That ran: started timer 2: toast, 3m.",
    ]


def test_a_read_leaves_the_answer_to_claude(real):
    turn, closed = a_round(real, ("list_timers", {}))
    assert closed is None and not turn.acted
    assert next_round(turn, START_TEA) is not None, "the action in the next round can still end the turn"


def test_a_failure_leaves_the_explaining_to_claude_for_the_rest_of_the_turn(real):
    turn, closed = a_round(real, pause_call("t99"))
    assert closed is None
    assert next_round(turn, START_TEA) is None, "something went wrong earlier: Claude says what did and didn't happen"


def test_a_proposal_or_a_question_with_buttons_is_not_an_ending(real):
    _, proposed = a_round(real, ("timer", {"duration": "5m", "label": "tea", "propose": True}))
    assert proposed is None
    _, asked = a_round(real, ("reset", {"propose": False}))
    assert asked is None or asked.remember, "a destructive word asks first; whatever ran says so"


def test_the_skills_live_state_is_gathered_for_the_note(real):
    assert asyncio.run(registry.live_state(real.ctx)).splitlines() == [
        "No timers are running or paused.",
        "No Pomodoro session is going.",
    ]
    a_round(real, START_TEA)
    assert 't1: "tea" · running, ' in asyncio.run(registry.live_state(real.ctx))
