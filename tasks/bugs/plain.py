from core import cards
from core.actions import EACH_DAY, LIST, SEE, Action, Field, LiveReply, Request, Shown
from core.cards import Button, Card
from core.errors import UserError
from core.permissions import is_allowed
from tasks.bugs import filing, listing, posts, rules, store

# ---------------------------------------------------------------------------
# Bugs in plain words (core/actions.py): "that's a bug", "show my open bugs",
# "close B2 and B5". Reporting logs something and changes no setup, so it
# needs no card; closing says one line with an Undo, as the Fixed button
# closes at once.
# ---------------------------------------------------------------------------
TASK, UNDO = "bugs", "undo"
NOT_YOURS = "Closing bugs isn't for you."
async def report_said(request: Request, data: dict, guessed: frozenset) -> str:
    """Report the message replied to, or else the user's own newest message
    before this one (never one of the bot's: the report is about that turn).
    What they said was wrong, if they typed it, is kept as the bug's first note."""
    if request.replied_to is not None:
        target, source = await posts.fetch_message(request.channel_id, request.replied_to), rules.REPLY
    else:
        target, source = await posts.latest_before(request.channel_id, request.message_id), rules.WORD
    rules.check_reportable(target)
    already = await store.open_for(request.user.id, target.channel.id, target.id)
    before = await posts.preceding(target)
    text = await filing.file_report(request.user, target.channel.id, rules.snapshot(target), before, source, request.message_id)
    note = (data.get("note") or "").strip()
    item = await store.open_for(request.user.id, target.channel.id, target.id)
    if note and item is not None:
        # Said to be saved only once it has been read back
        if not await filing.add_note(item.id, request.user.id, note, request.message_id):
            raise UserError(f"{text} · but your note didn't save. Write it in the bug's post.")
        text += " · 📝 your note is saved with it" if already is None else " · 📝 note added"
    return text


async def list_said(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    """The open bugs, as the word `bugs` shows them: Live, kept up to date in place."""
    shown = await listing.card(request.user.id)
    return LiveReply(listing.KEY, shown.text, shown)


def _numbers(said) -> list[int]:
    """The bug numbers said ("B2", "b5", "5"), each once, in the order said. An id of the other
    database (a self-test's D1 on live) is refused by name: never closed by words here."""
    found = []
    for each in said if isinstance(said, list) else [said]:
        number = rules.parse_id(str(each))
        if number not in found:
            found.append(number)
    return found


def closed_line(numbers: list[int]) -> str:
    return f"✅ Closed as fixed · {', '.join(rules.bug_id(number) for number in numbers)}"


def reopened_line(numbers: list[int]) -> str:
    return f"↩️ Undone · {', '.join(rules.bug_id(number) for number in numbers)} open again"


def _undo_button(numbers: list[int]) -> Button:
    return Button("Undo", TASK, UNDO, ",".join(str(number) for number in numbers), emoji="↩️", style=cards.PRIMARY)


async def _set(numbers: list[int], status: str, user_id: int) -> list[int]:
    """Set each bug to `status`, its post brought up to date as after a press; the ones changed,
    each read back first. A post that cannot be brought up to date never undoes the change."""
    changed = []
    for number in numbers:
        await store.set_status(number, status, user_id)
        item = await store.get(number)
        if item is None or item.status != status:
            raise UserError(f"{rules.bug_id(number)} didn't change. Try its button in #bugs.")
        changed.append(number)
        await posts.bring_up_to_date(item, rules.changed_text(number, status))
    listing.changed(user_id)
    return changed


async def close_said(request: Request, data: dict, guessed: frozenset) -> Shown:
    """ "close B2", "close B2 and B5", "B5 is fixed": closed as fixed at once, one line with an
    Undo. Only the owner may (as the Fixed button); the self-test still closes only its own."""
    if not is_allowed(request.user, posts.PERMISSION):
        raise UserError(NOT_YOURS)
    numbers = _numbers(data.get("bugs") or [])
    if not numbers:
        raise UserError(f"Which bug? Say its id, like {rules.bug_id(4)}.")
    to_close, already = [], []
    for number in numbers:
        item = await store.get(number)
        if item is None or item.user_id not in (None, request.user.id):
            raise UserError(f"I have no {rules.bug_id(number)}.")
        (to_close if item.status == rules.OPEN else already).append(number)
    if not to_close:
        said = ", ".join(rules.bug_id(number) for number in already)
        raise UserError(f"{said} {'is' if len(already) == 1 else 'are'} already closed.")
    closed = await _set(to_close, rules.FIXED, request.user.id)
    line = closed_line(closed) + (f"\n-# already closed: {', '.join(rules.bug_id(number) for number in already)}" if already else "")
    message_id = await cards.send(request.channel_id, Card(line, ((_undo_button(closed),),)))
    return Shown(line if message_id is not None else "not shown")


async def on_undo(press: cards.Press) -> str:
    """Undo on the line: the bugs it closed open again, the ones still closed by then."""
    if not is_allowed(press.user, posts.PERMISSION):
        return NOT_YOURS
    numbers = [int(each) for each in press.arg.split(",") if each.isdigit()]
    still = []
    for number in numbers:
        item = await store.get(number)
        if item is not None and item.status == rules.FIXED:
            still.append(number)
    line = reopened_line(await _set(still, rules.OPEN, press.user.id)) if still else "↩️ Nothing to undo: they are open already"
    await press.update(Card(line))
    return line


def register() -> None:
    cards.register(TASK, UNDO, on_undo)


ACTIONS = (
    Action(
        "bug_report",
        "The user says the bot itself got something wrong and wants it logged as a bug: \"that's a bug\", "
        "\"log that as a bug\", \"bug: it started two timers\" -> note \"it started two timers\". Only when "
        "they say bug or report. A correction of what they asked for (\"no, I meant 5 minutes\") is not "
        "a bug report: call `none`.",
        (
            Field(
                "note",
                "What the user said was wrong, in their words, if they said. Leave out if they only said it is a bug.",
            ),
        ),
        needs_card=False,
        run=report_said,
        purpose=EACH_DAY,
        say=("that's a bug: it started two timers",),
    ),
    Action(
        "bug_list",
        "The user asks which bugs are open (\"show my open bugs\", \"what bugs have I reported?\").",
        needs_card=False,
        run=list_said,
        purpose=SEE,
        say=("show my open bugs",),
    ),
    Action(
        "bug_close",
        "The user says one or more bugs, by their id, are fixed or to be closed: \"close B2\", \"close B2 and "
        "B5\", \"B5 is fixed\" -> bugs [\"B2\", \"B5\"].",
        (Field("bugs", "Each bug id the user said, as written (\"B2\").", type=LIST, required=True),),
        needs_card=False,
        run=close_said,
        purpose=EACH_DAY,
        say=("close B2 and B5",),
    ),
)
