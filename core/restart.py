import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import discord

from core import database, discord_utils, identity, scheduler
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
# ---------------------------------------------------------------------------
STARTED = real_now_nz()  # when this copy of the bot began: an input logged before it is not being handled now
RECEIVED, INTERRUPTED = "received", "interrupted"
WHY = "the bot stopped before this was finished"
TITLE = "🔁 Caught up after a restart"
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
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client is not None and channel_id else None
    if channel is None or message_id is None:
        return False
    message = channel.get_partial_message(message_id)
    try:
        await message.remove_reaction(SEEN, client.user)
    except discord.HTTPException:
        pass  # it had none, or has gone
    try:
        await message.add_reaction(FAILED)
    except discord.HTTPException as error:
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
            return f"A press of {task}/{action} was cut off by the stop. Nothing was done about it: press it again if it didn't take"
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


async def catch_up() -> list[str]:
    """Once, when the bot starts and its tasks are ready: put right what was
    cut off, run what came due meanwhile, and say all of it in one message in
    #bot-log. Returns the lines (none: nothing was posted). Never raises."""
    global _catching_up
    lines: list[str] = []
    try:
        for cut in await database.run(db_cut_off, STARTED):
            try:
                lines.append(await _put_right(cut))
            except Exception as error:
                log.exception("Could not put right the input cut off in log row %s", cut.row_id)
                lines.append(f"Log row {cut.row_id} was cut off by the stop and could not be checked: {error!r}")
        again, late = await scheduler.catch_up()
        if again:
            lines.append(f"{again} job{'' if again == 1 else 's'} cut off by the stop ran again")
        if late:
            lines.append(late_line(late))
        lines += _lines
    except Exception:
        log.exception("Catching up after the restart failed")
    finally:
        _lines.clear()
        _catching_up = False
    for line in lines:
        log.info("Caught up: %s", line)
    if lines:
        await discord_utils.log_simple(TITLE, "\n".join(f"• {line}" for line in lines))
    return lines
