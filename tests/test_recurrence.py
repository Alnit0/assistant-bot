"""The one repeat engine (core/recurrence.py): every kind, month ends, daylight saving, the words, and what is kept."""
from datetime import date, time, timedelta

import pytest

from core import day as days
from core import recurrence as rec
from core.recurrence import Repeat

MONDAY = date(2026, 10, 19)


def on(repeat, start=MONDAY, count=14):
    return [start + timedelta(days=each) for each in range(count) if rec.on_day(repeat, start + timedelta(days=each))]


def test_every_day_weekdays_weekends_and_chosen_days():
    assert len(on(Repeat(rec.DAILY))) == 14
    assert [each.weekday() for each in on(Repeat(rec.WEEKDAYS), count=7)] == [0, 1, 2, 3, 4]
    assert [each.weekday() for each in on(Repeat(rec.WEEKENDS), count=7)] == [5, 6]
    assert [each.weekday() for each in on(Repeat(rec.DAYS, weekdays=(0, 3)), count=7)] == [0, 3]


def test_every_n_days_counts_from_its_first_day_and_not_before():
    every_3 = Repeat(rec.EVERY, first=MONDAY + timedelta(days=1), every_days=3)
    assert on(every_3, count=10) == [MONDAY + timedelta(days=1), MONDAY + timedelta(days=4), MONDAY + timedelta(days=7)]


def test_a_one_off_is_on_its_day_only_and_has_no_next_after_it():
    once = Repeat(rec.ONCE, first=MONDAY)
    assert on(once) == [MONDAY]
    assert rec.next_due(once, time(9, 0), days.at(MONDAY, time(10, 0))) is None
    assert rec.next_due(once, time(9, 0), days.at(MONDAY, time(8, 0))) == days.at(MONDAY, time(9, 0))


@pytest.mark.parametrize("month_day,month,wanted", [(31, date(2026, 4, 1), 30), (31, date(2027, 2, 1), 28), (29, date(2028, 2, 1), 29), (15, date(2026, 11, 1), 15)])
def test_monthly_on_a_date_a_month_lacks_is_its_last_day(month_day, month, wanted):
    found = on(Repeat(rec.MONTHLY, month_day=month_day), start=month, count=31)
    assert [each.day for each in found if each.month == month.month] == [wanted]


def test_monthly_on_the_nth_weekday_and_the_last():
    first_monday = on(Repeat(rec.MONTHLY_NTH, nth=1, weekday=0), start=date(2026, 11, 1), count=30)
    assert first_monday == [date(2026, 11, 2)]
    last_friday = on(Repeat(rec.MONTHLY_NTH, nth=-1, weekday=4), start=date(2026, 10, 1), count=31)
    assert last_friday == [date(2026, 10, 30)]
    third_wed = on(Repeat(rec.MONTHLY_NTH, nth=3, weekday=2), start=date(2026, 12, 1), count=31)
    assert third_wed == [date(2026, 12, 16)]


def test_daylight_saving_never_moves_a_local_time():
    # New Zealand: clocks go back on Sun 5 Apr 2026 and forward on Sun 27 Sep 2026
    for day in (date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6), date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)):
        due = rec.next_due(Repeat(rec.DAILY), time(9, 0), days.at(day, time(0, 1)))
        assert days.local_time(due) == time(9, 0) and days.day_of(due) == day


def test_the_words():
    today = MONDAY
    assert rec.text(Repeat(rec.ONCE, first=today), today) == "today"
    assert rec.text(Repeat(rec.ONCE, first=today + timedelta(days=1)), today) == "tomorrow"
    assert rec.text(Repeat(rec.ONCE, first=date(2026, 10, 23)), today) == "Fri 23 Oct"
    assert rec.text(Repeat(rec.DAILY), today) == "every day"
    assert rec.text(Repeat(rec.WEEKENDS), today) == "weekends"
    assert rec.text(Repeat(rec.DAYS, weekdays=(0, 3)), today) == "every Mon and Thu"
    assert rec.text(Repeat(rec.DAYS, weekdays=(0, 2, 4)), today) == "every Mon, Wed and Fri"
    assert rec.text(Repeat(rec.EVERY, every_days=3), today) == "every 3 days"
    assert rec.text(Repeat(rec.MONTHLY, month_day=1), today) == "monthly on the 1st"
    assert rec.text(Repeat(rec.MONTHLY, month_day=22), today) == "monthly on the 22nd"
    assert rec.text(Repeat(rec.MONTHLY, month_day=13), today) == "monthly on the 13th"
    assert rec.text(Repeat(rec.MONTHLY_NTH, nth=1, weekday=0), today) == "monthly on the first Monday"
    assert rec.text(Repeat(rec.MONTHLY_NTH, nth=-1, weekday=4), today) == "monthly on the last Friday"


def test_what_is_kept_comes_back_the_same():
    for each in (Repeat(rec.DAYS, weekdays=(0, 3)), Repeat(rec.EVERY, first=MONDAY, every_days=3), Repeat(rec.MONTHLY, month_day=31), Repeat(rec.MONTHLY_NTH, nth=-1, weekday=4), Repeat(rec.ONCE, first=MONDAY), Repeat(rec.WEEKENDS)):
        assert rec.from_dict(rec.to_dict(each)) == each
    assert rec.from_dict(None) == rec.EVERY_DAY and rec.from_dict({"kind": "nonsense"}) == rec.EVERY_DAY


def test_from_what_claude_hands_over_python_checks_it():
    assert rec.from_fields({"repeat": "days", "weekdays": ["Monday", "thu"]}) == Repeat(rec.DAYS, weekdays=(0, 3))
    assert rec.from_fields({"repeat": "days"}) == Repeat(rec.DAILY), "chosen days with none named: every day"
    assert rec.from_fields({"repeat": "days", "weekdays": ["sat", "sun"]}) == Repeat(rec.WEEKENDS)
    assert rec.from_fields({"repeat": "days", "weekdays": ["mon", "tue", "wed", "thu", "fri"]}) == Repeat(rec.WEEKDAYS)
    assert rec.from_fields({"repeat": "every", "every_days": 0}, first=MONDAY) == Repeat(rec.EVERY, first=MONDAY, every_days=1)
    assert rec.from_fields({"repeat": "monthly", "month_day": 40}).month_day == 31
    assert rec.from_fields({"repeat": "monthly_nth", "nth": "last", "weekday": "friday"}) == Repeat(rec.MONTHLY_NTH, nth=-1, weekday=4)
    assert rec.from_fields({}, was=Repeat(rec.DAYS, weekdays=(1,))) == Repeat(rec.DAYS, weekdays=(1,)), "nothing said: as it was"
    assert rec.from_fields({"repeat": "bogus"}) == rec.EVERY_DAY
    assert [field.name for field in rec.fields()] == list(rec.FIELD_NAMES)
