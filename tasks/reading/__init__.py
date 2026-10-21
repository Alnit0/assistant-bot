from datetime import date, datetime

from core import config, database, repeats, scheduler, timetable
from core.actions import EACH_DAY
from core.attention import PROBLEM, Item
from core.context import Context
from core.design import QUIET
from tasks.base import ANY, Keyword, Task
from tasks.reading import news, plain, rules, store
from tasks.reading.news import ICON, TITLE
from tasks.reading.rules import TASK

# ---------------------------------------------------------------------------
# The morning news (behind READING_ENABLED, off; Alex, 21 Oct: the daily read
# and the planned News headlines as one task, "it makes sense to only have
# one set of news generated"). Seven or eight stories a day, one a topic
# (world politics, NZ politics, world news, tech, AI, NZ housing and money)
# and an extra or two for the biggest news, web development a wildcard; each
# a headline that is the link, its topic, and a TL;DR of about 30 words.
#
#   5:30 am   picked (`plain.pick_job`), before the 6 am briefing; the time
#             is its schedule's, changed in words like any other
#   6:00 am   round 7's hub: one purple embed in the briefing's second
#             message, 👍 on it for a good set. Before round 7 not in the hub
# ---------------------------------------------------------------------------
PICK_DEFAULT = timetable.Default("Morning news", news.RUN_AT)
PLACE = 80  # after to-dos: pills, Today, reminders, personal routines, gym, calendar, diary, to-dos, the news


async def items(user_id: int, now: datetime) -> list[Item]:
    """Only every source failing three days running deserves a look; one failing is quiet."""
    if rules.all_failed(await database.run(store.db_failed_days, user_id, rules.FAILED_DAYS)):
        return [Item("the morning news's sources have all failed for 3 days", PROBLEM, when=now, ping=False, short=("📰",))]
    return []


async def week(user_id: int, monday: date, upto: date):
    """For the week of everything: how many mornings had news, and how many he said were good."""
    from datetime import timedelta

    from core.weekly import Week

    found = [await database.run(store.db_news, user_id, monday + timedelta(days=ahead)) for ahead in range((upto - monday).days + 1)]
    sets = [each for each in found if each is not None and each[0]]
    if not sets:
        return None
    good = sum(1 for _, liked in sets if liked)
    return Week(f"{len(sets)} morning{'' if len(sets) == 1 else 's'} of news" + (f" · 👍 {good}" if good else ""), status=QUIET)


async def show_word(ctx: Context) -> str:
    found = await database.run(store.db_news, ctx.user.id, plain.today())
    if found is None or not found[0]:
        await ctx.reply(f"{ICON} No morning news picked today yet.")
        return "none"
    from core import cards

    await cards.send(ctx.channel_id, plain.news_card(found[0], plain.today()))
    return "shown"


class ReadingTask(Task):
    """The morning news: 7 or 8 stories a day across six topics, each with a short TL;DR."""

    name = TASK
    place = PLACE
    title = TITLE
    description = "Morning news: 7 or 8 stories a day (world and NZ politics, world news, tech, AI, NZ housing and money), each with a short TL;DR"
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
        return [Keyword(["morning news", "news"], "today's news: 7 or 8 stories, each a link with a short TL;DR", show_word, examples=["morning news"], channels=ANY, exact=True, purpose=EACH_DAY)]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {plain.PICK_JOB: plain.pick_job}

    def job_labels(self):
        return {plain.PICK_JOB: "morning news"}

    def setup(self, client) -> None:
        plain.register()
        scheduler.default_schedule(TASK, plain.PICK_JOB, PICK_DEFAULT)

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def week(self, user_id, monday, upto):
        return await week(user_id, monday, upto)

    async def day_items(self, user_id, day):
        return await plain.day_items(user_id, day)


task = ReadingTask()
