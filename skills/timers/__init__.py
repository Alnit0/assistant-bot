from datetime import timedelta

import discord

from core import devmode
from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from core.scheduler import utc_now
from skills.base import ANY, Keyword, Param, ReplyAction, Skill, Tool
from skills.timers import sessions, status, store, timers
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


async def undo_pause(ctx: Context, target: discord.Message) -> str:
    """Take back a pause (the Undo button on Claude's confirmation): set it going again."""
    module, record = await _target(target)
    return await module.resume(record)


async def undo_resume(ctx: Context, target: discord.Message) -> str:
    module, record = await _target(target)
    return await module.pause(record)


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


# ---------------------------------------------------------------------------
# Tools for Claude: the live state, and acting on a timer or session by the id
# that state gives. Claude never looks for a timer in the chat.
# ---------------------------------------------------------------------------
ENDED_WITHIN = timedelta(hours=24)  # how long an ended timer is still mentioned
TIMER_ACTIONS = ("pause", "resume", "cancel", "extend")
POMODORO_ACTIONS = ("pause", "resume", "start", "skip", "stop", "extend")


async def list_timers_tool(ctx: Context, value: dict) -> str:
    now = utc_now()
    active = await store.active_timers(user_id=ctx.user.id)
    ended = await store.ended_timers(ctx.user.id, now - ENDED_WITHIN)
    running = await store.active_sessions(user_id=ctx.user.id)
    return status.timers_text(
        active,
        ended,
        running[0] if running else None,
        now,
        here=ctx.channel_id,
        replied_to=ctx.reply_target_id,
        nominal=devmode.nominal_seconds,
    )


async def pomodoro_status_tool(ctx: Context, value: dict) -> str:
    running = await store.active_sessions(user_id=ctx.user.id)
    return status.session_text(
        running[0] if running else None, utc_now(), here=ctx.channel_id, nominal=devmode.nominal_seconds
    )


def _extra_time(value: dict) -> int:
    try:
        return parse_duration(value.get("duration", ""))
    except DurationError as error:
        raise UserError(f"{error} `duration` says how much time to add, e.g. 10m.")


async def timer_control_tool(ctx: Context, value: dict) -> str:
    timer_id = status.parse_ref(value["id"], status.TIMER)
    timer = await store.get_timer(timer_id) if timer_id is not None else None
    if timer is None or timer.user_id != ctx.user.id:
        raise UserError(f"There is no timer `{value['id']}`. Call list_timers and use an id from it, such as t12.")
    action = value["action"]
    if action == "extend":
        return await timers.extend(timer, _extra_time(value))
    return await {"pause": timers.pause, "resume": timers.resume, "cancel": timers.cancel}[action](timer)


async def pomodoro_control_tool(ctx: Context, value: dict) -> str:
    session_id = status.parse_ref(value["id"], status.SESSION)
    session = await store.get_session(session_id) if session_id is not None else None
    if session is None or session.user_id != ctx.user.id:
        raise UserError(
            f"There is no Pomodoro session `{value['id']}`. Call get_pomodoro_status and use the id from it, such as p4."
        )
    action = value["action"]
    if action == "extend":
        return await sessions.extend(session, _extra_time(value))
    return await sessions.ACTIONS[action](session)


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
                params=[
                    Param("duration", "How long, e.g. 25m, 90s, 1h30. Leave empty to list the timers instead.", required=False),
                    Param("label", "A short name for the timer, e.g. laundry.", required=False),
                ],
                tool_priority=10,
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
                params=[
                    Param(
                        "lengths",
                        "Focus and break lengths in minutes as focus/break or focus/break/long break, "
                        "e.g. 50/10 or 50/10/30. Empty means 25/5.",
                        required=False,
                    ),
                    Param(
                        "mode",
                        "auto starts each phase by itself; manual waits for Start. Empty uses the default.",
                        choices=("auto", "manual"),
                        required=False,
                    ),
                    Param("label", "What the session is for, e.g. writing.", required=False),
                ],
                tool_priority=9,
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
                tool=False,  # Claude acts by id (timer_control), never by finding the message
            ),
            ReplyAction(
                "pause",
                "pause that timer or session",
                pause_reply,
                examples=["pause"],
                permission=PERMISSION,
                applies_to=_is_ours,
                undo=undo_pause,
                tool=False,
            ),
            ReplyAction(
                ["resume", "unpause"],
                "carry on with a paused timer or session",
                resume_reply,
                examples=["resume"],
                permission=PERMISSION,
                applies_to=_is_ours,
                undo=undo_resume,
                tool=False,
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
                params=[Param("duration", "How much time to add, e.g. 10m.")],
                tool=False,
            ),
        ]

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "list_timers",
                "Read the user's timers as they are right now: each one's id, label, whether it is "
                "running or paused, the time left and its channel, plus timers that ended in the "
                'last day. Call it whenever the user asks about their timers ("show my timers", '
                '"how long is left on the tea timer?") and before every timer_control call, to '
                "get the id. It posts nothing: put the answer in your reply.",
                list_timers_tool,
                permission=PERMISSION,
                reads_only=True,
            ),
            Tool(
                "get_pomodoro_status",
                "Read the Pomodoro session as it is right now: its id, phase, round, time left, "
                "whether it is paused or waiting for the user to press Start, and its lengths. Call "
                'it whenever the user asks about their Pomodoro ("how long left in this round?") '
                "and before every pomodoro_control call, to get the id. It posts nothing: put the "
                "answer in your reply.",
                pomodoro_status_tool,
                permission=PERMISSION,
                reads_only=True,
            ),
            Tool(
                "timer_control",
                "Pause, resume, cancel or add time to one timer, by its id from list_timers. "
                'Examples: "pause the tea timer" -> id t12, action pause. "unpause it" or '
                '"carry on" -> action resume. "stop the laundry timer" -> action cancel. '
                '"give the tea timer 5 more minutes" -> action extend, duration 5m. If the '
                "label fits more than one timer, ask which. The timer's own message is updated; "
                "say in a line what was done.",
                timer_control_tool,
                params=[
                    Param("id", "The timer's id exactly as list_timers gave it, e.g. t12."),
                    Param("action", "What to do to it.", choices=TIMER_ACTIONS),
                    Param("duration", "For extend only: how much time to add, e.g. 10m.", required=False),
                ],
                permission=PERMISSION,
                tool_priority=8,
            ),
            Tool(
                "pomodoro_control",
                "Change the Pomodoro session that is going, by its id from get_pomodoro_status. "
                'Examples: "pause my pomodoro" -> id p4, action pause. "carry on" -> action '
                'resume. "start the break" when it is waiting for Start -> action start. "skip '
                'this break" -> action skip. "end the session" -> action stop. "10 more minutes '
                'on this round" -> action extend, duration 10m. The session card is updated; say '
                "in a line what was done.",
                pomodoro_control_tool,
                params=[
                    Param("id", "The session's id exactly as get_pomodoro_status gave it, e.g. p4."),
                    Param("action", "What to do to it.", choices=POMODORO_ACTIONS),
                    Param("duration", "For extend only: how much time to add, e.g. 10m.", required=False),
                ],
                permission=PERMISSION,
                tool_priority=7,
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
