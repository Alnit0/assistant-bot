from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core import database
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
STRING, INTEGER, LIST, BOOLEAN = "string", "integer", "list", "boolean"
TYPES = (STRING, INTEGER, LIST, BOOLEAN)

GUESSED = "guessed"  # the field of every action that lists what Claude guessed
NONE = "none"  # the action that says "nothing here fits"
NOT_THIS = "not_this"  # in a follow-up: "this isn't about the open card"
RESERVED = (NONE, NOT_THIS)

MIN_EXAMPLES, MAX_EXAMPLES = 2, 3
GUESS_MARK = "❓"
WARNING_MARK = "⚠️"


@dataclass(frozen=True)
class Field:
    """One thing Claude fills in for an action."""

    name: str  # snake_case
    description: str  # what to put here, with an example
    type: str = STRING
    choices: tuple[str, ...] = ()  # the only values allowed (a STRING, or each item of a LIST)
    required: bool = False


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


@dataclass
class Request:
    """Who is asking and where, for an action's code. Not a discord object:
    the same for a message and for a press of Save."""

    user: User
    channel_id: int | None
    text: str = ""  # what the user said (empty when Save is pressed)

    db = database


Prepare = Callable[[Request, dict, frozenset], Awaitable[Proposal]]
Apply = Callable[[Request, dict], Awaitable[str]]
Run = Callable[[Request, dict, frozenset], Awaitable[str]]


@dataclass(frozen=True)
class Action:
    name: str  # unique across every task: "pill_add"
    description: str  # for Claude: when this is the one, with an example
    fields: tuple[Field, ...] = ()
    needs_card: bool = True
    prepare: Prepare | None = None  # needs_card: the data as a Proposal
    apply: Apply | None = None  # needs_card: Save was pressed; returns what to say
    run: Run | None = None  # direct: do it; returns what to say

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
    live_state: Callable[[Request], Awaitable[str]] | None = None

    @property
    def title(self) -> str:
        return self.name.capitalize()

    def action(self, name: str) -> Action | None:
        return next((action for action in self.actions if action.name == name), None)


def flag(text: str, guessed: bool) -> str:
    """Text with ❓ after it if it was a guess, for a card or a reply."""
    return f"{text} {GUESS_MARK}" if guessed else text


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
            if action.needs_card and (action.prepare is None or action.apply is None):
                found.append(f"{where} needs a card, so it needs both `prepare` (the card) and `apply` (Save)")
            if not action.needs_card and action.run is None:
                found.append(f"{where} acts straight away, so it needs `run` (which writes the reply)")
            field_names = [entry_field.name for entry_field in action.fields]
            if len(set(field_names)) != len(field_names):
                found.append(f"{where} has two fields with the same name")
            for entry_field in action.fields:
                if entry_field.type not in TYPES:
                    found.append(f"{where}: field {entry_field.name} has an unknown type {entry_field.type!r}")
                if entry_field.name == GUESSED:
                    found.append(f"{where}: `{GUESSED}` is added to every action; a field can't be called that")
                if entry_field.choices and entry_field.type not in (STRING, LIST):
                    found.append(f"{where}: field {entry_field.name} has choices, which only text can have")
                if not entry_field.description.strip():
                    found.append(f"{where}: field {entry_field.name} has no description for Claude")
    return found


# ---------------------------------------------------------------------------
# Schemas: what Claude is told an action takes
# ---------------------------------------------------------------------------
def _property(entry_field: Field) -> dict:
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
    """The strict JSON schema of an action: its fields, and `guessed`, the
    names of the fields Claude filled in without being told."""
    properties = {entry_field.name: _property(entry_field) for entry_field in action.fields}
    properties[GUESSED] = {
        "type": "array",
        "items": {"type": "string", "enum": [entry_field.name for entry_field in action.fields]} if action.fields else {"type": "string"},
        "description": (
            "The names of the fields above that you guessed or assumed rather than read from the user's words "
            "(a time that could be morning or evening, a kind of schedule that wasn't stated). Empty if none."
        ),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [entry_field.name for entry_field in action.fields if entry_field.required] + [GUESSED],
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
        "The user's message is not about the open card at all: it is a new request, or about something else."
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


_PYTHON_TYPES = {STRING: str, INTEGER: int, BOOLEAN: bool}


def validate(action: Action, raw) -> tuple[dict, frozenset]:
    """(the data, the names of the fields that were guessed), or Invalid.

    Strict: every required field present, nothing that isn't a field, every
    value of its type and among its choices. Text is trimmed; an optional
    field left empty is left out, so code can tell "not said" from "said".
    """
    if not isinstance(raw, dict):
        raise Invalid("the input is not an object")
    known = {entry_field.name: entry_field for entry_field in action.fields}
    unknown = sorted(set(raw) - set(known) - {GUESSED})
    if unknown:
        raise Invalid(f"not fields of {action.name}: {', '.join(unknown)}")

    data: dict = {}
    for name, entry_field in known.items():
        if name not in raw or raw[name] is None:
            if entry_field.required:
                raise Invalid(f"`{name}` is missing")
            continue
        value = raw[name]
        if entry_field.type == LIST:
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
            expected = _PYTHON_TYPES[entry_field.type]
            # bool is an int in Python: an INTEGER must not be True
            if not isinstance(value, expected) or (entry_field.type == INTEGER and isinstance(value, bool)):
                raise Invalid(f"`{name}` must be {entry_field.type}")
            if entry_field.type == STRING:
                value = value.strip()
                if not value:
                    if entry_field.required:
                        raise Invalid(f"`{name}` is empty")
                    continue
                if entry_field.choices and value not in entry_field.choices:
                    raise Invalid(f"`{name}` is {value!r}, which is not one of {', '.join(entry_field.choices)}")
        data[name] = value

    guessed = raw.get(GUESSED, [])
    if not isinstance(guessed, list) or not all(isinstance(item, str) for item in guessed):
        raise Invalid(f"`{GUESSED}` must be a list of field names")
    # A guess about a field that isn't there says nothing
    return data, frozenset(name for name in guessed if name in data)
