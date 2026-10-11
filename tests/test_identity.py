"""Who the bot is seen to be (core/identity.py): its nickname in the server and its status
line. The words are pure; the Discord work runs against a fake member and client."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import clock, devmode, discord_utils, identity, scheduler, tidy

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
    "current, dev, wanted",
    [
        ("Hive", False, "Hive"),
        ("Hive", True, "Hive · DEV"),
        ("Hive · DEV", True, "Hive · DEV"),  # started on dev twice: marked once
        ("Hive · DEV", False, "Hive"),  # back on live: the base name again
        ("Hive · DEV · DEV", False, "Hive"),
        ("A" * 32, True, "A" * 26 + " · DEV"),  # Discord allows 32 characters
    ],
)
def test_the_nickname_is_the_base_name_on_live_and_marked_on_dev(current, dev, wanted):
    assert identity.nickname(current, dev) == wanted
    assert len(wanted) <= identity.MAX_NICKNAME


# ---------------------------------------------------------------------------
# The status line (pure)
# ---------------------------------------------------------------------------
def test_live_says_how_long_it_has_been_up_and_what_runs_next():
    pending = [job(tidy.JOB_TASK, tidy.JOB_KIND, timedelta(seconds=5)), job("core", "nightly_backup", timedelta(hours=6)), job("pills", "checklist", timedelta(hours=9))]
    next_up = identity.next_job(pending, NOW)
    assert next_up == "nightly backup 3:00 am", "a line being tidied away is not worth naming"
    assert identity.status_line(False, 7 * 3600 + 120, next_up, NONE) == "🟢 Live · up 7h · next: nightly backup 3:00 am"
    assert identity.status_line(False, 60, "", NONE) == "🟢 Live · up 1m", "nothing booked: nothing said about it"


def test_a_job_more_than_a_day_off_is_named_with_its_day_and_a_tasks_job_with_its_task():
    assert identity.next_job([job("pills", "checklist", timedelta(hours=33))], NOW) == "pills checklist Wed 6:00 am"
    assert identity.next_job([], NOW) == ""


@pytest.mark.parametrize("seconds, said", [(0, "0m"), (59 * 60, "59m"), (3600, "1h"), (47 * 3600, "47h"), (49 * 3600, "2d")])
def test_uptime_is_one_unit(seconds, said):
    assert identity.uptime(seconds) == said


def test_dev_says_so_and_how_far_the_clock_is_moved():
    assert identity.status_line(True, 3600, "nightly backup 3:00 am", NONE) == "🧪 DEV database"
    assert identity.status_line(True, 3600, "", timedelta(hours=13)) == "🧪 DEV database · clock +13h"
    assert identity.status_line(True, 3600, "", timedelta(hours=1, minutes=30)) == "🧪 DEV database · clock +1h 30m"


def test_a_job_that_failed_or_was_skipped_takes_the_line_over():
    trouble = [("core", "nightly_backup", "failed"), ("pills", "checklist", "skipped")]
    assert identity.status_line(False, 3600, "x", NONE, trouble[1:]) == "⚠️ pills checklist skipped · see #bot-log"
    assert identity.status_line(True, 3600, "x", timedelta(hours=2), trouble) == "⚠️ nightly backup failed (+1 more) · see #bot-log"


def test_dev_mode_is_said_in_front_and_the_line_fits_discord():
    assert identity.status_line(False, 7200, "", NONE, dev_mode=True) == "🛠️ Dev mode · 🟢 Live · up 2h"
    assert len(identity.status_line(False, 7200, "x" * 300, NONE)) == identity.MAX_STATUS


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
        seen.presence.append(activity.name)

    async def log_simple(title, description=None):
        seen.logged.append((title, description))

    client = SimpleNamespace(
        get_channel=lambda channel_id: SimpleNamespace(guild=SimpleNamespace(me=seen.member)), change_presence=change_presence,
    )
    monkeypatch.setattr(discord_utils, "client", client)
    monkeypatch.setattr(identity, "log_simple", log_simple)
    monkeypatch.setattr(identity, "_shown", None)
    return seen


def test_on_live_a_base_name_is_left_alone(server, monkeypatch):
    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    assert run(identity.set_nickname()) == "already Hive"
    assert server.member.edits == [] and server.logged == []


def test_on_dev_the_name_is_marked_and_back_on_live_it_is_the_base_name_again(server, monkeypatch):
    monkeypatch.setattr(identity, "DEV_DATABASE", True)
    assert run(identity.set_nickname()) == "Hive -> Hive · DEV"
    assert run(identity.set_nickname()) == "already Hive · DEV", "the name it has at the start is read each time"
    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    assert run(identity.set_nickname()) == "Hive · DEV -> Hive"
    assert server.member.edits == ["Hive · DEV", "Hive"] and server.logged == []


def test_with_no_nickname_the_base_is_the_bots_own_name(server, monkeypatch):
    server.member = Member(None)
    monkeypatch.setattr(identity, "DEV_DATABASE", True)
    run(identity.set_nickname())
    assert server.member.edits == ["hive-bot · DEV"]


def test_without_change_nickname_it_says_so_once_in_bot_log_and_changes_nothing(server, monkeypatch):
    server.member = Member("Hive", may=False)
    monkeypatch.setattr(identity, "DEV_DATABASE", True)
    assert run(identity.set_nickname()) == "Change Nickname is missing"
    assert server.member.edits == []
    ((title, said),) = server.logged
    assert title == "🏷️ Nickname not changed" and "**Change Nickname**" in said and "**Hive · DEV**" in said
    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    run(identity.set_nickname())
    assert len(server.logged) == 1, "nothing to change on live: nothing more is said"


def test_a_name_discord_refuses_is_reported_not_raised(server, monkeypatch):
    server.member = Member("Hive", refuse=True)
    monkeypatch.setattr(identity, "DEV_DATABASE", True)
    assert run(identity.set_nickname()) == "refused by Discord"
    assert server.logged[0][0] == "🏷️ Nickname not changed"


def test_the_status_is_only_sent_when_it_reads_differently(server, db, dev_off, monkeypatch):
    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    monkeypatch.setattr(identity.about, "STARTED", clock.real_now() - timedelta(hours=7, minutes=5))

    async def scenario():
        await scheduler.add_job("core", "nightly_backup", NOW.replace(year=2030, hour=14))  # 3:00 am NZ
        first = await identity.refresh()
        again = await identity.refresh()
        devmode.enable()
        third = await identity.refresh()
        return first, again, third

    assert run(scenario()) == (True, False, True)
    assert server.presence == ["🟢 Live · up 7h · next: nightly backup Sun 3:00 am", "🛠️ Dev mode · 🟢 Live · up 7h · next: nightly backup Sun 3:00 am"]


def test_a_failed_job_shows_until_its_next_run_works(server, db, dev_off, monkeypatch):
    monkeypatch.setattr(identity, "DEV_DATABASE", False)
    monkeypatch.setattr(identity.about, "STARTED", clock.real_now())

    async def no_log(*args):
        pass

    monkeypatch.setattr(scheduler, "log_error", no_log)
    outcome = {"fail": True}

    async def handler(job):
        if outcome["fail"]:
            raise OSError("disk full")

    scheduler.register_handler("core", "nightly_backup", handler)

    async def scenario():
        await scheduler.add_job("core", "nightly_backup", scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()
        await identity.refresh()
        outcome["fail"] = False
        await scheduler.add_job("core", "nightly_backup", scheduler.utc_now() - timedelta(minutes=1))
        await scheduler.run_all_due()
        await identity.refresh()

    run(scenario())
    assert server.presence == ["⚠️ nightly backup failed · see #bot-log", "🟢 Live · up 0m"]


def test_a_status_discord_refuses_never_raises(server, db, dev_off, monkeypatch):
    async def broken(activity=None):
        raise RuntimeError("gateway closed")

    monkeypatch.setattr(discord_utils.client, "change_presence", broken)
    assert run(identity.refresh()) is False
