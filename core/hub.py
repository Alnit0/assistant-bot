from core import scheduler
from core.config import HUB_CHANNEL_ID

# ---------------------------------------------------------------------------
# The hub: the channel where the day's regular cards are posted, and how they
# are written so that every task's card reads the same. Pure.
# ---------------------------------------------------------------------------
# The hub's morning routine: the schedule made for the pills checklist, with whatever else
# joins it (core/scheduler.py, `join_routine`). The order is the order they are posted in:
# the tidy and the briefing in front of the checklist, the other task cards after it
MORNING = "pills.checklist"
MORNING_NAME = "Morning routine"
TIDY_ORDER, BRIEFING_ORDER = 10, 20
# The task cards under the pills checklist, in the hub's fixed order (pills, then reminders,
# personal routines, gym, to-dos): each task joins the routine with its own order from
# CARDS_ORDER on (+10, +20, +30, +40 in that order), so it runs after the checklist
CARDS_ORDER = scheduler.AFTER
scheduler.name_routine(MORNING, MORNING_NAME)

SEGMENTS = 5
FILLED, EMPTY = "▰", "▱"


def channel_id() -> int | None:
    """The hub channel, or None if it isn't set in .env."""
    return HUB_CHANNEL_ID


def progress_bar(done: int, total: int, segments: int = SEGMENTS) -> str:
    """How far along: "▰▰▱▱▱ 2 of 5". The bar is rounded; the numbers are exact."""
    filled = round(segments * done / total) if total else 0
    return f"{FILLED * filled}{EMPTY * (segments - filled)} {done} of {total}"
