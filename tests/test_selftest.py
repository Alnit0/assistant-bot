"""The self-test's own parts that need no Discord: what it reads, what it reports, and what it refuses."""
import asyncio
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

from core import config
from selftest import __main__ as runner
from selftest import onlyyou, phases, report
from selftest.discordside import Pressed, Seen, Typed, seen


def run(coroutine):
    return asyncio.run(coroutine)


# --- reading a message back ------------------------------------------------------------------------------------
def test_a_typed_message_is_the_real_one_with_the_owner_as_its_author():
    real = SimpleNamespace(id=7, content="took zinc", author=SimpleNamespace(bot=True))
    owner = SimpleNamespace(bot=False, id=1)
    typed = Typed(real, owner)
    assert typed.author is owner and typed.id == 7 and typed.content == "took zinc"


def test_a_button_is_found_by_part_of_its_label():
    shown = Seen(1, "text", buttons=[("✅ Taken", "card.b:pills:prompt_taken:5"), ("🕐 Taken at…", "card.b:pills:prompt_at:5")])
    assert shown.button("taken at") == "card.b:pills:prompt_at:5" and shown.button("Snooze") is None
    assert shown.labels == ["✅ Taken", "🕐 Taken at…"]


def test_a_drawn_message_is_read_as_its_texts_buttons_and_box_colours():
    class TextDisplay:
        def __init__(self, content):
            self.content = content

    class Container:
        def __init__(self, colour, *children):
            self.accent_colour, self.children = SimpleNamespace(value=colour), list(children)

    class Row:
        def __init__(self, *children):
            self.children = list(children)

    button = SimpleNamespace(custom_id="card.b:pills:sheet_taken:9", label="Taken", emoji="✅")
    message = SimpleNamespace(
        id=3, content="", components=[TextDisplay("# 💊 Today"), Container(0xFAA61A, TextDisplay("**Pill A**"), Row(button))], embeds=[],
        flags=SimpleNamespace(components_v2=True, suppress_notifications=True), reactions=[SimpleNamespace(emoji="⚠️", me=True), SimpleNamespace(emoji="👍", me=False)],
        edited_at=None, author=SimpleNamespace(id=42), reference=None,
    )
    shown = seen(message, bot_id=42)
    assert shown.text == "# 💊 Today\n**Pill A**" and shown.buttons == [("✅ Taken", "card.b:pills:sheet_taken:9")]
    assert shown.v2 and shown.accents == [0xFAA61A] and shown.reactions == ["⚠️"] and shown.silent and not shown.edited


def test_a_simulated_press_does_the_real_thing_to_the_real_message():
    done = []

    class Message:
        id, channel = 5, SimpleNamespace(id=9)

        async def edit(self, **drawn):
            done.append(("edit", drawn))

        async def delete(self):
            done.append(("delete",))

    pressed = Pressed(SimpleNamespace(id=1), Message(), "card.b:pills:taken:5")
    assert not pressed.response.is_done()
    run(pressed.response.edit_message(content="new"))
    run(pressed.followup.send("only you see this", ephemeral=True))
    run(pressed.delete_original_response())
    assert done == [("edit", {"content": "new"}), ("delete",)] and pressed.edits == 1 and pressed.deleted
    assert pressed.said == ["only you see this"] and pressed.response.is_done()


# --- the report ------------------------------------------------------------------------------------------------
def _result(key, status="pass", **more):
    return {"phase": "p1", "key": key, "title": f"step {key}", "expect": "what should be", "source": "T1", "status": status, "saw": "", "claude": "", "odd": "", "seconds": 1.0, **more}


def test_the_report_says_what_failed_with_what_was_expected_and_what_happened():
    found = {"results": [_result("1.01"), _result("1.02", "fail", saw="the card reads | nothing"), _result("1.03", "skip", saw="needs --claude")], "exit": 0, "seconds": 30}
    text = report.text([("p1", {"CARDS_V2": "false"}, found)], 0.0123, True, "20261013-101100")
    assert "**Result:** 1 passed, 1 failed, 0 broke, 1 skipped, of 3 steps" in text and "US$0.0123 spent" in text
    failed = text.split("## What failed")[1].split("## Discoveries")[0]
    assert "| 1.02 | step 1.02 | what should be | the card reads ¦ nothing | T1 |" in failed and "1.01" not in failed
    assert "| 1.01 | step 1.01 | ✅ pass |" in text and "⏭️ skipped" in text
    assert "## Only you can check" in text and "lock screen" in text
    assert "python -m selftest --clear" in text and "python -m selftest --remove" in text and "data/dev.db" in text


def test_with_nothing_failed_it_says_so_and_with_no_real_requests_too():
    text = report.text([("p1", {}, {"results": [_result("1.01")], "exit": 0, "seconds": 5})], 0.0, False, "20261013-101100")
    assert "## What failed\n\nNothing." in text and "none real: every language step used a recorded answer" in text


def test_discoveries_list_what_was_odd_what_was_slow_what_the_log_warned_and_what_was_not_tested():
    results = [_result("1.01", odd="reads oddly"), _result("1.02", seconds=61.0), _result("1.03")]
    lines = "\n".join(report.discoveries(results, [(2, "WARNING assistant: something | odd"), (1, "ERROR discord: worse")], 537))
    assert "- 1.01: reads oddly" in lines and "- 1.02 step 1.02: 61s" in lines and "1.03" not in lines
    assert "- ×2 `WARNING assistant: something ¦ odd`" in lines and "- `ERROR discord: worse`" in lines
    assert "8 min 57 s" in lines and onlyyou.NOT_TESTED[0] in lines
    quiet = "\n".join(report.discoveries([_result("1.01")], [], 60))
    assert quiet.count("- Nothing.") == 1 and quiet.count("- None.") == 2


def test_only_the_warnings_and_errors_logged_during_the_run_are_listed(tmp_path):
    log = tmp_path / "bot.log"
    log.write_text(
        "2026-10-13 09:59:59,000 WARNING assistant: before the run\n"
        "2026-10-13 10:01:00,000 INFO assistant: nothing to see\n"
        "2026-10-13 10:02:00,000 WARNING assistant: twice\n"
        "Traceback (most recent call last):\n"
        "2026-10-13 10:03:00,000 WARNING assistant: twice\n"
        "2026-10-13 10:04:00,000 ERROR discord.client: once\n"
        "2026-10-13 10:30:00,000 ERROR assistant: after the run\n",
        encoding="utf-8",
    )
    found = report.log_trouble(datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 13, 10, 10), log)
    assert found == [(2, "WARNING assistant: twice"), (1, "ERROR discord.client: once")]
    assert report.log_trouble(datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 13, 10, 10), tmp_path / "none.log") == []


# --- what it will and won't do ---------------------------------------------------------------------------------
def test_the_phases_run_the_old_look_twice_then_the_new_then_the_old_again_with_reminders_on():
    names = [name for name, _, _ in runner.PHASES]
    assert names == ["p1", "p2", "p3", "p4", "p5", "p6"] == list(phases.PHASES)
    looks = [settings["CARDS_V2"] for _, settings, _ in runner.PHASES]
    assert looks[:4] == ["false", "false", "true", "false"], "off, a restart, on, and back off"
    assert [settings.get("BRIEFING_ENABLED", "false") for _, settings, _ in runner.PHASES] == ["false", "false", "false", "false", "true", "true"], "the briefing off, then on"
    assert [settings.get("HUB_TIDY", "false") for _, settings, _ in runner.PHASES] == ["false"] * 5 + ["true"], "the tidy off, then on"
    assert all(settings["REMINDERS_ENABLED"] == "true" for _, settings, _ in runner.PHASES)
    assert [off for _, _, off in runner.PHASES][1] > 60, "long enough off for a job to count as late"


def test_its_channels_are_its_own_and_never_the_real_ones():
    assert set(runner.CHANNELS) == set(runner.ENV_NAMES) == {"hub", "inbox", "bot-log"}
    assert all(name.startswith("selftest-") for name in runner.CHANNELS.values())


def test_the_dev_database_is_set_aside_and_put_back_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner, "WORK", tmp_path / "selftest")
    (tmp_path / "dev.db").write_text("mine", encoding="utf-8")
    (tmp_path / "dev-clock.json").write_text("{}", encoding="utf-8")
    saved = runner.set_aside("s1")
    assert not (tmp_path / "dev.db").exists() and (saved / "dev.db").read_text(encoding="utf-8") == "mine"
    (tmp_path / "dev.db").write_text("the test's", encoding="utf-8")
    runner.put_back(saved, "s1")
    assert (tmp_path / "dev.db").read_text(encoding="utf-8") == "mine" and (tmp_path / "dev-clock.json").exists()
    assert (tmp_path / "selftest" / "run-s1" / "dev.db").read_text(encoding="utf-8") == "the test's" and not saved.exists()
    # With no dev database to begin with, none is left behind
    (tmp_path / "dev.db").unlink()
    (tmp_path / "dev-clock.json").unlink()
    assert runner.set_aside("s2") is None
    (tmp_path / "dev.db").write_text("the test's", encoding="utf-8")
    runner.put_back(None, "s2")
    assert not (tmp_path / "dev.db").exists()


def test_a_phase_refuses_the_live_database_and_a_start_by_hand(tmp_path):
    env = {key: value for key, value in __import__("os").environ.items() if key != "SELFTEST"}
    live = subprocess.run([sys.executable, "-m", "selftest.phase", "--live", "p1", str(tmp_path / "out.json")], capture_output=True, text=True, cwd=config.BASE_DIR, env=env)
    assert live.returncode == 2 and "only runs on the dev database" in live.stdout
    by_hand = subprocess.run([sys.executable, "-m", "selftest.phase", "--dev", "p1", str(tmp_path / "out.json")], capture_output=True, text=True, cwd=config.BASE_DIR, env=env)
    assert by_hand.returncode == 2 and "python -m selftest" in by_hand.stdout and not (tmp_path / "out.json").exists()


# --- a test that hangs ---------------------------------------------------------------------------------------
def test_a_test_that_hangs_stops_the_run_with_its_name_and_where_it_was():
    from tests import watchdog

    code = "import time; from tests import watchdog; watchdog.watch('tests/test_x.py::test_stuck', 0.3); time.sleep(20)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=config.BASE_DIR, timeout=15)
    assert done.returncode == watchdog.EXIT_CODE != 0
    assert "TIMEOUT: tests/test_x.py::test_stuck ran for more than 0.3 seconds" in done.stderr
    assert "Thread" in done.stderr and "time.sleep" not in done.stdout, "where each thread was, for finding the cause"
    assert watchdog.SECONDS >= 30, "long enough that a slow machine never trips it"
    timer = watchdog.watch("tests/test_x.py::test_fine", 30)
    timer.cancel()
    assert timer.daemon, "a watcher never keeps the run alive"


# --- only what a change touches, and room on the PC ---------------------------------------------------------------
def test_a_changed_file_touches_the_stages_it_can_break():
    from selftest import stages

    assert stages.stages_of("docs/STATUS.md") == () and stages.stages_of("tests/test_x.py") == () and stages.stages_of("CLAUDE.md") == ()
    assert stages.stages_of("tasks/briefing/rules.py") == ("briefing",) and stages.stages_of("tasks\\pills\\summary.py") == ("briefing",)
    assert stages.stages_of("core/messages.py") == ("tidy",)
    assert stages.stages_of("tasks/pills/checklist.py") == ("day",)
    assert stages.stages_of("core/scheduler.py") == stages.ORDER and stages.stages_of("main.py") == stages.ORDER, "the bot's shared code: everything"
    assert stages.stages_of("selftest/phases.py") == stages.ORDER


def test_only_the_stages_touched_since_each_last_passed_are_run_and_one_never_passed_always_is():
    from selftest import stages

    assert stages.touched({"day": [], "briefing": [], "tidy": []}) == {}
    assert stages.touched({"day": ["docs/QA-RUN.md"], "briefing": ["tests/test_briefing.py"], "tidy": []}) == {}
    found = stages.touched({"day": ["tasks/briefing/rules.py"], "briefing": ["tasks/briefing/rules.py"], "tidy": ["tasks/briefing/rules.py"]})
    assert found == {"briefing": "tasks/briefing/rules.py"}
    assert list(stages.touched({"day": ["core/cards.py"], "briefing": ["core/cards.py"], "tidy": ["core/cards.py"]})) == ["day", "briefing", "tidy"]
    assert stages.touched({"day": [], "briefing": None, "tidy": []}) == {"briefing": "it has not passed here yet"}
    many = stages.touched({"day": [f"tasks/pills/{n}.py" for n in "abcde"], "briefing": [], "tidy": []})
    assert many == {"day": "tasks/pills/a.py, tasks/pills/b.py, tasks/pills/c.py and 2 more"}


def test_the_starts_for_a_stage_and_the_tidy_brings_the_briefing_s_start_with_it():
    from selftest import stages

    assert stages.phases_for(["day"]) == ["p1", "p2", "p3", "p4"] and stages.phases_for(["briefing"]) == ["p5"]
    assert stages.phases_for(["tidy"]) == ["p5", "p6"] and stages.phases_for(["tidy", "briefing"]) == ["p5", "p6"]
    assert stages.phases_for(stages.ORDER) == [name for name, _, _ in runner.PHASES], "every stage together is the whole story"
    assert {phase for each in stages.STAGES.values() for phase in each} == set(phases.PHASES)


def test_a_stage_has_passed_only_when_every_start_of_it_ran_with_nothing_failed(tmp_path):
    from selftest import stages

    assert stages.passed_stages(["p5", "p6"], set()) == ["briefing", "tidy"]
    assert stages.passed_stages(["p5", "p6"], {"p6"}) == ["briefing"]
    assert stages.passed_stages(["p1", "p2", "p3"], set()) == [], "the day stage was not run whole"
    where = tmp_path / "selftest" / "passed.json"
    assert stages.read_passed(where) == {}
    stages.write_passed(where, {"day": "abc", "tidy": "def"})
    assert stages.read_passed(where) == {"day": "abc", "tidy": "def"}
    where.write_text("not json", encoding="utf-8")
    assert stages.read_passed(where) == {}, "a file that can't be read means nothing has passed: everything is run"
    assert stages.changed_since(config.BASE_DIR, None) is None and stages.changed_since(config.BASE_DIR, "0" * 40) is None


def test_low_memory_is_said_before_a_run_and_stops_it(monkeypatch, capsys):
    from selftest import stages

    assert stages.memory_line(None) == (False, "free memory: could not be read")
    low, said = stages.memory_line(1024**3)
    assert low and "1.0 GB" in said and "LOW" in said
    assert stages.memory_line(3 * 1024**3) == (False, "free memory: 3.0 GB")
    free = stages.free_memory()
    assert free is None or free > 0

    started = []
    monkeypatch.setattr(runner.instance_lock, "holder", lambda: None)
    monkeypatch.setattr(runner.stages, "free_memory", lambda: 1024**3)
    monkeypatch.setattr(runner, "prepare_channels", lambda *a, **k: started.append("channels"))
    monkeypatch.setattr(sys, "argv", ["selftest", "--stages", "briefing"])
    assert runner.main() == 4 and started == [], "nothing is started, and the dev database is not moved"
    out = capsys.readouterr().out
    assert "LOW" in out and "not started" in out and "--anyway" in out


def test_a_stage_that_does_not_exist_is_refused_before_anything_starts(monkeypatch, capsys):
    monkeypatch.setattr(runner.instance_lock, "holder", lambda: None)
    monkeypatch.setattr(sys, "argv", ["selftest", "--stages", "pills"])
    assert runner.main() == 2 and "No such stage: pills" in capsys.readouterr().out


def test_a_run_that_begins_at_the_briefing_makes_its_own_pills_with_recorded_answers_only():
    import inspect

    source = inspect.getsource(phases.seed)
    assert "recorded_only = True" in source and "finally" in source and all(name in source for name in ("Testa", "Testany", "Testiron", "Testlate"))
    assert "await seed(h)" in inspect.getsource(phases.p5)
    assert 'h.memo["began_here"] = True' in source and 'h.memo.get("began_here")' in inspect.getsource(phases.p5), "the day before such a run has nothing recorded, and the step knows"


# --- what lasts of a run: the history, the summary, the bugs ---------------------------------------------------------
from selftest import bugs as selftest_bugs  # noqa: E402
from selftest import record  # noqa: E402
from tests.test_bugs import bugs_db  # noqa: E402, F401


def _steps(*pairs):
    return [{"key": key, "title": f"step {key}", "expect": "it works", "saw": "" if status == "pass" else "it did not", "status": status} for key, status in pairs]


def test_a_run_is_one_line_of_history_and_the_file_is_only_ever_added_to(tmp_path):
    where = tmp_path / "selftest" / "history.csv"
    assert record.read(where) == [], "no file yet is no runs"
    first = record.row("20261013-152146", "837b16cabcdef", "tidy", _steps(("5.01", "pass"), ("6.04", "fail"), ("6.05", "error"), ("6.06", "skip")), 0.015, True, 245)
    assert first == {
        "date": "2026-10-13 15:21", "commit": "837b16c", "ran": "tidy", "steps": "4", "passed": "1", "failed": "2",
        "failed_steps": "6.04 6.05", "spend_usd": "0.0150", "claude": "real", "seconds": "245", "note": "",
    }
    record.append(where, first)
    before = where.read_bytes()
    record.append(where, record.row("20261014-090000", None, "full", _steps(("1.01", "pass")), 0, False, 900))
    assert where.read_bytes().startswith(before), "what was there is never rewritten"
    assert where.read_text(encoding="utf-8").count("date,commit") == 1, "the heading is written once"
    rows = record.read(where)
    assert [each["date"] for each in rows] == ["2026-10-13 15:21", "2026-10-14 09:00"]
    assert (rows[1]["commit"], rows[1]["claude"], rows[1]["failed"], rows[1]["failed_steps"]) == ("", "recorded", "0", "")


def test_the_report_shows_the_latest_runs_newest_first_and_the_rest_of_it_is_left_as_it_was(tmp_path):
    rows = [record.row(f"202610{day:02d}-090000", "abc1234", "full", _steps(("1.01", "pass")), 0.1, True, 600) for day in range(1, 20)]
    rows.append(record.row("20261020-090000", "def5678", "day", _steps(("1.01", "fail"), ("1.02", "pass")), 0.05, False, 61))
    lines = record.view(rows)
    table = [each for each in lines if each.startswith("| 2026")]
    assert len(table) == record.SHOWN and "The latest 15 of 20 runs" in "\n".join(lines)
    assert table[0] == "| 2026-10-20 09:00 | `def5678` | day | 1 of 2 | **1** | 1.01 | US$0.0500 (recorded) | 1 min 01 s |"
    assert table[1] == "| 2026-10-19 09:00 | `abc1234` | full | 1 of 1 | 0 | · | US$0.1000 | 10 min 00 s |"
    assert record.view([])[2] == "No run on record yet."

    document = "# Self-test\n\nintro\n\n## What failed\n\nNothing.\n"
    once = record.with_view(document, rows[:1])
    twice = record.with_view(once, rows)
    assert once.index(record.START) < once.index("## What failed") and "2026-10-20" not in once
    assert twice.count(record.START) == 1 and twice.count("## Run history") == 1 and "2026-10-20 09:00" in twice
    assert twice.startswith("# Self-test\n\nintro\n\n") and twice.endswith("## What failed\n\nNothing.\n"), "only the table changes"
    assert record.with_view("# Self-test\n", rows).count(record.END) == 1, "a report with no place for it gets it at the end"
    path = tmp_path / "SELFTEST.md"
    path.write_bytes(document.replace("\n", "\r\n").encode("utf-8"))
    record.put_view(path, rows)
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") and b"Run history" in raw, "the file keeps its line endings"


def test_the_one_message_a_run_leaves_in_the_log_says_what_ran_what_failed_and_what_it_cost():
    fine = record.summary(record.row("20261013-152146", "837b16c", "tidy", _steps(*[(f"5.{n:02d}", "pass") for n in range(24)]), 0.015, True, 245))
    assert fine.splitlines() == ["🧪 Self-test · 2026-10-13 15:21 · tidy · commit `837b16c`", "✅ 24 of 24 steps passed · US$0.0150 spent · 4 min 05 s"]
    bad = record.summary(
        record.row("20261013-152146", "837b16c", "full", _steps(("5.01", "pass"), ("6.04", "fail"), ("6.05", "error")), 0.0, False, 900),
        ["D3 opened · step 6.04", "D2 failed again · step 6.05"], "the bugs were not brought up to date: no forum",
    )
    assert bad.splitlines()[1:] == [
        "❌ 2 of 3 steps failed: 6.04 6.05 · US$0.0000 spent (recorded answers) · 15 min 00 s",
        "🐞 D3 opened · step 6.04", "🐞 D2 failed again · step 6.05", "⚠️ the bugs were not brought up to date: no forum",
    ]
    stopped = record.summary(record.row("20261013-145437", "", "?", _steps(("1.01", "pass")), 0.059, False, 0, note=record.UNFINISHED))
    assert "⚠️ did not finish: stopped before the end (1 of 1 steps had passed)" in stopped and "commit `?`" in stopped
    for said in (fine, bad, stopped):
        assert said.startswith(record.MARK) and len(said) <= 1900
        # The steps look in #selftest-log for the bot's own cards by these words: a summary left there must not hold them
        assert not any(word in said for word in ("Tidy", "Backup saved", "Caught up", "Bot started", "Claude spend"))


def test_what_is_done_about_a_step_depends_on_whether_it_has_a_bug_and_how_that_bug_stands():
    known = {"1.01": 1, "1.02": 2, "1.03": 3, "1.04": 4, "1.05": 5, "1.06": 6, "1.07": 7}
    states = {1: "open", 2: "fixed", 3: "wontfix", 5: "open", 6: "fixed", 7: "open"}  # 4 is no longer in the database
    results = _steps(
        ("1.00", "fail"), ("1.01", "fail"), ("1.02", "error"), ("1.03", "fail"), ("1.04", "fail"),
        ("1.05", "pass"), ("1.06", "pass"), ("1.07", "skip"), ("1.08", "pass"),
    )
    Act = selftest_bugs.Act
    assert selftest_bugs.decide(results, known, states, "open", "fixed") == [
        Act(selftest_bugs.NEW, "1.00"),  # no bug yet
        Act(selftest_bugs.AGAIN, "1.01", 1),  # the same bug, a note
        Act(selftest_bugs.REOPENED, "1.02", 2),  # it had been marked Fixed
        Act(selftest_bugs.AGAIN, "1.03", 3),  # Won't fix stays as it was left: a note only
        Act(selftest_bugs.NEW, "1.04"),  # its bug went with the database
        Act(selftest_bugs.FIXED, "1.05", 5),  # passes again
    ], "one already Fixed that passes, one skipped and one with no bug that passes change nothing"
    assert selftest_bugs.decide(_steps(("9.01", "pass")), known, states, "open", "fixed") == [], "a step that was not part of the run is left alone"


def test_a_bug_s_words_say_the_step_what_was_expected_and_what_was_seen():
    step = {"key": "6.04", "title": "A copy was saved first", "expect": "The file is there", "saw": "no file" + "!" * 2000, "status": "fail"}
    said = selftest_bugs.content(step)
    assert said.startswith("Self-test step 6.04: A copy was saved first\nExpected: The file is there\nSeen: no file") and said.endswith("…") and len(said) < 1100
    assert selftest_bugs.note(selftest_bugs.FIXED, step, "2026-10-13 15:21", "837b16c") == "Passed again in the self-test of 2026-10-13 15:21 · commit `837b16c`: marked Fixed by the self-test."
    assert selftest_bugs.note(selftest_bugs.AGAIN, step, "2026-10-13 15:21", "").startswith("Failed again in the self-test of 2026-10-13 15:21 · commit `?`.\nSeen: no file")
    assert selftest_bugs.note(selftest_bugs.REOPENED, step, "d", "c").startswith("Failed again, so re-opened, in the self-test of d")
    assert selftest_bugs.line("opened", "D3", "6.04", "https://x/1") == "[D3](<https://x/1>) opened · step 6.04" and selftest_bugs.line("fixed", "D3", "6.04") == "D3 fixed · step 6.04"


def test_a_failing_step_gets_one_bug_which_is_noted_fixed_and_re_opened_as_the_step_goes(bugs_db, owner, monkeypatch, tmp_path):
    from tasks.bugs import posts, store
    from tasks.bugs import rules as bug_rules

    made, shown = [], []

    async def create_post(number, report, channel=None):
        if "6.05" in report.target.content:
            raise RuntimeError("Discord said no")
        made.append(number)
        return 7000 + number, f"https://discord.test/{number}"

    async def bring_up_to_date(item, said, channel=None):
        shown.append((item.id, item.status, said.splitlines()[0]))

    monkeypatch.setattr(posts, "create_post", create_post)
    monkeypatch.setattr(posts, "bring_up_to_date", bring_up_to_date)
    where = tmp_path / "selftest" / "bugs.json"
    assert not selftest_bugs.has_known(where)

    def after(*pairs):
        return {"date": "2026-10-13 15:21", "commit": "837b16c", "channel_id": 5, "results": _steps(*pairs)}

    first = run(selftest_bugs.apply(after(("6.04", "fail"), ("6.05", "fail"), ("6.06", "pass")), where, owner.id))
    number = selftest_bugs.read_known(where)["6.04"]
    name = bug_rules.bug_id(number)
    assert first[0] == {"step": "6.04", "bug": name, "what": "opened", "url": f"https://discord.test/{number}"}
    assert first[1]["step"] == "6.05" and first[1]["what"].startswith("could not be recorded") and "6.05" not in selftest_bugs.read_known(where), "one that can't be recorded does not stop the others, and is tried again next time"
    item = run(store.get(number))
    assert item.status == bug_rules.OPEN and item.report.source == bug_rules.SELFTEST and item.report.commit == "837b16c"
    assert item.report.target.content == "Self-test step 6.04: step 6.04\nExpected: it works\nSeen: it did not"
    card = bug_rules.opening_text(number, item.report)
    assert "by the self-test" in card and "from the self-test" in card and "> Expected: it works" in card, "the post reads like any other bug's"

    again = run(selftest_bugs.apply(after(("6.04", "error")), where, owner.id))
    assert again == [{"step": "6.04", "bug": name, "what": "failed again", "url": f"https://discord.test/{number}"}] and made == [number], "no second bug"
    item = run(store.get(number))
    notes = run(store.notes(number))
    assert item.status == bug_rules.OPEN and len(notes) == 1 and notes[0].author == bug_rules.SELF_TEST and notes[0].content.startswith("Failed again in the self-test")
    assert not item.fix_ready, "the self-test's note is not Claude Code saying a fix is ready"

    run(selftest_bugs.apply(after(("6.06", "pass")), where, owner.id))
    assert run(store.get(number)).status == bug_rules.OPEN, "a run the step was not part of leaves its bug alone"

    passed = run(selftest_bugs.apply(after(("6.04", "pass")), where, owner.id))
    assert passed[0]["what"] == "fixed" and run(store.get(number)).status == bug_rules.FIXED
    assert shown[-1] == (number, bug_rules.FIXED, "Passed again in the self-test of 2026-10-13 15:21 · commit `837b16c`: marked Fixed by the self-test.")
    assert run(selftest_bugs.apply(after(("6.04", "pass")), where, owner.id)) == [], "passing again says nothing more"

    back = run(selftest_bugs.apply(after(("6.04", "fail")), where, owner.id))
    assert back[0]["what"] == "re-opened" and back[0]["bug"] == name and run(store.get(number)).status == bug_rules.OPEN and made == [number]
    assert [event.event for event in run(store.events(number))] == [bug_rules.FIXED, bug_rules.REOPENED]


def test_a_post_changed_with_no_press_gets_its_card_a_line_its_tag_and_is_archived_when_closed(monkeypatch):
    from tasks.bugs import posts
    from tasks.bugs import rules as bug_rules

    did = []
    tag = lambda name: SimpleNamespace(name=name)  # noqa: E731
    forum = SimpleNamespace(available_tags=[tag("Open"), tag("Fixed"), tag("Won't fix"), tag("dev")])

    class Opening:
        async def edit(self, **kwargs):
            did.append(("card", kwargs["content"].splitlines()[-1][:12]))

    class Thread:
        archived = True
        applied_tags = [tag("Open"), tag("dev")]

        def get_partial_message(self, message_id):
            return Opening()

        async def edit(self, **kwargs):
            did.append(("edit", {key: ([each.name for each in value] if key == "applied_tags" else value) for key, value in kwargs.items()}))

        async def send(self, text, **kwargs):
            did.append(("said", text))

    async def channel(thread_id):
        return Thread()

    monkeypatch.setattr(posts, "_channel", channel)
    report = bug_rules.Report(bug_rules.SELFTEST, 5, "the self-test", bug_rules.Snapshot(0, "self-test", "Self-test step 6.04: x", "2026-10-13T02:21:00+00:00"), reported_at="2026-10-13T02:21:00+00:00")
    item = SimpleNamespace(id=3, thread_id=7003, status=bug_rules.FIXED, report=report, changed_at="2026-10-13T02:30:00+00:00", note_count=1)
    run(posts.bring_up_to_date(item, "Passed again.", forum))
    assert did[0] == ("edit", {"archived": False}), "an archived post is opened first: nothing in it can be edited"
    assert did[1][0] == "card" and did[2] == ("said", "Passed again.")
    assert did[3] == ("edit", {"applied_tags": ["Fixed", "dev"], "archived": True}), "the tag follows the status, the dev tag stays, and a closed bug's post is archived last"
    run(posts.bring_up_to_date(None, "x", forum))
    run(posts.bring_up_to_date(SimpleNamespace(id=4, thread_id=None), "x", forum))
    assert len(did) == 4, "a bug with no post has nothing to bring up to date"


# --- the runner: a run that was stopped, and what is kept after one -------------------------------------------------
def _runner_in(tmp_path, monkeypatch):
    data = tmp_path / "data"
    work = data / "selftest"
    work.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(runner, "WORK", work)
    monkeypatch.setattr(runner, "HISTORY", work / "history.csv")
    monkeypatch.setattr(runner, "BUGS", work / "bugs.json")
    monkeypatch.setattr(report, "PATH", tmp_path / "SELFTEST.md")
    return data, work


def test_a_run_that_was_stopped_is_put_right_and_recorded_before_the_next(tmp_path, monkeypatch):
    import json

    data, work = _runner_in(tmp_path, monkeypatch)
    assert runner.recover() == [], "nothing left behind: nothing to do"
    (work / "saved-20261013-145437").mkdir()
    (work / "saved-20261013-145437" / "dev.db").write_text("mine", encoding="utf-8")
    (data / "dev.db").write_text("the stopped run's", encoding="utf-8")
    (work / "run-20261013-145437").mkdir()
    (work / "run-20261013-145437" / "p1.json").write_text(json.dumps({"results": _steps(("1.01", "pass"), ("1.02", "pass"))}), encoding="utf-8")
    (added,) = runner.recover()
    assert (data / "dev.db").read_text(encoding="utf-8") == "mine", "the dev database that was set aside is back"
    assert (work / "run-20261013-145437" / "dev.db").read_text(encoding="utf-8") == "the stopped run's" and not (work / "saved-20261013-145437").exists()
    assert (added["date"], added["steps"], added["passed"], added["failed"], added["note"]) == ("2026-10-13 14:54", "2", "2", "0", record.UNFINISHED)
    assert record.read(work / "history.csv") == [added] and runner.recover() == [], "said once"


def test_with_nothing_failed_and_no_bug_on_record_no_process_is_started_for_bugs(tmp_path, monkeypatch):
    data, work = _runner_in(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: started.append(args) or SimpleNamespace(returncode=0, stdout='{"step": "6.04", "bug": "D3", "what": "fixed", "url": null}\nnoise\n', stderr=""))
    line = record.row("20261013-152146", "837b16c", "tidy", _steps(("6.04", "pass")), 0.0, False, 60)
    assert runner.file_bugs(line, _steps(("6.04", "pass")), "20261013-152146", 5) == ([], "") and started == []
    (work / "bugs.json").write_text('{"6.04": 3}', encoding="utf-8")
    assert runner.file_bugs(line, _steps(("6.04", "pass")), "20261013-152146", 5) == (["D3 fixed · step 6.04"], ""), "a bug on record is looked at even when everything passed: it may be fixed now"
    command = started[0][0]
    assert command[1:4] == ["-m", "selftest.bugs", "--dev"] and command[4].endswith("results.json"), "on the dev database, never the live one"
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Traceback\nUserError: no forum\n"))
    assert runner.file_bugs(line, _steps(("6.04", "fail")), "20261013-152146", 5) == ([], "the bugs were not brought up to date: UserError: no forum")


def test_after_a_run_the_history_the_table_and_the_summary_are_each_kept_whatever_happens_to_the_others(tmp_path, monkeypatch, capsys):
    data, work = _runner_in(tmp_path, monkeypatch)
    posted = []

    def no_bugs(*args):
        raise RuntimeError("the forum is gone")

    async def say(channel_id, text):
        posted.append((channel_id, text))

    monkeypatch.setattr(runner, "file_bugs", no_bugs)
    monkeypatch.setattr(runner, "say", say)
    results = _steps(("6.04", "fail"), ("6.05", "pass"))
    runner.keep(record.row("20261013-152146", "837b16c", "tidy", results, 0.015, True, 245), results, "20261013-152146", {"bot-log": 9})
    assert [each["failed_steps"] for each in record.read(work / "history.csv")] == ["6.04"]
    assert "| 2026-10-13 15:21 | `837b16c` | tidy | 1 of 2 | **1** | 6.04 |" in (tmp_path / "SELFTEST.md").read_text(encoding="utf-8")
    assert posted[0][0] == 9 and "❌ 1 of 2 steps failed: 6.04" in posted[0][1] and "⚠️ the bugs were not brought up to date: the forum is gone" in posted[0][1]

    async def no_discord(channel_id, text):
        raise RuntimeError("offline")

    monkeypatch.setattr(runner, "say", no_discord)
    runner.keep(record.row("20261013-160000", "837b16c", "tidy", results, 0.0, False, 60), results, "20261013-160000", {"bot-log": 9})
    assert len(record.read(work / "history.csv")) == 2 and "the summary could not be posted" in capsys.readouterr().out
