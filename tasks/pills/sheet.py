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
# only when CARDS_V2 is on. The round 3 type scale: a page title, then one box
# for the topic with the day's dots in its card title, a pill an item with a
# rule between them (due or overdue first, then coming up, then any time),
# the buttons of each pill's next dose under it, and what is done, paused or
# not today in one small line at the bottom. The box's edge is the most
# urgent state in it. Off, the checklist is the plain message of
# tasks/pills/today.py and none of this is used.
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
    """The status of a pill: that of what is still to do. Red only when a dose
    was missed and nothing is left to take today."""
    pending = [dose for dose in doses if dose.is_pending]
    if pending:
        return design.ANY_TIME if pending[0].is_untimed else design.DUE
    states = {dose.occurrence.state for dose in doses}
    if MISSED in states:
        return design.MISSED
    return design.DONE if DONE in states else design.QUIET


def _which(dose: Dose) -> str:
    return f"dose {dose.number} · " if dose.of > 1 else ""


# Where a pill comes in its box, by what is next for it (docs/DESIGN.md, round 3)
DUE_NOW, COMING, ANY, MISSED_ONLY, FINISHED = range(5)


def place(doses: list[Dose], now: datetime) -> tuple:
    """Where a pill goes: due or overdue first, then coming up, then any time,
    then one with only a miss left; a pill with nothing left goes in the small
    line at the bottom. Within each, the soonest, then by name."""
    waiting = next((dose for dose in doses if dose.is_pending), None)
    named = doses[0].pill.plan.name.lower()
    if waiting is None:
        return (MISSED_ONLY if status(doses) == design.MISSED else FINISHED, 0, named)
    if waiting.is_untimed:
        return (ANY, 0, named)
    at = today.shown_time(waiting)
    if at is None:
        return (COMING, float("inf"), named)
    return (DUE_NOW if at <= now else COMING, at.timestamp(), named)


def _happened(dose: Dose) -> str:
    """A dose no longer waiting, as a small line under its pill."""
    state = dose.occurrence.state
    if state == DONE:
        at = dose.occurrence.actual_at
        return design.small(f"✅ {_which(dose)}{timeinput.format_moment(at)}" if at else f"✅ {_which(dose)}taken")
    if state == MISSED:
        due = today.shown_time(dose)
        return f"missed · {_which(dose)}" + (f"was due {design.time(timeinput.format_moment(due))}" if due else "no time left")
    if dose.occurrence.automatic and dose.occurrence.reason:
        return design.small(f"⏭️ {_which(dose)}skipped by the bot: {dose.occurrence.reason}")
    return design.small(f"⏭️ {_which(dose)}skipped")


def _next(dose: Dose, now: datetime) -> str:
    """What is next for a pill, in one line: its dose, and when."""
    if dose.is_untimed:
        return f"{_which(dose)}any time"
    at = today.shown_time(dose)
    if at is not None:
        shown = timeinput.format_moment(at)
        return f"{_which(dose)}{'due ' if at <= now else ''}{design.when(shown, at, now)}"
    if dose.number > 1:
        return f"{_which(dose)}after dose {dose.number - 1}"
    return _which(dose).removesuffix(" · ") or "to take today"


def row(dose: Dose) -> tuple[Button, ...]:
    which = str(dose.occurrence.id)
    return (
        Button("Taken", TASK, S_TAKEN, which, emoji="✅", style=cards.SUCCESS),
        Button("Taken at…", TASK, S_AT, which, emoji="🕐", style=cards.PRIMARY),
        Button("Skip", TASK, S_SKIP, which, emoji="⏭️", style=cards.PRIMARY),
    )


def entry(doses: list[Dose], now: datetime, with_buttons: bool = True) -> design.Entry:
    """One pill in the box: its name in bold and a mark a dose, what is next
    for it, its note and a take-by warning small, what has happened to its
    other doses small, and the buttons of its next dose."""
    from tasks.pills import reminders  # it imports the checklist, which this module is used by

    pill = doses[0].pill
    waiting = next((dose for dose in doses if dose.is_pending), None)
    lines = [f"{design.name(pill.plan.name)} {''.join(MARKS[dose.occurrence.state] for dose in doses)}"]
    if waiting is not None:
        lines.append(_next(waiting, now))
    lines += [_happened(dose) for dose in doses if not dose.is_pending]
    if pill.plan.notes:
        lines.append(design.small(pill.plan.notes))
    if waiting is not None:
        lines.append(reminders._take_by(waiting, now) or "")
    return design.Entry(
        "\n".join(line for line in lines if line),
        status(doses),
        row(waiting) if waiting is not None and with_buttons else (),
    )


def _finished(doses: list[Dose]) -> str:
    """A pill with nothing left today, in a few words for the small line."""
    pill = doses[0].pill.plan.name
    taken = [dose for dose in doses if dose.occurrence.state == DONE]
    if not taken:
        return f"⏭️ {pill} skipped"
    if len(doses) == 1 and taken[0].occurrence.actual_at:
        return f"✅ {pill} · {timeinput.format_moment(taken[0].occurrence.actual_at)}"
    return f"✅ {pill}"


def tail(finished: list[list[Dose]], pills: list[Pill], day: date, limit: int = design.MAX_TEXT // 4) -> str:
    """The one small line at the bottom of the box: what is done, what is
    paused and what is not taken today. Never drops one without saying how
    many more there are."""
    said = [_finished(doses) for doses in finished]
    paused = sorted((pill for pill in pills if rules.status_on(pill, day) == PAUSED), key=lambda pill: pill.plan.name.lower())
    said += [f"⏸️ {pill.plan.name} paused" + (f" until {timeinput.format_date(pill.paused_until)}" if pill.paused_until else "") for pill in paused]
    said += [f"🗓️ {pill.plan.name} not today · {rules.days_text(pill.plan.schedule.days)}" for pill in today.not_today(pills, day)]
    shown, used = [], 0
    for part in said:
        if used + len(part) + 3 > limit:
            break
        shown.append(part)
        used += len(part) + 3
    if len(shown) < len(said):
        shown.append(f"and {len(said) - len(shown)} more")
    return " · ".join(shown)


def title(listed: list[Dose]) -> str:
    taken = sum(dose.occurrence.state == DONE for dose in listed)
    return f"💊 Today · {taken} of {len(listed)} taken" if listed else "💊 Today"


def page_title(day: date) -> str:
    """The checklist's page title: the topic and the day."""
    return f"💊 Today · {day:%a} {day.day} {day:%b}"


def layout(listed: list[Dose], pills: list[Pill], day: date, now: datetime) -> tuple:
    """Today's checklist as a page with one box (docs/DESIGN.md, round 3): the
    card title with the day's dots, then a pill an item in the order of what
    is next (due or overdue, coming up, any time, a miss), a rule between
    them, and the pills with nothing left in one small line at the bottom.
    When it would not fit one message, the buttons go first: only the next
    dose due keeps them, then none (design.fit does the rest).

    In round 1 of the design (DESIGN_ROUND=1) it is tasks/pills/sheet_r1.py."""
    if design.current() < 3:
        from tasks.pills import sheet_r1  # it uses this module

        return sheet_r1.layout(listed, pills, day, now)
    groups = sorted(_groups(listed), key=lambda doses: place(doses, now))
    open_ = [doses for doses in groups if place(doses, now)[0] != FINISHED]
    finished = [doses for doses in groups if place(doses, now)[0] == FINISHED]
    done, total = today.progress(listed)
    heading = design.card_title("💊 Pills", done, total)
    under = [] if listed else [NOTHING]
    bottom = tail(finished, pills, day)

    def built(buttons_on: set[int]) -> tuple:
        entries = [entry(doses, now, doses[0].pill.id in buttons_on) for doses in open_]
        fallback = design.DONE if finished and any(status(doses) == design.DONE for doses in finished) else design.QUIET
        box = design.topic(heading, entries, lines=under, tail=bottom, status="" if entries else fallback)
        return design.page([design.page_title(page_title(day))], [box])

    everyone = {doses[0].pill.id for doses in open_}
    first = {open_[0][0].pill.id} if open_ and any(dose.is_pending for dose in open_[0]) else set()
    pieces = ()
    for buttons_on in (everyone, first, set()):
        pieces = built(buttons_on)
        if not design.problem(pieces):
            return pieces
    return design.fit(pieces)


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
    another = await plain.logged_lately(listed, dose, clock.now())
    await confirm.show(request, actions.entry(TASK), "pill_log", plain.log_anyway(dose, at, asks, listed, another), frozenset())
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
