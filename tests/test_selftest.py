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
    assert names == ["p1", "p2", "p3", "p4", "p5"] == list(phases.PHASES)
    looks = [settings["CARDS_V2"] for _, settings, _ in runner.PHASES]
    assert looks[:4] == ["false", "false", "true", "false"], "off, a restart, on, and back off"
    assert [settings.get("BRIEFING_ENABLED", "false") for _, settings, _ in runner.PHASES] == ["false", "false", "false", "false", "true"], "the briefing off, then on"
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
