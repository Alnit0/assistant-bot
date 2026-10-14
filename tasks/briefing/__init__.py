import asyncio
import logging

from datetime import timedelta

from core import attention, cards, clock, config, database, health, hub, livelists, messages, money, notify, repeats, scheduler, summaries, tidy, timeinput
from core import day as days
from core.actions import SEE, Action, Field, LiveReply, Request, Shown
from core.cards import Card
from core.context import Context
from tasks.base import ANY, Keyword, Task
from tasks.briefing import rules
from tasks.briefing.rules import ICON, TASK

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Briefing: one card that says what today holds, a section from each task
# that has a summary (core/summaries.py). Behind BRIEFING_ENABLED: off, this
# task offers nothing, posts nothing and joins no routine.
#
# One briefing a day in the hub, posted as a step of the morning routine
# (before the checklist, so the checklist is the newest message), and edited
# in place whenever a section changes, so it always shows now. Nothing new
# is posted for a change. The next morning's takes its place.
#
# It keeps nothing and decides nothing: every number in it is a task's. It
# knows no other task: a task with a summary appears with no change here.
#
# Its order is the one ranking's (core/attention.py), as the status line's
# top item is: what is wrong and needs me on top, then what quiet hours held
# back overnight (core/notify.py), then the sections, the task whose item
# stands highest first. It ranks nothing itself.
# ---------------------------------------------------------------------------
JOB = "post"
IN_THE_HUB = "briefing:hub"  # the Live copy in the hub; asked for elsewhere it is "briefing"
ELSEWHERE = "briefing"
SLOT = "briefing"  # its place in the hub: one at a time (core/messages.py, with the tidy on)
ONLY_FOR = (
    "The summary of the user's day across everything the bot keeps (\"brief me\", \"what's on today?\"). Not one "
    "task's own list (what pills are left is the pills task), and not when the briefing is posted (that is the "
    "schedule task)."
)
EXAMPLES = ("brief me", "what's on today?")
# With DAY_QUESTIONS on, what the router reads instead: the day as a whole, also what is left and how it went
ONLY_FOR_THE_DAY = (
    "The user's day as a whole, across everything the bot keeps: what is on today (\"brief me\", \"what's on "
    "today?\"), what is still left to do today (\"what's left today?\"), and how yesterday or this week went "
    "overall (\"how did I go yesterday?\", \"how's this week going?\"). Not one named task's own list or history "
    "(which pills are left, or which were taken yesterday, is the pills task), not the weather (the weather "
    "task), and not when the briefing is posted (the schedule task)."
)
EXAMPLES_OF_THE_DAY = ("brief me", "what's on today?", "what's left today?", "how did I go yesterday?")


def enabled() -> bool:
    return bool(config.BRIEFING_ENABLED)


def answers_questions() -> bool:
    """Whether the day's questions are answered here (DAY_QUESTIONS, and the briefing itself on)."""
    return enabled() and bool(config.DAY_QUESTIONS)


async def card_for(user_id: int) -> Card | None:
    """The briefing as it reads now, or None with nothing to say."""
    today = days.today()
    now = clock.now()
    order = attention.ranked(await attention.gather(user_id, now), now)
    gathered = await summaries.gather(user_id, today)
    # The day's progress is counted in the order the tasks come, so its line never shuffles
    so_far = rules.progress(gathered) if config.DAY_PROGRESS else ()
    sections = rules.ordered(gathered, [item.task for _, item in order])
    problems = tuple(rules.problem(item) for rank, item in order if rank == attention.LEVEL_PROBLEM)
    held = tuple(rules.held(each.line, each.times) for each in await notify.held_overnight(user_id, today))
    notes = tuple(f"{timeinput.format_moment(each.at)} · {each.line}" for each in await notify.notes_for(user_id, today))
    if not (sections or problems or held or notes):
        return None
    hours = " to ".join(timeinput.format_time(each) for each in config.QUIET_HOURS)
    spend = await spend_line(today)
    return Card(rules.text(sections, today, problems, held, hours, notes, spend, so_far), (), rules.layout(sections, today, problems, held, hours, notes, spend, so_far))


async def spend_line(today) -> str:
    """Yesterday's Claude spend, in NZ$, or "" for a day with none. Live's own: the dev bot's briefing has no money in it."""
    if config.DEV_DATABASE:
        return ""
    try:
        you, testing = await health.spent_on(today - timedelta(days=1))
    except Exception:
        log.exception("Yesterday's spend could not be read for the briefing")
        return ""
    if money.nzd(you + testing) < 0.005:
        return ""
    return rules.spend_line(money.shown(you), money.shown(testing), money.shown(you + testing))


_said: dict[int, str] = {}  # what the briefing last read as, a user: an edit that would change nothing is not made


async def _shown(user_id: int) -> Card:
    """What a copy already up is rewritten as: the briefing, or the line that
    says there is nothing (a copy is never left saying what is no longer so)."""
    shown = await card_for(user_id) or Card(rules.NOTHING)
    _said[user_id] = shown.text
    return shown


def _hub_id(role: str = "hub") -> int | None:
    found = config.CHANNELS.get(role)
    return int(found) if found else hub.channel_id()


async def post_in_hub(user_id: int, channel_id: int, notify: bool = False) -> int | None:
    """A fresh briefing in the hub, in place of the one that was there: one at
    a time. Returns its message id, or None with nothing to say."""
    shown = await card_for(user_id)
    if shown is None:
        return None
    _said[user_id] = shown.text
    old = await database.run(livelists.db_get, user_id, IN_THE_HUB)
    if notify:
        # What notifies names nothing: posted as the one neutral line, and written in after
        message_id = await cards.send(channel_id, Card(rules.notice(timeinput.format_moment(clock.now()))))
        if message_id is not None:
            await cards.edit(channel_id, message_id, shown)
    else:
        message_id = await cards.send(channel_id, shown, silent=True)
    if message_id is None:
        return None
    # One briefing in the hub at a time (core/messages.py, with the tidy on)
    await messages.record(message_id, channel_id, lifetime=messages.REPLACED, slot=SLOT, task=TASK)
    await livelists.placed(user_id, IN_THE_HUB, channel_id, message_id, TASK)
    if old is not None and old.message_id != message_id:
        # The new one is up first, then the old goes: never a moment with none
        await cards.delete(old.channel_id, old.message_id)
    return message_id


async def post_job(job: scheduler.Job) -> None:
    """Scheduler handler: the morning's briefing, for the user the schedule is
    for. When is the engine's business."""
    channel_id = _hub_id(job.channel)
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if channel_id is None or user_id is None:
        scheduler.report(job, scheduler.SKIPPED)
        scheduler.note(job, "not posted: the hub channel is not set or can't be found")
        return
    posted = await post_in_hub(user_id, channel_id, notify=job.notify == "notify")
    scheduler.note(job, "posted" if posted is not None else "not posted: nothing to say today")


def summary_changed(task: str, user_id: int) -> None:
    """A task's summary may have changed: each copy that is up is rewritten in
    place. Several changes close together are one edit (core/live.py)."""
    for key in (IN_THE_HUB, ELSEWHERE):
        livelists.changed(user_id, key, lambda: _shown(user_id))


async def look_again() -> bool:
    """What deserves a look may have changed with no summary changing (a job
    failed, a problem went): the copies that are up are rewritten, but only
    if the briefing would read differently. True if they were told to."""
    user_id = await database.run(scheduler._db_owner)
    if user_id is None:
        return False
    shown = await card_for(user_id) or Card(rules.NOTHING)
    if shown.text == _said.get(user_id):
        return False
    summary_changed(TASK, user_id)
    return True


_looking: set[asyncio.Task] = set()


def attention_changed() -> None:
    """Told by the attention model (core/attention.py). Called, not awaited."""
    try:
        looking = asyncio.get_running_loop().create_task(look_again())
    except RuntimeError:
        return
    _looking.add(looking)
    looking.add_done_callback(_looking.discard)


async def show(request: Request, data: dict, guessed: frozenset):
    """"brief me": in the hub, the one that is there is brought up to date in
    place (one is posted if there is none); elsewhere, a copy there."""
    user_id = request.user.id
    if request.channel_id == _hub_id():
        if await livelists.refresh(user_id, IN_THE_HUB, lambda: _shown(user_id)):
            await tidy.pointer(request.channel_id, rules.UP_TO_DATE)
            return Shown("the briefing in the hub was brought up to date in place")
        if await post_in_hub(user_id, request.channel_id) is None:
            return rules.NOTHING
        return Shown("the briefing was posted in the hub")
    shown = await card_for(user_id)
    if shown is None:
        return rules.NOTHING
    return LiveReply(ELSEWHERE, shown.text, shown)


async def left_today(request: Request, data: dict, guessed: frozenset) -> str:
    """ "what's left today?": from every task's summary of today, in words from a template."""
    return rules.left(await summaries.gather(request.user.id, days.today()))


async def looking_back(request: Request, data: dict, guessed: frozenset) -> str:
    """ "how did I go yesterday?", "how's this week going?": from each task's record of the days."""
    user_id, today = request.user.id, days.today()
    if data.get("period") == rules.WEEK:
        monday = today - timedelta(days=today.weekday())
        found = [(monday + timedelta(days=ahead), await summaries.tallies(user_id, monday + timedelta(days=ahead))) for ahead in range(today.weekday() + 1)]
        return rules.week(found, today)
    before = today - timedelta(days=1)
    return rules.yesterday(before, await summaries.tallies(user_id, before), await summaries.gather(user_id, today))


async def show_word(ctx: Context) -> str:
    """`briefing`, `brief me`: the same, typed."""
    result = await show(Request(ctx.user, ctx.channel_id, ctx.text, message_id=ctx.message_id), {}, frozenset())
    if isinstance(result, LiveReply):
        await livelists.show(ctx.user.id, result.key, ctx.channel_id, result.card, task=TASK)
        return "shown"
    if isinstance(result, str):
        await ctx.reply(result)
        return result
    return result.summary


class BriefingTask(Task):
    """Briefing: what today holds, a section a task, in one card kept up to date."""

    name = TASK
    description = "Briefing: one card that says what today holds, kept up to date"
    icon = ICON

    @property
    def only_for(self) -> str:
        return ONLY_FOR_THE_DAY if answers_questions() else ONLY_FOR

    @property
    def examples(self) -> tuple:
        return EXAMPLES_OF_THE_DAY if answers_questions() else EXAMPLES

    show = "briefing_show"
    identity = ()  # it keeps nothing: there is nothing to be the same as
    on_repeat = repeats.ALLOW_ANOTHER

    def actions(self) -> list:
        if not enabled():
            return []
        return [
            Action(
                "briefing_show",
                "The user asks for the summary of their day across everything (\"brief me\", \"what's on today?\", "
                "\"what does today look like?\"). Not for what one task holds: \"what pills are left?\" is pills.",
                needs_card=False,
                run=show,
                purpose=SEE,
                say=("brief me",),
            ),
            *(self._questions() if answers_questions() else ()),
        ]

    def _questions(self) -> tuple:
        return (
            Action(
                "day_left",
                "The user asks what is still to do today, across everything (\"what's left today?\", \"what do I still "
                "have to do today?\", \"am I done for today?\"). Not what is on today as a whole: that is briefing_show.",
                needs_card=False,
                run=left_today,
                purpose=SEE,
                say=("what's left today?",),
            ),
            Action(
                "day_past",
                "The user asks how a day that is over, or the week so far, went as a whole (\"how did I go yesterday?\", "
                "\"how was yesterday?\" -> period yesterday; \"how's this week going?\", \"this week?\", \"how did the "
                "week go?\" -> period week). Not for today: that is briefing_show or day_left.",
                (Field("period", "Which stretch of time: yesterday, or the week so far.", choices=(rules.YESTERDAY, rules.WEEK), required=True),),
                needs_card=False,
                run=looking_back,
                purpose=SEE,
                say=("how did I go yesterday?", "how is this week going?"),
            ),
        )

    def keywords(self) -> list[Keyword]:
        if not enabled():
            return []
        return [
            Keyword(
                ["briefing", "brief me"],
                "what today holds, a section from each task that has something to say: brought up to date in place in the hub, "
                "a copy of its own anywhere else",
                show_word,
                examples=["brief me"],
                channels=ANY,
                exact=True,
                keep_command=True,
                purpose=SEE,
            )
        ]

    def job_handlers(self) -> dict:
        return {JOB: post_job} if enabled() else {}

    def job_labels(self) -> dict:
        return {JOB: "briefing"} if enabled() else {}

    def setup(self, client) -> None:
        if not enabled():
            return
        # The hub's morning routine: the briefing, then the checklist, so the checklist is the newest message
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, JOB), order=hub.BRIEFING_ORDER, name=hub.MORNING_NAME)
        summaries.on_change(summary_changed)
        attention.on_change(attention_changed)

    async def startup(self, client) -> None:
        if not enabled():
            return
        # A copy that is up shows now, not how things stood when the bot stopped
        for user_id in await database.run(lambda conn: [row[0] for row in conn.execute("SELECT DISTINCT user_id FROM live_lists WHERE key IN (?, ?)", (IN_THE_HUB, ELSEWHERE))]):
            summary_changed("", user_id)


task = BriefingTask()
