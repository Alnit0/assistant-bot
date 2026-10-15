from dataclasses import dataclass
from datetime import date, datetime, time

from core import cards, design, recurrence, timeinput
from core import day as days
from core.cards import Button

# ---------------------------------------------------------------------------
# Reminders I set myself (the task's folder is `nudges`: REMINDERS_ENABLED and
# tasks/pills/reminders.py are the pills' own). The words, when one is due,
# and how its messages are drawn. Pure.
#
# A reminder has a time of day and a repeat: once (on one day), every day,
# weekdays, chosen days of the week, or every N days from a first day. When
# it comes round, and how that is said, is the one repeat engine's
# (core/recurrence.py): in local time, so daylight saving never moves it.
# ---------------------------------------------------------------------------
TASK = "nudges"
ICON = "⏰"
TITLE = "Reminders"
ONCE, DAILY, WEEKDAYS, DAYS, EVERY = "once", "daily", "weekdays", "days", "every"
REPEATS = (ONCE, DAILY, WEEKDAYS, DAYS, EVERY)
DAY_WORDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DONE, SNOOZE, SNOOZE_FOR, BACK = "done", "snooze", "snooze_for", "back"
SNOOZES = (("10 minutes", 10), ("1 hour", 60), ("Tomorrow", 24 * 60))  # what Snooze offers: (label, minutes)
NOTHING = f"{ICON} You have no reminders."


@dataclass(frozen=True)
class Nudge:
    id: int
    user_id: int
    text: str
    at: time  # the time of day, local
    repeat: str = ONCE
    first: date | None = None  # the day of a one-off; the first day of "every N days"
    weekdays: tuple[int, ...] = ()  # for DAYS: Monday 0
    every_days: int = 1  # for EVERY


@dataclass(frozen=True)
class Fired:
    """One time a reminder went off: the occurrence it stands for, and what became of it."""

    id: int
    nudge_id: int
    local: str  # the occurrence: "2026-10-15T17:00"
    due_at: datetime  # when it went off (a snooze: when it went off again)
    message_id: int | None
    done_at: datetime | None = None
    snoozed_until: datetime | None = None
    late: bool = False

    @property
    def is_open(self) -> bool:
        return self.done_at is None and self.snoozed_until is None


def repeat_of(nudge: Nudge) -> recurrence.Repeat:
    """The reminder's repeat, as the one engine takes it. Its first day counts only
    for a one-off and for every N days, as it always has."""
    kind = nudge.repeat if nudge.repeat in REPEATS else ONCE
    return recurrence.Repeat(kind, nudge.first if kind in (ONCE, EVERY) else None, nudge.weekdays if kind == DAYS else (), nudge.every_days)


def on_day(nudge: Nudge, day: date) -> bool:
    """Whether a reminder is due at all on a day."""
    return recurrence.on_day(repeat_of(nudge), day)


def next_due(nudge: Nudge, after: datetime) -> datetime | None:
    """The first moment it is due strictly after `after`, or None (a one-off gone by)."""
    return recurrence.next_due(repeat_of(nudge), nudge.at, after)


def local(moment: datetime) -> str:
    """An occurrence as its run key and its record name it: the local day and time."""
    return f"{days.day_of(moment).isoformat()}T{days.local_time(moment):%H:%M}"


def due_today(nudges: list[Nudge], day: date) -> list[tuple[datetime, Nudge]]:
    """Each reminder due on a day, with its moment, in time order."""
    return sorted(((days.at(day, each.at), each) for each in nudges if on_day(each, day)), key=lambda pair: (pair[0], pair[1].id))


def repeat_text(nudge: Nudge, today: date) -> str:
    """When it is due, in words: "today", "Fri 16 Oct", "every day", "weekdays", "Mon and Thu", "every 3 days"."""
    return recurrence.text(repeat_of(nudge), today)


def when_text(nudge: Nudge, today: date) -> str:
    """ "today at **5:00 pm**", "every Mon at **9:00 am**"."""
    return f"{repeat_text(nudge, today)} at {design.time(timeinput.format_time(nudge.at))}"


def line(nudge: Nudge, today: date) -> str:
    return f"**{nudge.text}** · {when_text(nudge, today)}"


# --- what goes off ------------------------------------------------------------------------------------------------
def notice(at: datetime, late: bool = False) -> str:
    """The first line of a reminder that goes off: what a phone shows. It names nothing of mine."""
    return f"{ICON} Reminder · {timeinput.format_moment(at)}" + (" · late" if late else "")


def fired_row(fired_id: int) -> tuple[Button, ...]:
    which = str(fired_id)
    return (
        Button("Done", TASK, DONE, which, emoji="✅", style=cards.SUCCESS),
        Button("Snooze", TASK, SNOOZE, which, emoji="💤", style=cards.PRIMARY),
    )


def snooze_row(fired_id: int) -> tuple[Button, ...]:
    """What Snooze offers: 10 minutes, 1 hour, tomorrow at the same time; and back."""
    which = str(fired_id)
    return (
        *(Button(label, TASK, SNOOZE_FOR, f"{which}:{minutes}", style=cards.PRIMARY) for label, minutes in SNOOZES),
        cards.cancel(TASK, BACK, which),
    )


def fired_text(nudge: Nudge, at: datetime, late: bool) -> str:
    return "\n".join([notice(at, late), f"**{nudge.text}**"])


def fired_layout(nudge: Nudge, at: datetime, late: bool, row: tuple) -> tuple:
    """A reminder that has gone off, in round 3: the neutral line on top, then
    one amber box with what it is as its card title and the time in bold."""
    lines = [design.card_title(f"{ICON} {nudge.text}"), f"{'was due' if late else 'due'} {design.time(timeinput.format_moment(at))}"]
    if late:
        lines.append(design.small("the bot was off when it was due"))
    box = design.Box(design.DUE, (design.Text("\n".join(lines)), design.Row(tuple(row))))
    return design.fit(design.notifying(notice(at, late), box))


# --- the card in the hub: what is still to come today -------------------------------------------------------------
def coming(nudges: list[Nudge], now: datetime) -> list[tuple[datetime, Nudge]]:
    return [(moment, each) for moment, each in due_today(nudges, days.day_of(now)) if moment > now]


def card_layout(waiting: list[tuple[datetime, Nudge]], now: datetime) -> tuple:
    if design.current() >= 4:
        # Round 4 (the relevance rule): the next one in full, the rest of the day one small line of times
        things = [design.Thing(f"{design.name(each.text)}\n{design.when(timeinput.format_moment(moment), moment, now)}", design.COMING, moment, timeinput.format_moment(moment)) for moment, each in waiting]
        shown = design.relevant(things)
        box = design.topic(design.card_title(f"{ICON} {TITLE}"), list(shown.entries), tail="\n".join(shown.small), status=design.QUIET)
        return design.fit((box,))
    entries = [
        design.Entry(f"{design.name(each.text)}\n{design.when(timeinput.format_moment(moment), moment, now)}", design.DUE)
        for moment, each in waiting
    ]
    box = design.topic(design.card_title(f"{ICON} {TITLE}"), entries, status=design.QUIET)
    return design.fit((box,))


def card_text(waiting: list[tuple[datetime, Nudge]]) -> str:
    return "\n".join([f"## {ICON} {TITLE} · still to come today", *(f"**{timeinput.format_moment(moment)}** · {each.text}" for moment, each in waiting)])
