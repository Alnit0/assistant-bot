import json
import logging
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from core import actions, cards, database, design, lifecycle, llm, messages, restart, scheduler, users
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
#     [✅ Save] [↩️ Cancel]
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
ASKING = "-# or type your answer"  # under a card that asks a question
ANSWER_FIRST = "Answer the question on the card first."
LAPSED = "⌛ That card has gone and nothing was saved. Say it again to start over."
# Under the confirmation of a Save that was cut off by a restart, once the change has been read back
CHECKED = "-# checked after a restart"
# The confirmation itself is the task's own, kept when the change was applied. If the bot
# stopped before even that was kept, the change is there and its words are not
SAVED_PLAIN = "✅ Saved."


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
    # What Save said, kept as soon as the change was applied (None until then)
    confirmation: str | None = None
    # The question the card is asking, if any: {"text": …, "choices": [{"label", "data", "settles"}]}
    question: dict | None = None

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
    heading = f"{entry.icon} {entry.title} · {proposal.kind}"
    lines = [heading, *proposal.lines]
    lines += [f"{actions.WARNING_MARK} {warning}" for warning in proposal.warnings]
    if proposal.question is not None:
        # Everything that was understood, then the one question: a blurple button for each
        # likely answer, Cancel, and no Save until it is answered
        lines += [proposal.question.text, ASKING]
        answers = tuple(
            Button(cards.truncate_label(choice.label), CARDS, "answer", f"{card_id}:{index}", style=cards.PRIMARY)
            for index, choice in enumerate(proposal.question.choices[: actions.MAX_CHOICES])
        )
        row = (*answers, cards.cancel(CARDS, "cancel", str(card_id)))
        return Card("\n".join(lines), (row,), _designed(heading, proposal, row, ASKING))
    lines.append(FOOTER)
    # Red for what takes something away (a removal, anything that can't be undone), green for Save
    if proposal.destructive or proposal.kind == "remove":
        confirm = Button(proposal.confirm_label, CARDS, "save", str(card_id), emoji="🗑️", style=cards.DANGER)
    else:
        confirm = Button(proposal.confirm_label, CARDS, "save", str(card_id), emoji="✅", style=cards.SUCCESS)
    cancel = cards.cancel(CARDS, "cancel", str(card_id))
    row = (confirm, cancel) if proposal.can_save else (cancel,)
    return Card("\n".join(lines), (row,), _designed(heading, proposal, row, FOOTER))


def things(lines: tuple[str, ...]) -> list[str]:
    """A card's lines as its things, for the separators between them: a line
    that opens with a name in bold starts a new thing, and what follows
    belongs to it."""
    found: list[list[str]] = []
    for line in lines:
        if line.startswith("**") or not found:
            found.append([line])
        else:
            found[-1].append(line)
    return ["\n".join(each) for each in found]


def _designed(heading: str, proposal: Proposal, row: tuple, hint: str) -> tuple:
    """The same card as Components V2 (docs/DESIGN.md): one box, blurple for a
    decision, amber for one that asks first because something is risky, red
    for what can't be undone. Drawn only when CARDS_V2 is on."""
    status = design.DESTRUCTIVE if proposal.destructive else design.RISKY if proposal.risky else design.DECISION
    question = proposal.question.text if proposal.question is not None else ""

    def drawn(blocks: list[str]) -> tuple:
        return design.decision(heading, blocks, status=status, warnings=proposal.warnings, question=question, row=row, hint=hint)

    pieces = drawn(things(proposal.lines))
    # A separator between things while they fit; a card of many things is one block
    return pieces if not design.problem(pieces) else drawn(["\n".join(proposal.lines)])


def render_tie(entries: list[Entry], card_id: int, said: str) -> Card:
    """The question on a genuine tie: one button for each task it could be for."""
    row = tuple(
        Button(entry.title, CARDS, "pick", f"{card_id}:{entry.name}", emoji=entry.icon, style=cards.PRIMARY)
        for entry in entries
    )
    row = row + (cards.cancel(CARDS, "cancel", str(card_id), "Neither"),)
    quoted = cards.truncate_label(said, 100)
    # The same question drawn (docs/DESIGN.md, with CARDS_V2 on): a decision, an answer a button
    said = design.quote(quoted) if design.current() >= 3 else f"“{quoted}”"
    drawn = design.decision("❔ One question", [said], question="Which is it for?", row=row)
    return Card(f"Which is “{quoted}” for?", (row,), drawn)


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


def asked_about(card: Stored) -> tuple[str, ...]:
    """The fields an open card's question is about (what its answers settle):
    for the task, when a message that follows the card gives one of them."""
    choices = (card.question or {}).get("choices", []) if card is not None else []
    return tuple(dict.fromkeys(name for choice in choices for name in choice.get("settles", [])))


def on_screen(card: Stored) -> str:
    """An open card in a line, for the router to read."""
    entry = actions.entry(card.task)
    name = entry.title if entry else card.task
    said = " | ".join(line for line in card.said.split("\n") if line.strip())
    return f"a {name} card ({card.action}) from the user saying: {said}"


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "id, user_id, channel_id, message_id, kind, task, action, data, guessed, said, status, job_id, created_at, previous, confirmation, question"


def _stored(row: tuple) -> Stored:
    return Stored(
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], json.loads(row[7]),
        tuple(json.loads(row[8])), row[9], row[10], row[11], from_db(row[12]),
        json.loads(row[13]) if row[13] else None, row[14], json.loads(row[15]) if row[15] else None,
    )


def _asked(question: actions.Question | None) -> str | None:
    """A card's question as it is kept."""
    if question is None:
        return None
    choices = [{"label": choice.label, "data": choice.data, "settles": list(choice.settles)} for choice in question.choices[: actions.MAX_CHOICES]]
    return json.dumps({"text": question.text, "choices": choices}, ensure_ascii=False)


def db_asking(conn: sqlite3.Connection, card_id: int, proposal: Proposal, guessed) -> None:
    """Keep what a card now shows: its data, what was guessed, and its question (or none)."""
    conn.execute(
        "UPDATE confirm_cards SET data = ?, guessed = ?, question = ? WHERE id = ?",
        (json.dumps(proposal.data, ensure_ascii=False), json.dumps(sorted(guessed)), _asked(proposal.question), card_id),
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


def db_confirmed(conn: sqlite3.Connection, card_id: int, confirmation: str) -> None:
    """Keep what Save said, before anything is shown."""
    conn.execute("UPDATE confirm_cards SET confirmation = ? WHERE id = ?", (confirmation, card_id))


def after_restart(confirmation: str | None) -> str:
    """The card of a Save that was cut off and has been read back: the normal
    confirmation, and under it that it was checked."""
    return f"{confirmation or SAVED_PLAIN}\n{CHECKED}"


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
async def just_saved(user_id: int, channel_id: int | None) -> Stored | None:
    """The card this user saved a moment ago in this channel, if that Save is
    still the last thing a task did there (llm.just_saved). What a correction
    straight after a Save is about."""
    card_id = llm.just_saved(channel_id)
    if card_id is None:
        return None
    card = await database.run(db_get, card_id)
    return card if card is not None and card.user_id == user_id and card.status == SAVED and card.kind == CARD else None


async def latest_open(user_id: int, channel_id: int) -> Stored | None:
    return await database.run(db_latest_open, user_id, channel_id)


async def _place(card: Stored, shown: Card) -> Stored:
    """Post a stored card and book its expiry."""
    message_id = await cards.send(card.channel_id, shown)
    # What it answers (a message of mine in the hub) waits for it to be saved, cancelled or to expire
    await messages.card_opened(message_id)
    job_id = await scheduler.add_job(
        JOB_TASK, JOB_KIND, utc_now() + timedelta(minutes=EXPIRY_MINUTES), {"card": card.id}, card.user_id
    )
    await database.run(db_placed, card.id, message_id, job_id)
    return await database.run(db_get, card.id)


async def answered_in_words(card: Stored) -> None:
    """A card's question was answered by typing, and what was asked for is now
    done without a card: the card that asked goes."""
    await _take_away(card, REPLACED)


async def _take_away(card: Stored, status: str) -> None:
    """Close a card and remove its message: something newer has taken its place,
    or the user said no."""
    if await database.run(db_close, card.id, status):
        await scheduler.cancel_job(card.job_id)
        if card.message_id is not None:
            await cards.delete(card.channel_id, card.message_id)
            await messages.card_closed(card.message_id, saved=False)


def db_forget(conn: sqlite3.Connection, gone: set[int]) -> list[int | None]:
    """Close every open card whose message is among `gone`. Returns their expiry jobs."""
    rows = conn.execute("SELECT id, message_id, job_id FROM confirm_cards WHERE status = ?", (OPEN,)).fetchall()
    jobs = []
    for card_id, message_id, job_id in rows:
        if message_id in gone and db_close(conn, card_id, CANCELLED):
            jobs.append(job_id)
    return jobs


async def forget(gone: set[int]) -> None:
    """Messages were deleted (a channel reset): a card that was one of them is
    closed, so no later message is taken as being about it."""
    for job_id in await database.run(db_forget, gone):
        await scheduler.cancel_job(job_id)


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
    if proposal.question is not None:
        await database.run(db_asking, card.id, proposal, guessed)
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
    await messages.card_closed(card.message_id, saved=False)
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
    if card.question is not None:
        raise UserError(ANSWER_FIRST)  # no card that asks has a Save: this is only a guard
    # A UserError here (the name was taken meanwhile) is shown to the presser and the card stays
    request = Request(press.user, card.channel_id)
    said = await action.apply(request, card.data)
    placed = None
    if isinstance(said, actions.Answer):
        # About things of the task's own: once the card says so, the task is told which message it is
        said, placed = said.text, said.placed
    # Kept at once: should the bot stop before the card is rewritten, these are the words it gets at start
    await database.run(db_confirmed, card.id, said)
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
    said_in = getattr(press, "message_id", None) or card.message_id
    # The card is now its confirmation: in the hub it goes like any reply; anywhere else a
    # line that reports a change lasts the day
    await messages.card_closed(said_in, saved=True)
    if not messages.in_hub(card.channel_id):
        await messages.record(said_in, card.channel_id, lifetime=messages.DAY, task=card.task)
    if placed is not None and said_in is not None:
        await placed(said_in)
    # What a press did is part of the conversation: without it, whatever is asked
    # next is answered as if the card were still waiting
    llm.remember(card.channel_id, "(pressed the card's button)", said)
    # And what follows shortly is that task's first: about this card, if it points at nothing else
    llm.task_answered(card.channel_id, card.task, saved=card.id)
    return f"saved {card.task}/{card.action}: {said}"


async def on_answer(press: cards.Press) -> str | None:
    """A button under a card's question: the card is made again with that
    answer in it, in place. It may ask its next question, or now have Save.
    An action that only sometimes asks first (`card_if`) and no longer needs
    to is done at once, and the card says what was done."""
    card_id, _, index = press.arg.partition(":")
    card = await _open_card(press, card_id)
    if card is None:
        return "card had gone"
    choices = (card.question or {}).get("choices", [])
    entry = actions.entry(card.task)
    action = entry.action(card.action) if entry else None
    if action is None or not index.isdigit() or int(index) >= len(choices):
        await press.update(Card(LAPSED))
        await database.run(db_close, card.id, EXPIRED)
        return f"no such answer on card {card.id}"
    choice = choices[int(index)]
    data = choice["data"]
    # What the answer decides is no longer a guess
    guessed = frozenset(name for name in card.guessed if not any(name.endswith(settled) for settled in choice.get("settles", [])))
    request = Request(press.user, card.channel_id)
    asks_first = action.needs_card
    if action.card_if is not None:
        asks_first = await action.card_if(request, data, guessed)
    if not asks_first and action.run is not None:
        # Nothing left to ask or to look over: done, read back by the action itself, and said on the card
        said = await action.run(request, data, guessed)
        placed = None
        if isinstance(said, actions.Answer):
            said, placed = said.text, said.placed
        if not isinstance(said, str):
            raise UserError("That answer can't be taken from here. Say it instead.")
        if not await database.run(db_close, card.id, SAVED):
            raise UserError("That card was closed a moment ago.")
        await scheduler.cancel_job(card.job_id)
        await press.update(Card(said))
        said_in = getattr(press, "message_id", None) or card.message_id
        if placed is not None and said_in is not None:
            await placed(said_in)
        llm.remember(card.channel_id, f"(answered “{choice['label']}” on the card)", said)
        llm.task_answered(card.channel_id, card.task)
        return f"answered {choice['label']}: {said}"
    proposal = await action.prepare(request, data, guessed)
    kept = guessed | frozenset(proposal.guessed)
    await database.run(db_asking, card.id, proposal, kept)
    shown = render(entry, proposal, card.id)
    await press.update(shown)
    llm.remember(card.channel_id, f"(answered “{choice['label']}” on the card)", shown.text)
    return f"answered {choice['label']} on card {card.id}"


async def on_cancel(press: cards.Press) -> str | None:
    card = await database.run(db_get, int(press.arg)) if press.arg.isdigit() else None
    if card is not None and card.user_id == press.user.id and await database.run(db_close, card.id, CANCELLED):
        await scheduler.cancel_job(card.job_id)
        llm.remember(card.channel_id, "(pressed Cancel on the card)", "Cancelled: nothing was changed.")
        await messages.card_closed(card.message_id, saved=False)
    await press.remove()
    return f"cancelled card {press.arg}"


async def save_cut_off(cut: restart.CutOff, arg: str) -> str:
    """Save was pressed and the bot stopped before it had finished
    (core/restart.py). Nothing is applied a second time: the change is read
    back, as after any Save. If it is there the card is closed and gets the
    normal confirmation, with a line under it; if it isn't, the card is left
    open, exactly as it was, to be pressed again."""
    card = await database.run(db_get, int(arg)) if arg.isdigit() else None
    if card is None:
        return "Save was pressed on a card that is no longer kept: nothing to check"
    entry = actions.entry(card.task)
    action = entry.action(card.action) if entry else None
    # In words, for #bot-log: an action's name ("pill_add") is the code's own and stays in the log file
    name = f"a {card.task} card"
    log.info("The Save cut off by the stop was %s/%s (card %s)", card.task, card.action, card.id)
    if card.status != SAVED:
        if not card.is_open:
            return f"Save of {name} was cut off by the stop, on a card already closed ({card.status}): nothing to do"
        user = await users.get_user(card.user_id)
        if action is None or action.verify is None or user is None:
            return f"Save of {name} was cut off by the stop and can't be checked: its card is still open"
        wrong = await action.verify(Request(user, card.channel_id), card.data)
        if wrong:
            return f"Save of {name} was cut off by the stop before it took ({wrong}): its card is still open, press Save again"
        await database.run(db_close, card.id, SAVED)
        await scheduler.cancel_job(card.job_id)
    if card.message_id is not None:
        await cards.edit(card.channel_id, card.message_id, Card(after_restart(card.confirmation)))
    return f"Save of {name} was cut off by the stop after it took: read back, and its card now says so"


def setup() -> None:
    """Register the buttons and the expiry. Before the bot connects."""
    restart.on_cut_off(CARDS, "save", save_cut_off)
    cards.register(CARDS, "save", on_save)
    cards.register(CARDS, "cancel", on_cancel)
    cards.register(CARDS, "answer", on_answer)
    scheduler.register_handler(JOB_TASK, JOB_KIND, expired, "a card's expiry", housekeeping=True)


async def message_class(message_id: int) -> MessageClass | None:
    """An open card is Live: replaced or saved in place, and gone if left."""
    card = await database.run(db_by_message, message_id)
    return MessageClass.LIVE if card is not None and card.is_open else None
