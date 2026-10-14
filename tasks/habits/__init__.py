from datetime import date, datetime

from core import cards, config, hub, repeats, scheduler
from core import day as days
from core.actions import SEE, Summary
from core.attention import USEFUL, Item
from core.context import Context
from core.design import ANY_TIME, DONE
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.habits import plain, rules, store
from tasks.habits.rules import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# Personal routines (docs/specs/routines.md, private), behind HABITS_ENABLED:
# off, the task is not loaded at all. The folder is `habits` because
# "routine" in code is the scheduler's own (the 6 am routine); everywhere I
# read it, it is "Personal routines".
#
#   "make a morning routine: stretch, water, journal"   a card, Save makes it
#   "did stretch", or the button on the card              ticked off at once
#   "add meditate to my morning routine"                  a change card
#   my routines                                           the list
#
# Its card in the hub comes after the reminders card, each routine due today
# with its own dots; a day with none has no card. Each day starts afresh.
# ---------------------------------------------------------------------------
JOB = "card"
ORDER = hub.CARDS_ORDER + 20  # the hub's order: pills, reminders, personal routines, gym, to-dos


async def show_word(ctx: Context) -> str:
    await ctx.reply(rules.listed(await store.every(ctx.user.id)))
    return "listed"


async def summary(user_id: int, day: date) -> Summary | None:
    found = rules.due(await store.every(user_id), await store.ticked(user_id, day), day)
    if not found:
        return None
    from core import design

    lines = tuple(f"**{each.habit.name}** {design.progress(each.done, each.total)}" for each in found)
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    left = tuple(f"{each.habit.name}: {each.next_step.text}" for each in found if each.next_step is not None)
    return Summary(f"{done} of {total} steps", DONE if done == total else ANY_TIME, lines, done=done, total=total, left=left)


async def items(user_id: int, now: datetime) -> list[Item]:
    day = days.day_of(now)
    found = rules.due(await store.every(user_id), await store.ticked(user_id, day), day)
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    if not found or done == total:
        return []
    return [Item("personal routines to do today", USEFUL, can_act=True, short=(f"{done}/{total}",))]


class HabitsTask(Task):
    """Personal routines: my own checklists on chosen days."""

    name = TASK
    title = TITLE
    description = "Personal routines: your own named checklists of steps on chosen days"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    show = "habit_show"
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER  # one with the same name is refused on the card (add_card)

    def switched_on(self) -> bool:
        return bool(config.HABITS_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return await plain.item_names(request)

    def keywords(self) -> list[Keyword]:
        return [Keyword(["my routines", "routines"], "your personal routines: each one's steps and days", show_word, examples=["my routines"], channels=ANY, exact=True, purpose=SEE)]

    def buttons(self) -> list[ButtonNote]:
        return [ButtonNote("✅ a step", "on the personal routines card in the hub: that routine's next step is done")]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {JOB: plain.post_job}

    def job_labels(self):
        return {JOB: "personal routines card"}

    def setup(self, client) -> None:
        cards.register(TASK, rules.TICK, plain.on_tick)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, JOB), order=ORDER, name=hub.MORNING_NAME)

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)


task = HabitsTask()
