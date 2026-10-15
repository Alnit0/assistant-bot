"""Fixes from the overnight batch of 16 Oct: a destination named by a task's title, two destinations in one
clause, and the day in the hub's replay day. Made-up words only."""
from datetime import date

from core import actions, routing


def _entry(name, label=""):
    return actions.Entry(name, "•", f"Only for {name}.", ("a", "b"), (), on_repeat="allow_another", label=label)


ENTRIES = [_entry("todos", "To-dos"), _entry("diary"), _entry("shopping")]


def test_a_destination_named_by_the_tasks_title_is_read():
    assert [each.name for each in routing.named_destinations("add call the garage to my to-dos", ENTRIES)] == ["todos"]


def test_two_destinations_in_one_clause_the_last_is_where_it_goes():
    assert [each.name for each in routing.named_destinations("add write in my diary to my to-dos", ENTRIES)] == ["todos"]


def test_parts_joined_by_and_keep_a_destination_each():
    said = "put milk on my shopping list and add call the garage to my to-dos"
    assert [each.name for each in routing.named_destinations(said, ENTRIES)] == ["todos", "shopping"]


def test_the_replay_is_a_sunday():
    from selftest import day

    assert day.day_of_run(date(2026, 10, 16)) == date(2026, 10, 18)
    assert day.day_of_run(date(2026, 10, 18)) == date(2026, 10, 25), "from tomorrow: a Sunday is never today"
    assert day.SETTINGS["DESIGN_ROUND"] == "5" and day.SETTINGS["CALENDAR_WRITE"] == "true"
