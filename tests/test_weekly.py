"""The week of everything (core/weekly.py, behind WEEKLY_ALL): the Sunday summary as one card, a box a task."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone

from core import actions, config, design, weekly
from core import day as days
from core.actions import Entry
from tasks.calendar import rules as calendar
from tasks.habits import rules as habits
from tasks.pills import history
from tasks.todos import rules as todos
from tasks.todos.rules import Todo

MONDAY, SUNDAY = date(2026, 10, 12), date(2026, 10, 18)


def test_off_unless_switched_on():
    assert config.WEEKLY_ALL is False


def test_pills_week_says_taken_late_missed_and_skipped_with_the_streak_small():
    week = history.week_line(36, 42, 3, 2, 4, 3)
    assert week.line == "36 of 42 taken · 3 late · 2 missed · 4 skipped" and (week.done, week.total) == (40, 42)
    assert week.small == "🔥 Streak · 3 days" and week.status == design.MISSED
    assert history.week_line(7, 7, 0, 0, 0, 1).line == "7 of 7 taken" and history.week_line(7, 7, 0, 0, 0, 1).small == ""


def test_a_dose_is_late_half_an_hour_after_its_time():
    from core.occurrences import DONE, Occurrence

    due = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)

    def dose(minutes):
        return Occurrence(1, 1, "pills", 1, MONDAY, 1, None, due, DONE, due + timedelta(minutes=minutes), False, None)

    assert history.late([dose(29), dose(30), dose(90)]) == 2


def test_to_dos_week_is_done_still_open_and_the_oldest():
    done = Todo(1, 1, "Buy stamps", None, MONDAY, datetime(2026, 10, 13, 1, tzinfo=timezone.utc), MONDAY + timedelta(days=1))
    before = Todo(2, 1, "Old one", None, MONDAY - timedelta(days=20), datetime(2026, 9, 25, tzinfo=timezone.utc), date(2026, 9, 25))
    oldest = Todo(3, 1, "Renew the passport", MONDAY - timedelta(days=4), MONDAY - timedelta(days=9))
    other = Todo(4, 1, "Sort the garage", None, MONDAY + timedelta(days=1))
    week = todos.week_line([done, before, oldest, other], MONDAY, SUNDAY)
    assert week.line == "1 done this week · 2 still open" and (week.done, week.total) == (1, 3)
    assert week.small == "oldest: Renew the passport, from Thu 8 Oct" and week.status == design.DUE
    assert todos.week_line([before], MONDAY, SUNDAY) is None, "nothing this week and nothing open: left out"


def test_routines_week_is_the_days_each_was_done_as_dots():
    week = habits.week_line([("Morning", [True, True, False]), ("Evening", [True, True, True]), ("Weekend", [])])
    assert week.line == "**Morning** ●●○ 2/3 · **Evening** ●●● 3/3" and (week.done, week.total) == (5, 6)
    assert week.small == "every day: Evening", "a routine not on that week is left out"
    assert habits.week_line([("Weekend", [])]) is None


def test_the_calendar_says_counts_by_day_and_times_never_a_name():
    nxt = MONDAY + timedelta(days=7)
    week = calendar.week_line([(nxt, [days.at(nxt, time(9)), None]), (nxt + timedelta(days=1), []), (nxt + timedelta(days=4), [None])])
    assert week.line == "next week · Mon 2 · Fri 1" and week.small == "first: Mon 9:00 am"
    assert calendar.week_line([(nxt, [None])]).small == "first: Mon, all day"
    assert calendar.week_line([(nxt, [])]) is None


def _section(name, line, done=None, total=None):
    return weekly.Section(name, "💊", name.capitalize(), weekly.Week(line, done, total))


def test_one_card_a_box_a_task_and_its_first_line_names_nothing():
    sections = [_section("pills", "7 of 7 taken", 7, 7), _section("todos", "1 done this week", 1, 1)]
    pieces = weekly.layout(sections, MONDAY, SUNDAY)
    assert design.problem(pieces) == "" and len([piece for piece in pieces if isinstance(piece, design.Box)]) == 2
    shown = design.texts(pieces)
    assert shown[0] == "## 📆 Your week\n-# Mon 12 to Sun 18 Oct" and shown[1].startswith("### 💊 Pills ●●●●●●● 7/7")
    assert weekly.text(sections, MONDAY, SUNDAY).splitlines()[0] == "📆 Your week · Mon 12 to Sun 18 Oct"
    assert weekly.text([], MONDAY, SUNDAY).splitlines()[1] == weekly.QUIET_WEEK


def test_a_task_with_nothing_to_say_is_left_out(monkeypatch):
    async def something(user_id, monday, upto):
        return weekly.Week("a line")

    async def nothing(user_id, monday, upto):
        return None

    entries = [Entry("pills", "💊", "x", (), (), week=something), Entry("todos", "📝", "x", (), (), week=nothing), Entry("timers", "⏱️", "x", (), ())]
    monkeypatch.setattr(actions, "catalogue", lambda: entries)
    found = asyncio.run(weekly.gather(1, MONDAY, SUNDAY))
    assert [each.name for each in found] == ["pills"]


def test_the_preview_has_a_busy_and_a_quiet_week_each_in_one_message():
    from selftest import preview

    found = preview.weekly_cards()
    assert [label for label, _ in found if label][:1] == ["A busy week"] and len(found) == 4
    busy = "\n".join(design.texts(found[0][1]))
    assert "next week · " in busy and "Calendar" not in "\n".join(design.texts(found[2][1])), "the quiet week has no calendar box"
