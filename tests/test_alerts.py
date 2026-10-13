"""Being told about what needs me (core/alerts.py): a ping in the hub by day, one check when quiet hours end, what
is worth knowing in a small line of the briefing, and every line of "my schedule" with its last run."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import alerts, attention, clock, config, day, health, notify, restart, scheduler
from core.attention import PROBLEM, Item
from tasks import briefing
from tasks.briefing import rules as briefing_rules
from tasks.pills import attention as pills_attention
from tasks.pills import reminders
from tasks.schedule import rules as schedule_rules
from tests.test_pills_reminders import HUB, PILL_A, add, run, world  # noqa: F401

BACKUP = Item("backup failed", PROBLEM, bug="B14", when=datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc))  # 3:00 am in New Zealand


@pytest.fixture
def box(world, monkeypatch):
    """What needs me is whatever a test puts in `box.items`; by day, quiet hours in force from 10:00 pm to 7:00 am."""
    world.items = []

    async def problems(user_id, now):
        return list(world.items)

    monkeypatch.setattr(attention, "_providers", {})
    attention.provide("system", attention.PROBLEM_ICON, problems)
    monkeypatch.setattr(alerts, "where", lambda: HUB)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(config, "QUIET_HOURS", (time(22, 0), time(7, 0)))
    monkeypatch.setattr(config, "QUIET_HOURS_ENABLED", True)
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    clock.advance_to(day.at(world.day, time(10, 0)))
    return world


def said(world):
    return [(each.card.text, each.silent) for each in world.sent]


def test_a_ping_is_one_short_line_with_the_bug_and_the_time_and_never_more():
    assert alerts.line(BACKUP) == "⚠️ B14 · backup failed at 3:00 am"
    assert alerts.line(Item("the bot's memory use is high", PROBLEM)) == "⚠️ the bot's memory use is high"
    assert alerts.key(BACKUP) == "B14" and alerts.key(Item("x is wrong", PROBLEM, task="pills")) == "pills: x is wrong"
    assert alerts.count_line(1) == "⚠️ 1 thing needs a look" and alerts.count_line(2) == "⚠️ 2 things need a look"
    assert notify.KINDS[alerts.KIND].where == notify.DISCORD and not notify.KINDS[alerts.KIND].through, "one line of the alert table: Discord, and held by quiet hours"


def test_by_day_something_that_needs_me_pings_once_in_the_hub_and_its_line_goes_when_it_is_dealt_with(box):
    box.items.append(BACKUP)
    assert run(alerts.look()) == (1, 0)
    assert said(box) == [("<@1> ⚠️ B14 · backup failed at 3:00 am", False)], "I am mentioned, so it pings"
    assert run(alerts.look()) == (0, 0) and len(box.sent) == 1, "said once, however often the ranking is looked at"
    box.items.clear()
    assert run(alerts.look()) == (0, 1)
    assert box.deleted == [box.sent[0].id], "dealt with: its line goes"
    assert run(alerts.look()) == (0, 0)


def test_something_i_caused_is_shown_and_does_not_ping(box):
    box.items.append(Item("dev mode is on", PROBLEM, ping=False))
    assert run(alerts.look()) == (0, 0) and box.sent == []
    assert run(alerts.needing(box.owner.id, clock.now())) == []


def test_in_quiet_hours_nothing_is_posted_and_the_check_at_seven_pings_once_if_the_box_is_not_empty(box):
    clock.advance_to(day.at(box.day, time(23, 0)))
    box.items.append(BACKUP)
    assert run(alerts.look()) == (0, 0) and box.sent == [], "held: it is in the briefing's box in the morning"
    box.items.append(Item("the bot's memory use is high", PROBLEM, bug="B15"))
    run(alerts.look())
    clock.advance_to(day.at(box.day + timedelta(days=1), time(7, 0)))
    job = SimpleNamespace(user_id=box.owner.id, task="core", kind="needs_look", id=1)
    notes = []
    box_note = lambda job, text: notes.append(text)  # noqa: E731
    import core.scheduler as engine

    original = engine.note
    engine.note = box_note
    try:
        run(alerts.check_job(job))
    finally:
        engine.note = original
    assert said(box) == [("<@1> ⚠️ 2 things need a look", False)], "one ping for the lot, when quiet hours end"
    assert notes == ["2 need a look: said in the hub"]
    box.items.clear()
    assert run(alerts.look()) == (0, 3) and box.deleted == [box.sent[0].id], "all dealt with: the check's line goes too"


def test_the_check_says_nothing_with_an_empty_box_and_is_a_schedule_of_mine(box, monkeypatch):
    notes = []
    monkeypatch.setattr(scheduler, "note", lambda job, text: notes.append(text))
    run(alerts.check_job(SimpleNamespace(user_id=box.owner.id, task="core", kind="needs_look", id=1)))
    assert box.sent == [] and notes == ["nothing needs a look: nothing said"], "a job never does nothing in silence"
    assert (alerts.DEFAULT.name, alerts.DEFAULT.at, alerts.DEFAULT.locked) == ("Needs-a-look check", time(7, 0), False), "shown in my schedule, and mine to move"


def test_the_dev_bot_mentions_nobody_and_makes_no_sound(box, monkeypatch):
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    box.items.append(BACKUP)
    run(alerts.look())
    assert said(box) == [("⚠️ B14 · backup failed at 3:00 am", True)], "a self-test never reaches my phone"


def test_what_needs_me_is_on_top_of_the_briefing_with_its_bug_and_leaves_once_dealt_with(box):
    add(box, PILL_A)
    box.items.append(BACKUP)
    lines = run(briefing.card_for(box.owner.id)).text.splitlines()
    assert lines[3:5] == [briefing_rules.NEEDS, "⚠️ B14 · backup failed"]
    box.items.clear()
    assert briefing_rules.NEEDS not in run(briefing.card_for(box.owner.id)).text


# --- what needs me: the things the bot knows are wrong -----------------------------------------------------------------
def test_claude_spend_over_the_day_s_limit_needs_a_look_until_the_day_is_over(world, monkeypatch):
    spent = {"today": 0.2}

    async def run_db(func, *args):
        return spent["today"]

    monkeypatch.setattr(health.database, "run", run_db)
    monkeypatch.setattr(config, "DAILY_SPEND_LIMIT_NZD", 0.5)
    assert run(health.spend(1, clock.now())) == []
    spent["today"] = 0.61
    (item,) = run(health.spend(1, clock.now()))
    assert item.urgency == PROBLEM and item.what.startswith("Claude spend today is over the limit: ") and item.ping
    monkeypatch.setattr(config, "DAILY_SPEND_LIMIT_NZD", 0)
    assert run(health.spend(1, clock.now())) == [], "no limit set: nothing to be over"


def test_reminders_that_cannot_be_sent_need_a_look_and_name_no_pill(world, monkeypatch):
    add(world, PILL_A)
    assert not any(item.urgency == PROBLEM for item in run(pills_attention.items(world.owner.id, clock.now())))
    monkeypatch.setattr(reminders, "_said_no_hub", True)
    first = run(pills_attention.items(world.owner.id, clock.now()))[0]
    assert first.urgency == PROBLEM and first.what == "reminders can't be sent: the hub channel can't be found" and "Pill A" not in first.what + " ".join(first.short)
    monkeypatch.setattr(config, "REMINDERS_ENABLED", False)
    assert not reminders.cannot_send(), "switched off, nothing is being sent: nothing is wrong"


def test_dev_mode_and_the_self_test_s_month_are_shown_and_never_ping():
    assert health.spend_problem(2.5, 2.0).ping is False
    assert Item("x", PROBLEM).ping is True, "anything else wrong pings unless it says otherwise"


# --- worth knowing, not urgent ------------------------------------------------------------------------------------------
def test_what_is_worth_knowing_is_one_small_line_in_the_briefing_and_never_a_ping(box):
    add(box, PILL_A)
    before = len(box.sent)
    run(notify.worth_knowing("The PC restarted: the bot was off for about 12m · 2 things caught up"))
    assert len(box.sent) == before, "no message, no ping"
    today = day.today()
    (note,) = run(notify.notes_for(box.owner.id, today))
    assert note.line.startswith("The PC restarted") and run(notify.held_overnight(box.owner.id, today)) == [], "not an alert that was held: a note"
    lines = run(briefing.card_for(box.owner.id)).text.splitlines()
    small = [each for each in lines if each.startswith("-# 🗒️ ")]
    assert len(small) == 1 and small[0].endswith("· The PC restarted: the bot was off for about 12m · 2 things caught up")
    assert lines.index(small[0]) > next(at for at, each in enumerate(lines) if "**Pills**" in each), "under the sections, above the foot"


def test_only_the_latest_three_are_shown_and_the_rest_are_counted():
    assert briefing_rules.worth_knowing(("a", "b")) == ["-# 🗒️ a", "-# 🗒️ b"]
    assert briefing_rules.worth_knowing(("a", "b", "c", "d", "e")) == ["-# 🗒️ …and 2 more before", "-# 🗒️ c", "-# 🗒️ d", "-# 🗒️ e"]
    assert briefing_rules.text([], date(2026, 10, 14)) == briefing_rules.text([], date(2026, 10, 14), notes=()), "with none, the briefing reads as before"


def test_a_restart_is_said_for_the_briefing_in_a_line():
    assert restart.briefing_line("The PC restarted: the bot was off for about 12m", 1) == "The PC restarted: the bot was off for about 12m"
    assert restart.briefing_line("The PC restarted: the bot was off for about 12m", 3) == "The PC restarted: the bot was off for about 12m · 2 things caught up"
    assert restart.briefing_line("", 1) == "Restarted · 1 thing caught up"


def test_catching_up_leaves_a_line_for_the_briefing_and_still_says_it_all_in_bot_log(world, monkeypatch):
    monkeypatch.setattr(restart, "_lines", ["The checklist was posted late"])
    run(restart.catch_up())
    assert [title for title, _ in world.bot_log] == [restart.TITLE], "#bot-log is told exactly as it was"
    (note,) = run(notify.notes_for(world.owner.id, day.today()))
    assert note.line == "Restarted · 1 thing caught up"


# --- my schedule ----------------------------------------------------------------------------------------------------------
def test_every_line_of_my_schedule_says_when_it_last_ran_and_whether_it_worked():
    today = date(2026, 10, 14)
    listed = SimpleNamespace(last=("done", "2026-10-14T07:00:00"))
    assert schedule_rules.last_text(listed, today) == "last: today 7:00 am ✅"
    assert schedule_rules.last_text(SimpleNamespace(last=("failed", "2026-10-13T03:00:00")), today) == "last: Tue 13 Oct 3:00 am ⚠️ failed"
    assert schedule_rules.last_text(SimpleNamespace(last=None), today) == "last: not run yet"
    assert "#bot-log" not in " ".join(schedule_rules._ENDED.values()), "I never read #bot-log: the line says it itself"
