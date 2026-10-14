from datetime import date, datetime

from core import attention, config, database, hub, repeats, scheduler, timeinput
from core import day as days
from core.actions import SEE, Summary
from core.attention import TIMED, Item
from core.context import Context
from core.design import DUE, QUIET
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.nudges import plain, rules, store
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
ORDER = hub.CARDS_ORDER + 10  # the hub's order: pills, reminders, personal routines, gym, to-dos


async def show_word(ctx: Context) -> str:
    await ctx.reply(plain.listed(await store.every(ctx.user.id), days.today()))
    return "listed"


async def summary(user_id: int, day: date) -> Summary | None:
    """The day's reminders for the briefing, in time order, a line each."""
    due = rules.due_today(await store.every(user_id), day)
    if not due:
        return None
    lines = tuple(f"**{timeinput.format_moment(moment)}** · {each.text}" for moment, each in due)
    return Summary(f"{len(due)} today", DUE if due else QUIET, lines)


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
    return found


class NudgesTask(Task):
    """Reminders at a time I set, in plain words; they go off in the hub."""

    name = TASK
    title = TITLE
    description = "Reminders: at a time you set, once or repeating, posted in the hub with Done and Snooze"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    show = "nudge_show"
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER  # two reminders with the same words at different times are two

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
        return {plain.FIRE: plain.fire_job, plain.CARD: plain.post_job}

    def job_labels(self):
        # Never the reminder's words: a job's name is shown where anyone may glance
        return {plain.FIRE: "reminder", plain.CARD: "reminders card"}

    def setup(self, client) -> None:
        plain.register()
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, plain.CARD), order=ORDER, name=hub.MORNING_NAME)

    async def owns_message(self, message_id):
        return await database.run(store.db_message, message_id) is not None

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)


task = NudgesTask()
