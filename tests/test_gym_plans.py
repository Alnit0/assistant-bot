"""The gym's plans, a version a logbook imported (Alex, 19 Oct; tasks/gym/plans.py): named "2026-10-19 —
Upper/Lower 4-week" (the day, the split Claude read, the weeks Python counted), the new one active and the one
before kept; a JSON copy of each in data/gym/plans; listing, switching ("the October plan", "the previous plan",
"the upper lower one") and deleting, each change a card; the log never touched, each session keeping the plan
active then. Made-up logbooks (tests/gym_files.py)."""
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from core import config, database
from core.errors import UserError
from tasks.gym import plain, plans, store
from tests import gym_files
from tests.test_gym import imported, run, world  # noqa: F401

UTC = timezone.utc


def made_up(plan_id, name, day, active=False):
    return plans.Plan(plan_id, 1, name, datetime(day.year, day.month, day.day, 1, tzinfo=UTC), active)


# --- pure --------------------------------------------------------------------------------------------------------------
def test_a_plan_is_named_by_the_day_the_split_and_the_weeks():
    assert plans.plan_name(date(2026, 10, 19), "Upper/Lower", 4) == "2026-10-19 — Upper/Lower 4-week"
    assert plans.plan_name(date(2026, 11, 15), "Push/Pull/Legs", 6) == "2026-11-15 — Push/Pull/Legs 6-week"
    assert plans.plan_name(date(2026, 10, 19), "Full Body 3-day", None) == "2026-10-19 — Full Body 3-day"


def test_the_weeks_are_the_logbook_s_own_week_numbers_else_the_span_of_its_sessions():
    assert plans.weeks_of(["1", "2", "Week 4", "3"], []) == 4
    assert plans.weeks_of([], [date(2026, 9, 1), date(2026, 9, 22)]) == 4, "22 days: 4 weeks, rounded up"
    assert plans.weeks_of([], [date(2026, 9, 1)]) == 1 and plans.weeks_of([], []) is None


def test_a_plan_kept_before_has_its_split_from_its_workouts_names():
    assert plans.split_of(["Upper 1", "Lower 1", "Upper 2", "Lower 2"]) == "Upper/Lower"
    assert plans.split_of(["Push", "Pull", "Legs"]) == "Push/Pull/Legs"
    assert plans.split_of(["Full Body A", "Full Body B"]) == "Full Body 2-day"


def test_a_plan_is_found_by_its_month_its_split_or_its_day_and_the_previous_one():
    october = made_up(1, "2026-10-19 — Upper/Lower 4-week", date(2026, 10, 19))
    november = made_up(2, "2026-11-15 — Push/Pull/Legs 6-week", date(2026, 11, 15), active=True)
    every = [november, october]
    assert plans.matches(every, "the October plan") == [october]
    assert plans.matches(every, "use the upper lower one") == [october]
    assert plans.matches(every, "push pull legs") == [november]
    assert plans.matches(every, "2026-11-15") == [november]
    assert plans.matches(every, "the blue one") == [], "nothing fits: said, never a guess"
    assert plans.previous_of(every) == october


def test_the_confirmation_says_the_name_the_exercises_the_days_and_the_weeks():
    assert plans.active_line("2026-10-19 — Upper/Lower 4-week") == "✅ 2026-10-19 — Upper/Lower 4-week is now your active plan."
    assert plans.summary_line(24, 4, 4) == "24 exercises across 4 days, 4 weeks."


# --- importing: a version each time -----------------------------------------------------------------------------------
def kept(world):
    return run(plans.every(world.owner.id))


def test_each_import_is_a_plan_of_its_own_the_new_one_active(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    second, first = kept(world)
    assert second.active and not first.active and second.uploaded >= first.uploaded
    assert first.name.endswith(" — Upper/Lower 2-week") and first.name.startswith(world.today.isoformat())
    assert [each.name for each in run(store.plan(world.owner.id))] == ["Push", "Pull"], "the active plan's workouts"


def test_the_same_logbook_sent_again_is_not_logged_twice(world):
    imported(world)
    before = len(run(database.run(store.db_sessions, world.owner.id)))
    imported(world)
    assert len(run(database.run(store.db_sessions, world.owner.id))) == before and len(kept(world)) == 2


def test_each_plan_has_a_json_copy_in_data_gym_plans(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    folder = plans.folder()
    assert folder == config.DATA_DIR / "gym" / "plans"
    files = sorted(each.name for each in folder.iterdir())
    assert files == [f"{world.today.isoformat()}-2.json", f"{world.today.isoformat()}.json"], "a second on the same day is -2"
    first = json.loads((folder / f"{world.today.isoformat()}.json").read_text(encoding="utf-8"))
    assert set(first) == {"name", "uploaded", "active", "exercises"} and first["active"] is False
    assert first["exercises"][0]["workout"] == "Upper 1" and first["exercises"][0]["name"] and first["exercises"][0]["sets"]
    assert json.loads((folder / f"{world.today.isoformat()}-2.json").read_text(encoding="utf-8"))["active"] is True


# --- list, switch, delete ------------------------------------------------------------------------------------------------
def test_the_list_is_most_recent_first_with_the_active_one_marked(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    said = run(plans.list_said(world.request("show my gym plans"), {}, frozenset())).splitlines()
    assert said[0] == "🏋️ **Your gym plans** · 2"
    assert said[1].endswith("· ✅ active") and "Push" in said[1] and "Upper/Lower" in said[2] and "active" not in said[2]


def test_switching_back_is_a_card_and_the_log_stays_as_it_is(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    sessions = run(database.run(store.db_sessions, world.owner.id))
    card = run(plans.switch_card(world.request("go back to the previous plan"), {"previous": True}, frozenset()))
    assert card.kind == "change" and card.lines[0].endswith("Upper/Lower 2-week** → active")
    said = run(plans.switch_save(world.request(), card.data))
    assert said.splitlines()[0].endswith(" — Upper/Lower 2-week is now your active plan.") and said.splitlines()[1].endswith("across 4 days, 2 weeks.")
    assert run(plans.switch_check(world.request(), card.data)) == ""
    assert [each.name for each in run(store.plan(world.owner.id))][0] == "Upper 1", "its workouts, the rotation from its first"
    assert run(database.run(store.db_sessions, world.owner.id)) == sessions, "the log is never touched"
    with pytest.raises(UserError, match="active plan already"):
        run(plans.switch_card(world.request(), {"plan": "upper lower"}, frozenset()))


def test_a_name_that_fits_two_plans_asks_which(world):
    imported(world)
    imported(world)
    card = run(plans.switch_card(world.request(), {"plan": "upper lower"}, frozenset()))
    assert card.question is not None and len(card.question.choices) == 2


def test_deleting_the_active_plan_makes_the_most_recent_left_active_and_takes_its_file(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    card = run(plans.delete_card(world.request(), {"plan": "push"}, frozenset()))
    assert card.kind == "remove" and "becomes active" in card.lines[-1]
    said = run(plans.delete_save(world.request(), card.data))
    assert said.startswith("🗑️ Deleted **") and "active: **" in said and run(plans.delete_check(world.request(), card.data)) == ""
    (left,) = kept(world)
    assert left.active and not (plans.folder() / f"{world.today.isoformat()}-2.json").exists()
    last = run(plans.delete_card(world.request(), {"plan": "upper"}, frozenset()))
    assert "no plan will be active" in last.lines[-1]
    run(plans.delete_save(world.request(), last.data))
    assert kept(world) == [] and run(store.plan(world.owner.id)) == []
    assert run(database.run(store.db_sessions, world.owner.id)), "the log stays"


def test_each_session_keeps_the_plan_active_when_it_was_logged(world):
    imported(world)
    first = kept(world)[0].id
    imported(world, gym_files.wide_csv(), "wide.csv")
    second = kept(world)[0].id
    rows = run(database.run(lambda conn: conn.execute("SELECT DISTINCT plan_id FROM gym_sessions ORDER BY plan_id").fetchall()))
    assert [row[0] for row in rows] == [first, second]


# --- the plan kept before 19 Oct ----------------------------------------------------------------------------------------
def test_the_plan_kept_before_becomes_the_first_with_its_sessions():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    for step in store.MIGRATIONS[:-1]:
        step(conn)
    for position, name in enumerate(("Upper 1", "Lower 1")):
        conn.execute("INSERT INTO gym_workouts (user_id, name, position) VALUES (1, ?, ?)", (name, position))
    for day in ("2026-09-01", "2026-09-15"):
        conn.execute("INSERT INTO gym_sessions (user_id, name, day, status, source, started_at) VALUES (1, 'Upper 1', ?, 'finished', 'import', 'x')", (day,))
    store.MIGRATIONS[-1](conn)
    (plan,) = plans.db_plans(conn, 1)
    assert plan.active and plan.name.endswith(" — Upper/Lower 3-week")
    assert [each.name for each in store.db_plan(conn, 1)] == ["Upper 1", "Lower 1"]
    assert {row[0] for row in conn.execute("SELECT plan_id FROM gym_sessions")} == {plan.id}


# --- none named (live, 19 Oct: "Delete the gym plan" was declined) ----------------------------------------------------------
def test_delete_the_gym_plan_with_none_named_is_the_active_one(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    card = run(plans.delete_card(world.request("delete the gym plan"), {}, frozenset()))
    assert card.kind == "remove" and "Push/Pull" in card.lines[0] and card.confirm_label == "Delete"


def test_switch_plans_with_none_named_is_the_other_one_or_asks_which(world):
    imported(world)
    imported(world, gym_files.wide_csv(), "wide.csv")
    card = run(plans.switch_card(world.request("switch plans"), {}, frozenset()))
    assert card.question is None and "Upper/Lower" in card.lines[0]
    imported(world)
    asked = run(plans.switch_card(world.request("switch plans"), {}, frozenset()))
    assert asked.question is not None and len(asked.question.choices) == 2
    picked = asked.question.choices[0].data
    assert run(plans.switch_card(world.request(), picked, frozenset())).question is None, "an answer names its plan by id"
