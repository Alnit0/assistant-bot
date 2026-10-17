from datetime import date, datetime, timedelta

from core import config, database, repeats, scheduler
from core import day as days
from core.actions import SEE, Summary
from core.context import Context
from core.design import ANY_TIME, QUIET
from core.lifecycle import MessageClass
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.gym import plain, rules, session, store
from tasks.gym.rules import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# The gym (docs/specs/gym.md, private), behind GYM_ENABLED: off, not loaded.
# Alex's goals, in his words: help upkeep data entry, data retrieval, create
# consistency, lower administration, see progress, easy access to notes, make
# life easier. Flexible, never naggy: nothing is posted or pinged by itself
# but a session he asked for at a time.
#
#   his logbook (CSV, XLSX, pasted)  the plan and the log apart, on a card
#   starting a workout               the next in the queue, its card in #gym
#   Log on an exercise, or words     the sets, with last time and a suggestion
#   Finish                           a summary with PBs; the queue moves on
#   how's my bench going?            answered in place
#
# The briefing's The day has one line; the week's summary a line only with a
# target; the week view shows the days with a session.
# ---------------------------------------------------------------------------
PLACE = 40  # pills, Today, reminders, personal routines, gym, calendar, diary, to-dos


async def summary(user_id: int, day: date) -> Summary | None:
    """The day's one line: "next: Upper 2 · last session 3 days ago · 2 this week"."""
    nxt = await session.next_workout(user_id)
    if nxt is None:
        return None
    monday = day - timedelta(days=day.weekday())
    done = [each for each in await database.run(store.db_sessions, user_id) if each.status != store.OPEN]
    parts = [f"next: {nxt.name}"]
    before = [each for each in done if each.day <= day]
    if before:
        ago = (day - before[-1].day).days
        parts.append("last session today" if ago == 0 else "last session yesterday" if ago == 1 else f"last session {ago} days ago")
    this_week = sum(1 for each in done if monday <= each.day <= day)
    if this_week:
        parts.append(f"{this_week} this week")
    return Summary(" · ".join(parts[1:]) or "", QUIET, overview=" · ".join(parts))


async def week(user_id: int, monday: date, upto: date):
    """The week's summary: only with a target ("aim for 3 a week"), sessions against it."""
    from core.weekly import Week

    target = await database.run(store.db_target, user_id)
    if not target:
        return None
    count = sum(1 for each in await database.run(store.db_sessions, user_id, monday) if each.day <= upto and each.status != store.OPEN)
    return Week(f"{count} of {target} sessions", min(count, target), target, "", ANY_TIME)


async def plan_pieces(user_id: int, day: date) -> list:
    """For the week view and a plan: a session done that day, all day."""
    from core import planning

    return [planning.Piece(TASK, f"g{each.id}", ICON, each.name, all_day=True, done=True) for each in await database.run(store.db_sessions, user_id, day) if each.day == day]


async def plan_word(ctx: Context) -> str:
    await ctx.reply(await plain.show_plan(plain.Request(ctx.user, ctx.channel_id), {}, frozenset()))
    return "the gym plan"


class GymTask(Task):
    """The gym: the plan, the rotation, logging, progress."""

    name = TASK
    place = PLACE
    title = TITLE
    description = "Gym: your plan and log from your logbook, the next workout in #gym, logging by buttons or in words, suggested weights, bests and progress"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER  # a new logbook is a change to the plan, on its card (plain.import_card)

    def switched_on(self) -> bool:
        return bool(config.GYM_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        return await plain.item_names(request)

    def keywords(self) -> list[Keyword]:
        return [Keyword(["my gym plan", "gym plan"], "your gym plan: its workouts in the order they come round, and what is next", plan_word, examples=["my gym plan"], channels=ANY, exact=True, purpose=SEE)]

    def buttons(self) -> list[ButtonNote]:
        return [
            ButtonNote("📝 Log", "on each exercise of the workout card in #gym: a form a line a set, the suggested weight filled in, and a note"),
            ButtonNote("🏁 Finish workout", "on the workout card: what is not logged is not done, a summary with your bests, and the next workout comes round. Undo after it"),
        ]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {plain.POST_JOB: plain.post_job}

    def job_labels(self):
        return {plain.POST_JOB: "gym session"}

    def setup(self, client) -> None:
        session.register()

    async def owns_message(self, message_id):
        return await database.run(store.db_session_of_message, message_id) is not None

    async def message_class(self, message_id):
        return MessageClass.LIVE if await database.run(store.db_session_of_message, message_id) is not None else None

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def week(self, user_id, monday, upto):
        return await week(user_id, monday, upto)

    async def plan(self, user_id, day):
        return await plan_pieces(user_id, day)


task = GymTask()
