from dataclasses import dataclass
from datetime import date, datetime, timedelta

from tasks.timers.durations import DurationError, parse_duration

# ---------------------------------------------------------------------------
# Pomodoro: the rules of the cycle, and the arithmetic of pausing.
# Pure functions: no Discord, no database, no clock (times are passed in).
# ---------------------------------------------------------------------------
FOCUS, SHORT_BREAK, LONG_BREAK = "focus", "short_break", "long_break"
PHASE_NAMES = {FOCUS: "Focus", SHORT_BREAK: "Short break", LONG_BREAK: "Long break"}

DEFAULT_LABEL = "Pomodoro"


@dataclass(frozen=True)
class Plan:
    focus_s: int = 25 * 60
    short_s: int = 5 * 60
    long_s: int = 15 * 60
    rounds: int = 4  # focus rounds before the long break


def phase_length(plan: Plan, phase: str) -> int:
    return {FOCUS: plan.focus_s, SHORT_BREAK: plan.short_s, LONG_BREAK: plan.long_s}[phase]


def next_phase(plan: Plan, phase: str, round_number: int) -> tuple[str, int]:
    """What follows a phase: (phase, round).

    Focus is followed by a break (the long one after the last round of a set);
    a short break by the next round; a long break by round 1 of a new set.
    """
    if phase == FOCUS:
        return (LONG_BREAK if round_number >= plan.rounds else SHORT_BREAK), round_number
    if phase == SHORT_BREAK:
        return FOCUS, round_number + 1
    return FOCUS, 1


def counts_as_focus(phase: str, completed: bool) -> bool:
    """Only a focus phase that ran to its end goes in the log (not a skipped one)."""
    return phase == FOCUS and completed


def starts_by_itself(auto_continue: bool, is_late: bool) -> bool:
    """Whether the next phase's clock starts without the user pressing Start.

    Only in auto mode, and never when the phase ended while the bot was off:
    after downtime the user may not be there.
    """
    return auto_continue and not is_late


def parse_session(words: list[str]) -> tuple[Plan, str, bool | None]:
    """Read the words after "pomo": (plan, label, auto-continue or None for the default).

    "50/10" sets focus and short break; "50/10/30" the long break too. Numbers
    are minutes unless they carry a unit ("30s/10s", handy for testing).
    "auto" or "manual" chooses whether phases start by themselves. Anything
    else is the label (including a word with a slash that doesn't start with
    a digit, such as "read/write").
    """
    plan = Plan()
    auto: bool | None = None
    label_words = []
    for word in words:
        lowered = word.lower()
        if lowered in ("auto", "manual") and auto is None:
            auto = lowered == "auto"
        elif "/" in word and word[0].isdigit() and label_words == [] and plan == Plan():
            parts = word.split("/")
            if len(parts) not in (2, 3):
                raise DurationError("Use focus/break or focus/break/long break, e.g. `pomo 50/10`.")
            lengths = [parse_duration(part) for part in parts]
            plan = Plan(lengths[0], lengths[1], lengths[2] if len(lengths) == 3 else plan.long_s)
        else:
            label_words.append(word)
    return plan, " ".join(label_words) or DEFAULT_LABEL, auto


# ---------------------------------------------------------------------------
# Pausing, resuming and extending. The same arithmetic serves simple timers.
# ---------------------------------------------------------------------------
# `pomo` while a session is already going shows that session instead of failing
RESHOW, POINT = "reshow", "point"


def where_to_show(session_channel_id: int, typed_channel_id: int) -> str:
    """How to show a session that is already going: its card again at the bottom
    of its own channel, or a pointer to it when asked from somewhere else (the
    card, its alerts and the board all stay in the channel it was started in)."""
    return RESHOW if session_channel_id == typed_channel_id else POINT


def different_lengths(words: list[str], current: Plan) -> str | None:
    """The lengths asked for, as typed ("25/5"), if they aren't the ones the
    session that is already going has. None if none were given or they match.
    (`words` have been through parse_session, so they are known to be readable.)"""
    for word in words:
        if "/" in word and word[0].isdigit():
            asked = [parse_duration(part) for part in word.split("/")]
            going = [current.focus_s, current.short_s, current.long_s][: len(asked)]
            return word if asked != going else None
    return None


def remaining_seconds(ends_at: datetime, now: datetime) -> float:
    """Time left on a running clock, never negative."""
    return max(0.0, (ends_at - now).total_seconds())


def resumed_end(now: datetime, remaining: float) -> datetime:
    """When a paused clock will end if it is resumed now."""
    return now + timedelta(seconds=remaining)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FocusTotals:
    sessions: int
    seconds: int
    by_label: tuple[tuple[str, int], ...]  # (label, seconds), most time first


def _totals(entries: list[tuple[str, int]]) -> FocusTotals:
    by_label: dict[str, int] = {}
    for label, seconds in entries:
        by_label[label] = by_label.get(label, 0) + seconds
    ordered = tuple(sorted(by_label.items(), key=lambda item: (-item[1], item[0])))
    return FocusTotals(len(entries), sum(seconds for _, seconds in entries), ordered)


def week_start(day: date) -> date:
    """The Monday of the week `day` is in."""
    return day - timedelta(days=day.weekday())


def summarise_focus(
    log: list[tuple[datetime, str, int]], today: date, timezone
) -> tuple[FocusTotals, FocusTotals]:
    """Totals for today and for this week (Monday to today), in the given timezone.

    `log` is (completed at, label, seconds) for each completed focus phase.
    """
    start = week_start(today)
    today_entries, week_entries = [], []
    for completed_at, label, seconds in log:
        day = completed_at.astimezone(timezone).date()
        if start <= day <= today:
            week_entries.append((label, seconds))
            if day == today:
                today_entries.append((label, seconds))
    return _totals(today_entries), _totals(week_entries)
