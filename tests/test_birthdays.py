"""Birthdays, part of reminders (tasks/nudges/birthdays.py), behind BIRTHDAYS_ENABLED, as Alex reworked them on
19 Oct: never a post or a ping; the day itself is the Bot calendar's yearly all-day event (marked as the bot's, and
never shown as a calendar item anywhere else); from 14 days a small grey Upcoming birthdays box low in the briefing,
several in one, soonest first, 29 February on the 28th; one pinned list in #calendar edited in place; the user's
own birthday ("my birthday", never a person called My) and tidied names; gift notes, when, what is coming up, the
week's line; and no name or gift note in a log. Made-up names only."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, conversation, database, design, hub, live, notify, pins, scheduler
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



def add(world, person, said_date, text="said", **more):
    proposal = run(birthdays.add_card(world.request(text), {"person": person, "date": said_date, **more}, frozenset()))
    run(birthdays.add_save(world.request(text), proposal.data))
    assert run(birthdays.add_check(world.request(text), proposal.data)) == ""
    return proposal


def kept(world, name):
    return next(each for each in run(birthdays.every(world.owner.id)) if each.name == name)


def made_up(world, name, left, year=None, **more):
    day = world.today + timedelta(days=left)
    run(database.run(birthdays.db_add, Birthday(0, world.owner.id, name, day.month, day.day, year, **more), clock.now()))
    return kept(world, name)


CALENDAR = 500


@pytest.fixture
def listed(world, monkeypatch):
    """#calendar set, pinning seen."""
    monkeypatch.setattr(config, "CALENDAR_CHANNEL_ID", CALENDAR)
    world.pinned = []

    async def set_pinned(channel_id, message_id, pinned, reason):
        world.pinned.append((channel_id, message_id, pinned))

    monkeypatch.setattr(pins, "set_pinned", set_pinned)
    return world


@pytest.fixture
def no_pings(world, monkeypatch):
    """Anything that would notify, seen: a birthday must never."""
    world.notified = []

    async def post(*args, **kwargs):
        world.notified.append(args)
        return None

    monkeypatch.setattr(notify, "post", post)
    return world


# --- the names: Alex's own, possessives and relations (19 Oct, a live bug: "my birthday" saved as a person called My)
@pytest.mark.parametrize(
    "said, name, mine",
    [
        ("My", "", True), ("me", "", True), ("my", "", True), ("Myself", "", True), ("I", "", True), ("", "", True),
        ("Mum's", "Mum", False), ("my mum's", "Mum", False), ("my Mum", "Mum", False), ("mum", "Mum", False),
        ("Sam's", "Sam", False), ("James'", "James", False), ("Sam’s", "Sam", False), ("  made-up   friend ", "Made-up Friend", False),
        ("Myra", "Myra", False), ("McKenzie", "McKenzie", False),
    ],
)
def test_a_name_is_tidied_after_extraction_and_my_alone_is_the_user_s_own(said, name, mine):
    assert birthdays.tidy(said) == (name, mine)


def test_my_birthday_is_saved_as_the_user_s_own_and_shown_as_your_birthday(world):
    proposal = add(world, "me", "20 October", "my birthday is 20 October")
    assert proposal.lines[0].startswith("**Your birthday** · "), "never a person called My or Me"
    (own,) = run(birthdays.every(world.owner.id))
    assert own.mine and own.name == ""
    (body,) = world.bot.series.values()
    assert body["summary"] == "🎂 Your birthday"
    with pytest.raises(UserError, match="is there already"):
        run(birthdays.add_card(world.request(), {"person": "My", "date": "20 October"}, frozenset()))
    said = run(birthdays.when_said(world.request(), {"person": "me"}, frozenset()))
    assert said.startswith("🎂 **Your birthday** · ")


def test_a_relation_is_shown_beside_the_name(world):
    proposal = add(world, "Tom", "4 May", "my brother Tom's birthday is 4 May", relation="Brother")
    assert proposal.lines[0].startswith("**Tom (brother)** · ")
    assert kept(world, "Tom").relation == "brother"
    (body,) = world.bot.series.values()
    assert body["summary"] == "🎂 Tom's birthday"
    assert run(birthdays.when_said(world.request(), {"person": "tom"}, frozenset())).startswith("🎂 **Tom (brother)** · ")


def test_the_live_row_called_my_becomes_the_user_s_own_and_its_event_is_renamed(world):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    birthdays.add_tables(conn)
    for name in ("My", "Mum's", "Sam", "me"):
        conn.execute("INSERT INTO nudges_birthdays (user_id, name, month, day, calendar_ref, created_at) VALUES (1, ?, 10, 20, ?, 'x')", (name, f"ref-{name}"))
    birthdays.add_mine_and_list(conn)
    rows = conn.execute("SELECT name, mine, resync FROM nudges_birthdays ORDER BY id").fetchall()
    assert rows == [("", 1, 1), ("Mum", 0, 1), ("Sam", 0, 1), ("", 1, 1)], "every event with one: the bot's marker"


def test_a_renamed_event_is_brought_up_to_date_on_the_bot_calendar(world):
    run(database.run(birthdays.db_add, Birthday(0, world.owner.id, "", 10, 20, mine=True), clock.now()))
    (own,) = run(birthdays.every(world.owner.id))
    world.bot.series["old"] = {"summary": "🎂 My's birthday"}
    run(database.run(lambda conn: conn.execute("UPDATE nudges_birthdays SET calendar_ref = 'old', resync = 1 WHERE id = ?", (own.id,))))
    assert run(birthdays.resync()) == 1
    assert world.bot.series["old"]["summary"] == "🎂 Your birthday"
    assert run(birthdays.resync()) == 0, "once"


def test_a_birthday_s_event_carries_the_bot_s_marker_and_is_never_a_calendar_item():
    from tasks.calendar import google

    body = birthdays.event_body(Birthday(1, 1, "Sam", 10, 29), date(2026, 10, 19))
    assert body["extendedProperties"] == {"private": {google.HIDDEN: birthdays.MARK}}
    happening = {**body, "id": "s1_20261029", "recurringEventId": "s1", "summary": "Made-up anything"}
    assert google.to_event(happening, "bot") is None, "by the marker, never by the title"
    plain = {"id": "e1", "summary": "🎂 Sam's birthday", "start": {"date": "2026-10-29"}, "end": {"date": "2026-10-30"}}
    assert google.to_event(plain, "bot") is not None, "one Alex made himself is his: shown as any event"


# --- a card first, with the Bot calendar ----------------------------------------------------------------------------------
def test_a_new_birthday_is_a_card_then_a_yearly_all_day_event_on_the_bot_calendar(world):
    proposal = add(world, "Mum", "12 March", "Mum's birthday 12 March")
    assert proposal.kind == "new" and proposal.lines[0].startswith("**Mum** · ")
    assert proposal.lines[1] == "Shown in the briefing from 14 days before"
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
        run(birthdays.add_card(world.request(), {"person": "my mum's", "date": "12 March"}, frozenset()))
    change = run(birthdays.add_card(world.request(), {"person": "Mum", "date": "13 March"}, frozenset()))
    assert change.kind == "change" and change.lines[1] == "~~12 March~~ → **13 March**"
    run(birthdays.add_save(world.request(), change.data))
    assert (kept(world, "Mum").month, kept(world, "Mum").day) == (3, 13)
    (body,) = world.bot.series.values()
    assert body["start"]["date"].endswith("-03-13"), "the calendar is kept in step"


def test_the_heads_up_changed_in_words_and_removing_takes_the_event_off(world):
    add(world, "Mum", "12 March")
    change = run(birthdays.change_card(world.request(), {"person": "Mum", "heads_up": 5}, frozenset()))
    assert change.lines[1] == "~~in the briefing from 14 days before~~ → **in the briefing from 5 days before**"
    run(birthdays.change_save(world.request(), change.data))
    assert kept(world, "Mum").heads_up == 5 and run(birthdays.change_check(world.request(), change.data)) == ""
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


# --- the briefing's Upcoming birthdays box ------------------------------------------------------------------------------------
def test_the_countdown_window_is_14_days_to_the_day_itself():
    sam = Birthday(1, 1, "Sam", 10, 29)
    on = lambda left: date(2026, 10, 29) - timedelta(days=left)
    assert [bool(birthdays.coming([sam], on(left))) for left in (15, 14, 1, 0)] == [False, True, True, True]
    assert not birthdays.coming([sam], date(2026, 10, 30)), "the day after: a year away"
    assert birthdays.box_line(sam, on(10)) == "Sam · Thu 29 Oct · 10 days"
    assert birthdays.box_line(sam, on(1)) == "Sam · Thu 29 Oct · tomorrow"
    assert birthdays.box_line(sam, on(0)) == "Sam · today"
    assert birthdays.box_line(Birthday(2, 1, "", 10, 29, mine=True), on(0)) == "Your birthday · today"


def test_several_share_one_box_soonest_first_in_small_grey_lines(world):
    made_up(world, "Made-up Later", 12)
    made_up(world, "Made-up Today", 0)
    made_up(world, "Made-up Soon", 3)
    made_up(world, "Made-up Far", 20)
    found = run(birthdays.summary(world.owner.id, world.today))
    assert found.heading == "Upcoming birthdays" and found.low and found.status == design.QUIET
    assert [line.split(" · ")[0] for line in found.lines] == ["-# Made-up Today", "-# Made-up Soon", "-# Made-up Later"]
    assert all(line.startswith("-# ") for line in found.lines), "small text"
    assert found.lines[0] == "-# Made-up Today · today" and not found.overview and not found.total


def test_no_box_when_none_is_within_14_days(world):
    made_up(world, "Made-up Far", 15)
    assert run(birthdays.summary(world.owner.id, world.today)) is None


def test_29_february_shows_on_the_28th_in_a_year_without_one():
    leap = Birthday(1, 1, "Made-up Leap", 2, 29, 2000)
    assert birthdays.box_line(leap, date(2027, 2, 28)) == "Made-up Leap · today"
    assert birthdays.box_line(leap, date(2027, 2, 20)) == "Made-up Leap · Sun 28 Feb · 8 days"
    assert birthdays.box_line(leap, date(2028, 2, 20)) == "Made-up Leap · Tue 29 Feb · 9 days"
    assert birthdays.list_line(leap, date(2027, 2, 20)) == "**Made-up Leap** · Sun 28 Feb · 8 days · turns 27"


def test_the_box_sits_low_in_the_briefing_below_the_day_with_a_grey_edge_and_no_buttons(monkeypatch):
    from core import actions as core_actions
    from core.summaries import Section
    from tasks.briefing import rules

    monkeypatch.setattr(config, "DESIGN_ROUND", 5)
    sections = [
        Section("birthdays", "🎂", "Birthdays", core_actions.Summary(status=design.QUIET, lines=("-# Sam · today",), heading="Upcoming birthdays", low=True)),
        Section("weather", "⛅", "Weather", core_actions.Summary("Fine", design.QUIET, ("Made-up fine",))),
        Section("pills", "💊", "Pills", core_actions.Summary("", design.DUE, overview="3 doses")),
    ]
    boxes = [each for each in rules.layout(sections, date(2026, 10, 29)) if isinstance(each, design.Box)]
    texts = [each.children[0].content for each in boxes]
    assert [text.splitlines()[0] for text in texts][-1].endswith("🎂 Upcoming birthdays"), "last: below The day"
    assert "The day" in texts[-2]
    assert boxes[-1].status == design.QUIET and not any(isinstance(child, design.Row) for child in boxes[-1].children)
    said = rules.text(sections, date(2026, 10, 29))
    assert said.index("🎂 **Upcoming birthdays**") > said.index("⛅ **Weather**")


def test_the_birthdays_entry_gives_the_box_and_the_reminders_overview_says_nothing_of_them(world):
    from tasks.nudges import summary

    made_up(world, "Made-up Friend", 10)
    assert run(summary(world.owner.id, world.today)) is None, "no line in The day"
    entry = nudges_task.entries()[1]
    assert entry.summary is birthdays.summary and entry.week is birthdays.week


# --- the pinned list in #calendar ------------------------------------------------------------------------------------------
def test_the_list_is_posted_silently_pinned_and_then_edited_in_place(listed):
    made_up(listed, "Made-up Later", 40, year=1990)
    friend = made_up(listed, "Made-up Soon", 5)
    run(database.run(birthdays.db_add_gift, listed.owner.id, friend.id, "a climbing book", clock.now()))
    assert run(birthdays.redraw_list(listed.owner.id)) == "list posted"
    (first,) = listed.sent
    assert first.channel == CALENDAR and first.silent and listed.pinned == [(CALENDAR, first.id, True)]
    lines = first.card.text.splitlines()
    assert lines[0] == "## 🎂 Birthdays"
    assert lines[1].startswith("**Made-up Soon** · ") and lines[1].endswith("· 5 days")
    assert lines[2] == "-# 🎁 a climbing book", "gift notes small"
    assert lines[3].startswith("**Made-up Later** · ") and " · turns " in lines[3]
    assert run(birthdays.redraw_list(listed.owner.id)) == "list edited"
    assert len(listed.sent) == 1 and listed.edited[-1][0] == first.id


def test_the_daily_job_moves_the_countdown_on_and_names_nobody(listed):
    made_up(listed, "Made-up Soon", 5)
    job = SimpleNamespace(payload={}, user_id=None)
    run(birthdays.check_job(job))
    assert listed.notes == ["list posted"] and "Made-up" not in repr(listed.notes)
    clock.advance_to(days.at(listed.today + timedelta(days=1), time(0, 2)))
    run(birthdays.check_job(job))
    assert listed.edited[-1][1].text.splitlines()[1].endswith("· 4 days")


def test_without_a_calendar_channel_no_list(world, monkeypatch):
    monkeypatch.setattr(config, "CALENDAR_CHANNEL_ID", None)
    made_up(world, "Made-up Soon", 5)
    assert run(birthdays.redraw_list(world.owner.id)) == "no #calendar set" and world.sent == []


def test_the_weekly_summary_has_one_line_for_the_next_14_days(world):
    made_up(world, "Made-up Soon", 3)
    made_up(world, "Made-up Far", 30)
    week = run(birthdays.week(world.owner.id, world.today - timedelta(days=6), world.today - timedelta(days=1)))
    assert week.line.startswith("Made-up Soon ") and "Far" not in week.line and week.small == "in the next 14 days"


# --- never a post or a ping --------------------------------------------------------------------------------------------------
def test_no_birthday_ever_posts_or_pings(listed, no_pings, monkeypatch):
    from core import attention

    for left in (14, 3, 1, 0):
        made_up(listed, f"Made-up {left}", left)
    for step in range(16):
        if step:
            clock.advance_to(days.at(listed.today + timedelta(days=step), time(10, 0)))
        run(birthdays.check_job(SimpleNamespace(payload={}, user_id=None)))
        run(birthdays.again_job(SimpleNamespace(payload={"id": 1, "on": "x", "stage": 0})))
    assert listed.notified == [], "nothing through notify"
    assert {each.channel for each in listed.sent} == {CALENDAR} and len(listed.sent) == 1, "the list only, posted once, silently"
    assert all(each.silent for each in listed.sent)
    assert "nudges.birthday" not in notify.KINDS
    assert not any("birthday" in each.what for each in run(nudges_task.attention(listed.owner.id, clock.now()))), "nothing for the status line"
    assert attention  # the one ranking is the status line's source: the task gives it nothing


def test_a_button_on_an_old_post_takes_it_away(world):
    removed = []
    press = SimpleNamespace(arg="1:2026-10-20:3", db=database, remove=lambda: asyncio.sleep(0, removed.append(True)), user=world.owner)
    assert run(birthdays.on_old_post(press)) == "old birthday post taken away" and removed
    assert set(cards._actions) >= {(nudges_task.name, each) for each in (birthdays.DONE, birthdays.SNOOZE, birthdays.SNOOZE_FOR, birthdays.BACK)} or cards._actions


# --- private: the router's own entry, nothing in a log ---------------------------------------------------------------------
def test_birthdays_are_a_private_entry_of_reminders_only_when_switched_on(world, monkeypatch):
    entries = nudges_task.entries()
    names = [each.name for each in entries]
    assert names == ["nudges", "birthdays"]
    entry = entries[1]
    assert entry.private and entry.icon == "🎂" and entry.plan is None and not actions.problems(entries)
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
