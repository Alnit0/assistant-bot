from datetime import date, datetime, timedelta

from core import config, database, repeats, scheduler, timetable
from core.actions import EACH_DAY, Summary
from core.context import Context
from core.design import ANY_TIME, DONE, QUIET
from tasks.base import ANY, ButtonNote, Keyword, Task
from tasks.diary import mood, plain, rules, store
from tasks.diary.rules import ICON, TASK, TITLE

# ---------------------------------------------------------------------------
# The diary (behind DIARY_ENABLED, off): Alex's own words about his day, one
# entry a diary day (to 4:00 am), several messages appending to it, a mood on
# a small scale (tasks/diary/mood.py, behind DIARY_MOOD), one gentle evening
# ask if nothing is written by 9 pm, and a streak of days written.
#
#   "today was good, finally finished the essay"   kept; "📔 Saved · 😊 Good · streak 4"
#   "rough day" with no clear mood                 kept; the line asks with a button a mood
#   "actually today was ok"                        the mood changed, with Undo
#   "what did I write last Tuesday?"               that day, its words (asked for)
#   "show this week's diary"                       a line a day, moods, no words
#   "delete today's diary"                         a red card first
#
# Its words are kept in the database and nowhere else: no line said back, no
# log, notification, status line or Today card holds any of them (Entry.private).
# No attention items: it is never something to be told about.
# ---------------------------------------------------------------------------
ASK_DEFAULT = timetable.Default("Diary evening ask", rules.ASK_AT)
# The bot's own: at 6 pm the Today card is drawn again, so "Diary · not yet" comes up. Any other
# change to the card draws it right too: nothing depends on this having run
TODAY_DEFAULT = timetable.Default("Diary on the Today card", rules.SHOWN_FROM, locked=True)


async def summary(user_id: int, day: date) -> Summary | None:
    """For the briefing: the streak and whether today is written (round 5's overview line), "not yet" only
    from 6 pm. Never a past day's mood or words (Alex, 17 Oct): those are shown only when asked for."""
    from core import clock

    written = await database.run(store.db_days, user_id)
    if not written:
        return None
    line = rules.streak_line(rules.streak(written, day), day in written, rules.evening(clock.now()))
    glance = "written today" if day in written else "not written yet today"
    return Summary(glance, DONE if day in written else QUIET, overview=line)


async def today_lines(user_id: int, now: datetime) -> list:
    """Never on the Today card (Alex, 17 Oct): the diary's one line is in the briefing's The day only."""
    return []


async def week(user_id: int, monday: date, upto: date):
    """For the week of everything: the days written out of the week's; the streak small. No moods."""
    from core.weekly import Week

    span = [monday + timedelta(days=ahead) for ahead in range((upto - monday).days + 1)]
    found = await database.run(store.db_between, user_id, monday, upto)
    if not found:
        return None
    run = rules.streak(await database.run(store.db_days, user_id), upto)
    return Week(rules.days_written(len(found), len(span)), len(found), len(span), f"streak {run}" if run >= 2 else "", ANY_TIME)


async def show_word(ctx: Context) -> str:
    on = plain.today()
    days = rules.week_of(on)
    await ctx.reply(rules.span_answer(await database.run(store.db_between, ctx.user.id, days[0], days[-1]), days, on, "This week"))
    return "listed"


async def day_items(user_id: int, day: date) -> list:
    """For the hub in round 7: one line, the streak; nothing before the first entry. Never a mood or words."""
    from core import actions

    written = await database.run(store.db_days, user_id)
    if not written:
        return []
    run = rules.streak(written, day)
    return [actions.DayItem(actions.TRACKING, f"Diary · Streak: {run} day{'' if run == 1 else 's'}", icon="📓", state=actions.TAKEN if day in written else actions.PENDING, title="Diary", count=run)]


class DiaryTask(Task):
    """Alex's diary: his words about his day, a mood, a streak, read back on request."""

    name = TASK
    place = 60  # pills, Today, reminders, personal routines, gym, calendar, diary, to-dos
    title = TITLE
    description = "Diary: your own words about your day, a mood, and a streak; read back when you ask"
    icon = ICON
    only_for = plain.ONLY_FOR
    keeps = plain.KEEPS  # question 85: a message only about the day or a feeling is kept
    examples = plain.EXAMPLES
    show = ""  # "diary" on its own is the typed word: this week, a line a day
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER  # another message the same day adds to the entry
    private = True  # its words are kept by the task alone: the core logs a note in their place
    sticks = False  # a message straight after an entry is read afresh: it is not more diary by default

    def switched_on(self) -> bool:
        return bool(config.DIARY_ENABLED)

    def actions(self) -> list:
        return plain.actions()

    async def action_state(self, request):
        return await plain.state(request)

    def keywords(self) -> list[Keyword]:
        return [Keyword(["my diary", "diary"], "this week's diary: a line a day with its mood, no words", show_word, examples=["my diary"], channels=ANY, exact=True, purpose=EACH_DAY)]

    def buttons(self) -> list[ButtonNote]:
        if not mood.on():
            return []
        return [ButtonNote(" ".join(level.emoji for level in mood.CURRENT.levels), "under a diary entry, and on the evening ask: the day's mood. Undo puts it back")]

    def migrations(self):
        return store.MIGRATIONS

    def job_handlers(self):
        return {plain.ASK_JOB: plain.ask_job, plain.TODAY_JOB: plain.today_job}

    def job_labels(self):
        return {plain.ASK_JOB: "diary evening ask", plain.TODAY_JOB: "diary on the Today card"}

    def setup(self, client) -> None:
        plain.register()
        scheduler.default_schedule(TASK, plain.ASK_JOB, ASK_DEFAULT)
        scheduler.default_schedule(TASK, plain.TODAY_JOB, TODAY_DEFAULT)

    async def startup(self, client) -> None:
        await plain.load_asks()  # a reply to the evening ask still finds it after a restart

    def claim(self, ctx: Context):
        # A reply to the evening ask is the day's entry, as it was sent; never sent to Claude
        return plain.take_reply if plain.claims(ctx.reply_target_id) else None

    async def summary(self, user_id, day):
        return await summary(user_id, day)


    async def day_items(self, user_id, day):
        return await day_items(user_id, day)

    async def week(self, user_id, monday, upto):
        return await week(user_id, monday, upto)


task = DiaryTask()
