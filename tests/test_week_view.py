"""The week view (core/weekview.py, tasks/week), behind WEEK_VIEW: a box a day Monday to Sunday from every task's
day, what comes every day folded into one small line, today highlighted and past days faint; next week a line a
day; in #calendar this week pinned and next week below it, edited in place, posted again in order when gone, at
most an edit a minute; "my week" and the calendar's week and day answers in the same layout. Made-up names only."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, database, design, live, pins, planning, weekview
from core import day as days
from core.planning import Piece
from tasks import week

MONDAY = date(2026, 10, 19)
CALENDAR = 600


def at(day, hour, minute=0):
    return days.at(day, time(hour, minute))


def pieces_for(day):
    found = [
        Piece("pills", "p1.1", "💊", "Pill A", at(day, 8), fold="dose"),
        Piece("pills", "p1.2", "💊", "Pill A", at(day, 14), fold="dose"),
        Piece("pills", "p2.1", "💊", "Pill B", at(day, 8), fold="dose"),
        Piece("habits", "h1", "🔁", "Made-up morning", at(day, 7), at(day, 7, 30), fold="routine"),
        Piece("todos", "t1", "📝", "Made-up to-do", flexible=True),
    ]
    if day.weekday() == 2:
        found += [Piece("calendar", "e1", "📅", "Made-up dentist", at(day, 15), at(day, 16)), Piece("nudges", "n1", "⏰", "Made-up call", at(day, 12, 30))]
    if day.weekday() == 4:
        found.append(Piece("birthdays", "b1", "🎂", "Mum's birthday", all_day=True))
    return found


def test_a_day_lists_what_is_notable_in_time_order_and_folds_what_comes_every_day():
    wednesday = weekview.of(MONDAY + timedelta(days=2), pieces_for(MONDAY + timedelta(days=2)))
    assert [each.text for each in wednesday.notable] == ["Made-up call", "Made-up dentist"], "to-dos are not in it; doses and routines are counted"
    assert weekview.folded_line(wednesday) == "💊 3 doses · 🔁 1 routine"
    friday = weekview.of(MONDAY + timedelta(days=4), pieces_for(MONDAY + timedelta(days=4)))
    assert weekview.piece_line(friday.notable[0]) == "🎂 Mum's birthday", "all day first"
    assert weekview.piece_line(wednesday.notable[0]) == "**12:30 pm** · ⏰ Made-up call"


def test_this_week_is_a_box_a_day_today_highlighted_and_past_days_faint():
    found = [weekview.of(day, pieces_for(day)) for day in weekview.week_of(MONDAY + timedelta(days=3))]
    today = MONDAY + timedelta(days=2)
    layout = weekview.this_week(found, today)
    boxes = [each for each in layout if isinstance(each, design.Box)]
    assert len(boxes) == 7 and not design.problem(layout)
    assert [box.status for box in boxes][:3] == [design.QUIET, design.QUIET, design.DUE], "Wednesday is today"
    words = design.texts(layout)
    tuesday = next(each for each in words if "Tue 20 Oct" in each)
    assert all(line.startswith("-# ") for line in tuesday.splitlines()[1:]), "a day gone by is faint"
    assert any("Today · Wed 21 Oct" in each for each in words)
    assert weekview.span_text(MONDAY, MONDAY + timedelta(days=6)) == "19 to 25 Oct"


def test_next_week_is_one_line_a_day():
    following = [weekview.of(day, pieces_for(day)) for day in weekview.week_of(MONDAY + timedelta(days=7))]
    layout = weekview.next_week(following, MONDAY)
    (box,) = [each for each in layout if isinstance(each, design.Box)]
    words = "\n".join(design.texts(layout))
    assert "**Wed 28 Oct** · 12:30 pm Made-up call · 3:00 pm Made-up dentist · 💊 3 doses · 🔁 1 routine" in words
    assert "**Fri 30 Oct** · 🎂 Mum's birthday · 💊 3 doses · 🔁 1 routine" in words


# --- #calendar: two messages, pinned, edited in place ------------------------------------------------------------------
@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"week": week.MIGRATIONS})
    monkeypatch.setattr(config, "WEEK_VIEW", True)
    monkeypatch.setattr(config, "CALENDAR_CHANNEL_ID", CALENDAR)
    seen = SimpleNamespace(sent=[], edited=[], deleted=[], pinned=[], gone=set(), next_id=100)

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        if message_id in seen.gone:
            return False
        seen.edited.append(message_id)
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    async def set_pinned(channel_id, message_id, pinned, reason):
        seen.pinned.append(message_id)

    async def gather(user_id, day):
        return pieces_for(day)

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(pins, "set_pinned", set_pinned)
    monkeypatch.setattr(planning, "gather", gather)
    seen.owner = owner
    return seen


def test_the_first_draw_posts_both_silently_and_pins_this_week(world):
    said = asyncio.run(week.redraw(world.owner.id))
    assert said == "this posted, next posted"
    assert [each.silent for each in world.sent] == [True, True], "never a ping"
    assert world.pinned == [world.sent[0].id]
    assert world.sent[0].card.text.startswith("## 🗓️ This week") and world.sent[1].card.text.startswith("## 🗓️ Next week")


def test_after_that_both_are_edited_in_place(world):
    asyncio.run(week.redraw(world.owner.id))
    assert asyncio.run(week.redraw(world.owner.id)) == "this edited, next edited"
    assert len(world.sent) == 2 and world.edited == [world.sent[0].id, world.sent[1].id]


def test_this_week_gone_is_posted_again_and_next_week_again_below_it(world):
    asyncio.run(week.redraw(world.owner.id))
    first, second = world.sent[0].id, world.sent[1].id
    world.gone.add(first)
    assert asyncio.run(week.redraw(world.owner.id)) == "this posted, next posted"
    assert world.deleted == [second] and world.pinned[-1] == world.sent[2].id, "the order kept: this week, then next week"


def test_a_change_is_coalesced_to_at_most_one_edit_a_minute(world, monkeypatch):
    asked = []
    monkeypatch.setattr(live, "schedule", lambda key, refresh, slow=False, every=None: asked.append((key, every)))
    week.changed("todos", world.owner.id)
    week.changed("nudges", world.owner.id)
    assert asked == [(("week", world.owner.id), 60.0)] * 2, "one key: the requests become one edit"
    week.changed("week", world.owner.id)
    assert len(asked) == 2, "its own changes are not news"
    assert live.wait_needed(100.0, 130.0, 60.0) == 30.0


def test_the_bot_s_own_schedule_redraws_at_12_01_am_and_my_week_answers_in_place(world, monkeypatch):
    assert (week.DEFAULT.at, week.DEFAULT.locked) == (time(0, 1), True)
    assert week.task.job_handlers()[week.JOB] is week.redraw_job
    ctx = SimpleNamespace(user=world.owner, channel_id=100)
    assert asyncio.run(week.my_week(ctx)) == "this week shown"
    assert world.sent[-1].channel == 100 and world.sent[-1].card.text.startswith("## 🗓️ This week")


def test_the_calendar_answers_a_week_or_a_day_in_the_same_layout(world):
    from core.actions import Request
    from tasks.calendar import plain as calendar_plain

    asyncio.run(calendar_plain.show(Request(world.owner, 100, "next week"), {"span": "next_week"}, frozenset()))
    assert world.sent[-1].card.text.startswith("## 🗓️ Next week")
    asyncio.run(calendar_plain.show(Request(world.owner, 100, "what's on Thursday"), {"day": "Thursday"}, frozenset()))
    assert world.sent[-1].card.text.startswith("**Thu ") and "💊 3 doses" in world.sent[-1].card.text


def test_off_unless_switched_on_and_given_a_channel(monkeypatch):
    monkeypatch.setattr(config, "WEEK_VIEW", True)
    monkeypatch.setattr(config, "CALENDAR_CHANNEL_ID", None)
    assert not week.task.switched_on()
    monkeypatch.setattr(config, "CALENDAR_CHANNEL_ID", CALENDAR)
    assert week.task.switched_on()
