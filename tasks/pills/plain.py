from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from core import clock, database, day, dms, hub, livelists, occurrences, repeats, tidy, timeinput, trace
from core import schedule as core_schedule
from core.actions import BOOLEAN, INTEGER, ITEMS, LAST, LIST, MINUTES, TIME, TIMES, Action, Answer, Choice, Field, LiveReply, Proposal, Question, Request, Shown, State
from core.actions import EACH_DAY, SEE, SET_UP, flag, is_guessed
from core.actions import is_reference, point_at
from core.errors import UserError
from tasks.pills import checklist, history, listing, rules, store, taken, today
from tasks.pills import doses as limits
from tasks.pills.store import DOSE
from tasks.pills.today import Dose
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
    "is taken, pausing, resuming or removing it, listing them, saying that one was taken, skipped or not "
    "taken today (\"took my zinc\" is a request to tick it off, never a remark), and asking what is left "
    "to take today. Not shopping for them, and not timers, general reminders or to-dos."
)
EXAMPLES = (
    "add vitamin D once a day with food", "move the evening pill to 9pm", "pause iron until the 20th",
    "took my zinc", "I've taken my zinc today", "had pill A at 9", "I didn't take zinc",
)
# A pill is its name: asking to add one that is there is a change to it, never a second pill
IDENTITY = ("name",)
ON_REPEAT = repeats.UPDATE
WHERE = "pills"  # as in "already in your pills"

PLAN_FIELDS = ("name", "dose", "notes", "times", "per_day", "min_gap", "latest", "start", "end", "days", "weekdays")
# Where an item of the action calls a part of the plan something else
ITEM_KEYS = {"min_gap": "min_gap_minutes"}
# What each setting that can be taken away (rules.CLEARABLE) is called in an item
CLEARS = {"dose": ("dose",), "notes": ("notes",), "times": ("times",), "min_gap": ("min_gap_minutes",), "latest": ("latest",), "dates": ("start", "end", "days"), "weekdays": ("weekdays",)}
# A part of the plan, as a card names it when it couldn't be read
UNKNOWN = "❔"  # in place of a value the card is asking about
UNREAD = {
    "times": "times", "per_day": "doses a day", "min_gap": "gap", "latest": "latest time",
    "start": "start", "end": "end", "days": "days", "weekdays": "days of the week",
}
TRIES = rules.MAX_PER_DAY + 1


# ---------------------------------------------------------------------------
# From what was said to a plan
# ---------------------------------------------------------------------------
def overlay(pending: list[dict], items: list[dict], key: str, asked: tuple[str, ...] = ()) -> tuple[list[dict], list[str]]:
    """An open card's pills with a message's changes laid over them: (the
    pills as they now stand, the names it was asked to take off that weren't
    on it). A pill named again keeps what it had and takes what is new; one
    with `remove` leaves the card. `asked` is what the card's question was
    about: a time given in answer to "What time is the other dose?" is the
    other dose's, not a new time for the first. Pure."""
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
            merged[at] = _laid_over(merged[at], _answering(merged[at], rest, asked))
    return merged, missing


def _answering(held: dict, rest: dict, asked: tuple[str, ...]) -> dict:
    """The later item, read as the answer to the card's question when it is
    one. The card asked for the time of a dose that had none; the message
    gives fewer times than there are doses, and none the card has already:
    those are the missing ones, added to the card's own. (Claude hands over
    only what the message said: sometimes every time, sometimes the new one.)"""
    if "times" not in asked or not held.get("times") or not rest.get("times"):
        return rest
    doses = int(rest.get("per_day") or held.get("per_day") or 0)
    had, given = [str(each) for each in held["times"]], [str(each) for each in rest["times"]]
    same = {each.strip().lower() for each in had} & {each.strip().lower() for each in given}
    if doses and not same and len(had) < doses and len(given) < doses and len(had) + len(given) <= doses:
        return {**rest, "times": [*had, *given]}
    return rest


def _laid_over(held: dict, rest: dict) -> dict:
    """An item on the card with a later one over it. What the later one takes
    away is no longer given, and what it gives is no longer taken away."""
    taken = set(rest.get("clear") or [])
    kept = {name: value for name, value in held.items() if not any(name in CLEARS[part] for part in taken)}
    still = [part for part in kept.get("clear") or [] if not any(name in rest for name in CLEARS[part])]
    both = {**kept, **rest}
    clear = list(dict.fromkeys([*still, *(rest.get("clear") or [])]))
    both.pop("clear", None)
    return {**both, "clear": clear} if clear else both


def as_request(item: dict) -> rules.Request:
    """An item as extraction gives it, in the words rules.build reads: the
    times joined up, the gap's minutes with their unit."""
    said, clear = {}, set(item.get("clear") or [])
    for name in PLAN_FIELDS:
        value = item.get(ITEM_KEYS.get(name, name))
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(each) for each in value)
        elif name == "min_gap" and isinstance(value, int):
            if not value:
                clear.add("min_gap")  # a gap of nothing is no gap: a number, not a word
                continue
            value = f"{value}m"
        said[name] = str(value)
    return rules.Request(**said, clear=frozenset(clear))


@dataclass(frozen=True)
class Asked:
    """A question a pill's request raises, for the card: the words, and each
    likely answer as (label, the item's fields with that answer in them)."""

    text: str
    options: tuple[tuple[str, dict], ...] = ()
    settles: tuple[str, ...] = ()  # the item's fields an answer decides


@dataclass
class Read:
    """What was made of one pill's request. Nothing is guessed: what could
    mean two things is asked about on the card."""

    plan: Plan  # everything that was understood
    request: rules.Request  # what Save applies
    guessed: bool = False  # nothing is guessed any more (a time that could be either is asked about): always False
    moved: list[str] = field(default_factory=list)  # a line for each planned time moved to keep the gap
    unread: list[tuple[str, str]] = field(default_factory=list)  # (which part, why) for each part that couldn't be read
    unfit: str = ""  # why the doses can't fit in a day, if they can't
    asks: list[Asked] = field(default_factory=list)  # what has to be asked, the first one first
    unknown: list[str] = field(default_factory=list)  # times the plan holds only so it can be shown: each is asked about

    @property
    def held(self) -> bool:
        """Whether something has to be put right or answered before this can be saved."""
        return bool(self.unread or self.unfit or self.asks)

    def shown(self, text: str) -> str:
        """A line about the plan, with ❔ where a time is still being asked about."""
        for each in self.unknown:
            text = text.replace(f"`{each}`", UNKNOWN, 1)
        return text


def _time_asked(request: rules.Request, question: TimeQuestion) -> Asked:
    """ "8": is that the morning or the evening? Each answer is the item's times
    (or its latest time) with that one settled."""
    options = []
    for chosen in question.options:
        settled = rules.answer(request, question, chosen)
        fields_ = {"latest": settled.latest} if question.field == "latest" else {"times": rules.split_times(settled.times)}
        options.append((timeinput.format_time(chosen), fields_))
    return Asked(f"Is that {question.typed} in the morning or the evening?", tuple(options), (question.field,))


def settle(request: rules.Request, today: date, base: Plan | None = None) -> Read:
    """The plan a request makes, never guessing and never stopping at the first
    thing wrong. A time that could be morning or evening, a missing time and
    a missing number of doses are questions for the card (`asks`): the rest
    is still read, and the plan holds a stand-in so it can be shown (`shown`
    puts ❔ in its place). A part that can't be read is set aside with its
    reason; a schedule that can't fit is kept as read with its reason. Raises
    UserError only for what leaves nothing to show."""
    unread, asks, unknown = [], [], []
    for _ in range(TRIES + len(PLAN_FIELDS)):
        moved: list[str] = []
        try:
            return Read(rules.build(request, today, base, moved), request, False, moved, unread, "", asks, unknown)
        except TimeQuestion as question:
            asks.append(_time_asked(request, question))
            # Only so the rest can be read and shown: the morning (the evening for a latest time)
            stand_in = question.options[question.field == "latest"]
            unknown.append(timeinput.format_time(stand_in))
            request = rules.answer(request, question, stand_in)
        except rules.Ask as problem:
            asks.append(Asked(problem.question, tuple((label, _as_item(fields_)) for label, fields_ in problem.options), (ITEM_KEYS.get(problem.field, problem.field),)))
            unread.append((problem.field, problem.reason))
            request = replace(request, **{problem.drop: ""})
        except rules.Unreadable as problem:
            unread.append((problem.field, str(problem)))
            request = replace(request, **{problem.field: ""})
        except rules.DoesNotFit as problem:
            return Read(problem.plan, request, False, moved, unread, str(problem), asks, unknown)
    raise UserError("I couldn't read those times.")


def _as_item(fields_: dict) -> dict:
    """A plan's parts under the names an item of the action calls them."""
    return {ITEM_KEYS.get(name, name): value for name, value in fields_.items()}


def _asking(items: list[dict], at: int, asked: Asked, key: str, last) -> Question:
    """The card's question about the item at `at`: each answer is the whole
    request again, as extraction would hand it over, with that item answered."""
    choices = tuple(
        Choice(label, {LIST_KEY: [{**item, **fields_} if index == at else dict(item) for index, item in enumerate(items)], LAST: last}, asked.settles)
        for label, fields_ in asked.options
    )
    return Question(asked.text, choices)


def _which_one(resolved: list[dict], unclear: list[tuple[dict, list[Pill]]]) -> Question | None:
    """The question for a name that fits more than one pill, with a button a
    pill. `resolved` are the items already known; the others asked for come
    after, and are asked about in their turn."""
    if not unclear:
        return None
    raw, candidates = unclear[0]
    rest = [dict(item) for item, _ in unclear[1:]]
    choices = tuple(
        Choice(pill.plan.name, {LIST_KEY: [*(dict(item) for item in resolved), {**raw, "pill": pill.ref}, *rest]}, ("pill",))
        for pill in candidates
    )
    return Question(f"Which one is “{str(raw.get('pill', '')).strip()}”?", choices)


def _known(existing: list[Pill], name: str) -> Pill | None:
    """The pill the user already has by exactly this name, whatever the case."""
    return repeats.find(IDENTITY, {"name": name}, rules.listed(existing), lambda pill: {"name": pill.plan.name})


async def edit_on_card(request: Request, data: dict, on_card: dict) -> dict | None:
    """A change read as one to a saved pill, when the pill it names is only on
    the open "new" card: the same change as that card's own action takes it
    (the pill by its name on the card). None when any pill it names is saved,
    is not on the card, or the change is one only a saved pill can take (a
    new name, a setting taken away)."""
    on = [str(item.get("name", "")) for item in (on_card or {}).get("pills", []) if isinstance(item, dict) and item.get("name")]
    saved = await store.pills(request.user.id)
    changed = []
    for item in data.get("pills", []):
        which = str(item.get("pill", "")).strip()
        if item.get("name") or item.get("clear"):
            return None
        if is_reference(which):
            fits = on if len(on) == 1 else []
        else:
            if _known(saved, which) is not None or any(which.lower() == f"pl{pill.id}" for pill in rules.listed(saved)):
                return None
            fits = [name for name in on if name.strip().lower() == which.lower()]
        if len(fits) != 1:
            return None
        changed.append({**{part: value for part, value in item.items() if part != "pill"}, "name": fits[0]})
    return {**data, "pills": changed} if changed else None


def _change(item: dict) -> rules.Request:
    """What an item says about a pill that is already there: everything but its name."""
    return as_request({part: value for part, value in item.items() if part not in ("name", "pill")})


def _already(pill: Pill) -> str:
    return repeats.already(pill.plan.name, WHERE)


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

    async def render():
        return listing.card(await store.pills(user_id), day.today())

    livelists.changed(user_id, LIST_KEY, render)
    # Today's checklist follows the plan straight away: a pill added, changed, paused or removed
    checklist.changed(user_id)


def just_saved_pill(request: Request) -> str | None:
    """The pill the card saved a moment ago was about, as a name or an id:
    the one mentioned last on it, or the only one it held. None when no card
    was just saved, it was another task's, or it held several with none
    mentioned last: then nothing is known, and nothing is made up."""
    saved = request.just_saved
    if saved is None or saved.task != TASK:
        return None
    held = [item.get("pill") or item.get("name") for item in saved.data.get("pills", []) if isinstance(item, dict)]
    held = [str(each) for each in held if each]
    return saved.data.get(LAST) or (held[0] if len(held) == 1 else None)


async def _pointed(request: Request, items: list[dict], key: str) -> tuple[list[dict], str | None]:
    """The items with "it" given the pill it stands for, resolved here and never
    by Claude: the pill mentioned last on the open card; with no card, the
    pill on the card saved a moment ago ("no, I meant 9pm" straight after
    Save), which is known; failing both, the pill changed last, which is a
    guess and comes back as the second value. A new pill can't be "it":
    there is nothing it could mean."""
    if not any(is_reference(item.get(key)) for item in items):
        return items, None
    previous = request.previous or {}
    held = previous.get("pills", [])
    last = previous.get(LAST) or (held[-1].get(key) if held else None)
    if last is None and key == "pill":
        last = just_saved_pill(request)
    taken_as = None
    if last is None and key == "pill":
        changed = await request.db.run(store.db_last_changed, request.user.id)
        last = taken_as = f"{rules.ID_PREFIX}{changed}" if changed is not None else None
    return point_at(items, key, last), taken_as


def _resolve(pills: list[Pill], items: list[dict], said: str = "") -> tuple[list[tuple[dict, Pill]], list[str], list[tuple[dict, list[Pill]]]]:
    """Each item with the pill it means (its `pill` set to that pill's id),
    what couldn't be found, in words, and each item whose name fits more
    than one pill, with the pills it could be: those are asked about on the
    card, never in a message of their own. `said` is the message: a name
    Claude completed is asked about as the part of it that was typed."""
    found, problems, unclear = [], [], []
    for item in items:
        try:
            pill = rules.find(pills, str(item.get("pill", "")), said)
        except rules.Ambiguous as which:
            # Asked about in the words that were typed ("testv"), not the ones Claude made of them
            unclear.append(({**item, "pill": which.said}, which.candidates))
            continue
        except UserError as error:
            problems.append(str(error))
            continue
        found.append(({**item, "pill": pill.ref}, pill))
    return found, problems, unclear


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    today = day.today()
    existing = await store.pills(request.user.id)
    asked, _ = await _pointed(request, data["pills"], "name")
    items, missing = overlay(request.previous["pills"] if request.previous else [], asked, "name", request.asked)
    unsure = _unsure(data, guessed, "name")
    lines, kept, warnings = [], [], [f"{name} isn't on the card: nothing to take off" for name in missing]
    seen: set[str] = set()
    own_guesses: list[str] = []
    held, changes = False, 0
    first_ask: tuple[int, Asked] | None = None
    for at, item in enumerate(items):
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
        repeat = repeats.decide(ON_REPEAT, pill, changes=pill is None or read.plan != pill.plan or read.held)
        if repeat.kind == repeats.SAME:
            warnings.append(_already(pill))
            continue
        if repeat.kind == repeats.CHANGE:
            # One format for a change, on whichever card it is: field · old → new
            lines.append(flag(repeats.there_line(pill.plan.name, WHERE), name.lower() in unsure))
            lines += [
                read.shown(repeats.change_line(part, before, after))
                for part, before, after in rules.differences(pill.plan, read.plan)
            ]
            lines += _held_lines(read)
            changes += 1
        else:
            first, *rest = rules.card_lines(read.plan)
            lines += [flag(read.shown(first), name.lower() in unsure), *(read.shown(line) for line in rest), *_held_lines(read)]
        warnings += _held_warnings(read)
        if read.asks and first_ask is None:
            first_ask = (at, read.asks[0])
        # What is being asked about was never said: kept with the card as unsettled, so a
        # typed answer is read as the value itself and not as one more beside it
        own_guesses += [f"pills[{len(kept)}].{name}" for asked_ in read.asks for name in asked_.settles]
        # What can't be saved yet stays as it was said, so one reply can put it right
        fixed = dict(item) if read.held else _settled(item, read.request)
        kept.append({**fixed, "pill": pill.ref} if pill is not None else fixed)
        held = held or read.held
    if not kept:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "No pill to add.")
    last = str(asked[-1]["name"]) if asked else None
    question = _asking(items, first_ask[0], first_ask[1], "name", last) if first_ask else None
    return Proposal(
        lines=tuple(lines), data={"pills": kept, LAST: last}, warnings=tuple(warnings),
        kind="change" if changes == len(kept) else "new", guessed=tuple(own_guesses), can_save=not held, question=question,
    )


async def _unchanged(request: Request, data: dict, key: str = "name") -> list[Pill] | None:
    """The pills a message is about, if every one of them is already among the
    user's pills just as asked: named to be added (`key` "name") or to be
    changed ("pill"). None if anything is new or would change."""
    existing = await store.pills(request.user.id)
    today = day.today()
    found = []
    for item in data["pills"]:
        try:
            pill = _known(existing, str(item.get(key, ""))) if key == "name" else rules.find(existing, str(item.get(key, "")))
            if pill is None:
                return None
            read = settle(_change(item) if key == "name" else as_request(item), today, pill.plan)
        except UserError:
            return None
        if read.held or read.plan != pill.plan:
            return None
        found.append(pill)
    return found or None


def already_text(pills: list[Pill], today: date) -> str:
    """The one line for "that is already so", whichever way it was found: the
    pill is named, and shown as the list shows it."""
    return "\n".join(f"{ICON} {_already(pill)}\n{rules.describe_pill(pill, today)}" for pill in pills)


async def already_so(request: Request, about: str) -> str | None:
    """For a request extraction declined because it changes nothing: the same
    line, for the pill it named. None if that is no pill of the user's."""
    try:
        pill = rules.find(await store.pills(request.user.id), about)
    except UserError:
        return None
    return already_text([pill], day.today())


async def add_asks(request: Request, data: dict, guessed: frozenset = frozenset()) -> bool:
    """Whether adding needs a card: not when there is nothing to save, because
    every pill named is already there with these settings."""
    return bool(request.previous) or await _unchanged(request, data) is None


async def add_already(request: Request, data: dict, guessed: frozenset) -> str:
    """Said in place of a card when nothing would change: each pill, as it is."""
    return already_text(await _unchanged(request, data) or [], day.today())


async def edit_asks(request: Request, data: dict, guessed: frozenset = frozenset()) -> bool:
    """Whether a change needs a card: not when it would change nothing."""
    return bool(request.previous) or await _unchanged(request, data, "pill") is None


async def edit_already(request: Request, data: dict, guessed: frozenset) -> str:
    return already_text(await _unchanged(request, data, "pill") or [], day.today())


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
    found, problems, unclear = _resolve(existing, asked, request.text)
    resolved = [item for item, _ in found]
    items, missing = overlay(request.previous["pills"] if request.previous else [], resolved, "pill")
    by_ref = {pill.ref: pill for pill in existing}
    asked_as = {}
    for raw in asked:
        try:
            asked_as[rules.find(existing, str(raw.get("pill", ""))).ref] = str(raw.get("pill", "")).strip().lower()
        except UserError:
            continue
    if taken_as:
        unsure = unsure | {taken_as}
    lines, kept, warnings = [], [], [*problems, *[f"{name} isn't on the card: nothing to take off" for name in missing]]
    own_guesses: list[str] = []
    held = False
    first_ask: tuple[int, Asked] | None = None
    for at, item in enumerate(items):
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
            warnings.append(_already(pill))
            continue
        mark = asked_as.get(item["pill"], "") in unsure
        # One format for every edit: field · old → new
        lines.append(flag(f"**{pill.plan.name}**", mark))
        lines += [
            read.shown(f"{name} · {before} → {after}")
            for name, before, after in rules.differences(pill.plan, read.plan)
        ]
        lines += _held_lines(read)
        warnings += _held_warnings(read)
        if read.asks and first_ask is None:
            first_ask = (at, read.asks[0])
        own_guesses += [f"pills[{len(kept)}].{name}" for asked_ in read.asks for name in asked_.settles]
        kept.append(dict(item) if read.held else _settled(item, read.request))
        held = held or read.held
    last = resolved[-1]["pill"] if resolved else (request.previous or {}).get(LAST)
    # Which pill is meant comes before anything about it: one question at a time
    question = _which_one(items, unclear) or (_asking(items, first_ask[0], first_ask[1], "pill", last) if first_ask else None)
    if not kept and question is None:
        raise UserError("; ".join(warning.removeprefix("Not included: ") for warning in warnings) or "Nothing to change.")
    if kept:
        lines.append("-# Applies from the next dose. What is already recorded stays as it is.")
    return Proposal(
        lines=tuple(lines), data={"pills": kept, LAST: last}, warnings=tuple(warnings), kind="change",
        guessed=tuple(own_guesses), can_save=not held, question=question,
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
@dataclass
class Chosen:
    """The pills a card is about. Unpacks as the four things the cards read;
    `question` is what the card has to ask first, if a name fits several pills."""

    chosen: list
    warnings: list
    today: date
    marked: set
    question: Question | None = None

    def __iter__(self):
        return iter((self.chosen, self.warnings, self.today, self.marked))


async def _chosen(request: Request, data: dict, guessed: frozenset = frozenset()) -> Chosen:
    """The pills a card is about, once this message is taken in: (each item
    with its pill, what couldn't be found, today, the ids Claude guessed at)."""
    existing = await store.pills(request.user.id)
    asked, taken_as = await _pointed(request, data["pills"], "pill")
    found, problems, unclear = _resolve(existing, asked, request.text)
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
    return Chosen(chosen, warnings, day.today(), marked, _which_one(items, unclear))


def _none_left(warnings: list[str], otherwise: str) -> UserError:
    return UserError("; ".join(warnings) or otherwise)


async def pause_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    about = await _chosen(request, data, guessed)
    chosen, warnings, today, marked = about
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
    if not kept and about.question is None:
        raise _none_left(warnings, "No pill to pause.")
    if kept:
        lines.append("-# It won't be asked for while paused, and its streak is unaffected.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="change", can_save=not held, question=about.question)


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
    about = await _chosen(request, data, guessed)
    chosen, warnings, today, marked = about
    lines, kept = [], []
    for item, pill in chosen:
        if rules.status_on(pill, today) != PAUSED:
            warnings.append(f"{pill.plan.name} isn't paused")
            continue
        lines.append(flag(f"**{pill.plan.name}** · paused → active", pill.ref in marked))
        kept.append({"pill": pill.ref})
    if not kept and about.question is None:
        raise _none_left(warnings, "No pill to resume.")
    return Proposal(lines=tuple(lines), data={"pills": kept}, warnings=tuple(warnings), kind="change", question=about.question)


async def resume_save(request: Request, data: dict) -> str:
    done = []
    for item in data["pills"]:
        pill = rules.find(await store.pills(request.user.id), item["pill"])
        await store.set_status(pill.id, ACTIVE)
        done.append(f"**{pill.plan.name}**")
    _changed(request.user.id)
    return f"▶️ {', '.join(done)} resumed."


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    about = await _chosen(request, data, guessed)
    chosen, warnings, today, marked = about
    if not chosen and about.question is None:
        raise _none_left(warnings, "No pill to remove.")
    lines = [flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)} → removed", pill.ref in marked) for _, pill in chosen]
    if chosen:
        lines.append("-# This stops its reminders. Its history is kept.")
    return Proposal(
        lines=tuple(lines), data={"pills": [{"pill": pill.ref} for _, pill in chosen]}, warnings=tuple(warnings),
        kind="remove", confirm_label="Remove", question=about.question,
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
    about = await _chosen(request, data, guessed)
    chosen, warnings, today, marked = about
    if not chosen and about.question is None:
        raise _none_left(warnings, "No pill to delete.")
    lines = tuple(
        flag(f"**{pill.plan.name}** · {rules.schedule_text(pill.plan)} → deleted, with its history", pill.ref in marked)
        for _, pill in chosen
    )
    return Proposal(
        lines=lines, data={"pills": [{"pill": pill.ref} for _, pill in chosen]},
        warnings=(*warnings, "This deletes the history too and can't be undone"),
        kind="remove", destructive=True, confirm_label="Delete for good", question=about.question,
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
    shown = listing.card(await store.pills(request.user.id), day.today())
    return LiveReply(LIST_KEY, shown.text, shown)


async def state(request: Request) -> State:
    today = day.today()
    shown = rules.listed(await store.pills(request.user.id))
    return State(
        "The user's pills now (use the id, or the name)",
        tuple(f"{pill.ref}: {rules.plain(rules.describe_pill(pill, today))} [{rules.status_on(pill, today)}]" for pill in shown),
        empty="none yet",
    )


# ---------------------------------------------------------------------------
# Today: logging a dose by saying so, and the checklist
# ---------------------------------------------------------------------------
def _moment(said: str, now, not_before):
    """When a dose was taken, from the time given: today, not in the future and
    not before the dose before it. A time that could be morning or evening
    is the most recent one that can be right (at 9 pm, "8" is 8:00 pm)."""
    try:
        return timeinput.actual_moment(said, now, not_before)
    except timeinput.AmbiguousTime as unsure:
        today_ = day.day_of(now)
        possible = [day.at(today_, option) for option in unsure.options]
        return max(moment for moment in possible if moment <= now and (not_before is None or moment >= not_before))


def _not_today(pill: Pill, today_: date) -> str:
    state = rules.status_on(pill, today_)
    if state == PAUSED:
        return f"⏸️ **{pill.plan.name}** is paused: there is nothing to tick off today."
    if state == ENDED:
        return f"🏁 **{pill.plan.name}** has ended: there is nothing to tick off."
    if rules.is_off_day(pill, today_):
        return f"🗓️ **{pill.plan.name}** is taken {rules.days_text(pill.plan.schedule.days)}: there is nothing to tick off today."
    return f"🗓️ **{pill.plan.name}** starts {timeinput.format_date(pill.plan.start)}: there is nothing to tick off today."


def about(request: Request, things: list[tuple[int, int | None]]):
    """What an answer about these pills and doses does with its message once it
    is sent: records the line as theirs (`store.db_add_lines`), so a reply to
    it means that pill and that dose. Each is (pill id, the dose's occurrence
    id or None)."""
    things = list(things)

    async def placed(message_id: int) -> None:
        if things:
            await request.db.run(store.db_add_lines, request.user.id, message_id, things)

    return placed


def _of(step: "Step") -> list[tuple[int, int | None]]:
    """What a step's line is about."""
    if step.dose is not None:
        return [(step.dose.pill.id, step.dose.occurrence.id)]
    return [(step.pill.id, None)] if step.pill is not None else []


async def _log(request: Request, data: dict) -> tuple[str, list[tuple[int, int | None]]]:
    said, changed, things = [], False, []
    for item in data["doses"]:
        step = await _step(request, item)  # worked out afresh each time: the one before may have changed the day
        things += _of(step)
        if step.dose is None:
            said.append(step.say)
            continue
        said.append(await _do(step))
        changed = True
    return await _with_what_is_left(request.user.id, said, changed), things


async def log_doses(request: Request, data: dict, guessed: frozenset) -> str:
    """ "took my zinc", "had pill A at 9", "skip magnesium today", "I didn't take
    zinc": done at once, with no card (it is about today's doses, not the
    plan), read back before it is said, and the checklist follows."""
    return (await _log(request, data))[0]


async def log_answer(request: Request, data: dict, guessed: frozenset) -> Answer:
    """`log_doses`, as the action: its line is recorded as that pill's and that dose's."""
    said, things = await _log(request, data)
    return Answer(said, about(request, things))


def _recorded(save):
    """A plan card's Save, with the line it says recorded as the line of the
    pills on the card."""

    async def apply(request: Request, data: dict) -> Answer:
        said = await save(request, data)
        pills, things = await store.pills(request.user.id), []
        for item in data.get("pills", []):
            try:
                things.append((rules.find(pills, str(item.get("pill") or item.get("name") or "")).id, None))
            except UserError:
                continue
        return Answer(said, about(request, things))

    return apply


async def _with_what_is_left(user_id: int, said: list[str], changed: bool) -> str:
    if changed:
        checklist.changed(user_id)
        _, listed, _ = await checklist.view(user_id)
        said[-1] += f" · {today.left_text(listed)}"
    return "\n".join(said)


# A time given for a dose ticked off this recently is a correction of it, not another dose
CORRECTION_WINDOW = timedelta(minutes=5)


@dataclass
class Step:
    """What one "I took it" comes to, before anything is changed."""

    say: str = ""  # nothing to do: this is said as it is
    dose: Dose | None = None  # the dose it is about
    did: str = ""
    at: datetime | None = None
    was: datetime | None = None  # a correction of a dose already ticked off: when it had been taken
    asks: tuple[str, ...] = ()  # what is asked about on a card first: after the latest time, out of order, too close
    # No pill was named and nothing pointed at one: the code picked this one. Shown on a card, never done unseen
    picked: bool = False
    pill: Pill | None = None  # the pill it is about, also when there is nothing to do
    # Which pill is meant can't be told: the pills it could be, for the card to ask (with `say` as the plain line)
    which: tuple = ()
    # A dose of the day before, logged after midnight: that day. None for today's
    day: date | None = None
    # "That was dose 1": the dose this log was ticked off as. The log moves to `dose`; no second one is made
    moved_from: Dose | None = None
    # A dose of the same pill I logged in the last hour, when this would add another: the card says so
    another: Dose | None = None
    # A small line under a move's own: what becomes of the dose the log is moved away from
    extra: str = ""
    # "That was dose 1" with nothing logged today: the earlier days it could be about, for the card to ask
    days: tuple = ()


def db_last_logged(conn, user_id: int) -> int | None:
    """The pill whose dose the user changed last, by a button or by saying so."""
    events = occurrences.db_last_change(conn, user_id, TASK)
    found = occurrences.db_get(conn, events[-1].occurrence_id) if events else None
    return found.item_id if found is not None else None


def db_logged_lately(conn, user_id: int, since: datetime) -> int | None:
    """The pill of the last thing the user did to a dose, if that was since `since`:
    what the bot's latest pills message was about, and so what "it" means now."""
    events = occurrences.db_last_change(conn, user_id, TASK)
    if not events or events[-1].at < since:
        return None
    found = occurrences.db_get(conn, events[-1].occurrence_id)
    return found.item_id if found is not None else None


async def _unnamed(request: Request, listed: list[Dose], pointed: Pill | None, now: datetime, did: str) -> tuple[int | None, bool]:
    """Which pill is meant when none was named ("it", "the usual one"): (its id,
    whether the code only picked it). With an anchor it is that pill, and the
    dose is logged straight away: a reply to a message about one pill, or the
    pill a dose was logged for in the last few minutes. With no anchor the
    code picks the likeliest (the pill logged last; for a dose taken or
    skipped, one that still has a dose left today) and that is shown on a
    card with ❓, never logged unseen. None if there is nothing to pick from."""
    if pointed is not None:
        return pointed.id, False
    user_id = request.user.id
    lately = await request.db.run(db_logged_lately, user_id, now - CORRECTION_WINDOW)
    if lately is not None:
        # Never a line with no single subject: after "took zinc and iron", "it" names neither
        latest = set(await request.db.run(store.db_latest_line, user_id))
        return lately, len(latest) > 1 and lately in latest
    last = await request.db.run(db_last_logged, user_id)
    if did != checklist.NOT_TAKEN:
        left = {dose.pill.id for dose in listed if today.next_to_log(listed, dose.pill.id) is not None}
        if last not in left and len(left) == 1:
            return next(iter(left)), True
    return last, last is not None


async def _just_logged(dose: Dose, now: datetime) -> bool:
    """Whether the user ticked this dose off (or corrected it) a moment ago."""
    mine = [event for event in await occurrences.history(dose.occurrence.id) if event.source != occurrences.AUTOMATIC]
    return bool(mine) and now - mine[-1].at <= CORRECTION_WINDOW


async def _of_its_day(user_id: int, occurrence_id: int, today_: date) -> Dose | None:
    """A dose of an earlier day, found by its own id, among that day's doses."""
    found = await database.run(occurrences.db_get, occurrence_id)
    if found is None or found.day >= today_:
        return None
    _, listed, _ = await checklist.read(user_id, found.day)
    return next((each for each in listed if each.occurrence.id == occurrence_id), None)


async def _replied_to(request: Request, listed: list[Dose], today_: date) -> tuple[Pill | None, Dose | None]:
    """What a Discord reply points at, among today's messages: (the pill, the
    dose). A dose's own Taken / Skip message is that pill and that dose. The
    checklist is the pill on it, when there is only one. Neither if the
    message replied to is not one of these."""
    if request.replied_to is None:
        return None, None
    line = await request.db.run(store.db_line, request.replied_to)
    if line:
        # A line the bot said: about one pill it is that pill, and that dose if it is one of today's
        ids, doses = {pill_id for pill_id, _ in line}, {occurrence_id for _, occurrence_id in line if occurrence_id is not None}
        if len(ids) != 1:
            return None, None
        dose = next((each for each in listed if each.occurrence.id in doses), None) if len(doses) == 1 else None
        if dose is None and len(doses) == 1:
            # A line about a dose of a day that is over ("actually I didn't", replied to last
            # night's line after midnight): that dose, on its own day
            dose = await _of_its_day(request.user.id, next(iter(doses)), today_)
        pill = await store.pill(next(iter(ids)))
        return (pill, dose) if pill is not None and pill.user_id == request.user.id else (None, None)
    held = await request.db.run(store.db_messages, request.user.id, today_)
    message = next((each for each in held if each.message_id == request.replied_to), None)
    if message is None:
        # A reminder is about one dose: a reply to it means that dose
        from tasks.pills import reminders  # it imports this module's checks

        reminded = await reminders.dose_of(request.replied_to, listed)
        return (reminded.pill, reminded) if reminded is not None else (None, None)
    if message.kind == DOSE:
        dose = next((each for each in listed if each.occurrence.id == message.occurrence_id), None)
        return (dose.pill, dose) if dose is not None else (None, None)
    on_it = {dose.pill.id: dose.pill for dose in listed}
    return (next(iter(on_it.values())), None) if len(on_it) == 1 else (None, None)


async def _step(request: Request, item: dict) -> Step:
    """What an item of the message means for today's doses as they stand now.
    Nothing is changed here."""
    user_id = request.user.id
    pills, listed, today_ = await checklist.view(user_id)
    now = clock.now()
    named, picked = item.get("pill"), False
    # Where I point beats what is newest: a reply to a dose's message or to the checklist
    pointed, pointed_dose = await _replied_to(request, listed, today_)
    if is_reference(named) or not str(named or "").strip():
        # "it" is worked out here and never by Claude
        last, picked = await _unnamed(request, listed, pointed, now, item["did"])
        if last is None:
            return Step("⚠️ Which pill? Say its name.", which=tuple(_could_be(listed, item["did"])))
        named = f"{rules.ID_PREFIX}{last}"
    try:
        pill = rules.find(pills, str(named), request.text)
    except rules.Ambiguous as unclear:
        return Step(f"⚠️ {unclear}", which=tuple(unclear.candidates))
    except UserError as error:
        return Step(f"⚠️ {error}")
    step = await _for_pill(request, item, pill, listed, today_, now, pointed_dose)
    step.picked, step.pill = picked and step.dose is not None, pill
    if step.asks and step.dose is not None and step.did == checklist.TAKEN and step.was is None and step.moved_from is None and step.day is None:
        # It would add a dose, and is asked about anyway: one logged a moment ago is said first
        step.another = await logged_lately(listed, step.dose, now)
    return step


def _on_its_day(item: dict, dose: Dose, today_: date, now: datetime) -> Step:
    """What a reply to a line about a dose of an earlier day means for that dose.
    "Actually I didn't" makes it missed (its day is over); a time puts its time
    right. Nothing else is done to a day that is over."""
    on = dose.occurrence.day
    when = day_said(on, today_)
    if item["did"] == checklist.NOT_TAKEN:
        if dose.occurrence.state != occurrences.DONE:
            return Step(f"↩️ {dose.label} was not ticked off {when}: nothing to change.", pill=dose.pill)
        return Step(dose=dose, did=checklist.NOT_TAKEN, at=now, day=on, pill=dose.pill)
    if item["did"] == checklist.TAKEN and str(item.get("at", "")).strip() and dose.occurrence.state == occurrences.DONE:
        try:
            at = day.at(on, timeinput.parse_time(str(item["at"])))
        except timeinput.AmbiguousTime as unsure:
            # The half of the day that is closest to when it was logged
            logged = dose.occurrence.actual_at or day.at(on, time(12, 0))
            at = min((day.at(on, option) for option in unsure.options), key=lambda moment: abs((moment - logged).total_seconds()))
        except Exception:
            return Step(f"⚠️ {rules.plain(dose.label)}: “{item['at']}” is not a time I can read.", pill=dose.pill)
        return Step(dose=dose, did=checklist.TAKEN, at=at, was=dose.occurrence.actual_at, day=on, pill=dose.pill)
    return Step(f"💊 That line is about {when}: say what to put right for it, or say it of today.", pill=dose.pill)


def _could_be(listed: list[Dose], did: str) -> list[Pill]:
    """The pills an unnamed "I took it" could be about today: those with a dose
    still to log, or for "I didn't take it" those with a dose ticked off."""
    found: dict[int, Pill] = {}
    for dose in listed:
        fits = today.last_dealt_with(listed, dose.pill.id) if did == checklist.NOT_TAKEN else today.next_to_log(listed, dose.pill.id)
        if fits is not None:
            found.setdefault(dose.pill.id, dose.pill)
    return list(found.values())


async def _for_pill(request: Request, item: dict, pill: Pill, listed: list[Dose], today_: date, now: datetime, pointed_dose: Dose | None) -> Step:
    """What an item means for the pill it is about."""
    if pointed_dose is not None and pointed_dose.pill.id == pill.id and pointed_dose.occurrence.day < today_:
        # A reply to a line about a dose of a day that is over: the correction is for that day
        return _on_its_day(item, pointed_dose, today_, now)
    if pointed_dose is not None and pointed_dose.pill.id == pill.id and item.get("dose") is None:
        # The message replied to is about one dose: that dose, as if named by its number.
        # A pill or a dose number I state still wins over where I point
        item = {**item, "dose": pointed_dose.number}
    said_day = str(item.get("day") or "")
    if item.get("correction") and item["did"] == checklist.TAKEN and item.get("dose") is not None:
        # "That was dose 1": checked against what I logged, card or no card. That log moves; nothing is ever added
        return await _correcting(request, item, pill, listed, today_, now, said_day)
    if said_day in DAYS_BEFORE:
        # "took zinc last night at 11": a dose of the day before, whatever today looks like
        return await _yesterday(request, item, pill, now, said_day)
    if not rules.is_taken_on(pill, today_):
        return Step(_not_today(pill, today_))
    did, name = item["did"], pill.plan.name
    if item.get("dose") is not None:
        # A dose I name by its number is that dose, exactly: never the one the code would have picked
        return _numbered(pill, listed, today_, item, now)
    taken = today.last_taken(listed, pill.id)
    if did == checklist.NOT_TAKEN:
        # Taken or skipped by me (Skip is said in words in round 4, and "undo that" puts it back)
        dealt = today.last_dealt_with(listed, pill.id)
        if dealt is None:
            return Step(f"💊 **{name}** isn't ticked off today: there is nothing to change.")
        return Step(dose=dealt, did=did, at=now)
    if did == checklist.SKIP:
        pending = today.next_pending(listed, pill.id)
        if pending is None:
            return Step(f"💊 **{name}** has nothing left to take today.")
        return Step(dose=pending, did=did, at=now)

    given = str(item.get("at", "")).strip()
    if taken is not None and given:
        # A time for a dose just ticked off, or one earlier than the dose last taken (which no
        # later dose could have), is that dose's time put right: old → new, never a second dose
        earlier = today.before(listed, taken)
        try:
            at = _moment(given, now, earlier.occurrence.actual_at if earlier else None)
        except UserError as error:
            at, problem = None, f"⚠️ {rules.plain(taken.label)}: {error}"
        if at is None:
            if await _just_logged(taken, now):
                return Step(problem)
        elif at < taken.occurrence.actual_at or await _just_logged(taken, now):
            if at == taken.occurrence.actual_at:
                return Step(f"{today.line(taken)} already")
            return Step(dose=taken, did=checklist.TAKEN, at=at, was=taken.occurrence.actual_at)
    target = today.next_to_log(listed, pill.id)
    if target is None:
        # Already so: named and shown, as it stands on the checklist
        return Step(f"{today.line(taken)} already" if taken is not None else f"💊 **{name}** has nothing left to take today.")
    try:
        at = _moment(given, now, taken.occurrence.actual_at if taken else None) if given else now
    except UserError as error:
        if given and _small_hours(now):
            # Past midnight, a time that has not come yet today was last night: asked first, never assumed
            before = await _yesterday(request, item, pill, now, "")
            if before.dose is not None:
                return before
        return Step(f"⚠️ {rules.plain(target.label)}: {error}")
    return Step(dose=target, did=checklist.TAKEN, at=at, asks=(*_missed(target), *_late(pill, today_, at), *_too_soon(pill, taken, at)))


# --- a dose of the day before, logged after midnight ---------------------------------------------
YESTERDAY, LAST_NIGHT = "yesterday", "last_night"
DAYS_BEFORE = (YESTERDAY, LAST_NIGHT)
SMALL_HOURS = time(4, 0)  # until then, a time later than now is taken as last night's (and asked about)


def _small_hours(now: datetime) -> bool:
    return day.local_time(now) < SMALL_HOURS


def _time_on(said: str, on: date, not_before: datetime | None, not_after: datetime, evening: bool) -> tuple[datetime, bool]:
    """A time of day as I said it, placed on a day that is over: (the moment,
    whether it could as well have been the other half of the day). "Last
    night at 11" is the evening, and that is no guess."""
    try:
        return day.at(on, timeinput.parse_time(said)), False
    except timeinput.AmbiguousTime as unsure:
        fits = sorted(moment for moment in (day.at(on, option) for option in unsure.options) if (not_before is None or moment >= not_before) and moment <= not_after)
        if not fits:
            raise UserError(f"{said} doesn't fit yesterday's doses.")
        return fits[-1], len(fits) > 1 and not evening


async def _yesterday(request: Request, item: dict, pill: Pill, now: datetime, said_day: str) -> Step:
    """What "I took it last night" means for the day before's doses. Said in
    so many words with a time that reads one way, it is done at once; when
    the day or the time had to be worked out, the step asks first.
    `said_day` is "" when nobody said yesterday: the time alone points there."""
    name, on = pill.plan.name, day.day_of(now) - timedelta(days=1)
    if item["did"] != checklist.TAKEN:
        return Step("⚠️ For yesterday I can only log a dose as taken.")
    _, listed, _ = await checklist.read(request.user.id, on)
    mine = sorted((dose for dose in listed if dose.pill.id == pill.id), key=lambda dose: dose.number)
    if not mine:
        return Step(f"💊 **{name}** had nothing to take yesterday.")
    wanted = item.get("dose")
    if wanted is not None:
        target = next((dose for dose in mine if dose.number == wanted), None)
        if target is None:
            return Step(f"💊 **{name}** had {len(mine)} dose{'' if len(mine) == 1 else 's'} yesterday, not a dose {wanted}.")
    else:
        target = next((dose for dose in mine if dose.occurrence.state != occurrences.DONE), None)
    if target is None or target.occurrence.state == occurrences.DONE:
        return Step(f"{today.line(target or mine[-1])} · yesterday already")
    earlier = [dose.occurrence.actual_at for dose in mine if dose.number < target.number and dose.occurrence.state == occurrences.DONE and dose.occurrence.actual_at]
    last_moment = min(day.end_of(on) - timedelta(minutes=1), now)
    given, asks = str(item.get("at", "")).strip(), []
    if given:
        try:
            at, either = _time_on(given, on, max(earlier) if earlier else None, last_moment, said_day == LAST_NIGHT)
        except UserError as error:
            return Step(f"⚠️ {rules.plain(target.label)}: {error}")
        if earlier and at < max(earlier):
            return Step(f"⚠️ {rules.plain(target.label)}: {timeinput.format_moment(at)} is before the dose before it, at {timeinput.format_moment(max(earlier))}.")
        if either:
            asks.append(f"“{given}” could be morning or evening: taken as {timeinput.format_moment(at)}.")
    else:
        planned = today.shown_time(target) or target.due.at
        at = min(planned, last_moment) if planned is not None else last_moment
        asks.append(f"No time was given: {'its planned time' if planned is not None else 'the end of the day'} is used ({timeinput.format_moment(at)}).")
    if not said_day:
        asks.insert(0, f"It is past midnight and {timeinput.format_moment(at)} has not come yet today, so this is yesterday's dose.")
    return Step(dose=target, did=checklist.TAKEN, at=at, asks=(*asks, *_late(pill, on, at)), day=on)


def _too_soon(pill: Pill, last: Dose | None, at: datetime) -> tuple[str, ...]:
    """A dose taken before the gap since the one before it has passed: asked about first."""
    plan = pill.plan.schedule
    taken = last.occurrence.actual_at if last is not None else None
    if plan.gap is None or taken is None:
        return ()
    # To the minute, as times are said and shown: three hours after 8:40 is 11:40, whatever the seconds were
    at, taken = at.replace(second=0, microsecond=0), taken.replace(second=0, microsecond=0)
    if not timedelta(0) <= at - taken < plan.gap:
        return ()
    minutes = max(0, round((at - taken).total_seconds() / 60))
    # Under a minute there is no length worth saying: "0m after" reads as a mistake
    when = f"{rules.gap_text(minutes)}{_after(last)}" if minutes else f"just now{_just(last)}"
    return (f"That's {when}. {GAP_SAID} {rules.gap_text(plan.gap_minutes)}.",)


GAP_SAID = "The gap is at least"  # the sentence about a dose taken too soon


def _after(last: Dose) -> str:
    return f" after dose {last.number}, taken {timeinput.format_moment(last.occurrence.actual_at.replace(second=0, microsecond=0))}"


def _just(last: Dose) -> str:
    return f": dose {last.number} was taken {timeinput.format_moment(last.occurrence.actual_at.replace(second=0, microsecond=0))}"


def asked_about(dose: Dose, listed: list[Dose], at: datetime) -> tuple[str, ...]:
    """What ticking this dose off at `at` would be asked about first: it was
    missed, it is after its pill's latest time, or it is too soon after the
    dose before it. One place for a message, the typed shortcut and a button."""
    return (*_missed(dose), *_late(dose.pill, dose.occurrence.day, at), *_too_soon(dose.pill, today.before(listed, dose), at))


def _missed(dose: Dose) -> tuple[str, ...]:
    """A dose the bot has marked missed: logging it as taken after all is
    asked about first, never done unseen."""
    if dose.occurrence.state != occurrences.MISSED:
        return ()
    due = today.shown_time(dose) or dose.due.at
    return (f"Dose {dose.number} was missed" + (f" (due {timeinput.format_moment(due)})" if due else "") + ".",)


def asking(dose: Dose, asks: tuple[str, ...], another: Dose | None = None, moving: bool = False) -> str:
    """The question on the card that asks first: what is unusual, then what
    Log it would do. When I logged a dose of this pill in the last hour
    (`another`), that is said first and in so many words: the card would add
    a second dose, and never reads as if it only confirmed the first."""
    if another is not None:
        # The dose is named once, in the first sentence: "That's 20m later", not "…after dose 1, taken 8:00 am" again
        rest = [each.replace(_after(another), " later").replace(_just(another), "") if GAP_SAID in each else each for each in asks]
        return " ".join((already_logged(another), *rest, "Add another dose?"))
    if moving:
        return f"{' '.join(asks)} Move it anyway?"
    return f"{' '.join(asks)} " + ("Log it as taken now?" if dose.occurrence.state == occurrences.MISSED else "Log it anyway?")


def next_change(dose: Dose, listed: list[Dose], at: datetime) -> str:
    """What ticking this dose off at `at` would do to when the pill's next
    dose is due, as a small line `next: dose 2 · old → new`; nothing when it
    changes nothing or no dose is left."""
    mine = sorted((each for each in listed if each.pill.id == dose.pill.id), key=lambda each: each.number)
    coming = next((each for each in mine if each.number > dose.number and each.is_pending), None)
    if coming is None:
        return ""
    plan = dose.pill.plan.schedule
    by_number = {each.number: each.occurrence for each in mine}
    so_far = []
    for number in range(1, plan.per_day + 1):
        there = by_number.get(number)
        if number == dose.number:
            so_far.append(at)
        elif there is None or there.state == occurrences.PENDING:
            so_far.append(core_schedule.OPEN)
        else:
            so_far.append(there.actual_at if there.state == occurrences.DONE and there.actual_at else core_schedule.OUT)
    after = core_schedule.dues(plan, dose.occurrence.day, so_far)[coming.number - 1].at
    if after is not None and after > core_schedule.limit(plan, dose.occurrence.day):
        after = None
    before = today.shown_time(coming)
    if before == after or (before is not None and after is not None and before.replace(second=0, microsecond=0) == after.replace(second=0, microsecond=0)):
        return ""
    old = f"`{timeinput.format_moment(before)}`" if before else "no time"
    new = f"`{timeinput.format_moment(after)}`" if after else f"too late for today ({limits.limit_text(plan)})"
    return f"-# next: dose {coming.number} · {old} → {new}"


def _late(pill: Pill, today_: date, at: datetime) -> tuple[str, ...]:
    plan = pill.plan.schedule
    return (f"That's after the latest time, {limits.limit_text(plan)}.",) if limits.is_after_limit(plan, today_, at) else ()


def _out_of_place(listed: list[Dose], dose: Dose, at: datetime, logging: bool) -> tuple[str, ...]:
    """What a time for this dose breaks among the pill's other doses today: the
    order they were taken in, or the gap between them. Said on the card."""
    plan = dose.pill.plan.schedule
    said = []
    for other in sorted((each for each in listed if each.pill.id == dose.pill.id and each.number != dose.number), key=lambda each: each.number):
        earlier, taken = other.number < dose.number, other.occurrence.actual_at
        if other.occurrence.state != occurrences.DONE or taken is None:
            if logging and earlier and limits.decided_by_the_bot(other.occurrence):
                said.append(f"Dose {other.number} isn't ticked off.")
            continue
        shown = f"dose {other.number}, taken {timeinput.format_moment(taken)}"
        if at == taken:
            said.append(f"That's the same time as {shown}.")
        elif (at < taken) if earlier else (at > taken):
            said.append(f"That's {'before' if earlier else 'after'} {shown}.")
        elif plan.gap is not None and abs(at - taken) < plan.gap:
            said.append(f"That's less than {rules.gap_text(plan.gap_minutes)} {'after' if earlier else 'before'} {shown}.")
    return tuple(said)


# A dose logged this recently is named on a card that would add another one
RECENT = timedelta(hours=1)


async def _logged_at(dose: Dose) -> datetime | None:
    """When I last ticked this dose off or put it right: when I said so, not when it was taken."""
    mine = [event for event in await occurrences.history(dose.occurrence.id) if event.source != occurrences.AUTOMATIC]
    return mine[-1].at if mine else None


async def _last_logged(listed: list[Dose], pill_id: int, besides: Dose | None = None) -> tuple[Dose, datetime] | None:
    """The dose of this pill that I logged last today, and when I logged it."""
    found = []
    for dose in listed:
        if dose.pill.id != pill_id or dose.occurrence.state != occurrences.DONE or dose.occurrence.actual_at is None:
            continue
        if besides is not None and dose.occurrence.id == besides.occurrence.id:
            continue
        logged = await _logged_at(dose)
        if logged is not None:
            found.append((logged, dose.number, dose))
    if not found:
        return None
    logged, _, dose = max(found, key=lambda each: each[:2])
    return dose, logged


async def logged_lately(listed: list[Dose], dose: Dose, now: datetime) -> Dose | None:
    """Another dose of the same pill that I logged within the last hour, if any:
    what a card that would add this one says first."""
    last = await _last_logged(listed, dose.pill.id, besides=dose)
    return last[0] if last is not None and now - last[1] <= RECENT else None


def already_logged(another: Dose) -> str:
    return f"You already logged dose {another.number} at {timeinput.format_moment(another.occurrence.actual_at)}."


def _without(listed: list[Dose], gone: Dose) -> list[Dose]:
    """The day's doses as they would stand with one of them not ticked off."""
    return [Dose(each.pill, replace(each.occurrence, state=occurrences.PENDING, actual_at=None), each.due) if each.occurrence.id == gone.occurrence.id else each for each in listed]


MOVE_DAYS = 7  # how far back "which day was it?" looks for a day with a log
MOVE_CHOICES = 3  # and how many of those days it offers


def day_said(on: date, today_: date) -> str:
    """An earlier day in a sentence: "yesterday", or "on Mon 12 Oct"."""
    return "yesterday" if on == today_ - timedelta(days=1) else f"on {on:%a} {on.day} {on:%b}"


def _day_label(on: date, today_: date) -> str:
    return "Yesterday" if on == today_ - timedelta(days=1) else f"{on:%a} {on.day} {on:%b}"


async def _days_logged(request: Request, pill: Pill, today_: date) -> tuple[date, ...]:
    """The latest earlier days on which a dose of this pill was ticked off, newest first."""
    found = await request.db.run(occurrences.db_between, request.user.id, checklist.TASK, today_ - timedelta(days=MOVE_DAYS), today_ - timedelta(days=1), pill.id)
    logged = sorted({each.day for each in found if each.state == occurrences.DONE and each.actual_at is not None}, reverse=True)
    return tuple(logged[:MOVE_CHOICES])


async def _correcting(request: Request, item: dict, pill: Pill, listed: list[Dose], today_: date, now: datetime, said_day: str) -> Step:
    """ "That was dose 1", about a dose already logged: that log is moved to the
    dose I say, with the time it has (or the one I give with it). Always shown
    on a card, old → new, and never a second log: a correction logs nothing.

    Only today's logs are moved unasked. With nothing ticked off today it says
    so and asks which day (a button for each of the latest days with a log);
    a day I name, or pick there, is that day."""
    name, number = pill.plan.name, item["dose"]
    on = date.fromisoformat(item["on"]) if item.get("on") else (today_ - timedelta(days=1) if said_day in DAYS_BEFORE else today_)
    earlier = on != today_
    if earlier:
        _, listed, _ = await checklist.read(request.user.id, on)
    target = next((each for each in listed if each.pill.id == pill.id and each.number == number), None)
    if target is None or target.occurrence.state == occurrences.DONE:
        if not earlier:
            return _numbered(pill, listed, today_, item, now)  # no such dose, or it is that dose already: said as it is
        return Step(f"💊 **{name}** had no dose {number} {day_said(on, today_)}." if target is None else f"{today.line(target)} · {day_said(on, today_)} already")
    last = await _last_logged(listed, pill.id)
    if last is None:
        if earlier:
            return Step(f"💊 **{name}** has no dose ticked off {day_said(on, today_)}: there is nothing to move.")
        nothing = f"💊 **{name}** has no dose ticked off today: there is nothing to move."
        return Step(nothing, days=await _days_logged(request, pill, today_))
    logged_as = last[0]
    given, was = str(item.get("at", "")).strip(), logged_as.occurrence.actual_at
    if given and earlier:
        return Step("⚠️ For an earlier day the log is moved with the time it has: give the new time on its own afterwards.")
    try:
        at = _moment(given, now, None) if given else was
    except UserError as error:
        return Step(f"⚠️ {rules.plain(target.label)}: {error}")
    asks = (*_out_of_place(_without(listed, logged_as), target, at, logging=False), *_late(pill, on, at))
    step = Step(dose=target, did=checklist.TAKEN, at=at, was=was if at != was else None, asks=asks, moved_from=logged_as, day=on if earlier else None)
    step.extra = f"-# dose {logged_as.number} · not taken {day_said(on, today_).removeprefix('on ')}" if earlier else freed(step, listed)
    return step


def freed(step: Step, listed: list[Dose]) -> str:
    """What becomes of the dose a log is moved away from, as a small line:
    it is to take again, and when it is then due."""
    logged_as, really = step.moved_from, step.dose
    plan = really.pill.plan.schedule
    by_number = {each.number: each.occurrence for each in listed if each.pill.id == really.pill.id}
    so_far = []
    for number in range(1, plan.per_day + 1):
        there = by_number.get(number)
        if number == really.number:
            so_far.append(step.at)
        elif number == logged_as.number or there is None or there.state == occurrences.PENDING:
            so_far.append(core_schedule.OPEN)
        else:
            so_far.append(there.actual_at if there.state == occurrences.DONE and there.actual_at else core_schedule.OUT)
    due = core_schedule.dues(plan, really.occurrence.day, so_far)[logged_as.number - 1].at
    if due is not None and due > core_schedule.limit(plan, really.occurrence.day):
        return f"-# dose {logged_as.number} · too late for today ({limits.limit_text(plan)})"
    return f"-# dose {logged_as.number} · still to take" + (f" · `{timeinput.format_moment(due)}`" if due is not None else "")


def _numbered(pill: Pill, listed: list[Dose], today_: date, item: dict, now: datetime) -> Step:
    """What an item means when it says which dose by its number ("dose 1 at
    9am"): that dose is logged, or its time put right (old → new). A time
    that breaks the order or the gap is not refused: the card asks."""
    number, of, name = item["dose"], pill.plan.schedule.per_day, pill.plan.name
    dose = next((each for each in listed if each.pill.id == pill.id and each.number == number), None)
    if dose is None:
        return Step(f"⚠️ **{name}** is {'one dose' if of == 1 else f'{of} doses'} a day: there is no dose {number}.")
    did, state = item["did"], dose.occurrence.state
    if did == checklist.NOT_TAKEN:
        if state != occurrences.DONE and not (state == occurrences.SKIPPED and not dose.occurrence.automatic):
            return Step(f"💊 {dose.label} isn't ticked off today: there is nothing to change.")
        return Step(dose=dose, did=did, at=now)
    if did == checklist.SKIP:
        return Step(dose=dose, did=did, at=now) if dose.is_pending else Step(f"{today.line(dose)} already")
    given = str(item.get("at", "")).strip()
    taken = dose.occurrence.actual_at if state == occurrences.DONE else None
    if state == occurrences.DONE and not given:
        return Step(f"{today.line(dose)} already")
    try:
        at = _moment(given, now, None) if given else now
    except UserError as error:
        return Step(f"⚠️ {rules.plain(dose.label)}: {error}")
    if taken is not None and at == taken:
        return Step(f"{today.line(dose)} already")
    asks = (() if taken is not None else _missed(dose)) + _out_of_place(listed, dose, at, logging=taken is None) + (() if taken is not None else _late(pill, today_, at))
    return Step(dose=dose, did=checklist.TAKEN, at=at, was=taken, asks=asks)


async def _do(step: Step) -> str:
    """Make the change a step stands for, read back, and say it in a line."""
    if step.moved_from is not None:
        if step.moved_from.occurrence.state != occurrences.DONE:
            raise UserError(f"{rules.plain(step.moved_from.label)} has changed since: nothing was moved.")
        await checklist.move(step.moved_from, step.dose, step.at, occurrences.MESSAGE)
        return "✏️ " + _move_line(step)
    if step.was is not None:
        return checklist.corrected_text(await checklist.correct(step.dose, step.at, occurrences.MESSAGE), step.was)
    if step.day is not None and step.did == checklist.NOT_TAKEN:
        # A dose of a day that is over, not taken after all: missed, as nothing is left to take that day
        missed = await checklist.unmark_past(step.dose)
        return f"↩️ {missed.label} · not taken after all · {day_said(step.day, day.day_of(clock.now()))}"
    was_skipped = step.did == checklist.NOT_TAKEN and step.dose.occurrence.state == occurrences.SKIPPED
    said = checklist.marked_text(await checklist.mark(step.dose, step.did, step.at, occurrences.MESSAGE), step.did)
    if was_skipped:
        said = said.replace("no longer ticked off", "not skipped after all")
    return f"{said} · yesterday" if step.day is not None else said


# --- a dose logged after the pill's latest time is asked about first ------------------------------
def _pill_guessed(guessed: frozenset, index: int) -> bool:
    """Whether Claude guessed which pill this dose is of. A pill named exactly, one a
    part of a name picks out alone, and "it" (which the code resolves) are no guess."""
    return is_guessed(guessed, "doses", index, "pill")


async def log_asks(request: Request, data: dict, guessed: frozenset = frozenset()) -> bool:
    """Whether logging needs a card: when which pill is meant was a guess,
    Claude's or the code's own pick for a pill nobody named (a guess is never
    saved unseen), when a dose would be ticked off after its pill's latest
    time, or when a dose named by its number would be out of order or too
    close to another."""
    for index, item in enumerate(data["doses"]):
        if _pill_guessed(guessed, index):
            return True
        step = await _step(request, item)
        if step.asks or step.picked or step.which or step.days or step.moved_from is not None:
            return True  # `which`: the card asks which pill, never a message of its own; a log is never moved unseen
    return False


def _move_line(step: Step) -> str:
    """A log moved from one dose to another, and the day when it is not today's."""
    said = checklist.moved_text(step.moved_from, step.dose, step.at, step.was)
    return f"{said} · {day_said(step.day, day.today()).removeprefix('on ')}" if step.day is not None else said


def _preview(step: Step) -> str:
    """A step on the card, before it is done."""
    if step.moved_from is not None:
        return _move_line(step)
    if step.was is not None:
        return f"{step.dose.label} · taken {timeinput.format_moment(step.was)} → {timeinput.format_moment(step.at)}"
    if step.did == checklist.TAKEN:
        return f"{step.dose.label} · taken {timeinput.format_moment(step.at)}" + (" · yesterday" if step.day is not None else "")
    return f"{step.dose.label} · " + ("skipped" if step.did == checklist.SKIP else "no longer ticked off")


async def log_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """The card shown before a dose is logged: when the pill was a guess (its
    line is marked ❓, with Save and Cancel), or after its pill's latest time
    or out of order (what would be logged, with the time, and the question:
    Log it does it)."""
    lines, held, warnings, asked = [], [], [], False
    question, moving_only = None, True
    for index, item in enumerate(data["doses"]):
        step = await _step(request, item)
        moving_only = moving_only and (step.dose is None or step.moved_from is not None)
        if step.which and question is None:
            # One question, with a button a pill: each answer is the whole message again with this dose's pill named
            text = "Which pill?" if not str(item.get("pill") or "").strip() or is_reference(item.get("pill")) else rules.plain(step.say.removeprefix("⚠️ "))
            question = Question(text, tuple(
                Choice(pill.plan.name, {"doses": [{**each, "pill": pill.ref} if at == index else dict(each) for at, each in enumerate(data["doses"])]}, ("pill",))
                for pill in step.which
            ))
            continue
        if step.days and question is None:
            # Only today's logs are moved unasked: it says so, and asks which day, a button a day
            today_ = day.today()
            question = Question(f"{rules.plain(step.say.removeprefix('💊 ')).removesuffix(': there is nothing to move.')}. Which day was it?", tuple(
                Choice(_day_label(on, today_), {"doses": [{**each, "on": on.isoformat()} if at == index else dict(each) for at, each in enumerate(data["doses"])]}, ("on",))
                for on in step.days
            ))
            trace.note("correction check: nothing of that pill is logged today, and only today's logs are moved unasked: the card asks which day")
            continue
        if step.dose is None:
            warnings.append(step.say.removeprefix("⚠️ "))
            continue
        lines.append(flag(_preview(step), _pill_guessed(guessed, index) or step.picked))
        asked = asked or bool(step.asks)
        if step.another is not None:
            trace.note(f"recent-log check: dose {step.another.number} was logged in the last hour, so the card says so before it adds another")
        if step.moved_from is not None:
            trace.note(f"correction check: against what was logged, not only an open card: the log of dose {step.moved_from.number} is moved to dose {step.dose.number}, and nothing is added")
            if step.extra:
                lines.append(step.extra)
            if step.asks:
                warnings.append(asking(step.dose, step.asks, moving=True))
        elif step.asks:
            warnings.append(asking(step.dose, step.asks, step.another))
            _, listed, _ = await checklist.view(request.user.id)
            moved = next_change(step.dose, listed, step.at) if step.did == checklist.TAKEN and step.was is None and step.day is None else ""
            if moved:
                lines.append(moved)
        held.append({
            "occurrence": step.dose.occurrence.id, "did": step.did, "moment": step.at.isoformat(),
            **({"was": step.was.isoformat()} if step.was is not None else {}),
            **({"day": step.day.isoformat()} if step.day is not None else {}),
            **({"moved_from": step.moved_from.occurrence.id} if step.moved_from is not None else {}),
        })
    if not held and question is None:
        raise UserError("; ".join(warnings) or "Nothing to log.")
    # "Log it" answers a question the card asks; a guess to look over is an ordinary Save
    return Proposal(
        lines=tuple(lines), data={"doses": held}, warnings=tuple(warnings), kind="change",
        confirm_label=("Move it" if moving_only else "Log it") if asked else "Save", question=question, risky=asked,
    )


def log_anyway(dose: Dose, at: datetime, asks: tuple[str, ...], listed: list[Dose] | tuple = (), another: Dose | None = None) -> Proposal:
    """The card that asks before a dose is ticked off when it was missed, or
    at a time that is too soon or after the latest time: the same card
    whether the time was said in a message or typed into a reminder's form.
    With `listed` (the day's doses) it shows what that does to the next
    dose's time; with `another` (a dose of the pill logged in the last hour,
    `logged_lately`) it says so first. Log it does it."""
    step = Step(dose=dose, did=checklist.TAKEN, at=at, asks=asks)
    held = {"occurrence": dose.occurrence.id, "did": step.did, "moment": at.isoformat()}
    moved = next_change(dose, list(listed), at) if listed else ""
    return Proposal(lines=(_preview(step), *([moved] if moved else [])), data={"doses": [held]}, warnings=(asking(dose, asks, another),), kind="change", confirm_label="Log it", risky=True)


async def _held(request: Request, data: dict) -> list[Step]:
    """The steps a card holds, on the doses as they are now."""
    _, listed, _ = await checklist.view(request.user.id)
    by_id = {dose.occurrence.id: dose for dose in listed}
    steps = []
    for item in data["doses"]:
        on = date.fromisoformat(item["day"]) if item.get("day") else None
        if on is not None:
            # A dose of the day before: looked up on its own day, which is never changed by looking
            _, before, _ = await checklist.read(request.user.id, on)
            pool = {each.occurrence.id: each for each in before}
        else:
            pool = by_id
        dose = pool.get(item["occurrence"])
        if dose is None:
            raise UserError("That dose isn't on today's checklist any more." if on is None else "That dose of yesterday's is no longer there.")
        was = datetime.fromisoformat(item["was"]) if item.get("was") else None
        moved_from = pool.get(item["moved_from"]) if item.get("moved_from") is not None else None
        if item.get("moved_from") is not None and moved_from is None:
            raise UserError("That dose isn't on today's checklist any more.")
        steps.append(Step(dose=dose, did=item["did"], at=datetime.fromisoformat(item["moment"]), was=was, day=on, moved_from=moved_from))
    return steps


async def log_save(request: Request, data: dict) -> str:
    """Log it: exactly what the card showed, with the times it showed."""
    said = [await _do(step) for step in await _held(request, data)]
    return await _with_what_is_left(request.user.id, said, True)


async def log_saved(request: Request, data: dict) -> Answer:
    """`log_save`, as the action: the card, once saved, is the line of those doses."""
    steps = await _held(request, data)
    return Answer(await log_save(request, data), about(request, [thing for step in steps for thing in _of(step)]))


async def log_check(request: Request, data: dict) -> str:
    """Read each dose back: it is in the state, and at the time, the card said."""
    wrong = []
    for step in await _held(request, data):
        state, at = step.dose.occurrence.state, step.dose.occurrence.actual_at
        wanted = {checklist.TAKEN: occurrences.DONE, checklist.SKIP: occurrences.SKIPPED}.get(step.did, occurrences.PENDING)
        if state != wanted or (step.did == checklist.TAKEN and at != step.at):
            wrong.append(f"{rules.plain(step.dose.label)} is still {state}")
        if step.moved_from is not None and step.moved_from.occurrence.state == occurrences.DONE:
            wrong.append(f"{rules.plain(step.moved_from.label)} is still ticked off")
    return "; ".join(wrong)


async def show_today(request: Request, data: dict, guessed: frozenset) -> str:
    """ "what pills are left?": the answer itself, where it was asked (a
    question is never answered with only where to look). Its first line
    names no pill; a pointer to the checklist in the hub may follow it, small.
    Asking posts nothing in the hub: `pills` (the word) is the checklist."""
    _, listed, _ = await checklist.view(request.user.id)
    said = today.left_answer(listed, clock.now())
    where = hub.channel_id()
    if listed and where is not None and where != request.channel_id and not dms.is_dm(request.channel_id):
        said += f"\n-# the checklist is in <#{where}>"
    return said


def elsewhere_text(where: int) -> str:
    """The line that points to the checklist when it was asked for somewhere else."""
    return f"💊 Today's checklist is in <#{where}>."


async def names(request: Request) -> list[str]:
    """The names of the user's pills: a message that says one is for this task."""
    return [pill.plan.name for pill in rules.listed(await store.pills(request.user.id))]


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
        "out for a pill with no set time.",
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
    Field(
        "weekdays",
        "Only when it is taken on certain days of the week: those days. \"weekdays only\" -> [mon, tue, wed, thu, fri]; "
        "\"Mon Wed Fri\" -> [mon, wed, fri]; \"at weekends\" -> [sat, sun]. Give the full list it is taken on from now "
        "on. Leave out for a pill taken every day, and when the user says nothing about days.",
        LIST,
        choices=rules.DAY_WORDS,
    ),
)
_OFF_THE_CARD = Field(
    "remove",
    "Only in a follow-up to an open card: true to take this pill off the card (\"not the iron\").",
    BOOLEAN,
)
_CLEAR = Field(
    "clear",
    "The settings the user wants taken away from this pill, each by its name here: notes (\"no note any "
    "more\"), dose, times (\"it no longer needs a time\": it becomes any time), min_gap, latest (\"it can "
    "be taken at any hour\"), dates (\"it goes on with no end\": the course's start and end both go), "
    "weekdays (\"every day again\", \"not only on weekdays any more\": it is taken daily). "
    "Never give a word such as none as a value in their place. Leave out when nothing is taken away.",
    LIST,
    choices=rules.CLEARABLE,
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
        purpose=SET_UP,
        say=("add Pill A at 8 am", "add Pill B twice a day, at least 6 hours apart",),
        apply=_recorded(add_save),
        verify=add_check,
        # No card when every pill named is already there just as asked: that is said in a line
        card_if=add_asks,
        run=add_already,
    ),
    Action(
        "pill_edit",
        "Change a pill the user already has: its name, dose, notes, times, how often, the gap, the latest "
        "time or its dates. Give only what changes. To take a setting away, name it in `clear` and give no "
        "value for it. Examples: \"move the evening pill to 9pm\" -> pill Evening pill, times [9:00 pm]. "
        "\"vitamin D is 2 tablets now\" -> dose 2 tablets. \"iron no longer needs a time\" -> pill iron, "
        "clear [times]. Only for a pill that is in the state. A pill that is only on the open card and not saved "
        "yet is changed with pill_add, as a follow-up (\"make 11:30 11am instead\" -> pill_add, the pill by the "
        "name on the card, with every time it then has).",
        _one_or_more("to change", _WHICH, Field("name", "A new name for it, if it is being renamed."), *_PLAN_FIELDS, _CLEAR, _OFF_THE_CARD),
        prepare=edit_card,
        purpose=SET_UP,
        say=("move Pill A to 9 pm", "Pill B is 2 tablets now",),
        apply=_recorded(edit_save),
        verify=edit_check,
        # No card when nothing would change: the same line as adding what is already there
        card_if=edit_asks,
        run=edit_already,
        # A pill that is only on the open "new" card is changed there
        unsaved=("pill_add", edit_on_card),
    ),
    Action(
        "pill_pause",
        "Pause a pill: it stops being asked for until resumed. \"pause iron\" -> pill iron. \"pause iron until "
        "the 20th\" -> until the 20th (the day it is taken again).",
        _one_or_more("to pause", _WHICH, Field("until", "The day it is taken again, " + AS_SAID + " Leave out for no end."), _OFF_THE_CARD),
        prepare=pause_card,
        purpose=SET_UP,
        say=("pause Pill A until the 20th",),
        apply=_recorded(pause_save),
        verify=pause_check,
    ),
    Action(
        "pill_resume",
        "Take a paused pill again (\"resume iron\", \"start iron again\").",
        _one_or_more("to resume", _WHICH, _OFF_THE_CARD),
        prepare=resume_card,
        purpose=SET_UP,
        say=("resume Pill A",),
        apply=_recorded(resume_save),
        verify=resume_check,
    ),
    Action(
        "pill_remove",
        "Remove a pill the user no longer takes, keeping its history (\"remove iron\", \"I've stopped taking "
        "iron\"). This is the usual one.",
        _one_or_more("to remove", _WHICH, _OFF_THE_CARD),
        prepare=remove_card,
        purpose=SET_UP,
        say=("remove Pill A",),
        apply=remove_save,
        verify=remove_check,
    ),
    Action(
        "pill_delete",
        "Delete a pill TOGETHER WITH its history. Only when the user says so in as many words (\"delete iron "
        "and its history\", \"delete it completely\"); otherwise use pill_remove.",
        _one_or_more("to delete", _WHICH, _OFF_THE_CARD),
        prepare=delete_card,
        purpose=SET_UP,
        say=("delete Pill A and its history",),
        apply=delete_save,
        verify=delete_check,
    ),
    Action(
        "pill_log",
        "The user says they took, skipped or did not take a pill today (or, said in so many words, yesterday). Examples: \"took my zinc\" -> pill "
        "zinc, did taken. \"I've taken my zinc today\" -> pill zinc, did taken. \"had pill A at 9\" -> pill "
        "pill A, did taken, at 9:00. \"took iron and vitamin D\" -> one item each. \"skip magnesium today\" -> "
        "did skipped. \"I didn't take zinc\", \"I haven't actually taken zinc\" -> did not_taken (it is marked "
        "as still to take). \"undo that\" straight after a log -> pill @that, did not_taken. "
        "\"I took it at 9am\", \"I had it at 9pm\", \"it was 9pm actually\" -> pill @that, did taken, at the "
        "time said: give it like any other; the code works out that it corrects the dose just logged. \"I took dose 1 of "
        "pill A at 9am\" -> pill pill A, did taken, dose 1, at 9:00 am. \"dose 2 at 12:15pm\" -> pill @that, did taken, "
        "dose 2, at 12:15 pm. \"that was dose 1\", \"no, that was my first dose\", \"it was dose 1 not dose 2\" (about a dose "
        "ALREADY logged: they say which of the day's doses it really was) -> pill @that, did taken, dose 1, correction true, and no time: "
        "the code moves that log, nothing new is logged. Never for changing when a pill is taken from now on: that is pill_edit.",
        (
            Field(
                "doses", "Each pill that was taken, skipped or not taken, one item each, in the order said.", ITEMS, required=True,
                item_fields=(
                    _WHICH,
                    Field("did", "What happened to today's dose.", choices=(checklist.TAKEN, checklist.SKIP, checklist.NOT_TAKEN), required=True),
                    Field("at", "For taken only: the time it was taken, if the user gave one. Leave out for just now.", TIME),
                    Field(
                        "day",
                        "Only when the user SAYS the dose was the day before: \"last night\", \"yesterday evening\" -> last_night; "
                        "\"yesterday\", \"yesterday morning\" -> yesterday (\"took zinc last night at 11\" -> pill zinc, did taken, "
                        "at 11:00, day last_night). Leave out otherwise: never work the day out from the time.",
                        choices=("yesterday", "last_night"),
                    ),
                    Field(
                        "dose",
                        "Only when the user says WHICH of the day's doses by its number (\"dose 1\", \"my second dose\", "
                        "\"the 3rd one\"): that number. Leave out otherwise: the code knows which dose is next.",
                        INTEGER,
                    ),
                    Field(
                        "correction",
                        "true ONLY when the user says a dose they ALREADY logged was a different one of the day's doses (\"that was dose 1\", "
                        "\"no, that was my first dose\"): `dose` is then the number it really was. Leave out when they report taking a dose.",
                        BOOLEAN,
                    ),
                ),
            ),
        ),
        run=log_answer,
        purpose=EACH_DAY,
        say=("took Pill A", "had Pill A at 9 am", "skip Pill B today", "I didn't take Pill A",),
        # Done at once, unless a dose would be ticked off after its pill's latest time, or one named
        # by its number would be out of order: that is asked first
        card_if=log_asks,
        prepare=log_card,
        apply=log_saved,
        verify=log_check,
    ),
    Action(
        "pill_today",
        "The user asks what is left to take today (\"what pills are left?\", \"what pills do I have left today?\", "
        "\"what's left to take?\", \"have I taken everything?\"). Not when or whether a dose was taken: that is pill_taken.",
        needs_card=False,
        run=show_today,
        purpose=SEE,
        say=("what's left to take today?",),
    ),
    Action(
        "pill_taken",
        "The user asks when they took doses, or whether they took one, today or on a day gone by (\"when did I take my "
        "pills today?\", \"what time did I take dose 2?\", \"did I take my morning one?\", \"when did I last take Pill A?\", "
        "\"what did I take on Tuesday?\"). Not what is left: that is pill_today. Not how yesterday or the week went overall: that is pill_history.",
        (
            Field("day", "The day asked about, exactly as the user said it (\"today\", \"yesterday\", \"Tuesday\"). Never work out a date. Leave out for today."),
            Field("pill", "The pill's name, only when the user names one (\"Pill A\"). Leave out for all of them."),
            Field("dose", "Only when the user says which of the day's doses by its number (\"dose 2\", \"my second one\"): that number.", INTEGER),
            Field("part", "Only when the user names a part of the day for the dose (\"my morning one\").", choices=tuple(taken.PARTS)),
            Field("last", "true when the user asks when they LAST took a pill (\"when did I last take Pill A?\").", BOOLEAN),
            Field("also_left", "true when the same question also asks what is still left to take today.", BOOLEAN),
        ),
        needs_card=False,
        run=taken.show,
        purpose=SEE,
        say=("when did I take my pills today?", "did I take dose 2?"),
    ),
    Action(
        "pill_history",
        "The user asks what they took on a day that is over, or how the week went (\"what did I take yesterday?\", "
        "\"did I take everything yesterday?\" -> period yesterday; \"show my week\", \"how did I do this week?\", "
        "\"my pills this week\" -> period week). Not for today: that is pill_today. Not another day by name (\"on Tuesday\"): that is pill_taken.",
        (Field("period", "Which stretch of time: yesterday, or the week.", choices=(history.YESTERDAY, history.WEEK), required=True),),
        needs_card=False,
        run=history.show,
        purpose=SEE,
        say=("what did I take yesterday?", "show my week"),
    ),
    Action(
        "pill_list",
        "The user asks what pills they have or when they take them (\"show all my pills\", \"what do I take?\").",
        needs_card=False,
        run=show_list,
        purpose=SEE,
        say=("my pills",),
    ),
)
