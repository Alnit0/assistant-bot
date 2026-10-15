"""Which part of the self-test a change needs, and whether the PC has room for it.

No Discord and no bot here: only decisions, so they can be tested offline.
"""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

from core import money

# ---------------------------------------------------------------------------
# The run is one story in six starts of the dev bot. It is cut into three
# stages that can each be run alone:
#
#   day       starts 1 to 4: a pill day on the dev clock, the cards in both
#             looks, reminders, the restart in the middle, the engine and
#             `my schedule`
#   briefing  start 5: BRIEFING_ENABLED on
#   tidy      starts 5 and 6: HUB_TIDY on as well. Start 5 comes with it,
#             because the tidy has to find messages from before it was on
#
# A stage that begins at start 5 makes its own pills first (`phases.seed`),
# with recorded answers only.
# ---------------------------------------------------------------------------
STAGES = {"day": ("p1", "p2", "p3", "p4"), "briefing": ("p5",), "tidy": ("p5", "p6"), "todos": ("p7",), "round4": ("p8",), "hub": ("p9",)}
ORDER = ("day", "briefing", "tidy", "todos", "round4", "hub")
ABOUT_MINUTES = {"p1": 4, "p2": 2.5, "p3": 2, "p4": 1.5, "p5": 2, "p6": 2.5, "p7": 2, "p8": 1.5, "p9": 2}

# What a changed file touches, first match wins. Anything not listed is the
# bot's own code, shared by everything: all three stages.
NOTHING = ("docs/", "tests/", "evals/", ".claude/", "data/", "logs/")
RULES = (
    (("tasks/briefing/", "core/summaries.py", "tasks/pills/summary.py"), ("briefing",)),
    (("core/messages.py",), ("tidy",)),
    (("tasks/todos/", "core/hubcard.py"), ("todos", "hub")),
    (("tasks/nudges/", "tasks/habits/", "tasks/today/", "core/today.py", "core/recurrence.py"), ("hub",)),
    (("tasks/pills/sheet.py",), ("day", "round4")),
    (("tasks/",), ("day",)),
)

# Under this much free, a run is not started. Measured on 2026-10-13 (one full run, sampled every two
# seconds): the run's own processes peak at about 180 MB (the runner 63, the dev bot 121) and free memory
# dropped by at most 240 MB while it ran. So the run is small; what stops one is the rest of the PC (8 GB)
# running short, at which point Claude Code ends background commands. Runs started with 1.7 GB free or
# more all finished; one started at 1.6 GB was stopped. The line is that 1.6 GB plus the run's own 0.25 GB,
# rounded up: with 1.9 GB free at the start, the PC keeps about 1.65 GB while the run is at its peak
LOW_MEMORY = 1900 * 1024 * 1024


def phases_for(stages) -> list[str]:
    """The starts to run for these stages, each once, in the story's order."""
    return sorted({phase for stage in stages for phase in STAGES[stage]})


def stages_of(path: str) -> tuple[str, ...]:
    """The stages one changed file touches."""
    path = path.replace("\\", "/")
    if path.startswith(NOTHING) or (path.endswith(".md") and "/" not in path):
        return ()
    for prefixes, stages in RULES:
        if path.startswith(prefixes):
            return stages
    return ORDER


def touched(changed: dict[str, list[str] | None]) -> dict[str, str]:
    """{stage: why} for the stages to run. `changed` says, a stage, the files
    changed since that stage last passed (None: it has never passed)."""
    found: dict[str, str] = {}
    for stage in ORDER:
        paths = changed.get(stage)
        if paths is None:
            found[stage] = "it has not passed here yet"
            continue
        because = [path for path in paths if stage in stages_of(path)]
        if because:
            found[stage] = ", ".join(because[:3]) + (f" and {len(because) - 3} more" if len(because) > 3 else "")
    return found


# --- when a run is worth what it costs --------------------------------------------------------------------------
# Recorded answers are the rule: they cost nothing. Real requests to Claude are for when what
# Claude is given or asked may have changed: the prompts, the schemas (a task's actions and
# their fields) and the routing.
LANGUAGE = ("core/router.py", "core/routing.py", "core/extraction.py", "core/llm.py", "core/actions.py", "core/conversation.py")
LANGUAGE_IN_A_TASK = ("/plain.py", "/__init__.py")  # where a task says its actions, their fields and its examples


def is_language(path: str) -> bool:
    """Whether a changed file can change what Claude is asked or how its answer is read."""
    path = path.replace("\\", "/")
    return path in LANGUAGE or (path.startswith("tasks/") and path.endswith(LANGUAGE_IN_A_TASK))


def language_changed(paths: list[str] | None) -> list[str] | None:
    """Of the files changed since the last run with real requests, the ones
    that are about prompts, schemas or routing. None when that can't be told
    (no such run on record): then a real run is due."""
    return None if paths is None else [path for path in paths if is_language(path)]


def use_real(asked_real: bool, asked_recorded: bool, sunday_full: bool, language: list[str] | None, spent: float, limit: float) -> tuple[bool, str]:
    """Whether this run sends real requests, and why, in words for the run's
    first lines. The month's cap comes before everything: over it, nothing is spent."""
    if spent >= limit:
        return False, f"recorded answers only: this month's self-test spend is {money.shown(spent)}, over the limit of {money.shown(limit)} (SELFTEST_MONTHLY_LIMIT_NZD)"
    if asked_recorded:
        return False, "recorded answers, as asked"
    if asked_real:
        return True, "real requests, as asked"
    if sunday_full:
        return True, "real requests: the Sunday full run"
    if language is None:
        return True, "real requests: no run with real requests is on record"
    if language:
        shown = ", ".join(language[:3]) + (f" and {len(language) - 3} more" if len(language) > 3 else "")
        return True, f"real requests: prompts, schemas or routing changed since the last real run ({shown})"
    return False, "recorded answers: nothing about prompts, schemas or routing has changed since the last real run"


def last_real(rows: list[dict]) -> str | None:
    """The commit of the latest finished run with real requests, from the history. None with none."""
    for row in reversed(rows):
        if row.get("claude") == "real" and not row.get("note") and row.get("commit"):
            return row["commit"]
    return None


def nothing_new(head_commit: str | None, passed: dict[str, str]) -> bool:
    """A night with nothing to do: every stage last passed on the very commit
    that is checked out. (Edits that are not committed do not make a night's
    run: they are still being worked on.)"""
    return bool(head_commit) and all(passed.get(stage) == head_commit for stage in ORDER)


# --- what git says ---------------------------------------------------------------------------------------------
def _git(root: Path, *args: str) -> list[str] | None:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    return [line for line in done.stdout.splitlines() if line.strip()] if done.returncode == 0 else None


def head(root: Path) -> str | None:
    found = _git(root, "rev-parse", "HEAD")
    return found[0] if found else None


def changed_since(root: Path, commit: str | None) -> list[str] | None:
    """The files that differ from `commit`, committed or not, and the new ones
    git does not know yet. None when that can't be found out (then: run it)."""
    if not commit:
        return None
    differing = _git(root, "diff", "--name-only", commit)
    new = _git(root, "ls-files", "--others", "--exclude-standard")
    if differing is None or new is None:
        return None
    return sorted({*differing, *new})


def read_passed(path: Path) -> dict[str, str]:
    """{stage: the commit it last passed on}."""
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {stage: str(commit) for stage, commit in found.items() if stage in STAGES and commit}


def write_passed(path: Path, passed: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(passed, indent=1), encoding="utf-8")


def passed_stages(ran: list[str], failed_phases: set[str]) -> list[str]:
    """The stages whose every start ran with nothing failed."""
    return [stage for stage in ORDER if all(phase in ran and phase not in failed_phases for phase in STAGES[stage])]


# --- room on the PC --------------------------------------------------------------------------------------------
def free_memory() -> int | None:
    """Bytes of memory free now, or None where that can't be asked (not Windows)."""
    if sys.platform != "win32":
        return None

    class Status(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong), ("free_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
            ("free_virtual", ctypes.c_ulonglong), ("free_extended", ctypes.c_ulonglong),
        ]

    status = Status()
    status.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.free)


def memory_line(free: int | None) -> tuple[bool, str]:
    """(low or not, what to say)."""
    if free is None:
        return False, "free memory: could not be read"
    gb = free / 1024**3
    if free < LOW_MEMORY:
        return True, f"free memory: {gb:.1f} GB, which is LOW (under {LOW_MEMORY / 1024**3:.1f} GB): a run has been stopped by the PC for that before"
    return False, f"free memory: {gb:.1f} GB"
