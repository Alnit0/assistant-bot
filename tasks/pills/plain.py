from datetime import date

from core import day, livelists, occurrences, timeinput
from core.actions import BOOLEAN, INTEGER, ITEMS, Action, Field, LiveReply, Proposal, Request, State, flag, is_guessed
from core.errors import UserError
from tasks.pills import rules, store
from tasks.pills.rules import ACTIVE, ENDED, PAUSED, REMOVED, Pill, Plan, TimeQuestion

# ---------------------------------------------------------------------------
# Setting pills up in plain words (core/actions.py): guess, show, confirm.
#
# Claude fills in what was said; the code here reads it into a plan with
# tasks/pills/rules.py, shows its best reading on a confirm card, and only
# Save writes it. Nothing is asked before the card: a time that could be
# morning or evening is taken as the morning and marked ❓. A reply changes
# the card: the code lays the change over what the card holds.
#
# Every action takes a list of pills, so "pause iron and vitamin D" is one
# card. No discord.py and no Context: the same code runs for a message and
# for the press of Save.
# ---------------------------------------------------------------------------
TASK = "pills"
ICON = "💊"
LIST_KEY = "pills"
ONLY_FOR = (
    "Pills, vitamins, supplements and medicines the user takes: setting one up, changing when or how it "
    "is taken, pausing, resuming or removing it, and listing them. Not shopping for them, and not timers, "
    "general reminders or to-dos."
)
EXAMPLES = ("add vitamin D once a day with food", "move the evening pill to 9pm", "pause iron until the 20th")
HINT = "Try saying its name and when you take it, e.g. “add iron at 8am”."

PLAN_FIELDS = ("name", "dose", "notes", "times", "per_day", "min_gap", "start", "end", "days")
TRIES = rules.MAX_PER_DAY + 1


# ---------------------------------------------------------------------------
# From what was said to a plan
# ---------------------------------------------------------------------------
def overlay(pending: list[dict], items: list[dict], key: str) -> tuple[list[dict], list[str]]:
    """An open card's pills with a message's changes laid over them: (the
    pills as they now stand, the names it was asked to take off that weren't
    on it). A pill named again keeps what it had and takes what is new; one
    with `remove` leaves the card. Pure."""
    merged = [dict(item) for item in pending]
    missing: list[str] = []
    for item in items:
        name = str(item[key]).strip().lower()
        at = next((index for index, held in enumerate(merged) if str(held[key]).strip().lower() == name), None)
        if item.get("remove"):
            if at is None:
                missing.append(str(item[key]))
            else:
                merged.pop(at)
            continue
        rest = {field: value for field, value in item.items() if field != "remove"}
        if at is None:
            merged.append(rest)
        else:
            merged[at] = {**merged[at], **rest}
    return merged, missing


def as_request(item: dict) -> rules.Request:
    return rules.Request(**{name: str(item[name]) for name in PLAN_FIELDS if item.get(name) not in (None, "")})


def settle(request: rules.Request, today: date, base: Plan | None = None) -> tuple[Plan, rules.Request, bool]:
    """The plan a request makes, never asking: a time that could be morning or
    evening is read as the morning, and the last value says a guess was made.
    Also the request with those times settled, which is what Save applies."""
    guessed = False
    for _ in range(TRIES):
        try:
            return rules.build(request, today, base), request, guessed
        except TimeQuestion as question:
            request = rules.answer(request, question, question.options[0])
            guessed = True
    raise UserError("I couldn't read those times.")


def _unsure(data: dict, guessed: frozenset, key: str) -> set[str]:
    """The pills of this message that Claude guessed something about."""
    fields_ = [key, *PLAN_FIELDS, "until"]
    return {
        str(item[key]).strip().lower()
        for index, item in enumerate(data["pills"])
        if is_guessed(guessed, "pills", index) or any(is_guessed(guessed, "pills", index, name) for name in fields_)
    }


def _line(plan: Plan) -> str:
    return rules.describe(plan, "").strip()


def _changed(user_id: int) -> None:
    """The pills changed: the list last shown on request is brought up to date in place."""

    async def render() -> str:
        return rules.list_text(await store.pills(user_id), day.today())

    livelists.changed(user_id, LIST_KEY, render)


def _resolve(pills: list[Pill], items: list[dict]) -> tuple[list[tuple[dict, Pill]], list[str]]:
    """Each item with the pill it means (its `pill` set to that pill's id), and
    what couldn't be found, in words."""
    found, problems = [], []
    for item in items:
        try:
            pill = rules.find(pills, str(item.get("pill", "")))
        except UserError as error:
            problems.append(str(error))
            continue
        found.append(({**item, "pill": pill.ref}, pill))
    return found, problems


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    today = day.today()
    existing = await store.pills(request.user.id)
    items, missing = overlay(request.previous["pills"] if request.previous else [], data["pills"], "name")
    unsure = _unsure(data, guessed, "name")
    lines, kept, warnings = [], [], [f"{name} isn't on the card: nothing to take off" for name in missing]
    seen: set[str] = set()
    own_guesses: list[str] = []
    for item in items:
        name = str(item["name"]).strip()
        try:
            plan, settled, time_guess = settle(as_request(item), today)
            rules.check_name(plan, existing)
            if plan.name.lower() in seen:
                raise UserError("it is on this card twice")
        except UserError as error:
            warnings.append(f"Not included: {name} ({error})")
            continue
        seen.add(plan.name.lower())
        lines.append(flag(_line(plan), time_guess or name.lower() in unsure))
        if time_guess:
            own_guesses.append(f"pills[{len(kept)}].times")
        kept.append({**item, "times": settled.times} if settled.times else dict(item))
    if not kept:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "No pill to add.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="new", guessed=tuple(own_guesses))


async def add_save(request: Request, data: dict) -> str:
    today = day.today()
    user_id = request.user.id

    def save(conn) -> list[Pill]:
        # Checked again here, in the same transaction as the write: the list may
        # have changed since the card was shown
        saved = []
        for item in data["pills"]:
            plan = rules.build(as_request(item), today)
            rules.check_name(plan, store.db_pills(conn, user_id))
            saved.append(store.db_add(conn, user_id, plan))
        return saved

    saved = await request.db.run(save)
    _changed(user_id)
    if len(saved) == 1:
        return f"✅ Saved · {rules.describe_pill(saved[0], today)}"
    return f"✅ Saved · {ICON} {len(saved)} pills added: " + ", ".join(f"**{pill.plan.name}**" for pill in saved)


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------
async def edit_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    today = day.today()
    existing = await store.pills(request.user.id)
    unsure = _unsure(data, guessed, "pill")
    found, problems = _resolve(existing, data["pills"])
    resolved = [item for item, _ in found]
    items, missing = overlay(request.previous["pills"] if request.previous else [], resolved, "pill")
    by_ref = {pill.ref: pill for pill in existing}
    asked_as = {item["pill"]: str(raw.get("pill", "")).strip().lower() for (item, _), raw in zip(found, data["pills"])}
    lines, kept, warnings = [], [], [*problems, *[f"{name} isn't on the card: nothing to take off" for name in missing]]
    own_guesses: list[str] = []
    for item in items:
        pill = by_ref.get(item["pill"])
        if pill is None:
            continue
        try:
            plan, settled, time_guess = settle(as_request(item), today, pill.plan)
            rules.check_name(plan, existing, own_id=pill.id)
        except UserError as error:
            warnings.append(f"Not included: {pill.plan.name} ({error})")
            continue
        if plan == pill.plan:
            warnings.append(f"{pill.plan.name}: nothing would change")
            continue
        mark = time_guess or asked_as.get(item["pill"], "") in unsure
        lines += [f"**{pill.plan.name}**", f"Now: {_line(pill.plan)}", flag(f"New: {_line(plan)}", mark)]
        if time_guess:
            own_guesses.append(f"pills[{len(kept)}].times")
        kept.append({**item, "times": settled.times} if settled.times and item.get("times") else dict(item))
    if not kept:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "Nothing to change.")
    lines.append("-# Applies from the next dose. What is already recorded stays as it is.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="edit", guessed=tuple(own_guesses))


async def edit_save(request: Request, data: dict) -> str:
    today = day.today()
    user_id = request.user.id

    def save(conn) -> list[Pill]:
        saved = []
        for item in data["pills"]:
            pill = rules.find(store.db_pills(conn, user_id), item["pill"])
            plan = rules.build(as_request(item), today, pill.plan)
            rules.check_name(plan, store.db_pills(conn, user_id), own_id=pill.id)
            saved.append(store.db_edit(conn, pill.id, plan))
        return saved

    saved = await request.db.run(save)
    _changed(user_id)
    if len(saved) == 1:
        return f"✅ Updated · {rules.describe_pill(saved[0], today)}"
    return f"✅ Updated · {ICON} {len(saved)} pills: " + ", ".join(f"**{pill.plan.name}**" for pill in saved)


# ---------------------------------------------------------------------------
# Pause, resume, remove, delete: each a card naming the pills it is about
# ---------------------------------------------------------------------------
async def _chosen(
    request: Request, data: dict, guessed: frozenset = frozenset()
) -> tuple[list[tuple[dict, Pill]], list[str], date, set[str]]:
    """The pills a card is about, once this message is taken in: (each item
    with its pill, what couldn't be found, today, the ids Claude guessed at)."""
    existing = await store.pills(request.user.id)
    found, problems = _resolve(existing, data["pills"])
    resolved = [item for item, _ in found]
    items, missing = overlay(request.previous["pills"] if request.previous else [], resolved, "pill")
    by_ref = {pill.ref: pill for pill in existing}
    chosen = [(item, by_ref[item["pill"]]) for item in items if item["pill"] in by_ref]
    unsure = _unsure(data, guessed, "pill")
    marked = set()
    for raw in data["pills"]:
        if str(raw.get("pill", "")).strip().lower() not in unsure:
            continue
        try:
            marked.add(rules.find(existing, str(raw["pill"])).ref)
        except UserError:
            continue
    warnings = [*problems, *[f"{name} isn't on the card: nothing to take off" for name in missing]]
    return chosen, warnings, day.today(), marked


def _none_left(warnings: list[str], otherwise: str) -> UserError:
    return UserError("; ".join(warnings) or otherwise)


async def pause_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    chosen, warnings, today, marked = await _chosen(request, data, guessed)
    lines, kept = [], []
    for item, pill in chosen:
        name = pill.plan.name
        if rules.status_on(pill, today) == ENDED:
            warnings.append(f"{name} has ended: there is nothing to pause")
            continue
        until = None
        if str(item.get("until", "")).strip():
            try:
                until = timeinput.parse_date(str(item["until"]), today)
            except UserError as error:
                warnings.append(f"Not included: {name} ({error})")
                continue
            if until <= today:
                warnings.append(f"Not included: {name} (a pause ends on a later day than today)")
                continue
        when = f"paused until {timeinput.format_date(until)}" if until else "paused until you resume it"
        lines.append(flag(f"**{name}** · {when}", pill.ref in marked))
        kept.append({"pill": pill.ref, **({"until": until.isoformat()} if until else {})})
    if not kept:
        raise _none_left(warnings, "No pill to pause.")
    lines.append("-# It won't be asked for while paused, and its streak is unaffected.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="pause")


async def pause_save(request: Request, data: dict) -> str:
    done = []
    for item in data["pills"]:
        pill = rules.find(await store.pills(request.user.id), item["pill"])
        until = date.fromisoformat(item["until"]) if item.get("until") else None
        await store.set_status(pill.id, PAUSED, until)
        done.append(f"**{pill.plan.name}** paused" + (f" until {timeinput.format_date(until)}" if until else ""))
    _changed(request.user.id)
    return "⏸️ " + ", ".join(done) + "."


async def resume_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    chosen, warnings, today, marked = await _chosen(request, data, guessed)
    lines, kept = [], []
    for item, pill in chosen:
        if rules.status_on(pill, today) != PAUSED:
            warnings.append(f"{pill.plan.name} isn't paused")
            continue
        lines.append(flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)}", pill.ref in marked))
        kept.append({"pill": pill.ref})
    if not kept:
        raise _none_left(warnings, "No pill to resume.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="resume")


async def resume_save(request: Request, data: dict) -> str:
    done = []
    for item in data["pills"]:
        pill = rules.find(await store.pills(request.user.id), item["pill"])
        await store.set_status(pill.id, ACTIVE)
        done.append(f"**{pill.plan.name}**")
    _changed(request.user.id)
    return f"▶️ {', '.join(done)} resumed."


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    chosen, warnings, today, marked = await _chosen(request, data, guessed)
    if not chosen:
        raise _none_left(warnings, "No pill to remove.")
    lines = [flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)}", pill.ref in marked) for _, pill in chosen]
    lines.append("-# This stops its reminders. Its history is kept.")
    return Proposal(
        lines=tuple(lines), data={"pills": [{"pill": pill.ref} for _, pill in chosen]}, warnings=tuple(warnings),
        kind="remove", confirm_label="Remove",
    )


async def remove_save(request: Request, data: dict) -> str:
    done = []
    for item in data["pills"]:
        pill = rules.find(await store.pills(request.user.id), item["pill"])
        await store.set_status(pill.id, REMOVED)
        done.append(f"**{pill.plan.name}**")
    _changed(request.user.id)
    return f"🗑️ Removed {', '.join(done)}. " + ("Its history is kept." if len(done) == 1 else "Their history is kept.")


async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    chosen, warnings, today, marked = await _chosen(request, data, guessed)
    if not chosen:
        raise _none_left(warnings, "No pill to delete.")
    lines = tuple(flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)}", pill.ref in marked) for _, pill in chosen)
    return Proposal(
        lines=lines, data={"pills": [{"pill": pill.ref} for _, pill in chosen]},
        warnings=(*warnings, "This deletes the history too and can't be undone"),
        kind="delete", destructive=True, confirm_label="Delete for good",
    )


async def delete_save(request: Request, data: dict) -> str:
    user_id = request.user.id

    def delete(conn) -> list[str]:
        names = []
        for item in data["pills"]:
            pill = rules.find(store.db_pills(conn, user_id), item["pill"])
            occurrences.db_delete_item(conn, TASK, pill.id)
            store.db_delete(conn, pill.id)
            names.append(f"**{pill.plan.name}**")
        return names

    names = await request.db.run(delete)
    _changed(user_id)
    return f"🗑️ Deleted {', '.join(names)} and " + ("its history." if len(names) == 1 else "their history.")


# ---------------------------------------------------------------------------
# The list, and what extraction is told
# ---------------------------------------------------------------------------
async def show_list(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    # Read-only, no buttons. Live: this copy is rewritten in place when a pill changes
    return LiveReply(LIST_KEY, rules.list_text(await store.pills(request.user.id), day.today()))


async def state(request: Request) -> State:
    today = day.today()
    shown = rules.listed(await store.pills(request.user.id))
    return State(
        "The user's pills now (use the id, or the name)",
        tuple(f"{pill.ref}: {rules.plain(rules.describe_pill(pill, today))} [{rules.status_on(pill, today)}]" for pill in shown),
        empty="none yet",
    )


# ---------------------------------------------------------------------------
# The actions
# ---------------------------------------------------------------------------
AS_SAID = (
    "exactly as the user said it (8, 8pm, 20:00, tomorrow, the 20th): never convert it, never add am or "
    "pm, never work out a date. The code reads it."
)
_PLAN_FIELDS = (
    Field("dose", "How much each time, e.g. 1 tablet. Leave out if not said."),
    Field("notes", "Instructions, e.g. with food. Leave out if not said."),
    Field(
        "times",
        "The time of each dose, separated by commas, " + AS_SAID + " E.g. \"8am, 8pm\". With min_gap, at most "
        "one: the time of the first dose. Leave out for a pill with no set time.",
    ),
    Field("per_day", "How many doses a day, if said. Not needed when a time is given for each dose.", INTEGER),
    Field(
        "min_gap",
        "The least time between doses, with its unit: 3h, 90m. Only for a pill taken several times a day at "
        "least so long apart; then per_day is needed too (your best guess, listed as guessed, if not said).",
    ),
    Field("start", "For a course only: its first day, " + AS_SAID),
    Field("end", "For a course only: its last day, " + AS_SAID),
    Field("days", "For a course only: how many days it lasts, in place of end.", INTEGER),
)
_OFF_THE_CARD = Field(
    "remove",
    "Only in a follow-up to an open card: true to take this pill off the card (\"not the iron\").",
    BOOLEAN,
)
_WHICH = Field("pill", "Which pill: its id from the state given with the message (pl3), or its name as the user said it.", required=True)


def _one_or_more(what: str, *fields_: Field) -> tuple[Field, ...]:
    return (Field("pills", f"Each pill {what}, one item each, in the order said.", ITEMS, required=True, item_fields=fields_),)


ACTIONS = (
    Action(
        "pill_add",
        "Set up a new pill, vitamin, supplement or medicine. Examples: \"add vitamin D once a day with food\" "
        "-> name Vitamin D, notes with food. \"add iron at 8\" -> name Iron, times 8. \"add course A, 3 times a "
        "day, at least 3 hours apart, with food, for 7 days starting tomorrow\" -> name Course A, per_day 3, "
        "min_gap 3h, notes with food, start tomorrow, days 7. \"a new pill called A at 9am, 12pm and 3pm\" -> "
        "name A, times \"9am, 12pm, 3pm\". A pill with no end has no dates: leave start, end and days out. In "
        "a follow-up (\"8pm\", \"make it twice a day\"), give the pill by the name on the card and only what "
        "changes. A time said in a follow-up REPLACES the card's time (card shows 08:00, user says \"8pm\" -> "
        "times 8pm, never \"08:00, 8pm\"), unless the user says to add another dose.",
        _one_or_more(
            "to add",
            Field("name", "What it is called, as the user said it, e.g. Vitamin D.", required=True),
            *_PLAN_FIELDS,
            _OFF_THE_CARD,
        ),
        prepare=add_card,
        apply=add_save,
    ),
    Action(
        "pill_edit",
        "Change a pill the user already has: its name, dose, notes, times, how often, the gap or its dates. "
        "Give only what changes. To take something away give \"none\" for it (notes none; times none makes it "
        "untimed; end none makes it go on with no end). Examples: \"move the evening pill to 9pm\" -> pill "
        "Evening pill, times 9pm. \"vitamin D is 2 tablets now\" -> dose 2 tablets.",
        _one_or_more("to change", _WHICH, Field("name", "A new name for it, if it is being renamed."), *_PLAN_FIELDS, _OFF_THE_CARD),
        prepare=edit_card,
        apply=edit_save,
    ),
    Action(
        "pill_pause",
        "Pause a pill: it stops being asked for until resumed. \"pause iron\" -> pill iron. \"pause iron until "
        "the 20th\" -> until the 20th (the day it is taken again).",
        _one_or_more("to pause", _WHICH, Field("until", "The day it is taken again, " + AS_SAID + " Leave out for no end."), _OFF_THE_CARD),
        prepare=pause_card,
        apply=pause_save,
    ),
    Action(
        "pill_resume",
        "Take a paused pill again (\"resume iron\", \"start iron again\").",
        _one_or_more("to resume", _WHICH, _OFF_THE_CARD),
        prepare=resume_card,
        apply=resume_save,
    ),
    Action(
        "pill_remove",
        "Remove a pill the user no longer takes, keeping its history (\"remove iron\", \"I've stopped taking "
        "iron\"). This is the usual one.",
        _one_or_more("to remove", _WHICH, _OFF_THE_CARD),
        prepare=remove_card,
        apply=remove_save,
    ),
    Action(
        "pill_delete",
        "Delete a pill TOGETHER WITH its history. Only when the user says so in as many words (\"delete iron "
        "and its history\", \"delete it completely\"); otherwise use pill_remove.",
        _one_or_more("to delete", _WHICH, _OFF_THE_CARD),
        prepare=delete_card,
        apply=delete_save,
    ),
    Action(
        "pill_list",
        "The user asks what pills they have or when they take them (\"show all my pills\", \"what do I take?\").",
        needs_card=False,
        run=show_list,
    ),
)
