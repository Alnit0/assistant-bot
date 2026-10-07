import discord

from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from skills.base import ANY, Keyword, ReplyAction, Skill
from skills.timers import sessions, store, timers
from skills.timers.board import session_line, timer_line
from skills.timers.common import PERMISSION
from skills.timers.durations import DurationError, parse_duration


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
async def timer_word(ctx: Context) -> str:
    """`timer 25m laundry` starts one; `timer` on its own lists them."""
    if not ctx.args:
        return await list_timers(ctx)
    return await timers.start(ctx)


async def list_timers(ctx: Context) -> str:
    active = await store.active_timers(user_id=ctx.user.id)
    running = await store.active_sessions(user_id=ctx.user.id)
    if not active and not running:
        await ctx.reply("📋 No active timers.")
        return "no active timers"
    lines = ["📋 **Your timers**"]
    lines += [f"{session_line(session)} · <#{session.channel_id}>" for session in running]
    lines += [f"{timer_line(timer)} · <#{timer.channel_id}>" for timer in active]
    await ctx.reply("\n".join(lines))
    return f"{len(active)} timer(s), {len(running)} pomodoro"


# ---------------------------------------------------------------------------
# Reply actions: reply to a timer message, a session card or one of their notices
# ---------------------------------------------------------------------------
async def _is_ours(ctx: Context) -> bool:
    """Is the message being replied to a timer or a session? If not, the reply isn't for us."""
    target = ctx.reply_target_id
    if target is None:
        return False
    return (await store.timer_by_message(target) or await store.session_by_message(target)) is not None


async def _target(target: discord.Message):
    timer = await store.timer_by_message(target.id)
    if timer is not None:
        return timers, timer
    session = await store.session_by_message(target.id)
    if session is not None:
        return sessions, session
    raise UserError("That message isn't a timer or a Pomodoro session.")


async def cancel_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await ctx.confirm(await (timers.cancel(record) if module is timers else sessions.stop(record)))


async def pause_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await ctx.confirm(await module.pause(record))


async def resume_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await ctx.confirm(await module.resume(record))


async def extend_reply(ctx: Context, target: discord.Message) -> None:
    try:
        seconds = parse_duration(" ".join(ctx.args))
    except DurationError as error:
        raise UserError(f"{error} Try `+10m`.")
    module, record = await _target(target)
    await ctx.confirm(await module.extend(record, seconds))


async def acknowledge_reply(ctx: Context, target: discord.Message) -> None:
    """Reply "ok" to an alert (timer done, or a Pomodoro phase change) to clear it away."""
    module, record = await _target(target)
    if target.id != record.notice_message_id:
        raise UserError("Reply to the alert itself to acknowledge it.")
    await ctx.confirm(await (timers.dismiss(record) if module is timers else sessions.acknowledge(record)))


class TimersSkill(Skill):
    """Short timers and Pomodoro sessions. Typed words only: there are no slash commands."""

    name = "timers"
    description = "Short timers and Pomodoro focus sessions"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                "timer",
                "start a timer (the label is optional); on its own, lists your timers",
                timer_word,
                examples=["timer 25m", "timer 1h30 laundry", "timer 2 hours"],
                channels=ANY,
                permission=PERMISSION,
                takes_args=True,
                usage="<duration> [label]",
            ),
            Keyword(
                "timers",
                "list your active timers and the current Pomodoro",
                list_timers,
                examples=["timers"],
                channels=ANY,
                permission=PERMISSION,
            ),
            Keyword(
                ["pomo", "pomodoro"],
                "start a Pomodoro session: 25/5, with a 15-minute break after 4 rounds",
                sessions.start,
                examples=["pomo", "pomo 50/10", "pomo 50/10/30 writing", "pomo auto deep work"],
                channels=ANY,
                permission=PERMISSION,
                takes_args=True,
                usage="[focus/break[/long break]] [auto|manual] [label]",
            ),
            Keyword(
                ["pomo stats", "pomodoro stats"],
                "completed focus time today and this week",
                sessions.stats,
                examples=["pomo stats"],
                channels=ANY,
                permission=PERMISSION,
            ),
        ]

    def reply_actions(self) -> list[ReplyAction]:
        # Each only applies when the message replied to is a timer or a session, so
        # these everyday words stay free for everything else
        return [
            ReplyAction(
                ["cancel", "stop"],
                "cancel that timer, or stop that Pomodoro session",
                cancel_reply,
                examples=["cancel"],
                permission=PERMISSION,
                applies_to=_is_ours,
            ),
            ReplyAction(
                "pause",
                "pause that timer or session",
                pause_reply,
                examples=["pause"],
                permission=PERMISSION,
                applies_to=_is_ours,
            ),
            ReplyAction(
                "resume",
                "carry on with a paused timer or session",
                resume_reply,
                examples=["resume"],
                permission=PERMISSION,
                applies_to=_is_ours,
            ),
            ReplyAction(
                ["ok", "done", "dismiss", "got it"],
                "acknowledge a timer or Pomodoro alert, which clears it away",
                acknowledge_reply,
                examples=["ok"],
                permission=PERMISSION,
                applies_to=_is_ours,
            ),
            ReplyAction(
                ["extend", "add"],
                "add time to that timer, or to the current Pomodoro phase",
                extend_reply,
                examples=["+10m", "extend 5m"],
                permission=PERMISSION,
                takes_args=True,
                usage="<duration>",
                pattern=r"\+\s*(.+)",
                applies_to=_is_ours,
            ),
        ]

    def job_handlers(self) -> dict:
        return {
            timers.JOB_KIND: timers.on_due,
            sessions.JOB_KIND: sessions.on_due,
        }

    def migrations(self) -> list:
        return list(store.MIGRATIONS)

    async def message_class(self, message_id: int) -> MessageClass | None:
        if await store.is_board(message_id):
            return MessageClass.LIVE
        record = await store.timer_by_message(message_id) or await store.session_by_message(message_id)
        return store.message_class_of(record, message_id)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so buttons on messages from before a restart still work
        client.add_dynamic_items(timers.TimerButton, sessions.SessionButton)


skill = TimersSkill()
