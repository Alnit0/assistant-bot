"""Round 7 of the hub (DESIGN_ROUND=7, Alex, 21 Oct): the briefing as two messages of embeds, each embed's border
colour saying what it is (tasks/briefing/embeds.py), from what each task hands over (`Entry.day_items`). Message 1:
the date as its text, then the day's things in time order; message 2, no text: the to-dos and the diary, not sent
with neither. Also: 🗓️ for the calendar everywhere, and the calendar's answers its events alone. Made-up names."""
import subprocess
from datetime import date, time
from pathlib import Path

import pytest

from core import actions, config, database, design, livelists
from core import day as days
from core.actions import DOSE, EVENT, MISSED, ROUTINE, SKIPPED, TAKEN, TODO, TRACKING, DayItem, Entry
from core.cards import MAX_EMBEDS, Card, Embed
from tasks import briefing
from tasks.briefing import embeds
from tests.test_briefing import on  # noqa: F401
from tests.test_pills_reminders import HUB, add, at, log, run, world  # noqa: F401

TODAY = date(2026, 10, 21)  # a Wednesday


def local(hour, minute=0, on=TODAY):
    return days.at(on, time(hour, minute))


NOW = local(9, 30)


def statuses(card):
    return [each.status for each in card.embeds]


def lines(card):
    return [each.description for each in card.embeds]


# --- message 1: the day in time order ---------------------------------------------------------------------------------
def test_the_date_is_the_message_s_text_and_each_thing_is_an_embed():
    card = embeds.your_day([DayItem(EVENT, "Team meeting", local(11), local(12))], TODAY, NOW)
    assert card.heading == "🗓️ **Wednesday 21 October**" and card.text.startswith(card.heading)
    assert lines(card) == ["11:00 am · Team meeting · until 12:00 pm"] and statuses(card) == [design.NOTABLE]


def test_mixed_kinds_are_in_time_order_whoever_s_they_are():
    items = [DayItem(ROUTINE, "Evening", local(22)), DayItem(EVENT, "Work", local(9), local(17), repeats=True), DayItem(DOSE, "Morning dose", local(8))]
    card = embeds.your_day(items, TODAY, NOW)
    assert lines(card) == ["8:00 am · 💊 Morning dose · 🟥 Due", "9:00 am · Work · until 5:00 pm", "10:00 pm · 🌙 Evening"]
    assert statuses(card) == [design.DUE_NOW, design.ROUTINE, design.ROUTINE], "a dose due red; work, which repeats, blue; a routine blue"


def test_at_the_same_time_events_come_first_then_doses_then_routines():
    items = [DayItem(ROUTINE, "Morning", local(8)), DayItem(DOSE, "Morning dose", local(8)), DayItem(EVENT, "Team meeting", local(8))]
    assert [each.description.split(" · ")[1] for each in embeds.your_day(items, TODAY, NOW).embeds] == ["Team meeting", "💊 Morning dose", "🌙 Morning"]


def test_a_point_event_has_no_until_and_an_all_day_or_coming_one_a_title_and_its_days():
    items = [
        DayItem(EVENT, "Team meeting", local(14), local(14)),
        DayItem(EVENT, "Conference", first_day=TODAY, last_day=TODAY),
        DayItem(EVENT, "Hen do", first_day=date(2026, 11, 21), last_day=date(2026, 11, 22)),
        DayItem(EVENT, "Dentist", local(15, on=date(2026, 10, 23)), local(16, on=date(2026, 10, 23))),
    ]
    card = embeds.your_day(items, TODAY, NOW)
    assert [(each.title, each.description, each.status) for each in card.embeds] == [
        ("🎉 Conference", "Wed 21 Oct · all day", design.NOTABLE),
        ("", "2:00 pm · Team meeting", design.NOTABLE),
        ("🎉 Dentist", "Fri 23 Oct · 3:00 pm to 4:00 pm", design.NOTABLE),
        ("🎉 Hen do", "Sat 21 Nov to Sun 22 Nov · all day", design.NOTABLE),
    ], "all day first, coming up last, in date order; no calendar emoji on a line"
    assert not any("🗓️" in each.description or "\U0001F4C5" in each.description for each in card.embeds)


@pytest.mark.parametrize("item, line, status", [
    (DayItem(DOSE, "Evening dose", local(20)), "8:00 pm · 💊 Evening dose · ⬜ Later", design.LATER),
    (DayItem(DOSE, "Morning dose", local(8)), "8:00 am · 💊 Morning dose · 🟥 Due", design.DUE_NOW),
    (DayItem(DOSE, "Morning dose", local(8), state=TAKEN, done_at=local(8, 5)), "8:00 am · 💊 Morning dose · 🟩 Taken 8:05 am", design.TAKEN),
    (DayItem(DOSE, "Midday dose", local(9), state=SKIPPED), "9:00 am · 💊 Midday dose · ⏭️ Skipped", design.LATER),
    (DayItem(DOSE, "Midday dose", local(9), state=MISSED), "9:00 am · 💊 Midday dose · ⬛ Missed", design.LATER),
])
def test_each_dose_state_has_its_square_and_its_border(item, line, status):
    (embed,) = embeds.your_day([item], TODAY, NOW).embeds
    assert (embed.description, embed.status) == (line, status)


def test_the_border_colours_are_the_ones_asked_for():
    assert {status: design.embed_colour(status) for status in (design.ROUTINE, design.TAKEN, design.DUE_NOW, design.NOTABLE, design.LATER, design.PREPARED, design.TODOS, design.TRACKING)} == {
        design.ROUTINE: 0x5865F2, design.TAKEN: 0x57F287, design.DUE_NOW: 0xED4245, design.NOTABLE: 0xFEE75C,
        design.LATER: 0x4E5058, design.PREPARED: 0x9B59B6, design.TODOS: 0xEB459E, design.TRACKING: 0x5865F2,
    }


def test_more_than_ten_things_end_in_one_grey_embed_of_the_rest():
    items = [DayItem(DOSE, f"Dose {number}", local(6 + number)) for number in range(14)]
    card = embeds.your_day(items, TODAY, local(5))
    assert len(card.embeds) == MAX_EMBEDS and card.embeds[-1].title == embeds.MORE_TITLE and card.embeds[-1].status == design.LATER
    assert card.embeds[-1].description.count("\n") == 4, "the last five, a line each"


# --- message 2: everything else -------------------------------------------------------------------------------------------
def test_message_two_is_the_to_dos_and_the_diary_with_no_text_of_its_own():
    items = [DayItem(TODO, "Buy stamps"), DayItem(TODO, "Call the plumber", state=TAKEN), DayItem(TRACKING, "Diary · Streak: 4 days", icon="📓")]
    card = embeds.everything_else(items)
    todos, diary = card.embeds
    assert card.heading == "" and (todos.title, todos.description, todos.status) == ("☑️ To-dos", "☐ Buy stamps\n☑ Call the plumber", design.TODOS)
    assert (diary.description, diary.status) == ("📓 Diary · Streak: 4 days", design.TRACKING)
    assert embeds.everything_else([DayItem(DOSE, "Morning dose", local(8))]) is None, "nothing for it: not sent"


# --- the hub: one message or two ------------------------------------------------------------------------------------------
def _entry(name, items):
    async def day_items(user_id, day):
        return items

    return Entry(name, "📦", f"Only for {name}.", ("a", "b"), (), day_items=day_items, on_repeat="allow_another")


@pytest.fixture
def seven(on, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    return on


def posted(world):
    return [each for each in world.sent if each.card.embeds or each.card.heading]


def test_the_briefing_is_two_messages_with_something_for_both(seven, monkeypatch):
    seen = list(actions.catalogue())
    actions.set_catalogue([*seen, _entry("made_up_day", [DayItem(EVENT, "Team meeting", local(11, on=seven.day), local(12, on=seven.day))]),
                           _entry("made_up_list", [DayItem(TODO, "Buy stamps")])])
    first = run(briefing.post_in_hub(seven.owner.id, HUB))
    one, two = posted(seven)
    assert one.id == first and one.card.heading.startswith("🗓️ **") and two.card.heading == "" and two.silent
    assert [each.title for each in two.card.embeds] == ["☑️ To-dos"]
    again = run(briefing.post_in_hub(seven.owner.id, HUB))
    assert again != first and {first, two.id} <= set(seven.deleted), "the next morning's take both places"


def test_the_briefing_is_one_message_when_the_second_would_be_empty(seven):
    actions.set_catalogue([*actions.catalogue(), _entry("made_up_day", [DayItem(EVENT, "Team meeting", local(11, on=seven.day), local(12, on=seven.day))])])
    run(briefing.post_in_hub(seven.owner.id, HUB))
    (only,) = posted(seven)
    assert only.card.embeds[0].description.endswith("Team meeting · until 12:00 pm")


def test_real_doses_as_the_pills_task_hands_them_over(seven):
    add(seven, {"name": "Morning dose", "times": ["8:00 am"]}, {"name": "Evening dose", "times": ["8:00 pm"]})
    at(seven, 9, 0)
    log(seven, {"pill": "morning dose", "did": "taken", "at": "8:05 am"})
    run(briefing.post_in_hub(seven.owner.id, HUB))
    (one,) = posted(seven)
    assert lines(one.card) == ["8:00 am · 💊 Morning dose · 🟩 Taken 8:05 am", "8:00 pm · 💊 Evening dose · ⬜ Later"]
    assert statuses(one.card) == [design.TAKEN, design.LATER]


def test_a_change_rewrites_both_messages_in_place_as_embeds(seven):
    """Through a day's changes the two messages stay where they are, edited, and stay embeds."""
    briefing.task.setup(None)
    add(seven, {"name": "Morning dose", "times": ["8:00 am"]})
    actions.set_catalogue([*actions.catalogue(), _entry("made_up_list", [DayItem(TODO, "Buy stamps")])])
    first = run(briefing.post_in_hub(seven.owner.id, HUB))
    two = posted(seven)[1].id
    at(seven, 9, 0)
    log(seven, {"pill": "morning dose", "did": "taken", "at": "8:05 am"})
    ones = [card for message_id, card in seven.edited if message_id == first]
    assert ones and ones[-1].embeds and lines(ones[-1])[0].endswith("🟩 Taken 8:05 am"), "edited in place, still embeds"
    assert len(posted(seven)) == 2 and first not in seven.deleted and two not in seven.deleted, "nothing posted again"


def test_a_hub_message_from_before_round_seven_is_posted_again_as_embeds(seven, monkeypatch):
    """A briefing posted under round 5 is a layout, which Discord never lets take embeds (live, 21 Oct: the
    hub's message read as plain lines all day): the first change posts it again, as embeds, and the old goes."""
    from core import cards

    briefing.task.setup(None)
    add(seven, {"name": "Morning dose", "times": ["8:00 am"]})
    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    old = run(briefing.post_in_hub(seven.owner.id, HUB))
    assert seven.sent[-1].card.layout and not seven.sent[-1].card.embeds, "round 5's look"
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    edit = cards.edit

    async def refusing(channel_id, message_id, card, *, fall_back=True):
        if message_id == old and card.embeds:
            if not fall_back:
                raise cards.Unfit("message can't take embeds", 400, 50035)
            return await edit(channel_id, message_id, card.__class__(card.text, card.rows))
        return await edit(channel_id, message_id, card)

    monkeypatch.setattr(cards, "edit", refusing)
    async def changed():
        briefing.summary_changed("pills", seven.owner.id)

    run(changed())
    (fresh,) = posted(seven)
    assert fresh.id != old and fresh.card.heading.startswith("🗓️ **") and fresh.silent and old in seven.deleted
    assert run(database.run(livelists.db_get, seven.owner.id, briefing.IN_THE_HUB)).message_id == fresh.id
    assert not [card for message_id, card in seven.edited if message_id == old], "never left as plain words"


def test_round_five_is_untouched(on):  # noqa: F811
    add(on, {"name": "Morning dose", "times": ["8:00 am"]})
    run(briefing.post_in_hub(on.owner.id, HUB))
    assert on.sent[-1].card.embeds == () and on.sent[-1].card.layout, "the default draws as before"


def test_discord_draws_the_embeds_with_their_colours():
    from interfaces.discord import render

    card = Card("x", embeds=(Embed("8:00 am · 💊 Morning dose · 🟥 Due", status=design.DUE_NOW), Embed("☐ Buy stamps", "☑️ To-dos", design.TODOS)), heading="🗓️ **Wednesday 21 October**")
    drawn = render.drawn(card)
    assert drawn["content"] == "🗓️ **Wednesday 21 October**" and [each.colour.value for each in drawn["embeds"]] == [0xED4245, 0xEB459E]
    assert drawn["embeds"][1].title == "☑️ To-dos" and drawn["embeds"][0].description.endswith("🟥 Due")
    assert render.drawn(Card("x", embeds=card.embeds))["content"] is None, "message 2: no text"


# --- the calendar emoji and the calendar's own answers -----------------------------------------------------------------
def test_the_calendar_emoji_is_the_spiral_calendar_everywhere():
    from tasks.calendar import rules

    assert rules.ICON == "🗓️"
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=Path(__file__).parent.parent).stdout.decode().split("\0")
    old = "\U0001F4C5"  # written by its code point, so this file holds none either
    holding = [name for name in files if name and (Path(__file__).parent.parent / name).is_file() and old.encode() in (Path(__file__).parent.parent / name).read_bytes()]
    assert holding == [], f"the old calendar emoji is still in {holding}"


def test_calendar_lookups_hold_its_events_and_never_a_routine_or_a_dose(monkeypatch):
    from core import planning, weekview

    async def gathered(user_id, day):
        return [planning.Piece("calendar", "e1", "🗓️", "Team meeting", local(11), local(12)), planning.Piece("pills", "p1.1", "💊", "Morning dose", local(8), fold="dose"),
                planning.Piece("habits", "h1", "🔁", "Evening", local(22), fold="routine")]

    monkeypatch.setattr(planning, "gather", gathered)
    (found,) = run(weekview.gather(1, [TODAY], only="calendar"))
    assert [each.text for each in found.notable] == ["Team meeting"] and found.folded == ()
    (everything,) = run(weekview.gather(1, [TODAY]))
    assert {word for _, word, _ in everything.folded} == {"dose", "routine"}, "the week view itself keeps them"
