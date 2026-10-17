import base64
import csv
import io
import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from typing import Awaitable, Callable

from core import actions, cards, confirm, costs, database, design, dms, extraction, llm, messages, routing, scheduler, trace
from core.actions import Attachment, Entry, Request
from core.cards import Button, Card
from core.clock import now as clock_now
from core.config import INBOX_CHANNEL_ID
from core.errors import UserError

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The smart inbox: whatever Alex sends, sorted into the right things.
#
#   "renew rego by Friday, call Mum Sunday 2pm, need milk, dentist Thursday 3pm"
#   a photo, a screenshot, a PDF or a CSV sent in #inbox or a direct message
#
# One request (`sort`) splits what was sent into items, each in his own words
# and for the task that takes it; Claude reads the files (images and PDFs as
# they are, a CSV as its rows, read by Python). Each item then goes to its
# task's own extraction and its own `prepare`, exactly as if it had been sent
# alone, and the task writes every word of its line. One card lists them all:
#
#     ## 📥 Inbox · 4 things
#     📝 To-dos · **Renew rego** · Friday
#     ⏰ Reminders · **Call Mum** · Sunday `2:00 pm`
#     📝 To-dos · **Milk** · any day
#     📅 Calendar · **Dentist** · Thursday `3:00 pm` to `4:00 pm`
#     [✅ Save all] [↩️ Cancel]
#     -# or tell me what to change: make the rego one a reminder at 9am Friday
#
# Nothing is saved before Save; Save does each item with its task's own
# `apply` (or `run`, for a log), read back as always; Undo takes back each
# with its action's `undo`. A change in words while the card is on screen
# asks `sort` again with the card's items and the change, and only the items
# that changed are read again. A message for one thing never comes here: the
# router says `several` for two or more, and a question is never an item.
#
# Privacy: what a file holds never reaches a log, a trace or #bot-log (a
# placeholder stands in), and nothing is kept of a file after it is read but
# what a task needs (a gym plan's rows, in inbox_kept, for the gym task to
# come). The card's first line names no item: it is what a phone may show.
# ---------------------------------------------------------------------------
CARDS = "inbox"  # the name the card's buttons go by in core/cards.py
SORT = "sort"  # the kind of row in confirm_cards
TOOL = "sort"
PURPOSE = "sort"  # what the request is counted under
ICON = "📥"
UNSURE = "unsure"  # where an item goes could not be told: asked on the card
GYM_PLAN = "gym_plan"  # a table that is a gym plan: its rows kept for the gym task to come
MAX_TOKENS = 900
MAX_FILES = 3
MAX_IMAGE = 5 * 1024 * 1024  # what the API takes in one image
MAX_PDF = 10 * 1024 * 1024
MAX_CSV = 1024 * 1024
CSV_ROWS = 200  # the most rows read from a table
IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
FROM_A_FILE = "(read from a file: not kept here)"  # what logs and traces show in place of what a file held

HINT = "-# or tell me what to change: make the milk one a reminder at 9am"
NOTHING_FOUND = "📥 Nothing to sort in that"
CANT_READ = "📥 I can't read that kind of file yet: photos, screenshots, PDFs and CSVs."
TOO_BIG = "📥 That file is too big for me to read"


# ---------------------------------------------------------------------------
# Files: which can be read, and how they are sent
# ---------------------------------------------------------------------------
def kind_of(attachment: Attachment) -> str:
    """ "image", "pdf", "csv", or "" for a file that can't be read. Pure."""
    said = (attachment.content_type or "").split(";")[0].strip().lower()
    if said in IMAGES.values() or attachment.extension in IMAGES:
        return "image"
    if said == "application/pdf" or attachment.extension == "pdf":
        return "pdf"
    if said in ("text/csv", "application/vnd.ms-excel") or attachment.extension == "csv":
        return "csv"
    return ""


def too_big(attachment: Attachment) -> bool:
    limit = {"image": MAX_IMAGE, "pdf": MAX_PDF, "csv": MAX_CSV}.get(kind_of(attachment), 0)
    return attachment.size > limit


def media_type(attachment: Attachment) -> str:
    said = (attachment.content_type or "").split(";")[0].strip().lower()
    if said in IMAGES.values():
        return said
    return IMAGES.get(attachment.extension, "image/png")


def table(data: bytes) -> list[list[str]]:
    """A CSV's rows, empty ones left out, at most CSV_ROWS. Pure."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    return [row for row in rows if any(row)][:CSV_ROWS]


@dataclass(frozen=True)
class Read:
    """What was sent, ready for `sort`: the blocks of each image and PDF, and each table's rows."""

    blocks: tuple[dict, ...] = ()
    tables: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = ()  # (file name, rows)
    kinds: tuple[str, ...] = ()  # "image", "pdf", "csv": for the log, which never shows what they hold


async def read_files(attachments: tuple[Attachment, ...]) -> Read:
    """Fetch each file that can be read. Nothing is written anywhere: the bytes live only for this request."""
    blocks, tables, kinds = [], [], []
    for attachment in [each for each in attachments if kind_of(each)][:MAX_FILES]:
        kind = kind_of(attachment)
        if too_big(attachment) or attachment.fetch is None:
            continue
        data = await attachment.fetch()
        kinds.append(kind)
        if kind == "csv":
            tables.append((attachment.name, tuple(tuple(row) for row in table(data))))
        elif kind == "pdf":
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode("ascii")}})
        else:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type(attachment), "data": base64.b64encode(data).decode("ascii")}})
    return Read(tuple(blocks), tuple(tables), tuple(kinds))


def files_for(channel_id: int | None, attachments: tuple[Attachment, ...]) -> bool:
    """Whether the files sent with a message are the smart inbox's to read: in #inbox or a direct message,
    and at least one of a kind it reads."""
    return bool(attachments) and (channel_id == INBOX_CHANNEL_ID or dms.is_dm(channel_id)) and any(kind_of(each) for each in attachments)


# ---------------------------------------------------------------------------
# The request: what was sent, split into items
# ---------------------------------------------------------------------------
RULES = (
    "You sort what the user sent a personal assistant bot into the separate things it holds, each for the task that "
    "will take it. You do not act and you do not answer: you only call the `sort` tool.\n"
    "- One item for each separate thing: a to-do, a reminder, something that expires or must be renewed, an "
    "appointment, a step of a routine, a pill taken, a note about their day. Its words are a request that stands on "
    "its own, in the user's own words, with its own day and time, as if it had been sent alone (\"dentist Thursday "
    "3pm\"). Keep the user's words; add only what the item needs from the rest (a day said once for two things).\n"
    "- task: the task below that takes it; read each one's \"only for\" line. unsure when it cannot be told where it "
    "goes: its words still as said.\n"
    "- A question is never an item, and nor is a greeting or a please.\n"
    "- From a file (a photo, a screenshot, a PDF, a table): an item for each thing in it worth keeping. An appointment "
    "or a booking confirmation is an event for the calendar, with its day and time (\"dentist Thursday 23 October "
    "3pm\"). A bill or a letter with a day it is due is a reminder, asked for in so many words (\"remind me to pay the "
    "power bill by 28 October\"), or something that expires if it is a renewal (\"car registration expires 14 November\"). A medicine label is one "
    "item for pills, asking to add it as printed: its name, the dose and how often (\"add Testvit 1 tablet twice "
    "daily\"); never a dose taken. A table that is plainly a gym plan (exercises with sets or reps) is one item, task "
    "gym_plan, its words a short name for it (\"gym plan\"). With nothing worth keeping, give no items and say in saw, "
    "in under 15 words, what the file shows.\n"
    "- With the card's items given and a change asked for: give the whole list as it should be after the change, in "
    "the same order. An item the change is not about is copied word for word, with its task. Change only what the "
    "user asked (\"make the rego one a reminder at 9am Friday\": that item's task and words, nothing else). If the "
    "message is not a change to the card at all (a question, something new), set about_card to false."
)


def tool(entries: list[Entry]) -> dict:
    places = [entry.name for entry in entries] + [GYM_PLAN, UNSURE]
    return {
        "name": TOOL,
        "description": "The separate things in what was sent, each with the task that takes it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "words": {"type": "string", "description": "The thing as a request of its own, in the user's words."},
                            "task": {"type": "string", "enum": places},
                        },
                        "required": ["words", "task"],
                        "additionalProperties": False,
                    },
                },
                "saw": {"type": "string", "description": "With no items from a file: what it shows, in under 15 words. Otherwise empty."},
                "about_card": {"type": "boolean", "description": "With the card's items given: false if the message is not a change to them."},
            },
            "required": ["items", "saw", "about_card"],
            "additionalProperties": False,
        },
    }


def system_blocks(entries: list[Entry]) -> list[dict]:
    return [{"type": "text", "text": f"{RULES}\n\n{routing.catalogue_text(entries)}", "cache_control": llm.CACHED}]


def user_turn(text: str, read: Read | None = None, on_card: list[dict] | None = None) -> list[dict] | str:
    """What changes from request to request: the files, the card's items, and what was said."""
    parts = []
    if on_card is not None:
        parts.append("The card's items now:\n" + "\n".join(f"{at}. [{item['task']}] {item['words']}" for at, item in enumerate(on_card, 1)))
        parts.append(f"The change asked for:\n{text}")
    else:
        parts.append(f"The message:\n{text or '(no words: only the files)'}")
    for name, rows in (read.tables if read else ()):
        shown = "\n".join(", ".join(row) for row in rows[:60])
        parts.append(f"A table sent as a file ({name}, {len(rows)} rows):\n{shown}")
    words = "\n\n".join(parts)
    if read is None or not read.blocks:
        return words
    return [*read.blocks, {"type": "text", "text": words}]


@dataclass(frozen=True)
class Sorted:
    items: tuple[tuple[str, str], ...] = ()  # (words, task)
    saw: str = ""
    about_card: bool = True
    problem: str = ""


def parse(raw, names: list[str]) -> Sorted:
    """What `sort` returned, checked in code: an item for no task here is unsure. Pure."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return Sorted(problem="sort returned no list of items")
    places = set(names) | {GYM_PLAN, UNSURE}
    items = []
    for each in raw["items"]:
        if not isinstance(each, dict) or not str(each.get("words", "")).strip():
            continue
        task = each.get("task") if each.get("task") in places else UNSURE
        items.append((str(each["words"]).strip(), task))
    saw = raw.get("saw") if isinstance(raw.get("saw"), str) else ""
    return Sorted(tuple(items), saw.strip(), raw.get("about_card") is not False)


async def ask(entries: list[Entry], text: str, read: Read | None = None, on_card: list[dict] | None = None) -> Sorted:
    called = await llm.call_tool(
        system_blocks(entries), user_turn(text, read, on_card), [tool(entries)],
        choice={"type": "tool", "name": TOOL}, purpose=PURPOSE, max_tokens=MAX_TOKENS,
    )
    found = parse(called[1] if called else None, [entry.name for entry in entries])
    if found.problem:
        log.warning("Smart inbox: %s", found.problem)  # never what it held
    return found


# ---------------------------------------------------------------------------
# Each item, read by its own task
# ---------------------------------------------------------------------------
def _entry(name: str, entries: list[Entry]) -> Entry | None:
    return next((entry for entry in entries if entry.name == name), None)


def unclear(words: str, task: str, why: str = "where does this go?", file: bool = False) -> dict:
    return {"words": words, "task": task, "lines": [f"❓ “{words}” · {why}"], "ready": False, "file": file}


async def prepare(request: Request, words: str, task: str, entries: list[Entry], state_of, *, file: bool = False, rows=None) -> dict:
    """One item as its task reads it: what the card shows for it and what Save does. A question for a
    task is returned as {"question": Extracted}, to be answered as any question is."""
    if task == GYM_PLAN:
        if not rows:
            return unclear(words, UNSURE, "a gym plan needs its table: send the CSV", file)
        return {
            "words": words, "task": GYM_PLAN, "data": {"name": words, "rows": [list(row) for row in rows]}, "ready": True, "file": file,
            "lines": [f"🏋️ Gym · **{words}** · {len(rows)} rows kept for the gym task to come"],
        }
    entry = _entry(task, entries)
    if entry is None:
        return unclear(words, UNSURE, file=file)
    found = await extraction.extract(entry, words, await state_of(entry, request), elsewhere="the rest of the message, sorted separately")
    if not found.fitted:
        return unclear(words, task, "I couldn't tell what to do with this", file)
    action = found.action
    if action.purpose == actions.SEE:
        return {"question": found, "words": words, "task": task}
    item = {"words": words, "task": task, "action": action.name, "guessed": sorted(found.guessed), "file": file}
    try:
        needs_card = action.needs_card
        if action.card_if is not None:
            needs_card = await action.card_if(request, found.data, frozenset(found.guessed))
        if not needs_card or action.prepare is None:
            # A log (a dose taken, a note about the day): done at Save, its words as he said them
            return {**item, "data": found.data, "direct": True, "ready": True, "lines": [f"“{words}”"]}
        try:
            proposal = await action.prepare(request, found.data, frozenset(found.guessed))
        except actions.HandOff as handoff:
            # A task's own rule hands it to another task (a day and no time: a to-do)
            target = actions.handed(handoff)
            if target is None:
                raise UserError("That can't be done here.") from None
            task, action = target[0].name, target[1]
            item = {**item, "task": task, "action": action.name, "guessed": []}
            found = replace(found, data=handoff.data, guessed=frozenset())
            proposal = await action.prepare(request, handoff.data, frozenset())
    except UserError as error:
        return {**item, "lines": [design.warning(str(error))], "ready": False}
    lines = [*proposal.lines, *[design.warning(each) for each in proposal.warnings]]
    question = proposal.question.text if proposal.question is not None else ""
    if question:
        lines.append(f"❓ {question}")
    return {
        **item, "data": proposal.data, "guessed": sorted(set(found.guessed) | set(proposal.guessed)), "lines": lines or [f"“{words}”"],
        "ready": proposal.can_save and not question, "kind": proposal.kind,
    }


# ---------------------------------------------------------------------------
# The card (pure)
# ---------------------------------------------------------------------------
def heading(count: int) -> str:
    """The card's first line: never an item's name, so nothing private reaches a lock screen."""
    return f"{ICON} Inbox · {count} thing{'' if count == 1 else 's'}"


def block(item: dict, entries: list[Entry]) -> str:
    """One item: where it goes, and its task's own lines."""
    entry = _entry(item["task"], entries)
    lines = list(item["lines"])
    if entry is None or lines[0].startswith("❓") or item["task"] == GYM_PLAN:
        return "\n".join(lines)
    return "\n".join([f"{entry.icon} {entry.title} · {lines[0]}", *lines[1:]])


def render(items: list[dict], entries: list[Entry], card_id: int) -> Card:
    ready = [each for each in items if each.get("ready")]
    waiting = len(items) - len(ready)
    title = heading(len(items))
    blocks = [block(each, entries) for each in items]
    warnings = [f"Save leaves out {waiting} still to answer: tell me, or it stays unsaved"] if waiting and ready else []
    label = "Save all" if not waiting else f"Save {len(ready)}"
    cancel = cards.cancel(CARDS, "cancel", str(card_id))
    row = (Button(label, CARDS, "save", str(card_id), emoji="✅", style=cards.SUCCESS), cancel) if ready else (cancel,)
    text = "\n".join([title, *blocks, *[design.warning(each) for each in warnings], HINT])
    layout = design.decision(title, blocks, status=design.DECISION, warnings=warnings, row=row, hint=HINT)
    if design.problem(layout):
        layout = design.decision(title, ["\n".join(blocks)], status=design.DECISION, warnings=warnings, row=row, hint=HINT)
    return Card(text, (row,), layout)


def logged(items: list[dict], entries: list[Entry]) -> str:
    """The card as the log and the trace keep it: an item from a file, or for a task that keeps its words
    to itself (the diary), is a placeholder."""
    shown = []
    for item in items:
        entry = _entry(item["task"], entries)
        where = f"{entry.icon} {entry.title}" if entry else item["task"]
        if item.get("file"):
            shown.append(f"{where} · {FROM_A_FILE}")
        elif entry is not None and entry.private:
            shown.append(f"{where} · {actions.PRIVATE_NOTE}")
        else:
            shown.append(f"{where} · {' / '.join(item['lines'])}")
    return f"card: smart inbox · {len(items)} things: " + " | ".join(shown)


# ---------------------------------------------------------------------------
# Kept rows (a gym plan) and the open card
# ---------------------------------------------------------------------------
def db_keep(conn: sqlite3.Connection, user_id: int, kind: str, name: str, rows: list, at: str) -> int:
    return conn.execute(
        "INSERT INTO inbox_kept (user_id, kind, name, rows, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, kind, name, json.dumps(rows, ensure_ascii=False), at)
    ).lastrowid


def db_unkeep(conn: sqlite3.Connection, user_id: int, kind: str, name: str) -> bool:
    row = conn.execute("SELECT id FROM inbox_kept WHERE user_id = ? AND kind = ? AND name = ? ORDER BY id DESC LIMIT 1", (user_id, kind, name)).fetchone()
    if row is not None:
        conn.execute("DELETE FROM inbox_kept WHERE id = ?", (row[0],))
    return row is not None


def db_kept(conn: sqlite3.Connection, user_id: int, kind: str) -> list[tuple[str, list]]:
    return [(name, json.loads(rows)) for name, rows in conn.execute("SELECT name, rows FROM inbox_kept WHERE user_id = ? AND kind = ? ORDER BY id", (user_id, kind))]


def db_open(conn: sqlite3.Connection, user_id: int, channel_id: int) -> confirm.Stored | None:
    row = conn.execute(
        f"SELECT {confirm._COLUMNS} FROM confirm_cards WHERE user_id = ? AND channel_id = ? AND kind = ? AND status = ? ORDER BY id DESC LIMIT 1",
        (user_id, channel_id, SORT, confirm.OPEN),
    ).fetchone()
    return confirm._stored(row) if row else None


def db_set_data(conn: sqlite3.Connection, card_id: int, data: dict) -> None:
    conn.execute("UPDATE confirm_cards SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), card_id))


async def open_card(user_id: int, channel_id: int) -> confirm.Stored | None:
    return await database.run(db_open, user_id, channel_id)


def sticks(card: confirm.Stored, now, replied_to: int | None, latest: int | None) -> bool:
    """A message is about the card when it replies to it, or the card is the bot's latest word and fresh."""
    return confirm.sticks(confirm.Stored(**{**card.__dict__, "kind": confirm.CARD}), now, replied_to=replied_to, latest_bot_message_id=latest)


# ---------------------------------------------------------------------------
# Sorting a message, files, or a change to the card
# ---------------------------------------------------------------------------
Answer = Callable[[Request, object], Awaitable[None]]  # answers a question as any is answered (conversation.act)
State = Callable[[Entry, Request], Awaitable[str]]


async def sort(
    request: Request, entries: list[Entry], turn, state_of: State, answer: Answer, *,
    read: Read | None = None, replaces: confirm.Stored | None = None,
) -> bool:
    """Sort what was sent onto one card. False when a change asked for was not about the card after all
    (the caller then handles the message as any other)."""
    from_file = read is not None
    before = list(replaces.data.get("items", [])) if replaces is not None else None
    found = await ask(entries, request.text, read, before)
    if replaces is not None and not found.about_card:
        trace.note("smart inbox: the message is not a change to the card: handled as any other")
        return False
    turn.route = costs.ROUTER
    turn.why.append("smart inbox: " + (f"read {len(read.kinds)} file(s): {', '.join(read.kinds)}" if from_file else "a change to its card" if replaces else "several things in one message"))
    if not found.items:
        saw = found.saw[:1].lower() + found.saw[1:] if found.saw[1:2].islower() else found.saw
        line = f"{NOTHING_FOUND}: {saw.rstrip('.')}" if saw else f"{NOTHING_FOUND}."
        turn.said.append(NOTHING_FOUND if from_file else line)
        await cards.send(request.channel_id, Card(line))
        return True
    rows = next((rows for _, rows in read.tables), None) if read else None
    items, questions = [], []
    for words, task in found.items:
        same = next((each for each in before or [] if each.get("words") == words and each.get("task") == task and "question" not in each), None)
        if same is not None:
            items.append(same)
            continue
        file = from_file or bool(before and any(each.get("file") for each in before))
        item = await prepare(replace_text(request, words), words, task, entries, state_of, file=file, rows=rows)
        if "question" in item:
            questions.append(item["question"])
            continue
        items.append(item)
        if item["task"] in [entry.name for entry in entries]:
            turn.tasks.append(item["task"])
    turn.extracted.append({"smart inbox": [{"task": each["task"], "action": each.get("action", ""), "ready": each.get("ready", False)} for each in items]})
    for question in questions:
        if not from_file:
            await answer(request, question)
    if not items:
        return True
    said = request.text if replaces is None else "\n".join(part for part in (replaces.said, request.text) if part)
    card = await database.run(confirm.db_add, request.user.id, request.channel_id, SORT, "", SORT, {"items": items}, (), FROM_A_FILE if from_file else said)
    placed = await confirm._place(card, render(items, entries, card.id))
    if replaces is not None:
        await confirm._take_away(replaces, confirm.REPLACED)
    turn.said.append(logged(items, entries))
    if replaces is not None:
        trace.note(f"smart inbox: card {replaces.id} replaced by {placed.id}")
    return True


def replace_text(request: Request, words: str) -> Request:
    from dataclasses import replace

    return replace(request, text=words, attachments=())


# ---------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------
async def _card(press: cards.Press, status: str) -> confirm.Stored | None:
    card = await database.run(confirm.db_get, int(press.arg)) if press.arg.isdigit() else None
    if card is None or card.kind != SORT or card.user_id != press.user.id or card.status != status:
        return None
    return card


def _said(result) -> str:
    if isinstance(result, actions.Answer):
        return result.text
    if isinstance(result, (actions.Shown,)):
        return result.summary
    if isinstance(result, actions.LiveReply):
        return result.text
    return str(result)


async def _save_one(request: Request, item: dict) -> str:
    """One item, done by its own task, read back as after any Save. Its line, or a ⚠️ line saying it didn't take."""
    if item["task"] == GYM_PLAN:
        await database.run(db_keep, request.user.id, GYM_PLAN, item["data"]["name"], item["data"]["rows"], clock_now().isoformat())
        return f"✅ Kept · 🏋️ **{item['data']['name']}** · {len(item['data']['rows'])} rows, for the gym task to come"
    entry = actions.entry(item["task"])
    action = entry.action(item["action"]) if entry else None
    if action is None:
        return design.warning("That can't be saved any more: what it belonged to has gone.")
    if item.get("direct"):
        return _said(await action.run(request, item["data"], frozenset(item.get("guessed", ()))))
    said = _said(await action.apply(request, item["data"]))
    wrong = await action.verify(request, item["data"]) if action.verify is not None else ""
    return design.warning(f"{entry.title}: that didn't save ({wrong})") if wrong else said


async def on_save(press: cards.Press) -> str | None:
    card = await _card(press, confirm.OPEN)
    if card is None:
        await press.update(Card(confirm.LAPSED))
        return "card had gone"
    if not await database.run(confirm.db_close, card.id, confirm.SAVED):
        raise UserError("That card was closed a moment ago.")
    await scheduler.cancel_job(card.job_id)
    items = card.data.get("items", [])
    lines, saved = [], []
    for index, item in enumerate(items):
        if not item.get("ready"):
            continue
        request = Request(press.user, card.channel_id, item["words"])
        try:
            said = await _save_one(request, item)
        except UserError as error:
            said = design.warning(str(error))
        except Exception:
            log.exception("Smart inbox: an item of card %s could not be saved (%s)", card.id, item["task"])
            said = design.warning("One thing didn't save: nothing of it was changed. Say it again on its own.")
        if not said.startswith(design.WARNING):
            saved.append(index)
        lines.append(said)
    await database.run(db_set_data, card.id, {**card.data, "saved": saved})
    left = len(items) - len([each for each in items if each.get("ready")])
    text = "\n".join([f"✅ Saved · {len(saved)} of {len(items)}", *lines, *([design.small(f"{left} not saved: still to answer")] if left else [])])
    row = (Button("Undo", CARDS, "undo", str(card.id), emoji="↩️", style=cards.PRIMARY),) if saved else ()
    await press.update(Card(text, (row,) if row else ()))
    said_in = getattr(press, "message_id", None) or card.message_id
    await messages.card_closed(said_in, saved=True)
    if not messages.in_hub(card.channel_id):
        await messages.record(said_in, card.channel_id, lifetime=messages.DAY, task="")
    llm.remember(card.channel_id, "(pressed Save on the inbox card)", f"Saved {len(saved)} of {len(items)}")
    llm.task_answered(card.channel_id, "")
    return f"smart inbox: saved {len(saved)} of {len(items)}"


async def on_undo(press: cards.Press) -> str | None:
    card = await _card(press, confirm.SAVED)
    if card is None or card.data.get("undone"):
        await press.update(Card("↩️ Already undone."))
        return "nothing to undo"
    await database.run(db_set_data, card.id, {**card.data, "undone": True})
    items = card.data.get("items", [])
    lines = []
    for index in reversed(card.data.get("saved", [])):
        item = items[index]
        request = Request(press.user, card.channel_id, item["words"])
        try:
            if item["task"] == GYM_PLAN:
                gone = await database.run(db_unkeep, press.user.id, GYM_PLAN, item["data"]["name"])
                lines.append(f"↩️ 🏋️ **{item['data']['name']}** · " + ("not kept" if gone else "was not there"))
                continue
            entry = actions.entry(item["task"])
            action = entry.action(item["action"]) if entry else None
            if action is None or action.undo is None:
                where = f"{entry.icon} {entry.title}" if entry else "That one"
                lines.append(f"{where} · can't be undone from here: say undo that, or change it there")
                continue
            lines.append(await action.undo(request, item["data"]))
        except UserError as error:
            lines.append(design.warning(str(error)))
        except Exception:
            log.exception("Smart inbox: an item of card %s could not be undone (%s)", card.id, item["task"])
            lines.append(design.warning("One thing could not be undone: check it in its own list."))
    await press.update(Card("\n".join(["↩️ Undone", *reversed(lines)])))
    llm.remember(card.channel_id, "(pressed Undo on the inbox card)", "Undone")
    return f"smart inbox: undone card {card.id}"


async def on_cancel(press: cards.Press) -> str | None:
    card = await _card(press, confirm.OPEN)
    if card is not None and await database.run(confirm.db_close, card.id, confirm.CANCELLED):
        await scheduler.cancel_job(card.job_id)
        await messages.card_closed(card.message_id, saved=False)
        llm.remember(card.channel_id, "(pressed Cancel on the inbox card)", "Cancelled: nothing was changed.")
    await press.remove()
    return f"smart inbox: cancelled card {press.arg}"


def setup() -> None:
    cards.register(CARDS, "save", on_save)
    cards.register(CARDS, "undo", on_undo)
    cards.register(CARDS, "cancel", on_cancel)
