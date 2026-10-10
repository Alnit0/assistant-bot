from dataclasses import dataclass, field, replace
from datetime import date

from core import day, livelists, occurrences, timeinput
from core.actions import BOOLEAN, INTEGER, ITEMS, LAST, MINUTES, TIME, TIMES, Action, Field, LiveReply, Proposal, Request, State
from core.actions import flag, is_guessed
from core.actions import is_reference, point_at
from core.errors import UserError
from tasks.pills import rules, store
from tasks.pills.rules import ACTIVE, ENDED, PAUSED, REMOVED, Pill, Plan, TimeQuestion

# ---------------------------------------------------------------------------
# Setting pills up in plain words (core/actions.py): guess, show, confirm.
#
# Claude fills in what was said; the code here reads it into a plan with
# tasks/pills/rules.py, shows its best reading on a confirm card, and only
# Save writes it. Nothing is asked before the card: a time that could be
# morning or evening is taken as the morning (a latest time as the evening)
# and marked ❓. A planned time too close to the one before is moved, and the
# card says so. A schedule that can't fit in a day is shown as it was read
# with the reason, and a part that can't be read at all is marked ❔ with the
# reason beside everything that was understood: either way the card has no
# Save until a reply puts it right. A reply changes the card: the code lays
# the change over what the card holds.
#
# Claude gives times in the one fixed form and lengths of time as minutes
# (core/actions.py: TIMES, TIME, MINUTES), so nothing here reads free text
# that could have come structured; what arrives in another form is still
# read where it can be.
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

PLAN_FIELDS = ("name", "dose", "notes", "times", "per_day", "min_gap", "latest", "start", "end", "days")
# Where an item of the action calls a part of the plan something else
ITEM_KEYS = {"min_gap": "min_gap_minutes"}
# A part of the plan, as a card names it when it couldn't be read
UNREAD = {
    "times": "times", "per_day": "doses a day", "min_gap": "gap", "latest": "latest time",
    "start": "start", "end": "end", "days": "days",
}
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
    """An item as extraction gives it, in the words rules.build reads: the
    times joined up, the gap's minutes with their unit."""
    said = {}
    for name in PLAN_FIELDS:
        value = item.get(ITEM_KEYS.get(name, name))
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(each) for each in value)
        elif name == "min_gap" and isinstance(value, int):
            value = f"{value}m" if value else "none"
        said[name] = str(value)
    return rules.Request(**said)


@dataclass
class Read:
    """What was made of one pill's request, never asking."""

    plan: Plan  # everything that was understood
    request: rules.Request  # with the times that were guessed settled: what Save applies
    guessed: bool = False  # a time that could be morning or evening was taken as one of them
    moved: list[str] = field(default_factory=list)  # a line for each planned time moved to keep the gap
    unread: list[tuple[str, str]] = field(default_factory=list)  # (which part, why) for each part that couldn't be read
    unfit: str = ""  # why the doses can't fit in a day, if they can't

    @property
    def held(self) -> bool:
        """Whether something has to be put right before this can be saved."""
        return bool(self.unread or self.unfit)


def settle(request: rules.Request, today: date, base: Plan | None = None) -> Read:
    """The plan a request makes, never asking and never stopping at the first
    thing wrong: a time that could be morning or evening is read as the
    morning (a latest time as the evening) and marked as a guess; a part that
    can't be read is set aside with its reason and the rest is still read; a
    schedule that can't fit is kept as read with its reason. Raises UserError
    only for what leaves nothing to show."""
    guessed, unread = False, []
    for _ in range(TRIES + len(PLAN_FIELDS)):
        moved: list[str] = []
        try:
            return Read(rules.build(request, today, base, moved), request, guessed, moved, unread)
        except TimeQuestion as question:
            request = rules.answer(request, question, question.options[question.field == "latest"])
            guessed = True
        except rules.Unreadable as problem:
            unread.append((problem.field, str(problem)))
            request = replace(request, **{problem.field: ""})
        except rules.DoesNotFit as problem:
            return Read(problem.plan, request, guessed, moved, unread, str(problem))
    raise UserError("I couldn't read those times.")


def _known(existing: list[Pill], name: str) -> Pill | None:
    """The pill the user already has by exactly this name, whatever the case."""
    wanted = name.strip().lower()
    return next((pill for pill in rules.listed(existing) if pill.plan.name.lower() == wanted), None)


def _change(item: dict) -> rules.Request:
    """What an item says about a pill that is already there: everything but its name."""
    return as_request({part: value for part, value in item.items() if part not in ("name", "pill")})


def _already(pill: Pill) -> str:
    return f"**{pill.plan.name}** is already in your pills with these settings"


def _held_lines(read: Read) -> list[str]:
    """A line for each part that couldn't be read: marked ❔, with the reason."""
    return [f"❔ {UNREAD[part]} · {reason}" for part, reason in read.unread]


def _held_warnings(read: Read) -> list[str]:
    return [*read.moved, *([f"{read.plan.name} can't be saved yet: {read.unfit}"] if read.unfit else [])]


def _unsure(data: dict, guessed: frozenset, key: str) -> set[str]:
    """The pills of this message that Claude guessed something about."""
    fields_ = [key, *(ITEM_KEYS.get(name, name) for name in PLAN_FIELDS), "until"]
    return {
        str(item[key]).strip().lower()
        for index, item in enumerate(data["pills"])
        if is_guessed(guessed, "pills", index) or any(is_guessed(guessed, "pills", index, name) for name in fields_)
    }


def _line(plan: Plan) -> str:
    return rules.describe(plan, "").strip()


def _settled(item: dict, settled: rules.Request) -> dict:
    """An item with the times the code settled in place of the ones said, so
    Save applies what the card showed."""
    fixed = dict(item)
    if item.get("times") and settled.times:
        fixed["times"] = rules.split_times(settled.times)
    if item.get("latest") and settled.latest:
        fixed["latest"] = settled.latest
    return fixed


def _changed(user_id: int) -> None:
    """The pills changed: the list last shown on request is brought up to date in place."""

    async def render() -> str:
        return rules.list_text(await store.pills(user_id), day.today())

    livelists.changed(user_id, LIST_KEY, render)


async def _pointed(request: Request, items: list[dict], key: str) -> tuple[list[dict], str | None]:
    """The items with "it" given the pill it stands for, resolved here and never
    by Claude: the pill mentioned last on the open card; with no card, the
    pill changed last, which is a guess and comes back as the second value.
    A new pill can't be "it": there is nothing it could mean."""
    if not any(is_reference(item.get(key)) for item in items):
        return items, None
    previous = request.previous or {}
    held = previous.get("pills", [])
    last = previous.get(LAST) or (held[-1].get(key) if held else None)
    taken_as = None
    if last is None and key == "pill":
        changed = await request.db.run(store.db_last_changed, request.user.id)
        last = taken_as = f"{rules.ID_PREFIX}{changed}" if changed is not None else None
    return point_at(items, key, last), taken_as


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
    asked, _ = await _pointed(request, data["pills"], "name")
    items, missing = overlay(request.previous["pills"] if request.previous else [], asked, "name")
    unsure = _unsure(data, guessed, "name")
    lines, kept, warnings = [], [], [f"{name} isn't on the card: nothing to take off" for name in missing]
    seen: set[str] = set()
    own_guesses: list[str] = []
    held, changes = False, 0
    for item in items:
        name = str(item["name"]).strip()
        pill = _known(existing, name)
        try:
            if pill is not None:
                # Already one of the user's pills: what was said is a change to it, never a second pill
                read = settle(_change(item), today, pill.plan)
            else:
                read = settle(as_request(item), today)
                rules.check_name(read.plan, existing)
            if read.plan.name.lower() in seen:
                raise UserError("it is on this card twice")
        except UserError as error:
            warnings.append(f"Not included: {name} ({error})")
            continue
        seen.add(read.plan.name.lower())
        if pill is not None and read.plan == pill.plan and not read.held:
            warnings.append(_already(pill))
            continue
        if pill is not None:
            # One format for a change, on whichever card it is: field · old → new
            lines.append(flag(f"**{pill.plan.name}** · already in your pills", name.lower() in unsure))
            lines += [
                flag(f"{part} · {before} → {after}", read.guessed and part == "schedule")
                for part, before, after in rules.differences(pill.plan, read.plan)
            ]
            lines += _held_lines(read)
            changes += 1
        else:
            first, *rest = rules.card_lines(read.plan)
            lines += [flag(first, read.guessed or name.lower() in unsure), *rest, *_held_lines(read)]
        warnings += _held_warnings(read)
        if read.guessed:
            own_guesses.append(f"pills[{len(kept)}].times")
        # What can't be saved yet stays as it was said, so one reply can put it right
        fixed = dict(item) if read.held else _settled(item, read.request)
        kept.append({**fixed, "pill": pill.ref} if pill is not None else fixed)
        held = held or read.held
    if not kept:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "No pill to add.")
    last = str(asked[-1]["name"]) if asked else None
    return Proposal(
        lines=tuple(lines), data={"pills": kept, LAST: last}, warnings=tuple(warnings),
        kind="change" if changes == len(kept) else "new", guessed=tuple(own_guesses), can_save=not held,
    )


async def _unchanged(request: Request, data: dict) -> list[Pill] | None:
    """The pills a message asks to add, if every one of them is already among
    the user's pills just as asked; None if anything is new or would change."""
    existing = await store.pills(request.user.id)
    today = day.today()
    found = []
    for item in data["pills"]:
        pill = _known(existing, str(item.get("name", "")))
        if pill is None:
            return None
        try:
            read = settle(_change(item), today, pill.plan)
        except UserError:
            return None
        if read.held or read.plan != pill.plan:
            return None
        found.append(pill)
    return found or None


async def add_asks(request: Request, data: dict) -> bool:
    """Whether adding needs a card: not when there is nothing to save, because
    every pill named is already there with these settings."""
    return bool(request.previous) or await _unchanged(request, data) is None


async def add_already(request: Request, data: dict, guessed: frozenset) -> str:
    """Said in place of a card when nothing would change: each pill, as it is."""
    today = day.today()
    pills = await _unchanged(request, data) or []
    return "\n".join(f"{ICON} {_already(pill)}\n{rules.describe_pill(pill, today)}" for pill in pills)


async def add_save(request: Request, data: dict) -> str:
    today = day.today()
    user_id = request.user.id

    def save(conn) -> list[tuple[Pill, bool]]:
        # Checked again here, in the same transaction as the write: the list may
        # have changed since the card was shown
        saved = []
        for item in data["pills"]:
            if item.get("pill"):
                pill = rules.find(store.db_pills(conn, user_id), item["pill"])
                plan = rules.build(_change(item), today, pill.plan)
                saved.append((store.db_edit(conn, pill.id, plan), True))
                continue
            plan = rules.build(as_request(item), today)
            rules.check_name(plan, store.db_pills(conn, user_id))
            saved.append((store.db_add(conn, user_id, plan), False))
        return saved

    saved = await request.db.run(save)
    _changed(user_id)
    if len(saved) == 1:
        pill, changed = saved[0]
        return f"✅ {'Updated' if changed else 'Saved'} · {rules.describe_pill(pill, today)}"
    names = ", ".join(f"**{pill.plan.name}**" for pill, _ in saved)
    if not any(changed for _, changed in saved):
        return f"✅ Saved · {ICON} {len(saved)} pills added: {names}"
    return f"✅ Saved · {ICON} {len(saved)} pills: {names}"


async def add_check(request: Request, data: dict) -> str:
    """Read each pill back: it is there, in use, with the plan the card showed."""
    today = day.today()
    listed = rules.listed(await store.pills(request.user.id))
    saved = {pill.plan.name.lower(): pill for pill in listed}
    by_ref = {pill.ref: pill for pill in listed}
    wrong = []
    for item in data["pills"]:
        if item.get("pill"):
            # A change to a pill that was there: asking for it again must change nothing
            pill = by_ref.get(item["pill"])
            if pill is None:
                wrong.append(f"{item['pill']} is not among your pills")
            elif rules.build(_change(item), today, pill.plan) != pill.plan:
                wrong.append(f"{pill.plan.name} is still {rules.plain(_line(pill.plan))}")
            continue
        plan = rules.build(as_request(item), today)
        pill = saved.get(plan.name.lower())
        if pill is None:
            wrong.append(f"{plan.name} is not among your pills")
        elif pill.plan != plan:
            wrong.append(f"{plan.name} was saved as {rules.plain(_line(pill.plan))}")
    return "; ".join(wrong)


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------
async def edit_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    today = day.today()
    existing = await store.pills(request.user.id)
    unsure = _unsure(data, guessed, "pill")
    asked, taken_as = await _pointed(request, data["pills"], "pill")
    found, problems = _resolve(existing, asked)
    resolved = [item for item, _ in found]
    items, missing = overlay(request.previous["pills"] if request.previous else [], resolved, "pill")
    by_ref = {pill.ref: pill for pill in existing}
    asked_as = {item["pill"]: str(raw.get("pill", "")).strip().lower() for (item, _), raw in zip(found, asked)}
    if taken_as:
        unsure = unsure | {taken_as}
    lines, kept, warnings = [], [], [*problems, *[f"{name} isn't on the card: nothing to take off" for name in missing]]
    own_guesses: list[str] = []
    held = False
    for item in items:
        pill = by_ref.get(item["pill"])
        if pill is None:
            continue
        try:
            read = settle(as_request(item), today, pill.plan)
            rules.check_name(read.plan, existing, own_id=pill.id)
        except UserError as error:
            warnings.append(f"Not included: {pill.plan.name} ({error})")
            continue
        if read.plan == pill.plan and not read.held:
            warnings.append(f"{pill.plan.name}: nothing would change")
            continue
        mark = asked_as.get(item["pill"], "") in unsure
        # One format for every edit: field · old → new
        lines.append(flag(f"**{pill.plan.name}**", mark))
        lines += [
            flag(f"{name} · {before} → {after}", read.guessed and name == "schedule")
            for name, before, after in rules.differences(pill.plan, read.plan)
        ]
        lines += _held_lines(read)
        warnings += _held_warnings(read)
        if read.guessed:
            own_guesses.append(f"pills[{len(kept)}].times")
        kept.append(dict(item) if read.held else _settled(item, read.request))
        held = held or read.held
    if not kept:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "Nothing to change.")
    lines.append("-# Applies from the next dose. What is already recorded stays as it is.")
    last = resolved[-1]["pill"] if resolved else (request.previous or {}).get(LAST)
    return Proposal(
        lines=tuple(lines), data={"pills": kept, LAST: last}, warnings=tuple(warnings), kind="change",
        guessed=tuple(own_guesses), can_save=not held,
    )


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


async def edit_check(request: Request, data: dict) -> str:
    """Read each pill back: asking for the same change again must change nothing."""
    today = day.today()
    by_ref = {pill.ref: pill for pill in await store.pills(request.user.id)}
    wrong = []
    for item in data["pills"]:
        pill = by_ref.get(item["pill"])
        if pill is None:
            wrong.append(f"{item['pill']} is not among your pills")
        elif rules.build(as_request(item), today, pill.plan) != pill.plan:
            wrong.append(f"{pill.plan.name} is still {rules.plain(_line(pill.plan))}")
    return "; ".join(wrong)


async def _status_check(request: Request, data: dict, wanted: str) -> str:
    """Read each pill back: its status is what the card said it would be."""
    wrong = []
    for item in data["pills"]:
        pill = await store.pill(int(str(item["pill"]).removeprefix(rules.ID_PREFIX)))
        if pill is None:
            wrong.append(f"{item['pill']} is gone")
        elif pill.status != wanted:
            wrong.append(f"{pill.plan.name} is still {pill.status}")
        elif wanted == PAUSED and (pill.paused_until.isoformat() if pill.paused_until else None) != item.get("until"):
            wrong.append(f"{pill.plan.name} is paused until {pill.paused_until}")
    return "; ".join(wrong)


async def pause_check(request: Request, data: dict) -> str:
    return await _status_check(request, data, PAUSED)


async def resume_check(request: Request, data: dict) -> str:
    return await _status_check(request, data, ACTIVE)


async def remove_check(request: Request, data: dict) -> str:
    return await _status_check(request, data, REMOVED)


async def delete_check(request: Request, data: dict) -> str:
    """Read back: the pill's row is gone, and so is every dose recorded for it."""
    wrong = []
    for item in data["pills"]:
        pill_id = int(str(item["pill"]).removeprefix(rules.ID_PREFIX))
        if await store.pill(pill_id) is not None:
            wrong.append(f"{item['pill']} is still there")
    return "; ".join(wrong)


# ---------------------------------------------------------------------------
# Pause, resume, remove, delete: each a card naming the pills it is about
# ---------------------------------------------------------------------------
async def _chosen(
    request: Request, data: dict, guessed: frozenset = frozenset()
) -> tuple[list[tuple[dict, Pill]], list[str], date, set[str]]:
    """The pills a card is about, once this message is taken in: (each item
    with its pill, what couldn't be found, today, the ids Claude guessed at)."""
    existing = await store.pills(request.user.id)
    asked, taken_as = await _pointed(request, data["pills"], "pill")
    found, problems = _resolve(existing, asked)
    resolved = [item for item, _ in found]
    items, missing = overlay(request.previous["pills"] if request.previous else [], resolved, "pill")
    by_ref = {pill.ref: pill for pill in existing}
    chosen = [(item, by_ref[item["pill"]]) for item in items if item["pill"] in by_ref]
    unsure = _unsure(data, guessed, "pill")
    marked = {taken_as} if taken_as else set()
    for raw in asked:
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
    lines, kept, held = [], [], False
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
                # Not read: on the card with the reason, and no Save until a reply gives the day
                lines += [f"**{name}** · {rules.status_on(pill, today)} → paused until ❔", f"❔ until · {error}"]
                kept.append({"pill": pill.ref, "until": str(item["until"])})
                held = True
                continue
            if until <= today:
                warnings.append(f"Not included: {name} (a pause ends on a later day than today)")
                continue
        when = f"paused until {timeinput.format_date(until)}" if until else "paused until you resume it"
        lines.append(flag(f"**{name}** · {rules.status_on(pill, today)} → {when}", pill.ref in marked))
        kept.append({"pill": pill.ref, **({"until": until.isoformat()} if until else {})})
    if not kept:
        raise _none_left(warnings, "No pill to pause.")
    lines.append("-# It won't be asked for while paused, and its streak is unaffected.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="change", can_save=not held)


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
        lines.append(flag(f"**{pill.plan.name}** · paused → active", pill.ref in marked))
        kept.append({"pill": pill.ref})
    if not kept:
        raise _none_left(warnings, "No pill to resume.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="change")


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
    lines = [flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)} → removed", pill.ref in marked) for _, pill in chosen]
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
    lines = tuple(
        flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)} → deleted, with its history", pill.ref in marked)
        for _, pill in chosen
    )
    return Proposal(
        lines=lines, data={"pills": [{"pill": pill.ref} for _, pill in chosen]},
        warnings=(*warnings, "This deletes the history too and can't be undone"),
        kind="remove", destructive=True, confirm_label="Delete for good",
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
AS_SAID = "exactly as the user said it (tomorrow, friday, the 20th): never work out a date. The code reads it."
_PLAN_FIELDS = (
    Field("dose", "How much each time, e.g. 1 tablet. Leave out if not said."),
    Field("notes", "Instructions, e.g. with food. Leave out if not said."),
    Field(
        "times",
        "The time of each dose, in the order said. \"Every 2 hours from 8am\" is a time for each dose. Leave "
        "out for a pill with no set time. When changing a pill, the one value `none` takes its times away "
        "(\"it no longer needs a time\").",
        TIMES,
    ),
    Field("per_day", "How many doses a day, if said. Not needed when a time is given for each dose.", INTEGER),
    Field(
        "min_gap_minutes",
        "The least time between doses (\"at least 3 hours apart\" -> 180). It can go with times. Without a "
        "time for each dose, per_day is needed too (your best guess, listed as guessed, if not said).",
        MINUTES,
    ),
    Field(
        "latest",
        "The time of day after which it must not be taken (\"not after 4pm\" -> `4:00 pm`). Leave out if not said.",
        TIME,
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
_WHICH = Field(
    "pill",
    "Which pill: its id from the state given with the message (pl3), or its name as the user said it. "
    "\"it\" or \"that one\" is `@that`: never work out which pill a pronoun means.",
    required=True,
)


def _one_or_more(what: str, *fields_: Field) -> tuple[Field, ...]:
    return (Field("pills", f"Each pill {what}, one item each, in the order said.", ITEMS, required=True, item_fields=fields_),)


ACTIONS = (
    Action(
        "pill_add",
        "Set up a new pill, vitamin, supplement or medicine. Examples: \"add vitamin D once a day with food\" "
        "-> name Vitamin D, notes with food. \"add iron at 8\" -> name Iron, times [8:00]. \"add course A, 3 times a "
        "day, at least 3 hours apart, with food, for 7 days starting tomorrow\" -> name Course A, per_day 3, "
        "min_gap_minutes 180, notes with food, start tomorrow, days 7. \"a new pill called A at 9am, 12pm and "
        "3pm\" -> name A, times [9:00 am, 12:00 pm, 3:00 pm]. \"add pill A, 3 times a day at 8am, 11:30 and "
        "3pm, at least 3 hours apart, not after 4pm, without food\" -> name Pill A, per_day 3, times [8:00 am, "
        "11:30 am, 3:00 pm], min_gap_minutes 180, latest 4:00 pm, notes without food. A pill with no end has no "
        "dates: leave start, end and days out. In a follow-up (\"8pm\", \"make it twice a day\"), give the "
        "pill by the name on the card and only what changes. A time said in a follow-up REPLACES the card's "
        "time (card shows 8:00 am, user says \"8pm\" -> times [8:00 pm], never both), unless the user says to "
        "add another dose. If the pill named is already in the state, this is still the action for \"add\": "
        "give what the user said, exactly as for a new one, and the code works out whether anything changes.",
        _one_or_more(
            "to add",
            Field("name", "What it is called, as the user said it, e.g. Vitamin D.", required=True),
            *_PLAN_FIELDS,
            _OFF_THE_CARD,
        ),
        prepare=add_card,
        apply=add_save,
        verify=add_check,
        # No card when every pill named is already there just as asked: that is said in a line
        card_if=add_asks,
        run=add_already,
    ),
    Action(
        "pill_edit",
        "Change a pill the user already has: its name, dose, notes, times, how often, the gap, the latest "
        "time or its dates. Give only what changes. To take something away give \"none\" for it (notes none; "
        "times [none] makes it any time; latest none; end none makes it go on with no end), and 0 for "
        "min_gap_minutes to take the gap away. Examples: \"move the evening pill to 9pm\" -> pill "
        "Evening pill, times [9:00 pm]. \"vitamin D is 2 tablets now\" -> dose 2 tablets.",
        _one_or_more("to change", _WHICH, Field("name", "A new name for it, if it is being renamed."), *_PLAN_FIELDS, _OFF_THE_CARD),
        prepare=edit_card,
        apply=edit_save,
        verify=edit_check,
    ),
    Action(
        "pill_pause",
        "Pause a pill: it stops being asked for until resumed. \"pause iron\" -> pill iron. \"pause iron until "
        "the 20th\" -> until the 20th (the day it is taken again).",
        _one_or_more("to pause", _WHICH, Field("until", "The day it is taken again, " + AS_SAID + " Leave out for no end."), _OFF_THE_CARD),
        prepare=pause_card,
        apply=pause_save,
        verify=pause_check,
    ),
    Action(
        "pill_resume",
        "Take a paused pill again (\"resume iron\", \"start iron again\").",
        _one_or_more("to resume", _WHICH, _OFF_THE_CARD),
        prepare=resume_card,
        apply=resume_save,
        verify=resume_check,
    ),
    Action(
        "pill_remove",
        "Remove a pill the user no longer takes, keeping its history (\"remove iron\", \"I've stopped taking "
        "iron\"). This is the usual one.",
        _one_or_more("to remove", _WHICH, _OFF_THE_CARD),
        prepare=remove_card,
        apply=remove_save,
        verify=remove_check,
    ),
    Action(
        "pill_delete",
        "Delete a pill TOGETHER WITH its history. Only when the user says so in as many words (\"delete iron "
        "and its history\", \"delete it completely\"); otherwise use pill_remove.",
        _one_or_more("to delete", _WHICH, _OFF_THE_CARD),
        prepare=delete_card,
        apply=delete_save,
        verify=delete_check,
    ),
    Action(
        "pill_list",
        "The user asks what pills they have or when they take them (\"show all my pills\", \"what do I take?\").",
        needs_card=False,
        run=show_list,
    ),
)
