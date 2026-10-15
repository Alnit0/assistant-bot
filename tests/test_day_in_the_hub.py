"""A day in the hub (selftest/day.py, 15 Oct): the replay's own reading of the hub, and what it found.

The replay ran the dev bot through a made-up day and read the hub back eight times. What it found
that was plainly wrong is fixed and tested here: the status line held by an overdue to-do all day,
the line after Taken left in the hub all day, the briefing's reminders and calendar boxes that never
moved on from the morning, and the pills box's "Next" for a dose long due. The understanding checks
of the same day (evals/fixtures/crosstask.json) add "done" for a reminder that went off, and the
rest of today by part ("what's on tonight?", "what's next?").
"""
from datetime import date, datetime, time, timedelta

import pytest

from core import attention, clock, database, messages
from core import day as days
from core.actions import Summary
from core.attention import TIMED, Item
from core.errors import UserError
from core.summaries import Section
from selftest import day as replay
from tasks.briefing import rules as briefing
from tests.test_nudges import add, at, fired, run, world  # noqa: F401

DAY = date(2026, 10, 16)


def local(hour, minute=0, on=DAY):
    return days.at(on, time(hour, minute))


# --- the replay's own reading of the hub (pure) ------------------------------------------------------------------
def test_the_made_up_calendar_has_an_all_day_event_three_timed_and_one_cancelled_left_out():
    from tasks.calendar import rules

    found = rules.on_day(rules.parse(replay.ics(DAY), DAY, DAY), DAY)
    assert [each.title for each in found] == ["Test conference", "Test standup", "Test lunch", "Test gym"], "the cancelled one is not there"
    assert found[0].all_day and all(not each.all_day for each in found[1:])


def test_a_message_reads_as_plain_lines_with_its_boxes_buttons_and_dropdowns():
    raw = {"flags": replay.COMPONENTS_V2, "components": [{"type": 17, "id": 1, "components": [
        {"type": 10, "id": 2, "content": "### 📝 To-dos ○ 0/1"},
        {"type": 14, "id": 3},
        {"type": 1, "id": 4, "components": [{"type": 2, "id": 5, "label": "Taken", "emoji": {"name": "✅"}, "custom_id": "x"}]},
        {"type": 1, "id": 6, "components": [{"type": 3, "id": 7, "custom_id": "y", "placeholder": "Done", "options": [{"label": "Buy stamps", "value": "1"}]}]},
    ]}]}
    assert replay.lines_of(raw) == ["┌ box", "### 📝 To-dos ○ 0/1", "———", "[✅ Taken]", "[▾ Done: Buy stamps]", "└"]
    assert replay.heading(raw) == "📝 To-dos ○ 0/1"
    copy = replay.copy_payload(raw)
    assert copy["flags"] == replay.COMPONENTS_V2 and "content" not in copy and copy["allowed_mentions"] == {"parse": []}
    assert "id" not in str(copy["components"]).replace("custom_id", ""), "the ids of the original are not sent again"


def test_a_message_of_words_is_copied_as_words():
    copy = replay.copy_payload({"content": "✅ **Pill B** · taken 7:05 am", "flags": 4096})
    assert copy["content"] == "✅ **Pill B** · taken 7:05 am" and "flags" not in copy


def _message(key="", kind="", day="2026-10-16", typed=False, text="x"):
    return {"id": hash((key, kind, text)), "key": key, "kind": kind, "day": day, "typed": typed, "raw": {"content": text}}


def test_the_order_of_the_hub_is_checked_briefing_then_task_cards_then_the_moment():
    good = {"day": "2026-10-16", "messages": [_message("briefing:hub"), _message(kind="checklist"), _message("today:hub"), _message("nudges:hub"), _message("habits.r1:hub"), _message("todos:hub"), _message(text="✅ done")]}
    assert replay.rule_problems(good) == []
    late = {"day": "2026-10-16", "messages": [_message("briefing:hub"), _message("todos:hub"), _message("habits.r1:hub", text="🔁 Morning")]}
    assert replay.rule_problems(late) == ["out of order: “🔁 Morning” is under something that comes after it"]


def test_a_card_twice_and_a_message_from_another_day_are_problems():
    snap = {"day": "2026-10-16", "messages": [_message("todos:hub", text="a"), _message("todos:hub", text="b"), _message(day="2026-10-15", text="old line")]}
    assert replay.rule_problems(snap) == ["todos:hub is in the hub 2 times", "left from 2026-10-15: “old line”"]


def test_what_changed_between_two_moments_is_one_line():
    before = {"status": "💊 1/6", "messages": [{"id": 1, "raw": {"content": "### Pills 0/6"}}, {"id": 2, "raw": {"content": "line"}}]}
    after = {"status": "💊 2/6", "messages": [{"id": 1, "raw": {"content": "### Pills 1/6"}}, {"id": 3, "raw": {"content": "⏰ Reminder"}}]}
    assert replay.changes(before, after) == "new: ⏰ Reminder · gone: line · rewritten: Pills 1/6 · status line 💊 1/6 → 💊 2/6"
    assert replay.changes(None, after) == "2 messages"


def test_the_replay_never_starts_in_the_nightly_self_test_s_window():
    assert replay.may_run(datetime(2026, 10, 16, 3, 20)) and replay.may_run(datetime(2026, 10, 16, 4, 29))
    assert replay.may_run(datetime(2026, 10, 16, 3, 14)) == "" and replay.may_run(datetime(2026, 10, 16, 4, 30)) == ""


def test_the_replay_turns_on_every_switch_live_has_and_never_a_real_calendar():
    for name in ("REMINDERS_ENABLED", "BRIEFING_ENABLED", "HUB_TIDY", "QUIET_HOURS_ENABLED", "TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED", "TODAY_CARD", "CALENDAR_ENABLED", "WEATHER_ENABLED", "WEEKLY_ALL", "DIARY_ENABLED", "READING_ENABLED", "CALENDAR_WRITE"):
        assert replay.SETTINGS[name] == "true", name
    assert "CALENDAR_ICS_URL" not in replay.SETTINGS, "the made-up file is handed over by the launcher, never a link"
    assert not {"GOOGLE_SA_KEY_PATH", "READING_SOURCE", "GOOGLE_CALENDAR_FAKE"} & set(replay.SETTINGS), "no key; the made-up files by the launcher"
    assert replay.SETTINGS["CALENDAR_BOT_ID"].startswith("made-up")
    assert [moment for moment, _ in replay.MOMENTS] == [(6, 0), (7, 30), (9, 45), (12, 0), (15, 0), (18, 30), (21, 0), (23, 45)]


# --- the status line: what fell due today at a time beats what was carried over -----------------------------------
def test_a_dose_due_now_comes_before_to_dos_overdue_from_yesterday():
    now = local(9, 15)
    carried = Item("to-dos overdue", TIMED, when=days.start_of(DAY), can_act=True, short=("2 overdue",), carried=True)
    dose = Item("dose due", TIMED, when=local(8, 0), can_act=True, short=("due 8am",))
    assert attention.top([carried, dose], now) is dose
    assert attention.top([carried], now) is carried, "on its own it is still due now (level 2)"
    later = Item("next", TIMED, when=local(10, 30), short=("10:30am",))
    assert attention.top([carried, later], now) is carried, "carried over is still before what is only coming"


def test_overdue_to_dos_are_handed_in_as_carried_over(make_db, owner, dev_clock):
    from tasks import todos
    from tasks.todos import store

    make_db({"todos": store.MIGRATIONS})
    yesterday = days.today()
    run(database.run(store.db_add, owner.id, "Renew the passport", yesterday, yesterday, clock.now()))
    dev_clock.advance_to(days.at(yesterday + timedelta(days=1), time(9, 0)))
    (overdue,) = [each for each in run(todos.items(owner.id, clock.now())) if each.urgency == TIMED]
    assert overdue.carried and overdue.short == ("1 overdue",)


# --- the line after Taken leaves the hub ---------------------------------------------------------------------------
def test_a_line_that_invites_a_reply_goes_by_itself_after_its_time(make_db, monkeypatch, dev_clock):
    from core import config

    make_db()
    monkeypatch.setattr(config, "HUB_TIDY", True)
    monkeypatch.setattr(messages, "in_hub", lambda channel_id: True)
    run(messages.record(4242, 555))
    assert run(database.run(messages.db_get, 4242)).lifetime == messages.DAY
    run(messages.expire_in(4242, timedelta(minutes=30)))
    row = run(database.run(messages.db_get, 4242))
    assert row.lifetime == messages.EXPIRY and abs((row.expires_at - clock.now()) - timedelta(minutes=30)) < timedelta(seconds=1)


def test_the_line_after_taken_waits_as_long_as_a_card_does():
    from tasks.pills import sheet

    assert sheet.CORRECTABLE_FOR == timedelta(minutes=30)


# --- reminders in the briefing: what is dealt with leaves the box --------------------------------------------------
def test_the_briefing_s_reminders_are_what_is_still_to_come_and_the_rest_one_small_line(world):  # noqa: F811
    from tasks import nudges
    from tasks.nudges import plain

    add(world, text="call the bank", time="10:30 am")
    add(world, text="put the bins out", time="5:00 pm")
    before = run(nudges.summary(world.owner.id, world.day))
    assert before.lines == ("**10:30 am** · Call the bank", "**5:00 pm** · Put the bins out") and before.hint == ""
    at(world, 10, 30)
    waiting = run(nudges.summary(world.owner.id, world.day))
    assert waiting.lines[0] == "**10:30 am** · Call the bank", "one that went off and is waiting stays, first"
    (open_,) = fired(world)
    run(database.run(__import__("tasks.nudges.store", fromlist=["x"]).db_done, open_.id, clock.now()))
    after = run(nudges.summary(world.owner.id, world.day))
    assert after.lines == ("**5:00 pm** · Put the bins out",) and after.hint == "✅ 1 earlier today" and after.glance == "2 today"
    assert after.left == ("Put the bins out `5:00 pm`",) and after.left_at == (days.at(world.day, time(17, 0)),)
    assert plain.TASK == "nudges"


# --- done in words, for a reminder that went off -------------------------------------------------------------------
def test_done_straight_after_a_reminder_went_off_ticks_off_that_one_and_it_leaves_the_hub(world):  # noqa: F811
    from core import llm
    from tasks.nudges import plain

    add(world, text="call the bank", time="10:30 am")
    at(world, 10, 30)
    assert llm.answering_task(555) == "nudges", "the reminder is the bot's latest word in the hub: done straight after is its"
    (open_,) = fired(world)
    said = run(plain.done(world.request("done"), {"reminder": "@that"}, frozenset()))
    assert said == "✅ Call the bank · done" and fired(world) == [] and open_.message_id in world.deleted


def test_done_with_a_name_picks_that_one_and_a_reply_picks_the_one_replied_to(world):  # noqa: F811
    from core.actions import Request
    from tasks.nudges import plain

    add(world, text="call the bank", time="10:30 am")
    add(world, text="put the bins out", time="10:45 am")
    at(world, 10, 50)
    bank, bins = sorted(fired(world), key=lambda each: each.due_at)
    assert run(plain.done(world.request("done the bank"), {"reminder": "bank"}, frozenset())) == "✅ Call the bank · done"
    assert [each.id for each in fired(world)] == [bins.id]
    replied = Request(world.owner, 100, "done", replied_to=bins.message_id)
    assert run(plain.done(replied, {}, frozenset())) == "✅ Put the bins out · done" and fired(world) == []


def test_done_with_nothing_waiting_says_so_and_changes_nothing(world):  # noqa: F811
    from tasks.nudges import plain

    add(world, text="call the bank", time="10:30 am")
    with pytest.raises(UserError, match="nothing to tick off"):
        run(plain.done(world.request("done"), {}, frozenset()))


def test_done_in_words_is_a_log_with_no_card(world):  # noqa: F811
    from tasks.nudges import plain

    (action,) = [each for each in plain.actions() if each.name == "nudge_done"]
    assert not action.needs_card and action.purpose == "each day"


# --- the calendar's box moves on through the day --------------------------------------------------------------------
@pytest.mark.parametrize("hour, minute, glance", [(6, 0, "4 events · next 9:00 am"), (9, 5, "4 events · on now until 9:15 am"), (14, 0, "4 events · next 6:00 pm"), (20, 0, "4 events · all over")])
def test_the_calendar_box_says_what_is_next_not_the_first_of_the_day(make_db, owner, dev_clock, monkeypatch, tmp_path, hour, minute, glance):
    from core import config
    from tasks import calendar
    from tasks.calendar import store

    feed = tmp_path / "day.ics"
    feed.write_text(replay.ics(days.today() + timedelta(days=1)), encoding="utf-8")
    make_db({"calendar": store.MIGRATIONS})
    monkeypatch.setattr(config, "CALENDAR_ICS_URL", str(feed))
    run(calendar.update(owner.id))
    the_day = days.today() + timedelta(days=1)
    dev_clock.advance_to(days.at(the_day, time(hour, minute)))
    said = run(calendar.summary(owner.id, the_day))
    assert said.glance == glance
    assert all(moment > clock.now() for moment in said.left_at) and len(said.left) == len(said.left_at)


# --- the rest of today, by part, in time order across tasks (pure) ---------------------------------------------------
def _sections():
    pills = Section("pills", "💊", "Pills", Summary(done=1, total=3, left=("Pill A (dose 2 of 3) `12:00 pm`", "Pill C `9:00 pm`", "Pill D"), left_at=(local(12), local(21), None)))
    nudges = Section("nudges", "⏰", "Reminders", Summary(left=("Put the bins out `5:00 pm`",), left_at=(local(17),)))
    todos = Section("todos", "📝", "To-dos", Summary(done=0, total=1, left=("Book a haircut",)))
    calendar = Section("calendar", "📅", "Calendar", Summary(left=("Test gym `6:00 pm`",), left_at=(local(18),)))
    return [pills, nudges, todos, calendar]


def test_what_s_left_today_is_in_time_order_across_tasks_with_what_has_no_time_last():
    assert briefing.left(_sections(), "", local(11)).splitlines() == [
        "☀️ **Left today** · ●○○○ 1/4",
        "💊 Pill A (dose 2 of 3) `12:00 pm`", "⏰ Put the bins out `5:00 pm`", "📅 Test gym `6:00 pm`", "💊 Pill C `9:00 pm`",
        "💊 Pill D", "📝 Book a haircut",
    ]


def test_what_s_on_tonight_is_what_is_due_from_5_pm_and_the_untimed_in_one_small_line():
    assert briefing.left(_sections(), briefing.TONIGHT, local(11)).splitlines() == [
        "☀️ **Left tonight** · ●○○○ 1/4", "⏰ Put the bins out `5:00 pm`", "📅 Test gym `6:00 pm`", "💊 Pill C `9:00 pm`",
        "-# and 2 with no time, any time today",
    ]
    assert briefing.left(_sections(), briefing.AFTERNOON, local(11)).splitlines()[:2] == ["☀️ **Left this afternoon** · ●○○○ 1/4", "💊 Pill A (dose 2 of 3) `12:00 pm`"]
    assert briefing.left(_sections(), briefing.MORNING, local(11)) == "☀️ **Nothing at a time this morning** · ●○○○ 1/4\n-# 2 with no time, any time today"


def test_what_s_next_is_the_first_thing_still_to_come():
    assert briefing.left(_sections(), briefing.NEXT, local(11)).splitlines() == ["☀️ **Next** · ●○○○ 1/4", "💊 Pill A (dose 2 of 3) `12:00 pm`", "-# then 5 more today"]


def test_a_part_claude_did_not_name_is_the_whole_day(make_db, owner, dev_clock):
    from core.actions import Request
    from tasks import briefing as task

    make_db()
    said = run(task.left_today(Request(owner, 100, "what's left?"), {"part": "elevenses"}, frozenset()))
    assert said == briefing.NOTHING


def test_day_left_takes_a_part_of_the_day_from_claude_and_nothing_else():
    from tasks import briefing as task

    (action,) = [each for each in task.task._questions() if each.name == "day_left"]
    (part,) = action.fields
    assert part.name == "part" and set(part.choices) == {"morning", "afternoon", "evening", "tonight", "next"} and not part.required


# --- the pills box: a dose whose time has come is due ---------------------------------------------------------------
def test_the_pills_box_says_due_for_a_dose_whose_time_has_come():
    from types import SimpleNamespace

    from tasks.pills import summary, today

    dose = SimpleNamespace(is_pending=True, pill=SimpleNamespace(plan=SimpleNamespace(name="Pill A")), number=1, of=3)
    original = today.shown_time
    today.shown_time = lambda each: local(8)
    try:
        assert summary.next_line([dose], local(9, 15)) == "**Due:** Pill A, dose 1 · `8:00 am`"
        assert summary.next_line([dose], local(7)) == "**Next:** Pill A, dose 1 · `8:00 am`"
        assert summary.next_line([dose]) == "**Next:** Pill A, dose 1 · `8:00 am`"
    finally:
        today.shown_time = original


# --- the hints the router is given: a word with an ending of its own ------------------------------------------------
def test_a_name_with_an_ending_is_still_a_hint_for_the_router():
    from core import routing

    named = {"habits": ["Stretch", "Floss"], "todos": ["Buy milk"]}
    assert routing.name_hints("took pill A and did my stretches", named) == [("stretches", "habits")]
    assert routing.name_hints("flossed", named) == [("flossed", "habits")]
    assert routing.name_hints("stretching", named) == [], "a longer ending is another word: no hint"
    assert routing.name_hints("stre", named) == [("stre", "habits")], "the start of a name, as before"
