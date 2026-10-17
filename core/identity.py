import asyncio
import logging
from datetime import datetime, timedelta

from core import attention, clock, config, live, scheduler, surface
from core import day as days
from core.config import DEV_DATABASE, INBOX_CHANNEL_ID, SELFTEST_BACK
from core.users import get_user_by_discord_id
from core.discord_utils import log_simple
from core.durations import format_duration

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Who the bot is seen to be: its nickname in the server and its status line.
# (The presence, the online dot, is Discord's: the bot never sets it.)
#
# Nickname: the name I gave it, BOT_NAME in its settings file, used on every
# start. A suffix only for a real state, always "Name · state". There is one:
# the dev bot is "Name · testing" while a self-test runs, and its plain name
# again after. Live keeps its plain name: its states are in the status line.
# With no BOT_NAME the nickname is left as it is. Nothing else renames a bot.
#
# Status line: the custom status text under the name. On live it is the top
# item of the attention model (core/attention.py), in its short form: the
# icon, then numbers and short 12-hour times joined by " · ", and never a
# pill's name. Nothing to look at is a blank status line.
#   something wrong that needs me            ⚠️ B14 · backup failed
#   due now or overdue                       💊 due 12pm
#   the next timed thing today               💊 2/5 · 12pm
#   something useful that isn't timed        🌅 6am
#   nothing                                  (blank)
# Other bots, other lines:
#   the dev bot during a self-test           🧪 41/103 · 6m   (· ❌2 once steps fail)
#   the dev bot otherwise                    ✅ 149/150 · NZ$3.64 of NZ$3.50 · clock +13h
#                                            (its last self-test and this month's self-test spend; 17 Oct)
#   a self-test on live's account (no dev bot)   🧪 Self-test running · back about 4:15 pm
# Dev mode on live is one of the things that need me (a level 1 item of its
# own, core/health.py): it is no longer a mark in front of the line.
#
# It is brought up to date when a state changes: whoever hands in attention
# items says so (`attention.changed`), and the moment the next timed item
# falls due is waited for, once. There is no ticker. It is only sent to
# Discord when it reads differently.
# ---------------------------------------------------------------------------
STATE_MARK = " · "
MAX_NICKNAME = 32  # Discord's limit
MAX_STATUS = 128
SELFTEST_ICON = "🧪"
FAILED_MARK = "❌"

_shown: str | None = None
_started = False
_wake: asyncio.TimerHandle | None = None  # the one wait for the next timed item to fall due
_progress = ""  # the dev bot during a self-test: its line, set by the run itself


# ---------------------------------------------------------------------------
# Pure: what the nickname and the status should read
# ---------------------------------------------------------------------------
def nickname(name: str, state: str = "") -> str:
    """What the nickname should be: the name it was given, and "Name · state"
    while it is in a state worth showing. "" with no name given: the nickname
    is then left alone."""
    name = name.strip()
    if not name:
        return ""
    if not state:
        return name[:MAX_NICKNAME].rstrip()
    suffix = STATE_MARK + state
    return name[: MAX_NICKNAME - len(suffix)].rstrip() + suffix


def uptime(seconds: float) -> str:
    """ "12m", "7h", "3d": one unit, the largest that fits."""
    minutes = max(0, int(seconds // 60))
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 48 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // (24 * 60)}d"


def job_name(task: str, kind: str) -> str:
    """A job in words: "nightly backup", "pills checklist". The words are the
    ones the job was registered with (core/scheduler.py, `label`)."""
    return scheduler.label(task, kind)


def selftest_line(done: int, total: int, minutes_left: int, failed: int = 0) -> str:
    """The dev bot's status line during a self-test: steps done of all, the
    minutes left, and how many failed once any has: "🧪 41/103 · 6m · ❌2".
    With the number of steps not known, the count alone."""
    pieces = [f"{done}/{total}" if total else str(done), f"{max(0, minutes_left)}m"]
    if failed:
        pieces.append(f"{FAILED_MARK}{failed}")
    return f"{SELFTEST_ICON} {' · '.join(pieces)}"


def dev_line(row: dict | None, spent: float, limit: float) -> str:
    """The dev bot's own line when no self-test is running: its last run's result and this month's spend
    ("✅ 149/150 · NZ$3.64 of NZ$3.50", ❌ when a step failed). Live's line never has any of it."""
    from core import money

    spend = f"{money.shown(spent)} of {money.shown(limit)}"
    if row is None:
        return f"{SELFTEST_ICON} no self-test yet · {spend}"
    try:
        steps, passed, failed = int(row.get("steps") or 0), int(row.get("passed") or 0), int(row.get("failed") or 0)
    except ValueError:
        return f"{SELFTEST_ICON} DEV database · {spend}"
    mark = FAILED_MARK if failed or row.get("note") else "✅"
    return f"{mark} {passed}/{steps} · {spend}"


def status_line(dev: bool, ahead: timedelta, top: str = "", selftest_back: str = "", progress: str = "", dev_said: str = "") -> str:
    """The status line. `top` is the attention model's top item in its short
    form (live's line; "" is blank). `progress` is a self-test's own line on
    the dev bot. `selftest_back` is when live is expected back, in a
    self-test that runs as live's own account because there is no dev bot:
    live is stopped for it, and that comes before everything else."""
    if selftest_back:
        return f"{SELFTEST_ICON} Self-test running · back about {selftest_back}"[:MAX_STATUS]
    if progress:
        return progress[:MAX_STATUS]
    if dev:
        moved = f" · clock +{format_duration(ahead.total_seconds())}" if ahead.total_seconds() >= 1 else ""
        line = f"{dev_said or SELFTEST_ICON + ' DEV database'}{moved}"
    else:
        line = top
    return line[:MAX_STATUS]


# ---------------------------------------------------------------------------
# The interface's side, through the door (core/surface.py)
# ---------------------------------------------------------------------------
async def set_nickname() -> str:
    """Make the nickname say which bot this is. Returns what was done, for the log.
    Without Change Nickname it is left as it is and #bot-log says so, once a start."""
    # The bot's name in our server: the one #inbox is in
    name = surface.name(INBOX_CHANNEL_ID)
    if name is None:
        return "the server was not found"
    current = name.current
    wanted = nickname(config.BOT_NAME, config.NAME_STATE)
    if not wanted:
        log.info("Nickname: BOT_NAME is not set, so it is left as it is")
        return "left as it is (BOT_NAME is not set)"
    if wanted == current:
        return f"already {current}"
    if not name.can_change:
        log.warning("Could not change the nickname to %s: Change Nickname is missing", wanted)
        await log_simple(
            "🏷️ Nickname not changed",
            f"I'd be **{wanted}** here, but my role lacks **Change Nickname**, so I am still **{current}**.",
        )
        return "Change Nickname is missing"
    try:
        await surface.rename(INBOX_CHANNEL_ID, wanted, "The name it was given (BOT_NAME), with its state if it has one")
    except surface.Failed as error:
        log.warning("Could not change the nickname to %s: %s", wanted, error)
        await log_simple("🏷️ Nickname not changed", f"Discord refused **{wanted}**: {error}")
        return "refused by Discord"
    log.info("Nickname: %s -> %s", current, wanted)
    return f"{current} -> {wanted}"


async def _items(now: datetime) -> list:
    """Live's attention items now (the owner's). None for a bot whose line is not made of them."""
    if DEV_DATABASE:
        return []
    owner = await get_user_by_discord_id(config.OWNER_ID)
    return await attention.gather(owner.id, now) if owner is not None else []


async def current_line(items: list | None = None, now: datetime | None = None) -> str:
    """The status line as things stand now."""
    now = now or clock.now()
    items = await _items(now) if items is None else items
    # Only Alex's own things: dev mode, the self-test and the nightly are never on it (17 Oct)
    top = attention.status_line(attention.top_mine(items, now))
    return status_line(DEV_DATABASE, clock.offset(), top, SELFTEST_BACK, _progress, _dev_said() if DEV_DATABASE else "")


def _dev_said() -> str:
    """The dev bot's line, read from the self-test's own files (data/selftest): never live's."""
    from core import health

    try:
        folder = config.DATA_DIR / health.SELFTEST_DIR
        return dev_line(health.last_run(folder), *health.selftest_spend())
    except Exception:
        log.exception("The dev bot's status line could not read the self-test's files")
        return ""


def _wait_for(when: datetime | None, now: datetime) -> None:
    """Look again at the moment the next timed item falls due, or the day ends:
    the only waiting there is, and for one moment at a time."""
    global _wake
    if _wake is not None:
        _wake.cancel()
        _wake = None
    day_end = days.end_of(days.day_of(now))
    moment = min(when, day_end) if when is not None else day_end
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _wake = loop.call_later(max(1.0, (moment - now).total_seconds() + 1.0), look_again)


async def refresh() -> bool:
    """Bring the status line up to date. Only sent to Discord when it reads
    differently from what is shown; nothing to show is a blank status line.
    Never raises. True if it was sent."""
    global _shown
    if not surface.connected():
        return False
    try:
        now = clock.now()
        items = await _items(now)
        _wait_for(attention.next_change(items, now), now)
        line = await current_line(items, now)
        if line == _shown:
            return False
        await surface.status(line)
        _shown = line
        return True
    except Exception as error:
        log.warning("Could not change the bot's status line: %s", error)
        return False


def look_again() -> None:
    """A state changed: bring the status line up to date soon, in the
    background. Called, not awaited; asked many times at once it is done once."""
    live.schedule(("status line",), refresh)


def set_progress(done: int, total: int, minutes_left: int, failed: int = 0) -> None:
    """A self-test says how far it is: the dev bot's status line while it runs."""
    global _progress
    _progress = selftest_line(done, total, minutes_left, failed)
    look_again()


async def start() -> None:
    """Once the bot is connected: the nickname, then the status line, and from
    then on whenever a state changes. Safe to call again (on_ready fires after
    reconnects)."""
    global _started
    if _started:
        return
    _started = True
    await set_nickname()
    attention.on_change(look_again)
    await refresh()
