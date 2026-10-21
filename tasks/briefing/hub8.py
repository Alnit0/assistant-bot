from dataclasses import dataclass
from datetime import date, datetime

from core import design, timeinput
from core import day as days
from core.actions import DOSE, EVENT, MISSED, PENDING, PREPARED, ROUTINE, SKIPPED, TAKEN, TODO, TRACKING, DayItem
from core.design import Box, Row, Separator, Text

# ---------------------------------------------------------------------------
# Round 8 of the hub (DESIGN_ROUND=8, Alex, 22 Oct): round 5's boxes, headings,
# rules and small text, with round 7's one good idea, the coloured edge that
# says what state a box is in (design.EMBED_COLOURS, unchanged in meaning).
# ONE message, and nothing in it twice. Pure: from the day's items as the tasks
# hand them over (`Entry.day_items`) and the time; it knows kinds of things,
# never whose they are.
#
#   ## Thursday 22 October                       the page title, outside any box
#   -# Next: Pill B · 2:00 pm                    the next thing still to come
#   ┃ ### 💊 Pills ●○○ 1/3                        red: a dose due; green: all taken;
#   ┃ ~~Pill A · 8:00 am~~ / -# taken 8:28 am     grey otherwise. Taken struck through,
#   ┃ **Pill B · dose 1 of 2 · 11:00 am** [Taken] the next due bold (with its one button),
#   ┃ Pill B · dose 2 of 2 · 6:00 pm              later plain
#   ┃ ### 🗓️ Today                                 yellow with a one-off event today, else
#   ┃ **Event · on now · until 4:00 pm**          blue. Events and routines, no doses;
#   ┃ Evening · 10:30 pm                          done or over struck and faint
#   ┃ -# Coming up: Event Sat 24 Oct
#   ┃ ### To-dos                                   pink: the first three open, "and N more"
#   -# Diary streak 4 · 8 stories in #news       last, outside any box
#
# State is said by text style alone: no squares, no status emoji, one emoji on
# a box's heading and none in its lines. Exact times only (no countdown near a
# pill, Alex 16 Oct). Too big for one message, the To-dos box is a second
# message; a box is never split.
# ---------------------------------------------------------------------------
PILLS_TITLE = "💊 Pills"
TODAY_TITLE = "🗓️ Today"
TODOS_TITLE = "To-dos"
NEXT = "Next"
COMING_UP = "Coming up"
NOTHING_TODAY = "Nothing on today."
TODOS_FIRST = design.LIST_FIRST  # round 4's list rule: the first three open in full
ORDER = {EVENT: 0, DOSE: 1, ROUTINE: 2}  # at the same time


@dataclass(frozen=True)
class Hub:
    """Round 8's hub: the one message's layout, and the second message's (the To-dos box) when it would not fit."""

    first: tuple
    second: tuple | None = None


def heading(today: date) -> str:
    return design.page_title(f"{today:%A} {today.day} {today:%B}")


def _t(moment: datetime) -> str:
    return timeinput.format_moment(moment)


def _day(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _struck(line: str) -> str:
    return f"~~{line}~~"


def _bold(line: str) -> str:
    return f"**{line}**"


def _coming(item: DayItem, today: date) -> bool:
    """An event on a later day: one line at the foot of the Today box."""
    first = item.first_day if item.at is None else days.day_of(item.at)
    return item.kind == EVENT and first is not None and first > today


def _key(item: DayItem) -> tuple:
    """All day first, then by time (events, doses, routines at the same time), then what has no time."""
    if item.kind == EVENT and item.at is None:
        return (0, 0.0, 0, item.text.lower())
    if item.at is None:
        return (2, 0.0, ORDER.get(item.kind, 9), item.text.lower())
    return (1, item.at.timestamp(), ORDER.get(item.kind, 9), item.text.lower())


# --- the pills box -------------------------------------------------------------------------------------------------
def _due(item: DayItem, now: datetime) -> bool:
    """A dose due or overdue: still to take, its time come."""
    return item.state == PENDING and item.at is not None and item.at <= now


def dose_line(item: DayItem) -> str:
    """ "Pill B · dose 1 of 2 · 11:00 am", as the pills card writes it; "any time" for one with no time."""
    return " · ".join([item.text, *([f"dose {item.number} of {item.of}"] if item.of > 1 else []), _t(item.at) if item.at is not None else "any time"])


def pills_status(doses: list[DayItem], now: datetime) -> str:
    """The box's edge, its most urgent state: red with a dose due; green once every dose is dealt with and none was
    missed; grey otherwise (later, a missed one, a day still to come)."""
    if any(_due(each, now) for each in doses):
        return design.DUE_NOW
    if doses and all(each.state in (TAKEN, SKIPPED) for each in doses) and any(each.state == TAKEN for each in doses):
        return design.TAKEN
    return design.LATER


def _pills_emphasised(doses: list[DayItem], now: datetime) -> set[int]:
    """Which doses are bold: every one due now, or with none due, the next still to take."""
    due = {at for at, each in enumerate(doses) if _due(each, now)}
    if due:
        return due
    waiting = [at for at, each in enumerate(doses) if each.state == PENDING]
    return {waiting[0]} if waiting else set()


def pills_box(doses: list[DayItem], now: datetime) -> Box:
    """The Pills box: its heading with round 3's dots and count, then a dose a line in time order, a rule between."""
    doses = sorted(doses, key=_key)
    done = sum(each.state in (TAKEN, SKIPPED) for each in doses)
    children: list = [Text(design.card_title(PILLS_TITLE, done, len(doses)))]
    bold = _pills_emphasised(doses, now)
    for at, each in enumerate(doses):
        line = dose_line(each)
        if each.state == TAKEN:
            said = _struck(line) + ("\n" + design.small(f"taken {_t(each.done_at)}") if each.done_at is not None else "\n" + design.small("taken"))
        elif each.state == SKIPPED:
            said = _struck(line) + "\n" + design.small("skipped")
        elif each.state == MISSED:
            said = _struck(line) + "\n" + design.small("missed")
        else:
            said = _bold(line) if at in bold else line
        children += [Separator(), Text(said)]
        if each.button is not None and each.state == PENDING:
            children.append(Row((each.button,)))
    return Box(pills_status(doses, now), tuple(children))


# --- the today box -------------------------------------------------------------------------------------------------
def _over(item: DayItem, now: datetime, today: date) -> bool:
    """Done (a routine finished) or over (an event that has ended, or an all-day one on a day gone)."""
    if item.kind == ROUTINE:
        return item.state == TAKEN
    if item.at is None:
        return (item.last_day or item.first_day or today) < today
    return (item.until if item.until is not None and item.until > item.at else item.at) <= now


def _on_now(item: DayItem, now: datetime) -> bool:
    return item.kind == EVENT and item.at is not None and item.until is not None and item.at <= now < item.until


def today_line(item: DayItem, now: datetime) -> str:
    """ "Event · 8:00 am until 4:00 pm"; while on, "Event · on now · until 4:00 pm"; a routine "Evening · 10:30 pm";
    an all-day event "Event · all day". An event's title as it was written, with no emoji of ours."""
    if item.kind == EVENT:
        if item.at is None:
            last = item.last_day or item.first_day
            return f"{item.text} · all day" + (f" · until {_day(last)}" if last is not None and item.first_day is not None and last > item.first_day else "")
        if _on_now(item, now):
            return f"{item.text} · on now · until {_t(item.until)}"
        if item.until is not None and item.until > item.at:
            return f"{item.text} · {_t(item.at)} until {_t(item.until)}"
        return f"{item.text} · {_t(item.at)}"
    return f"{item.text} · {_t(item.at)}" if item.at is not None else f"{item.text} · any time"


def today_status(things: list[DayItem], today: date) -> str:
    """Yellow when a one-off (notable) event is today, blue otherwise."""
    return design.NOTABLE if any(each.kind == EVENT and not each.repeats and not _coming(each, today) for each in things) else design.ROUTINE


def today_box(things: list[DayItem], coming: list[DayItem], today: date, now: datetime) -> Box:
    """The Today box: events and routines in time order, a rule between; what is done or over struck and faint,
    what is on now and the next still to come bold; then one small line of one-off events in the days ahead."""
    things = sorted(things, key=_key)
    over = [_over(each, now, today) for each in things]
    upcoming = [at for at, each in enumerate(things) if not over[at] and each.at is not None and each.at > now]
    bold = {at for at, each in enumerate(things) if _on_now(each, now)} | ({upcoming[0]} if upcoming else set())
    children: list = [Text(design.card_title(TODAY_TITLE))]
    for at, each in enumerate(things):
        line = today_line(each, now)
        said = design.small(_struck(line)) if over[at] else _bold(line) if at in bold else line
        children += [Separator(), Text(said)]
    if coming:
        when = lambda each: each.first_day if each.at is None else days.day_of(each.at)  # noqa: E731
        ahead = sorted(coming, key=lambda each: (when(each), each.at.timestamp() if each.at is not None else 0.0))
        children += [Separator(), Text(design.small(f"{COMING_UP}: " + ", ".join(f"{each.text} {_day(when(each))}" for each in ahead)))]
    return Box(today_status(things, today), tuple(children))


# --- the to-dos box, the foot, the next thing ----------------------------------------------------------------------
def todos_box(open_todos: list[DayItem]) -> Box:
    """The To-dos box, pink: round 4's list rule, the first three open in full, then "and N more"."""
    children: list = [Text(design.card_title(TODOS_TITLE))]
    for each in open_todos[:TODOS_FIRST]:
        children += [Separator(), Text(each.text)]
    if len(open_todos) > TODOS_FIRST:
        children += [Separator(), Text(design.small(f"and {len(open_todos) - TODOS_FIRST} more"))]
    return Box(design.TODOS, tuple(children))


def foot(items: list[DayItem]) -> str:
    """The small last line, each part only when it has something: "Diary streak 4 · 8 stories in #news" (the news
    part opens the day's news message). No emoji."""
    parts = []
    for each in items:
        if each.kind == TRACKING and each.count is not None:
            parts.append(f"{each.title or each.text} streak {each.count}")
        elif each.kind == TRACKING:
            parts.append(each.text)
    for each in items:
        if each.kind == PREPARED:
            said = each.text.removeprefix(each.icon).strip() if each.icon else each.text
            parts.append(f"[{said}]({each.link})" if each.link else said)
    return design.small(" · ".join(parts)) if parts else ""


def next_line(items: list[DayItem], today: date, now: datetime) -> str:
    """ "-# Next: Pill B · 2:00 pm": the next dose, event or routine still to come today, at its time; "" with none."""
    waiting = [
        each for each in items
        if each.kind in ORDER and each.at is not None and each.at > now and days.day_of(each.at) == today
        and (each.kind == EVENT or each.state == PENDING)
    ]
    if not waiting:
        return ""
    first = min(waiting, key=_key)
    return design.small(f"{NEXT}: {first.text} · {_t(first.at)}")


# --- the message ---------------------------------------------------------------------------------------------------
def layout(items: list[DayItem], today: date, now: datetime) -> Hub:
    """Round 8's hub from the day's items: the page title and the next thing, the Pills box (only with doses today),
    the Today box (only with events or routines today), the To-dos box (only with open ones), the small last line.
    Over what one message takes, the To-dos box goes to a second message; never a box split."""
    doses = [each for each in items if each.kind == DOSE]
    things = [each for each in items if each.kind in (EVENT, ROUTINE) and not _coming(each, today)]
    coming = [each for each in items if _coming(each, today)]
    open_todos = [each for each in items if each.kind == TODO and each.state != TAKEN]
    top = [heading(today), next_line(items, today, now)]
    boxes = ([pills_box(doses, now)] if doses else []) + ([today_box(things, coming, today, now)] if things else [])
    todos = todos_box(open_todos) if open_todos else None
    end = foot(items)
    if not boxes and todos is None and not end:
        top.append(design.small(NOTHING_TODAY))
    first = tuple([Text("\n".join(line for line in top if line)), *boxes, *([todos] if todos else []), *([Text(end)] if end else [])])
    if not design.problem(first) or todos is None:
        return Hub(design.fit(first))
    # Too big for one message: the To-dos box is a message of its own under it
    first = tuple([Text("\n".join(line for line in top if line)), *boxes, *([Text(end)] if end else [])])
    return Hub(design.fit(first), (todos,))


def words(pieces) -> str:
    """A layout's words, a text a line: the copy that is compared, and what a plain message would say."""
    return "\n".join(design.texts(pieces))
