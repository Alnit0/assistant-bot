from datetime import date, datetime, time, timedelta

from core import config, database, hub, hubcard, repeats, scheduler, timetable
from core.actions import EACH_DAY, Summary
from core.attention import PROBLEM, Item
from core.context import Context
from core.design import DONE, QUIET
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.reading import plain, rules, store
from tasks.reading.rules import ICON, LABELS, TASK, TITLE

# ---------------------------------------------------------------------------
# The daily read (behind READING_ENABLED, off): one article a day for keeping
# learning, about using AI, programming and the tech news, balanced over the
# week and shaped by 👍, 👎 and words. The sources are tasks/reading/feeds.json
# with what was added or removed in words; Claude picks among articles whose
# text was read and writes the TL;DR from it (tasks/reading/pick.py).
#
#   5:30 am   picked (`plain.pick_job`), before the 6 am briefing
#   6:00 am   its card in the hub, after the other task cards; one line in
#             round 5's overview box
#
# Its card is the read itself (the title as a link, the source, the reading
# time, the TL;DR small, 👍 and 👎 in blurple): round 5's overview box is a
# line a task, and buttons never go on the briefing.
# ---------------------------------------------------------------------------
PICK_AT = time(5, 30)
PICK_DEFAULT = timetable.Default("Daily read pick", PICK_AT)
PLACE = 80  # after to-dos: pills, Today, reminders, personal routines, gym, calendar, diary, to-dos, daily read
ORDER = hub.CARDS_ORDER + PLACE
hubcard.order(TASK, ORDER, lambda user_id: lambda: plain.hub_card(user_id))


async def summary(user_id: int, day: date) -> Summary | None:
    read = await store.current(user_id, day)
    if read is None:
        return None
    return Summary(f"{read.minutes} min", DONE if read.vote > 0 else QUIET, (rules.headline(read),), overview=rules.overview(read))


async def items(user_id: int, now: datetime) -> list[Item]:
    """Only every source failing three days running deserves a look; one failing is quiet."""
    if rules.all_failed(await database.run(store.db_failed_days, user_id, rules.FAILED_DAYS)):
        return [Item("the daily read's sources have all failed for 3 days", PROBLEM, when=now, ping=False, short=("📖",))]
    return []


async def week(user_id: int, monday: date, upto: date):
    from core.weekly import Week

    reads = await database.run(store.db_between, user_id, monday, upto)
    if not reads:
        return None
    return Week(rules.week_line(reads), status=QUIET)


async def show_word(ctx: Context) -> str:
    read = await store.current(ctx.user.id, plain.today())
    if read is None:
        await ctx.reply(f"{ICON} No read picked today yet.")
        return "none"
    await ctx.reply(rules.card_text(read))
    return "shown"


class ReadingTask(Task):
    """One article a day for Alex to keep learning: AI usage, programming, tech news."""

    name = TASK
    place = PLACE
    title = TITLE
    description = "Daily read: one article a day about using AI, programming or tech news, with a short TL;DR"
    icon = ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    show = ""
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return bool(config.READING_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    def keywords(self) -> list[Keyword]:
        return [Keyword(["daily read", "reading"], "today's read: the article, its source, how long, and its TL;DR", show_word, examples=["daily read"], channels=ANY, exact=True, purpose=EACH_DAY)]

    def buttons(self) -> list[ButtonNote]:
        return [ButtonNote("👍 👎", "on the daily read's card: more or less like this; after 👎, Another one")]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {plain.PICK_JOB: plain.pick_job, plain.CARD_JOB: plain.post_job}

    def job_labels(self):
        return {plain.PICK_JOB: "daily read pick", plain.CARD_JOB: "daily read card"}

    def setup(self, client) -> None:
        plain.register()
        scheduler.default_schedule(TASK, plain.PICK_JOB, PICK_DEFAULT)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, plain.CARD_JOB), order=ORDER, name=hub.MORNING_NAME)

    async def summary(self, user_id, day):
        return await summary(user_id, day)

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def week(self, user_id, monday, upto):
        return await week(user_id, monday, upto)


task = ReadingTask()
