import logging
from datetime import date, datetime, time, timedelta

from core import cards, clock, database, hub, lifecycle, live, llm, occurrences, scheduler, timeinput
from core import day as days
from core import schedule as core_schedule
from core.cards import Button, Card
from core.errors import UserError
from core.lifecycle import MessageClass
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from tasks.pills import doses as limits
from tasks.pills import rules, store, today
from tasks.pills.rules import Pill
from tasks.pills.store import CHECKLIST, DOSE
from tasks.pills.today import TASK, Dose

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Pills: the daily checklist. One message for today in the hub, edited in
# place whenever anything changes, with a message of its own under it for each
# dose that has no time (Taken / Skip). It is posted at 6:00 am without a
# notification, when the bot starts later than that, and afresh when asked
# for: the old copy goes, so there is only ever one for today.
#
# Every time and date here comes from the one clock (core/clock.py, through
# core/day.py), which is the clock `dev clock` moves. A day that is over is
# closed by the rollover and, failing that, by whatever looks at today next
# (close_past): nothing depends on a job having run.
#
# The checklist is never the record: a dose is a row of the occurrence log
# (core/occurrences.py), changed only through it, and what is shown is
# written again from the pills and those rows each time (tasks/pills/today.py).
# Where the messages are is kept in pills_messages, so a restart finds them.
#
# No discord.py: messages and buttons go through core/cards.py.
# ---------------------------------------------------------------------------
POST_AT = time(6, 0)
JOB = "checklist"
LIMIT_JOB = "limit"  # looks again when a pill's latest time passes
TAKEN, SKIP, NOT_TAKEN = "taken", "skipped", "not_taken"


# ---------------------------------------------------------------------------
# The day's doses
# ---------------------------------------------------------------------------
def db_sync(conn, user_id: int, day: date, now: datetime) -> tuple[list[Pill], list[Occurrence]]:
    """Make sure every dose the plans call for on `day` has its occurrence
    (asking twice never makes a second or resets one), and read them all."""
    pills = store.db_pills(conn, user_id)
    for pill in pills:
        for number, planned in today.wanted(pill, day):
            occurrences.db_ensure(conn, user_id, TASK, pill.id, day, number, planned, now=now)
    if day == days.day_of(now):
        db_settle(conn, user_id, pills, day, now)
    return pills, occurrences.db_for_day(conn, user_id, TASK, day)


def db_settle(conn, user_id: int, pills: list[Pill], day: date, now: datetime) -> None:
    """No dose is left waiting once it can't be taken today: it is skipped with
    the reason, or missed if the pill's limit passed with nothing taken; and
    one the bot had closed comes back if there is room for it again
    (tasks/pills/doses.py). Only what really differs is written."""
    found: dict[int, dict[int, Occurrence]] = {}
    for occurrence in occurrences.db_for_day(conn, user_id, TASK, day):
        found.setdefault(occurrence.item_id, {})[occurrence.seq] = occurrence
    for pill in pills:
        mine = found.get(pill.id)
        if not mine or not rules.is_taken_on(pill, day):
            continue
        for number, (state, reason) in limits.outcomes(pill.plan.schedule, day, mine, now).items():
            dose = mine[number]
            if state == dose.state and (state != SKIPPED or dose.reason == reason):
                continue
            if state == PENDING:
                occurrences.db_reopen(conn, dose.id, occurrences.AUTOMATIC, now=now)
            elif state == SKIPPED:
                occurrences.db_skip(conn, dose.id, occurrences.AUTOMATIC, automatic=True, reason=reason, now=now)
            else:
                occurrences.db_miss(conn, dose.id, now=now)


async def view(user_id: int, day: date | None = None) -> tuple[list[Pill], list[Dose], date]:
    """The user's pills and the day's doses as they stand now (today, unless
    told). Any earlier day still open is closed first."""
    await close_past()
    now = clock.now()
    day = day or days.today(now)
    pills, found = await database.run(db_sync, user_id, day, now)
    return pills, today.doses(pills, found, day), day


# ---------------------------------------------------------------------------
# The messages
# ---------------------------------------------------------------------------
def dose_card(dose: Dose) -> Card:
    """The message a dose with no time gets: no snooze, there is no time pressure."""
    which = str(dose.occurrence.id)
    return Card(
        today.dose_text(dose),
        ((Button("Taken", TASK, TAKEN, which, emoji="✅", style=cards.SUCCESS), Button("Skip", TASK, SKIP, which, emoji="⏭️", style=cards.PRIMARY)),),
    )


async def _remove(message: store.Message) -> None:
    """Take one of our messages away and forget where it was."""
    if lifecycle.deletes(MessageClass.LIVE if message.kind == CHECKLIST else MessageClass.ALERT):
        await cards.delete(message.channel_id, message.message_id)
    await database.run(store.db_drop_message, message.message_id)


async def _dose_messages(user_id: int, day: date, listed: list[Dose], held: list[store.Message], channel_id: int) -> None:
    """One message for each dose with no time that is still to take, and none for any other."""
    want = {dose.occurrence.id: dose for dose in listed if dose.is_pending and dose.is_untimed}
    have = {message.occurrence_id: message for message in held if message.kind == DOSE}
    for occurrence_id, message in have.items():
        if occurrence_id not in want:
            await _remove(message)
    for occurrence_id, dose in want.items():
        if occurrence_id not in have:
            message_id = await cards.send(channel_id, dose_card(dose), silent=True)
            if message_id is not None:
                await database.run(store.db_add_message, user_id, day, DOSE, occurrence_id, channel_id, message_id)


async def post(user_id: int, channel_id: int | None = None) -> int | None:
    """A fresh copy of today's checklist at the bottom of the hub (of
    `channel_id` when no hub is set), without a notification, and under it a
    message for each dose with no time. The old copy and its messages go:
    there is only ever one checklist for today. Returns the message's id."""
    channel_id = hub.channel_id() or channel_id
    if channel_id is None:
        return None
    pills, listed, day = await view(user_id)
    for old in await database.run(store.db_messages, user_id, day):
        await _remove(old)
    message_id = await cards.send(channel_id, Card(today.checklist(listed, pills, day)), silent=True)
    if message_id is None:
        return None
    await database.run(store.db_add_message, user_id, day, CHECKLIST, None, channel_id, message_id)
    await _dose_messages(user_id, day, listed, [], channel_id)
    await book_limit(pills, day)
    return message_id


async def refresh(user_id: int) -> None:
    """Bring today's checklist and the messages under it up to date in place.
    Nothing to do if it hasn't been posted today; posted afresh if it has gone."""
    pills, listed, day = await view(user_id)
    held = await database.run(store.db_messages, user_id, day)
    sheet = next((message for message in held if message.kind == CHECKLIST), None)
    if sheet is None:
        return
    if not await cards.edit(sheet.channel_id, sheet.message_id, Card(today.checklist(listed, pills, day))):
        log.info("Today's pills checklist has gone from channel %s: posting it again", sheet.channel_id)
        await database.run(store.db_drop_message, sheet.message_id)
        await post(user_id, sheet.channel_id)
        return
    await _dose_messages(user_id, day, listed, held, sheet.channel_id)
    await book_limit(pills, day)


async def book_limit(pills: list[Pill], day: date) -> None:
    """Look again when the next latest time of today has passed, so that what is
    left then is closed on the checklist without anyone having to ask."""
    now = clock.now()
    coming = [
        moment for pill in pills if rules.is_taken_on(pill, day) and pill.plan.schedule.latest is not None
        for moment in [core_schedule.limit(pill.plan.schedule, day)] if moment > now
    ]
    if coming:
        # A minute past it: "not after 4:00 pm" still holds at 4:00 pm
        await scheduler.ensure(TASK, LIMIT_JOB, min(coming) + timedelta(minutes=1))


async def limit_job(job: scheduler.Job) -> None:
    """Scheduler handler: a pill's latest time has passed. Each checklist is
    brought up to date, which closes what can't be taken any more and books
    the next look."""
    for user_id in await database.run(store.db_users):
        await refresh(user_id)


async def channel_cleared(channel_id: int, gone: set[int]) -> None:
    """The channel was reset: if today's checklist or one of its Taken / Skip
    messages went with it, post the whole of it afresh there. `post` forgets
    the old messages, so the records point at the new ones only."""
    day = days.today(clock.now())
    for user_id in await database.run(store.db_users):
        held = await database.run(store.db_messages, user_id, day)
        if any(message.channel_id == channel_id and message.message_id in gone for message in held):
            await post(user_id, channel_id)


def changed(user_id: int) -> None:
    """A pill or a dose changed: bring the checklist up to date, in the background."""
    live.schedule(("pills-checklist", user_id), lambda: refresh(user_id))


# ---------------------------------------------------------------------------
# Marking a dose
# ---------------------------------------------------------------------------
def db_mark(conn, occurrence_id: int, did: str, at: datetime, source: str) -> Occurrence:
    """Mark a dose taken (at `at`), skipped, or not taken after all, and read it back."""
    if did == TAKEN:
        occurrences.db_done(conn, occurrence_id, at, source)
    elif did == SKIP:
        occurrences.db_skip(conn, occurrence_id, source)
    else:
        occurrences.db_reopen(conn, occurrence_id, source)
    return occurrences.db_get(conn, occurrence_id)


_STATE = {TAKEN: DONE, SKIP: SKIPPED, NOT_TAKEN: PENDING}


async def mark(dose: Dose, did: str, at: datetime, source: str) -> Dose:
    """Change a dose and return it as the database now has it. Raises UserError
    if it didn't save: nothing is said to have happened that didn't."""
    after = await database.run(db_mark, dose.occurrence.id, did, at, source)
    if after is None or after.state != _STATE[did] or (did == TAKEN and after.actual_at != at):
        raise UserError(f"That didn't save: {rules.plain(dose.label)} is still {dose.occurrence.state}.")
    return Dose(dose.pill, after, dose.due)


def db_correct(conn, occurrence_id: int, at: datetime, source: str) -> Occurrence:
    occurrences.db_change(conn, occurrence_id, occurrences.CORRECTED, source, actual_at=at)
    return occurrences.db_get(conn, occurrence_id)


async def correct(dose: Dose, at: datetime, source: str) -> Dose:
    """Change when a dose already ticked off was taken, and return it as the
    database now has it. Raises UserError if it didn't save."""
    after = await database.run(db_correct, dose.occurrence.id, at, source)
    if after is None or after.state != DONE or after.actual_at != at:
        raise UserError(f"That didn't save: {rules.plain(dose.label)} is still as it was.")
    return Dose(dose.pill, after, dose.due)


def corrected_text(dose: Dose, was: datetime) -> str:
    """A correction in one line: what it was, and what it is now."""
    return f"✏️ {dose.label} · taken {timeinput.format_moment(was)} → {timeinput.format_moment(dose.occurrence.actual_at)}"


def marked_text(dose: Dose, did: str) -> str:
    """What marking a dose did, in one line."""
    if did == NOT_TAKEN:
        return f"↩️ {dose.label} · no longer ticked off"
    return today.line(dose)


async def _pressed(press: cards.Press, did: str) -> str:
    """Taken or Skip on a dose's own message: the message goes, the checklist changes."""
    _, listed, _ = await view(press.user.id)
    dose = next((each for each in listed if str(each.occurrence.id) == press.arg), None)
    if dose is None or not dose.is_pending:
        # Dealt with already (by a message, or from another copy): there is nothing left to press
        await press.remove()
        if press.message_id is not None:
            await database.run(store.db_drop_message, press.message_id)
        return "already dealt with"
    after = await mark(dose, did, clock.now(), occurrences.BUTTON)
    await press.remove()
    if press.message_id is not None:
        await database.run(store.db_drop_message, press.message_id)
    await refresh(press.user.id)
    said = marked_text(after, did)
    # So that the next message isn't answered as if this were still waiting
    llm.remember(press.channel_id, f"(pressed {'Taken' if did == TAKEN else 'Skip'} on {rules.plain(dose.label)})", said)
    llm.task_answered(press.channel_id, TASK)
    return said


async def on_taken(press: cards.Press) -> str:
    return await _pressed(press, TAKEN)


async def on_skip(press: cards.Press) -> str:
    return await _pressed(press, SKIP)


def register() -> None:
    cards.register(TASK, TAKEN, on_taken)
    cards.register(TASK, SKIP, on_skip)
    # The 6:00 am post is booked for "the next 6:00 am": booked again if the clock goes back
    scheduler.keep_booked(f"{TASK}/{JOB}", book_next)


# ---------------------------------------------------------------------------
# 6:00 am, a late start, and the end of the day
# ---------------------------------------------------------------------------
async def _post_if_due(user_id: int) -> None:
    """Post today's checklist unless it is there already or there is nothing on it."""
    pills, listed, day = await view(user_id)
    if any(message.kind == CHECKLIST for message in await database.run(store.db_messages, user_id, day)):
        await refresh(user_id)
    elif listed:
        await post(user_id)


async def book_next() -> None:
    """Make sure the next 6:00 am post is booked, as the clock now reads."""
    await scheduler.ensure(TASK, JOB, scheduler.next_run(POST_AT, clock.now()))


async def post_job(job: scheduler.Job) -> None:
    """Scheduler handler: 6:00 am. Post each user's checklist, then book tomorrow's."""
    try:
        for user_id in await database.run(store.db_users):
            await _post_if_due(user_id)
    finally:
        await book_next()


async def startup() -> None:
    """When the bot starts: book 6:00 am, and post today's checklist if that time has passed."""
    await book_next()
    if hub.channel_id() is None:
        log.info("HUB_CHANNEL_ID is not set: the pills checklist is only posted when asked for")
        return
    now = clock.now()
    if now >= days.at(days.today(now), POST_AT):
        for user_id in await database.run(store.db_users):
            await _post_if_due(user_id)


def db_close(conn, started: date, now: datetime) -> list[store.Message]:
    """The days before `started` are over. Each dose still open is closed as
    it stood when its pill's day ran out (tasks/pills/doses.py): missed if
    it had its time, set aside with the reason if it never could have been
    taken in time, and set aside if it is no longer in its pill's plan.
    Neither kind of setting aside breaks a streak. Returns the messages those
    days left behind."""
    pills = {pill.id: pill for pill in store.db_all_pills(conn)}
    decided: dict[tuple[date, int], dict] = {}
    for left in occurrences.db_pending_before(conn, TASK, started):
        pill = pills.get(left.item_id)
        if pill is None or left.seq not in [number for number, _ in today.wanted(pill, left.day)]:
            occurrences.db_skip(conn, left.id, occurrences.AUTOMATIC, automatic=True, reason="no longer in the plan", now=now)
            continue
        key = (left.day, left.item_id)
        if key not in decided:
            mine = {each.seq: each for each in occurrences.db_for_day(conn, left.user_id, TASK, left.day, left.item_id)}
            plan = pill.plan.schedule
            # As things stood the moment the pill's day was over
            decided[key] = limits.outcomes(plan, left.day, mine, core_schedule.limit(plan, left.day) + timedelta(seconds=1))
        state, reason = decided[key].get(left.seq, (MISSED, None))
        if state == SKIPPED:
            occurrences.db_skip(conn, left.id, occurrences.AUTOMATIC, automatic=True, reason=reason, now=now)
        else:
            occurrences.db_miss(conn, left.id, now=now)
    return store.db_messages_before(conn, started)


async def close_past() -> None:
    """Close every day before today that is still open: what was untouched is
    missed, the messages for single doses go, and each old checklist is
    written one last time and left as it is. Safe to ask at any time, and
    asked before anything is shown or marked: a day is over because the
    clock says so, not because a job happened to run."""
    now = clock.now()
    for message in await database.run(db_close, days.today(now), now):
        if message.kind == CHECKLIST:
            pills = await store.pills(message.user_id)
            found = await occurrences.for_day(message.user_id, TASK, message.day)
            text = today.checklist(today.doses(pills, found, message.day), pills, message.day)
            await cards.edit(message.channel_id, message.message_id, Card(text))
            await database.run(store.db_drop_message, message.message_id)
        else:
            await _remove(message)


async def new_day(ended: date, started: date) -> None:
    """A day has ended (core/day.py): close it."""
    await close_past()
