"""The nightly self-test (core/nightly.py, behind NIGHTLY_SELFTEST) and its ping (selftest/notify.py)."""
import asyncio
import sys
from datetime import datetime, time, timezone
from types import SimpleNamespace

import pytest

from core import config, nightly, scheduler
from selftest import __main__ as runner
from selftest import notify, record


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def night(monkeypatch):
    """Live with the switch on, and stand-ins for the process and #bot-log."""
    seen = SimpleNamespace(started=[], said=[], notes=[], reported=[], code=0)

    class Process:
        pid, returncode = 4242, None

        async def wait(self):
            Process.returncode = seen.code
            return seen.code

    async def start(full):
        seen.started.append(full)
        Process.returncode = None
        return Process()

    async def log_error(title, details):
        seen.said.append((title, details))

    monkeypatch.setattr(config, "NIGHTLY_SELFTEST", True)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(nightly, "start", start)
    monkeypatch.setattr(nightly, "log_error", log_error)
    monkeypatch.setattr(nightly, "_running", None)
    monkeypatch.setattr(nightly, "_watching", None)
    monkeypatch.setattr(scheduler, "note", lambda job, text: seen.notes.append(text))
    monkeypatch.setattr(scheduler, "report", lambda job, ended: seen.reported.append(ended))
    return seen


def _job(local_at="2026-10-14T03:00"):
    return scheduler.Job(id=1, user_id=None, task="core", kind="nightly_selftest", payload={}, due_at=datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc), local_at=local_at)


def test_it_is_off_unless_switched_on_and_never_the_dev_bot_s(monkeypatch):
    assert config.flag(None, False) is False and config.flag("", False) is False, "off unless .env says otherwise (whatever this PC's own .env says)"
    monkeypatch.setattr(config, "NIGHTLY_SELFTEST", True)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    assert nightly.enabled()
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert not nightly.enabled(), "the dev bot never starts a self-test of itself"


def test_its_schedule_is_made_only_while_it_is_on_and_only_on_live(monkeypatch):
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_labels", {})
    monkeypatch.setattr(scheduler, "_standing", {})
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(config, "NIGHTLY_SELFTEST", False)
    nightly.setup()
    assert ("core", "nightly_selftest") in scheduler._handlers and scheduler._standing == {}, "off: a run booked earlier still has its handler, which says off; no schedule is made"
    assert scheduler.label("core", "nightly_selftest") == "nightly self-test"
    monkeypatch.setattr(config, "NIGHTLY_SELFTEST", True)
    nightly.setup()
    default = scheduler._standing[("core", "nightly_selftest")]
    assert (default.name, default.at, default.locked, default.channel) == ("Nightly self-test", time(3, 30), False, "bot-log"), "3:30 am, after the 3:00 am backup, and mine to move with `my schedule`"
    assert default.missed == "skip:180", "a night the bot was off for is not run in the middle of the morning"
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_standing", {})
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    nightly.setup()
    assert scheduler._handlers == {} and scheduler._standing == {}


def test_the_stages_touched_on_a_weeknight_and_everything_on_a_sunday():
    now = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)  # Wednesday 3:00 am in NZ
    assert not nightly.is_full("2026-10-14T03:00", now) and nightly.is_full("2026-10-18T03:00", now), "by the day the run stands for"
    assert nightly.is_full(None, datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)), "a one-off run goes by the day it is in NZ"
    assert nightly.command(False) == [sys.executable, "-m", "selftest", "--nightly"]
    assert nightly.command(True) == [sys.executable, "-m", "selftest", "--nightly", "--full"]
    assert "--claude" not in nightly.command(True), "recorded answers: a night costs nothing"


def test_the_job_only_starts_the_run_and_says_so(night):
    async def twice():
        await nightly.nightly_job(_job())
        assert night.started == [False] and night.reported == [] and night.said == []
        assert night.notes == ["started as the dev bot: the stages touched since each last passed; the result is in the self-test's log channel"]
        night.notes.clear()
        await nightly.nightly_job(_job("2026-10-18T03:00"))  # the next night, with the first still going

    run(twice())
    assert night.started == [False] and night.reported == [scheduler.SKIPPED] and night.notes == ["the last one is still running"], "never two at once"


def test_off_it_starts_nothing_and_says_off(night, monkeypatch):
    monkeypatch.setattr(config, "NIGHTLY_SELFTEST", False)
    run(nightly.nightly_job(_job()))
    assert night.started == [] and night.notes == ["off (NIGHTLY_SELFTEST)"] and night.said == []


def test_a_run_that_could_not_start_is_said_in_bot_log_and_failing_steps_are_the_run_s_own_to_report(night):
    assert nightly.how_it_ended(0) == "" and nightly.how_it_ended(1) == "", "it ran: its summary, its bugs and the ping say the rest"
    assert "too little memory" in nightly.how_it_ended(4) and "no dev bot" in nightly.how_it_ended(3) and nightly.how_it_ended(9) == "it ended with code 9"

    async def through(code):
        night.code = code
        await nightly.nightly_job(_job())
        await nightly._watching

    run(through(1))
    assert night.said == [], "a failed step is not live's to say"
    nightly._running = None
    run(through(4))
    assert night.said == [("Nightly self-test did not run", "Too little memory was free. Its own words are in `logs/selftest-nightly.log`.")]


def test_a_start_is_given_nothing_of_live_s_environment(monkeypatch, tmp_path):
    seen = {}

    async def exec_(*command, cwd=None, env=None, stdout=None, stderr=None):
        seen.update(command=list(command), env=env, cwd=cwd)
        return SimpleNamespace(pid=1, returncode=None)

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "_SET_BEFORE", {"PATH"})
    monkeypatch.setenv("DISCORD_TOKEN", "live-token")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    run(nightly.start(True))
    assert seen["command"][1:] == ["-m", "selftest", "--nightly", "--full"] and "DISCORD_TOKEN" not in seen["env"], "the run reads the dev bot's settings for itself"
    assert (tmp_path / "selftest-nightly.log").exists()


# --- the ping ---------------------------------------------------------------------------------------------------------
def _line(failed="0", steps="24", failed_steps="", note=""):
    return {"date": "2026-10-14 03:00", "commit": "abc1234", "ran": "nightly, day", "steps": steps, "passed": str(int(steps) - int(failed)), "failed": failed, "failed_steps": failed_steps, "spend_usd": "0.0000", "claude": "recorded", "seconds": "600", "note": note}


def test_the_phone_is_pinged_only_when_a_step_fails():
    assert not notify.wanted(_line()), "a night with everything passing says nothing on the phone"
    assert notify.wanted(_line("2", "24", "1.04 3.02")) and notify.wanted(_line(note=record.UNFINISHED))
    assert notify.words(_line("2", "24", "1.04 3.02")) == "2 of 24 steps failed (nightly, day): 1.04 3.02"
    assert notify.words(_line(note=record.UNFINISHED)) == "nightly, day: did not finish: stopped before the end"


def test_the_ping_goes_to_the_topic_at_priority_5_and_the_topic_is_never_given_away(tmp_path, capsys):
    sent = []

    def post(request, timeout=None):
        sent.append((request.full_url, dict(request.header_items()), request.data.decode("utf-8")))

    for content in ("NTFY_TOPIC=secret-topic-1\n", "secret-topic-1\n", "# mine\nNTFY_TOPIC=\"secret-topic-1\"\n"):
        where = tmp_path / ".env.notify"
        where.write_text(content, encoding="utf-8")
        assert notify.send("2 of 24 steps failed", path=where, post=post) is True
    assert {url for url, _, _ in sent} == {"https://ntfy.sh/secret-topic-1"}, "the name in front, the topic alone, or quoted"
    headers = sent[0][1]
    assert headers["Priority"] == "5" and headers["Title"].startswith("=?UTF-8?B?") and sent[0][2] == "2 of 24 steps failed"
    assert notify.send("x", path=tmp_path / "missing", post=post) is False, "no file: nothing is sent and nothing is said"

    def down(request, timeout=None):
        raise OSError("no network")

    assert notify.send("x", path=where, post=down) is False, "ntfy not reachable: silently"
    assert "secret-topic-1" not in capsys.readouterr().out


def test_a_nightly_run_pings_after_its_summary_and_any_other_run_never_does(monkeypatch, tmp_path):
    from selftest import report

    work = tmp_path / "selftest"
    work.mkdir()
    pinged = []
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner, "WORK", work)
    monkeypatch.setattr(runner, "HISTORY", work / "history.csv")
    monkeypatch.setattr(runner, "BUGS", work / "bugs.json")
    monkeypatch.setattr(report, "PATH", tmp_path / "SELFTEST.md")
    monkeypatch.setattr(runner, "file_bugs", lambda *args: ([], ""))

    async def say(channel_id, text):
        pass

    monkeypatch.setattr(runner, "say", say)
    monkeypatch.setattr(runner.notify, "send", lambda body: pinged.append(body) or True)
    bad = [{"key": "1.04", "title": "t", "expect": "e", "saw": "s", "status": "fail"}, {"key": "1.05", "title": "t", "expect": "e", "saw": "", "status": "pass"}]
    fine = [{"key": "1.05", "title": "t", "expect": "e", "saw": "", "status": "pass"}]
    runner.keep(record.row("20261014-030000", "abc", "nightly, day", bad, 0.0, False, 60), bad, "20261014-030000", {"bot-log": 9}, True)
    assert pinged == ["1 of 2 steps failed (nightly, day): 1.04"]
    runner.keep(record.row("20261015-030000", "abc", "nightly, day", fine, 0.0, False, 60), fine, "20261015-030000", {"bot-log": 9}, True)
    runner.keep(record.row("20261015-100000", "abc", "day", bad, 0.0, False, 60), bad, "20261015-100000", {"bot-log": 9})
    assert len(pinged) == 1, "a night that passed, and a run I started myself, ping nothing"


def test_a_night_with_nothing_to_run_still_leaves_a_line_in_the_log_channel(monkeypatch):
    said = []

    async def say(channel_id, text):
        said.append((channel_id, text))

    monkeypatch.setattr(runner, "say", say)
    monkeypatch.setattr(runner, "settings_channels", lambda: {"bot-log": 9})
    runner.quiet_night()
    assert said[0][0] == 9 and said[0][1].startswith(record.MARK) and "nothing was run" in said[0][1], "kept through the emptying, like every run's summary"


# --- keeping the self-test's cost low (2026-10-13) --------------------------------------------------------------------
from selftest import stages  # noqa: E402


def test_real_requests_are_only_for_what_can_change_what_claude_is_asked():
    for path in ("core/router.py", "core/routing.py", "core/extraction.py", "core/llm.py", "core/actions.py", "tasks/pills/plain.py", "tasks/schedule/__init__.py", "tasks\\pills\\plain.py"):
        assert stages.is_language(path), path
    for path in ("core/scheduler.py", "tasks/pills/checklist.py", "tasks/pills/sheet.py", "docs/DESIGN.md", "selftest/phases.py", "tests/test_x.py", "core/identity.py"):
        assert not stages.is_language(path), path
    assert stages.language_changed(["core/scheduler.py", "tasks/pills/plain.py", "docs/x.md"]) == ["tasks/pills/plain.py"]
    assert stages.language_changed([]) == [] and stages.language_changed(None) is None


def test_recorded_answers_are_the_rule_and_each_reason_to_pay_is_said():
    def real(**given):
        base = {"asked_real": False, "asked_recorded": False, "sunday_full": False, "language": [], "spent": 0.5, "limit": 2.0}
        return stages.use_real(**{**base, **given})

    assert real() == (False, "recorded answers: nothing about prompts, schemas or routing has changed since the last real run")
    assert real(language=["core/router.py"]) == (True, "real requests: prompts, schemas or routing changed since the last real run (core/router.py)")
    assert real(language=["a", "b", "c", "d", "e"])[1].endswith("(a, b, c and 2 more)")
    assert real(sunday_full=True) == (True, "real requests: the Sunday full run")
    assert real(asked_real=True) == (True, "real requests, as asked")
    assert real(asked_recorded=True, language=["core/router.py"], sunday_full=True) == (False, "recorded answers, as asked")
    assert real(language=None) == (True, "real requests: no run with real requests is on record")
    for reason in ({"asked_real": True}, {"sunday_full": True}, {"language": ["core/router.py"]}, {"language": None}):
        used, why = real(spent=2.0, **reason)
        assert used is False and why == "recorded answers only: this month's self-test spend is NZ$2.00, over the limit of NZ$2.00 (SELFTEST_MONTHLY_LIMIT_NZD)", "over the month's limit nothing is spent, whatever the reason"


def test_the_last_real_run_and_a_night_with_nothing_new_are_read_from_what_is_kept():
    rows = [
        {"commit": "aaa1111", "claude": "real", "note": ""}, {"commit": "bbb2222", "claude": "recorded", "note": ""},
        {"commit": "ccc3333", "claude": "real", "note": "did not finish: stopped before the end"}, {"commit": "", "claude": "real", "note": ""},
    ]
    assert stages.last_real(rows) == "aaa1111", "a run that did not finish, or has no commit, is not one to measure from"
    assert stages.last_real([]) is None
    same = {"day": "abc", "briefing": "abc", "tidy": "abc", "todos": "abc"}
    assert stages.nothing_new("abc", same) and not stages.nothing_new("def", same)
    assert not stages.nothing_new("abc", {"day": "abc", "briefing": "abc"}), "a stage that has never passed is something new"
    assert not stages.nothing_new(None, same)


def test_a_weeknight_with_no_new_commits_runs_nothing_and_leaves_its_line(monkeypatch, capsys):
    said, prepared = [], []
    monkeypatch.setattr(runner.instance_lock, "holder", lambda path: None)
    monkeypatch.setattr(runner.stages, "head", lambda root: "abc")
    monkeypatch.setattr(runner.stages, "read_passed", lambda path: {"day": "abc", "briefing": "abc", "tidy": "abc", "todos": "abc"})
    monkeypatch.setattr(runner, "quiet_night", lambda: said.append("line"))
    monkeypatch.setattr(runner, "prepare_channels", lambda *a, **k: prepared.append(1))
    monkeypatch.setattr(sys, "argv", ["selftest", "--nightly"])
    assert runner.main() == 0 and said == ["line"] and prepared == [], "no bot is started and nothing is emptied"
    assert "no new commits since every stage last passed" in capsys.readouterr().out


def test_the_self_test_s_month_is_added_up_from_its_history_and_over_the_limit_it_is_a_problem(tmp_path, monkeypatch):
    from core import attention, health

    rows = [
        {"date": "2026-09-30 03:00", "spend_usd": "0.9000"}, {"date": "2026-10-01 03:00", "spend_usd": "0.1500"},
        {"date": "2026-10-13 20:01", "spend_usd": "1.9000"}, {"date": "2026-10-14 03:00", "spend_usd": ""}, {"date": "2026-10-15 03:00", "spend_usd": "x"},
    ]
    assert health.month_spend(rows, "2026-10") == pytest.approx(2.05) and health.month_spend(rows, "2026-11") == 0
    assert health.spend_problem(1.99, 2.0) is None
    item = health.spend_problem(2.05, 2.0)
    assert item.urgency == attention.USEFUL and attention.status_line(item) == "🧪 self-test spend · NZ$2.05", "worth knowing, not something wrong"
    folder = tmp_path / "selftest"
    folder.mkdir()
    (folder / "history.csv").write_text("date,commit,ran,steps,passed,failed,failed_steps,spend_usd,claude,seconds,note\n2026-10-01 03:00,a,full,3,3,0,,1.2000,real,5,\n2026-10-13 03:00,a,full,3,3,0,,0.9000,real,5,\n", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(config, "SELFTEST_MONTHLY_LIMIT_NZD", 2.0)
    now = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
    assert health.selftest_spend(now) == (pytest.approx(2.1), 2.0)
    monkeypatch.setattr(health, "selftest_spend", lambda now=None: (2.1, 2.0))
    found = asyncio.run(health.selftest(1, now))
    assert [attention.status_line(item) for item in found] == ["🧪 self-test spend · NZ$2.10"], "live shows it when there is nothing else to show (the run itself passed)"
    assert config.SELFTEST_MONTHLY_LIMIT_NZD == 2.0


def test_dev_cost_shows_what_the_self_test_has_spent_this_month():
    from core import costs

    nothing = costs.Period() if hasattr(costs, "Period") else None
    if nothing is None:
        pytest.skip("no empty period to report on")
    said = costs.report(nothing, nothing, [], "assistant.db", selftest=(1.24, 2.0))
    assert "Self-test this month: NZ$1.24 of NZ$2.00" in said
    assert "Self-test this month: NZ$2.31 of NZ$2.00 · over the limit: recorded answers only until next month" in costs.report(nothing, nothing, [], "assistant.db", selftest=(2.31, 2.0))
    assert "Self-test" not in costs.report(nothing, nothing, [], "assistant.db")
