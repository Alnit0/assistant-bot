"""The schedule model (core/schedule.py): when each of a day's is due, from the plan and what was done."""
from datetime import date, time, timedelta

from core import day, schedule
from core.schedule import AFTER_PREVIOUS, ANY_TIME, OPEN, OUT, PLANNED, WAITING, Due, Schedule

DAY = date(2026, 10, 12)


def at(hour, minute=0):
    return day.at(DAY, time(hour, minute))


def shown(found):
    """Each due as (the NZ time or None, why)."""
    return [(day.local_time(due.at) if due.at else None, due.why) for due in found]


# The worked example: planned 8:00 am, 11:30 am and 3:00 pm, at least 3h apart, not after 4:00 pm
PILL_A = Schedule(3, (time(8, 0), time(11, 30), time(15, 0)), gap_minutes=180, latest=time(16, 0))
# No times: the first when ready, the others the gap after the one before
COURSE_A = Schedule(3, gap_minutes=180)


# --- the rule: the later of the planned time and the one before, done + the gap ------------------
def test_before_anything_is_done_every_dose_is_due_at_its_planned_time():
    assert shown(schedule.dues(PILL_A, DAY)) == [(time(8, 0), PLANNED), (time(11, 30), PLANNED), (time(15, 0), PLANNED)]


def test_pill_a_dose_1_on_time_leaves_the_others_at_their_planned_times():
    found = schedule.dues(PILL_A, DAY, [at(8)])
    assert shown(found)[1:] == [(time(11, 30), PLANNED), (time(15, 0), PLANNED)]


def test_pill_a_dose_1_an_hour_late_moves_dose_2_by_the_gap_and_dose_3_holds_if_dose_2_is_on_time():
    found = schedule.dues(PILL_A, DAY, [at(9)])
    assert shown(found)[1:] == [(time(12, 0), AFTER_PREVIOUS), (time(15, 0), PLANNED)]


def test_pill_a_dose_2_late_moves_dose_3_by_the_gap():
    assert shown(schedule.dues(PILL_A, DAY, [at(8), at(12, 30)]))[2] == (time(15, 30), AFTER_PREVIOUS)


def test_pill_a_dose_2_too_late_puts_dose_3_after_the_latest_time():
    due = schedule.dues(PILL_A, DAY, [at(8), at(13, 15)])[2]
    assert day.local_time(due.at) == time(16, 15) and due.at > schedule.limit(PILL_A, DAY)


def test_the_plan_itself_never_moves():
    schedule.dues(PILL_A, DAY, [at(9), at(13, 15)])
    assert PILL_A.times == (time(8, 0), time(11, 30), time(15, 0))


# --- the shapes of schedule -----------------------------------------------------------------------
def test_no_times_and_no_gap_is_any_time_for_every_dose():
    assert shown(schedule.dues(Schedule(2), DAY)) == [(None, ANY_TIME), (None, ANY_TIME)]
    assert not schedule.dues(Schedule(), DAY)[0].is_timed


def test_planned_times_without_a_gap_stay_put_whatever_was_done():
    twice = Schedule(2, (time(8, 0), time(20, 0)))
    assert shown(schedule.dues(twice, DAY, [at(19, 30)])) == [(time(8, 0), PLANNED), (time(20, 0), PLANNED)]


def test_a_gap_with_no_times_waits_for_the_first_then_follows_what_was_done():
    assert shown(schedule.dues(COURSE_A, DAY)) == [(None, ANY_TIME), (None, WAITING), (None, WAITING)]
    found = schedule.dues(COURSE_A, DAY, [at(8, 12)])
    assert shown(found)[1:] == [(time(11, 12), AFTER_PREVIOUS), (time(14, 12), AFTER_PREVIOUS)]
    assert shown(schedule.dues(COURSE_A, DAY, [at(8, 12), at(11, 40)]))[2] == (time(14, 40), AFTER_PREVIOUS)


def test_a_time_for_the_first_dose_only():
    first = Schedule(3, (time(8, 0),), gap_minutes=180)
    assert shown(schedule.dues(first, DAY)) == [(time(8, 0), PLANNED), (time(11, 0), AFTER_PREVIOUS), (time(14, 0), AFTER_PREVIOUS)]


# --- what was skipped, and what is overdue ---------------------------------------------------------------
def test_a_dose_that_was_skipped_or_missed_is_not_waited_for():
    # The gap is measured from the last dose actually taken
    assert shown(schedule.dues(PILL_A, DAY, [at(9, 30), OUT]))[2] == (time(15, 0), PLANNED)
    assert shown(schedule.dues(PILL_A, DAY, [at(12, 30), OUT]))[2] == (time(15, 30), AFTER_PREVIOUS)
    assert shown(schedule.dues(COURSE_A, DAY, [OUT]))[1] == (None, ANY_TIME), "nothing was taken: there is nothing to wait for"


def test_a_dose_still_open_past_its_time_is_expected_now_at_the_earliest():
    # Dose 2 was due at 12:00 pm and it is 12:40 pm: dose 3 can't be before 3:40 pm
    found = schedule.dues(PILL_A, DAY, [at(9), OPEN], now=at(12, 40))
    assert shown(found)[1:] == [(time(12, 0), AFTER_PREVIOUS), (time(15, 40), AFTER_PREVIOUS)]
    assert shown(schedule.dues(PILL_A, DAY, [at(9)], now=at(10)))[2] == (time(15, 0), PLANNED), "not yet due: as planned"


# --- the day's limit ---------------------------------------------------------------------------------------
def test_the_days_limit_is_the_latest_time_or_the_end_of_the_day():
    assert schedule.limit(PILL_A, DAY) == at(16)
    assert schedule.limit(COURSE_A, DAY) == day.end_of(DAY)


def test_due_times_are_real_moments():
    due = schedule.dues(COURSE_A, DAY, [at(8, 12)])[1]
    assert due == Due(at(8, 12) + timedelta(hours=3), AFTER_PREVIOUS)


# --- planned times closer together than the gap -----------------------------------------------------------------
def test_a_planned_time_too_close_to_the_one_before_moves_later():
    close = Schedule(3, (time(8, 0), time(11, 30), time(14, 0)), gap_minutes=180)
    fixed, moves = schedule.spaced(close)
    assert fixed.times == (time(8, 0), time(11, 30), time(14, 30))
    assert [(move.index, move.before, move.was, move.now) for move in moves] == [(2, time(11, 30), time(14, 0), time(14, 30))]


def test_a_move_pushes_the_ones_after_it_and_a_good_schedule_is_left_alone():
    fixed, moves = schedule.spaced(Schedule(3, (time(8, 0), time(9, 0), time(12, 0)), gap_minutes=180))
    assert fixed.times == (time(8, 0), time(11, 0), time(14, 0)) and len(moves) == 2
    assert schedule.spaced(PILL_A) == (PILL_A, [])
    assert schedule.spaced(Schedule(2, (time(8, 0), time(8, 30)))) == (Schedule(2, (time(8, 0), time(8, 30))), []), "no gap"
