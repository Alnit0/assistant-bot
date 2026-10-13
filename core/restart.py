import logging
import re
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import clock, database, discord_utils, identity, outgoing, scheduler, surface
from core.config import real_now_nz

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Starting again, after a restart or a crash: the bot catches up on what it
# missed, says so once in #bot-log, and never says a thing was done that
# wasn't.
#
# Nothing here remembers anything of its own. What was going on when the bot
# stopped is read from what is already kept:
#
#   message_log     every input is logged as "received" before it is handled
#                   and given its outcome after. A row still "received" from
#                   before this start was cut off half way: it is marked
#                   "interrupted", a message of mine gets ⚠️ in place of 👀
#                   (as any message that failed does), and a button press is
#                   put right by its task if the task said how (`on_cut_off`)
#   scheduled_jobs  a job left running goes back in the queue, and every job
#                   that came due while the bot was off runs now, late
#                   (core/scheduler.py, `catch_up`)
#
# A task that catches up on something of its own at start (a checklist posted
# late, a day closed late) says so with `caught_up`, and all of it goes in one
# message. With nothing to say, nothing is posted.
#
# A start itself says nothing anywhere: that the bot is up is its presence
# and its status line. A restart that was asked for leaves no trace. One
# that was not is said, as the first line of that same one message:
#
#   the PC restarted   it started after the bot last noted it was running
#                      (`bot_alive`, noted twice a minute: core/missed.py)
#   the bot crashed    the run ended by itself with an error, which main.py
#                      notes on its way out (`note_crash`)
#
# Anything else is taken as asked for: the service stopped or restarted by
# hand. (A process killed with no chance to say so, and no restart of the
# PC, reads as asked for too: there is nothing to tell the two apart by.)
# ---------------------------------------------------------------------------
STARTED = real_now_nz()  # when this copy of the bot began: an input logged before it is not being handled now
RECEIVED, INTERRUPTED = "received", "interrupted"
WHY = "the bot stopped before this was finished"
TITLE = "🔁 Caught up after a restart"
UNEXPECTED = "⚠️ Back after an unexpected stop"  # the title instead, when nobody asked for the restart
SLACK = timedelta(seconds=90)  # the PC is up a while before the bot is: a start this close to the last note is the same run
SEEN, FAILED = "👀", "⚠️"
# Inputs that are a message of the user's own (core/database.py, OWN_MESSAGE_KINDS): those get the ⚠️
OWN_MESSAGES = ("chat", "command", "reply_action", "expected", "confirmation")
PRESS = "card"  # a button, dropdown or form of core/cards.py, logged as "card: task/action arg"
SHOWN = 60  # how much of what was said goes in the line
_PRESS = re.compile(r"card: (?P<task>[a-z0-9_]+)/(?P<action>[a-z0-9_]+)(?: (?P<arg>\S+))?")


@dataclass(frozen=True)
class CutOff:
    """An input the bot was still handling when it stopped."""

    row_id: int
    kind: str
    content: str
    channel_id: int | None
    message_id: int | None  # my message, or for a press the message the button is on
    user_id: int | None

    @property
    def press(self) -> tuple[str, str, str] | None:
        """(task, action, arg) if this was a press on a card."""
        found = _PRESS.match(self.content) if self.kind == PRESS else None
        return (found["task"], found["action"], found["arg"] or "") if found else None


# `async (cut, arg) -> str`: put right a press that was cut off, and return the line for #bot-log
Recovery = Callable[[CutOff, str], Awaitable[str]]

_recoveries: dict[tuple[str, str], Recovery] = {}
_lines: list[str] = []
_catching_up = True  # from the moment the bot starts until `catch_up` has reported


def on_cut_off(task: str, action: str, recover: Recovery) -> None:
    """Say how a press of this button is put right if the bot stopped while
    doing it. Without one, the press is only reported."""
    _recoveries[(task, action)] = recover


def caught_up(line: str) -> bool:
    """A task did something late because the bot was off: one line for the
    start's message in #bot-log. Only kept while the bot is starting (False
    otherwise: the same work done on time is nothing to report)."""
    if _catching_up:
        _lines.append(line)
    return _catching_up


def db_cut_off(conn: sqlite3.Connection, before: datetime) -> list[CutOff]:
    """The inputs still "received" from before this start, each marked
    interrupted so it is only ever found once."""
    rows = conn.execute(
        "SELECT id, kind, content, channel_id, discord_message_id, user_id, received_at FROM message_log WHERE status = ? ORDER BY id",
        (RECEIVED,),
    ).fetchall()
    found = [CutOff(*row[:6]) for row in rows if datetime.fromisoformat(row[6]) < before]
    for cut in found:
        conn.execute("UPDATE message_log SET status = ?, error = ? WHERE id = ?", (INTERRUPTED, WHY, cut.row_id))
    return found


async def mark(channel_id: int | None, message_id: int | None) -> bool:
    """⚠️ in place of 👀 on a message of mine that was never answered."""
    if surface.place(channel_id) is None or message_id is None:
        return False
    try:
        await surface.unreact(channel_id, message_id, SEEN)
    except surface.Failed:
        pass  # it had none, or has gone
    try:
        await surface.react(channel_id, message_id, FAILED)
    except surface.Failed as error:
        log.info("Could not mark message %s as cut off: %s", message_id, error)
        return False
    return True


async def _put_right(cut: CutOff) -> str:
    """Deal with one input that was cut off, and say what was done about it."""
    press = cut.press
    if press is not None:
        task, action, arg = press
        recover = _recoveries.get((task, action))
        if recover is None:
            # Which button, in the code's own words, is for the log file: the card says whose it was
            log.info("The press cut off by the stop was %s/%s %s (log row %s)", task, action, arg, cut.row_id)
            return f"A press of a button of {task}'s was cut off by the stop. Nothing was done about it: press it again if it didn't take"
        return await recover(cut, arg)
    said = cut.content if len(cut.content) <= SHOWN else cut.content[: SHOWN - 1] + "…"
    if cut.kind in OWN_MESSAGES and await mark(cut.channel_id, cut.message_id):
        return f"“{said}” was cut off by the stop and never answered: marked {FAILED}, say it again"
    return f"“{said}” ({cut.kind}) was cut off by the stop and never finished"


def late_line(jobs: list) -> str:
    """The jobs that ran late, in a line: "pills checklist (2h late), tidy ×3"."""
    names: dict[str, list[float]] = {}
    for job in jobs:
        names.setdefault(identity.job_name(job.task, job.kind), []).append(job.late_by)
    parts = [
        f"{name} ({identity.uptime(max(late))} late)" if len(late) == 1 else f"{name} ×{len(late)}"
        for name, late in names.items()
    ]
    return "Ran late, as the bot was off when they were due: " + ", ".join(parts)


def skipped_line(jobs: list) -> str:
    """The runs that were not done because they were too late to be worth it,
    under their schedule's own rule: "morning briefing (7h late)"."""
    parts = [f"{identity.job_name(job.task, job.kind)} ({identity.uptime(job.late_by)} late)" for job in jobs]
    return "Skipped as too late, as its schedule says: " + ", ".join(parts)


# --- a restart nobody asked for ---------------------------------------------------------------------------------------
def booted_at() -> datetime | None:
    """When the PC started, or None where that can't be asked (not Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_uint64
        return clock.real_now() - timedelta(milliseconds=ctypes.windll.kernel32.GetTickCount64())
    except Exception:
        return None


def db_last_run(conn: sqlite3.Connection) -> tuple[datetime | None, str]:
    """When the bot last noted it was running, and how that run ended if it
    ended by itself with an error. Read once: the note of the error is cleared."""
    row = conn.execute("SELECT at, ended FROM bot_alive WHERE id = 1").fetchone()
    if row is None:
        return None, ""
    conn.execute("UPDATE bot_alive SET ended = NULL WHERE id = 1")
    return datetime.fromisoformat(row[0]), row[1] or ""


def note_crash(error: BaseException) -> None:
    """The run is ending by itself with an error: noted for the next start to
    say. Blocking, on the way out of main.py. Never raises."""
    try:
        conn = database.connect()
        try:
            with conn:
                conn.execute("UPDATE bot_alive SET ended = ? WHERE id = 1", (f"{type(error).__name__}: {error}"[:200],))
        finally:
            conn.close()
    except Exception:
        log.exception("Could not note that the bot stopped with an error")


def stopped_line(alive: datetime | None, ended: str, booted: datetime | None, now: datetime) -> str:
    """The line for a restart nobody asked for, or "" for one that was asked
    for (and for a first start, with no earlier run to speak of). Pure."""
    if alive is None:
        return ""
    off = identity.uptime(max(0.0, (now - alive).total_seconds()))
    if booted is not None and booted > alive + SLACK:
        return f"The PC restarted: the bot was off for about {off}"
    if ended:
        return f"The bot stopped by itself with an error and was started again: off for about {off}"
    return ""


def checked(lines: list[str]) -> list[str]:
    """The lines as they may be shown: the same check as everything the bot
    says (core/outgoing.py: no internal label), and no job by the code's own
    name for it. A line with nothing left to say is dropped."""
    said = [outgoing.clean(scheduler.in_words(line)) for line in lines]
    return [line for line in said if line.strip()]


async def catch_up() -> list[str]:
    """Once, when the bot starts and its tasks are ready: put right what was
    cut off, run what came due meanwhile, and say all of it in one message in
    #bot-log. Returns the lines (none: nothing was posted). Never raises."""
    global _catching_up
    lines: list[str] = []
    unexpected = ""
    try:
        alive, ended = await database.run(db_last_run)
        unexpected = stopped_line(alive, ended, booted_at(), clock.real_now())
        if unexpected:
            lines.append(unexpected)
            log.warning("This start was not asked for: %s%s", unexpected, f" ({ended})" if ended else "")
        for cut in await database.run(db_cut_off, STARTED):
            try:
                lines.append(await _put_right(cut))
            except Exception as error:
                log.exception("Could not put right the input cut off in log row %s", cut.row_id)
                lines.append(f"Log row {cut.row_id} was cut off by the stop and could not be checked: {error!r}")
        again, late, skipped = await scheduler.catch_up()
        if again:
            lines.append(f"{again} job{'' if again == 1 else 's'} cut off by the stop ran again")
        if late:
            lines.append(late_line(late))
        if skipped:
            lines.append(skipped_line(skipped))
        lines += _lines
    except Exception:
        log.exception("Catching up after the restart failed")
    finally:
        _lines.clear()
        _catching_up = False
    lines = checked(lines)
    for line in lines:
        log.info("Caught up: %s", line)
    if lines:
        await discord_utils.log_simple(UNEXPECTED if unexpected else TITLE, "\n".join(f"• {line}" for line in lines))
    return lines
