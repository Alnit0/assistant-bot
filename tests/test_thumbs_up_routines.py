"""👍 on a routine's own card (Alex, 21 Oct): every item still open today is done, the card becomes a plain green
embed with 🟩 Done, and taking the 👍 away opens those items again. With 👍 on the routine has no dropdown; ticking
in words works as before. Made-up routine and items."""
import pytest

from core import config, thumbsup, design
from tasks.habits import plain, rules
from tests.test_habits import evening, run, tick, today, world  # noqa: F401


@pytest.fixture
def on(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "THUMBS_UP", True)
    thumbsup.reset()
    from core import cards

    cards.register(rules.TASK, rules.ALL_DONE, plain.on_all_done)
    cards.register(rules.TASK, rules.ALL_UNDO, plain.on_all_undone)
    evening(world)
    from core import clock
    from core import day as days
    from datetime import time

    clock.advance_to(days.at(world.day, time(18, 30)))
    yield world
    thumbsup.reset()


def own(world):
    (found,) = today(world)
    return run(plain.own_card(world.owner.id, found.habit.id))


def test_the_routine_s_own_card_is_a_plain_embed_with_no_dropdown_that_a_thumbs_up_confirms(on):
    card = own(on)
    (embed,) = card.embeds
    assert embed.status == design.ROUTINE and embed.description.splitlines()[0] == "6:00 pm · 🌙 Evening"
    assert card.rows == () and card.layout == () and card.thumbs_up.action == rules.ALL_DONE
    assert "👍 when it's all done" in embed.description


def test_thumbs_up_does_it_all_turns_it_green_and_taking_it_away_undoes_it(on):
    card = own(on)
    press = thumbsup.ReactionPress(on.owner, rules.TASK, rules.ALL_DONE, card.thumbs_up.arg, 100, 555)
    assert run(plain.on_all_done(press)) == "✅ Evening · all done"
    (found,) = today(on)
    assert found.finished
    done = own(on)
    assert done.embeds[0].status == design.TAKEN and done.embeds[0].description.endswith("· 🟩 Done") and done.thumbs_up is None
    run(plain.on_all_undone(thumbsup.ReactionPress(on.owner, rules.TASK, rules.ALL_UNDO, press.undo.arg, 100, 555)))
    assert today(on)[0].done == 0, "the three it ticked are open again"


def test_ticking_in_words_still_works_and_counts_on_the_card(on):
    tick(on, "floss")
    card = own(on)
    assert "▫️ floss" not in card.embeds[0].description and "✅ 1 done" in card.embeds[0].description


def test_a_thumbs_up_after_it_was_all_done_in_words_is_nothing(on):
    tick(on, "brush teeth", "floss", "skincare")
    card = own(on)
    assert card.thumbs_up is None, "done: the card asks nothing, so no 👍 is noted"
    (found,) = today(on)
    press = thumbsup.ReactionPress(on.owner, rules.TASK, rules.ALL_DONE, str(found.habit.id), 100, 555)
    assert run(plain.on_all_done(press)) == "already dealt with" and press.undo is None


def test_switched_off_the_dropdown_is_still_there(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "THUMBS_UP", False)
    evening(world)
    from core import clock
    from core import day as days
    from datetime import time

    clock.advance_to(days.at(world.day, time(18, 30)))
    card = own(world)
    assert card.embeds == () and any(type(piece).__name__ == "Select" for box in card.layout for piece in box.children)
