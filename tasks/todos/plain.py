from core import cards, clock, hubcard, names, summaries, timeinput
from core import day as days
from core.actions import ITEMS, Field, LiveReply, Proposal, Request, State, flag, is_guessed, is_reference
from core.cards import Card
from core.errors import UserError
from tasks.todos import rules, store
from tasks.todos.rules import ICON, TASK, Todo

# ---------------------------------------------------------------------------
# To-dos in plain words. Adding, changing and removing one is a card that
# only Save writes; ticking one off (or back) is a log, done at once and said
# in a line, as a pill taken is. Claude hands over the words as I said them
# and a day as I said it ("Friday"); Python reads the day and finds which
# to-do a name means (core/names.py), and asks when more than one fits.
# Takes a Request, never a Context, and calls no Discord.
# ---------------------------------------------------------------------------
LIST = "todos"
REF = "t"  # a to-do as a card's data names it: "t12"

ONLY_FOR = (
    "The user's to-do list: things they plan to do, each with a day if they give one (\"add call Ryan Friday\", "
    "\"put buy stamps on my list\"), ticking one off or back (\"I called Ryan\", \"done the stamps\", \"undo that\"), "
    "moving one to another day, renaming or removing one, and seeing the list. Not a reminder at a time of day (that "
    "is the reminders task), not pills, and not a personal routine of steps done every day."
)
EXAMPLES = ("add call Ryan Friday", "done buy stamps", "what's on my to-do list?")

_WHICH = (
    "Which to-do, exactly as the user said it (its words or part of them, from the state). Never complete or correct "
    "it: the code finds which is meant, and asks when more than one fits."
)
_DAY = (
    "The day it is for, exactly as the user said it (\"Friday\", \"tomorrow\", \"the 20th\", \"today\"). Never work out "
    "a date. Leave out when no day was said."
)


def ref(todo: Todo) -> str:
    return f"{REF}{todo.id}"


def today():
    return days.today()


async def every(user_id: int) -> list[Todo]:
    return await store.every(user_id)


def _read_day(said: str, on: "days.date"):
    try:
        return timeinput.parse_date(said, on)
    except Exception as error:
        raise UserError(f"“{said}” is not a day I can read.") from error


# ---------------------------------------------------------------------------
# The card in the hub, and the list
# ---------------------------------------------------------------------------
async def hub_card(user_id: int) -> Card | None:
    """Today's to-dos as the hub's card, or None on a day with nothing for today."""
    on = today()
    found = rules.on(await every(user_id), on)
    if found.is_empty:
        return None
    from core import design

    if design.current() >= 5 and not found.overdue and not found.today:
        return None  # round 5: every to-do of today's done, so the card leaves the hub; a new one brings it back
    return Card(rules.text(found, on), rules.buttons(found), rules.layout(found, on))


def changed(user_id: int) -> None:
    """Something of mine changed: the hub's card and the briefing follow."""
    hubcard.changed(TASK, user_id, lambda: hub_card(user_id))
    summaries.changed(TASK, user_id)
    from core import attention

    attention.changed()


async def post_job(job) -> None:
    """The morning routine's step: today's card, fresh under the ones before it."""
    from core import scheduler

    user_id = job.user_id
    if user_id is None:
        from core import database

        user_id = await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    posted = await hubcard.post(TASK, user_id, lambda: hub_card(user_id))
    scheduler.note(job, "posted" if posted is not None else "not posted: nothing for today")


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    return LiveReply(LIST, rules.listed(await every(request.user.id), today()))


async def state(request: Request) -> State:
    on = today()
    lines = []
    for each in await every(request.user.id):
        if each.is_done and each.done_on != on:
            continue
        status = "done today" if each.is_done else (f"for {rules.day_text(each.day, on)}" if each.day else "any day")
        lines.append(f"{each.text} ({status})")
    return State("The user's to-dos now", tuple(lines), "none")


async def item_names(request: Request) -> list[str]:
    on = today()
    return [each.text for each in await every(request.user.id) if not each.is_done or each.done_on == on]


# ---------------------------------------------------------------------------
# Which to-do is meant
# ---------------------------------------------------------------------------
def find(todos: list[Todo], wanted: str, said: str = "") -> Todo:
    wanted = str(wanted).strip()
    if wanted.lower().startswith(REF) and wanted[len(REF):].isdigit():
        found = [each for each in todos if each.id == int(wanted[len(REF):])]
        if found:
            return found[0]
    try:
        return names.find(todos, wanted, lambda each: each.text)
    except names.Unnamed:
        raise UserError("Which to-do?")
    except names.Unknown:
        raise UserError(f"There is no to-do “{wanted}” on your list.")
    except names.Ambiguous as which:
        listed = " or ".join(f"**{each.text}**" for each in which.candidates[:4])
        raise UserError(f"“{wanted}” could be {listed}: say which.")


def _one(todos: list[Todo], item: dict, said: str, last: Todo | None = None) -> Todo:
    wanted = str(item.get("todo", "")).strip()
    if is_reference(wanted) or not wanted:
        if last is not None:
            return last
        if len(todos) == 1:
            return todos[0]
        raise UserError("Which to-do?")
    return find(todos, wanted, said)


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    on = today()
    open_ = [each for each in await every(request.user.id) if not each.is_done]
    lines, kept, warnings = [], [], []
    for index, item in enumerate(data.get(LIST) or []):
        words = str(item.get("text", "")).strip()
        if not words:
            continue
        words = words[:1].upper() + words[1:]
        said_day = str(item.get("day") or "").strip()
        day = None
        if said_day:
            try:
                day = _read_day(said_day, on)
            except UserError as error:
                warnings.append(str(error) + " It is for any day")
        same = next((each for each in open_ if each.text.lower() == words.lower()), None)
        if same is not None:
            warnings.append(f"{rules.line(same, on)} is already on your list: not added twice")
            continue
        when = rules.day_text(day, on) if day else "any day"
        lines.append(flag(f"**{words}** · {when}", is_guessed(guessed, LIST, index, "day")))
        kept.append({"text": words, "day": day.isoformat() if day else None})
    if not kept:
        raise UserError("; ".join(warnings) or "Nothing to add.")
    return Proposal(lines=tuple(lines), data={LIST: kept}, warnings=tuple(warnings), kind="new")


async def add_save(request: Request, data: dict) -> str:
    from datetime import date

    on, now = today(), clock.now()

    def write(conn):
        for item in data[LIST]:
            store.db_add(conn, request.user.id, item["text"], date.fromisoformat(item["day"]) if item["day"] else None, on, now)

    await request.db.run(write)
    changed(request.user.id)
    said = ", ".join(f"**{item['text']}**" for item in data[LIST])
    return f"✅ Added · {ICON} {said}"


async def add_check(request: Request, data: dict) -> str:
    there = {each.text for each in await every(request.user.id) if not each.is_done}
    missing = [item["text"] for item in data[LIST] if item["text"] not in there]
    return f"not on the list: {', '.join(missing)}" if missing else ""


# ---------------------------------------------------------------------------
# Done, and not done after all: a log, at once
# ---------------------------------------------------------------------------
async def done(request: Request, data: dict, guessed: frozenset) -> str:
    on, now = today(), clock.now()
    open_ = [each for each in await every(request.user.id) if not each.is_done]
    if not open_:
        raise UserError("There is nothing open on your to-do list.")
    ticked: list[Todo] = []
    for item in data.get(LIST) or [{}]:
        todo = _one([each for each in open_ if each not in ticked], item, request.text)
        ticked.append(todo)
    await request.db.run(lambda conn: [store.db_done(conn, each.id, now, on) for each in ticked])
    after = {each.id: each for each in await every(request.user.id)}
    wrong = [each.text for each in ticked if after.get(each.id) is None or not after[each.id].is_done]
    if wrong:
        raise UserError(f"Could not tick off {', '.join(wrong)}.")
    changed(request.user.id)
    left = rules.on(list(after.values()), on)
    still = len(left.overdue) + len(left.today)
    return f"✅ {', '.join(f'**{each.text}**' for each in ticked)} · done" + (f" · {still} left today" if still else " · nothing left today")


async def undone(request: Request, data: dict, guessed: frozenset) -> str:
    on = today()
    finished = sorted((each for each in await every(request.user.id) if each.is_done), key=lambda each: each.done_at, reverse=True)
    if not finished:
        raise UserError("Nothing on your to-do list is ticked off.")
    back: list[Todo] = []
    for item in data.get(LIST) or [{}]:
        # "undo that" with nothing named: the one ticked off last
        back.append(_one([each for each in finished if each not in back], item, request.text, last=finished[0] if not back else None))
    await request.db.run(lambda conn: [store.db_done(conn, each.id, None, None) for each in back])
    after = {each.id: each for each in await every(request.user.id)}
    if any(after.get(each.id) is None or after[each.id].is_done for each in back):
        raise UserError("Could not put it back.")
    changed(request.user.id)
    return f"↩️ {', '.join(rules.line(after[each.id], on) for each in back)} · not done"


# ---------------------------------------------------------------------------
# Change and remove: cards
# ---------------------------------------------------------------------------
async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    on = today()
    open_ = [each for each in await every(request.user.id) if not each.is_done]
    lines, kept, warnings = [], [], []
    for index, item in enumerate(data.get(LIST) or []):
        try:
            todo = _one(open_, item, request.text)
        except UserError as error:
            warnings.append(str(error))
            continue
        words = str(item.get("text") or "").strip() or todo.text
        words = words[:1].upper() + words[1:]
        day = todo.day
        if item.get("day"):
            try:
                day = _read_day(str(item["day"]), on)
            except UserError as error:
                warnings.append(str(error))
        differs = []
        if words != todo.text:
            differs.append(f"words · {todo.text} → {words}")
        if day != todo.day:
            differs.append(f"day · {rules.day_text(todo.day, on) if todo.day else 'any day'} → {rules.day_text(day, on) if day else 'any day'}")
        if not differs:
            warnings.append(f"**{todo.text}** is already like that")
            continue
        lines += [flag(f"**{todo.text}**", is_guessed(guessed, LIST, index, "todo")), *differs]
        kept.append({"todo": ref(todo), "text": words, "day": day.isoformat() if day else None})
    if not kept:
        raise UserError("; ".join(warnings) or "Nothing to change.")
    return Proposal(lines=tuple(lines), data={LIST: kept}, warnings=tuple(warnings), kind="change")


async def change_save(request: Request, data: dict) -> str:
    from datetime import date

    await request.db.run(lambda conn: [store.db_change(conn, int(item["todo"][len(REF):]), item["text"], date.fromisoformat(item["day"]) if item["day"] else None) for item in data[LIST]])
    changed(request.user.id)
    on = today()
    found = {ref(each): each for each in await every(request.user.id)}
    return "✅ Saved · " + " · ".join(rules.line(found[item["todo"]], on) for item in data[LIST] if item["todo"] in found)


async def change_check(request: Request, data: dict) -> str:
    found = {ref(each): each for each in await every(request.user.id)}
    wrong = [item["text"] for item in data[LIST] if item["todo"] not in found or found[item["todo"]].text != item["text"] or (found[item["todo"]].day.isoformat() if found[item["todo"]].day else None) != item["day"]]
    return f"not as the card said: {', '.join(wrong)}" if wrong else ""


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    on = today()
    todos = await every(request.user.id)
    lines, kept, warnings = [], [], []
    for index, item in enumerate(data.get(LIST) or []):
        try:
            todo = _one(todos, item, request.text)
        except UserError as error:
            warnings.append(str(error))
            continue
        lines.append(flag(f"**{todo.text}** → removed", is_guessed(guessed, LIST, index, "todo")))
        kept.append({"todo": ref(todo), "text": todo.text})
    if not kept:
        raise UserError("; ".join(warnings) or "Nothing to remove.")
    return Proposal(lines=tuple(lines), data={LIST: kept}, warnings=tuple(warnings), kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    now = clock.now()
    await request.db.run(lambda conn: [store.db_remove(conn, int(item["todo"][len(REF):]), now) for item in data[LIST]])
    changed(request.user.id)
    return f"🗑️ Removed {', '.join(f'**{item['text']}**' for item in data[LIST])}"


async def remove_check(request: Request, data: dict) -> str:
    there = {ref(each) for each in await every(request.user.id)}
    left = [item["text"] for item in data[LIST] if item["todo"] in there]
    return f"still there: {', '.join(left)}" if left else ""


# ---------------------------------------------------------------------------
# The Done button on the card
# ---------------------------------------------------------------------------
async def on_done(press: cards.Press) -> str:
    return await _done(press, press.arg)


async def on_picked(press: cards.Press) -> str:
    """The Done dropdown (round 4): the to-do picked is done, as its button would make it."""
    return await _done(press, press.values[0] if press.values else "")


async def _done(press: cards.Press, which: str) -> str:
    todo = await press.db.run(store.db_get, int(which)) if which.isdigit() else None
    if todo is None or todo.is_done:
        changed(press.user.id)  # the card is brought up to date, which takes the button away
        return "already dealt with"
    await press.db.run(store.db_done, todo.id, clock.now(), today())
    changed(press.user.id)
    return f"✅ {todo.text} · done"


FIELDS_ADD = (
    Field("text", "What is to be done, in the user's own words, without the day (\"call Ryan\").", required=True),
    Field("day", _DAY),
)
FIELDS_WHICH = (Field("todo", _WHICH, required=True),)
FIELDS_CHANGE = (
    Field("todo", _WHICH, required=True),
    Field("text", "New words for it, only if the user gave them."),
    Field("day", "The new day, exactly as the user said it. Never work out a date. Only if they gave one."),
)
DESCRIPTIONS = {
    "todo_add": "Add one or more to-dos (\"add call Ryan Friday\" -> text call Ryan, day Friday; \"put stamps and milk on my list\" -> two items).",
    "todo_done": "One or more to-dos are done (\"I called Ryan\", \"done the stamps\", \"tick off call Ryan\"). A log: no card.",
    "todo_undone": "A to-do ticked off by mistake is not done after all (\"undo that\", \"call Ryan isn't done\"). With nothing named, leave todo as @that.",
    "todo_change": "Move a to-do to another day or change its words (\"move call Ryan to Monday\", \"call Ryan is call Ryan back\"). Never for a time of day: a to-do keeps none, so \"that was at 9\" is none.",
    "todo_remove": "Take one or more to-dos off the list (\"remove buy stamps\", \"forget the dentist one\").",
    "todo_show": "The user asks what is on their to-do list (\"my to-dos\", \"what's on my list?\").",
}


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    items = lambda fields, what: (Field(LIST, what, ITEMS, required=True, item_fields=fields),)  # noqa: E731
    return [
        Action("todo_add", DESCRIPTIONS["todo_add"], items(FIELDS_ADD, "Each to-do to add, one item each."), prepare=add_card, apply=add_save, verify=add_check, purpose=SET_UP, say=("add call Ryan Friday",)),
        Action("todo_done", DESCRIPTIONS["todo_done"], items(FIELDS_WHICH, "Each to-do that is done, one item each."), needs_card=False, run=done, purpose=EACH_DAY, say=("done call Ryan",)),
        Action("todo_undone", DESCRIPTIONS["todo_undone"], items(FIELDS_WHICH, "Each to-do that is not done after all."), needs_card=False, run=undone, purpose=EACH_DAY, say=("undo that",)),
        Action("todo_change", DESCRIPTIONS["todo_change"], items(FIELDS_CHANGE, "Each to-do to change, one item each."), prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("move call Ryan to Monday",)),
        Action("todo_remove", DESCRIPTIONS["todo_remove"], items(FIELDS_WHICH, "Each to-do to remove, one item each."), prepare=remove_card, apply=remove_save, verify=remove_check, purpose=SET_UP, say=("remove call Ryan",)),
        Action("todo_show", DESCRIPTIONS["todo_show"], needs_card=False, run=show, purpose=SEE, say=("my to-dos",)),
    ]
