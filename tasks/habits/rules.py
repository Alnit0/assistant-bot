from dataclasses import dataclass, field
from datetime import date, datetime, time

from core import cards, design, recurrence, timeinput
from core import day as days
from core.recurrence import Repeat

# ---------------------------------------------------------------------------
# Personal routines: my own named routines (a morning routine, an evening
# one). The folder is `habits` because "routine" in code is the scheduler's
# (the 6 am routine); everywhere I read it, it is "Personal routines". The
# words, what a day holds, when one matters, and its cards. Pure.
#
# A routine has a repeat (core/recurrence.py), a when (at a time, a window
# from and until, or any time today) and a nudge (none, at the start, or if
# it is not done by the end of its window). It is an ordered list of items:
# a step, or a group with a name whose own steps are a guide to read, not
# ticked one by one. One tick an item; a group's tick is the whole group;
# the dots count items. An item, or a step in a group, may have a repeat of
# its own (exfoliate Mondays and Thursdays): on other days it is not there.
#
# A routine starts again each day: what is ticked is kept by day, so a new
# day has nothing ticked without anything having to run. No streaks, and
# nothing nags unless a nudge was asked for.
#
# Its cards follow round 4: a routine is a list, so the list rule
# (`design.listed`): the first three open items in full, "+N more", and one
# Done dropdown for every open item, never a button under each.
# ---------------------------------------------------------------------------
TASK = "habits"
ICON = "🔁"
TITLE = "Personal routines"
DAY_WORDS = recurrence.DAY_WORDS
TICK = "tick"  # the button of the plain look, and of a card drawn before the rework
PICKED = "picked"  # the one Done dropdown of a routine (the list rule)
NOTHING = f"{ICON} You have no personal routines."
MAX_ITEMS = 25  # a routine's items: what one dropdown can hold
MAX_GUIDE = 12  # steps in a group

STEP, GROUP = "step", "group"
AT, WINDOW, ANY_TIME = "at", "window", "any_time"
WHENS = (AT, WINDOW, ANY_TIME)
NUDGE_NONE, NUDGE_START, NUDGE_END = "none", "start", "end"
NUDGES = (NUDGE_NONE, NUDGE_START, NUDGE_END)
# What a routine is at a moment
NOT_YET, OPEN, OVERDUE, FINISHED = "not_yet", "open", "overdue", "finished"
DONE_MENU = "✅ Done: pick one"


@dataclass(frozen=True)
class GuideStep:
    """A step inside a group: read, not ticked."""

    text: str
    repeat: Repeat | None = None  # its own; None: whenever its group is there


@dataclass(frozen=True)
class Item:
    id: int
    text: str  # the step's words, or the group's name
    kind: str = STEP
    guide: tuple[GuideStep, ...] = ()  # a group's steps, in order
    repeat: Repeat | None = None  # its own; None: whenever the routine is on

    @property
    def is_group(self) -> bool:
        return self.kind == GROUP

    def on(self, day: date) -> bool:
        return self.repeat is None or recurrence.on_day(self.repeat, day)

    def guide_on(self, day: date) -> tuple[str, ...]:
        return tuple(step.text for step in self.guide if step.repeat is None or recurrence.on_day(step.repeat, day))


@dataclass(frozen=True)
class Habit:
    id: int
    user_id: int
    name: str
    repeat: Repeat = recurrence.EVERY_DAY
    items: tuple[Item, ...] = ()
    when: str = ANY_TIME
    at: time | None = None  # for AT
    start: time | None = None  # for WINDOW
    end: time | None = None  # for WINDOW
    nudge: str = NUDGE_NONE

    def on(self, day: date) -> bool:
        return recurrence.on_day(self.repeat, day)

    def items_on(self, day: date) -> tuple[Item, ...]:
        return tuple(each for each in self.items if each.on(day))


@dataclass(frozen=True)
class Today:
    """One routine on one day: its items that day, and which are ticked."""

    habit: Habit
    day: date
    items: tuple[Item, ...]
    ticked: frozenset[int] = field(default_factory=frozenset)  # item ids

    @property
    def done(self) -> int:
        return sum(each.id in self.ticked for each in self.items)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def finished(self) -> bool:
        return self.total > 0 and self.done == self.total

    @property
    def open_items(self) -> tuple[Item, ...]:
        return tuple(each for each in self.items if each.id not in self.ticked)

    @property
    def next_item(self) -> Item | None:
        return next(iter(self.open_items), None)

    def starts(self) -> datetime | None:
        """When it begins that day: its time, or its window's start; None any time."""
        habit = self.habit
        moment = habit.at if habit.when == AT else habit.start if habit.when == WINDOW else None
        return days.at(self.day, moment) if moment is not None else None

    def ends(self) -> datetime | None:
        """When its window closes that day, or None (a time, or any time, has no end)."""
        if self.habit.when != WINDOW or self.habit.end is None:
            return None
        return days.at(self.day, self.habit.end)


def due(habits: list[Habit], ticked: set[int], day: date) -> list[Today]:
    """The routines on a day, in time order (any time last), each with its items that day."""
    found = [Today(each, day, each.items_on(day), frozenset(item.id for item in each.items if item.id in ticked)) for each in habits if each.on(day)]
    found = [each for each in found if each.items]
    return sorted(found, key=lambda each: (each.starts() is None, each.starts().timestamp() if each.starts() else 0, each.habit.id))


def state(today: Today, now: datetime) -> str:
    """What a routine is now: not yet (its time or window is still to come), open,
    overdue (a time gone by, or a window closed, with it not done), or finished."""
    if today.finished:
        return FINISHED
    start, end = today.starts(), today.ends()
    if start is not None and now < start:
        return NOT_YET
    if today.habit.when == AT:
        return OVERDUE
    if end is not None and now >= end:
        return OVERDUE
    return OPEN


def window_ok(start: time | None, end: time | None) -> bool:
    """A window is from a time until a later one, the same day."""
    return start is not None and end is not None and end > start


# --- the words ------------------------------------------------------------------------------------------------
def time_text(moment: time) -> str:
    return timeinput.format_time(moment)


def when_text(habit: Habit) -> str:
    """ "at 7:00 am", "6:00 pm to 11:00 pm", "any time"."""
    if habit.when == AT and habit.at is not None:
        return f"at {time_text(habit.at)}"
    if habit.when == WINDOW and habit.start is not None and habit.end is not None:
        return f"{time_text(habit.start)} to {time_text(habit.end)}"
    return "any time"


def nudge_text(habit: Habit) -> str:
    if habit.nudge == NUDGE_START:
        return "a nudge when it starts"
    if habit.nudge == NUDGE_END:
        return "a nudge if not done by the end" if habit.when == WINDOW else "a nudge if not done"
    return "no nudge"


def item_text(item: Item, today: date, with_repeat: bool = True) -> str:
    """One item in words: "Floss", "Skincare (cleanser, toner, serum)", "Exfoliate · every Mon and Thu"."""
    said = item.text
    if item.is_group and item.guide:
        said += " (" + ", ".join(step.text + (f" · {recurrence.text(step.repeat, today)}" if step.repeat is not None and with_repeat else "") for step in item.guide) + ")"
    if item.repeat is not None and with_repeat:
        said += f" · {recurrence.text(item.repeat, today)}"
    return said


def items_text(items, today: date) -> str:
    return " · ".join(f"{number}. {item_text(each, today)}" for number, each in enumerate(items, 1))


def summary_line(habit: Habit, today: date) -> str:
    """ "**Evening** · every day · 6:00 pm to 11:00 pm · 4 items"."""
    count = len(habit.items)
    return f"**{habit.name}** · {recurrence.text(habit.repeat, today)} · {when_text(habit)} · {count} item{'' if count == 1 else 's'}"


def listed(habits: list[Habit], today: date | None = None) -> str:
    """ "my routines": each routine, when, and its items."""
    if not habits:
        return NOTHING
    today = today or days.today()
    lines = [f"{ICON} **{TITLE}** · {len(habits)}"]
    for each in habits:
        lines.append(f"• {summary_line(each, today)}" + (f" · {nudge_text(each)}" if each.nudge != NUDGE_NONE else ""))
        lines.append(design.small(items_text(each.items, today)))
    return "\n".join(lines)


# --- the cards (the list rule, core/design.py) ------------------------------------------------------------------
def item_line(item: Item, day: date) -> str:
    """An item in full: its name in bold, and a group's steps for that day in one small line, a guide."""
    guide = item.guide_on(day)
    return "\n".join([design.name(item.text), *([design.small(" → ".join(guide))] if item.is_group and guide else [])])


def done_menu(today: Today) -> cards.Select:
    """One Done dropdown for every open item of the routine, in order; a group's
    tick is the whole group."""
    options = tuple(
        cards.Option(cards.truncate_label(each.text, cards.MAX_OPTION_TEXT), str(each.id), description=f"the whole group · {len(each.guide_on(today.day))} steps" if each.is_group else "")
        for each in today.open_items[: design.MAX_MENU]
    )
    return cards.Select(TASK, PICKED, options, placeholder=DONE_MENU, arg=str(today.habit.id))


def status_of(today: Today, now: datetime) -> str:
    return {FINISHED: design.DONE, OVERDUE: design.DUE, NOT_YET: design.QUIET}.get(state(today, now), design.ANY_TIME)


def when_line(today: Today, now: datetime) -> str:
    said = when_text(today.habit)
    if state(today, now) == OVERDUE:
        said += " · not done yet"
    return design.small(said)


def _parts(today: Today, now: datetime, heading: str) -> tuple[list, list]:
    """A routine's pieces by the list rule: (its texts and rules, its dropdown if any)."""
    listing = design.listed(today.open_items)
    children: list = [design.Text("\n".join([heading, when_line(today, now)]))]
    for each in listing.shown:
        children += [design.Separator(), design.Text(item_line(each, today.day))]
    small = [design.more_line(listing.more), *([f"✅ {today.done} done"] if today.done else [])]
    small = [line for line in small if line]
    if small:
        children += [design.Separator(), design.Text("\n".join(design.small(line) for line in small))]
    return children, ([done_menu(today)] if listing.menu else [])


def routine_card(today: Today, now: datetime) -> tuple:
    """Layout B: a routine's own card in the hub, from its time or window until it is
    done: its card title with its dots, when, the first three open items in full, "+N
    more", what is done counted, and one Done dropdown under them."""
    children, menu = _parts(today, now, design.card_title(f"{ICON} {today.habit.name}", today.done, today.total))
    return design.fit((design.Box(status_of(today, now), (*children, *menu)),))


def routine_text(today: Today) -> str:
    lines = [f"{ICON} **{today.habit.name}** · {today.done} of {today.total} · {when_text(today.habit)}"]
    lines += [f"{'✅' if each.id in today.ticked else '▫️'} {item_text(each, today.day, with_repeat=False)}" for each in today.items]
    return "\n".join(lines)


def all_layout(found: list[Today], now: datetime) -> tuple:
    """Layout A: one Personal routines card holding every routine of the day, a large
    rule between them, each by the list rule, and the dropdowns at the bottom (one a
    routine with something open, in the same order)."""
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    children: list = [design.Text(design.card_title(f"{ICON} {TITLE}", done, total))]
    menus: list = []
    for each in found:
        parts, menu = _parts(each, now, f"{design.name(each.habit.name)} {design.progress(each.done, each.total)}")
        children += [design.Separator(large=True), *parts]
        menus += menu
    waiting = [status_of(each, now) for each in found if not each.finished]
    return design.fit((design.Box(design.urgent(waiting) if waiting else design.DONE, (*children, *menus)),))


def all_text(found: list[Today]) -> str:
    return "\n\n".join(routine_text(each) for each in found)


# --- the plain look (CARDS_V2 off): a button for each routine's next item ----------------------------------------
def tick_button(item: Item) -> cards.Button:
    return cards.Button(cards.truncate_label(item.text, 60), TASK, TICK, str(item.id), emoji="✅", style=cards.SUCCESS)


def buttons(found: list[Today]) -> tuple:
    waiting = [each.next_item for each in found if each.next_item is not None][:5]
    return (tuple(tick_button(item) for item in waiting),) if waiting else ()
