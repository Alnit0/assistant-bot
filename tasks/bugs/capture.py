import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from core.config import BASE_DIR, LOG_DIR
from core.clock import real_now
from core.scheduler import to_db
from tasks.bugs import rules, store

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Gathering what goes with a report, once the message and the ones before it
# are in hand: the logged turn, the log's errors from around it, and the code
# that was running. No Discord in here.
# ---------------------------------------------------------------------------
LOG_FILE = LOG_DIR / "bot.log"
LOG_TAIL_BYTES = 400_000  # the end of bot.log is enough: a report is about something recent

_commit: str | None = None


def read_commit() -> str:
    """The short hash of the commit checked out here, or "unknown". Blocking."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as error:
        log.info("Could not read the git commit: %s", error)
        return "unknown"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unknown"


async def git_commit() -> str:
    """The commit the bot started on: read once (at startup) and remembered, so
    it names the code that is running and not what has been checked out since."""
    global _commit
    if _commit is None:
        _commit = await asyncio.to_thread(read_commit)
    return _commit


def read_log_tail(path: Path | None = None, max_bytes: int = LOG_TAIL_BYTES) -> list[str]:
    """The last lines of bot.log. Blocking. Empty if it can't be read."""
    path = path or LOG_FILE
    try:
        with open(path, "rb") as file:
            file.seek(0, 2)
            start = max(0, file.tell() - max_bytes)
            file.seek(start)
            lines = file.read().decode("utf-8", errors="replace").splitlines()
            # Starting part-way through the file means part-way through a line
            return lines[1:] if start else lines
    except OSError as error:
        log.info("Could not read %s: %s", path, error)
        return []


def _log_clock(moment: datetime) -> datetime:
    """A moment as bot.log writes it: this machine's local time, with no zone."""
    return moment.astimezone().replace(tzinfo=None)


async def build(
    *,
    source: str,
    channel_id: int,
    target: rules.Snapshot,
    preceding: list[rules.Snapshot],
    exclude_message_id: int | None = None,
) -> rules.Report:
    """Put a report together around a message and the ones before it."""
    target_at = datetime.fromisoformat(target.at)
    turn = rules.pick_turn(await store.recent_log(channel_id), target.message_id, target_at, exclude_message_id)
    start, end = rules.log_window(turn, target_at)
    lines = await asyncio.to_thread(read_log_tail)
    return rules.Report(
        source=source,
        channel_id=channel_id,
        channel=rules.channel_label(channel_id),
        target=target,
        preceding=preceding,
        turn=turn,
        errors=rules.related_errors(lines, _log_clock(start), _log_clock(end)),
        commit=await git_commit(),
        reported_at=to_db(real_now()),
    )
