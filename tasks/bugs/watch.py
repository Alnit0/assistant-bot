import asyncio
import logging
import sqlite3

from core import database
from tasks.bugs import listing

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Changes made to the bugs outside the bot: a fix marked shipped from the
# command line (python -m tasks.bugs.cli shipped), which writes to the
# database and cannot tell the running bot. Once a minute the bot reads a
# short fingerprint of every bug (its status, whether a fix shipped, when it
# closes) and, when it differs from the last, tells the bugs list and the
# attention model, so Needs a look is redrawn within a minute. Reading only:
# nothing here writes, posts or files anything, and a minute with no change
# is not a job and leaves no note.
# ---------------------------------------------------------------------------
EVERY = 60.0  # seconds between looks


def db_fingerprint(conn: sqlite3.Connection) -> tuple:
    """Every bug as (id, user, status, shipped at, closes on): any change made from anywhere shows in it."""
    return tuple(conn.execute("SELECT id, user_id, status, shipped_at, closes_on FROM bugs_items ORDER BY id").fetchall())


def users_changed(before: tuple, after: tuple) -> list[int]:
    """The users whose bugs differ between two fingerprints, each once, in order. Pure."""
    old = {row[0]: row for row in before}
    new = {row[0]: row for row in after}
    found = [row[1] for key, row in new.items() if old.get(key) != row]
    found += [row[1] for key, row in old.items() if key not in new]
    return [user_id for user_id in dict.fromkeys(found) if user_id is not None]


async def look(before: tuple | None) -> tuple:
    """One look: the fingerprint now, with each user whose bugs changed since `before` told.
    The first look (`before` None) only learns where things stand."""
    after = await database.run(db_fingerprint)
    if before is not None and after != before:
        changed = users_changed(before, after)
        log.info("Bugs changed outside the bot (%s): Needs a look is redrawn", ", ".join(f"user {each}" for each in changed) or "no user")
        for user_id in changed:
            listing.changed(user_id)
    return after


async def watching(every: float = EVERY) -> None:
    """Look once a minute for as long as the bot runs. A look that fails is logged and the next one tried."""
    seen = None
    while True:
        try:
            seen = await look(seen)
        except Exception:
            log.exception("The bugs could not be read for changes made outside the bot")
        await asyncio.sleep(every)
