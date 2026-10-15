import asyncio
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from core import actions, attention, cards, clock, config, confirm, database, design, discord_utils, hub, lifecycle, llm, messages, notify, occurrences, restart, scheduler, surface, timeinput
from core import day as days
from core import schedule as core_schedule
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
# and then it goes and nothing more is sent for that dose. The dose itself is
# still to take: reminders running out is no deadline, and a dose is missed
# only once it can no longer be taken today (tasks/pills/doses.py). Only ever
# one prompt a dose.
#
# A dose left like that gets one more nudge, its last chance: 30 minutes
# before the last moment it can be taken with every dose after it still
# fitting the day (`fits_until`). It notifies like any reminder, through the
# notify service, and names no pill in what the phone shows ("💊 Last chance
# today · take by 6:00 pm"). At that moment it goes, and that is the end.
#
# A post that Discord refuses is tried again: after 1, 2 and 5 minutes, then
# every 5, until it is up or the dose stops fitting the day (the last chance:
# until its moment). What failed is kept in the prompt's row (`attempts`,
# `tried_at`), so a restart carries on where it was. Before each new try the
# hub is read: an earlier try that did go through (the bare line is there)
# is taken up and finished, and never posted a second time.
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
# line ("💊 Dose due · 11:12 am"), which is what the phone shows, and the
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

P_TAKEN, P_AT, P_SNOOZE, P_SKIP = "prompt_taken", "prompt_at", "prompt_snooze", "prompt_skip"
RETRY_MINUTES = (1, 2, 5)  # after the first, second and third try that failed; then every 5
LOOK_BACK = 50  # how many of the hub's latest messages are read for a try that went through after all
LAST_CHANCE = timedelta(minutes=30)  # before a dose stops fitting the day: one more nudge, the last
# What `reminders` says once the three are over: waiting for the last chance, that nudge up, all done
OVER, LAST_UP, FINISHED = REMINDERS + 1, REMINDERS + 2, REMINDERS + 3
POST, STOP, DROP, WAIT, LAST, END = "post", "stop", "drop", "wait", "last", "end"
KIND = "pills.reminder"  # what kind of alert a prompt is: where it goes is core/notify.py's to say
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
    reminders: int = 0  # how many times it has been posted again; past REMINDERS once they are over (OVER, LAST_UP, FINISHED)
    snoozed_until: datetime | None = None
    # A post that Discord refused: `reminders` is then the one being tried, and `message_id` the copy still up
    attempts: int = 0  # how many tries have failed
    tried_at: datetime | None = None  # when the last of them was

    @property
    def is_over(self) -> bool:
        """Every reminder went unanswered: the message has gone and nothing more
        is posted for this dose. It is kept so that it is not asked about again."""
        return self.reminders > REMINDERS

    @property
    def is_last_chance(self) -> bool:
        """The message up is the last-chance nudge."""
        return self.reminders == LAST_UP


# ---------------------------------------------------------------------------
# What to do (pure)
# ---------------------------------------------------------------------------
def wants_prompt(dose: Dose, now: datetime) -> bool:
    """Whether a dose is one to remind about now or later today: still to
    take, with a time, and that time within its pill's day."""
    return dose.is_pending and today.shown_time(dose) is not None and not limits.is_after_limit(dose.pill.plan.schedule, dose.occurrence.day, now)


def fits_until(dose: Dose, listed: list[Dose]) -> datetime:
    """The last moment a dose can be taken with every dose of its pill still
    to come after it fitting the day: the day's limit, less the gap for each
    of those. Past it, a dose stops fitting."""
    plan = dose.pill.plan.schedule
    later = sum(1 for each in listed if each.pill.id == dose.pill.id and each.number > dose.number and each.is_pending)
    by = limits.take_by(plan, dose.occurrence.day, later) if later else None
    return by if by is not None else core_schedule.limit(plan, dose.occurrence.day)


def by_text(dose: Dose, by: datetime) -> str:
    """That moment as it is said: "6:00 pm", or "midnight"."""
    plan = dose.pill.plan.schedule
    return "midnight" if plan.latest is None and by == core_schedule.limit(plan, dose.occurrence.day) else timeinput.format_moment(by)


def retry_at(prompt: Prompt) -> datetime:
    """When a post that failed is tried again: 1, 2 and 5 minutes after the
    first three tries, and every 5 minutes after that."""
    return prompt.tried_at + timedelta(minutes=RETRY_MINUTES[min(prompt.attempts, len(RETRY_MINUTES)) - 1])


def decide(dose: Dose, prompt: Prompt | None, now: datetime, by: datetime | None = None) -> tuple[str, datetime | None, int]:
    """What to do about one dose now: (POST, STOP, DROP, WAIT, LAST or END,
    when to look again, which reminder a POST is: 0 for the first prompt).
    STOP is the end of its reminders: the prompt goes, and the dose stays to
    take. LAST is its last chance, 30 minutes before `by` (`fits_until`), and
    END takes that down at `by`. Without `by` no last chance is given.

    Worked out from what is kept, never from how many jobs ran: however long
    the bot was off, a dose that is due gets one prompt, the next in its
    turn."""
    if not wants_prompt(dose, now):
        return (DROP if prompt is not None else WAIT), None, 0
    due, next_look = minute(dose.due.at), minute(now) + EVERY
    if prompt is not None and prompt.attempts and prompt.tried_at is not None:
        # Discord refused it: tried again in its turn, until it is up or the dose stops fitting the day
        end = minute(by) if by is not None and by > due else None
        if prompt.is_last_chance and end is not None:
            end = min(end, minute(prompt.last_at) + LAST_CHANCE)
        if end is not None and now >= end:
            return END, None, prompt.reminders
        again = retry_at(prompt)
        if now < again:
            # Its next try, or the moment there is no more point in one, whichever comes first
            return WAIT, (min(again, end) if end is not None else again), prompt.reminders
        return (LAST, end, prompt.reminders) if prompt.is_last_chance else (POST, next_look, prompt.reminders)
    if prompt is not None and prompt.is_over:
        # Its reminders are over. Only if it has since come to be due later (the dose before it
        # was taken late) does it start afresh, at that time
        if due > minute(prompt.last_at):
            return DROP, due, 0
        if by is None or prompt.reminders >= FINISHED:
            return WAIT, None, prompt.reminders
        by = minute(by)
        if prompt.is_last_chance:
            # It goes at the moment it named: half an hour after it was posted (what is left may have
            # changed since, and with it the moment worked out now)
            by = min(by, minute(prompt.last_at) + LAST_CHANCE)
            if now >= by:
                return END, None, prompt.reminders
            return (LAST, by, prompt.reminders) if prompt.message_id is None else (WAIT, by, prompt.reminders)
        nudge = by - LAST_CHANCE
        if nudge <= minute(prompt.last_at) or now >= by:
            # It was asked about that late anyway, or the moment has passed: no nudge
            return WAIT, None, prompt.reminders
        return (LAST, by, prompt.reminders) if now >= nudge else (WAIT, nudge, prompt.reminders)
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
        return STOP, None, prompt.reminders
    return POST, next_look, prompt.reminders + 1


# ---------------------------------------------------------------------------
# The words (pure)
# ---------------------------------------------------------------------------
def notice(dose: Dose, reminders: int = 0, by: str = "") -> str:
    """The one line the phone shows. It says a dose is due and when: never
    which pill, its dose number or its note ("Routine" was the bot's own word
    until 15 Oct, and read like a personal routine). A reminder posted again
    says which it is: the dose's time, then the 2nd, 3rd and last reminder,
    15 minutes apart."""
    if reminders == LAST_UP:
        return f"💊 Last chance today · take by {by}"
    line = f"💊 Dose due · {timeinput.format_moment(dose.due.at)}"
    return f"{line} · {again(reminders)}" if reminders else line


def again(reminders: int) -> str:
    """Which reminder a dose's prompt posted again is, in words: "2nd reminder" … "last reminder"."""
    return "last reminder" if reminders >= REMINDERS else f"{reminders + 1}{'nd' if reminders + 1 == 2 else 'rd' if reminders + 1 == 3 else 'th'} reminder"


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
    by = by_text(dose, fits_until(dose, listed))
    lines = [notice(dose, prompt.reminders, by)]
    lines.append(f"**{dose.pill.plan.name}**" + (f" · dose {dose.number} of {dose.of}" if dose.of > 1 else ""))
    due = f"Due `{timeinput.format_moment(dose.due.at)}`"
    before = today.before(listed, dose)
    plan = dose.pill.plan.schedule
    if dose.due.why == AFTER_PREVIOUS and before is not None and plan.gap_minutes:
        due += f" · {rules.gap_text(plan.gap_minutes)} after dose {before.number} at {timeinput.format_moment(before.occurrence.actual_at)}"
    lines.append(due)
    if dose.pill.plan.notes:
        lines.append(f"-# {dose.pill.plan.notes}")
    if prompt.is_last_chance:
        later = [each.number for each in listed if each.pill.id == dose.pill.id and each.number > dose.number and each.is_pending]
        lines.append(f"-# ⚠️ After {by} " + (f"dose {later[-1]} no longer fits today" if later else "it can no longer be taken today"))
        lines.append(f"-# ⏰ The last reminder for this dose · first asked {timeinput.format_moment(prompt.asked_at)}")
        return "\n".join(lines)
    take_by = _take_by(dose, now)
    if take_by:
        lines.append(take_by)
    if prompt.snoozed_until is not None:
        lines.append(f"-# 💤 Snoozed until {timeinput.format_moment(prompt.snoozed_until)}")
    elif prompt.reminders:
        left = REMINDERS - prompt.reminders
        coming = timeinput.format_moment(prompt.last_at + EVERY)
        more = "none after it" if not left else (f"one more at {coming}" if left == 1 else f"{left} more, the next at {coming}")
        lines.append(f"-# ⏰ {again(prompt.reminders).capitalize()} · first asked {timeinput.format_moment(prompt.asked_at)} · {more}")
    return "\n".join(lines)


def card(dose: Dose, listed: list[Dose], prompt: Prompt, now: datetime) -> Card:
    which = str(dose.occurrence.id)
    row = (
        Button("Taken", TASK, P_TAKEN, which, emoji="✅", style=cards.SUCCESS),
        Button("Taken at…", TASK, P_AT, which, emoji="🕐", style=cards.PRIMARY),
        Button("Snooze 15m", TASK, P_SNOOZE, which, emoji="⏰", style=cards.PRIMARY),
        Button("Skip", TASK, P_SKIP, which, emoji="⏭️", style=cards.PRIMARY),
    )
    if design.current() >= 4:
        # Round 4: one Taken, at once (a reply to the line it leaves puts the time right) and Snooze;
        # Skip and a time are said in words
        row = (Button("Taken", TASK, P_TAKEN, which, emoji="✅", style=cards.SUCCESS), Button("Snooze 15m", TASK, P_SNOOZE, which, emoji="⏰", style=cards.PRIMARY))
    if prompt.is_last_chance:
        row = tuple(button for button in row if button.action != P_SNOOZE)  # there is nothing left to snooze into
    said = text(dose, listed, prompt, now)
    return Card(said, (row,), drawn(dose, listed, prompt, now, said, row))


def drawn(dose: Dose, listed: list[Dose], prompt: Prompt, now: datetime, said: str, row: tuple) -> tuple:
    """The reminder as Components V2 (CARDS_V2), in the round 3 type scale: the
    neutral line stays on top, outside the box and with no page title (it is
    what a lock screen shows); under it one box, amber while it is due and grey
    while it is snoozed, its card title the pill with its day's dots, then the
    dose and its time in bold with how far off it is, then the small lines.
    In round 1 (DESIGN_ROUND=1): the pill's name and the lines as they read, in the box."""
    status = design.QUIET if prompt.snoozed_until is not None else design.DUE
    if design.current() < 3:
        first, name, *rest = said.split("\n")
        return design.notifying(first, design.item(status, name, *rest, row=row))
    first, _, due, *rest = said.split("\n")
    mine = [each for each in listed if each.pill.id == dose.pill.id]
    done = sum(each.occurrence.state in (occurrences.DONE, occurrences.SKIPPED) for each in mine)
    heading = design.card_title(f"💊 {dose.pill.plan.name}", done, len(mine) if len(mine) > 1 else None)
    at = dose.due.at
    when = design.when(timeinput.format_moment(at), at, now) if at is not None else ""
    after = due.partition(" · ")[2] if " · " in due else ""
    which = design.name(f"Dose {dose.number}") + " · " if dose.of > 1 else ""
    lines = [heading, f"{which}{'due ' if at is not None and at <= now else ''}{when}", design.small(after) if after else "", *rest]
    box = design.Box(status, (design.Text("\n".join(line for line in lines if line)), design.Row(tuple(row))))
    return design.bolded(design.notifying(first, box))


# ---------------------------------------------------------------------------
# What is kept (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = "occurrence_id, user_id, day, channel_id, message_id, asked_at, last_at, reminders, snoozed_until, attempts, tried_at"


def _prompt(row: tuple) -> Prompt:
    return Prompt(
        row[0], row[1], date.fromisoformat(row[2]), row[3], row[4], from_db(row[5]), from_db(row[6]), row[7], from_db(row[8]) if row[8] else None,
        row[9] or 0, from_db(row[10]) if row[10] else None,
    )


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
        f"INSERT OR REPLACE INTO pills_prompts ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prompt.occurrence_id, prompt.user_id, prompt.day.isoformat(), prompt.channel_id, prompt.message_id,
            to_db(prompt.asked_at), to_db(prompt.last_at), prompt.reminders, to_db(prompt.snoozed_until) if prompt.snoozed_until else None,
            prompt.attempts, to_db(prompt.tried_at) if prompt.tried_at else None,
        ),
    )


def db_forget(conn: sqlite3.Connection, occurrence_id: int) -> None:
    conn.execute("DELETE FROM pills_prompts WHERE occurrence_id = ?", (occurrence_id,))


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


def cannot_send() -> bool:
    """Whether a reminder that was due could not be posted: there is no hub to post in."""
    return enabled() and _said_no_hub


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


async def _went_through(channel_id: int, line: str, old: Prompt, now: datetime) -> int | None:
    """A try that Discord said had failed and that is in the hub all the same:
    a message of the bot's that is the bare line and nothing else (the pill
    was never written into it), no older than the tries are, and not a
    message kept for any dose. Its id, or None. Raises surface.Failed if the
    hub can't be read: then nothing is posted, for it can't be told."""
    kept = {prompt.message_id for prompt in await database.run(db_prompts)}
    # How long this has been tried for, by the bot's clock; a message's own time is Discord's, the real one
    me, window, real = surface.me(), (now - old.asked_at) + timedelta(minutes=2), clock.real_now()
    for message in await surface.history(channel_id, limit=LOOK_BACK):
        if message.author.id == me and message.id not in kept and (message.content or "").strip() == line and real - message.created_at <= window:
            return message.id
    return None


async def _keep_failed(dose: Dose, channel_id: int, old: Prompt | None, reminders: int, now: datetime, message_id: int | None, why) -> datetime:
    """A try failed: kept, with when, so that it is tried again in its turn. Returns when."""
    first = old is None or not old.attempts
    failed = Prompt(
        dose.occurrence.id, dose.pill.user_id, dose.occurrence.day, channel_id, message_id,
        old.asked_at if old else minute(now),
        # A last chance counts its half hour from its first try; a reminder keeps the time of the copy that is up
        minute(now) if old is None or (reminders == LAST_UP and first) else old.last_at,
        reminders, None, (old.attempts if old else 0) + 1, minute(now),  # to the minute, as every look is
    )
    await database.run(db_keep, failed)
    log.warning("Pills reminders: dose %s could not be posted (try %s): %s. Tried again at %s", dose.occurrence.id, failed.attempts, why, timeinput.format_moment(retry_at(failed)))
    return retry_at(failed)


async def _post(dose: Dose, listed: list[Dose], old: Prompt | None, reminders: int, now: datetime) -> bool | datetime:
    """Put a fresh copy of a dose's prompt up, in place of the one before.
    First the neutral line, which is what notifies (through the notify
    service: Discord, my phone, or held by quiet hours); then the pill is
    written into it. True when it is up; False if there is nowhere to post
    it; when Discord refused, the moment it is tried again.

    A try after one that failed first reads the hub: if that one went
    through after all, it is taken up and finished, and nothing is posted
    a second time."""
    channel_id = hub.channel_id()
    if channel_id is None:
        await _hub_missing(True)
        return False
    line = notice(dose, reminders, by_text(dose, fits_until(dose, listed)))
    message_id = None
    try:
        if old is not None and old.attempts:
            message_id = await _went_through(channel_id, line, old, now)
        if message_id is not None:
            log.info("Pills reminders: an earlier try for dose %s had gone through (message %s): finished, not posted again", dose.occurrence.id, message_id)
            await messages.record(message_id, channel_id)
        else:
            message_id = await notify.post(
                KIND,
                channel_id,
                Card(line),
                user_id=dose.pill.user_id,
                item=attention.Item("a dose is due", attention.TIMED, when=dose.due.at, can_act=True),
                key=str(dose.occurrence.id),
                private=tuple(sorted({each.pill.plan.name for each in listed})),
            )
    except surface.Failed as error:
        return await _keep_failed(dose, channel_id, old, reminders, now, old.message_id if old else None, error)
    await _hub_missing(message_id is None)
    if message_id is None:
        return False
    if old is not None and old.message_id is not None and lifecycle.deletes(MessageClass.ALERT):
        await cards.delete(old.channel_id, old.message_id)
    prompt = Prompt(dose.occurrence.id, dose.pill.user_id, dose.occurrence.day, channel_id, message_id, old.asked_at if old else minute(now), minute(now), reminders)
    await database.run(db_keep, prompt)
    if not await cards.edit(channel_id, message_id, card(dose, listed, prompt, now)):
        # The line is up and the pill is not in it: the next try finds it there and finishes it
        return await _keep_failed(dose, channel_id, replace(prompt, attempts=old.attempts if old else 0), reminders, now, None, "the line was posted, but the pill could not be written into it")
    return True


async def _run(user_id: int) -> tuple[datetime | None, int]:
    """Do what is due for one user. Returns when to look again, and how many prompts were posted."""
    now = clock.now()
    _, listed, day = await checklist.view(user_id)
    kept = {prompt.occurrence_id: prompt for prompt in await database.run(db_prompts, user_id)}
    by_id = {dose.occurrence.id: dose for dose in listed}
    nearest: datetime | None = None
    posted = 0
    for occurrence_id, prompt in kept.items():
        if occurrence_id not in by_id or not enabled():
            # A day that is over, a pill that went, or reminders switched off: nothing of it stays
            await _take_down(prompt)
            log.info("Pills reminders: prompt for dose %s taken down (%s)", occurrence_id, "off" if not enabled() else "no longer today's")
    if not enabled():
        return None, 0
    for dose in listed:
        prompt = kept.get(dose.occurrence.id)
        what, again, reminders = decide(dose, prompt, now, fits_until(dose, listed))
        if what == POST:
            sent = await _post(dose, listed, prompt, reminders, now)
            if sent is True:
                posted += 1
                log.info("Pills reminders: dose %s posted (reminder %s of %s)", dose.occurrence.id, reminders, REMINDERS)
            elif sent is False:
                log.warning("Pills reminders: dose %s is due and there is no hub channel to post in", dose.occurrence.id)
                again = None
            else:
                # Discord refused: when to look again is worked out from what is now kept
                _, again, _ = decide(dose, await database.run(db_prompt, dose.occurrence.id), now, fits_until(dose, listed))
        elif what == STOP:
            # The last reminder went unanswered: the message goes and nothing more is sent. The dose is
            # still to take, so what is kept stays, as over: it is never asked about a second time
            if prompt.message_id is not None and lifecycle.deletes(MessageClass.ALERT):
                await cards.delete(prompt.channel_id, prompt.message_id)
            await database.run(db_keep, replace(prompt, message_id=None, reminders=OVER, snoozed_until=None))
            log.info("Pills reminders: dose %s was not answered after %s reminders: it is still to take, and gets one last chance", dose.occurrence.id, REMINDERS)
            # When that is (if at all) is worked out from what is now kept
            _, again, _ = decide(dose, replace(prompt, message_id=None, reminders=OVER, snoozed_until=None), now, fits_until(dose, listed))
        elif what == LAST:
            sent = await _post(dose, listed, replace(prompt, message_id=None), LAST_UP, now)
            if sent is True:
                posted += 1
                log.info("Pills reminders: dose %s given its last chance", dose.occurrence.id)
            elif sent is False:
                again = None
            else:
                _, again, _ = decide(dose, await database.run(db_prompt, dose.occurrence.id), now, fits_until(dose, listed))
        elif what == END:
            if prompt.message_id is not None and lifecycle.deletes(MessageClass.ALERT):
                await cards.delete(prompt.channel_id, prompt.message_id)
            await database.run(db_keep, replace(prompt, message_id=None, reminders=FINISHED))
            log.info("Pills reminders: the last chance for dose %s has passed: nothing more is sent", dose.occurrence.id)
        elif what == DROP:
            await _take_down(prompt)
            if dose.occurrence.state in (occurrences.DONE, occurrences.SKIPPED):
                # Taken or skipped: if quiet hours had held its reminder back, the briefing lists it no longer
                await notify.dealt_with(user_id, KIND, str(dose.occurrence.id))
            log.info("Pills reminders: prompt for dose %s taken down (dealt with, or past its time)", dose.occurrence.id)
        if again is not None and (nearest is None or again < nearest):
            nearest = again
    return nearest, posted


def job_key(due_at: datetime) -> str:
    """The reminders' one job, as a run with a key: the moment it looks."""
    return f"{TASK}.{JOB}@{to_db(due_at)}"


async def _book(due_at: datetime | None) -> None:
    """One job for the next moment anything is due; none when nothing is. A
    one-off of the scheduler's with a key, so the same look is never booked
    twice. What is done when it runs is still worked out then (`decide`)."""
    pending = await scheduler.pending_jobs(TASK, JOB)
    for extra in pending[1:]:
        await scheduler.cancel_job(extra.id)
    if due_at is None:
        if pending:
            await scheduler.cancel_job(pending[0].id)
    elif pending:
        if pending[0].due_at != due_at:
            await scheduler.reschedule_job(pending[0].id, due_at, job_key(due_at))
    elif await scheduler.add_job(TASK, JOB, due_at, key=job_key(due_at)) is None:
        # A look at this very moment has already run (the clock was moved, or a look ran late and
        # nothing has changed since). It is still wanted: booked as a look of its own
        await scheduler.add_job(TASK, JOB, due_at, key=f"{job_key(due_at)}+{to_db(clock.real_now())}")


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
    await notify.dealt_with(dose.pill.user_id, KIND, str(dose.occurrence.id))
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
    said = await _done(press, dose, checklist.TAKEN, clock.now(), occurrences.BUTTON)
    if design.current() >= 4:
        # Round 4: the line it leaves says when, and a reply to it with a time puts it right
        from tasks.pills import sheet  # the checklist's buttons; it imports this module

        await sheet.correctable_line(press, dose, said)
    return said


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
        another = await plain.logged_lately(listed, dose, now)
        await confirm.show(request, actions.entry(TASK), "pill_log", plain.log_anyway(dose, at, asks, listed, another), frozenset())
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
