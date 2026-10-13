import re
import sqlite3
from datetime import datetime
from pathlib import Path

from core import config
from selftest import onlyyou

# ---------------------------------------------------------------------------
# The self-test's report: docs/SELFTEST.md, written again by every full run.
# ---------------------------------------------------------------------------
PATH = config.BASE_DIR / "docs" / "SELFTEST.md"
# The log of the bot that ran the steps: the dev bot's own when there is one
LOG = config.BASE_DIR / "logs" / ("dev-bot.log" if config.test_bot_token() else "bot.log")
MARK = {"pass": "✅ pass", "fail": "❌ fail", "error": "💥 broke", "skip": "⏭️ skipped"}
SLOW = 12.0  # seconds: a step slower than this is listed (most of a step is waiting on Discord)
PHASE_WORDS = {
    "p1": "Start 1: the old look, reminders on. A day of pills up to the afternoon, then the bot is cut off mid-message",
    "p2": "Start 2: the same settings, after 75 seconds off. The catch-up, then the rest of the day and the next morning",
    "p3": "Start 3: `CARDS_V2` on. Every card posted and edited in the new look, and the old look's messages edited under it",
    "p4": "Start 4: `CARDS_V2` off again, and a tiny spend limit. The new look's messages edited under the old, and the spend line",
    "p5": "Start 5: `BRIEFING_ENABLED` on (the starts before it had it off). The morning routine, “brief me”, and the briefing kept up to date in place",
    "p6": "Start 6: `HUB_TIDY` on as well (off until now). What is said in the hub goes once handled, pinned stays, yesterday goes in the morning, and a copy is saved first",
}
_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (WARNING|ERROR|CRITICAL) (.*)$")


def spent(database: Path) -> float:
    """What the run's requests to Claude cost, from its own database."""
    if not database.exists():
        return 0.0
    conn = sqlite3.connect(database)
    try:
        return float(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls").fetchone()[0])
    except sqlite3.Error:
        return 0.0
    finally:
        conn.close()


def log_trouble(began: datetime, ended: datetime, path: Path = LOG) -> list[tuple[int, str]]:
    """The warnings and errors the bot logged during the run: (how often, the line without its time)."""
    if not path.exists():
        return []
    found: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        at = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S")
        if began <= at <= ended:
            said = f"{match[2]} {match[3]}"
            found[said] = found.get(said, 0) + 1
    return [(count, said) for said, count in found.items()]


def _cell(text: str) -> str:
    return " ".join(str(text).replace("|", "¦").split())


def discoveries(results: list[dict], trouble: list[tuple[int, str]], seconds: int) -> list[str]:
    lines = ["## Discoveries", "", "What is worth a look whether or not its step passed.", ""]
    odd = [each for each in results if each.get("odd")]
    lines += ["**Odd, though the step passed**", ""]
    lines += [f"- {each['key']}: {each['odd']}" for each in odd] or ["- Nothing."]
    lines += ["", f"**Warnings and errors in `logs/{LOG.name}` during the run**", ""]
    lines += [f"- {'×' + str(count) + ' ' if count > 1 else ''}`{_cell(said)[:300]}`" for count, said in trouble] or ["- None."]
    slow = sorted((each for each in results if each.get("seconds", 0) >= SLOW), key=lambda each: -each["seconds"])
    lines += ["", f"**Slow steps** ({SLOW:.0f} seconds or more; a step is mostly waiting for Discord, and each input is given about a second to settle)", ""]
    lines += [f"- {each['key']} {each['title']}: {each['seconds']:.0f}s" for each in slow] or ["- None."]
    lines += ["", f"The whole run took {seconds // 60} min {seconds % 60} s, 75 seconds of it with the bot off on purpose.", ""]
    lines += ["**In the specs and not tested here**", ""]
    lines += [f"- {each}" for each in onlyyou.NOT_TESTED]
    return lines + [""]


def text(phases, cost: float, claude: bool, stamp: str, partial: bool = False, began: datetime | None = None, ended: datetime | None = None, ran: str = "") -> str:
    results = [each for _, _, found in phases for each in found["results"]]
    counts = {status: sum(1 for each in results if each["status"] == status) for status in MARK}
    real = sum(1 for each in results if each.get("claude") == "real request")
    seconds = int((ended - began).total_seconds()) if began and ended else sum(found.get("seconds", 0) for _, _, found in phases)
    lines = [
        "# Self-test",
        "",
        "Written by `python -m selftest`: the dev bot run against real Discord in",
        "channels of its own (#selftest-hub, #selftest-inbox, #selftest-log), on an",
        "empty copy of the dev database, with the dev clock. What is typed and",
        "pressed is simulated (handed straight to the bot's own entry points); what",
        "the bot posts, edits and deletes is real, and is read back from Discord and",
        "from the database before a step passes. How it works and what it can't",
        "see: `docs/DEVELOPMENT.md`, \"The self-test\".",
        "",
        f"**Run:** {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}, {seconds // 60} min {seconds % 60} s"
        + ((f" · **part of the run only: {ran}**" if ran else " · **part of the run only**") if partial else ""),
        f"**Result:** {counts['pass']} passed, {counts['fail']} failed, {counts['error']} broke, {counts['skip']} skipped, of {len(results)} steps",
        f"**Requests to Claude:** {'real for ' + str(real) + ' steps' if claude else 'none real: every language step used a recorded answer'} · US${cost:.4f} spent",
        "",
    ]
    bad = [each for each in results if each["status"] in ("fail", "error")]
    lines += ["## What failed", ""]
    if bad:
        lines += ["| Step | What | Expected | What happened | From |", "|---|---|---|---|---|"]
        lines += [f"| {each['key']} | {_cell(each['title'])} | {_cell(each['expect'])} | {_cell(each['saw'])} | {_cell(each['source'])} |" for each in bad]
    else:
        lines.append("Nothing.")
    lines.append("")
    lines += discoveries(results, log_trouble(began, ended) if began and ended else [], seconds)
    for name, settings, found in phases:
        said = ", ".join(f"`{key}={value}`" for key, value in settings.items())
        lines += [f"## {PHASE_WORDS.get(name, name)}", "", f"Settings: {said}. Took {found.get('seconds', '?')}s; the process ended with {found.get('exit')}.", ""]
        lines += ["| Step | What | Result | Expected | Saw | Claude | From |", "|---|---|---|---|---|---|---|"]
        for each in found["results"]:
            lines.append(
                f"| {each['key']} | {_cell(each['title'])} | {MARK[each['status']]} | {_cell(each['expect'])} | {_cell(each['saw'])} | {_cell(each.get('claude', ''))} | {_cell(each['source'])} |"
            )
        lines.append("")
    lines += onlyyou.lines()
    lines += [
        "## The test's channels and data",
        "",
        "- The category `selftest` and its three channels are left in place, holding the last run. Every run empties them first.",
        "- To empty them now: `python -m selftest --clear`. To delete them and the category: `python -m selftest --remove` (the next run makes them again). Both work over HTTP, with live running.",
        "- `data/dev.db` and the dev clock are as they were before the run: they are moved aside for it and put back after.",
        f"- The run's own database and each start's results are kept in `data/selftest/run-{stamp}/` (never in git). Delete the folder when you like.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write(phases, cost: float, claude: bool, stamp: str, partial: bool = False, began: datetime | None = None, ended: datetime | None = None, ran: str = "") -> Path:
    path = PATH if not partial else config.DATA_DIR / "selftest" / f"run-{stamp}" / "SELFTEST-partial.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text(phases, cost, claude, stamp, partial, began, ended, ran).replace("\n", "\r\n").encode("utf-8"))
    return path
