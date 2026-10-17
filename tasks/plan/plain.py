import logging
from datetime import date, datetime, time, timedelta

from core import clock, database, design, names, planning, summaries, timeinput
from core import day as days
from core.actions import BOOLEAN, ITEMS, LIST, MINUTES, TIME, Choice, Field, Proposal, Request, State, flag
from core.errors import UserError
from tasks.plan import store

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Plan my day in plain words: the conversation over the core's engine
# (core/planning.py).
#
#   "plan my day", "plan tomorrow"     the plan card: Save, Put it on my calendar, Cancel
#   "replan", "what should I do now?"  the same from now: what is done and fixed stays
#   on the open card, in words:        "I'm out 2 to 4", "move laundry to the evening",
#                                      "drop the shopping", "make the essay 2 hours",
#                                      "I start at 8 tomorrow"
#
# Claude hands over values: how long each to-do takes (15, 30, 60 or 90
# minutes, from its words), the times said, which to-do is meant (its id from
# the state, or its words: core/names.py finds it). Python does every sum and
# places everything. Save keeps the times (the Today card shows them); Put it
# on my calendar is a card of its own first, and its Save adds the blocks to
# the Bot calendar too. A plan never pings: nothing is booked by it.
# ---------------------------------------------------------------------------
TASK = "plan"
ICON = planning.ICON
TITLE = "Plan my day"
TODAY, TOMORROW = "today", "tomorrow"
CALENDAR_LABEL = "Put it on my calendar"
NO_CALENDAR_LABEL = "Without the calendar"

ONLY_FOR = (
    "Planning the user's day: putting their open to-dos into the free time around what is fixed (events, pills, "
    "reminders, routines), with a card to save it: \"plan my day\", \"plan tomorrow\", \"replan\", \"what should I do "
    "now?\", and changes to that plan before it is saved (\"I'm out 2 to 4\", \"move laundry to the evening\", \"drop "
    "the shopping\", \"make the essay 2 hours\", \"I start at 8 tomorrow\"). Not adding, ticking off or moving a to-do "
    "to another day (the to-dos task), not what is on or left today (the day as a whole), and not adding an event "
    "(the calendar task)."
)
EXAMPLES = ("plan my day", "plan tomorrow", "what should I do now?")


# --- reading what was said ------------------------------------------------------------------------------------------
def _merged(before: dict, now: dict) -> dict:
    """What has been said about this plan so far, with this message's on top: times out and to-dos
    dropped add up, a length or a move said again replaces the one before."""
    said = {key: value for key, value in before.items()}
    for key in ("day", "starts", "ends"):
        if now.get(key) not in (None, "", []):
            said[key] = now[key]
    if now.get("from_now"):
        said["from_now"] = True
    said["estimates"] = {**(before.get("estimates") or {}), **{str(each.get("todo")): each.get("length") for each in now.get("estimates") or [] if each.get("todo")}}
    said["out"] = [*(before.get("out") or []), *(each for each in now.get("out") or [] if each.get("from") and each.get("to"))]
    said["drop"] = sorted({*(before.get("drop") or []), *(str(each) for each in now.get("drop") or [] if str(each).strip())})
    said["lengths"] = {**(before.get("lengths") or {}), **{str(each.get("todo")): each.get("minutes") for each in now.get("lengths") or [] if each.get("todo")}}
    moves = {str(each.get("todo")): {"part": each.get("part") or "", "at": each.get("at") or ""} for each in now.get("moves") or [] if each.get("todo")}
    said["moves"] = {**(before.get("moves") or {}), **moves}
    return said


def _reading(typed: str, start: datetime, end: datetime, day: date, later: bool = False) -> tuple[datetime | None, bool]:
    """A time said for the plan, on its day: (the moment, whether it was a guess). One with no am or pm is
    the reading inside the planned window (the later of two for an end); None when it can't be read."""
    try:
        return days.at(day, timeinput.parse_time(typed)), False
    except timeinput.AmbiguousTime as which:
        readings = [days.at(day, each) for each in which.options]
        inside = [each for each in readings if start <= each <= end] or readings
        return (inside[-1] if later else inside[0]), len(inside) > 1
    except Exception:
        return None, False


def _time_of(typed, later: bool = False) -> time | None:
    """A time for the window's start or end; with no am or pm, the morning for a start ("I start at 8") and
    the evening for an end ("done by 9")."""
    try:
        return timeinput.parse_time(str(typed))
    except timeinput.AmbiguousTime as which:
        return which.options[-1] if later else which.options[0]
    except Exception:
        return None


def _which(pieces: list[planning.Piece], said: str) -> planning.Piece | None:
    """The to-do a value means: its id from the state ("t12"), else its words (core/names.py)."""
    wanted = str(said or "").strip()
    by_ref = next((each for each in pieces if each.ref == wanted.lower()), None)
    if by_ref is not None:
        return by_ref
    try:
        return names.find(pieces, wanted, lambda each: each.text)
    except (names.Unknown, names.Ambiguous, names.Unnamed):
        return None


def _day_of(said: dict, today: date) -> date:
    return today + timedelta(days=1) if str(said.get("day") or "").lower() == TOMORROW else today


# --- the card ---------------------------------------------------------------------------------------------------------
async def _pieces(user_id: int, day: date) -> list[planning.Piece]:
    """The day from every task, without the blocks a plan put on the Bot calendar (they are the plan's own)."""
    ours = await database.run(store.db_calendar_refs, user_id)
    return [each for each in await planning.gather(user_id, day) if not (each.task == "calendar" and each.ref in ours)]


async def build(request: Request, said: dict) -> tuple[planning.Plan, dict, list[str], set[str]]:
    """The plan from what was said: the plan, the lengths used ({ref: [minutes, said]}), the warnings,
    and the refs whose part of the card is a guess."""
    now = clock.now()
    today = days.day_of(now)
    day = _day_of(said, today)
    start, end = planning.window(day, now, _time_of(said.get("starts")) if said.get("starts") else None, _time_of(said.get("ends"), later=True) if said.get("ends") else None, bool(said.get("from_now")))
    if end <= start:
        raise UserError(f"{ICON} The day is planned to {timeinput.format_moment(end)}, and that has gone by. Say “plan tomorrow”.")
    pieces = await _pieces(request.user.id, day)
    flexible = [each for each in pieces if each.flexible]
    warnings, guessed = [], set()
    kept = await database.run(store.db_lengths, request.user.id)
    lengths: dict[str, list] = {ref: [minutes, said_so] for ref, (minutes, said_so) in kept.items()}
    for todo, estimate in (said.get("estimates") or {}).items():
        piece = _which(flexible, todo)
        if piece is not None and not (piece.ref in lengths and lengths[piece.ref][1]) and piece.ref not in kept:
            lengths[piece.ref] = [planning.estimate(estimate), False]
    for todo, minutes in (said.get("lengths") or {}).items():
        piece = _which(flexible, todo)
        if piece is None:
            warnings.append(f"“{todo}” is not among your to-dos")
        elif planning.length(minutes) is not None:
            lengths[piece.ref] = [planning.length(minutes), True]
    dropped = set()
    for todo in said.get("drop") or []:
        piece = _which(flexible, todo)
        if piece is None:
            warnings.append(f"“{todo}” is not among your to-dos")
        else:
            dropped.add(piece.ref)
    parts, at = {}, {}
    for todo, move in (said.get("moves") or {}).items():
        piece = _which(flexible, todo)
        if piece is None:
            warnings.append(f"“{todo}” is not among your to-dos")
            continue
        if move.get("at"):
            moment, guess = _reading(str(move["at"]), start, end, day)
            if moment is None:
                warnings.append(f"“{move['at']}” is not a time I can read")
            else:
                at[piece.ref] = moment
                if guess:
                    guessed.add(piece.ref)
        elif move.get("part") in planning.PARTS:
            parts[piece.ref] = move["part"]
    out = []
    for span in said.get("out") or []:
        begin, first_guess = _reading(str(span.get("from")), start, end, day)
        finish, second_guess = _reading(str(span.get("to")), begin or start, end + timedelta(hours=12), day, later=False)
        if begin is None or finish is None:
            warnings.append(f"“{span.get('from')} to {span.get('to')}” is not a time I can read")
            continue
        if finish <= begin:
            finish += timedelta(hours=12) if finish + timedelta(hours=12) > begin else timedelta(days=1)
        out.append((begin, finish))
        if first_guess or second_guess:
            guessed.add(f"out@{begin.isoformat()}")
    plan = planning.place(day, pieces, {ref: value[0] for ref, value in lengths.items()}, start, end, out=out, parts=parts, at=at, dropped=dropped)
    used = {slot.piece.ref: lengths.get(slot.piece.ref, [planning.DEFAULT_LENGTH, False]) for slot in plan.slots}
    for piece, _ in plan.left_out:
        if piece.ref in lengths:
            used[piece.ref] = lengths[piece.ref]
    return plan, used, warnings, guessed


def _lines(plan: planning.Plan, guessed: set[str], today: date) -> tuple[str, ...]:
    found = list(planning.lines(plan, today))
    for slot in plan.slots:
        if slot.piece.ref in guessed:
            found = [flag(each, True) if each.startswith(f"**{timeinput.format_moment(slot.start)} · {slot.piece.icon} {slot.piece.text}**") else each for each in found]
    for gap in plan.out:
        if f"out@{gap.start.isoformat()}" in guessed:
            found = [flag(each, True) if each.startswith(f"{timeinput.format_moment(gap.start)} · out until") else each for each in found]
    return tuple(found)


def _slots(plan: planning.Plan) -> list[dict]:
    return [
        {"task": slot.piece.task, "ref": slot.piece.ref, "icon": slot.piece.icon, "text": slot.piece.text, "start": slot.start.isoformat(), "minutes": slot.minutes}
        for slot in plan.slots
    ]


def calendar_writer():
    """The Bot calendar, when the plan may add to it; None otherwise."""
    from tasks.calendar import plain as calendar_plain, source

    if not calendar_plain.writing():
        return None
    found = source.bot()
    return found if found is not None and found.can_write else None


async def plan_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    before = (request.previous or {}).get("said") or data.get("said") or {}
    said = _merged(before, {key: value for key, value in data.items() if key not in ("said", "calendar")})
    on_calendar = bool(data.get("calendar", (request.previous or {}).get("calendar", False)))
    plan, used, warnings, mine = await build(request, said)
    today = days.today()
    lines = list(_lines(plan, mine, today))
    if not [each for each in plan.slots] and not plan.left_out and not plan.done:
        warnings.append("No open to-dos to place")
    elif not plan.slots:
        warnings.append(f"No free time between {timeinput.format_moment(plan.start)} and {timeinput.format_moment(plan.end)}: nothing could be placed")
    writer = calendar_writer() if plan.slots else None
    keep = {"said": said, "day": plan.day.isoformat(), "slots": _slots(plan), "lengths": used, "calendar": on_calendar and writer is not None}
    also = ()
    if on_calendar and writer is not None:
        count = len(plan.slots)
        lines.append(design.small(f"Save adds {count} block{'' if count == 1 else 's'} to the Bot calendar too"))
        also = (Choice(NO_CALENDAR_LABEL, {"said": said, "calendar": False}),)
    elif writer is not None:
        also = (Choice(CALENDAR_LABEL, {"said": said, "calendar": True}),)
    return Proposal(lines=tuple(lines), data=keep, warnings=tuple(warnings), kind="new", can_save=bool(plan.slots), also=also, guessed=tuple(sorted(mine)))


# --- saving ---------------------------------------------------------------------------------------------------------
def _saved(each: dict, calendar_ref: str | None = None) -> store.Saved:
    return store.Saved(each["task"], each["ref"], each["icon"], each["text"], datetime.fromisoformat(each["start"]), int(each["minutes"]), calendar_ref)


async def _to_calendar(user_id: int, day: date, slots: list[dict]) -> list[str | None]:
    """The plan's blocks on the Bot calendar, in place of the ones an earlier plan of that day put there."""
    from tasks.calendar import plain as calendar_plain, store as calendar_store

    writer = calendar_writer()
    if writer is None:
        raise UserError(f"{ICON} Adding to the calendar is off: say “plan my day” again to save it without.")
    for old in await store.day(user_id, day):
        if old.calendar_ref:
            try:
                await writer.delete(old.calendar_ref)
            except Exception:
                log.warning("Plan: an earlier block could not be taken off the Bot calendar")
    refs = []
    for each in slots:
        start = datetime.fromisoformat(each["start"])
        made = await writer.add(each["text"], start, start + timedelta(minutes=int(each["minutes"])))
        await database.run(calendar_store.db_put, user_id, made)
        refs.append(made.ref)
    calendar_plain._changed(user_id)
    return refs


async def plan_save(request: Request, data: dict) -> str:
    day = date.fromisoformat(data["day"])
    slots = list(data.get("slots") or [])
    refs = await _to_calendar(request.user.id, day, slots) if data.get("calendar") else [None] * len(slots)
    saved = [_saved(each, ref) for each, ref in zip(slots, refs)]
    now = clock.now()
    await database.run(store.db_save, request.user.id, day, saved, now)
    await database.run(store.db_set_lengths, request.user.id, {ref: (int(value[0]), bool(value[1])) for ref, value in (data.get("lengths") or {}).items()}, now)
    summaries.changed(TASK, request.user.id)
    which = "today's" if day == days.today() else "tomorrow's" if day == days.today() + timedelta(days=1) else f"{day:%a} {day.day} {day:%b}'s"
    first = timeinput.format_moment(saved[0].start) if saved else ""
    said = f"{ICON} Saved · {which} plan · {len(saved)} thing{'' if len(saved) == 1 else 's'}" + (f" · first {first}" if first else "")
    return said + (" · on the Bot calendar" if data.get("calendar") else "")


async def plan_check(request: Request, data: dict) -> str:
    there = await store.day(request.user.id, date.fromisoformat(data["day"]))
    wanted = [(each["ref"], each["start"]) for each in data.get("slots") or []]
    if [(each.ref, each.start.isoformat()) for each in there] != wanted:
        return "the plan is not as the card said"
    if data.get("calendar") and any(not each.calendar_ref for each in there):
        return "a block is not on the Bot calendar"
    return ""


# --- what extraction is told -------------------------------------------------------------------------------------------
async def state(request: Request) -> State:
    """The open to-dos with the ids the plan knows them by, and whether a plan is saved."""
    today = days.today()
    lines = []
    for each in [piece for piece in await planning.gather(request.user.id, today) if piece.flexible and not piece.done]:
        rank = {planning.OVERDUE: "overdue", planning.TODAY: "for today"}.get(each.rank, "any day")
        lines.append(f"{each.ref}: {each.text} ({rank})")
    if await store.day(request.user.id, today):
        lines.append("(a plan is saved for today)")
    return State("The user's open to-dos, by id", tuple(lines), "none")


async def today_lines(user_id: int, now: datetime) -> list:
    """For the Today card: each thing of today's saved plan at its time (one on the Bot calendar is there already)."""
    from core.today import Line

    day = days.day_of(now)
    saved = await store.day(user_id, day)
    if not saved:
        return []
    done = {each.ref for each in await planning.gather(user_id, day) if each.flexible and each.done}
    return [
        Line(each.icon, f"**{each.text}** · planned", each.start, each.start + timedelta(minutes=each.minutes), done=each.ref in done)
        for each in saved if not each.calendar_ref
    ]


_TODO = "Which to-do: its id from the state (\"t12\"), else its words exactly as the user said them."


def actions() -> list:
    from core.actions import EACH_DAY, Action

    return [
        Action(
            "plan_day",
            "Plan the user's day (\"plan my day\", \"plan tomorrow\" -> day tomorrow; \"replan\", \"what should I do now?\" "
            "-> from_now), or change the plan on the open card (\"I'm out 2 to 4\" -> out; \"move laundry to the evening\" -> "
            "moves; \"drop the shopping\" -> drop; \"make the essay 2 hours\" -> lengths 120; \"I start at 8 tomorrow\" -> "
            "starts 8:00, day tomorrow). For a new plan, fill estimates for every to-do in the state. Never work out a time "
            "or place anything: the code does.",
            (
                Field("day", "today or tomorrow. Leave out for today.", choices=(TODAY, TOMORROW)),
                Field("from_now", "True for \"replan\" and \"what should I do now?\": planned again from now.", BOOLEAN),
                Field("starts", "When the user's day starts, only if said (\"I start at 8\").", TIME),
                Field("ends", "When the user's day ends, only if said (\"done by 9pm\").", TIME),
                Field(
                    "estimates", "For a new plan: every to-do in the state, with how long it takes from its words "
                    "(\"email Sam\" 15, \"weekly shop\" 60, \"write the essay\" 90).", ITEMS,
                    item_fields=(Field("todo", _TODO, required=True), Field("length", "15, 30, 60 or 90.", choices=("15", "30", "60", "90"), required=True)),
                ),
                Field(
                    "out", "Times the user is busy or away, as said (\"I'm out 2 to 4\" -> from 2:00, to 4:00).", ITEMS,
                    item_fields=(Field("from", "When it starts.", TIME, required=True), Field("to", "When it ends.", TIME, required=True)),
                ),
                Field(
                    "moves", "A to-do moved to a part of the day or a time (\"laundry in the evening\" -> part evening; "
                    "\"essay at 3\" -> at 3:00).", ITEMS,
                    item_fields=(Field("todo", _TODO, required=True), Field("part", "morning, afternoon or evening.", choices=tuple(planning.PARTS)), Field("at", "A time, if one was said.", TIME)),
                ),
                Field("drop", "To-dos left out of the plan (\"drop the shopping\" -> [shopping]), as in todo.", LIST),
                Field(
                    "lengths", "A length the user says a to-do takes (\"make the essay 2 hours\" -> 120).", ITEMS,
                    item_fields=(Field("todo", _TODO, required=True), Field("minutes", "How long, as the user said it.", MINUTES, required=True)),
                ),
            ),
            prepare=plan_card, apply=plan_save, verify=plan_check, purpose=EACH_DAY, say=("plan my day", "plan tomorrow", "replan"),
        ),
    ]
