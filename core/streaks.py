"""Streaks, worked out from the occurrence log (core/occurrences.py).

Pure: rows in, numbers out. Nothing is stored and nothing is shown yet.

The rule: only a missed occurrence breaks a streak. One that was skipped (by
hand or by the bot, whatever its cause), a day with nothing expected (a pause,
a pill not yet started) and what is still waiting today never break one, and
never add to one either. A day adds to the streak when something was done on
it and nothing was missed.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from core.occurrences import DONE, MISSED, Occurrence


@dataclass(frozen=True)
class Streak:
    days: int = 0  # days in a row, up to today, with something done and nothing missed
    done: int = 0  # how many were done in those days
    since: date | None = None  # the first day of the streak
    longest: int = 0  # the longest run of days there has been, this one included
    broken_on: date | None = None  # the last day something was missed


def _days(found: Iterable[Occurrence], today: date) -> dict[date, tuple[int, int]]:
    """(done, missed) for each day up to today that had either."""
    days: dict[date, tuple[int, int]] = {}
    for occurrence in found:
        if occurrence.day > today or occurrence.state not in (DONE, MISSED):
            continue
        done, missed = days.get(occurrence.day, (0, 0))
        days[occurrence.day] = (done + (occurrence.state == DONE), missed + (occurrence.state == MISSED))
    return days


def streak(found: Iterable[Occurrence], today: date) -> Streak:
    """The streak of these occurrences as it stands on `today`."""
    days = _days(found, today)
    run = done = longest = 0
    since: date | None = None
    broken_on: date | None = None
    for day in sorted(days):
        did, missed = days[day]
        if missed:
            # The day something was missed is not part of a streak, whatever else was done on it
            run, done, since, broken_on = 0, 0, None, day
            continue
        run, done = run + 1, done + did
        since = since or day
        longest = max(longest, run)
    return Streak(run, done, since, longest, broken_on)


def by_item(found: Iterable[Occurrence], today: date) -> dict[int, Streak]:
    """The streak of each item (each pill) on its own."""
    items: dict[int, list[Occurrence]] = {}
    for occurrence in found:
        items.setdefault(occurrence.item_id, []).append(occurrence)
    return {item_id: streak(rows, today) for item_id, rows in items.items()}


def breaks(occurrence: Occurrence) -> bool:
    """Whether this occurrence breaks a streak: only a missed one does."""
    return occurrence.state == MISSED
