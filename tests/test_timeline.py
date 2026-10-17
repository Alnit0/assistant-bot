"""Round 6, the timeline hub (core/timeline.py), a preview behind DESIGN_ROUND=6: the header with the day's dots,
weather and what's next and the done line; a card an item in time order, its button only when it can be acted on
now; a dose that moved, old struck and new bold with why; a long event on now with its end and time left, free
time never inside it; free gaps of 90 minutes or more with how many to-dos fit; to-dos with no time last. Pure."""
from datetime import date, time

from core import config, design, timeline
from core import day as days
from core.timeline import Header, Item

DAY = date(2026, 10, 19)


def at(hour, minute=0):
    return days.at(DAY, time(hour, minute))


def words(pieces) -> str:
    return "\n".join(design.texts(pieces))


def test_round_6_is_a_preview_round_and_live_stays_on_5(monkeypatch):
    monkeypatch.setattr(config, "DESIGN_ROUND", 6)
    assert design.current() == 6 and 6 not in design.ROUNDS and design.LATEST == 5


def test_a_moved_dose_shows_old_struck_new_bold_with_why_and_only_the_due_one_has_taken():
    later = Item(timeline.DOSE, "💊", "Pill A (dose 2 of 3)", at(12, 15), planned=at(11), why="dose 1 was taken at 9:15 am", later=True)
    shown = words(timeline.card(later, at(10)))
    assert "~~11:00 am~~ → **12:15 pm**" in shown and "dose 1 was taken at 9:15 am" in shown and "planned" in shown
    assert not design.buttons(timeline.card(later, at(10))), "a later dose has no button"
    due = Item(timeline.DOSE, "💊", "Pill B", at(7), button="Taken")
    assert [button.label for button in design.buttons(timeline.card(due, at(7, 2)))] == ["Taken"]


def test_a_long_event_is_on_now_with_its_end_and_free_time_is_never_inside_it():
    work = Item(timeline.EVENT, "💼", "Work", at(8), at(17))
    shown = words(timeline.card(work, at(13)))
    assert "on now · until **5:00 pm** · 4h left" in shown
    found = timeline.gaps([work], at(7), at(22), todos=6)
    assert [(gap.at, gap.until) for gap in found] == [(at(17), at(22))], "7 to 8 is too short; nothing inside work"
    assert found[0].details == ("until 10:00 pm · 5h · room for 6 to-dos",)


def test_done_things_leave_their_cards_for_the_done_line_and_to_dos_with_no_time_come_last():
    items = [
        Item(timeline.DOSE, "💊", "Pill B", at(7), done=True, done_at=at(7, 5)),
        Item(timeline.EVENT, "📅", "Standup", at(9), at(9, 15)),
        Item(timeline.REMINDER, "⏰", "Call the bank", at(10, 30), button="Done"),
    ]
    messages = timeline.hub(Header(DAY, 1, 2, "14° to 20° · drizzle"), items, at(10, 0), at(22), ["**Buy stamps**"])
    head = words(messages[0])
    assert "●○ 1/2" in head and "14° to 20° · drizzle · next: ⏰ Call the bank 10:30 am" in head
    assert "✅ Standup 9:15 am · Pill B 7:05 am" in head or "✅ Pill B 7:05 am · Standup 9:15 am" in head
    assert "Needs a look" not in head, "only for a real problem"
    bodies = [words(each) for each in messages[1:]]
    assert bodies[0].startswith("### ⏰ Call the bank · 10:30 am")
    assert bodies[-1].startswith("### 📝 To-dos · 1"), "to-dos with no time last"
    assert any(body.startswith("### 🌿 Free · 10:45 am") or "Free" in body for body in bodies)
    with_problem = timeline.hub(Header(DAY, 1, 2, problems=("backup failed",)), items, at(10), at(22))
    assert "⚠️ Needs a look" in words(with_problem[0])


def test_the_one_moving_pills_card_variant():
    doses = [
        Item(timeline.DOSE, "💊", "Pill B", at(7), done=True, done_at=at(7, 5)),
        Item(timeline.DOSE, "💊", "Pill A (dose 2 of 3)", at(12, 15), planned=at(11), why="dose 1 was taken at 9:15 am"),
        Item(timeline.DOSE, "💊", "Pill C", at(21)),
    ]
    shown = words(timeline.one_pills_card(doses, at(12, 20)))
    assert "### 💊 Pills · 12:15 pm · 1 of 3 taken" in shown and "~~11:00 am~~ → **12:15 pm**" in shown and "then Pill C 9:00 pm" in shown
    assert [button.label for button in design.buttons(timeline.one_pills_card(doses, at(12, 20)))] == ["Taken"]


def test_every_moment_of_the_preview_day_fits_its_messages():
    from selftest import tonight

    for hour in (7, 12, 20):
        for busy in (False, True):
            for pieces in tonight.round_6_moment(hour, busy):
                assert not design.problem(pieces), (hour, busy)
    assert len(tonight.plan_cards()) == 16
