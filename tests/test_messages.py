"""Message lifetimes and the tidy that keeps the hub clean (core/messages.py), behind HUB_TIDY."""
import asyncio
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

from core import clock, config, database, day, devmode, discord_utils, hub, messages, scheduler
from core.messages import DAY, EXPIRY, KEPT, REPLACED

HUB, INBOX = 400, 100


def run(coroutine):
    return asyncio.run(coroutine)


class Message:
    def __init__(self, channel, message_id, said, author="Assistant"):
        self.channel, self.id, self.content = channel, message_id, said
        self.author = SimpleNamespace(display_name=author)
        self.created_at = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)
        self.pinned, self.reactions, self.components, self.embeds = False, [], [], []

    async def delete(self):
        if self.id in self.channel.stuck:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        self.channel.deleted.append(self.id)
        del self.channel.messages[self.id]


class Channel:
    def __init__(self, channel_id, name):
        self.id, self.name, self.messages, self.deleted, self.stuck = channel_id, name, {}, [], set()

    def say(self, message_id, said, author="Assistant"):
        self.messages[message_id] = Message(self, message_id, said, author)
        return message_id

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.messages[message_id]


@pytest.fixture
def world(db, dev_clock, dev_off, monkeypatch, tmp_path):
    """The tidy switched on, a hub and an inbox that remember what was deleted, and noon tomorrow."""
    seen = SimpleNamespace(hub=Channel(HUB, "hub"), inbox=Channel(INBOX, "inbox"), bot_log=[], exports=tmp_path / "exports")
    channels = {HUB: seen.hub, INBOX: seen.inbox}

    async def log_simple(title, description=None):
        seen.bot_log.append((title, description))

    monkeypatch.setattr(config, "HUB_TIDY", True)
    monkeypatch.setattr(config, "EXPORTS_DIR", seen.exports)
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=channels.get))
    monkeypatch.setattr(discord_utils, "log_simple", log_simple)
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_labels", {})
    seen.day = day.today() + timedelta(days=1)
    clock.advance_to(day.at(seen.day, time(12, 0)))
    return seen


def rows():
    conn = database.connect()
    try:
        return {row[0]: row[1:] for row in conn.execute("SELECT message_id, lifetime, slot, exchange, mine, waits, gone_at IS NOT NULL, why FROM bot_messages")}
    finally:
        conn.close()


def copy(world, name="hub"):
    found = sorted(world.exports.glob(f"tidy-{name}-*.txt"))
    return found[-1].read_text(encoding="utf-8") if found else ""


# --- recording ---------------------------------------------------------------------------------------------------
def test_switched_off_nothing_is_recorded_and_nothing_is_ever_removed(world, monkeypatch):
    monkeypatch.setattr(config, "HUB_TIDY", False)
    run(messages.record(world.hub.say(1, "a line"), HUB))
    run(messages.begin(world.hub.say(2, "took zinc", "Alex"), HUB, 1))
    run(messages.handled(2))
    clock.advance(timedelta(days=2))
    done = run(messages.tidy())
    assert rows() == {} and world.hub.deleted == [] and (done.removed, done.problems) == (0, ())
    messages.setup()
    assert scheduler._handlers == {} and scheduler.routine_steps(hub.MORNING) == (hub.MORNING,), "and it joins no routine"


def test_in_the_hub_a_message_lasts_the_day_and_elsewhere_only_what_is_declared_is_recorded(world):
    run(messages.record(world.hub.say(1, "a line"), HUB))
    run(messages.record(world.hub.say(2, "kept, it says"), HUB, lifetime=KEPT))
    run(messages.record(world.inbox.say(3, "an answer"), INBOX))
    run(messages.record(world.inbox.say(4, "a line that reports a change"), INBOX, lifetime=DAY))
    found = rows()
    assert sorted(found) == [1, 2, 4], "one in #inbox with nothing declared has no row: it is never touched"
    assert found[1][0] == DAY and found[2][0] == DAY and found[4][0] == DAY, "in the hub nothing is kept: “kept” there is the end of the day"


# --- replaced ----------------------------------------------------------------------------------------------------
def test_a_newer_message_in_the_same_slot_takes_the_place_of_the_older_at_once(world):
    run(messages.record(world.hub.say(10, "## 💊 Pills · yesterday"), HUB, lifetime=REPLACED, slot="pills.checklist"))
    assert world.hub.deleted == [], "one alone replaces nothing"
    run(messages.record(world.hub.say(11, "## 💊 Pills · today"), HUB, lifetime=REPLACED, slot="pills.checklist"))
    assert world.hub.deleted == [10] and 11 in world.hub.messages, "the new one was up first, then the old went"
    assert rows()[10][5:] == (1, "replaced") and "## 💊 Pills · yesterday" in copy(world), "what it said was written down first"
    run(messages.record(world.hub.say(12, "☀️ Today"), HUB, lifetime=REPLACED, slot="briefing"))
    assert world.hub.deleted == [10], "another slot is another thing"


# --- what is said in the hub -------------------------------------------------------------------------------------
def test_my_message_in_the_hub_and_the_reply_go_two_minutes_after_the_reply(world):
    run(_exchange(world, 20, "took zinc", reply=(21, "✅ **Zinc** · taken 12:00 pm")))
    found = rows()
    assert found[20][:4] == (EXPIRY, "", None, 1) and found[21][:4] == (EXPIRY, "", 20, 0), "the reply is tied to what it answers"
    (job,) = run(scheduler.pending_jobs("core", messages.EXPIRY_KIND))
    assert abs((job.due_at - clock.now()) - messages.AFTER_REPLY) < timedelta(seconds=1)
    clock.advance(timedelta(minutes=1, seconds=59))
    assert run(messages.tidy(expiry_only=True)).removed == 0 and world.hub.deleted == []
    clock.advance(timedelta(seconds=2))
    done = run(messages.tidy(expiry_only=True))
    assert done.removed == 2 and world.hub.deleted == [20, 21] and world.bot_log == [], "gone, and nothing is said about it anywhere"
    said = copy(world)
    assert "Alex\ntook zinc" in said and "Assistant\n✅ **Zinc** · taken 12:00 pm" in said


async def _exchange(world, mine, said, reply=None, failed=False):
    """A message of mine in the hub, handled: as main.on_message does it."""
    world.hub.say(mine, said, "Alex")
    await messages.begin(mine, HUB, 1)
    if reply is not None:
        await messages.record(world.hub.say(*reply), HUB)
    await messages.handled(mine, failed)


def test_the_same_in_another_channel_is_left_alone(world):
    async def said():
        world.inbox.say(30, "took zinc", "Alex")
        await messages.begin(30, INBOX, 1)
        await messages.record(world.inbox.say(31, "✅ taken"), INBOX)
        await messages.handled(30)

    run(said())
    clock.advance(timedelta(days=1))
    assert rows() == {} and run(messages.tidy()).removed == 0 and world.inbox.deleted == []


def test_with_a_card_they_wait_for_it_and_go_when_it_is_saved_cancelled_or_expires(world):
    async def asked(mine, card):
        world.hub.say(mine, "add zinc", "Alex")
        await messages.begin(mine, HUB, 1)
        await messages.record(world.hub.say(card, "💊 Pills · new"), HUB)
        await messages.card_opened(card)
        await messages.handled(mine)

    run(asked(40, 41))
    clock.advance(timedelta(minutes=10))
    assert run(messages.tidy(expiry_only=True)).removed == 0, "ten minutes on, the card is still open: nothing goes"
    # Saved: my message goes at once, the card (now its confirmation) two minutes later
    run(messages.card_closed(41, saved=True))
    assert run(messages.tidy(expiry_only=True)).removed == 1 and world.hub.deleted == [40]
    clock.advance(timedelta(minutes=2, seconds=1))
    assert run(messages.tidy(expiry_only=True)).removed == 1 and world.hub.deleted == [40, 41]
    # Cancelled, or expired: the card is taken away by the card's own code, and my message goes
    run(asked(42, 43))
    del world.hub.messages[43]
    run(messages.card_closed(43, saved=False))
    assert run(messages.tidy(expiry_only=True)).removed == 1 and world.hub.deleted == [40, 41, 42] and rows()[43][5:] == (1, "its card was closed")


def test_one_that_failed_keeps_its_mark_until_the_morning_tidy_and_one_with_no_reply_goes_after_two_minutes(world):
    run(_exchange(world, 50, "do the thing", failed=True))
    run(_exchange(world, 51, "nice weather"))
    clock.advance(timedelta(minutes=3))
    assert run(messages.tidy(expiry_only=True)).removed == 1 and world.hub.deleted == [51], "a remark that needed no reply"
    assert rows()[50][0] == DAY
    clock.advance_to(day.at(world.day + timedelta(days=1), time(6, 0)))
    assert run(messages.tidy()).removed == 1 and world.hub.deleted == [51, 50], "nothing from a past day stays"


# --- the three rules, and what deleting does -----------------------------------------------------------------------
def test_pinned_or_marked_is_always_kept_and_not_tried_again(world):
    run(_exchange(world, 60, "what's left?", reply=(61, "💊 2 to take")))
    world.hub.messages[61].pinned = True
    world.hub.messages[60].reactions = [SimpleNamespace(emoji="📌", count=1)]
    clock.advance(timedelta(minutes=3))
    done = run(messages.tidy(expiry_only=True))
    assert (done.removed, done.kept) == (0, 2) and world.hub.deleted == [] and done.line() == "0 removed · 2 kept (📌)"
    assert rows()[61][0] == KEPT and rows()[60][0] == KEPT
    clock.advance(timedelta(days=3))
    assert run(messages.tidy()).kept == 0 and world.hub.deleted == [], "kept: it is not looked at again"


def test_a_message_with_no_row_is_never_touched(world):
    world.hub.say(70, "from before this system")
    world.hub.say(71, "a timer's card, sent some other way")
    run(messages.record(world.hub.say(72, "recorded"), HUB))
    clock.advance(timedelta(days=2))
    assert run(messages.tidy()).removed == 1 and world.hub.deleted == [72] and sorted(world.hub.messages) == [70, 71]


def test_with_the_copy_not_written_nothing_is_deleted_and_bot_log_is_told(world, monkeypatch):
    def broken(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(messages, "_write", broken)
    run(messages.record(world.hub.say(80, "a line"), HUB))
    clock.advance(timedelta(days=1))
    done = run(messages.tidy())
    assert (done.removed, done.left) == (0, 1) and world.hub.deleted == [] and rows()[80][5] == 0
    ((title, said),) = world.bot_log
    assert title == "🧹 Tidy · something could not be removed" and "the copy could not be saved (disk full), so nothing was removed there" in said
    assert "Nothing was changed in the database" in said


def test_one_that_cannot_be_deleted_is_tried_three_times_then_left_and_the_others_still_go(world):
    run(messages.record(world.hub.say(90, "stuck"), HUB))
    run(messages.record(world.hub.say(91, "fine"), HUB))
    world.hub.stuck.add(90)
    clock.advance(timedelta(days=1))
    first = run(messages.tidy())
    assert (first.removed, first.left) == (1, 1) and world.hub.deleted == [91] and world.bot_log == [], "not said yet: it is tried again"
    run(messages.tidy())
    third = run(messages.tidy())
    assert third.left == 1 and len(world.bot_log) == 1 and "after 3 tries" in world.bot_log[0][1] and rows()[90][0] == KEPT
    assert run(messages.tidy()).left == 0 and len(world.bot_log) == 1, "said once, then left"


def test_one_already_gone_counts_as_gone_and_dev_cleanup_off_stops_all_of_it(world, monkeypatch):
    run(messages.record(100, HUB))  # never in the channel: deleted by hand, say
    run(messages.record(world.hub.say(101, "a line"), HUB))
    clock.advance(timedelta(days=1))
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: False)
    off = run(messages.tidy())
    assert off.removed == 0 and off.problems == ("clean-up is switched off (`dev cleanup off`): nothing was removed",) and world.hub.deleted == []
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: True)
    assert run(messages.tidy()).removed == 1 and rows()[100][5:] == (1, "already gone")


def test_a_line_that_reports_a_change_outside_the_hub_goes_at_the_end_of_its_day(world):
    run(messages.record(world.inbox.say(110, "✅ Saved · 💊 **Zinc**"), INBOX, lifetime=DAY))
    assert run(messages.tidy()).removed == 0, "today it stays"
    clock.advance_to(day.at(world.day + timedelta(days=1), time(6, 0)))
    assert run(messages.tidy()).removed == 1 and world.inbox.deleted == [110] and "✅ Saved" in copy(world, "inbox")


# --- the tidy as a job -------------------------------------------------------------------------------------------
def test_switched_on_the_tidy_is_the_first_step_of_the_morning_routine_and_says_what_it_did(world):
    messages.setup()
    assert scheduler.routine_steps(hub.MORNING) == ("core.hub_tidy", hub.MORNING)
    scheduler.join_routine(hub.MORNING, "briefing.post", order=hub.BRIEFING_ORDER, name=hub.MORNING_NAME)
    assert scheduler.routine_steps(hub.MORNING) == ("core.hub_tidy", "briefing.post", hub.MORNING), "tidy, briefing, checklist"
    assert scheduler.label("core", messages.TIDY_KIND) == "morning tidy"
    run(messages.record(world.hub.say(120, "yesterday's line"), HUB))
    clock.advance_to(day.at(world.day + timedelta(days=1), time(6, 0)))
    job = scheduler.Job(7, None, "core", messages.TIDY_KIND, {}, clock.now())
    run(messages.tidy_job(job))
    assert scheduler._notes.pop(7) == "1 removed" and world.bot_log == [] and 7 not in scheduler._reported
