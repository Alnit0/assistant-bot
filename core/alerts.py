import asyncio
import logging
import sqlite3
from datetime import datetime, time

from core import attention, cards, clock, config, database, hub, lifecycle, messages, notify, scheduler, surface, timeinput, timetable
from core.attention import Item
from core.cards import Card
from core.lifecycle import MessageClass

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Being told about what needs me.
#
# "Needs me" is level 1 of the one ranking (core/attention.py): a job that
# did not work, reminders that can't be sent, Claude spend over the day's
# limit, the bot's memory over its limit, any bug the bot filed itself. The
# briefing shows them in its "Needs a look" box and the status line shows
# the first. This is the third surface, the ping:
#
#   by day       when one appears, the bot mentions me in the hub with one
#                short line ("⚠️ B14 · backup failed at 3:00 am"). When it is
#                dealt with (it is no longer in the ranking) the line goes,
#                by the tidy.
#   quiet hours  nothing is posted: it is in the briefing's box in the
#                morning, and when quiet hours end one check (a schedule, at
#                7:00 am, shown in "my schedule") pings once if the box is
#                not empty: "⚠️ 2 things need a look".
#
# All of it goes through the notify service, as the kind "system.problem":
# where that kind goes is one line of its table. Nothing here decides what
# needs me, and nothing here writes to #bot-log: that stays the record it
# was. The rule this serves: anything I need to know reaches me through the
# briefing or a ping, never only through #bot-log.
#
# The dev bot posts its lines without a mention and without a sound: a
# self-test must never reach my phone.
# ---------------------------------------------------------------------------
KIND = "system.problem"
JOB_TASK, JOB_KIND = "core", "needs_look"
LABEL = "needs-a-look check"
DEFAULT = timetable.Default("Needs-a-look check", time(7, 0), notify=timetable.NOTIFY)
CHECK = "the 7:00 am check"  # the key its own line is kept under
ICON = "⚠️"


def key(item: Item) -> str:
    """What a problem's line in the hub is kept under: its bug if it has one, else what it says."""
    return item.bug or f"{item.task}: {item.what}"


def lasting(item: Item) -> str:
    """What a problem is known by for good, for pinging: it pings once, ever (16 Oct: a bug renumbered
    pinged again for a self-test run already pinged at 7:00 am)."""
    return item.once or key(item)


def line(item: Item) -> str:
    """The one short line of a ping: "⚠️ B14 · backup failed at 3:00 am". Never a name of mine."""
    said = f"{item.icon or ICON} {f'{item.bug} · ' if item.bug else ''}{item.what}"
    return f"{said} at {timeinput.format_moment(item.when)}" if item.when is not None else said


def count_line(count: int) -> str:
    return f"{ICON} 1 thing needs a look" if count == 1 else f"{ICON} {count} things need a look"


def addressed(text: str) -> str:
    """The line with me mentioned in front, so that it pings. The dev bot mentions nobody."""
    who = "" if config.DEV_DATABASE else surface.mention(config.OWNER_ID)
    return f"{who} {text}".strip()


def where() -> int | None:
    """The hub; the inbox if there is no hub to post in."""
    found = hub.channel_id()
    return found if surface.place(found) is not None else config.INBOX_CHANNEL_ID


async def needing(user_id: int, now: datetime) -> list[Item]:
    """What needs me now and is worth a ping, in the ranking's order."""
    ranked = attention.ranked(await attention.gather(user_id, now), now)
    return [item for rank, item in ranked if rank == attention.LEVEL_PROBLEM and item.ping]


# --- what has been said ------------------------------------------------------------------------------------------------
def db_known(conn: sqlite3.Connection) -> dict[str, tuple[int | None, int | None]]:
    return {row[0]: (row[1], row[2]) for row in conn.execute("SELECT key, channel_id, message_id FROM needs_look")}


def db_keep(conn: sqlite3.Connection, name: str, user_id: int, said: str, now: datetime, channel_id: int | None, message_id: int | None) -> None:
    conn.execute(
        """
        INSERT INTO needs_look (key, user_id, line, first_at, channel_id, message_id) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET line = excluded.line, channel_id = excluded.channel_id, message_id = excluded.message_id
        """,
        (name, user_id, said, now.isoformat(), channel_id, message_id),
    )


def db_pinged(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT key FROM alerts_pinged")}


def db_ping(conn: sqlite3.Connection, names: list[str], user_id: int, said: str, now: datetime) -> None:
    conn.executemany("INSERT OR IGNORE INTO alerts_pinged (key, user_id, line, at) VALUES (?, ?, ?, ?)", [(name, user_id, said, now.isoformat()) for name in names])


def db_forget(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM needs_look WHERE key = ?", (name,))


async def _take_down(channel_id: int | None, message_id: int | None) -> None:
    """A line whose thing is dealt with goes: by the tidy when it is on, else at once."""
    if channel_id is None or message_id is None:
        return
    if messages.enabled():
        await database.run(messages.db_expire, [message_id], clock.now())
        await messages.book_expiry()
    elif lifecycle.deletes(MessageClass.ALERT):
        await cards.delete(channel_id, message_id)


async def _say(user_id: int, name: str, text: str, item: Item, now: datetime) -> int | None:
    channel_id = where()
    if channel_id is None:
        return None
    message_id = await notify.post(KIND, channel_id, Card(addressed(text)), user_id=user_id, item=item, key=name, quiet=config.DEV_DATABASE)
    await database.run(db_keep, name, user_id, text, now, channel_id, message_id)
    return message_id


_looking = asyncio.Lock()


async def look() -> tuple[int, int]:
    """Bring the pings up to date with what needs me now: a line for each new
    thing (by day), and the line of each thing dealt with taken down.
    Returns (said, taken down). Never raises."""
    said = gone = 0
    try:
        async with _looking:
            user_id = await database.run(notify.db_owner)
            if user_id is None:
                return 0, 0
            now = clock.now()
            needs = {key(item): item for item in await needing(user_id, now)}
            known = await database.run(db_known)
            pinged = await database.run(db_pinged)
            for name, item in needs.items():
                if name in known:
                    continue
                if lasting(item) in pinged:
                    # Pinged once already (before a restart, a new number, a change of words): kept, never said again
                    await database.run(db_keep, name, user_id, line(item), now, None, None)
                    log.info("Needs a look, pinged before, not again: %s", line(item))
                    continue
                if notify.holds(KIND, now):
                    # Quiet hours: nothing is posted. It is in the briefing's box, and the 7:00 am check pings once
                    await database.run(db_keep, name, user_id, line(item), now, None, None)
                    log.info("Needs a look, held by quiet hours: %s", line(item))
                    continue
                await _say(user_id, name, line(item), item, now)
                await database.run(db_ping, [lasting(item)], user_id, line(item), now)
                log.info("Needs a look, said in the hub: %s", line(item))
                said += 1
            for name, (channel_id, message_id) in known.items():
                if name in needs or (name == CHECK and needs):
                    continue
                await _take_down(channel_id, message_id)
                await database.run(db_forget, name)
                log.info("No longer needs a look: %s", name)
                gone += 1
    except Exception:
        log.exception("Could not bring the pings for what needs a look up to date")
    return said, gone


_pending: set[asyncio.Task] = set()


def changed() -> None:
    """Told by the attention model that the ranking may be different. Called, not awaited."""
    try:
        looking = asyncio.get_running_loop().create_task(look())
    except RuntimeError:
        return
    _pending.add(looking)
    looking.add_done_callback(_pending.discard)


async def check_job(job: scheduler.Job) -> None:
    """Scheduler handler, when quiet hours end: one ping if anything needs me. When is the engine's business."""
    user_id = job.user_id or await database.run(notify.db_owner)
    if user_id is None:
        scheduler.note(job, "nothing said: there is no owner yet")
        return
    await look()
    now = clock.now()
    needs = await needing(user_id, now)
    if not needs:
        scheduler.note(job, "nothing needs a look: nothing said")
        return
    pinged = await database.run(db_pinged)
    fresh = [item for item in needs if lasting(item) not in pinged]
    if not fresh:
        scheduler.note(job, f"{len(needs)} need a look, every one pinged before: nothing said")
        return
    needs = fresh
    known = await database.run(db_known)
    await _take_down(*known.get(CHECK, (None, None)))  # yesterday's, if it is still up
    posted = await _say(user_id, CHECK, count_line(len(needs)), needs[0], now)
    if posted is not None:
        await database.run(db_ping, [lasting(item) for item in needs], user_id, count_line(len(needs)), now)
    scheduler.note(job, f"{len(needs)} need a look: " + ("said in the hub" if posted is not None else "held (quiet hours), or nowhere to say it"))


def setup() -> None:
    scheduler.register_handler(JOB_TASK, JOB_KIND, check_job, LABEL)
    scheduler.default_schedule(JOB_TASK, JOB_KIND, DEFAULT)
    attention.on_change(changed)
