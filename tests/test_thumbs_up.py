"""👍 on a message that asks one simple yes (Alex, 21 Oct; core/thumbsup.py): it does what the message's own
button does, through the same handler. The registry is in memory, fed by core/cards.py from each card's
`thumbs_up`; the reaction is the builtin task's, checked at once and acted on after the quiet period like every
reaction but 🐞. In the world of the pills reminder tests (a hub, cards that record). Made-up names."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, config, thumbsup
from core.cards import Button, Card
from core.errors import UserError
from tasks import registry
from tasks.builtin import BuiltinTask
from core import occurrences
from tasks.pills import checklist, reminders
from tests.test_pills_reminders import HUB, add, at, log, prompts, run, world  # noqa: F401
from tests.test_registry import reactions_watched  # noqa: F401

MORNING = {"name": "Morning dose", "times": ["8:00 am"]}


@pytest.fixture
def on(world, monkeypatch):  # noqa: F811
    """👍 switched on, the registry empty, a made-up yes action registered."""
    monkeypatch.setattr(config, "THUMBS_UP", True)
    thumbsup.reset()
    world.yes = []

    async def made_up_yes(press):
        world.yes.append((press.arg, press.message_id))
        return f"done {press.arg}"

    cards.register("made_up", "yes", made_up_yes)
    # The world's stand-ins for sending, editing and deleting, with the same notes core/cards.py makes
    # (the real ones are checked in test_the_real_cards_note_and_forget_the_yes)
    sent, edited, deleted = cards.send, cards.edit, cards.delete

    async def send(channel_id, card, silent=False):
        message_id = await sent(channel_id, card, silent=silent)
        if card.thumbs_up is not None:
            thumbsup.register(message_id, channel_id, card.thumbs_up)
        return message_id

    async def edit(channel_id, message_id, card):
        done = await edited(channel_id, message_id, card)
        thumbsup.follow(message_id, channel_id, card)
        return done

    async def delete(channel_id, message_id):
        thumbsup.drop(message_id)
        return await deleted(channel_id, message_id)

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    yield world
    thumbsup.reset()


def test_the_real_cards_note_and_forget_the_yes(monkeypatch):
    """core/cards.py itself: send notes a card's yes, an edit with none forgets it, a delete forgets it."""
    from core import messages, surface

    monkeypatch.setattr(config, "THUMBS_UP", True)
    thumbsup.reset()
    monkeypatch.setattr(surface, "place", lambda channel_id: object())

    async def send_card(channel_id, card, text, silent=False):
        return 4242

    async def edit_card(channel_id, message_id, card, plain):
        return None

    async def delete(channel_id, message_id):
        return None

    async def record(*args, **kwargs):
        return None

    monkeypatch.setattr(surface, "send_card", send_card)
    monkeypatch.setattr(surface, "edit_card", edit_card)
    monkeypatch.setattr(surface, "delete", delete)
    monkeypatch.setattr(messages, "record", record)
    yes = Button("Done", "made_up", "yes", "x")
    assert run(cards.send(HUB, Card("Evening routine", thumbs_up=yes))) == 4242 and thumbsup.pending(4242).button == yes
    run(cards.edit(HUB, 4242, Card("Evening routine", thumbs_up=yes)))
    assert thumbsup.tracked(4242), "rewritten with the same yes: kept"
    run(cards.edit(HUB, 4242, Card("Evening routine · how long?")))
    assert not thumbsup.tracked(4242)
    run(cards.send(HUB, Card("Evening routine", thumbs_up=yes)))
    run(cards.delete(HUB, 4242))
    assert not thumbsup.tracked(4242)
    thumbsup.reset()


def posted(world, thumbs_up=Button("Done", "made_up", "yes", "evening-routine")):
    return run(cards.send(HUB, Card("Evening routine", thumbs_up=thumbs_up)))


# --- the registry --------------------------------------------------------------------------------------------------------
def test_a_thumbs_up_on_a_tracked_message_runs_its_action_and_the_entry_goes(on):
    message_id = posted(on)
    assert thumbsup.tracked(message_id)
    assert run(thumbsup.confirm(message_id, on.owner)) == "done evening-routine"
    assert on.yes == [("evening-routine", message_id)]
    assert not thumbsup.tracked(message_id), "fulfilled: gone from the registry"


def test_a_second_thumbs_up_does_nothing(on):
    message_id = posted(on)
    run(thumbsup.confirm(message_id, on.owner))
    assert run(thumbsup.confirm(message_id, on.owner)) is None and len(on.yes) == 1


def test_an_untracked_message_is_nothing_and_says_nothing(on):
    message_id = run(cards.send(HUB, Card("Made-up note")))
    assert not thumbsup.tracked(message_id) and run(thumbsup.confirm(message_id, on.owner)) is None and on.yes == []


def test_an_entry_lasts_24_hours(on):
    now = clock.now()
    thumbsup.register(77, HUB, Button("Done", "made_up", "yes", "x"), now=now)
    assert thumbsup.pending(77, now + timedelta(hours=23, minutes=59)) is not None
    assert thumbsup.pending(77, now + timedelta(hours=24)) is None and not thumbsup.tracked(77)


def test_a_card_rewritten_without_a_yes_or_deleted_is_forgotten(on):
    message_id = posted(on)
    run(cards.edit(HUB, message_id, Card("Evening routine · asked how long")))
    assert not thumbsup.tracked(message_id)
    again = posted(on)
    run(cards.delete(HUB, again))
    assert not thumbsup.tracked(again)


def test_switched_off_nothing_is_noted_and_there_is_no_reaction(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "THUMBS_UP", False)
    thumbsup.reset()
    assert not thumbsup.tracked(posted(world)) and BuiltinTask().reactions() == []


def test_an_action_that_cannot_be_done_keeps_the_yes_for_another_try(on):
    async def refuses(press):
        raise UserError("Not now.")

    cards.register("made_up", "refuses", refuses)
    message_id = posted(on, Button("Done", "made_up", "refuses", "x"))
    with pytest.raises(UserError):
        run(thumbsup.confirm(message_id, on.owner))
    assert thumbsup.tracked(message_id)


# --- the reaction: only 👍, only the user, only a tracked message ---------------------------------------------------------
@pytest.fixture
def thumbs(on, reactions_watched, monkeypatch):  # noqa: F811
    (reaction,) = BuiltinTask().reactions()
    monkeypatch.setitem(registry._reactions, registry._emoji_key(reaction.emoji), (BuiltinTask(), reaction))
    monkeypatch.setattr(registry, "_reaction_debouncer", SimpleNamespace(trigger=reactions_watched.debounced.append, delay=0))
    reactions_watched.world = on
    return reactions_watched


def reacted(emoji, message_id, user_id=1):
    return SimpleNamespace(emoji=emoji, channel_id=HUB, message_id=message_id, user_id=user_id)


def test_a_thumbs_up_on_a_tracked_message_waits_its_quiet_period(thumbs):
    message_id = posted(thumbs.world)
    payload = reacted("👍", message_id)
    asyncio.run(registry.reaction_changed(payload, True))
    assert thumbs.debounced == [(payload, True)] and thumbs.refused == []


def test_a_thumbs_up_on_an_untracked_message_is_ignored_in_silence(thumbs):
    asyncio.run(registry.reaction_changed(reacted("👍", 12345), True))
    assert thumbs.debounced == [] and thumbs.refused == [] and thumbs.marks == []


def test_another_emoji_on_a_tracked_message_is_ignored(thumbs):
    message_id = posted(thumbs.world)
    asyncio.run(registry.reaction_changed(reacted("🙂", message_id), True))
    assert thumbs.debounced == [] and thumbsup.tracked(message_id) and thumbs.world.yes == []


def test_the_bot_s_own_thumbs_up_is_never_input(thumbs, monkeypatch):
    message_id = posted(thumbs.world)
    applied = []

    async def nobody(discord_id):
        return None  # the bot is no user of its own

    async def apply(key, payload, user):
        applied.append(key)

    monkeypatch.setattr(registry, "get_user_by_discord_id", nobody)
    monkeypatch.setattr(registry, "_apply_reaction", apply)
    asyncio.run(registry._reactions_quiet([(reacted("👍", message_id, user_id=999), True)]))
    assert applied == [] and thumbsup.tracked(message_id)


def test_after_the_quiet_period_it_runs_once(thumbs, monkeypatch):
    message_id = posted(thumbs.world)
    asyncio.run(registry.dispatch_reaction(reacted("👍", message_id)))
    assert thumbs.world.yes == [("evening-routine", message_id)]
    asyncio.run(registry._reactions_quiet([(reacted("👍", message_id), True)]))
    assert len(thumbs.world.yes) == 1, "done already: a later one is nothing"


# --- a real one: a dose's reminder -----------------------------------------------------------------------------------------
def reminder_id(world):
    ((message_id, _, buttons),) = prompts(world)
    return message_id, buttons


def test_thumbs_up_on_a_dose_reminder_is_taken(on):
    add(on, MORNING)
    at(on, 8, 0)
    message_id, buttons = reminder_id(on)
    assert "Taken" in buttons and thumbsup.pending(message_id).button.action == reminders.P_TAKEN
    said = run(thumbsup.confirm(message_id, on.owner))
    assert "Morning dose" in said and prompts(on) == [] and message_id in on.deleted, "taken: the reminder goes, as with its button"


def test_typing_taken_still_works_and_a_thumbs_up_after_it_is_nothing(on):
    add(on, MORNING)
    at(on, 8, 0)
    message_id, _ = reminder_id(on)
    at(on, 8, 6)
    said = log(on, {"pill": "morning dose", "did": "taken", "at": "8:05 am"})
    assert "Morning dose" in said, "typed: taken, as it always was"
    assert prompts(on) == [] and not thumbsup.tracked(message_id), "typed first: the reminder went, and its yes with it"
    taken = [dose for dose in run(checklist.read(on.owner.id))[1] if dose.occurrence.state == occurrences.DONE]
    assert len(taken) == 1, "logged once: the 👍 after the words did nothing more"
    assert run(thumbsup.confirm(message_id, on.owner)) is None


# --- a 👍 that is a signal (a news card: liked or read): its own kind, silent ---------------------------------------
def test_a_signal_s_thumbs_up_runs_on_and_off_silently_and_asks_no_yes(thumbs):
    world = thumbs.world

    async def noted(press):
        world.yes.append(("on", press.arg))
        return "noted"

    async def unnoted(press):
        world.yes.append(("off", press.arg))
        return "not noted"

    cards.register("made_up", "on", noted)
    cards.register("made_up", "off", unnoted)
    thumbsup.signal(4242, HUB, Button("Liked", "made_up", "on", "4242"), Button("Not liked", "made_up", "off", "4242"))
    assert thumbsup.tracked(4242) and thumbsup.pending(4242) is None, "no yes waits on it"
    asyncio.run(registry.dispatch_reaction(reacted("👍", 4242)))
    assert world.yes == [("on", "4242")] and ("✅", True) not in thumbs.marks, "silent: no ✅"
    assert run(thumbsup.undo(4242, world.owner)) == "not noted"
    assert run(thumbsup.confirm(4242, world.owner)) == "noted" and thumbsup.tracked(4242), "as often as he likes"
    thumbsup.forget_signal(4242)
    assert not thumbsup.tracked(4242) and run(thumbsup.confirm(4242, world.owner)) is None


def test_a_signal_needs_thumbs_up_on(monkeypatch):
    monkeypatch.setattr(config, "THUMBS_UP", False)
    thumbsup.reset()
    thumbsup.signal(4243, HUB, Button("Liked", "made_up", "on", "1"), Button("Not liked", "made_up", "off", "1"))
    assert not thumbsup.tracked(4243)
