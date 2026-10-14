"""Personal routines (tasks/habits), behind HABITS_ENABLED: making one, ticking steps by words and by button, a fresh start each day, chosen days, changing, removing, the card, the briefing and attention."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import attention, cards, clock, config, design
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.habits import plain, rules, store
from tasks.habits import task as habits_task

INBOX = 100


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner):
    make_db({"habits": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, told=[])
    monkeypatch.setattr(plain, "changed", lambda user_id: seen.told.append(user_id))
    wednesday = days.today() + timedelta(days=(2 - days.today().weekday()) % 7 or 7)
    seen.day = wednesday
    clock.advance_to(days.at(wednesday, time(7, 0)))
    seen.request = lambda text="said": Request(owner, INBOX, text)
    return seen


def make(world, **data):
    proposal = run(plain.add_card(world.request(), data, frozenset()))
    run(plain.add_save(world.request(), proposal.data))
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    return proposal


def morning(world, days_=None):
    return make(world, routine="morning routine", steps=["stretch", "water", "journal"], **({"days": days_} if days_ else {}))


def test_off_unless_set_and_not_in_help():
    assert config.HABITS_ENABLED is False and not habits_task.switched_on()
    registry.load()
    assert "habits" not in [task.name for task in registry.loaded_tasks()]


def test_making_one_is_a_card_with_its_days_and_steps(world):
    proposal = morning(world, ["mon", "tue", "wed", "thu", "fri"])
    assert proposal.lines == ("**Morning** · weekdays", "1. Stretch · 2. Water · 3. Journal")
    with pytest.raises(UserError, match="already"):
        run(plain.add_card(world.request(), {"routine": "Morning", "steps": ["x"]}, frozenset()))


def test_ticking_a_step_by_words_says_how_far_along_and_what_is_next(world):
    morning(world)
    assert run(plain.tick(world.request("did stretch"), {"steps": ["stretch"]}, frozenset())) == "✅ **Stretch** · Morning 1/3 · next: Water"
    assert run(plain.tick(world.request(), {"steps": ["water", "journal"]}, frozenset())) == "✅ **Water**, **Journal** · Morning done"
    with pytest.raises(UserError, match="Every step"):
        run(plain.tick(world.request(), {"steps": ["stretch"]}, frozenset()))


def test_undo_puts_a_step_back(world):
    morning(world)
    run(plain.tick(world.request(), {"steps": ["stretch"]}, frozenset()))
    assert run(plain.untick(world.request("undo stretch"), {"steps": ["stretch"]}, frozenset())) == "↩️ **Stretch** · not done · Morning 0/3 · next: Stretch"


def test_the_button_ticks_the_next_step_and_a_second_press_does_nothing(world):
    morning(world)
    (shown,) = run(plain.today_of(world.owner.id))
    step = shown.next_step
    press = SimpleNamespace(user=world.owner, arg=str(step.id), db=cards.Press.db)
    assert run(plain.on_tick(press)) == "✅ Stretch" and run(plain.on_tick(press)) == "already dealt with"


def test_each_day_starts_afresh(world):
    morning(world)
    run(plain.tick(world.request(), {"steps": ["stretch", "water"]}, frozenset()))
    clock.advance_to(days.at(world.day + timedelta(days=1), time(7, 0)))
    (shown,) = run(plain.today_of(world.owner.id))
    assert shown.done == 0 and shown.next_step.text == "Stretch"


def test_a_routine_on_chosen_days_is_not_due_on_the_others(world):
    morning(world, ["sat", "sun"])
    assert run(plain.today_of(world.owner.id)) == [] and run(plain.hub_card(world.owner.id)) is None, "a Wednesday: no card"


def test_adding_and_removing_steps_is_a_change_card(world):
    morning(world)
    proposal = run(plain.change_card(world.request(), {"routine": "morning", "steps": ["meditate"]}, frozenset()))
    assert proposal.lines[:2] == ("**Morning**", "steps · 3 → 4") and design.changed(proposal.lines[1]) == "steps · ~~3~~ → **4**"
    run(plain.change_save(world.request(), proposal.data))
    assert run(plain.change_check(world.request(), proposal.data)) == ""
    proposal = run(plain.change_card(world.request(), {"routine": "morning", "steps": ["water"], "steps_change": "remove"}, frozenset()))
    run(plain.change_save(world.request(), proposal.data))
    assert [step.text for step in run(store.every(world.owner.id))[0].steps] == ["Stretch", "Journal", "Meditate"]


def test_a_tick_survives_a_change_to_the_other_steps(world):
    morning(world)
    run(plain.tick(world.request(), {"steps": ["stretch"]}, frozenset()))
    proposal = run(plain.change_card(world.request(), {"routine": "morning", "steps": ["meditate"]}, frozenset()))
    run(plain.change_save(world.request(), proposal.data))
    (shown,) = run(plain.today_of(world.owner.id))
    assert (shown.done, shown.total) == (1, 4)


def test_removing_is_a_red_card(world):
    morning(world)
    proposal = run(plain.remove_card(world.request(), {"routine": "morning"}, frozenset()))
    assert proposal.confirm_label == "Remove" and proposal.lines[0] == "**Morning** → removed"
    run(plain.remove_save(world.request(), proposal.data))
    assert run(store.every(world.owner.id)) == [] and run(plain.remove_check(world.request(), proposal.data)) == ""


def test_the_card_has_dots_a_routine_an_item_and_finished_ones_in_one_small_line(world):
    assert run(plain.hub_card(world.owner.id)) is None
    morning(world)
    make(world, routine="evening", steps=["read"])
    run(plain.tick(world.request(), {"steps": ["read"]}, frozenset()))
    run(plain.tick(world.request(), {"steps": ["stretch"]}, frozenset()))
    shown = run(plain.hub_card(world.owner.id))
    (box,) = shown.layout
    assert box.children[0].content == "### 🔁 Personal routines ●●○○ 2/4"
    assert box.children[2].content.startswith("**Morning** ●○○ 1/3\nnext: Water")
    assert [button.label for button in design.buttons(shown.layout)] == ["Water"] and box.children[-1].content == "-# ✅ Evening"


def test_the_briefing_and_attention(world):
    from tasks import habits

    morning(world)
    said = run(habits.summary(world.owner.id, world.day))
    assert (said.done, said.total) == (0, 3) and said.lines == ("**Morning** ○○○ 0/3",)
    now = clock.now()
    (useful,) = run(habits.items(world.owner.id, now))
    assert attention.level(useful, now) == attention.LEVEL_USEFUL and useful.short == ("0/3",)
    run(plain.tick(world.request(), {"steps": ["stretch", "water", "journal"]}, frozenset()))
    assert run(habits.items(world.owner.id, now)) == []
