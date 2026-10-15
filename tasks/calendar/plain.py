from datetime import datetime, timedelta

from core import clock, config, database, design, timeinput
from core import day as days
from core.actions import TIME, Field, Proposal, Request, State
from core.errors import UserError
from tasks.calendar import rules, source, store
from tasks.calendar.rules import ICON, NEXT_WEEK, SPANS, WEEK

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
    "Events in the user's own calendar, to read: what is on a day or a week (\"what's on tomorrow?\", \"what's on "
    "Friday?\", \"what's on this week?\", \"my calendar\"), when an event is, or whether it is on (\"when is the dentist?\", \"is the gym on tonight?\"), and whether "
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


async def show(request: Request, data: dict, guessed: frozenset) -> str:
    """What is on a day, or this week, or next week."""
    today = days.today()
    events = await store.events(request.user.id)
    span = data.get("span") if data.get("span") in SPANS else rules.DAY_SPAN
    if span in (WEEK, NEXT_WEEK):
        return rules.week_answer(events, rules.span_days(span, today), today, "this week" if span == WEEK else "next week")
    return rules.day_answer(events, read_day(data.get("day"), today), today)


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
            "What is on the user's calendar on a day or a week (\"what's on tomorrow?\" -> day tomorrow; \"what's on this week?\" -> span week; \"next week\" -> span next_week; \"my calendar\" -> nothing).",
            (Field("day", _DAY), Field("span", "day (one day), week (the rest of this week), next_week (Monday to Sunday next week). Leave out for one day.", choices=SPANS)),
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
    and what it clashes with in every calendar."""
    _writer()
    title = rules.title_from(data.get("title"), request.text)
    if not title:
        raise UserError(f"{ICON} What is it called? Say it with its name, like “dentist Friday 3pm”.")
    if not data.get("time"):
        raise UserError(f"{ICON} What time? Say it with a time, like “{title.lower()} Friday 3pm”.")
    today = days.today()
    start = days.at(read_day(data.get("day"), today), rules.read_time(str(data["time"])))
    end = start + timedelta(minutes=_length(data.get("length"), DEFAULT_LENGTH))
    warnings = list(_clash_lines(await store.events(request.user.id), start, end, today))
    if start < clock.now():
        warnings.insert(0, "That time has gone by")
    return Proposal(
        lines=(f"**{title}**", rules.span_text(start, end, today), design.small("on the Bot calendar")),
        data={"title": title, "start": _iso(start), "end": _iso(end)}, warnings=tuple(warnings), kind="new",
    )


async def add_save(request: Request, data: dict) -> str:
    made = await _writer().add(data["title"], _moment(data["start"]), _moment(data["end"]))
    await database.run(store.db_put, request.user.id, made)
    await database.run(store.db_change, request.user.id, store.ADDED, made.ref, made.title, (None, None), (made.start, made.end), clock.now())
    _changed(request.user.id)
    return f"{ICON} Added · **{made.title}** · {rules.span_text(made.start, made.end, days.today())}"


async def _last_ref(request: Request, kind: str) -> str:
    last = await database.run(store.db_last_change, request.user.id)
    return last[2] if last is not None and last[1] == kind else ""


async def add_check(request: Request, data: dict) -> str:
    ref = await _last_ref(request, store.ADDED)
    return "" if ref and await _writer().get(ref) is not None else "it is not in the Bot calendar"


async def _mine(request: Request, words) -> rules.Event:
    """The next event whose name fits the words; one on another calendar is said, never changed."""
    if not str(words or "").strip():
        raise UserError(f"{ICON} Which event?")
    found = rules.next_matching(await store.events(request.user.id), str(words), clock.now())
    if not found.mine or found.all_day:
        raise UserError(rules.NOT_MINE.format(icon=ICON, title=found.title))
    return found


async def move_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "move the dentist to 4pm", "move the dentist to Monday": its day, its time or its length."""
    _writer()
    event = await _mine(request, data.get("search"))
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
    moved = await _writer().move(data["ref"], _moment(data["start"]), _moment(data["end"]))
    await database.run(store.db_put, request.user.id, moved)
    was = tuple(_moment(each) for each in data["was"])
    await database.run(store.db_change, request.user.id, store.MOVED, moved.ref, moved.title, was, (moved.start, moved.end), clock.now())
    _changed(request.user.id)
    return f"{ICON} Moved · **{moved.title}** · {rules.span_text(moved.start, moved.end, days.today())}"


async def move_check(request: Request, data: dict) -> str:
    found = await _writer().get(data["ref"])
    return "" if found is not None and found.start == _moment(data["start"]) else "the Bot calendar still has the old time"


async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    _writer()
    event = await _mine(request, data.get("search"))
    return Proposal(
        lines=(f"**{event.title}** · {rules.span_text(event.start, event.end, days.today())}",),
        data={"ref": event.ref, "title": event.title, "was": [_iso(event.start), _iso(event.end)]},
        kind="remove", destructive=True, confirm_label="Delete",
    )


async def delete_save(request: Request, data: dict) -> str:
    await _writer().delete(data["ref"])
    await database.run(store.db_drop, request.user.id, source.BOT, data["ref"])
    was = tuple(_moment(each) for each in data["was"])
    await database.run(store.db_change, request.user.id, store.DELETED, data["ref"], data["title"], was, (None, None), clock.now())
    _changed(request.user.id)
    return f"🗑️ {ICON} **{data['title']}** · deleted"


async def delete_check(request: Request, data: dict) -> str:
    return "" if await _writer().get(data["ref"]) is None else "it is still in the Bot calendar"


async def undo(request: Request, data: dict, guessed: frozenset) -> str:
    """ "undo that" after an add, a move or a delete in the Bot calendar: back as it was."""
    writer = _writer()
    last = await database.run(store.db_last_change, request.user.id)
    if last is None:
        raise UserError(f"{ICON} There is nothing in the calendar to undo.")
    change_id, kind, ref, title, before, after = last
    if kind == store.ADDED:
        await writer.delete(ref)
        await database.run(store.db_drop, request.user.id, source.BOT, ref)
        said = f"↩️ {ICON} **{title}** · taken off the calendar"
    elif kind == store.MOVED:
        back = await writer.move(ref, before[0], before[1])
        await database.run(store.db_put, request.user.id, back)
        said = f"↩️ {ICON} **{title}** · back to {rules.span_text(back.start, back.end, days.today())}"
    else:
        again = await writer.add(title, before[0], before[1])
        await database.run(store.db_put, request.user.id, again)
        said = f"↩️ {ICON} **{title}** · back on the calendar"
    await database.run(store.db_undone, change_id)
    _changed(request.user.id)
    return said


def writing_actions() -> list:
    from core.actions import EACH_DAY, MINUTES, Action

    which = Field("search", "The words naming the event, exactly as the user said them, without \"my\", \"the\" or \"next\". Never complete or correct them.", required=True)
    return [
        Action(
            "calendar_add",
            "Add an event to the calendar: an appointment or a plan with a day and a time and no \"remind me\" (\"dentist Friday 3pm\" -> "
            "title dentist, day Friday, time 3pm; \"lunch with Sam Thursday at 1 for 90 minutes\" -> title lunch with Sam, length 90; "
            "\"put the plumber on my calendar tomorrow at 10\").",
            (
                Field("title", "What it is, in the user's own words exactly as said (\"dentist\", \"lunch with Sam\"), without the day, the time or the length.", required=True),
                Field("day", _DAY),
                Field("time", "When it starts, as the user said it.", TIME),
                Field("length", "How long, only when the user says (\"for an hour\" -> 60, \"for 90 minutes\" -> 90).", MINUTES),
            ),
            prepare=add_card, apply=add_save, verify=add_check, purpose=EACH_DAY, say=("dentist Friday 3pm for an hour",),
        ),
        Action(
            "calendar_move",
            "Move an event the bot added to the calendar to another day, time or length (\"move the dentist to 4pm\" -> search dentist, time 4pm; "
            "\"move lunch with Sam to Monday\" -> day Monday).",
            (which, Field("day", _DAY), Field("time", "The new start, as the user said it.", TIME), Field("length", "A new length, only when said.", MINUTES)),
            prepare=move_card, apply=move_save, verify=move_check, purpose=EACH_DAY, say=("move the dentist to 4pm",),
        ),
        Action(
            "calendar_delete",
            "Delete an event the bot added to the calendar (\"delete the dentist from my calendar\", \"cancel lunch with Sam\").",
            (which,), prepare=delete_card, apply=delete_save, verify=delete_check, purpose=EACH_DAY, say=("delete the dentist from my calendar",),
        ),
        Action(
            "calendar_undo",
            "Undo the last add, move or delete in the calendar (\"undo that\" straight after it).",
            (), needs_card=False, run=undo, purpose=EACH_DAY, say=("undo that",),
        ),
    ]


ONLY_FOR_WRITING = (
    "Events in the user's own calendar: reading what is on a day or a week (\"what's on tomorrow?\", \"what's on this week?\", "
    "\"my calendar\"), when an event is or whether it is on (\"when is the dentist?\", \"is the gym on tonight?\"), whether they "
    "are free (\"am I free at 3 tomorrow?\"), and adding an event: an appointment or a plan said with a day and a time and no "
    "\"remind me\" (\"dentist Friday 3pm\", \"lunch with Sam Thursday at 1\", \"put the plumber on my calendar\"), and moving, "
    "deleting or undoing one. A request to be reminded (\"remind me about the dentist Friday\") is a reminder, not the calendar. "
    "The rest of today across everything (\"what's on tonight?\") is the briefing. Not pills, not to-dos (a thing to do with no "
    "time), not personal routines, and not when the bot's own jobs run (that is the schedule task)."
)
