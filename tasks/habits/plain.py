from core import attention, cards, clock, database, hubcard, names, scheduler, summaries
from core import day as days
from core.actions import ADD, LIST, REMOVE, SET, Field, LiveReply, Proposal, Request, State, flag, is_guessed, is_reference
from core.cards import Card
from core.errors import UserError
from tasks.habits import rules, store
from tasks.habits.rules import DAY_WORDS, ICON, TASK, Habit, Step

# ---------------------------------------------------------------------------
# Personal routines in plain words. Making, changing and removing one is a
# card that only Save writes; ticking a step off (or back) is a log, done at
# once. Claude hands over the routine's name and the steps as I said them,
# and days as weekdays; Python finds which routine or step a name means
# (core/names.py). Takes a Request, never a Context, and calls no Discord.
# ---------------------------------------------------------------------------
LIST_KEY = "habits"
REF = "h"

ONLY_FOR = (
    "The user's personal routines: their own named checklists of a few steps done on chosen days (\"make a morning "
    "routine: stretch, water, journal, on weekdays\"), adding or removing a step, the days, ticking a step off or "
    "back (\"did stretch\", \"done water\", \"undo stretch\"), removing a routine, and seeing them. Not the bot's own "
    "morning routine of posts (that is the schedule task), not pills, and not a one-off to-do."
)
EXAMPLES = ("make a morning routine: stretch, water, journal", "did stretch", "add meditate to my morning routine")

_WHICH = "Which personal routine, exactly as the user said it (\"morning\"). Never complete or correct it. Leave out if none was named."
_DAYS = "The days of the week named: \"weekdays\" is mon tue wed thu fri, \"every day\" is all seven. Only the days named."


def ref(habit: Habit) -> str:
    return f"{REF}{habit.id}"


async def every(user_id: int) -> list[Habit]:
    return await store.every(user_id)


def _weekdays(found) -> tuple[int, ...]:
    picked = sorted({DAY_WORDS.index(str(each).lower()[:3]) for each in found or [] if str(each).lower()[:3] in DAY_WORDS})
    return () if len(picked) == 7 else tuple(picked)


def _steps(found) -> list[str]:
    said = [str(each).strip() for each in found or [] if str(each).strip()]
    return [each[:1].upper() + each[1:] for each in said]


def _name(text: str) -> str:
    text = text.strip()
    for tail in (" routine", " Routine"):
        text = text.removesuffix(tail)
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------
# The card in the hub, the list, and what extraction is told
# ---------------------------------------------------------------------------
async def today_of(user_id: int) -> list[rules.Today]:
    day = days.today()
    return rules.due(await every(user_id), await store.ticked(user_id, day), day)


async def hub_card(user_id: int) -> Card | None:
    found = await today_of(user_id)
    if not found:
        return None
    return Card(rules.text(found), rules.buttons(found), rules.layout(found))


def changed(user_id: int) -> None:
    hubcard.changed(TASK, user_id, lambda: hub_card(user_id))
    summaries.changed(TASK, user_id)
    attention.changed()


async def post_job(job) -> None:
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    posted = await hubcard.post(TASK, user_id, lambda: hub_card(user_id))
    scheduler.note(job, "posted" if posted is not None else "not posted: no personal routine today")


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    return LiveReply(LIST_KEY, rules.listed(await every(request.user.id)))


async def state(request: Request) -> State:
    day = days.today()
    ticked = await store.ticked(request.user.id, day)
    lines = [
        f"{each.name} ({rules.days_text(each.weekdays)}; steps: " + ", ".join(f"{step.text}{' (done today)' if step.id in ticked else ''}" for step in each.steps) + ")"
        for each in await every(request.user.id)
    ]
    return State("The user's personal routines now", tuple(lines), "none")


async def item_names(request: Request) -> list[str]:
    habits = await every(request.user.id)
    return [*(each.name for each in habits), *(step.text for each in habits for step in each.steps)]


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


def _which_step(found: list[rules.Today], wanted: str, want_ticked: bool) -> tuple[rules.Today, Step]:
    """The step a name means, among today's routines: one still to do for a tick,
    one ticked for an untick. Two that fit are said, never guessed."""
    pairs = [(each, step) for each in found for step in each.habit.steps if (step.id in each.ticked) == want_ticked]
    if not pairs:
        raise UserError("Nothing is ticked off today." if want_ticked else "Every step of today's routines is done.")
    try:
        return names.find(pairs, wanted, lambda pair: pair[1].text)
    except names.Unknown:
        raise UserError(f"No step “{wanted}” is {'ticked off' if want_ticked else 'left'} today.")
    except names.Ambiguous as which:
        raise UserError(f"“{wanted}” could be {' or '.join(f'**{pair[1].text}** ({pair[0].habit.name})' for pair in which.candidates[:4])}: say which.")


# ---------------------------------------------------------------------------
# Make, change, remove: cards
# ---------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    name = _name(str(data.get("routine") or ""))
    if not name:
        raise UserError("What is the routine called?")
    steps = _steps(data.get("steps"))
    if not steps:
        raise UserError(f"What are the steps of {name}?")
    if len(steps) > rules.MAX_STEPS:
        raise UserError(f"A routine has at most {rules.MAX_STEPS} steps.")
    if any(each.name.lower() == name.lower() for each in await every(request.user.id)):
        raise UserError(f"You have a routine called **{name}** already: say what to change in it.")
    weekdays = _weekdays(data.get("days"))
    lines = (flag(f"**{name}** · {rules.days_text(weekdays)}", is_guessed(guessed, "days")), rules.steps_text(steps))
    return Proposal(lines=lines, data={"name": name, "weekdays": list(weekdays), "steps": steps}, kind="new")


async def add_save(request: Request, data: dict) -> str:
    await request.db.run(store.db_add, request.user.id, data["name"], tuple(data["weekdays"]), data["steps"], clock.now())
    changed(request.user.id)
    return f"✅ Saved · {ICON} **{data['name']}** · {rules.days_text(tuple(data['weekdays']))} · {len(data['steps'])} steps"


async def add_check(request: Request, data: dict) -> str:
    there = [each for each in await every(request.user.id) if each.name == data["name"]]
    return "" if there and [step.text for step in there[0].steps] == data["steps"] else "the routine is not as the card said"


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    habits = await every(request.user.id)
    wanted = str(data.get("routine") or "")
    if is_reference(wanted) or not wanted.strip():
        if len(habits) != 1:
            raise UserError("Which routine?")
        habit = habits[0]
    else:
        habit = find(habits, wanted)
    steps = [step.text for step in habit.steps]
    named = _steps(data.get("steps"))
    change = data.get("steps_change") or ADD
    if named:
        if change == SET:
            steps = named
        elif change == REMOVE:
            gone = {each.lower() for each in named}
            missing = [each for each in named if each.lower() not in {step.lower() for step in steps}]
            if missing:
                raise UserError(f"{habit.name} has no step {', '.join(f'“{each}”' for each in missing)}.")
            steps = [each for each in steps if each.lower() not in gone]
        else:
            steps = steps + [each for each in named if each.lower() not in {step.lower() for step in steps}]
    weekdays = _weekdays(data.get("days")) if data.get("days") else habit.weekdays
    name = _name(str(data.get("new_name") or "")) or habit.name
    differs = []
    if name != habit.name:
        differs.append(f"name · {habit.name} → {name}")
    if weekdays != habit.weekdays:
        differs.append(f"days · {rules.days_text(habit.weekdays)} → {rules.days_text(weekdays)}")
    if steps != [step.text for step in habit.steps]:
        if not steps:
            raise UserError("That leaves no step at all: remove the routine instead.")
        differs.append(f"steps · {len(habit.steps)} → {len(steps)}")
        differs.append(design_steps(steps))
    if not differs:
        raise UserError(f"**{habit.name}** is already like that.")
    return Proposal(lines=(flag(f"**{habit.name}**", is_guessed(guessed, "routine")), *differs), data={"id": habit.id, "name": name, "weekdays": list(weekdays), "steps": steps}, kind="change")


def design_steps(steps: list[str]) -> str:
    return f"-# {rules.steps_text(steps)}"


async def change_save(request: Request, data: dict) -> str:
    now = clock.now()

    def write(conn):
        store.db_change(conn, data["id"], data["name"], tuple(data["weekdays"]))
        store.db_set_steps(conn, request.user.id, data["id"], data["steps"], now)

    await request.db.run(write)
    changed(request.user.id)
    return f"✅ Saved · {ICON} **{data['name']}** · {rules.days_text(tuple(data['weekdays']))} · {rules.steps_text(data['steps'])}"


async def change_check(request: Request, data: dict) -> str:
    there = next((each for each in await every(request.user.id) if each.id == data["id"]), None)
    if there is None or there.name != data["name"] or [step.text for step in there.steps] != data["steps"] or list(there.weekdays) != data["weekdays"]:
        return "the routine is not as the card said"
    return ""


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    habit = find(await every(request.user.id), str(data.get("routine") or ""))
    return Proposal(lines=(flag(f"**{habit.name}** → removed", is_guessed(guessed, "routine")), f"-# {len(habit.steps)} steps, {rules.days_text(habit.weekdays)}"), data={"id": habit.id, "name": habit.name}, kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    await request.db.run(store.db_remove, data["id"], clock.now())
    changed(request.user.id)
    return f"🗑️ Removed **{data['name']}**"


async def remove_check(request: Request, data: dict) -> str:
    return "the routine is still there" if any(each.id == data["id"] for each in await every(request.user.id)) else ""


# ---------------------------------------------------------------------------
# Ticking a step off, and back: a log, at once
# ---------------------------------------------------------------------------
def _progress_line(found: list[rules.Today], habit_id: int) -> str:
    today = next(each for each in found if each.habit.id == habit_id)
    if today.finished:
        return f"{today.habit.name} done"
    return f"{today.habit.name} {today.done}/{today.total}" + (f" · next: {today.next_step.text}" if today.next_step else "")


async def tick(request: Request, data: dict, guessed: frozenset) -> str:
    day, now = days.today(), clock.now()
    found = await today_of(request.user.id)
    if not found:
        raise UserError("No personal routine is on today.")
    ticked = []
    for wanted in _steps(data.get("steps")) or [""]:
        today, step = _which_step(found, wanted, want_ticked=False) if wanted else (found[0], found[0].next_step)
        if step is None:
            raise UserError("Which step?")
        await request.db.run(store.db_tick, request.user.id, step.id, day, now)
        ticked.append((today.habit.id, step))
    after = await today_of(request.user.id)
    if any(step.id not in next(each for each in after if each.habit.id == habit_id).ticked for habit_id, step in ticked):
        raise UserError("Could not tick it off.")
    changed(request.user.id)
    return f"✅ {', '.join(f'**{step.text}**' for _, step in ticked)} · {_progress_line(after, ticked[-1][0])}"


async def untick(request: Request, data: dict, guessed: frozenset) -> str:
    day = days.today()
    found = await today_of(request.user.id)
    back = []
    for wanted in _steps(data.get("steps")):
        today, step = _which_step(found, wanted, want_ticked=True)
        await request.db.run(store.db_untick, step.id, day)
        back.append((today.habit.id, step))
    if not back:
        raise UserError("Which step?")
    after = await today_of(request.user.id)
    changed(request.user.id)
    return f"↩️ {', '.join(f'**{step.text}**' for _, step in back)} · not done · {_progress_line(after, back[-1][0])}"


async def on_tick(press: cards.Press) -> str:
    """The button under a routine on the card: its next step is done."""
    step = await press.db.run(store.db_step, int(press.arg)) if press.arg.isdigit() else None
    if step is None:
        changed(press.user.id)
        return "gone"
    fresh = await press.db.run(store.db_tick, step[0], int(press.arg), days.today(), clock.now())
    changed(press.user.id)
    return f"✅ {step[2]}" if fresh else "already dealt with"


_ROUTINE = Field("routine", _WHICH)


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    return [
        Action(
            "habit_add",
            "Make a personal routine (\"make a morning routine: stretch, water, journal, on weekdays\" -> routine morning, steps stretch water journal, days mon tue wed thu fri).",
            (Field("routine", "Its name, as the user said it (\"morning\").", required=True), Field("steps", "Its steps, in order, in the user's words.", LIST, required=True), Field("days", _DAYS + " Leave out for every day.", LIST, choices=DAY_WORDS)),
            prepare=add_card, apply=add_save, verify=add_check, purpose=SET_UP, say=("make a morning routine: stretch, water, journal",),
        ),
        Action(
            "habit_change",
            "Change a personal routine: add steps (\"add meditate to my morning routine\" -> steps meditate, steps_change add), take steps out (steps_change remove), give all its steps (set), its days, or a new name.",
            (_ROUTINE, Field("steps", "The steps named, in the user's words.", LIST), Field("steps_change", "add: these as well. remove: not these. set: exactly these. Leave out for add.", choices=(ADD, REMOVE, SET)), Field("days", _DAYS, LIST, choices=DAY_WORDS), Field("new_name", "A new name, only if the user gave one.")),
            prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("add meditate to my morning routine",),
        ),
        Action("habit_remove", "Remove a personal routine (\"remove my evening routine\").", (Field("routine", _WHICH, required=True),), prepare=remove_card, apply=remove_save, verify=remove_check, purpose=SET_UP, say=("remove my evening routine",)),
        Action("habit_tick", "One or more steps of today's personal routines are done (\"did stretch\", \"done water and journal\"). A log: no card.", (_ROUTINE, Field("steps", "Each step done, in the user's words.", LIST)), needs_card=False, run=tick, purpose=EACH_DAY, say=("did stretch",)),
        Action("habit_untick", "A step ticked off by mistake is not done after all (\"undo stretch\").", (_ROUTINE, Field("steps", "Each step that is not done after all.", LIST, required=True)), needs_card=False, run=untick, purpose=EACH_DAY, say=("undo stretch",)),
        Action("habit_show", "The user asks what personal routines they have (\"my routines\").", needs_card=False, run=show, purpose=SEE, say=("my routines",)),
    ]
