"""Live lists (core/livelists.py): a list shown on request is kept up to date in place; only the latest copy is."""
import asyncio
from datetime import timedelta

import pytest

from core import cards, database, live, livelists
from core.cards import Button, Card
from core.lifecycle import MessageClass
from core.scheduler import utc_now

HUB = 400


@pytest.fixture
def channel(db, monkeypatch):
    seen = {"sent": [], "edited": [], "next": 900, "gone": set()}

    async def send(channel_id, card, silent=False):
        seen["next"] += 1
        seen["sent"].append((channel_id, seen["next"], card.text, silent))
        return seen["next"]

    async def edit(channel_id, message_id, card):
        if message_id in seen["gone"]:
            return False
        seen["edited"].append((channel_id, message_id, card.text, len(card.rows)))
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    live.reset()
    return seen


def run(coroutine):
    async def to_the_end():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(to_the_end())


def test_showing_a_list_posts_it_and_makes_it_the_live_copy(channel):
    message_id = run(livelists.show(1, "pills:today", HUB, "## 💊 Pills", silent=True))
    assert channel["sent"] == [(HUB, message_id, "## 💊 Pills", True)]
    assert run(livelists.message_class(message_id)) is MessageClass.LIVE
    assert run(livelists.message_class(12345)) is None


def test_a_change_rewrites_the_live_copy_in_place_with_the_list_as_it_now_is(channel):
    message_id = run(livelists.show(1, "shopping", HUB, "milk, eggs"))
    current = {"text": "eggs"}

    async def render():
        return current["text"]

    async def scenario():
        livelists.changed(1, "shopping", render)

    run(scenario())
    assert channel["edited"] == [(HUB, message_id, "eggs", 0)] and len(channel["sent"]) == 1, "no new message"


def test_several_changes_at_once_are_one_rewrite_with_the_final_state(channel):
    message_id = run(livelists.show(1, "shopping", HUB, "milk, eggs, bread"))
    state = {"text": "milk, eggs, bread"}

    async def render():
        return state["text"]

    async def scenario():
        for now in ("eggs, bread", "bread", "nothing"):
            state["text"] = now
            livelists.changed(1, "shopping", render)

    run(scenario())
    assert channel["edited"] == [(HUB, message_id, "nothing", 0)]


def test_asking_again_makes_the_new_copy_live_and_leaves_the_old_one_as_it_was(channel):
    first = run(livelists.show(1, "shopping", HUB, "milk"))
    second = run(livelists.show(1, "shopping", 100, "milk"))

    async def render():
        return "milk, eggs"

    assert run(livelists.refresh(1, "shopping", render)) is True
    assert channel["edited"] == [(100, second, "milk, eggs", 0)]
    assert run(livelists.message_class(first)) is None, "the older copy is no longer kept up to date"


def test_a_list_can_be_a_card_with_buttons(channel):
    message_id = run(livelists.show(1, "pills:today", HUB, Card("list", ((Button("Taken", "pills", "taken", "1"),),))))

    async def render():
        return Card("list, changed", ((Button("Taken", "pills", "taken", "1"),),))

    run(livelists.refresh(1, "pills:today", render))
    assert channel["edited"] == [(HUB, message_id, "list, changed", 1)]


def test_a_list_that_was_never_shown_or_has_gone_is_not_rewritten(channel):
    async def render():
        return "anything"

    assert run(livelists.refresh(1, "shopping", render)) is False
    message_id = run(livelists.show(1, "shopping", HUB, "milk"))
    channel["gone"].add(message_id)  # deleted by hand
    assert run(livelists.refresh(1, "shopping", render)) is False


def test_lists_are_kept_apart_by_user_and_by_key(channel):
    mine = run(livelists.show(1, "shopping", HUB, "milk"))
    run(livelists.show(1, "packing", HUB, "socks"))

    async def render():
        return "changed"

    run(livelists.refresh(1, "shopping", render))
    assert [edit[1] for edit in channel["edited"]] == [mine]
    assert run(livelists.refresh(2, "shopping", render)) is False, "someone else has shown no such list"


def test_where_the_live_copy_is_survives_a_restart(channel):
    message_id = run(livelists.show(1, "shopping", HUB, "milk"))
    found = run(database.run(livelists.db_get, 1, "shopping"))
    assert (found.channel_id, found.message_id) == (HUB, message_id), "a row, not memory"


# ---------------------------------------------------------------------------
# A list on screen is context for what is said next
# ---------------------------------------------------------------------------
def test_a_list_remembers_whose_task_it_is_and_when_it_was_shown(channel):
    message_id = run(livelists.show(1, "packing", HUB, "socks", task="packing"))
    found = run(livelists.by_message(message_id))
    assert (found.key, found.task, found.message_id) == ("packing", "packing", message_id)
    assert utc_now() - found.shown_at < timedelta(seconds=5)
    assert run(livelists.by_message(None)) is None and run(livelists.by_message(123)) is None


@pytest.mark.parametrize(
    "age, latest, said, expected",
    [
        (0, 50, "add milk", True),
        (4, 50, "and two more eggs please", True),
        (6, 50, "add milk", False),  # shown too long ago
        (0, 51, "add milk", False),  # the bot has said something else since
        (0, None, "add milk", False),
        (0, 50, "could you please put honey and also some jam on the list for me", False),  # not a short follow-up
        (0, 50, "   ", False),
    ],
)
def test_when_a_message_is_taken_as_being_for_the_list_on_screen(age, latest, said, expected):
    now = utc_now()
    shown = livelists.Placed(1, "packing", HUB, 50, "packing", now - timedelta(minutes=age))
    assert livelists.sticks(shown, said, now, latest) is expected


def test_a_list_with_no_task_is_nobodys_context():
    now = utc_now()
    assert not livelists.sticks(livelists.Placed(1, "x", HUB, 50, "", now), "add milk", now, 50)
    assert not livelists.sticks(livelists.Placed(1, "x", HUB, 50, "packing", None), "add milk", now, 50)
