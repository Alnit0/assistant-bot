"""Round 8 of the hub (DESIGN_ROUND=8, Alex, 22 Oct): round 5's boxes, headings, rules and small text, with round 7's
coloured edges saying each box's state (tasks/briefing/hub8.py). One message, nothing in it twice: no separate pills
checklist, Today card or to-dos card beside it. State by text style alone, never a square. Made-up names."""
from datetime import date, time

import pytest

from core import actions, config, database, design, livelists
from core import day as days
from core.actions import DOSE, EVENT, MISSED, PREPARED, ROUTINE, SKIPPED, TAKEN, TODO, TRACKING, DayItem
from core.cards import Button
from core.design import Box, Row, Separator, Text
from tasks import briefing
from tasks.briefing import hub8
from tests.test_briefing import on  # noqa: F401
from tests.test_pills_reminders import HUB, add, at, log, run, world  # noqa: F401
from tests.test_round7 import _entry

TODAY = date(2026, 10, 22)  # a Thursday
SQUARES = ("🟩", "🟥", "⬜", "⏭️", "⬛", "☐", "☑")


def local(hour, minute=0, on=TODAY):
    return days.at(on, time(hour, minute))


def boxes(pieces):
    return [each for each in pieces if isinstance(each, Box)]


def box(pieces, title):
    return next(each for each in boxes(pieces) if design.texts(each.children)[0].startswith(f"### {title}"))


def lines(found):
    """A box's texts after its heading."""
    return design.texts(found.children)[1:]


def drawn(items, now):
    return hub8.layout(items, TODAY, now).first


DOSES = [
    DayItem(DOSE, "Pill A", local(8), state=TAKEN, done_at=local(8, 28), number=1, of=1),
    DayItem(DOSE, "Pill B", local(11), number=1, of=2, button=Button("Taken", "pills", "sheet_taken", "7", emoji="✅")),
    DayItem(DOSE, "Pill B", local(18), number=2, of=2),
]


# --- the page ------------------------------------------------------------------------------------------------------
def test_the_page_title_is_the_date_then_the_next_thing_and_nothing_else_outside_a_box():
    pieces = drawn([*DOSES, DayItem(EVENT, "Team meeting", local(14), local(15))], local(11, 30))
    assert design.texts(pieces[:1]) == ["## Thursday 22 October\n-# Next: Team meeting · 2:00 pm"]
    assert [design.texts(each.children)[0] for each in boxes(pieces)] == ["### 💊 Pills ●○○ 1/3", "### 🗓️ Today"]


def test_the_next_line_names_a_dose_by_its_time_never_a_countdown():
    pieces = drawn(DOSES, local(12))
    assert design.texts(pieces[:1])[0].endswith("-# Next: Pill B · 6:00 pm")
    assert "<t:" not in hub8.words(pieces), "exact times only, wherever a pill is (Alex, 16 Oct)"


def test_with_nothing_left_to_come_there_is_no_next_line():
    pieces = drawn([DayItem(DOSE, "Pill A", local(8), state=TAKEN, done_at=local(8, 5), of=1)], local(21))
    assert design.texts(pieces[:1]) == ["## Thursday 22 October"]


# --- the pills box -------------------------------------------------------------------------------------------------
def test_a_taken_dose_is_struck_through_with_when_it_was_taken_small_under_it():
    pills = box(drawn(DOSES, local(11, 30)), "💊 Pills")
    assert lines(pills)[0] == "~~Pill A · 8:00 am~~\n-# taken 8:28 am"


def test_the_dose_due_is_bold_with_its_one_button_and_later_ones_plain():
    pills = box(drawn(DOSES, local(11, 30)), "💊 Pills")
    assert lines(pills)[1:] == ["**Pill B · dose 1 of 2 · 11:00 am**", "Pill B · dose 2 of 2 · 6:00 pm"]
    (row,) = [each for each in pills.children if isinstance(each, Row)]
    assert [each.label for each in row.buttons] == ["Taken"], "the one Taken, on the dose that can be taken now"
    assert pills.children.index(row) == pills.children.index(Text("**Pill B · dose 1 of 2 · 11:00 am**")) + 1, "under its line"


def test_with_none_due_the_next_to_take_is_bold():
    pills = box(drawn([DayItem(DOSE, "Pill C", local(14), of=1), DayItem(DOSE, "Pill D", local(20), of=1)], local(9)), "💊 Pills")
    assert lines(pills) == ["**Pill C · 2:00 pm**", "Pill D · 8:00 pm"]


@pytest.mark.parametrize("state, said", [(SKIPPED, "skipped"), (MISSED, "missed")])
def test_a_skipped_or_missed_dose_is_struck_through_and_says_so_small(state, said):
    pills = box(drawn([DayItem(DOSE, "Pill E", local(9), state=state, of=1)], local(12)), "💊 Pills")
    assert lines(pills) == [f"~~Pill E · 9:00 am~~\n-# {said}"]


def test_doses_have_a_rule_between_them():
    pills = box(drawn(DOSES, local(11, 30)), "💊 Pills")
    kinds = [type(each) for each in pills.children]
    assert kinds == [Text, Separator, Text, Separator, Text, Row, Separator, Text]


@pytest.mark.parametrize("items, now, status", [
    (DOSES, local(11, 30), design.DUE_NOW),  # a dose due: red
    (DOSES, local(9), design.LATER),  # one taken, the rest later: grey
    ([DayItem(DOSE, "Pill A", local(8), state=TAKEN, done_at=local(8, 5)), DayItem(DOSE, "Pill F", local(9), state=TAKEN, done_at=local(9, 1))], local(15), design.TAKEN),
    ([DayItem(DOSE, "Pill A", local(8), state=TAKEN, done_at=local(8, 5)), DayItem(DOSE, "Pill F", local(9), state=MISSED)], local(15), design.LATER),
    ([DayItem(DOSE, "Pill A", local(8), state=TAKEN, done_at=local(8, 5)), DayItem(DOSE, "Pill F", local(9), state=SKIPPED)], local(15), design.TAKEN),
])
def test_the_pills_box_edge_is_its_most_urgent_state(items, now, status):
    assert box(drawn(items, now), "💊 Pills").status == status


def test_no_pills_box_on_a_day_with_no_doses():
    assert not [each for each in boxes(drawn([DayItem(EVENT, "Team meeting", local(14), local(15))], local(9))) if "Pills" in design.texts(each.children)[0]]


# --- the today box -------------------------------------------------------------------------------------------------
def test_the_today_box_holds_events_and_routines_and_never_a_dose():
    items = [*DOSES, DayItem(EVENT, "Work", local(8), local(16), repeats=True), DayItem(ROUTINE, "Evening", local(22, 30))]
    today = box(drawn(items, local(11, 30)), "🗓️ Today")
    assert lines(today) == ["**Work · on now · until 4:00 pm**", "**Evening · 10:30 pm**"]
    assert not any("Pill" in line for line in lines(today)), "doses live only in the Pills box"


def test_an_event_reads_from_until_and_the_next_one_to_come_is_bold():
    items = [DayItem(EVENT, "Team meeting", local(9), local(10)), DayItem(EVENT, "Workshop", local(13), local(14)), DayItem(EVENT, "Book club", local(19), local(21))]
    today = box(drawn(items, local(11)), "🗓️ Today")
    assert lines(today) == ["-# ~~Team meeting · 9:00 am until 10:00 am~~", "**Workshop · 1:00 pm until 2:00 pm**", "Book club · 7:00 pm until 9:00 pm"]


def test_a_routine_done_is_struck_and_faint():
    today = box(drawn([DayItem(ROUTINE, "Evening", local(22, 30), state=TAKEN)], local(22, 45)), "🗓️ Today")
    assert lines(today) == ["-# ~~Evening · 10:30 pm~~"]


def test_one_off_events_coming_up_are_one_small_line_last():
    items = [DayItem(ROUTINE, "Evening", local(22)), DayItem(EVENT, "Hen do", first_day=date(2026, 10, 24), last_day=date(2026, 10, 25)),
             DayItem(EVENT, "Dentist", local(15, on=date(2026, 10, 23)), local(16, on=date(2026, 10, 23)))]
    today = box(drawn(items, local(9)), "🗓️ Today")
    assert lines(today)[-1] == "-# Coming up: Dentist Fri 23 Oct, Hen do Sat 24 Oct"


@pytest.mark.parametrize("items, status", [
    ([DayItem(EVENT, "Work", local(8), local(16), repeats=True), DayItem(ROUTINE, "Evening", local(22))], design.ROUTINE),
    ([DayItem(EVENT, "Work", local(8), local(16), repeats=True), DayItem(EVENT, "Workshop", local(13), local(14))], design.NOTABLE),
    ([DayItem(EVENT, "Conference", first_day=TODAY, last_day=TODAY)], design.NOTABLE),
])
def test_the_today_box_is_yellow_with_a_one_off_event_today_and_blue_otherwise(items, status):
    assert box(drawn(items, local(9)), "🗓️ Today").status == status


def test_no_today_box_without_events_or_routines_today():
    assert [design.texts(each.children)[0] for each in boxes(drawn(DOSES, local(9)))] == ["### 💊 Pills ●○○ 1/3"]


# --- the to-dos box and the foot -----------------------------------------------------------------------------------
def test_the_to_dos_box_is_pink_with_the_first_three_open_and_the_rest_counted():
    items = [DayItem(TODO, f"To-do {number}") for number in range(1, 6)] + [DayItem(TODO, "Done one", state=TAKEN)]
    todos = box(drawn(items, local(9)), "To-dos")
    assert todos.status == design.TODOS and lines(todos) == ["To-do 1", "To-do 2", "To-do 3", "-# and 2 more"]


def test_the_foot_is_one_small_line_of_the_streak_and_the_news_linked_with_no_emoji():
    items = [DayItem(TRACKING, "Diary · Streak: 4 days", icon="📓", title="Diary", count=4),
             DayItem(PREPARED, "📰 8 stories in #news", icon="📰", title="Morning news", link="https://example.test/news", count=8)]
    pieces = drawn(items, local(9))
    assert design.texts(pieces[-1:]) == ["-# Diary streak 4 · [8 stories in #news](https://example.test/news)"]


# --- emoji, squares, limits ----------------------------------------------------------------------------------------
def _busy():
    return [
        *DOSES,
        DayItem(DOSE, "Pill C", local(13), state=SKIPPED, of=1), DayItem(DOSE, "Pill D", local(7), state=MISSED, of=1),
        DayItem(EVENT, "Work", local(8), local(16), repeats=True), DayItem(EVENT, "Workshop", local(13), local(14)),
        DayItem(ROUTINE, "Evening", local(22, 30), state=TAKEN), DayItem(EVENT, "Hen do", first_day=date(2026, 10, 24), last_day=date(2026, 10, 24)),
        *[DayItem(TODO, f"To-do {number}") for number in range(1, 5)],
        DayItem(TRACKING, "Diary · Streak: 4 days", icon="📓", title="Diary", count=4),
    ]


def test_no_status_square_or_status_emoji_anywhere_in_round_eight():
    said = hub8.words(drawn(_busy(), local(11, 30)))
    assert not [each for each in SQUARES if each in said]
    assert said.count("💊") == 1 and said.count("🗓️") == 1 and "📓" not in said and "📰" not in said and "🌙" not in said


def test_it_is_one_message_that_discord_takes():
    hub = hub8.layout(_busy(), TODAY, local(11, 30))
    assert hub.second is None and not design.problem(hub.first)


def test_too_big_for_one_message_the_to_dos_box_is_a_second_message_never_a_box_split():
    many = [DayItem(DOSE, f"Pill {number}", local(6 + number), of=1) for number in range(8)]
    events = [DayItem(EVENT, f"Event {number}", local(6 + number), local(7 + number)) for number in range(6)]
    items = [*many, *events, *[DayItem(TODO, f"To-do {number}") for number in range(5)]]
    hub = hub8.layout(items, TODAY, local(5))
    assert hub.second is not None and not design.problem(hub.first)
    assert [design.texts(each.children)[0] for each in boxes(hub.first)] == ["### 💊 Pills ○○○○○○○○ 0/8", "### 🗓️ Today"]
    (todos,) = hub.second
    assert todos.status == design.TODOS and lines(todos)[-1] == "-# and 2 more", "the whole To-dos box, as it would be in the first"


def test_discord_draws_each_box_with_its_coloured_edge():
    from interfaces.discord import render

    pieces = drawn(DOSES, local(11, 30))
    containers = [each for each in render.layout_view(pieces).children if hasattr(each, "accent_colour")]
    assert [each.accent_colour.value for each in containers] == [0xED4245]


# --- in the hub ----------------------------------------------------------------------------------------------------
@pytest.fixture
def eight(on, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "DESIGN_ROUND", 8)
    return on


def layouts(world):
    return [each for each in world.sent if each.card.layout]


def test_the_hub_is_one_message_with_real_doses_and_their_taken_button(eight):
    add(eight, {"name": "Pill A", "times": ["8:00 am"]}, {"name": "Pill B", "times": ["8:00 pm"]})
    at(eight, 9, 0)
    first = run(briefing.post_in_hub(eight.owner.id, HUB))
    (one,) = layouts(eight)
    assert one.id == first and one.silent
    pills = box(one.card.layout, "💊 Pills")
    assert lines(pills) == ["**Pill A · 8:00 am**", "Pill B · 8:00 pm"] and pills.status == design.DUE_NOW
    assert [each.action for each in design.buttons(one.card.layout)] == ["sheet_taken"]
    assert run(database.run(livelists.db_get, eight.owner.id, briefing.IN_THE_HUB_8)).message_id == first


def test_taken_redraws_the_one_message_in_place_struck_through(eight):
    briefing.task.setup(None)
    add(eight, {"name": "Pill A", "times": ["8:00 am"]}, {"name": "Pill B", "times": ["8:00 pm"]})
    at(eight, 8, 30)
    first = run(briefing.post_in_hub(eight.owner.id, HUB))
    log(eight, {"pill": "pill a", "did": "taken", "at": "8:28 am"})
    ones = [card for message_id, card in eight.edited if message_id == first]
    assert ones and lines(box(ones[-1].layout, "💊 Pills"))[0] == "~~Pill A · 8:00 am~~\n-# taken 8:28 am"
    assert len(layouts(eight)) == 1 and first not in eight.deleted, "edited in place, nothing posted again"


def test_nothing_shows_twice_no_checklist_today_card_or_to_dos_card_in_round_eight(eight):
    from core import hubcard
    from tasks.pills import checklist
    from tasks.today import card as today_card
    from tasks.todos import plain as todos_plain

    add(eight, {"name": "Pill A", "times": ["8:00 am"]})
    at(eight, 9, 0)
    posted, why, problem = run(checklist._post_if_due(eight.owner.id))
    assert not posted and not problem and "round 8" in why and not layouts(eight), "no checklist"
    assert run(today_card(eight.owner.id)) is None and run(todos_plain.hub_card(eight.owner.id)) is None
    assert run(hubcard.post("today", eight.owner.id, lambda: today_card(eight.owner.id))) is None and not layouts(eight)


def test_a_round_seven_hub_is_posted_fresh_in_round_eight_at_the_first_change(eight, monkeypatch):
    """Discord can't turn embeds into a layout: round 7's two messages go, and one of round 8's is posted."""
    briefing.task.setup(None)
    add(eight, {"name": "Pill A", "times": ["8:00 am"]})
    actions.set_catalogue([*actions.catalogue(), _entry("made_up_list", [DayItem(TODO, "To-do 1")])])
    monkeypatch.setattr(config, "DESIGN_ROUND", 7)
    old = run(briefing.post_in_hub(eight.owner.id, HUB))
    old_more = eight.sent[-1].id
    assert eight.sent[0].card.embeds and old_more != old, "round 7's two messages of embeds"
    monkeypatch.setattr(config, "DESIGN_ROUND", 8)

    async def changed():
        briefing.summary_changed("pills", eight.owner.id)

    run(changed())
    (fresh,) = layouts(eight)
    assert fresh.id not in (old, old_more) and {old, old_more} <= set(eight.deleted)
    assert not [card for message_id, card in eight.edited if message_id in (old, old_more)], "never edited across kinds"
    assert run(database.run(livelists.db_get, eight.owner.id, briefing.IN_THE_HUB_8)).message_id == fresh.id
    assert run(database.run(livelists.db_get, eight.owner.id, briefing.IN_THE_HUB)) is None
    assert run(database.run(livelists.db_get, eight.owner.id, briefing.IN_THE_HUB_MORE)) is None


def test_a_round_five_layout_is_posted_fresh_too(eight, monkeypatch):
    briefing.task.setup(None)
    add(eight, {"name": "Pill A", "times": ["8:00 am"]})
    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    old = run(briefing.post_in_hub(eight.owner.id, HUB))
    monkeypatch.setattr(config, "DESIGN_ROUND", 8)

    async def changed():
        briefing.summary_changed("pills", eight.owner.id)

    run(changed())
    assert eight.sent[-1].id != old and old in eight.deleted and box(eight.sent[-1].card.layout, "💊 Pills")


def test_brief_me_outside_the_hub_shows_the_same_message(eight):
    from core.actions import LiveReply, Request

    add(eight, {"name": "Pill A", "times": ["8:00 am"]})
    at(eight, 9, 0)
    shown = run(briefing.show(Request(eight.owner, 4242, "brief me"), {}, frozenset()))
    assert isinstance(shown, LiveReply) and box(shown.card.layout, "💊 Pills") and shown.card.layout[0].content.startswith("## ")


def test_rounds_five_six_and_seven_stay_selectable_and_eight_is_built():
    assert 8 in design.ROUNDS and design.LATEST == 5 and design.EMBEDS_ROUND == 7 and 6 in design.PREVIEW_ROUNDS


def test_round_seven_still_writes_a_dose_s_number_in_its_line():
    from tasks.briefing import embeds

    card = embeds.your_day([DayItem(DOSE, "Pill B", local(18), number=2, of=2)], TODAY, local(9))
    assert card.embeds[0].description == "6:00 pm · 💊 Pill B (dose 2 of 2) · ⬜ Later"


# --- the day in the hub (selftest/day.py) --------------------------------------------------------------------------
def test_the_day_run_flags_a_card_twice_or_a_square_in_round_eight_and_nothing_in_other_rounds():
    from selftest import day as replay
    from tests.test_day_in_the_hub import _message

    clean = {"day": "2026-10-16", "messages": [_message("briefing:hub8", text="## Thursday\n~~Pill A · 8:00 am~~"), _message("habits.r1:hub")]}
    assert replay.rule_problems(clean) == []
    doubled = {"day": "2026-10-16", "messages": [_message("briefing:hub8", text="🟩 Taken"), _message(kind="checklist"), _message("todos:hub")]}
    assert replay.rule_problems(doubled) == ["shown twice in round 8: the pills checklist", "shown twice in round 8: todos:hub", "a status square in round 8's hub: 🟩"]
    seven = {"day": "2026-10-16", "messages": [_message("briefing:hub", text="🟩 Taken"), _message(kind="checklist")]}
    assert replay.rule_problems(seven) == []
