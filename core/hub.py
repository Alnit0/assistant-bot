from core.config import HUB_CHANNEL_ID

# ---------------------------------------------------------------------------
# The hub: the channel where the day's regular cards are posted, and how they
# are written so that every task's card reads the same. Pure.
# ---------------------------------------------------------------------------
SEGMENTS = 5
FILLED, EMPTY = "▰", "▱"


def channel_id() -> int | None:
    """The hub channel, or None if it isn't set in .env."""
    return HUB_CHANNEL_ID


def progress_bar(done: int, total: int, segments: int = SEGMENTS) -> str:
    """How far along: "▰▰▱▱▱ 2 of 5". The bar is rounded; the numbers are exact."""
    filled = round(segments * done / total) if total else 0
    return f"{FILLED * filled}{EMPTY * (segments - filled)} {done} of {total}"
