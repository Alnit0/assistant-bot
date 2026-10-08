import discord

from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from tasks.base import ANY, Keyword, Param, ReplyAction, Task, Tool
from tasks.timers import board, control, sessions, store, timers
from tasks.timers.common import PERMISSION, delete_message
from tasks.timers.durations import DurationError, parse_duration


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
async def timer_word(ctx: Context) -> str:
    """`timer 25m laundry` starts one; `timer` on its own lists them."""
    if not ctx.args:
        return await list_timers(ctx)
    return await timers.start(ctx)


async def list_timers(ctx: Context) -> str:
    """Show the "Your timers" list. It is live: one per channel, kept up to date
    (tasks/timers/board.py), so an old one never goes on counting down wrongly."""
    active = await store.active_timers(user_id=ctx.user.id)
    running = await store.active_sessions(user_id=ctx.user.id)
    # The list already in this channel is replaced by the new one at the bottom
    previous = dict(await store.lists(ctx.user.id)).get(ctx.channel_id)
    message = await ctx.reply(board.render_list(active, running))
    if previous is not None:
        await delete_message(ctx.channel_id, previous, MessageClass.LIVE)
    if not active and not running:
        await store.forget_list(ctx.channel_id)
        return "no active timers"
    await store.save_list(ctx.channel_id, message.id, ctx.user.id)
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


# For Claude: "pause all timers" means everything, the Pomodoro included
SCOPE = Param(
    "scope",
    "Leave empty to include the Pomodoro session: that is what \"all\", \"everything\" and \"all "
    "timers\" mean. Use \"except pomodoro\" only when the user says to leave the Pomodoro alone.",
    choices=("except pomodoro",),
    required=False,
)


class TimersTask(Task):
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
                ["pause all", "pause everything"],
                "pause every running timer, and the Pomodoro too unless you add `except pomodoro`",
                control.pause_all,
                examples=["pause all", "pause all timers", "pause all except pomodoro"],
                channels=ANY,
                permission=PERMISSION,
                takes_args=True,
                usage="[timers] [except pomodoro]",
                accepts=control.scope_is_ours,
                keep_command=True,
                params=[SCOPE],
                tool_priority=9,
            ),
            Keyword(
                ["resume all", "unpause all", "resume everything"],
                "set every paused timer going again, and the Pomodoro too unless you add `except pomodoro`",
                control.resume_all,
                examples=["resume all", "resume all timers", "resume all except pomodoro"],
                channels=ANY,
                permission=PERMISSION,
                takes_args=True,
                usage="[timers] [except pomodoro]",
                accepts=control.scope_is_ours,
                keep_command=True,
                params=[SCOPE],
                tool_priority=9,
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
                "Read the user's timers again: each one's id, label, whether it is running or "
                "paused, the time left and its channel, plus timers that ended in the last day. "
                "The same is already given with every message as the live state, so this is "
                "rarely needed: only to look again after something has changed in the same "
                "turn. It posts nothing: put the answer in your reply.",
                control.list_timers_tool,
                permission=PERMISSION,
                reads_only=True,
            ),
            Tool(
                "get_pomodoro_status",
                "Read the Pomodoro session again: its id, phase, round, time left, whether it is "
                "paused or waiting for the user to press Start, and its lengths. The same is "
                "already given with every message as the live state, so this is rarely needed. "
                "It posts nothing: put the answer in your reply.",
                control.pomodoro_status_tool,
                permission=PERMISSION,
                reads_only=True,
            ),
            Tool(
                "timer_history",
                "Read what has happened to the user's timers and Pomodoro, with the time of each "
                "event and what was left on the clock then: started, paused, resumed, extended, "
                "cancelled, finished. Call it for questions about the past (\"what was on dinner "
                "when I paused it?\", \"when did I resume the tea timer?\", \"what happened to my "
                "timers?\"). It posts nothing: put the answer in your reply.",
                control.timer_history_tool,
                params=[
                    Param(
                        "id",
                        "One timer (t12) or session (p4) from the live state, "
                        "or empty for the latest events of all of them.",
                        required=False,
                    )
                ],
                permission=PERMISSION,
                reads_only=True,
            ),
            Tool(
                "timer_control",
                "Pause, resume, cancel or add time to one timer, several, or all of them, in ONE "
                "call. Take the ids from the live state given with the message. Examples: "
                '"pause the tea timer" -> ids t12, action pause. "unpause it" or "carry on" -> '
                'action resume. "stop the laundry timer" -> ids t7, action cancel. "give tea 5 '
                'more minutes" -> action extend, duration 5m. "cancel tea and dinner" -> ids '
                '"t12 t14". "cancel all timers" or "stop everything" -> ids all, action cancel. '
                '"stop all timers called tea" -> ids all, label tea, action cancel: that acts on '
                "every timer whose label has that word (tea, Tea 2), whatever the case. Never "
                "make one call per timer. If the user names one timer and the label fits more "
                "than one, ask which. To pause or resume everything including the Pomodoro, use "
                "pause_all or resume_all. The result names each timer it changed, as saved: "
                "report that, not what you expected.",
                control.timer_control_tool,
                params=[
                    Param(
                        "ids",
                        'One or more ids from the live state, separated by spaces, e.g. "t12" or '
                        '"t12 t14"; or "all" for every timer.',
                    ),
                    Param("action", "What to do to them. stop is the same as cancel.", choices=control.TIMER_ACTIONS),
                    Param("duration", "For extend only: how much time to add, e.g. 10m.", required=False),
                    Param(
                        "label",
                        'With ids "all" only: act on just the timers whose label has these words, '
                        "e.g. tea. Empty for every timer.",
                        required=False,
                    ),
                ],
                permission=PERMISSION,
                tool_priority=8,
            ),
            Tool(
                "pomodoro_control",
                "Change the Pomodoro session that is going. Take its id from the live state given "
                'with the message, or use "current": there is only ever one. Examples: "pause '
                'my pomodoro" -> id current, action pause. "carry on" -> action resume. "start '
                'the break" when it is waiting for Start -> action start. "skip this break" -> '
                'action skip. "end the session" -> action stop. "10 more minutes on this round" '
                "-> action extend, duration 10m. The result ends with the state as it was saved: "
                "report that, not what you expected.",
                control.pomodoro_control_tool,
                params=[
                    Param("id", 'The session\'s id from the live state, e.g. p4, or "current".'),
                    Param("action", "What to do to it.", choices=control.POMODORO_ACTIONS),
                    Param("duration", "For extend only: how much time to add, e.g. 10m.", required=False),
                ],
                permission=PERMISSION,
                tool_priority=7,
            ),
        ]

    async def live_state(self, ctx: Context) -> str:
        return await control.live_state(ctx)

    def job_handlers(self) -> dict:
        return {
            timers.JOB_KIND: timers.on_due,
            sessions.JOB_KIND: sessions.on_due,
        }

    def migrations(self) -> list:
        return list(store.MIGRATIONS)

    async def message_class(self, message_id: int) -> MessageClass | None:
        if await store.is_board(message_id) or await store.is_list(message_id):
            return MessageClass.LIVE
        record = await store.timer_by_message(message_id) or await store.session_by_message(message_id)
        return store.message_class_of(record, message_id)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so buttons on messages from before a restart still work
        client.add_dynamic_items(timers.TimerButton, sessions.SessionButton)


task = TimersTask()
