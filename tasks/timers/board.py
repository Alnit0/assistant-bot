import logging
from datetime import datetime

import discord

from core import discord_utils, live
from core.discord_utils import log_error
from tasks.timers import store
from tasks.timers.durations import format_duration
from tasks.timers.pomodoro import PHASE_NAMES, phase_length

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


# ---------------------------------------------------------------------------
# The "Your timers" list (`timers`): every timer of the user's, whatever the
# channel. One live message per channel it was asked for in, rewritten on every
# change like the board, so its countdowns never go on running for a timer
# that has since been paused. When nothing is left it says so and is forgotten.
# ---------------------------------------------------------------------------
LIST_TITLE = "📋 **Your timers**"
LIST_EMPTY = "📋 No active timers."
LIST_FOOTER = "-# Live: this updates whenever a timer changes"


def render_list(timers: list[store.Timer], sessions: list[store.Session]) -> str:
    if not timers and not sessions:
        return LIST_EMPTY
    lines = [f"{session_line(session)} · <#{session.channel_id}>" for session in sessions]
    lines += [f"{timer_line(timer)} · <#{timer.channel_id}>" for timer in timers]
    return "\n".join([LIST_TITLE, *lines, LIST_FOOTER])


async def refresh_lists(user_id: int) -> None:
    """Rewrite every live "Your timers" list of this user with how things stand now."""
    client = discord_utils.client
    shown = await store.lists(user_id)
    if client is None or not shown:
        return
    timers = await store.active_timers(user_id=user_id)
    sessions = await store.active_sessions(user_id=user_id)
    text = render_list(timers, sessions)
    for channel_id, message_id in shown:
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        try:
            await channel.get_partial_message(message_id).edit(content=text)
        except discord.NotFound:
            await store.forget_list(channel_id)  # deleted or archived by hand
            continue
        except discord.HTTPException as error:
            log.warning("Could not update a timers list: %s", error)
            continue
        if not timers and not sessions:
            # Nothing left to follow: it stays as a one-line record
            await store.forget_list(channel_id)


async def refresh(channel_id: int, user_id: int | None = None) -> None:
    """Bring a channel's board up to date, and the user's "Your timers" lists with it.

    Returns at once: the edits follow in the background, one per message
    however many changes asked for it (core/live.py). Both are written from
    what the database says when they run."""

    async def board() -> None:
        await _refresh_board(channel_id, user_id)

    live.schedule(("timers board", channel_id), board)
    if user_id is not None:

        async def lists() -> None:
            await refresh_lists(user_id)

        live.schedule(("timers lists", user_id), lists)


async def _refresh_board(channel_id: int, user_id: int | None = None) -> None:
    """Rewrite a channel's board. Creates and pins it the first time it is needed."""
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


