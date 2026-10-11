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


# --- what the day's limit does to the doses still open ---------------------------------------------------
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence  # noqa: E402

REASON = "not enough time before 4:00 pm"


def found(*doses):
    """The day's occurrences of one pill: each is a state, or the moment it was taken."""
    made = {}
    for number, each in enumerate(doses, 1):
        state, taken, automatic, reason = (DONE, each, False, None) if not isinstance(each, (str, tuple)) else (*((each,) if isinstance(each, str) else each), None, False, None)[:4]
        made[number] = Occurrence(number, 1, "pills", 1, DAY, number, PILL_A.planned(number - 1), None, state, taken if state == DONE else None, bool(automatic), reason)
    return made


def test_while_there_is_time_everything_stays_open():
    assert doses.outcomes(PILL_A, DAY, found(PENDING, PENDING, PENDING), at(7)) == {1: (PENDING, None), 2: (PENDING, None), 3: (PENDING, None)}
    assert doses.outcomes(PILL_A, DAY, found(at(9), PENDING, PENDING), at(12, 59)) == {2: (PENDING, None), 3: (PENDING, None)}


def test_a_dose_that_can_never_be_in_time_is_skipped_with_the_reason():
    assert doses.outcomes(PILL_A, DAY, found(at(9), PENDING, PENDING), at(13, 1)) == {2: (PENDING, None), 3: (SKIPPED, REASON)}
    assert doses.outcomes(PILL_A, DAY, found(at(8), at(13, 15), PENDING), at(13, 16)) == {3: (SKIPPED, REASON)}
    late = at(22, 57)
    assert doses.outcomes(PILL_A, DAY, found(late, PENDING, PENDING), late) == {2: (SKIPPED, REASON), 3: (SKIPPED, REASON)}


def test_a_dose_that_had_its_time_is_missed_once_the_limit_has_passed():
    assert doses.outcomes(PILL_A, DAY, found(at(9), PENDING, PENDING), at(16, 1)) == {2: (MISSED, None), 3: (SKIPPED, REASON)}
    assert doses.outcomes(PILL_A, DAY, found(at(8), at(12, 40), PENDING), at(16, 1)) == {3: (MISSED, None)}, "it was due at 3:40 pm"


def test_with_nothing_taken_all_day_everything_left_is_missed_at_the_limit():
    assert doses.outcomes(PILL_A, DAY, found(PENDING, PENDING, PENDING), at(16, 1)) == {1: (MISSED, None), 2: (MISSED, None), 3: (MISSED, None)}
    before = doses.outcomes(PILL_A, DAY, found(PENDING, PENDING, PENDING), at(15))
    assert before == {1: (PENDING, None), 2: (SKIPPED, REASON), 3: (SKIPPED, REASON)}, "at 3 pm only one more can be in time"


def test_only_what_the_bot_decided_is_looked_at_again():
    by_me = (SKIPPED, None, False, None)
    by_the_bot = (SKIPPED, None, True, REASON)
    missed = (MISSED, None, True, None)
    assert doses.outcomes(PILL_A, DAY, found(by_me, PENDING, PENDING), at(7)) == {2: (PENDING, None), 3: (PENDING, None)}, "what I skipped stays skipped"
    assert doses.outcomes(PILL_A, DAY, found(at(9), by_the_bot, missed), at(11)) == {2: (PENDING, None), 3: (PENDING, None)}, "there is room again"


def test_logging_is_late_only_for_a_pill_with_a_latest_time():
    assert doses.is_after_limit(PILL_A, DAY, at(16, 1)) and not doses.is_after_limit(PILL_A, DAY, at(16))
    assert not doses.is_after_limit(COURSE_A, DAY, at(23, 59))
    assert doses.limit_text(PILL_A) == "4:00 pm" and doses.limit_text(COURSE_A) == "midnight"
