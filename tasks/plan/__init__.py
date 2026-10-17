from core import config, repeats
from tasks.base import Task
from tasks.plan import plain, store
from tasks.plan.plain import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# Plan my day, behind PLAN_MY_DAY (off: not loaded at all). The engine is the
# core's (core/planning.py): every task hands over its day through its
# contract (`plan`), and the code places the to-dos in the free time around
# what is fixed. This task is only the conversation over it (as the schedule
# task is over the scheduler): its words, its card, what is saved, and the
# saved times on the Today card. It has no card of its own in the hub, posts
# nothing by itself and never pings.
# ---------------------------------------------------------------------------
PLACE = 90  # after every task with a card in the hub


class PlanTask(Task):
    """Plan my day: to-dos placed in the free time around what is fixed."""

    name = TASK
    place = PLACE
    title = TITLE
    description = "Plan my day: your to-dos placed in the free time around what is fixed, saved to the Today card or the Bot calendar"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    identity = ()  # a plan is one a day: Save replaces the day's plan (store.db_save), so nothing is a repeat
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return bool(config.PLAN_MY_DAY)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    def migrations(self):
        return store.MIGRATIONS

    async def today(self, user_id, now):
        return await plain.today_lines(user_id, now)


task = PlanTask()
