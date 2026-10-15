from dataclasses import replace
from datetime import time

from core import attention, cards, clock, config, database, design, hubcard, live, names, recurrence, scheduler, summaries, timeinput
from core import day as days
from core.actions import BOOLEAN, ITEMS, LIST, TIME, Field, LiveReply, Proposal, Request, State, flag, is_guessed, is_reference
from core.cards import Card
from core.errors import UserError
from tasks.habits import rules, store
from tasks.habits.rules import ANY_TIME, AT, GROUP, ICON, NUDGES, STEP, TASK, WINDOW, GuideStep, Habit, Item

# ---------------------------------------------------------------------------
# Personal routines in plain words. Making, changing and removing one is a
# card that only Save writes; ticking an item off (or back) is a log, done at
# once. Claude hands over the routine's name, the items as I said them (a
# group with its steps), the repeat's fields, and times as said; Python reads
# every time (core/timeinput.py), works out every repeat (core/recurrence.py)
# and finds which routine, item or step a name means (core/names.py). Takes a
# Request, never a Context, and calls no Discord.
#
#   "make an evening routine 6pm to 11pm: brush teeth, floss"     habit_add
#   "add skincare to my evening routine: cleanser, toner, serum"  habit_items
#   "put serum before toner"                                      habit_move
#   "exfoliate only on Mondays and Thursdays"                     habit_item_repeat
#   "make my evening routine 6pm to 11pm", "nudge me if not done"  habit_change
#   "done skincare", "did floss"; "undo floss"                    habit_tick, habit_untick
# ---------------------------------------------------------------------------
LIST_KEY = "habits"
REF = "h"
START = "start"  # the job: a routine's own card at its time or its window's start (layout B)

ONLY_FOR = (
    "The user's personal routines: their own named routines of steps and groups of steps (\"make an evening routine "
    "6pm to 11pm: brush teeth, floss, skincare: cleanser, toner, serum\"), when and how often each is on, a nudge, "
    "adding, removing or moving an item, a step's own days, ticking an item off or back (\"did floss\", \"done "
    "skincare\", \"undo floss\"), removing a routine, and seeing them. Not the bot's own morning routine of posts "
    "(that is the schedule task), not pills, not a reminder at a time (that is reminders), and not a one-off to-do."
)
EXAMPLES = ("make an evening routine 6pm to 11pm: brush teeth, floss", "did floss", "add skincare to my evening routine: cleanser, toner, serum")

_WHICH = "Which personal routine, exactly as the user said it (\"evening\"). Never complete or correct it. Leave out if none was named."
_ITEM = "An item or a step, exactly as the user said it (\"serum\"). Never complete or correct it."


def ref(habit: Habit) -> str:
    return f"{REF}{habit.id}"


async def every(user_id: int) -> list[Habit]:
    return await store.every(user_id)


def _words(text) -> str:
    text = str(text or "").strip()
    return text[:1].upper() + text[1:]


def _name(text: str) -> str:
    text = str(text or "").strip()
    for tail in (" routine", " Routine"):
        text = text.removesuffix(tail)
    return _words(text)


def _time(said, what: str) -> time | None:
    """A time as said ("6pm", "18:00"), read by timeinput; one with no am or pm that
    could be either is asked about, never guessed."""
    if not said:
        return None
    try:
        return timeinput.parse_time(str(said))
    except timeinput.AmbiguousTime as which:
        raise UserError(f"Is {what} {said} {' or '.join(timeinput.format_time(each) for each in which.options)}? Say it with am or pm.")
    except Exception:
        raise UserError(f"“{said}” is not a time I can read for {what}.")


# ---------------------------------------------------------------------------
# A routine as a card's data, and back (what Save writes, and what is read back)
# ---------------------------------------------------------------------------
def _guide_data(guide) -> list:
    return [{"text": each.text, **({"repeat": recurrence.to_dict(each.repeat)} if each.repeat is not None else {})} for each in guide]


def as_data(habit: Habit) -> dict:
    return {
        "id": habit.id, "name": habit.name, "repeat": recurrence.to_dict(habit.repeat), "when": habit.when,
        "at": habit.at.isoformat("minutes") if habit.at else None, "start": habit.start.isoformat("minutes") if habit.start else None,
        "end": habit.end.isoformat("minutes") if habit.end else None, "nudge": habit.nudge,
        "items": [{"id": each.id, "text": each.text, "kind": each.kind, "guide": _guide_data(each.guide), "repeat": recurrence.to_dict(each.repeat) if each.repeat is not None else None} for each in habit.items],
    }


def from_data(data: dict, user_id: int) -> Habit:
    def clock_of(text):
        return time.fromisoformat(text) if text else None

    items = tuple(
        Item(
            int(each.get("id") or 0), each["text"], each.get("kind") or STEP,
            tuple(GuideStep(step["text"], recurrence.from_dict(step["repeat"]) if step.get("repeat") else None) for step in each.get("guide") or ()),
            recurrence.from_dict(each["repeat"]) if each.get("repeat") else None,
        )
        for each in data["items"]
    )
    return Habit(int(data.get("id") or 0), user_id, data["name"], recurrence.from_dict(data["repeat"]), items, data["when"], clock_of(data.get("at")), clock_of(data.get("start")), clock_of(data.get("end")), data.get("nudge") or rules.NUDGE_NONE)


def _shape(habit: Habit) -> dict:
    """What a check compares: everything but the ids (a new item gets its id on Save)."""
    data = as_data(habit)
    data.pop("id")
    for each in data["items"]:
        each.pop("id")
    return data


# ---------------------------------------------------------------------------
# The card in the hub, the list, and what extraction is told
# ---------------------------------------------------------------------------
async def today_of(user_id: int) -> list[rules.Today]:
    day = days.today()
    return rules.due(await every(user_id), await store.ticked(user_id, day), day)


def layout_b() -> bool:
    """Layout B (the default): the Today card is the overview, and each routine has a
    card of its own from its time or window until it is done. Layout A: one card."""
    return config.ROUTINES_LAYOUT != "a"


def slot(habit_id: int) -> str:
    """A routine's own card's place in the hub (layout B)."""
    return f"{TASK}.r{habit_id}"


async def hub_card(user_id: int) -> Card | None:
    """Layout A: the one Personal routines card, every routine on today by the list
    rule. Layout B has none: each routine has its own (`own_card`)."""
    if layout_b():
        return None
    found = await today_of(user_id)
    if not found:
        return None
    return Card(rules.all_text(found), rules.buttons(found), rules.all_layout(found, clock.now()))


async def own_card(user_id: int, habit_id: int) -> Card | None:
    """Layout B: a routine's own card, from its time or its window's start (any time:
    from the morning) until it is done; None before then, after, and on a day it is off."""
    now = clock.now()
    found = next((each for each in await today_of(user_id) if each.habit.id == habit_id), None)
    if found is None or rules.state(found, now) in (rules.NOT_YET, rules.FINISHED):
        return None
    return Card(rules.routine_text(found), rules.buttons([found]), rules.routine_card(found, now))


async def refresh_own(user_id: int) -> None:
    """Each routine's own card as it should be now: posted once it has started, edited
    while it is open, taken away once it is done or off; and its start booked."""
    for each in await every(user_id):
        await hubcard.refresh(TASK, user_id, lambda habit_id=each.id: own_card(user_id, habit_id), slot=slot(each.id))
    await book_starts(user_id)


async def book_starts(user_id: int) -> None:
    """A run at the start of each routine still to come today, once (its key)."""
    now = clock.now()
    for each in await today_of(user_id):
        start = each.starts()
        if start is not None and start > now and not each.finished:
            local = f"{days.day_of(start).isoformat()}T{days.local_time(start):%H:%M}"
            await scheduler.add_job(TASK, START, start, {"id": each.habit.id}, user_id=user_id, key=f"h{each.habit.id}@{local}")


def changed(user_id: int) -> None:
    hubcard.changed(TASK, user_id, lambda: hub_card(user_id))
    if layout_b():
        live.schedule(("habits-own", user_id), lambda: refresh_own(user_id))
    summaries.changed(TASK, user_id)
    attention.changed()


async def post_job(job) -> None:
    """With the morning routine: layout A's one card, or in layout B a fresh copy of
    each routine's own card that has started (any time ones), and the starts booked."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    if not layout_b():
        posted = await hubcard.post(TASK, user_id, lambda: hub_card(user_id))
        scheduler.note(job, "posted" if posted is not None else "not posted: no personal routine today")
        return
    posted = 0
    for each in await every(user_id):
        posted += await hubcard.post(TASK, user_id, lambda habit_id=each.id: own_card(user_id, habit_id), slot=slot(each.id)) is not None
    await book_starts(user_id)
    scheduler.note(job, f"{posted} routine card{'' if posted == 1 else 's'} posted; the rest come at their start")


async def start_job(job) -> None:
    """A routine's time or window has come (layout B): its own card goes up."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None or not layout_b():
        scheduler.note(job, "nothing to do: " + ("nobody to post for" if user_id is None else "layout A"))
        return
    shown = await hubcard.refresh(TASK, user_id, lambda: own_card(user_id, int(job.payload.get("id") or 0)), slot=slot(int(job.payload.get("id") or 0)))
    scheduler.note(job, f"its card: {shown or 'nothing to show (done, off today, or gone)'}")


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    return LiveReply(LIST_KEY, rules.listed(await every(request.user.id)))


async def state(request: Request) -> State:
    day = days.today()
    ticked = await store.ticked(request.user.id, day)
    lines = []
    for each in await every(request.user.id):
        items = ", ".join(f"{rules.item_text(item, day)}{' (done today)' if item.id in ticked else ''}" for item in each.items)
        lines.append(f"{each.name} ({recurrence.text(each.repeat, day)}; {rules.when_text(each)}; {rules.nudge_text(each)}; items: {items})")
    return State("The user's personal routines now", tuple(lines), "none")


async def item_names(request: Request) -> list[str]:
    habits = await every(request.user.id)
    return [*(each.name for each in habits), *(item.text for each in habits for item in each.items), *(step.text for each in habits for item in each.items for step in item.guide)]


def find(habits: list[Habit], wanted: str) -> Habit:
    wanted = _name(str(wanted))
    if wanted.lower().startswith(REF) and wanted[len(REF):].isdigit():
        found = [each for each in habits if each.id == int(wanted[len(REF):])]
        if found:
            return found[0]
    try:
        return names.find(habits, wanted, lambda each: each.name)
    except names.Unknown:
        raise UserError(f"There is no personal routine “{wanted}”.")
    except names.Ambiguous as which:
        raise UserError(f"“{wanted}” could be {' or '.join(f'**{each.name}**' for each in which.candidates[:4])}: say which.")


def _places(habit: Habit, wanted: str, quiet: bool = False) -> list[tuple[int, int | None]]:
    """Where a name is in a routine: [(the item's place, the step's place in its group
    or None)], or [] when quiet and it is not there. Matched by core/names.py; two
    that fit are said, never guessed."""
    spots = [(at, None, item.text) for at, item in enumerate(habit.items)]
    spots += [(at, inner, step.text) for at, item in enumerate(habit.items) for inner, step in enumerate(item.guide)]
    try:
        found = names.find(spots, str(wanted), lambda spot: spot[2])
    except names.Unknown:
        if quiet:
            return []
        raise UserError(f"{habit.name} has no item or step “{wanted}”.")
    except names.Ambiguous as which:
        if quiet:
            return []
        raise UserError(f"“{wanted}” could be {' or '.join(f'**{spot[2]}**' for spot in which.candidates[:4])}: say which.")
    return [(found[0], found[1])]


def _the_routine(habits: list[Habit], wanted, item_named: str = "") -> Habit:
    """The routine meant: the one named; with none named, the only one, or the only
    one holding the item named."""
    wanted = str(wanted or "")
    if wanted.strip() and not is_reference(wanted):
        return find(habits, wanted)
    if len(habits) == 1:
        return habits[0]
    if item_named:
        holding = [each for each in habits if _places(each, item_named, quiet=True)]
        if len(holding) == 1:
            return holding[0]
    if not habits:
        raise UserError("You have no personal routines yet.")
    raise UserError("Which routine?")


# ---------------------------------------------------------------------------
# Make: a card
# ---------------------------------------------------------------------------
def _items(said) -> tuple[Item, ...]:
    """The items as said: each a step, or a group when it has steps of its own."""
    found = []
    for each in said or []:
        if isinstance(each, str):
            each = {"text": each}
        text = _words(each.get("text"))
        if not text:
            continue
        guide = tuple(GuideStep(_words(step)) for step in each.get("steps") or [] if str(step).strip())
        if len(guide) > rules.MAX_GUIDE:
            raise UserError(f"A group has at most {rules.MAX_GUIDE} steps.")
        own = recurrence.from_fields({"repeat": recurrence.DAYS, "weekdays": each["days"]}) if recurrence.day_numbers(each.get("days")) else None
        found.append(Item(0, text, GROUP if guide else STEP, guide, own))
    return tuple(found)


def _when(data: dict, was: Habit | None) -> dict:
    """When a routine is on, from what was said and what it was: at a time, a window, or any time."""
    at, start, end = _time(data.get("time"), "the time"), _time(data.get("from"), "the start"), _time(data.get("until"), "the end")
    if data.get("any_time"):
        return {"when": ANY_TIME, "at": None, "start": None, "end": None}
    if start or end:
        start = start or (was.start if was else None)
        end = end or (was.end if was else None)
        if not rules.window_ok(start, end):
            raise UserError("A window runs from a time until a later one the same day: say both (“6pm to 11pm”).")
        return {"when": WINDOW, "at": None, "start": start, "end": end}
    if at:
        return {"when": AT, "at": at, "start": None, "end": None}
    if was is not None:
        return {"when": was.when, "at": was.at, "start": was.start, "end": was.end}
    return {"when": ANY_TIME, "at": None, "start": None, "end": None}


def _nudge(data: dict, was: Habit | None) -> str:
    said = str(data.get("nudge") or "")
    return said if said in NUDGES else (was.nudge if was else rules.NUDGE_NONE)


def _checked(habit: Habit) -> Habit:
    if not habit.items:
        raise UserError("That leaves nothing in the routine: remove the routine instead.")
    if len(habit.items) > rules.MAX_ITEMS:
        raise UserError(f"A routine has at most {rules.MAX_ITEMS} items.")
    if habit.nudge == rules.NUDGE_END and habit.when != WINDOW:
        raise UserError("A nudge if it is not done by the end needs a window (“6pm to 11pm”).")
    return habit


async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    name = _name(str(data.get("routine") or ""))
    if not name:
        raise UserError("What is the routine called?")
    items = _items(data.get("items"))
    if not items:
        raise UserError(f"What is in {name}? Say its steps (a group with its own steps after a colon).")
    if any(each.name.lower() == name.lower() for each in await every(request.user.id)):
        raise UserError(f"You have a routine called **{name}** already: say what to change in it.")
    habit = _checked(Habit(0, request.user.id, name, recurrence.from_fields(data, first=days.today()), items, nudge=_nudge(data, None), **_when(data, None)))
    today = days.today()
    lines = [rules.summary_line(habit, today), design.small(rules.items_text(habit.items, today))]
    if habit.nudge != rules.NUDGE_NONE:
        lines.append(rules.nudge_text(habit))
    return Proposal(lines=tuple(lines), data=as_data(habit), kind="new")


async def add_save(request: Request, data: dict) -> str:
    habit = from_data(data, request.user.id)
    await request.db.run(store.db_add, request.user.id, habit, clock.now())
    changed(request.user.id)
    return f"✅ Saved · {ICON} {rules.summary_line(habit, days.today())}"


async def add_check(request: Request, data: dict) -> str:
    wanted = _shape(from_data(data, request.user.id))
    there = [each for each in await every(request.user.id) if each.name == data["name"]]
    return "" if there and _shape(there[0]) == wanted else "the routine is not as the card said"


# ---------------------------------------------------------------------------
# Change: cards, each showing what changes
# ---------------------------------------------------------------------------
def _differs(before: Habit, after: Habit) -> list[str]:
    today = days.today()
    found = []
    if before.name != after.name:
        found.append(f"name · {before.name} → {after.name}")
    if before.repeat != after.repeat:
        found.append(f"days · {recurrence.text(before.repeat, today)} → {recurrence.text(after.repeat, today)}")
    if (before.when, before.at, before.start, before.end) != (after.when, after.at, after.start, after.end):
        found.append(f"when · {rules.when_text(before)} → {rules.when_text(after)}")
    if before.nudge != after.nudge:
        found.append(f"nudge · {rules.nudge_text(before)} → {rules.nudge_text(after)}")
    if _shape(before)["items"] != _shape(after)["items"]:
        if len(before.items) != len(after.items):
            found.append(f"items · {len(before.items)} → {len(after.items)}")
        found.append(design.small(rules.items_text(after.items, today)))
    return found


def _change_proposal(before: Habit, after: Habit, guessed: frozenset) -> Proposal:
    differs = _differs(before, _checked(after))
    if not differs:
        raise UserError(f"**{before.name}** is already like that.")
    return Proposal(lines=(flag(f"**{before.name}**", is_guessed(guessed, "routine")), *differs), data=as_data(after), kind="change")


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """Its name, how often, when, or the nudge."""
    habit = _the_routine(await every(request.user.id), data.get("routine"))
    repeat = recurrence.from_fields(data, was=habit.repeat, first=days.today()) if any(data.get(name) for name in recurrence.FIELD_NAMES) else habit.repeat
    after = replace(habit, name=_name(str(data.get("new_name") or "")) or habit.name, repeat=repeat, nudge=_nudge(data, habit), **_when(data, habit))
    return _change_proposal(habit, after, guessed)


async def items_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """Items added (a group with its steps, or steps added to a group), or taken out."""
    named = [str(each.get("text") if isinstance(each, dict) else each) for each in data.get("items") or []]
    habit = _the_routine(await every(request.user.id), data.get("routine"), str(data.get("group") or "") or (named[0] if named else ""))
    items = list(habit.items)
    if data.get("change") == "remove":
        gone = {_places(habit, wanted)[0] for wanted in named}
        kept = []
        for at, item in enumerate(items):
            if (at, None) in gone:
                continue
            guide = tuple(step for inner, step in enumerate(item.guide) if (at, inner) not in gone)
            kept.append(replace(item, guide=guide, kind=GROUP if guide else STEP))
        items = kept
    elif data.get("group"):
        ((at, inner),) = _places(habit, str(data["group"]))
        if inner is not None or not items[at].is_group:
            raise UserError(f"**{items[at].text if inner is None else items[at].guide[inner].text}** is not a group.")
        there = {step.text.lower() for step in items[at].guide}
        items[at] = replace(items[at], guide=items[at].guide + tuple(GuideStep(_words(each)) for each in named if each.strip() and each.strip().lower() not in there))
    else:
        there = {each.text.lower(): at for at, each in enumerate(items)}
        for each in _items(data.get("items")):
            at = there.get(each.text.lower())
            if at is None:
                items.append(each)
            elif each.is_group:
                # A group named again with steps: its new steps are added to it
                old = {step.text.lower() for step in items[at].guide}
                items[at] = replace(items[at], kind=GROUP, guide=items[at].guide + tuple(step for step in each.guide if step.text.lower() not in old))
    return _change_proposal(habit, replace(habit, items=tuple(items)), guessed)


async def move_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "put serum before toner": an item among the items, or a step within its group."""
    wanted, other = str(data.get("item") or ""), str(data.get("other") or "")
    if not wanted or not other:
        raise UserError("Move what, before or after what?")
    habit = _the_routine(await every(request.user.id), data.get("routine"), wanted)
    ((at, inner),) = _places(habit, wanted)
    ((other_at, other_inner),) = _places(habit, other)
    after = str(data.get("where") or "before") == "after"
    items = list(habit.items)
    if inner is None and other_inner is None:
        moving = items.pop(at)
        target = items.index(habit.items[other_at])
        items.insert(target + (1 if after else 0), moving)
    elif inner is not None and other_inner is not None and at == other_at:
        guide = list(items[at].guide)
        moving = guide.pop(inner)
        target = guide.index(items[at].guide[other_inner])
        guide.insert(target + (1 if after else 0), moving)
        items[at] = replace(items[at], guide=tuple(guide))
    else:
        raise UserError("Those two are not in the same list: a step moves within its group, and an item among the items.")
    return _change_proposal(habit, replace(habit, items=tuple(items)), guessed)


async def item_repeat_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "exfoliate only on Mondays and Thursdays": an item's or a step's own days.
    "every day" again takes its own days away."""
    wanted = str(data.get("item") or "")
    if not wanted:
        raise UserError("Which item or step?")
    habit = _the_routine(await every(request.user.id), data.get("routine"), wanted)
    ((at, inner),) = _places(habit, wanted)
    repeat = recurrence.from_fields(data, first=days.today())
    own = None if repeat.kind == recurrence.DAILY else repeat
    items = list(habit.items)
    if inner is None:
        items[at] = replace(items[at], repeat=own)
    else:
        guide = list(items[at].guide)
        guide[inner] = replace(guide[inner], repeat=own)
        items[at] = replace(items[at], guide=tuple(guide))
    return _change_proposal(habit, replace(habit, items=tuple(items)), guessed)


async def change_save(request: Request, data: dict) -> str:
    habit = from_data(data, request.user.id)
    await request.db.run(store.db_change, habit, clock.now())
    changed(request.user.id)
    return f"✅ Saved · {ICON} {rules.summary_line(habit, days.today())}"


async def change_check(request: Request, data: dict) -> str:
    there = next((each for each in await every(request.user.id) if each.id == data["id"]), None)
    return "" if there is not None and _shape(there) == _shape(from_data(data, request.user.id)) else "the routine is not as the card said"


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    habit = find(await every(request.user.id), str(data.get("routine") or ""))
    lines = (flag(f"**{habit.name}** → removed", is_guessed(guessed, "routine")), design.small(f"{len(habit.items)} items, {recurrence.text(habit.repeat, days.today())}"))
    return Proposal(lines=lines, data={"id": habit.id, "name": habit.name}, kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    await request.db.run(store.db_remove, data["id"], clock.now())
    await hubcard.remove(TASK, request.user.id, slot(data["id"]))
    changed(request.user.id)
    return f"🗑️ Removed **{data['name']}**"


async def remove_check(request: Request, data: dict) -> str:
    return "the routine is still there" if any(each.id == data["id"] for each in await every(request.user.id)) else ""


# ---------------------------------------------------------------------------
# Ticking an item off, and back: a log, at once. A step inside a group ticks
# its group (the group's steps are a guide, not ticked one by one).
# ---------------------------------------------------------------------------
def _progress_line(found: list[rules.Today], habit_id: int) -> str:
    today = next(each for each in found if each.habit.id == habit_id)
    if today.finished:
        return f"{today.habit.name} done"
    return f"{today.habit.name} {today.done}/{today.total}" + (f" · next: {today.next_item.text}" if today.next_item else "")


def _which_item(found: list[rules.Today], wanted: str, want_ticked: bool) -> tuple[rules.Today, Item]:
    """The item a name means among today's routines: one still to do for a tick, one
    ticked for an untick. A step of a group means its group. Two that fit are said."""
    spots = []
    for each in found:
        for item in each.items:
            if (item.id in each.ticked) != want_ticked:
                continue
            spots.append((each, item, item.text))
            spots += [(each, item, step) for step in item.guide_on(each.day)]
    if not spots:
        raise UserError("Nothing is ticked off today." if want_ticked else "Everything in today's routines is done.")
    try:
        today, item, _ = names.find(spots, wanted, lambda spot: spot[2])
    except names.Unknown:
        raise UserError(f"Nothing called “{wanted}” is {'ticked off' if want_ticked else 'left'} today.")
    except names.Ambiguous as which:
        raise UserError(f"“{wanted}” could be {' or '.join(f'**{spot[2]}** ({spot[0].habit.name})' for spot in which.candidates[:4])}: say which.")
    return today, item


def _said(data: dict) -> list[str]:
    return [_words(each) for each in data.get("items") or [] if str(each).strip()]


async def tick(request: Request, data: dict, guessed: frozenset) -> str:
    day, now = days.today(), clock.now()
    found = await today_of(request.user.id)
    if not found:
        raise UserError("No personal routine is on today.")
    if data.get("routine") and not is_reference(str(data["routine"])):
        habit = find([each.habit for each in found], str(data["routine"]))
        found = [each for each in found if each.habit.id == habit.id]
    ticked = []
    for wanted in _said(data) or [""]:
        today, item = _which_item(found, wanted, want_ticked=False) if wanted else (found[0], found[0].next_item)
        if item is None:
            raise UserError("Which one?")
        await request.db.run(store.db_tick, request.user.id, item.id, day, now)
        ticked.append((today.habit.id, item))
    after = await today_of(request.user.id)
    if any(item.id not in next(each for each in after if each.habit.id == habit_id).ticked for habit_id, item in ticked):
        raise UserError("Could not tick it off.")
    changed(request.user.id)
    return f"✅ {', '.join(f'**{item.text}**' for _, item in ticked)} · {_progress_line(after, ticked[-1][0])}"


async def untick(request: Request, data: dict, guessed: frozenset) -> str:
    day = days.today()
    found = await today_of(request.user.id)
    back = []
    for wanted in _said(data):
        today, item = _which_item(found, wanted, want_ticked=True)
        await request.db.run(store.db_untick, item.id, day)
        back.append((today.habit.id, item))
    if not back:
        raise UserError("Which one?")
    after = await today_of(request.user.id)
    changed(request.user.id)
    return f"↩️ {', '.join(f'**{item.text}**' for _, item in back)} · not done · {_progress_line(after, back[-1][0])}"


async def _tick_by_id(press: cards.Press, which: str) -> str:
    item = await press.db.run(store.db_step, int(which)) if which.isdigit() else None
    if item is None:
        changed(press.user.id)
        return "gone"
    fresh = await press.db.run(store.db_tick, item[0], int(which), days.today(), clock.now())
    changed(press.user.id)
    return f"✅ {item[2]}" if fresh else "already dealt with"


async def on_tick(press: cards.Press) -> str:
    """A button of the plain look: that item is done."""
    return await _tick_by_id(press, press.arg)


async def on_picked(press: cards.Press) -> str:
    """The Done dropdown under a routine: the item picked is done (a group: the whole group)."""
    return await _tick_by_id(press, press.values[0] if press.values else "")


_ROUTINE = Field("routine", _WHICH)
_ITEMS = Field(
    "items",
    "The items, in order, in the user's words. A group (\"skincare: cleanser, toner, serum\") is one item with its steps.",
    ITEMS,
    item_fields=(
        Field("text", "The step, or the group's name (\"floss\", \"skincare\").", required=True),
        Field("steps", "Only for a group: its steps, in order (\"cleanser\", \"toner\").", LIST),
        Field("days", "Only if the user gave this item days of its own (\"exfoliate on Mondays\" -> mon).", LIST, choices=rules.DAY_WORDS),
    ),
)
_WHEN = (
    Field("time", "At a time: the time, as the user said it (\"7am\"). Not for a window.", TIME),
    Field("from", "A window's start, as said (\"6pm to 11pm\" -> 6pm).", TIME),
    Field("until", "A window's end, as said (\"6pm to 11pm\" -> 11pm).", TIME),
    Field("any_time", "True when the user says any time today, with no time.", BOOLEAN),
    Field("nudge", "none (no nudge), start (a nudge when it starts), end (a nudge if it is not done by the end of its window). Only if the user said.", choices=NUDGES),
)


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    repeat = recurrence.fields()
    return [
        Action(
            "habit_add",
            "Make a personal routine (\"make an evening routine 6pm to 11pm: brush teeth, floss, skincare: cleanser, toner\" -> routine evening, from 6pm, until 11pm, items brush teeth, floss, skincare with steps cleanser toner).",
            (Field("routine", "Its name, as the user said it (\"evening\").", required=True), replace(_ITEMS, required=True), *repeat, *_WHEN),
            prepare=add_card, apply=add_save, verify=add_check, purpose=SET_UP, say=("make an evening routine 6pm to 11pm: brush teeth, floss",),
        ),
        Action(
            "habit_change",
            "Change a personal routine's name, how often it is on, when (a time, a window, any time) or its nudge (\"make my evening routine 6pm to 11pm\" -> routine evening, from 6pm, until 11pm; \"nudge me if my evening routine isn't done\" -> nudge end).",
            (_ROUTINE, Field("new_name", "A new name, only if the user gave one."), *repeat, *_WHEN),
            prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("make my evening routine 6pm to 11pm",),
        ),
        Action(
            "habit_items",
            "Add items to a personal routine, or steps to one of its groups, or take items or steps out (\"add skincare to my evening routine: cleanser, toner, serum\" -> items skincare with steps; \"add toner to skincare\" -> group skincare, items toner; \"take floss out\" -> change remove).",
            (_ROUTINE, _ITEMS, Field("group", "Only when steps are added to a group already there: the group, as said."), Field("change", "add or remove. Leave out for add.", choices=("add", "remove"))),
            prepare=items_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("add skincare to my evening routine: cleanser, toner, serum",),
        ),
        Action(
            "habit_move",
            "Move an item or a step of a personal routine before or after another (\"put serum before toner\" -> item serum, where before, other toner).",
            (_ROUTINE, Field("item", _ITEM, required=True), Field("where", "before or after.", choices=("before", "after")), Field("other", "The one it goes before or after, as said.", required=True)),
            prepare=move_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("put serum before toner",),
        ),
        Action(
            "habit_item_repeat",
            "Give one item or step of a personal routine days of its own (\"exfoliate only on Mondays and Thursdays\" -> item exfoliate, repeat days, weekdays mon thu; \"exfoliate every day again\" -> repeat daily).",
            (_ROUTINE, Field("item", _ITEM, required=True), *repeat),
            prepare=item_repeat_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("exfoliate only on Mondays and Thursdays",),
        ),
        Action("habit_remove", "Remove a personal routine (\"remove my evening routine\").", (Field("routine", _WHICH, required=True),), prepare=remove_card, apply=remove_save, verify=remove_check, purpose=SET_UP, say=("remove my evening routine",)),
        Action("habit_tick", "One or more items of today's personal routines are done (\"did floss\", \"done skincare\"). A log: no card.", (_ROUTINE, Field("items", "Each item done, in the user's words.", LIST)), needs_card=False, run=tick, purpose=EACH_DAY, say=("did floss",)),
        Action("habit_untick", "An item ticked off by mistake is not done after all (\"undo floss\").", (_ROUTINE, Field("items", "Each item that is not done after all.", LIST, required=True)), needs_card=False, run=untick, purpose=EACH_DAY, say=("undo floss",)),
        Action("habit_show", "The user asks what personal routines they have (\"my routines\").", needs_card=False, run=show, purpose=SEE, say=("my routines",)),
    ]
