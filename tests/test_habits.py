"""Personal routines (tasks/habits), behind HABITS_ENABLED, after the rework: a repeat, a when (a time, a window, any time) and a nudge; items that are steps or groups with guide steps; an item's own days; ticking by words and by the Done dropdown; a fresh start each day; changing, moving, removing; the cards by the list rule; the briefing and attention."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import attention, cards, clock, config, design, recurrence
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
    monday = days.today() + timedelta(days=(0 - days.today().weekday()) % 7 or 7)
    seen.day = monday
    clock.advance_to(days.at(monday, time(7, 0)))
    seen.request = lambda text="said": Request(owner, INBOX, text)
    return seen


def make(world, **data):
    proposal = run(plain.add_card(world.request(), data, frozenset()))
    run(plain.add_save(world.request(), proposal.data))
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    return proposal


def change(world, prepare, **data):
    proposal = run(prepare(world.request(), data, frozenset()))
    run(plain.change_save(world.request(), proposal.data))
    assert run(plain.change_check(world.request(), proposal.data)) == ""
    return proposal


SKINCARE = {"text": "skincare", "steps": ["cleanser", "toner", "serum", "moisturiser"]}


def evening(world, **more):
    return make(world, routine="evening routine", items=[{"text": "brush teeth"}, {"text": "floss"}, SKINCARE], **{"from": "6pm", "until": "11pm", **more})


def mine(world):
    (habit,) = run(store.every(world.owner.id))
    return habit


def tick(world, *said, routine=None):
    return run(plain.tick(world.request(), {"items": list(said), **({"routine": routine} if routine else {})}, frozenset()))


def today(world):
    return run(plain.today_of(world.owner.id))


# --- switched off --------------------------------------------------------------------------------------------
def test_off_unless_set_and_not_in_help():
    assert config.HABITS_ENABLED is False and not habits_task.switched_on()
    registry.load()
    assert "habits" not in [task.name for task in registry.loaded_tasks()]


# --- making one ------------------------------------------------------------------------------------------------
def test_making_one_is_a_card_with_its_window_and_items_and_a_group(world):
    proposal = evening(world)
    assert proposal.lines[0] == "**Evening** · every day · 6:00 pm to 11:00 pm · 3 items"
    assert proposal.lines[1] == "-# 1. Brush teeth · 2. Floss · 3. Skincare (Cleanser, Toner, Serum, Moisturiser)"
    habit = mine(world)
    assert (habit.when, habit.start, habit.end, habit.nudge) == (rules.WINDOW, time(18, 0), time(23, 0), rules.NUDGE_NONE)
    assert [item.kind for item in habit.items] == [rules.STEP, rules.STEP, rules.GROUP] and len(habit.items[2].guide) == 4
    with pytest.raises(UserError, match="already"):
        run(plain.add_card(world.request(), {"routine": "Evening", "items": ["x"]}, frozenset()))


def test_at_a_time_on_chosen_days_and_any_time(world):
    make(world, routine="morning", items=["stretch"], time="7am", repeat="days", weekdays=["mon", "thu"])
    make(world, routine="reading", items=["read"])
    morning, reading = run(store.every(world.owner.id))
    assert (morning.when, morning.at) == (rules.AT, time(7, 0)) and morning.repeat == recurrence.Repeat(recurrence.DAYS, weekdays=(0, 3))
    assert reading.when == rules.ANY_TIME and reading.repeat == recurrence.EVERY_DAY


def test_a_window_must_end_after_it_starts_and_an_end_nudge_needs_a_window(world):
    with pytest.raises(UserError, match="window"):
        make(world, routine="late", items=["x"], **{"from": "11pm", "until": "1am"})
    with pytest.raises(UserError, match="needs a window"):
        make(world, routine="late", items=["x"], time="9pm", nudge="end")


def test_a_time_with_no_am_or_pm_is_asked_never_guessed(world):
    with pytest.raises(UserError, match="am or pm"):
        make(world, routine="late", items=["x"], time="9")


# --- changing it -----------------------------------------------------------------------------------------------
def test_add_a_group_add_a_step_to_it_and_take_one_out(world):
    make(world, routine="evening", items=["brush teeth", "floss"])
    proposal = change(world, plain.items_card, routine="evening", items=[SKINCARE])
    assert proposal.lines[1] == "items · 2 → 3"
    change(world, plain.items_card, routine="evening", group="skincare", items=["eye cream"])
    assert [step.text for step in mine(world).items[2].guide][-1] == "Eye cream"
    change(world, plain.items_card, routine="evening", items=["toner", "floss"], change="remove")
    assert [item.text for item in mine(world).items] == ["Brush teeth", "Skincare"] and "Toner" not in [step.text for step in mine(world).items[1].guide]


def test_put_serum_before_toner_moves_a_step_within_its_group(world):
    evening(world)
    change(world, plain.move_card, item="serum", where="before", other="toner")
    assert [step.text for step in mine(world).items[2].guide] == ["Cleanser", "Serum", "Toner", "Moisturiser"]
    change(world, plain.move_card, item="skincare", where="before", other="brush teeth")
    assert [item.text for item in mine(world).items] == ["Skincare", "Brush teeth", "Floss"]
    with pytest.raises(UserError, match="same list"):
        run(plain.move_card(world.request(), {"item": "serum", "other": "floss"}, frozenset()))


def test_exfoliate_only_on_mondays_and_thursdays_shows_on_those_days_only(world):
    evening(world)
    change(world, plain.items_card, routine="evening", group="skincare", items=["exfoliate"])
    change(world, plain.item_repeat_card, item="exfoliate", repeat="days", weekdays=["mon", "thu"])
    skincare = mine(world).items[2]
    assert skincare.guide_on(world.day) == ("Cleanser", "Toner", "Serum", "Moisturiser", "Exfoliate"), "a Monday"
    assert "Exfoliate" not in skincare.guide_on(world.day + timedelta(days=1)), "a Tuesday"
    change(world, plain.item_repeat_card, item="floss", repeat="weekends")
    assert [item.text for item in mine(world).items_on(world.day)] == ["Brush teeth", "Skincare"], "floss: weekends only"
    change(world, plain.item_repeat_card, item="exfoliate", repeat="daily")
    assert mine(world).items[2].guide[-1].repeat is None, "every day again: its own days go"


def test_make_my_evening_routine_6pm_to_11pm_and_a_nudge(world):
    make(world, routine="evening", items=["floss"])
    proposal = change(world, plain.change_card, routine="evening", **{"from": "6pm", "until": "11pm"})
    assert proposal.lines[1] == "when · any time → 6:00 pm to 11:00 pm"
    change(world, plain.change_card, routine="evening", nudge="end")
    assert mine(world).nudge == rules.NUDGE_END
    with pytest.raises(UserError, match="already like that"):
        run(plain.change_card(world.request(), {"routine": "evening", "nudge": "end"}, frozenset()))


def test_removing_is_a_red_card(world):
    evening(world)
    proposal = run(plain.remove_card(world.request(), {"routine": "evening"}, frozenset()))
    assert proposal.confirm_label == "Remove" and proposal.lines[0] == "**Evening** → removed"
    run(plain.remove_save(world.request(), proposal.data))
    assert run(store.every(world.owner.id)) == [] and run(plain.remove_check(world.request(), proposal.data)) == ""


# --- ticking ---------------------------------------------------------------------------------------------------
def test_one_tick_an_item_a_group_is_one_item_and_a_step_of_it_ticks_the_group(world):
    evening(world)
    assert tick(world, "floss") == "✅ **Floss** · Evening 1/3 · next: Brush teeth"
    assert tick(world, "serum") == "✅ **Skincare** · Evening 2/3 · next: Brush teeth", "a step of a group means its group"
    assert tick(world, "brush teeth") == "✅ **Brush teeth** · Evening done"
    with pytest.raises(UserError, match="Everything"):
        tick(world, "floss")


def test_undo_puts_an_item_back(world):
    evening(world)
    tick(world, "skincare")
    assert run(plain.untick(world.request("undo skincare"), {"items": ["skincare"]}, frozenset())) == "↩️ **Skincare** · not done · Evening 0/3 · next: Brush teeth"


def test_the_done_dropdown_ticks_what_was_picked_and_a_second_pick_does_nothing(world):
    evening(world)
    skincare = mine(world).items[2]
    press = SimpleNamespace(user=world.owner, arg=str(mine(world).id), values=(str(skincare.id),), db=cards.Press.db)
    assert run(plain.on_picked(press)) == "✅ Skincare" and run(plain.on_picked(press)) == "already dealt with"


def test_each_day_starts_afresh_and_a_routine_on_other_days_is_not_there(world):
    evening(world)
    make(world, routine="weekend", items=["long walk"], repeat="weekends")
    tick(world, "floss", routine="evening")
    assert [each.habit.name for each in today(world)] == ["Evening"], "a Monday: the weekend one is not on"
    clock.advance_to(days.at(world.day + timedelta(days=1), time(7, 0)))
    (shown,) = today(world)
    assert shown.done == 0


# --- when a routine matters ------------------------------------------------------------------------------------
def test_its_state_by_its_when(world):
    evening(world)
    (shown,) = today(world)
    assert rules.state(shown, days.at(world.day, time(17, 0))) == rules.NOT_YET
    assert rules.state(shown, days.at(world.day, time(19, 0))) == rules.OPEN
    assert rules.state(shown, days.at(world.day, time(23, 30))) == rules.OVERDUE
    make(world, routine="morning", items=["stretch"], time="7:30am")
    morning = next(each for each in today(world) if each.habit.name == "Morning")
    assert rules.state(morning, days.at(world.day, time(9, 0))) == rules.OPEN, "a time that has come is due, not overdue"
    assert rules.status_of(morning, days.at(world.day, time(9, 0))) == design.DUE


def test_attention_any_time_is_level_4_a_time_is_due_from_then_a_window_only_with_a_nudge(world):
    from tasks import habits

    make(world, routine="reading", items=["read"])
    make(world, routine="morning", items=["stretch"], time="7:30am")
    evening(world)
    early = days.at(world.day, time(7, 0))
    found = {item.what: attention.level(item, early) for item in run(habits.items(world.owner.id, early))}
    assert found == {"Reading routine": attention.LEVEL_USEFUL, "Morning routine": attention.LEVEL_NEXT}
    late = days.at(world.day, time(23, 30))
    found = {item.what: attention.level(item, late) for item in run(habits.items(world.owner.id, late))}
    assert found == {"Reading routine": attention.LEVEL_USEFUL, "Morning routine": attention.LEVEL_DUE}, "the window closed undone: no nudge, nothing"
    change(world, plain.change_card, routine="evening", nudge="end")
    found = {item.what: attention.level(item, late) for item in run(habits.items(world.owner.id, late))}
    assert found["Evening routine not done"] == attention.LEVEL_DUE


# --- the cards (the list rule) ---------------------------------------------------------------------------------
def test_a_routine_still_to_come_has_its_when_and_count_and_no_dropdown(world):
    evening(world)
    (shown,) = today(world)
    pieces = rules.routine_card(shown, days.at(world.day, time(17, 0)))
    assert [line for text in design.texts(pieces) for line in text.splitlines()] == ["### 🔁 Evening ○○○ 0/3", "-# 6:00 pm to 11:00 pm", "-# 3 items"]
    assert design.menus(pieces) == [], "round 4: a control only on what can be done now"



def test_a_routines_card_shows_three_in_full_more_and_one_dropdown(world):
    make(world, routine="long", items=[f"step {each}" for each in range(1, 11)])
    (shown,) = today(world)
    pieces = rules.routine_card(shown, clock.now())
    lines = [line for text in design.texts(pieces) for line in text.splitlines()]
    assert lines[0] == "### 🔁 Long ○○○○○○○○○○ 0/10" and lines[1] == "-# any time"
    assert [line for line in lines if line.startswith("**")] == ["**Step 1**", "**Step 2**", "**Step 3**"] and "-# +7 more" in lines
    (menu,) = design.menus(pieces)
    assert len(menu.options) == 10 and menu.placeholder == "✅ Done: pick one" and design.buttons(pieces) == []
    cards.check_layout(pieces)


def test_a_group_shows_its_steps_for_the_day_as_a_small_guide(world):
    evening(world)
    clock.advance_to(days.at(world.day, time(19, 0)))
    (shown,) = today(world)
    lines = [line for text in design.texts(rules.routine_card(shown, clock.now())) for line in text.splitlines()]
    assert "**Skincare**" in lines and "-# Cleanser → Toner → Serum → Moisturiser" in lines


def test_layout_a_holds_every_routine_with_the_dropdowns_at_the_bottom(world, monkeypatch):
    monkeypatch.setattr(config, "ROUTINES_LAYOUT", "a")
    evening(world)
    make(world, routine="reading", items=["read"])
    tick(world, "read")
    clock.advance_to(days.at(world.day, time(19, 0)))
    shown = run(plain.hub_card(world.owner.id))
    (box,) = shown.layout
    assert box.children[0].content == "### 🔁 Personal routines ●○○○ 1/4"
    assert isinstance(box.children[-1], cards.Select), "the dropdowns at the bottom"
    assert len(design.menus(shown.layout)) == 1, "a finished routine has none"
    cards.check_layout(shown.layout)


def test_group_steps_always_show_in_full_the_first_three_is_items_only(world):
    make(world, routine="long", items=[{"text": "skincare", "steps": [f"step {each}" for each in range(1, 11)]}, "a", "b", "c", "d"])
    (shown,) = today(world)
    lines = [line for text in design.texts(rules.routine_card(shown, clock.now())) for line in text.splitlines()]
    assert "-# " + " → ".join(f"Step {each}" for each in range(1, 11)) in lines, "every step of the group"
    assert [line for line in lines if line.startswith("**")] == ["**Skincare**", "**A**", "**B**"] and "-# +2 more" in lines


# --- layout B (the default): the Today card, and a card a routine from its start ------------------------------
def test_layout_b_is_the_default_and_has_no_one_card(world):
    assert plain.layout_b()
    evening(world)
    assert run(plain.hub_card(world.owner.id)) is None


def test_layout_a_by_setting(world, monkeypatch):
    monkeypatch.setattr(config, "ROUTINES_LAYOUT", "a")
    evening(world)
    assert run(plain.hub_card(world.owner.id)) is not None


def test_a_routines_own_card_from_its_start_until_it_is_done(world):
    evening(world)
    habit_id = mine(world).id
    assert run(plain.own_card(world.owner.id, habit_id)) is None, "7:00 am: its window starts at 6 pm"
    clock.advance_to(days.at(world.day, time(18, 0)))
    shown = run(plain.own_card(world.owner.id, habit_id))
    assert shown is not None and design.texts(shown.layout)[0].startswith("### 🔁 Evening ○○○ 0/3")
    tick(world, "brush teeth", "floss", "skincare")
    assert run(plain.own_card(world.owner.id, habit_id)) is None, "done: tidied away"


def test_each_start_still_to_come_is_booked_once(world, monkeypatch):
    from core import scheduler

    booked = []

    async def add_job(task, kind, due, payload=None, user_id=None, key=None):
        booked.append((task, kind, due, payload, key))
        return len(booked)

    monkeypatch.setattr(scheduler, "add_job", add_job)
    evening(world)
    make(world, routine="reading", items=["read"])
    run(plain.book_starts(world.owner.id))
    ((task, kind, due, payload, key),) = booked
    assert (task, kind, payload) == ("habits", plain.START, {"id": mine_named(world, "Evening").id}) and due == days.at(world.day, time(18, 0))
    assert key == f"h{mine_named(world, 'Evening').id}@{world.day.isoformat()}T18:00", "any time has no start to book"


def mine_named(world, name):
    return next(each for each in run(store.every(world.owner.id)) if each.name == name)


def test_the_briefing_line_has_its_when(world):
    from tasks import habits

    evening(world)
    said = run(habits.summary(world.owner.id, world.day))
    assert (said.done, said.total) == (0, 3) and said.lines == ("**Evening** ○○○ 0/3 · 6:00 pm to 11:00 pm",)


def test_a_routine_made_before_the_rework_keeps_its_days_as_its_repeat():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    store.MIGRATIONS[0](conn)
    conn.execute("INSERT INTO habits_items (user_id, name, weekdays, created_at) VALUES (1, 'Old', '[0, 3]', '2026-10-01')")
    conn.execute("INSERT INTO habits_items (user_id, name, weekdays, created_at) VALUES (1, 'Daily', '[]', '2026-10-01')")
    conn.execute("INSERT INTO habits_steps (user_id, habit_id, position, text) VALUES (1, 1, 0, 'Stretch')")
    store.MIGRATIONS[1](conn)
    old, daily = store.db_all(conn, 1)
    assert old.repeat == recurrence.Repeat(recurrence.DAYS, weekdays=(0, 3)) and daily.repeat == recurrence.EVERY_DAY
    assert old.items[0].kind == rules.STEP and old.when == rules.ANY_TIME


def test_the_week_counts_a_routine_only_from_the_day_it_was_made(world):
    """Found 16 Oct in a day in the hub: routines made on a Saturday were counted 1 of 7 for that week."""
    from tasks import habits

    clock.advance_to(days.at(world.day + timedelta(days=5), time(7, 0)))  # the Saturday
    evening(world)
    week = run(habits.task.week(world.owner.id, world.day, world.day + timedelta(days=6)))
    assert week.total == 2, "Saturday and Sunday only: the days before it was made were never its"
