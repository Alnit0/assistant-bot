from datetime import date

import pytest

from skills.lab.common import Args, LabError
from skills.lab.data import build_csv, fill_days

USAGE = "lab chart [quickchart|matplotlib] [days]"


def args(text: str) -> Args:
    return Args(text.split(), USAGE)


# --- reading the words after a lab phrase -----------------------------------
def test_a_choice_is_taken_when_it_is_one_of_the_options():
    reader = args("Matplotlib 14")
    assert reader.choice(["quickchart", "matplotlib"], "quickchart") == "matplotlib"
    assert reader.words == ["14"]


def test_a_choice_falls_back_to_its_default():
    reader = args("14")
    assert reader.choice(["quickchart", "matplotlib"], "quickchart") == "quickchart"
    assert reader.words == ["14"], "the word is left for whatever reads next"


def test_a_required_choice_that_is_missing_gives_the_usage():
    with pytest.raises(LabError, match="Usage: `lab chart"):
        args("loud").choice(["normal", "silent"])


def test_a_number_within_range():
    assert args("14").number("days", 30, 1, 90) == 14


def test_a_missing_number_uses_the_default():
    assert args("").number("days", 30, 1, 90) == 30
    assert args("soon").number("days", 30, 1, 90) == 30


@pytest.mark.parametrize("text", ["0", "91", "-5"])
def test_a_number_out_of_range_says_what_the_range_is(text):
    with pytest.raises(LabError, match="days must be between 1 and 90"):
        args(text).number("days", 30, 1, 90)


def test_a_flag_is_noticed_and_used_up():
    reader = args("multiple")
    assert reader.flag("multiple") is True
    assert reader.flag("multiple") is False


@pytest.mark.parametrize("text, expected", [("delay 90", 90), ("90", 90), ("", 0)])
def test_a_delay_with_or_without_the_word(text, expected):
    assert args(text).delay(3600) == expected


@pytest.mark.parametrize("text", ["delay", "delay soon"])
def test_the_word_delay_needs_a_number(text):
    with pytest.raises(LabError, match="Usage:"):
        args(text).delay(3600)


def test_a_delay_longer_than_allowed_is_refused():
    with pytest.raises(LabError, match="delay must be between 0 and 3600"):
        args("delay 4000").delay(3600)


def test_leftover_words_are_a_mistake():
    reader = args("matplotlib 14 please")
    reader.choice(["quickchart", "matplotlib"], "quickchart")
    reader.number("days", 30, 1, 90)
    with pytest.raises(LabError, match="Usage:"):
        reader.finish()


def test_nothing_left_over_is_fine():
    args("").finish()


# --- daily stats for the chart and the CSV ----------------------------------
def test_days_with_nothing_logged_are_filled_with_zeros():
    rows = [("2026-10-05", 3, 2, 1, 0, 100, 50, 0.01), ("2026-10-07", 1, 0, 0, 1, 10, 5, 0.001)]
    stats = fill_days(rows, date(2026, 10, 5), date(2026, 10, 7))
    assert [day.day for day in stats] == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]
    assert [day.messages for day in stats] == [3, 0, 1]
    assert (stats[1].commands, stats[1].errors, stats[1].cost) == (0, 0, 0.0)
    assert stats[2].errors == 1


def test_one_day_is_one_entry():
    assert len(fill_days([], date(2026, 10, 7), date(2026, 10, 7))) == 1


def test_the_csv_has_a_header_and_one_line_per_day():
    stats = fill_days([("2026-10-06", 3, 2, 1, 0, 100, 50, 0.0123)], date(2026, 10, 6), date(2026, 10, 7))
    assert build_csv(stats).splitlines() == [
        "date,messages,commands,other,errors,input_tokens,output_tokens,cost_usd",
        "2026-10-06,3,2,1,0,100,50,0.012300",
        "2026-10-07,0,0,0,0,0,0,0.000000",
    ]
