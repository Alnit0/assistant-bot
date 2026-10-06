import logging
import re
from datetime import datetime, timedelta, timezone

import discord

from core import scheduler
from core.config import POMO_AUTO_CONTINUE, TIMEZONE, now_nz
from core.context import Context
from core.discord_utils import report_interaction_error
from core.errors import UserError
from core.scheduler import utc_now
from skills.timers import board, store
from skills.timers.board import stamp
from skills.timers.common import (
    PING,
    SKILL,
    channel_for,
    delete_message,
    edit_message,
    log_press,
    mention,
    owner_pressed,
)
from skills.timers.durations import DurationError, format_duration
from skills.timers.pomodoro import (
    FOCUS,
    PHASE_NAMES,
    FocusTotals,
    counts_as_focus,
    next_phase,
    parse_session,
    phase_length,
    remaining_seconds,
    resumed_end,
    summarise_focus,
    week_start,
)

log = logging.getLogger("assistant")

JOB_KIND = "pomo_phase_due"
USAGE = "Usage: `pomo [focus/break[/long break]] [auto|manual] [label]`, e.g. `pomo 50/10 writing`."


# ---------------------------------------------------------------------------
# The session card: one message per session, edited in place
# ---------------------------------------------------------------------------
def _where(session: store.Session) -> str:
    return f"{PHASE_NAMES[session.phase]} · round {session.round} of {session.rounds}"


def render_card(session: store.Session) -> str:
    title = f"**{session.label}**"
    if session.state == store.RUNNING:
        return (
            f"🍅 {title} · {_where(session)}\n"
            f"Ends {stamp(session.ends_at)} ({stamp(session.ends_at, 't')})"
        )
    if session.state == store.PAUSED:
        return f"⏸️ {title} · {_where(session)}\nPaused with {format_duration(session.remaining_s)} left"
    if session.state == store.WAITING:
        length = format_duration(phase_length(session.plan, session.phase))
        return f"🍅 {title} · {_where(session)}\n{PHASE_NAMES[session.phase]} ({length}) is next. Press **Start** when you're ready."
    done = f"{session.focus_rounds} focus round{'' if session.focus_rounds == 1 else 's'}"
    return f"⏹️ {title} · stopped after {done} ({format_duration(session.focus_seconds)} of focus)"


BUTTONS = {
    "ok": ("OK", "👍", discord.ButtonStyle.secondary),
    "pause": ("Pause", "⏸️", discord.ButtonStyle.secondary),
    "resume": ("Resume", "▶️", discord.ButtonStyle.success),
    "start": ("Start", "▶️", discord.ButtonStyle.success),
    "skip": ("Skip", "⏭️", discord.ButtonStyle.secondary),
    "stop": ("Stop", "⏹️", discord.ButtonStyle.danger),
}


def _view(session_id: int, actions: list[str]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in actions:
        view.add_item(SessionButton(session_id, action))
    return view


def card_view(session: store.Session) -> discord.ui.View | None:
    """The card's buttons for the state it is in. Always the complete set."""
    first = {store.RUNNING: "pause", store.PAUSED: "resume", store.WAITING: "start"}.get(session.state)
    if first is None:
        return None  # stopped: no buttons
    return _view(session.id, [first, "skip", "stop"])


async def _update_card(session: store.Session) -> None:
    await edit_message(
        session.channel_id, session.message_id, content=render_card(session), view=card_view(session)
    )


async def _changed(session: store.Session) -> None:
    """Save a session and bring its card and the channel's board up to date."""
    await store.save_session(session)
    await _update_card(session)
    await board.refresh(session.channel_id, session.user_id)


# ---------------------------------------------------------------------------
# Moving through the phases
# ---------------------------------------------------------------------------
async def _clear_notice(session: store.Session) -> None:
    await delete_message(session.channel_id, session.notice_message_id)
    session.notice_message_id = None


async def _notify(session: store.Session, text: str, actions: list[str]) -> None:
    """@mention the user about a phase change, replacing the previous notice."""
    await _clear_notice(session)
    channel = channel_for(session.channel_id)
    if channel is None:
        return
    try:
        notice = await channel.send(
            f"🍅 {mention(session.discord_user_id)} {text}",
            view=_view(session.id, actions),
            allowed_mentions=PING,
        )
        session.notice_message_id = notice.id
    except discord.HTTPException as error:
        log.warning("Could not post the phase notice for session %s: %s", session.id, error)


async def _begin_phase(session: store.Session, seconds: float | None = None) -> None:
    """Start the clock on the session's current phase, with a job for when it ends."""
    await scheduler.cancel_job(session.job_id)
    if seconds is None:
        seconds = phase_length(session.plan, session.phase)
    session.state = store.RUNNING
    session.ends_at = utc_now() + timedelta(seconds=seconds)
    session.remaining_s = None
    session.job_id = await scheduler.add_job(
        SKILL, JOB_KIND, session.ends_at, {"session_id": session.id}, session.user_id
    )


def _advance(session: store.Session) -> str:
    """Move the session on to its next phase. Returns the name of the one just left."""
    left = PHASE_NAMES[session.phase]
    session.phase, session.round = next_phase(session.plan, session.phase, session.round)
    return left


async def on_due(job: scheduler.Job) -> None:
    """A phase ran to its end (called by the scheduler)."""
    session = await store.get_session(job.payload["session_id"])
    # Paused, skipped or stopped since this job was booked: nothing to do
    if session is None or session.state != store.RUNNING or session.job_id != job.id:
        return

    if counts_as_focus(session.phase, completed=True):
        session.focus_rounds += 1
        session.focus_seconds += session.focus_s
        await store.log_focus(session, session.focus_s)
    finished_round = session.round
    left = _advance(session)
    session.job_id = None
    upcoming = PHASE_NAMES[session.phase]
    length = format_duration(phase_length(session.plan, session.phase))
    headline = f"**{left} done** (round {finished_round} of {session.rounds})."

    # After downtime nothing starts by itself: the user may not be there
    if session.auto_continue and not job.is_late:
        await _begin_phase(session)
        await _notify(
            session, f"{headline} {upcoming} ({length}) has started, ends {stamp(session.ends_at)}.", ["ok", "skip"]
        )
    else:
        session.state, session.ends_at = store.WAITING, None
        late = f"\n-# It ended {stamp(job.due_at)}, while I was offline." if job.is_late else ""
        await _notify(session, f"{headline} {upcoming} ({length}) is next.{late}", ["start", "skip"])
    await _changed(session)


# ---------------------------------------------------------------------------
# pomo [...]
# ---------------------------------------------------------------------------
async def start(ctx: Context) -> str:
    try:
        plan, label, auto = parse_session(ctx.args)
    except DurationError as error:
        raise UserError(f"{error} {USAGE}")
    running = await store.active_sessions(user_id=ctx.user.id)
    if running:
        raise UserError(
            f"**{running[0].label}** is still going. Press Stop on its card (or reply `stop` to it) first."
        )

    session = await store.add_session(
        store.Session(
            user_id=ctx.user.id,
            discord_user_id=ctx.author.id,
            channel_id=ctx.channel_id,
            label=label[:80],
            focus_s=plan.focus_s,
            short_s=plan.short_s,
            long_s=plan.long_s,
            rounds=plan.rounds,
            auto_continue=POMO_AUTO_CONTINUE if auto is None else auto,
            phase=FOCUS,
        )
    )
    await _begin_phase(session)
    message = await ctx.reply(render_card(session), view=card_view(session))
    session.message_id = message.id
    await store.save_session(session)
    await board.refresh(session.channel_id, session.user_id)
    lengths = "/".join(format_duration(s) for s in (plan.focus_s, plan.short_s, plan.long_s))
    return f"started pomodoro {session.id}: {session.label}, {lengths}, {'auto' if session.auto_continue else 'manual'}"


# ---------------------------------------------------------------------------
# Changing a session (buttons and reply actions)
# ---------------------------------------------------------------------------
async def press_start(session: store.Session) -> str:
    if session.state != store.WAITING:
        raise UserError("That phase has already started.")
    await _clear_notice(session)
    await _begin_phase(session)
    await _changed(session)
    return f"▶️ {PHASE_NAMES[session.phase]} started"


async def skip(session: store.Session) -> str:
    """Skip the phase that is running (it isn't logged), or the one waiting to start."""
    if not session.active:
        raise UserError("That session has ended.")
    left = _advance(session)
    await _clear_notice(session)
    await _begin_phase(session)
    await _changed(session)
    return f"⏭️ Skipped {left.lower()}; {PHASE_NAMES[session.phase].lower()} started"


async def pause(session: store.Session) -> str:
    if session.state != store.RUNNING:
        raise UserError("The session isn't running, so it can't be paused.")
    await scheduler.cancel_job(session.job_id)
    session.remaining_s = remaining_seconds(session.ends_at, utc_now())
    session.state, session.ends_at, session.job_id = store.PAUSED, None, None
    await _changed(session)
    return f"⏸️ Paused: {session.label} ({format_duration(session.remaining_s)} left)"


async def resume(session: store.Session) -> str:
    if session.state == store.WAITING:
        return await press_start(session)
    if session.state != store.PAUSED:
        raise UserError("The session isn't paused.")
    await _begin_phase(session, session.remaining_s)
    await _changed(session)
    return f"▶️ Resumed: {session.label}"


async def extend(session: store.Session, seconds: int) -> str:
    if session.state == store.PAUSED:
        session.remaining_s += seconds
    elif session.state == store.RUNNING:
        session.ends_at = resumed_end(session.ends_at, seconds)
        if not await scheduler.reschedule_job(session.job_id, session.ends_at):
            session.job_id = await scheduler.add_job(
                SKILL, JOB_KIND, session.ends_at, {"session_id": session.id}, session.user_id
            )
    else:
        raise UserError("Press Start first: there is no phase running to add time to.")
    await _changed(session)
    return f"➕ Added {format_duration(seconds)} to this {PHASE_NAMES[session.phase].lower()}"


async def stop(session: store.Session) -> str:
    if not session.active:
        raise UserError("That session has already ended.")
    await scheduler.cancel_job(session.job_id)
    await _clear_notice(session)
    session.state, session.ends_at, session.remaining_s, session.job_id = store.STOPPED, None, None, None
    await _changed(session)
    return f"⏹️ Stopped: {session.label}"


async def acknowledge(session: store.Session) -> str:
    """The phase-change alert has been seen: clear it away. The card carries on as it is."""
    if session.notice_message_id is None:
        raise UserError("There is no alert to acknowledge.")
    await _clear_notice(session)
    await _changed(session)
    return "👍 Noted"


ACTIONS = {
    "ok": acknowledge,
    "pause": pause,
    "resume": resume,
    "start": press_start,
    "skip": skip,
    "stop": stop,
}


class SessionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"timers:p:(?P<id>\d+):(?P<action>ok|pause|resume|start|skip|stop)",
):
    """A button on a session card or phase notice. Its id carries the session's id,
    so it works after a restart."""

    def __init__(self, session_id: int, action: str):
        label, emoji, style = BUTTONS[action]
        super().__init__(
            discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"timers:p:{session_id}:{action}")
        )
        self.session_id = session_id
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(int(match["id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            session = await store.get_session(self.session_id)
            if session is None or not await owner_pressed(interaction, session.user_id):
                return
            # Answer straight away; the action edits the card and notices itself
            await interaction.response.defer()
            try:
                outcome = await ACTIONS[self.action](session)
            except UserError as error:
                # A stale button (the state moved on): just put the card right
                outcome = f"not done: {error}"
                await _update_card(session)
                if interaction.message.id != session.message_id:
                    await delete_message(session.channel_id, interaction.message.id)
            await log_press(interaction, f"pomodoro button: {self.action}", outcome)
        except Exception as error:
            await report_interaction_error(interaction, error, f"Pomodoro button failed: {self.action}")


# ---------------------------------------------------------------------------
# pomo stats
# ---------------------------------------------------------------------------
def _totals_lines(title: str, totals: FocusTotals) -> list[str]:
    if totals.sessions == 0:
        return [f"**{title}:** nothing yet"]
    rounds = f"{totals.sessions} round{'' if totals.sessions == 1 else 's'}"
    lines = [f"**{title}:** {format_duration(totals.seconds)} of focus in {rounds}"]
    lines += [f"• {label}: {format_duration(seconds)}" for label, seconds in totals.by_label[:5]]
    return lines


def render_stats(today: FocusTotals, week: FocusTotals) -> str:
    return "\n".join(["🍅 **Focus stats**", *_totals_lines("Today", today), *_totals_lines("This week", week)])


async def stats(ctx: Context) -> str:
    today = now_nz().date()
    # Midnight on Monday in NZ, as a moment
    since = datetime.combine(week_start(today), datetime.min.time(), tzinfo=TIMEZONE).astimezone(timezone.utc)
    log_rows = await store.focus_log(ctx.user.id, since)
    today_totals, week_totals = summarise_focus(log_rows, today, TIMEZONE)
    await ctx.reply(render_stats(today_totals, week_totals))
    return f"focus today {format_duration(today_totals.seconds)}, this week {format_duration(week_totals.seconds)}"
