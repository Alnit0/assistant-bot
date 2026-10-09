"""Times the user types and how they are shown (core/timeinput.py)."""
from datetime import datetime, time, timedelta

import pytest

from core import timeinput
from core.config import TIMEZONE
from core.errors import UserError
from core.timeinput import AmbiguousTime


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


@pytest.mark.parametrize(
    "typed, expected",
    [
        # 12-hour
        ("8pm", time(20, 0)),
        ("8 pm", time(20, 0)),
        ("8:30am", time(8, 30)),
        ("8.30 am", time(8, 30)),
        ("8PM", time(20, 0)),
        ("8 p.m.", time(20, 0)),
        ("12am", time(0, 0)),
        ("12pm", time(12, 0)),
        ("12:15 am", time(0, 15)),
        ("11:59pm", time(23, 59)),
        # 24-hour
        ("20:00", time(20, 0)),
        ("20.00", time(20, 0)),
        ("08:30", time(8, 30)),
        ("2030", time(20, 30)),
        ("0830", time(8, 30)),
        ("00:05", time(0, 5)),
        ("0:05", time(0, 5)),
        ("13:00", time(13, 0)),
        ("20", time(20, 0)),
        ("08", time(8, 0)),
        # words
        ("noon", time(12, 0)),
        ("midday", time(12, 0)),
        ("midnight", time(0, 0)),
        ("Noon", time(12, 0)),
        # as it arrives from a sentence
        ("at 20:00", time(20, 0)),
        ("  at  8 pm ", time(20, 0)),
    ],
)
def test_times_that_can_only_mean_one_thing(typed, expected):
    assert timeinput.parse_time(typed) == expected


@pytest.mark.parametrize(
    "typed, options, question",
    [
        ("8", (time(8, 0), time(20, 0)), "8am or 8pm?"),
        ("at 8", (time(8, 0), time(20, 0)), "8am or 8pm?"),
        ("8:30", (time(8, 30), time(20, 30)), "8:30 am or 8:30 pm?"),
        ("8.30", (time(8, 30), time(20, 30)), "8:30 am or 8:30 pm?"),
        ("830", (time(8, 30), time(20, 30)), "8:30 am or 8:30 pm?"),
        ("12", (time(0, 0), time(12, 0)), "12am or 12pm?"),
        ("12:30", (time(0, 30), time(12, 30)), "12:30 am or 12:30 pm?"),
        ("1", (time(1, 0), time(13, 0)), "1am or 1pm?"),
    ],
)
def test_a_time_that_could_be_morning_or_evening_is_asked_about_never_guessed(typed, options, question):
    with pytest.raises(AmbiguousTime) as raised:
        timeinput.parse_time(typed)
    assert raised.value.options == options
    assert str(raised.value) == question
    assert isinstance(raised.value, UserError), "so it is shown as it is when nothing catches it"


@pytest.mark.parametrize(
    "typed",
    ["", "soon", "25:00", "8:75", "13pm", "0am", "8:5", "24", "2460", "875", "8 o'clock", "8pm tomorrow", "-8", "8:30:15"],
)
def test_what_is_not_a_time_is_refused_with_examples(typed):
    with pytest.raises(UserError, match="can't read") as raised:
        timeinput.parse_time(typed)
    assert not isinstance(raised.value, AmbiguousTime)
    assert "`8pm`" in str(raised.value)


@pytest.mark.parametrize(
    "value, shown",
    [
        (time(8, 30), "8:30 am"),
        (time(20, 0), "8:00 pm"),
        (time(0, 0), "12:00 am"),
        (time(12, 0), "12:00 pm"),
        (time(0, 5), "12:05 am"),
        (time(12, 59), "12:59 pm"),
        (time(23, 59), "11:59 pm"),
        (time(9, 4), "9:04 am"),
    ],
)
def test_times_are_always_shown_in_12_hour_form(value, shown):
    assert timeinput.format_time(value) == shown


def test_whatever_was_typed_is_shown_the_same_way():
    assert timeinput.format_time(timeinput.parse_time("20:00")) == "8:00 pm"
    assert timeinput.format_time(timeinput.parse_time("2030")) == "8:30 pm"
    assert timeinput.format_time(timeinput.parse_time("8.30 am")) == "8:30 am"


def test_a_moment_is_shown_in_nz_time():
    assert timeinput.format_moment(datetime.fromisoformat("2026-10-09T07:04:00+00:00")) == "8:04 pm"


# ---------------------------------------------------------------------------
# A time given for something already done
# ---------------------------------------------------------------------------
NOW = nz(2026, 10, 9, 14, 0)


def test_a_time_earlier_today_is_accepted():
    assert timeinput.actual_moment("9am", NOW) == nz(2026, 10, 9, 9, 0)
    assert timeinput.actual_moment("14:00", NOW) == NOW, "now itself is not the future"
    timeinput.check_actual(nz(2026, 10, 9, 0, 0), NOW)


def test_a_time_in_the_future_is_refused():
    with pytest.raises(UserError, match=r"3:00 pm hasn't happened yet: it's 2:00 pm now\."):
        timeinput.actual_moment("3pm", NOW)


def test_a_time_on_another_day_is_refused():
    with pytest.raises(UserError, match="isn't today"):
        timeinput.check_actual(NOW - timedelta(days=1), NOW)
    with pytest.raises(UserError, match="isn't today"):
        timeinput.check_actual(nz(2026, 10, 8, 23, 59), NOW)


def test_a_time_before_the_previous_one_is_refused():
    previous = nz(2026, 10, 9, 10, 0)
    with pytest.raises(UserError, match=r"9:00 am is before the previous one, at 10:00 am\."):
        timeinput.actual_moment("9am", NOW, not_before=previous)
    assert timeinput.actual_moment("10:00", NOW, not_before=previous) == previous
    assert timeinput.actual_moment("11am", NOW, not_before=previous) == nz(2026, 10, 9, 11, 0)


def test_morning_or_evening_is_settled_when_only_one_can_be_meant():
    # At 2pm, "9" can only be this morning: 9pm hasn't happened
    assert timeinput.actual_moment("9", NOW) == nz(2026, 10, 9, 9, 0)
    assert timeinput.actual_moment("9:30", NOW) == nz(2026, 10, 9, 9, 30)
    # After a previous one at 10am, "1" can only be 1pm
    assert timeinput.actual_moment("1", NOW, not_before=nz(2026, 10, 9, 10, 0)) == nz(2026, 10, 9, 13, 0)


def test_morning_or_evening_is_still_asked_when_both_could_be_meant():
    with pytest.raises(AmbiguousTime, match="9am or 9pm"):
        timeinput.actual_moment("9", nz(2026, 10, 9, 22, 0))


def test_when_neither_reading_fits_the_reason_is_the_morning_ones():
    # 9am is before the previous one, 9pm hasn't happened
    with pytest.raises(UserError, match="9:00 am is before the previous one") as raised:
        timeinput.actual_moment("9", NOW, not_before=nz(2026, 10, 9, 10, 0))
    assert not isinstance(raised.value, AmbiguousTime)
