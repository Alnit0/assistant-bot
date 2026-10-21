"""Repeating events in the Bot calendar (tasks/calendar/series.py, core/recurrence.py): made in words as a
real Google recurrence, one happening changed or cancelled, this and following split, the whole series
changed, a series ended from a day, deleted completely, and every change undone.

Google is a fake in memory that expands a series the way the API does with singleEvents (an RRULE read
in the event's own time zone, its exceptions and its end kept). No real call is made; the calendar ids,
the key and every event here are made up.
"""
import asyncio
import json
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from dateutil import rrule as dateutil_rrule

from core import clock, config, live, recurrence
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks.calendar import google, plain, rules, series, source, store

BOT_ID, MAIN_ID = "made-up-bot@group.calendar.example", "made-up-main@example.com"
TOKEN_URI = "https://oauth2.example/token"
DAY = date(2026, 11, 2)  # a Monday
AUCKLAND = ZoneInfo("Pacific/Auckland")


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


class SeriesGoogle:
    """The Calendar API in memory, with repeating events: a series is kept as it was sent and
    expanded on reading (singleEvents), a happening changed or cancelled is an exception."""

    def __init__(self):
        self.calendars = {BOT_ID: {}, MAIN_ID: {}}
        self.exceptions: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.next = 0

    @staticmethod
    def _start(value: dict) -> datetime:
        found = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
        return found if found.tzinfo else found.replace(tzinfo=ZoneInfo(value.get("timeZone") or "UTC"))

    def _happenings(self, master: dict, low: datetime, high: datetime) -> list[dict]:
        start, end = self._start(master["start"]), self._start(master["end"])
        found = []
        line = next(each for each in master["recurrence"] if each.startswith("RRULE:"))
        for moment in dateutil_rrule.rrulestr(line, dtstart=start).between(low - (end - start), high, inc=True):
            ref = f"{master['id']}_{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
            item = {"id": ref, "recurringEventId": master["id"], "status": "confirmed", "summary": master["summary"],
                    "start": {"dateTime": moment.isoformat()}, "end": {"dateTime": (moment + (end - start)).isoformat()}}
            item.update(self.exceptions.get(ref, {}))
            if item["status"] != "cancelled" and self._start(item["end"]) > low and self._start(item["start"]) < high:
                found.append(item)
        return found

    def _instance(self, calendar: dict, ref: str) -> dict | None:
        """One happening by its id, as it is now (its exception applied, cancelled ones too)."""
        master_id, _, stamp = ref.rpartition("_")
        master = calendar.get(master_id)
        if master is None or not stamp:
            return None
        moment = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        start, end = self._start(master["start"]), self._start(master["end"])
        line = next(each for each in master["recurrence"] if each.startswith("RRULE:"))
        if not dateutil_rrule.rrulestr(line, dtstart=start).between(moment - timedelta(seconds=1), moment + timedelta(seconds=1), inc=True):
            return None
        local = moment.astimezone(start.tzinfo)
        item = {"id": ref, "recurringEventId": master_id, "status": "confirmed", "summary": master["summary"],
                "start": {"dateTime": local.isoformat()}, "end": {"dateTime": (local + (end - start)).isoformat()}}
        item.update(self.exceptions.get(ref, {}))
        return item

    def send(self, method, url, body, headers):
        if url == TOKEN_URI:
            return 200, json.dumps({"access_token": "made-up-token", "expires_in": 3600}).encode()
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.split("/calendars/", 1)[1].split("/")
        calendar_id, ref = urllib.parse.unquote(path[0]), (urllib.parse.unquote(path[2]) if len(path) > 2 else "")
        self.calls.append((method, calendar_id))
        calendar = self.calendars[calendar_id]
        payload = json.loads(body) if body else {}
        if method == "GET" and not ref:
            query = dict(urllib.parse.parse_qsl(parsed.query))
            assert query["singleEvents"] == "true", "a series is read a happening at a time"
            low, high = datetime.fromisoformat(query["timeMin"]), datetime.fromisoformat(query["timeMax"])
            items = []
            for each in calendar.values():
                if each.get("recurrence"):
                    items += self._happenings(each, low, high)
                elif self._start(each["start"]) < high and self._start(each["end"]) > low:
                    items.append(each)
            return 200, json.dumps({"items": items}).encode()
        if method == "POST":
            self.next += 1
            made = {"id": f"s{self.next}", "status": "confirmed", **payload}
            calendar[made["id"]] = made
            return 200, json.dumps(made).encode()
        if ref in calendar:
            if method == "GET":
                return 200, json.dumps(calendar[ref]).encode()
            if method == "PATCH":
                calendar[ref].update(payload)
                return 200, json.dumps(calendar[ref]).encode()
            if method == "DELETE":
                del calendar[ref]
                return 204, b""
        happening = self._instance(calendar, ref)
        if happening is None:
            return 404, b"{}"
        if method == "GET":
            return 200, json.dumps(happening).encode()
        if method == "PATCH":
            self.exceptions.setdefault(ref, {}).update(payload)
            return 200, json.dumps({**happening, **payload}).encode()
        if method == "DELETE":
            self.exceptions.setdefault(ref, {})["status"] = "cancelled"
            return 204, b""
        return 400, b"{}"

    def series(self):
        return [each for each in self.calendars[BOT_ID].values() if each.get("recurrence")]

    def writes(self):
        return {calendar_id for method, calendar_id in self.calls if method != "GET"}


@pytest.fixture
def made_up_key(scratch):
    import rsa

    _, private = rsa.newkeys(512)
    path = scratch / "made-up-key.json"
    path.write_text(json.dumps({"type": "service_account", "client_email": "made-up@example.iam", "token_uri": TOKEN_URI, "private_key": private.save_pkcs1().decode()}), encoding="utf-8")
    return path


@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner, made_up_key):
    make_db({"calendar": store.MIGRATIONS})
    fake = SeriesGoogle()
    for name, value in (("CALENDAR_ENABLED", True), ("CALENDAR_ICS_URL", ""), ("CALENDAR_READ", "google:CALENDAR_BOT_ID"),
                        ("GOOGLE_SA_KEY_PATH", str(made_up_key)), ("CALENDAR_BOT_ID", BOT_ID), ("CALENDAR_MAIN_ID", MAIN_ID), ("CALENDAR_WRITE", True)):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(google, "_send", fake.send)
    google._token.clear()
    clock.advance_to(days.at(DAY, time(7, 0)))
    live.reset()
    world = SimpleNamespace(owner=owner, fake=fake)
    world.request = lambda text="said": Request(owner, 100, text)
    return world


def card(world, prepare, data, text="said"):
    return run(prepare(world.request(text), data, frozenset()))


def save(world, apply, verify, proposal, text="said"):
    said = run(apply(world.request(text), proposal.data))
    assert run(verify(world.request(text), proposal.data)) == "", "read back before it is confirmed"
    return said


def kept(world):
    return run(store.events(world.owner.id))


def times_on(world, day, title="Work"):
    return [(days.local_time(each.start), days.local_time(each.end)) for each in rules.on_day(kept(world), day) if each.title == title]


WORK = {"title": "work", "repeat": "weekdays", "time": "9", "ends_at": "5:30"}


def add_work(world, **more):
    proposal = card(world, plain.add_card, {**WORK, **more}, "work every weekday 9 to 5:30")
    save(world, plain.add_save, plain.add_check, proposal, "work every weekday 9 to 5:30")
    return proposal


# --- made in words, as a real recurrence ------------------------------------------------------------------------------
def test_work_every_weekday_9_to_5_30_is_a_card_then_a_real_google_recurrence(world):
    proposal = card(world, plain.add_card, WORK, "work every weekday 9 to 5:30")
    assert proposal.lines[:3] == ("**Work**", "Weekdays · `9:00 am` to `5:30 pm`", "From Mon 2 Nov · no end")
    assert proposal.lines[3].endswith("Next: Mon 2 Nov, Tue 3 Nov, Wed 4 Nov") and proposal.kind == "new"
    said = save(world, plain.add_save, plain.add_check, proposal)
    assert said == "🗓️ Added · **Work** · weekdays · `9:00 am` to `5:30 pm`, from Mon 2 Nov"
    (made,) = world.fake.series()
    assert made["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"]
    assert made["start"] == {"dateTime": "2026-11-02T09:00:00", "timeZone": "Pacific/Auckland"}, "local time and its zone"
    assert times_on(world, DAY + timedelta(days=4)) == [(time(9, 0), time(17, 30))] and times_on(world, DAY + timedelta(days=5)) == []
    assert world.fake.writes() == {BOT_ID}, "no other calendar is ever written to"


@pytest.mark.parametrize("said, lines, rule", [
    ({"title": "swim", "repeat": "days", "weekdays": ["mon", "thu"], "every_weeks": 2, "time": "6pm"},
     ("Every 2 weeks on Mon and Thu · `6:00 pm` to `7:00 pm`", "From Mon 2 Nov · no end", "Next: Mon 2 Nov, Thu 5 Nov, Mon 16 Nov"),
     "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH"),
    ({"title": "rent", "repeat": "monthly", "month_day": 1, "time": "10am", "times": 6},
     ("Monthly on the 1st · `10:00 am` to `11:00 am`", "From Tue 1 Dec · 6 times", "Next: Tue 1 Dec, Fri 1 Jan, Mon 1 Feb"),
     "RRULE:FREQ=MONTHLY;BYMONTHDAY=1;COUNT=6"),
    ({"title": "class", "repeat": "days", "weekdays": ["wed"], "time": "7pm", "until": "16 December"},
     ("Every Wed · `7:00 pm` to `8:00 pm`", "From Wed 4 Nov · until Wed 16 Dec", "Next: Wed 4 Nov, Wed 11 Nov, Wed 18 Nov"),
     "RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL=20261216T105959Z"),
])
def test_every_kind_of_repeat_shows_its_pattern_start_next_three_and_end(world, said, lines, rule):
    proposal = card(world, plain.add_card, said, said["title"])
    assert (proposal.lines[1], proposal.lines[2]) == lines[:2] and proposal.lines[3].endswith(lines[2])
    assert proposal.data["rrule"] == rule
    save(world, plain.add_save, plain.add_check, proposal, said["title"])
    assert world.fake.series()[0]["recurrence"] == [rule]


def test_a_series_until_a_day_ends_that_day_in_auckland(world):
    add_work(world, until="6 November")
    assert times_on(world, date(2026, 11, 6)) == [(time(9, 0), time(17, 30))] and times_on(world, date(2026, 11, 9)) == []


def test_undo_after_adding_takes_the_whole_series_off(world):
    add_work(world)
    assert run(plain.undo(world.request("undo that"), {}, frozenset())) == "↩️ 🗓️ **Work** · taken off the calendar"
    assert world.fake.series() == [] and [each for each in kept(world) if each.title == "Work"] == []


# --- one happening ---------------------------------------------------------------------------------------------------
def test_cancel_work_next_tuesday_cancels_that_day_only_and_undo_brings_it_back(world):
    add_work(world)
    proposal = card(world, plain.cancel_card, {"search": "work", "day": "10 November", "scope": "one"}, "cancel work next Tuesday")
    assert proposal.lines[0] == "**Work** · Tue 10 Nov · `9:00 am` to `5:30 pm` · 8 hours 30 minutes · cancelled"
    assert save(world, plain.cancel_save, plain.cancel_check, proposal).startswith("🗓️ Cancelled · **Work** · Tue 10 Nov")
    assert times_on(world, date(2026, 11, 10)) == [] and times_on(world, date(2026, 11, 11)) == [(time(9, 0), time(17, 30))]
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    assert times_on(world, date(2026, 11, 10)) == [(time(9, 0), time(17, 30))]


def test_work_next_friday_is_10_to_2_moves_that_day_only(world):
    add_work(world)
    proposal = card(world, plain.move_card, {"search": "work", "day": "13 November", "time": "10", "ends_at": "2", "scope": "one"}, "work next Friday is 10 to 2")
    save(world, plain.move_save, plain.move_check, proposal)
    assert times_on(world, date(2026, 11, 13)) == [(time(10, 0), time(14, 0))]
    assert times_on(world, date(2026, 11, 12)) == [(time(9, 0), time(17, 30))], "the rest as they are"
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    assert times_on(world, date(2026, 11, 13)) == [(time(9, 0), time(17, 30))]


def test_a_day_that_could_mean_one_or_the_series_asks_just_that_day_or_from_then_on(world):
    add_work(world)
    asked = card(world, plain.cancel_card, {"search": "work", "day": "Thursday"}, "cancel work on Thursday")
    assert asked.question.text == "Just Thu 5 Nov, or from then on?"
    assert [each.label for each in asked.question.choices] == ["Just Thu 5 Nov", "From then on"]
    answered = card(world, plain.cancel_card, asked.question.choices[0].data)
    assert answered.question is None and answered.data["op"] == "cancel_one"
    today = card(world, plain.cancel_card, {"search": "work"}, "cancel work")
    assert today.question.text == "Just today, or from then on?", "said on a day it is on: today, or from now on"


# --- this and following, the whole series ---------------------------------------------------------------------------------
def test_work_starts_at_8_30_from_next_week_splits_the_series_and_the_past_is_unchanged(world):
    add_work(world)
    clock.advance_to(days.at(DAY + timedelta(days=2), time(7, 0)))
    proposal = card(world, plain.move_card, {"search": "work", "day": "next Monday", "time": "8:30", "scope": "following"}, "work starts at 8:30 from next week")
    assert proposal.lines[1].startswith("From Mon 9 Nov · ") and proposal.data["op"] == "following"
    save(world, plain.move_save, plain.move_check, proposal)
    old, new = world.fake.series()
    assert old["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20261108T105959Z"], "the past part ends the day before"
    assert new["start"]["dateTime"] == "2026-11-09T08:30:00" and new["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"]
    assert times_on(world, date(2026, 11, 6)) == [(time(9, 0), time(17, 30))]
    assert times_on(world, date(2026, 11, 9)) == [(time(8, 30), time(17, 0))], "the same length from the new start"
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    (only,) = world.fake.series()
    assert only["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"] and times_on(world, date(2026, 11, 9)) == [(time(9, 0), time(17, 30))]


def test_a_change_to_every_time_moves_the_whole_series(world):
    add_work(world)
    proposal = card(world, plain.move_card, {"search": "work", "time": "8:30", "ends_at": "5", "scope": "all"}, "work is 8:30 to 5 every day")
    assert proposal.lines[1].startswith("Every time · ") and proposal.data["op"] == "all"
    save(world, plain.move_save, plain.move_check, proposal)
    assert times_on(world, DAY) == [(time(8, 30), time(17, 0))] and times_on(world, date(2026, 11, 20)) == [(time(8, 30), time(17, 0))]
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    assert times_on(world, DAY) == [(time(9, 0), time(17, 30))]


# --- stop, and delete completely ------------------------------------------------------------------------------------------
def test_cancel_work_from_a_day_ends_the_series_there_keeping_the_past(world):
    add_work(world)
    clock.advance_to(days.at(date(2026, 11, 11), time(7, 0)))
    proposal = card(world, plain.cancel_card, {"search": "work", "day": "1 December", "scope": "following"}, "cancel work from December")
    assert proposal.lines[1] == "Ends · the last one Mon 30 Nov" and proposal.data["op"] == "stop"
    assert save(world, plain.cancel_save, plain.cancel_check, proposal) == "🗓️ Ended · **Work** · the last one Mon 30 Nov; past ones kept"
    assert world.fake.series()[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20261130T105959Z"]
    assert times_on(world, date(2026, 11, 30)) and not times_on(world, date(2026, 12, 1))
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    assert times_on(world, date(2026, 12, 1)) == [(time(9, 0), time(17, 30))]


def test_stopping_before_its_first_one_says_delete_instead(world):
    add_work(world)
    with pytest.raises(UserError, match="before its first one: say delete work"):
        card(world, plain.cancel_card, {"search": "work", "scope": "all"}, "stop work")


def test_delete_completely_is_a_red_card_and_undo_makes_it_again(world):
    add_work(world)
    proposal = card(world, plain.delete_card, {"search": "work"}, "delete work completely")
    assert proposal.destructive and proposal.kind == "remove" and proposal.lines == ("**Work** · weekdays", "-# every time, past ones too")
    assert save(world, plain.delete_save, plain.delete_check, proposal) == "🗑️ 🗓️ **Work** · deleted, every time"
    assert world.fake.series() == [] and times_on(world, DAY + timedelta(days=1)) == []
    run(plain.undo(world.request("undo that"), {}, frozenset()))
    (again,) = world.fake.series()
    assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"] and times_on(world, DAY + timedelta(days=1)) == [(time(9, 0), time(17, 30))]


# --- reading: daylight saving, a series ended in the past -----------------------------------------------------------------
def test_through_daylight_saving_9_am_stays_9_am(world):
    clock.advance_to(days.at(date(2027, 3, 29), time(7, 0)))  # NZ daylight time ends on Sun 4 Apr 2027
    add_work(world)
    before, after = rules.on_day(kept(world), date(2027, 4, 2)), rules.on_day(kept(world), date(2027, 4, 5))
    assert [days.local_time(each.start) for each in before + after] == [time(9, 0), time(9, 0)]
    assert before[0].start.astimezone(timezone.utc).hour == 20 and after[0].start.astimezone(timezone.utc).hour == 21, "the UTC moment moves, the local time does not"


def test_a_series_ended_in_the_past_shows_nothing_and_cannot_be_changed(world):
    world.fake.calendars[BOT_ID]["old"] = {"id": "old", "status": "confirmed", "summary": "Work",
                                          "start": {"dateTime": "2019-10-21T09:00:00", "timeZone": "Pacific/Auckland"},
                                          "end": {"dateTime": "2019-10-21T17:30:00", "timeZone": "Pacific/Auckland"},
                                          "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20220805T115959Z"]}
    run(series.refresh(world.owner.id, source.bot()))
    assert [each for each in kept(world) if each.title == "Work"] == []
    with pytest.raises(UserError, match="Nothing is on your calendar|Nothing like"):
        card(world, plain.cancel_card, {"search": "work", "scope": "one"}, "cancel work")


def test_a_series_read_back_is_its_happenings_each_knowing_its_series(world):
    add_work(world)
    week = [each for each in kept(world) if each.title == "Work" and days.day_of(each.start) <= DAY + timedelta(days=6)]
    assert len(week) == 5 and {each.series for each in week} == {world.fake.series()[0]["id"]} and all(each.mine for each in week)


# --- the engine's own sums -------------------------------------------------------------------------------------------------
def test_the_repeat_engine_writes_and_reads_its_rrules():
    biweekly = recurrence.Repeat(recurrence.DAYS, date(2026, 11, 2), (0, 3), every_weeks=2)
    assert recurrence.rrule(biweekly) == "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH"
    assert recurrence.from_rrule(recurrence.rrule(biweekly), date(2026, 11, 2)) == biweekly
    last = recurrence.Repeat(recurrence.MONTHLY, date(2026, 11, 30), month_day=31)
    assert recurrence.rrule(last) == "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1", "a date a month lacks is its last day"
    assert recurrence.dates(recurrence.Repeat(recurrence.DAYS, date(2026, 11, 2), (0,), times=3), date(2026, 11, 10), 5) == [date(2026, 11, 16)], "counted from the first"
    assert recurrence.full_text(recurrence.Repeat(recurrence.WEEKDAYS, until=date(2022, 8, 5)), date(2026, 1, 1)) == "weekdays, until Fri 5 Aug"


def test_a_start_and_an_end_said_together_are_read_together():
    assert rules.read_span("9", "5:30") == (time(9, 0), time(17, 30))
    assert rules.read_span("10", "2") == (time(10, 0), time(14, 0))
    assert rules.read_span("8:30pm", "11pm") == (time(20, 30), time(23, 0))


def test_a_range_said_with_one_am_or_pm_keeps_its_start(world):
    """Found 16 Oct on live: "… 7 to 10pm" had its start put back to 10 pm by the stated-time check."""
    from core import actions

    add = next(each for each in plain.writing_actions() if each.name == "calendar_add")
    data = {"title": "dinner", "day": "Friday", "time": "7:00 pm", "length": 180}
    assert actions.restated(add, data, "dinner Friday 7 to 10pm") == (data, [])
    assert actions.restated(add, {"title": "dinner", "time": "7:00 pm", "ends_at": "10:00 pm"}, "dinner Friday 7 to 10pm")[1] == []

