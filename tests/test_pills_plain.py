"""Setting pills up in plain words (tasks/pills/plain.py): the confirm card for each action,
what Save writes, and every word said. Against a temporary database."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, database, day, livelists, timeinput
from core.actions import LiveReply, Request
from core.errors import UserError
from tasks import registry
from tasks.pills import plain, rules, store
from core.schedule import Schedule
from tasks.pills.rules import ACTIVE, PAUSED, REMOVED

HUB = 400


@pytest.fixture
def world(make_db, monkeypatch, owner):
    make_db({"pills": store.MIGRATIONS})
    changed = []
    monkeypatch.setattr(livelists, "changed", lambda user_id, key, render: changed.append((user_id, key)))
    return SimpleNamespace(owner=owner, changed=changed, request=lambda **more: Request(owner, HUB, "said", **more))


def run(coroutine):
    return asyncio.run(coroutine)


def pills(world):
    return run(store.pills(world.owner.id))


def card(world, prepare, *items, guessed=(), previous=None):
    return run(prepare(world.request(previous=previous), {"pills": list(items)}, frozenset(guessed)))


def add(world, *items):
    """Put pills straight in: a card, then Save."""
    proposal = card(world, plain.add_card, *items)
    return run(plain.add_save(world.request(), proposal.data))


# --- pills saved before the one schedule model ------------------------------------------
def test_pills_saved_with_a_kind_of_schedule_come_through_the_migration_unchanged(make_db, owner):
    make_db({"pills": store.MIGRATIONS[:1]})
    old = [
        ("Vitamin D", "untimed", "[]", 1, None),
        ("Evening pill", "fixed", '["20:00"]', 1, None),
        ("Course A", "interval", "[]", 3, 180),
        ("Course B", "interval", '["08:00"]', 3, 90),
    ]

    def insert(conn):
        conn.executemany(
            "INSERT INTO pills_pills (user_id, name, kind, times, per_day, gap_minutes, status, created_at, updated_at) "
            f"VALUES ({owner.id}, ?, ?, ?, ?, ?, 'active', '2026-10-09T00:00:00', '2026-10-09T00:00:00')",
            old,
        )

    run(database.run(insert))
    make_db({"pills": store.MIGRATIONS})
    assert [(pill.plan.name, pill.plan.schedule) for pill in run(store.pills(owner.id))] == [
        ("Vitamin D", Schedule(1)),
        ("Evening pill", Schedule(1, (time(20, 0),))),
        ("Course A", Schedule(3, gap_minutes=180)),
        ("Course B", Schedule(3, (time(8, 0),), gap_minutes=90)),
    ]


# --- the contract ---------------------------------------------------------------------
def test_the_pills_task_meets_the_contract_and_every_change_needs_a_card():
    registry.load()
    entry = actions.entry("pills")
    assert entry is not None and (entry.icon, entry.title) == ("💊", "Pills") and "Not shopping" in entry.only_for
    assert [(action.name, action.needs_card) for action in entry.actions] == [
        ("pill_add", True), ("pill_edit", True), ("pill_pause", True), ("pill_resume", True),
        ("pill_remove", True), ("pill_delete", True), ("pill_list", False),
    ]
    assert actions.problems([entry]) == [] and registry.problems() == []
    for action in entry.actions[:-1]:
        assert action.field("pills").type == actions.ITEMS, "one request can hold several pills"


# --- laying a change over a card (pure) ---------------------------------------------------
def test_a_pill_named_again_keeps_what_it_had_and_takes_what_is_new():
    held = [{"name": "Iron", "times": "08:00", "notes": "with food"}, {"name": "Zinc"}]
    assert plain.overlay(held, [{"name": "iron", "times": "8pm"}], "name") == (
        [{"name": "iron", "times": "8pm", "notes": "with food"}, {"name": "Zinc"}], [],
    )
    assert plain.overlay(held, [{"name": "Magnesium", "per_day": 2}], "name")[0][-1] == {"name": "Magnesium", "per_day": 2}
    assert plain.overlay(held, [{"name": "zinc", "remove": True}, {"name": "copper", "remove": True}], "name") == ([held[0]], ["copper"])


# --- add: guess, show, confirm ---------------------------------------------------------------
def test_a_plain_pill_is_one_line_and_nothing_is_saved_before_save(world):
    proposal = card(world, plain.add_card, {"name": "Vitamin D", "notes": "with food"})
    assert proposal.lines == ("**Vitamin D** · daily, any time · *with food*",) and proposal.kind == "new"
    assert proposal.warnings == () and pills(world) == []
    assert run(plain.add_save(world.request(), proposal.data)) == "✅ Saved · 💊 **Vitamin D** · daily, any time · *with food*"
    (pill,) = pills(world)
    assert (pill.plan.name, pill.plan.schedule, pill.plan.notes) == ("Vitamin D", Schedule(1), "with food")
    assert world.changed == [(world.owner.id, "pills")], "the list on screen is brought up to date"


def test_a_time_that_could_be_morning_or_evening_is_taken_as_morning_and_flagged_never_asked(world):
    proposal = card(world, plain.add_card, {"name": "Iron", "times": "8"})
    assert proposal.lines == ("**Iron** · daily at `8:00 am` ❓",)
    assert proposal.data == {"pills": [{"name": "Iron", "times": "08:00"}], "_last": "Iron"}, "Save applies what the card showed"


def test_a_reply_with_the_time_replaces_the_guess_and_the_flag_goes(world):
    first = card(world, plain.add_card, {"name": "Iron", "times": "8", "notes": "with food"})
    second = card(world, plain.add_card, {"name": "Iron", "times": "8pm"}, previous=first.data)
    assert second.lines == ("**Iron** · daily at `8:00 pm` · *with food*",), "the note said before is kept by the code"
    run(plain.add_save(world.request(), second.data))
    assert pills(world)[0].plan.schedule.times == (time(20, 0),)


def test_a_guess_claude_made_is_flagged_on_that_pills_line_only(world):
    proposal = card(
        world, plain.add_card, {"name": "A", "per_day": 3, "min_gap": "3h"}, {"name": "B"}, guessed=["pills[0].per_day"],
    )
    assert proposal.lines == ("**A** · 3× daily, at least 3h apart, first dose when ready ❓", "**B** · daily, any time")


def test_fixed_times_and_a_course_read_as_the_spec_shows_them(world):
    today = day.today()
    proposal = card(
        world, plain.add_card,
        {"name": "A", "times": "9am, 12pm, 3pm"},
        {"name": "Course A", "per_day": 3, "min_gap": "3h", "notes": "with food", "start": "tomorrow", "days": 7},
    )
    dates = timeinput.format_dates(today + timedelta(days=1), today + timedelta(days=7))
    assert proposal.lines == (
        "**A** · daily at `9:00 am`, `12:00 pm`, `3:00 pm`",
        f"**Course A** · 3× daily, at least 3h apart, first dose when ready · *with food* · {dates}",
    )
    assert run(plain.add_save(world.request(), proposal.data)) == "✅ Saved · 💊 2 pills added: **A**, **Course A**"
    assert [(pill.plan.name, pill.plan.schedule) for pill in pills(world)] == [
        ("A", Schedule(3, (time(9, 0), time(12, 0), time(15, 0)))), ("Course A", Schedule(3, gap_minutes=180)),
    ]


# --- one model: planned times, a gap and a latest time ---------------------------------------------
PILL_A = {"name": "Pill A", "per_day": 3, "times": "8am, 11:30, 3pm", "min_gap": "3h", "latest": "4pm", "notes": "without food"}


def test_pill_a_is_on_the_card_exactly_as_said_and_is_saved_and_read_back(world):
    proposal = card(world, plain.add_card, PILL_A)
    assert proposal.lines == (
        "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm`",
        "At least 3h apart · not after `4:00 pm` · *without food*",
    )
    assert proposal.warnings == () and proposal.guessed == (), "nothing guessed: 11:30 can only be the morning"
    run(plain.add_save(world.request(), proposal.data))
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    assert pills(world)[0].plan.schedule == Schedule(3, (time(8, 0), time(11, 30), time(15, 0)), 180, time(16, 0))
    assert run(plain.show_list(world.request(), {}, frozenset())).text.splitlines()[1] == (
        "💊 **Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm` · at least 3h apart · not after `4:00 pm` · *without food*"
    )


def test_planned_times_closer_than_the_gap_are_moved_with_a_warning_and_save_keeps_the_fix(world):
    proposal = card(world, plain.add_card, {**PILL_A, "times": "8am, 11:30, 2pm"})
    assert proposal.lines[0] == "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `2:30 pm`"
    assert proposal.warnings == ("11:30 am to 2:00 pm is under 3h: the third dose moves to 2:30 pm",)
    run(plain.add_save(world.request(), proposal.data))
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    assert pills(world)[0].plan.schedule.times[2] == time(14, 30)


def test_a_latest_time_that_could_be_morning_or_evening_is_taken_as_the_evening_and_flagged(world):
    proposal = card(world, plain.add_card, {"name": "B", "latest": "4"})
    assert proposal.lines == ("**B** · daily, any time ❓", "Not after `4:00 pm`")
    assert proposal.data["pills"] == [{"name": "B", "latest": "16:00"}], "Save applies what the card showed"


def test_an_edit_adds_a_gap_and_a_latest_time_to_a_pill_with_times(world):
    add(world, {"name": "Pill A", "times": "8am, 11:30am, 3pm"})
    proposal = card(world, plain.edit_card, {"pill": "pill a", "min_gap": "3h", "latest": "4pm"})
    assert proposal.lines[1] == (
        "schedule · daily at `8:00 am`, `11:30 am`, `3:00 pm` → "
        "3× daily · `8:00 am`, `11:30 am`, `3:00 pm` · at least 3h apart · not after `4:00 pm`"
    )
    run(plain.edit_save(world.request(), proposal.data))
    assert run(plain.edit_check(world.request(), proposal.data)) == ""
    assert pills(world)[0].plan.schedule == Schedule(3, (time(8, 0), time(11, 30), time(15, 0)), 180, time(16, 0))


def test_another_pill_said_after_the_card_joins_it_and_one_can_be_taken_off(world):
    first = card(world, plain.add_card, {"name": "Iron"})
    both = card(world, plain.add_card, {"name": "Zinc", "per_day": 2}, previous=first.data)
    assert both.lines == ("**Iron** · daily, any time", "**Zinc** · 2× daily, any time")
    one = card(world, plain.add_card, {"name": "iron", "remove": True}, previous=both.data)
    assert one.lines == ("**Zinc** · 2× daily, any time",)
    off = card(world, plain.add_card, {"name": "copper", "remove": True}, previous=one.data)
    assert off.warnings == ("copper isn't on the card: nothing to take off",)


def test_a_pill_that_cannot_be_a_plan_is_named_on_the_card_and_the_rest_stay(world):
    add(world, {"name": "Iron"})
    proposal = card(world, plain.add_card, {"name": "Zinc"}, {"name": "iron"}, {"name": "X", "times": "8am", "per_day": 3})
    assert proposal.lines == ("**Zinc** · daily, any time",)
    assert proposal.warnings[0].startswith("Not included: iron (There is already a pill called **Iron**")
    assert proposal.warnings[1].startswith("Not included: X (That is 1 time for 3 doses a day")


def test_when_no_pill_can_be_a_plan_the_reason_is_said_and_there_is_no_card(world):
    with pytest.raises(UserError, match=r"X \(A minimum gap needs at least 2 doses a day\.\)"):
        card(world, plain.add_card, {"name": "X", "min_gap": "3h", "per_day": 1})


def test_a_name_taken_between_the_card_and_save_is_refused_at_save(world):
    proposal = card(world, plain.add_card, {"name": "Iron"})
    add(world, {"name": "Iron"})
    with pytest.raises(UserError, match="already a pill called"):
        run(plain.add_save(world.request(), proposal.data))
    assert len(pills(world)) == 1


# --- edit --------------------------------------------------------------------------------------
def test_an_edit_shows_now_and_new_and_save_changes_only_what_was_said(world):
    add(world, {"name": "Evening pill", "times": "8pm", "notes": "with food"})
    proposal = card(world, plain.edit_card, {"pill": "evening pill", "times": "9pm"})
    assert proposal.lines == (
        "**Evening pill**",
        "schedule · daily at `8:00 pm` → daily at `9:00 pm`",
        "-# Applies from the next dose. What is already recorded stays as it is.",
    ) and proposal.kind == "change", "one format for an edit: field · old → new, and only what changes"
    assert pills(world)[0].plan.schedule.times == (time(20, 0),), "nothing until Save"
    assert run(plain.edit_save(world.request(), proposal.data)) == "✅ Updated · 💊 **Evening pill** · daily at `9:00 pm` · *with food*"
    assert pills(world)[0].plan.schedule.times == (time(21, 0),) and pills(world)[0].plan.notes == "with food"


def test_an_edit_by_id_a_rename_and_taking_a_note_away(world):
    add(world, {"name": "Iron", "notes": "with food"})
    (pill,) = pills(world)
    proposal = card(world, plain.edit_card, {"pill": pill.ref, "name": "Iron II", "notes": "none"})
    assert proposal.lines[:3] == ("**Iron**", "name · Iron → Iron II", "notes · with food → none")
    run(plain.edit_save(world.request(), proposal.data))
    assert (pills(world)[0].plan.name, pills(world)[0].plan.notes) == ("Iron II", "")


def test_an_edit_with_an_unclear_time_is_guessed_and_flagged_and_a_reply_settles_it(world):
    add(world, {"name": "Iron", "times": "8am"})
    first = card(world, plain.edit_card, {"pill": "iron", "times": "9"})
    assert first.lines[1] == "schedule · daily at `8:00 am` → daily at `9:00 am` ❓"
    second = card(world, plain.edit_card, {"pill": "iron", "times": "9pm"}, previous=first.data)
    assert second.lines[1] == "schedule · daily at `8:00 am` → daily at `9:00 pm`"


def test_an_edit_that_changes_nothing_or_names_no_pill_says_so(world):
    add(world, {"name": "Iron", "times": "8am"})
    with pytest.raises(UserError, match="Iron: nothing would change"):
        card(world, plain.edit_card, {"pill": "iron", "times": "8am"})
    with pytest.raises(UserError, match="I don't have a pill called “zinc”"):
        card(world, plain.edit_card, {"pill": "zinc", "times": "8am"})


# --- pause, resume, remove, delete -------------------------------------------------------------------
def test_a_pause_is_a_card_and_save_pauses_until_the_day_said(world):
    add(world, {"name": "Iron"}, {"name": "Zinc"})
    proposal = card(world, plain.pause_card, {"pill": "iron", "until": "tomorrow"}, {"pill": "zinc"})
    tomorrow = day.today() + timedelta(days=1)
    assert proposal.lines == (
        f"**Iron** · active → paused until {timeinput.format_date(tomorrow)}",
        "**Zinc** · active → paused until you resume it",
        "-# It won't be asked for while paused, and its streak is unaffected.",
    ) and proposal.kind == "change"
    assert all(pill.status == ACTIVE for pill in pills(world)), "nothing until Save"
    assert run(plain.pause_save(world.request(), proposal.data)) == f"⏸️ **Iron** paused until {timeinput.format_date(tomorrow)}, **Zinc** paused."
    assert [(pill.plan.name, pill.status, pill.paused_until) for pill in pills(world)] == [("Iron", PAUSED, tomorrow), ("Zinc", PAUSED, None)]


def test_a_pause_that_would_end_today_is_named_and_left_out(world):
    add(world, {"name": "Iron"})
    with pytest.raises(UserError, match=r"Iron \(a pause ends on a later day than today\)"):
        card(world, plain.pause_card, {"pill": "iron", "until": "today"})


def test_resume_is_a_card_for_the_paused_ones_only(world):
    add(world, {"name": "Iron"}, {"name": "Zinc"})
    run(plain.pause_save(world.request(), {"pills": [{"pill": "iron"}]}))
    proposal = card(world, plain.resume_card, {"pill": "iron"}, {"pill": "zinc"})
    assert proposal.lines == ("**Iron** · paused → active",) and proposal.warnings == ("Zinc isn't paused",) and proposal.kind == "change"
    assert run(plain.resume_save(world.request(), proposal.data)) == "▶️ **Iron** resumed."
    assert all(pill.status == ACTIVE for pill in pills(world))


def test_remove_keeps_the_history_and_says_so_on_the_card(world):
    add(world, {"name": "Iron"})
    proposal = card(world, plain.remove_card, {"pill": "iron"})
    assert proposal.lines == ("**Iron** · daily, any time → removed", "-# This stops its reminders. Its history is kept.")
    assert (proposal.kind, proposal.confirm_label, proposal.destructive) == ("remove", "Remove", False)
    assert run(plain.remove_save(world.request(), proposal.data)) == "🗑️ Removed **Iron**. Its history is kept."
    assert pills(world) == [] and run(store.pill(1)).status == REMOVED


def test_delete_is_a_card_of_its_own_kind_that_cannot_be_undone(world):
    add(world, {"name": "Iron"})
    proposal = card(world, plain.delete_card, {"pill": "iron"})
    assert (proposal.kind, proposal.destructive, proposal.confirm_label) == ("remove", True, "Delete for good")
    assert proposal.warnings == ("This deletes the history too and can't be undone",)
    assert run(plain.delete_save(world.request(), proposal.data)) == "🗑️ Deleted **Iron** and its history."
    assert run(store.pill(1)) is None


def test_a_guess_at_which_pill_is_flagged_on_its_line(world):
    add(world, {"name": "Iron"}, {"name": "Zinc"})
    proposal = card(world, plain.remove_card, {"pill": "iron"}, {"pill": "zinc"}, guessed=["pills[1].pill"])
    assert proposal.lines[:2] == ("**Iron** · daily, any time → removed", "**Zinc** · daily, any time → removed ❓")


def test_a_pill_can_be_taken_off_a_remove_card_by_a_reply(world):
    add(world, {"name": "Iron"}, {"name": "Zinc"})
    first = card(world, plain.remove_card, {"pill": "iron"}, {"pill": "zinc"})
    second = card(world, plain.remove_card, {"pill": "zinc", "remove": True}, previous=first.data)
    assert second.data == {"pills": [{"pill": "pl1"}]}


# --- the list, and what extraction is told ------------------------------------------------------------------
def test_the_list_is_read_only_and_live(world):
    add(world, {"name": "Iron", "times": "8am"})
    shown = run(plain.show_list(world.request(), {}, frozenset()))
    assert shown == LiveReply("pills", "## 💊 Pills\n💊 **Iron** · daily at `8:00 am`")


def test_the_state_has_a_line_a_pill_with_its_id_and_what_it_is_today(world):
    add(world, {"name": "Iron", "times": "8am"}, {"name": "Zinc"})
    run(plain.pause_save(world.request(), {"pills": [{"pill": "zinc"}]}))
    state = run(plain.state(world.request()))
    assert state.heading == "The user's pills now (use the id, or the name)"
    assert state.lines == ("pl1: 💊 Iron · daily at 8:00 am [active]", "pl2: ⏸️ Zinc · daily, any time · paused [paused]")
    assert actions.shown_state(run(plain.state(SimpleNamespace(user=SimpleNamespace(id=99)))), "x")[0] == (
        "The user's pills now (use the id, or the name): none yet"
    )


def test_a_time_the_code_guessed_is_kept_with_the_card_as_a_guess(world):
    # Seen in the live eval on 2026-10-10: with the card showing 08:00 as if it had been
    # said, "8pm" came back as two doses, "08:00, 8pm"
    proposal = card(world, plain.add_card, {"name": "Zinc"}, {"name": "Iron", "times": "8"})
    assert proposal.guessed == ("pills[1].times",)
    assert card(world, plain.add_card, {"name": "Iron", "times": "8am"}).guessed == ()
    add(world, {"name": "Evening", "times": "8pm"})
    assert card(world, plain.edit_card, {"pill": "evening", "times": "9"}).guessed == ("pills[0].times",)


# --- QA 2026-10-10: read back, references, and one format for an edit ---------------------------------
def test_every_pill_change_is_read_back_before_it_is_confirmed(world, monkeypatch):
    add(world, {"name": "Iron", "times": "8am"}, {"name": "Zinc"})
    request = world.request()
    assert run(plain.add_check(request, {"pills": [{"name": "Iron", "times": "08:00"}, {"name": "Zinc"}]})) == ""
    assert run(plain.add_check(request, {"pills": [{"name": "Copper"}, {"name": "Iron", "times": "9pm"}]})) == (
        "Copper is not among your pills; Iron was saved as Iron · daily at 8:00 am"
    )
    assert run(plain.edit_check(request, {"pills": [{"pill": "pl1", "times": "9pm"}]})) == "Iron is still Iron · daily at 8:00 am"
    run(plain.edit_save(request, {"pills": [{"pill": "pl1", "times": "9pm"}]}))
    assert run(plain.edit_check(request, {"pills": [{"pill": "pl1", "times": "9pm"}]})) == ""

    assert run(plain.pause_check(request, {"pills": [{"pill": "pl2"}]})) == "Zinc is still active"
    run(plain.pause_save(request, {"pills": [{"pill": "pl2"}]}))
    assert run(plain.pause_check(request, {"pills": [{"pill": "pl2"}]})) == ""
    assert run(plain.resume_check(request, {"pills": [{"pill": "pl2"}]})) == "Zinc is still paused"
    assert run(plain.remove_check(request, {"pills": [{"pill": "pl2"}]})) == "Zinc is still paused"


def test_delete_is_only_confirmed_once_the_pill_is_really_gone(world, monkeypatch):
    # QA 2026-10-10: "Delete for good" has to be true before it is said
    add(world, {"name": "Zinc"})
    request = world.request()
    assert run(plain.delete_check(request, {"pills": [{"pill": "pl1"}]})) == "pl1 is still there"
    run(plain.delete_save(request, {"pills": [{"pill": "pl1"}]}))
    assert run(plain.delete_check(request, {"pills": [{"pill": "pl1"}]})) == "" and run(store.pill(1)) is None
    assert all(action.verify is not None for action in plain.ACTIONS if action.apply is not None)


def test_it_on_a_pills_card_is_the_pill_mentioned_last(world):
    first = card(world, plain.add_card, {"name": "Iron"}, {"name": "Zinc"})
    assert first.data["_last"] == "Zinc"
    second = card(world, plain.add_card, {"name": "@that", "per_day": 2}, previous=first.data)
    assert second.lines == ("**Iron** · daily, any time", "**Zinc** · 2× daily, any time")


def test_it_with_no_card_is_the_pill_changed_last_and_that_is_flagged(world):
    add(world, {"name": "Iron"}, {"name": "Zinc"})
    run(plain.edit_save(world.request(), {"pills": [{"pill": "pl1", "notes": "with food"}]}))
    proposal = card(world, plain.pause_card, {"pill": "@that"})
    assert proposal.lines[0] == "**Iron** · active → paused until you resume it ❓"
    assert proposal.data["pills"] == [{"pill": "pl1"}]


def test_a_new_pill_cannot_be_it(world):
    with pytest.raises(UserError, match="I can't tell what “it” is"):
        card(world, plain.add_card, {"name": "@that", "times": "8am"})


def test_a_pill_sent_back_with_the_card_changes_nothing(world):
    # Seen in the live eval on 2026-10-10: "and zinc once a day" came back with the card's iron as well
    first = card(world, plain.add_card, {"name": "Iron", "times": "8am"})
    second = card(world, plain.add_card, {"name": "Iron", "times": "08:00"}, {"name": "Zinc", "per_day": 1}, previous=first.data)
    assert second.lines == ("**Iron** · daily at `8:00 am`", "**Zinc** · daily, any time")


def test_an_edit_lists_each_field_that_changes_as_old_to_new():
    old = rules.Plan("Iron", "1 tablet", "", Schedule(1, (time(8, 0),)))
    new = rules.Plan("Iron", "2 tablets", "with food", Schedule(2, (time(8, 0), time(20, 0))))
    assert rules.differences(old, new) == [
        ("dose", "1 tablet", "2 tablets"),
        ("notes", "none", "with food"),
        ("schedule", "daily at `8:00 am`", "daily at `8:00 am`, `8:00 pm`"),
    ]
    assert rules.differences(old, old) == []
    gap = rules.Plan("A", schedule=Schedule(3, gap_minutes=180))
    timed = rules.Plan("A", schedule=Schedule(3, (time(9, 0),), 180))
    assert rules.differences(gap, timed) == [
        ("schedule", "3× daily, at least 3h apart, first dose when ready", "3× daily, at least 3h apart, first dose at `9:00 am`"),
    ]
