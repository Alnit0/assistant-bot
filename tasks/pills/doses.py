from datetime import date, datetime

from core import schedule, timeinput
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from core.schedule import Due, Schedule

# ---------------------------------------------------------------------------
# Pills: what the day's limit means for a dose. Pure, and it knows a pill only
# by its schedule (core/schedule.py says when each dose is due).
#
# The day's limit is the pill's latest time if it has one, otherwise midnight.
# A dose that would be due after it can no longer fit today; a dose with a gap
# has a time it must be taken by for those after it to still fit.
#
# No dose is left waiting once it can no longer be taken today (outcomes):
#   one that could never have been taken in time (the dose before it was
#   taken too late, or is still not taken and now can't be in time for this
#   one) is skipped by the bot, with the reason, the moment that is so;
#   one that had its time and wasn't taken is missed once the limit has
#   passed, and so is everything left if nothing of the pill was taken all day.
# Both are the bot's own conclusions and are looked at again whenever anything
# changes: a dose it skipped comes back if a correction makes room for it.
# ---------------------------------------------------------------------------
NO_TIME = "not enough time before "
# Why the bot set a dose aside, as the occurrence log keeps it (`cause`): what
# code reads. The reason beside it is only ever shown
NO_ROOM = "no_room"  # it could never have been taken in time: looked at again when anything changes
NOT_IN_PLAN = "not_in_plan"  # its pill was removed or changed during the day: final
IGNORED = "ignored"  # missed after every reminder went unanswered (reminders.py): final


def fits(due: Due, plan: Schedule, day: date) -> bool:
    """Whether a dose due then is still within the day's limit. One with no time always is."""
    return due.at is None or due.at <= schedule.limit(plan, day)


def take_by(plan: Schedule, day: date, later: int) -> datetime | None:
    """The latest moment a dose can be taken so that the `later` doses still
    to come after it fit before the day's limit, the gap apart. None for a
    pill with no gap: nothing depends on when it is taken."""
    if plan.gap is None:
        return None
    return schedule.limit(plan, day) - plan.gap * later


def limit_text(plan: Schedule) -> str:
    """The day's limit as it is said: "4:00 pm", or "midnight"."""
    return timeinput.format_time(plan.latest) if plan.latest is not None else "midnight"


def is_after_limit(plan: Schedule, day: date, moment: datetime) -> bool:
    """Whether a moment is past the pill's latest time. A pill without one has
    no such time: midnight ends the day for everything."""
    return plan.latest is not None and moment > schedule.limit(plan, day)


def decided_by_the_bot(occurrence) -> bool:
    """Whether a dose's state is the bot's to decide: still open, skipped by the
    bot because it couldn't fit, or missed because the limit passed. What the
    user did (taken, skipped by hand) is never touched."""
    if occurrence.state == PENDING:
        return True
    if occurrence.state == SKIPPED:
        return bool(occurrence.automatic) and occurrence.cause == NO_ROOM
    # Missed because the day's limit passed is looked at again; missed after its reminders is not
    return occurrence.state == MISSED and bool(occurrence.automatic) and occurrence.cause != IGNORED


def outcomes(plan: Schedule, day: date, found: dict, now: datetime) -> dict[int, tuple[str, str | None]]:
    """What each dose the bot decides should be now: {which: (state, reason)}.
    `found` is the day's occurrences by number.

    A dose can still be taken if the earliest it could be (not before now,
    not before its planned time, not before the gap after the dose before
    it) is within the day's limit. One that can't: if it could never have
    been in time whatever was done now, it is skipped, with the reason; if
    it had its time and that passed, or nothing of the pill was taken all
    day, it was missed.
    """
    limit = schedule.limit(plan, day)
    reason = NO_TIME + limit_text(plan)
    taken_any = any(occurrence.state == DONE for occurrence in found.values())
    decided: dict[int, tuple[str, str | None]] = {}
    anchor: datetime | None = None  # when the dose before was taken, or could be at the earliest
    for index in range(plan.per_day):
        occurrence = found.get(index + 1)
        if occurrence is None:
            continue
        if occurrence.state == DONE and occurrence.actual_at is not None:
            anchor = occurrence.actual_at
            continue
        if not decided_by_the_bot(occurrence):
            continue
        # From when it could be taken, whatever time it is now
        planned = plan.planned(index)
        available = schedule.days.at(day, planned) if planned is not None else None
        if plan.gap is not None and anchor is not None:
            available = max(available, anchor + plan.gap) if available is not None else anchor + plan.gap
        earliest = max(available, now) if available is not None else now
        fits = earliest <= limit if plan.latest is not None else earliest < limit
        anchor = earliest  # the doses after it wait on it, taken or not
        if fits:
            decided[index + 1] = (PENDING, None)
        elif not taken_any and now > limit:
            decided[index + 1] = (MISSED, None)
        elif available is not None and (available > limit or (plan.latest is None and available >= limit)):
            decided[index + 1] = (SKIPPED, reason)
        else:
            decided[index + 1] = (MISSED, None)
    return decided
