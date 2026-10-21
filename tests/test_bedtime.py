"""The bedtime nudge (tasks/bedtime), behind BEDTIME_ENABLED: set in words (a weekend's midnight its own row, on
the next morning), the wind-down message with what is open tonight and tomorrow's first thing, an earlier
bedtime when tomorrow starts early (never more than an hour earlier), nothing open, goodnight before the nudge,
the diary's ask folded in, the line at bedtime once, a neutral lock screen through quiet hours. Made-up data."""
import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, hub, live, notify, planning, scheduler, timetable
from core import day as days
from core.actions import Request
from core.planning import Piece
import tasks.bedtime as bedtime

HUB = 400


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


def at(day, hour, minute=0):
    return days.at(day, time(hour, minute))


# --- pure -----------------------------------------------------------------------------------------------------------------
def test_a_night_runs_to_4_am_and_a_midnight_bedtime_is_the_next_morning():
    friday = date(2026, 10, 23)
    assert bedtime.night_of(at(friday + timedelta(days=1), 0, 30)) == friday
    assert bedtime.bed_moment(friday, time(0, 0)) == at(friday + timedelta(days=1), 0, 0)
    assert bedtime.bed_moment(friday, time(23, 0)) == at(friday, 23, 0)


def test_an_earlier_bedtime_when_tomorrow_starts_early_never_more_than_an_hour():
    night = date(2026, 10, 21)
    bed = at(night, 23, 0)
    assert bedtime.earlier(bed, at(night + timedelta(days=1), 9, 0)) is None, "8 hours and 45 minutes: fine"
    assert bedtime.earlier(bed, at(night + timedelta(days=1), 7, 30)) == at(night, 22, 45), "7:30 start: up 6:45, bed 10:45"
    assert bedtime.earlier(bed, at(night + timedelta(days=1), 5, 0)) == at(night, 22, 0), "never more than an hour earlier"
    assert bedtime.earlier(bed, None) is None


def test_the_wind_down_words_with_nothing_open():
    night = date(2026, 10, 21)
    lines = bedtime.wind_down_text(at(night, 23), [], ("🗓️ Made-up standup", at(night + timedelta(days=1), 9)), None)
    assert lines == ["🌙 Wind down · bed at 11:00 pm", "-# tomorrow: 🗓️ Made-up standup 9:00 am"]


# --- in words, and its schedule rows ------------------------------------------------------------------------------------------
@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"bedtime": bedtime.MIGRATIONS})
    monkeypatch.setattr(config, "BEDTIME_ENABLED", True)
    monkeypatch.setattr(config, "DIARY_ENABLED", False)
    monkeypatch.setattr(config, "OWNER_ID", owner.discord_id)
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    seen = SimpleNamespace(owner=owner, posted=[], edited=[], notes=[], pieces={})

    async def post(kind, channel, card, **more):
        seen.posted.append((kind, card.text))
        return 900 + len(seen.posted)

    async def edit(channel_id, message_id, card):
        seen.edited.append(card)
        return True

    async def gather(user_id, day):
        return seen.pieces.get(day, [])

    async def book():
        return None

    monkeypatch.setattr(notify, "post", post)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(planning, "gather", gather)
    monkeypatch.setattr(scheduler, "book", book)
    monkeypatch.setattr(scheduler, "note", lambda job, line: seen.notes.append(line))
    seen.day = date(2026, 10, 21) if days.today() < date(2026, 10, 21) else days.today() + timedelta(days=(2 - days.today().weekday()) % 7 or 7)
    seen.request = lambda text="said": Request(owner, HUB, text)
    return seen


def set_bedtime(world, items, wind_down=None):
    proposal = run(bedtime.set_card(world.request(), {"bedtimes": items, **({"wind_down": wind_down} if wind_down else {})}, frozenset()))
    run(bedtime.set_save(world.request(), proposal.data))
    assert run(bedtime.set_check(world.request(), proposal.data)) == ""
    return proposal


def test_bedtime_in_words_with_the_weekend_s_own_and_its_schedule_rows(world):
    proposal = set_bedtime(world, [{"time": "11:00 pm"}, {"time": "12:00 am", "days": ["fri", "sat"]}])
    assert proposal.lines[:2] == ("**11:00 pm** · Mon, Tue, Wed, Thu, Sun", "**12:00 am** · Fri, Sat")
    rows = [each for each in run(database.run(timetable.db_all)) if each.user_id == world.owner.id]
    named = {(each.name, each.at, each.days) for each in rows}
    assert ("Bedtime", time(0, 0), (5, 6)) in named, "Friday's and Saturday's midnight run on Saturday and Sunday mornings"
    assert ("Wind down", time(23, 30), (4, 5)) in named, "their wind-down the evening before, at 11:30 pm"
    assert ("Wind down", time(22, 30), (0, 1, 2, 3, 6)) in named
    set_bedtime(world, [{"time": "10:30 pm"}])
    live_rows = [each for each in run(database.run(timetable.db_all)) if each.user_id == world.owner.id and each.state == timetable.ON]
    assert len(live_rows) == 2, "a new bedtime takes the old rows' place"


def test_the_wind_down_message_with_what_is_open_and_an_earlier_time_for_an_early_start(world):
    set_bedtime(world, [{"time": "11:00 pm"}])
    clock.advance_to(at(world.day, 22, 30))
    tomorrow = world.day + timedelta(days=1)
    world.pieces[world.day] = [Piece("pills", "p1.3", "💊", "Pill A", at(world.day, 22, 45)), Piece("nudges", "n1", "⏰", "Made-up", at(world.day, 22, 50))]
    world.pieces[tomorrow] = [Piece("calendar", "e1", "🗓️", "Made-up early flight", at(tomorrow, 7, 0), at(tomorrow, 9)), Piece("pills", "p1.1", "💊", "Pill A", at(tomorrow, 8))]
    run(bedtime.wind_job(SimpleNamespace(payload={})))
    assert world.posted == [("bedtime.nudge", "🌙 Wind down")], "the lock screen names nothing"
    text = world.edited[-1].text
    assert text.splitlines()[0] == "🌙 Wind down · bed at 11:00 pm"
    assert "still open tonight: 💊 1 dose still due · ⏰ 1 reminder still to come" in text
    assert "tomorrow: 🗓️ Made-up early flight 7:00 am" in text and "bed at 10:15 pm gives you 8 hours" in text
    assert "Pill A" not in text, "no pill's name"
    run(bedtime.wind_job(SimpleNamespace(payload={})))
    assert len(world.posted) == 1, "once a night"


def test_goodnight_before_the_nudge_makes_the_night_quiet(world):
    set_bedtime(world, [{"time": "11:00 pm"}])
    clock.advance_to(at(world.day, 21, 50))
    assert run(bedtime.goodnight(world.request("goodnight"), {}, frozenset())) == "🌙 Goodnight"
    clock.advance_to(at(world.day, 22, 30))
    run(bedtime.wind_job(SimpleNamespace(payload={})))
    clock.advance_to(at(world.day, 23, 0))
    run(bedtime.bed_job(SimpleNamespace(payload={})))
    assert world.posted == [] and world.notes == ["not sent: goodnight was said", "not sent: goodnight was said"]


def test_the_line_at_bedtime_once_and_a_kind_that_gets_through_quiet_hours(world):
    set_bedtime(world, [{"time": "11:00 pm"}])
    clock.advance_to(at(world.day, 23, 0))
    run(bedtime.bed_job(SimpleNamespace(payload={})))
    run(bedtime.bed_job(SimpleNamespace(payload={})))
    assert world.posted == [("bedtime.nudge", "🌙 Bedtime")] and world.edited[-1].text == "🌙 Bedtime · sleep well"
    kind = notify.KINDS["bedtime.nudge"]
    assert kind.through and kind.where == notify.DISCORD


def test_the_diary_s_ask_is_folded_into_the_wind_down_when_they_are_close(world, monkeypatch, make_db):
    from tasks.diary import plain as diary_plain, store as diary_store

    make_db({"bedtime": bedtime.MIGRATIONS, "diary": diary_store.MIGRATIONS})
    monkeypatch.setattr(config, "DIARY_ENABLED", True)
    set_bedtime(world, [{"time": "9:30 pm"}])  # wind down at 9:00 pm, the diary's ask's own time
    clock.advance_to(at(world.day, 20, 45))
    assert run(bedtime.folds_diary(world.owner.id, clock.now()))
    clock.advance_to(at(world.day, 21, 0))
    run(bedtime.wind_job(SimpleNamespace(payload={})))
    shown = world.edited[-1]
    assert "📔 How was today?" in shown.text and "📔 diary not yet" in shown.text
    assert shown.rows and shown.rows[0][0].label == "Write", "the ask's own buttons, in the one message"
    assert run(database.run(diary_store.db_ask, world.owner.id, diary_plain.today())) is not None, "the diary's ask is taken: it won't come again"


def test_no_bedtime_set_sends_nothing(world):
    clock.advance_to(at(world.day, 22, 30))
    run(bedtime.wind_job(SimpleNamespace(payload={})))
    assert world.posted == [] and world.notes == ["not sent: no bedtime tonight"]
