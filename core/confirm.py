import json
import logging
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from core import actions, cards, database, lifecycle, llm, scheduler
from core.actions import Entry, Proposal, Request
from core.cards import Button, Card
from core.discord_utils import log_error
from core.errors import UserError
from core.lifecycle import MessageClass
from core.scheduler import from_db, to_db, utc_now

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Confirm cards: guess, show, confirm. The standard for anything that changes
# what a task has set up.
#
#     💊 Pills · new
#     **G** · 10× daily, fixed times every 2h
#     First `8:00 am` ❓ · last `12:00 am`
#     ⚠️ Only 9 fit before midnight
#     [✅ Save] [✖️ Cancel]
#     -# or tell me what to change
#
# The card says what would be saved, with every guess flagged and every
# problem shown with its fix applied. Save applies exactly the data on the
# card; nothing is saved before it. Saying what to change makes a new card
# and takes this one away. Left alone for 30 minutes it goes, with nothing
# saved.
#
# A card is a row (confirm_cards), not memory: it survives a restart, and so
# do its buttons (core/cards.py). The same table holds the question asked on
# a tie between tasks ("which is this for?").
#
# No discord.py here. Deciding what to do with a message is
# core/conversation.py's job; this file shows, stores, saves and expires.
# ---------------------------------------------------------------------------
CARDS = "confirm"  # the name these cards' buttons go by in core/cards.py
JOB_TASK, JOB_KIND = "core", "confirm_expire"
EXPIRY_MINUTES = 30
STICKY_MINUTES = 5  # how long a plain message is taken as being about the card

CARD, TIE = "card", "tie"
OPEN, SAVED, CANCELLED, EXPIRED, REPLACED, PICKED = "open", "saved", "cancelled", "expired", "replaced", "picked"
FAILED = "failed"  # Save was pressed, and what was read back from the database did not match the card

FOOTER = "-# or tell me what to change"
LAPSED = "⌛ That card has gone and nothing was saved. Say it again to start over."


@dataclass(frozen=True)
class Stored:
    """A card as it is kept."""

    id: int
    user_id: int
    channel_id: int
    message_id: int | None
    kind: str  # CARD or TIE
    task: str  # the entry it belongs to (empty for a tie)
    action: str
    data: dict  # what Save applies; for a tie, {"tasks": [...]}
    guessed: tuple[str, ...]
    said: str  # everything the user said that led to it, oldest first, one message a line
    status: str
    job_id: int | None
    created_at: datetime
    # The data of the card this one replaced, for the same action: what it was
    # before the user's last change. None for a first card
    previous: dict | None = None

    @property
    def is_open(self) -> bool:
        return self.status == OPEN


# ---------------------------------------------------------------------------
# What a card looks like (pure)
# ---------------------------------------------------------------------------
def render(entry: Entry, proposal: Proposal, card_id: int) -> Card:
    """The card for a proposal: what kind of change, every interpretation,
    the warnings, and the buttons."""
    proposal = _checked_kind(proposal)
    lines = [f"{entry.icon} {entry.title} · {proposal.kind}", *proposal.lines]
    lines += [f"{actions.WARNING_MARK} {warning}" for warning in proposal.warnings]
    lines.append(FOOTER)
    if proposal.destructive:
        confirm = Button(proposal.confirm_label, CARDS, "save", str(card_id), emoji="🗑️", style=cards.DANGER)
    else:
        confirm = Button(proposal.confirm_label, CARDS, "save", str(card_id), emoji="✅", style=cards.SUCCESS)
    return Card("\n".join(lines), ((confirm, Button("Cancel", CARDS, "cancel", str(card_id), emoji="✖️")),))


def render_tie(entries: list[Entry], card_id: int, said: str) -> Card:
    """The question on a genuine tie: one button for each task it could be for."""
    row = tuple(
        Button(entry.title, CARDS, "pick", f"{card_id}:{entry.name}", emoji=entry.icon, style=cards.PRIMARY)
        for entry in entries
    )
    return Card(f"Which is “{cards.truncate_label(said, 100)}” for?", (row + (Button("Neither", CARDS, "cancel", str(card_id), emoji="✖️"),),))


def sticks(
    card: Stored, now: datetime, *, replied_to: int | None = None, latest_bot_message_id: int | None = None
) -> bool:
    """Whether a message is taken as being about this card without asking the
    router: it is a reply to the card, or the card is the last thing the bot
    said in the channel and is still fresh."""
    if not card.is_open or card.kind != CARD or card.message_id is None:
        return False
    if replied_to is not None:
        return replied_to == card.message_id
    fresh = now - card.created_at <= timedelta(minutes=STICKY_MINUTES)
    return fresh and latest_bot_message_id == card.message_id


_NO = r"(?:no|nope|nah|not that|not that one|wrong|wrong one|wrong list|i meant|i mean|sorry)"
_FOR = r"(?:i meant|i mean|it'?s for|it is for|for|to|on|in|put it on|put it in|make it)"


def redirect(text: str, entries: list[Entry], current: str) -> Entry | None:
    """The task a bare redirect names: "no, shopping", "nope, the packing list",
    "I meant shopping", "shopping instead". None for anything else, including
    the task the card is already for.

    Only the exact shape counts, and only the words of the redirect are
    looked at: it says where the request on the card belongs, and is never
    part of that request. Looser wording is left to the router and extraction.
    """
    said = re.sub(r"[\s,.;:!-]+", " ", text.strip().lower()).strip()
    for entry in entries:
        if entry.name == current:
            continue
        name = rf"(?:the |my )?{re.escape(entry.name)}(?: list| one| task)?"
        leading = re.fullmatch(rf"{_NO} (?:{_FOR} )?{name}(?: instead| please)?", said)
        trailing = re.fullmatch(rf"(?:{_FOR} )?{name} instead", said)
        if leading or trailing:
            return entry
    return None


_CORRECTION = re.compile(rf"\s*{_NO}\b[\s,.;:!-]+\S", re.IGNORECASE)


def is_correction(text: str) -> bool:
    """Whether a message says the last change was wrong and what was meant
    instead: "No, 2 bread rolls", "nope, the eggs", "sorry, I meant jam". A
    bare "no" says nothing was meant instead, and is not one."""
    return bool(_CORRECTION.match(text))


def on_screen(card: Stored) -> str:
    """An open card in a line, for the router to read."""
    entry = actions.entry(card.task)
    name = entry.title if entry else card.task
    said = " | ".join(line for line in card.said.split("\n") if line.strip())
    return f"a {name} card ({card.action}) from the user saying: {said}"


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, channel_id, message_id, kind, task, action, data, guessed, said, status, job_id, created_at, previous"


def _stored(row: tuple) -> Stored:
    return Stored(
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], json.loads(row[7]),
        tuple(json.loads(row[8])), row[9], row[10], row[11], from_db(row[12]),
        json.loads(row[13]) if row[13] else None,
    )


def db_add(
    conn: sqlite3.Connection, user_id: int, channel_id: int, kind: str, task: str, action: str,
    data: dict, guessed, said: str, now: datetime | None = None, previous: dict | None = None,
) -> Stored:
    cursor = conn.execute(
        """
        INSERT INTO confirm_cards
            (user_id, channel_id, kind, task, action, data, guessed, said, status, created_at, previous)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, channel_id, kind, task, action, json.dumps(data, ensure_ascii=False),
            json.dumps(sorted(guessed)), said, OPEN, to_db(now or utc_now()),
            json.dumps(previous, ensure_ascii=False) if previous is not None else None,
        ),
    )
    return db_get(conn, cursor.lastrowid)


def db_get(conn: sqlite3.Connection, card_id: int) -> Stored | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM confirm_cards WHERE id = ?", (card_id,)).fetchone()
    return _stored(row) if row else None


def db_latest_open(conn: sqlite3.Connection, user_id: int, channel_id: int) -> Stored | None:
    """The user's newest open card in a channel (not a tie question)."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM confirm_cards WHERE user_id = ? AND channel_id = ? AND kind = ? AND status = ? "
        "ORDER BY id DESC LIMIT 1",
        (user_id, channel_id, CARD, OPEN),
    ).fetchone()
    return _stored(row) if row else None


def db_by_message(conn: sqlite3.Connection, message_id: int) -> Stored | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM confirm_cards WHERE message_id = ?", (message_id,)).fetchone()
    return _stored(row) if row else None


def db_placed(conn: sqlite3.Connection, card_id: int, message_id: int | None, job_id: int | None) -> None:
    conn.execute("UPDATE confirm_cards SET message_id = ?, job_id = ? WHERE id = ?", (message_id, job_id, card_id))


def db_close(conn: sqlite3.Connection, card_id: int, status: str, now: datetime | None = None) -> bool:
    """Close an open card. False if it wasn't open any more: two presses, or a
    press racing the expiry, close it once."""
    cursor = conn.execute(
        "UPDATE confirm_cards SET status = ?, closed_at = ? WHERE id = ? AND status = ?",
        (status, to_db(now or utc_now()), card_id, OPEN),
    )
    return cursor.rowcount == 1


# ---------------------------------------------------------------------------
# Showing, replacing and expiring
# ---------------------------------------------------------------------------
async def latest_open(user_id: int, channel_id: int) -> Stored | None:
    return await database.run(db_latest_open, user_id, channel_id)


async def _place(card: Stored, shown: Card) -> Stored:
    """Post a stored card and book its expiry."""
    message_id = await cards.send(card.channel_id, shown)
    job_id = await scheduler.add_job(
        JOB_TASK, JOB_KIND, utc_now() + timedelta(minutes=EXPIRY_MINUTES), {"card": card.id}, card.user_id
    )
    await database.run(db_placed, card.id, message_id, job_id)
    return await database.run(db_get, card.id)


async def _take_away(card: Stored, status: str) -> None:
    """Close a card and remove its message: something newer has taken its place,
    or the user said no."""
    if await database.run(db_close, card.id, status):
        await scheduler.cancel_job(card.job_id)
        if card.message_id is not None:
            await cards.delete(card.channel_id, card.message_id)


def said_so_far(replaces: Stored | None, text: str, undone: bool = False) -> str:
    """Everything said about a card, one message a line: what the card it
    replaces came from, then this message. With `undone`, the last message
    about the old card was a mistake being corrected, and is left out."""
    if replaces is None:
        return text
    lines = [line for line in replaces.said.split("\n") if line.strip()]
    if undone and len(lines) > 1:
        lines = lines[:-1]
    if replaces.task and text and text not in lines[-1:]:
        lines.append(text)
    return "\n".join(lines) or text


def _checked_kind(proposal: Proposal) -> Proposal:
    """A card's kind is one of the three every task uses. Anything else is a
    mistake in the task's code: it is logged and shown as a change."""
    if proposal.kind in actions.KINDS:
        return proposal
    log.error("A card was given the kind %r; the kinds are %s", proposal.kind, ", ".join(actions.KINDS))
    return replace(proposal, kind="change")


async def show(
    request: Request, entry: Entry, action_name: str, proposal: Proposal, guessed, replaces: Stored | None = None,
    *, moved: bool = False, undone: bool = False,
) -> Stored:
    """Post a confirm card for a proposal. `replaces` is the card this one
    corrects: it is deleted, so there is only ever the latest to accept.

    The new card remembers what the old one held, so that a "No, …" straight
    after can take this change back. With `moved` the old card belonged to
    another task ("no, packing"): what was said stays as it was. With `undone`
    this card corrects a mistaken change, which is forgotten."""
    same_action = replaces is not None and not moved and replaces.task == entry.name and replaces.action == action_name
    if replaces is None:
        said = request.text
    elif moved:
        said = replaces.said
    else:
        said = said_so_far(replaces, request.text, undone)
    # After a correction the card goes back to what the mistake was made on, not to the mistake
    previous = (replaces.previous if undone else replaces.data) if same_action else None
    card = await database.run(
        db_add, request.user.id, request.channel_id, CARD, entry.name, action_name,
        proposal.data, guessed, said, None, previous,
    )
    # Only the data is kept: Save applies that and nothing else
    placed = await _place(card, render(entry, proposal, card.id))
    if replaces is not None:
        await _take_away(replaces, REPLACED)
    return placed


async def ask_which(request: Request, entries: list[Entry]) -> Stored:
    """Post the question for a tie between tasks."""
    card = await database.run(
        db_add, request.user.id, request.channel_id, TIE, "", "", {"tasks": [entry.name for entry in entries]}, (), request.text
    )
    return await _place(card, render_tie(entries, card.id, request.text))


async def expired(job: scheduler.Job) -> None:
    """Scheduler handler: a card nobody answered goes, and nothing is saved."""
    card = await database.run(db_get, job.payload.get("card", 0))
    if card is None or card.job_id != job.id or not await database.run(db_close, card.id, EXPIRED):
        return
    if card.message_id is None:
        return
    if lifecycle.deletes(MessageClass.TRANSIENT):
        await cards.delete(card.channel_id, card.message_id)
    else:
        await cards.edit(card.channel_id, card.message_id, Card("⌛ Expired: nothing was saved."))


# ---------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------
async def _open_card(press: cards.Press, card_id: str) -> Stored | None:
    card = await database.run(db_get, int(card_id)) if card_id.isdigit() else None
    if card is None or card.user_id != press.user.id or not card.is_open:
        await press.update(Card(LAPSED))
        return None
    return card


async def on_save(press: cards.Press) -> str | None:
    """Save: apply exactly what the card showed, then say so in the task's own words."""
    card = await _open_card(press, press.arg)
    if card is None:
        return "card had gone"
    entry = actions.entry(card.task)
    action = entry.action(card.action) if entry else None
    if action is None or action.apply is None:
        await press.update(Card("⌛ That can't be saved any more: what it belonged to has gone."))
        await database.run(db_close, card.id, EXPIRED)
        return f"no action {card.task}/{card.action}"
    # A UserError here (the name was taken meanwhile) is shown to the presser and the card stays
    request = Request(press.user, card.channel_id)
    said = await action.apply(request, card.data)
    # Nothing is confirmed on the strength of `apply` having returned: the change is
    # read back from the database first, and "saved" is only said if it is there
    wrong = await action.verify(request, card.data) if action.verify is not None else ""
    closed = await database.run(db_close, card.id, FAILED if wrong else SAVED)
    await scheduler.cancel_job(card.job_id)
    if wrong:
        log.error("Save of %s/%s did not take: %s (card %s, data %s)", card.task, card.action, wrong, card.id, card.data)
        await log_error(f"Save did not take: {card.action}", wrong, json.dumps(card.data, ensure_ascii=False))
        said = f"⚠️ That didn't save: {wrong}. Nothing is confirmed; please check and ask again."
        await press.update(Card(said))
        llm.remember(card.channel_id, "(pressed the card's button)", said)
        return f"NOT saved {card.task}/{card.action}: {wrong}"
    if not closed:
        raise UserError("That card was closed a moment ago.")
    await press.update(Card(said))
    # What a press did is part of the conversation: without it, whatever is asked
    # next is answered as if the card were still waiting
    llm.remember(card.channel_id, "(pressed the card's button)", said)
    return f"saved {card.task}/{card.action}: {said}"


async def on_cancel(press: cards.Press) -> str | None:
    card = await database.run(db_get, int(press.arg)) if press.arg.isdigit() else None
    if card is not None and card.user_id == press.user.id and await database.run(db_close, card.id, CANCELLED):
        await scheduler.cancel_job(card.job_id)
        llm.remember(card.channel_id, "(pressed Cancel on the card)", "Cancelled: nothing was changed.")
    await press.remove()
    return f"cancelled card {press.arg}"


def setup() -> None:
    """Register the buttons and the expiry. Before the bot connects."""
    cards.register(CARDS, "save", on_save)
    cards.register(CARDS, "cancel", on_cancel)
    scheduler.register_handler(JOB_TASK, JOB_KIND, expired)


async def message_class(message_id: int) -> MessageClass | None:
    """An open card is Live: replaced or saved in place, and gone if left."""
    card = await database.run(db_by_message, message_id)
    return MessageClass.LIVE if card is not None and card.is_open else None
