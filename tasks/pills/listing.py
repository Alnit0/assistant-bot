from datetime import date

from core import design
from core.cards import Card
from tasks.pills import rules
from tasks.pills.rules import ACTIVE, ENDED, PAUSED, UPCOMING, Pill

# ---------------------------------------------------------------------------
# "My pills": every pill I have, as a card. Its words are rules.list_text, as
# they always were; this is the same list in the one style of docs/DESIGN.md
# (drawn with CARDS_V2 on): a box a pill in use, then Paused and Ended as a
# box of lines each. Nothing in a list is waiting to be done, so every box is
# the quiet colour; what is due today is the checklist's to show. No buttons:
# every change is by words, on a card.
# ---------------------------------------------------------------------------
FOLD_AFTER = 12  # more pills in use than this share one box of lines: a message takes 40 components


def layout(pills: list[Pill], today: date) -> tuple:
    groups: dict[str, list[str]] = {state: [] for state in (ACTIVE, UPCOMING, PAUSED, ENDED)}
    for pill in rules._by_name(pills):
        state = rules.status_on(pill, today)
        if state in groups:
            groups[state].append(rules.describe_pill(pill, today))
    in_use = [*groups[ACTIVE], *groups[UPCOMING]]
    if not in_use:
        nothing = rules.EMPTY_LIST if not groups[PAUSED] and not groups[ENDED] else "Nothing is being taken at the moment."
        boxes = [design.item(design.QUIET, nothing)]
    elif len(in_use) > FOLD_AFTER:
        boxes = [design.item(design.QUIET, *in_use)]
    else:
        boxes = [design.item(design.QUIET, line) for line in in_use]
    later = []
    if groups[PAUSED]:
        later.append(design.item(design.QUIET, "⏸️ **Paused**", *(design.small(line.removeprefix("⏸️ ")) for line in groups[PAUSED])))
    if groups[ENDED]:
        later.append(design.item(design.QUIET, "🏁 **Ended**", *(design.small(line.removeprefix("🏁 ")) for line in groups[ENDED])))
    counts = [f"{len(in_use)} in use"] if in_use else []
    counts += [f"{len(groups[PAUSED])} paused"] if groups[PAUSED] else []
    return design.standing("💊 Pills", " · ".join(counts), boxes, later)


def card(pills: list[Pill], today: date) -> Card:
    """The list as a card: the words it has always had, and the same list drawn."""
    return Card(rules.list_text(pills, today), (), layout(pills, today))
