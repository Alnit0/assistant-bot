import csv
import json
import logging
from datetime import datetime

from core import attention, config, database, hub, scheduler, timetable
from core.attention import PROBLEM, USEFUL, Item

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The core's own attention items (core/attention.py): what is wrong with the
# bot itself, and when the day starts again.
#
# For now live shows its own system problems at level 1:
#   - a job whose latest run failed, or was skipped for a real problem (the
#     run log), until that job next works:            ⚠️ backup failed
#   - a self-test whose latest run had a failing step or did not finish,
#     with the id of the bug of its first failing step: ⚠️ D3 · self-test failed
# and, when nothing else is left, when the morning routine next runs:  🌅 6am
#
# All of it is read from what the bot already keeps (the run log, the
# self-test's own files): nothing is written and nothing is asked of Claude.
# A bug with a fix ready to retest is the bugs task's own item.
# ---------------------------------------------------------------------------
SELFTEST_DIR = "selftest"
MORNING_ICON = "🌅"
DEV_BUG = "D"  # a self-test's bugs are the dev database's (tasks/bugs/rules.py)
_SHORTER = ("nightly ",)  # "nightly backup failed" is "backup failed" on a status line


def job_problem(label: str, ended: str) -> str:
    """A job that did not work, in a few words: "backup failed", "pills checklist not done"."""
    for start in _SHORTER:
        label = label.removeprefix(start)
    return f"{label} {'failed' if ended == scheduler.FAILED else 'not done'}"


async def jobs(user_id: int, now: datetime) -> list[Item]:
    """A level 1 item for each kind of job whose latest run did not work, the most recent first."""
    found = []
    for task, kind, ended in await scheduler.troubled():
        said = job_problem(scheduler.label(task, kind), ended)
        found.append(Item(said, PROBLEM, short=(said,)))
    return found


def last_run(folder) -> dict | None:
    """The self-test's latest run, as its line of history; None with no history."""
    try:
        with (folder / "history.csv").open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
    except OSError:
        return None
    return rows[-1] if rows else None


def selftest_problem(row: dict | None, bugs: dict) -> Item | None:
    """The item for a self-test's latest run, if it failed or did not finish.
    `bugs` is {step: the number of its bug}."""
    if row is None:
        return None
    failed = (row.get("failed_steps") or "").split()
    if not failed and not row.get("note"):
        return None
    said = "self-test failed" if failed else "self-test did not finish"
    number = next((bugs[step] for step in failed if step in bugs), None)
    try:
        when = datetime.strptime(row.get("date") or "", "%Y-%m-%d %H:%M").replace(tzinfo=config.TIMEZONE)
    except ValueError:
        when = None
    return Item(said, PROBLEM, when=when, bug=f"{DEV_BUG}{number}" if number is not None else "", short=(said,))


async def selftest(user_id: int, now: datetime) -> list[Item]:
    """Live's own: the dev bot never reports on the self-test it is running."""
    if config.DEV_DATABASE:
        return []
    folder = config.DATA_DIR / SELFTEST_DIR
    try:
        bugs = {str(step): int(number) for step, number in json.loads((folder / "bugs.json").read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError, TypeError):
        bugs = {}
    found = selftest_problem(last_run(folder), bugs)
    return [found] if found is not None else []


async def morning(user_id: int, now: datetime) -> list[Item]:
    """When the morning routine next runs: something useful with nothing else to say."""
    schedule = await database.run(timetable.db_for_default, hub.MORNING)
    if schedule is None or schedule.state != timetable.ON:
        return []
    coming = await scheduler.coming(schedule)
    if coming is None:
        return []
    return [Item("the morning routine", USEFUL, when=coming.moment, short=(attention.short_time(coming.moment),), icon=MORNING_ICON)]


def setup() -> None:
    """Hand the core's own items in, and say they may have changed whenever a job has run."""
    attention.provide("system", attention.PROBLEM_ICON, jobs)
    attention.provide("selftest", attention.PROBLEM_ICON, selftest)
    attention.provide("morning", MORNING_ICON, morning)
    scheduler.on_ran(attention.changed)
