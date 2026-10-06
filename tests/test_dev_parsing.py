import pytest

from core import devmode
from core.errors import UserError


@pytest.mark.parametrize(
    "words, expected",
    [(["60"], 60), (["0"], 0), (["2.5"], 2.5), (["2s"], 2), (["60x"], 60), (["60X"], 60)],
)
def test_a_number(words, expected):
    assert devmode.parse_number(words, "dev speed <n>") == expected


@pytest.mark.parametrize("words", [[], ["fast"], ["1", "2"], ["x"], [""]])
def test_not_a_number_gives_the_usage(words):
    with pytest.raises(UserError, match=r"Usage: `dev speed <n>`\."):
        devmode.parse_number(words, "dev speed <n>")


@pytest.mark.parametrize("words, expected", [(["on"], True), (["off"], False), (["ON"], True), (["Off"], False)])
def test_on_and_off(words, expected):
    assert devmode.parse_on_off(words, "dev verbose on|off") is expected


@pytest.mark.parametrize("words", [[], ["yes"], ["on", "please"], ["1"]])
def test_anything_else_gives_the_usage(words):
    with pytest.raises(UserError, match=r"Usage: `dev verbose on\|off`\."):
        devmode.parse_on_off(words, "dev verbose on|off")


def test_a_bad_value_leaves_dev_mode_as_it_was(dev_off):
    devmode.enable()
    with pytest.raises(UserError):
        devmode.set_speed(devmode.parse_number(["0"], "dev speed <n>"))
    assert devmode.settings == devmode.DEFAULTS
