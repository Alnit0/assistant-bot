from dataclasses import dataclass
from datetime import date

from core import cards, design
from core.cards import Button

# ---------------------------------------------------------------------------
# Personal routines: my own named checklists on chosen days (a morning
# routine of a few steps). The folder is `habits` because "routine" in code
# is the scheduler's (the 6 am routine); everywhere I read it, it is
# "Personal routines". The words, what a day holds, and the card. Pure.
#
# A routine starts again each day: what is ticked is kept by day, so a new
# day has nothing ticked without anything having to run.
# ---------------------------------------------------------------------------
TASK = "habits"
ICON = "🔁"
TITLE = "Personal routines"
DAY_WORDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TICK = "tick"
NOTHING = f"{ICON} You have no personal routines."
MAX_STEPS = 12


@dataclass(frozen=True)
class Step:
    id: int
    text: str


@dataclass(frozen=True)
class Habit:
    id: int
    user_id: int
    name: str
    weekdays: tuple[int, ...] = ()  # Monday 0; empty: every day
    steps: tuple[Step, ...] = ()

    def on(self, day: date) -> bool:
        return not self.weekdays or day.weekday() in self.weekdays


@dataclass(frozen=True)
class Today:
    """One routine on one day: its steps and which are ticked."""

    habit: Habit
    ticked: frozenset[int]  # step ids

    @property
    def done(self) -> int:
        return sum(step.id in self.ticked for step in self.habit.steps)

    @property
    def total(self) -> int:
        return len(self.habit.steps)

    @property
    def finished(self) -> bool:
        return self.total > 0 and self.done == self.total

    @property
    def next_step(self) -> Step | None:
        return next((step for step in self.habit.steps if step.id not in self.ticked), None)


def due(habits: list[Habit], ticked: set[int], day: date) -> list[Today]:
    """The routines due on a day, in the order they were made."""
    return [Today(each, frozenset(step.id for step in each.steps if step.id in ticked)) for each in habits if each.on(day) and each.steps]


def days_text(weekdays: tuple[int, ...]) -> str:
    if not weekdays or len(weekdays) == 7:
        return "every day"
    if tuple(sorted(weekdays)) == (0, 1, 2, 3, 4):
        return "weekdays"
    if tuple(sorted(weekdays)) == (5, 6):
        return "weekends"
    return ", ".join(DAY_WORDS[each].capitalize() for each in sorted(weekdays))


def steps_text(steps) -> str:
    return " · ".join(f"{at}. {step}" for at, step in enumerate(steps, 1))


def tick_button(step: Step) -> Button:
    return Button(cards.truncate_label(step.text, 60), TASK, TICK, str(step.id), emoji="✅", style=cards.SUCCESS)


def entry(today: Today) -> design.Entry:
    """One routine in the box: its name with its own dots and count, the next step,
    and a button that ticks that step off."""
    step = today.next_step
    lines = [f"{design.name(today.habit.name)} {design.progress(today.done, today.total)}"]
    if step is not None:
        lines.append(f"next: {step.text}")
    ticked = [each.text for each in today.habit.steps if each.id in today.ticked]
    if ticked:
        lines.append(design.small("✅ " + " · ".join(ticked)))
    return design.Entry("\n".join(lines), design.ANY_TIME, (tick_button(step),) if step is not None else ())


def layout(found: list[Today]) -> tuple:
    """The card in round 3: one box, its card title with the day's dots over every
    step, a routine an item, and the finished ones in one small line at the bottom."""
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    waiting = [each for each in found if not each.finished]
    finished = [each for each in found if each.finished]
    box = design.topic(
        design.card_title(f"{ICON} {TITLE}", done, total),
        [entry(each) for each in waiting],
        tail=" · ".join(f"✅ {each.habit.name}" for each in finished),
        status="" if waiting else design.DONE,
    )
    return design.fit((box,))


def text(found: list[Today]) -> str:
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    lines = [f"## {ICON} {TITLE} · {done} of {total} done"]
    for each in found:
        mark = "✅" if each.finished else "▫️"
        step = each.next_step
        lines.append(f"{mark} **{each.habit.name}** · {each.done} of {each.total}" + (f" · next: {step.text}" if step else ""))
    return "\n".join(lines)


def buttons(found: list[Today]) -> tuple:
    waiting = [each.next_step for each in found if each.next_step is not None][:5]
    return (tuple(tick_button(step) for step in waiting),) if waiting else ()


def listed(habits: list[Habit]) -> str:
    if not habits:
        return NOTHING
    return "\n".join([f"{ICON} **{TITLE}** · {len(habits)}", *(f"• **{each.name}** · {days_text(each.weekdays)} · {steps_text(step.text for step in each.steps)}" for each in habits)])
