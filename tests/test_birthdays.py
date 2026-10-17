"""Birthdays, part of reminders (tasks/nudges/birthdays.py), behind BIRTHDAYS_ENABLED: read as said (a year only
when said, 29 February), a card first with the Bot calendar's yearly all-day event, the age turning, gift notes;
a quiet line 14 days before, a post 3 days before with the gift notes and one on the day, each once and neutral
on the lock screen; timing changed in words; changed and removed with the calendar kept in step; when, and what is
coming up; and no name or gift note in a log. Made-up names only."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, conversation, database, hub, live, notify, scheduler
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks.nudges import birthdays, store
from tasks.nudges import task as nudges_task
from tasks.nudges.birthdays import Birthday

HUB = 400


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


class FakeBot:
    """The Bot calendar, made up: each series as the API keeps it."""

    can_write = True

    def __init__(self):
        self.series, self.next = {}, 0

    async def insert(self, body):
        self.next += 1
        self.series[f"s{self.next}"] = dict(body)
        return {"id": f"s{self.next}", **body}

    async def patch(self, ref, body):
        self.series[ref].update(body)
        return self.series[ref]

    async def raw(self, ref):
        return self.series.get(ref)

    async def delete(self, ref):
        del self.series[ref]


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"nudges": store.MIGRATIONS})
    monkeypatch.setattr(config, "BIRTHDAYS_ENABLED", True)
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=8000, jobs=[], pushed=[], bot=FakeBot())

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        cards.check(card)
        seen.edited.append((message_id, card))
        return True

    async def add_job(task, kind, due, payload, user_id=None, key=""):
        seen.jobs.append((kind, due, payload, key))

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(scheduler, "add_job", add_job)
    seen.notes = []
    monkeypatch.setattr(scheduler, "note", lambda job, line: seen.notes.append(line))
    monkeypatch.setattr(birthdays, "changed", lambda user_id: None)
    monkeypatch.setattr(birthdays, "writer", lambda: seen.bot)
    monkeypatch.setattr(birthdays, "_calendar_refresh", lambda user_id: asyncio.sleep(0))
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    birthdays.register()
    live.reset()
    seen.today = date(2027, 3, 1) if days.today() < date(2027, 3, 1) else days.today() + timedelta(days=1)
    clock.advance_to(days.at(seen.today, time(10, 0)))
    seen.request = lambda text="said": Request(owner, HUB, text)
    return seen


def add(world, person, said_date, text="said"):
    proposal = run(birthdays.add_card(world.request(text), {"person": person, "date": said_date}, frozenset()))
    run(birthdays.add_save(world.request(text), proposal.data))
    assert run(birthdays.add_check(world.request(text), proposal.data)) == ""
    return proposal


def kept(world, name):
    return next(each for each in run(birthdays.every(world.owner.id)) if each.name == name)


def made_up(world, name, left, year=None, before=birthdays.BEFORE):
    day = world.today + timedelta(days=left)
    run(database.run(birthdays.db_add, Birthday(0, world.owner.id, name, day.month, day.day, year, before), clock.now()))
    return kept(world, name)


# --- reading and the dates: 29 February -------------------------------------------------------------------------------
def test_a_birthday_is_read_as_said_with_a_year_only_when_one_was_said():
    assert birthdays.read("12 March") == (3, 12, None)
    assert birthdays.read("3 June 1995") == (6, 3, 1995)
    assert birthdays.read("29 Feb") == (2, 29, None) and birthdays.read("March 12") == (3, 12, None)
    for wrong in ("tomorrow", "Friday", "sometime"):
        with pytest.raises(UserError):
            birthdays.read(wrong)


def test_29_february_is_the_28th_in_a_year_without_one_and_the_age_counts_on():
    leap = Birthday(1, 1, "Made-up Leap", 2, 29, 2000)
    assert birthdays.on(leap, 2027) == date(2027, 2, 28) and birthdays.on(leap, 2028) == date(2028, 2, 29)
    assert birthdays.next_on(leap, date(2027, 3, 1)) == date(2028, 2, 29)
    assert birthdays.next_on(leap, date(2026, 10, 18)) == date(2027, 2, 28)
    assert birthdays.turning(leap, date(2026, 10, 18)) == 27
    assert birthdays.rule(leap) == "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1", "the last day of February every year on the calendar"
    assert birthdays.rule(Birthday(2, 1, "Mum", 3, 12)) == "RRULE:FREQ=YEARLY"


def test_the_stages_a_quiet_line_from_14_days_then_3_days_and_the_day():
    mum = Birthday(1, 1, "Mum", 3, 20)
    on = lambda left: date(2027, 3, 20) - timedelta(days=left)
    assert [birthdays.is_quiet(mum, on(left)) for left in (15, 14, 4, 3)] == [False, True, True, False]
    assert [birthdays.stage(mum, on(left)) for left in (5, 4, 3, 2, 1, 0)] == [None, None, 3, 3, 3, 0]
    assert birthdays.neutral(3) == "🎂 Birthday in 3 days" and birthdays.neutral(0) == "🎂 Birthday today"


# --- a card first, with the Bot calendar ----------------------------------------------------------------------------------
def test_a_new_birthday_is_a_card_then_a_yearly_all_day_event_on_the_bot_calendar(world):
    proposal = add(world, "Mum", "12 March", "Mum's birthday 12 March")
    assert proposal.kind == "new" and proposal.lines[0].startswith("**Mum** · ")
    assert proposal.lines[1] == "Told: a line 14 days before; posted 3 days before and on the day"
    assert proposal.lines[2] == "-# 🎂 and a yearly all-day event on the Bot calendar", "the card says so"
    ((ref, body),) = world.bot.series.items()
    assert body["summary"] == "🎂 Mum's birthday" and body["recurrence"] == ["RRULE:FREQ=YEARLY"]
    first = date.fromisoformat(body["start"]["date"])
    assert (first.month, first.day) == (3, 12) and body["end"]["date"] == (first + timedelta(days=1)).isoformat()
    assert kept(world, "Mum").calendar_ref == ref


def test_with_a_year_the_age_they_are_turning_is_shown(world):
    proposal = add(world, "Sam", "3 June 1995")
    turning = date(world.today.year if date(world.today.year, 6, 3) >= world.today else world.today.year + 1, 6, 3).year - 1995
    assert proposal.lines[0].endswith(f"· turns {turning}")


def test_without_the_calendar_it_is_in_reminders_only(world, monkeypatch):
    monkeypatch.setattr(birthdays, "writer", lambda: None)
    proposal = add(world, "Mum", "12 March")
    assert proposal.lines[2] == "-# in your reminders" and kept(world, "Mum").calendar_ref is None


def test_the_same_birthday_again_says_so_and_a_new_day_is_a_change(world):
    add(world, "Mum", "12 March")
    with pytest.raises(UserError, match="is there already"):
        run(birthdays.add_card(world.request(), {"person": "mum", "date": "12 March"}, frozenset()))
    change = run(birthdays.add_card(world.request(), {"person": "Mum", "date": "13 March"}, frozenset()))
    assert change.kind == "change" and change.lines[1] == "~~12 March~~ → **13 March**"
    run(birthdays.add_save(world.request(), change.data))
    assert (kept(world, "Mum").month, kept(world, "Mum").day) == (3, 13)
    (body,) = world.bot.series.values()
    assert body["start"]["date"].endswith("-03-13"), "the calendar is kept in step"


def test_timing_changed_in_words_and_removing_takes_the_event_off(world):
    add(world, "Mum", "12 March")
    change = run(birthdays.change_card(world.request(), {"person": "Mum", "before": [5]}, frozenset()))
    assert change.lines[1] == "~~a line 14 days before; posted 3 days before and on the day~~ → **a line 14 days before; posted 5 days before and on the day**"
    run(birthdays.change_save(world.request(), change.data))
    assert kept(world, "Mum").before == (5, 0) and run(birthdays.change_check(world.request(), change.data)) == ""
    remove = run(birthdays.remove_card(world.request(), {"person": "Mum"}, frozenset()))
    assert remove.kind == "remove" and "its Bot calendar event goes too" in remove.lines[1]
    run(birthdays.remove_save(world.request(), remove.data))
    assert run(birthdays.every(world.owner.id)) == [] and world.bot.series == {}
    assert run(birthdays.remove_check(world.request(), remove.data)) == ""


# --- gift notes, when, and what is coming up ------------------------------------------------------------------------------
def test_gift_notes_are_a_card_and_shown_with_when(world):
    add(world, "Mum", "12 March")
    proposal = run(birthdays.gift_card(world.request(), {"person": "Mum", "note": "a scarf"}, frozenset()))
    assert proposal.lines == ("**Mum** · 🎁 a scarf",)
    run(birthdays.gift_save(world.request(), proposal.data))
    assert run(birthdays.gift_check(world.request(), proposal.data)) == ""
    said = run(birthdays.when_said(world.request(), {"person": "mum"}, frozenset()))
    assert said.startswith("🎂 **Mum** · ") and said.endswith("-# 🎁 a scarf")
    with pytest.raises(UserError, match="no birthday for “Sam”"):
        run(birthdays.gift_card(world.request(), {"person": "Sam", "note": "a book"}, frozenset()))


def test_upcoming_birthdays_are_the_next_90_days_soonest_first(world):
    made_up(world, "Made-up Far", 120)
    made_up(world, "Made-up Soon", 10)
    made_up(world, "Made-up Sooner", 2)
    run(birthdays.soon_said(world.request(), {}, frozenset()))
    text = world.sent[-1].card.text
    assert text.startswith("## 🎂 Birthdays coming up · 2") and text.index("Made-up Sooner") < text.index("Made-up Soon**") and "Far" not in text


# --- the briefing's quiet line and the posts -------------------------------------------------------------------------------
def test_from_14_days_a_quiet_line_in_the_briefing_overview(world, monkeypatch):
    from tasks.nudges import summary

    made_up(world, "Made-up Friend", 10)
    made_up(world, "Made-up Later", 20)
    found = run(summary(world.owner.id, world.today))
    assert found.overview == "🎂 Made-up Friend in 10 days"


def test_3_days_before_a_post_with_the_gift_notes_neutral_on_the_lock_screen_and_once(world):
    friend = made_up(world, "Made-up Friend", 3, year=1990)
    run(database.run(birthdays.db_add_gift, world.owner.id, friend.id, "a climbing book", clock.now()))
    job = SimpleNamespace(payload={}, note=None)
    run(birthdays.check_job(job))
    first = world.sent[-1].card
    assert first.text == "🎂 Birthday in 3 days", "what a phone shows names nobody"
    _, drawn = world.edited[-1]
    assert "Made-up Friend's birthday" in drawn.text and "🎁 a climbing book" in drawn.text and "turns " in drawn.text
    assert [button.label for button in drawn.rows[0]] == ["Done", "Snooze"]
    run(birthdays.check_job(job))
    assert len(world.sent) == 1, "once a birthday and stage"
    assert world.notes == ["1 birthday post", "no birthday post today"] or world.notes[0] == "1 birthday post"
    assert "Friend" not in repr(world.notes), "a job's note names nobody"


def test_on_the_day_a_post_and_one_missed_while_off_is_posted_late_once(world):
    made_up(world, "Made-up Today", 0)
    made_up(world, "Made-up Missed", 2)  # its 3-day post was missed: posted now, once
    run(birthdays.check_job(SimpleNamespace(payload={}, note=None)))
    assert sorted(each.card.text for each in world.sent) == ["🎂 Birthday in 2 days", "🎂 Birthday today"]
    today_post = next(card for _, card in world.edited if "Made-up Today" in card.text)
    assert "🎁" not in today_post.text


def test_done_takes_the_post_away_and_snooze_books_it_again(world):
    friend = made_up(world, "Made-up Friend", 3)
    run(birthdays.check_job(SimpleNamespace(payload={}, note=None)))
    (row,) = world.edited[-1][1].rows
    removed = []
    press = SimpleNamespace(arg=row[0].arg, db=database, remove=lambda: asyncio.sleep(0, removed.append(True)), user=world.owner)
    assert run(birthdays.on_done(press)) == "birthday post done" and removed
    snoozed = SimpleNamespace(arg=f"{row[1].arg}:60", db=database, remove=lambda: asyncio.sleep(0), user=world.owner)
    said = run(birthdays.on_snooze_for(snoozed))
    assert said.startswith("💤 again at") and world.jobs[-1][0] == birthdays.AGAIN_JOB and world.jobs[-1][2]["id"] == friend.id
    assert "Friend" not in said, "a press's log names nobody"


# --- private: the router's own entry, nothing in a log ---------------------------------------------------------------------
def test_birthdays_are_a_private_entry_of_reminders_only_when_switched_on(world, monkeypatch):
    entries = nudges_task.entries()
    names = [each.name for each in entries]
    assert names == ["nudges", "birthdays"]
    entry = entries[1]
    assert entry.private and entry.icon == "🎂" and entry.plan is not None and not actions.problems(entries)
    assert "Not birthdays" in entries[0].only_for
    assert all(action.say for action in entry.actions), "every way in is in #commands"
    monkeypatch.setattr(config, "BIRTHDAYS_ENABLED", False)
    assert [each.name for each in nudges_task.entries()] == ["nudges"]


def test_a_message_for_birthdays_keeps_no_name_or_gift_note_in_the_log(world, monkeypatch):
    monkeypatch.setattr(actions, "_entries", {})  # put back after the test
    actions.set_catalogue(nudges_task.entries())
    logged = []

    async def log_result(row_id, **values):
        logged.append(values)

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(conversation, "log_result", log_result)
    monkeypatch.setattr(conversation, "send_log", nothing)
    monkeypatch.setattr(database, "record_cost", nothing)
    turn = conversation.Turn(tasks=["birthdays"], extracted=[{"task": "birthdays", "action": "birthday_gift", "data": {"person": "Mum", "note": "a scarf"}}], said=["🎁 Saved · gift idea for **Mum**"])
    spent = SimpleNamespace(claude_calls=[])
    monkeypatch.setattr(conversation.timing, "as_dict", lambda spent, duration: {})
    run(conversation._finish(SimpleNamespace(channel_id=HUB, text="gift idea for Mum: a scarf"), 1, turn, spent, 0.1))
    every = repr(logged)
    assert "Mum" not in every and "scarf" not in every and actions.PRIVATE_NOTE in every
    assert '"action": "birthday_gift"' in every, "which action it was is kept"
