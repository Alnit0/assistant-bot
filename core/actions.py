import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core import database, trace
from core.users import User

# ---------------------------------------------------------------------------
# Actions: what a task can be asked to do in plain words, as the routing
# standard has it.
#
# Claude understands; Python does the work and the talking. A task declares:
#   - an Entry for the router's catalogue: its name, icon, what it is "only
#     for", and two or three things one might say to it. The router never
#     sees more than that
#   - its Actions: for each, the fields Claude is to fill in (a strict schema
#     is built from them), and what Python does with them
#
# An action is one of two kinds:
#   - needs_card (anything that changes setup): `prepare` turns the data into
#     a Proposal, the confirm card shows it, and only Save runs `apply`
#   - direct (logging, questions, quick actions): `run` does it and returns
#     what to say
# Either way every word the user reads comes from the task's own code. Claude
# never writes a confirmation.
#
# This file is the contract and the checking of what Claude returns. Pure: no
# Discord, no API calls. core/routing.py and core/extraction.py make the
# calls, core/confirm.py shows the cards, core/conversation.py ties them up.
# ---------------------------------------------------------------------------
STRING, INTEGER, LIST, BOOLEAN, ITEMS = "string", "integer", "list", "boolean", "items"
TYPES = (STRING, INTEGER, LIST, BOOLEAN, ITEMS)

GUESSED = "guessed"  # the field of every action that lists what Claude guessed
# The field of every action that lists what was asked for and could not be put
# into it. Nothing is ever dropped without a word: the card or reply says so
NOT_INCLUDED = "not_included"
ADDED = (GUESSED, NOT_INCLUDED)  # in every action's schema; a task's field can't use these names
NONE = "none"  # the action that says "nothing here fits"
NOT_THIS = "not_this"  # in a follow-up: "this isn't about the open card"
RESERVED = (NONE, NOT_THIS)

MIN_EXAMPLES, MAX_EXAMPLES = 2, 3
GUESS_MARK = "❓"
WARNING_MARK = "⚠️"
STATE_LINES = 20  # the most of a task's state that goes to extraction with one message


@dataclass(frozen=True)
class State:
    """What a task has now, for extraction to read with a message: a heading
    and a line for each thing. A task returns this from `live_state`, not one
    long string, so that only what the message could be about is sent."""

    heading: str  # "On the shopping list now"
    lines: tuple[str, ...] = ()
    empty: str = "nothing"


def _stems(text: str) -> set[str]:
    words = re.findall(r"[^\W_]+", str(text).lower())
    return {word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words if len(word) > 2}


def shown_state(state: "State | str", said: str, limit: int = STATE_LINES) -> tuple[str, int, int]:
    """A task's state as it is sent to extraction: (the text, lines sent, lines
    there are). A long state is cut to `limit` lines: first the ones that
    share a word with what was said (what the message could refer to), then
    the others in the task's own order, and it says how many were left out."""
    if isinstance(state, str):
        every = [line for line in state.splitlines() if line.strip()]
        heading, every, empty = (every[0].rstrip(":"), every[1:], "") if len(every) > limit else ("", every, "")
    else:
        heading, every, empty = state.heading, list(state.lines), state.empty
    total = len(every)
    if total <= limit:
        sent = every
    else:
        heard = _stems(said)
        about = [line for line in every if _stems(line) & heard]
        chosen = set(map(id, about[:limit]))
        for line in every:
            if len(chosen) >= limit:
                break
            chosen.add(id(line))
        sent = [line for line in every if id(line) in chosen]  # in the task's order
    if not sent:
        return (f"{heading}: {empty}" if heading and empty else heading), 0, total
    left = total - len(sent)
    more = f"\n(and {left} more not shown: what the message names is among the lines above if it is there at all)" if left else ""
    body = "\n".join(f"- {line}" for line in sent) if heading else "\n".join(sent)
    return (f"{heading}:\n{body}{more}" if heading else f"{body}{more}"), len(sent), total


@dataclass(frozen=True)
class Field:
    """One thing Claude fills in for an action."""

    name: str  # snake_case
    description: str  # what to put here, with an example
    type: str = STRING
    choices: tuple[str, ...] = ()  # the only values allowed (a STRING, or each item of a LIST)
    required: bool = False
    # For ITEMS: the fields of each item. One request can hold several things
    # ("add honey, jam and 5 eggs"), so anything that can be asked for in the
    # plural takes a list of items, never a single one
    item_fields: tuple["Field", ...] = ()


@dataclass(frozen=True)
class Proposal:
    """What a confirm card shows: every interpretation written out, guesses
    flagged, problems shown with the sensible fix already applied."""

    lines: tuple[str, ...]  # the card's body, one interpretation a line
    data: dict  # exactly what Save will apply (fixes included)
    warnings: tuple[str, ...] = ()  # shown with ⚠️
    kind: str = "new"  # the kind of change, for the first line: new, edit, pause, remove…
    destructive: bool = False  # can't be undone: a card of its own kind
    confirm_label: str = "Save"
    # What the task's own code guessed in `data` (a time taken as the morning),
    # named as Claude names a guess ("pills[0].times"). Kept with the card beside
    # Claude's guesses, so a follow-up knows the value was never said
    guessed: tuple[str, ...] = ()


@dataclass
class Request:
    """Who is asking and where, for an action's code. Not a discord object:
    the same for a message and for a press of Save."""

    user: User
    channel_id: int | None
    text: str = ""  # what the user said (empty when Save is pressed)
    # When the message corrects an open card of this same action: that card's
    # data, as it stood. `prepare` builds the new card from it and what the
    # message changes (see merge_items), so code, not Claude, carries the rest
    # of the card over and does any sums
    previous: dict | None = None
    # The message the user replied to, if they replied to one ("pause this")
    replied_to: int | None = None
    # The user's own message (None for a press of a button)
    message_id: int | None = None

    db = database


@dataclass(frozen=True)
class LiveReply:
    """What a direct action returns when its reply is a list shown on request:
    the message becomes the Live copy of that list, kept up to date in place
    when the data changes (core/livelists.py). `key` names the list."""

    key: str
    text: str


@dataclass(frozen=True)
class Shown:
    """What a direct action returns when it has put its own message in the
    channel (a timer's message with its buttons, a session card): nothing more
    is posted for it. `summary` is for the log; `also`, if there is any, is
    said as well (a guess to point out, something that could not be done)."""

    summary: str
    also: str = ""


Prepare = Callable[[Request, dict, frozenset], Awaitable[Proposal]]
Apply = Callable[[Request, dict], Awaitable[str]]
Run = Callable[[Request, dict, frozenset], Awaitable["str | LiveReply | Shown"]]
CardIf = Callable[[Request, dict], Awaitable[bool]]


@dataclass(frozen=True)
class Action:
    name: str  # unique across every task: "pill_add"
    description: str  # for Claude: when this is the one, with an example
    fields: tuple[Field, ...] = ()
    needs_card: bool = True
    prepare: Prepare | None = None  # needs_card: the data as a Proposal
    apply: Apply | None = None  # needs_card: Save was pressed; returns what to say
    run: Run | None = None  # direct: do it; returns what to say
    # For an action that only sometimes needs a card (cancelling one timer acts
    # at once, cancelling several asks first): `async (request, data) -> bool`.
    # Such an action has all three of `prepare`, `apply` and `run`
    card_if: CardIf | None = None

    def field(self, name: str) -> Field | None:
        return next((entry for entry in self.fields if entry.name == name), None)


@dataclass(frozen=True)
class Entry:
    """A task as the router knows it, with the actions extraction may pick from."""

    name: str  # lower case: "pills"
    icon: str  # "💊"
    only_for: str  # what it is for and what it is not, in a sentence or two
    examples: tuple[str, ...]  # two or three things one might say to it
    actions: tuple[Action, ...]
    # Said when nothing fits: how to ask ("Try saying the name and when you take it.")
    hint: str = ""
    # `async (request) -> str`: what extraction should know about this task's
    # state right now (names and ids). Goes in the user turn, never the cached part
    live_state: Callable[[Request], Awaitable["State | str"]] | None = None

    @property
    def title(self) -> str:
        return self.name.capitalize()

    def action(self, name: str) -> Action | None:
        return next((action for action in self.actions if action.name == name), None)


def flag(text: str, guessed: bool) -> str:
    """Text with ❓ after it if it was a guess, for a card or a reply.

    ❓ is for a genuine guess: a time that could be morning or evening, a
    field Claude wasn't sure of. A value simply left at its default (one of
    something, when no amount was said) is not a guess and is never flagged,
    so that ❓ still means something on a card with several lines."""
    return f"{text} {GUESS_MARK}" if guessed else text


# ---------------------------------------------------------------------------
# Changes to the items of a list: add, set, remove
#
# For any task that keeps a list of things with amounts. A request names the
# items it is about and, for each, what to do: add more of it (or add it
# new), set what it should be, or remove it. Claude says which; code does the
# sum and shows before -> after. The same three work on a saved list and on
# an open card that isn't saved yet.
# ---------------------------------------------------------------------------
ADD, SET, REMOVE = "add", "set", "remove"
CHANGE = "change"  # the name of the item field that says which


def change_field() -> Field:
    """The `change` field of an item, the same for every list-like task."""
    return Field(
        CHANGE,
        "What to do with this item. add: the user wants it added, or more of it (\"add 3 milk\", \"another "
        "loaf\", \"milk too\"): any amount is how many MORE. set: the user says what it should be (\"make the "
        "eggs 7\", \"make it 2\", \"change milk to 3\", \"I only need 2\"): the amount is the new total. "
        "remove: take it off altogether (\"remove the jam\", \"no jam\", \"drop the eggs\"). Never work a "
        "total out yourself: give what the user said and which of the three it is. Leave out for add.",
        choices=(ADD, SET, REMOVE),
    )


def merge_items(
    pending: list[dict],
    changes: list[dict],
    *,
    key: str = "item",
    amount: str | None = "quantity",
    same=None,
    exists=None,
    said: str | None = None,
) -> tuple[list[dict], list[str]]:
    """An open card's items with a message's changes applied: (the items as
    they now stand, the names it was asked to remove that aren't anywhere).

    `pending` is what the card holds, `changes` what the message is about,
    each item with its `change` (add if left out). `key` names an item and
    `amount` is the field that counts it (None if the task has no amounts).
    `same(a, b)` says whether two names are the same item; `exists(name)`
    whether one is in the saved list, so that removing something that is only
    on the card takes it off the card, and removing something saved becomes a
    removal to confirm.

    Code does the sums: adding 3 to a card that adds 2 adds 5; setting
    replaces whatever was pending. The name is kept as typed last.

    `said` is the message the changes came from. Claude is asked for the
    changes only; as a safety net, a line of the card that comes back beside
    other changes, without the message naming it, is taken as the card
    restated and not as more of it (see `_restated`).
    """
    same = same or (lambda one, other: str(one).strip().lower() == str(other).strip().lower())
    merged = [dict(item) for item in pending]
    missing: list[str] = []
    for change in changes:
        was = next((item for item in merged if same(item[key], change[key])), None)
        if _restated(change, was, changes, key, amount, same, said):
            trace.note(f"restatement check: {change[key]} came back with the card and the message doesn't name it: not added again")
            # As it was: left alone. With another amount: that is what it should be, never added on top
            if amount is not None and amount in change:
                was[amount] = change[amount]
            was.update({field: value for field, value in change.items() if field not in (amount, CHANGE, key)})
            continue
        name, what = change[key], change.get(CHANGE, ADD)
        at = next((index for index, item in enumerate(merged) if same(item[key], name)), None)
        was = merged[at] if at is not None else None
        if was is not None and what != REMOVE and len(changes) > 1:
            trace.note(f"restatement check: {name} is on the card and came back, taken as a real change ({what})")
        trace.note(f"merge: {name} {what}" + (f" {change[amount]}" if amount is not None and amount in change else "") + (" (on the card)" if was is not None else " (new to the card)"))
        if what == REMOVE:
            if at is not None:
                merged.pop(at)
            if exists is not None and exists(name):
                merged.append({key: name, CHANGE: REMOVE})
            elif was is None or was.get(CHANGE) == REMOVE:
                missing.append(name)
            continue
        now = {field: value for field, value in change.items() if field != CHANGE}
        if what == SET or was is None or was.get(CHANGE) == REMOVE:
            # Set replaces whatever was pending; a first mention, or one after a removal, stands as it is
            now[CHANGE] = what
        else:
            # More of something the card already changes: the amounts add up, and it stays what it was
            now = {**{field: value for field, value in was.items() if field != CHANGE}, **now}
            if amount is not None:
                now[amount] = was.get(amount, 1) + change.get(amount, 1)
            now[CHANGE] = was.get(CHANGE, ADD)
        if at is not None:
            merged[at] = now
        else:
            merged.append(now)
    return merged, missing


def _restated(change: dict, was: dict | None, changes: list[dict], key: str, amount: str | None, same, said: str | None) -> bool:
    """Whether a change is only a line of the open card sent back, not something
    the message asked for. The safety net for when Claude repeats the card
    ("and jam" coming back as butter and jam): without it the butter would be
    added a second time.

    It is, when the item is on the card, something else came back with it (a
    message about this item alone is a real change, pronoun or not: "two
    more"), the message doesn't name it, and it is an add, or a set to what
    the card already has. Works for a card of one line as for many."""
    if was is None or len(changes) < 2:
        return False
    kind = change.get(CHANGE, ADD)
    if kind == REMOVE or was.get(CHANGE) == REMOVE:
        return False
    if said is not None and _named(change[key], said, same):
        return False
    unchanged = amount is None or change.get(amount, was.get(amount, 1)) == was.get(amount, 1)
    return kind == ADD or unchanged


def _named(name: str, said: str, same) -> bool:
    """Whether a message names an item: every word of the name is in it,
    by the task's own rule for the same name ("egg" names "eggs")."""
    heard = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", said.lower())
    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", str(name).lower())
    return bool(words) and all(any(same(word, other) for other in heard) for word in words)


def path(name: str, index: int | None = None, sub: str = "") -> str:
    """How a guess is named: "times", "times[0]", "items[2].quantity"."""
    return name + (f"[{index}]" if index is not None else "") + (f".{sub}" if sub else "")


def is_guessed(guessed: frozenset, name: str, index: int | None = None, sub: str = "") -> bool:
    """Whether this value was a guess: named itself, or as part of what holds it
    ("items[2]" covers "items[2].quantity")."""
    wanted = path(name, index, sub)
    return wanted in guessed or (bool(sub) and path(name, index) in guessed) or (index is not None and name in guessed)


# ---------------------------------------------------------------------------
# The catalogue: every entry of every loaded task, set by the registry
# ---------------------------------------------------------------------------
_entries: dict[str, Entry] = {}


def set_catalogue(entries: list[Entry]) -> None:
    _entries.clear()
    _entries.update({entry.name: entry for entry in entries})


def catalogue() -> list[Entry]:
    return list(_entries.values())


def entry(name: str) -> Entry | None:
    return _entries.get(name)


def problems(entries: list[Entry]) -> list[str]:
    """What is wrong with a set of entries, in words: the contract every task
    must meet before the bot starts routing to it. Empty if nothing is."""
    found: list[str] = []
    names: dict[str, str] = {}
    seen_entries: set[str] = set()
    for entry in entries:
        who = entry.name or "(unnamed)"
        if not entry.name or entry.name != entry.name.lower() or " " in entry.name:
            found.append(f"{who}: an entry's name is one lower-case word")
        if entry.name in seen_entries:
            found.append(f"{who}: two entries share this name")
        seen_entries.add(entry.name)
        if not entry.icon.strip():
            found.append(f"{who}: needs an icon")
        if not entry.only_for.strip():
            found.append(f"{who}: needs an \"only for\" line, so the router can tell it from other tasks")
        if not MIN_EXAMPLES <= len(entry.examples) <= MAX_EXAMPLES:
            found.append(f"{who}: needs {MIN_EXAMPLES} to {MAX_EXAMPLES} example phrases, not {len(entry.examples)}")
        if not entry.actions:
            found.append(f"{who}: has no actions")
        for action in entry.actions:
            where = f"{who}: action {action.name or '(unnamed)'}"
            if not action.name or action.name in RESERVED:
                found.append(f"{where} needs a name of its own")
            elif action.name in names:
                found.append(f"{where} is also an action of {names[action.name]}")
            else:
                names[action.name] = who
            if not action.description.strip():
                found.append(f"{where} has no description for Claude")
            if action.card_if is not None:
                if action.prepare is None or action.apply is None or action.run is None:
                    found.append(f"{where} needs a card only sometimes (`card_if`), so it needs `prepare`, `apply` and `run`")
            elif action.needs_card and (action.prepare is None or action.apply is None):
                found.append(f"{where} needs a card, so it needs both `prepare` (the card) and `apply` (Save)")
            elif not action.needs_card and action.run is None:
                found.append(f"{where} acts straight away, so it needs `run` (which writes the reply)")
            field_names = [entry_field.name for entry_field in action.fields]
            if len(set(field_names)) != len(field_names):
                found.append(f"{where} has two fields with the same name")
            for entry_field in action.fields:
                if entry_field.type not in TYPES:
                    found.append(f"{where}: field {entry_field.name} has an unknown type {entry_field.type!r}")
                if entry_field.name in ADDED:
                    found.append(f"{where}: `{entry_field.name}` is added to every action; a field can't be called that")
                if entry_field.choices and entry_field.type not in (STRING, LIST):
                    found.append(f"{where}: field {entry_field.name} has choices, which only text can have")
                if not entry_field.description.strip():
                    found.append(f"{where}: field {entry_field.name} has no description for Claude")
                if entry_field.type == ITEMS:
                    if not entry_field.item_fields:
                        found.append(f"{where}: field {entry_field.name} is a list of items, so it needs `item_fields`")
                    for inner in entry_field.item_fields:
                        if inner.type not in (STRING, INTEGER, BOOLEAN):
                            found.append(f"{where}: an item's field {inner.name} must be text, a number or yes/no")
                        if not inner.description.strip():
                            found.append(f"{where}: an item's field {inner.name} has no description for Claude")
                elif entry_field.item_fields:
                    found.append(f"{where}: field {entry_field.name} has `item_fields` but is not a list of items")
    return found


# ---------------------------------------------------------------------------
# Schemas: what Claude is told an action takes
# ---------------------------------------------------------------------------
def _property(entry_field: Field) -> dict:
    if entry_field.type == ITEMS:
        return {
            "type": "array",
            "description": entry_field.description,
            "items": {
                "type": "object",
                "properties": {inner.name: _property(inner) for inner in entry_field.item_fields},
                "required": [inner.name for inner in entry_field.item_fields if inner.required],
                "additionalProperties": False,
            },
        }
    if entry_field.type == LIST:
        items: dict = {"type": "string"}
        if entry_field.choices:
            items["enum"] = list(entry_field.choices)
        return {"type": "array", "items": items, "description": entry_field.description}
    prop: dict = {"type": entry_field.type, "description": entry_field.description}
    if entry_field.choices:
        prop["enum"] = list(entry_field.choices)
    return prop


def schema(action: Action) -> dict:
    """The strict JSON schema of an action: its fields, `guessed` (what Claude
    filled in without being told) and `not_included` (what was asked for and
    could not be put into the action)."""
    properties = {entry_field.name: _property(entry_field) for entry_field in action.fields}
    properties[GUESSED] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "What you genuinely guessed rather than read from the user's words: a time that could be morning or "
            "evening, a vague amount, a kind of schedule that wasn't stated. Name each by its field, with its "
            "place in a list where it has one: `times[0]`, `items[2].quantity`. A field you left out because "
            "the user didn't say (so its default applies) is not a guess: don't list it. Empty if none."
        ),
    }
    properties[NOT_INCLUDED] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Every part of what the user asked for that you could NOT put into this action, each copied "
            "word for word. The user is told, so nothing is dropped unseen. Empty if all of it is covered."
        ),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [entry_field.name for entry_field in action.fields if entry_field.required] + [GUESSED, NOT_INCLUDED],
        "additionalProperties": False,
    }


def tool(action: Action, strict: bool = False) -> dict:
    """An action as the API takes it."""
    definition = {"name": action.name, "description": action.description, "input_schema": schema(action)}
    if strict:
        definition["strict"] = True
    return definition


NONE_TOOL = {
    "name": NONE,
    "description": (
        "Nothing here fits what the user said, or it isn't clear enough to act on even with a best guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Why, in a few words. For the log, not the user."}},
        "required": ["reason"],
        "additionalProperties": False,
    },
}
NOT_THIS_TOOL = {
    "name": NOT_THIS,
    "description": (
        "The user's message is not about the open card or this task's list at all: it is a new request for "
        "something else."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Why, in a few words. For the log, not the user."}},
        "required": ["reason"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Checking what Claude returned. Always done, strict schema or not
# ---------------------------------------------------------------------------
class Invalid(ValueError):
    """What Claude returned doesn't fit the action's schema. The message says how."""


@dataclass(frozen=True)
class Checked:
    """What Claude returned, once it has been checked."""

    data: dict
    guessed: frozenset  # paths: "times", "times[0]", "items[2].quantity"
    not_included: tuple[str, ...] = ()  # what was asked for and is not in `data`, to be told to the user

    def __iter__(self):
        # (data, guessed), for code that only wants those two
        return iter((self.data, self.guessed))


_PYTHON_TYPES = {STRING: str, INTEGER: int, BOOLEAN: bool}
_GUESS_PATH = re.compile(r"(\w+)(?:\[(\d+)\])?(?:\.(\w+))?")


def _scalar(entry_field: Field, value, where: str):
    """One text, number or yes/no value, checked. Returns it, or None if it is
    an optional text left empty."""
    expected = _PYTHON_TYPES[entry_field.type]
    # bool is an int in Python: an INTEGER must not be True
    if not isinstance(value, expected) or (entry_field.type == INTEGER and isinstance(value, bool)):
        raise Invalid(f"`{where}` must be {entry_field.type}")
    if entry_field.type != STRING:
        return value
    value = value.strip()
    if not value:
        if entry_field.required:
            raise Invalid(f"`{where}` is empty")
        return None
    if entry_field.choices and value not in entry_field.choices:
        raise Invalid(f"`{where}` is {value!r}, which is not one of {', '.join(entry_field.choices)}")
    return value


def _item(entry_field: Field, raw, where: str) -> dict:
    """One item of a list of items, checked like a small action of its own."""
    if not isinstance(raw, dict):
        raise Invalid(f"`{where}` is not an object")
    known = {inner.name: inner for inner in entry_field.item_fields}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise Invalid(f"`{where}` has what is not a field of an item: {', '.join(unknown)}")
    item: dict = {}
    for name, inner in known.items():
        if name not in raw or raw[name] is None:
            if inner.required:
                raise Invalid(f"`{where}.{name}` is missing")
            continue
        value = _scalar(inner, raw[name], f"{where}.{name}")
        if value is not None:
            item[name] = value
    return item


def validate(action: Action, raw) -> Checked:
    """What Claude returned, checked: the data, what was guessed, and what was
    left out. Raises Invalid if it doesn't fit the action at all.

    Strict: every required field present, nothing that isn't a field, every
    value of its type and among its choices. Text is trimmed; an optional
    field left empty is left out, so code can tell "not said" from "said".

    In a list of items, one item that doesn't fit is not allowed to sink the
    rest, and is not dropped unseen either: it is left out of the data and
    named in `not_included`, which the user is shown.
    """
    if not isinstance(raw, dict):
        raise Invalid("the input is not an object")
    known = {entry_field.name: entry_field for entry_field in action.fields}
    unknown = sorted(set(raw) - set(known) - set(ADDED))
    if unknown:
        raise Invalid(f"not fields of {action.name}: {', '.join(unknown)}")

    data: dict = {}
    left_out: list[str] = []
    shifted: set[str] = set()
    for name, entry_field in known.items():
        if name not in raw or raw[name] is None:
            if entry_field.required:
                raise Invalid(f"`{name}` is missing")
            continue
        value = raw[name]
        if entry_field.type == ITEMS:
            if not isinstance(value, list):
                raise Invalid(f"`{name}` must be a list of items")
            items = []
            dropped: set[int] = set()
            for index, each in enumerate(value):
                try:
                    items.append(_item(entry_field, each, f"{name}[{index}]"))
                except Invalid:
                    # In the user's terms: what the item was, not what was wrong with its form
                    dropped.add(index)
                    left_out.append(", ".join(str(part) for part in each.values()) if isinstance(each, dict) and each else str(each))
            if not items:
                if entry_field.required:
                    raise Invalid(f"`{name}` has no item that can be used" if value else f"`{name}` is empty")
                continue
            if dropped:
                # The places Claude named no longer line up: a guess about an item is forgotten
                # rather than pinned on the wrong one
                shifted.add(name)
            value = items
        elif entry_field.type == LIST:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise Invalid(f"`{name}` must be a list of strings")
            value = [item.strip() for item in value if item.strip()]
            wrong = [item for item in value if entry_field.choices and item not in entry_field.choices]
            if wrong:
                raise Invalid(f"`{name}` has {wrong[0]!r}, which is not one of {', '.join(entry_field.choices)}")
            if not value:
                if entry_field.required:
                    raise Invalid(f"`{name}` is empty")
                continue
        else:
            value = _scalar(entry_field, value, name)
            if value is None:
                continue
        data[name] = value

    guessed = raw.get(GUESSED, [])
    if not isinstance(guessed, list) or not all(isinstance(item, str) for item in guessed):
        raise Invalid(f"`{GUESSED}` must be a list of field names")
    not_included = raw.get(NOT_INCLUDED, [])
    if not isinstance(not_included, list) or not all(isinstance(item, str) for item in not_included):
        raise Invalid(f"`{NOT_INCLUDED}` must be a list of the parts left out")
    left_out = [part.strip() for part in not_included if part.strip()] + left_out
    # A guess named by an item's field alone ("duration" for "timers[0].duration"),
    # seen from Claude on a list of one: it is put where it belongs, on each item that
    # has that field, so the guess is still flagged rather than forgotten
    lists = [entry_field for entry_field in action.fields if entry_field.type == ITEMS and entry_field.name in data]
    placed: list[str] = []
    for name in guessed:
        if name in known or "[" in name or "." in name or len(lists) != 1 or lists[0].name in shifted:
            placed.append(name)
        elif any(inner.name == name for inner in lists[0].item_fields):
            placed += [path(lists[0].name, index, name) for index, item in enumerate(data[lists[0].name]) if name in item]
        else:
            placed.append(name)
    guessed = placed
    kept = frozenset(
        name for name in guessed if _guess_is_about(name, data) and not ("[" in name and name.split("[")[0] in shifted)
    )
    return Checked(data, kept, tuple(left_out))


def _guess_is_about(guess: str, data: dict) -> bool:
    """Whether a guess names something that is in the data: a guess about a
    field that isn't there says nothing."""
    match = _GUESS_PATH.fullmatch(guess.strip())
    if not match or match[1] not in data:
        return False
    value = data[match[1]]
    if match[2] is None:
        return match[3] is None
    if not isinstance(value, list) or int(match[2]) >= len(value):
        return False
    return match[3] is None or (isinstance(value[int(match[2])], dict) and match[3] in value[int(match[2])])
