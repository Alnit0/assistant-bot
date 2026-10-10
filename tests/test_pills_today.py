"""Pills: the day's doses and the checklist as it is written (tasks/pills/today.py, core/hub.py). Pure."""
from datetime import date, time

from core import day, hub
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from core.schedule import Schedule
from tasks.pills import today
from tasks.pills.rules import ACTIVE, PAUSED, REMOVED, Pill, Plan

DAY = date(2026, 10, 12)


def at(hour, minute=0):
    return day.at(DAY, time(hour, minute))


def pill(pill_id, name, notes="", status=ACTIVE, paused_until=None, start=None, end=None, **schedule):
    return Pill(pill_id, 1, Plan(name, notes=notes, schedule=Schedule(**schedule), start=start, end=end), status, paused_until)


_ids = iter(range(1, 10_000))


def dose(of: Pill, seq=1, state=PENDING, taken=None, automatic=False, reason=None):
    planned = of.plan.schedule.planned(seq - 1)
    return Occurrence(next(_ids), 1, "pills", of.id, DAY, seq, planned, None, state, taken, automatic, reason)


VITAMIN_D = pill(1, "Vitamin D")
MAGNESIUM = pill(2, "Magnesium", notes="with food")
COURSE_A = pill(3, "Course A", per_day=3, gap_minutes=180)
EVENING = pill(4, "Evening pill", times=(time(20, 0),))
MORNING = pill(5, "Morning pill", times=(time(7, 0),))
IRON = pill(6, "Iron", status=PAUSED, paused_until=date(2026, 10, 20))
PILL_A = pill(7, "Pill A", per_day=3, times=(time(8, 0), time(11, 30), time(15, 0)), gap_minutes=180, latest=time(16, 0))


# --- the progress bar (core/hub.py) --------------------------------------------------------------
def test_the_progress_bar_is_five_segments_rounded_with_exact_numbers():
    assert hub.progress_bar(2, 5) == "▰▰▱▱▱ 2 of 5"
    assert hub.progress_bar(0, 3) == "▱▱▱▱▱ 0 of 3" and hub.progress_bar(3, 3) == "▰▰▰▰▰ 3 of 3"
    assert hub.progress_bar(1, 7) == "▰▱▱▱▱ 1 of 7" and hub.progress_bar(6, 7) == "▰▰▰▰▱ 6 of 7"
    assert hub.progress_bar(0, 0) == "▱▱▱▱▱ 0 of 0"


# --- which doses a pill has on a day -------------------------------------------------------------------
def test_a_pill_has_a_dose_for_each_of_its_times_only_on_a_day_it_is_taken():
    assert today.wanted(VITAMIN_D, DAY) == [(1, None)]
    assert today.wanted(PILL_A, DAY) == [(1, time(8, 0)), (2, time(11, 30)), (3, time(15, 0))]
    assert today.wanted(IRON, DAY) == [], "paused"
    assert today.wanted(pill(8, "Gone", status=REMOVED), DAY) == []
    course = pill(9, "Course B", start=date(2026, 10, 13), end=date(2026, 10, 14))
    assert today.wanted(course, DAY) == [], "it starts tomorrow"
    assert today.wanted(course, date(2026, 10, 14)) == [(1, None)] and today.wanted(course, date(2026, 10, 15)) == []


# --- the checklist ---------------------------------------------------------------------------------------
def test_the_checklist_as_the_day_goes_on():
    pills = [VITAMIN_D, MAGNESIUM, COURSE_A, EVENING, MORNING, IRON]
    found = [
        dose(VITAMIN_D, state=DONE, taken=at(8, 4)),
        dose(MAGNESIUM),
        dose(COURSE_A, 1, DONE, at(14, 10)), dose(COURSE_A, 2), dose(COURSE_A, 3),
        dose(EVENING),
        dose(MORNING, state=MISSED),
    ]
    listed = today.doses(pills, found, DAY, at(15))
    assert today.checklist(listed, pills, DAY).splitlines() == [
        "## 💊 Pills · ▰▱▱▱▱ 2 of 7",
        "",
        "✅ **Course A** (dose 1 of 3) · taken 2:10 pm",
        "💊 **Magnesium** · *with food*",
        "✅ **Vitamin D** · taken 8:04 am",
        "❌ **Morning pill** · missed",
        "💊 **Course A** (dose 2 of 3) · `5:10 pm`",
        "💊 **Evening pill** · `8:00 pm`",
        "💊 **Course A** (dose 3 of 3) · `8:10 pm`",
        "",
        "### ⏸️ Paused",
        "⏸️ **Iron** · paused until 20 Oct",
    ]
    assert today.progress(listed) == (2, 7), "taken and skipped are dealt with; a paused pill is not counted"


def test_doses_with_no_time_come_first_then_the_timed_ones_by_when_they_are_due_today():
    pills = [EVENING, PILL_A, MAGNESIUM, VITAMIN_D]
    found = [dose(EVENING), dose(PILL_A, 1, DONE, at(9)), dose(PILL_A, 2), dose(PILL_A, 3), dose(MAGNESIUM), dose(VITAMIN_D)]
    listed = today.doses(pills, found, DAY, at(9, 30))
    assert [today.line(each) for each in listed] == [
        "💊 **Magnesium** · *with food*",
        "💊 **Vitamin D**",
        "✅ **Pill A** (dose 1 of 3) · taken 9:00 am",
        "💊 **Pill A** (dose 2 of 3) · `12:00 pm`",  # today's time: dose 1 was an hour late
        "💊 **Pill A** (dose 3 of 3) · `3:00 pm`",
        "💊 **Evening pill** · `8:00 pm`",
    ]


def test_a_dose_that_follows_one_not_yet_taken_says_so_and_only_the_first_is_untimed():
    listed = today.doses([COURSE_A], [dose(COURSE_A, 1), dose(COURSE_A, 2), dose(COURSE_A, 3)], DAY, at(9))
    assert [today.line(each) for each in listed] == [
        "💊 **Course A** (dose 1 of 3)",
        "💊 **Course A** (dose 2 of 3) · *after dose 1*",
        "💊 **Course A** (dose 3 of 3) · *after dose 2*",
    ]
    assert [each.is_untimed for each in listed] == [True, False, False], "one Taken / Skip message: the others wait"


def test_skipped_by_me_and_by_the_bot_read_differently():
    mine = today.doses([VITAMIN_D], [dose(VITAMIN_D, state=SKIPPED)], DAY)[0]
    bots = today.doses([MAGNESIUM], [dose(MAGNESIUM, state=SKIPPED, automatic=True, reason="not enough time before midnight")], DAY)[0]
    assert today.line(mine) == "⏭️ **Vitamin D** · skipped"
    assert today.line(bots) == "⏭️ **Magnesium** · *skipped automatically: not enough time before midnight*"


def test_a_day_with_nothing_to_take_says_so_and_still_shows_what_is_paused():
    assert today.checklist([], [IRON], DAY).splitlines() == [
        "## 💊 Pills", "", "Nothing to take today.", "", "### ⏸️ Paused", "⏸️ **Iron** · paused until 20 Oct",
    ]
    assert today.checklist([], [], DAY) == "## 💊 Pills\n\nNothing to take today."


def test_a_pill_that_is_not_taken_today_has_no_line_whatever_was_recorded():
    listed = today.doses([IRON, VITAMIN_D], [dose(IRON, state=DONE, taken=at(8)), dose(VITAMIN_D)], DAY)
    assert [each.pill.plan.name for each in listed] == ["Vitamin D"]


# --- what a reply needs ------------------------------------------------------------------------------------
def test_the_next_dose_to_take_the_last_one_taken_and_what_is_left():
    listed = today.doses([PILL_A, VITAMIN_D], [dose(PILL_A, 1, DONE, at(8)), dose(PILL_A, 2), dose(PILL_A, 3), dose(VITAMIN_D)], DAY, at(9))
    assert today.next_pending(listed, PILL_A.id).number == 2 and today.last_taken(listed, PILL_A.id).number == 1
    assert today.last_taken(listed, VITAMIN_D.id) is None
    assert today.left_text(listed) == "still to take today: Vitamin D, Pill A (dose 2 of 3) `11:30 am`, Pill A (dose 3 of 3) `3:00 pm`"
    assert today.left_text([each for each in listed if not each.is_pending]) == "nothing left to take today"
    assert today.dose_text(today.doses([MAGNESIUM], [dose(MAGNESIUM)], DAY)[0]) == "💊 **Magnesium** · *with food*"
