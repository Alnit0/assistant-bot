from core import clock, timeinput
from core import day as days
from core.actions import TIME, Field, Request, State
from core.errors import UserError
from tasks.calendar import rules, store
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

