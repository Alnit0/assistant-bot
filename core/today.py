import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from core import actions, design, timeinput

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The Today card: the day in time order, in one card under the pills card
# (behind TODAY_CARD, off unless set). Each task that has things for today
# hands them over as `Line`s (its `today` in the task contract), and this
# file draws them, so the card reads the same whoever's they are: to-dos,
# personal routines (a line each, with its time or window), reminders as
# notes at their times, and calendar events. Pills keep their own card
# above it. All-day events are one small line at the top.
#
# It follows round 4's relevance rule (core/design.py): what can be done now
# in full, the next timed thing in full, the rest of the day one small line
# of times, and what is done one small line with a count. What has no time
# comes after the timed things, by the list rule (the first three, "+N
# more"). When everything is done the card is one small line. It has no
# buttons: each thing is done on its own card, or in words.
# ---------------------------------------------------------------------------
ICON = "📅"
TITLE = "Today"
TIME_LIMIT = 2.0  # seconds a task gets


@dataclass(frozen=True)
class Line:
    """One thing on the Today card, as a task hands it over."""

    icon: str  # the task's own
    text: str  # its name in bold, then what it is ("**Evening** · 6:00 pm to 11:00 pm")
    at: datetime | None = None  # when it is, or starts; None any time today
    until: datetime | None = None  # a window's end
    done: bool = False
    note: bool = False  # only to read (a reminder): it is not done, it is at its time
    event: bool = False  # a calendar event: over once it has ended, never ticked
    all_day: bool = False  # an all-day event: in the small line at the top


def _full(line: Line) -> str:
    return f"{line.icon} {line.text}"


def _when(line: Line, now: datetime) -> str:
    return timeinput.format_moment(line.at) if line.at is not None else ""


def _over(line: Line, now: datetime) -> bool:
    """An event that has ended (one with no end: once it has started)."""
    return line.at is not None and (line.until if line.until is not None else line.at) <= now


def layout(lines: list[Line], now: datetime) -> tuple:
    """The card: its title with the day's dots (notes and events not counted), all-day
    events in one small line on top, then by the relevance rule (events that are over
    one small line with a count); one small line when everything is done."""
    all_day = [each for each in lines if each.all_day]
    lines = [each for each in lines if not each.all_day]
    doable = [each for each in lines if not each.note and not each.event]
    done = [each for each in doable if each.done]
    notes_left = [each for each in lines if each.note and each.at is not None and each.at > now]
    events_left = [each for each in lines if each.event and not _over(each, now)]
    events_over = [each for each in lines if each.event and _over(each, now)]
    if not doable and not notes_left and not events_left and not all_day:
        return ()
    if doable and len(done) == len(doable) and not notes_left and not events_left and not all_day:
        return (design.Text(design.small(f"{ICON} {TITLE} · all done ✅ {len(done)}")),)
    things = []
    for each in lines:
        if each.done or (each.note and (each.at is None or each.at <= now)) or (each.event and _over(each, now)):
            continue
        if each.at is None:
            continue
        if each.at <= now:
            if each.event:
                text = f"{_full(each)}\n{design.small('on now · until ' + timeinput.format_moment(each.until))}" if each.until else _full(each)
                things.append(design.Thing(text, design.NOW, each.at, _when(each, now), status=design.DUE))
                continue
            overdue = each.until is not None and now >= each.until
            text = _full(each) + (f"\n{design.small('not done yet')}" if overdue else "")
            things.append(design.Thing(text, design.NOW, each.at, _when(each, now), status=design.DUE))
        else:
            things.append(design.Thing(f"{_full(each)}\n{design.when(timeinput.format_moment(each.at), each.at, now)}", design.COMING, each.at, _when(each, now)))
    shown = design.relevant(things)
    any_time = design.listed([each for each in doable if not each.done and each.at is None])
    entries = [*shown.entries, *(design.Entry(_full(each), design.ANY_TIME) for each in any_time.shown)]
    earlier = [f"{events_over[0].icon} {len(events_over)} earlier today"] if events_over else []
    small = [*earlier, *shown.small, design.more_line(any_time.more), *([f"✅ {len(done)} done"] if done else [])]
    top = [design.small(f"{all_day[0].icon} all day · " + " · ".join(each.text for each in all_day))] if all_day else []
    title = design.card_title(f"{ICON} {TITLE}", len(done), len(doable)) if doable else design.card_title(f"{ICON} {TITLE}")
    box = design.topic(title, entries, lines=top, tail="\n".join(line for line in small if line), status="" if entries else design.QUIET)
    return design.fit(design.bolded((box,)))


def text(lines: list[Line], now: datetime) -> str:
    """The same card as plain text: the old look, and what is logged."""
    if not lines:
        return ""
    said = [f"## {ICON} {TITLE}"]
    for each in sorted(lines, key=lambda each: (each.at is None, each.at.timestamp() if each.at else 0)):
        mark = "✅" if each.done else "🗒️" if each.note or each.event else "▫️"
        when = f" · {timeinput.format_moment(each.at)}" if each.at is not None and "·" not in each.text else ""
        said.append(f"{mark} {_full(each)}{when}")
    return "\n".join(said)


async def gather(user_id: int, now: datetime) -> list[Line]:
    """Every task's things for today, in time order (any time last). A task that
    can't be read is left out and logged: the card still shows the rest."""
    found: list[Line] = []
    for entry in actions.catalogue():
        if entry.today is None:
            continue
        try:
            found += list(await asyncio.wait_for(entry.today(user_id, now), TIME_LIMIT))
        except Exception:
            log.exception("The Today lines of %s could not be read", entry.name)
    return sorted(found, key=lambda each: (each.at is None, each.at.timestamp() if each.at else 0))
