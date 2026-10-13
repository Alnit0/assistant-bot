import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import discord

from core import cards, channels, clock, database, design, discord_utils
from core.cards import Button, Card
from core.config import CHANNELS, TIMEZONE
from core.timeinput import format_time

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# What I said while the bot was off.
#
# Discord never hands over what was sent while the bot was not connected, so
# on start it looks: every channel named in the settings (but #commands, where
# only the bot posts) is read back to the last moment the bot knows it was
# running, and each message of mine it has not seen gets a card under it:
#
#     📭 I was offline when you sent this · 3:12 pm
#     > took zinc
#     [Handle it now] [↩️ Ignore]
#
# Nothing is acted on without the press: by the time the bot is back, "took
# zinc" may no longer be true as written. Handle it now takes the message as
# if it had just been sent; Ignore removes the card and nothing else.
#
# "The last moment it was running" is a note it leaves itself twice a minute
# (`bot_alive`), in real time, never the dev clock's. A message gets one card
# ever (`missed_messages`), so a second restart before the press asks nothing
# twice. A first start, with no note yet, has nothing to go on and reads
# nothing.
# ---------------------------------------------------------------------------
TASK = "missed"
HANDLE, IGNORE = "handle", "ignore"
ASKED, HANDLED, IGNORED, GONE = "asked", "handled", "ignored", "gone"
EVERY_SECONDS = 30  # how often the bot notes that it is running
SLACK = timedelta(seconds=EVERY_SECONDS + 5)  # a message sent since the last note may have been seen: looked up, not assumed
MAX_CARDS = 20  # more than this after one stop and only the latest get a card; the rest are counted
PER_CHANNEL = 100  # how far back one channel is read
QUOTE = 300
HEADING = "📭 **I was offline when you sent this**"

# main.py's: who sent a message, if it is one of mine the bot acts on; and taking it as if it had just arrived
Sender = Callable[[discord.Message], Awaitable[object | None]]
Take = Callable[[discord.Message, object], Awaitable[None]]
_sender: Sender | None = None
_take: Take | None = None
_seen: set[int] = set()  # what arrived the usual way since this start
_ticker: asyncio.Task | None = None


# --- what is kept ----------------------------------------------------------------------------------------------------
def db_alive(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT at FROM bot_alive WHERE id = 1").fetchone()
    return datetime.fromisoformat(row[0]) if row else None


def db_note_alive(conn: sqlite3.Connection, now: datetime) -> None:
    conn.execute("INSERT INTO bot_alive (id, at) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET at = excluded.at", (now.isoformat(),))


def db_known(conn: sqlite3.Connection, message_ids: list[int]) -> set[int]:
    """Those of these messages the bot has dealt with or asked about already."""
    if not message_ids:
        return set()
    marks = ", ".join("?" for _ in message_ids)
    asked = conn.execute(f"SELECT message_id FROM missed_messages WHERE message_id IN ({marks})", message_ids).fetchall()
    logged = conn.execute(f"SELECT discord_message_id FROM message_log WHERE discord_message_id IN ({marks})", message_ids).fetchall()
    return {row[0] for row in asked} | {row[0] for row in logged}


def db_add(conn: sqlite3.Connection, message_id: int, channel_id: int, user_id: int, sent_at: datetime, now: datetime) -> bool:
    """Note a message as asked about. False if it already was: it gets no second card."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO missed_messages (message_id, channel_id, user_id, state, sent_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, channel_id, user_id, ASKED, sent_at.isoformat(), now.isoformat()),
    )
    return cursor.rowcount == 1


def db_set_card(conn: sqlite3.Connection, message_id: int, card_message_id: int | None) -> None:
    conn.execute("UPDATE missed_messages SET card_message_id = ? WHERE message_id = ?", (card_message_id, message_id))


def db_close(conn: sqlite3.Connection, message_id: int, state: str, now: datetime) -> bool:
    """Answer the card. True only for the press that does it: a second press, or one after a restart, finds it closed."""
    cursor = conn.execute(
        "UPDATE missed_messages SET state = ?, closed_at = ? WHERE message_id = ? AND state = ?", (state, now.isoformat(), message_id, ASKED)
    )
    return cursor.rowcount == 1


def db_owner(conn: sqlite3.Connection, message_id: int) -> int | None:
    row = conn.execute("SELECT user_id FROM missed_messages WHERE message_id = ?", (message_id,)).fetchone()
    return row[0] if row else None


# --- pure ------------------------------------------------------------------------------------------------------------
def quote(text: str, files: int = 0) -> str:
    """The message as the card shows it: its start, quoted, and how many files came with it."""
    text = " ".join(text.split())
    if len(text) > QUOTE:
        text = text[: QUOTE - 1] + "…"
    with_files = f"📎 {files} file{'' if files == 1 else 's'}" if files else ""
    return "\n".join(f"> {line}" for line in (text, with_files) if line) or "> (no text)"


def card(message_id: int, text: str, sent_at: datetime, url: str = "", files: int = 0) -> Card:
    when = format_time(sent_at.astimezone(TIMEZONE).time())
    day = f"{sent_at.astimezone(TIMEZONE):%a %d %b}, " if sent_at.astimezone(TIMEZONE).date() != clock.real_now().astimezone(TIMEZONE).date() else ""
    link = f" · [the message]({url})" if url else ""
    which = str(message_id)
    row = (Button("Handle it now", TASK, HANDLE, which, emoji="▶️"), cards.cancel(TASK, IGNORE, which, label="Ignore"))
    # The same card drawn (docs/DESIGN.md, with CARDS_V2 on): a decision, in one box
    drawn = design.decision(
        "📭 I was offline when you sent this", [quote(text, files)], context=f"{day}{when}{link}", question="Handle it now?", row=row,
    )
    return Card(f"{HEADING} · {day}`{when}`{link}\n{quote(text, files)}", (row,), drawn)


def to_read(names: dict[str, int]) -> list[int]:
    """The channels to read back: every one named, each once, but #commands."""
    return sorted({channel_id for name, channel_id in names.items() if name != "commands"})


def unanswered(found: list, since: datetime, known: set[int], seen: set[int]) -> list:
    """Of the messages of mine found in the channels, the ones sent while the
    bot was off and never dealt with, oldest first."""
    fresh = [message for message in found if message.created_at > since and message.id not in known and message.id not in seen]
    return sorted(fresh, key=lambda message: message.created_at)


def latest(missed: list, limit: int = MAX_CARDS) -> tuple[list, int]:
    """(the ones that get a card, how many older ones do not)."""
    return missed[-limit:], max(0, len(missed) - limit)


def more_line(left_out: int) -> str:
    return f"📭 {left_out} earlier message{'' if left_out == 1 else 's'} of yours from while I was offline {'has' if left_out == 1 else 'have'} no card: scroll up, and send again what still matters."


# --- on start --------------------------------------------------------------------------------------------------------
def saw(message_id: int) -> None:
    """A message arrived the usual way: it was not missed, whatever the clock says."""
    _seen.add(message_id)


async def look() -> int:
    """Read back what I said while the bot was off, and ask about each. Returns
    how many cards were posted. Never raises: a start is not held up by this."""
    try:
        return await _look()
    except Exception:
        log.exception("Could not read back what was said while the bot was off")
        return 0


async def _look() -> int:
    now = clock.real_now()
    last = await database.run(db_alive)
    await database.run(db_note_alive, now)
    if last is None:
        log.info("Missed messages: no note of when the bot last ran (a first start): nothing is read back")
        return 0
    if _sender is None:
        return 0
    since = last - SLACK
    found = []
    by_id = {channel.id: channel for channel in channels.named()}
    for channel_id in to_read(CHANNELS):
        channel = by_id.get(channel_id)
        if channel is None:
            continue
        try:
            async for message in channel.history(limit=PER_CHANNEL, after=since, oldest_first=True):
                if await _sender(message) is not None:
                    found.append(message)
        except discord.HTTPException as error:
            log.warning("Missed messages: #%s could not be read back: %s", getattr(channel, "name", channel_id), error)
    known = await database.run(db_known, [message.id for message in found])
    missed, left_out = latest(unanswered(found, since, known, _seen))
    posted = 0
    for message in missed:
        user = await _sender(message)
        if user is None or not await database.run(db_add, message.id, message.channel.id, user.id, message.created_at, now):
            continue
        sent = await cards.send(message.channel.id, card(message.id, message.content, message.created_at, message.jump_url, len(message.attachments)))
        await database.run(db_set_card, message.id, sent)
        posted += 1
    if left_out:
        client = discord_utils.client
        inbox = client.get_channel(CHANNELS.get("inbox")) if client is not None else None
        if inbox is not None:
            await inbox.send(more_line(left_out))
    off_for = max(0, int((now - last).total_seconds()))
    log.info(
        "Missed messages: off for about %d min since %s; %d of mine found, %d already dealt with, %d card%s posted%s",
        off_for // 60, last.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"), len(found), len(found) - len(missed) - left_out,
        posted, "" if posted == 1 else "s", f", {left_out} older left without one" if left_out else "",
    )
    return posted


async def _keep_noting() -> None:
    while True:
        await asyncio.sleep(EVERY_SECONDS)
        try:
            await database.run(db_note_alive, clock.real_now())
        except Exception as error:
            log.warning("Could not note that the bot is running: %s", error)


def start() -> None:
    """Begin noting that the bot is running. Safe to call again (on_ready fires after reconnects)."""
    global _ticker
    if _ticker is None or _ticker.done():
        _ticker = asyncio.create_task(_keep_noting(), name="missed: alive")


# --- the card's buttons ----------------------------------------------------------------------------------------------
async def on_handle(press: cards.Press) -> str | None:
    message_id = int(press.arg) if press.arg.isdigit() else 0
    if await database.run(db_owner, message_id) != press.user.id or not await database.run(db_close, message_id, HANDLED, clock.real_now()):
        await press.remove()  # answered already (a second press, or the other button first)
        return f"the card for message {press.arg} was already answered"
    client = discord_utils.client
    channel = client.get_channel(press.channel_id) if client is not None else None
    try:
        message = await channel.fetch_message(message_id) if channel is not None else None
    except discord.HTTPException:
        message = None
    user = await _sender(message) if message is not None and _sender is not None else None
    if message is None or user is None or _take is None:
        await press.remove()
        await press.say("That message has gone, so there is nothing to handle.")
        return f"message {press.arg} has gone"
    # The card goes first: that answers the press, and the reply to the message takes its place
    await press.remove()
    await _take(message, user)
    return f"handled message {press.arg}, sent while the bot was off"


async def on_ignore(press: cards.Press) -> str | None:
    message_id = int(press.arg) if press.arg.isdigit() else 0
    if await database.run(db_owner, message_id) == press.user.id:
        await database.run(db_close, message_id, IGNORED, clock.real_now())
    await press.remove()
    return f"ignored message {press.arg}, sent while the bot was off"


def setup(sender: Sender, take: Take) -> None:
    global _sender, _take
    _sender, _take = sender, take
    cards.register(TASK, HANDLE, on_handle)
    cards.register(TASK, IGNORE, on_ignore)
