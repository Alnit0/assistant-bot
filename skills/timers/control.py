from datetime import timedelta

from core.config import TIMEZONE
from core.context import Context
from core.errors import UserError
from core.scheduler import utc_now
from skills.timers import board, sessions, status, store, timers
from skills.timers.durations import DurationError, parse_duration

# ---------------------------------------------------------------------------
# Acting on timers and the session by id (Claude's tools), and on all of them
# at once (`pause all`, `resume all`).
#
# Whatever is reported back is read from the database after the change, never
# assumed from the call having returned: "resumed" means the saved timer is
# running.
# ---------------------------------------------------------------------------
ENDED_WITHIN = timedelta(hours=24)  # how long an ended timer is still mentioned
TIMER_ACTIONS = ("pause", "resume", "cancel", "extend")
POMODORO_ACTIONS = ("pause", "resume", "start", "skip", "stop", "extend")

# The state each action must leave behind
_TIMER_AFTER = {
    "pause": {store.PAUSED},
    "resume": {store.RUNNING},
    "cancel": {store.CANCELLED, store.DISMISSED},
    "extend": {store.RUNNING, store.PAUSED},
}
_SESSION_AFTER = {
    "pause": {store.PAUSED},
    "resume": {store.RUNNING},
    "start": {store.RUNNING},
    "skip": {store.RUNNING},
    "stop": {store.STOPPED},
    "extend": {store.RUNNING, store.PAUSED},
}


# --- reading -----------------------------------------------------------------
async def list_timers_tool(ctx: Context, value: dict) -> str:
    now = utc_now()
    active = await store.active_timers(user_id=ctx.user.id)
    ended = await store.ended_timers(ctx.user.id, now - ENDED_WITHIN)
    running = await store.active_sessions(user_id=ctx.user.id)
    text = status.timers_text(
        active, ended, running[0] if running else None, now, here=ctx.channel_id, replied_to=ctx.reply_target_id
    )
    return f"{text}\n{status.ONLY_READ}"


async def pomodoro_status_tool(ctx: Context, value: dict) -> str:
    running = await store.active_sessions(user_id=ctx.user.id)
    text = status.session_text(running[0] if running else None, utc_now(), here=ctx.channel_id)
    return f"{text}\n{status.ONLY_READ}"


async def timer_history_tool(ctx: Context, value: dict) -> str:
    wanted = value.get("id", "").strip()
    kind = record_id = None
    if wanted:
        for prefix, name in ((status.TIMER, store.TIMER), (status.SESSION, store.SESSION)):
            if wanted.lower().startswith(prefix) and status.parse_ref(wanted, prefix) is not None:
                kind, record_id = name, status.parse_ref(wanted, prefix)
        if kind is None:
            raise UserError(f"`{wanted}` is not an id. Use one from list_timers (t12) or get_pomodoro_status (p4), or leave it empty.")
    found = await store.events(ctx.user.id, kind, record_id)
    return f"{status.events_text(found, TIMEZONE)}\n{status.ONLY_READ}"


# --- one timer or session, by id ----------------------------------------------
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
        said = await timers.extend(timer, _extra_time(value))
    else:
        said = await {"pause": timers.pause, "resume": timers.resume, "cancel": timers.cancel}[action](timer)

    # What is in the database now is the result, not what the call said it did
    saved = await store.get_timer(timer.id)
    if saved is None or saved.status not in _TIMER_AFTER[action]:
        state = "gone" if saved is None else f"still {saved.status}"
        raise UserError(f"That did not take: **{timer.label}** is {state}. Nothing has changed; tell the user so.")
    return f'{said}\nNow saved as: {status.ref(status.TIMER, saved.id)}: "{saved.label}" · {status.timer_state(saved, utc_now())}'


async def pomodoro_control_tool(ctx: Context, value: dict) -> str:
    session_id = status.parse_ref(value["id"], status.SESSION)
    session = await store.get_session(session_id) if session_id is not None else None
    if session is None or session.user_id != ctx.user.id:
        raise UserError(
            f"There is no Pomodoro session `{value['id']}`. Call get_pomodoro_status and use the id from it, such as p4."
        )
    action = value["action"]
    if action == "extend":
        said = await sessions.extend(session, _extra_time(value))
    else:
        said = await sessions.ACTIONS[action](session)

    saved = await store.get_session(session.id)
    if saved is None or saved.state not in _SESSION_AFTER[action]:
        state = "gone" if saved is None else f"still {saved.state}"
        raise UserError(f"That did not take: **{session.label}** is {state}. Nothing has changed; tell the user so.")
    if saved.state == store.STOPPED:
        return said
    return f"{said}\nNow saved as: {status.session_text(saved, utc_now(), here=ctx.channel_id)}"


# --- all of them at once -------------------------------------------------------
_SCOPE_WORDS = {"timers", "timer", "my", "the", "of", "them"}
_LEAVE_OUT = {"except", "but", "not", "only", "just", "without"}
_POMODORO_WORDS = {"pomodoro", "pomo", "session"}


def scope_is_ours(args: list[str]) -> bool:
    """Whether the words after `pause all` are a scope we understand ("timers",
    "except pomodoro", "timers only"). Anything else isn't this word."""
    return all(word.lower() in _SCOPE_WORDS | _LEAVE_OUT | _POMODORO_WORDS for word in args)


def leaves_out_pomodoro(args: list[str]) -> bool:
    """`pause all` includes the Pomodoro; "except pomodoro" or "timers only" leaves it."""
    return any(word.lower() in _LEAVE_OUT for word in args)


async def _all(ctx: Context, pausing: bool) -> str:
    """Pause (or resume) every timer of the user's, and the Pomodoro unless it
    was left out. Says exactly what was done, from what was saved."""
    with_session = not leaves_out_pomodoro(ctx.args)
    wanted, after = (store.RUNNING, store.PAUSED) if pausing else (store.PAUSED, store.RUNNING)
    change = timers.pause if pausing else timers.resume
    now = utc_now()
    done, left_alone, channels = [], [], set()

    for timer in await store.active_timers(user_id=ctx.user.id):
        if timer.status != wanted:
            continue
        try:
            # One refresh of the board at the end, not one per timer
            await change(timer, refresh=False)
        except UserError as error:
            left_alone.append(f"{timer.label} ({error})")
            channels.add(timer.channel_id)
            continue
        saved = await store.get_timer(timer.id)
        channels.add(timer.channel_id)
        if saved is None or saved.status != after:
            left_alone.append(f"{timer.label} (it did not take: still {getattr(saved, 'status', 'missing')})")
        else:
            done.append(status.bulk_line(saved.label, saved.left(utc_now())))

    session_note = ""
    running = await store.active_sessions(user_id=ctx.user.id) if with_session else []
    if running:
        session = running[0]
        if session.state == wanted:
            await (sessions.pause if pausing else sessions.resume)(session)
            saved = await store.get_session(session.id)
            if saved is not None and saved.state == after:
                done.append(status.bulk_line(f"🍅 {saved.label}", saved.left(utc_now()), status.phase_text(saved)))
            else:
                left_alone.append(f"🍅 {session.label} (it did not take)")
        elif session.state == store.WAITING:
            session_note = f"🍅 {session.label} is waiting for Start, so nothing of it is counting down."
    elif not with_session:
        session_note = "The Pomodoro was left as it is."

    for channel_id in channels:
        await board.refresh(channel_id, ctx.user.id)
    text = status.bulk_text(pausing, done, left_alone, session_note)
    await ctx.reply(text)
    return text


async def pause_all(ctx: Context) -> str:
    return await _all(ctx, pausing=True)


async def resume_all(ctx: Context) -> str:
    return await _all(ctx, pausing=False)
