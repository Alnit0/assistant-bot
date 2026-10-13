"""The attention model (core/attention.py): one ranking, the status line's words, the core's own
items (core/health.py), pills' items, and how far a self-test is on the dev bot's status line."""
import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import actions, attention, config, day, health, scheduler
from core.attention import PROBLEM, TIMED, USEFUL, Item
from tasks.pills import attention as pills_attention
from tests.test_pills_checklist import DAY, add, log, run, world  # noqa: F401

NOW = day.at(DAY, time(11, 0))  # 11:00 am on a Monday


def at(hour, minute=0, on=DAY):
    return day.at(on, time(hour, minute))


# --- the pecking order ------------------------------------------------------------------------------------------------
def test_the_level_of_an_item_follows_its_urgency_its_time_and_the_clock():
    assert attention.level(Item("backup failed", PROBLEM), NOW) == 1
    assert attention.level(Item("a dose is due", TIMED, when=at(10, 30)), NOW) == 2, "its time has come"
    assert attention.level(Item("a dose is due", TIMED, when=NOW), NOW) == 2, "due now"
    assert attention.level(Item("the next dose", TIMED, when=at(12)), NOW) == 3, "later today"
    assert attention.level(Item("doses any time", USEFUL), NOW) == 4 and attention.level(Item("the morning", USEFUL, when=at(6, on=DAY + timedelta(days=1))), NOW) == 4
    assert attention.level(Item("tomorrow's", TIMED, when=at(8, on=DAY + timedelta(days=1))), NOW) is None, "a timed item for another day is not ranked"
    assert attention.level(Item("no time", TIMED), NOW) is None


def test_one_ranking_lower_level_first_and_soonest_first_within_a_level():
    items = [
        Item("morning", USEFUL, short=("6am",), icon="🌅"), Item("next b", TIMED, when=at(15), short=("3pm",)),
        Item("next a", TIMED, when=at(12), short=("2/5", "12pm")), Item("due late", TIMED, when=at(10, 45), short=("due 10:45am",)),
        Item("due early", TIMED, when=at(9), short=("due 9am",)), Item("old problem", PROBLEM, when=at(3)),
        Item("new problem", PROBLEM, when=at(10)), Item("tomorrow", TIMED, when=at(8, on=DAY + timedelta(days=1))),
        Item("progress", USEFUL, short=("2/5",)), Item("a problem with no time", PROBLEM),
    ]
    order = attention.ranked(items, NOW)
    assert [(rank, item.what) for rank, item in order] == [
        (1, "new problem"), (1, "old problem"), (1, "a problem with no time"),
        (2, "due early"), (2, "due late"), (3, "next a"), (3, "next b"), (4, "morning"), (4, "progress"),
    ], "the most recent problem first; what is due soonest first; useful things in the order they were handed in"
    assert attention.top(items, NOW).what == "new problem"
    assert attention.top([item for item in items if item.urgency != PROBLEM], NOW).what == "due early"
    assert attention.top([items[0], items[8], items[7]], NOW).what == "morning", "nothing timed left today: the first useful thing"
    assert attention.top([items[7]], NOW) is None and attention.top([], NOW) is None, "and with none of those, nothing"


def test_the_ranking_changes_by_the_clock_at_the_moment_a_timed_item_falls_due():
    items = [Item("next", TIMED, when=at(12)), Item("later", TIMED, when=at(15)), Item("past", TIMED, when=at(9)), Item("p", PROBLEM, when=at(13))]
    assert attention.next_change(items, NOW) == at(12)
    assert attention.next_change(items, at(15, 1)) is None


# --- the status line's words ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("hour, minute, said", [(12, 0, "12pm"), (6, 0, "6am"), (8, 30, "8:30am"), (0, 5, "12:05am"), (23, 59, "11:59pm"), (13, 0, "1pm")])
def test_a_time_on_the_status_line_is_short_and_on_the_12_hour_clock(hour, minute, said):
    assert attention.short_time(at(hour, minute)) == said


def test_the_status_line_is_the_icon_then_the_short_pieces_and_a_problem_points_at_its_bug():
    assert attention.status_line(Item("the next dose", TIMED, when=at(12), short=("2/5", "12pm"), icon="💊")) == "💊 2/5 · 12pm"
    assert attention.status_line(Item("a dose is due", TIMED, when=at(12), short=("due 12pm",), icon="💊")) == "💊 due 12pm"
    assert attention.status_line(Item("backup failed", PROBLEM, bug="B14", short=("backup failed",))) == "⚠️ B14 · backup failed"
    assert attention.status_line(Item("backup failed", PROBLEM)) == "⚠️ backup failed", "no bug filed: its words"
    assert attention.status_line(Item("the morning routine", USEFUL, short=("6am",), icon="🌅")) == "🌅 6am"
    assert attention.status_line(None) == "" and attention.status_line(Item("Zinc is due", TIMED, when=at(12), icon="💊")) == "", "nothing short to say: blank, never its words (they may name a pill)"
    assert len(attention.status_line(Item("x", PROBLEM, short=("y" * 300,)))) == 128


# --- gathering: tasks through the contract, the core's own parts by registering -----------------------------------
def test_items_are_gathered_from_every_task_that_hands_some_in_and_one_that_fails_is_left_out(monkeypatch):
    async def pills(user_id, now):
        return [Item("the next dose", TIMED, when=at(12), short=("2/5", "12pm"))]

    async def broken(user_id, now):
        raise RuntimeError("boom")

    async def system(user_id, now):
        return [Item("backup failed", PROBLEM, short=("backup failed",)), Item("odd", "no such urgency")]

    def entry(name, icon, provider=None):
        return actions.Entry(name, icon, f"Only for {name}.", ("a", "b"), (), attention=provider, on_repeat="allow_another")

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(attention, "_providers", {})
    actions.set_catalogue([entry("pills", "💊", pills), entry("gym", "🏋️", broken), entry("timers", "⏲️")])
    attention.provide("system", "⚠️", system)
    found = asyncio.run(attention.gather(1, NOW))
    assert [(item.task, item.icon, item.what) for item in found] == [("system", "⚠️", "backup failed"), ("pills", "💊", "the next dose")]
    assert attention.status_line(attention.top(found, NOW)) == "⚠️ backup failed"


def test_whoever_hands_in_items_says_when_they_may_have_changed(monkeypatch):
    told = []
    monkeypatch.setattr(attention, "_listeners", [])
    attention.on_change(lambda: told.append("status line"))
    attention.on_change(lambda: 1 / 0)  # one surface failing never stops the telling
    attention.changed()
    assert told == ["status line"]


def test_the_contract_carries_attention_only_for_a_task_that_hands_some_in():
    from tasks import registry
    from tasks.bugs import task as bugs_task
    from tasks.pills import task as pills_task
    from tasks.schedule import task as schedule_task

    registry.load()
    assert pills_task.entries()[0].attention is not None and bugs_task.entries()[0].attention is not None
    assert schedule_task.entries()[0].attention is None, "a task with nothing to hand in is simply not asked"


# --- pills ---------------------------------------------------------------------------------------------------------------
def _line(world, now):
    world.now = now
    items = run(pills_attention.items(world.owner.id, now))
    return attention.status_line(attention.top([Item(**{**vars(item), "icon": "💊"}) for item in items], now)), items


def test_pills_hand_in_what_is_due_what_is_next_and_what_is_simply_left(world):
    add(world, {"name": "Pill A", "times": ["8:00 am", "12:00 pm"]}, {"name": "Evening pill", "times": ["8:00 pm"]}, {"name": "Zinc"}, {"name": "Iron"})
    assert _line(world, at(7))[0] == "💊 0/5 · 8am", "the next dose with a time, and how far the day is"
    assert _line(world, at(8, 10))[0] == "💊 due 8am", "its time has come"
    log(world, {"pill": "pill a", "did": "taken"})
    log(world, {"pill": "zinc", "did": "taken"})
    assert _line(world, at(8, 20))[0] == "💊 2/5 · 12pm"
    line, items = _line(world, at(12, 30))
    assert line == "💊 due 12pm" and all(item.can_act for item in items)
    log(world, {"pill": "pill a", "did": "taken"})
    world.now = at(20, 5)
    log(world, {"pill": "evening pill", "did": "taken"})
    assert _line(world, at(20, 6))[0] == "💊 4/5", "only a dose with no time is left: useful, not timed"
    log(world, {"pill": "iron", "did": "taken"})
    assert _line(world, at(20, 7)) == ("", []), "everything dealt with: nothing from pills"


def test_no_pill_is_ever_named_in_what_the_status_line_shows(world):
    add(world, {"name": "Secretpill", "times": ["8:00 am"]}, {"name": "Otherone"})
    for now in (at(7), at(9)):
        for item in run(pills_attention.items(world.owner.id, now)):
            assert "Secretpill" not in " ".join(item.short) + item.what and "Otherone" not in " ".join(item.short) + item.what


def test_reading_pills_items_writes_nothing(world):
    from core import database

    add(world, {"name": "Pill A", "times": ["8:00 am"]})

    def counts(conn):
        return conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0], conn.execute("SELECT COUNT(*) FROM occurrence_events").fetchone()[0]

    before = run(database.run(counts))
    run(pills_attention.items(world.owner.id, at(23, 30)))
    run(pills_attention.items(world.owner.id, at(9, on=DAY + timedelta(days=1))))
    assert run(database.run(counts)) == before


# --- the core's own: what is wrong with the bot, and the next morning ------------------------------------------------
def test_a_job_that_did_not_work_is_a_problem_in_a_few_words():
    assert health.job_problem("nightly backup", scheduler.FAILED) == "backup failed"
    assert health.job_problem("pills checklist", scheduler.SKIPPED) == "pills checklist not done"


def test_a_self_test_that_failed_or_did_not_finish_points_at_the_bug_of_its_first_failing_step():
    passed = {"date": "2026-10-13 03:00", "failed": "0", "failed_steps": "", "note": ""}
    failed = {"date": "2026-10-13 03:00", "failed": "2", "failed_steps": "1.07 3.02", "note": ""}
    stopped = {"date": "2026-10-13 03:00", "failed": "0", "failed_steps": "", "note": "did not finish: stopped before the end"}
    assert health.selftest_problem(passed, {}) is None and health.selftest_problem(None, {}) is None
    item = health.selftest_problem(failed, {"3.02": 4, "1.07": 3})
    assert (item.urgency, item.bug, item.short) == (PROBLEM, "D3", ("self-test failed",)) and attention.status_line(item) == "⚠️ D3 · self-test failed"
    assert attention.status_line(health.selftest_problem(failed, {})) == "⚠️ self-test failed", "no bug was filed for it"
    assert attention.status_line(health.selftest_problem(stopped, {})) == "⚠️ self-test did not finish"


def test_live_reads_the_self_test_s_own_files_and_the_dev_bot_never_reports_on_itself(tmp_path, monkeypatch):
    folder = tmp_path / "selftest"
    folder.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    assert asyncio.run(health.selftest(1, NOW)) == [], "no history: nothing to say"
    (folder / "history.csv").write_text("date,commit,ran,steps,passed,failed,failed_steps,spend_usd,claude,seconds,note\n2026-10-12 03:00,a,full,3,3,0,,0,recorded,5,\n2026-10-13 03:00,a,full,3,2,1,1.07,0,recorded,5,\n", encoding="utf-8")
    (folder / "bugs.json").write_text(json.dumps({"1.07": 3}), encoding="utf-8")
    (found,) = asyncio.run(health.selftest(1, NOW))
    assert attention.status_line(found) == "⚠️ D3 · self-test failed", "the latest run is what counts"
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert asyncio.run(health.selftest(1, NOW)) == []


def test_the_bugs_task_hands_in_only_a_bug_with_a_fix_ready_to_retest(monkeypatch):
    from tasks import bugs
    from tasks.bugs import rules, store

    def bug(number, ready):
        return SimpleNamespace(id=number, summary=f"bug {number}", post_url=f"https://discord.test/{number}", fix_ready=ready)

    async def open_items(user_id):
        return [bug(4, False), bug(7, True)]

    monkeypatch.setattr(store, "open_items", open_items)
    (item,) = asyncio.run(bugs.needs_me(1, NOW))
    assert (item.urgency, item.bug, item.short, item.can_act, item.link) == (PROBLEM, rules.bug_id(7), ("retest",), True, "https://discord.test/7")
    assert attention.status_line(item) == f"⚠️ {rules.bug_id(7)} · retest"


# --- quiet hours: a setting, for pings only ---------------------------------------------------------------------------
def test_quiet_hours_are_a_setting_and_ten_to_six_unless_said():
    assert config.QUIET_HOURS == (time(22, 0), time(6, 0))
    assert config.hours("21:30-07:00", (time(22), time(6))) == (time(21, 30), time(7, 0))
    assert config.hours("nonsense", (time(22), time(6))) == (time(22), time(6)) and config.hours(None, (time(22), time(6))) == (time(22), time(6))


# --- how far a self-test is, on the dev bot's status line -----------------------------------------------------------------
def test_the_run_knows_how_many_steps_to_expect_from_the_last_time_each_start_ran(tmp_path, monkeypatch):
    from selftest import __main__ as runner

    monkeypatch.setattr(runner, "STEPS", tmp_path / "steps.json")
    assert runner.steps_known() == {} and runner.steps_expected({}, ["p5", "p6"]) == 0, "never run: the count is shown alone"
    (tmp_path / "steps.json").write_text(json.dumps({"p5": 14, "p6": 10}), encoding="utf-8")
    known = runner.steps_known()
    assert runner.steps_expected(known, ["p5", "p6"]) == 24 and runner.steps_expected(known, ["p4", "p5"]) == 0


def test_the_harness_tells_the_status_line_after_every_step(monkeypatch):
    from core import identity
    from selftest.harness import Harness

    told = []
    monkeypatch.setattr(identity, "set_progress", lambda *given: told.append(given))
    for name, value in (("SELFTEST_DONE", "40"), ("SELFTEST_FAILED", "1"), ("SELFTEST_TOTAL", "103")):
        monkeypatch.setenv(name, value)
    import time as real

    monkeypatch.setenv("SELFTEST_ENDS", str(real.time() + 6 * 60))
    harness = Harness(SimpleNamespace(client=None), "p3", None, claude=False, budget=0.0)
    harness.results = [{"status": "pass"}, {"status": "fail"}]
    harness.tell_progress()
    assert told == [(42, 103, 6, 2)]
    assert identity.selftest_line(*told[0]) == "🧪 42/103 · 6m · ❌2"
    harness.steps_in_all = 41
    assert harness.progress()[:2] == (42, 42), "more steps than last time: the total follows, never 42/41"
