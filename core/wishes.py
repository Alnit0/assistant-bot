import logging
import sqlite3
from datetime import date, datetime

from core import database
from core.clock import now as clock_now

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The wishlist: what live could not do for Alex, kept quietly, one row a time.
#
# A wish is kept whenever a message ends in a decline ("I can't do that
# yet"), "I didn't understand that", "I can't log that yet", or a correction
# straight after a change (the change was a misread). Nothing is said and
# nothing pings: what he was told is exactly what he would have been told.
# A wish holds a date, the task (or none) and why, all in the code's own
# words: never his message, so no pill, event or diary word is ever in one.
# He can add one himself ("add to my wishlist: …", his own words, kept as
# said). The week's summary shows how many, in one small line; the
# `/suggest` skill folds them into the next brainstorm (docs/BRAINSTORM.md).
# ---------------------------------------------------------------------------
DECLINED = "asked for something it can't do yet"
NOT_UNDERSTOOD = "not understood"
NO_TASK = "said something was done that no task keeps"
MISREAD = "corrected straight after a change: misread"
ASKED = "added by Alex"


def summary(task_title: str, why: str) -> str:
    """The neutral line a wish is kept as: the task and why, never the message. Pure."""
    return f"{task_title or 'No task'} · {why}"


def db_add(conn: sqlite3.Connection, user_id: int, task: str, why: str, said: str, at: datetime) -> int:
    return conn.execute(
        "INSERT INTO wishes (user_id, task, why, summary, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, task, why, said, at.isoformat())
    ).lastrowid


def db_since(conn: sqlite3.Connection, user_id: int, since: date) -> list[tuple[str, str, str, str]]:
    """(day, task, why, summary) of each wish from `since` (its local midnight: a Monday morning's wish is
    the Sunday before in UTC), oldest first."""
    from datetime import timezone

    from core import day as days

    start = days.start_of(since).astimezone(timezone.utc).isoformat()
    return [
        (row[0][:10], row[1], row[2], row[3])
        for row in conn.execute("SELECT created_at, task, why, summary FROM wishes WHERE user_id = ? AND created_at >= ? ORDER BY id", (user_id, start))
    ]


async def note(user_id: int | None, task: str, task_title: str, why: str) -> None:
    """Keep a wish, quietly. A failure is logged and never reaches the conversation."""
    if user_id is None:
        return
    try:
        await database.run(db_add, user_id, task, why, summary(task_title, why), clock_now())
    except Exception:
        log.exception("A wish could not be kept")


async def add_said(user_id: int, words: str) -> None:
    """One Alex asked for, in his own words."""
    await database.run(db_add, user_id, "", ASKED, words.strip()[:300], clock_now())


async def week_line(user_id: int, monday: date) -> str:
    """The week's summary's small line: how many wishes this week, or "" for none."""
    count = len(await database.run(db_since, user_id, monday))
    if not count:
        return ""
    return f"{count} wish{'' if count == 1 else 'es'} on your wishlist this week: what I couldn't do yet"
