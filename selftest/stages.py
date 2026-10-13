"""Which part of the self-test a change needs, and whether the PC has room for it.

No Discord and no bot here: only decisions, so they can be tested offline.
"""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

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
STAGES = {"day": ("p1", "p2", "p3", "p4"), "briefing": ("p5",), "tidy": ("p5", "p6")}
ORDER = ("day", "briefing", "tidy")
ABOUT_MINUTES = {"p1": 4, "p2": 2.5, "p3": 2, "p4": 1.5, "p5": 2, "p6": 2.5}

# What a changed file touches, first match wins. Anything not listed is the
# bot's own code, shared by everything: all three stages.
NOTHING = ("docs/", "tests/", "evals/", ".claude/", "data/", "logs/")
RULES = (
    (("tasks/briefing/", "core/summaries.py", "tasks/pills/summary.py"), ("briefing",)),
    (("core/messages.py",), ("tidy",)),
    (("tasks/",), ("day",)),
)

LOW_MEMORY = 1500 * 1024 * 1024  # under this much free, a run has been stopped by the PC before (8 GB in all)


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
