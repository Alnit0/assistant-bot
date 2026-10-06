import logging
import re
from datetime import timedelta

import discord

from core import scheduler
from core.context import Context
from core.discord_utils import report_interaction_error
from core.errors import UserError
from core.scheduler import utc_now
from skills.timers import board, store
from skills.timers.board import stamp
from skills.timers.common import (
    PING,
    SKILL,
    delete_message,
    edit_message,
    channel_for,
    log_press,
    mention,
    owner_pressed,
)
from skills.timers.durations import DurationError, format_duration, split_duration
from skills.timers.pomodoro import remaining_seconds, resumed_end

log = logging.getLogger("assistant")

JOB_KIND = "timer_due"
DEFAULT_LABEL = "Timer"
MAX_ACTIVE = 20
SNOOZE_SECONDS = 5 * 60  # the "+5 min" button
USAGE = "Usage: `timer <duration> [label]`, e.g. `timer 25m` or `timer 1h30 laundry`."


# ---------------------------------------------------------------------------
# What a timer's own message says
# ---------------------------------------------------------------------------
def render_timer(timer: store.Timer) -> str:
    length = format_duration(timer.duration_s)
    if timer.status == store.RUNNING:
        return (
            f"⏱️ **{timer.label}** · {length} · ends {stamp(timer.ends_at)} ({stamp(timer.ends_at, 't')})\n"
            "-# Reply to this with `cancel`, `pause` or `+10m`"
        )
    if timer.status == store.PAUSED:
        return (
            f"⏸️ **{timer.label}** · paused with {format_duration(timer.remaining_s)} left\n"
            "-# Reply to this with `resume`, `cancel` or `+10m`"
        )
    if timer.status == store.CANCELLED:
        return f"🚫 **{timer.label}** · {length} · cancelled"
    return f"✅ **{timer.label}** · {length} · finished"


async def _changed(timer: store.Timer) -> None:
    """Save a timer and bring its message and the channel's board up to date."""
    await store.save_timer(timer)
    await edit_message(timer.channel_id, timer.message_id, content=render_timer(timer))
    await board.refresh(timer.channel_id, timer.user_id)


async def _run(timer: store.Timer, seconds: float) -> None:
    """Set a timer running for `seconds` from now, with a job for when it ends."""
    await scheduler.cancel_job(timer.job_id)
    timer.status = store.RUNNING
    timer.ends_at = utc_now() + timedelta(seconds=seconds)
    timer.remaining_s = None
    timer.job_id = await scheduler.add_job(SKILL, JOB_KIND, timer.ends_at, {"timer_id": timer.id}, timer.user_id)


# ---------------------------------------------------------------------------
# timer <duration> [label]
# ---------------------------------------------------------------------------
async def start(ctx: Context) -> str:
    try:
        seconds, label = split_duration(ctx.args)
    except DurationError as error:
        raise UserError(f"{error} {USAGE}")
    if len(await store.active_timers(user_id=ctx.user.id)) >= MAX_ACTIVE:
        raise UserError(f"You already have {MAX_ACTIVE} timers running. Cancel one first.")

    timer = await store.add_timer(
        store.Timer(
            user_id=ctx.user.id,
            discord_user_id=ctx.author.id,
            channel_id=ctx.channel_id,
            label=(label or DEFAULT_LABEL)[:80],
            duration_s=seconds,
        )
    )
    await _run(timer, seconds)
    message = await ctx.reply(render_timer(timer))
    timer.message_id = message.id
    await store.save_timer(timer)
    await board.refresh(timer.channel_id, timer.user_id)
    return f"started timer {timer.id}: {timer.label}, {format_duration(seconds)}"


# ---------------------------------------------------------------------------
# When a timer runs out (called by the scheduler)
# ---------------------------------------------------------------------------
async def on_due(job: scheduler.Job) -> None:
    timer = await store.get_timer(job.payload["timer_id"])
    # Cancelled, paused or extended since this job was booked: nothing to do
    if timer is None or timer.status != store.RUNNING or timer.job_id != job.id:
        return

    timer.status = store.FINISHED
    timer.job_id = None
    text = f"⏰ {mention(timer.discord_user_id)} **{timer.label}** is done ({format_duration(timer.duration_s)})."
    if job.is_late:
        text += f"\n-# It finished {stamp(job.due_at)}, while I was offline."

    channel = channel_for(timer.channel_id)
    if channel is not None:
        try:
            notice = await channel.send(text, view=finished_view(timer.id), allowed_mentions=PING)
            timer.notice_message_id = notice.id
        except discord.HTTPException as error:
            log.warning("Could not announce that timer %s finished: %s", timer.id, error)
    await _changed(timer)


# ---------------------------------------------------------------------------
# Changing a timer (reply actions and buttons)
# ---------------------------------------------------------------------------
async def cancel(timer: store.Timer) -> str:
    if timer.status == store.FINISHED:
        return await dismiss(timer)
    if not timer.active:
        raise UserError(f"**{timer.label}** has already ended.")
    await scheduler.cancel_job(timer.job_id)
    timer.status, timer.job_id = store.CANCELLED, None
    await _changed(timer)
    return f"🚫 Cancelled: {timer.label}"


async def pause(timer: store.Timer) -> str:
    if timer.status != store.RUNNING:
        raise UserError(f"**{timer.label}** isn't running, so it can't be paused.")
    await scheduler.cancel_job(timer.job_id)
    timer.remaining_s = remaining_seconds(timer.ends_at, utc_now())
    timer.status, timer.ends_at, timer.job_id = store.PAUSED, None, None
    await _changed(timer)
    return f"⏸️ Paused: {timer.label} ({format_duration(timer.remaining_s)} left)"


async def resume(timer: store.Timer) -> str:
    if timer.status != store.PAUSED:
        raise UserError(f"**{timer.label}** isn't paused.")
    await _run(timer, timer.remaining_s)
    await _changed(timer)
    return f"▶️ Resumed: {timer.label} ({format_duration(remaining_seconds(timer.ends_at, utc_now()))} left)"


async def extend(timer: store.Timer, seconds: int) -> str:
    if timer.status == store.PAUSED:
        timer.remaining_s += seconds
    elif timer.status == store.RUNNING:
        timer.ends_at = resumed_end(timer.ends_at, seconds)
        if not await scheduler.reschedule_job(timer.job_id, timer.ends_at):
            # Its job has just run or gone: book a fresh one
            timer.job_id = await scheduler.add_job(SKILL, JOB_KIND, timer.ends_at, {"timer_id": timer.id}, timer.user_id)
    elif timer.status == store.FINISHED:
        await restart(timer, seconds)
        return f"➕ {timer.label}: {format_duration(seconds)} more"
    else:
        raise UserError(f"**{timer.label}** has already ended.")
    await _changed(timer)
    return f"➕ Added {format_duration(seconds)} to {timer.label}"


async def restart(timer: store.Timer, seconds: float) -> None:
    """Set a finished timer going again, clearing away its "done" notice."""
    await delete_message(timer.channel_id, timer.notice_message_id)
    timer.notice_message_id = None
    await _run(timer, seconds)
    await _changed(timer)


async def dismiss(timer: store.Timer) -> str:
    await delete_message(timer.channel_id, timer.notice_message_id)
    timer.status, timer.notice_message_id = store.DISMISSED, None
    await store.save_timer(timer)
    return f"👍 Dismissed: {timer.label}"


# ---------------------------------------------------------------------------
# Buttons on the "it's done" notice. Their ids carry the timer's id, so they
# work after a restart.
# ---------------------------------------------------------------------------
BUTTONS = {
    "plus5": ("+5 min", "➕", discord.ButtonStyle.primary),
    "restart": ("Restart", "🔁", discord.ButtonStyle.secondary),
    "dismiss": ("Dismiss", "👍", discord.ButtonStyle.secondary),
}


class TimerButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"timers:t:(?P<id>\d+):(?P<action>plus5|restart|dismiss)",
):
    def __init__(self, timer_id: int, action: str):
        label, emoji, style = BUTTONS[action]
        super().__init__(
            discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"timers:t:{timer_id}:{action}")
        )
        self.timer_id = timer_id
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(int(match["id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            timer = await store.get_timer(self.timer_id)
            if timer is None or not await owner_pressed(interaction, timer.user_id):
                return
            # Answer straight away; the work below edits and deletes messages itself
            await interaction.response.defer()
            if timer.status != store.FINISHED:
                await delete_message(timer.channel_id, interaction.message.id)
                return
            if self.action == "plus5":
                await restart(timer, SNOOZE_SECONDS)
                outcome = f"{timer.label}: 5 more minutes"
            elif self.action == "restart":
                await restart(timer, timer.duration_s)
                outcome = f"{timer.label}: restarted for {format_duration(timer.duration_s)}"
            else:
                outcome = await dismiss(timer)
            await log_press(interaction, f"timer button: {self.action}", outcome)
        except Exception as error:
            await report_interaction_error(interaction, error, f"Timer button failed: {self.action}")


def finished_view(timer_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in BUTTONS:
        view.add_item(TimerButton(timer_id, action))
    return view
