from dataclasses import dataclass
from datetime import date, timedelta

from core import actions, design

# ---------------------------------------------------------------------------
# The week, for everything (behind WEEKLY_ALL, off until Alex approves): the
# Sunday evening summary as one card, a box a task, each task's own short
# line for the week it is given (`Entry.week`). A task with nothing to say
# that week is left out. Round 4: what the week came to in full, the detail
# in one small line. No discord.py, and nothing here knows a task.
#
# What can reach a lock screen is the card's first line, the page title,
# which names nothing. A task still keeps names off its line where the rule
# says so (the calendar: counts and times only).
# ---------------------------------------------------------------------------
TITLE = "📆 Your week"
QUIET_WEEK = "A quiet week: nothing to sum up."


@dataclass(frozen=True)
class Week:
    """One task's week, in its own words: a line, the dots it counts (or none), a small line, a status."""

    line: str
    done: int | None = None
    total: int | None = None
    small: str = ""
    status: str = design.QUIET


@dataclass(frozen=True)
class Section:
    name: str
    icon: str
    title: str
    week: Week


def span(monday: date, sunday: date) -> str:
    """ "Mon 12 to Sun 18 Oct" """
    first = f"{monday:%a} {monday.day}" + ("" if monday.month == sunday.month else f" {monday:%b}")
    return f"{first} to {sunday:%a} {sunday.day} {sunday:%b}"


def layout(sections: list[Section], monday: date, sunday: date, foot: str = "") -> tuple:
    """The card: its page title and the week's dates, then a box a task. `foot`: one small line under them
    (the wishlist's count), or none."""
    top = [design.page_title(TITLE), design.small(span(monday, sunday))]
    if not sections:
        return design.page([*top, QUIET_WEEK], [], [design.small(foot)] if foot else [])
    boxes = [
        design.topic(design.card_title(f"{each.icon} {each.title}", each.week.done, each.week.total), lines=[each.week.line], tail=each.week.small, status=each.week.status)
        for each in sections
    ]
    return design.fit(design.page(top, boxes, [design.small(foot)] if foot else []))


def text(sections: list[Section], monday: date, sunday: date, foot: str = "") -> str:
    """The same in words: the title first (what a phone shows), then a line a task."""
    lines = [f"{TITLE} · {span(monday, sunday)}"]
    lines += [f"{each.icon} {each.week.line}" for each in sections] or [QUIET_WEEK]
    return "\n".join([*lines, *([design.small(foot)] if foot else [])])


async def gather(user_id: int, monday: date, upto: date) -> list[Section]:
    """Every task's week that has something to say, in the order each task says it comes."""
    found = []
    for entry in actions.in_place():
        if entry.week is None:
            continue
        week = await entry.week(user_id, monday, upto)
        if week is not None:
            found.append(Section(entry.name, entry.icon, entry.title, week))
    return found


def sunday_of(monday: date) -> date:
    return monday + timedelta(days=6)
