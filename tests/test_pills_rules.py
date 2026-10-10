"""Pills: building a plan from what was said, and putting it into words (tasks/pills/rules.py)."""
from datetime import date, time

import pytest

from core.errors import UserError
from tasks.pills import rules
from tasks.pills.rules import ACTIVE, ENDED, FIXED, INTERVAL, PAUSED, REMOVED, UNTIMED, UPCOMING, Pill, Plan, Request, TimeQuestion

TODAY = date(2026, 10, 9)  # a Friday


def build(base=None, **said):
    return rules.build(Request(**said), TODAY, base)


def pill(pill_id=1, status=ACTIVE, paused_until=None, **plan):
    plan.setdefault("name", f"Pill {pill_id}")
    return Pill(pill_id, 1, Plan(**plan), status, paused_until)


# ---------------------------------------------------------------------------
# New pills
# ---------------------------------------------------------------------------
def test_once_a_day_with_nothing_else_is_untimed():
    plan = build(name="Vitamin D")
    assert plan == Plan("Vitamin D", kind=UNTIMED, per_day=1)
    assert rules.describe(plan) == "💊 **Vitamin D** · daily, untimed"


def test_a_time_makes_it_fixed_and_is_shown_in_12_hour_form():
    plan = build(name="Evening pill", times="20:00")
    assert (plan.kind, plan.times, plan.per_day) == (FIXED, (time(20, 0),), 1)
    assert rules.describe(plan) == "💊 **Evening pill** · daily at `8:00 pm`"


def test_several_times_are_put_in_order():
    plan = build(name="Twice", times="8pm and 8am")
    assert plan.times == (time(8, 0), time(20, 0)) and plan.per_day == 2
    assert rules.describe(plan) == "💊 **Twice** · daily at `8:00 am` and `8:00 pm`"
    assert rules.schedule_text(build(name="Thrice", times="8am, noon; 20:00")) == "daily at `8:00 am`, `12:00 pm` and `8:00 pm`"


def test_a_gap_makes_it_an_interval_course_with_inclusive_dates():
    plan = build(name="Course A", per_day="3", min_gap="3 hours", notes="with food", start="tomorrow", days="7")
    assert (plan.kind, plan.per_day, plan.gap_minutes, plan.times) == (INTERVAL, 3, 180, ())
    assert (plan.start, plan.end) == (date(2026, 10, 10), date(2026, 10, 16)), "7 days, the last one a day of taking"
    assert rules.describe(plan) == (
        "💊 **Course A** · 3× daily, ≥3h apart · *with food* · 10 to 16 Oct · first dose when ready"
    )


def test_an_interval_pill_may_give_its_first_dose_a_time():
    plan = build(name="Course B", per_day="3 times a day", min_gap="90m", times="8am")
    assert plan.times == (time(8, 0),)
    assert rules.describe(plan) == "💊 **Course B** · 3× daily, ≥1h 30m apart · first dose at `8:00 am`"


def test_dose_and_notes_are_shown():
    plan = build(name="Magnesium", dose="1 tablet", notes="with food", per_day="twice")
    assert rules.describe(plan) == "💊 **Magnesium** (1 tablet) · 2× daily, untimed · *with food*"


def test_a_pill_with_no_end_has_no_dates_at_all():
    plan = build(name="Vitamin D")
    assert plan.start is None and plan.end is None and not plan.is_course
    assert "Oct" not in rules.describe(plan)


@pytest.mark.parametrize(
    "said, start, end",
    [
        ({"start": "tomorrow", "end": "the 16th"}, date(2026, 10, 10), date(2026, 10, 16)),
        ({"end": "20 Oct"}, date(2026, 10, 9), date(2026, 10, 20)),  # no start: from today
        ({"days": "5 days"}, date(2026, 10, 9), date(2026, 10, 13)),
        ({"start": "monday", "days": "1"}, date(2026, 10, 12), date(2026, 10, 12)),
        ({"start": "the 28th", "end": "the 3rd"}, date(2026, 10, 28), date(2026, 11, 3)),  # the 3rd after it starts
    ],
)
def test_course_dates(said, start, end):
    plan = build(name="Course", **said)
    assert (plan.start, plan.end) == (start, end)


# ---------------------------------------------------------------------------
# Never guessed
# ---------------------------------------------------------------------------
def test_a_time_that_could_be_morning_or_evening_is_a_question():
    with pytest.raises(TimeQuestion) as raised:
        build(name="Evening pill", times="8")
    question = raised.value
    assert (question.index, question.typed, question.options) == (0, "8", (time(8, 0), time(20, 0)))
    assert "8am or 8pm?" in str(question)


def test_answering_settles_that_time_and_leaves_the_rest_as_said():
    request = Request(name="Twice", times="8am, 8")
    with pytest.raises(TimeQuestion) as raised:
        rules.build(request, TODAY)
    assert raised.value.index == 1
    answered = rules.answer(request, raised.value, time(20, 0))
    assert answered.times == "8am, 20:00"
    assert rules.build(answered, TODAY).times == (time(8, 0), time(20, 0))


def test_each_unclear_time_is_asked_about_in_turn():
    request = Request(name="Twice", times="8 and 9:30")
    with pytest.raises(TimeQuestion) as first:
        rules.build(request, TODAY)
    request = rules.answer(request, first.value, time(8, 0))
    with pytest.raises(TimeQuestion) as second:
        rules.build(request, TODAY)
    assert (second.value.index, second.value.typed) == (1, "9:30")
    request = rules.answer(request, second.value, time(21, 30))
    assert rules.build(request, TODAY).times == (time(8, 0), time(21, 30))


def test_a_gap_with_no_unit_is_not_guessed_to_be_hours():
    with pytest.raises(UserError, match="3 hours or 3 minutes"):
        build(name="Course", per_day="3", min_gap="3")


@pytest.mark.parametrize(
    "said, reason",
    [
        ({}, "What is the pill called"),
        ({"name": "x" * 61}, "name is too long"),
        ({"name": "A", "notes": "x" * 101}, "note is too long"),
        ({"name": "A", "times": "soon"}, "can't read “soon” as a time"),
        ({"name": "A", "times": "8am, 8:00 am"}, "Two of those times are the same"),
        ({"name": "A", "times": "8am, 8pm", "per_day": "3"}, "2 times for 3 doses a day"),
        ({"name": "A", "per_day": "lots"}, "How many times a day"),
        ({"name": "A", "per_day": "0"}, "How many times a day"),
        ({"name": "A", "per_day": "13"}, "How many times a day"),
        ({"name": "A", "min_gap": "3h"}, "How many times a day"),
        ({"name": "A", "min_gap": "3h", "per_day": "1"}, "at least 2 doses"),
        ({"name": "A", "min_gap": "12h", "per_day": "3"}, "don't fit in a day"),
        ({"name": "A", "min_gap": "3h", "per_day": "3", "times": "8am, 8pm"}, "only the first dose can have a time"),
        ({"name": "A", "min_gap": "ages", "per_day": "3"}, "can't read “ages” as a gap"),
        ({"name": "A", "start": "tomorrow"}, "When does it end"),
        ({"name": "A", "end": "the 20th", "days": "7"}, "not both"),
        ({"name": "A", "start": "20 Oct", "end": "2026-10-15"}, "before it starts"),
        ({"name": "A", "end": "2026-10-01"}, "already over"),
        ({"name": "A", "days": "a week"}, "For how many days"),
        ({"name": "A", "start": "whenever", "days": "7"}, "can't read “whenever” as a date"),
    ],
)
def test_what_does_not_make_a_plan_is_refused_with_a_short_reason(said, reason):
    with pytest.raises(UserError, match=reason) as raised:
        build(**said)
    assert not isinstance(raised.value, TimeQuestion)


def test_two_pills_in_use_cannot_share_a_name():
    others = [pill(1, name="Vitamin D"), pill(2, name="Old one", status=REMOVED)]
    with pytest.raises(UserError, match="already a pill called \\*\\*Vitamin D"):
        rules.check_name(Plan("vitamin d"), others)
    rules.check_name(Plan("vitamin d"), others, own_id=1)  # itself, being edited
    rules.check_name(Plan("Old one"), others)  # a removed pill's name is free again


# ---------------------------------------------------------------------------
# Editing: only what was said changes
# ---------------------------------------------------------------------------
EVENING = Plan("Evening pill", dose="1 tablet", notes="with food", kind=FIXED, times=(time(20, 0),), per_day=1)
COURSE = Plan("Course A", kind=INTERVAL, per_day=3, gap_minutes=180, start=date(2026, 10, 10), end=date(2026, 10, 16))


def test_an_edit_changes_only_what_it_names():
    assert build(EVENING, times="9pm") == Plan(
        "Evening pill", dose="1 tablet", notes="with food", kind=FIXED, times=(time(21, 0),), per_day=1
    )
    assert build(EVENING, dose="2 tablets").dose == "2 tablets"
    assert build(EVENING, name="Night pill").name == "Night pill"
    assert build(EVENING) == EVENING


def test_none_takes_a_value_away():
    assert build(EVENING, notes="none").notes == ""
    assert build(EVENING, dose="none").dose == ""
    untimed = build(EVENING, times="none")
    assert (untimed.kind, untimed.times, untimed.per_day) == (UNTIMED, (), 1)
    forever = build(COURSE, end="none")
    assert (forever.start, forever.end) == (None, None)


def test_changing_the_kind_of_schedule_drops_what_belonged_to_the_old_kind():
    # Fixed times -> a gap: the old times don't become "the first dose"
    by_gap = build(EVENING, per_day="3", min_gap="4h")
    assert (by_gap.kind, by_gap.times, by_gap.per_day, by_gap.gap_minutes) == (INTERVAL, (), 3, 240)
    # A gap -> a time for each dose: the gap goes
    by_times = build(COURSE, times="8am, 2pm, 8pm")
    assert (by_times.kind, by_times.gap_minutes, by_times.per_day) == (FIXED, None, 3)
    # A gap, and one time: that is the first dose, still by gap
    first = build(COURSE, times="8am")
    assert (first.kind, first.times, first.gap_minutes) == (INTERVAL, (time(8, 0),), 180)


def test_an_interval_edit_keeps_the_count_it_had():
    assert build(COURSE, min_gap="2h").per_day == 3
    assert build(COURSE, per_day="4").gap_minutes == 180


def test_course_dates_can_be_moved():
    longer = build(COURSE, days="10")
    assert (longer.start, longer.end) == (date(2026, 10, 10), date(2026, 10, 19))
    later = build(COURSE, end="the 20th")
    assert (later.start, later.end) == (date(2026, 10, 10), date(2026, 10, 20))


def test_a_request_merged_with_a_later_one_keeps_what_the_later_one_leaves_out():
    first = Request(name="Evening pill", times="8", notes="with food")
    merged = first.merged(Request(times="9pm", dose="2 tablets"))
    assert merged == Request(name="Evening pill", times="9pm", notes="with food", dose="2 tablets")


# ---------------------------------------------------------------------------
# What a pill is today
# ---------------------------------------------------------------------------
def test_a_course_is_upcoming_then_active_through_its_last_day_then_ended():
    course = pill(name="Course A", start=date(2026, 10, 10), end=date(2026, 10, 16))
    assert rules.status_on(course, date(2026, 10, 9)) == UPCOMING
    assert rules.status_on(course, date(2026, 10, 10)) == ACTIVE
    assert rules.status_on(course, date(2026, 10, 16)) == ACTIVE, "the last date is a day of taking"
    assert rules.status_on(course, date(2026, 10, 17)) == ENDED
    assert rules.is_taken_on(course, date(2026, 10, 16)) and not rules.is_taken_on(course, date(2026, 10, 17))


def test_a_pause_with_an_end_date_is_over_on_that_date():
    iron = pill(name="Iron", status=PAUSED, paused_until=date(2026, 10, 20))
    assert rules.status_on(iron, date(2026, 10, 19)) == PAUSED
    assert rules.status_on(iron, date(2026, 10, 20)) == ACTIVE
    assert rules.status_on(pill(status=PAUSED), date(2030, 1, 1)) == PAUSED, "no end date: until told"


def test_removed_and_ended_win_over_paused():
    assert rules.status_on(pill(status=REMOVED), TODAY) == REMOVED
    over = pill(status=PAUSED, start=date(2026, 10, 1), end=date(2026, 10, 5))
    assert rules.status_on(over, TODAY) == ENDED


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------
def test_the_list_groups_in_use_paused_and_ended_and_leaves_out_removed():
    pills = [
        pill(1, name="Vitamin D"),
        pill(2, name="Iron", status=PAUSED, paused_until=date(2026, 10, 20)),
        pill(3, name="Course B", kind=INTERVAL, per_day=3, gap_minutes=180, start=date(2026, 10, 1), end=date(2026, 10, 7)),
        pill(4, name="Gone", status=REMOVED),
        pill(5, name="Course A", kind=INTERVAL, per_day=3, gap_minutes=180, start=date(2026, 10, 10), end=date(2026, 10, 16)),
        pill(6, name="evening pill", kind=FIXED, times=(time(20, 0),)),
    ]
    assert rules.list_text(pills, TODAY).splitlines() == [
        "## 💊 Pills",
        "💊 **evening pill** · daily at `8:00 pm`",
        "💊 **Vitamin D** · daily, untimed",
        "🗓️ **Course A** · 3× daily, ≥3h apart · 10 to 16 Oct · first dose when ready · starts 10 Oct",
        "### ⏸️ Paused",
        "⏸️ **Iron** · daily, untimed · paused until 20 Oct",
        "### 🏁 Ended",
        "🏁 **Course B** · 3× daily, ≥3h apart · 1 to 7 Oct · first dose when ready",
    ]
    assert [p.id for p in rules.listed(pills)] == [5, 3, 6, 2, 1], "by name, whatever the case"


def test_an_empty_list_says_how_to_start():
    assert rules.list_text([], TODAY) == f"## 💊 Pills\n{rules.EMPTY_LIST}"
    assert rules.list_text([pill(status=REMOVED)], TODAY) == f"## 💊 Pills\n{rules.EMPTY_LIST}"
    only_paused = rules.list_text([pill(name="Iron", status=PAUSED)], TODAY)
    assert "Nothing is being taken at the moment." in only_paused and "⏸️ **Iron** · daily, untimed · paused" in only_paused


# ---------------------------------------------------------------------------
# Which pill is meant
# ---------------------------------------------------------------------------
PILLS = [pill(1, name="Vitamin D"), pill(2, name="Vitamin C"), pill(3, name="Iron"), pill(4, name="Old iron", status=REMOVED)]


@pytest.mark.parametrize("wanted, found", [("pl3", 3), ("PL 1", 1), ("iron", 3), ("  Vitamin  D ", 1), ("vitamin c", 2), ("iro", 3)])
def test_a_pill_is_found_by_id_whole_name_or_part_of_one(wanted, found):
    assert rules.find(PILLS, wanted).id == found


def test_when_more_than_one_fits_the_user_is_asked():
    with pytest.raises(UserError, match=r"Which one: \*\*Vitamin C\*\* or \*\*Vitamin D\*\*\?"):
        rules.find(PILLS, "vitamin")


def test_the_whole_name_wins_over_part_of_another():
    pills = [pill(1, name="Iron"), pill(2, name="Iron plus")]
    assert rules.find(pills, "iron").id == 1


def test_a_pill_that_is_not_there_lists_the_ones_that_are():
    with pytest.raises(UserError, match="don't have a pill called “zinc”. Yours: Iron, Vitamin C, Vitamin D"):
        rules.find(PILLS, "zinc")
    with pytest.raises(UserError, match="no pills yet"):
        rules.find([], "zinc")
    with pytest.raises(UserError, match="Which pill"):
        rules.find(PILLS, " ")
    with pytest.raises(UserError, match="don't have"):
        rules.find(PILLS, "pl4")  # removed


# ---------------------------------------------------------------------------
# For Claude
# ---------------------------------------------------------------------------

