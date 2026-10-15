import logging
from datetime import date, time, timedelta

from core import cards, clock, config, database, design, hub, messages, occurrences, scheduler, streaks, timetable
from core import day as days
from core.actions import LiveReply, Request
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
SLOT = "pills.week"  # the week's slot, kept for what was posted under it before 16 Oct
# The Sunday summary is news of the moment: posted at the bottom of the hub, once, and gone at the
# next morning's tidy (question 91), never moved above the cards that come up after it
YESTERDAY, WEEK = "yesterday", "week"
LOOK_BACK = timedelta(days=400)  # how far back a streak is counted
STREAK_FROM = 2  # a streak is worth saying from this many days
MARKS = {DONE: "✅", SKIPPED: "⏭️", MISSED: "❌", PENDING: "▫️"}
NOT_IN_PLAN = "not_in_plan"


# --- pure ------------------------------------------------------------------------------------------------------------
def mine(found: list[Occurrence]) -> list[Occurrence]:
    """The doses that were mine to take: all but those the bot set aside because the plan no longer called for them."""
    return [each for each in found if not (each.state == SKIPPED and each.automatic and each.cause == NOT_IN_PLAN)]


def tallied(found: list[Occurrence]) -> tuple[int, int] | None:
    """(dealt with, all) of the doses that were mine to take, as the checklist counts a day:
    taken and skipped are dealt with. None with nothing to take."""
    found = mine(found)
    if not found:
        return None
    return sum(each.state in (DONE, SKIPPED) for each in found), len(found)


async def tally(user_id: int, day: date) -> tuple[int, int] | None:
    """A day as it was recorded, whatever has become of the pills since."""
    return tallied(await occurrences.for_day(user_id, TASK, day))


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


# --- the same, drawn (docs/DESIGN.md; only with CARDS_V2 on) -----------------------------------------------------------
STATUS = {DONE: design.DONE, MISSED: design.MISSED, SKIPPED: design.QUIET, PENDING: design.ANY_TIME}
FOLD_AFTER = 12


def status_of(rows: list[Occurrence]) -> str:
    """A day's colour: red when something was missed, blue while something is
    still to take, green when something was taken, otherwise quiet."""
    states = {each.state for each in rows}
    for state in (MISSED, PENDING, DONE):
        if state in states:
            return STATUS[state]
    return design.QUIET


def day_layout(pills: dict[int, Pill], found: list[Occurrence], day: date, now_day: date) -> tuple:
    """One day: the count in the heading, a box a dose in the colour of what became of it."""
    text = day_text(pills, found, day, now_day).splitlines()
    named = {now_day - timedelta(days=1): "Yesterday", now_day: "Today"}.get(day, day_name(day))
    listed = _doses(pills, found)
    if not listed:
        return design.standing(f"💊 {named}", day_name(day), [design.item(design.QUIET, text[0].removeprefix("💊 "))])
    listed.sort(key=lambda dose: (dose.occurrence.actual_at is None, dose.occurrence.actual_at or days.start_of(day), dose.pill.plan.name.lower(), dose.number))
    if len(listed) > FOLD_AFTER:
        boxes = [design.item(status_of([dose.occurrence for dose in listed]), *text[1:])]
    else:
        boxes = [design.item(STATUS.get(dose.occurrence.state, design.QUIET), today.line(dose)) for dose in listed]
    return design.standing(f"💊 {named} · {counted(found)}", day_name(day), boxes)


def week_layout(found: list[Occurrence], now_day: date, run: int = 0, title: str = "This week") -> tuple:
    """The week: the count in the heading, a box a day in the colour of how it went, the streak under them."""
    lines = week_text(found, now_day, run, title).splitlines()
    head, span, *count = [part.strip() for part in lines[0].removeprefix("💊 ").replace("**", "").split(" · ")]
    monday, _ = week_of(now_day)
    by_day: dict[date, list[Occurrence]] = {}
    for each in mine(found):
        by_day.setdefault(each.day, []).append(each)
    day_lines = [line for line in lines[1:] if line.startswith("`")]
    if not day_lines:
        return design.standing(f"💊 {head}", span, [design.item(design.QUIET, lines[1])])
    boxes = []
    for offset, line in enumerate(day_lines):
        day = monday + timedelta(days=offset)
        name, _, rest = line.removeprefix("`").partition("` ")
        boxes.append(design.item(status_of(by_day.get(day, [])), f"**{' '.join(name.split())}** · {rest}"))
    return design.standing(f"💊 {head}" + (f" · {' · '.join(count)}" if count else ""), span, boxes, hint=streak_line(run))


# --- reading ---------------------------------------------------------------------------------------------------------
def db_names(conn, user_id: int) -> dict[int, Pill]:
    """Every pill there has been, removed ones too: a day is shown as it was."""
    return {pill.id: pill for pill in store.db_pills(conn, user_id, include_removed=True)}


async def streak_days(user_id: int, now_day: date) -> int:
    """How many days in a row, up to today, something was taken and nothing missed."""
    found = await database.run(occurrences.db_between, user_id, TASK, now_day - LOOK_BACK, now_day)
    return streaks.streak(mine(found), now_day).days


async def yesterday_card(user_id: int) -> Card:
    now_day = days.today()
    day = now_day - timedelta(days=1)
    pills, found = await database.run(db_names, user_id), await occurrences.for_day(user_id, TASK, day)
    return Card(day_text(pills, found, day, now_day), (), day_layout(pills, found, day, now_day))


async def yesterday(user_id: int) -> str:
    return (await yesterday_card(user_id)).text


async def week_card(user_id: int, title: str = "This week") -> Card:
    now_day = days.today()
    monday, _ = week_of(now_day)
    found = await database.run(occurrences.db_between, user_id, TASK, monday, now_day)
    run = await streak_days(user_id, now_day)
    return Card(week_text(found, now_day, run, title), (), week_layout(found, now_day, run, title))


async def week(user_id: int, title: str = "This week") -> str:
    return (await week_card(user_id, title)).text


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    """ "what did I take yesterday?", "show my week": answered from the record,
    a line a dose or a day. A card: its words, and the same drawn with CARDS_V2 on."""
    period = WEEK if data.get("period") == WEEK else YESTERDAY
    shown = await (week_card(request.user.id) if period == WEEK else yesterday_card(request.user.id))
    return LiveReply(f"pills.{period}", shown.text, shown)


# --- the week of everything (core/weekly.py) -----------------------------------------------------------------------
LATE_AFTER = timedelta(minutes=30)  # a dose taken this long after its time is late


def late(found: list[Occurrence]) -> int:
    """How many doses were taken late: half an hour or more after they were due."""
    return sum(1 for each in found if each.state == DONE and each.due_at is not None and each.actual_at is not None and each.actual_at - each.due_at >= LATE_AFTER)


def week_line(taken: int, total: int, late_: int, missed: int, skipped: int, run: int):
    """Pills' line in the week of everything: "18 of 21 taken · 2 late · 1 missed", the streak small."""
    from core.weekly import Week

    parts = [f"{taken} of {total} taken"] + [f"{count} {word}" for count, word in ((late_, "late"), (missed, "missed"), (skipped, "skipped")) if count]
    status = design.MISSED if missed else design.DONE if taken + skipped == total else design.QUIET
    return Week(" · ".join(parts), taken + skipped, total, streak_line(run), status)


async def week_of_pills(user_id: int, monday: date, upto: date):
    found = mine(await database.run(occurrences.db_between, user_id, TASK, monday, upto))
    if not found:
        return None
    return week_line(
        sum(each.state == DONE for each in found), len(found), late(found), sum(each.state == MISSED for each in found),
        sum(each.state == SKIPPED for each in found), await streak_days(user_id, upto),
    )


async def everything_card(user_id: int, now_day: date) -> Card | None:
    """The week of everything for the summary, or None when no task has anything to say."""
    from core import weekly

    monday, _ = week_of(now_day)
    sections = await weekly.gather(user_id, monday, now_day)
    if not sections:
        return None
    sunday = weekly.sunday_of(monday)
    return Card(weekly.text(sections, monday, sunday), (), weekly.layout(sections, monday, sunday))


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
        if config.WEEKLY_ALL:
            card = await everything_card(user_id, now_day)
            if card is None:
                log.info("Weekly summary, job %s, user %s: no task had anything this week, nothing posted", job.id, user_id)
                continue
            message_id = await cards.send(where, card, silent=job.notify != timetable.NOTIFY)
            await messages.record(message_id, where, lifetime=messages.DAY, task=TASK, user_id=user_id)
            posted += 1
            log.info("Weekly summary of everything, job %s, user %s: posted", job.id, user_id)
            continue
        monday, _ = week_of(now_day)
        found = mine(await database.run(occurrences.db_between, user_id, TASK, monday, now_day))
        if not found:
            log.info("Weekly pills summary, job %s, user %s: nothing was to take this week, nothing posted", job.id, user_id)
            continue
        run = await streak_days(user_id, now_day)
        text = week_text(found, now_day, run, "Your week")
        message_id = await cards.send(where, Card(text, (), week_layout(found, now_day, run, "Your week")), silent=job.notify != timetable.NOTIFY)
        await messages.record(message_id, where, lifetime=messages.DAY, task=TASK, user_id=user_id)
        posted += 1
        log.info("Weekly pills summary, job %s, user %s: posted (%s)", job.id, user_id, text.splitlines()[0])
    scheduler.note(job, f"posted for {posted}" if posted else "nothing was to take this week")


def register() -> None:
    """The schedule only while it is switched on; the handler always (the
    task gives it), so a run booked before it went off says "off"."""
    if enabled():
        scheduler.default_schedule(TASK, WEEK_JOB, DEFAULT)
