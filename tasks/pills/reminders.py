import asyncio
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from core import actions, cards, clock, config, confirm, database, design, discord_utils, hub, lifecycle, llm, occurrences, restart, scheduler, timeinput
from core import day as days
from core.actions import Request
from core.cards import Button, Card, Field, Form
from core.lifecycle import MessageClass
from core.schedule import AFTER_PREVIOUS
from core.scheduler import from_db, to_db
from tasks.pills import checklist, rules, today
from tasks.pills import doses as limits
from tasks.pills.today import TASK, Dose

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Pills: reminders (the spec's prompts). Each dose with a time gets a message
# of its own when it is due, so that it notifies: Taken, Taken at…, Snooze,
# Skip. Left alone, it is posted again every 15 minutes, three more times,
# then the dose is missed. Only ever one prompt a dose.
#
# REMINDERS_ENABLED (off unless set) gates all of it: off, no reminder is ever
# sent, nothing is booked, and any prompt left from when it was on is removed.
#
# Nothing here keeps time in memory. What is to be done is worked out every
# time from the day's doses (tasks/pills/today.py), what is kept about each
# prompt (`pills_prompts`: when it was first and last posted, how many
# reminders have gone, a snooze) and the clock; `run` does what is due and
# books one job for the next moment anything is. So a restart, a late job or
# a job run twice all come to the same: a dose still due gets one prompt,
# never one for each reminder that was missed, and nothing is ever posted
# after its pill's latest time (docs/ARCHITECTURE.md, "What survives a
# restart").
#
# The notification never names a pill: the message is posted as one neutral
# line ("💊 Routine due · 11:12 am"), which is what the phone shows, and the
# pill, the dose and the buttons are written into it straight after (an edit
# notifies nobody).
#
# The top half is pure (what to do, and every word); the bottom half does it
# through core/cards.py. No discord.py.
# ---------------------------------------------------------------------------
JOB = "remind"
EVERY = timedelta(minutes=15)  # between a prompt and the reminder after it
REMINDERS = 3  # how many times it is posted again before the dose is missed
SNOOZE = timedelta(minutes=15)
TAKE_BY_WITHIN = timedelta(hours=2)  # the take-by line shows only when it is this close
IGNORED = limits.IGNORED

P_TAKEN, P_AT, P_SNOOZE, P_SKIP = "prompt_taken", "prompt_at", "prompt_snooze", "prompt_skip"
POST, MISS, DROP, WAIT = "post", "miss", "drop", "wait"
AGAIN = "A pill reminder"  # what a channel reset would post again: no pill is named


def enabled() -> bool:
    return bool(config.REMINDERS_ENABLED)


def minute(moment: datetime) -> datetime:
    """A moment to the minute. Reminders keep to whole minutes: "one more at
    8:45 pm" is then exactly when the next one comes."""
    return moment.replace(second=0, microsecond=0)


@dataclass(frozen=True)
class Prompt:
    """What is kept about a dose's prompt."""

    occurrence_id: int
    user_id: int
    day: date
    channel_id: int
    message_id: int | None  # None once the message has gone (a channel reset): it is posted again
    asked_at: datetime  # when it was first posted
    last_at: datetime  # when the copy now up was posted
    reminders: int = 0  # how many times it has been posted again
    snoozed_until: datetime | None = None


# ---------------------------------------------------------------------------
# What to do (pure)
# ---------------------------------------------------------------------------
def wants_prompt(dose: Dose, now: datetime) -> bool:
    """Whether a dose is one to remind about now or later today: still to
    take, with a time, and that time within its pill's day."""
    return dose.is_pending and today.shown_time(dose) is not None and not limits.is_after_limit(dose.pill.plan.schedule, dose.occurrence.day, now)


def decide(dose: Dose, prompt: Prompt | None, now: datetime) -> tuple[str, datetime | None, int]:
    """What to do about one dose now: (POST, MISS, DROP or WAIT, when to look
    again, which reminder a POST is: 0 for the first prompt).

    Worked out from what is kept, never from how many jobs ran: however long
    the bot was off, a dose that is due gets one prompt, the next in its
    turn."""
    if not wants_prompt(dose, now):
        return (DROP if prompt is not None else WAIT), None, 0
    due, next_look = minute(dose.due.at), minute(now) + EVERY
    if prompt is None:
        return (POST, next_look, 0) if now >= due else (WAIT, due, 0)
    if prompt.snoozed_until is not None:
        if now < prompt.snoozed_until:
            return WAIT, prompt.snoozed_until, prompt.reminders
        # The snooze is over: a fresh copy, which is not one of the reminders
        return POST, next_look, prompt.reminders
    if prompt.message_id is None:
        return POST, next_look, prompt.reminders
    again = minute(prompt.last_at) + EVERY
    if now < again:
        return WAIT, again, prompt.reminders
    if prompt.reminders >= REMINDERS:
        return MISS, None, prompt.reminders
    return POST, next_look, prompt.reminders + 1


# ---------------------------------------------------------------------------
# The words (pure)
# ---------------------------------------------------------------------------
def notice(dose: Dose, reminders: int = 0) -> str:
    """The one line the phone shows. It says a routine is due and when: never
    which pill, its dose or its note."""
    line = f"💊 Routine due · {timeinput.format_moment(dose.due.at)}"
    return f"{line} · reminder {reminders} of {REMINDERS}" if reminders else line


def _take_by(dose: Dose, now: datetime) -> str | None:
    plan = dose.pill.plan.schedule
    later = dose.of - dose.number
    by = limits.take_by(plan, dose.occurrence.day, later) if later else None
    if by is None or by - now > TAKE_BY_WITHIN:
        return None
    rest = f"dose {dose.number + 1}" if later == 1 else "the doses after it"
    return f"-# ⚠️ Take by {timeinput.format_moment(by)} so {rest} still fit{'s' if later == 1 else ''}"


def text(dose: Dose, listed: list[Dose], prompt: Prompt, now: datetime) -> str:
    """The prompt as it reads once the pill is written into it."""
    lines = [notice(dose, prompt.reminders)]
    lines.append(f"**{dose.pill.plan.name}**" + (f" · dose {dose.number} of {dose.of}" if dose.of > 1 else ""))
    due = f"Due `{timeinput.format_moment(dose.due.at)}`"
    before = today.before(listed, dose)
    plan = dose.pill.plan.schedule
    if dose.due.why == AFTER_PREVIOUS and before is not None and plan.gap_minutes:
        due += f" · {rules.gap_text(plan.gap_minutes)} after dose {before.number} at {timeinput.format_moment(before.occurrence.actual_at)}"
    lines.append(due)
    if dose.pill.plan.notes:
        lines.append(f"-# {dose.pill.plan.notes}")
    take_by = _take_by(dose, now)
    if take_by:
        lines.append(take_by)
    if prompt.snoozed_until is not None:
        lines.append(f"-# 💤 Snoozed until {timeinput.format_moment(prompt.snoozed_until)}")
    elif prompt.reminders:
        left = REMINDERS - prompt.reminders
        coming = timeinput.format_moment(prompt.last_at + EVERY)
        more = "the last reminder" if not left else (f"one more at {coming}" if left == 1 else f"{left} more, the next at {coming}")
        lines.append(f"-# ⏰ Reminder {prompt.reminders} of {REMINDERS} · first asked {timeinput.format_moment(prompt.asked_at)} · {more}")
    return "\n".join(lines)


def card(dose: Dose, listed: list[Dose], prompt: Prompt, now: datetime) -> Card:
    which = str(dose.occurrence.id)
    row = (
        Button("Taken", TASK, P_TAKEN, which, emoji="✅", style=cards.SUCCESS),
        Button("Taken at…", TASK, P_AT, which, emoji="🕐", style=cards.PRIMARY),
        Button("Snooze 15m", TASK, P_SNOOZE, which, emoji="⏰", style=cards.PRIMARY),
        Button("Skip", TASK, P_SKIP, which, emoji="⏭️", style=cards.PRIMARY),
    )
    said = text(dose, listed, prompt, now)
    # As Components V2 (CARDS_V2): the neutral line stays on top, outside the box, and the
    # pill is in a box under it: amber while it is due, grey while it is snoozed
    first, name, *rest = said.split("\n")
    status = design.QUIET if prompt.snoozed_until is not None else design.DUE
    return Card(said, (row,), design.notifying(first, design.item(status, name, *rest, row=row)))


# ---------------------------------------------------------------------------
# What is kept (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "occurrence_id, user_id, day, channel_id, message_id, asked_at, last_at, reminders, snoozed_until"


def _prompt(row: tuple) -> Prompt:
    return Prompt(row[0], row[1], date.fromisoformat(row[2]), row[3], row[4], from_db(row[5]), from_db(row[6]), row[7], from_db(row[8]) if row[8] else None)


def db_prompts(conn: sqlite3.Connection, user_id: int | None = None) -> list[Prompt]:
    sql, values = f"SELECT {_COLUMNS} FROM pills_prompts", ()
    if user_id is not None:
        sql, values = sql + " WHERE user_id = ?", (user_id,)
    return [_prompt(row) for row in conn.execute(sql + " ORDER BY occurrence_id", values).fetchall()]


def db_prompt(conn: sqlite3.Connection, occurrence_id: int) -> Prompt | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM pills_prompts WHERE occurrence_id = ?", (occurrence_id,)).fetchone()
    return _prompt(row) if row else None


def db_by_message(conn: sqlite3.Connection, message_id: int) -> Prompt | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM pills_prompts WHERE message_id = ?", (message_id,)).fetchone()
    return _prompt(row) if row else None


def db_keep(conn: sqlite3.Connection, prompt: Prompt) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO pills_prompts ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prompt.occurrence_id, prompt.user_id, prompt.day.isoformat(), prompt.channel_id, prompt.message_id,
            to_db(prompt.asked_at), to_db(prompt.last_at), prompt.reminders, to_db(prompt.snoozed_until) if prompt.snoozed_until else None,
        ),
    )


def db_forget(conn: sqlite3.Connection, occurrence_id: int) -> None:
    conn.execute("DELETE FROM pills_prompts WHERE occurrence_id = ?", (occurrence_id,))


def db_ignored(conn: sqlite3.Connection, occurrence_id: int, now: datetime) -> None:
    """Every reminder went unanswered: the dose is missed, and that is final
    (its cause says so: tasks/pills/doses.py never opens it again by itself)."""
    occurrences.db_miss(conn, occurrence_id, cause=IGNORED, now=now)


async def is_prompt(message_id: int) -> bool:
    return await database.run(db_by_message, message_id) is not None


async def dose_of(message_id: int, listed: list[Dose]) -> Dose | None:
    """The dose a prompt is about, for a reply to it ("took it at 9")."""
    prompt = await database.run(db_by_message, message_id)
    return next((dose for dose in listed if prompt is not None and dose.occurrence.id == prompt.occurrence_id), None)


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------
_running = asyncio.Lock()
NO_HUB = ("💊 Pill reminders can't be sent", "Reminders are on, but the hub channel is not set or can't be found. Nothing is sent until it is.")
_said_no_hub = False


async def _hub_missing(missing: bool) -> None:
    """Reminders are on and there is nowhere to post them: said once in
    #bot-log, and not again until the hub has been found in between."""
    global _said_no_hub
    if missing and not _said_no_hub:
        log.warning("Pills reminders: on, and the hub channel can't be found")
        await discord_utils.log_simple(*NO_HUB)
    _said_no_hub = missing


async def _take_down(prompt: Prompt) -> None:
    if prompt.message_id is not None and lifecycle.deletes(MessageClass.ALERT):
        await cards.delete(prompt.channel_id, prompt.message_id)
    await database.run(db_forget, prompt.occurrence_id)


async def _post(dose: Dose, listed: list[Dose], old: Prompt | None, reminders: int, now: datetime) -> bool:
    """Put a fresh copy of a dose's prompt up, in place of the one before.
    First the neutral line, which is what notifies; then the pill is written
    into it. False if there is nowhere to post it."""
    channel_id = hub.channel_id()
    message_id = await cards.send(channel_id, Card(notice(dose, reminders))) if channel_id is not None else None
    await _hub_missing(message_id is None)
    if message_id is None:
        return False
    if old is not None and old.message_id is not None and lifecycle.deletes(MessageClass.ALERT):
        await cards.delete(old.channel_id, old.message_id)
    prompt = Prompt(dose.occurrence.id, dose.pill.user_id, dose.occurrence.day, channel_id, message_id, old.asked_at if old else minute(now), minute(now), reminders)
    await database.run(db_keep, prompt)
    await cards.edit(channel_id, message_id, card(dose, listed, prompt, now))
    return True


async def _run(user_id: int) -> tuple[datetime | None, int]:
    """Do what is due for one user. Returns when to look again, and how many prompts were posted."""
    now = clock.now()
    _, listed, day = await checklist.view(user_id)
    kept = {prompt.occurrence_id: prompt for prompt in await database.run(db_prompts, user_id)}
    by_id = {dose.occurrence.id: dose for dose in listed}
    nearest: datetime | None = None
    posted, missed = 0, False
    for occurrence_id, prompt in kept.items():
        if occurrence_id not in by_id or not enabled():
            # A day that is over, a pill that went, or reminders switched off: nothing of it stays
            await _take_down(prompt)
            log.info("Pills reminders: prompt for dose %s taken down (%s)", occurrence_id, "off" if not enabled() else "no longer today's")
    if not enabled():
        return None, 0
    for dose in listed:
        prompt = kept.get(dose.occurrence.id)
        what, again, reminders = decide(dose, prompt, now)
        if what == POST:
            if await _post(dose, listed, prompt, reminders, now):
                posted += 1
                log.info("Pills reminders: dose %s posted (reminder %s of %s)", dose.occurrence.id, reminders, REMINDERS)
            else:
                log.warning("Pills reminders: dose %s is due and there is no hub channel to post in", dose.occurrence.id)
                again = None
        elif what == MISS:
            await database.run(db_ignored, dose.occurrence.id, now)
            await _take_down(prompt)
            missed = True
            log.info("Pills reminders: dose %s missed after %s reminders", dose.occurrence.id, REMINDERS)
        elif what == DROP:
            await _take_down(prompt)
            log.info("Pills reminders: prompt for dose %s taken down (dealt with, or past its time)", dose.occurrence.id)
        if again is not None and (nearest is None or again < nearest):
            nearest = again
    if missed:
        await checklist.refresh(user_id)
    return nearest, posted


async def _book(due_at: datetime | None) -> None:
    """One job for the next moment anything is due; none when nothing is."""
    pending = await scheduler.pending_jobs(TASK, JOB)
    for extra in pending[1:]:
        await scheduler.cancel_job(extra.id)
    if due_at is None:
        if pending:
            await scheduler.cancel_job(pending[0].id)
    elif pending:
        if pending[0].due_at != due_at:
            await scheduler.reschedule_job(pending[0].id, due_at)
    else:
        await scheduler.add_job(TASK, JOB, due_at)


async def run() -> int:
    """Do whatever is due now for everyone, and book the next look. Safe to
    call at any time and as often as wanted. Returns how many prompts went up."""
    from tasks.pills import store  # reminders is imported by the task's own modules

    async with _running:
        nearest: datetime | None = None
        total = 0
        users = set(await database.run(store.db_users)) | {prompt.user_id for prompt in await database.run(db_prompts)}
        for user_id in sorted(users):
            again, posted = await _run(user_id)
            total += posted
            if again is not None and (nearest is None or again < nearest):
                nearest = again
        await _book(nearest if enabled() else None)
        if total:
            # Only kept while the bot is starting (core/restart.py): a reminder sent on time is nothing to report
            restart.caught_up(f"{total} pill reminder{'' if total == 1 else 's'} posted at start: {'it' if total == 1 else 'they'} came due while the bot was off")
        return total


async def remind_job(job: scheduler.Job) -> None:
    """Scheduler handler: something is due."""
    posted = await run()
    log.info("Pills reminders, job %s%s: %s posted", job.id, f", {job.late_by / 60:.0f} minutes late" if job.is_late else "", posted)


async def startup() -> None:
    """When the bot starts: catch up. One prompt for each dose that is due, and the next look booked."""
    if not enabled():
        log.info("Pills reminders are off (REMINDERS_ENABLED): no reminder is sent")
    elif hub.channel_id() is None:
        await _hub_missing(True)  # known at once, not only when the first dose comes due
    waiting = any(job.due_at <= clock.now() for job in await scheduler.pending_jobs(TASK, JOB))
    if waiting and enabled():
        return  # the overdue job runs as the scheduler starts, and says what it caught up on
    await run()


def changed() -> None:
    """A dose or a plan changed: look again, in the background."""
    from core import live

    if enabled():
        live.schedule(("pills-reminders",), run)


async def channel_cleared(channel_id: int, gone: set[int]) -> None:
    """A prompt that went with a channel reset is posted again."""
    lost = [prompt for prompt in await database.run(db_prompts) if prompt.channel_id == channel_id and prompt.message_id in gone]
    for prompt in lost:
        await database.run(db_keep, replace(prompt, message_id=None))
    if lost:
        await run()


async def reposted(channel_id: int, gone: set[int]) -> list[str]:
    held = await database.run(db_prompts)
    return [AGAIN] if any(prompt.channel_id == channel_id and prompt.message_id in gone for prompt in held) else []


# ---------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------
async def _dose(press: cards.Press) -> tuple[Dose | None, list[Dose], Prompt | None]:
    _, listed, _ = await checklist.view(press.user.id)
    dose = next((each for each in listed if str(each.occurrence.id) == press.arg), None)
    prompt = await database.run(db_prompt, int(press.arg)) if press.arg.isdigit() else None
    return dose, listed, prompt


async def _gone(press: cards.Press) -> str:
    """Dealt with already (by a message, or the day is over): the prompt only goes."""
    await press.remove()
    if press.arg.isdigit():
        await database.run(db_forget, int(press.arg))
    return "already dealt with"


async def _done(press: cards.Press, dose: Dose, did: str, at: datetime, source: str) -> str:
    after = await checklist.mark(dose, did, at, source)
    await press.remove()
    await database.run(db_forget, dose.occurrence.id)
    await checklist.refresh(press.user.id)
    await run()
    said = checklist.marked_text(after, did)
    llm.remember(press.channel_id, f"(pressed {'Taken' if did == checklist.TAKEN else 'Skip'} on the reminder for {rules.plain(dose.label)})", said)
    llm.task_answered(press.channel_id, TASK)
    return said


async def on_taken(press: cards.Press) -> str:
    dose, _, _ = await _dose(press)
    if dose is None or not dose.is_pending:
        return await _gone(press)
    return await _done(press, dose, checklist.TAKEN, clock.now(), occurrences.BUTTON)


async def on_skip(press: cards.Press) -> str:
    dose, _, _ = await _dose(press)
    if dose is None or not dose.is_pending:
        return await _gone(press)
    return await _done(press, dose, checklist.SKIP, clock.now(), occurrences.BUTTON)


FORM_TITLE = "When did you take it?"


async def on_taken_at(press: cards.Press) -> str:
    """Taken at…: a one-box form for the time, read and checked as a time said in a message is."""
    if press.fields is None:
        await press.open_form(Form(FORM_TITLE, TASK, P_AT, (Field("at", "Time taken", placeholder="8:15 am"),), press.arg))
        return "asked for the time"
    dose, listed, _ = await _dose(press)
    if dose is None or not dose.is_pending:
        return await _gone(press)
    from tasks.pills import plain  # plain imports this module

    now = clock.now()
    before = today.before(listed, dose)
    at = plain._moment(str(press.fields.get("at", "")).strip(), now, before.occurrence.actual_at if before else None)
    asks = plain.asked_about(dose, listed, at)
    if asks:
        # Too soon, or after the latest time: the same "Log it anyway?" card as when the time is said
        # in a message. Nothing is logged by asking, and the reminder stays until the dose is dealt with
        request = Request(press.user, press.channel_id, f"(Taken at… {timeinput.format_moment(at)} on the reminder for {rules.plain(dose.label)})")
        await confirm.show(request, actions.entry(TASK), "pill_log", plain.log_anyway(dose, at, asks, listed), frozenset())
        return f"asked first: {' '.join(asks)}"
    return await _done(press, dose, checklist.TAKEN, at, occurrences.FORM)


async def on_snooze(press: cards.Press) -> str:
    dose, listed, prompt = await _dose(press)
    if dose is None or not dose.is_pending or prompt is None:
        return await _gone(press)
    now = clock.now()
    snoozed = replace(prompt, snoozed_until=minute(now) + SNOOZE)
    await database.run(db_keep, snoozed)
    await press.update(card(dose, listed, snoozed, now))
    await run()
    return f"snoozed until {timeinput.format_moment(snoozed.snoozed_until)}"


def register() -> None:
    cards.register(TASK, P_TAKEN, on_taken)
    cards.register(TASK, P_SKIP, on_skip)
    cards.register(TASK, P_SNOOZE, on_snooze)
    cards.register(TASK, P_AT, on_taken_at, opens_form=True)
    checklist.on_change(changed)
