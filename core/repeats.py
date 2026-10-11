import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Adding something that is already there.
#
# Every task that takes plain words declares two things (core/actions.py,
# `Entry`):
#
#   identity    the fields that make two items the same thing: ("name",) for a
#               pill. Empty when nothing a task holds is ever "the same" as
#               something asked for (each timer is its own, each bug report).
#   on_repeat   what asking to add one that is already there means:
#       update          it is a change to the one there (pills)
#       add_to_amount   more of it: the amounts are added (a shopping list)
#       allow_another   a second one, side by side (timers, bug reports)
#       ask             a question on the card. Not available until cards
#                       can ask (the gap list, G1): the contract refuses it
#
# This file does the matching, decides what a request for something that is
# there comes to, and writes the words every task says about it, so "already
# there" reads the same whichever task it is. Whether a thing exists is for
# code to find out here, never a reason for Claude to decline.
#
# Pure: no Discord, no database. A task hands over what it holds.
# ---------------------------------------------------------------------------
UPDATE, ADD_TO_AMOUNT, ALLOW_ANOTHER, ASK = "update", "add_to_amount", "allow_another", "ask"
ON_REPEAT = (UPDATE, ADD_TO_AMOUNT, ALLOW_ANOTHER, ASK)
# Not until a card can ask a question (docs/BACKLOG.md, G1)
NOT_BUILT = (ASK,)

# What a request to add comes to
NEW, SAME, CHANGE, MORE, ANOTHER, QUESTION = "new", "same", "change", "more", "another", "question"


def normal(value) -> str:
    """A value as it is compared: text without case or stray spaces. Only for
    comparing: what is shown and kept is always the name as it was typed."""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def key(identity: Iterable[str], values: dict) -> tuple[str, ...] | None:
    """What makes an item itself, from its fields. None when a task declares
    no identity, or the item lacks one of the fields: it matches nothing."""
    fields = tuple(identity)
    if not fields or any(values.get(name) in (None, "") for name in fields):
        return None
    return tuple(normal(values[name]) for name in fields)


def find(identity: Iterable[str], wanted: dict, existing: Iterable, values: Callable = lambda thing: thing, same: Callable | None = None):
    """The one of `existing` that is the same thing as `wanted`, or None.
    `values(thing)` gives a thing's fields as a dict. `same(one, other)`
    compares two values in a task's own way (singular and plural of a name,
    say) in place of `normal`."""
    fields = tuple(identity)
    mine = key(fields, wanted)
    if mine is None:
        return None
    for thing in existing:
        theirs = values(thing)
        if same is not None:
            if all(theirs.get(name) not in (None, "") and same(str(wanted[name]), str(theirs[name])) for name in fields):
                return thing
        elif key(fields, theirs) == mine:
            return thing
    return None


@dataclass(frozen=True)
class Repeat:
    """What asking to add something comes to. `there` is the one already held."""

    kind: str  # NEW, SAME, CHANGE, MORE, ANOTHER or QUESTION
    there: object = None


def decide(on_repeat: str, there, changes: bool = True) -> Repeat:
    """What a request to add comes to, given the one that is already there
    (None if there is none) and whether what was said would change it."""
    if there is None or on_repeat == ALLOW_ANOTHER:
        return Repeat(ANOTHER if there is not None else NEW, there)
    if on_repeat == ADD_TO_AMOUNT:
        return Repeat(MORE, there)
    if on_repeat == ASK:
        return Repeat(QUESTION, there)
    return Repeat(CHANGE if changes else SAME, there)


def problems(who: str, identity: tuple[str, ...], on_repeat: str, fields: set[str]) -> list[str]:
    """What is wrong with a task's declaration, in words. `fields` are the
    names of every field its actions take, an item's fields included."""
    found = []
    if on_repeat not in ON_REPEAT:
        found.append(f"{who}: needs `on_repeat`, what adding something that is already there means: one of {', '.join(ON_REPEAT)}")
    elif on_repeat in NOT_BUILT:
        found.append(f"{who}: `on_repeat` {on_repeat} needs questions on the card, which are not built yet (the gap list, G1)")
    elif on_repeat != ALLOW_ANOTHER and not identity:
        found.append(f"{who}: `on_repeat` {on_repeat} needs an `identity`: the fields that make two items the same")
    for name in identity:
        if name not in fields:
            found.append(f"{who}: `identity` names `{name}`, which is no field of any of its actions")
    return found


# ---------------------------------------------------------------------------
# The words, the same for every task
# ---------------------------------------------------------------------------
def already(name: str, where: str) -> str:
    """Said when adding what is there would change nothing: "**Iron** is already
    in your pills with these settings". `where` is the task's or list's name."""
    return f"**{name}** is already in your {where} with these settings"


def there_line(name: str, where: str) -> str:
    """The first line for something on an add card that is already there, above
    the changes to it: "**Iron** · already in your pills"."""
    return f"**{name}** · already in your {where}"


def change_line(field: str, before, after) -> str:
    """One format for a change, on whichever card it is: field · old → new."""
    return f"{field} · {before} → {after}"
