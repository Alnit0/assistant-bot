"""The Today card (core/today.py, tasks/today), behind TODAY_CARD: the day in time order by round 4's relevance rule, any time last by the list rule, reminders as notes, one small line when all is done."""
import asyncio
from datetime import date, time

from core import cards, config, design, today
from core import day as days
from core.today import Line
from tasks import registry

DAY = date(2026, 10, 19)


def at(hour, minute=0):
    return days.at(DAY, time(hour, minute))


def lines_of(pieces):
    return [line for text in design.texts(pieces) for line in text.splitlines()]


def a_day():
    return [
        Line("🔁", "**Morning** · at 7:00 am · 0/3", at(7)),
        Line("⏰", "**Call the bank**", at(11), note=True),
        Line("🔁", "**Evening** · 6:00 pm to 11:00 pm · 0/3", at(18), at(23)),
        Line("⏰", "**Bins out**", at(19, 30), note=True),
        Line("📝", "**Pay the power bill** · from yesterday"),
        Line("📝", "**Call the dentist**"),
        Line("📝", "**Buy stamps**"),
        Line("📝", "**Book the WOF**"),
        Line("📝", "**Reply to Sam**", done=True),
    ]


def test_off_unless_set_and_not_loaded():
    assert config.TODAY_CARD is False
    registry.load()
    assert "today" not in [task.name for task in registry.loaded_tasks()]


def test_the_morning_what_is_due_now_in_full_the_next_in_full_the_rest_small_and_any_time_last():
    pieces = today.layout(a_day(), at(7, 10))
    lines = lines_of(pieces)
    assert lines[0] == "### 🗓️ Today ●○○○○○○ 1/7", "notes are not counted"
    full = [line for line in lines if not line.startswith(("-#", "###"))]
    assert full[0] == "🔁 **Morning** · at 7:00 am · 0/3", "due now, first"
    assert full[1] == "⏰ **Call the bank**", "the next timed thing, in full"
    assert full[3:] == ["📝 **Pay the power bill** · from yesterday", "📝 **Call the dentist**", "📝 **Buy stamps**"], "any time last, the first three"
    assert "-# later today · 6:00 pm, 7:30 pm" in lines and "-# +1 more" in lines and "-# ✅ 1 done" in lines
    assert design.buttons(pieces) == [] and design.menus(pieces) == [], "no buttons: each is done on its own card"
    cards.check_layout(pieces)


def test_a_window_closed_undone_says_so():
    lines = lines_of(today.layout(a_day(), at(23, 30)))
    assert "🔁 **Evening** · 6:00 pm to 11:00 pm · 0/3" in lines and "-# not done yet" in lines
    assert not any("Bins out" in line for line in lines), "a note whose time has gone is not shown"


def test_when_everything_is_done_the_card_is_one_small_line():
    done = [Line("🔁", "**Morning**", at(7), done=True), Line("📝", "**Buy stamps**", done=True), Line("⏰", "**Bins out**", at(8), note=True)]
    assert lines_of(today.layout(done, at(9))) == ["-# 🗓️ Today · all done ✅ 2"]
    assert today.layout([], at(9)) == ()


def test_the_plain_text_marks_each_line():
    said = today.text(a_day(), at(7, 10)).splitlines()
    assert said[0] == "## 🗓️ Today" and said[1] == "▫️ 🔁 **Morning** · at 7:00 am · 0/3" and "🗒️ ⏰ **Call the bank** · 11:00 am" in said and "✅ 📝 **Reply to Sam**" in said


def test_gather_asks_every_task_with_a_today_and_leaves_out_one_that_fails(monkeypatch):
    from types import SimpleNamespace

    from core import actions

    async def fine(user_id, now):
        return [Line("📝", "**Later**"), Line("🔁", "**Early**", at(7))]

    async def broken(user_id, now):
        raise RuntimeError("no")

    monkeypatch.setattr(actions, "catalogue", lambda: [SimpleNamespace(name="a", today=fine), SimpleNamespace(name="b", today=broken), SimpleNamespace(name="c", today=None)])
    found = asyncio.run(today.gather(1, at(6)))
    assert [each.text for each in found] == ["**Early**", "**Later**"], "in time order, any time last"
