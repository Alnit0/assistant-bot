import re
from datetime import datetime

from tasks.timers import store
from core.durations import format_duration
from tasks.timers.pomodoro import PHASE_NAMES, phase_length

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

NO_SESSION = "No Pomodoro session is going."


def age(moment: datetime, now: datetime) -> str:
    """How long ago, in a word or two: "just now", "5m ago", "2h ago"."""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def ref(kind: str, record_id: int) -> str:
    return f"{kind}{record_id}"


def parse_ref(text: str, kind: str) -> int | None:
    """The record id in "t12" (or "T12", "12", "#12"). None if it isn't one of this kind."""
    cleaned = text.strip().lower().lstrip("#")
    if cleaned.startswith(kind):
        cleaned = cleaned[len(kind) :]
    return int(cleaned) if cleaned.isdigit() else None


ALL = "all"
# Words that say "a timer" rather than name one: "the tea timer" is the label "tea"
_NOT_A_LABEL = {"the", "a", "my", "timer", "timers", "called", "named", "one", "ones", "all"}


def parse_refs(text: str, kind: str) -> tuple[list[int], list[str]]:
    """The record ids in "t12 t14" (or "t12, t14", "t12 and t14"), in order and
    once each, and the pieces that are not ids of this kind."""
    ids, bad = [], []
    for piece in re.split(r"[\s,;]+", text.strip()):
        if not piece or piece.lower() in ("and", "&"):
            continue
        record_id = parse_ref(piece, kind)
        if record_id is None:
            bad.append(piece)
        elif record_id not in ids:
            ids.append(record_id)
    return ids, bad


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def label_matches(label: str, wanted: str) -> bool:
    """Whether a timer's label is the one meant by `wanted`: every word asked
    for is a word of the label, whatever the case. So "tea" is "Tea" and
    "tea 2" (every timer called tea), but not "team" or "steam"; and "the
    tea timer" is "tea". Nothing asked for fits every label."""
    asked = [word for word in _words(wanted) if word not in _NOT_A_LABEL] or _words(wanted)
    have = set(_words(label))
    return all(word in have for word in asked)


def labelled(timers: list[store.Timer], wanted: str) -> list[store.Timer]:
    """The timers a label picks out: all of them if no label was given."""
    if not wanted.strip():
        return list(timers)
    return [timer for timer in timers if label_matches(timer.label, wanted)]


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
# `pause all` / `resume all`: exactly what was done
# ---------------------------------------------------------------------------
def bulk_line(label: str, left: float, where: str = "") -> str:
    return f"{label} · " + (f"{where} · " if where else "") + f"{format_duration(left)} left"


CONTROL_WORDS = {
    "pause": ("⏸️", "Paused"),
    "resume": ("▶️", "Resumed"),
    "cancel": ("🚫", "Cancelled"),
    "extend": ("➕", "Added time to"),
}


def control_text(action: str, done: list[str], left_alone: list[str]) -> str:
    """What timer_control did to several timers at once: each one by name."""
    icon, verb = CONTROL_WORDS[action]
    lines = [f"{icon} **{verb} {len(done)}**", *(f"• {line}" for line in done)]
    if left_alone:
        lines.append("Left alone: " + "; ".join(left_alone))
    return "\n".join(lines)


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
