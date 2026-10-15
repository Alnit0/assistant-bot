from datetime import date, datetime, timedelta

from core import cards, config, hub, repeats, scheduler
from core import day as days
from core.actions import SEE, Summary
from core.attention import TIMED, USEFUL, Item
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
#   "make an evening routine 6pm to 11pm: brush teeth, floss"   a card, Save makes it
#   "did floss", or the Done dropdown on the card                ticked off at once
#   "add skincare to my evening routine: cleanser, toner"        a change card
#   my routines                                                  the list
#
# Its card in the hub comes after the reminders card, each routine on today
# by the list rule; a day with none has no card. Each day starts afresh.
# How much one matters comes from its when (attention): any time is never
# urgent (level 4); at a time is due from that time (level 2, and the next
# timed thing before it); a window is quiet while open, and once it closes
# undone, overdue (level 2) only if a nudge was asked for. No streaks.
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

    lines = tuple(f"**{each.habit.name}** {design.progress(each.done, each.total)} · {rules.when_text(each.habit)}" for each in found)
    done, total = sum(each.done for each in found), sum(each.total for each in found)
    waiting = [each for each in found if each.next_item is not None]
    left = tuple(f"{each.habit.name}: {each.next_item.text}" for each in waiting)
    return Summary(f"{done} of {total} items", DONE if done == total else ANY_TIME, lines, done=done, total=total, left=left, left_at=tuple(each.starts() for each in waiting))


def attention_of(today: rules.Today, now: datetime) -> Item | None:
    """What one routine is worth now, by its when (see the top of this file)."""
    state = rules.state(today, now)
    if state == rules.FINISHED:
        return None
    short = (f"{today.done}/{today.total}",)
    if today.habit.when == rules.AT:
        return Item(f"{today.habit.name} routine", TIMED, today.starts(), can_act=state != rules.NOT_YET, short=short)
    if today.habit.when == rules.WINDOW:
        if state == rules.OVERDUE and today.habit.nudge == rules.NUDGE_END:
            return Item(f"{today.habit.name} routine not done", TIMED, today.ends(), can_act=True, short=short)
        return None  # quiet while it is open, and nothing nags without a nudge
    return Item(f"{today.habit.name} routine", USEFUL, can_act=True, short=short)


async def items(user_id: int, now: datetime) -> list[Item]:
    day = days.day_of(now)
    found = rules.due(await store.every(user_id), await store.ticked(user_id, day), day)
    return [item for item in (attention_of(each, now) for each in found) if item is not None]


async def today_lines(user_id: int, now: datetime) -> list:
    """For the Today card: each routine on today, a line each with its time or window."""
    from core.today import Line

    day = days.day_of(now)
    found = rules.due(await store.every(user_id), await store.ticked(user_id, day), day)
    return [Line(ICON, f"**{each.habit.name}** · {rules.when_text(each.habit)} · {each.done}/{each.total}", each.starts(), each.ends(), each.finished) for each in found]


class HabitsTask(Task):
    """Personal routines: my own checklists on chosen days."""

    name = TASK
    title = TITLE
    description = "Personal routines: your own named routines of steps and groups, each on its days at a time, in a window or any time"
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
        return [Keyword(["my routines", "routines"], "your personal routines: each one's items, days and time", show_word, examples=["my routines"], channels=ANY, exact=True, purpose=SEE)]

    def buttons(self) -> list[ButtonNote]:
        return [ButtonNote(rules.DONE_MENU, "the dropdown under a routine on its card in the hub: pick an item to tick it off (a group: the whole group)")]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {JOB: plain.post_job, plain.START: plain.start_job}

    def job_labels(self):
        return {JOB: "personal routines cards", plain.START: "a personal routine's card at its start"}

    def setup(self, client) -> None:
        cards.register(TASK, rules.TICK, plain.on_tick)
        cards.register(TASK, rules.PICKED, plain.on_picked)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, JOB), order=ORDER, name=hub.MORNING_NAME)

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def week(self, user_id, monday, upto):
        habits = await store.every(user_id)
        found: dict[int, tuple[str, list[bool]]] = {each.id: (each.name, []) for each in habits}
        day = monday
        while day <= upto:
            for each in rules.due(habits, await store.ticked(user_id, day), day):
                found[each.habit.id][1].append(each.finished)
            day += timedelta(days=1)
        return rules.week_line(list(found.values()))

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def today(self, user_id, now):
        return await today_lines(user_id, now)


task = HabitsTask()
