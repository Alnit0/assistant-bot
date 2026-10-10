from datetime import timedelta

from core.context import Context
from core.errors import UserError
from core.scheduler import utc_now
from tasks.timers import board, sessions, status, store, timers
from tasks.timers.durations import DurationError, parse_duration

# ---------------------------------------------------------------------------
# Acting on timers and the session by id (Claude's tools), and on all of them
# at once (`pause all`, `resume all`).
#
# Whatever is reported back is read from the database after the change, never
# assumed from the call having returned: "resumed" means the saved timer is
# running.
# ---------------------------------------------------------------------------
ENDED_WITHIN = timedelta(hours=24)  # how long an ended timer is still mentioned
POMODORO_ACTIONS = ("pause", "resume", "start", "skip", "stop", "extend")
_SAME_AS = {"stop": "cancel"}  # stopping a timer is cancelling it
# With "all", which timers an action is about (the others are not a failure)
_ALL_APPLIES_TO = {"pause": store.RUNNING, "resume": store.PAUSED}
_THE_SESSION = {"", "current", "all", "it", "pomodoro", "session"}

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


# --- one timer or session, by id ----------------------------------------------
def _extra_time(value: dict) -> int:
    try:
        return parse_duration(value.get("duration", ""))
    except DurationError as error:
        raise UserError(f"{error} `duration` says how much time to add, e.g. 10m.")


async def chosen_timers(user_id: int, value: dict, action: str) -> list[store.Timer]:
    """The timers a change is about: the ids given, or with "all" every one
    the action can apply to, narrowed to a label if one was given."""
    wanted, label = value.get("ids", "").strip(), value.get("label", "").strip()
    if wanted.lower() != status.ALL:
        ids, bad = status.parse_refs(wanted, status.TIMER)
        chosen = []
        for timer_id in ids:
            timer = await store.get_timer(timer_id)
            if timer is None or timer.user_id != user_id:
                bad.append(status.ref(status.TIMER, timer_id))
            else:
                chosen.append(timer)
        if bad or not chosen:
            named = ", ".join(f"`{piece}`" for piece in bad) or "that"
            raise UserError(
                f"There is no timer {named}. Use the ids in the live state (such as t12, several "
                f'separated by spaces), or "{status.ALL}".'
            )
        return chosen

    active = await store.active_timers(user_id=user_id)
    if not active:
        raise UserError("No timers are running or paused, so there is nothing to do that to.")
    fitting = status.labelled(active, label)
    if not fitting:
        going = ", ".join(f'"{timer.label}"' for timer in active)
        raise UserError(f'No timer going is called "{label}". The ones going are: {going}.')
    # "Pause all" is about the ones running, "resume all" the ones paused
    needs = _ALL_APPLIES_TO.get(action)
    chosen = [timer for timer in fitting if needs is None or timer.status == needs]
    if not chosen:
        raise UserError(f"None of them is {needs}, so nothing was changed. Tell the user so.")
    return chosen


async def change_timers(user_id: int, value: dict) -> tuple[str, list[store.Timer]]:
    """Pause, resume, cancel or add time to the timers `value` names (`ids`,
    `action`, and `duration` or `label` where they apply): (what to tell the
    user, each timer as it is now saved). Raises UserError if nothing changed."""
    action = _SAME_AS.get(value["action"], value["action"])
    extra = _extra_time(value) if action == "extend" else 0
    chosen = await chosen_timers(user_id, value, action)

    done, said_each, left_alone = [], [], []
    for timer in chosen:
        try:
            if action == "extend":
                said = await timers.extend(timer, extra)
            else:
                said = await {"pause": timers.pause, "resume": timers.resume, "cancel": timers.cancel}[action](timer)
        except UserError as error:
            if len(chosen) == 1:
                raise  # the one that was asked for: its reason is the answer
            left_alone.append(f"{timer.label} ({error})")
            continue
        # What is in the database now is the result, not what the call said it did
        saved = await store.get_timer(timer.id)
        if saved is None or saved.status not in _TIMER_AFTER[action]:
            state = "gone" if saved is None else f"still {saved.status}"
            left_alone.append(f"**{timer.label}** is {state}")
        else:
            done.append(saved)
            said_each.append(said)

    if not done:
        if len(chosen) == 1 and left_alone[0].startswith("**"):
            raise UserError(f"That did not take: {left_alone[0]}. Nothing has changed; tell the user so.")
        raise UserError(f"Nothing has changed: {'; '.join(left_alone)}. Tell the user so.")

    now = utc_now()
    if len(chosen) == 1:
        shown = said_each[0]
    else:
        lines = [saved.label if action == "cancel" else status.bulk_line(saved.label, saved.left(now)) for saved in done]
        shown = status.control_text(action, lines, left_alone)
    return shown, done


async def change_session(user_id: int, value: dict) -> tuple[str, store.Session]:
    """Change the session `value` names (`id`, `action`, `duration` for
    extend): (what to tell the user, the session as it is now saved)."""
    wanted = value.get("id", "").strip()
    if wanted.lower() in _THE_SESSION:
        # There is only ever one going: no id is needed to mean it
        running = await store.active_sessions(user_id=user_id)
        session = running[0] if running else None
        if session is None:
            raise UserError("No Pomodoro session is going, so there is nothing to do that to.")
    else:
        session_id = status.parse_ref(wanted, status.SESSION)
        session = await store.get_session(session_id) if session_id is not None else None
    if session is None or session.user_id != user_id:
        raise UserError(
            f'There is no Pomodoro session `{wanted}`. Use the id in the live state, such as p4, or "current".'
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
    return said, saved


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
    text = await change_all(ctx.user.id, pausing, with_session=not leaves_out_pomodoro(ctx.args))
    await ctx.reply(text)
    return text


async def change_all(user_id: int, pausing: bool, with_session: bool = True) -> str:
    """Pause (or resume) every timer of the user's, and the Pomodoro unless it
    was left out. Says exactly what was done, from what was saved."""
    wanted, after = (store.RUNNING, store.PAUSED) if pausing else (store.PAUSED, store.RUNNING)
    change = timers.pause if pausing else timers.resume
    now = utc_now()
    done, left_alone, channels = [], [], set()

    for timer in await store.active_timers(user_id=user_id):
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
    running = await store.active_sessions(user_id=user_id) if with_session else []
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
        await board.refresh(channel_id, user_id)
    return status.bulk_text(pausing, done, left_alone, session_note)


async def pause_all(ctx: Context) -> str:
    return await _all(ctx, pausing=True)


async def resume_all(ctx: Context) -> str:
    return await _all(ctx, pausing=False)
