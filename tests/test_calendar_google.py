"""The calendar with several sources and writing (tasks/calendar): the iCal link and the Google Calendar API
through a service account, merged into one view; adding, moving and deleting in the Bot calendar only.

The Google API is a fake in memory (google._send): no real call is made. The key is made up here, the
calendar ids are made up, and no real event is in this file.
"""
import asyncio
import json
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import clock, config, database, live
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks import calendar
from tasks.calendar import google, plain, rules, source, store

BOT_ID, MAIN_ID = "made-up-bot@group.calendar.example", "made-up-main@example.com"
TOKEN_URI = "https://oauth2.example/token"
DAY = date(2026, 11, 2)  # a Monday
ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:made-up
BEGIN:VEVENT
UID:standup
SUMMARY:Made-up standup
DTSTART;TZID=Pacific/Auckland:20261102T090000
DTEND;TZID=Pacific/Auckland:20261102T093000
END:VEVENT
BEGIN:VEVENT
UID:both
SUMMARY:Made-up lunch
DTSTART;TZID=Pacific/Auckland:20261103T123000
DTEND;TZID=Pacific/Auckland:20261103T133000
END:VEVENT
BEGIN:VEVENT
UID:clash
SUMMARY:Made-up review
DTSTART;TZID=Pacific/Auckland:20261106T143000
DTEND;TZID=Pacific/Auckland:20261106T153000
END:VEVENT
END:VCALENDAR
"""


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


class FakeGoogle:
    """The Calendar API in memory: calendars by id, events by id, every call written down."""

    def __init__(self):
        self.calendars = {BOT_ID: {}, MAIN_ID: {}}
        self.calls = []
        self.next = 0
        self.down = set()

    def send(self, method, url, body, headers):
        if url == TOKEN_URI:
            assert b"assertion=" in body, "a signed request for the token"
            return 200, json.dumps({"access_token": "made-up-token", "expires_in": 3600}).encode()
        assert headers["Authorization"] == "Bearer made-up-token"
        path = urllib.parse.urlparse(url).path.split("/calendars/", 1)[1].split("/")
        calendar_id, ref = urllib.parse.unquote(path[0]), (urllib.parse.unquote(path[2]) if len(path) > 2 else "")
        self.calls.append((method, calendar_id))
        if calendar_id in self.down:
            return 503, b"{}"
        found = self.calendars.get(calendar_id)
        if found is None:
            return 404, b"{}"
        payload = json.loads(body) if body else {}
        if method == "GET" and not ref:
            return 200, json.dumps({"items": list(found.values())}).encode()
        if method == "POST":
            self.next += 1
            made = {"id": f"e{self.next}", "status": "confirmed", **payload}
            found[made["id"]] = made
            return 200, json.dumps(made).encode()
        if ref not in found:
            return 404, b"{}"
        if method == "GET":
            return 200, json.dumps(found[ref]).encode()
        if method == "PATCH":
            found[ref].update(payload)
            return 200, json.dumps(found[ref]).encode()
        if method == "DELETE":
            del found[ref]
            return 204, b""
        return 400, b"{}"

    def put(self, calendar_id, title, start, end):
        self.next += 1
        self.calendars[calendar_id][f"e{self.next}"] = {"id": f"e{self.next}", "summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}

    def writes(self):
        return [(method, calendar_id) for method, calendar_id in self.calls if method != "GET"]


@pytest.fixture
def made_up_key(scratch):
    import rsa

    _, private = rsa.newkeys(512)
    path = scratch / "made-up-key.json"
    path.write_text(json.dumps({"type": "service_account", "client_email": "made-up@example.iam", "token_uri": TOKEN_URI, "private_key": private.save_pkcs1().decode()}), encoding="utf-8")
    return path


@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner, scratch, made_up_key):
    make_db({"calendar": store.MIGRATIONS})
    feed = scratch / "made-up.ics"
    feed.write_text(ICS, encoding="utf-8")
    fake = FakeGoogle()
    for name, value in (("CALENDAR_ENABLED", True), ("CALENDAR_ICS_URL", str(feed)), ("CALENDAR_READ", "ics,google:CALENDAR_BOT_ID"),
                        ("GOOGLE_SA_KEY_PATH", str(made_up_key)), ("CALENDAR_BOT_ID", BOT_ID), ("CALENDAR_MAIN_ID", MAIN_ID), ("CALENDAR_WRITE", True)):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(google, "_send", fake.send)
    google._token.clear()
    clock.advance_to(days.at(DAY, time(8, 0)))
    live.reset()
    return SimpleNamespace(owner=owner, fake=fake, request=lambda text="said": Request(owner, 100, text))


def at(day, hour, minute=0):
    return days.at(day, time(hour, minute))


def kept(world):
    return run(store.events(world.owner.id))


# --- several sources ---------------------------------------------------------------------------------------------
def test_the_setting_lists_the_calendars_and_their_sources(world, monkeypatch):
    assert [(type(each).__name__, each.origin) for each in source.sources()] == [("IcsSource", "link"), ("GoogleSource", "bot")]
    monkeypatch.setattr(config, "CALENDAR_READ", f"ics,google:{MAIN_ID},google:CALENDAR_BOT_ID")
    assert [each.origin for each in source.sources()] == ["link", "google1", "bot"]
    monkeypatch.setattr(config, "CALENDAR_READ", "")
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    assert [each.origin for each in source.sources()] == ["link"], "unset: the link alone, as before"
    monkeypatch.setattr(config, "CALENDAR_WRITE", True)
    assert [each.origin for each in source.sources()] == ["link", "bot"], "writing on: the Bot calendar is read too"


def test_no_id_is_in_a_sources_words():
    assert BOT_ID not in repr(google.GoogleSource(BOT_ID, "bot")) and BOT_ID not in str(google.GoogleSource(BOT_ID, "bot"))


def test_the_calendars_merge_into_one_view_each_happening_once(world):
    world.fake.put(BOT_ID, "Made-up lunch", at(DAY + timedelta(days=1), 12, 30), at(DAY + timedelta(days=1), 13, 30))
    world.fake.put(BOT_ID, "Made-up swim", at(DAY, 18), at(DAY, 19))
    assert run(calendar.update(world.owner.id)) == ""
    titles = [each.title for each in kept(world)]
    assert titles.count("Made-up lunch") == 1, "the same happening in two calendars, once"
    assert {"Made-up standup", "Made-up swim", "Made-up review"} <= set(titles)
    lunch = next(each for each in kept(world) if each.title == "Made-up lunch")
    assert lunch.mine, "the bot's own copy is the one kept: it can change it"
    today = [line.text for line in run(calendar.today_lines(world.owner.id, clock.now()))]
    assert today == ["**Made-up standup**", "**Made-up swim**"], "the Today card shows both calendars"


def test_one_calendar_failing_keeps_its_last_copy_and_the_others_are_read(world):
    world.fake.put(BOT_ID, "Made-up swim", at(DAY, 18), at(DAY, 19))
    run(calendar.update(world.owner.id))
    world.fake.down.add(BOT_ID)
    why = run(calendar.update(world.owner.id))
    assert why.startswith("bot: Google answered 503") and BOT_ID not in why
    assert "Made-up swim" in [each.title for each in kept(world)], "its last good copy stays"


def test_a_calendar_not_listed_any_more_leaves_the_copy(world, monkeypatch):
    world.fake.put(BOT_ID, "Made-up swim", at(DAY, 18), at(DAY, 19))
    run(calendar.update(world.owner.id))
    monkeypatch.setattr(config, "CALENDAR_READ", "ics")
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    run(calendar.update(world.owner.id))
    assert "Made-up swim" not in [each.title for each in kept(world)]


# --- only the Bot calendar is ever written to --------------------------------------------------------------------------
def test_no_other_calendar_is_ever_written_to(world, monkeypatch):
    main = google.GoogleSource(MAIN_ID, "google1")
    assert not main.can_write
    for write in (lambda: main.add("x", at(DAY, 9), at(DAY, 10)), lambda: main.move("e1", at(DAY, 9), at(DAY, 10)), lambda: main.delete("e1")):
        with pytest.raises(google.NotAllowed):
            run(write())
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    with pytest.raises(google.NotAllowed):
        run(source.bot().add("x", at(DAY, 9), at(DAY, 10)))
    assert world.fake.writes() == [], "not one write reached any calendar"


def test_the_writing_actions_are_there_only_with_writing_on(world, monkeypatch):
    assert "calendar_add" in [each.name for each in plain.actions()]
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    assert [each.name for each in plain.actions()] == ["calendar_show", "calendar_when", "calendar_free"]
    assert "a new event said with a time" in calendar.task.only_for


# --- adding ----------------------------------------------------------------------------------------------------------
def _add(world, said, data):
    run(calendar.update(world.owner.id))
    return run(plain.add_card(world.request(said), data, frozenset()))


def test_adding_is_a_card_with_its_title_day_time_length_and_clashes(world):
    proposal = _add(world, "dentist Friday 2:45pm for an hour", {"title": "dentist", "day": "Friday", "time": "2:45 pm"})
    assert proposal.lines[0] == "**Dentist**"
    assert proposal.lines[1] == "Fri 6 Nov · `2:45 pm` to `3:45 pm` · 1 hour", "an hour unless said"
    assert proposal.warnings == ("Clashes with **Made-up review** · 2:30 pm to 3:30 pm",), "checked against every calendar"
    assert proposal.kind == "new" and not proposal.destructive


def test_save_adds_it_to_the_bot_calendar_and_the_copy_and_undo_takes_it_away(world):
    proposal = _add(world, "lunch with Sam Thursday at 1 for 90 minutes", {"title": "lunch with Sam", "day": "Thursday", "time": "1 pm", "length": 90})
    said = run(plain.add_save(world.request(), proposal.data))
    assert said == "📅 Added · **Lunch with Sam** · Thu 5 Nov · `1:00 pm` to `2:30 pm` · 90 minutes"
    assert world.fake.writes() == [("POST", BOT_ID)]
    assert run(plain.add_check(world.request(), proposal.data)) == ""
    assert "Lunch with Sam" in [each.title for each in kept(world)], "in the copy at once"
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == "↩️ 📅 **Lunch with Sam** · taken off the calendar"
    assert world.fake.calendars[BOT_ID] == {} and "Lunch with Sam" not in [each.title for each in kept(world)]


def test_a_title_is_only_ever_the_users_own_words(world):
    assert rules.title_from("dentist", "Dentist Friday 3pm") == "Dentist"
    assert rules.title_from("lunch with Sam", "put lunch with Sam on my calendar") == "Lunch with Sam"
    assert rules.title_from("dental appointment", "dentist Friday 3pm") == "", "words not said are never a title"
    with pytest.raises(UserError):
        _add(world, "Friday 3pm", {"title": "appointment", "time": "3pm", "day": "Friday"})


def test_no_time_no_card(world):
    with pytest.raises(UserError, match="What time"):
        _add(world, "dentist Friday", {"title": "dentist", "day": "Friday"})


# --- moving and deleting --------------------------------------------------------------------------------------------------
def _added(world, title="dentist", day="Friday", at_time="3pm"):
    proposal = _add(world, f"{title} {day} {at_time}", {"title": title, "day": day, "time": at_time})
    run(plain.add_save(world.request(), proposal.data))


def test_moving_an_event_the_bot_added_and_undo(world):
    _added(world)
    proposal = run(plain.move_card(world.request("move the dentist to 4pm"), {"search": "dentist", "time": "4pm"}, frozenset()))
    assert proposal.lines == ("**Dentist**", "~~Fri 6 Nov · `3:00 pm` to `4:00 pm` · 1 hour~~ → **Fri 6 Nov · `4:00 pm` to `5:00 pm` · 1 hour**")
    run(plain.move_save(world.request(), proposal.data))
    assert run(plain.move_check(world.request(), proposal.data)) == ""
    moved = next(each for each in kept(world) if each.title == "Dentist")
    assert days.local_time(moved.start) == time(16, 0)
    assert run(plain.undo(world.request("undo that"), {}, frozenset())).startswith("↩️ 📅 **Dentist** · back to Fri 6 Nov · `3:00 pm`")


def test_deleting_is_a_red_card_and_undo_puts_it_back(world):
    _added(world)
    proposal = run(plain.delete_card(world.request("delete the dentist"), {"search": "dentist"}, frozenset()))
    assert proposal.destructive and proposal.confirm_label == "Delete" and proposal.kind == "remove"
    assert run(plain.delete_save(world.request(), proposal.data)) == "🗑️ 📅 **Dentist** · deleted"
    assert run(plain.delete_check(world.request(), proposal.data)) == "" and "Dentist" not in [each.title for each in kept(world)]
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == "↩️ 📅 **Dentist** · back on the calendar"
    assert len(world.fake.calendars[BOT_ID]) == 1


def test_an_event_on_another_calendar_is_never_changed(world):
    run(calendar.update(world.owner.id))
    for card in (lambda: plain.move_card(world.request("move the review to 4pm"), {"search": "review", "time": "4pm"}, frozenset()),
                 lambda: plain.delete_card(world.request("delete the review"), {"search": "review"}, frozenset())):
        with pytest.raises(UserError) as said:
            run(card())
        assert "I can only change events I added" in str(said.value) and "add" in str(said.value)
    assert world.fake.writes() == []


def test_what_extraction_is_told_holds_no_event_name(world):
    _added(world)
    told = run(plain.state(world.request()))
    assert "Dentist" not in str(told) and "Made-up" not in str(told)


def test_writing_off_says_so(world, monkeypatch):
    monkeypatch.setattr(config, "CALENDAR_WRITE", False)
    with pytest.raises(UserError, match="off"):
        run(plain.add_card(world.request("dentist Friday 3pm"), {"title": "dentist", "time": "3pm"}, frozenset()))
