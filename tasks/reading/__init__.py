from datetime import date, datetime

from core import config, database, hub, repeats, scheduler, timetable
from core.actions import EACH_DAY, Request
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
#   6:00 am   a card a story in #news (`plain.post_job`, a step of the
#             morning routine before the briefing; 21 Oct, night: "could each
#             news article be its own card?"), 👍 on one for liked or read;
#             round 7's hub one line, "📰 8 stories in #news". Before round 7
#             not in the hub
# ---------------------------------------------------------------------------
PICK_DEFAULT = timetable.Default("Morning news", news.RUN_AT)
PLACE = 80  # after to-dos: pills, Today, reminders, personal routines, gym, calendar, diary, to-dos, the news


async def items(user_id: int, now: datetime) -> list[Item]:
    """Only every source failing three days running deserves a look; one failing is quiet."""
    found = [Item(each, PROBLEM, when=now, ping=False, short=("📰",)) for each in plain._cannot_make]
    if rules.all_failed(await database.run(store.db_failed_days, user_id, rules.FAILED_DAYS)):
        found.append(Item("the morning news's sources have all failed for 3 days", PROBLEM, when=now, ping=False, short=("📰",)))
    return found


async def week(user_id: int, monday: date, upto: date):
    """For the week of everything: how many mornings had news, and how many stories he liked or read."""
    from datetime import timedelta

    from core.weekly import Week

    found = [await database.run(store.db_news, user_id, monday + timedelta(days=ahead)) for ahead in range((upto - monday).days + 1)]
    sets = [each for each in found if each is not None and each[0]]
    if not sets:
        return None
    good = await database.run(store.db_liked_between, user_id, monday, upto)
    return Week(f"{len(sets)} morning{'' if len(sets) == 1 else 's'} of news" + (f" · 👍 {good}" if good else ""), status=QUIET)


async def show_word(ctx: Context) -> str:
    said = await plain.show(Request(ctx.user, ctx.channel_id, ctx.text), {"what": "today"}, frozenset())
    if isinstance(said, str):
        await ctx.reply(said)
        return "said"
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
    home = plain.NEWS  # #news listens like #inbox, the news first
    home_examples = ("another one", "more like this")

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
        return {plain.PICK_JOB: plain.pick_job, plain.POST_JOB: plain.post_job}

    def job_labels(self):
        return {plain.PICK_JOB: "morning news", plain.POST_JOB: "morning news cards"}

    def setup(self, client) -> None:
        plain.register()
        scheduler.default_schedule(TASK, plain.PICK_JOB, PICK_DEFAULT)
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, plain.POST_JOB), order=hub.PREPARED_ORDER, name=hub.MORNING_NAME)

    async def startup(self, client) -> None:
        # The cards up have their 👍 again, and #news (made before) listens again
        await plain.note_cards()
        owner = await database.run(scheduler._db_owner)
        if owner is not None:
            await plain.recall_channel(owner)

    async def message_class(self, message_id):
        from core.lifecycle import MessageClass

        return MessageClass.LIVE if await database.run(store.db_card_of, message_id) is not None else None

    async def attention(self, user_id, now):
        return await items(user_id, now)

    async def week(self, user_id, monday, upto):
        return await week(user_id, monday, upto)

    async def day_items(self, user_id, day):
        return await plain.day_items(user_id, day)


task = ReadingTask()
