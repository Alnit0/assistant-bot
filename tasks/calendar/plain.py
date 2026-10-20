import logging
from datetime import date, datetime, timedelta

from core import clock, config, database, design, recurrence, timeinput
from core import day as days
from core.actions import BOOLEAN, TIME, Choice, Field, Proposal, Question, Request, Shown, State
from core.errors import UserError
from tasks.calendar import rules, series, source, store
from tasks.calendar.rules import ICON, NEXT_WEEK, SPANS, WEEK

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The calendar in plain words: questions only (it is read only). Extraction
# is handed the day and the search words as they were said, and nothing of
# the calendar: no event's name or description ever goes to Claude, in the
# state, the names or anywhere else. Python reads the day, finds the event
# by core/names.py and writes the answer from a template (rules.py), in
# place, where it was asked.
#
#   "what's on tomorrow?", "what's on Friday?"   a day
#   "what's on this week?", "next week"          a week, each day by the list rule
#   "when is the dentist?"                        the next one whose name fits
#   "am I free at 3 tomorrow?"                    what is on then, or free
# ---------------------------------------------------------------------------
ONLY_FOR = (
    "Events in the user's own calendar, to read: what is on a day, a week, a month, a year or a range of days (\"what's on tomorrow?\", \"what's on "
    "Friday?\", \"what's on this week?\", \"what's on in November?\", \"what's on from Monday to Friday?\", \"my calendar\"), when an event is, or whether it is on (\"when is the dentist?\", \"is the gym on tonight?\"), and whether "
    "they are free at a time (\"am I free at 3 tomorrow?\"). Events only. It adds and changes nothing: a new event "
    "said with a time (\"dentist Friday 3pm\") is a reminder. The rest of today across everything (\"what's on "
    "tonight?\", \"what have I got this afternoon?\") is the briefing. Not pills, not reminders "
    "the user set, not to-dos, not personal routines, and not when the bot's own jobs run (that is the schedule task)."
)
EXAMPLES = ("what's on tomorrow?", "when is the dentist?", "am I free at 3 tomorrow?")

_DAY = "The day asked about, exactly as the user said it (\"today\", \"tomorrow\", \"Friday\", \"16 Oct\"). Never work out a date. Leave out for today."


def read_day(said, today):
    """A day as said, read by core/timeinput.py; none said is today."""
    if not said or str(said).strip().lower() == "today":
        return today
    try:
        return timeinput.parse_date(str(said), today)
    except Exception:
        raise UserError(f"“{said}” is not a day I can read.")


async def show(request: Request, data: dict, guessed: frozenset):
    """What is on a day, or this week, or next week. With the week view on, in its layout: every task's day,
    not only the calendar's (core/weekview.py), answered where it was asked."""
    today = days.today()
    span = data.get("span") if data.get("span") in SPANS else rules.DAY_SPAN
    asked = rules.span_of(span, today, read_day, data.get("day"), data.get("until"), data.get("month"), data.get("year"))
    in_copy = _in_copy(asked, today)
    # The week view's layout where it was before: a day, this week and next week (it reads the copy)
    plain_week = span in (WEEK, NEXT_WEEK) and not data.get("until") and not (span == WEEK and data.get("day"))
    plain_day = span == rules.DAY_SPAN and not data.get("until")
    if config.WEEK_VIEW and in_copy and (plain_week or plain_day):
        return await _week_view(request, span, data, today)
    events, missed = (await store.events(request.user.id), "") if in_copy else await _read_span(asked)
    said = rules.span_answer(events, asked, today)
    return said + (f"\n{design.small(missed)}" if missed else "")


def _in_copy(asked: rules.Span, today) -> bool:
    """Whether the copy kept every 15 minutes covers the span (yesterday to AHEAD_DAYS ahead)."""
    return asked.first >= today - timedelta(days=rules.BEHIND_DAYS) and asked.last <= today + timedelta(days=rules.AHEAD_DAYS)


async def _read_span(asked: rules.Span) -> tuple[list, str]:
    """Every calendar read for a span the copy does not reach (a month or a year ahead, the past), as
    one; a calendar that can't be read just now is said in a small line, and all of them failing is
    said instead of an answer."""
    found, failed = [], 0
    every = source.sources()
    for each in every:
        try:
            found += await each.events(asked.first, asked.last)
        except Exception as error:
            failed += 1
            log.warning("Calendar: a span not read from %s (%s)", each.origin, type(error).__name__)
    if not every or failed == len(every):
        raise UserError(f"{ICON} I couldn't read your calendar for that just now. Try again in a minute.")
    return rules.merged(found), ("⚠️ One of your calendars couldn't be read just now: this is the rest." if failed else "")


async def _week_view(request: Request, span: str, data: dict, today) -> Shown:
    from core import cards, weekview
    from core.cards import Card

    if span in (WEEK, NEXT_WEEK):
        first = today if span == WEEK else today + timedelta(days=7)
        found = await weekview.gather(request.user.id, weekview.week_of(first))
        title = weekview.THIS_WEEK if span == WEEK else weekview.NEXT_WEEK
        layout = weekview.this_week(found, today) if span == WEEK else weekview.next_week(found, today)
        card = Card(weekview.text(found, today, title), (), layout)
    else:
        (found,) = await weekview.gather(request.user.id, [read_day(data.get("day"), today)])
        card = Card(weekview.short_line(found, today), (), weekview.one_day(found, today))
    message_id = await cards.send(request.channel_id, card)
    return Shown(card.text if message_id is not None else "not shown")


async def when(request: Request, data: dict, guessed: frozenset) -> str:
    """When the next event whose name fits the words is."""
    words = str(data.get("search") or "").strip()
    if not words:
        raise UserError("When is what?")
    return rules.when_answer(rules.next_matching(await store.events(request.user.id), words, clock.now()), days.today())


async def free(request: Request, data: dict, guessed: frozenset) -> str:
    """Whether anything is on at a time on a day."""
    today = days.today()
    if not data.get("time"):
        raise UserError("Free at what time?")
    moment = days.at(read_day(data.get("day"), today), rules.read_time(str(data["time"])))
    return rules.free_answer(await store.events(request.user.id), moment, today)


async def state(request: Request) -> State:
    """What extraction is told: how many events are kept, never what they are called."""
    found = rules.on_day(await store.events(request.user.id), days.today())
    return State("The user's calendar (events are found by code: their names are never given here)", (f"today: {rules.count_text(len(found))}",), "nothing")


def actions() -> list:
    from core.actions import SEE, Action

    return [*reading_actions(), *(writing_actions() if writing() else [])]


def reading_actions() -> list:
    from core.actions import SEE, Action

    return [
        Action(
            "calendar_show",
            "What is on the user's calendar over any span (\"what's on tomorrow?\" -> day tomorrow; \"what's on 21 November?\" -> day 21 November; "
            "\"what's on this week?\" -> span week; \"next week\" -> span next_week; \"the week of 28 November\" -> span week, day 28 November; "
            "\"what's on in November?\" -> span month, month November; \"next month\" -> span next_month; \"December\" -> span month, month December; "
            "\"what's on in 2027?\" -> span year, year 2027; \"next year\" -> span next_year; \"from Monday to Friday\" -> day Monday, until Friday; "
            "\"21 to 25 November\" -> day 21 November, until 25 November; \"my calendar\" -> nothing). "
            "A question only: a new event said with a title and all day (\"hen do Saturday, all day\") is adding, never this.",
            (
                Field("day", _DAY + " For a week: a day in it (\"the week of 28 November\" -> 28 November). For a range: its first day."),
                Field("until", "For a range, its last day exactly as said (\"from Monday to Friday\" -> Friday; \"21 to 25 November\" -> 25 November). Never work out a date. Leave out otherwise."),
                Field("month", "For span month, the month as said (\"November\", \"December 2027\"). Leave out for this month."),
                Field("year", "For span year, the year as said (\"2027\"). Leave out for this year."),
                Field("span", "day (one day), week (the rest of this week, or the week a day said is in), next_week (Monday to Sunday next week), "
                      "month (a month: the one said, or this one), next_month, year (a year: the one said, or this one), next_year. Leave out for one day or a range.", choices=SPANS),
            ),
            needs_card=False, run=show, purpose=SEE, say=("what's on tomorrow?", "what's on this week?"),
        ),
        Action(
            "calendar_when",
            "When an event in the user's calendar is (\"when is the dentist?\" -> search dentist; \"when's my next team sync?\" -> search team sync).",
            (Field("search", "The words naming the event, exactly as the user said them, without \"my\", \"the\" or \"next\". Never complete or correct them.", required=True),),
            needs_card=False, run=when, purpose=SEE, say=("when is the dentist?",),
        ),
        Action(
            "calendar_free",
            "Whether the user is free at a time (\"am I free at 3 tomorrow?\" -> day tomorrow, time 3; \"am I busy at 10:30?\" -> time 10:30).",
            (Field("day", _DAY), Field("time", "The time asked about, as the user said it.", TIME, required=True)),
            needs_card=False, run=free, purpose=SEE, say=("am I free at 3 tomorrow?",),
        ),
    ]


# --- writing, in the Bot calendar only (CALENDAR_WRITE) ------------------------------------------------------------
# Adding, moving and deleting events, each on a card first; "undo that" after each. Only the Bot
# calendar is ever written to (google.GoogleSource checks it on every write). An event is found by
# code from the words as said (core/names.py); its name never goes to Claude. A new event's title is
# the user's own words (rules.title_from). One on another calendar is never changed: it is said so.
DEFAULT_LENGTH = 60  # minutes, when no length is said
LONGEST = 24 * 60


def writing() -> bool:
    return bool(config.CALENDAR_WRITE) and source.bot() is not None


def _writer():
    found = source.bot()
    if not config.CALENDAR_WRITE or found is None or not found.can_write:
        raise UserError(f"{ICON} Adding to the calendar is off.")
    return found


def _length(said, default: int) -> int:
    try:
        minutes = int(said) if said not in (None, "") else default
    except (TypeError, ValueError):
        minutes = default
    return max(5, min(LONGEST, minutes))


def _changed(user_id: int) -> None:
    from core import attention, summaries

    summaries.changed(rules.TASK, user_id)
    attention.changed()


def _clash_lines(events, start, end, today, leaving: str = "") -> tuple[str, ...]:
    return tuple(f"Clashes with **{each.title}** · {rules.when_text(each, days.day_of(start))}" for each in rules.clashes(events, start, end, leaving))


def _iso(moment):
    return moment.isoformat() if moment else None


def _moment(text):
    return datetime.fromisoformat(text) if text else None


async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "dentist Friday 3pm for an hour": a card with the title, the day, the time and the length,
    and what it clashes with in every calendar. "All day event 21 and 22 November, the hen do": an
    all-day one. With no time said, the card asks for one, with All day a button; a typed answer
    ("All day", "3pm") is read against the card, what it asked kept (`request.previous`)."""
    _writer()
    previous = request.previous or {}
    title = rules.title_from(data.get("title"), request.text) or rules.title_from(data.get("title") or previous.get("title"), str(previous.get("title") or ""))
    if not title:
        raise UserError(f"{ICON} What is it called? Say it with its name, like “dentist Friday 3pm”.")
    said = {"title": title, "day": data.get("day") or previous.get("day") or "", "last_day": data.get("last_day") or previous.get("last_day") or ""}
    today = days.today()
    if data.get("all_day"):
        return _all_day_card(said, data, today)
    if not data.get("time"):
        first, last = _days_of(said, today)
        line = rules.day_name(first, today) + (f" to {rules.day_name(last, today)}" if last != first else "")
        question = Question("At what time?", (Choice("All day", {**said, "all_day": True}, ("time", "all_day")),))
        return Proposal(lines=(f"**{title}**", f"{line} · ❔", design.small("on the Bot calendar")), data={**said, "time": ""}, kind="new", question=question)
    day = read_day(said["day"], today)
    at = rules.read_span(str(data["time"]), str(data["ends_at"]))[0] if data.get("ends_at") else rules.read_time(str(data["time"]))
    start = days.at(day, at)
    end = _ends(data, start, DEFAULT_LENGTH)
    warnings = list(_clash_lines(await store.events(request.user.id), start, end, today))
    repeat = series.said_repeat(data, day, read_day(data["until"], today) if data.get("until") else None)
    if repeat is not None:
        return series.add_card(title, repeat, at, int((end - start).total_seconds() // 60), today, clock.now(), [])
    if start < clock.now():
        warnings.insert(0, "That time has gone by")
    return Proposal(
        lines=(f"**{title}**", rules.span_text(start, end, today), design.small("on the Bot calendar")),
        data={"title": title, "start": _iso(start), "end": _iso(end)}, warnings=tuple(warnings), kind="new",
    )


LONGEST_DAYS = 31  # an all-day event's days at most


def _days_of(said: dict, today):
    """The first and last day of an event as said ("21 and 22 November": day 21 November, last_day 22
    November); one day when no last day is said."""
    first = read_day(said.get("day"), today)
    last = read_day(said["last_day"], first) if said.get("last_day") else first
    if last < first:
        raise UserError(f"{ICON} It ends before it starts: {rules.day_name(last, today)} is before {rules.day_name(first, today)}.")
    if (last - first).days >= LONGEST_DAYS:
        raise UserError(f"{ICON} That is more than {LONGEST_DAYS} days: say its first and last day.")
    return first, last


def _all_day_card(said: dict, data: dict, today) -> Proposal:
    """An all-day event on the Bot calendar, over one day or several. Never a to-do or a reminder:
    "event" or "all day" was said."""
    if data.get("repeat"):
        raise UserError(f"{ICON} I can't add a repeating all-day event yet: say it with a time, or one day at a time.")
    first, last = _days_of(said, today)
    warnings = ("That day has gone by",) if last < today else ()
    return Proposal(
        lines=(f"**{said['title']}**", rules.days_text(first, last, today), design.small("on the Bot calendar")),
        data={**said, "all_day": True, "first": first.isoformat(), "last": last.isoformat()}, warnings=warnings, kind="new",
    )


def _ends(data: dict, start: datetime, default: int) -> datetime:
    """When it ends: the end said ("9 to 5:30": the one after the start), else the length said, else `default` minutes."""
    if data.get("ends_at"):
        end = days.at(days.day_of(start), rules.read_span(timeinput.format_moment(start), str(data["ends_at"]))[1])
        if end <= start:
            end += timedelta(hours=12) if end + timedelta(hours=12) > start else timedelta(days=1)
        return end
    return start + timedelta(minutes=_length(data.get("length"), default))


async def add_save(request: Request, data: dict) -> str:
    if data.get("rrule"):
        return await series.add_save(request, data, _writer())
    if data.get("first"):
        made = await _writer().add_all_day(data["title"], date.fromisoformat(data["first"]), date.fromisoformat(data["last"]))
        when_said = rules.days_text(made.first_day, made.last_day, days.today())
    else:
        made = await _writer().add(data["title"], _moment(data["start"]), _moment(data["end"]))
        when_said = rules.span_text(made.start, made.end, days.today())
    await database.run(store.db_put, request.user.id, made)
    await database.run(store.db_change, request.user.id, store.ADDED, made.ref, made.title, (None, None), (made.start, made.end), clock.now())
    _changed(request.user.id)
    return f"{ICON} Added · **{made.title}** · {when_said}"


async def _last_ref(request: Request, kind: str) -> str:
    last = await database.run(store.db_last_change, request.user.id)
    return last[2] if last is not None and last[1] == kind else ""


async def add_check(request: Request, data: dict) -> str:
    ref = await _last_ref(request, store.ADDED)
    return "" if ref and await _writer().get(ref) is not None else "it is not in the Bot calendar"


async def _mine(request: Request, words, day_said=None) -> rules.Event:
    """The next event whose name fits the words (a repeating one: its happening on the day said, if
    one was; pass no day for a change from a day on, where the day is where the series is cut);
    one on another calendar is said, never changed. An all-day one the bot added is its own too (21 Oct);
    a repeating all-day one (a birthday's is hidden, never found) is said, never changed."""
    if not str(words or "").strip():
        raise UserError(f"{ICON} Which event?")
    events = await store.events(request.user.id)
    found = rules.next_matching(events, str(words), clock.now())
    if found.repeats and day_said:
        found = rules.matching_on(events, str(words), read_day(day_said, days.today()))
    if not found.mine:
        raise UserError(rules.NOT_MINE.format(icon=ICON, title=found.title))
    if found.all_day and found.repeats:
        raise UserError(f"{ICON} **{found.title}** repeats all day: I can't change that one in words yet.")
    return found


def _all_day_data(event: rules.Event) -> dict:
    return {"ref": event.ref, "title": event.title, "all_day": True, "was": [event.first_day.isoformat(), event.last_day.isoformat()]}


def _move_all_day_card(data: dict, event: rules.Event) -> Proposal:
    """ "move the hen do to 28 November": to a new first day, as many days as before unless a last day is said."""
    if data.get("time") or data.get("length") or data.get("ends_at"):
        raise UserError(f"{ICON} **{event.title}** is all day: say the day to move it to, like “move it to 28 November”.")
    if not data.get("day"):
        raise UserError(f"{ICON} Move it to which day?")
    today = days.today()
    first = read_day(data["day"], today)
    last = first + (event.last_day - event.first_day)
    if data.get("last_day"):
        first, last = _days_of({"day": data["day"], "last_day": data["last_day"]}, today)
    if (first, last) == (event.first_day, event.last_day):
        raise UserError(f"{ICON} **{event.title}** is on those days already.")
    return Proposal(
        lines=(f"**{event.title}**", design.change(rules.days_text(event.first_day, event.last_day, today), rules.days_text(first, last, today))),
        data={**_all_day_data(event), "first": first.isoformat(), "last": last.isoformat()},
        warnings=("That day has gone by",) if last < today else (), kind="change",
    )


def _dates(pair) -> tuple:
    return tuple(date.fromisoformat(each) for each in pair)


async def move_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "move the dentist to 4pm", "move the dentist to Monday": its day, its time or its length."""
    writer = _writer()
    event = await _mine(request, data.get("search"), None if series.scope_of(data) == series.FOLLOWING else data.get("day"))
    if event.all_day:
        return _move_all_day_card(data, event)
    if event.repeats:
        if not (data.get("time") or data.get("length") or data.get("ends_at")):
            raise UserError(f"{ICON} To what time?")
        return await series.move_card(request, data, event, writer)
    if not (data.get("day") or data.get("time") or data.get("length")):
        raise UserError(f"{ICON} Move it to when?")
    today = days.today()
    day = read_day(data.get("day"), today) if data.get("day") else days.day_of(event.start)
    at = rules.read_time(str(data["time"])) if data.get("time") else days.local_time(event.start)
    start = days.at(day, at)
    end = start + timedelta(minutes=_length(data.get("length"), int((event.end - event.start).total_seconds() // 60) or DEFAULT_LENGTH))
    if (start, end) == (event.start, event.end):
        raise UserError(f"{ICON} **{event.title}** is at that time already.")
    return Proposal(
        lines=(f"**{event.title}**", design.change(rules.span_text(event.start, event.end, today), rules.span_text(start, end, today))),
        data={"ref": event.ref, "title": event.title, "was": [_iso(event.start), _iso(event.end)], "start": _iso(start), "end": _iso(end)},
        warnings=_clash_lines(await store.events(request.user.id), start, end, today, leaving=event.ref), kind="change",
    )


async def move_save(request: Request, data: dict) -> str:
    if data.get("op") in (series.ALL, series.FOLLOWING):
        return await series.series_save(request, data, _writer())
    if data.get("all_day"):
        moved = await _writer().move_all_day(data["ref"], *_dates((data["first"], data["last"])))
        await database.run(store.db_put, request.user.id, moved)
        await database.run(store.db_change, request.user.id, store.MOVED, moved.ref, moved.title, (None, None), (None, None), clock.now(),
                           {"all_day": True, "before": data["was"], "after": [data["first"], data["last"]]})
        _changed(request.user.id)
        return f"{ICON} Moved · **{moved.title}** · {rules.days_text(moved.first_day, moved.last_day, days.today())}"
    moved = await _writer().move(data["ref"], _moment(data["start"]), _moment(data["end"]))
    await database.run(store.db_put, request.user.id, moved)
    was = tuple(_moment(each) for each in data["was"])
    await database.run(store.db_change, request.user.id, store.MOVED, moved.ref, moved.title, was, (moved.start, moved.end), clock.now())
    _changed(request.user.id)
    return f"{ICON} Moved · **{moved.title}** · {rules.span_text(moved.start, moved.end, days.today())}"


async def move_check(request: Request, data: dict) -> str:
    if data.get("op") in (series.ALL, series.FOLLOWING):
        return await series.series_check(request, data, _writer())
    found = await _writer().get(data["ref"])
    if data.get("all_day"):
        return "" if found is not None and found.first_day == date.fromisoformat(data["first"]) else "the Bot calendar still has the old day"
    return "" if found is not None and found.start == _moment(data["start"]) else "the Bot calendar still has the old time"


async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    writer = _writer()
    event = await _mine(request, data.get("search"), data.get("day"))
    if event.repeats:
        return await series.delete_card(event, writer)
    if event.all_day:
        return Proposal(
            lines=(f"**{event.title}** · {rules.days_text(event.first_day, event.last_day, days.today())}",),
            data=_all_day_data(event), kind="remove", destructive=True, confirm_label="Delete",
        )
    return Proposal(
        lines=(f"**{event.title}** · {rules.span_text(event.start, event.end, days.today())}",),
        data={"ref": event.ref, "title": event.title, "was": [_iso(event.start), _iso(event.end)]},
        kind="remove", destructive=True, confirm_label="Delete",
    )


async def delete_save(request: Request, data: dict) -> str:
    if data.get("op") == "series_delete":
        return await series.delete_save(request, data, _writer())
    await _writer().delete(data["ref"])
    await database.run(store.db_drop, request.user.id, source.BOT, data["ref"])
    if data.get("all_day"):
        await database.run(store.db_change, request.user.id, store.DELETED, data["ref"], data["title"], (None, None), (None, None), clock.now(), {"all_day": True, "before": data["was"]})
    else:
        was = tuple(_moment(each) for each in data["was"])
        await database.run(store.db_change, request.user.id, store.DELETED, data["ref"], data["title"], was, (None, None), clock.now())
    _changed(request.user.id)
    return f"🗑️ {ICON} **{data['title']}** · deleted"


async def delete_check(request: Request, data: dict) -> str:
    if data.get("op") == "series_delete":
        return await series.delete_check(request, data, _writer())
    return "" if await _writer().get(data["ref"]) is None else "it is still in the Bot calendar"


async def cancel_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "cancel work next Tuesday", "stop work": a repeating event's happening or its series from a
    day; a one-off is deleted, on its red card."""
    writer = _writer()
    event = await _mine(request, data.get("search"), None if series.scope_of(data) == series.FOLLOWING else data.get("day"))
    if not event.repeats:
        return await delete_card(request, data, guessed)
    return await series.cancel_card(request, data, event, writer)


async def cancel_save(request: Request, data: dict) -> str:
    if data.get("op") in ("cancel_one", "stop"):
        return await series.cancel_save(request, data, _writer())
    return await delete_save(request, data)


async def cancel_check(request: Request, data: dict) -> str:
    if data.get("op") in ("cancel_one", "stop"):
        return await series.cancel_check(request, data, _writer())
    return await delete_check(request, data)


async def undo(request: Request, data: dict, guessed: frozenset) -> str:
    """ "undo that" after an add, a move or a delete in the Bot calendar: back as it was."""
    writer = _writer()
    last = await database.run(store.db_last_change, request.user.id)
    if last is None:
        raise UserError(f"{ICON} There is nothing in the calendar to undo.")
    change_id, kind, ref, title, before, after, detail = last
    if kind in (store.CANCELLED_ONE, store.SERIES_CHANGED, store.SERIES_DELETED):
        said = await series.undo(kind, ref, title, detail, writer)
    elif kind == store.ADDED:
        await writer.delete(ref)
        await database.run(store.db_drop, request.user.id, source.BOT, ref)
        said = f"↩️ {ICON} **{title}** · taken off the calendar"
    elif kind == store.MOVED and detail.get("all_day"):
        back = await writer.move_all_day(ref, *_dates(detail["before"]))
        await database.run(store.db_put, request.user.id, back)
        said = f"↩️ {ICON} **{title}** · back to {rules.days_text(back.first_day, back.last_day, days.today())}"
    elif kind == store.MOVED:
        back = await writer.move(ref, before[0], before[1])
        await database.run(store.db_put, request.user.id, back)
        said = f"↩️ {ICON} **{title}** · back to {rules.span_text(back.start, back.end, days.today())}"
    elif detail.get("all_day"):
        again = await writer.add_all_day(title, *_dates(detail["before"]))
        await database.run(store.db_put, request.user.id, again)
        said = f"↩️ {ICON} **{title}** · back on the calendar"
    else:
        again = await writer.add(title, before[0], before[1])
        await database.run(store.db_put, request.user.id, again)
        said = f"↩️ {ICON} **{title}** · back on the calendar"
    await database.run(store.db_undone, change_id)
    await series.refresh(request.user.id, writer)  # a series is many happenings: the copy read again
    _changed(request.user.id)
    return said


async def add_undo(request: Request, data: dict) -> str:
    """Take back an add saved a moment ago: the last change in the Bot calendar, undone."""
    return await undo(request, {}, frozenset())


def writing_actions() -> list:
    from core.actions import EACH_DAY, MINUTES, Action

    which = Field("search", "The words naming the event, exactly as the user said them, without \"my\", \"the\" or \"next\". Never complete or correct them.", required=True)
    ends_at = Field("ends_at", "When it ends, only when the user says (\"9 to 5:30\" -> 5:30; \"10 to 2\" -> 2).", TIME)
    scope = Field(
        "scope",
        "For a repeating event: one (that day only: \"next Tuesday\", \"on the 20th\", \"just today\"), following (from a day on: "
        "\"from next week\", \"from now on\", \"stop\"), all (every time: \"always\", \"every day\"). Leave out when it could be either.",
        choices=series.SCOPES,
    )
    which_day = Field("day", "For a repeating event, the day of the one meant or the first day of the change, as the user said it (\"next Tuesday\"; \"from next week\" -> next Monday). Never work out a date.")
    return [
        Action(
            "calendar_add",
            "Add an event to the calendar: an appointment or a plan with a day and a time and no \"remind me\" (\"dentist Friday 3pm\" -> "
            "title dentist, day Friday, time 3pm; \"lunch with Sam Thursday at 1 for 90 minutes\" -> title lunch with Sam, length 90; "
            "\"put the plumber on my calendar tomorrow at 10\"; \"book lunch with Sam Thursday at 1\", \"make a dentist appointment for Friday at 3pm\": make, book and put are adding), or a repeating one (\"work every weekday 9 to 5:30\" -> title work, "
            "repeat weekdays, time 9, ends_at 5:30; \"swimming Mondays and Thursdays at 6pm until December\" -> repeat days, weekdays mon thu, until December), "
            "or an all-day one, over one day or several (\"add an all day event 21 and 22 November, Sam's party\" -> title Sam's party, day 21 November, "
            "last_day 22 November, all_day; \"hen do Saturday, all day\" -> title hen do, day Saturday, all_day; \"conference Friday to Sunday, all day\"). Said as an event or all day, it is an event even with no time, never a to-do. "
            "With no time said, leave time out: the card asks.",
            (
                Field("title", "What it is, in the user's own words exactly as said (\"dentist\", \"lunch with Sam\"), without the day, the time or the length, and without add, make, book or put (\"book lunch with Sam\" -> lunch with Sam; \"make a dentist appointment\" -> dentist appointment; \"an all day event\" is not part of it).", required=True),
                Field("day", _DAY + " For an event over several days, its first day."),
                Field("last_day", "For an event over several days, its last day exactly as said (\"21 and 22 November\" -> day 21 November, last_day 22 November; \"Friday to Sunday\" -> day Friday, last_day Sunday). Never work out a date. Leave out for one day."),
                Field("all_day", "True when the user says all day or all-day (\"an all day event\"; \"All day\" as the answer to the card's \"At what time?\"). Leave out otherwise.", BOOLEAN),
                Field("time", "When it starts, as the user said it.", TIME),
                Field("length", "How long, only when the user says (\"for an hour\" -> 60, \"for 90 minutes\" -> 90).", MINUTES),
                ends_at,
                *recurrence.fields(),
                *recurrence.end_fields(),
            ),
            prepare=add_card, apply=add_save, verify=add_check, undo=add_undo, purpose=EACH_DAY, say=("dentist Friday 3pm for an hour",),
        ),
        Action(
            "calendar_move",
            "Move an event the bot added to the calendar to another day, time or length (\"move the dentist to 4pm\" -> search dentist, time 4pm; "
            "\"move lunch with Sam to Monday\" -> day Monday; an all-day one: \"move the hen do to 28 November\" -> search hen do, day 28 November), or change the times of a repeating one (\"work next Friday is 10 to 2\" -> "
            "search work, day next Friday, time 10, ends_at 2, scope one; \"work starts at 8:30 from next week\" -> day next Monday, time 8:30, scope following).",
            (which, Field("day", _DAY + " For a repeating event: the day of the one meant, or the first day of the change. For one over several days, its new first day."),
             Field("last_day", "For an event over several days, a new last day, only when said (\"to 28 and 29 November\" -> day 28 November, last_day 29 November). Never work out a date."),
             Field("time", "The new start, as the user said it.", TIME), Field("length", "A new length, only when said.", MINUTES), ends_at, scope),
            prepare=move_card, apply=move_save, verify=move_check, purpose=EACH_DAY, say=("move the dentist to 4pm",),
        ),
        Action(
            "calendar_delete",
            "Delete an event the bot added to the calendar (\"delete the dentist from my calendar\"), or a repeating one completely, every time (\"delete work completely\").",
            (which,), prepare=delete_card, apply=delete_save, verify=delete_check, purpose=EACH_DAY, say=("delete the dentist from my calendar",),
        ),
        Action(
            "calendar_cancel",
            "Cancel an event the bot added: one day of a repeating event (\"cancel work next Tuesday\" -> search work, day next Tuesday, scope one), "
            "a repeating event from a day on, past ones kept (\"stop work\" -> scope following; \"cancel work from November\" -> day 1 November, scope following), "
            "or a one-off (\"cancel lunch with Sam\").",
            (which, which_day, scope), prepare=cancel_card, apply=cancel_save, verify=cancel_check, purpose=EACH_DAY, say=("cancel work next Tuesday",),
        ),
        Action(
            "calendar_undo",
            "Undo the last add, move or delete in the calendar (\"undo that\" straight after it).",
            (), needs_card=False, run=undo, purpose=EACH_DAY, say=("undo that",),
        ),
    ]


ONLY_FOR_WRITING = (
    "Events in the user's own calendar: reading what is on a day, a week, a month, a year or a range of days (\"what's on tomorrow?\", \"what's on this week?\", "
    "\"what's on in November?\", \"what's on from Monday to Friday?\", \"my calendar\"), when an event is or whether it is on (\"when is the dentist?\", \"is the gym on tonight?\"), whether they "
    "are free (\"am I free at 3 tomorrow?\"), and adding an event: an appointment or a plan said with a day and a time and no "
    "\"remind me\" (\"dentist Friday 3pm\", \"lunch with Sam Thursday at 1\", \"put the plumber on my calendar\", \"book lunch with Sam\", "
    "\"make a dentist appointment for Friday at 3pm\"), a repeating event "
    "(\"work every weekday 9 to 5:30\", \"swimming Mondays and Thursdays at 6pm\"), and moving, cancelling (\"cancel work next Tuesday\", "
    "\"stop work\"), deleting or undoing one. An all-day event (\"all day event 21 and 22 November\") is the calendar too, with no time. A request to be reminded (\"remind me about the dentist Friday\") is a reminder, not the calendar. "
    "The rest of today across everything (\"what's on tonight?\") is the briefing. Not pills, not to-dos (a thing to do with no "
    "time), not personal routines, and not when the bot's own jobs run (that is the schedule task)."
)
