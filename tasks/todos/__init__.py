from datetime import date, datetime

from core import attention, cards, config, hub, livelists, repeats, scheduler
from core import day as days
from core.actions import EACH_DAY, Summary
from core.attention import TIMED, USEFUL, Item
from core.context import Context
from core.design import ANY_TIME, DONE, DUE
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.todos import plain, rules, store
from tasks.todos.rules import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# To-dos: the planned list of things to do (docs/specs/todos.md, private).
# Behind TODOS_ENABLED: off, the task is not loaded at all.
#
#   "add call Ryan Friday"        a card: Call Ryan · Fri 16 Oct, Save adds it
#   "I called Ryan", Done         ticked off at once, one line says so
#   "undo that"                   back to not done
#   "move call Ryan to Monday"    a change card: day · Fri → Mon
#   my to-dos                     the list
#
# Its card in the hub comes under the pills checklist and the other task
# cards (core/hub.py), posted by the morning routine and edited in place; a
# day with nothing for today has no card. Overdue to-dos are what to look at
# now (attention level 2), today's with no time are useful (level 4).
# ---------------------------------------------------------------------------
JOB = "card"
ORDER = hub.CARDS_ORDER + 40  # the hub's order: pills, reminders, personal routines, gym, to-dos


async def show_word(ctx: Context) -> str:
    shown = rules.listed(await store.every(ctx.user.id), days.today())
    message = await ctx.reply(shown)
    if message is not None:
        await livelists.placed(ctx.user.id, plain.LIST, ctx.channel_id, message.id, TASK)
    return "listed"


async def summary(user_id: int, day: date) -> Summary | None:
    """Today's to-dos for the briefing: overdue first, then today's, a line each."""
    found = rules.on(await store.every(user_id), day)
    if found.is_empty:
        return None
    waiting = [f"{rules.line(each, day)} · overdue" for each in found.overdue] + [f"**{each.text}**" for each in found.today]
    status = DUE if found.overdue else ANY_TIME if found.today else DONE
    left = tuple(each.text for each in (*found.overdue, *found.today))
    return Summary(f"{len(found.done)} of {found.total} done", status, tuple(waiting), done=len(found.done), total=found.total, left=left)


async def items(user_id: int, now: datetime) -> list[Item]:
    """What deserves a look: overdue to-dos now (level 2), today's with no time (level 4).
    Never a to-do's words in what the status line shows."""
    day = days.day_of(now)
    found = rules.on(await store.every(user_id), day)
    said = []
    if found.overdue:
        said.append(Item("to-dos overdue", TIMED, when=days.start_of(day), can_act=True, short=(f"{len(found.overdue)} overdue",)))
    if found.today:
        said.append(Item("to-dos for today", USEFUL, can_act=True, short=(f"{len(found.done)}/{found.total}",)))
    return said


class TodosTask(Task):
    """The to-do list, in plain words, with a card in the hub."""

    name = TASK
    title = TITLE
    description = "To-dos: the planned list of things to do, each with a day if it has one"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    show = "todo_show"
    identity = ()
    # Two to-dos with the same words: the card says the one there is and adds nothing (add_card)
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return bool(config.TODOS_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return await plain.item_names(request)

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(["my to-dos", "to-dos", "todos"], "the to-do list: what is overdue, today's, and what is for later", show_word, examples=["my to-dos"], channels=ANY, exact=True, purpose=EACH_DAY),
        ]

    def buttons(self) -> list[ButtonNote]:
        return [ButtonNote("✅ Done", "on the to-dos card in the hub: tick that to-do off")]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {JOB: plain.post_job}

    def job_labels(self):
        return {JOB: "to-dos card"}

    def setup(self, client) -> None:
        cards.register(TASK, rules.DONE_ACTION, plain.on_done)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, JOB), order=ORDER, name=hub.MORNING_NAME)

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)


task = TodosTask()
