import asyncio
import logging
from datetime import datetime, timedelta

import discord

from core import about, clock, devmode, discord_utils, scheduler, tidy
from core.config import DEV_DATABASE, INBOX_CHANNEL_ID, TIMEZONE
from core.discord_utils import log_simple
from core.durations import format_duration
from core.timeinput import format_time

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Who the bot is seen to be: its nickname in the server and its status line,
# so the live bot and the dev database can be told apart at a glance.
#
# Nickname: the name it has in the server is its base name. On the dev
# database it is "<base> · DEV"; on live it is the base name again.
#
# Status, in order:
#   a job's latest run failed or was skipped   ⚠️ nightly backup failed · see #bot-log
#   the dev database                           🧪 DEV database · clock +13h
#   live                                       🟢 Live · up 7h · next: nightly backup 3:00 am
# with "🛠️ Dev mode" in front while dev mode is on.
#
# The status is looked at again every few minutes and only sent to Discord
# when it reads differently. A change I make myself (dev mode, the dev clock)
# shows at once.
# ---------------------------------------------------------------------------
DEV_SUFFIX = " · DEV"
MAX_NICKNAME = 32  # Discord's limit
MAX_STATUS = 128
EVERY_SECONDS = 5 * 60
DEV_MODE = "🛠️ Dev mode"
# Jobs that are the bot tidying up after itself: never the "next job" worth showing
_NOT_SHOWN = {(tidy.JOB_TASK, tidy.JOB_KIND)}

_ticker: asyncio.Task | None = None
_shown: str | None = None


# ---------------------------------------------------------------------------
# Pure: what the nickname and the status should read
# ---------------------------------------------------------------------------
def base_name(current: str) -> str:
    """The name without the dev mark, so a start on live after one on the dev
    database finds the base name again."""
    name, mark = current.strip(), DEV_SUFFIX.strip()
    while name.endswith(mark):
        name = name[: -len(mark)].rstrip()
    return name


def nickname(current: str, dev: bool) -> str:
    """What the nickname should be, given what it is now."""
    base = base_name(current)
    if not dev:
        return base
    return base[: MAX_NICKNAME - len(DEV_SUFFIX)].rstrip() + DEV_SUFFIX


def uptime(seconds: float) -> str:
    """ "12m", "7h", "3d": one unit, the largest that fits."""
    minutes = max(0, int(seconds // 60))
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 48 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // (24 * 60)}d"


def job_name(task: str, kind: str) -> str:
    """A job in words: "nightly backup", "pills checklist"."""
    kind = kind.replace("_", " ")
    return kind if task == "core" else f"{task} {kind}"


def next_job(pending, now: datetime) -> str:
    """The next job worth naming and when: "nightly backup 3:00 am" (with the
    day if it is more than a day off). "" if nothing is booked."""
    for job in pending:  # soonest first
        if (job.task, job.kind) in _NOT_SHOWN:
            continue
        local = job.due_at.astimezone(TIMEZONE)
        day = f"{local:%a} " if job.due_at - now > timedelta(hours=24) else ""
        return f"{job_name(job.task, job.kind)} {day}{format_time(local.time())}"
    return ""


def status_line(
    dev: bool, up_seconds: float, next_up: str, ahead: timedelta, trouble=(), dev_mode: bool = False
) -> str:
    """The status line. `trouble` is (task, kind, "failed" or "skipped") for each
    kind of job whose latest run didn't work, the most recent first."""
    if trouble:
        task, kind, ended = trouble[0]
        more = f" (+{len(trouble) - 1} more)" if len(trouble) > 1 else ""
        line = f"⚠️ {job_name(task, kind)} {ended}{more} · see #bot-log"
    elif dev:
        moved = f" · clock +{format_duration(ahead.total_seconds())}" if ahead.total_seconds() >= 1 else ""
        line = f"🧪 DEV database{moved}"
    else:
        line = f"🟢 Live · up {uptime(up_seconds)}" + (f" · next: {next_up}" if next_up else "")
    return (f"{DEV_MODE} · {line}" if dev_mode else line)[:MAX_STATUS]


# ---------------------------------------------------------------------------
# Discord's side
# ---------------------------------------------------------------------------
def _member():
    """The bot as a member of our server (the one #inbox is in)."""
    client = discord_utils.client
    channel = client.get_channel(INBOX_CHANNEL_ID) if client is not None else None
    guild = getattr(channel, "guild", None)
    return getattr(guild, "me", None)


async def set_nickname() -> str:
    """Make the nickname say which bot this is. Returns what was done, for the log.
    Without Change Nickname it is left as it is and #bot-log says so, once a start."""
    member = _member()
    if member is None:
        return "the server was not found"
    current = member.nick or member.name
    wanted = nickname(current, DEV_DATABASE)
    if wanted == current:
        return f"already {current}"
    if not member.guild_permissions.change_nickname:
        log.warning("Could not change the nickname to %s: Change Nickname is missing", wanted)
        await log_simple(
            "🏷️ Nickname not changed",
            f"I'd be **{wanted}** here, but my role lacks **Change Nickname**, so I am still **{current}**.",
        )
        return "Change Nickname is missing"
    try:
        await member.edit(nick=wanted, reason="Says which database this bot is on")
    except discord.HTTPException as error:
        log.warning("Could not change the nickname to %s: %s", wanted, error)
        await log_simple("🏷️ Nickname not changed", f"Discord refused **{wanted}**: {error}")
        return "refused by Discord"
    log.info("Nickname: %s -> %s", current, wanted)
    return f"{current} -> {wanted}"


async def current_line() -> str:
    """The status as things stand now."""
    up = (clock.real_now() - about.STARTED).total_seconds()
    pending = await scheduler.all_pending()
    return status_line(
        DEV_DATABASE, up, next_job(pending, clock.now()), clock.offset(), await scheduler.troubled(), devmode.enabled
    )


async def refresh() -> bool:
    """Bring the status up to date. Only sent to Discord when it reads
    differently from what is shown. Never raises. True if it was sent."""
    global _shown
    client = discord_utils.client
    if client is None:
        return False
    try:
        line = await current_line()
        if line == _shown:
            return False
        await client.change_presence(activity=discord.CustomActivity(name=line))
        _shown = line
        return True
    except Exception as error:
        log.warning("Could not change the bot's status: %s", error)
        return False


async def _loop() -> None:
    while True:
        await refresh()
        await asyncio.sleep(EVERY_SECONDS)


async def start() -> None:
    """Once the bot is connected: the nickname, then the status and its ticker.
    Safe to call again (on_ready fires after reconnects)."""
    global _ticker
    if _ticker is not None and not _ticker.done():
        return
    await set_nickname()
    _ticker = asyncio.create_task(_loop(), name="identity status")
