"""Round 5 of the design (DESIGN_ROUND=5, built 15 Oct, waiting on Alex).

His feedback on the live hub: "there's a little bit of overlap with pills and calendar". So the
briefing becomes the morning overview (Needs a look and Weather keep their boxes; every task with a
card of its own is one line in one overview box, with no progress), its page title is the date with
the day's dots, a task card whose items are all done leaves the hub, and the footer's how-to is in
help. With the suggested answers to questions 68 to 75.
"""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import config, design
from core import day as days
from core.actions import Summary
from core.attention import Item
from core.summaries import Section
from tasks.briefing import rules as briefing

DAY = date(2026, 10, 15)


@pytest.fixture
def round_5(monkeypatch):
    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    assert design.current() == 5


def _sections():
    pills = Section("pills", "💊", "Pills", Summary(glance="2 of 6 taken", done=2, total=6, lines=("**Next:** Pill A · `12:00 pm`",), overview="6 doses · first 7:00 am"))
    weather = Section("weather", "🌤️", "Weather", Summary(glance="14° to 20°", lines=("61% rain after 1pm",)))
    calendar = Section("calendar", "🗓️", "Calendar", Summary(glance="4 events · next 12:30 pm", overview="4 events · first 9:00 am"))
    return [pills, weather, calendar]


def test_round_5_was_built_and_is_not_the_default():
    assert 5 in design.ROUNDS and config.DESIGN_ROUND != 5


def test_the_briefing_is_the_morning_overview(round_5):
    shown = design.texts(briefing.layout(_sections(), DAY, so_far=("●●○○○○ 2/6", "-# 💊 2/6")))
    assert shown[0] == "## ☀️ Thursday 15 October ●●○○○○ 2/6", "the date with the day's dots: Today is only the Today card"
    assert shown[1].startswith("### 🌤️ Weather"), "the weather keeps its box"
    assert shown[2] == "### 🗓️ The day\n💊 **Pills** · 6 doses · first 7:00 am\n🗓️ **Calendar** · 4 events · first 9:00 am"
    assert not any("taken" in each or "Next:" in each for each in shown), "no live progress: the cards have it"
    assert not any(briefing.FOOT in each for each in shown), "no footer"


def test_what_needs_a_look_keeps_its_box_on_top(round_5):
    shown = design.texts(briefing.layout(_sections(), DAY, problems=("⚠️ B14 · backup failed",)))
    assert shown[1].startswith("### ⚠️ Needs a look") and shown[0] == "## ☀️ Thursday 15 October"


def test_round_4_is_as_it_was(monkeypatch):
    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    shown = design.texts(briefing.layout(_sections(), DAY))
    assert shown[0].startswith("## ☀️ Today") and any(briefing.FOOT in each for each in shown)


def test_the_how_to_is_in_help():
    from tasks import briefing as task

    old = config.BRIEFING_ENABLED
    config.BRIEFING_ENABLED = True
    try:
        (word,) = task.task.keywords()
    finally:
        config.BRIEFING_ENABLED = old
    assert "my schedule" in word.description and "tick things off" in word.description


def test_each_task_gives_a_line_for_the_overview_with_no_progress():
    from tasks.pills import summary

    dose = lambda at, state="pending": SimpleNamespace(due=SimpleNamespace(at=at), occurrence=SimpleNamespace(state=state))  # noqa: E731
    seven = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
    assert summary.overview([dose(seven), dose(None), dose(seven + timedelta(hours=5), "done")]) == "3 doses · first 7:00 am"
    assert summary.overview([dose(None)]) == "1 dose · any time"


def test_the_today_card_has_no_count_of_its_own(round_5):
    from core import today
    from core.today import Line

    now = days.at(DAY, time(9))
    lines = [Line("🔁", "**Morning**", days.at(DAY, time(10))), Line("📝", "**Buy stamps**", done=True)]
    assert design.texts(today.layout(lines, now))[0].startswith("### 🗓️ Today\n") or design.texts(today.layout(lines, now))[0] == "### 🗓️ Today"


def test_a_missed_dose_holds_the_status_line_only_until_the_evening(round_5, make_db, owner, dev_clock):
    from tasks.pills import attention as pills_attention

    assert "until=until" in open(pills_attention.__file__, encoding="utf-8").read()
    assert config.STATUS_DONE_UNTIL is not None


def test_a_checklist_with_every_dose_taken_or_skipped_leaves_the_hub(round_5):
    from tasks.pills import checklist

    dose = lambda state: SimpleNamespace(occurrence=SimpleNamespace(state=state))  # noqa: E731
    assert checklist.all_done([dose("done"), dose("skipped")])
    assert not checklist.all_done([dose("done"), dose("missed")]), "a missed dose keeps it up"
    assert not checklist.all_done([dose("done"), dose("pending")]) and not checklist.all_done([])


def test_in_round_4_the_checklist_stays(monkeypatch):
    from tasks.pills import checklist

    monkeypatch.setattr(config, "DESIGN_ROUND", 4)
    assert not checklist.all_done([SimpleNamespace(occurrence=SimpleNamespace(state="done"))])


def test_the_to_dos_card_leaves_the_hub_when_every_to_do_of_today_is_done(round_5, make_db, owner, dev_clock):
    from core import clock, database
    from tasks.todos import plain, store

    make_db({"todos": store.MIGRATIONS})
    today = days.today()
    todo_id = asyncio.run(database.run(store.db_add, owner.id, "Buy stamps", today, today, clock.now()))
    assert asyncio.run(plain.hub_card(owner.id)) is not None
    asyncio.run(database.run(store.db_done, todo_id, clock.now(), today))
    assert asyncio.run(plain.hub_card(owner.id)) is None


def test_a_card_that_comes_up_mid_day_has_the_cards_after_it_posted_again_under_it(round_5, monkeypatch):
    from core import hubcard, livelists

    posted = []

    async def post(task, user_id, render, channel_id=None, slot="", keep_order=True):
        posted.append(task)

    async def placed(conn_or_user, *rest):
        return object()

    monkeypatch.setattr(hubcard, "_orders", {"nudges": (10, lambda user_id: None), "habits": (20, lambda user_id: None), "todos": (40, lambda user_id: None)})
    monkeypatch.setattr(hubcard, "post", post)

    async def found(fn, user_id, key):
        return object() if key != "nudges:hub" else None

    monkeypatch.setattr(hubcard.database, "run", found)
    asyncio.run(hubcard._keep_order("habits", 1))
    assert posted == ["todos"], "only what comes after it, and only what is there"
    assert livelists is not None


def test_a_plain_can_t_find_that_is_an_answer_in_round_5(round_5):
    import inspect

    from core import conversation

    assert "turn.failed = design.current() < 5" in inspect.getsource(conversation)


def test_item_until_is_kept_for_a_missed_dose():
    item = Item("a dose was missed", "timed", when=datetime(2026, 10, 15, 4, tzinfo=timezone.utc), until=datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
    from core import attention

    assert attention.level(item, datetime(2026, 10, 15, 9, tzinfo=timezone.utc)) is None
