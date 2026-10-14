from dataclasses import dataclass
from datetime import date, datetime

from core import design, timeinput
from core.cards import Button
from core import cards

# ---------------------------------------------------------------------------
# To-dos: the words, what counts as today, and how the card is drawn. Pure.
#
# A to-do is a line of words and, if I gave one, the day it is for. One whose
# day has passed and is not done is overdue: it keeps its day, so the card can
# say "from Tue 13 Oct", and nothing has to run for it to carry over (it is
# worked out from the day, never stored). One with no day is for any day from
# the day it was added.
# ---------------------------------------------------------------------------
TASK = "todos"
ICON = "📝"
TITLE = "To-dos"
DONE_ACTION = "done"
MAX_SHOWN = 12  # to-dos a card lists; the rest are counted
NOTHING = f"{ICON} Nothing on your to-do list."


@dataclass(frozen=True)
class Todo:
    id: int
    user_id: int
    text: str
    day: date | None  # the day it is for; None for any day
    added_on: date
    done_at: datetime | None = None
    done_on: date | None = None  # the local day it was done

    @property
    def is_done(self) -> bool:
        return self.done_at is not None


@dataclass(frozen=True)
class Day:
    """A day's to-dos, as the card and the briefing read them."""

    overdue: tuple[Todo, ...]  # open, for a day before today, the oldest first
    today: tuple[Todo, ...]  # open, for today or for any day
    done: tuple[Todo, ...]  # done today
    later: tuple[Todo, ...]  # open, for a later day

    @property
    def total(self) -> int:
        return len(self.overdue) + len(self.today) + len(self.done)

    @property
    def is_empty(self) -> bool:
        """Nothing for today: no card, no line in the briefing."""
        return self.total == 0


def on(todos: list[Todo], today: date) -> Day:
    """What a day holds. A to-do for a later day is not today's, and one that was
    added after today is not either (a look back at an earlier day)."""
    mine = [each for each in todos if each.added_on <= today]
    open_ = [each for each in mine if not each.is_done]
    overdue = sorted((each for each in open_ if each.day is not None and each.day < today), key=lambda each: (each.day, each.id))
    current = sorted((each for each in open_ if each.day is None or each.day == today), key=lambda each: (each.day is None, each.id))
    later = sorted((each for each in open_ if each.day is not None and each.day > today), key=lambda each: (each.day, each.id))
    done = sorted((each for each in mine if each.is_done and each.done_on == today), key=lambda each: each.done_at)
    return Day(tuple(overdue), tuple(current), tuple(done), tuple(later))


def day_text(day: date, today: date) -> str:
    """A day as a to-do says it: "today", "tomorrow", "Fri 16 Oct"."""
    if day == today:
        return "today"
    if (day - today).days == 1:
        return "tomorrow"
    if (today - day).days == 1:
        return "yesterday"
    return f"{day:%a} {day.day} {day:%b}"


def line(todo: Todo, today: date) -> str:
    """One to-do in words, for a card or a reply: "**Call Ryan** · Fri 16 Oct"."""
    when = f" · {day_text(todo.day, today)}" if todo.day is not None else ""
    return f"**{todo.text}**{when}"


def done_button(todo: Todo) -> Button:
    return Button("Done", TASK, DONE_ACTION, str(todo.id), emoji="✅", style=cards.SUCCESS)


def entry(todo: Todo, today: date, overdue: bool, with_button: bool = True) -> design.Entry:
    lines = [design.name(todo.text)]
    if overdue:
        lines.append(design.small(f"from {day_text(todo.day, today)}"))
    return design.Entry("\n".join(lines), design.DUE if overdue else design.ANY_TIME, (done_button(todo),) if with_button else ())


def tail(found: Day, today: date) -> str:
    """The one small line at the bottom: what is done today, then how many are for later."""
    said = [f"✅ {each.text}" for each in found.done]
    if found.later:
        said.append(f"{len(found.later)} more later" + (f", next {day_text(found.later[0].day, today)}" if found.later[0].day else ""))
    return " · ".join(said)


def layout_r4(found: Day, today: date) -> tuple:
    """Round 4 (the relevance rule, core/design.py): a to-do has no time, so every
    open one for today can be done now: a full line with its Done; overdue first,
    with the day it was for. Done is one small line with a count, and what is for
    later days one more."""
    things = [design.Thing("\n".join([design.name(each.text), design.small(f"from {day_text(each.day, today)}")]), design.NOW, status=design.DUE, row=(done_button(each),)) for each in found.overdue]
    things += [design.Thing(design.name(each.text), design.NOW, status=design.ANY_TIME, row=(done_button(each),)) for each in found.today]
    things += [design.Thing(each.text, design.FINISHED) for each in found.done]
    shown = design.relevant(things)
    small = list(shown.small)
    if found.later:
        small.append(f"{len(found.later)} more later" + (f", next {day_text(found.later[0].day, today)}" if found.later[0].day else ""))
    title = design.card_title(f"{ICON} {TITLE}", len(found.done), found.total)
    box = design.topic(title, list(shown.entries)[:MAX_SHOWN], tail="\n".join(small), status="" if shown.entries else design.DONE)
    return design.fit(design.bolded((box,)))


def layout(found: Day, today: date) -> tuple:
    """The card in round 3 (docs/DESIGN.md): one box, its card title with the
    day's dots, overdue first (amber, with the day it was for), then today's,
    a Done button under each, and what is done in one small line. When it
    would not fit, the buttons go from the last up (design.fit)."""
    if design.current() >= 4:
        return layout_r4(found, today)
    waiting = [(each, True) for each in found.overdue] + [(each, False) for each in found.today]
    shown = waiting[:MAX_SHOWN]
    entries = [entry(todo, today, overdue) for todo, overdue in shown]
    lines = [design.small(f"and {len(waiting) - len(shown)} more")] if len(waiting) > len(shown) else []
    title = design.card_title(f"{ICON} {TITLE}", len(found.done), found.total)
    box = design.topic(title, entries, tail=tail(found, today), status="" if entries else design.DONE)
    if lines:
        box = design.Box(box.status, (*box.children, design.Text("\n".join(lines))))
    return design.fit(design.bolded((box,)))


def text(found: Day, today: date) -> str:
    """The same card as plain text: the old look, and what is logged."""
    lines = [f"## {ICON} {TITLE} · {len(found.done)} of {found.total} done"]
    lines += [f"⏰ {line(each, today)}" for each in found.overdue]
    lines += [f"▫️ {line(each, today)}" for each in found.today]
    lines += [f"✅ ~~{each.text}~~" for each in found.done]
    if found.later:
        lines.append(f"-# {len(found.later)} more later")
    return "\n".join(lines)


def buttons(found: Day) -> tuple:
    """The Done buttons for the plain look: one row of up to five, the most pressing first."""
    waiting = [*found.overdue, *found.today][:5]
    return (tuple(done_button(each) for each in waiting),) if waiting else ()


def listed(todos: list[Todo], today: date) -> str:
    """ "my to-dos": everything open, by day, and what was done today."""
    found = on(todos, today)
    if not (found.overdue or found.today or found.later or found.done):
        return NOTHING
    lines = [f"{ICON} **To-dos** · {len(found.overdue) + len(found.today) + len(found.later)} open"]
    lines += [f"⏰ {line(each, today)}" for each in found.overdue]
    lines += [f"▫️ {line(each, today)}" for each in found.today]
    lines += [f"🗓️ {line(each, today)}" for each in found.later]
    lines += [f"✅ ~~{each.text}~~" for each in found.done]
    return "\n".join(lines)
