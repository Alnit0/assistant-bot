"""What becomes of a tool call from Claude: run, proposed, confirmed with buttons, or refused.
The registry's runner and the button helpers are replaced by stand-ins that record."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core import confirmations, llm, pending, tools
from core.context import Context
from skills import registry, toolcalls

INBOX = 100
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


class FakeChannel:
    def __init__(self, messages=()):
        self.id = INBOX
        self.sent = []
        self._messages = list(messages)

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

    def make(text="Set a timer", reply_to=None, recent=(RENT, MILK, TEA)):
        seen.channel = FakeChannel(recent)
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
def test_the_tools_are_ready_for_the_api(world):
    turn = world().turn
    names = [definition["name"] for definition in turn.definitions]
    assert names == turn.names and names[-1] == toolcalls.RECENT
    assert {"timer", "pomo", "reply_archive", "reply_pin", "reset"} <= set(names)
    assert not [name for name in names if name.startswith(("lab", "dev"))], "no lab, and no dev while dev mode is off"
    assert turn.strict == {"timer", "pomo", "help", "reply_extend"}
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
    monkeypatch.setattr(tools, "STRICT_LIMIT", 2)
    monkeypatch.setattr(tools.choose_strict, "__defaults__", (2,))
    for _ in range(2):
        turn = asyncio.run(toolcalls.prepare(seen.ctx))
    assert len(turn.strict) == 2
    assert len(warnings) == 1 and warnings[0][0] == "Too many strict tools"
    assert "help" in warnings[0][1] or "reply_extend" in warnings[0][1]


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
    assert llm.history_for(INBOX)[-1]["content"].startswith("[The user agreed. `pomo writing`: done")


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
