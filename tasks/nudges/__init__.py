from datetime import date, datetime

from core import attention, clock, config, database, hub, hubcard, repeats, scheduler, timeinput
from core import day as days
from core.actions import SEE, Summary
from core.attention import TIMED, Item
from core.context import Context
from core.design import DUE, QUIET
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.nudges import expiry, plain, rules, store
from tasks.nudges.rules import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# Reminders I set myself (docs/specs/reminders.md, private), behind
# NUDGES_ENABLED: off, the task is not loaded at all. The folder is `nudges`
# because REMINDERS_ENABLED and tasks/pills/reminders.py are the pills' own;
# everywhere I read it, it is "Reminders".
#
#   "remind me at 5pm to call Mum"       a card, Save books it
#   "every Monday 9am put the bins out"  a card: every Mon at 9:00 am
#   "move that to 6"                     a change card, asking am or pm
#   my reminders                         the list
#
# When one goes off it is posted at the bottom of the hub with Done and
# Snooze (tasks/nudges/plain.py). The hub's card shows what is still to come
# today, and is not there when nothing is.
# ---------------------------------------------------------------------------
PLACE = 20  # where it comes (Task.place): pills, Today, reminders, personal routines, gym, calendar, diary, to-dos
ORDER = hub.CARDS_ORDER + PLACE  # its card under the pills checklist, in that order
hubcard.order(TASK, ORDER, lambda user_id: lambda: plain.hub_card(user_id))


async def show_word(ctx: Context) -> str:
    await ctx.reply(plain.listed(await store.every(ctx.user.id), days.today()))
    return "listed"


async def summary(user_id: int, day: date) -> Summary | None:
    """The day's reminders for the briefing, in time order: one that went off and is waiting, then
    those still to come, a line each; those dealt with (or gone by) one small line with a count."""
    nudges = await store.every(user_id)
    due = rules.due_today(nudges, day)
    # Renewals between their first nudge and the day before: a quiet part of the overview line
    renewals = expiry.overview(await expiry.every(user_id), day)
    if not due:
        return Summary("", QUIET, overview=renewals) if renewals else None
    now = clock.now()
    by_id = {each.id: each for each in nudges}
    waiting = [(each.due_at, by_id[each.nudge_id]) for each in reversed(await database.run(store.db_open, user_id)) if each.nudge_id in by_id and days.day_of(each.due_at) == day]
    coming = [(moment, each) for moment, each in due if moment > now] if day == days.day_of(now) else due
    left = [*waiting, *coming]
    lines = tuple(f"**{timeinput.format_moment(moment)}** · {each.text}" for moment, each in left)
    gone = len(due) - len(coming) - len(waiting)
    return Summary(
        f"{len(due)} today", DUE if waiting else QUIET, lines, hint=f"✅ {gone} earlier today" if gone > 0 else "",
        overview=f"{len(due)} today · first {timeinput.format_moment(due[0][0])}" + (f" · {renewals}" if renewals else ""),
        left=tuple(f"{each.text} `{timeinput.format_moment(moment)}`" for moment, each in left), left_at=tuple(moment for moment, _ in left),
    )


async def items(user_id: int, now: datetime) -> list[Item]:
    """One that went off and is not dealt with is due now (level 2); the next still
    to come today is next (level 3). Never a reminder's words on the status line."""
    found = []
    open_ = [each for each in await database.run(store.db_open, user_id) if days.day_of(each.due_at) == days.day_of(now)]
    if open_:
        found.append(plain.item(None, open_[0].due_at))
    coming = rules.coming(await store.every(user_id), now)
    if coming:
        found.append(Item("the next reminder", TIMED, when=coming[0][0], can_act=False, short=(attention.short_time(coming[0][0]),)))
    return found + expiry.expired_items(await expiry.every(user_id), days.day_of(now))


async def today_lines(user_id: int, now: datetime) -> list:
    """For the Today card: each reminder due today, as a note at its time."""
    from core.today import Line

    return [Line(ICON, f"**{each.text}**", moment, note=True) for moment, each in rules.due_today(await store.every(user_id), days.day_of(now))]


async def plan_pieces(user_id: int, day: date) -> list:
    """For a plan (core/planning.py): each reminder that day at its time, fixed; a renewal due that day at
    no time."""
    from core import planning

    found = [planning.Piece(TASK, f"n{each.id}", ICON, each.text, moment) for moment, each in rules.due_today(await store.every(user_id), day)]
    found += [planning.Piece(TASK, f"e{each.id}", expiry.RENEW_ICON, f"{each.name} due", all_day=True) for each in await expiry.every(user_id) if each.open and each.due == day]
    return found


class NudgesTask(Task):
    """Reminders at a time I set, in plain words; they go off in the hub."""

    name = TASK
    place = PLACE  # pills, Today, reminders, personal routines, gym, calendar, diary, to-dos
    title = TITLE
    description = "Reminders: at a time you set, once or repeating, posted in the hub with Done and Snooze"
    icon = ICON
    @property
    def only_for(self) -> str:
        # The calendar taking new events changes where "dentist Friday 3pm" goes (tasks/calendar)
        calendar_adds = config.CALENDAR_ENABLED and config.CALENDAR_WRITE and bool(config.CALENDAR_BOT_ID)
        return plain.ONLY_FOR_WITH_CALENDAR if calendar_adds else plain.ONLY_FOR

    examples = plain.EXAMPLES
    show = "nudge_show"
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER  # two reminders with the same words at different times are two
    leads = ("remind me",)  # Alex, 15 Oct: a message starting so is a reminder, whatever destination it names

    def switched_on(self) -> bool:
        return bool(config.NUDGES_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return await plain.item_names(request)

    def keywords(self) -> list[Keyword]:
        return [Keyword(["my reminders", "reminders"], "the reminders you have set: what, and when", show_word, examples=["my reminders"], channels=ANY, exact=True, purpose=SEE)]

    def buttons(self) -> list[ButtonNote]:
        return [
            ButtonNote("✅ Done", "on a reminder that went off: it is dealt with, and leaves the hub"),
            ButtonNote("💤 Snooze", "on a reminder that went off: again in 10 minutes, in 1 hour, or tomorrow at the same time"),
        ]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {plain.FIRE: plain.fire_job, plain.CARD: plain.post_job, expiry.CHECK_JOB: expiry.check_job, expiry.AGAIN_JOB: expiry.again_job}

    def job_labels(self):
        # Never the reminder's words: a job's name is shown where anyone may glance
        return {plain.FIRE: "reminder", plain.CARD: "reminders card", expiry.CHECK_JOB: "renewals check", expiry.AGAIN_JOB: "renewal"}

    def setup(self, client) -> None:
        plain.register()
        expiry.register()
        scheduler.default_schedule(TASK, expiry.CHECK_JOB, expiry.CHECK_DEFAULT)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, plain.CARD), order=ORDER, name=hub.MORNING_NAME)

    async def owns_message(self, message_id):
        return await database.run(store.db_message, message_id) is not None or await database.run(expiry.db_post_of, message_id) is not None

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def today(self, user_id, now):
        return await today_lines(user_id, now)

    async def plan(self, user_id, day):
        return await plan_pieces(user_id, day)


task = NudgesTask()
