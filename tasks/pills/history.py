import logging
from datetime import date, time, timedelta

from core import cards, clock, config, database, hub, messages, occurrences, scheduler, streaks, timetable
from core import day as days
from core.actions import Request
from core.cards import Card
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from core.schedule import ANY_TIME, Due
from tasks.pills import store, today
from tasks.pills.rules import Pill
from tasks.pills.today import TASK, Dose

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Pills, looking back: a day that is over ("what did I take yesterday"), the
# week ("show my week"), the streak, and the weekly summary.
#
# All of it is read from the occurrence log, which is the record: nothing
# here writes, and nothing is asked of Claude. A day is shown as it was
# recorded, whatever has become of the pill since (paused, removed, its plan
# changed); only a dose the bot set aside because the plan no longer called
# for it is left out, as it is for a streak.
#
# The week is Monday to Sunday, the one today is in. The weekly summary
# (behind WEEKLY_SUMMARY, off unless switched on) is the same week, posted in
# the hub on Sunday evening by a schedule like any other: `my schedule`
# moves it.
#
# The streak is counted in days, one for all pills (core/streaks.py): a day
# counts when something was taken and nothing was missed; only a missed dose
# breaks it. It is shown from two days up.
# ---------------------------------------------------------------------------
WEEK_JOB = "weekly"
WEEK_LABEL = "weekly pills summary"
WEEK_AT = time(19, 0)
SUNDAY = 6
# Sunday at 7:00 pm in the hub, without a notification; a Sunday the bot was off for is skipped the next day
DEFAULT = timetable.Default("Weekly pills summary", WEEK_AT, days=(SUNDAY,), missed=timetable.skip_after(5 * 60))
SLOT = "pills.week"  # one at a time in the hub: a newer one takes the older one's place
YESTERDAY, WEEK = "yesterday", "week"
LOOK_BACK = timedelta(days=400)  # how far back a streak is counted
STREAK_FROM = 2  # a streak is worth saying from this many days
MARKS = {DONE: "✅", SKIPPED: "⏭️", MISSED: "❌", PENDING: "▫️"}
NOT_IN_PLAN = "not_in_plan"


# --- pure ------------------------------------------------------------------------------------------------------------
def mine(found: list[Occurrence]) -> list[Occurrence]:
    """The doses that were mine to take: all but those the bot set aside because the plan no longer called for them."""
    return [each for each in found if not (each.state == SKIPPED and each.automatic and each.cause == NOT_IN_PLAN)]


def counted(found: list[Occurrence]) -> str:
    """ "4 of 5 taken · 1 missed · 1 skipped", or "" with nothing to take."""
    found = mine(found)
    if not found:
        return ""
    parts = [f"{sum(each.state == DONE for each in found)} of {len(found)} taken"]
    for state, word in ((MISSED, "missed"), (SKIPPED, "skipped")):
        count = sum(each.state == state for each in found)
        if count:
            parts.append(f"{count} {word}")
    return " · ".join(parts)


def day_name(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _doses(pills: dict[int, Pill], found: list[Occurrence]) -> list[Dose]:
    """A day's rows as doses, for wording them as the checklist does. A dose
    of a pill that has been deleted since has no name left, and is left out."""
    return [Dose(pills[each.item_id], each, Due(None, ANY_TIME)) for each in mine(found) if each.item_id in pills]


def day_text(pills: dict[int, Pill], found: list[Occurrence], day: date, now_day: date) -> str:
    """One day as it was recorded: a heading with the count, and a line a dose."""
    named = {now_day - timedelta(days=1): "Yesterday", now_day: "Today"}.get(day, "")
    listed = _doses(pills, found)
    if not listed:
        return f"💊 Nothing was to take {named.lower()} ({day_name(day)})." if named else f"💊 Nothing was to take on {day_name(day)}."
    head = (f"💊 **{named}** · {day_name(day)}" if named else f"💊 **{day_name(day)}**") + f" · {counted(found)}"
    listed.sort(key=lambda dose: (dose.occurrence.actual_at is None, dose.occurrence.actual_at or days.start_of(day), dose.pill.plan.name.lower(), dose.number))
    return "\n".join([head, *(today.line(dose) for dose in listed)])


def week_of(day: date) -> tuple[date, date]:
    """Monday to Sunday of the week a day is in."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def streak_line(run: int) -> str:
    """The streak in a line, or "" while it is not worth saying."""
    return f"🔥 Streak · {run} days" if run >= STREAK_FROM else ""


def week_text(found: list[Occurrence], now_day: date, run: int = 0, title: str = "This week") -> str:
    """The week today is in, a line a day up to today: a mark a dose, and the
    count. Days still to come are left out."""
    monday, sunday = week_of(now_day)
    by_day: dict[date, list[Occurrence]] = {}
    for each in mine(found):
        if monday <= each.day <= now_day:
            by_day.setdefault(each.day, []).append(each)
    so_far = [each for rows in by_day.values() for each in rows]
    span = f"{monday:%a} {monday.day} – {sunday:%a} {sunday.day} {sunday:%b}"
    lines = [f"💊 **{title}** · {span}" + (f" · {counted(so_far)}" if so_far else "")]
    if not so_far:
        return "\n".join([*lines, "Nothing was to take this week."])
    day = monday
    while day <= now_day:
        rows = sorted(by_day.get(day, []), key=lambda each: (each.item_id, each.seq))
        if rows:
            taken = sum(each.state == DONE for each in rows)
            left = " so far" if day == now_day and any(each.state == PENDING for each in rows) else ""
            lines.append(f"`{day:%a} {day.day:>2}` {''.join(MARKS.get(each.state, '▫️') for each in rows)} {taken} of {len(rows)}{left}")
        else:
            lines.append(f"`{day:%a} {day.day:>2}` nothing to take")
        day += timedelta(days=1)
    said = streak_line(run)
    return "\n".join([*lines, *([said] if said else [])])


# --- reading ---------------------------------------------------------------------------------------------------------
def db_names(conn, user_id: int) -> dict[int, Pill]:
    """Every pill there has been, removed ones too: a day is shown as it was."""
    return {pill.id: pill for pill in store.db_pills(conn, user_id, include_removed=True)}


async def streak_days(user_id: int, now_day: date) -> int:
    """How many days in a row, up to today, something was taken and nothing missed."""
    found = await database.run(occurrences.db_between, user_id, TASK, now_day - LOOK_BACK, now_day)
    return streaks.streak(mine(found), now_day).days


async def yesterday(user_id: int) -> str:
    now_day = days.today()
    day = now_day - timedelta(days=1)
    return day_text(await database.run(db_names, user_id), await occurrences.for_day(user_id, TASK, day), day, now_day)


async def week(user_id: int, title: str = "This week") -> str:
    now_day = days.today()
    monday, _ = week_of(now_day)
    found = await database.run(occurrences.db_between, user_id, TASK, monday, now_day)
    return week_text(found, now_day, await streak_days(user_id, now_day), title)


async def show(request: Request, data: dict, guessed: frozenset) -> str:
    """ "what did I take yesterday?", "show my week": answered from the record, in a line a dose or a day."""
    if data.get("period") == WEEK:
        return await week(request.user.id)
    return await yesterday(request.user.id)


# --- the weekly summary ----------------------------------------------------------------------------------------------
def enabled() -> bool:
    return config.WEEKLY_SUMMARY


async def week_job(job: scheduler.Job) -> None:
    """Scheduler handler: Sunday evening's summary of the week, in the hub.
    A week with nothing to take posts nothing, and says so in the log."""
    if not enabled():
        scheduler.note(job, "off (WEEKLY_SUMMARY)")
        log.info("Weekly pills summary: off (WEEKLY_SUMMARY), nothing posted")
        return
    where = hub.channel_id()
    if where is None:
        scheduler.report(job, scheduler.SKIPPED)
        scheduler.note(job, "not posted: the hub channel is not set")
        return
    posted = 0
    for user_id in await database.run(store.db_users):
        now_day = days.today()
        monday, _ = week_of(now_day)
        found = mine(await database.run(occurrences.db_between, user_id, TASK, monday, now_day))
        if not found:
            log.info("Weekly pills summary, job %s, user %s: nothing was to take this week, nothing posted", job.id, user_id)
            continue
        text = week_text(found, now_day, await streak_days(user_id, now_day), "Your week")
        message_id = await cards.send(where, Card(text), silent=job.notify != timetable.NOTIFY)
        await messages.record(message_id, where, lifetime=messages.REPLACED, slot=SLOT, task=TASK, user_id=user_id)
        posted += 1
        log.info("Weekly pills summary, job %s, user %s: posted (%s)", job.id, user_id, text.splitlines()[0])
    scheduler.note(job, f"posted for {posted}" if posted else "nothing was to take this week")


def register() -> None:
    """The schedule only while it is switched on; the handler always (the
    task gives it), so a run booked before it went off says "off"."""
    if enabled():
        scheduler.default_schedule(TASK, WEEK_JOB, DEFAULT)
