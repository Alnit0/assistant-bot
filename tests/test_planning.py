"""Plan my day, the engine (core/planning.py): fixed things stay where they are, to-dos are placed in the
free time in order with 15 minutes between any two things, never more than 6 hours of them, one free block of
30 minutes always left, what does not fit said; the window, a part of the day, a time, a time out, a day with no
free time; and the card's words. Pure, made-up names only."""
from datetime import date, datetime, time, timedelta

import pytest

from core import config, planning
from core import day as days
from core.planning import Piece

DAY = date(2026, 10, 19)  # a Monday
EARLY = days.at(DAY, time(5, 0))  # before the day starts: the whole window is open


def at(hour, minute=0):
    return days.at(DAY, time(hour, minute))


def todo(ref, text, rank=planning.ANY_DAY, done=False):
    return Piece("todos", ref, "📝", text, flexible=True, rank=rank, done=done)


def fixed(ref, text, start, end=None, task="calendar"):
    return Piece(task, ref, "📅", text, start, end)


def plan(pieces, lengths=None, start=None, end=None, **more):
    first, last = planning.window(DAY, EARLY)
    return planning.place(DAY, pieces, lengths or {}, start or first, end or last, **more)


def times(found):
    return [(slot.piece.ref, f"{days.local_time(slot.start):%H:%M}", slot.minutes) for slot in found.slots]


# --- lengths and words ---------------------------------------------------------------------------------------------------
def test_claude_s_estimate_is_one_of_the_four_lengths_and_said_lengths_are_kept():
    assert [planning.estimate(each) for each in ("15", "30", 60, "90", "45", "200", "soon", None)] == [15, 30, 60, 90, 30, 90, 30, 30]
    assert planning.length(120) == 120 and planning.length("2") == 5 and planning.length(0) is None and planning.length("x") is None
    assert planning.length(10_000) == planning.LONGEST
    assert [planning.minutes_text(each) for each in (15, 60, 90, 135)] == ["15 min", "1h", "1h 30m", "2h 15m"]
    assert planning.free_text(0) == "no free time" and planning.free_text(120) == "2h free"


def test_the_window_is_7_to_10_unless_said_and_today_never_before_now():
    assert planning.window(DAY, EARLY) == (at(7), at(22))
    assert planning.window(DAY, EARLY, time(8, 0)) == (at(8), at(22)), "I start at 8"
    assert planning.window(DAY, EARLY, time(8, 0), time(7, 0)) == (at(8), at(19)), "an end before the start is the evening's"
    assert planning.window(DAY, at(13, 2)) == (at(13, 5), at(22)), "today: from now, on a 5-minute mark"
    assert planning.window(DAY + timedelta(days=1), at(13, 2))[0] == days.at(DAY + timedelta(days=1), time(7, 0)), "tomorrow: the whole day"


# --- placing -------------------------------------------------------------------------------------------------------------
def test_to_dos_go_in_order_around_what_is_fixed_with_15_minutes_between():
    pieces = [
        fixed("e1", "Made-up standup", at(9), at(9, 30)),
        todo("t1", "Email Sam", planning.ANY_DAY),
        todo("t2", "Write the essay", planning.OVERDUE),
        todo("t3", "Weekly shop", planning.TODAY),
    ]
    found = plan(pieces, {"t1": 15, "t2": 90, "t3": 60})
    # Overdue first: the essay does not fit before 9 (7:00 to 8:30 leaves 30 minutes before standup? 8:30 + 15 > 9:00 is fine)
    assert times(found) == [("t2", "07:00", 90), ("t3", "09:45", 60), ("t1", "11:00", 15)]
    for slot in found.slots:
        assert not (slot.start < at(9, 30) + timedelta(minutes=15) and slot.end > at(9) - timedelta(minutes=15)), "15 minutes from the standup"
    assert found.fixed[0].ref == "e1" and not found.left_out


def test_a_dose_or_a_reminder_is_a_moment_that_keeps_15_minutes_clear():
    pieces = [fixed("p1.1", "Pill A", at(7, 20), task="pills"), todo("t1", "Email Sam")]
    found = plan(pieces, {"t1": 15})
    assert times(found) == [("t1", "07:40", 15)], "7:00 would end 7:15, too near 7:20; the dose takes 5 minutes, then 15 clear"
    touching = plan([fixed("p1.1", "Pill A", at(7, 30), task="pills"), todo("t1", "Email Sam")], {"t1": 15})
    assert times(touching) == [("t1", "07:00", 15)], "ending 15 minutes before it is enough"


def test_never_more_than_6_hours_of_flexible_things():
    pieces = [todo(f"t{n}", f"Made-up job {n}") for n in range(1, 6)]
    found = plan(pieces, {f"t{n}": 90 for n in range(1, 6)})
    assert found.planned_minutes == 360 and len(found.slots) == 4
    assert [(piece.ref, why) for piece, why in found.left_out] == [("t5", planning.OVER_LIMIT)]


def test_one_free_block_of_30_minutes_is_always_left():
    # A window of 2 hours: 90 minutes leaves the last 30 free; the email would take that block
    found = plan([todo("t1", "Made-up long job"), todo("t2", "Email Sam")], {"t1": 90, "t2": 15}, at(9), at(11))
    assert [(piece.ref, why) for piece, why in found.left_out] == [("t2", planning.KEEP_FREE)]
    assert times(found) == [("t1", "09:00", 90)]
    assert any(gap.minutes >= planning.FREE_BLOCK for gap in found.gaps)


def test_a_day_with_no_free_time_places_nothing_and_says_so():
    pieces = [fixed("e1", "Made-up conference", at(6), at(23)), todo("t1", "Email Sam"), todo("t2", "Weekly shop")]
    found = plan(pieces, {"t1": 15, "t2": 60})
    assert not found.slots and found.free_minutes == 0 and not found.gaps
    assert {why for _, why in found.left_out} == {planning.NO_ROOM}
    assert planning.nothing_fits(found)
    shown = planning.lines(found, DAY)
    assert "nothing to place" in shown[0] and "no free time" in shown[0]
    assert any("not placed (no room): Email Sam, Weekly shop" in each for each in shown)


def test_a_part_of_the_day_a_time_a_time_out_and_a_drop():
    pieces = [todo("t1", "Laundry"), todo("t2", "Write the essay"), todo("t3", "Weekly shop")]
    found = plan(
        pieces, {"t1": 60, "t2": 120, "t3": 60}, out=[(at(14), at(16))], parts={"t1": "evening"}, at={"t2": at(10)}, dropped={"t3"},
    )
    assert times(found) == [("t2", "10:00", 120), ("t1", "17:00", 60)]
    assert found.out[0].start == at(14) and "t3" not in {piece.ref for piece, _ in found.left_out}
    taken = plan([fixed("e1", "Made-up meeting", at(10), at(11)), todo("t2", "Write the essay")], {"t2": 60}, at={"t2": at(10, 30)})
    assert [(piece.ref, why) for piece, why in taken.left_out] == [("t2", planning.TIME_TAKEN)]


def test_what_is_done_is_kept_and_never_placed_again():
    found = plan([todo("t1", "Email Sam", done=True), todo("t2", "Weekly shop")], {"t2": 60})
    assert [each.ref for each in found.done] == ["t1"] and times(found) == [("t2", "07:00", 60)]
    assert any(each == "-# ✅ done: Email Sam" for each in planning.lines(found, DAY))


def test_replanning_from_now_keeps_the_fixed_things_and_places_what_is_left_after_now():
    now = at(13, 2)
    start, end = planning.window(DAY, now, from_now=True)
    found = planning.place(DAY, [fixed("e1", "Made-up gym", at(18), at(19)), todo("t1", "Email Sam"), todo("t2", "Weekly shop")], {"t1": 15, "t2": 60}, start, end)
    assert times(found) == [("t1", "13:05", 15), ("t2", "13:35", 60)]


# --- the card's words ----------------------------------------------------------------------------------------------------
def test_the_card_is_in_time_order_with_fixed_marked_slots_bold_and_gaps_small():
    pieces = [
        fixed("e1", "Made-up standup", at(9), at(9, 30)),
        fixed("p1.1", "Pill A", at(8), task="pills"),
        fixed("p2.1", "Pill B", at(8), task="pills"),
        Piece("nudges", "b1", "🎂", "Made-up birthday", all_day=True),
        todo("t1", "Email Sam"),
    ]
    found = plan(pieces, {"t1": 15}, at(7), at(12))
    shown = planning.lines(found, DAY)
    assert shown[0] == "**Today · Mon 19 Oct** · 1 thing planned · 4h 10m free"
    assert shown[1] == "-# all day · 🎂 Made-up birthday"
    assert shown[2] == "**7:00 am · 📝 Email Sam** · 15 min"
    assert shown[3] == "-# free 7:15 am to 8:00 am"
    assert shown[4] == "8:00 am · 📅 Pill A, Pill B · fixed", "two doses at one time are one line"
    assert shown[6] == "9:00 am · 📅 Made-up standup · fixed"
    assert shown[-1] == "-# free 9:30 am to 12:00 pm"
    assert planning.summary_line(found, DAY - timedelta(days=1)).startswith("**Tomorrow · Mon 19 Oct** · ")
    assert planning.summary_line(found, DAY - timedelta(days=3)).startswith("**Mon 19 Oct** · ")


def test_the_evening_ask_offers_tomorrow_only_from_8pm_and_only_when_switched_on(monkeypatch):
    monkeypatch.setattr(config, "PLAN_MY_DAY", True)
    assert planning.offer_line(at(19, 59)) == ""
    assert planning.offer_line(at(21)) == "-# Say “plan tomorrow” to plan it"
    monkeypatch.setattr(config, "PLAN_MY_DAY", False)
    assert planning.offer_line(at(21)) == ""
