from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from core import day as days

# ---------------------------------------------------------------------------
# The schedule model: how often something is done in a day, and when each one
# is due. One shape for everything with a schedule. Pure: no clock, no
# database, no Discord, and nothing about what is being scheduled.
#
#   per_day       how many times a day
#   times         the planned time of each, in order; none means "any time".
#                 Fewer than per_day: only the first ones have a planned time
#   gap_minutes   the shortest time allowed between two, measured from when
#                 the earlier one was actually done
#   latest        nothing is due after this time of day
# Every setting but per_day is optional. (Days of the week come here later.)
#
# The rule for when one is due:
#   the later of its planned time and (the one before, done + the gap).
# Only the schedule is stored. What is due today is always worked out again
# from it and from what has been done so far (dues), so the plan never moves.
#
# Moments are UTC; planned times and `latest` are NZ local, placed on a day by
# core/day.py.
# ---------------------------------------------------------------------------
DAY_MINUTES = 24 * 60


@dataclass(frozen=True)
class Schedule:
    per_day: int = 1
    times: tuple[time, ...] = ()
    gap_minutes: int | None = None
    latest: time | None = None

    @property
    def gap(self) -> timedelta | None:
        return timedelta(minutes=self.gap_minutes) if self.gap_minutes is not None else None

    def planned(self, index: int) -> time | None:
        """The planned time of one of the day's (from 0), if it has one."""
        return self.times[index] if index < len(self.times) else None


# What became of one of the day's so far, other than the moment it was done
OPEN = "open"  # still to do
OUT = "out"  # skipped or missed: nothing waits for it

# Why something is due when it is
PLANNED = "planned"  # its planned time
AFTER_PREVIOUS = "after previous"  # the one before, plus the gap
ANY_TIME = "any time"  # no planned time and nothing to wait for
WAITING = "waiting"  # no time yet: it follows one that hasn't been done


@dataclass(frozen=True)
class Due:
    at: datetime | None  # None while it has no time
    why: str

    @property
    def is_timed(self) -> bool:
        return self.at is not None


def limit(schedule: Schedule, day: date) -> datetime:
    """The day's limit: the latest time if there is one, otherwise the end of the day. UTC."""
    return days.at(day, schedule.latest) if schedule.latest is not None else days.end_of(day)


def dues(
    schedule: Schedule, day: date, so_far: Sequence[datetime | str] = (), now: datetime | None = None
) -> list[Due]:
    """When each of the day's is due, given what has been done so far.

    `so_far` says what became of each, in order: the moment it was done, OPEN
    or OUT; any it leaves out are OPEN. One still open is expected at its own
    due time (not before `now`, if given), so those after it show when they
    will be due if it is done on time. One that was done keeps the time it
    would have been due, for the record.
    """
    found: list[Due] = []
    previous: datetime | None = None  # when the one before was done, or is expected to be
    waiting = False  # the one before is still to do, and has no time
    for index in range(schedule.per_day):
        planned = schedule.planned(index)
        planned_at = days.at(day, planned) if planned is not None else None
        if planned_at is not None and (schedule.gap is None or previous is None or planned_at >= previous + schedule.gap):
            due = Due(planned_at, PLANNED)
        elif schedule.gap is not None and previous is not None:
            due = Due(previous + schedule.gap, AFTER_PREVIOUS)
        else:
            due = Due(None, WAITING if waiting else ANY_TIME)
        found.append(due)

        state = so_far[index] if index < len(so_far) else OPEN
        if isinstance(state, datetime):
            previous, waiting = state, False
        elif state == OPEN and schedule.gap is not None:
            if due.at is not None:
                previous, waiting = (max(due.at, now) if now is not None else due.at), False
            else:
                previous, waiting = None, True
    return found


@dataclass(frozen=True)
class Move:
    """A planned time that had to move to keep the gap from the one before."""

    index: int
    before: time  # the one it was too close to, as it now stands
    was: time
    now: time


def spaced(schedule: Schedule) -> tuple[Schedule, list[Move]]:
    """The schedule with its planned times at least the gap apart: one that is
    too close to the one before moves later, and so may those after it. Also
    what moved. A time that would move past midnight is left where it is: the
    caller's own checks refuse it."""
    if schedule.gap_minutes is None or len(schedule.times) < 2:
        return schedule, []
    times, moves = list(schedule.times), []
    for index in range(1, len(times)):
        earliest = _minutes(times[index - 1]) + schedule.gap_minutes
        if _minutes(times[index]) < earliest < DAY_MINUTES:
            moved = time(*divmod(earliest, 60))
            moves.append(Move(index, times[index - 1], times[index], moved))
            times[index] = moved
    return replace(schedule, times=tuple(times)), moves


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute
