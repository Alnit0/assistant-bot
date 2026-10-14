"""To-dos (tasks/todos), behind TODOS_ENABLED: adding, ticking off and back, carry over, changing and removing, the hub card, the briefing and attention."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import attention, cards, clock, config, design, hubcard
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.todos import plain, rules, store
from tasks.todos import task as todos_task

INBOX = 100


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner):
    """An empty list, at 9 am on a Wednesday; what the hub card and the briefing were told is kept."""
    make_db({"todos": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, told=[])
    monkeypatch.setattr(plain, "changed", lambda user_id: seen.told.append(user_id))
    wednesday = days.today() + timedelta(days=(2 - days.today().weekday()) % 7 or 7)
    seen.day = wednesday
    clock.advance_to(days.at(wednesday, time(9, 0)))
    seen.request = lambda text="said": Request(owner, INBOX, text)
    return seen


def add(world, *items, said="add"):
    proposal = run(plain.add_card(world.request(said), {"todos": list(items)}, frozenset()))
    run(plain.add_save(world.request(said), proposal.data))
    assert run(plain.add_check(world.request(said), proposal.data)) == ""
    return proposal


def today(world):
    return rules.on(run(store.every(world.owner.id)), world.day)


# --- adding -----------------------------------------------------------------------------------------------------
def test_a_to_do_with_a_day_is_a_card_first_and_save_adds_it(world):
    proposal = run(plain.add_card(world.request("add call Ryan Friday"), {"todos": [{"text": "call Ryan", "day": "Friday"}]}, frozenset()))
    friday = world.day + timedelta(days=2)
    assert proposal.kind == "new" and proposal.lines == (f"**Call Ryan** · Fri {friday.day} {friday:%b}",)
    assert run(store.every(world.owner.id)) == [], "nothing is added until Save"
    run(plain.add_save(world.request(), proposal.data))
    (todo,) = run(store.every(world.owner.id))
    assert todo.text == "Call Ryan" and todo.day == world.day + timedelta(days=2) and world.told


def test_one_with_no_day_is_for_any_day_and_several_are_one_card(world):
    proposal = add(world, {"text": "buy stamps"}, {"text": "milk", "day": "today"})
    assert proposal.lines == ("**Buy stamps** · any day", "**Milk** · today")
    assert [each.text for each in today(world).today] == ["Milk", "Buy stamps"], "today's first, then those for any day"


def test_the_same_words_twice_are_not_added_twice(world):
    add(world, {"text": "buy stamps"})
    with pytest.raises(UserError, match="already on your list"):
        run(plain.add_card(world.request(), {"todos": [{"text": "Buy stamps"}]}, frozenset()))


def test_a_day_that_cannot_be_read_is_said_and_the_to_do_is_for_any_day(world):
    proposal = run(plain.add_card(world.request(), {"todos": [{"text": "call Ryan", "day": "whenever-ish"}]}, frozenset()))
    assert proposal.lines == ("**Call Ryan** · any day",) and "not a day I can read" in proposal.warnings[0]


# --- done and undone ----------------------------------------------------------------------------------------------
def test_done_by_words_ticks_it_off_at_once_and_says_what_is_left(world):
    add(world, {"text": "call Ryan", "day": "today"}, {"text": "buy stamps"})
    said = run(plain.done(world.request("I called Ryan"), {"todos": [{"todo": "ryan"}]}, frozenset()))
    assert said == "✅ **Call Ryan** · done · 1 left today"
    assert [each.text for each in today(world).done] == ["Call Ryan"]


def test_undo_with_nothing_named_puts_back_the_one_ticked_off_last(world):
    add(world, {"text": "call Ryan"}, {"text": "buy stamps"})
    run(plain.done(world.request(), {"todos": [{"todo": "ryan"}]}, frozenset()))
    clock.advance_to(clock.now() + timedelta(minutes=5))
    run(plain.done(world.request(), {"todos": [{"todo": "stamps"}]}, frozenset()))
    said = run(plain.undone(world.request("undo that"), {"todos": [{"todo": "@that"}]}, frozenset()))
    assert said == "↩️ **Buy stamps** · not done" and [each.text for each in today(world).done] == ["Call Ryan"]


def test_a_name_that_fits_two_is_asked_never_guessed(world):
    add(world, {"text": "call Ryan"}, {"text": "call Mum"})
    with pytest.raises(UserError, match="say which"):
        run(plain.done(world.request("done call"), {"todos": [{"todo": "call"}]}, frozenset()))
    assert today(world).done == ()


def test_the_done_button_ticks_it_off_and_a_second_press_does_nothing(world):
    add(world, {"text": "call Ryan"})
    (todo,) = run(store.every(world.owner.id))
    press = SimpleNamespace(user=world.owner, arg=str(todo.id), db=cards.Press.db)
    assert run(plain.on_done(press)) == "✅ Call Ryan · done"
    assert run(plain.on_done(press)) == "already dealt with"


# --- carry over ------------------------------------------------------------------------------------------------------
def test_an_undone_to_do_carries_over_as_overdue_and_keeps_its_day(world):
    add(world, {"text": "call Ryan", "day": "today"}, {"text": "pay the bill", "day": "today"})
    run(plain.done(world.request(), {"todos": [{"todo": "bill"}]}, frozenset()))
    tomorrow = world.day + timedelta(days=1)
    found = rules.on(run(store.every(world.owner.id)), tomorrow)
    assert [each.text for each in found.overdue] == ["Call Ryan"] and found.done == (), "yesterday's done one has gone; the open one is overdue"
    box = rules.layout(found, tomorrow)[0]
    assert box.status == design.DUE and "-# from yesterday" in box.children[2].content


def test_one_for_a_later_day_is_not_today_s(world):
    add(world, {"text": "call Ryan", "day": "Friday"})
    found = today(world)
    assert found.is_empty and len(found.later) == 1


# --- change and remove ------------------------------------------------------------------------------------------------
def test_moving_a_to_do_is_a_change_card_old_struck_through_new_bold(world):
    add(world, {"text": "call Ryan", "day": "Friday"})
    proposal = run(plain.change_card(world.request("move call Ryan to Monday"), {"todos": [{"todo": "call ryan", "day": "Monday"}]}, frozenset()))
    assert proposal.kind == "change" and proposal.lines[1].startswith("day · Fri ") and " → Mon " in proposal.lines[1]
    assert design.changed(proposal.lines[1]).startswith("day · ~~Fri ")
    run(plain.change_save(world.request(), proposal.data))
    assert run(plain.change_check(world.request(), proposal.data)) == ""
    assert run(store.every(world.owner.id))[0].day.weekday() == 0


def test_removing_is_a_card_with_a_red_remove_and_the_row_is_kept(world):
    add(world, {"text": "call Ryan"})
    proposal = run(plain.remove_card(world.request(), {"todos": [{"todo": "ryan"}]}, frozenset()))
    assert proposal.kind == "remove" and proposal.confirm_label == "Remove" and proposal.lines == ("**Call Ryan** → removed",)
    run(plain.remove_save(world.request(), proposal.data))
    assert run(store.every(world.owner.id)) == [] and run(plain.remove_check(world.request(), proposal.data)) == ""


# --- the card, the briefing and attention ----------------------------------------------------------------------------
def test_a_day_with_nothing_for_today_has_no_card(world):
    assert run(plain.hub_card(world.owner.id)) is None
    add(world, {"text": "later", "day": "Friday"})
    assert run(plain.hub_card(world.owner.id)) is None, "only for later: still no card"


def test_the_card_is_round_3_overdue_first_a_done_button_each_and_done_in_one_small_line(world):
    add(world, {"text": "call Ryan", "day": "today"}, {"text": "buy stamps"}, {"text": "pay the bill", "day": "today"})
    run(plain.done(world.request(), {"todos": [{"todo": "bill"}]}, frozenset()))
    shown = run(plain.hub_card(world.owner.id))
    (box,) = shown.layout
    assert box.children[0].content == "### 📝 To-dos ●○○ 1/3"
    assert [button.label for button in design.buttons(shown.layout)] == ["Done", "Done"] and all(button.style == cards.SUCCESS for button in design.buttons(shown.layout))
    assert box.children[-1].content == "-# ✅ Pay the bill"
    assert design.problem(shown.layout) == "" and shown.text.startswith("## 📝 To-dos · 1 of 3 done")


def test_a_long_list_still_fits_one_message(world):
    add(world, *({"text": f"thing {n:02}"} for n in range(40)))
    shown = run(plain.hub_card(world.owner.id))
    assert design.problem(shown.layout) == "" and "and 28 more" in "\n".join(design.texts(shown.layout))


def test_the_briefing_has_today_s_to_dos_with_the_day_s_count(world):
    from tasks import todos

    assert run(todos.summary(world.owner.id, world.day)) is None
    add(world, {"text": "call Ryan", "day": "today"}, {"text": "buy stamps"})
    said = run(todos.summary(world.owner.id, world.day))
    assert (said.done, said.total, said.status) == (0, 2, design.ANY_TIME) and said.lines == ("**Call Ryan**", "**Buy stamps**")


def test_overdue_is_what_to_look_at_now_and_today_s_are_useful(world):
    from tasks import todos

    add(world, {"text": "call Ryan", "day": "today"})
    now = clock.now()
    (useful,) = run(todos.items(world.owner.id, now))
    assert attention.level(useful, now) == attention.LEVEL_USEFUL and useful.short == ("0/1",)
    later = days.at(world.day + timedelta(days=1), time(9, 0))
    overdue = run(todos.items(world.owner.id, later))[0]
    assert attention.level(overdue, later) == attention.LEVEL_DUE and overdue.short == ("1 overdue",)
    assert "Ryan" not in attention.status_line(overdue), "never a to-do's words on the status line"


# --- the switch ------------------------------------------------------------------------------------------------------
def test_off_unless_set_and_then_not_in_help_or_the_router(monkeypatch):
    assert config.TODOS_ENABLED is False and not todos_task.switched_on()
    registry.load()
    assert "todos" not in [task.name for task in registry.loaded_tasks()]
    monkeypatch.setattr(config, "TODOS_ENABLED", True)
    registry.load()
    try:
        assert "todos" in [task.name for task in registry.loaded_tasks()]
        from core import actions

        entry = actions.entry("todos")
        assert entry.title == "To-dos" and not actions.problems([entry])
    finally:
        monkeypatch.setattr(config, "TODOS_ENABLED", False)
        registry.load()
