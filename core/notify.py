import asyncio
import base64
import logging
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core import attention, cards, clock, config, database, devmode, dms
from core import day as days
from core.cards import Card
from core.config import TIMEZONE

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The notify service: the one way an alert leaves the bot.
#
# A task that has something to tell me now hands it over with its kind
# ("pills.reminder") and the attention item it is about (core/attention.py).
# What happens to it is decided here and nowhere else:
#
#   where     each kind is set to Discord only, ntfy, or both, in one place:
#             KINDS, below. A kind that is not there is Discord only.
#   Discord   the message is posted in its channel; it notifies there unless
#             its kind is ntfy only, or quiet hours hold it.
#   ntfy      a push to my phone, behind NOTIFY_NTFY, to the bot's own topic
#             (NTFY_BOT_TOPIC in .env: a secret, never printed or logged).
#             Tapping it opens the Discord message. With the switch off, or
#             no topic, nothing is pushed and every kind notifies in Discord:
#             an alert is never lost to a setting.
#   wording   what the phone shows is neutral: the kind's fixed title and the
#             one line the task posts first, which names nothing of mine. A
#             line that does name one of my things is not pushed: the title
#             goes by itself, and the log says so.
#   level     an alert stands where its item stands in the one ranking. In
#             quiet hours (QUIET_HOURS, behind QUIET_HOURS_ENABLED) only
#             level 1 notifies: anything else is still posted, without a
#             sound and with no push, and is kept as held back, for the
#             briefing to list in the morning. Asked for again for the same
#             thing (a reminder of a reminder), it is one line there.
#
# Only live pushes: the dev bot never does, so a self-test never reaches my
# phone through here. A push that fails is logged and nothing else: with a
# kind set to both, Discord has notified anyway.
# ---------------------------------------------------------------------------
DISCORD, NTFY, BOTH = "discord", "ntfy", "both"
WHERE = (DISCORD, NTFY, BOTH)


@dataclass(frozen=True)
class Kind:
    """One kind of alert: what the phone shows as its title (fixed, neutral
    words) and where it goes."""

    title: str
    where: str = DISCORD


# The one place: every kind of alert, and where it goes
KINDS: dict[str, Kind] = {
    "pills.reminder": Kind("Reminder", BOTH),
}
UNLISTED = Kind("Alert", DISCORD)

SERVER = "https://ntfy.sh"
TIMEOUT = 8  # seconds a push gets
# How loud a push is, by where its item stands (ntfy: 5 is urgent, 4 high, 3 the default)
PRIORITIES = {attention.LEVEL_PROBLEM: 5, attention.LEVEL_DUE: 4}
PRIORITY = 3
NOT_SAID = "Open Discord to see it."  # the body of a push whose own line could not be shown
KEEP_HELD = timedelta(days=7)  # what was held back is kept this long


def kind(name: str) -> Kind:
    found = KINDS.get(name)
    if found is None or found.where not in WHERE:
        log.warning("Notify: %s is not a kind of alert in core/notify.py: Discord only", name)
        return UNLISTED
    return found


def ready() -> bool:
    """Whether a push can be sent at all: the switch is on, there is a topic,
    and this is live."""
    return bool(config.NOTIFY_NTFY and config.NTFY_BOT_TOPIC and not config.DEV_DATABASE)


def pushes(name: str) -> bool:
    """Whether this kind is pushed to my phone now."""
    return ready() and kind(name).where in (NTFY, BOTH)


def link(channel_id: int | None, message_id: int | None) -> str:
    """Where a message is, as the link Discord opens. "" if it can't be said."""
    return cards.link(channel_id, message_id)


# --- quiet hours ------------------------------------------------------------------------------------------------------
def quiet(now: datetime) -> bool:
    """Whether a moment is in quiet hours, by the NZ clock. Over midnight when
    they start later than they end."""
    start, end = config.QUIET_HOURS
    local = now.astimezone(TIMEZONE).time()
    if start == end:
        return False
    return start <= local < end if start < end else local >= start or local < end


def holds(rank: int | None, now: datetime) -> bool:
    """Whether an alert at this level is held back now: in quiet hours only
    level 1 notifies. Never with the switch off, or while dev mode says to
    ignore quiet hours."""
    if not config.QUIET_HOURS_ENABLED or devmode.quiet_hours_ignored():
        return False
    return rank != attention.LEVEL_PROBLEM and quiet(now)


def window(day: date) -> tuple[datetime, datetime]:
    """The quiet hours that ended on a day: what its briefing calls overnight."""
    start, end = config.QUIET_HOURS
    return (days.at(day, start) if start < end else days.at(day - timedelta(days=1), start)), days.at(day, end)


@dataclass(frozen=True)
class Held:
    """One alert that quiet hours held back."""

    kind: str
    line: str  # the neutral line it was posted as
    at: datetime  # when it was first held
    times: int = 1  # how often it was asked for (a reminder of a reminder is the same one)


def db_hold(conn: sqlite3.Connection, user_id: int, name: str, key: str, line: str, rank: int, channel_id: int, message_id: int, now: datetime) -> None:
    conn.execute("DELETE FROM held_alerts WHERE held_at < ?", ((now - KEEP_HELD).isoformat(),))
    conn.execute(
        """
        INSERT INTO held_alerts (user_id, kind, key, line, level, channel_id, message_id, held_at, times)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(user_id, kind, key) DO UPDATE SET times = times + 1, channel_id = excluded.channel_id, message_id = excluded.message_id
        """,
        (user_id, name, key, line, rank, channel_id, message_id, now.isoformat()),
    )


def db_held(conn: sqlite3.Connection, user_id: int, since: datetime, until: datetime) -> list[Held]:
    rows = conn.execute(
        "SELECT kind, line, held_at, times FROM held_alerts WHERE user_id = ? AND held_at >= ? AND held_at < ? ORDER BY held_at, id",
        (user_id, since.isoformat(), until.isoformat()),
    ).fetchall()
    return [Held(name, line, datetime.fromisoformat(at), times) for name, line, at, times in rows]


async def held_overnight(user_id: int, day: date) -> list[Held]:
    """What quiet hours held back in the night that ended on this day, the
    earliest first. Read only."""
    since, until = window(day)
    return await database.run(db_held, user_id, since, until)


# --- the push ---------------------------------------------------------------------------------------------------------
def neutral(line: str, private: tuple[str, ...]) -> bool:
    """Whether a line may be shown on a lock screen: it names none of these."""
    return not dms.names_in(line, {name: name for name in private})


def _request(topic: str, title: str, body: str, click: str, priority: int) -> urllib.request.Request:
    headers = {
        # A header holds ASCII only: the title goes as RFC 2047, which ntfy reads
        "Title": "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?=",
        "Priority": str(priority),
        "Content-Type": "text/plain; charset=utf-8",
    }
    if click:
        headers["Click"] = click  # tapping the push opens the Discord message
    return urllib.request.Request(f"{SERVER}/{topic}", data=body.encode("utf-8"), method="POST", headers=headers)


def _deliver(request: urllib.request.Request) -> None:
    urllib.request.urlopen(request, timeout=TIMEOUT).close()


async def push(name: str, line: str, click: str = "", rank: int | None = None, private: tuple[str, ...] = ()) -> bool:
    """Push one alert to my phone. True if it went. Never raises, and never
    says the topic: what goes wrong is logged by its kind only."""
    if not pushes(name):
        return False
    said = line.strip().split("\n", 1)[0]
    if not said or not neutral(said, private):
        if said:
            log.error("Notify: the line of %s names one of the user's things: pushed with its title only", name)
        said = NOT_SAID
    try:
        # Off the event loop: a slow ntfy never holds the bot up
        await asyncio.to_thread(_deliver, _request(config.NTFY_BOT_TOPIC, kind(name).title, said, click, PRIORITIES.get(rank, PRIORITY)))
    except Exception as error:
        log.warning("Notify: %s could not be pushed to ntfy (%s)", name, type(error).__name__)
        return False
    log.info("Notify: %s pushed to ntfy (level %s)", name, rank)
    return True


_pushing: set[asyncio.Task] = set()


def _push_later(*args) -> None:
    sending = asyncio.create_task(push(*args))
    _pushing.add(sending)
    sending.add_done_callback(_pushing.discard)


async def settle() -> None:
    """Wait for the pushes on their way (a test, a shutdown)."""
    if _pushing:
        await asyncio.gather(*list(_pushing), return_exceptions=True)


# --- the one way out --------------------------------------------------------------------------------------------------
async def post(
    name: str, channel_id: int, card: Card, *, user_id: int, item: attention.Item, key: str = "", private: tuple[str, ...] = ()
) -> int | None:
    """Post an alert of this kind in a channel and tell me about it as its
    kind and its level say. `card` is what is posted first, and its first
    line is what a phone shows: the task writes the rest in after. `key` is
    what it is about (a dose's id), so that asked for again it is the same
    alert; `private` the names its line must not show. Returns the message's
    id, or None if there is nowhere to post it."""
    now = clock.now()
    # An alert is a thing whose time has come: one the ranking would not place (its day is over) stands as due
    rank = attention.level(item, now) or attention.LEVEL_DUE
    held = holds(rank, now)
    by_push = pushes(name) and not held
    silent = held or (by_push and kind(name).where == NTFY)
    message_id = await cards.send(channel_id, card, silent=silent)
    if message_id is None:
        return None
    if held:
        await database.run(db_hold, user_id, name, key or str(message_id), card.text.split("\n", 1)[0], rank, channel_id, message_id, now)
        log.info("Notify: %s held back by quiet hours (level %s): posted without a sound, for the briefing to list", name, rank)
    elif by_push:
        _push_later(name, card.text, link(channel_id, message_id), rank, private)
    return message_id
