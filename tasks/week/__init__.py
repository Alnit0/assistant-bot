import logging
import sqlite3
from datetime import time, timedelta

from core import cards, clock, config, database, live, pins, repeats, scheduler, summaries, timetable, weekview
from core import day as days
from core.actions import SEE
from core.cards import Card
from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from tasks.base import ANY, Keyword, Task

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The week view in #calendar, behind WEEK_VIEW (off: not loaded) and with
# CALENDAR_CHANNEL_ID set. Two messages there, and nothing else of the bot's:
#
#   this week   pinned, one box a day Monday to Sunday (core/weekview.py)
#   next week   below it, a line a day
#
# Both are edited in place whenever a task says its day changed, at most
# once a minute (core/live.py), and again by a schedule of the bot's own at
# 12:01 am, which makes Monday's the new week. An edit never notifies; the
# first post is silent. "my week" anywhere answers in place with the same
# layout (the calendar task answers "this week", "next week" and "what's on
# Thursday" with it too).
# ---------------------------------------------------------------------------
TASK = "week"
ICON = weekview.ICON
JOB = "redraw"
DEFAULT = timetable.Default("Week view", time(0, 1), locked=True)
THIS, NEXT = "this", "next"
EVERY = 60.0  # seconds: at most one edit a minute


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE week_messages (
            user_id INTEGER NOT NULL REFERENCES users(id),
            slot TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, slot)
        )
        """
    )


MIGRATIONS = [create_tables]


def db_where(conn: sqlite3.Connection, user_id: int, slot: str) -> tuple[int, int] | None:
    row = conn.execute("SELECT channel_id, message_id FROM week_messages WHERE user_id = ? AND slot = ?", (user_id, slot)).fetchone()
    return (row[0], row[1]) if row else None


def db_put(conn: sqlite3.Connection, user_id: int, slot: str, channel_id: int, message_id: int) -> None:
    conn.execute(
        "INSERT INTO week_messages (user_id, slot, channel_id, message_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id, slot) DO UPDATE SET channel_id = excluded.channel_id, message_id = excluded.message_id",
        (user_id, slot, channel_id, message_id),
    )


def db_is_ours(conn: sqlite3.Connection, message_id: int) -> bool:
    return conn.execute("SELECT 1 FROM week_messages WHERE message_id = ?", (message_id,)).fetchone() is not None


async def cards_for(user_id: int) -> dict[str, Card]:
    today = days.today()
    this = await weekview.gather(user_id, weekview.week_of(today))
    following = await weekview.gather(user_id, weekview.week_of(today + timedelta(days=7)))
    return {
        THIS: Card(weekview.text(this, today, weekview.THIS_WEEK), (), weekview.this_week(this, today)),
        NEXT: Card(weekview.text(following, today, weekview.NEXT_WEEK), (), weekview.next_week(following, today)),
    }


async def redraw(user_id: int) -> str:
    """Both messages up to date: edited in place, or posted (silently) if gone, this week pinned."""
    channel_id = config.CALENDAR_CHANNEL_ID
    if channel_id is None:
        return "no #calendar set"
    said = []
    posted_this = False
    for slot, card in (await cards_for(user_id)).items():
        where = await database.run(db_where, user_id, slot)
        if where is not None and where[0] == channel_id and not posted_this and await cards.edit(channel_id, where[1], card):
            said.append(f"{slot} edited")
            continue
        if where is not None and posted_this:
            await cards.delete(where[0], where[1])  # next week stays below this week: posted again after it
        message_id = await cards.send(channel_id, card, silent=True)
        if message_id is None:
            return "#calendar can't be found"
        await database.run(db_put, user_id, slot, channel_id, message_id)
        if slot == THIS:
            posted_this = True
            try:
                await pins.set_pinned(channel_id, message_id, True, "The week view: this week")
            except UserError as error:
                log.warning("Week view: this week could not be pinned: %s", error)
        said.append(f"{slot} posted")
    return ", ".join(said)


def changed(task: str, user_id: int) -> None:
    """A task's day changed: the week view is redrawn soon, at most once a minute (the changes coalesced)."""
    if task == TASK or config.CALENDAR_CHANNEL_ID is None:
        return

    async def refresh() -> None:
        await redraw(user_id)

    live.schedule((TASK, user_id), refresh, every=EVERY)


async def redraw_job(job) -> None:
    """The bot's own, 12:01 am: today moves on, and on Monday the new week begins."""
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not drawn: there is nobody to draw it for")
        return
    scheduler.note(job, await redraw(user_id))


async def my_week(ctx: Context) -> str:
    """ "my week": this week, in place, with the same layout."""
    today = days.today()
    found = await weekview.gather(ctx.user.id, weekview.week_of(today))
    await cards.send(ctx.channel_id, Card(weekview.text(found, today, weekview.THIS_WEEK), (), weekview.this_week(found, today)))
    return "this week shown"


class WeekTask(Task):
    """The week view: this week and next in #calendar, kept up to date."""

    name = TASK
    title = "Week"
    description = "Week: this week pinned in #calendar and next week below it, kept up to date; “my week” anywhere"
    icon = ICON
    only_for = "Nothing: the week view is drawn from the other tasks; the calendar task answers questions about a week."
    examples = ()
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return bool(config.WEEK_VIEW) and config.CALENDAR_CHANNEL_ID is not None

    def keywords(self) -> list[Keyword]:
        return [Keyword(["my week"], "this week, a box a day: events, reminders, birthdays and what is due, with what comes every day counted", my_week, examples=["my week"], channels=ANY, exact=True, purpose=SEE)]

    def migrations(self):
        return MIGRATIONS

    def job_handlers(self):
        return {JOB: redraw_job}

    def job_labels(self):
        return {JOB: "week view"}

    def setup(self, client) -> None:
        scheduler.default_schedule(TASK, JOB, DEFAULT)
        summaries.on_change(changed)

    async def startup(self, client) -> None:
        from core.users import get_user_by_discord_id

        owner = await get_user_by_discord_id(int(config.OWNER_ID)) if config.OWNER_ID else None
        if owner is not None:
            live.background(redraw(owner.id))  # a start says nothing: the two messages are only brought up to date

    async def message_class(self, message_id):
        return MessageClass.LIVE if await database.run(db_is_ours, message_id) else None

    async def owns_message(self, message_id):
        return await database.run(db_is_ours, message_id)


task = WeekTask()
