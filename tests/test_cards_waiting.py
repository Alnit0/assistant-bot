"""Cards waiting for an answer (core/confirm.py), after a live bug of 19 Oct: Save on a repeating calendar event
took 5.8 seconds, a second tap meanwhile said "the card has gone and nothing was saved" over what had been saved.
A card is kept in the database and waits at least 24 hours (a week at a time in #guide, or pinned or 📌); a slow
Save says so on the card and a second press does nothing; a press after Save shows what was saved; the hub's tidy
never takes a waiting card; an expired one offers Redo, which makes it again from what was said. Restarts are in
tests/test_restart.py. Made-up data."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import config, confirm, database, messages, scheduler
from core import day as days
from tests.test_conversation import open_cards, route, run, shop_add, shopping_list, world  # noqa: F401


@pytest.fixture
def card(world, dev_clock):
    world.claude(route("shopping"), shop_add("milk", 2))
    world.say("add 2 milk")
    world.clock = dev_clock
    return open_cards()[-1]


def later(world, by: timedelta):
    async def move():
        world.clock.advance(by)
        await scheduler.run_all_due()

    run(move())


def buttons(shown):
    return [button.label for row in shown.rows for button in row]


# --- how long a card waits ----------------------------------------------------------------------------------------
def test_a_card_waits_at_least_24_hours(world, card):
    later(world, timedelta(hours=23, minutes=59))
    assert run(database.run(confirm.db_get, card.id)).is_open
    press = world.Press(card.id, card.message_id)
    run(confirm.on_save(press))
    assert press.cards[-1].text.startswith("✅ Saved") and shopping_list() == [{"item": "milk", "quantity": 2}]


def test_after_24_hours_it_expires_and_a_press_offers_redo_never_typing_again(world, card):
    later(world, timedelta(hours=24, minutes=1))
    assert run(database.run(confirm.db_get, card.id)).status == confirm.EXPIRED
    press = world.Press(card.id, card.message_id)
    assert run(confirm.on_save(press)) == "card had gone"
    assert press.cards[-1].text == confirm.EXPIRED_TEXT and buttons(press.cards[-1]) == ["Redo"] and shopping_list() == []


def test_redo_makes_the_same_card_again_from_what_was_said(world, card):
    from core import conversation

    later(world, timedelta(hours=25))
    world.claude(shop_add("milk", 2))  # the task's extraction only: the router is not asked again
    before = len(world.requests)
    redo = world.Press(card.id, card.message_id)
    said = run(conversation.on_redo(redo))
    assert said.startswith(f"redone card {card.id}") and redo.removed
    assert len(world.requests) == before + 1, "one request, extraction"
    fresh = open_cards()[-1]
    assert fresh.id != card.id and fresh.is_open and fresh.said == "add 2 milk"
    assert world.sent[-1][1].text.startswith("🛒 Shopping · new")
    again = world.Press(card.id, card.message_id)
    assert run(conversation.on_redo(again)) == "nothing to redo", "only an expired card is redone"


def test_a_card_in_guide_waits_a_week(world, card, monkeypatch):
    monkeypatch.setitem(config.CHANNELS, "guide", 100)
    assert confirm.lifetime(100) == timedelta(days=7) and confirm.lifetime(400) == timedelta(hours=24)


def test_a_pinned_card_is_kept_another_week_instead_of_expiring(world, card, monkeypatch):
    from core import surface

    async def fetch(channel_id, message_id):
        return SimpleNamespace(pinned=True, reactions=[])

    monkeypatch.setattr(surface, "fetch", fetch)
    later(world, timedelta(hours=24, minutes=1))
    kept = run(database.run(confirm.db_get, card.id))
    assert kept.is_open and kept.job_id != card.job_id, "booked again a week on"


# --- Save: slow, pressed twice, pressed after ---------------------------------------------------------------------
def test_a_slow_save_says_so_first_and_a_second_press_meanwhile_does_nothing(world, card, monkeypatch):
    from core import actions

    action = actions.entry("shopping").action(card.action)
    real = action.apply

    async def slow(request, data):
        await asyncio.sleep(confirm.SLOW_SAVE + 0.3)
        return await real(request, data)

    monkeypatch.setattr(confirm, "SLOW_SAVE", 0.05)
    object.__setattr__(action, "apply", slow)  # an Action is frozen: put back below
    first, second = world.Press(card.id, card.message_id), world.Press(card.id, card.message_id)

    async def both():
        saving = asyncio.ensure_future(confirm.on_save(first))
        await asyncio.sleep(0.1)
        return await confirm.on_save(second), await saving

    try:
        again, done = run(both())
    finally:
        object.__setattr__(action, "apply", real)
    assert first.cards[0].text == confirm.SAVING and first.cards[0].rows == (), "said at once, with no button to press again"
    assert first.cards[-1].text.startswith("✅ Saved") and done.startswith("saved")
    assert again == "pressed again while saving: nothing done" and second.cards == []
    assert shopping_list() == [{"item": "milk", "quantity": 2}], "saved once"


def test_a_press_after_save_shows_what_was_saved(world, card):
    run(confirm.on_save(world.Press(card.id, card.message_id)))
    later_press = world.Press(card.id, card.message_id)
    run(confirm.on_save(later_press))
    assert later_press.cards[-1].text.startswith("✅ Saved · 🛒 **milk** × 2"), "never “nothing was saved” after a Save"


# --- the hub's tidy -----------------------------------------------------------------------------------------------------
def test_the_tidy_never_takes_a_waiting_card():
    import sqlite3

    from core import migrations

    conn = sqlite3.connect(":memory:")
    for each in migrations.MIGRATIONS:
        each(conn)
    yesterday = days.at(days.today() - timedelta(days=1), time(22, 0))
    for message_id in (1, 2):
        messages.db_add(conn, message_id, 400, messages.EXPIRY, yesterday)
    conn.execute("UPDATE bot_messages SET waits = 1 WHERE message_id = 1")
    due = [each.message_id for each in messages.db_due(conn, yesterday + timedelta(hours=10), 400)]
    assert due == [2], "the card waiting since last night stays; the rest of yesterday goes"
