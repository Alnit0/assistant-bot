import asyncio
import csv
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from core import attention, clock, config, costs, database, devmode, hub, money, scheduler, timetable
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
#   - live's own memory use over the limit, or growing for a day: ⚠️ B9 · memory 312 MB
#   - dev mode left on (on live it shortens waits and keeps messages): 🛠️ dev mode
#
# A system problem files a bug by itself, one for each kind of problem: the
# next time it happens the same bug gets a note, never a second bug. The bugs
# task does the filing (`set_bugs`); here it is only asked for. So the item
# can point at its bug: ⚠️ B14 · backup failed.
#
# All of it is read from what the bot already keeps (the run log, the
# self-test's own files, its own process): nothing is asked of Claude. A bug
# with a fix ready to retest is the bugs task's own item.
# ---------------------------------------------------------------------------
SELFTEST_DIR = "selftest"
MORNING_ICON = "🌅"
DEV_BUG = "D"  # a self-test's bugs are the dev database's (tasks/bugs/rules.py)
_SHORTER = ("nightly ",)  # "nightly backup failed" is "backup failed" on a status line


# --- a bug for a system problem: filed by the bugs task, asked for here --------------------------------------------------
# `async (key, summary, details) -> the bug's id ("B14"), or ""`: file a bug for this kind of
# problem, or add a note to the one that is open. `async (key) -> id or ""`: the open one, if any
# `async (key, text) -> id or ""`: say on the open bug that its problem is over, once; never closes it
File = Callable[[str, str, str], Awaitable[str]]
Find = Callable[[str], Awaitable[str]]
Over = Callable[[str, str], Awaitable[str]]
_file: File | None = None
_find: Find | None = None
_over: Over | None = None
# The kinds of job whose latest run did not work: when one of them next works, its bug is told.
# Kept here so that a run that works costs nothing to look at unless its kind was in trouble
_in_trouble: set[tuple[str, str]] = set()


def set_bugs(file: File, find: Find, over: Over | None = None) -> None:
    global _file, _find, _over
    _file, _find, _over = file, find, over


async def file_bug(key: str, summary: str, details: str) -> str:
    """A bug for this kind of problem: a new one, or a note on the open one. "" if
    it could not be filed (no bugs task, no forum): the problem is still said."""
    if _file is None:
        return ""
    try:
        return await _file(key, summary, details)
    except Exception:
        log.exception("Could not file a bug for %s", key)
        return ""


async def bug_for(key: str) -> str:
    if _find is None:
        return ""
    try:
        return await _find(key)
    except Exception:
        log.exception("Could not look up the bug for %s", key)
        return ""


def job_key(task: str, kind: str) -> str:
    """What a job's bug is known by, in words: one bug for each kind of job."""
    return f"the {scheduler.label(task, kind)} job"


async def job_trouble(job, outcome: str, detail: str) -> None:
    """A run did not work (told by the scheduler): its kind of job gets a bug, or a note on the one it has."""
    label = scheduler.label(job.task, job.kind)
    summary = f"{label} {'failed' if outcome == scheduler.FAILED else 'was not done'}"
    _in_trouble.add((job.task, job.kind))
    filed = await file_bug(job_key(job.task, job.kind), summary[0].upper() + summary[1:], detail or "No reason was given.")
    log.info("A run that did not work (%s): %s", summary, f"bug {filed}" if filed else "no bug could be filed")


def worked_again(label: str, when: datetime) -> str:
    """The note a bug gets when its kind of job next works. The bug stays open: closing it is mine."""
    local = when.astimezone(config.TIMEZONE)
    from core.timeinput import format_time  # times are written one way everywhere

    return f"Worked again: the {label} ran without a problem on {local:%a} {local.day} {local:%b} at {format_time(local.time())}. This bug is still open: close it with Fixed when you are satisfied."


async def job_worked(job) -> None:
    """A run worked (told by the scheduler). If its kind of job had not been
    working, its open bug gets a note saying so, once. The bug is never closed here."""
    if (job.task, job.kind) not in _in_trouble:
        return
    _in_trouble.discard((job.task, job.kind))
    if _over is None:
        return
    try:
        noted = await _over(job_key(job.task, job.kind), worked_again(scheduler.label(job.task, job.kind), clock.real_now()))
    except Exception:
        log.exception("Could not note on its bug that %s/%s worked again", job.task, job.kind)
        return
    log.info("A kind of job that had not been working worked again (%s): %s", scheduler.label(job.task, job.kind), f"noted on {noted}" if noted else "it has no open bug")


async def remember_trouble() -> None:
    """On start: the kinds of job whose latest run did not work (the run log
    knows), so that the next one that works is noticed after a restart too."""
    try:
        _in_trouble.update((task, kind) for task, kind, _ in await scheduler.troubled())
    except Exception:
        log.exception("Could not read which jobs were not working")


def job_problem(label: str, ended: str) -> str:
    """A job that did not work, in a few words: "backup failed", "pills checklist not done"."""
    for start in _SHORTER:
        label = label.removeprefix(start)
    return f"{label} {'failed' if ended == scheduler.FAILED else 'not done'}"


async def jobs(user_id: int, now: datetime) -> list[Item]:
    """A level 1 item for each kind of job whose latest run did not work, the most recent first."""
    found = []
    when = await scheduler.troubled_at()
    for task, kind, ended in await scheduler.troubled():
        said = job_problem(scheduler.label(task, kind), ended)
        found.append(Item(said, PROBLEM, when=when.get((task, kind)), bug=await bug_for(job_key(task, kind)), short=(said,)))
    return found


# --- dev mode left on -------------------------------------------------------------------------------------------------------
DEV_MODE_ICON = "🛠️"


async def dev_mode(user_id: int, now: datetime) -> list[Item]:
    """On live, dev mode is something to put right: waits are short and nothing tidies itself."""
    if config.DEV_DATABASE or not devmode.enabled:
        return []
    return [Item("dev mode is on", PROBLEM, can_act=True, short=("dev mode",), icon=DEV_MODE_ICON, ping=False)]


# --- Claude spend over the day's limit --------------------------------------------------------------------------------------
SPEND_ICON = "💰"


async def spend(user_id: int, now: datetime) -> list[Item]:
    """A level 1 item on a day whose Claude spend has passed the daily limit: it goes with the day."""
    limit = costs.daily_limit()
    if limit <= 0:
        return []
    spent = await database.run(costs.db_spent_on, now)
    if spent <= limit:
        return []
    said = f"Claude spend today is over the limit: {costs.money(spent)} of {costs.limit_money(limit)}"
    return [Item(said, PROBLEM, short=("spend", costs.limit_money(spent)), icon=SPEND_ICON)]


# --- the bot's own memory ----------------------------------------------------------------------------------------------
MEMORY_KEY = "the bot's memory use"
SAMPLE_EVERY = 3600  # seconds: looked at, and logged, every hour
DAY_OF_SAMPLES = 24
GROWTH_WORTH_SAYING = 15.0  # MB over a day: less than this is noise, not growth
_samples: list[tuple[datetime, float]] = []  # (when, MB) since this start, the latest last; a day and a bit is kept
_memory_watch: asyncio.Task | None = None
_memory_said: datetime | None = None  # when a bug was last filed or noted for it


def memory_mb() -> float | None:
    """What this process holds of its own right now (private bytes), in MB. None where it can't be asked."""
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes as wt

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
                )]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wt.HANDLE
            if not ctypes.windll.psapi.GetProcessMemoryInfo(wt.HANDLE(ctypes.windll.kernel32.GetCurrentProcess()), ctypes.byref(counters), counters.cb):
                return None
            return counters.PrivateUsage / (1024 * 1024)
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return None


def growing(samples: list[float]) -> float:
    """How much memory use grew over the last day, in MB, if it kept growing:
    a day of hourly readings, each quarter of the day higher on average than
    the one before, and the last at least 15 MB above the first. 0 otherwise
    (also with less than a day of readings)."""
    if len(samples) < DAY_OF_SAMPLES:
        return 0.0
    day = samples[-DAY_OF_SAMPLES:]
    quarters = [sum(day[start:start + 6]) / 6 for start in range(0, DAY_OF_SAMPLES, 6)]
    rose = all(later > earlier for earlier, later in zip(quarters, quarters[1:]))
    return quarters[-1] - quarters[0] if rose and quarters[-1] - quarters[0] >= GROWTH_WORTH_SAYING else 0.0


def memory_problem(now_mb: float | None, samples: list[float], limit: float) -> str:
    """What is wrong with the memory use, in words, or "": over the limit, or growing for a day."""
    if now_mb is None:
        return ""
    if now_mb > limit:
        return f"it is {now_mb:.0f} MB, over the limit of {limit:.0f} MB"
    grew = growing(samples)
    return f"it has kept growing for a day: {grew:.0f} MB more, {now_mb:.0f} MB now" if grew else ""


def memory_line() -> str:
    """For `dev status`: what the bot holds now, its peak since it started, and how it moved over the last day."""
    now_mb = memory_mb()
    if now_mb is None:
        return "Memory: can't be read here"
    held = [value for _, value in _samples] or [now_mb]
    parts = [f"Memory: {now_mb:.0f} MB", f"peak {max(max(held), now_mb):.0f} MB since it started"]
    if len(held) >= 2:
        back = held[-DAY_OF_SAMPLES] if len(held) >= DAY_OF_SAMPLES else held[0]
        hours = min(len(held), DAY_OF_SAMPLES) - 1
        parts.append(f"{now_mb - back:+.0f} MB over the last {hours or 1} hour{'' if hours == 1 else 's'}")
    return " · ".join(parts) + f" (said as a problem over {config.MEMORY_LIMIT_MB:.0f} MB)"


async def memory(user_id: int, now: datetime) -> list[Item]:
    """A level 1 item while live's memory use is over the limit or has kept growing for a day."""
    if config.DEV_DATABASE:
        return []
    now_mb = memory_mb()
    if not memory_problem(now_mb, [value for _, value in _samples], config.MEMORY_LIMIT_MB):
        return []
    return [Item("the bot's memory use is high", PROBLEM, bug=await bug_for(MEMORY_KEY), short=(f"memory {now_mb:.0f} MB",))]


async def sample_memory(now: datetime | None = None) -> str:
    """Take the hour's reading: keep it, log it, and file or note a bug if
    something is wrong (once a day at most). Returns what is wrong, or ""."""
    global _memory_said
    now = now or clock.real_now()
    now_mb = memory_mb()
    if now_mb is None:
        return ""
    _samples.append((now, now_mb))
    del _samples[: max(0, len(_samples) - DAY_OF_SAMPLES - 2)]
    held = [value for _, value in _samples]
    wrong = memory_problem(now_mb, held, config.MEMORY_LIMIT_MB)
    log.info("Memory: %.0f MB (peak %.0f MB since the start, %d readings)%s", now_mb, max(held), len(held), f": {wrong}" if wrong else "")
    if wrong and not config.DEV_DATABASE and (_memory_said is None or now - _memory_said >= timedelta(days=1)):
        _memory_said = now
        await file_bug(MEMORY_KEY, "The bot's memory use is high", f"{wrong[0].upper()}{wrong[1:]}. The last readings, an hour apart, in MB: {', '.join(f'{value:.0f}' for value in held[-12:])}.")
    if wrong:
        attention.changed()
    return wrong


async def _watch_memory() -> None:
    while True:
        try:
            await sample_memory()
        except Exception:
            log.exception("Could not take the hour's memory reading")
        await asyncio.sleep(SAMPLE_EVERY)


def start() -> None:
    """Once the bot is connected: the first memory reading, then one an hour. Safe to call again."""
    global _memory_watch
    if _memory_watch is None or _memory_watch.done():
        _memory_watch = asyncio.create_task(_watch_memory(), name="health: memory")
        asyncio.create_task(remember_trouble(), name="health: jobs in trouble")


def history(folder) -> list[dict]:
    """The self-test's runs, a line each, oldest first; none with no history."""
    try:
        with (folder / "history.csv").open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))
    except OSError:
        return []


def last_run(folder) -> dict | None:
    """The self-test's latest run, as its line of history; None with no history."""
    rows = history(folder)
    return rows[-1] if rows else None


def month_spend(rows: list[dict], month: str) -> float:
    """What the self-test's runs spent on real requests in a month ("2026-10"), from the history."""
    total = 0.0
    for row in rows:
        if (row.get("date") or "").startswith(month):
            try:
                total += float(row.get("spend_usd") or 0)
            except ValueError:
                pass
    return total


def selftest_spend(now: datetime | None = None) -> tuple[float, float]:
    """(spent this month, the month's limit), by the real clock: money is real."""
    from core import clock

    month = f"{(now or clock.real_now()).astimezone(config.TIMEZONE):%Y-%m}"
    return month_spend(history(config.DATA_DIR / SELFTEST_DIR), month), selftest_limit()


def selftest_limit() -> float:
    """The self-test's month in US$, as its spend is recorded: SELFTEST_MONTHLY_LIMIT_NZD at the rate in use."""
    return money.usd(config.SELFTEST_MONTHLY_LIMIT_NZD)


def day_spend(rows: list[dict], day) -> float:
    """What the self-test's runs spent (US$) on one day, from the history."""
    total = 0.0
    for row in rows:
        if (row.get("date") or "").startswith(f"{day:%Y-%m-%d}"):
            try:
                total += float(row.get("spend_usd") or 0)
            except ValueError:
                pass
    return total


async def spent_on(day) -> tuple[float, float]:
    """(the bot's own use, the self-tests) in US$ on one day: what the briefing's spend line is made of. Read only."""
    return await database.run(costs.db_spent_day, day), day_spend(history(config.DATA_DIR / SELFTEST_DIR), day)


SELFTEST_ICON = "🧪"


def spend_problem(spent: float, limit: float) -> Item | None:
    """The item for a month in which the self-test has spent its limit: from then on its runs use recorded answers only."""
    if spent < limit:
        return None
    # Useful to know, not something wrong: nothing is to be done about it, and it lasts until the month ends.
    # So it is shown only when nothing else is (level 4), never in the box and never as a ping
    return Item("the self-test has spent this month's limit: recorded answers only until next month", USEFUL, short=("self-test spend", money.shown(spent)), icon=SELFTEST_ICON, ping=False)


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
    found = [selftest_problem(last_run(folder), bugs), spend_problem(*selftest_spend())]
    return [each for each in found if each is not None]


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
    attention.provide("memory", attention.PROBLEM_ICON, memory)
    attention.provide("dev mode", DEV_MODE_ICON, dev_mode)
    attention.provide("spend", SPEND_ICON, spend)
    attention.provide("morning", MORNING_ICON, morning)
    scheduler.on_ran(attention.changed)
    scheduler.on_trouble(job_trouble)
    scheduler.on_worked(job_worked)
