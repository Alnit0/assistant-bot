"""The diary (tasks/diary, behind DIARY_ENABLED, off): words about the day, a mood, a streak, one evening ask.

Made-up entries only. No test prints or keeps an entry's words anywhere but the temporary database.
"""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, hub, live, scheduler, timeinput
from core import day as days
from core.actions import Request, Shown
from core.errors import UserError
from tasks.diary import mood, plain, rules, store
from tasks.diary.rules import Entry

HUB, INBOX = 555, 100
MADE_UP = "Made-up day: walked to the shops and back."


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"diary": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=9000)

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
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
    monkeypatch.setattr(plain, "changed", lambda user_id: None)
    monkeypatch.setattr(config, "OWNER_ID", owner.discord_id)
    plain.register()
    live.reset()
    seen.day = days.today() + timedelta(days=1)
    seen.at = lambda hour, minute=0, ahead=0: clock.advance_to(days.at(seen.day + timedelta(days=ahead), time(hour, minute)))
    seen.at(19, 0)
    seen.request = lambda text=MADE_UP: Request(owner, INBOX, text)
    return seen


def write(world, text=MADE_UP, said_mood=None):
    return run(plain.write(world.request(text), {"mood": said_mood} if said_mood else {}, frozenset()))


def entry(world, day=None):
    return run(store.entry(world.owner.id, day or world.day))


class Press:
    db = database

    def __init__(self, world, arg, message_id=1):
        self.user, self.arg, self.message_id, self.channel_id = world.owner, arg, message_id, HUB
        self.shown = []

    async def update(self, card):
        self.shown.append(card)


# --- the day, and appending ------------------------------------------------------------------------------------
def test_off_unless_switched_on():
    assert config.DIARY_ENABLED is False and config.DIARY_MOOD is True


def test_the_diary_day_ends_at_4_am():
    on = date(2026, 10, 15)
    assert rules.diary_day(days.at(on, time(23, 50))) == on
    assert rules.diary_day(days.at(on + timedelta(days=1), time(0, 30))) == on, "just after midnight is the evening before"
    assert rules.diary_day(days.at(on + timedelta(days=1), time(3, 59))) == on
    assert rules.diary_day(days.at(on + timedelta(days=1), time(4, 0))) == on + timedelta(days=1)


def test_several_messages_on_one_day_append_to_one_entry(world):
    first = write(world, said_mood="good")
    assert first == "📔 Saved · 😊 Good"
    second = write(world, "Made-up: a second note.")
    assert second == "📔 Added to today · 😊 Good"
    kept = entry(world)
    assert kept.notes == 2 and kept.text == f"{MADE_UP}\n\nMade-up: a second note.", "the words as sent, a blank line between"


def test_a_message_after_midnight_goes_to_the_evening_before(world):
    write(world, said_mood="ok")
    world.at(0, 40, ahead=1)
    write(world, "Made-up: one more thought.")
    assert entry(world).notes == 2 and entry(world, world.day + timedelta(days=1)) is None


def test_the_line_said_back_names_none_of_the_words(world):
    said = write(world, said_mood="good")
    assert MADE_UP not in said and "shops" not in said


# --- the mood ---------------------------------------------------------------------------------------------------
def test_a_mood_the_words_made_clear_is_on_the_line(world):
    assert write(world, said_mood="bad") == "📔 Saved · 😞 Bad"
    assert entry(world).mood_scale == "three" and entry(world).mood == "bad", "kept with the scale it was recorded on"


def test_with_no_clear_mood_the_line_asks_with_a_blurple_button_a_mood(world):
    result = write(world)
    assert isinstance(result, Shown)
    (row,) = world.sent[-1].card.rows
    assert [button.label for button in row] == ["Good", "OK", "Bad"] and {button.style for button in row} == {cards.PRIMARY}
    assert MADE_UP not in world.sent[-1].card.text


def test_a_mood_by_button_and_its_undo(world):
    write(world)
    pressed = Press(world, f"{world.day.isoformat()}:ok")
    assert run(plain.on_mood(pressed)) == "📔 Saved · 😐 OK"
    assert entry(world).mood == "ok"
    assert run(plain.on_undo(Press(world, world.day.isoformat()))) == "📔 Mood · back to none"
    assert entry(world).mood is None


def test_a_mood_changed_in_words_shows_old_to_new_and_undo_puts_it_back(world):
    write(world, said_mood="bad")
    run(plain.set_mood(world.request("actually today was ok"), {"mood": "ok"}, frozenset()))
    assert world.sent[-1].card.text == "📔 Mood · ~~😞 Bad~~ → **😐 OK**"
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == "📔 Mood · back to 😞 Bad"


def test_a_mood_that_is_not_on_the_scale_is_never_kept(world):
    write(world, said_mood="ecstatic")
    assert entry(world).mood is None
    with pytest.raises(UserError):
        run(plain.set_mood(world.request(), {"mood": "ecstatic"}, frozenset()))


def test_an_old_entry_reads_on_the_scale_it_was_recorded_on(monkeypatch):
    five = mood.Scale("five", tuple(mood.Level(str(n), f"Level {n}", f"{n}️⃣") for n in range(1, 6)), cards.PRIMARY, "a score")
    monkeypatch.setattr(mood, "SCALES", {**mood.SCALES, "five": five})
    monkeypatch.setattr(mood, "CURRENT", five)
    assert mood.shown("three", "good") == "😊 Good", "an entry from before the change still reads"
    assert mood.shown("five", "4") == "4️⃣ Level 4" and mood.checked("good") is None and mood.checked("4") == "4"
    assert mood.shown("gone", "x") == "x", "a scale no longer known is shown by its key"


def test_with_the_mood_off_there_are_no_buttons_and_no_mood_actions(world, monkeypatch):
    monkeypatch.setattr(config, "DIARY_MOOD", False)
    assert write(world, said_mood="good") == "📔 Saved" and entry(world).mood is None
    assert world.sent == [], "no buttons asked"
    assert [action.name for action in plain.actions()] == ["diary_write", "diary_show", "diary_delete"]


# --- the evening ask ----------------------------------------------------------------------------------------------
def _ask(world):
    job = SimpleNamespace(id=1, payload={}, notes=[])
    return run(plain.ask_job(job))


def test_the_evening_ask_is_posted_once_and_names_nothing(world, monkeypatch):
    noted = []
    monkeypatch.setattr(scheduler, "note", lambda job, text: noted.append(text))
    world.at(21, 0)
    _ask(world)
    assert world.sent[-1].card.text == rules.ASK and world.sent[-1].channel == HUB
    _ask(world)
    assert noted == ["asked", "not asked: asked already today"], "one ask a day, never repeated"


def test_no_ask_when_today_is_written(world, monkeypatch):
    noted = []
    monkeypatch.setattr(scheduler, "note", lambda job, text: noted.append(text))
    write(world, said_mood="good")
    world.at(21, 0)
    _ask(world)
    assert noted == ["not asked: today is written"]


def test_writing_or_a_mood_clears_the_ask(world, monkeypatch):
    monkeypatch.setattr(scheduler, "note", lambda job, text: None)
    world.at(21, 0)
    _ask(world)
    asked = world.sent[-1].id
    write(world, said_mood="good")
    assert asked in world.deleted


def test_the_ask_is_never_sent_to_ntfy_and_waits_out_quiet_hours():
    from core import notify

    said = notify.KINDS["diary.ask"]
    assert said.where == notify.DISCORD and not said.through


# --- the streak ---------------------------------------------------------------------------------------------------
def test_the_streak_counts_days_in_a_row_back_from_today_or_yesterday():
    on = date(2026, 10, 15)
    assert rules.streak({on, on - timedelta(days=1), on - timedelta(days=2)}, on) == 3
    assert rules.streak({on - timedelta(days=1), on - timedelta(days=2)}, on) == 2, "today not written yet: it still stands"
    assert rules.streak({on, on - timedelta(days=2)}, on) == 1, "a day missed breaks it"
    assert rules.streak(set(), on) == 0


def test_the_streak_holds_across_midnight(world):
    write(world, said_mood="good")
    world.at(9, 0, ahead=1)
    assert write(world, "Made-up: the next day.").summary == "📔 Saved · streak 2", "no mood said: the line asks, and still says the streak"


# --- reading back -------------------------------------------------------------------------------------------------
def test_a_day_read_back_shows_its_words_only_when_asked(world):
    write(world, said_mood="good")
    plainly = run(plain.show(world.request(), {"day": "today"}, frozenset()))
    assert plainly.splitlines()[0] == "📔 **Today** · 😊 Good · 1 note" and MADE_UP not in plainly
    asked = run(plain.show(world.request(), {"day": "today", "words": True}, frozenset()))
    assert f"> {MADE_UP}" in asked and MADE_UP not in asked.splitlines()[0], "the first line names nothing"


def test_last_tuesday_is_the_one_gone_by():
    thursday = date(2026, 10, 15)
    assert timeinput.parse_past_date("last Tuesday", thursday) == date(2026, 10, 13)
    assert timeinput.parse_past_date("yesterday", thursday) == date(2026, 10, 14)
    assert timeinput.parse_past_date("13 Oct", thursday) == date(2026, 10, 13)
    assert timeinput.parse_past_date("20 Oct", thursday) == date(2025, 10, 20)
    with pytest.raises(UserError):
        timeinput.parse_past_date("tomorrow", thursday)


def test_the_week_and_the_month_read_back_with_moods_and_no_words():
    on = date(2026, 10, 15)
    entries = [Entry(1, 1, date(2026, 10, 13), MADE_UP, "three", "good", notes=1), Entry(2, 1, date(2026, 10, 14), MADE_UP, "three", "bad", notes=1)]
    week = rules.span_answer(entries, rules.week_of(on), on, "This week")
    assert week.splitlines()[:3] == ["📔 **This week** · 2 of 4 days · 😊 1 · 😞 1", "Tue 13 Oct · 😊", "Wed 14 Oct · 😞"] and MADE_UP not in week
    month = rules.mood_answer(entries, rules.month_of(on), "October")
    assert month.splitlines() == ["📔 **October** · 😊 1 · 😞 1", "·" * 12 + "😊😞" + "·"]


# --- deleting -----------------------------------------------------------------------------------------------------
def test_deleting_a_day_is_a_red_card_first_and_its_words_go(world):
    write(world, said_mood="ok")
    proposal = run(plain.delete_card(world.request("delete today's diary"), {}, frozenset()))
    assert proposal.destructive and proposal.kind == "remove" and MADE_UP not in "\n".join(proposal.lines)
    assert entry(world) is not None, "nothing goes before the card is pressed"
    run(plain.delete_save(world.request(), proposal.data))
    assert entry(world) is None and run(plain.delete_check(world.request(), proposal.data)) == ""


# --- the hub: the Today card, the briefing, the week ------------------------------------------------------------------
def test_the_today_card_line_and_the_briefing_line_name_no_words(world):
    from tasks import diary

    (line,) = run(diary.today_lines(world.owner.id, clock.now()))
    assert line.text == "**Diary** · not yet" and not line.done
    write(world, said_mood="good")
    (line,) = run(diary.today_lines(world.owner.id, clock.now()))
    assert line.text == "**Diary** · 😊 Good" and line.done
    world.at(9, 0, ahead=1)
    said = run(diary.summary(world.owner.id, world.day + timedelta(days=1)))
    assert said.overview == "streak 1 · yesterday 😊" and said.glance == "not written yet today"


def test_the_week_of_everything_shows_a_mood_a_day(world):
    from tasks import diary

    write(world, said_mood="good")
    monday = world.day - timedelta(days=world.day.weekday())
    week = run(diary.week(world.owner.id, monday, world.day))
    assert week.line.endswith("😊") and week.line.count("·") == (world.day - monday).days


# --- privacy ------------------------------------------------------------------------------------------------------
def test_the_task_keeps_its_words_to_itself_and_nothing_sticks_to_it():
    from tasks import diary

    (entry_,) = diary.task.entries() if config.DIARY_ENABLED else _entries_on(diary)
    assert entry_.private and not entry_.sticks


def _entries_on(diary):
    old = config.DIARY_ENABLED
    config.DIARY_ENABLED = True
    try:
        return diary.task.entries()
    finally:
        config.DIARY_ENABLED = old


def test_what_extraction_is_told_holds_no_words(world):
    write(world, said_mood="good")
    told = run(plain.state(world.request()))
    assert MADE_UP not in str(told) and "written" in str(told)


def test_the_message_log_keeps_a_note_in_place_of_a_private_task_s_words(make_db, owner):
    from core import actions, conversation

    make_db()
    row = run(database.log_received(MADE_UP, "chat", 4242, INBOX, user_id=owner.id))
    assert actions.PRIVATE_NOTE not in MADE_UP
    run(database.log_result(row, content=actions.PRIVATE_NOTE))
    conn = database.connect()
    try:
        (content,) = conn.execute("SELECT content FROM message_log WHERE id = ?", (row,)).fetchone()
    finally:
        conn.close()
    assert content == actions.PRIVATE_NOTE and conversation is not None
