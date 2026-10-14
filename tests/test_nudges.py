"""Reminders I set myself (tasks/nudges), behind NUDGES_ENABLED: setting them in words, the repeat rules, going off once and only once, retry, quiet hours, snooze, a restart, the card and attention."""
import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from core import attention, cards, clock, config, database, design, hub, live, scheduler, surface
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.nudges import plain, rules, store
from tasks.nudges import task as nudges_task
from tasks.nudges.rules import Nudge

HUB, INBOX = 555, 100


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"nudges": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=7000, refuse=0)

    async def send(channel_id, card, silent=False):
        cards.check(card)
        if seen.refuse:
            seen.refuse -= 1
            raise surface.Failed("503 Service Unavailable")
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        cards.check(card)
        seen.edited.append((message_id, card))
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_standing", {})
    monkeypatch.setattr(plain, "changed", lambda user_id: None)
    for kind, handler in nudges_task.job_handlers().items():
        scheduler.register_handler(rules.TASK, kind, handler)
    plain.register()
    live.reset()
    # A Wednesday, 9 am
    wednesday = days.today() + timedelta(days=(2 - days.today().weekday()) % 7 or 7)
    seen.day = wednesday
    clock.advance_to(days.at(wednesday, time(9, 0)))
    seen.request = lambda text="said", previous=None: Request(owner, INBOX, text, previous=previous)
    return seen


def at(world, hour, minute=0, day_offset=0):
    clock.advance_to(days.at(world.day + timedelta(days=day_offset), time(hour, minute)))
    return run(scheduler.run_all_due())


def add(world, said="said", **data):
    proposal = run(plain.add_card(world.request(said), data, frozenset()))
    assert proposal.question is None, proposal
    run(plain.add_save(world.request(said), proposal.data))
    assert run(plain.add_check(world.request(said), proposal.data)) == ""
    return proposal


def booked():
    return sorted(job.payload["local"] for job in run(scheduler.pending_jobs(rules.TASK, plain.FIRE)))


class Press:
    def __init__(self, world, message_id, arg):
        self.user, self.arg, self.message_id, self.channel_id, self.world = world.owner, arg, message_id, HUB, world
        self.shown, self.removed = [], False
        self.db = cards.Press.db

    async def update(self, card):
        self.shown.append(card)

    async def remove(self):
        self.removed = True


def press(world, action, arg):
    pressed = Press(world, world.sent[-1].id, arg)
    return pressed, run(cards._actions[(rules.TASK, action)].handler(pressed))


def fired(world):
    return run(database.run(store.db_open, world.owner.id))


# --- the repeat rules (pure) ------------------------------------------------------------------------------------------
def nudge(repeat, **more):
    return Nudge(1, 1, "Bins", time(9, 0), repeat, **more)


def test_each_repeat_is_due_on_its_days():
    monday = date(2026, 10, 19)
    week = [monday + timedelta(days=n) for n in range(7)]
    assert [rules.on_day(nudge(rules.DAILY), each) for each in week] == [True] * 7
    assert [rules.on_day(nudge(rules.WEEKDAYS), each) for each in week] == [True] * 5 + [False] * 2
    assert [rules.on_day(nudge(rules.DAYS, weekdays=(0, 3)), each) for each in week] == [True, False, False, True, False, False, False]
    assert [rules.on_day(nudge(rules.EVERY, first=monday, every_days=3), each) for each in week] == [True, False, False, True, False, False, True]
    assert [rules.on_day(nudge(rules.ONCE, first=monday + timedelta(days=2)), each) for each in week] == [False, False, True, False, False, False, False]
    assert rules.repeat_text(nudge(rules.DAYS, weekdays=(0, 3)), monday) == "every Mon and Thu"
    assert rules.repeat_text(nudge(rules.EVERY, every_days=3), monday) == "every 3 days"


def test_a_one_off_gone_by_has_no_next_time():
    once = nudge(rules.ONCE, first=date(2026, 10, 19))
    assert rules.next_due(once, days.at(date(2026, 10, 19), time(8, 0))) == days.at(date(2026, 10, 19), time(9, 0))
    assert rules.next_due(once, days.at(date(2026, 10, 19), time(9, 30))) is None


def test_daylight_saving_never_moves_a_reminder():
    daily = nudge(rules.DAILY)
    # NZ daylight saving ends on Sunday 4 April 2027 and begins on Sunday 26 September 2027
    for change in (date(2027, 4, 4), date(2027, 9, 26)):
        before = days.at(change - timedelta(days=1), time(10, 0))
        due = rules.next_due(daily, before)
        assert days.day_of(due) == change and days.local_time(due) == time(9, 0)
        after = rules.next_due(daily, due)
        assert days.local_time(after) == time(9, 0), "the day after the change, still 9:00 am"


# --- setting one --------------------------------------------------------------------------------------------------------
def test_off_unless_set_and_not_in_help(monkeypatch):
    assert config.NUDGES_ENABLED is False and not nudges_task.switched_on()
    registry.load()
    assert "nudges" not in [task.name for task in registry.loaded_tasks()]


def test_a_reminder_at_a_time_is_a_card_and_save_books_it(world):
    proposal = add(world, "remind me at 5pm to call Mum", text="call Mum", time="5:00 pm")
    assert proposal.lines[0] == "**Call Mum** · today at **5:00 pm**" and proposal.lines[1].startswith("-# next: today at 5:00 pm")
    assert booked() == [f"{world.day.isoformat()}T17:00"]


def test_a_time_gone_by_today_with_no_day_is_tomorrow_marked_as_a_guess(world):
    proposal = run(plain.add_card(world.request(), {"text": "stretch", "time": "8:00 am"}, frozenset()))
    assert proposal.lines[0] == "**Stretch** · tomorrow at **8:00 am** ❓" and "day" in proposal.guessed


def test_a_time_with_no_am_or_pm_is_asked_on_the_card(world):
    proposal = run(plain.add_card(world.request("remind me at 6 to call Mum"), {"text": "call Mum", "time": "6:00"}, frozenset()))
    assert proposal.question.text == "Is that 6:00 in the morning or the evening?"
    assert [choice.label for choice in proposal.question.choices] == ["6:00 am", "6:00 pm"]
    answered = run(plain.add_card(world.request(), proposal.question.choices[1].data, frozenset()))
    assert answered.question is None and answered.lines[0] == "**Call Mum** · today at **6:00 pm**"


def test_in_twenty_minutes_is_worked_out_by_the_code(world):
    proposal = add(world, text="check the oven", in_minutes=20)
    assert proposal.lines[0] == "**Check the oven** · today at **9:20 am**"


def test_every_monday_is_a_repeating_reminder(world):
    proposal = add(world, text="put the bins out", time="9:00 am", repeat="days", weekdays=["mon"])
    assert proposal.lines[0] == "**Put the bins out** · every Mon at **9:00 am**"
    assert len(booked()) == 1 and date.fromisoformat(booked()[0][:10]).weekday() == 0


# --- going off -----------------------------------------------------------------------------------------------------------
def test_at_its_time_it_goes_off_in_the_hub_as_a_neutral_line_then_drawn_with_done_and_snooze(world):
    add(world, text="call Mum", time="5:00 pm", repeat="daily")
    at(world, 17, 0)
    first = world.sent[-1]
    assert first.card.text == "⏰ Reminder · 5:00 pm" and first.channel == HUB, "what a phone shows names nothing"
    message_id, drawn = world.edited[-1]
    assert message_id == first.id and [button.label for button in design.buttons(drawn.layout)] == ["Done", "Snooze"]
    assert [button.style for button in design.buttons(drawn.layout)] == [cards.SUCCESS, cards.PRIMARY]
    assert drawn.layout[1].children[0].content.startswith("### ⏰ Call Mum\ndue **5:00 pm**")
    assert booked() == [f"{(world.day + timedelta(days=1)).isoformat()}T17:00"], "the next one is booked as this one goes off"


def test_an_occurrence_is_never_posted_twice(world):
    add(world, text="call Mum", time="5:00 pm")
    at(world, 17, 0)
    occurrence = SimpleNamespace(payload={"id": 1, "local": f"{world.day.isoformat()}T17:00"}, due_at=days.at(world.day, time(17, 0)), is_late=False)
    notes = []
    original = scheduler.note
    scheduler.note = lambda job, said: notes.append(said)
    try:
        run(plain.fire_job(occurrence))
    finally:
        scheduler.note = original
    assert len(world.sent) == 1 and notes == ["not posted: it went off already"]


def test_one_that_cannot_be_posted_is_tried_again_after_a_minute_and_posted_once(world):
    add(world, text="call Mum", time="5:00 pm")
    world.refuse = 1
    at(world, 17, 0)
    assert world.sent == [] and fired(world) == []
    at(world, 17, 2)
    assert len(world.sent) == 1 and len(fired(world)) == 1


def test_it_gets_through_quiet_hours_with_a_sound_and_never_to_ntfy(world, monkeypatch):
    from core import notify

    monkeypatch.setattr(config, "QUIET_HOURS_ENABLED", True)
    monkeypatch.setattr(config, "QUIET_HOURS", (time(22, 0), time(7, 0)))
    add(world, text="take the bread out", time="11:00 pm")
    at(world, 23, 0)
    assert world.sent[-1].silent is False
    assert notify.kind(plain.KIND).through and notify.kind(plain.KIND).where == notify.DISCORD


def test_missed_while_the_bot_was_off_it_goes_off_once_when_it_is_back_marked_late(world, monkeypatch):
    add(world, text="call Mum", time="5:00 pm", repeat="daily")
    # Off from before 5 pm until 8 pm: real time went by (the dev clock's own jumps are never counted as late)
    monkeypatch.setattr(clock, "skipped_between", lambda since, until: 0.0)
    at(world, 20, 0)
    assert [each.card.text for each in world.sent] == ["⏰ Reminder · 5:00 pm · late"]
    assert "was due **5:00 pm**" in world.edited[-1][1].layout[1].children[0].content
    assert booked() == [f"{(world.day + timedelta(days=1)).isoformat()}T17:00"]


# --- done and snooze ------------------------------------------------------------------------------------------------------
def test_done_leaves_the_hub_and_nothing_is_due_any_more(world):
    add(world, text="call Mum", time="5:00 pm")
    at(world, 17, 0)
    (open_,) = fired(world)
    pressed, said = press(world, rules.DONE, str(open_.id))
    assert said == "✅ Call Mum · done" and pressed.removed and fired(world) == []
    assert run(plain.on_done(Press(world, 0, str(open_.id)))) == "already dealt with", "a second press does nothing"


def test_snooze_offers_ten_minutes_an_hour_and_tomorrow_and_goes_off_again(world):
    add(world, text="call Mum", time="5:00 pm")
    at(world, 17, 0)
    (open_,) = fired(world)
    pressed, _ = press(world, rules.SNOOZE, str(open_.id))
    labels = [button.label for button in design.buttons(pressed.shown[-1].layout)]
    assert labels == ["10 minutes", "1 hour", "Tomorrow", "Cancel"]
    assert [button.style for button in design.buttons(pressed.shown[-1].layout)][-1] == cards.SECONDARY
    pressed, said = press(world, rules.SNOOZE_FOR, f"{open_.id}:10")
    assert pressed.removed and said == "💤 Call Mum · again at 5:10 pm" and fired(world) == []
    at(world, 17, 11)
    assert [each.card.text for each in world.sent] == ["⏰ Reminder · 5:00 pm", "⏰ Reminder · 5:10 pm"] and len(fired(world)) == 1


def test_tomorrow_is_tomorrow_at_the_time_it_was_due():
    due = days.at(date(2026, 10, 21), time(17, 0))
    assert plain.snoozed_until(24 * 60, due, days.at(date(2026, 10, 21), time(17, 40))) == days.at(date(2026, 10, 22), time(17, 0))


# --- change and remove --------------------------------------------------------------------------------------------------
def test_move_that_to_6_asks_am_or_pm_then_shows_old_struck_new_bold(world):
    add(world, text="call Mum", time="5:00 pm")
    asked = run(plain.change_card(world.request("move that to 6"), {"reminder": "@that", "time": "6:00"}, frozenset()))
    assert asked.question is not None and [choice.label for choice in asked.question.choices] == ["6:00 am", "6:00 pm"]
    proposal = run(plain.change_card(world.request(), asked.question.choices[1].data, frozenset()))
    assert proposal.lines[1] == "time · 5:00 pm → 6:00 pm" and design.changed(proposal.lines[1]) == "time · ~~5:00 pm~~ → **6:00 pm**"
    run(plain.change_save(world.request(), proposal.data))
    assert run(plain.change_check(world.request(), proposal.data)) == "" and booked() == [f"{world.day.isoformat()}T18:00"]


def test_removing_is_a_red_card_and_nothing_stays_booked(world):
    add(world, text="call Mum", time="5:00 pm")
    proposal = run(plain.remove_card(world.request(), {"reminder": "mum"}, frozenset()))
    assert proposal.confirm_label == "Remove" and proposal.lines[0] == "**Call Mum** → removed"
    run(plain.remove_save(world.request(), proposal.data))
    assert run(plain.remove_check(world.request(), proposal.data)) == "" and booked() == []


# --- the card, the briefing and attention --------------------------------------------------------------------------------
def test_the_card_shows_what_is_still_to_come_today_and_is_gone_when_nothing_is(world):
    assert run(plain.hub_card(world.owner.id)) is None
    add(world, text="call Mum", time="5:00 pm")
    add(world, text="stretch", time="11:00 am")
    shown = run(plain.hub_card(world.owner.id))
    (box,) = shown.layout
    assert box.children[0].content == "### ⏰ Reminders" and box.children[2].content.startswith("**Stretch**\n**11:00 am** · <t:")
    assert design.buttons(shown.layout) == [], "nothing on it can be done now"
    clock.advance_to(days.at(world.day, time(18, 0)))
    assert run(plain.hub_card(world.owner.id)) is None


def test_the_briefing_lists_the_day_s_reminders_in_time_order(world):
    from tasks import nudges

    add(world, text="call Mum", time="5:00 pm")
    add(world, text="stretch", time="11:00 am")
    said = run(nudges.summary(world.owner.id, world.day))
    assert said.lines == ("**11:00 am** · Stretch", "**5:00 pm** · Call Mum") and said.total is None


def test_one_that_went_off_is_due_now_and_the_next_is_next(world):
    from tasks import nudges

    add(world, text="call Mum", time="5:00 pm")
    add(world, text="stretch", time="6:00 pm")
    now = clock.now()
    (coming,) = run(nudges.items(world.owner.id, now))
    assert attention.level(coming, now) == attention.LEVEL_NEXT and coming.short == ("5pm",)
    at(world, 17, 0)
    now = clock.now()
    found = run(nudges.items(world.owner.id, now))
    assert attention.level(found[0], now) == attention.LEVEL_DUE and found[0].short == ("due 5pm",)
    assert "Mum" not in attention.status_line(found[0])


def test_a_time_claude_read_as_the_evening_is_shown_as_a_guess(world):
    add(world, text="call Mum", time="5:00 pm")
    proposal = run(plain.change_card(world.request("move that to 6"), {"reminder": "@that", "time": "6:00 pm"}, frozenset({"time"})))
    assert proposal.question is None and proposal.lines[1] == "time · 5:00 pm → 6:00 pm ❓"
    assert design.changed(proposal.lines[1]) == "time · ~~5:00 pm~~ → **6:00 pm** ❓"
