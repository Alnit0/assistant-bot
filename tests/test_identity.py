"""Who the bot is seen to be (core/identity.py): its nickname in the server and its status
line. The words are pure; the Discord work runs against a fake member and client."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import clock, devmode, discord_utils, identity, scheduler

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)  # 9:00 pm in NZ
NONE = timedelta(0)


def run(coroutine):
    return asyncio.run(coroutine)


def job(task, kind, due_in):
    return scheduler.Job(1, None, task, kind, {}, NOW + due_in)


# ---------------------------------------------------------------------------
# The nickname (pure)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, state, wanted",
    [
        ("Hive", "", "Hive"),
        ("  Hive ", "", "Hive"),
        ("Hive", "testing", "Hive · testing"),  # a real state, always "Name · state"
        ("", "testing", ""),  # no name given: the nickname is left alone
        ("A" * 40, "", "A" * 32),  # Discord allows 32 characters
        ("A" * 32, "testing", "A" * 22 + " · testing"),
    ],
)
def test_the_nickname_is_the_name_it_was_given_with_a_suffix_only_for_a_real_state(name, state, wanted):
    assert identity.nickname(name, state) == wanted
    assert len(wanted) <= identity.MAX_NICKNAME


# ---------------------------------------------------------------------------
# The status line (pure)
# ---------------------------------------------------------------------------
def test_live_s_status_line_is_the_top_attention_item_and_nothing_else():
    assert identity.status_line(False, NONE, "💊 2/5 · 12pm") == "💊 2/5 · 12pm"
    assert identity.status_line(False, NONE, "⚠️ B14 · backup failed") == "⚠️ B14 · backup failed"
    assert identity.status_line(False, NONE, "") == "", "nothing to look at: a blank status line"
    assert "Live" not in identity.status_line(False, NONE, "🌅 6am") and "up " not in identity.status_line(False, NONE, "🌅 6am"), "no “Live”, no uptime: the presence dot says it is on"


@pytest.mark.parametrize("seconds, said", [(0, "0m"), (59 * 60, "59m"), (3600, "1h"), (47 * 3600, "47h"), (49 * 3600, "2d")])
def test_uptime_is_one_unit(seconds, said):
    assert identity.uptime(seconds) == said, "still used where a late job is said (and by `dev status`)"


def test_the_dev_bot_says_which_database_and_how_far_the_clock_is_moved():
    assert identity.status_line(True, NONE, "💊 due 12pm") == "🧪 DEV database", "outside a self-test it says which bot it is, not what is due"
    assert identity.status_line(True, timedelta(hours=13)) == "🧪 DEV database · clock +13h"
    assert identity.status_line(True, timedelta(hours=1, minutes=30)) == "🧪 DEV database · clock +1h 30m"


def test_the_dev_bot_in_a_self_test_says_how_far_the_run_is():
    assert identity.selftest_line(41, 103, 6) == "🧪 41/103 · 6m"
    assert identity.selftest_line(41, 103, 6, 2) == "🧪 41/103 · 6m · ❌2", "once steps fail"
    assert identity.selftest_line(41, 0, 6) == "🧪 41 · 6m", "the number of steps is not known the first time"
    assert identity.selftest_line(103, 103, -2) == "🧪 103/103 · 0m", "a run that takes longer than expected is never minus two minutes"
    assert identity.status_line(True, timedelta(hours=13), "", progress="🧪 41/103 · 6m") == "🧪 41/103 · 6m"
    assert identity.status_line(True, NONE, "", "4:15 pm", "🧪 41/103 · 6m") == "🧪 Self-test running · back about 4:15 pm", "a run on live's own account says when live is back, before anything"


def test_dev_mode_is_no_longer_a_mark_in_front_and_the_line_fits_discord():
    import inspect

    assert "dev_mode" not in inspect.signature(identity.status_line).parameters, "dev mode on live is a level 1 item of its own (core/health.py)"
    assert len(identity.status_line(False, NONE, "x" * 300)) == identity.MAX_STATUS


# ---------------------------------------------------------------------------
# Discord's side
# ---------------------------------------------------------------------------
class Member:
    def __init__(self, nick=None, may=True, refuse=False):
        self.nick, self.name = nick, "hive-bot"
        self.guild_permissions = SimpleNamespace(change_nickname=may)
        self.edits, self.refuse = [], refuse

    async def edit(self, nick=None, reason=None):
        if self.refuse:
            import discord

            raise discord.HTTPException(SimpleNamespace(status=403, reason="No"), {"code": 50013, "message": "Missing Permissions"})
        self.edits.append(nick)
        self.nick = nick


@pytest.fixture
def server(monkeypatch):
    seen = SimpleNamespace(member=Member("Hive"), logged=[], presence=[])

    async def change_presence(activity=None):
        seen.presence.append(activity.name if activity is not None else None)  # None: the status line is blank

    async def log_simple(title, description=None):
        seen.logged.append((title, description))

    client = SimpleNamespace(
        get_channel=lambda channel_id: SimpleNamespace(guild=SimpleNamespace(me=seen.member)), change_presence=change_presence,
    )
    monkeypatch.setattr(discord_utils, "client", client)
    monkeypatch.setattr(identity, "log_simple", log_simple)
    monkeypatch.setattr(identity, "_shown", None)
    return seen


def _named(monkeypatch, name, state=""):
    monkeypatch.setattr(identity.config, "BOT_NAME", name)
    monkeypatch.setattr(identity.config, "NAME_STATE", state)


def test_a_bot_that_already_has_its_name_is_left_alone(server, monkeypatch):
    _named(monkeypatch, "Hive")
    assert run(identity.set_nickname()) == "already Hive"
    assert server.member.edits == [] and server.logged == []


def test_on_start_the_bot_takes_the_name_it_was_given_whatever_it_was_called(server, monkeypatch):
    server.member = Member("Hive · DEV")  # the old marker goes with the first start
    _named(monkeypatch, "Hive")
    assert run(identity.set_nickname()) == "Hive · DEV -> Hive"
    server.member = Member(None)  # no nickname yet
    assert run(identity.set_nickname()) == "hive-bot -> Hive"


def test_the_dev_bot_says_testing_during_a_self_test_and_is_plain_again_after(server, monkeypatch):
    _named(monkeypatch, "Hive", "testing")
    assert run(identity.set_nickname()) == "Hive -> Hive · testing"
    assert run(identity.set_nickname()) == "already Hive · testing"
    _named(monkeypatch, "Hive")
    assert run(identity.set_nickname()) == "Hive · testing -> Hive"
    assert server.member.edits == ["Hive · testing", "Hive"] and server.logged == []


def test_with_no_name_given_nothing_is_renamed(server, monkeypatch):
    server.member = Member("Whatever I called it")
    _named(monkeypatch, "", "testing")
    assert run(identity.set_nickname()) == "left as it is (BOT_NAME is not set)" and server.member.edits == []


def test_without_change_nickname_it_says_so_once_in_bot_log_and_changes_nothing(server, monkeypatch):
    server.member = Member("Old", may=False)
    _named(monkeypatch, "Hive")
    assert run(identity.set_nickname()) == "Change Nickname is missing"
    assert server.member.edits == []
    ((title, said),) = server.logged
    assert title == "🏷️ Nickname not changed" and "**Change Nickname**" in said and "**Hive**" in said
    server.member = Member("Hive", may=False)
    run(identity.set_nickname())
    assert len(server.logged) == 1, "nothing to change: nothing more is said"


def test_a_name_discord_refuses_is_reported_not_raised(server, monkeypatch):
    server.member = Member("Old", refuse=True)
    _named(monkeypatch, "Hive")
    assert run(identity.set_nickname()) == "refused by Discord"
    assert server.logged[0][0] == "🏷️ Nickname not changed"


def test_only_the_dev_bot_in_a_self_test_has_a_state_in_its_name():
    assert identity.config.NAME_STATE == "", "this is not a self-test's bot"
    assert identity.STATE_MARK == " · "


@pytest.fixture
def looking(server, db, dev_off, monkeypatch, owner):
    """Live, with attention items handed in by the test."""
    held = SimpleNamespace(items=[], now=NOW)

    async def gather(user_id, now):
        return list(held.items)

    async def who(discord_id):
        return owner

    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    monkeypatch.setattr(identity, "SELFTEST_BACK", "")
    monkeypatch.setattr(identity, "_progress", "")
    monkeypatch.setattr(identity, "_wake", None)
    monkeypatch.setattr(identity.attention, "gather", gather)
    monkeypatch.setattr(identity, "get_user_by_discord_id", who)
    monkeypatch.setattr(clock, "now", lambda: held.now)
    held.server = server
    return held


def _item(short, urgency, minutes=None, **more):
    from core.attention import Item

    return Item("x", urgency, when=NOW + timedelta(minutes=minutes) if minutes is not None else None, short=short, icon=more.pop("icon", "💊"), **more)


def test_the_status_line_is_only_sent_when_it_reads_differently_and_blank_is_no_status(looking):
    from core.attention import TIMED

    async def scenario():
        looking.items = [_item(("2/5", "9:30pm"), TIMED, 30)]
        first = await identity.refresh()
        again = await identity.refresh()
        looking.items = [_item(("due 9:30pm",), TIMED, 0)]
        third = await identity.refresh()
        looking.items = []
        fourth = await identity.refresh()
        return first, again, third, fourth

    assert run(scenario()) == (True, False, True, True)
    assert looking.server.presence == ["💊 2/5 · 9:30pm", "💊 due 9:30pm", None], "nothing to look at clears the status line"


def test_it_looks_again_at_the_moment_the_next_timed_item_falls_due_and_never_on_a_ticker(looking, monkeypatch):
    from core.attention import TIMED

    waits = []

    class Loop:
        def call_later(self, seconds, callback):
            waits.append((round(seconds), callback))
            return SimpleNamespace(cancel=lambda: waits.append("cancelled"))

    monkeypatch.setattr(identity.asyncio, "get_running_loop", lambda: Loop())
    looking.items = [_item(("2/5", "9:30pm"), TIMED, 30), _item(("3/5", "10pm"), TIMED, 60)]
    run(identity.refresh())
    assert waits == [(30 * 60 + 1, identity.look_again)], "one wait, for the soonest item still to come"
    looking.items = []
    run(identity.refresh())
    assert waits[1] == "cancelled" and waits[2] == (3 * 3600 + 1, identity.look_again), "with nothing timed left, the end of the day (9 pm now: three hours)"
    assert not hasattr(identity, "EVERY_SECONDS") and not hasattr(identity, "_loop"), "there is no ticker any more"


def test_a_failed_job_shows_until_its_next_run_works(server, db, dev_off, monkeypatch, owner):
    from core import attention, health

    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    monkeypatch.setattr(identity, "_progress", "")
    monkeypatch.setattr(identity, "_wake", None)
    monkeypatch.setattr(attention, "_providers", {})
    monkeypatch.setattr(attention, "_listeners", [])
    monkeypatch.setattr(scheduler, "_after_run", [])
    told = []
    health.setup()
    attention.on_change(lambda: told.append(1))

    async def who(discord_id):
        return owner

    monkeypatch.setattr(identity, "get_user_by_discord_id", who)

    async def no_log(*args):
        pass

    monkeypatch.setattr(scheduler, "log_error", no_log)
    monkeypatch.setattr(scheduler, "RETRY_AFTER", timedelta(0))  # its one second try runs in the same pass, and fails too
    outcome = {"fail": True}

    async def handler(job):
        if outcome["fail"]:
            raise OSError("disk full")

    scheduler.register_handler("core", "nightly_backup", handler, "nightly backup")

    async def scenario():
        await scheduler.add_job("core", "nightly_backup", scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()
        await identity.refresh()
        outcome["fail"] = False
        await scheduler.add_job("core", "nightly_backup", scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()
        await identity.refresh()

    run(scenario())
    assert server.presence == ["⚠️ backup failed", None], "it stays until that job next works; then there is nothing to say"
    assert len(told) >= 2, "a pass that ran a job says the items may have changed"


def test_a_status_discord_refuses_never_raises(server, db, dev_off, monkeypatch):
    async def broken(activity=None):
        raise RuntimeError("gateway closed")

    monkeypatch.setattr(discord_utils.client, "change_presence", broken)
    assert run(identity.refresh()) is False


def test_the_dev_bot_s_own_line_is_its_last_self_test_and_the_month_s_spend_and_live_s_never_is(monkeypatch):
    from datetime import timedelta

    from core import config, identity

    monkeypatch.setattr(config, "USD_TO_NZD", 1.0)
    row = {"steps": "150", "passed": "149", "failed": "0", "note": ""}
    assert identity.dev_line(row, 3.64, 3.50) == "✅ 149/150 · NZ$3.64 of NZ$3.50"
    assert identity.dev_line({**row, "failed": "2", "passed": "147"}, 0.0, 3.5).startswith("❌ 147/150")
    assert identity.dev_line(None, 0.0, 3.5) == "🧪 no self-test yet · NZ$0.00 of NZ$3.50"
    said = identity.dev_line(row, 3.64, 3.50)
    assert identity.status_line(True, timedelta(hours=13), dev_said=said) == said + " · clock +13h"
    assert identity.status_line(False, timedelta(0), top="💊 due 8pm", dev_said=said) == "💊 due 8pm", "live's line never has it"
