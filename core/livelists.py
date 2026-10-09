import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import cards, database, live
from core.cards import Card
from core.lifecycle import MessageClass
from core.scheduler import from_db, to_db, utc_now

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Live lists: a list shown on request stays true.
#
# When a task shows a list because it was asked ("what do I need to buy?",
# `pills`), that message is Live: whenever the data behind it changes, by any
# route, it is rewritten in place. Only the latest copy is Live. Asking again
# posts a fresh one, which takes over; an older copy further up is left as it
# was, and is no longer kept up to date.
#
# A task uses it in two places:
#   - where it shows the list: return actions.LiveReply(key, text) from a
#     direct action (core/conversation.py posts it and records it here), or
#     call show() itself for a list posted some other way (a typed word)
#   - where the data changes: changed(user_id, key, render), with `render`
#     giving the list as it is now. The edit happens in the background, once
#     however many changes asked for it (core/live.py)
#
# A list on screen is also context, as an open card is: while it is the last
# thing the bot said in the channel and under five minutes old, a short
# message that follows is taken to be for that list's task (sticks).
#
# `key` names the list within the bot ("shopping", "pills:today"). One row
# per user and key (live_lists), so it survives a restart. No discord.py.
# ---------------------------------------------------------------------------
Render = Callable[[], Awaitable[Card | str]]

STICKY_MINUTES = 5  # as for a confirm card
SHORT_WORDS = 8  # a follow-up to a list is short: "add milk", "and two more eggs please"


@dataclass(frozen=True)
class Placed:
    user_id: int
    key: str
    channel_id: int
    message_id: int
    task: str = ""  # the task (router entry) the list belongs to
    shown_at: datetime | None = None


_COLUMNS = "user_id, key, channel_id, message_id, task, shown_at"


def _placed(row: tuple) -> Placed:
    return Placed(row[0], row[1], row[2], row[3], row[4] or "", from_db(row[5]) if row[5] else None)


def sticks(found: Placed, text: str, now: datetime, latest_bot_message_id: int | None) -> bool:
    """Whether a message is taken as being for this list's task without asking
    the router: the list is the last thing the bot said in the channel, it was
    shown in the last few minutes, and the message is a short one."""
    if not found.task or found.shown_at is None or latest_bot_message_id != found.message_id:
        return False
    fresh = now - found.shown_at <= timedelta(minutes=STICKY_MINUTES)
    return fresh and 0 < len(text.split()) <= SHORT_WORDS


def _as_card(shown: Card | str) -> Card:
    return shown if isinstance(shown, Card) else Card(shown)


def db_get(conn: sqlite3.Connection, user_id: int, key: str) -> Placed | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM live_lists WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return _placed(row) if row else None


def db_set(
    conn: sqlite3.Connection, user_id: int, key: str, channel_id: int, message_id: int, task: str = "",
    now: datetime | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO live_lists (user_id, key, channel_id, message_id, task, shown_at) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            channel_id = excluded.channel_id, message_id = excluded.message_id,
            task = excluded.task, shown_at = excluded.shown_at
        """,
        (user_id, key, channel_id, message_id, task, to_db(now or utc_now())),
    )


def db_by_message(conn: sqlite3.Connection, message_id: int) -> Placed | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM live_lists WHERE message_id = ?", (message_id,)).fetchone()
    return _placed(row) if row else None


async def by_message(message_id: int | None) -> Placed | None:
    """The list whose Live copy this message is, if it is one."""
    return await database.run(db_by_message, message_id) if message_id is not None else None


async def placed(user_id: int, key: str, channel_id: int, message_id: int | None, task: str = "") -> None:
    """Note that this message is now the latest copy of the list: the Live one.
    `task` is the task the list belongs to, for a message that follows it."""
    if message_id is not None:
        await database.run(db_set, user_id, key, channel_id, message_id, task)


async def show(
    user_id: int, key: str, channel_id: int, shown: Card | str, *, silent: bool = False, task: str = ""
) -> int | None:
    """Post a list and make it the Live copy. Returns the message's id."""
    message_id = await cards.send(channel_id, _as_card(shown), silent=silent)
    await placed(user_id, key, channel_id, message_id, task)
    return message_id


async def refresh(user_id: int, key: str, render: Render) -> bool:
    """Rewrite the Live copy now. False if there is none, or it has gone."""
    found = await database.run(db_get, user_id, key)
    if found is None:
        return False
    return await cards.edit(found.channel_id, found.message_id, _as_card(await render()))


def changed(user_id: int, key: str, render: Render) -> None:
    """The data behind a list has changed: bring its Live copy up to date, in
    the background. Does nothing if the list was never shown."""
    live.schedule(("list", user_id, key), lambda: refresh(user_id, key, render))


async def message_class(message_id: int) -> MessageClass | None:
    """The latest copy of a list is Live."""
    return MessageClass.LIVE if await database.run(db_by_message, message_id) is not None else None
