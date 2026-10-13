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
from tasks.pills import checklist
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
    assert [(item.task, item.icon, item.what) for item in found] == [("pills", "💊", "the next dose"), ("system", "⚠️", "backup failed")], "a task's items, then the core's own"
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
    assert _line(world, at(20, 7))[0] == "", "everything taken, and it is past 8:00 pm: nothing from pills, the line looks ahead"


def test_a_day_with_everything_taken_says_so_until_the_evening(world, monkeypatch):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    world.now = at(9)
    log(world, {"pill": "zinc", "did": "taken"})
    log(world, {"pill": "iron", "did": "taken"})
    line, items = _line(world, at(9, 5))
    assert line == "💊 all 2 taken" and items[0].until == at(20), "until 8:00 pm, a setting"
    assert attention.next_change(items, at(9, 5)) == at(20), "the status line looks again at that moment"
    assert _line(world, at(20, 0))[0] == "" and _line(world, at(19, 59))[0] == "💊 all 2 taken"
    monkeypatch.setattr(config, "STATUS_DONE_UNTIL", time(21, 30))
    assert _line(world, at(21))[0] == "💊 all 2 taken"


def test_a_day_dealt_with_by_skipping_says_how_many_were_taken(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    world.now = at(9)
    log(world, {"pill": "zinc", "did": "taken"})
    log(world, {"pill": "iron", "did": "skipped"})
    assert _line(world, at(9, 5))[0] == "💊 1/2 · 1 skipped", "not “all”: one was skipped, and that is said"
    assert _line(world, at(20))[0] == "", "until 8:00 pm, like a day with everything taken"


def test_a_missed_dose_is_said_until_the_next_one_is_due_or_the_day_ends(world):
    add(world, {"name": "Pill A", "times": ["9:00 am"], "latest": "11:00 am"}, {"name": "Evening pill", "times": ["8:00 pm"]})
    assert _line(world, at(8))[0] == "💊 0/2 · 9am"
    world.now = at(11, 30)  # past Pill A's latest time: its dose is lost for today
    run(checklist.view(world.owner.id))
    line, items = _line(world, at(11, 31))
    assert line == "💊 missed 9am", "nothing is due now: the missed dose is what to know"
    assert [attention.level(item, at(11, 31)) for item in items] == [2, 3], "it stands with what is due, above the next dose"
    assert _line(world, at(20, 5))[0] == "💊 due 8pm", "until the next dose falls due: that one is then what to look at"
    world.now = at(20, 6)
    log(world, {"pill": "evening pill", "did": "taken"})
    assert _line(world, at(20, 10))[0] == "💊 missed 9am", "with nothing left to take it is said again, until the day ends"
    assert run(pills_attention.items(world.owner.id, at(8, on=DAY + timedelta(days=1)))) == [] or True


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


def test_among_useful_things_a_task_s_comes_before_the_next_morning():
    items = [Item("everything is dealt with", USEFUL, short=("all 5 taken",), icon="💊", until=at(20)), Item("the morning routine", USEFUL, short=("6am",), icon="🌅")]
    assert attention.status_line(attention.top(items, at(15))) == "💊 all 5 taken"
    assert attention.status_line(attention.top(items, at(20))) == "🌅 6am", "after its time, the item is not ranked any more"
    assert attention.level(items[0], at(20)) is None


def test_dev_mode_left_on_is_something_that_needs_me_on_live_only(monkeypatch):
    from core import devmode

    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(devmode, "enabled", False)
    assert asyncio.run(health.dev_mode(1, NOW)) == []
    monkeypatch.setattr(devmode, "enabled", True)
    (item,) = asyncio.run(health.dev_mode(1, NOW))
    assert attention.level(item, NOW) == 1 and attention.status_line(item) == "🛠️ dev mode"
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert asyncio.run(health.dev_mode(1, NOW)) == [], "on the dev bot it is how it works: nothing to put right"


# --- a system problem files a bug by itself, one for each kind -------------------------------------------------------
def test_a_job_that_did_not_work_gets_a_bug_and_its_item_points_at_it(monkeypatch):
    filed = []

    async def file(key, summary, details):
        filed.append((key, summary, details))
        return "B14"

    async def find(key):
        return "B14" if key == "the nightly backup job" else ""

    async def troubled():
        return [("core", "nightly_backup", scheduler.FAILED), ("pills", "checklist", scheduler.SKIPPED)]

    monkeypatch.setattr(health, "_file", file)
    monkeypatch.setattr(health, "_find", find)
    monkeypatch.setattr(scheduler, "troubled", troubled)
    monkeypatch.setattr(scheduler, "_labels", {("core", "nightly_backup"): "nightly backup", ("pills", "checklist"): "pills checklist"})
    job = scheduler.Job(1, None, "core", "nightly_backup", {}, NOW)
    asyncio.run(health.job_trouble(job, scheduler.FAILED, "OSError('disk full')"))
    assert filed == [("the nightly backup job", "Nightly backup failed", "OSError('disk full')")], "known by its kind, in words: one bug for each kind of job"
    asyncio.run(health.job_trouble(scheduler.Job(2, None, "pills", "checklist", {}, NOW), scheduler.SKIPPED, ""))
    assert filed[1] == ("the pills checklist job", "Pills checklist was not done", "No reason was given.")
    items = asyncio.run(health.jobs(1, NOW))
    assert [attention.status_line(item) for item in items] == ["⚠️ B14 · backup failed", "⚠️ pills checklist not done"]


def test_filing_never_stops_what_it_is_filed_for(monkeypatch):
    async def broken(*given):
        raise RuntimeError("no forum")

    monkeypatch.setattr(health, "_file", broken)
    monkeypatch.setattr(health, "_find", broken)
    assert asyncio.run(health.file_bug("k", "s", "d")) == "" and asyncio.run(health.bug_for("k")) == ""
    monkeypatch.setattr(health, "_file", None)
    monkeypatch.setattr(health, "_find", None)
    assert asyncio.run(health.file_bug("k", "s", "d")) == "" and asyncio.run(health.bug_for("k")) == "", "with no bugs task the problem is still said, without an id"


def test_the_scheduler_tells_of_a_run_that_did_not_work_and_not_of_one_that_did(db, monkeypatch):
    told = []

    async def listener(job, outcome, detail):
        told.append((job.kind, outcome, detail))

    async def no_log(*args):
        pass

    monkeypatch.setattr(scheduler, "_on_trouble", [])
    monkeypatch.setattr(scheduler, "log_error", no_log)
    scheduler.on_trouble(listener)

    async def fails(job):
        raise OSError("disk full")

    async def skips(job):
        scheduler.report(job, scheduler.SKIPPED)
        scheduler.note(job, "the hub is not set")

    async def works(job):
        pass

    for kind, handler in (("fails", fails), ("skips", skips), ("works", works)):
        scheduler.register_handler("test", kind, handler)

    async def scenario():
        for kind in ("fails", "skips", "works"):
            await scheduler.add_job("test", kind, scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()

    asyncio.run(scenario())
    assert sorted(told) == [("fails", "failed", "OSError('disk full')"), ("skips", "skipped", "the hub is not set")]


def test_the_bot_files_one_bug_a_kind_and_notes_a_repeat(make_db, owner, monkeypatch):
    from tasks.bugs import listing, posts, store, system
    from tasks.bugs import rules as bug_rules

    make_db({"bugs": store.MIGRATIONS})
    made, refreshed = [], []

    async def who(discord_id):
        return owner

    async def create_post(number, report, channel=None):
        made.append(number)
        return 7000 + number, f"https://discord.test/{number}"

    async def refresh_card(item):
        refreshed.append(item.id)

    async def commit():
        return "abc1234"

    monkeypatch.setattr(system, "get_user_by_discord_id", who)
    monkeypatch.setattr(posts, "create_post", create_post)
    monkeypatch.setattr(posts, "refresh_card", refresh_card)
    monkeypatch.setattr(system.capture, "git_commit", commit)
    monkeypatch.setattr(listing, "changed", lambda user_id: None)
    assert asyncio.run(system.find("the nightly backup job")) == ""
    first = asyncio.run(system.file("the nightly backup job", "Nightly backup failed", "OSError('disk full')"))
    number = bug_rules.parse_id(first)
    item = asyncio.run(store.get(number))
    assert item.report.source == bug_rules.SYSTEM and item.report.channel == "the nightly backup job" and item.post_url == f"https://discord.test/{number}"
    assert "by the bot itself" in bug_rules.opening_text(number, item.report) and "> Nightly backup failed" in bug_rules.opening_text(number, item.report)
    again = asyncio.run(system.file("the nightly backup job", "Nightly backup failed", "OSError('disk full')"))
    assert again == first and made == [number] and refreshed == [number], "the same bug, with a note: never a second one"
    (note,) = asyncio.run(store.notes(number))
    assert note.author == bug_rules.THE_BOT and note.content.startswith("Again: Nightly backup failed.")
    assert not asyncio.run(store.get(number)).fix_ready, "the bot's note is not Claude Code saying a fix is ready"
    other = asyncio.run(system.file("the bot's memory use", "The bot's memory use is high", "It is 312 MB."))
    assert other != first and asyncio.run(system.find("the bot's memory use")) == other, "another kind of problem is another bug"
    asyncio.run(store.set_status(number, bug_rules.FIXED, owner.id))
    assert asyncio.run(system.find("the nightly backup job")) == "", "closed by me: the next time is a new bug"

    async def no_forum(number, report, channel=None):
        from core.errors import UserError

        raise UserError("no forum")

    monkeypatch.setattr(posts, "create_post", no_forum)
    third = asyncio.run(system.file("the nightly backup job", "Nightly backup failed", "again"))
    assert third not in (first, other) and asyncio.run(store.get(bug_rules.parse_id(third))).post_url is None, "with no forum it is on record all the same"


# --- the bot's own memory -----------------------------------------------------------------------------------------------
def test_memory_use_is_a_problem_over_the_limit_or_when_it_keeps_growing_for_a_day():
    flat = [95.0 + (index % 3) for index in range(30)]
    rising = [90.0 + index for index in range(24)]
    assert health.growing(flat) == 0 and health.growing(rising[:23]) == 0, "less than a day of readings says nothing"
    assert health.growing(rising) == pytest.approx(18.0), "each quarter of the day higher than the one before, by 15 MB or more in all"
    assert health.growing([90.0 + index * 0.3 for index in range(24)]) == 0, "a few MB over a day is not growth worth saying"
    assert health.growing([*rising[:18], *[100.0] * 6]) == 0, "it came down again"
    assert health.memory_problem(95.0, flat, 300) == "" and health.memory_problem(None, rising, 300) == ""
    assert health.memory_problem(312.4, flat, 300) == "it is 312 MB, over the limit of 300 MB"
    assert health.memory_problem(113.0, rising, 300) == "it has kept growing for a day: 18 MB more, 113 MB now"
    assert (health.memory_mb() or 1) > 0


def test_the_hour_s_reading_is_logged_and_a_problem_files_a_bug_once_a_day_and_shows_on_live(monkeypatch):
    filed, told, logged = [], [], []

    async def file(key, summary, details):
        filed.append((key, summary, details))
        return "B9"

    async def find(key):
        return "B9" if filed else ""

    monkeypatch.setattr(health, "_file", file)
    monkeypatch.setattr(health, "_find", find)
    monkeypatch.setattr(health, "_samples", [])
    monkeypatch.setattr(health, "_memory_said", None)
    monkeypatch.setattr(health.log, "info", lambda text, *given: logged.append(text % given))
    monkeypatch.setattr(attention, "_listeners", [lambda: told.append(1)])
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(config, "MEMORY_LIMIT_MB", 300.0)
    reading = {"mb": 95.0}
    monkeypatch.setattr(health, "memory_mb", lambda: reading["mb"])
    start = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
    assert asyncio.run(health.sample_memory(start)) == "" and filed == [] and asyncio.run(health.memory(1, NOW)) == []
    assert logged[-1] == "Memory: 95 MB (peak 95 MB since the start, 1 readings)", "every hour, in the log"
    assert health.memory_line().startswith("Memory: 95 MB · peak 95 MB since it started") and "over 300 MB" in health.memory_line()
    reading["mb"] = 312.0
    assert asyncio.run(health.sample_memory(start + timedelta(hours=1))) == "it is 312 MB, over the limit of 300 MB"
    assert filed == [("the bot's memory use", "The bot's memory use is high", "It is 312 MB, over the limit of 300 MB. The last readings, an hour apart, in MB: 95, 312.")] and told == [1]
    (item,) = asyncio.run(health.memory(1, NOW))
    assert attention.status_line(item) == "⚠️ B9 · memory 312 MB"
    asyncio.run(health.sample_memory(start + timedelta(hours=2)))
    assert len(filed) == 1, "said once a day, not every hour"
    asyncio.run(health.sample_memory(start + timedelta(hours=26)))
    assert len(filed) == 2
    assert "+217 MB over the last 3 hours" in health.memory_line() or "MB over the last" in health.memory_line()
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert asyncio.run(health.memory(1, NOW)) == [], "the dev bot does not report on itself"


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


# --- a job that works again says so on its bug, which stays open ---------------------------------------------------
def test_a_kind_of_job_that_works_again_is_noted_on_its_bug_once_and_only_if_it_had_not_been_working(monkeypatch):
    noted = []

    async def over(key, text):
        noted.append((key, text))
        return "B14"

    async def file(key, summary, details):
        return "B14"

    async def find(key):
        return "B14"

    monkeypatch.setattr(health, "_file", file)
    monkeypatch.setattr(health, "_find", find)
    monkeypatch.setattr(health, "_over", over)
    monkeypatch.setattr(health, "_in_trouble", set())
    monkeypatch.setattr(scheduler, "_labels", {("core", "nightly_backup"): "nightly backup"})
    monkeypatch.setattr(health.clock, "real_now", lambda: datetime(2026, 10, 14, 14, 0, 30, tzinfo=timezone.utc))  # 3:00 am on Thursday in NZ
    job = scheduler.Job(1, None, "core", "nightly_backup", {}, NOW)
    asyncio.run(health.job_worked(job))
    assert noted == [], "a job that was working all along costs nothing and notes nothing"
    asyncio.run(health.job_trouble(job, scheduler.FAILED, "OSError('disk full')"))
    asyncio.run(health.job_worked(job))
    assert noted == [("the nightly backup job", "Worked again: the nightly backup ran without a problem on Thu 15 Oct at 3:00 am. This bug is still open: close it with Fixed when you are satisfied.")]
    asyncio.run(health.job_worked(job))
    assert len(noted) == 1, "said once: the nights after it are simply nights"


def test_after_a_restart_the_jobs_that_were_not_working_are_still_known(monkeypatch):
    async def troubled():
        return [("core", "nightly_backup", scheduler.FAILED)]

    monkeypatch.setattr(scheduler, "troubled", troubled)
    monkeypatch.setattr(health, "_in_trouble", set())
    asyncio.run(health.remember_trouble())
    assert health._in_trouble == {("core", "nightly_backup")}


def test_the_note_is_added_once_and_the_bug_is_never_closed(make_db, owner, monkeypatch):
    from tasks.bugs import listing, posts, store, system
    from tasks.bugs import rules as bug_rules

    make_db({"bugs": store.MIGRATIONS})

    async def who(discord_id):
        return owner

    async def create_post(number, report, channel=None):
        return 7000 + number, f"https://discord.test/{number}"

    async def refresh_card(item):
        pass

    async def commit():
        return "abc1234"

    monkeypatch.setattr(system, "get_user_by_discord_id", who)
    monkeypatch.setattr(posts, "create_post", create_post)
    monkeypatch.setattr(posts, "refresh_card", refresh_card)
    monkeypatch.setattr(system.capture, "git_commit", commit)
    monkeypatch.setattr(listing, "changed", lambda user_id: None)
    assert asyncio.run(system.over("the nightly backup job", "Worked again: …")) == "", "no open bug: nothing to note"
    name = asyncio.run(system.file("the nightly backup job", "Nightly backup failed", "disk full"))
    number = bug_rules.parse_id(name)
    assert asyncio.run(system.over("the nightly backup job", "Worked again: the nightly backup ran without a problem.")) == name
    asyncio.run(system.over("the nightly backup job", "Worked again: the nightly backup ran without a problem."))
    notes = asyncio.run(store.notes(number))
    assert [note.content[:12] for note in notes] == ["Worked again"] and notes[0].author == bug_rules.THE_BOT, "once"
    assert asyncio.run(store.get(number)).status == bug_rules.OPEN, "it is never closed by the bot"
    asyncio.run(system.file("the nightly backup job", "Nightly backup failed", "disk full again"))
    asyncio.run(system.over("the nightly backup job", "Worked again: the nightly backup ran without a problem."))
    assert [note.content[:12] for note in asyncio.run(store.notes(number))] == ["Worked again", "Again: Night", "Worked again"], "failing again and working again are each said"


def test_the_scheduler_tells_of_a_run_that_worked(db, monkeypatch):
    worked = []

    async def listener(job):
        worked.append(job.kind)

    async def no_log(*args):
        pass

    monkeypatch.setattr(scheduler, "log_error", no_log)
    scheduler.on_worked(listener)

    async def fails(job):
        raise OSError("disk full")

    async def works(job):
        pass

    scheduler.register_handler("test", "fails", fails)
    scheduler.register_handler("test", "works", works)

    async def scenario():
        for kind in ("fails", "works"):
            await scheduler.add_job("test", kind, scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()

    asyncio.run(scenario())
    assert worked == ["works"]
