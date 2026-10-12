from datetime import datetime, timezone

from core import day
from core.actions import BOOLEAN, EACH_DAY, ITEMS, SEE, Action, Answer, Field, Proposal, Request, Shown, State, is_guessed, is_reference
from core.config import TIMEZONE
from core.errors import UserError
from core.lifecycle import MessageClass
from core.llm import ANSWER_STICKS
from core.scheduler import utc_now
from core.timeinput import format_time
from tasks.timers import board, control, sessions, status, store, timers
from tasks.timers.common import channel_for, delete_message
from core.durations import DurationError, format_duration, parse_duration
from tasks.timers.pomodoro import PHASE_NAMES, different_lengths, parse_session, phase_length, summarise_focus, week_start

# ---------------------------------------------------------------------------
# Timers and the Pomodoro session in plain words (core/actions.py).
#
# Claude fills in one of the actions below; the code here does it and writes
# every word of the answer. A single action acts at once and the reply says
# what was done (a guess is pointed out with ❓). Cancelling several timers at
# once asks first, with a card.
#
# Nothing here needs the message itself: the same code runs for a message and
# for a button, so each action posts through `sender(channel_id)`.
# ---------------------------------------------------------------------------
ICON = "⏱️"
ONLY_FOR = (
    "Countdown timers that run for a length of time (tea for 5 minutes, laundry for an hour) and the "
    "Pomodoro focus session: starting, pausing, resuming, adding time, cancelling, and questions about "
    "them. Not pills, not reminders or alarms at a time of day, and not anything on a schedule."
)
EXAMPLES = ("set a timer for 5 minutes called tea", "pause the laundry timer", "start a pomodoro")

CHANGES = ("pause", "resume", "cancel", "extend")
SESSION_CHANGES = control.POMODORO_ACTIONS
GUESS = "❓"


def sender(channel_id: int):
    """`send(text, view=…)` for a channel: how an action posts a timer's own message."""

    async def send(text: str, *, view=None):
        channel = channel_for(channel_id)
        if channel is None:
            raise UserError("I can't reach this channel just now.")
        return await (channel.send(text) if view is None else channel.send(text, view=view))

    return send


def about(request: Request, records):
    """What an answer about these timers or sessions does with its message once
    it is sent: records it as theirs (`store.note_message`)."""
    records = list(records)

    async def placed(message_id: int) -> None:
        await store.note_message(message_id, request.channel_id, records)

    return placed


def _seconds(said: str, what: str) -> int:
    try:
        return parse_duration(said)
    except DurationError as error:
        raise UserError(f"{what}: {error}")


# ---------------------------------------------------------------------------
# What extraction is told: every timer and the session, with their ids
# ---------------------------------------------------------------------------
async def state(request: Request) -> State:
    now = utc_now()
    active = await store.active_timers(user_id=request.user.id)
    ended = await store.ended_timers(request.user.id, now - control.ENDED_WITHIN)
    running = await store.active_sessions(user_id=request.user.id)
    # Any message about a timer says which one a reply to it means: its card, its
    # alert, or a line that said what was done to it
    replied = [(store.TIMER, timer.id) for timer in await store.timers_about(request.replied_to)]
    replied += [(store.SESSION, session.id) for session in await store.sessions_about(request.replied_to)]
    return State(
        "Timers and the Pomodoro session now (use these ids)",
        tuple(state_lines(active, ended, running[0] if running else None, now, request.channel_id, frozenset(replied))),
        empty="no timers and no Pomodoro session",
    )


def state_lines(active, ended, session, now: datetime, here: int | None = None, replied: frozenset = frozenset()) -> list[str]:
    """A line for each timer that is going, each that ended lately (so "the tea
    timer" that has finished can be told from one that never was), and the
    session. `replied` is what the message the user replied to is about, as
    (kind, id). Pure."""
    lines = []
    for timer in active:
        text = f'{status.ref(status.TIMER, timer.id)}: "{timer.label}" · {status.timer_state(timer, now)}'
        if timer.channel_id == here:
            text += " · in this channel"
        if (store.TIMER, timer.id) in replied:
            text += " · the user replied to this one"
        lines.append(text)
    for timer in ended:
        lines.append(
            f'{status.ref(status.TIMER, timer.id)}: "{timer.label}" · {status.timer_state(timer, now)} '
            "(over: nothing more can be done to it)"
        )
    if session is not None:
        text = f"Pomodoro session {status.session_text(session, now, here=here)}"
        if (store.SESSION, session.id) in replied:
            text += " · the user replied to this one"
        lines.append(text)
    return lines


# ---------------------------------------------------------------------------
# Starting timers
# ---------------------------------------------------------------------------
async def start(request: Request, data: dict, guessed: frozenset) -> Shown:
    """Start each timer asked for. Each posts its own message with its buttons;
    what was guessed or could not be started is said after them."""
    send = sender(request.channel_id)
    started, unsure, refused, guessed_ones = [], [], [], []
    for index, item in enumerate(data["timers"]):
        label = (item.get("label") or "").strip()
        name = label or item["duration"]
        try:
            seconds = parse_duration(item["duration"])
            timer = await timers.start_one(request.user.id, request.user.discord_id, request.channel_id, seconds, label, send)
        except DurationError as error:
            refused.append(f"{name} ({error})")
            continue
        except UserError as error:
            refused.append(f"{name} ({error})")
            continue
        started.append(f"{timer.label} {format_duration(seconds)}")
        if is_guessed(guessed, "timers", index, "duration"):
            unsure.append(f"**{timer.label}** · {format_duration(seconds)}")
            guessed_ones.append(timer)
    if not started:
        raise UserError("No timer started: " + "; ".join(refused))
    also = []
    if unsure:
        also.append(f"{GUESS} I guessed the length: {', '.join(unsure)}. Tell me if it should be something else.")
    if refused:
        also.append("⚠️ Not started: " + "; ".join(refused))
    # The line that points out a guessed length is about the timers it names
    return Shown(f"started {len(started)} timer(s): " + ", ".join(started), "\n".join(also), about(request, guessed_ones) if guessed_ones else None)


# ---------------------------------------------------------------------------
# Changing timers: one acts at once; cancelling several asks first
# ---------------------------------------------------------------------------
def which_one(active, now: datetime) -> str:
    """Asked when nothing says which timer is meant: each one going, by name.
    (Until a card can ask with buttons: G1 in docs/BACKLOG.md.)"""
    return "\n".join(["Which timer? Say its name.", *(status.left_line(timer, now) for timer in active)])


async def which_timers(request: Request, data: dict, guessed: frozenset = frozenset()) -> str:
    """The ids a change is about, worked out here and never by Claude, in this
    order. A message about one timer that the user replied to (its card, its
    alert, a line that said what was done to it) means that timer, whatever
    was said. A timer the user named is that one. Otherwise nothing named
    one ("it", or a name Claude says it guessed): the one timer the last
    message here was about, if that was in the last few minutes; or the only
    one going. With several going and none of those, no timer is picked: the
    user is asked which, and nothing is done."""
    mine = request.user.id
    if request.replied_to is not None:
        replied = [timer for timer in await store.timers_about(request.replied_to) if timer.user_id == mine]
        if len(replied) == 1:
            return status.ref(status.TIMER, replied[0].id)
    wanted = data["which"]
    if not is_reference(wanted) and not is_guessed(guessed, "which"):
        return wanted
    active = await store.active_timers(user_id=mine)
    if not active:
        if not is_reference(wanted):
            return wanted  # one that has ended: the action says so in its own words
        raise UserError("No timers are running or paused.")
    # Still going, or its alert still showing: one that has gone is nothing "it" could be now
    lately = [
        timer for timer in await store.latest_about(mine, request.channel_id, utc_now() - ANSWER_STICKS)
        if timer.active or timer.status == store.FINISHED
    ]
    if len(lately) == 1:
        return status.ref(status.TIMER, lately[0].id)
    if len(active) == 1:
        return status.ref(status.TIMER, active[0].id)
    raise UserError(which_one(active, utc_now()))


async def _control_value(request: Request, data: dict, guessed: frozenset = frozenset()) -> dict:
    return {"ids": await which_timers(request, data, guessed), "action": data["action"], "duration": data.get("duration", "")}


async def cancels_several(request: Request, data: dict, guessed: frozenset = frozenset()) -> bool:
    """Whether this is a bulk stop, which asks first: cancelling more than one timer."""
    if data["action"] != "cancel":
        return False
    try:
        return len(await control.chosen_timers(request.user.id, await _control_value(request, data, guessed), "cancel")) > 1
    except UserError:
        return False  # nothing to cancel: `change` says so in its own words


async def cancel_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    chosen = await control.chosen_timers(request.user.id, await _control_value(request, data, guessed), "cancel")
    now = utc_now()
    lines = tuple(f"**{timer.label}** · {status.timer_state(timer, now)} → cancelled" for timer in chosen)
    return Proposal(
        lines=lines,
        data={"ids": [timer.id for timer in chosen]},
        warnings=(f"This cancels {len(chosen)} timers and can't be undone",),
        kind="remove",
        destructive=True,
        confirm_label=f"Cancel {len(chosen)} timers",
    )


async def cancel_saved(request: Request, data: dict) -> Answer:
    """Confirmed: cancel each timer on the card that is still going. The card,
    once it says so, is a line about each of them."""
    done, gone, cancelled = [], 0, []
    for timer_id in data["ids"]:
        timer = await store.get_timer(timer_id)
        if timer is None or timer.user_id != request.user.id or not timer.active:
            gone += 1
            continue
        await timers.cancel(timer)
        done.append(timer.label)
        cancelled.append(timer)
    if not done:
        raise UserError("None of those timers is still going, so nothing was cancelled.")
    return Answer(status.control_text("cancel", done, [f"{gone} had already ended"] if gone else []), about(request, cancelled))


async def cancel_check(request: Request, data: dict) -> str:
    """Read each timer back: none of them is still going."""
    still = []
    for timer_id in data["ids"]:
        timer = await store.get_timer(timer_id)
        if timer is not None and timer.active:
            still.append(f"{timer.label} is still {timer.status}")
    return "; ".join(still)


async def change(request: Request, data: dict, guessed: frozenset) -> Answer:
    # A timer that was guessed is never changed: `which_timers` asks which instead
    shown, done = await control.change_timers(request.user.id, await _control_value(request, data, guessed))
    if data["action"] == "extend" and is_guessed(guessed, "duration"):
        shown += f"\n{GUESS} I guessed how much time to add."
    return Answer(shown, about(request, done))


async def change_all(request: Request, data: dict, guessed: frozenset) -> Answer:
    said = await control.change_all(request.user.id, data["action"] == "pause", with_session=not data.get("leave_pomodoro", False))
    # About every one of them: "it" straight after this names none
    return Answer(said, about(request, await store.active_timers(user_id=request.user.id)))


# ---------------------------------------------------------------------------
# Showing and asking
# ---------------------------------------------------------------------------
async def how_long(request: Request, data: dict, guessed: frozenset) -> Answer:
    """ "how long is left on tea?": the time left on each timer asked about, a
    line each, to the second, in the format of the paused card."""
    wanted = await which_timers(request, data, guessed)
    if wanted.strip().lower() == status.ALL:
        found = await store.active_timers(user_id=request.user.id)
    else:
        ids, _ = status.parse_refs(wanted, status.TIMER)
        found = [timer for timer in [await store.get_timer(timer_id) for timer_id in ids] if timer is not None and timer.user_id == request.user.id]
    if not found:
        raise UserError("I couldn't tell which timer you meant. Say its name.")
    now = utc_now()
    return Answer("\n".join(status.left_line(timer, now) for timer in found), about(request, found))


async def show_list(request: Request, data: dict, guessed: frozenset) -> Shown:
    """The live "Your timers" list, as the word `timers` shows it: one per
    channel, the new one at the bottom taking the old one's place."""
    user_id, channel_id = request.user.id, request.channel_id
    active = await store.active_timers(user_id=user_id)
    running = await store.active_sessions(user_id=user_id)
    previous = dict(await store.lists(user_id)).get(channel_id)
    message = await sender(channel_id)(board.render_list(active, running))
    if previous is not None:
        await delete_message(channel_id, previous, MessageClass.LIVE)
    if not active and not running:
        await store.forget_list(channel_id)
        return Shown("no active timers")
    await store.save_list(channel_id, message.id, user_id)
    return Shown(f"listed {len(active)} timer(s), {len(running)} pomodoro")


def history_text(events: list[store.Event], zone) -> str:
    """What happened to the timers, for the user: a line an event, oldest first."""
    if not events:
        return f"{ICON} Nothing has happened to a timer lately."
    lines = [f"{ICON} **What happened** (oldest first)"]
    for event in events:
        local = event.at.astimezone(zone)
        icon = "🍅 " if event.kind == store.SESSION else ""
        text = f"• {local:%a} {format_time(local.time())} · {icon}**{event.label}** · {event.event}"
        if event.detail:
            text += f" ({event.detail})"
        if event.remaining_s is not None and event.event not in (store.WAS_FINISHED, store.PHASE_FINISHED):
            text += f" · {format_duration(event.remaining_s)} left"
        lines.append(text)
    return "\n".join(lines)


async def history(request: Request, data: dict, guessed: frozenset) -> str:
    wanted = (data.get("which") or "").strip()
    kind = record_id = None
    if wanted:
        for prefix, name in ((status.TIMER, store.TIMER), (status.SESSION, store.SESSION)):
            if wanted.lower().startswith(prefix) and status.parse_ref(wanted, prefix) is not None:
                kind, record_id = name, status.parse_ref(wanted, prefix)
        if kind is None:
            raise UserError("I couldn't tell which timer you meant. Say its name, or ask what happened to all of them.")
    return history_text(await store.events(request.user.id, kind, record_id), TIMEZONE)


# ---------------------------------------------------------------------------
# The Pomodoro session
# ---------------------------------------------------------------------------
def session_line(session: store.Session | None, now: datetime) -> str:
    """The session in a line, for the user."""
    if session is None:
        return "🍅 No Pomodoro session is going."
    phase = PHASE_NAMES[session.phase]
    if session.state == store.RUNNING:
        doing = f"{format_duration(session.left(now))} left"
    elif session.state == store.PAUSED:
        doing = f"paused with {format_duration(session.remaining_s)} left"
    else:
        doing = f"waiting for Start ({format_duration(phase_length(session.plan, session.phase))})"
    return f"🍅 **{session.label}** · {phase}, round {session.round} of {session.rounds} · {doing}"


async def pomo_start(request: Request, data: dict, guessed: frozenset) -> Shown:
    words = [word for word in ((data.get("lengths") or "").strip(), (data.get("mode") or "").strip()) if word]
    words += (data.get("label") or "").split()
    try:
        plan, label, auto = parse_session(words)
    except DurationError as error:
        raise UserError(f"{error} Say the lengths as focus and break, e.g. 50 and 10 minutes.")
    send = sender(request.channel_id)
    running = await store.active_sessions(user_id=request.user.id)
    if running:
        # One session at a time, and asking again isn't a mistake: show the one there is
        session = running[0]
        old_card = session.message_id
        message = await send(sessions.render_card(session), view=sessions.card_view(session))
        session.message_id = message.id
        await store.save_session(session)
        await delete_message(session.channel_id, old_card, MessageClass.LIVE)
        asked = different_lengths(words, session.plan)
        note = "Already going: here it is again."
        if asked:
            note += f" It runs at {status.lengths_text(session)}; stop it first to start one at {asked}."
        return Shown(f"pomodoro {session.id} already going; card shown again", f"-# {note}")
    summary = await sessions.start_session(request.user.id, request.user.discord_id, request.channel_id, plan, label, auto, send)
    also = f"{GUESS} I guessed the lengths. Tell me if they should be something else." if is_guessed(guessed, "lengths") else ""
    return Shown(summary, also)


async def pomo_change(request: Request, data: dict, guessed: frozenset) -> Answer:
    said, session = await control.change_session(request.user.id, {"id": "current", "action": data["action"], "duration": data.get("duration", "")})
    return Answer(said, about(request, [session]))


async def pomo_status(request: Request, data: dict, guessed: frozenset) -> str:
    running = await store.active_sessions(user_id=request.user.id)
    return session_line(running[0] if running else None, utc_now())


async def pomo_stats(request: Request, data: dict, guessed: frozenset) -> str:
    today = day.today()
    since = datetime.combine(week_start(today), datetime.min.time(), tzinfo=TIMEZONE).astimezone(timezone.utc)
    today_totals, week_totals = summarise_focus(await store.focus_log(request.user.id, since), today, TIMEZONE)
    return sessions.render_stats(today_totals, week_totals)


# ---------------------------------------------------------------------------
# The actions
# ---------------------------------------------------------------------------
_WHICH = (
    "The id of each timer meant, taken from the state given with the message, separated by spaces: "
    "\"t12\", or \"t12 t14\" for several. \"all\" for every timer (\"cancel all my timers\", \"stop "
    "everything\"). Match what the user said to a label in the state. \"it\", \"that\", \"this one\" or "
    "just \"the timer\" is `@that`: never work out which timer a pronoun means, the code does. If two "
    "labels fit a name and you cannot tell, give the likeliest and list `which` as guessed."
)
_DURATION = "A length of time as the user said it, in short form with s, m or h only: 5m, 90s, 1h30, 2h. Never a time of day."

ACTIONS = (
    Action(
        "timer_start",
        "Start one or more countdown timers. Examples: \"set a timer for 5 minutes\" -> one timer, duration "
        "5m. \"timer 20 min for tea\" -> duration 20m, label tea. \"start six one-minute timers called a, "
        "b, c, d, e and f\" -> six timers, each 1m with its label. Not for a Pomodoro, and not for a time "
        "of day (\"at 5pm\") or anything repeating: call `none` for those. A length that may be too long "
        "(\"three days\") is still filled in, in hours (72h): the code says what the limit is.",
        (
            Field(
                "timers",
                "Each timer to start, one item each, in the order said.",
                ITEMS,
                required=True,
                item_fields=(
                    Field("duration", _DURATION + " For a vague length (\"a few minutes\") give your best guess and list it as guessed.", required=True),
                    Field("label", "A short name if the user gave one (tea, laundry), as they said it. Leave out if they didn't."),
                ),
            ),
        ),
        needs_card=False,
        run=start,
        purpose=EACH_DAY,
        say=("set a timer for 5 minutes called tea",),
    ),
    Action(
        "timer_change",
        "Pause, resume, cancel or add time to timers that are going. Examples: \"pause the tea timer\" -> "
        "which t12, action pause. \"carry on\" or \"unpause it\" -> action resume. \"stop the laundry "
        "timer\" -> action cancel. \"give tea 5 more minutes\" -> action extend, duration 5m. \"cancel tea "
        "and dinner\" -> which \"t12 t14\". \"cancel all timers\" -> which all. \"stop all timers called "
        "tea\" -> the id of every timer whose label has tea. To pause or resume EVERYTHING, the Pomodoro included, use "
        "`timer_all`. For the Pomodoro session itself use `pomo_change`.",
        (
            Field("which", _WHICH, required=True),
            Field("action", "What to do to them. Stopping a timer is cancel.", choices=CHANGES, required=True),
            Field("duration", "For extend only: how much time to add. " + _DURATION),
        ),
        prepare=cancel_card,
        purpose=EACH_DAY,
        say=("pause the tea timer", "give tea 5 more minutes", "cancel all timers",),
        apply=cancel_saved,
        verify=cancel_check,
        run=change,
        card_if=cancels_several,
    ),
    Action(
        "timer_all",
        "Pause or resume everything at once: every timer AND the Pomodoro session (\"pause everything\", "
        "\"pause all\", \"resume all my timers\"). Set leave_pomodoro only when the user says to leave the "
        "Pomodoro alone (\"pause all except the pomodoro\").",
        (
            Field("action", "pause or resume.", choices=("pause", "resume"), required=True),
            Field("leave_pomodoro", "true only if the user said to leave the Pomodoro session as it is.", BOOLEAN),
        ),
        needs_card=False,
        run=change_all,
        purpose=EACH_DAY,
        say=("pause everything", "resume everything",),
    ),
    Action(
        "timer_list",
        "The user asks to see their timers in general (\"show my timers\", \"what timers do I have?\", "
        "\"what's running?\"). For how long is left on a timer they name, use `timer_left`.",
        needs_card=False,
        run=show_list,
        purpose=SEE,
        say=("show my timers",),
    ),
    Action(
        "timer_left",
        "The user asks how long is left on a timer they name, or on \"it\" (\"how long left on tea?\" -> "
        "which t12; \"how much longer on it?\" -> which `@that`; \"how long on tea and dinner?\" -> which "
        "\"t12 t14\"). For the Pomodoro session use `pomo_status`.",
        (Field("which", _WHICH, required=True),),
        needs_card=False,
        run=how_long,
        purpose=SEE,
        say=("how long is left on tea?",),
    ),
    Action(
        "timer_history",
        "A question about what HAPPENED to timers or the Pomodoro, in the past (\"when did I pause "
        "dinner?\", \"what happened to my timers?\", \"what was left on tea when I paused it?\").",
        (Field("which", "The id of the one timer (t12) or session (p4) asked about, from the state. Leave out for all of them."),),
        needs_card=False,
        run=history,
        purpose=SEE,
        say=("what happened to my timers?",),
    ),
    Action(
        "pomo_start",
        "Start a Pomodoro focus session (\"start a pomodoro\", \"pomodoro 50/10 for writing\", \"focus "
        "session\"). Lengths default to 25/5.",
        (
            Field(
                "lengths",
                "Focus and break in minutes as focus/break, or focus/break/long break: \"50/10\", \"50/10/30\". "
                "Leave out if the user gave none.",
            ),
            Field("mode", "auto if each phase should start by itself, manual if it should wait for Start. Leave out if not said.", choices=("auto", "manual")),
            Field("label", "What the session is for, e.g. writing. Leave out if not said."),
        ),
        needs_card=False,
        run=pomo_start,
        purpose=EACH_DAY,
        say=("start a pomodoro", "pomodoro 50/10 for writing",),
    ),
    Action(
        "pomo_change",
        "Change the Pomodoro session that is going: \"pause my pomodoro\" -> pause. \"carry on with the "
        "session\" -> resume. \"start the break\" when it is waiting for Start -> start. \"skip this break\" "
        "-> skip. \"end the session\" or \"stop the pomodoro\" -> stop. \"10 more minutes on this round\" -> "
        "extend, duration 10m.",
        (
            Field("action", "What to do to the session.", choices=SESSION_CHANGES, required=True),
            Field("duration", "For extend only: how much time to add. " + _DURATION),
        ),
        needs_card=False,
        run=pomo_change,
        purpose=EACH_DAY,
        say=("pause my pomodoro", "skip this break", "end the session",),
    ),
    Action(
        "pomo_status",
        "A question about the Pomodoro session as it is now (\"how long left on my pomodoro?\", \"which "
        "round am I on?\", \"is my pomodoro paused?\").",
        needs_card=False,
        run=pomo_status,
        purpose=SEE,
        say=("how long is left on my pomodoro?",),
    ),
    Action(
        "pomo_stats",
        "How much focus time the user has done (\"how much have I focused today?\", \"pomodoro stats\").",
        needs_card=False,
        run=pomo_stats,
        purpose=SEE,
        say=("how much have I focused today?",),
    ),
)
