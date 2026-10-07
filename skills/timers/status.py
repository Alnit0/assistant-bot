from collections.abc import Callable
from datetime import datetime

from core.tools import age
from skills.timers import store
from skills.timers.durations import format_duration
from skills.timers.pomodoro import PHASE_NAMES, phase_length, remaining_seconds

# ---------------------------------------------------------------------------
# The live state of timers and the Pomodoro session, in words for Claude.
# Pure: records and the time are passed in, text comes out.
#
# Claude can't read Discord's live timestamps, so it is given the time left
# as it stands, and an id for each record: "t12" for a timer, "p4" for a
# session. The control tools take that id, so nothing is found by searching
# the chat.
# ---------------------------------------------------------------------------
TIMER, SESSION = "t", "p"

NO_TIMERS = "No timers are running or paused."
NO_SESSION = "No Pomodoro session is going."


def ref(kind: str, record_id: int) -> str:
    return f"{kind}{record_id}"


def parse_ref(text: str, kind: str) -> int | None:
    """The record id in "t12" (or "T12", "12", "#12"). None if it isn't one of this kind."""
    cleaned = text.strip().lower().lstrip("#")
    if cleaned.startswith(kind):
        cleaned = cleaned[len(kind) :]
    return int(cleaned) if cleaned.isdigit() else None


def _where(channel_id: int, here: int | None) -> str:
    return f"<#{channel_id}>" + (" (this channel)" if channel_id == here else "")


def _same(seconds: float) -> float:
    return seconds


def timer_state(timer: store.Timer, now: datetime, nominal: Callable[[float], float] = _same) -> str:
    """What a timer is doing and how long it has left. `nominal` turns real
    seconds into the timer's own (dev mode can run the clock faster)."""
    if timer.status == store.RUNNING:
        return f"running, {format_duration(nominal(remaining_seconds(timer.ends_at, now)))} left"
    if timer.status == store.PAUSED:
        return f"paused with {format_duration(timer.remaining_s)} left"
    if timer.status == store.CANCELLED:
        return "cancelled"
    when = f" {age(timer.ends_at, now)}" if timer.ends_at is not None else ""
    waiting = ", its alert not dismissed yet" if timer.status == store.FINISHED else ""
    return f"finished{when}{waiting}"


def timers_text(
    active: list[store.Timer],
    ended: list[store.Timer],
    session: store.Session | None,
    now: datetime,
    *,
    here: int | None = None,
    replied_to: int | None = None,
    nominal: Callable[[float], float] = _same,
) -> str:
    """Every timer that is going, then the ones that ended lately (so "the tea
    timer" that has already finished can be told apart from one that never
    existed). `replied_to` is the message the user replied to, if any: the
    timer it belongs to is pointed out."""

    def line(timer: store.Timer) -> str:
        parts = [f'{ref(TIMER, timer.id)}: "{timer.label}"', timer_state(timer, now, nominal)]
        if timer.active:
            parts.append(_where(timer.channel_id, here))
        else:
            parts.append(f"was {format_duration(timer.duration_s)}")
        text = " · ".join(parts)
        if replied_to is not None and replied_to in (timer.message_id, timer.notice_message_id):
            text += " · the user replied to this one"
        return text

    lines = []
    if active:
        lines.append("Timers going now. Use the id with timer_control:")
        lines += [line(timer) for timer in active]
    else:
        lines.append(NO_TIMERS)
    if ended:
        lines.append("Ended in the last day (nothing more can be done to these):")
        lines += [line(timer) for timer in ended]
    if session is not None:
        lines.append(
            f'Pomodoro: {ref(SESSION, session.id)} "{session.label}" is going; get_pomodoro_status has the details.'
        )
    return "\n".join(lines)


def lengths_text(session: store.Session) -> str:
    """A session's lengths as they are typed: "50m/10m/30m"."""
    return "/".join(format_duration(seconds) for seconds in (session.focus_s, session.short_s, session.long_s))


def session_text(
    session: store.Session | None,
    now: datetime,
    *,
    here: int | None = None,
    nominal: Callable[[float], float] = _same,
) -> str:
    """The session that is going: phase, round, time left or what it is waiting for."""
    if session is None:
        return NO_SESSION
    phase = PHASE_NAMES[session.phase]
    if session.state == store.RUNNING:
        state = f"running, {format_duration(nominal(remaining_seconds(session.ends_at, now)))} left in this phase"
    elif session.state == store.PAUSED:
        state = f"paused with {format_duration(session.remaining_s)} left in this phase"
    else:
        length = format_duration(phase_length(session.plan, session.phase))
        state = f"waiting for Start: {phase} ({length}) is next and nothing is counting down"
    return " · ".join(
        [
            f'{ref(SESSION, session.id)}: "{session.label}"',
            f"{phase}, round {session.round} of {session.rounds}",
            state,
            f"lengths {lengths_text(session)} (focus/break/long break)",
            "phases start by themselves" if session.auto_continue else "each phase waits for Start",
            _where(session.channel_id, here),
        ]
    )
