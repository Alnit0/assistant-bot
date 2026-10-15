import logging
from datetime import date, datetime, timedelta

from core import attention, clock, config, database, repeats, scheduler, summaries, timeinput
from core import day as days
from core.actions import SEE, Summary
from core.attention import PROBLEM, TIMED, Item
from core.context import Context
from core.design import ANY_TIME, DONE, DUE
from tasks.base import ANY, Keyword, Task
from tasks.calendar import plain, rules, source, store
from tasks.calendar.rules import ICON, TASK, TITLE

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The calendar (docs/specs/calendar.md, private), behind CALENDAR_ENABLED:
# off, it is not loaded at all. Read only, from the calendar's secret iCal
# link (CALENDAR_ICS_URL, in live's .env only), through a source that can be
# swapped later (source.py).
#
#   Reading   on start-up and every 15 minutes (a run booked by the engine,
#             one at a time). The copy is replaced whole on a good read; a
#             read that fails keeps the last good copy and is not an alert
#             until it has failed for 6 hours, then it needs a look.
#   The hub   today's events on the Today card, the briefing's line (a count
#             and the first time), and attention: an event starting in the
#             next 30 minutes is level 3, with only its time on the status
#             line. Never an event's name anywhere a lock screen can show.
#   Words     questions only (plain.py): no event's name goes to Claude.
#
# No reminders before events yet.
# ---------------------------------------------------------------------------
FETCH = "fetch"
EVERY = timedelta(minutes=15)


def enabled() -> bool:
    return bool(config.CALENDAR_ENABLED)


async def update(user_id: int) -> str:
    """Read the feed and keep the copy. Returns "" if that worked, else why not in words that
    never hold the link; the last good copy stays. Never raises."""
    found = source.current()
    now = clock.now()
    if found is None:
        await database.run(store.db_failed, user_id, "no calendar link is set", now)
        return "no calendar link is set"
    today = days.day_of(now)
    try:
        events = await found.events(today - timedelta(days=rules.BEHIND_DAYS), today + timedelta(days=rules.AHEAD_DAYS))
    except source.FetchFailed as error:
        why = str(error)
    except Exception as error:
        why = f"it could not be read ({type(error).__name__})"
    else:
        await database.run(store.db_keep, user_id, events, now)
        summaries.changed(TASK, user_id)
        attention.changed()
        return ""
    log.warning("Calendar: not read (%s); the last copy stays", why)
    await database.run(store.db_failed, user_id, why, now)
    attention.changed()
    return why


async def _owner(job: scheduler.Job) -> int | None:
    return job.user_id or await database.run(scheduler._db_owner)


async def fetch_job(job: scheduler.Job) -> None:
    """Scheduler handler: read the feed, and book the next read in 15 minutes."""
    user_id = await _owner(job)
    await scheduler.ensure(TASK, FETCH, clock.now() + EVERY)
    if user_id is None:
        scheduler.note(job, "not read: there is no owner yet")
        return
    wrong = await update(user_id)
    if wrong:
        scheduler.note(job, f"not read ({wrong}): the last copy stays; again in 15 minutes")
        return
    read = await database.run(store.db_read, user_id)
    scheduler.note(job, f"read: {rules.count_text(read[3] if read else 0)} kept; again in 15 minutes")


async def summary(user_id: int, day: date) -> Summary | None:
    """The briefing's line: how many events there are that day, and the first one's time."""
    found = rules.on_day(await store.events(user_id), day)
    if not found:
        return None
    timed = [each for each in found if not each.all_day and days.day_of(each.start) == day]
    glance = rules.count_text(len(found)) + (f" · first {timeinput.format_moment(timed[0].start)}" if timed else " · all day")
    now = clock.now()
    upcoming = [each for each in timed if each.end > now]
    status = DUE if upcoming else ANY_TIME if not timed else DONE
    return Summary(glance, status)


async def items(user_id: int, now: datetime) -> list[Item]:
    """An event starting in the next 30 minutes (level 3), its time only; a feed not read for
    6 hours (a problem: it needs a look)."""
    found = []
    read = await database.run(store.db_read, user_id)
    if read is not None and read[1] is not None and now - read[1] >= rules.STALE:
        found.append(Item("calendar not read for 6 hours", PROBLEM, read[1], can_act=False, short=("calendar not read",)))
    for each in rules.coming(await store.events(user_id), now):
        if each.start - now > rules.SOON:
            break
        found.append(Item("calendar event soon", TIMED, each.start, can_act=False, short=(attention.short_time(each.start),)))
    return found


async def today_lines(user_id: int, now: datetime) -> list:
    """For the Today card: today's events, all-day ones in its small line at the top."""
    from core.today import Line

    found = rules.on_day(await store.events(user_id), days.day_of(now))
    return [
        Line(ICON, f"**{each.title}**", all_day=True) if each.all_day else Line(ICON, f"**{each.title}**", each.start, each.end if each.end > each.start else None, event=True)
        for each in found
    ]


async def show_word(ctx: Context) -> str:
    await ctx.reply(rules.day_answer(await store.events(ctx.user.id), days.today(), days.today()))
    return "shown"


class CalendarTask(Task):
    """The calendar, read only: what is on, in the hub and in words."""

    name = TASK
    title = TITLE
    description = "Calendar: your events, read only, on the Today card, in the briefing and in answers"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    show = "calendar_show"
    identity = ()  # it adds nothing
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return enabled()

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return []  # an event's name is never handed on: the router and extraction never see one

    def keywords(self) -> list[Keyword]:
        return [Keyword(["calendar", "my calendar"], "what is on your calendar today", show_word, examples=["calendar"], channels=ANY, exact=True, purpose=SEE)]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {FETCH: fetch_job}

    def job_labels(self):
        return {FETCH: "calendar read"}

    async def startup(self, client) -> None:
        # A read now, and from it one every 15 minutes: one booked at a time
        await scheduler.ensure(TASK, FETCH, clock.now())

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def today(self, user_id, now):
        return await today_lines(user_id, now)


task = CalendarTask()
