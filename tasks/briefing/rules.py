from datetime import date

from core import design
from core.summaries import Section

# ---------------------------------------------------------------------------
# The briefing's words and how it is drawn. Pure. It holds no section's own
# words: each is its task's (core/summaries.py), and the briefing only puts
# them in order under one heading.
# ---------------------------------------------------------------------------
TASK = "briefing"
ICON = "☀️"
HEADING = f"{ICON} Today"
NOTHING = f"{ICON} Nothing on today."
UP_TO_DATE = f"{ICON} The briefing above is up to date."
FOOT = "always up to date · tick things off on their own message · say “my schedule” to change when this is posted"


def date_line(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B}"


def notice(at: str) -> str:
    """The one line a briefing that notifies is first posted as: what the phone
    shows. It names nothing of mine."""
    return f"{ICON} Morning briefing · {at}"


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


def text(sections: list[Section], day: date) -> str:
    """The briefing as a plain message (the old look, and what is logged)."""
    lines = [f"## {HEADING}", design.small(date_line(day))]
    for section in sections:
        lines += ["", _name(section), *_lines(section)]
    lines += ["", design.small(FOOT)]
    return "\n".join(lines)


def layout(sections: list[Section], day: date) -> tuple:
    """The briefing in the one style of docs/DESIGN.md: a standing message, a
    box a task in the colour of its status, and no buttons."""
    boxes = [
        design.item(section.summary.status if section.summary is not None and section.summary.status else design.QUIET, _name(section), *_lines(section))
        for section in sections
    ]
    return design.standing(HEADING, date_line(day), boxes, hint=FOOT)
