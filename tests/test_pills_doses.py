"""Pills: a dose and the day's limit (tasks/pills/doses.py). The worked example for Pill A."""
from datetime import date, time

from core import day, schedule
from core.schedule import Schedule
from tasks.pills import doses

DAY = date(2026, 10, 12)
PILL_A = Schedule(3, (time(8, 0), time(11, 30), time(15, 0)), gap_minutes=180, latest=time(16, 0))
COURSE_A = Schedule(3, gap_minutes=180)


def at(hour, minute=0):
    return day.at(DAY, time(hour, minute))


def test_pill_a_dose_3_fits_after_dose_2_at_half_past_twelve_and_not_after_quarter_past_one():
    on_time = schedule.dues(PILL_A, DAY, [at(8), at(12, 30)])[2]
    too_late = schedule.dues(PILL_A, DAY, [at(8), at(13, 15)])[2]
    assert doses.fits(on_time, PILL_A, DAY), "3:30 pm, before 4:00 pm"
    assert not doses.fits(too_late, PILL_A, DAY), "4:15 pm, after 4:00 pm: it is skipped automatically"


def test_a_dose_due_exactly_at_the_latest_time_fits_and_one_with_no_time_always_does():
    assert doses.fits(schedule.dues(PILL_A, DAY, [at(8), at(13)])[2], PILL_A, DAY)
    assert doses.fits(schedule.dues(COURSE_A, DAY)[1], COURSE_A, DAY)


def test_pill_a_dose_2_must_be_taken_by_one_for_dose_3_to_fit():
    assert doses.take_by(PILL_A, DAY, later=1) == at(13)
    assert doses.take_by(PILL_A, DAY, later=2) == at(10), "dose 1, with two to come"
    assert doses.take_by(PILL_A, DAY, later=0) == at(16), "the last dose: the latest time itself"


def test_with_no_latest_time_the_limit_is_midnight_and_with_no_gap_there_is_no_take_by():
    assert day.local_time(doses.take_by(COURSE_A, DAY, later=1)) == time(21, 0)
    assert doses.take_by(Schedule(2, (time(8, 0), time(20, 0))), DAY, later=1) is None
