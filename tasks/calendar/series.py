from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from core import clock, database, design, recurrence, timeinput
from core import day as days
from core.actions import Choice, Proposal, Question, Request
from core.errors import UserError
from tasks.calendar import rules, source, store
from tasks.calendar.google import local_time
from tasks.calendar.rules import ICON

# ---------------------------------------------------------------------------
# Repeating events in the Bot calendar (the only calendar ever written to).
# A series is made in words through the shared repeat engine
# (core/recurrence.py) and kept by Google as a real recurrence (an RRULE),
# so it behaves as any repeating event there; it is read back a happening at
# a time (singleEvents), with its end and its exceptions as Google keeps them.
#
#   "work every weekday 9 to 5:30"            a new series, on a card
#   "cancel work next Tuesday"                that one happening, cancelled
#   "work next Friday is 10 to 2"             that one happening, moved
#   "work starts at 8:30 from next week"      this and following: split in two,
#                                             the past unchanged
#   "work is 8:30 to 5 every day"             the whole series
#   "stop work", "cancel work from November"  the series ends there (UNTIL),
#                                             past happenings kept
#   "delete work"                             the whole series, on a red card
#
# One that could mean one day or the series asks: just that day, or from then
# on. Every change is a card first, and "undo that" after (store.SERIES_*).
# The event is found by code from the words as said; its name never goes to
# Claude.
# ---------------------------------------------------------------------------
ONE, FOLLOWING, ALL = "one", "following", "all"
SCOPES = (ONE, FOLLOWING, ALL)
SHOWN_NEXT = 3  # dates on a new series' card


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _short(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _times(start: datetime, end: datetime) -> str:
    return f"`{timeinput.format_moment(start)}` to `{timeinput.format_moment(end)}`"


def _end_of(day: date) -> datetime:
    """The moment a local day is over, in UTC: an RRULE's UNTIL."""
    return (days.start_of(day + timedelta(days=1)) - timedelta(seconds=1)).astimezone(timezone.utc)


def _api_moment(value: dict) -> datetime:
    """A start or an end as the API keeps it, as a UTC moment (a local time is in its zone)."""
    from zoneinfo import ZoneInfo

    found = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    if found.tzinfo is None:
        found = found.replace(tzinfo=ZoneInfo(value.get("timeZone") or str(rules.TIMEZONE)))
    return found.astimezone(timezone.utc)


def _rule_of(master: dict) -> str:
    return next((each for each in master.get("recurrence") or [] if each.startswith("RRULE:")), "")


def repeat_of(master: dict) -> recurrence.Repeat:
    """A series' repeat, from its RRULE: its first day, and its end day in local time."""
    line = _rule_of(master)
    first = days.day_of(_api_moment(master["start"]))
    until = None
    for part in line.removeprefix("RRULE:").split(";"):
        if part.startswith("UNTIL="):
            value = part[6:]
            moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if "T" in value else datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
            until = days.day_of(moment)
    return recurrence.from_rrule(line, first, until)


def ended(repeat: recurrence.Repeat, last: date | None) -> recurrence.Repeat:
    """The same repeat, ending on `last` (its number of times dropped: the end is a day now)."""
    return replace(repeat, until=last, times=None)


def rule_line(repeat: recurrence.Repeat) -> str:
    return recurrence.rrule(repeat, _end_of(repeat.until) if repeat.until is not None else None)


def _end_words(repeat: recurrence.Repeat) -> str:
    if repeat.times is not None:
        return f"{repeat.times} time{'' if repeat.times == 1 else 's'}"
    if repeat.until is not None:
        return f"until {_short(repeat.until)}"
    return "no end"


def _pattern(repeat: recurrence.Repeat, today: date) -> str:
    """How often, without its end: "weekdays", "every 2 weeks on Mon and Thu"."""
    return recurrence.full_text(ended(repeat, None), today)


# --- a new series -----------------------------------------------------------------------------------------------
def said_repeat(data: dict, first: date, until: date | None) -> recurrence.Repeat | None:
    """The repeat said with a new event, starting on `first`; None for a one-off."""
    if not (data.get("repeat") and data.get("repeat") != recurrence.ONCE) and not data.get("weekdays"):
        return None
    made = recurrence.from_fields(data, None, first)
    if made.kind == recurrence.ONCE:
        return None
    return recurrence.with_end(made, data, first, until)


def add_card(title: str, repeat: recurrence.Repeat, at: time, minutes: int, today: date, now: datetime, warnings: list[str]) -> Proposal:
    """The card for a new series: the pattern and the time, the start date, the next three dates, and its end."""
    coming = [day for day in recurrence.dates(repeat, repeat.first, SHOWN_NEXT + 1) if days.at(day, at) > now][:SHOWN_NEXT]
    if not coming:
        raise UserError(f"{ICON} That never comes round: every one of them has gone by.")
    first = coming[0]
    start = days.at(first, at)
    end = start + timedelta(minutes=minutes)
    started = replace(repeat, first=first)
    if repeat.times is not None and repeat.first is not None and first > repeat.first:
        # One gone by already today is not made: the count goes on from the first to come
        started = replace(started, times=max(1, repeat.times - len([day for day in recurrence.dates(repeat, repeat.first, repeat.times) if day < first])))
    return Proposal(
        lines=(
            f"**{title}**",
            f"{_upper(_pattern(started, today))} · {_times(start, end)}",
            f"From {_short(first)} · {_end_words(started)}",
            design.small("Next: " + ", ".join(_short(day) for day in coming)),
            design.small("on the Bot calendar"),
        ),
        data={"title": title, "start": start.isoformat(), "end": end.isoformat(), "rrule": rule_line(started), "pattern": _pattern(started, today)},
        warnings=tuple(warnings), kind="new",
    )


async def add_save(request: Request, data: dict, writer) -> str:
    start, end = datetime.fromisoformat(data["start"]), datetime.fromisoformat(data["end"])
    made = await writer.insert({"summary": data["title"], "start": local_time(start), "end": local_time(end), "recurrence": [data["rrule"]]})
    await database.run(store.db_change, request.user.id, store.ADDED, made["id"], data["title"], (None, None), (start, end), clock.now())
    await refresh(request.user.id, writer)
    return f"{ICON} Added · **{data['title']}** · {data['pattern']} · {_times(start, end)}, from {_short(days.day_of(start))}"


# --- which happening, and what is meant ---------------------------------------------------------------------------
def _ask(data: dict, day: date, today: date) -> Question:
    said = "today" if day == today else _short(day)
    return Question(
        f"Just {said}, or from then on?",
        (Choice(f"Just {said}", {**data, "scope": ONE}, ("scope",)), Choice("From then on", {**data, "scope": FOLLOWING}, ("scope",))),
    )


def scope_of(data: dict) -> str:
    return data.get("scope") if data.get("scope") in SCOPES else ""


def cut_day(data: dict, event: rules.Event) -> date:
    """Where a change from a day on starts: the day said ("from 1 November"), else the happening's own."""
    from tasks.calendar import plain

    return plain.read_day(data["day"], days.today()) if data.get("day") else days.day_of(event.start)


def _new_times(data: dict, event: rules.Event, day: date) -> tuple[datetime, datetime]:
    """The happening's new start and end on `day`: the time said (or its own), and the end said, the
    length said, or its own length."""
    from tasks.calendar import plain

    own = days.local_time(event.start)
    if data.get("time") and data.get("ends_at"):
        at = rules.read_span(str(data["time"]), str(data["ends_at"]))[0]
    elif data.get("time"):
        # "starts at 8:30" for an event at 9:00 am: of the two readings, the one nearer its own time
        readings = rules._readings(str(data["time"]))
        at = min(readings, key=lambda each: abs((each.hour * 60 + each.minute) - (own.hour * 60 + own.minute)))
    else:
        at = own
    start = days.at(day, at)
    if data.get("ends_at"):
        end = days.at(day, rules.read_span(timeinput.format_moment(start), str(data["ends_at"]))[1])
        if end <= start:
            end += timedelta(hours=12) if end + timedelta(hours=12) > start else timedelta(days=1)
    else:
        own = int((event.end - event.start).total_seconds() // 60) or plain.DEFAULT_LENGTH
        end = start + timedelta(minutes=plain._length(data.get("length"), own))
    return start, end


async def move_card(request: Request, data: dict, event: rules.Event, writer) -> Proposal:
    """A new time for a repeating event: that one happening, from it on (split), or every time."""
    today = days.today()
    day = days.day_of(event.start)
    scope = scope_of(data)
    start, end = _new_times(data, event, day)
    if not scope:
        return Proposal(lines=(f"**{event.title}**", design.change(rules.span_text(event.start, event.end, today), rules.span_text(start, end, today))), data=data, kind="change", question=_ask(data, day, today))
    if scope == ONE:
        return Proposal(
            lines=(f"**{event.title}**", design.change(rules.span_text(event.start, event.end, today), rules.span_text(start, end, today)), design.small("just this day: the rest as they are")),
            data={"op": ONE, "ref": event.ref, "title": event.title, "was": [event.start.isoformat(), event.end.isoformat()], "start": start.isoformat(), "end": end.isoformat()}, kind="change",
        )
    master = await writer.raw(event.series)
    if master is None:
        raise UserError(f"{ICON} **{event.title}** isn't in the Bot calendar any more.")
    repeat = repeat_of(master)
    first_start = _api_moment(master["start"])
    if scope == FOLLOWING:
        cut = cut_day(data, event)
        coming = recurrence.dates(repeat, max(cut, repeat.first), 1)
        if not coming:
            raise UserError(f"{ICON} **{event.title}** has none from {_short(cut)}.")
        day = coming[0]
        start, end = _new_times(data, event, day)
    whole = scope == ALL or day <= days.day_of(first_start)
    was, now_times = _times(event.start, event.end), _times(start, end)
    common = {"series": event.series, "title": event.title, "before": {"start": master["start"], "end": master["end"], "recurrence": master.get("recurrence") or []}}
    if whole:
        new_start = days.at(days.day_of(first_start), days.local_time(start))
        return Proposal(
            lines=(f"**{event.title}**", f"Every time · {design.change(was, now_times)}", design.small(_pattern(repeat, today))),
            data={**common, "op": ALL, "start": new_start.isoformat(), "end": (new_start + (end - start)).isoformat()}, kind="change",
        )
    return Proposal(
        lines=(f"**{event.title}**", f"From {_short(day)} · {design.change(was, now_times)}", design.small("before then: as it was")),
        data={**common, "op": FOLLOWING, "from": day.isoformat(), "start": start.isoformat(), "end": end.isoformat()}, kind="change",
    )


def _split(repeat: recurrence.Repeat, day: date) -> tuple[recurrence.Repeat, recurrence.Repeat]:
    """A series cut before `day`: the part before (ending the day before) and the part from `day`
    (its end or what is left of its number of times)."""
    before = ended(repeat, day - timedelta(days=1))
    left = None
    if repeat.times is not None:
        gone = len([each for each in recurrence.dates(repeat, repeat.first, repeat.times) if each < day])
        left = max(1, repeat.times - gone)
    after = replace(repeat, first=day, until=repeat.until if left is None else None, times=left)
    return before, after


def last_before(repeat: recurrence.Repeat, since: date) -> date | None:
    """The last day it came round on before `since` (with its end and its number of times), or None."""
    if repeat.first is None or since <= repeat.first:
        return None
    if repeat.times is not None:
        kept = [each for each in recurrence.dates(repeat, repeat.first, repeat.times) if each < since]
        return kept[-1] if kept else None
    day = since - timedelta(days=1)
    while day >= repeat.first and (since - day).days <= recurrence.LOOK_AHEAD:
        if recurrence.on_day(repeat, day):
            return day
        day -= timedelta(days=1)
    return None


async def series_save(request: Request, data: dict, writer) -> str:
    """Save a change to a series (op all, following or stop) and keep what undo needs."""
    master = await writer.raw(data["series"])
    if master is None:
        raise UserError(f"{ICON} **{data['title']}** isn't in the Bot calendar any more.")
    repeat = repeat_of(master)
    made = ""
    if data["op"] == ALL:
        start, end = datetime.fromisoformat(data["start"]), datetime.fromisoformat(data["end"])
        await writer.patch(data["series"], {"start": local_time(start), "end": local_time(end)})
        said = f"{ICON} Changed · **{data['title']}** · every time {_times(start, end)}"
    elif data["op"] == FOLLOWING:
        day = date.fromisoformat(data["from"])
        before, after = _split(repeat, day)
        start, end = datetime.fromisoformat(data["start"]), datetime.fromisoformat(data["end"])
        await writer.patch(data["series"], {"recurrence": [rule_line(before)]})
        new = await writer.insert({"summary": data["title"], "start": local_time(start), "end": local_time(end), "recurrence": [rule_line(after)]})
        made = new["id"]
        said = f"{ICON} Changed · **{data['title']}** · from {_short(day)} {_times(start, end)}; before then as it was"
    else:  # stop: the series ends the day before
        last = date.fromisoformat(data["last"])
        await writer.patch(data["series"], {"recurrence": [rule_line(ended(repeat, last))]})
        said = f"{ICON} Ended · **{data['title']}** · the last one {_short(last)}; past ones kept"
    await database.run(store.db_change, request.user.id, store.SERIES_CHANGED, data["series"], data["title"], (None, None), (None, None), clock.now(), {"before": data["before"], "made": made})
    await refresh(request.user.id, writer)
    return said


async def series_check(request: Request, data: dict, writer) -> str:
    master = await writer.raw(data["series"])
    if master is None:
        return "the series is not in the Bot calendar"
    if data["op"] == ALL:
        return "" if _api_moment(master["start"]) == datetime.fromisoformat(data["start"]) else "the Bot calendar still has the old time"
    return "" if master.get("recurrence") != data["before"]["recurrence"] else "the series still has its old end"


# --- cancel and stop ----------------------------------------------------------------------------------------------
async def cancel_card(request: Request, data: dict, event: rules.Event, writer) -> Proposal:
    """ "cancel work next Tuesday": that happening; "stop work", "cancel work from November": the series ends."""
    today = days.today()
    day = days.day_of(event.start)
    scope = scope_of(data)
    if not scope:
        return Proposal(lines=(f"**{event.title}** · {rules.span_text(event.start, event.end, today)}",), data=data, kind="change", question=_ask(data, day, today))
    if scope == ONE:
        return Proposal(
            lines=(f"**{event.title}** · {rules.span_text(event.start, event.end, today)} · cancelled", design.small("just this day: the rest as they are")),
            data={"op": "cancel_one", "ref": event.ref, "title": event.title, "was": [event.start.isoformat(), event.end.isoformat()]}, kind="change",
        )
    master = await writer.raw(event.series)
    if master is None:
        raise UserError(f"{ICON} **{event.title}** isn't in the Bot calendar any more.")
    repeat = repeat_of(master)
    since = cut_day(data, event) if scope == FOLLOWING else today
    last = last_before(repeat, since)
    if last is None:
        raise UserError(f"{ICON} That would end **{event.title}** before its first one: say delete {event.title.lower()} to remove it.")
    return Proposal(
        lines=(f"**{event.title}** · {_pattern(repeat, today)}", f"Ends · the last one {_short(last)}", design.small(f"none from {_short(since)}; past ones kept")),
        data={"op": "stop", "series": event.series, "title": event.title, "last": last.isoformat(), "before": {"start": master["start"], "end": master["end"], "recurrence": master.get("recurrence") or []}},
        kind="change",
    )


async def cancel_save(request: Request, data: dict, writer) -> str:
    if data["op"] == "cancel_one":
        await writer.patch(data["ref"], {"status": "cancelled"})
        await database.run(store.db_change, request.user.id, store.CANCELLED_ONE, data["ref"], data["title"], tuple(datetime.fromisoformat(each) for each in data["was"]), (None, None), clock.now())
        await refresh(request.user.id, writer)
        return f"{ICON} Cancelled · **{data['title']}** · {_short(days.day_of(datetime.fromisoformat(data['was'][0])))}; the rest as they are"
    return await series_save(request, data, writer)


async def cancel_check(request: Request, data: dict, writer) -> str:
    if data["op"] == "cancel_one":
        found = await writer.raw(data["ref"])
        return "" if found is None or found.get("status") == "cancelled" else "that day is still on"
    return await series_check(request, data, writer)


# --- delete the whole series ------------------------------------------------------------------------------------------
async def delete_card(event: rules.Event, writer) -> Proposal:
    master = await writer.raw(event.series)
    if master is None:
        raise UserError(f"{ICON} **{event.title}** isn't in the Bot calendar any more.")
    today = days.today()
    return Proposal(
        lines=(f"**{event.title}** · {_pattern(repeat_of(master), today)}", design.small("every time, past ones too")),
        data={"op": "series_delete", "series": event.series, "title": event.title},
        kind="remove", destructive=True, confirm_label="Delete",
    )


_KEPT = ("summary", "start", "end", "recurrence", "description", "location")


async def delete_save(request: Request, data: dict, writer) -> str:
    master = await writer.raw(data["series"])
    if master is None:
        raise UserError(f"{ICON} **{data['title']}** isn't in the Bot calendar any more.")
    await writer.delete(data["series"])
    body = {key: master[key] for key in _KEPT if key in master}
    await database.run(store.db_change, request.user.id, store.SERIES_DELETED, data["series"], data["title"], (None, None), (None, None), clock.now(), {"body": body})
    await refresh(request.user.id, writer)
    return f"🗑️ {ICON} **{data['title']}** · deleted, every time"


async def delete_check(request: Request, data: dict, writer) -> str:
    found = await writer.raw(data["series"])
    return "" if found is None or found.get("status") == "cancelled" else "it is still in the Bot calendar"


# --- undo, and the copy ---------------------------------------------------------------------------------------------
async def undo(kind: str, ref: str, title: str, detail: dict, writer) -> str:
    if kind == store.CANCELLED_ONE:
        await writer.patch(ref, {"status": "confirmed"})
        return f"↩️ {ICON} **{title}** · on again that day"
    if kind == store.SERIES_CHANGED:
        before = detail["before"]
        await writer.patch(ref, {"start": before["start"], "end": before["end"], "recurrence": before["recurrence"]})
        if detail.get("made"):
            await writer.delete(detail["made"])
        return f"↩️ {ICON} **{title}** · as it was"
    await writer.insert(detail["body"])
    return f"↩️ {ICON} **{title}** · back on the calendar, every time"


async def refresh(user_id: int, writer) -> None:
    """The Bot calendar's part of the copy read again at once: a series is many happenings."""
    today = days.today()
    events = await writer.events(today - timedelta(days=rules.BEHIND_DAYS), today + timedelta(days=rules.AHEAD_DAYS))
    await database.run(store.db_keep_from, user_id, source.BOT, events)
