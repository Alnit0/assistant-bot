import discord

from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from core import repeats
from core.actions import EACH_DAY, SEE
from tasks.base import ANY, ButtonNote, Keyword, ReplyAction, Task
from tasks.timers import board, control, plain, sessions, store, timers
from tasks.timers.common import PERMISSION, delete_message
from core.durations import DurationError, parse_duration


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
    return len(await store.timers_about(target)) + len(await store.sessions_about(target)) == 1


async def _target(target: discord.Message):
    """The one timer or session a message is about: its card, its alert, or a
    line that says what was done to it."""
    about = await store.timers_about(target.id)
    running = await store.sessions_about(target.id)
    if len(about) == 1 and not running:
        return timers, about[0]
    if len(running) == 1 and not about:
        return sessions, running[0]
    raise UserError("That message isn't a timer or a Pomodoro session.")


async def _said(ctx: Context, record, text: str) -> None:
    """Say what was done, and record the line as that timer's or session's:
    a reply to it means the same one."""
    message = await ctx.confirm(text)
    await store.note_message(getattr(message, "id", None), ctx.channel_id, [record])


async def cancel_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await _said(ctx, record, await (timers.cancel(record) if module is timers else sessions.stop(record)))


async def pause_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await _said(ctx, record, await module.pause(record))


async def resume_reply(ctx: Context, target: discord.Message) -> None:
    module, record = await _target(target)
    await _said(ctx, record, await module.resume(record))


async def extend_reply(ctx: Context, target: discord.Message) -> None:
    try:
        seconds = parse_duration(" ".join(ctx.args))
    except DurationError as error:
        raise UserError(f"{error} Try `+10m`.")
    module, record = await _target(target)
    await _said(ctx, record, await module.extend(record, seconds))


async def acknowledge_reply(ctx: Context, target: discord.Message) -> None:
    """Reply "ok" to an alert (timer done, or a Pomodoro phase change) to clear it away."""
    module, record = await _target(target)
    if target.id != record.notice_message_id:
        raise UserError("Reply to the alert itself to acknowledge it.")
    await ctx.confirm(await (timers.dismiss(record) if module is timers else sessions.acknowledge(record)))


class TimersTask(Task):
    """Short timers and Pomodoro sessions. Typed words only: there are no slash commands."""

    name = "timers"
    description = "Short timers and Pomodoro focus sessions"
    # In plain words (tasks/timers/plain.py): how the router knows this task
    icon = plain.ICON
    only_for = plain.ONLY_FOR
    examples = plain.EXAMPLES
    # Each timer is its own: a second one called tea runs beside the first
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER
    show = "timer_list"

    def actions(self) -> list:
        return list(plain.ACTIONS)

    async def action_state(self, request):
        return await plain.state(request)

    async def item_names(self, request):
        # The names the user gave their running timers ("tea"): a message that says one is for
        # this task. A timer with no name is known by its length, which names nothing
        found = []
        for timer in await store.active_timers(user_id=request.user.id):
            try:
                parse_duration(timer.label)
            except DurationError:
                found.append(timer.label)
        return found

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
                purpose=EACH_DAY,
            ),
            Keyword(
                "timers",
                "list your active timers and the current Pomodoro",
                list_timers,
                examples=["timers"],
                channels=ANY,
                permission=PERMISSION,
                purpose=SEE,
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
                purpose=EACH_DAY,
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
                purpose=EACH_DAY,
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
                purpose=EACH_DAY,
            ),
            Keyword(
                ["pomo stats", "pomodoro stats"],
                "completed focus time today and this week",
                sessions.stats,
                examples=["pomo stats"],
                channels=ANY,
                permission=PERMISSION,
                purpose=SEE,
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
                ["resume", "unpause"],
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

    def buttons(self) -> list[ButtonNote]:
        def named(table, action: str) -> str:
            label, emoji, _ = table[action]
            return f"{emoji} {label}"

        return [
            ButtonNote(named(timers.BUTTONS, "dismiss"), "on a finished timer's alert: clear it away"),
            ButtonNote(named(timers.BUTTONS, "plus5"), "on a finished timer's alert: run it for 5 more minutes"),
            ButtonNote(named(timers.BUTTONS, "restart"), "on a finished timer's alert: run it again for its full length"),
            ButtonNote(named(sessions.BUTTONS, "start"), "on the Pomodoro card: start the phase that is waiting"),
            ButtonNote(named(sessions.BUTTONS, "pause"), "on the Pomodoro card: pause this phase; Resume carries on"),
            ButtonNote(named(sessions.BUTTONS, "skip"), "on the Pomodoro card: go on to the next phase now"),
            ButtonNote(named(sessions.BUTTONS, "stop"), "on the Pomodoro card: end the session"),
            ButtonNote(named(sessions.BUTTONS, "ok"), "on a Pomodoro phase alert: clear it away"),
        ]

    def job_handlers(self) -> dict:
        return {
            timers.JOB_KIND: timers.on_due,
            sessions.JOB_KIND: sessions.on_due,
        }

    def job_labels(self) -> dict:
        # What each job is called wherever I read it (the status line, the start's message)
        return {timers.JOB_KIND: "timer ending", sessions.JOB_KIND: "Pomodoro phase"}

    def migrations(self) -> list:
        return list(store.MIGRATIONS)

    async def channel_cleared(self, channel_id: int, gone: set[int]) -> None:
        # Running timers and a session keep going whatever happens to their cards: each card
        # that went is posted again, quietly, and then the board
        send = plain.sender(channel_id)
        await timers.repost(channel_id, gone, send)
        await sessions.repost(channel_id, gone, send)
        await board.channel_cleared(channel_id, gone)

    async def reposted(self, channel_id: int, gone: set[int]) -> list[str]:
        return await board.reposted(channel_id, gone)

    async def owns_message(self, message_id: int) -> bool:
        # Every message about a timer or a session, going or over (its card, its alert, a
        # line that says what was done to it), the board and the list
        if await store.timers_about(message_id) or await store.sessions_about(message_id):
            return True
        return await store.is_board(message_id) or await store.is_list(message_id)

    async def message_class(self, message_id: int) -> MessageClass | None:
        if await store.is_board(message_id) or await store.is_list(message_id):
            return MessageClass.LIVE
        record = await store.timer_by_message(message_id) or await store.session_by_message(message_id)
        return store.message_class_of(record, message_id)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so buttons on messages from before a restart still work
        client.add_dynamic_items(timers.TimerButton, sessions.SessionButton)


task = TimersTask()
