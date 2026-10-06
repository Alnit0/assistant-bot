import logging
from datetime import datetime

import discord

from core import discord_utils
from core.discord_utils import log_error
from skills.timers import store
from skills.timers.durations import format_duration
from skills.timers.pomodoro import PHASE_NAMES, phase_length

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The "Active timers" board: one pinned message per channel, rewritten whenever
# anything in that channel changes.
# ---------------------------------------------------------------------------
TITLE = "📋 **Active timers**"
EXEMPT_EMOJI = "📌"  # marks the board as not to be cleared by the nightly sweep


def stamp(moment: datetime, style: str = "R") -> str:
    """A Discord timestamp that counts down by itself, with no edits from us."""
    return f"<t:{int(moment.timestamp())}:{style}>"


def timer_line(timer: store.Timer) -> str:
    if timer.status == store.PAUSED:
        return f"⏸️ {timer.label} · paused, {format_duration(timer.remaining_s)} left"
    return f"⏱️ {timer.label} · ends {stamp(timer.ends_at)}"


def session_line(session: store.Session) -> str:
    phase = PHASE_NAMES[session.phase]
    where = f"{phase} · round {session.round} of {session.rounds}"
    if session.state == store.PAUSED:
        return f"⏸️ {session.label} · {where} · paused, {format_duration(session.remaining_s)} left"
    if session.state == store.WAITING:
        length = format_duration(phase_length(session.plan, session.phase))
        return f"🍅 {session.label} · {phase} ({length}) is next · waiting for Start"
    return f"🍅 {session.label} · {where} · ends {stamp(session.ends_at)}"


def render_board(timers: list[store.Timer], sessions: list[store.Session]) -> str:
    lines = [session_line(session) for session in sessions] + [timer_line(timer) for timer in timers]
    return "\n".join([TITLE, *(lines or ["No active timers"])])


async def refresh(channel_id: int, user_id: int | None = None) -> None:
    """Bring a channel's board up to date. Creates and pins it the first time it is needed."""
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client else None
    if channel is None:
        return
    timers = await store.active_timers(channel_id=channel_id)
    sessions = await store.active_sessions(channel_id=channel_id)
    text = render_board(timers, sessions)

    board_id = await store.get_board(channel_id)
    if board_id is not None:
        try:
            await channel.get_partial_message(board_id).edit(content=text)
            return
        except discord.NotFound:
            board_id = None  # someone deleted it: make a new one if there is anything to show
        except discord.HTTPException as error:
            log.warning("Could not update the timers board: %s", error)
            return
    if not timers and not sessions:
        return

    try:
        message = await channel.send(text, silent=True)
    except discord.HTTPException as error:
        log.warning("Could not post the timers board: %s", error)
        return
    await store.save_board(channel_id, message.id, user_id)
    try:
        await message.pin(reason="Active timers board")
    except discord.HTTPException as error:
        log.warning("Could not pin the timers board: %s", error)
        await log_error(
            "Timers board not pinned",
            f"I posted the board in {getattr(channel, 'mention', channel_id)} but couldn't pin it. "
            "The bot's role needs Pin Messages (or Manage Messages) there.",
        )
    try:
        await message.add_reaction(EXEMPT_EMOJI)
    except discord.HTTPException:
        pass


