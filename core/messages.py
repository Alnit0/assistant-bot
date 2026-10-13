import contextvars
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import discord

from core import clearing, clock, config, database, discord_utils, hub, lifecycle, protection, scheduler
from core import day as days
from core.lifecycle import MessageClass

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Message lifetimes and the tidy, behind HUB_TIDY (off unless set: off,
# nothing is recorded and nothing is ever deleted by this).
#
# The hub is a clean place to check in on what is relevant now
# (docs/CONVERSATION.md, principle 8). So every message the bot posts there,
# and every message of mine there, is recorded with a lifetime:
#
#   replaced  gone the moment a newer one takes its place (today's checklist,
#             the briefing): a message is sent with a `slot`, and a newer one
#             in the same slot replaces the older
#   day       gone at the first tidy after its day is over
#   expiry    gone when its own time comes: what I said in the hub and the
#             reply go 2 minutes after the reply, or when the card it led to
#             is saved, cancelled or expires
#   kept      never, by itself
#
# Three rules sit above what is declared. Pinned or 📌 is always kept (looked
# at on the message as it is at that moment). In the hub nothing is kept:
# "kept" there means the end of the day. And a message with no row here (one
# from before this, or sent some other way) is never touched.
#
# Deleting only removes the message: no record of any task is changed. What
# it said is written to data/exports/ first; if that can't be written,
# nothing is deleted. Nothing is said in the channel that is tidied, and
# #bot-log hears only of a failure.
# ---------------------------------------------------------------------------
REPLACED, DAY, EXPIRY, KEPT = "replaced", "day", "expiry", "kept"
AFTER_REPLY = timedelta(minutes=2)  # how long what was said in the hub stays once it is answered
MAX_TRIES = 3  # a message that can't be deleted this many times is left, and said once
JOB_TASK, EXPIRY_KIND, TIDY_KIND = "core", "message_expiry", "hub_tidy"
TITLE = "🧹 Tidy"

# The message of mine being handled now, if it was said in the hub: what the bot posts there
# meanwhile is its answer, and goes with it
_exchange: contextvars.ContextVar[int | None] = contextvars.ContextVar("exchange", default=None)


def enabled() -> bool:
    return bool(config.HUB_TIDY)


def in_hub(channel_id: int | None) -> bool:
    return channel_id is not None and channel_id == hub.channel_id()


@dataclass(frozen=True)
class Row:
    message_id: int
    channel_id: int
    lifetime: str
    slot: str
    day: str
    expires_at: datetime | None
    exchange: int | None
    mine: bool
    tries: int
    waits: bool


_COLUMNS = "message_id, channel_id, lifetime, slot, day, expires_at, exchange, mine, tries, waits"


def _row(row: tuple) -> Row:
    return Row(row[0], row[1], row[2], row[3] or "", row[4], scheduler.from_db(row[5]) if row[5] else None, row[6], bool(row[7]), row[8], bool(row[9]))


def _stamp(moment: datetime) -> str:
    return scheduler.to_db(moment)


# ---------------------------------------------------------------------------
# The rows (blocking; called through database.run)
# ---------------------------------------------------------------------------
def db_add(
    conn: sqlite3.Connection, message_id: int, channel_id: int, lifetime: str, now: datetime, *, slot: str = "", task: str = "",
    user_id: int | None = None, exchange: int | None = None, mine: bool = False,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO bot_messages (message_id, channel_id, user_id, task, lifetime, slot, day, posted_at, exchange, mine)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, channel_id, user_id, task, lifetime, slot, days.day_of(now).isoformat(), _stamp(now), exchange, int(mine)),
    )


def db_get(conn: sqlite3.Connection, message_id: int) -> Row | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM bot_messages WHERE message_id = ? AND gone_at IS NULL", (message_id,)).fetchone()
    return _row(row) if row else None


def db_all(conn: sqlite3.Connection) -> list[Row]:
    return [_row(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM bot_messages WHERE gone_at IS NULL ORDER BY message_id")]


def db_older_in_slot(conn: sqlite3.Connection, slot: str, channel_id: int, newer: int) -> list[Row]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM bot_messages WHERE slot = ? AND channel_id = ? AND message_id != ? AND gone_at IS NULL ORDER BY message_id",
        (slot, channel_id, newer),
    ).fetchall()
    return [_row(row) for row in rows]


def db_due(conn: sqlite3.Connection, now: datetime, hub_channel: int | None, expiry_only: bool = False) -> list[Row]:
    """What is to go now: what has expired; and, at a tidy, what belongs to a
    day that is over (everything recorded in the hub, whatever it declared,
    and a "day" message anywhere). A message waiting for its card is left."""
    today = days.day_of(now).isoformat()
    found = []
    for each in db_all(conn):
        if each.lifetime == KEPT:
            continue  # pinned, or left after it could not be deleted
        expired = each.lifetime == EXPIRY and each.expires_at is not None and each.expires_at <= now
        past = each.day < today and (each.channel_id == hub_channel or each.lifetime == DAY)
        if expired or (past and not expiry_only):
            found.append(each)
    return found


def db_gone(conn: sqlite3.Connection, message_id: int, why: str, now: datetime) -> None:
    conn.execute("UPDATE bot_messages SET gone_at = ?, why = ? WHERE message_id = ?", (_stamp(now), why, message_id))


def db_keep(conn: sqlite3.Connection, message_id: int, why: str) -> None:
    """Not to be tried again: it is pinned, or it could not be deleted."""
    conn.execute("UPDATE bot_messages SET lifetime = ?, why = ?, expires_at = NULL WHERE message_id = ?", (KEPT, why, message_id))


def db_tried(conn: sqlite3.Connection, message_id: int) -> int:
    conn.execute("UPDATE bot_messages SET tries = tries + 1 WHERE message_id = ?", (message_id,))
    return conn.execute("SELECT tries FROM bot_messages WHERE message_id = ?", (message_id,)).fetchone()[0]


def db_expire(conn: sqlite3.Connection, message_ids: list[int], at: datetime) -> None:
    for message_id in message_ids:
        conn.execute(
            "UPDATE bot_messages SET lifetime = ?, expires_at = ?, waits = 0 WHERE message_id = ? AND gone_at IS NULL AND lifetime != ?",
            (EXPIRY, _stamp(at), message_id, KEPT),
        )


def db_exchange(conn: sqlite3.Connection, mine: int) -> list[Row]:
    """My message and what the bot said in answer to it."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM bot_messages WHERE (message_id = ? OR exchange = ?) AND gone_at IS NULL ORDER BY message_id", (mine, mine)
    ).fetchall()
    return [_row(row) for row in rows]


def db_next_expiry(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT MIN(expires_at) FROM bot_messages WHERE gone_at IS NULL AND lifetime = ? AND expires_at IS NOT NULL", (EXPIRY,)).fetchone()
    return scheduler.from_db(row[0]) if row and row[0] else None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
async def record(message_id: int | None, channel_id: int | None, *, lifetime: str | None = None, slot: str = "", task: str = "", user_id: int | None = None) -> None:
    """Note a message the bot has just posted, with its lifetime. With none
    declared, a message in the hub lasts the day and one anywhere else is
    not recorded at all. In the hub "kept" is the end of the day. One posted
    while a message of mine in the hub is being handled is its answer."""
    if not enabled() or message_id is None or channel_id is None:
        return
    hub_message = in_hub(channel_id)
    if lifetime is None:
        if not hub_message:
            return
        lifetime = DAY
    if hub_message and lifetime == KEPT:
        lifetime = DAY
    mine = _exchange.get() if hub_message and lifetime == DAY and not slot else None
    await database.run(lambda conn: db_add(conn, message_id, channel_id, lifetime, clock.now(), slot=slot, task=task, user_id=user_id, exchange=mine))
    if lifetime == REPLACED and slot:
        older = await database.run(db_older_in_slot, slot, channel_id, message_id)
        if older:
            # The new one is up: the one it replaces goes now
            await remove(older, "replaced")


async def begin(message_id: int, channel_id: int, user_id: int | None) -> None:
    """A message of mine in the hub is about to be handled: it is recorded, and
    what the bot posts there until it is handled is its answer."""
    if not enabled() or not in_hub(channel_id):
        return
    await database.run(lambda conn: db_add(conn, message_id, channel_id, EXPIRY, clock.now(), user_id=user_id, mine=True))
    _exchange.set(message_id)


async def handled(message_id: int, failed: bool = False) -> None:
    """My message in the hub has been handled. It and the reply go 2 minutes
    from now, unless the reply is a card still waiting to be saved or
    cancelled (then they go with the card). One that failed keeps its ⚠️
    until the morning tidy."""
    if not enabled() or _exchange.get() != message_id:
        return
    _exchange.set(None)
    rows = await database.run(db_exchange, message_id)
    if not rows:
        return
    if failed:
        await database.run(lambda conn: conn.execute("UPDATE bot_messages SET lifetime = ?, expires_at = NULL WHERE message_id = ?", (DAY, message_id)))
        return
    if any(each.waits for each in rows):
        return
    await database.run(db_expire, [each.message_id for each in rows], clock.now() + AFTER_REPLY)
    await book_expiry()


async def card_opened(message_id: int | None) -> None:
    """A confirm card went up: what it answers waits for it to be saved,
    cancelled or to expire."""
    if not enabled() or message_id is None:
        return
    await database.run(lambda conn: conn.execute("UPDATE bot_messages SET waits = 1 WHERE message_id = ? AND gone_at IS NULL", (message_id,)))


async def card_closed(message_id: int | None, saved: bool) -> None:
    """The card was saved, cancelled or expired. My message goes now; the card,
    which on Save has become its confirmation, 2 minutes later like any reply."""
    if not enabled() or message_id is None:
        return
    row = await database.run(db_get, message_id)
    if row is None or not row.waits:
        return
    now = clock.now()
    if row.exchange is not None:
        await database.run(db_expire, [row.exchange], now)
    if saved:
        await database.run(db_expire, [message_id], now + AFTER_REPLY)
    else:
        await database.run(db_gone, message_id, "its card was closed", now)
    await book_expiry()
    scheduler.wake()


async def book_expiry() -> None:
    """One job for the next moment anything expires."""
    due = await database.run(db_next_expiry)
    if due is not None:
        await scheduler.ensure(JOB_TASK, EXPIRY_KIND, due)


# ---------------------------------------------------------------------------
# Removing
# ---------------------------------------------------------------------------
@dataclass
class Tidied:
    removed: int = 0
    kept: int = 0  # pinned or 📌
    left: int = 0  # could not be deleted
    problems: tuple[str, ...] = ()

    def line(self) -> str:
        parts = [f"{self.removed} removed"] + ([f"{self.kept} kept (📌)"] if self.kept else []) + ([f"{self.left} left"] if self.left else [])
        return " · ".join(parts)


def transcript_path(channel_name: str, now: datetime) -> Path:
    safe = "".join(letter if letter.isalnum() or letter in "-_" else "-" for letter in channel_name.lower()).strip("-") or "channel"
    return config.EXPORTS_DIR / f"tidy-{safe}-{days.day_of(now).isoformat()}.txt"


def transcript_lines(messages: list) -> str:
    """What is about to be removed, a message a block: when, who, what it said."""
    blocks = []
    for message in messages:
        when = message.created_at.astimezone(config.TIMEZONE)
        author = getattr(getattr(message, "author", None), "display_name", "?")
        blocks.append(f"[{when:%Y-%m-%d %H:%M}] {author}\n{clearing._said(message)}\n")
    return "\n".join(blocks)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(text + "\n")


async def remove(rows: list[Row], why: str) -> Tidied:
    """Remove these messages, each by the rules: one that is pinned or 📌
    stays (and is not tried again); what they said is written to
    data/exports/ first, and with that not written nothing is deleted; one
    that can't be deleted is tried at the next tidy, three times."""
    done = Tidied()
    if not rows:
        return done
    if not lifecycle.deletes(MessageClass.LIVE):
        return Tidied(problems=("clean-up is switched off (`dev cleanup off`): nothing was removed",))
    client = discord_utils.client
    problems: list[str] = []
    by_channel: dict[int, list[Row]] = {}
    for each in rows:
        by_channel.setdefault(each.channel_id, []).append(each)
    now = clock.now()
    for channel_id, mine in by_channel.items():
        channel = client.get_channel(channel_id) if client is not None else None
        if channel is None:
            problems.append(f"channel {channel_id} can't be found: {len(mine)} left")
            done.left += len(mine)
            continue
        going = []
        for each in mine:
            try:
                message = await channel.fetch_message(each.message_id)
            except discord.NotFound:
                await database.run(db_gone, each.message_id, "already gone", now)
                continue
            except discord.HTTPException as error:
                problems.append(f"#{channel.name}: a message could not be read ({error.status})")
                done.left += 1
                continue
            if protection.is_protected(message):
                await database.run(db_keep, each.message_id, protection.protection(message))
                done.kept += 1
                continue
            going.append((each, message))
        if not going:
            continue
        try:
            _write(transcript_path(channel.name, now), transcript_lines([message for _, message in going]))
        except OSError as error:
            problems.append(f"#{channel.name}: the copy could not be saved ({error}), so nothing was removed there")
            done.left += len(going)
            continue
        for each, message in going:
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as error:
                done.left += 1
                if await database.run(db_tried, each.message_id) >= MAX_TRIES:
                    await database.run(db_keep, each.message_id, f"could not be deleted: {error}")
                    problems.append(f"#{channel.name}: a message could not be deleted after {MAX_TRIES} tries ({error}); it is left now. Delete it by hand, or `reset channel` there")
                continue
            await database.run(db_gone, each.message_id, why, now)
            done.removed += 1
    done.problems = tuple(problems)
    if problems:
        await discord_utils.log_simple(f"{TITLE} · something could not be removed", "\n".join(f"• {problem}" for problem in problems) + "\n-# Nothing was changed in the database: only messages are removed")
    return done


async def tidy(expiry_only: bool = False) -> Tidied:
    """Remove what is due: at any time what has expired; at the tidy also what
    belongs to a day that is over."""
    if not enabled():
        return Tidied()
    due = await database.run(db_due, clock.now(), hub.channel_id(), expiry_only)
    return await remove(due, "expired" if expiry_only else "tidied")


async def tidy_job(job: scheduler.Job) -> None:
    """Scheduler handler: the tidy, a step of the morning routine."""
    done = await tidy()
    scheduler.note(job, done.line() + (f" · {len(done.problems)} problem(s), see #bot-log" if done.problems else ""))
    if done.problems and not done.removed and done.left:
        scheduler.report(job, scheduler.SKIPPED)


async def expiry_job(job: scheduler.Job) -> None:
    """Scheduler handler: something in the hub has had its 2 minutes."""
    done = await tidy(expiry_only=True)
    scheduler.note(job, done.line())
    await book_expiry()


def setup() -> None:
    """Register the handlers, and join the morning routine in front of
    everything, so the hub is clean when the briefing and the checklist
    arrive. Nothing when HUB_TIDY is off."""
    if not enabled():
        return
    scheduler.register_handler(JOB_TASK, TIDY_KIND, tidy_job, "morning tidy")
    scheduler.register_handler(JOB_TASK, EXPIRY_KIND, expiry_job, "tidying the hub", housekeeping=True)
    scheduler.join_routine(hub.MORNING, scheduler.handler_name(JOB_TASK, TIDY_KIND), order=hub.TIDY_ORDER, name=hub.MORNING_NAME)

