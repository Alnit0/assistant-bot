"""A message in plain words, end to end: follow-up, router, extraction, confirm cards, ties and chat
(core/conversation.py, core/confirm.py), with the two demo tasks and a scripted Claude."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, confirm, conversation, costs, database, live, livelists, llm, scheduler, timing
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


def _guesses(guessed, index=0):
    """A test's "quantity" as Claude names it: its place in the list."""
    return [name if "[" in name else f"items[{index}].{name}" for name in guessed]


def _thing(thing):
    """A name, (name, quantity) or (name, quantity, change) as an item."""
    if isinstance(thing, str):
        return {"item": thing}
    item = {"item": thing[0]}
    if thing[1] is not None:
        item["quantity"] = thing[1]
    if len(thing) > 2:
        item["change"] = thing[2]
    return item


def shop_add(item, quantity=None, guessed=(), not_included=(), change=None):
    """One thing on the shopping list. `guessed` names its fields ("quantity");
    `change` is add (the default), set or remove."""
    thing = _thing((item, quantity, change) if change else (item, quantity))
    return ("demo_shop_change", {"items": [thing], "guessed": _guesses(guessed), "not_included": list(not_included)})


def shop_add_all(*things, guessed=(), not_included=()):
    """Several things: names, (name, quantity) or (name, quantity, change)."""
    return ("demo_shop_change", {"items": [_thing(thing) for thing in things], "guessed": list(guessed), "not_included": list(not_included)})


def SAVED(*things, last=None):
    """Items as a card keeps them: each with its amount and what to do with it,
    and the one mentioned last (the last of them, unless said)."""
    return {
        "items": [{"item": name, "quantity": quantity, "change": change} for name, quantity, change in things],
        "_last": last or things[-1][0],
    }


def tick(*names):
    return ("demo_shop_tick", {"items": [{"item": name} for name in names], "guessed": [], "not_included": []})


def pack(item, bag=None, guessed=(), change=None):
    thing = {"item": item} if bag is None else {"item": item, "bag": bag}
    if change:
        thing["change"] = change
    return ("demo_pack_change", {"items": [thing], "guessed": _guesses(guessed), "not_included": []})


@pytest.fixture
def world(make_db, monkeypatch, owner):
    """A database, the two demo tasks in the catalogue, a channel that records, and a Claude that is scripted."""
    # The real tasks' tables too: the golden conversations (tests/test_golden.py) use this world
    from tasks.pills import store as pills_store
    from tasks.timers import store as timers_store

    make_db({"lab": state.MIGRATIONS, "pills": pills_store.MIGRATIONS, "timers": timers_store.MIGRATIONS})
    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue(demo.ENTRIES)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(scheduler, "_handlers", dict(scheduler._handlers))
    monkeypatch.setattr(llm, "_histories", {})
    live.reset()
    conversation.setup()

    seen = SimpleNamespace(sent=[], deleted=[], edited=[], requests=[], chats=[], next_id=5000, bot_messages=[], order=[], reactions=[])

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

        async def acknowledge(emoji="✅"):
            seen.reactions.append((text, emoji))

        seen.next_id += 1
        return SimpleNamespace(
            user=owner, channel_id=channel_id, message_id=message_id or seen.next_id, text=text,
            reply_target_id=reply_to, is_reply=reply_to is not None, reply=reply, recent_messages=recent_messages, replies=replies,
            acknowledge=acknowledge,
        )

    seen.message = message

    def say(text, **options):
        ctx = message(text, **options)
        return ctx, run(conversation.handle(ctx, "the shortcuts", chat_here=seen.chat_here))

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
    """Run it, and let anything it left for the background (a Live list's rewrite) finish."""

    async def to_the_end():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(to_the_end())


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
    world.claude(route("shopping"), shop_add("milk"))
    ctx, handled = world.say("add milk to the shopping list")

    assert handled.done
    assert [(request.purpose, request.task) for request in world.requests] == [("router", ""), ("extraction", "shopping")]
    assert "demo_shop_change" not in str(world.requests[0].tools), "the router never sees actions"
    assert world.requests[1].tools == ["demo_shop_change", "demo_shop_list", "demo_shop_tick", "demo_shop_clear", "none"]

    (message_id, card), = world.sent
    assert card.text.splitlines() == ["🛒 Shopping · new", "milk · × 1", "-# or tell me what to change"]
    assert [button.label for button in card.rows[0]] == ["Save", "Cancel"]
    assert shopping_list() == [], "a guess the user hasn't accepted is never saved"
    assert ctx.replies == [], "and Claude wrote nothing"

    (stored,) = open_cards()
    assert (stored.task, stored.action, stored.data, stored.guessed, stored.said, stored.status, stored.message_id) == (
        "shopping", "demo_shop_change", SAVED(("milk", 1, "add")), (), "add milk to the shopping list", "open", message_id,
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
    assert open_cards()[0].status == "saved" and "saved shopping/demo_shop_change" in result
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
        "eggs · × 20",
        "⚠️ eggs: 144 is more than the list takes, 20 at most",
        "-# or tell me what to change",
    ]
    assert open_cards()[0].data == SAVED(("eggs", 20, "add")), "Save saves the fixed amount"


def test_an_action_that_only_logs_or_answers_needs_no_card(world):
    run(demo._save("shopping", 1, [{"item": "bread", "quantity": 1}, {"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), tick("bread"))
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
    assert card.text.splitlines()[:3] == ["🛒 Shopping · remove", "Clear the whole shopping list: 1 item.", "**This can't be undone.**"]
    confirm_button = card.rows[0][0]
    assert (confirm_button.label, confirm_button.style) == ("Clear for good", cards.DANGER)
    assert shopping_list() != []
    run(confirm.on_save(press := world.Press(open_cards()[0].id)))
    assert press.cards[-1].text == "🗑️ The shopping list is cleared." and shopping_list() == []


def test_when_nothing_fits_python_says_so_in_neutral_words_naming_no_task(world):
    # QA 2026-10-10: "open the post" was answered with how to report a bug
    world.claude(route("shopping"), ("none", {"reason": "not a shopping request"}))
    world.say("shopping is boring")
    assert world.sent[0][1].text == "🤔 I didn't understand that."
    assert "shopping" not in world.sent[0][1].text and "Try" not in world.sent[0][1].text
    assert open_cards() == []


def test_what_claude_returns_is_checked_and_a_bad_call_is_nothing_fitted(world):
    world.claude(route("shopping"), ("demo_shop_change", {"items": "milk", "guessed": []}))
    world.say("add two milk")
    assert world.sent[0][1].text == "🤔 I didn't understand that."
    assert json.loads(rows()[0][6])[0]["reason"] == "demo_shop_change: `items` must be a list of items"


def test_a_problem_the_user_can_fix_is_said_in_the_tasks_own_words(world):
    world.claude(route("shopping"), tick("caviar"))
    world.say("got the caviar")
    assert world.sent[0][1].text == "⚠️ “caviar” isn't on the shopping list. On it: nothing."
    assert rows()[0][5] == "error"


def test_two_tasks_in_one_message_each_get_their_own_card(world):
    world.claude(route("shopping", "packing"), shop_add("milk", 1), pack("passport", "carry-on"))
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
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    first = world.sent[0][0]

    world.claude(shop_add("milk", 3, change="set"))
    world.say("make it 3")

    assert [(request.purpose, request.task) for request in world.requests[2:]] == [("extraction", "shopping")], "one request"
    follow_up = world.requests[2]
    assert follow_up.tools[-2:] == ["none", "not_this"]
    assert "1. item: milk, quantity: 1, change: add" in follow_up.user and "what the user has said about it, oldest first: add milk" in follow_up.user

    assert world.deleted == [first], "the old card is deleted"
    assert world.sent[-1][1].text.splitlines()[1] == "milk · × 3", "and a fresh one posted"
    old, new = open_cards()
    assert (old.status, new.status, new.data, new.guessed) == ("replaced", "open", SAVED(("milk", 3, "set")), ())
    assert new.said == "add milk\nmake it 3", "it knows everything said about it"
    assert new.previous == SAVED(("milk", 1, "add")), "and what it was before this change"
    assert [row[1] for row in rows()] == ["router", "follow-up"]
    assert run(scheduler.pending_jobs(confirm.JOB_TASK, confirm.JOB_KIND))[0].payload == {"card": new.id}, "one expiry, the new card's"


def test_a_discord_reply_to_the_card_sticks_however_old_it_is(world, dev_clock):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    card_message = world.sent[0][0]
    world.bot_messages.append(9999)  # the bot has said something else since
    dev_clock.advance(timedelta(minutes=20))

    world.claude(shop_add("milk", 5, change="set"))
    world.say("five please", reply_to=card_message)
    assert world.requests[-1].purpose == "extraction" and len(world.requests) == 3, "no router"
    assert open_cards()[-1].data == SAVED(("milk", 5, "set"))


def test_a_plain_message_does_not_stick_once_the_bot_has_said_something_else(world):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    world.bot_messages.append(9999)  # a timer went off in between

    world.claude(route("packing"), pack("socks"))
    world.say("pack socks")
    router = world.requests[2]
    assert router.purpose == "router"
    assert "On screen, waiting for the user: a Shopping card (demo_shop_change) from the user saying: add milk" in router.user
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
    card = confirm.Stored(1, 1, INBOX, 50, confirm.CARD, "shopping", "demo_shop_change", {}, (), "add milk", confirm.OPEN, None, now - timedelta(minutes=age))
    assert confirm.sticks(card, now, replied_to=replied_to, latest_bot_message_id=latest) is expected


def test_a_closed_card_or_a_tie_question_never_sticks():
    now = utc_now()
    closed = confirm.Stored(1, 1, INBOX, 50, confirm.CARD, "shopping", "x", {}, (), "", confirm.SAVED, None, now)
    tie = confirm.Stored(1, 1, INBOX, 50, confirm.TIE, "", "", {}, (), "", confirm.OPEN, None, now)
    assert not confirm.sticks(closed, now, latest_bot_message_id=50) and not confirm.sticks(tie, now, latest_bot_message_id=50)


def test_no_shopping_only_re_routes_the_card_and_its_words_never_reach_claude_at_all(world):
    # QA 2026-10-09: "no, shopping" was saved as an item called shopping
    world.claude(route("packing"), pack("socks"))
    world.say("add socks")
    packing_card = world.sent[0][0]

    world.claude()  # nothing is scripted: none is needed
    world.say("no, shopping")

    assert world.requests[2:] == [], "the items are carried over in code: no request, nothing to misread"
    assert world.deleted == [packing_card]
    assert world.sent[-1][1].text.splitlines()[:2] == ["🛒 Shopping · new", "socks · × 1"]
    packing, shopping = open_cards()
    assert (packing.status, shopping.status, shopping.said) == ("replaced", "open", "add socks")
    assert shopping.data == SAVED(("socks", 1, "add")) and shopping.previous is None
    assert rows()[-1][1:4] == ("follow-up", "shopping", 0)
    run(confirm.on_save(world.Press(shopping.id)))
    assert shopping_list() == [{"item": "socks", "quantity": 1}], "socks, and nothing called shopping"


@pytest.mark.parametrize(
    "said, target",
    [
        ("no, shopping", "shopping"),
        ("No, shopping.", "shopping"),
        ("nope, the shopping list", "shopping"),
        ("no the shopping one", "shopping"),
        ("I meant shopping", "shopping"),
        ("not that, shopping", "shopping"),
        ("wrong list, shopping", "shopping"),
        ("sorry, I meant the shopping list", "shopping"),
        ("shopping instead", "shopping"),
        ("put it on the shopping list instead", "shopping"),
        ("no, for shopping please", "shopping"),
        # not a redirect: these are left to the router and extraction
        ("no, packing", None),  # the card is already for packing
        ("shopping", None),
        ("shopping list", None),
        ("no", None),
        ("no, add milk to the shopping list", None),
        ("no, shopping is boring", None),
        ("add shopping", None),
    ],
)
def test_what_counts_as_a_bare_redirect(said, target):
    found = confirm.redirect(said, demo.ENTRIES, current="packing")
    assert (found.name if found else None) == target


def test_a_redirect_in_looser_words_goes_by_the_router_with_what_was_asked_before(world):
    world.claude(route("packing"), pack("socks"))
    world.say("add socks")

    world.claude(("not_this", {"reason": "wants the other list"}), route("shopping"), shop_add("socks"))
    world.say("actually that belongs with the things to buy")

    assert [(request.purpose, request.task) for request in world.requests[2:]] == [
        ("extraction", "packing"), ("router", ""), ("extraction", "shopping"),
    ]
    told = world.requests[-1].user
    assert "Just before this, the user asked: add socks" in told
    assert "the words that redirect it are never an item, a name or any other value" in told
    assert world.sent[-1][1].text.splitlines()[:2] == ["🛒 Shopping · new", "socks · × 1"]
    assert [(card.task, card.status) for card in open_cards()] == [("packing", "replaced"), ("shopping", "open")], (
        "the same socks, for the other list: the packing card is replaced, not left beside the new one"
    )
    assert "redirect check: card 1 holds the same items, so the new card replaces it" in traces()[-1]["checks"]


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

    world.claude(pack("socks"))
    press = world.Press(f"{question.id}:packing", question.message_id)
    result = run(conversation.on_pick(press))

    assert press.removed, "the question goes"
    assert world.requests[-1].purpose == "extraction" and world.requests[-1].task == "packing"
    assert "The message:\nadd socks" in world.requests[-1].user
    assert world.sent[-1][1].text.splitlines()[:2] == ["🧳 Packing · new", "socks · checked bag"]
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
    world.claude(route("packing"), pack("socks", "checked"))
    world.say("pack socks in the checked bag")
    (stored,) = open_cards()
    run(demo._save("packing", 1, [{"item": "socks", "bag": "carry-on"}]))  # added some other way meanwhile
    with pytest.raises(UserError, match="all on the packing list already"):
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
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    (content, route_taken, tasks, calls, reply, status, extracted), = rows()
    assert (content, route_taken, tasks, calls, status) == ("add milk", "router", "shopping", 2, "ok")
    assert reply == "card: shopping · new: milk · × 1"
    assert json.loads(extracted) == [{"task": "shopping", "action": "demo_shop_change", "data": {"items": [{"item": "milk"}]}, "guessed": []}]
    assert purposes() == [("router", ""), ("extraction", "shopping")]

    conn = database.connect()
    cost = conn.execute("SELECT cost_usd, duration_s FROM message_log WHERE route = 'router'").fetchone()
    conn.close()
    assert cost[0] == pytest.approx(2 * costs.price(HAIKU, 500, 30)) and cost[1] is not None


def test_the_exchange_is_remembered_in_pythons_words_for_the_router_to_see(world):
    world.claude(route("shopping"), tick("caviar"))
    world.say("got the caviar")
    said = "⚠️ “caviar” isn't on the shopping list. On it: nothing."
    assert llm.history_for(INBOX)[-2:] == [
        {"role": "user", "content": "got the caviar"},
        {"role": "assistant", "content": said},
    ]
    world.claude(route())
    world.say("thanks")
    assert f"User: got the caviar\nBot: {said}" in world.requests[-1].user


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
    _, handled = world.say("what do I need to buy?")
    assert errors == ["Action failed: demo_shop_list"] and rows()[0][5] == "error"
    assert world.sent == [], "nothing I could do about it, so no words: the ⚠️ on my message says it"
    assert handled.failed, "the caller swaps 👀 for ⚠️"
    assert traces()[-1]["error"] == "Action failed: demo_shop_list: RuntimeError('boom')", "kept for dev why and a bug report"


def test_a_failure_i_can_do_something_about_gets_one_plain_line(world, monkeypatch):
    async def quiet(*args, **options):
        return None

    monkeypatch.setattr(conversation, "log_error", quiet)

    class APITimeoutError(Exception):
        pass

    async def call_tool(*args, **options):
        raise APITimeoutError("timed out")

    monkeypatch.setattr(llm, "call_tool", call_tool)
    _, handled = world.say("add milk")
    assert [card.text for _, card in world.sent] == ["⏳ Claude didn't answer just now. Wait a moment and send it again."]
    assert handled.failed and handled.done and rows()[-1][5] == "error"
    assert traces()[-1]["error"].startswith("Message failed: APITimeoutError")


def test_what_i_can_act_on_is_a_matter_of_what_failed():
    class RateLimitError(Exception):
        pass

    class Overloaded(Exception):
        status_code = 529

    assert conversation.what_i_can_do(RateLimitError()) == conversation.BUSY
    assert conversation.what_i_can_do(Overloaded()) == conversation.BUSY
    assert conversation.what_i_can_do(KeyError("x")) == "" and conversation.what_i_can_do(RuntimeError("boom")) == ""


def test_a_problem_i_can_fix_is_said_in_the_tasks_words_and_kept_as_the_error(world):
    world.claude(route("shopping"), tick("caviar"))
    _, handled = world.say("got the caviar")
    assert world.sent[0][1].text.startswith("⚠️ “caviar” isn't on the shopping list") and handled.failed
    assert traces()[-1]["error"].startswith("demo_shop_tick: “caviar” isn't on the shopping list")


# ---------------------------------------------------------------------------
# Mixed messages: every part is dealt with
# ---------------------------------------------------------------------------
MIXED = "what's the capital of France, and add milk to the shopping list"


def test_a_question_and_a_request_in_one_message_get_an_answer_and_a_card(world):
    # QA 2026-10-09: this made the milk card and left the question unanswered
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk"))
    ctx, handled = world.say(MIXED)

    assert handled.done
    assert ctx.replies == ["Paris."], "the chat part is answered"
    (text, options), = world.chats
    assert text == "what's the capital of France", "only that part is put to Claude, with no tools"
    assert options.get("tools") is None and options["purpose"] == "chat"
    assert world.sent[0][1].text.splitlines()[:2] == ["🛒 Shopping · new", "milk · × 1"], "and the card is made"
    assert world.order == ["answer", "card"], "the answer first, so the card stays the last thing on screen"
    assert shopping_list() == []

    (content, route_taken, tasks, calls, reply, status, _), = rows()
    assert (route_taken, tasks, calls, status) == ("router", "shopping", 3, "ok")
    assert reply == "Paris.\ncard: shopping · new: milk · × 1"
    assert purposes() == [("router", ""), ("chat", ""), ("extraction", "shopping")]


def test_a_correction_still_finds_the_card_after_a_mixed_message(world):
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk"))
    world.say(MIXED)
    world.claude(shop_add("milk", 3, change="set"))
    world.say("make it 3")
    assert world.requests[-1].purpose == "extraction" and len(world.requests) == 3, "a follow-up: no router"
    assert world.sent[-1][1].text.splitlines()[1] == "milk · × 3"


def test_a_question_and_two_requests_get_an_answer_and_two_cards(world):
    world.claude(
        route("packing", "shopping", chat_part="tell me a joke"),
        pack("charger"),
        shop_add("batteries"),
    )
    ctx, _ = world.say("pack my charger, put batteries on the shopping list, and tell me a joke")
    assert ctx.replies == ["Paris."] and world.chats[0][0] == "tell me a joke"
    assert [card.text.splitlines()[0] for _, card in world.sent] == ["🧳 Packing · new", "🛒 Shopping · new"]
    assert world.order == ["answer", "card", "card"]
    assert rows()[0][2:4] == ("packing,shopping", 4)


def test_a_request_with_no_chat_part_gets_no_chat_reply(world):
    world.claude(route("shopping"), shop_add("eggs"))
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
        {"role": "assistant", "content": "Paris.\ncard: shopping · new: milk · × 1"},
    ]


def test_while_tasks_remain_on_the_old_way_a_mixed_message_is_still_dealt_with_here(world):
    world.chat_here = False  # #inbox, before the old way has gone
    world.claude(route("shopping", chat_part="what's the capital of France"), shop_add("milk", 1))
    ctx, handled = world.say(MIXED)
    assert handled.done and ctx.replies == ["Paris."] and len(world.sent) == 1


def test_ticking_off_names_what_is_left_so_a_count_cannot_be_misread(world):
    # QA 2026-10-09: "Ticked off milk · 1 left to buy" read as if milk went from 3 to 1
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 3}, {"item": "eggs", "quantity": 20}]))
    world.claude(route("shopping"), tick("milk"))
    world.say("got the milk")
    assert world.sent[-1][1].text == "☑️ Ticked off **milk** × 3 · still to buy: eggs"
    world.claude(route("shopping"), tick("eggs"))
    world.say("got the eggs")
    assert world.sent[-1][1].text == "☑️ Ticked off **eggs** × 20 · nothing left to buy"


# ---------------------------------------------------------------------------
# The open card goes with the message, whichever way it is routed
# ---------------------------------------------------------------------------
def test_a_correction_after_the_bot_has_said_something_else_still_reaches_the_card(world):
    # QA 2026-10-09: "add bread", a question, then "make it 2" got "I couldn't work that out":
    # the router chose shopping but the card wasn't passed on
    world.claude(route("shopping"), shop_add("bread"))
    world.say("add bread")
    bread_card = world.sent[0][0]
    world.bot_messages.append(9999)  # an answer to something else in between

    world.claude(route("shopping"), shop_add("bread", 2, change="set"))
    world.say("make it 2")

    router, extraction_request = world.requests[2:]
    assert router.purpose == "router" and "a Shopping card (demo_shop_change) from the user saying: add bread" in router.user
    assert extraction_request.tools[-2:] == ["none", "not_this"], "extraction is told about the card"
    assert "1. item: bread, quantity: 1, change: add" in extraction_request.user
    assert world.deleted == [bread_card] and world.sent[-1][1].text.splitlines()[1] == "bread · × 2"
    assert [card.status for card in open_cards()] == ["replaced", "open"]


def test_another_item_said_after_a_card_joins_that_card(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    first = world.sent[0][0]
    world.claude(shop_add("eggs"))  # only what the message is about comes back
    world.say("eggs")
    assert world.deleted == [first]
    assert world.sent[-1][1].text.splitlines()[1:3] == ["milk · × 1", "eggs · × 1"], "the code keeps the milk: one card, both items"
    assert [card.status for card in open_cards()] == ["replaced", "open"]


def test_a_new_request_for_the_same_task_is_read_afresh_when_extraction_says_so(world):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    world.bot_messages.append(9999)
    world.claude(route("shopping"), ("not_this", {"reason": "a different request"}), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    assert [request.tools[-1] for request in world.requests[3:]] == ["not_this", "none"], "with the card, then without"
    assert world.sent[-1][1].text == "🛒 The shopping list is empty." and open_cards()[0].status == "open"


# ---------------------------------------------------------------------------
# A list shown on request is Live: the latest copy is kept up to date in place
# ---------------------------------------------------------------------------
def test_the_list_shown_on_request_is_rewritten_in_place_when_the_list_changes(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 3}, {"item": "eggs", "quantity": 20}]))
    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    list_message = world.sent[-1][0]
    assert world.sent[-1][1].text == "## 🛒 Shopping list\n- **milk** × 3\n- **eggs** × 20"
    assert run(livelists.message_class(list_message)) is not None, "it is a Live message"

    world.claude(tick("milk"))  # straight after the list: its task, no router
    world.say("got the milk")
    assert world.edited == [(list_message, "## 🛒 Shopping list\n- **eggs** × 20")], "edited in place, not posted again"

    world.claude(route("shopping"), shop_add("bread", 2))
    world.say("add 2 bread")
    assert len(world.edited) == 1, "a card is not a change: nothing is saved yet"
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert world.edited[-1] == (list_message, "## 🛒 Shopping list\n- **eggs** × 20\n- **bread** × 2")

    world.claude(route("shopping"), ("demo_shop_clear", {"guessed": []}))
    world.say("clear my shopping list")
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert world.edited[-1] == (list_message, "🛒 The shopping list is empty.")


def test_only_the_latest_copy_of_a_list_is_live(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 1}, {"item": "eggs", "quantity": 1}]))
    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("what do I need to buy?")
    first = world.sent[-1][0]
    world.bot_messages.append(9998)  # something else was said in between
    world.claude(route("shopping"), ("demo_shop_list", {"guessed": []}))
    world.say("show me the shopping list again")
    second = world.sent[-1][0]

    world.claude(tick("milk"))
    world.say("got the milk")
    assert [message_id for message_id, _ in world.edited] == [second], "the older copy is left as it was"
    assert run(livelists.message_class(first)) is None and run(livelists.message_class(second)) is not None


def test_a_list_that_was_never_shown_has_nothing_to_rewrite(world):
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    run(confirm.on_save(world.Press(open_cards()[0].id)))
    assert world.edited == []


def test_each_list_is_live_on_its_own(world):
    world.claude(route("packing"), ("demo_pack_list", {"guessed": []}))
    world.say("what am I packing?")
    packing_message = world.sent[-1][0]
    world.bot_messages.append(9998)  # so that what follows is not taken as being for the packing list
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk to the shopping list")
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert world.edited == [], "the shopping list changed; the packing list on screen did not"
    world.claude(route("packing"), pack("socks", "checked"))
    world.say("pack socks in the checked bag")
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert world.edited == [(packing_message, "## 🧳 Packing list\n- **socks** · checked bag")]


# ---------------------------------------------------------------------------
# Names as typed; singular and plural are the same item
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "one, other",
    [("milk", "milks"), ("Eggs", "egg"), ("loaf", "loaves"), ("tomato", "Tomatoes"), ("berry", "berries"), ("box", "boxes"), ("oat milk", "Oat Milks")],
)
def test_singular_and_plural_are_the_same_item(one, other):
    assert demo.same_item(one, other) and demo.same_item(other, one)


@pytest.mark.parametrize("one, other", [("milk", "oat milk"), ("glass", "glasses of wine"), ("bus", "bun"), ("egg", "eggplant")])
def test_different_things_are_not(one, other):
    assert not demo.same_item(one, other)


def test_adding_the_singular_of_what_is_on_the_list_adds_to_it_under_the_name_just_typed(world):
    # QA 2026-10-09: "milks" was typed once, and "milk" added later showed as "milks × 4"
    run(demo._save("shopping", 1, [{"item": "milks", "quantity": 1}]))
    world.claude(route("shopping"), shop_add("milk", 3))
    world.say("add 3 milk")
    card = world.sent[-1][1]
    assert card.text.splitlines()[:2] == ["🛒 Shopping · change", "milk · 1 → 4"], "what it is now and what it will be"
    run(confirm.on_save(press := world.Press(open_cards()[-1].id)))
    assert shopping_list() == [{"item": "milk", "quantity": 4}], "one item, named as it was typed this time"
    assert press.cards[-1].text == "✅ Saved · 🛒 **milk** × 4 is on the shopping list"


def test_a_name_is_kept_exactly_as_typed(world):
    world.claude(route("shopping"), shop_add("Oat Milks", 2))
    world.say("add 2 Oat Milks")
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert shopping_list() == [{"item": "Oat Milks", "quantity": 2}]


def test_ticking_off_finds_the_item_in_either_number_and_by_part_of_its_name_if_only_one_has_it(world):
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 6}, {"item": "oat milk", "quantity": 1}, {"item": "bread", "quantity": 1}]))
    world.claude(route("shopping"), tick("egg"))
    world.say("got an egg")
    assert world.sent[-1][1].text == "☑️ Ticked off **eggs** × 6 · still to buy: oat milk, bread"
    world.claude(route("shopping"), tick("milk"))
    world.say("got the milk")
    assert world.sent[-1][1].text == "☑️ Ticked off **oat milk** × 1 · still to buy: bread"


def test_adding_does_not_merge_into_something_that_only_shares_a_word(world):
    run(demo._save("shopping", 1, [{"item": "oat milk", "quantity": 1}]))
    world.claude(route("shopping"), shop_add("milk", 1))
    world.say("add milk")
    assert "already on the list" not in world.sent[-1][1].text
    run(confirm.on_save(world.Press(open_cards()[-1].id)))
    assert shopping_list() == [{"item": "oat milk", "quantity": 1}, {"item": "milk", "quantity": 1}]


# ---------------------------------------------------------------------------
# Several things in one request: one card, every item, nothing dropped
# ---------------------------------------------------------------------------
SEVERAL = "Add honey, jam, peanut butter, rubbish bags and 5 eggs"
FIVE = shop_add_all("honey", "jam", "peanut butter", "rubbish bags", ("eggs", 5))


def test_several_items_in_one_message_are_one_card_with_every_item_and_one_save(world):
    # QA 2026-10-09: this gave a card with only honey; four items were dropped without a word
    world.claude(route("shopping"), FIVE)
    world.say(SEVERAL)

    (message_id, card), = world.sent
    assert card.text.splitlines() == [
        "🛒 Shopping · new",
        "honey · × 1",
        "jam · × 1",
        "peanut butter · × 1",
        "rubbish bags · × 1",
        "eggs · × 5",
        "-# or tell me what to change",
    ]
    assert [button.label for button in card.rows[0]] == ["Save", "Cancel"], "one Save for all of it"
    assert "❓" not in card.text, "one of each is the default, not a guess"
    assert shopping_list() == []

    run(confirm.on_save(press := world.Press(open_cards()[0].id)))
    assert press.cards[-1].text == "✅ Saved · 🛒 5 items added to the shopping list"
    assert shopping_list() == [
        {"item": "honey", "quantity": 1}, {"item": "jam", "quantity": 1}, {"item": "peanut butter", "quantity": 1},
        {"item": "rubbish bags", "quantity": 1}, {"item": "eggs", "quantity": 5},
    ]


def test_two_items_are_one_card(world):
    world.claude(route("shopping"), shop_add_all("butter", "jam"))
    world.say("add butter and jam")
    assert world.sent[0][1].text.splitlines()[1:3] == ["butter · × 1", "jam · × 1"] and len(world.sent) == 1


def a_card_of_five(world):
    world.claude(route("shopping"), FIVE)
    world.say(SEVERAL)
    return world.sent[0][0]


def test_a_reply_changes_one_item_and_the_card_is_replaced(world):
    first = a_card_of_five(world)
    world.claude(shop_add("eggs", 6, change="set"))  # the eggs alone: the code keeps the rest
    world.say("make the eggs 6")
    assert world.deleted == [first]
    assert world.sent[-1][1].text.splitlines()[1:6] == ["honey · × 1", "jam · × 1", "peanut butter · × 1", "rubbish bags · × 1", "eggs · × 6"]
    assert [card.status for card in open_cards()] == ["replaced", "open"]
    assert "2. item: jam, quantity: 1, change: add" in world.requests[-1].user, "extraction is shown the card's lines"


def test_a_reply_removes_one_item_and_the_card_is_replaced(world):
    first = a_card_of_five(world)
    world.claude(shop_add("jam", change="remove"))
    world.say("remove the jam")
    assert world.deleted == [first]
    assert world.sent[-1][1].text.splitlines()[1:5] == ["honey · × 1", "peanut butter · × 1", "rubbish bags · × 1", "eggs · × 5"]
    assert "jam" not in world.sent[-1][1].text, "it was only on the card, so it simply goes"


def test_a_reply_adds_an_item_to_the_same_card(world):
    first = a_card_of_five(world)
    world.claude(shop_add("milk"))
    world.say("add milk too")
    assert world.deleted == [first], "one card, replaced: not a second one beside it"
    assert world.sent[-1][1].text.splitlines()[1:7] == [
        "honey · × 1", "jam · × 1", "peanut butter · × 1", "rubbish bags · × 1", "eggs · × 5", "milk · × 1",
    ]
    assert [card.status for card in open_cards()] == ["replaced", "open"]


def test_a_card_sent_back_whole_is_not_taken_as_one_more_of_everything(world):
    # Seen in the live eval on 2026-10-09: for "add milk too" Claude returned all five items and milk
    first = a_card_of_five(world)
    world.claude(shop_add_all(("honey", 1, "add"), ("jam", 1, "add"), ("peanut butter", 1, "add"), ("rubbish bags", 1, "add"), ("eggs", 5, "add"), ("milk", 1, "add")))
    world.say("add milk too")
    assert world.sent[-1][1].text.splitlines()[1:7] == [
        "honey · × 1", "jam · × 1", "peanut butter · × 1", "rubbish bags · × 1", "eggs · × 5", "milk · × 1",
    ], "nothing is doubled"


def test_no_packing_moves_every_item_to_a_packing_card(world):
    first = a_card_of_five(world)
    world.claude(shop_add("eggs", 6, change="set"))
    world.say("make the eggs 6")
    world.claude()  # the move itself needs no request
    world.say("no, packing")
    assert world.requests[3:] == [], "carried over in code, as the card stood after its corrections"
    assert world.sent[-1][1].text.splitlines() == [
        "🧳 Packing · new",
        "honey · checked bag", "jam · checked bag", "peanut butter · checked bag", "rubbish bags · checked bag", "eggs · checked bag",
        "-# or tell me what to change",
    ]
    assert first in world.deleted and [card.status for card in open_cards()] == ["replaced", "replaced", "open"]
    run(confirm.on_save(press := world.Press(open_cards()[-1].id)))
    assert press.cards[-1].text == "✅ Saved · 🧳 5 items added to the packing list" and shopping_list() == []


def test_an_item_lost_in_the_move_is_said_on_the_card_whatever_extraction_returned(world, monkeypatch):
    # When a card can't be carried over in code, extraction reads it over. Seen in the live
    # eval on 2026-10-09: moved to packing, the eggs (the one item with an amount) were left out
    monkeypatch.setattr(conversation, "_carried_over", lambda card, target: None)
    a_card_of_five(world)
    world.claude(("demo_pack_change", {"items": [{"item": name} for name in ("honey", "jam", "peanut butter", "rubbish bags")], "guessed": [], "not_included": []}))
    world.say("no, packing")
    assert "no, packing" not in world.requests[-1].user and '"item": "rubbish bags"' in world.requests[-1].user
    assert world.sent[-1][1].text.splitlines()[-2] == "⚠️ Not included: eggs"


def test_items_for_two_tasks_in_one_message_are_one_card_per_task(world):
    world.claude(
        route("shopping", "packing"),
        shop_add_all("jam"),
        ("demo_pack_change", {"items": [{"item": "sunscreen"}, {"item": "hat"}], "guessed": [], "not_included": []}),
    )
    world.say("add jam to the shopping list and pack sunscreen and a hat")
    assert [card.text.splitlines()[:-1] for _, card in world.sent] == [
        ["🛒 Shopping · new", "jam · × 1"],
        ["🧳 Packing · new", "sunscreen · checked bag", "hat · checked bag"],
    ]


def test_what_cannot_go_on_the_card_is_said_on_the_card(world):
    world.claude(route("shopping"), shop_add("milk", not_included=["remind me to call mum at 5"]))
    world.say("add milk, and remind me to call mum at 5")
    assert world.sent[0][1].text.splitlines() == [
        "🛒 Shopping · new", "milk · × 1", "⚠️ Not included: remind me to call mum at 5", "-# or tell me what to change",
    ]
    assert "Not included: remind me to call mum at 5" in rows()[0][4], "and in the log"


def test_an_item_that_does_not_fit_the_schema_is_said_on_the_card_and_the_rest_are_kept(world):
    world.claude(route("shopping"), ("demo_shop_change", {"items": [{"item": "honey"}, {"item": "jam", "quantity": "lots"}], "guessed": []}))
    world.say("add honey and lots of jam")
    assert world.sent[0][1].text.splitlines()[1:3] == ["honey · × 1", "⚠️ Not included: jam, lots"]


def test_what_was_left_out_of_a_reply_is_said_after_it(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 1}, {"item": "eggs", "quantity": 6}]))
    world.claude(route("shopping"), ("demo_shop_tick", {"items": [{"item": "milk"}], "guessed": [], "not_included": ["and book the dentist"]}))
    world.say("got the milk and book the dentist")
    assert world.sent[-1][1].text == "☑️ Ticked off **milk** × 1 · still to buy: eggs\n⚠️ Not included: and book the dentist"


def test_ticking_off_several_names_the_ones_that_were_not_on_the_list(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 1}, {"item": "eggs", "quantity": 6}, {"item": "bread", "quantity": 1}]))
    world.claude(route("shopping"), tick("milk", "eggs", "caviar"))
    world.say("got the milk, the eggs and the caviar")
    assert world.sent[-1][1].text == "☑️ Ticked off **milk** × 1, **eggs** × 6 · still to buy: bread\n⚠️ Not on the list: caviar"


# ---------------------------------------------------------------------------
# ❓ is for genuine guesses only
# ---------------------------------------------------------------------------
def test_a_default_amount_is_not_flagged(world):
    world.claude(route("shopping"), shop_add("milk"))  # no quantity given: one is assumed
    world.say("add milk")
    assert world.sent[0][1].text.splitlines()[1] == "milk · × 1"
    assert open_cards()[0].guessed == ()


def test_a_genuine_guess_is_flagged_on_its_own_line_only(world):
    world.claude(route("shopping"), shop_add_all("honey", ("eggs", 3), "jam", guessed=["items[1].quantity"]))
    world.say("add honey, a few eggs and jam")
    assert world.sent[0][1].text.splitlines()[1:4] == ["honey · × 1", "eggs · × 3 ❓", "jam · × 1"]
    assert open_cards()[0].guessed == ("items[1].quantity",)


def test_a_default_bag_is_not_flagged_either(world):
    world.claude(route("packing"), pack("socks"))
    world.say("pack socks")
    assert world.sent[0][1].text.splitlines()[1] == "socks · checked bag"


# ---------------------------------------------------------------------------
# A list shown on request is context, as an open card is
# ---------------------------------------------------------------------------
def show_packing_list(world):
    world.claude(route("packing"), ("demo_pack_list", {"guessed": []}))
    world.say("what am I packing?")
    return world.sent[-1][0]


def test_a_short_message_straight_after_a_list_goes_to_that_lists_task(world):
    # QA 2026-10-09: after "what am I packing?", "add milk" went to shopping
    show_packing_list(world)
    world.claude(pack("milk"))
    world.say("add milk")

    (request,) = world.requests[2:]
    assert (request.purpose, request.task) == ("extraction", "packing"), "no router: the list on screen says which task"
    assert request.tools[-1] == "not_this", "extraction can still say it is for something else"
    assert world.sent[-1][1].text.splitlines()[:2] == ["🧳 Packing · new", "milk · checked bag"], "the card shows the task"
    assert rows()[-1][1] == "follow-up"


def test_no_shopping_still_corrects_a_card_that_came_from_the_list_on_screen(world):
    show_packing_list(world)
    world.claude(pack("milk"))
    world.say("add milk")
    packing_card = world.sent[-1][0]
    world.claude(shop_add("milk"))
    world.say("no, shopping")
    assert world.deleted == [packing_card] and world.sent[-1][1].text.splitlines()[:2] == ["🛒 Shopping · new", "milk · × 1"]


def test_a_message_plainly_for_something_else_is_read_afresh(world):
    show_packing_list(world)
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 1}]))
    world.claude(("not_this", {"reason": "about shopping"}), route("shopping"), tick("milk"))
    world.say("got the milk")  # short enough to be tried against the list first
    assert [(request.purpose, request.task) for request in world.requests[2:]] == [
        ("extraction", "packing"), ("router", ""), ("extraction", "shopping"),
    ]
    assert "On screen, waiting for the user: the packing list, just shown" in world.requests[3].user
    assert world.sent[-1][1].text.startswith("☑️ Ticked off **milk**")


def test_a_named_destination_is_never_tried_against_the_list_on_screen(world):
    show_packing_list(world)
    world.claude(route("shopping"), shop_add("milk"))
    world.say("put milk on my shopping list")
    assert [(request.purpose, request.task) for request in world.requests[2:]] == [("router", ""), ("extraction", "shopping")]
    assert world.sent[-1][1].text.splitlines()[0] == "🛒 Shopping · new"


def test_a_long_message_after_a_list_goes_to_the_router(world):
    show_packing_list(world)
    world.claude(route("shopping"), shop_add_all("honey", "jam"))
    world.say("could you please put honey and also some jam on the shopping list for me")
    assert world.requests[2].purpose == "router"


def test_a_list_stops_being_context_once_the_bot_says_something_else_or_five_minutes_pass(world, dev_clock):
    show_packing_list(world)
    world.bot_messages.append(9998)
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    assert world.requests[2].purpose == "router"

    run(confirm.on_cancel(world.Press(open_cards()[-1].id)))
    show_packing_list(world)
    dev_clock.advance(timedelta(minutes=livelists.STICKY_MINUTES, seconds=1))
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    assert world.requests[-2].purpose == "router"


def test_an_open_card_comes_before_a_list(world):
    show_packing_list(world)
    world.claude(pack("socks"))
    world.say("add socks")  # a packing card, now the last thing on screen
    world.claude(pack("socks", "carry-on"))
    world.say("carry-on")
    assert "The open card:" in world.requests[-1].user, "the card is what the message is about"
    assert world.sent[-1][1].text.splitlines()[1] == "socks · carry-on bag"


# ---------------------------------------------------------------------------
# Set, add and remove: Claude says which, Python does the sum (QA 2026-10-09)
# ---------------------------------------------------------------------------
def card_lines(world):
    """The latest card, without its footer."""
    return world.sent[-1][1].text.splitlines()[:-1]


def save(world):
    run(confirm.on_save(press := world.Press(open_cards()[-1].id)))
    return press.cards[-1].text


def test_make_the_eggs_7_sets_the_amount_and_the_card_shows_before_and_after(world):
    # Seen: with no card open, "make the eggs 7" added 7 to 5 and saved 12
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 5}]))
    world.claude(route("shopping"), shop_add("eggs", 7, change="set"))
    world.say("make the eggs 7")
    assert card_lines(world) == ["🛒 Shopping · change", "eggs · 5 → 7"]
    assert "On the shopping list now:\n- eggs × 5" in world.requests[-1].user, "extraction is shown the list"
    assert save(world) == "✅ Saved · 🛒 **eggs** × 7 is on the shopping list"
    assert shopping_list() == [{"item": "eggs", "quantity": 7}]


def test_add_3_milk_to_2_is_5_and_python_does_the_sum(world):
    # Seen: milk × 2 on the list, "add 3 milk", Save -> milk × 3
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("milk", 3))  # the 3 as said: no total from Claude
    world.say("add 3 milk")
    assert card_lines(world) == ["🛒 Shopping · change", "milk · 2 → 5"]
    assert open_cards()[-1].data == SAVED(("milk", 3, "add")), "the card keeps the change, not a total"
    assert save(world) == "✅ Saved · 🛒 **milk** × 5 is on the shopping list"
    assert shopping_list() == [{"item": "milk", "quantity": 5}]


def test_adding_more_on_an_open_card_adds_up_on_the_card(world):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    world.claude(shop_add("milk", 3))
    world.say("add 3 milk")
    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 5"]
    assert open_cards()[-1].data == SAVED(("milk", 5, "add"))
    assert save(world) == "✅ Saved · 🛒 **milk** × 5 is on the shopping list"


def test_setting_after_adding_on_a_card_replaces_what_was_pending(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("milk", 3))
    world.say("add 3 milk")
    world.claude(shop_add("milk", 4, change="set"))
    world.say("make it 4")
    assert card_lines(world) == ["🛒 Shopping · change", "milk · 2 → 4"]
    save(world)
    assert shopping_list() == [{"item": "milk", "quantity": 4}]


def test_setting_what_it_already_is_says_nothing_changes(world):
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 5}]))
    world.claude(route("shopping"), shop_add("eggs", 5, change="set"))
    world.say("make the eggs 5")
    assert card_lines(world) == ["🛒 Shopping · change", "eggs · × 5", "⚠️ eggs is already × 5: nothing changes"]


def test_one_message_can_add_set_and_remove_and_save_says_how_many_of_each(world):
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 5}, {"item": "jam", "quantity": 1}, {"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), shop_add_all("honey", ("eggs", 7, "set"), ("milk", 3, "add"), ("jam", None, "remove")))
    world.say("add honey and 3 milk, make the eggs 7 and remove the jam")
    assert card_lines(world) == ["🛒 Shopping · change", "honey · × 1", "eggs · 5 → 7", "milk · 2 → 5", "jam · × 1 → removed"]
    assert save(world) == "✅ Saved · 🛒 shopping list updated: 1 added, 2 changed, 1 removed"
    assert shopping_list() == [{"item": "eggs", "quantity": 7}, {"item": "milk", "quantity": 5}, {"item": "honey", "quantity": 1}]


def test_remove_the_jam_from_the_saved_list_is_a_card_and_save_removes_it(world):
    run(demo._save("shopping", 1, [{"item": "jam", "quantity": 1}, {"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("jam", change="remove"))
    world.say("remove the jam")
    assert card_lines(world) == ["🛒 Shopping · change", "jam · × 1 → removed"]
    assert shopping_list() == [{"item": "jam", "quantity": 1}, {"item": "milk", "quantity": 2}], "nothing until Save"
    assert save(world) == "✅ Saved · 🛒 **jam** removed from the shopping list"
    assert shopping_list() == [{"item": "milk", "quantity": 2}]


def test_removing_what_a_card_was_adding_to_a_saved_item_becomes_its_removal(world):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 2}]))
    world.claude(route("shopping"), shop_add_all("honey", ("milk", 3)))
    world.say("add honey and 3 milk")
    world.claude(shop_add("milk", change="remove"))
    world.say("remove the milk")
    assert card_lines(world) == ["🛒 Shopping · change", "honey · × 1", "milk · × 2 → removed"]


def test_removing_what_is_nowhere_is_said_and_no_card_is_made(world):
    world.claude(route("shopping"), shop_add("tea", change="remove"))
    world.say("remove the tea")
    assert world.sent[-1][1].text == "⚠️ tea isn't on the shopping list."
    assert open_cards() == []


def test_removing_what_is_nowhere_from_an_open_card_is_a_warning_on_it(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    world.claude(shop_add("tea", change="remove"))
    world.say("remove the tea")
    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 1", "⚠️ tea isn't on the list: nothing to remove"]


def test_the_packing_list_removes_and_moves_the_same_way(world):
    run(demo._save("packing", 1, [{"item": "socks", "bag": "checked"}, {"item": "passport", "bag": "checked"}]))
    world.claude(route("packing"), ("demo_pack_change", {"items": [{"item": "socks", "change": "remove"}, {"item": "passport", "bag": "carry-on", "change": "set"}], "guessed": [], "not_included": []}))
    world.say("remove the socks and put my passport in the carry-on")
    assert card_lines(world) == ["🧳 Packing · change", "socks · checked bag → removed", "passport · checked bag → carry-on bag"]
    assert save(world) == "✅ Saved · 🧳 packing list updated: 1 changed, 1 removed"
    assert run(demo._items("packing", 1)) == [{"item": "passport", "bag": "carry-on"}]


# ---------------------------------------------------------------------------
# "Not included" is only for what no card covers
# ---------------------------------------------------------------------------
def test_each_cards_part_of_a_mixed_message_is_not_reported_by_the_other(world):
    # Seen: two cards, each listing the other's part as not included
    world.claude(
        route("shopping", "packing"),
        shop_add("jam", not_included=["pack sunscreen and a hat"]),
        ("demo_pack_change", {"items": [{"item": "sunscreen"}, {"item": "hat"}], "guessed": [], "not_included": ["add jam to the shopping list"]}),
    )
    world.say("add jam to the shopping list and pack sunscreen and a hat")
    assert [card.text.splitlines()[:-1] for _, card in world.sent] == [
        ["🛒 Shopping · new", "jam · × 1"],
        ["🧳 Packing · new", "sunscreen · checked bag", "hat · checked bag"],
    ]
    shopping_request, packing_request = world.requests[1:]
    assert "handled elsewhere (the packing task)" in shopping_request.user
    assert "handled elsewhere (the shopping task)" in packing_request.user


def test_a_part_that_no_card_covers_is_still_said(world):
    world.claude(
        route("shopping", "packing"),
        shop_add("jam", not_included=["pack a hat", "book the dentist"]),
        pack("hat"),
    )
    world.say("add jam, pack a hat and book the dentist")
    assert world.sent[0][1].text.splitlines()[1:3] == ["jam · × 1", "⚠️ Not included: book the dentist"]


def test_the_part_that_was_answered_in_plain_words_is_not_reported_either(world):
    world.claude(
        route("shopping", chat_part="what is the capital of France?"),
        ("chat", "Paris."),
        shop_add("jam", not_included=["what's the capital of France"]),
    )
    world.say("add jam, and what's the capital of France?")
    assert "Not included" not in world.sent[-1][1].text


def test_uncovered_goes_by_what_the_other_task_actually_took():
    shopping, packing = actions.entry("shopping") or demo.SHOPPING, demo.PACKING
    took = conversation.Extracted(packing, packing.action("demo_pack_change"), {"items": [{"item": "sunscreen"}]}, frozenset())
    found = conversation.Extracted(
        shopping, shopping.action("demo_shop_change"), {"items": [{"item": "jam"}]}, frozenset(),
        not_included=("pack sunscreen", "pack a hat"),
    )
    assert conversation.uncovered(found, [found, took]).not_included == ("pack a hat",), "the hat was taken by nothing"
    assert conversation.uncovered(found, [found]).not_included == ("pack sunscreen", "pack a hat")


# ---------------------------------------------------------------------------
# "It" is the last thing mentioned; a correction undoes the mistake
# ---------------------------------------------------------------------------
def milk_and_bread_rolls(world):
    world.claude(route("shopping"), shop_add_all("milk", "bread rolls"))
    world.say("add milk and bread rolls")


def test_a_name_claude_works_out_for_a_pronoun_is_put_back_for_the_code_to_resolve(world):
    # Seen: a card with milk and bread rolls; "make it 2" changed the milk, because Claude chose
    milk_and_bread_rolls(world)
    world.claude(shop_add("milk", 2, change="set"))  # Claude names the wrong one
    world.say("make it 2")
    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 1", "bread rolls · × 2"], "the code's rule, not Claude's pick"
    assert "reference check: Claude named milk for a pronoun; put back for the code to resolve" in traces()[-1]["checks"]


def test_no_2_bread_rolls_undoes_the_wrong_change_and_applies_the_right_one(world):
    # Seen: after "make it 2" wrongly changed the milk, "No, 2 bread rolls" set the bread rolls and left milk at 2
    milk_and_bread_rolls(world)
    world.claude(shop_add("milk", 2, change="set"))
    world.say("make the milk 2")
    assert card_lines(world)[1:] == ["milk · × 2", "bread rolls · × 1"]

    world.claude(shop_add("bread rolls", 2, change="set"))
    world.say("No, 2 bread rolls")

    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 1", "bread rolls · × 2"], "milk is back to 1"
    asked = world.requests[-1].user
    assert 'the user\'s last change ("make the milk 2") was a mistake and has been UNDONE' in asked
    assert "1. item: milk, quantity: 1, change: add" in asked, "extraction is shown the card as it was before the mistake"
    card = open_cards()[-1]
    assert card.said == "add milk and bread rolls\nNo, 2 bread rolls", "the mistake is no longer part of what was said"
    assert card.previous == SAVED(("milk", 1, "add"), ("bread rolls", 1, "add")), "still the card before the mistake"
    assert save(world) == "✅ Saved · 🛒 2 items added to the shopping list"
    assert shopping_list() == [{"item": "milk", "quantity": 1}, {"item": "bread rolls", "quantity": 2}]


def test_no_on_a_card_that_has_not_been_changed_has_nothing_to_undo(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    world.claude(shop_add("milk", 3, change="set"))
    world.say("no, 3")
    assert card_lines(world)[1] == "milk · × 3"
    assert "UNDONE" not in world.requests[-1].user


def test_a_change_that_is_not_a_correction_keeps_the_one_before_it(world):
    milk_and_bread_rolls(world)
    world.claude(shop_add("milk", 2, change="set"))
    world.say("make the milk 2")
    world.claude(shop_add("bread rolls", 3, change="set"))
    world.say("and 3 bread rolls")
    assert card_lines(world)[1:] == ["milk · × 2", "bread rolls · × 3"]


@pytest.mark.parametrize(
    "said, expected",
    [
        ("No, 2 bread rolls", True),
        ("no 2 bread rolls", True),
        ("Nope, the eggs", True),
        ("sorry, I meant jam", True),
        ("wrong one - the bread rolls", True),
        ("no", False),
        ("No.", False),
        ("make it 2", False),
        ("november is fine", False),
        ("not bad, add 2 more", False),
    ],
)
def test_what_counts_as_a_correction(said, expected):
    assert confirm.is_correction(said) is expected


# ---------------------------------------------------------------------------
# A follow-up returns only its changes; a card sent back with them is not added again
# ---------------------------------------------------------------------------
def test_and_jam_then_and_honey_leave_the_butter_as_it_was(world):
    # QA 2026-10-10: butter × 2 on the list. "Add butter" 2 → 3; "and jam" came back as
    # butter and jam and made it 2 → 4; "and honey" left it at 4
    run(demo._save("shopping", 1, [{"item": "butter", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("butter"))
    world.say("Add butter")
    assert card_lines(world) == ["🛒 Shopping · change", "butter · 2 → 3"]

    world.claude(shop_add("jam"))  # what is asked for: jam alone
    world.say("and jam")
    assert card_lines(world) == ["🛒 Shopping · change", "butter · 2 → 3", "jam · × 1"]
    asked = world.requests[-1].user
    assert "the lines already on the card (kept by the bot's code: do NOT send them back):\n  1. item: butter, quantity: 1, change: add" in asked
    assert asked.endswith("A line of the card that the message does not name or point at stays out of your answer.")

    world.claude(shop_add("honey"))
    world.say("and honey")
    assert card_lines(world) == ["🛒 Shopping · change", "butter · 2 → 3", "jam · × 1", "honey · × 1"]
    assert save(world) == "✅ Saved · 🛒 shopping list updated: 2 added, 1 changed"
    assert shopping_list() == [{"item": "butter", "quantity": 3}, {"item": "jam", "quantity": 1}, {"item": "honey", "quantity": 1}]


@pytest.mark.parametrize("said", ["and jam", "also jam", "plus jam", "jam too"])
def test_a_one_line_card_sent_back_with_the_new_item_is_not_added_again(world, said):
    # The safety net: what was seen on 2026-10-10, whatever the wording
    run(demo._save("shopping", 1, [{"item": "butter", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("butter"))
    world.say("Add butter")
    world.claude(shop_add_all(("butter", 1, "add"), "jam"))
    world.say(said)
    assert card_lines(world) == ["🛒 Shopping · change", "butter · 2 → 3", "jam · × 1"], "butter stays 2 → 3"
    world.claude(shop_add_all("butter", "jam", "honey"))
    world.say("and honey")
    assert card_lines(world) == ["🛒 Shopping · change", "butter · 2 → 3", "jam · × 1", "honey · × 1"]


def test_an_item_on_the_card_that_the_message_names_again_is_a_real_change(world):
    world.claude(route("shopping"), shop_add("butter"))
    world.say("Add butter")
    world.claude(shop_add_all("butter", "jam"))
    world.say("and another butter and jam")
    assert card_lines(world) == ["🛒 Shopping · new", "butter · × 2", "jam · × 1"]


# ---------------------------------------------------------------------------
# The trace of a message, and the cap on the state sent to extraction
# ---------------------------------------------------------------------------
def traces():
    def read(conn):
        return [json.loads(kept) if kept else {} for (kept,) in conn.execute("SELECT trace FROM message_log ORDER BY id")]

    return run(database.run(read))


def test_every_message_keeps_why_it_went_the_way_it_did_and_what_the_code_did(world):
    run(demo._save("shopping", 1, [{"item": "butter", "quantity": 2}]))
    world.claude(route("shopping"), shop_add("butter"))
    world.say("Add butter")
    world.claude(shop_add_all(("butter", 1, "add"), "jam"))
    world.say("and jam")
    first, second = traces()

    assert first["router"] == {"tasks": ["shopping"], "tie": False, "chat": False, "chat_part": "", "problem": ""}
    assert first["why"] == ["nothing on screen claimed it"]
    assert "open card: none, so the sticky and correction checks were skipped" in first["checks"]
    assert first["card"] == {"before": [], "after": ["butter · 2 → 3"]}
    assert first["state"] == {"shopping": {"sent": 1, "total": 1}}

    assert "router" not in second, "a follow-up never asks the router"
    assert second["why"][0].startswith("card 1 (shopping) is open and the message sticks to it: it is the bot's latest message")
    assert any(check.startswith("sticky check: card 1 sticks") for check in second["checks"])
    assert "correction check: not a correction of the last change" in second["checks"]
    assert "restatement check: butter came back with the card and the message doesn't name it: not added again" in second["checks"]
    assert "merge: jam add (new to the card)" in second["checks"] and "card 1 replaced" in second["checks"]
    assert second["card"] == {"before": ["butter 1 add"], "after": ["butter · 2 → 3", "jam · × 1"]}


def test_the_trace_says_when_a_change_was_undone(world):
    milk_and_bread_rolls(world)
    world.claude(shop_add("milk", 2, change="set"))
    world.say("make it 2")
    world.claude(shop_add("bread rolls", 2, change="set"))
    world.say("No, 2 bread rolls")
    last = traces()[-1]
    assert "correction check: the last change is undone first" in last["checks"]
    assert "card 2 replaced (last change undone first)" in last["checks"]


def test_the_trace_says_what_the_not_included_check_dropped_and_kept(world):
    world.claude(
        route("shopping", "packing"),
        shop_add("jam", not_included=["pack a hat", "book the dentist"]),
        pack("hat"),
    )
    world.say("add jam, pack a hat and book the dentist")
    checks = traces()[-1]["checks"]
    assert 'not-included check: "pack a hat" dropped, covered by another task' in checks
    assert 'not-included check: "book the dentist" is covered by nothing: said to the user' in checks


def test_a_long_list_is_capped_before_it_goes_to_extraction_and_the_count_is_kept(world):
    many = [{"item": f"thing {number}", "quantity": 1} for number in range(60)] + [{"item": "eggs", "quantity": 5}]
    run(demo._save("shopping", 1, many))
    world.claude(route("shopping"), shop_add("eggs", 7, change="set"))
    world.say("make the eggs 7")
    asked = world.requests[-1].user
    assert asked.count("\n- ") == actions.STATE_LINES and "- eggs × 5" in asked, "what the message names is among them"
    assert "(and 41 more not shown" in asked
    assert traces()[-1]["state"] == {"shopping": {"sent": 20, "total": 61}}
    assert card_lines(world) == ["🛒 Shopping · change", "eggs · 5 → 7"], "the code still has the whole list"
    assert run(database.run(costs.db_state_sent, "2000-01-01")) == (1, 20, 61)


# ---------------------------------------------------------------------------
# QA 2026-10-10: read back before confirming; "it" is the code's; nothing to do; what is stated wins
# ---------------------------------------------------------------------------
def test_saved_is_only_said_once_the_change_has_been_read_back(world, monkeypatch):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    card = open_cards()[-1]

    async def lost(kind, user_id, items):
        return None  # the write goes nowhere

    logged = []

    async def log_error(title, detail, said=""):
        logged.append((title, detail))

    monkeypatch.setattr(demo, "_save", lost)
    monkeypatch.setattr(confirm, "log_error", log_error)
    outcome = run(confirm.on_save(press := world.Press(card.id)))
    assert press.cards[-1].text == "⚠️ That didn't save: milk is not on the list. Nothing is confirmed; please check and ask again."
    assert "Saved" not in press.cards[-1].text and outcome.startswith("NOT saved shopping/demo_shop_change")
    assert logged == [("Save did not take: demo_shop_change", "milk is not on the list")]
    assert open_cards()[-1].status == "failed" and shopping_list() == []


def test_what_a_press_did_is_remembered_so_the_next_message_is_not_answered_as_if_it_were_waiting(world):
    # QA 2026-10-10: after Delete for good was pressed, the next message was told "I'm waiting for you to confirm"
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    saved = save(world)
    history = llm.history_for(world.channel_id) if hasattr(world, "channel_id") else llm.history_for(open_cards()[-1].channel_id)
    assert history[-2:] == [{"role": "user", "content": "(pressed the card's button)"}, {"role": "assistant", "content": saved}]

    world.claude(route("shopping"), shop_add("jam"))
    world.say("add jam")
    run(confirm.on_cancel(world.Press(open_cards()[-1].id)))
    assert llm.history_for(open_cards()[-1].channel_id)[-1]["content"] == "Cancelled: nothing was changed."


def test_each_demo_change_is_read_back_item_by_item(world):
    request = SimpleNamespace(user=SimpleNamespace(id=1), text="", previous=None)
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 5}, {"item": "jam", "quantity": 1}]))
    wanted = {"items": [
        {"item": "eggs", "quantity": 7, "change": "set"}, {"item": "jam", "change": "remove"}, {"item": "milk", "quantity": 2, "change": "add"},
    ]}
    assert run(demo.shop_change_check(request, wanted)) == "eggs is × 5, not × 7; jam is still on the list; milk is not on the list"
    run(demo.shop_change_save(request, wanted))
    assert run(demo.shop_change_check(request, wanted)) == ""
    assert run(demo.shop_clear_check(request, {})) == "2 items still on the shopping list"


def test_it_is_resolved_by_the_code_to_the_item_mentioned_last_and_is_not_a_guess(world):
    # QA 2026-10-09 and 10: "make it 2" changed the first item. Claude now only says "it" was used
    milk_and_bread_rolls(world)
    world.claude(shop_add("@that", 2, change="set"))
    world.say("make it 2")
    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 1", "bread rolls · × 2"], "no ❓: it is a rule, not a guess"
    assert open_cards()[-1].data["_last"] == "bread rolls"


def test_it_follows_whatever_was_mentioned_last_not_the_last_line_of_the_card(world):
    milk_and_bread_rolls(world)
    world.claude(shop_add("milk", 3, change="set"))
    world.say("make the milk 3")
    world.claude(shop_add("@that", 4, change="set"))
    world.say("actually make it 4")
    assert card_lines(world)[1:] == ["milk · × 4", "bread rolls · × 1"]


def test_with_no_card_it_is_the_newest_thing_on_the_list_and_that_is_flagged(world):
    run(demo._save("shopping", 1, [{"item": "eggs", "quantity": 5}, {"item": "jam", "quantity": 1}]))
    world.claude(route("shopping"), shop_add("@that", 3, change="set"))
    world.say("make it 3")
    assert card_lines(world) == ["🛒 Shopping · change", "jam · 1 → 3 ❓"]


def test_with_nothing_it_could_mean_the_bot_says_so(world):
    world.claude(route("shopping"), shop_add("@that", 3, change="set"))
    world.say("make it 3")
    assert world.sent[-1][1].text == "⚠️ I can't tell what “it” is. Say its name."
    assert open_cards() == []


def test_a_message_that_needs_nothing_done_gets_no_reply_at_all(world):
    # QA 2026-10-10: "Note one" was answered "Just another note from you. No action needed."
    world.claude(("route", {"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}))
    world.say("note one")
    assert world.sent == [] and len(world.requests) == 1, "one request to the router, and silence"
    row = rows()[-1]
    assert (row[1], row[5]) == ("router", "ok") and not row[4], "logged, with nothing shown"
    assert traces()[-1]["router"]["nothing"] is True
    assert "the message asks nothing and needs nothing done: no reply" in traces()[-1]["why"]


def test_a_named_destination_wins_over_an_open_card_and_over_the_router(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    shopping_card = world.sent[-1][0]
    # The card is fresh and would claim "add socks"; the router gets it wrong as well
    world.claude(route("shopping"), pack("socks"))
    world.say("add socks to the packing list")
    assert [(request.purpose, request.task) for request in world.requests[2:]] == [("router", ""), ("extraction", "packing")]
    assert world.sent[-1][1].text.splitlines()[:2] == ["🧳 Packing · new", "socks · checked bag"]
    assert shopping_card not in world.deleted, "the shopping card is left open"
    checks = traces()[-1]["checks"]
    assert "named destination: packing (stated, so it decides the task)" in checks
    assert "named destination: the router said ['shopping'], overruled by what was stated" in checks


def test_a_named_destination_that_is_the_open_cards_own_task_still_sticks(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    world.claude(shop_add("jam"))
    world.say("and jam on the shopping list")
    assert world.requests[-1].purpose == "extraction" and len(world.requests) == 3, "no router: it is that card's task"
    assert card_lines(world)[1:] == ["milk · × 1", "jam · × 1"]


def test_an_amount_i_stated_is_never_flagged_whatever_claude_listed(world):
    world.claude(route("shopping"), shop_add("eggs", 3, guessed=["quantity"]))
    world.say("add 3 eggs")
    assert card_lines(world) == ["🛒 Shopping · new", "eggs · × 3"] and open_cards()[-1].guessed == ()
    assert any(check.startswith("stated check: no longer a guess") for check in traces()[-1]["checks"])
    run(confirm.on_cancel(world.Press(open_cards()[-1].id)))
    world.claude(route("shopping"), shop_add("eggs", 3, guessed=["quantity"]))
    world.say("add a few eggs")
    assert card_lines(world) == ["🛒 Shopping · new", "eggs · × 3 ❓"], "a real guess is still flagged"


# ---------------------------------------------------------------------------
# Batch 1 of the conversation gaps (2026-10-10): G2, G5, G6, G10, G12
# ---------------------------------------------------------------------------
def test_a_reply_to_an_older_card_is_about_that_card_and_the_trace_says_so(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk to the shopping list")
    older = world.sent[-1][0]
    world.claude(route("packing"), pack("socks"))
    world.say("add socks to the packing list")
    newest = world.sent[-1][0]
    world.claude(shop_add("@that", 2, change="set"))
    world.say("make it 2", reply_to=older)
    assert world.requests[-1].purpose == "extraction" and world.requests[-1].task == "shopping", "no router: the reply says which"
    assert older in world.deleted and newest not in world.deleted
    assert card_lines(world) == ["🛒 Shopping · new", "milk · × 2"]
    assert any(check.startswith("reply check: card 1 was replied to") for check in traces()[-1]["checks"])
    assert [(card.task, card.status) for card in open_cards()] == [("shopping", "replaced"), ("packing", "open"), ("shopping", "open")]


def test_a_reply_to_something_that_is_not_an_open_card_changes_nothing_about_which_card_is_meant(world):
    world.claude(route("shopping"), shop_add("milk"))
    world.say("add milk")
    world.claude(route("shopping"), shop_add("jam"))
    world.say("and jam", reply_to=4242)  # a message that is no card: the newest open card is still the conversation
    assert world.requests[-1].purpose == "extraction"


def test_a_message_that_needs_nothing_gets_no_words_and_no_reaction_is_left(world):
    world.claude(("route", {"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}))
    _, handled = world.say("shopping is boring")
    assert world.reactions == [] and world.sent == [], "✅ is not used to acknowledge: the 👀 coming off is the sign"
    assert handled.done and not handled.failed


def test_a_card_of_an_unknown_kind_is_shown_as_a_change_and_logged(monkeypatch):
    logged = []
    monkeypatch.setattr(confirm.log, "error", lambda text, *args: logged.append(text % args))
    shown = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, kind="tweak"), 1)
    assert shown.text.splitlines()[0] == "🛒 Shopping · change"
    assert logged == ["A card was given the kind 'tweak'; the kinds are new, change, remove"]
    for kind in ("new", "change", "remove"):
        assert confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, kind=kind), 1).text.splitlines()[0].endswith(kind)


def test_a_looser_redirect_about_something_else_leaves_the_first_card_open(world):
    world.claude(route("packing"), pack("socks"))
    world.say("add socks")
    world.claude(("not_this", {"reason": "a shopping request"}), route("shopping"), shop_add("milk"))
    world.say("oh and I need milk from the shop")
    assert [(card.task, card.status) for card in open_cards()] == [("packing", "open"), ("shopping", "open")], (
        "other items: a request of its own, so both cards stay"
    )
