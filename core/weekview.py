import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from core import design, planning, timeinput

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The week view (behind WEEK_VIEW, in #calendar): every task's days, read
# through the same contract a plan reads (`Entry.plan`, core/planning.py), so
# nothing here knows a task.
#
#   this week   one box a day, Monday to Sunday: the notable things in time
#               order (events with their times, timed reminders, what is due
#               all day: birthdays, expiries), and what comes every day folded
#               into one small line ("💊 3 doses · 🔁 2 routines"). Today is
#               highlighted; days gone by are faint
#   next week   one box, a line a day
#
# To-dos are not in it (a plan places them). Pure but for `gather`.
# ---------------------------------------------------------------------------
ICON = "🗓️"
THIS_WEEK, NEXT_WEEK = "This week", "Next week"


@dataclass(frozen=True)
class Day:
    day: date
    notable: tuple[planning.Piece, ...] = ()  # all day first, then in time order
    folded: tuple[tuple[str, str, int], ...] = ()  # (icon, word, how many): "💊", "dose", 3


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_of(day: date) -> list[date]:
    first = monday_of(day)
    return [first + timedelta(days=ahead) for ahead in range(7)]


def of(day: date, pieces: list[planning.Piece]) -> Day:
    """What a day holds for the week view, from its pieces."""
    all_day = [each for each in pieces if each.all_day]
    timed = sorted((each for each in pieces if not each.flexible and not each.all_day and not each.fold and each.at is not None), key=lambda each: (each.at, each.text))
    counts: Counter = Counter()
    icons: dict[str, str] = {}
    for each in pieces:
        if each.fold and not each.flexible:
            counts[each.fold] += 1
            icons.setdefault(each.fold, each.icon)
    folded = tuple((icons[word], word, count) for word, count in counts.items())
    return Day(day, tuple(all_day + timed), folded)


def piece_line(piece: planning.Piece) -> str:
    if piece.all_day or piece.at is None:
        return f"{piece.icon} {piece.text}"
    return f"{design.time(timeinput.format_moment(piece.at))} · {piece.icon} {piece.text}"


def folded_line(found: Day) -> str:
    return " · ".join(f"{icon} {count} {word}{'' if count == 1 else 's'}" for icon, word, count in found.folded)


def day_title(day: date, today: date) -> str:
    said = f"{day:%a} {day.day} {day:%b}"
    return f"Today · {said}" if day == today else said


def box(found: Day, today: date) -> design.Box:
    """A day's box: today highlighted (amber), a day gone by faint (every line small), the rest quiet."""
    past = found.day < today
    lines = [piece_line(each) for each in found.notable] or ["nothing on"]
    folded = folded_line(found)
    if past:
        lines = [design.small(each) for each in lines]
    status = design.DUE if found.day == today else design.QUIET
    return design.topic(design.card_title(day_title(found.day, today)), lines=lines, tail=folded, status=status)


def short_line(found: Day, today: date) -> str:
    """A day on one line, for next week: "**Mon 26 Oct** · 9:00 am Dentist · 🎂 Mum's birthday · 💊 3 doses"."""
    parts = [f"**{found.day:%a} {found.day.day} {found.day:%b}**"]
    parts += [f"{timeinput.format_moment(each.at)} {each.text}" if each.at is not None and not each.all_day else f"{each.icon} {each.text}" for each in found.notable]
    if found.folded:
        parts.append(folded_line(found))
    if len(parts) == 1:
        parts.append("nothing on")
    return " · ".join(parts)


def span_text(first: date, last: date) -> str:
    return f"{first.day} {first:%b} to {last.day} {last:%b}" if first.month != last.month else f"{first.day} to {last.day} {last:%b}"


def this_week(found: list[Day], today: date) -> tuple:
    """This week as a page: its title and a box a day."""
    top = [design.page_title(f"{ICON} {THIS_WEEK}"), design.small(span_text(found[0].day, found[-1].day))]
    return design.fit(design.page(top, [box(each, today) for each in found]))


def next_week(found: list[Day], today: date) -> tuple:
    """Next week in one box, a line a day."""
    title = design.card_title(f"{ICON} {NEXT_WEEK} · {span_text(found[0].day, found[-1].day)}")
    return design.fit((design.topic(title, lines=[short_line(each, today) for each in found], status=design.QUIET),))


def one_day(found: Day, today: date) -> tuple:
    """One day, as a question about it is answered: the same box."""
    return design.fit((box(found, today),))


def text(found: list[Day], today: date, title: str) -> str:
    """The same as plain text: the old look, and what is logged (names nothing private: the plan's pieces only)."""
    said = [f"## {ICON} {title} · {span_text(found[0].day, found[-1].day)}"]
    for each in found:
        said.append(short_line(each, today))
    return "\n".join(said)


async def gather(user_id: int, days: list[date], only: str = "") -> list[Day]:
    """Each day of the list from every task's contract; with `only`, that task's things alone (the calendar's
    own answers are its events, never a dose or a routine: Alex, 21 Oct)."""
    return [of(day, [each for each in await planning.gather(user_id, day) if not only or each.task == only]) for day in days]
