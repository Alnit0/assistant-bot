from datetime import datetime

from core.tools import age
from skills.timers import store
from skills.timers.durations import format_duration
from skills.timers.pomodoro import PHASE_NAMES, phase_length

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
NO_EVENTS = (
    "Nothing is recorded for that. What happens to timers has only been kept since the record "
    "was added, so anything earlier is not here."
)
# Put after everything a read tool returns: Claude once read the list and then
# said the timer was running again
ONLY_READ = "(This only read the state. Nothing was changed by this call.)"


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


def timer_state(timer: store.Timer, now: datetime) -> str:
    """What a timer is doing and how long it has left, in its own time (dev
    mode can run a clock faster; the timer knows its speed)."""
    if timer.status == store.RUNNING:
        return f"running, {format_duration(timer.left(now))} left"
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
) -> str:
    """Every timer that is going, then the ones that ended lately (so "the tea
    timer" that has already finished can be told apart from one that never
    existed). `replied_to` is the message the user replied to, if any: the
    timer it belongs to is pointed out."""

    def line(timer: store.Timer) -> str:
        parts = [f'{ref(TIMER, timer.id)}: "{timer.label}"', timer_state(timer, now)]
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
) -> str:
    """The session that is going: phase, round, time left or what it is waiting for."""
    if session is None:
        return NO_SESSION
    phase = PHASE_NAMES[session.phase]
    if session.state == store.RUNNING:
        state = f"running, {format_duration(session.left(now))} left in this phase"
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


def phase_text(session: store.Session) -> str:
    return f"{PHASE_NAMES[session.phase]}, round {session.round}"


# ---------------------------------------------------------------------------
# What happened: the events of a timer or session, oldest first
# ---------------------------------------------------------------------------
def events_text(events: list[store.Event], zone) -> str:
    """One line per event with the local time and what was left on the clock then."""
    if not events:
        return NO_EVENTS
    lines = ["What happened, oldest first (times are local):"]
    for event in events:
        kind = TIMER if event.kind == store.TIMER else SESSION
        text = f'{event.at.astimezone(zone):%a %H:%M:%S} · {ref(kind, event.record_id)} "{event.label}" · {event.event}'
        if event.detail:
            text += f" ({event.detail})"
        if event.remaining_s is not None and event.event not in (store.WAS_FINISHED, store.PHASE_FINISHED):
            text += f" · {format_duration(event.remaining_s)} left"
        lines.append(text)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# `pause all` / `resume all`: exactly what was done
# ---------------------------------------------------------------------------
def bulk_line(label: str, left: float, where: str = "") -> str:
    return f"{label} · " + (f"{where} · " if where else "") + f"{format_duration(left)} left"


def bulk_text(pausing: bool, done: list[str], left_alone: list[str], note: str = "") -> str:
    """What `pause all` or `resume all` did: each one by name with the time left on it."""
    icon, verb, nothing = ("⏸️", "Paused", "running") if pausing else ("▶️", "Resumed", "paused")
    if done:
        lines = [f"{icon} **{verb} {len(done)}**", *(f"• {line}" for line in done)]
    else:
        lines = [f"{icon} Nothing was {nothing}, so nothing was {verb.lower()}."]
    if left_alone:
        lines.append("Left alone: " + "; ".join(left_alone))
    if note:
        lines.append(note)
    return "\n".join(lines)
