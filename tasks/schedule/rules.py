from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from core import design, timeinput, timetable
from core.errors import UserError
from core.timetable import ALL_DAYS, DAY_NAMES, NOTIFY, ON, PAUSED, REMOVED, SILENT, Occurrence, Schedule

# ---------------------------------------------------------------------------
# My schedule, in words: the list, the lines of a change card, and reading
# what Claude handed over (a time in the one form, days as a list of
# weekdays, a date as I said it). Pure: no clock, no database, no Discord.
# ---------------------------------------------------------------------------
TASK = "schedule"
ICON = "🗓️"
HEADING = f"{ICON} My schedule"
DAY_WORDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PAUSE, RESUME = "pause", "resume"
HINT = "say what to change: “move the pills checklist to 7”, “pause it until Monday”"
PILL_TIMES = "Pill times belong to each pill: say “pills”"


@dataclass(frozen=True)
class Listed:
    """A schedule as the list shows it: with what each step is called, when it
    next runs and how its last run ended."""

    schedule: Schedule
    steps: tuple[str, ...]  # each step in words ("pills checklist")
    coming: Occurrence | None = None
    last: tuple[str, str] | None = None  # (how it ended, the local date and time it stood for)


def notify_text(notify: str) -> str:
    return "notifies" if notify == NOTIFY else "silent"


def when(schedule: Schedule) -> str:
    """ "every day at `6:00 am`", "Mon to Fri at `5:00 pm`"."""
    return f"{timetable.days_text(schedule.days)} at `{timeinput.format_time(schedule.at)}`"


def day_text(day: date, today: date) -> str:
    """A day as it is said beside a time: today, tomorrow, or "Mon 19 Oct"."""
    if day == today:
        return "today"
    if (day - today).days == 1:
        return "tomorrow"
    return f"{day:%a} {day.day} {day:%b}"


def moment_text(local: datetime, today: date) -> str:
    return f"{day_text(local.date(), today)} {timeinput.format_time(local.time())}"


def paused_text(schedule: Schedule, today: date) -> str:
    if schedule.state != PAUSED:
        return "no"
    return f"until {day_text(schedule.paused_until, today)}" if schedule.paused_until else "until you turn it back on"


_ENDED = {"done": "✅", "failed": "⚠️ failed", "skipped": "⚠️ not done", "missed": "⏭️ set aside"}
NOT_RUN = "last: not run yet"


def last_text(listed: Listed, today: date) -> str:
    """When a schedule last ran and whether it worked: every line of the list says so."""
    if listed.last is None:
        return NOT_RUN
    ended, stamp = listed.last
    return f"last: {moment_text(datetime.fromisoformat(stamp), today)} {_ENDED.get(ended, ended)}"


def _detail(listed: Listed, today: date) -> str:
    schedule = listed.schedule
    parts = [f"#{schedule.channel}", notify_text(schedule.notify)]
    if listed.coming is not None:
        parts.append(f"next: {moment_text(listed.coming.local, today)}")
    parts.append(last_text(listed, today))
    return " · ".join(parts)


def _steps(listed: Listed) -> list[str]:
    """A routine's steps, numbered. One step is the schedule itself: nothing to list."""
    return [f"{number}. {step}" for number, step in enumerate(listed.steps, start=1)] if len(listed.steps) > 1 else []


def split(found: list[Listed]) -> tuple[list[Listed], list[Listed], list[Listed]]:
    """(mine and on, mine and paused, the bot's own), each in the order of the time of day."""
    mine = [each for each in found if not each.schedule.locked and each.schedule.state != REMOVED]
    own = [each for each in found if each.schedule.locked and each.schedule.state != REMOVED]
    return [each for each in mine if each.schedule.state == ON], [each for each in mine if each.schedule.state == PAUSED], own


def _counts(on: list, paused: list) -> str:
    return f"{len(on)} on" + (f" · {len(paused)} paused" if paused else "") + " · times are New Zealand time"


OWN = "The bot's own, not changed here:"


def _own_lines(own: list[Listed], today: date) -> list[str]:
    """The bot's own schedules, a line each, with when each last ran and whether it worked."""
    said = [f"{each.schedule.name} · {timeinput.format_time(each.schedule.at)} · {last_text(each, today)}" for each in own]
    return [OWN, *said] if own else []


def list_text(found: list[Listed], today: date) -> str:
    """The list as a plain message (the old look, and what is logged)."""
    on, paused, own = split(found)
    lines = [f"## {HEADING}", design.small(_counts(on, paused))]
    for each in on:
        lines += ["", f"**{each.schedule.name}** · {when(each.schedule)}", *_steps(each), design.small(_detail(each, today))]
    if paused:
        lines += ["", "⏸️ **Paused**"]
        lines += [design.small(f"{each.schedule.name} · {when(each.schedule)} · {paused_text(each.schedule, today)}") for each in paused]
    if not on and not paused:
        lines += ["", "Nothing is scheduled."]
    lines += ["", *(design.small(line) for line in (*_own_lines(own, today), PILL_TIMES, HINT) if line)]
    return "\n".join(lines)


def list_layout(found: list[Listed], today: date) -> tuple:
    """The list in the one style of docs/DESIGN.md: a box a schedule, the next
    to run amber (due next, with a time), the rest grey (to come), the paused
    ones together under a separator. No buttons: every change is by words."""
    on, paused, own = split(found)
    soonest = min((each.coming.moment for each in on if each.coming is not None), default=None)
    boxes = [
        design.item(
            design.DUE if each.coming is not None and each.coming.moment == soonest else design.QUIET,
            f"**{each.schedule.name}** · {when(each.schedule)}", *_steps(each), design.small(_detail(each, today)),
        )
        for each in on
    ]
    later = []
    if paused:
        lines = [design.small(f"{each.schedule.name} · {when(each.schedule)} · {paused_text(each.schedule, today)}") for each in paused]
        later.append(design.item(design.QUIET, "⏸️ **Paused**", *lines))
    hint = "\n".join(design.small(line) for line in (*_own_lines(own, today), PILL_TIMES, HINT) if line)
    pieces = design.standing(HEADING, _counts(on, paused), boxes, later)
    return (*pieces, design.Text(hint))


# ---------------------------------------------------------------------------
# Reading what was handed over
# ---------------------------------------------------------------------------
def read_time(text: str) -> time:
    """A time of day in the one form Claude hands over ("7:00 am")."""
    try:
        return timeinput.parse_time(text)
    except Exception as error:
        raise UserError(f"“{text}” is not a time I can read: {error}") from error


def read_days(words) -> tuple[int, ...]:
    """Weekdays as handed over (mon … sun) as numbers, Monday 0."""
    found = []
    for word in words or ():
        key = str(word).strip().lower()[:3]
        if key not in DAY_WORDS:
            raise UserError(f"“{word}” is not a day of the week.")
        found.append(DAY_WORDS.index(key))
    return tuple(sorted(set(found)))


def changed_days(now: tuple[int, ...], named: tuple[int, ...], how: str) -> tuple[int, ...]:
    """The days after "also Saturdays" (add), "not on Sundays" (remove) or "weekdays only" (set)."""
    if how == "add":
        return tuple(sorted(set(now) | set(named)))
    if how == "remove":
        return tuple(sorted(set(now) - set(named)))
    return tuple(sorted(set(named)))


def read_until(text: str, today: date) -> date:
    """The day a pause ends, from the date as I said it ("Monday", "the 20th")."""
    try:
        until = timeinput.parse_date(text, today)
    except Exception as error:
        raise UserError(f"“{text}” is not a date I can read: {error}") from error
    if until <= today:
        raise UserError(f"“{text}” is {day_text(until, today)}: a pause ends on a later day.")
    return until


def local_today(now: datetime, zone: str = timetable.ZONE) -> date:
    return now.astimezone(ZoneInfo(zone)).date()


def change_lines(before: Schedule, after: Schedule, today: date) -> list[str]:
    """What differs, as `field · old → new`, in the order the settings are said."""
    found = []
    if before.at != after.at:
        found.append(f"time · `{timeinput.format_time(before.at)}` → `{timeinput.format_time(after.at)}`")
    if before.days != after.days:
        found.append(f"days · {timetable.days_text(before.days)} → {timetable.days_text(after.days)}")
    if before.notify != after.notify:
        found.append(f"notify · {notify_text(before.notify)} → {notify_text(after.notify)}")
    if (before.state, before.paused_until) != (after.state, after.paused_until):
        old, new = paused_text(before, today), paused_text(after, today)
        found.append(f"paused · {old} → {'on' if new == 'no' else new}")
    if before.channel != after.channel:
        found.append(f"channel · #{before.channel} → #{after.channel}")
    return found


def next_line(name: str, coming: Occurrence | None, today: date) -> str:
    return f"{name} {moment_text(coming.local, today)}" if coming is not None else f"{name}: not while it is paused"


def part_of_day(at: time) -> str:
    return "Morning" if at.hour < 12 else "Afternoon" if at.hour < 17 else "Evening" if at.hour < 21 else "Night"


def name_for(label: str, at: time, taken: set[str]) -> str:
    """What a schedule I add is called: the thing it runs ("Pills checklist");
    if that is taken, with the part of the day ("Evening pills checklist"),
    and a number if that is taken too. Names are told apart whatever the case."""
    plain = label[:1].upper() + label[1:]
    if plain.lower() not in taken:
        return plain
    timed = f"{part_of_day(at)} {label}"
    number, name = 2, timed
    while name.lower() in taken:
        name, number = f"{timed} {number}", number + 1
    return name


def all_days() -> tuple[int, ...]:
    return ALL_DAYS


def day_names() -> tuple[str, ...]:
    return DAY_NAMES
