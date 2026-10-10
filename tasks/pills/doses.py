from datetime import date, datetime

from core import schedule
from core.schedule import Due, Schedule

# ---------------------------------------------------------------------------
# Pills: what the day's limit means for a dose. Pure, and it knows a pill only
# by its schedule (core/schedule.py says when each dose is due).
#
# The day's limit is the pill's latest time if it has one, otherwise midnight.
# A dose that would be due after it can no longer fit today; a dose with a gap
# has a time it must be taken by for those after it to still fit.
# ---------------------------------------------------------------------------


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
