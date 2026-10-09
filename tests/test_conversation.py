"""A message in plain words, end to end: follow-up, router, extraction, confirm cards, ties and chat
(core/conversation.py, core/confirm.py), with the two demo tasks and a scripted Claude."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, confirm, conversation, costs, database, llm, scheduler, timing
from core.actions import Proposal
from core.cards import Card
from core.errors import UserError
from core.scheduler import utc_now
from tasks.lab import demo, state

INBOX, HUB = 100, 400
HAIKU = "claude-haiku-4-5"


def route(*tasks, tie=False, chat_part=""):
    return (
        "route",
        {"kind": "task" if tasks else "chat", "tasks": list(tasks), "confidence": "tie" if tie else "high", "chat_part": chat_part},
    )


def shop_add(item, quantity=None, guessed=()):
    data = {"item": item, "guessed": list(guessed)}
    if quantity is not None:
        data["quantity"] = quantity
    return ("demo_shop_add", data)


@pytest.fixture
def world(make_db, monkeypatch, owner):
    """A database, the two demo tasks in the catalogue, a channel that records, and a Claude that is scripted."""
    make_db({"lab": state.MIGRATIONS})
    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue(demo.ENTRIES)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(scheduler, "_handlers", dict(scheduler._handlers))
    monkeypatch.setattr(llm, "_histories", {})
    conversation.setup()

    seen = SimpleNamespace(sent=[], deleted=[], edited=[], requests=[], chats=[], next_id=5000, bot_messages=[], order=[])

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append((seen.next_id, card))
        seen.order.append("card")
        seen.bot_messages.append(seen.next_id)
        return seen.next_id

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    async def edit(channel_id, message_id, card):
        seen.edited.append((message_id, card.text))
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "edit", edit)

    def claude(*answers):
        queue = list(answers)

        async def call_tool(system, user, tools, *, choice, purpose, task="", max_tokens=600):
            seen.requests.append(SimpleNamespace(purpose=purpose, task=task, user=user, tools=[tool["name"] for tool in tools]))
            timing.record_claude(0.5, HAIKU, 500, 30, purpose=purpose, task=task)
            assert queue, f"an unscripted request was made: {purpose} {task}"
            return queue.pop(0)

        async def ask_claude(text, capabilities="", channel_id=None, **options):
            seen.chats.append((text, options))
            timing.record_claude(0.9, HAIKU, 300, 40, purpose=options.get("purpose", ""))
            assert options.get("tools") is None, "chat has no tools"
            # As the real one does: chat remembers its own exchange
            llm.remember(channel_id, text, "Paris.")
            seen.order.append("answer")
            return llm.ChatResult(reply="Paris.")

        monkeypatch.setattr(llm, "call_tool", call_tool)
        monkeypatch.setattr(llm, "ask_claude", ask_claude)
        seen.left = queue

    seen.claude = claude

    def message(text, channel_id=INBOX, reply_to=None, message_id=None):
        replies = []

        async def reply(said, view=None):
            replies.append(said)
            seen.next_id += 1
            seen.bot_messages.append(seen.next_id)
            return SimpleNamespace(id=seen.next_id)

        async def recent_messages(limit):
            return [SimpleNamespace(id=bot_id, author=SimpleNamespace(bot=True)) for bot_id in reversed(seen.bot_messages)][:limit]

        seen.next_id += 1
        return SimpleNamespace(
            user=owner, channel_id=channel_id, message_id=message_id or seen.next_id, text=text,
            reply_target_id=reply_to, is_reply=reply_to is not None, reply=reply, recent_messages=recent_messages, replies=replies,
        )

    seen.message = message

    def say(text, **options):
        ctx = message(text, **options)
        return ctx, asyncio.run(conversation.handle(ctx, "the shortcuts", chat_here=seen.chat_here))

    seen.chat_here = True
    seen.say = say
    seen.owner = owner

    class Press:
        """Stands in for cards.Press."""

        db = database

        def __init__(self, arg, message_id=None):
            self.user, self.arg, self.message_id, self.channel_id, self.row_id = owner, str(arg), message_id, INBOX, None
            self.cards, self.told, self.removed = [], [], False

        async def update(self, card):
            cards.check(card)
            self.cards.append(card)

        async def say(self, text):
            self.told.append(text)

        async def remove(self):
            self.removed = True

    seen.Press = Press
    return seen


def run(coroutine):
    return asyncio.run(coroutine)


def rows():
    conn = database.connect()
    try:
        return conn.execute(
            "SELECT content, route, tasks, claude_calls, reply, status, extracted FROM message_log WHERE route IS NOT NULL ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def purposes():
    conn = database.connect()
    try:
        return conn.execute("SELECT purpose, task FROM llm_calls ORDER BY id").fetchall()
    finally:
        conn.close()


def open_cards():
    conn = database.connect()
    try:
        return [confirm._stored(row) for row in conn.execute(f"SELECT {confirm._COLUMNS} FROM confirm_cards ORDER BY id").fetchall()]
    finally:
        conn.close()


def shopping_list():
    return run(demo._items("shopping", 1))


# ---------------------------------------------------------------------------
# Anything else: the router, then extraction for the task
# ---------------------------------------------------------------------------
def test_a_setup_change_is_two_requests_and_a_card_and_nothing_is_saved(world):
    world.claude(route("shopping"), shop_add("milk", 1, guessed=["quantity"]))
    ctx, handled = world.say("add milk to the shopping list")

    assert handled.done
    assert [(request.purpose, request.task) for request in world.requests] == [("router", ""), ("extraction", "shopping")]
    assert "demo_shop_add" not in str(world.requests[0].tools), "the router never sees actions"
    assert world.requests[1].tools == ["demo_shop_add", "demo_shop_list", "demo_shop_tick", "demo_shop_clear", "none"]

    (message_id, card), = world.sent
    assert card.text.splitlines() == ["🛒 Shopping · new", "**milk** · × 1 ❓", "-# or tell me what to change"]
    assert [button.label for button in card.rows[0]] == ["Save", "Cancel"]
    assert shopping_list() == [], "a guess the user hasn't accepted is never saved"
    assert ctx.replies == [], "and Claude wrote nothing"

    (stored,) = open_cards()
    assert (stored.task, stored.action, stored.data, stored.guessed, stored.said, stored.status, stored.message_id) == (
        "shopping", "demo_shop_add", {"item": "milk", "quantity": 1}, ("quantity",), "add milk to the shopping list", "open", message_id,
    )


def test_save_applies_exactly_what_the_card_showed_and_python_says_so(world):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    (stored,) = open_cards()

    press = world.Press(stored.id, stored.message_id)
    result = run(confirm.on_save(press))
    assert press.cards[-1].text == "✅ Saved · 🛒 **milk** × 2 is on the shopping list"
    assert press.cards[-1].rows == (), "the buttons go"
    assert shopping_list() == [{"item": "milk", "quantity": 2}]
    assert open_cards()[0].status == "saved" and "saved shopping/demo_shop_add" in result
    assert run(scheduler.pending_jobs(confirm.JOB_TASK, confirm.JOB_KIND)) == [], "nothing left to expire"

    # Pressed again (a second tap, or an old card): nothing happens twice
    again = world.Press(stored.id)
    assert run(confirm.on_save(again)) == "card had gone"
    assert again.cards[-1].text == confirm.LAPSED and shopping_list() == [{"item": "milk", "quantity": 2}]


def test_cancel_removes_the_card_and_saves_nothing(world):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    (stored,) = open_cards()
    press = world.Press(stored.id)
    run(confirm.on_cancel(press))
    assert press.removed and open_cards()[0].status == "cancelled" and shopping_list() == []


def test_a_problem_is_shown_on_the_card_with_the_fix_applied(world):
    world.claude(route("shopping"), shop_add("eggs", 144))
    world.say("add 144 eggs")
    card = world.sent[0][1]
    assert card.text.splitlines() == [
        "🛒 Shopping · new",
        "**eggs** · × 20",
        "⚠️ 144 is more than the list takes: 20 at most",
        "-# or tell me what to change",
    ]
    assert open_cards()[0].data == {"item": "eggs", "quantity": 20}, "Save saves the fixed amount"


def test_an_action_that_only_logs_or_answers_needs_no_card(world):
    run(demo._save("shopping", 1, [{"item": "bread", "quantity": 1}, {"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), ("demo_shop_tick", {"item": "bread", "guessed": []}))
    world.say("got the bread")
    assert [card.text for _, card in world.sent] == ["☑️ Ticked off **bread** × 1 · still to buy: milk"]
    assert world.sent[0][1].rows == () and open_cards() == []
    assert shopping_list() == [{"item": "milk", "quantity": 2}], "done straight away"

    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    assert world.sent[-1][1].text == "## 🛒 Shopping list\n- **milk** × 2"


def test_a_destructive_action_gets_a_card_of_its_own_kind(world):
    run(demo._save("shopping", 1, [{"item": "bread", "quantity": 1}]))
    world.claude(route("shopping"), ("demo_shop_clear", {"guessed": []}))
    world.say("clear my shopping list")
    card = world.sent[0][1]
    assert card.text.splitlines()[:3] == ["🛒 Shopping · clear", "Clear the whole shopping list: 1 item.", "**This can't be undone.**"]
    confirm_button = card.rows[0][0]
    assert (confirm_button.label, confirm_button.style) == ("Clear for good", cards.DANGER)
    assert shopping_list() != []
    run(confirm.on_save(press := world.Press(open_cards()[0].id)))
    assert press.cards[-1].text == "🗑️ The shopping list is cleared." and shopping_list() == []


def test_when_nothing_fits_python_says_so_with_the_tasks_hint(world):
    world.claude(route("shopping"), ("none", {"reason": "not a shopping request"}))
    world.say("shopping is boring")
    assert world.sent[0][1].text == "🛒 I couldn't work that out for shopping. Try “add milk to the shopping list”."
    assert open_cards() == []


def test_what_claude_returns_is_checked_and_a_bad_call_is_nothing_fitted(world):
    world.claude(route("shopping"), ("demo_shop_add", {"item": "milk", "quantity": "two", "guessed": []}))
    world.say("add two milk")
    assert world.sent[0][1].text.startswith("🛒 I couldn't work that out for shopping.")
    assert json.loads(rows()[0][6])[0]["reason"] == "demo_shop_add: `quantity` must be integer"


def test_a_problem_the_user_can_fix_is_said_in_the_tasks_own_words(world):
    world.claude(route("shopping"), ("demo_shop_tick", {"item": "caviar", "guessed": []}))
    world.say("got the caviar")
    assert world.sent[0][1].text == "⚠️ “caviar” isn't on the shopping list. On it: nothing."
    assert rows()[0][5] == "error"


def test_two_tasks_in_one_message_each_get_their_own_card(world):
    world.claude(route("shopping", "packing"), shop_add("milk", 1), ("demo_pack_add", {"item": "passport", "bag": "carry-on", "guessed": []}))
    world.say("add milk to the shopping list and pack my passport in the carry-on")
    assert [card.text.splitlines()[0] for _, card in world.sent] == ["🛒 Shopping · new", "🧳 Packing · new"]
    assert [(request.purpose, request.task) for request in world.requests] == [
        ("router", ""), ("extraction", "shopping"), ("extraction", "packing"),
    ]
    assert len(open_cards()) == 2 and rows()[0][2] == "shopping,packing"


# ---------------------------------------------------------------------------
# Follow-ups stick to the open card
# ---------------------------------------------------------------------------
def test_a_message_straight_after_a_card_goes_to_its_task_without_the_router(world):
    world.claude(route("shopping"), shop_add("milk", 1, guessed=["quantity"]))
    world.say("add milk")
    first = world.sent[0][0]

    world.claude(shop_add("milk", 3))
    world.say("make it 3")

    assert [(request.purpose, request.task) for request in world.requests[2:]] == [("extraction", "shopping")], "one request"
    follow_up = world.requests[2]
    assert follow_up.tools[-2:] == ["none", "not_this"]
    assert '"quantity": 1' in follow_up.user and "still guessed: quantity" in follow_up.user

    assert world.deleted == [first], "the old card is deleted"
    assert world.sent[-1][1].text.splitlines()[1] == "**milk** · × 3", "and a fresh one posted, the guess settled"
    old, new = open_cards()
    assert (old.status, new.status, new.data, new.guessed) == ("replaced", "open", {"item": "milk", "quantity": 3}, ())
    assert new.said == "add milk", "it still knows what it came from"
    assert [row[1] for row in rows()] == ["router", "follow-up"]
    assert run(scheduler.pending_jobs(confirm.JOB_TASK, confirm.JOB_KIND))[0].payload == {"card": new.id}, "one expiry, the new card's"


def test_a_discord_reply_to_the_card_sticks_however_old_it_is(world, dev_clock):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    card_message = world.sent[0][0]
    world.bot_messages.append(9999)  # the bot has said something else since
    dev_clock.advance(timedelta(minutes=20))

    world.claude(shop_add("milk", 5))
    world.say("five please", reply_to=card_message)
    assert world.requests[-1].purpose == "extraction" and len(world.requests) == 3, "no router"
    assert open_cards()[-1].data == {"item": "milk", "quantity": 5}


def test_a_plain_message_does_not_stick_once_the_bot_has_said_something_else(world):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    world.bot_messages.append(9999)  # a timer went off in between

    world.claude(route("packing"), ("demo_pack_add", {"item": "socks", "guessed": []}))
    world.say("pack socks")
    router = world.requests[2]
    assert router.purpose == "router"
    assert "On screen, waiting for the user: a Shopping card (demo_shop_add) from the user saying: add milk" in router.user
    assert [card.status for card in open_cards()] == ["open", "open"], "the shopping card is left alone"


def test_a_plain_message_does_not_stick_to_a_card_older_than_five_minutes(world, dev_clock):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    dev_clock.advance(timedelta(minutes=confirm.STICKY_MINUTES, seconds=1))
    world.claude(route(), )
    world.say("what's the capital of France?")
    assert world.requests[2].purpose == "router"


@pytest.mark.parametrize(
    "age, replied_to, latest, expected",
    [
        (0, None, 50, True),  # the bot's latest message, and fresh
        (4, None, 50, True),
        (6, None, 50, False),  # too old
        (0, None, 51, False),  # the bot has said something since
        (0, None, None, False),
        (30, 50, 51, True),  # a reply to the card: always
        (0, 49, 50, False),  # a reply to something else: never
    ],
)
def test_when_a_message_is_taken_as_being_about_the_card(age, replied_to, latest, expected):
    now = utc_now()
    card = confirm.Stored(1, 1, INBOX, 50, confirm.CARD, "shopping", "demo_shop_add", {}, (), "add milk", confirm.OPEN, None, now - timedelta(minutes=age))
    assert confirm.sticks(card, now, replied_to=replied_to, latest_bot_message_id=latest) is expected


def test_a_closed_card_or_a_tie_question_never_sticks():
    now = utc_now()
    closed = confirm.Stored(1, 1, INBOX, 50, confirm.CARD, "shopping", "x", {}, (), "", confirm.SAVED, None, now)
    tie = confirm.Stored(1, 1, INBOX, 50, confirm.TIE, "", "", {}, (), "", confirm.OPEN, None, now)
    assert not confirm.sticks(closed, now, latest_bot_message_id=50) and not confirm.sticks(tie, now, latest_bot_message_id=50)


def test_not_this_hands_the_message_to_the_router_and_the_new_card_takes_the_old_ones_place(world):
    world.claude(route("packing"), ("demo_pack_add", {"item": "socks", "guessed": ["bag"]}))
    world.say("add socks")
    packing_card = world.sent[0][0]

    world.claude(("not_this", {"reason": "wants the other list"}), route("shopping"), shop_add("socks", 1, guessed=["quantity"]))
    world.say("no, shopping")

    assert [(request.purpose, request.task) for request in world.requests[2:]] == [
        ("extraction", "packing"), ("router", ""), ("extraction", "shopping"),
    ]
    assert "Just before this, the user said: add socks" in world.requests[-1].user
    assert world.deleted == [packing_card]
    assert world.sent[-1][1].text.splitlines()[:2] == ["🛒 Shopping · new", "**socks** · × 1 ❓"]
    assert [(card.task, card.status) for card in open_cards()] == [("packing", "replaced"), ("shopping", "open")]


def test_not_this_for_something_unrelated_leaves_the_card_alone(world):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    world.claude(("not_this", {"reason": "a general question"}), route())
    world.say("what's the capital of France?")
    assert world.chats and open_cards()[0].status == "open" and world.deleted == []


# ---------------------------------------------------------------------------
# A genuine tie: buttons, never a guess
# ---------------------------------------------------------------------------
def test_a_tie_asks_which_task_with_a_button_each_and_runs_nothing(world):
    world.claude(route("shopping", "packing", tie=True))
    world.say("add socks")
    (message_id, card), = world.sent
    assert card.text == "Which is “add socks” for?"
    assert [(button.emoji, button.label) for button in card.rows[0]] == [("🛒", "Shopping"), ("🧳", "Packing"), ("✖️", "Neither")]
    assert len(world.requests) == 1, "no extraction until the user says which"
    (question,) = open_cards()
    assert (question.kind, question.data, question.said) == ("tie", {"tasks": ["shopping", "packing"]}, "add socks")
    assert rows()[0][2] == "shopping,packing"


def test_picking_a_task_runs_extraction_on_what_was_said(world):
    world.claude(route("shopping", "packing", tie=True))
    world.say("add socks")
    (question,) = open_cards()

    world.claude(("demo_pack_add", {"item": "socks", "guessed": ["bag"]}))
    press = world.Press(f"{question.id}:packing", question.message_id)
    result = run(conversation.on_pick(press))

    assert press.removed, "the question goes"
    assert world.requests[-1].purpose == "extraction" and world.requests[-1].task == "packing"
    assert "The message:\nadd socks" in world.requests[-1].user
    assert world.sent[-1][1].text.splitlines()[:2] == ["🧳 Packing · new", "**socks** · checked bag ❓"]
    assert [(card.kind, card.status) for card in open_cards()] == [("tie", "picked"), ("card", "open")]
    assert result.startswith("picked packing")

    # Pressed again, the question has gone
    again = world.Press(f"{question.id}:shopping")
    assert run(conversation.on_pick(again)) == "question had gone" and again.cards[-1].text == confirm.LAPSED


def test_neither_removes_the_question(world):
    world.claude(route("shopping", "packing", tie=True))
    world.say("add socks")
    (question,) = open_cards()
    run(confirm.on_cancel(press := world.Press(question.id)))
    assert press.removed and open_cards()[0].status == "cancelled"


# ---------------------------------------------------------------------------
# Not a task: chat, with no tools
# ---------------------------------------------------------------------------
def test_a_general_question_is_a_plain_reply_with_no_tools(world):
    world.claude(route())
    ctx, handled = world.say("what's the capital of France?")
    assert handled.done and ctx.replies == ["Paris."]
    (text, options), = world.chats
    assert text == "what's the capital of France?" and options.get("tools") is None and options["purpose"] == "chat"
    assert rows()[0][1:4] == ("chat", "", 2) and purposes() == [("router", ""), ("chat", "")]


def test_while_tasks_remain_on_the_old_way_chat_is_handed_back_with_its_log_row(world):
    world.chat_here = False
    world.claude(route())
    ctx, handled = world.say("set a timer for 5 minutes")
    assert not handled.done and handled.row_id is not None
    assert ctx.replies == [] and world.chats == [] and world.sent == []
    assert rows() == [], "the row is the caller's to finish: one message, logged once"


def test_with_nothing_in_the_catalogue_nothing_is_asked_at_all(world, monkeypatch):
    monkeypatch.setattr(actions, "_entries", {})
    world.claude()
    ctx, handled = world.say("hello")
    assert not handled.done and handled.row_id is None and world.requests == []


def test_the_router_listens_in_the_inbox_and_the_hub_only():
    assert conversation.listens_in(INBOX) and conversation.listens_in(HUB)
    assert not conversation.listens_in(300) and not conversation.listens_in(999)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------
def test_a_card_left_for_thirty_minutes_is_deleted_and_nothing_is_saved(world, dev_clock):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    (stored,) = open_cards()

    async def later():
        dev_clock.advance(timedelta(minutes=confirm.EXPIRY_MINUTES + 1))
        return await scheduler.run_all_due()

    assert run(later()) == 1
    assert world.deleted == [stored.message_id] and open_cards()[0].status == "expired" and shopping_list() == []
    press = world.Press(stored.id)
    assert run(confirm.on_save(press)) == "card had gone" and shopping_list() == []


def test_with_clean_up_off_an_expired_card_stays_and_says_so(world, dev_clock, dev_off):
    from core import devmode

    devmode.enable()
    devmode.set_cleanup(False)
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")

    async def later():
        dev_clock.advance(timedelta(minutes=confirm.EXPIRY_MINUTES + 1))
        await scheduler.run_all_due()

    run(later())
    assert world.deleted == [] and world.edited == [(world.sent[0][0], "⌛ Expired: nothing was saved.")]


def test_a_card_survives_a_restart_because_it_is_a_row(world):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    (stored,) = open_cards()
    # Nothing is held in memory: a new process finds the card, its data and its buttons' ids
    card = world.sent[0][1]
    assert [cards.make_id("b", button.task, button.action, button.arg) for button in card.rows[0]] == [
        f"card.b:confirm:save:{stored.id}", f"card.b:confirm:cancel:{stored.id}",
    ]
    assert ("confirm", "save") in cards._actions and ("confirm", "pick") in cards._actions
    assert run(confirm.message_class(stored.message_id)) is not None
    run(confirm.on_save(world.Press(stored.id)))
    assert run(confirm.message_class(stored.message_id)) is None, "saved: no longer live"


# ---------------------------------------------------------------------------
# Save, when things have changed since the card
# ---------------------------------------------------------------------------
def test_a_problem_at_save_is_told_to_the_presser_and_the_card_stays_open(world):
    world.claude(route("packing"), ("demo_pack_add", {"item": "socks", "bag": "checked", "guessed": []}))
    world.say("pack socks in the checked bag")
    (stored,) = open_cards()
    run(demo._save("packing", 1, [{"item": "socks", "bag": "carry-on"}]))  # added some other way meanwhile
    with pytest.raises(UserError, match="socks is already on the packing list"):
        run(confirm.on_save(world.Press(stored.id)))
    assert open_cards()[0].status == "open"


def test_someone_elses_card_cannot_be_saved(world, stranger):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    (stored,) = open_cards()
    press = world.Press(stored.id)
    press.user = stranger
    assert run(confirm.on_save(press)) == "card had gone" and shopping_list() == []


# ---------------------------------------------------------------------------
# What a card looks like
# ---------------------------------------------------------------------------
def test_a_card_states_the_task_the_kind_of_change_every_line_and_every_warning():
    proposal = Proposal(
        lines=("**G** · 10× daily, fixed times every 2h", "First `8:00 am` ❓ · last `12:00 am`"),
        data={}, warnings=("Only 9 fit before midnight",),
    )
    pills = actions.Entry("pills", "💊", "x", ("a", "b"), ())
    card = confirm.render(pills, proposal, 7)
    assert card.text.splitlines() == [
        "💊 Pills · new",
        "**G** · 10× daily, fixed times every 2h",
        "First `8:00 am` ❓ · last `12:00 am`",
        "⚠️ Only 9 fit before midnight",
        "-# or tell me what to change",
    ]
    assert [(button.emoji, button.label, button.action, button.arg) for button in card.rows[0]] == [
        ("✅", "Save", "save", "7"), ("✖️", "Cancel", "cancel", "7"),
    ]


# ---------------------------------------------------------------------------
# The log: route, tasks, what was extracted, the outcome and the cost
# ---------------------------------------------------------------------------
def test_every_message_is_logged_with_its_route_tasks_extraction_and_each_request(world):
    world.claude(route("shopping"), shop_add("milk", 1, guessed=["quantity"]))
    world.say("add milk")
    (content, route_taken, tasks, calls, reply, status, extracted), = rows()
    assert (content, route_taken, tasks, calls, status) == ("add milk", "router", "shopping", 2, "ok")
    assert reply == "card: shopping · new: **milk** · × 1 ❓"
    assert json.loads(extracted) == [{"task": "shopping", "action": "demo_shop_add", "data": {"item": "milk", "quantity": 1}, "guessed": ["quantity"]}]
    assert purposes() == [("router", ""), ("extraction", "shopping")]

    conn = database.connect()
    cost = conn.execute("SELECT cost_usd, duration_s FROM message_log WHERE route = 'router'").fetchone()
    conn.close()
    assert cost[0] == pytest.approx(2 * costs.price(HAIKU, 500, 30)) and cost[1] is not None


def test_the_exchange_is_remembered_in_pythons_words_for_the_router_to_see(world):
    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    assert llm.history_for(INBOX)[-2:] == [
        {"role": "user", "content": "what do I need to buy?"},
        {"role": "assistant", "content": "🛒 The shopping list is empty."},
    ]
    world.claude(route())
    world.say("thanks")
    assert "User: what do I need to buy?\nBot: 🛒 The shopping list is empty." in world.requests[-1].user


def test_a_crash_in_a_tasks_code_is_reported_and_the_user_is_told_it_did_not_work(world, monkeypatch):
    errors = []

    async def log_error(title, details, user_text=None):
        errors.append(title)

    monkeypatch.setattr(conversation, "log_error", log_error)

    async def boom(request, data, guessed):
        raise RuntimeError("boom")

    broken = actions.Entry("shopping", "🛒", "x", ("a", "b"), (actions.Action("demo_shop_list", "List.", needs_card=False, run=boom),))
    actions.set_catalogue([broken])
    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    assert world.sent[0][1].text == conversation.WENT_WRONG and errors == ["Action failed: demo_shop_list"]
    assert rows()[0][5] == "error"


# ---------------------------------------------------------------------------
# Mixed messages: every part is dealt with
# ---------------------------------------------------------------------------
MIXED = "what's the capital of France, and add milk to the shopping list"


def test_a_question_and_a_request_in_one_message_get_an_answer_and_a_card(world):
    # QA 2026-10-09: this made the milk card and left the question unanswered
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk", 1, guessed=["quantity"]))
    ctx, handled = world.say(MIXED)

    assert handled.done
    assert ctx.replies == ["Paris."], "the chat part is answered"
    (text, options), = world.chats
    assert text == "what's the capital of France", "only that part is put to Claude, with no tools"
    assert options.get("tools") is None and options["purpose"] == "chat"
    assert world.sent[0][1].text.splitlines()[:2] == ["🛒 Shopping · new", "**milk** · × 1 ❓"], "and the card is made"
    assert world.order == ["answer", "card"], "the answer first, so the card stays the last thing on screen"
    assert shopping_list() == []

    (content, route_taken, tasks, calls, reply, status, _), = rows()
    assert (route_taken, tasks, calls, status) == ("router", "shopping", 3, "ok")
    assert reply == "Paris.\ncard: shopping · new: **milk** · × 1 ❓"
    assert purposes() == [("router", ""), ("chat", ""), ("extraction", "shopping")]


def test_a_correction_still_finds_the_card_after_a_mixed_message(world):
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk", 1, guessed=["quantity"]))
    world.say(MIXED)
    world.claude(shop_add("milk", 3))
    world.say("make it 3")
    assert world.requests[-1].purpose == "extraction" and len(world.requests) == 3, "a follow-up: no router"
    assert world.sent[-1][1].text.splitlines()[1] == "**milk** · × 3"


def test_a_question_and_two_requests_get_an_answer_and_two_cards(world):
    world.claude(
        route("packing", "shopping", chat_part="tell me a joke"),
        ("demo_pack_add", {"item": "charger", "guessed": ["bag"]}),
        shop_add("batteries", 1, guessed=["quantity"]),
    )
    ctx, _ = world.say("pack my charger, put batteries on the shopping list, and tell me a joke")
    assert ctx.replies == ["Paris."] and world.chats[0][0] == "tell me a joke"
    assert [card.text.splitlines()[0] for _, card in world.sent] == ["🧳 Packing · new", "🛒 Shopping · new"]
    assert world.order == ["answer", "card", "card"]
    assert rows()[0][2:4] == ("packing,shopping", 4)


def test_a_request_with_no_chat_part_gets_no_chat_reply(world):
    world.claude(route("shopping"), shop_add("eggs", 1, guessed=["quantity"]))
    ctx, _ = world.say("hi, could you add eggs to the shopping list please?")
    assert ctx.replies == [] and world.chats == [] and len(world.requests) == 2


def test_a_mixed_message_with_a_tie_answers_then_asks_which(world):
    world.claude(route("shopping", "packing", tie=True, chat_part="what's the capital of France"))
    ctx, _ = world.say("what's the capital of France, and add socks")
    assert ctx.replies == ["Paris."] and world.sent[0][1].text.startswith("Which is")
    assert world.order == ["answer", "card"]


def test_a_mixed_message_is_remembered_once_as_a_whole(world):
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk", 1))
    world.say(MIXED)
    assert llm.history_for(INBOX) == [
        {"role": "user", "content": MIXED},
        {"role": "assistant", "content": "Paris.\ncard: shopping · new: **milk** · × 1"},
    ]


def test_while_tasks_remain_on_the_old_way_a_mixed_message_is_still_dealt_with_here(world):
    world.chat_here = False  # #inbox, before the old way has gone
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk", 1))
    ctx, handled = world.say(MIXED)
    assert handled.done and ctx.replies == ["Paris."] and len(world.sent) == 1


def test_ticking_off_names_what_is_left_so_a_count_cannot_be_misread(world):
    # QA 2026-10-09: "Ticked off milk · 1 left to buy" read as if milk went from 3 to 1
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 3}, {"item": "eggs", "quantity": 20}]))
    world.claude(route("shopping"), ("demo_shop_tick", {"item": "milk", "guessed": []}))
    world.say("got the milk")
    assert world.sent[-1][1].text == "☑️ Ticked off **milk** × 3 · still to buy: eggs"
    world.claude(route("shopping"), ("demo_shop_tick", {"item": "eggs", "guessed": []}))
    world.say("got the eggs")
    assert world.sent[-1][1].text == "☑️ Ticked off **eggs** × 20 · nothing left to buy"
