from datetime import date

from core import design
from core.attention import Item
from core.summaries import Section

# ---------------------------------------------------------------------------
# The briefing's words and how it is drawn. Pure. It holds no section's own
# words: each is its task's (core/summaries.py), and the briefing only puts
# them in order under one heading.
#
# The order is not the briefing's either: it is the one ranking's
# (core/attention.py), the same the status line shows the top of. What is
# wrong and needs me (level 1) is a box on top; then what quiet hours held
# back overnight, if anything; then a section a task, the task whose item
# stands highest first, and those with nothing ranked after, as they were.
# ---------------------------------------------------------------------------
TASK = "briefing"
ICON = "☀️"
HEADING = f"{ICON} Today"
NOTHING = f"{ICON} Nothing on today."
UP_TO_DATE = f"{ICON} The briefing above is up to date."
NEEDS = "⚠️ **Needs a look**"
HELD = "🌙 **Held back overnight**"
FOOT = "always up to date · tick things off on their own message · say “my schedule” to change when this is posted"


def date_line(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B}"


def notice(at: str) -> str:
    """The one line a briefing that notifies is first posted as: what the phone
    shows. It names nothing of mine."""
    return f"{ICON} Morning briefing · {at}"


def ordered(sections: list[Section], order: list[str]) -> list[Section]:
    """The sections in the ranking's order. `order` is the tasks of the ranked
    items, the highest first: a task comes where its best item stands, and one
    with nothing ranked comes after those, in the order it was given."""
    place: dict[str, int] = {}
    for at, name in enumerate(order):
        place.setdefault(name, at)
    return sorted(sections, key=lambda section: place.get(section.task, len(order)))


def problem(item: Item) -> str:
    """A level 1 item as the briefing says it: its icon, its bug if one was
    filed, and what is wrong in words."""
    return f"{item.icon or '⚠️'} {f'{item.bug} · ' if item.bug else ''}{item.what}"


def held(line: str, times: int = 1) -> str:
    """One alert quiet hours held back: the neutral line it was posted as, and
    how often it was asked for if more than once."""
    return line if times <= 1 else f"{line} · {times} times"


def held_note(hours: str) -> str:
    return f"quiet hours ({hours}): posted without a sound"


def _name(section: Section) -> str:
    glance = section.summary.glance if section.summary is not None else ""
    return f"{section.icon} **{section.title}**" + (f" · {glance}" if glance else "")


def _lines(section: Section) -> list[str]:
    """A section's lines under its name: what it says, then its hint and the
    line about the day before, both small."""
    if section.summary is None:
        return [design.small(f"⚠️ {section.problem or 'couldn’t be read'}")]
    said = section.summary
    return [*said.lines, *(design.small(line) for line in (said.hint, said.before) if line)]


MAX_NOTES = 3


def worth_knowing(notes: tuple[str, ...]) -> list[str]:
    """What is worth knowing and needs nothing done, each in one small line: the
    latest three, and the rest counted."""
    shown = [design.small(f"🗒️ {note}") for note in notes[-MAX_NOTES:]]
    return [*([design.small(f"🗒️ …and {len(notes) - MAX_NOTES} more before")] if len(notes) > MAX_NOTES else []), *shown]


def text(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = ()) -> str:
    """The briefing as a plain message (the old look, and what is logged)."""
    lines = [f"## {HEADING}", design.small(date_line(day))]
    if problems:
        lines += ["", NEEDS, *problems]
    if held_back:
        lines += ["", HELD, *held_back, *([design.small(held_note(hours))] if hours else [])]
    for section in sections:
        lines += ["", _name(section), *_lines(section)]
    if notes:
        lines += ["", *worth_knowing(notes)]
    lines += ["", design.small(FOOT)]
    return "\n".join(lines)


def layout(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = ()) -> tuple:
    """The briefing in the one style of docs/DESIGN.md: a standing message, a
    box a task in the colour of its status, and no buttons. What needs a look
    is a box of its own on top, then what was held back overnight."""
    boxes = []
    if problems:
        boxes.append(design.item(design.MISSED, NEEDS, *problems))
    if held_back:
        boxes.append(design.item(design.QUIET, HELD, *held_back, *([design.small(held_note(hours))] if hours else [])))
    boxes += [
        design.item(section.summary.status if section.summary is not None and section.summary.status else design.QUIET, _name(section), *_lines(section))
        for section in sections
    ]
    pieces = design.standing(HEADING, date_line(day), boxes)
    return (*pieces, *([design.Text("\n".join(worth_knowing(notes)))] if notes else []), design.Text(design.small(FOOT)))
