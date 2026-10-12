import logging
from datetime import date, datetime

from core import actions, cards, clock, confirm, design, llm, occurrences, timeinput
from core.actions import Request
from core.cards import Button, Field, Form
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from tasks.pills import checklist, rules, today
from tasks.pills.rules import PAUSED, Pill
from tasks.pills.today import TASK, Dose

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Pills: today's checklist as a Components V2 message (docs/DESIGN.md), drawn
# only when CARDS_V2 is on. One box a pill, in the colour of what is still to
# do, with the buttons of its next dose inside the box; Paused in a section
# of its own. Off, the checklist is the plain message of tasks/pills/today.py
# and none of this is used.
#
# The top half is pure (what the message holds, and how it is made to fit
# Discord's 40 components); the bottom half is the three buttons. They never
# remove the message they are on: it is the checklist, rewritten in place.
#
# No discord.py: the records are core/design.py's, and core/cards.py draws them.
# ---------------------------------------------------------------------------
S_TAKEN, S_AT, S_SKIP = "sheet_taken", "sheet_at", "sheet_skip"
MARKS = {DONE: "●", PENDING: "○", MISSED: "✕", SKIPPED: "⏭"}
NOTHING = "Nothing to take today."
FORM_TITLE = "When did you take it?"


def _groups(listed: list[Dose]) -> list[list[Dose]]:
    """Today's doses, a pill at a time, in the order the pills first appear."""
    found: dict[int, list[Dose]] = {}
    for dose in listed:
        found.setdefault(dose.pill.id, []).append(dose)
    return [sorted(doses, key=lambda dose: dose.number) for doses in found.values()]


def status(doses: list[Dose]) -> str:
    """The colour of a pill's box: that of what is still to do. Red only when
    a dose was missed and nothing is left to take today."""
    pending = [dose for dose in doses if dose.is_pending]
    if pending:
        return design.ANY_TIME if pending[0].is_untimed else design.DUE
    states = {dose.occurrence.state for dose in doses}
    if MISSED in states:
        return design.MISSED
    return design.DONE if DONE in states else design.QUIET


def _which(dose: Dose) -> str:
    return f"dose {dose.number} · " if dose.of > 1 else ""


def _happened(dose: Dose) -> str:
    """What has happened to a dose that is no longer waiting, in a line."""
    state = dose.occurrence.state
    if state == DONE:
        at = dose.occurrence.actual_at
        return f"✅ {_which(dose)}{timeinput.format_moment(at)}" if at else f"✅ {_which(dose)}taken"
    if state == MISSED:
        due = today.shown_time(dose)
        return f"❌ {_which(dose)}missed" + (f" · was due {timeinput.format_moment(due)}" if due else "")
    if dose.occurrence.automatic and dose.occurrence.reason:
        return design.small(f"⏭️ {_which(dose)}skipped by the bot: {dose.occurrence.reason}")
    return f"⏭️ {_which(dose)}skipped"


def _next(dose: Dose) -> str:
    """The dose that is next, in a line. Nothing for one with no time: its box says "any time"."""
    when = today.shown_time(dose)
    if when is not None:
        shown = f"`{timeinput.format_moment(when)}`"
        return f"**Next:** dose {dose.number} · {shown}" if dose.of > 1 else f"Due {shown}"
    if dose.is_untimed:
        return ""
    return f"**Next:** dose {dose.number} · after dose {dose.number - 1}" if dose.number > 1 else ""


def row(dose: Dose) -> tuple[Button, ...]:
    which = str(dose.occurrence.id)
    return (
        Button("Taken", TASK, S_TAKEN, which, emoji="✅", style=cards.SUCCESS),
        Button("Taken at…", TASK, S_AT, which, emoji="🕐", style=cards.PRIMARY),
        Button("Skip", TASK, S_SKIP, which, emoji="⏭️", style=cards.PRIMARY),
    )


def box(doses: list[Dose], now: datetime, with_buttons: bool = True) -> design.Box:
    """One pill's box: its name and a mark a dose, its note, what has happened,
    what is next, a take-by warning, and the buttons of its next dose."""
    from tasks.pills import reminders  # it imports the checklist, which this module is used by

    pill = doses[0].pill
    waiting = next((dose for dose in doses if dose.is_pending), None)
    name = f"**{pill.plan.name}** · {''.join(MARKS[dose.occurrence.state] for dose in doses)}"
    if waiting is not None and waiting.is_untimed:
        name += " · any time"
    lines = [design.small(pill.plan.notes) if pill.plan.notes else ""]
    lines += [_happened(dose) for dose in doses if not dose.is_pending]
    if waiting is not None:
        lines += [_next(waiting), reminders._take_by(waiting, now) or ""]
    return design.item(status(doses), name, *lines, row=row(waiting) if waiting is not None and with_buttons else ())


def _paused(pills: list[Pill], day: date) -> list[design.Box]:
    paused = sorted((pill for pill in pills if rules.status_on(pill, day) == PAUSED), key=lambda pill: pill.plan.name.lower())
    if not paused:
        return []
    lines = [
        design.small(pill.plan.name + (f" · until {timeinput.format_date(pill.paused_until)}" if pill.paused_until else ""))
        for pill in paused
    ]
    return [design.item(design.QUIET, "⏸️ **Paused**", *lines)]


def _folded(groups: list[list[Dose]], limit: int) -> design.Box:
    """Pills with nothing left to do today, as one box of lines. Never drops
    one without saying how many more there are."""
    lines = [today.line(dose) for doses in groups for dose in doses]
    shown, used = [], 0
    for line in lines:
        if used + len(line) + 1 > limit:
            break
        shown.append(line)
        used += len(line) + 1
    if len(shown) < len(lines):
        shown.append(design.small(f"and {len(lines) - len(shown)} more"))
    return design.item(design.QUIET, "**Dealt with**", *shown)


def title(listed: list[Dose]) -> str:
    taken = sum(dose.occurrence.state == DONE for dose in listed)
    return f"💊 Today · {taken} of {len(listed)} taken" if listed else "💊 Today"


def layout(listed: list[Dose], pills: list[Pill], day: date, now: datetime) -> tuple:
    """Today's checklist as a layout that fits one message. When it would not
    fit, buttons go first (only the next dose due keeps them), then the pills
    with nothing left to do are folded into one box of lines."""
    groups = _groups(listed)
    context = f"{day:%A} {day.day} {day:%B}"
    later = _paused(pills, day)

    def built(buttons_on: set[int], folded: bool) -> tuple:
        open_, closed = [], []
        for doses in groups:
            (open_ if any(dose.is_pending for dose in doses) or not folded else closed).append(doses)
        boxes = [box(doses, now, doses[0].pill.id in buttons_on) for doses in open_]
        if closed:
            boxes.append(_folded(closed, design.MAX_TEXT // 2))
        if not boxes:
            boxes = [design.Text(NOTHING)]
        return design.standing(title(listed), context, boxes, later)

    everyone = {doses[0].pill.id for doses in groups}
    pending = sorted(
        (dose for dose in listed if dose.is_pending),
        key=lambda dose: (dose.due.at is None, dose.due.at.timestamp() if dose.due.at else 0, dose.pill.plan.name.lower()),
    )
    first = {pending[0].pill.id} if pending else set()
    for buttons_on, folded in ((everyone, False), (first, False), (first, True), (set(), True)):
        pieces = built(buttons_on, folded)
        if not design.problem(pieces):
            return pieces
    # More pills still to take than one message has room for: a line each, and how many more
    waiting = [today.line(dose) for dose in pending]
    room = (design.MAX_TEXT // 2) // max(len(line) + 1 for line in waiting)
    lines = waiting[:room] + ([design.small(f"and {len(waiting) - room} more")] if len(waiting) > room else [])
    done = [doses for doses in groups if not any(dose.is_pending for dose in doses)]
    boxes = [design.item(design.DUE, "**Still to take**", *lines)] + ([_folded(done, design.MAX_TEXT // 4)] if done else [])
    return design.standing(title(listed), context, boxes, later)


# ---------------------------------------------------------------------------
# The buttons. The message they are on is the checklist: it is never removed,
# only written again (checklist.refresh)
# ---------------------------------------------------------------------------
async def _dose(press: cards.Press) -> tuple[Dose | None, list[Dose]]:
    _, listed, _ = await checklist.view(press.user.id)
    return next((each for each in listed if str(each.occurrence.id) == press.arg), None), listed


async def _stale(press: cards.Press) -> str:
    """Dealt with already (by a message, a reminder, or the day is over): the
    checklist is brought up to date, which takes the button away."""
    await checklist.refresh(press.user.id)
    return "already dealt with"


async def _done(press: cards.Press, dose: Dose, did: str, at: datetime, source: str) -> str:
    after = await checklist.mark(dose, did, at, source)
    await checklist.refresh(press.user.id)
    checklist.tell_changed()
    said = checklist.marked_text(after, did)
    # So that the next message isn't answered as if this were still waiting
    llm.remember(press.channel_id, f"(pressed {'Taken' if did == checklist.TAKEN else 'Skip'} on the checklist for {rules.plain(dose.label)})", said)
    llm.task_answered(press.channel_id, TASK)
    return said


async def _asked_first(press: cards.Press, dose: Dose, listed: list[Dose], at: datetime, how: str) -> str | None:
    """Too soon, or after the latest time: the same "Log it anyway?" card as
    when it is said in a message. Nothing is logged by asking."""
    from tasks.pills import plain  # plain imports the checklist

    asks = plain.asked_about(dose, listed, at)
    if not asks:
        return None
    request = Request(press.user, press.channel_id, f"({how} on the checklist for {rules.plain(dose.label)})")
    await confirm.show(request, actions.entry(TASK), "pill_log", plain.log_anyway(dose, at, asks, listed), frozenset())
    return f"asked first: {' '.join(asks)}"


def _loggable(dose: Dose | None) -> bool:
    """Whether Taken can still do something for this dose: it is waiting, or it
    was missed (a press on a checklist not yet rewritten), which asks first."""
    return dose is not None and (dose.is_pending or dose.occurrence.state == MISSED)


async def on_taken(press: cards.Press) -> str:
    dose, listed = await _dose(press)
    if not _loggable(dose):
        return await _stale(press)
    now = clock.now()
    return await _asked_first(press, dose, listed, now, "Taken") or await _done(press, dose, checklist.TAKEN, now, occurrences.BUTTON)


async def on_skip(press: cards.Press) -> str:
    dose, _ = await _dose(press)
    if dose is None or not dose.is_pending:
        return await _stale(press)
    return await _done(press, dose, checklist.SKIP, clock.now(), occurrences.BUTTON)


async def on_taken_at(press: cards.Press) -> str:
    """Taken at…: a one-box form for the time, read and checked as a time said in a message is."""
    if press.fields is None:
        await press.open_form(Form(FORM_TITLE, TASK, S_AT, (Field("at", "Time taken", placeholder="8:15 am"),), press.arg))
        return "asked for the time"
    dose, listed = await _dose(press)
    if dose is None or not dose.is_pending:
        return await _stale(press)
    from tasks.pills import plain

    now = clock.now()
    before = today.before(listed, dose)
    at = plain._moment(str(press.fields.get("at", "")).strip(), now, before.occurrence.actual_at if before else None)
    asked = await _asked_first(press, dose, listed, at, f"Taken at… {timeinput.format_moment(at)}")
    return asked or await _done(press, dose, checklist.TAKEN, at, occurrences.FORM)


def register() -> None:
    cards.register(TASK, S_TAKEN, on_taken)
    cards.register(TASK, S_SKIP, on_skip)
    cards.register(TASK, S_AT, on_taken_at, opens_form=True)
