from core import clock, config, database, hub, hubcard, repeats, scheduler, summaries, today
from core.cards import Card
from tasks.base import Task

# ---------------------------------------------------------------------------
# The Today card (core/today.py), behind TODAY_CARD: off, it is not loaded at
# all. One card in the hub under the pills card: the day in time order, from
# what each task hands over (to-dos, personal routines, reminders as notes).
# It routes nothing and has no buttons; it is posted with the morning routine
# and brought up to date in place whenever a task says its day changed.
# ---------------------------------------------------------------------------
TASK = "today"
JOB = "card"
ORDER = hub.CARDS_ORDER + 5  # the hub's order: pills, then this, then the task cards


async def card(user_id: int) -> Card | None:
    now = clock.now()
    lines = await today.gather(user_id, now)
    pieces = today.layout(lines, now)
    if not pieces:
        return None
    return Card(today.text(lines, now), (), pieces)


async def post_job(job) -> None:
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    posted = await hubcard.post(TASK, user_id, lambda: card(user_id))
    scheduler.note(job, "posted" if posted is not None else "not posted: nothing on today")


def changed(task: str, user_id: int) -> None:
    """A task's day changed: the card is brought up to date (its own changes are not news)."""
    if task != TASK:
        hubcard.changed(TASK, user_id, lambda: card(user_id))


class TodayTask(Task):
    """The Today card: the day in time order, under the pills card."""

    name = TASK
    title = "Today"
    description = "The Today card: the day in time order (to-dos, personal routines, reminders) under the pills card"
    icon = today.ICON
    only_for = "Nothing: the Today card is drawn from the other tasks and routes nothing."
    examples = ()
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER

    def switched_on(self) -> bool:
        return bool(config.TODAY_CARD)

    def actions(self) -> list:
        return []

    def job_handlers(self):
        return {JOB: post_job}

    def job_labels(self):
        return {JOB: "Today card"}

    def setup(self, client) -> None:
        scheduler.join_routine(hub.MORNING, scheduler.handler_name(TASK, JOB), order=ORDER, name=hub.MORNING_NAME)
        summaries.on_change(changed)


task = TodayTask()
