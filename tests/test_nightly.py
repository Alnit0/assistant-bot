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
    assert config.NIGHTLY_SELFTEST is False, "off by default"
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
    assert (default.name, default.at, default.locked, default.channel) == ("Nightly self-test", time(3, 0), False, "bot-log"), "3:00 am, and mine to move with `my schedule`"
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
