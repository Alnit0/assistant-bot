"""When doses were taken (tasks/pills/taken.py): bug from live, 15 Oct. "When did I take my pills today" was
answered with what is left; now each taken dose and its time, and anything skipped or missed. Made-up pills."""
from datetime import date, time
from types import SimpleNamespace

from core import day as days
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from core.schedule import ANY_TIME, Due
from tasks.pills import plain, taken
from tasks.pills.today import Dose

DAY = date(2026, 10, 15)


def pill(pill_id, name, per_day=1):
    return SimpleNamespace(id=pill_id, plan=SimpleNamespace(name=name, schedule=SimpleNamespace(per_day=per_day)))


def dose(of, seq, state, planned=None, at=None, day=DAY):
    when = days.at(day, at) if at else None
    occurrence = Occurrence(seq, 1, "pills", of.id, day, seq, planned, days.at(day, planned) if planned else None, state, when, False, None)
    return Dose(of, occurrence, Due(None, ANY_TIME))


A, B = pill(1, "Pill A", 3), pill(2, "Pill B")


def _day():
    return [
        dose(A, 1, DONE, time(8), time(8, 4)),
        dose(A, 2, SKIPPED, time(11)),
        dose(A, 3, PENDING, time(14)),
        dose(B, 1, MISSED, time(7)),
    ]


def test_each_taken_dose_with_its_time_then_skipped_and_missed():
    said = taken.answer(_day(), DAY, DAY)
    first, *rest = said.splitlines()
    assert first == "💊 **1 taken today** · ●●○○ 2/4", "the first line names no pill"
    assert rest[0] == "✅ **Pill A** (dose 1 of 3) · taken 8:04 am"
    assert rest[1:] == ["❌ **Pill B** · missed", "⏭️ **Pill A** (dose 2 of 3) · skipped"], "in time order"
    assert "dose 3" not in said, "a dose still to take is not part of when they were taken"


def test_a_dose_asked_about_by_number_still_to_take_is_said_not_yet():
    chosen = taken.narrowed(_day(), number=3)
    assert taken.answer(chosen, DAY, DAY, narrowed_to=True).splitlines() == ["💊 **Nothing taken today yet** · ○ 0/1", "💊 **Pill A** (dose 3 of 3) · not taken yet"]


def test_narrowed_by_pill_and_by_part_of_the_day():
    assert [each.number for each in taken.narrowed(_day(), pill_id=1)] == [1, 2, 3]
    assert [(each.pill.id, each.number) for each in taken.narrowed(_day(), part="morning")] == [(1, 1), (1, 2), (2, 1)]
    assert [each.number for each in taken.narrowed(_day(), part="afternoon")] == [3]


def test_a_day_gone_by_is_named():
    yesterday = date(2026, 10, 14)
    said = taken.answer([dose(B, 1, DONE, time(21), time(21, 10), day=yesterday)], yesterday, DAY)
    assert said.splitlines()[0].startswith("💊 **1 taken yesterday**")
    tuesday = date(2026, 10, 13)
    assert taken.answer([], tuesday, DAY) == "💊 Nothing was to take on Tue 13 Oct."


def test_when_last_taken():
    last = dose(A, 2, DONE, time(11), time(11, 20), day=date(2026, 10, 14))
    assert taken.last_answer(last, DAY) == "💊 **Last taken yesterday**\n✅ **Pill A** (dose 2 of 3) · taken 11:20 am"
    assert taken.last_answer(None, DAY).startswith("💊 Not taken in the last")


def test_the_day_said_is_read_by_the_code():
    assert taken._day(None, DAY) == DAY and taken._day("today", DAY) == DAY
    assert taken._day("yesterday", DAY) == date(2026, 10, 14)
    assert taken._day("Tuesday", DAY) == date(2026, 10, 13)


def test_what_is_left_and_when_taken_are_two_actions():
    names = [action.name for action in plain.ACTIONS]
    assert "pill_today" in names and "pill_taken" in names
    asked = next(action for action in plain.ACTIONS if action.name == "pill_taken")
    assert {field.name for field in asked.fields} == {"day", "pill", "dose", "part", "last", "also_left"}
    assert "pill_taken" in next(action for action in plain.ACTIONS if action.name == "pill_today").description
