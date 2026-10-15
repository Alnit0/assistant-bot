from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from core import design, names, timeinput
from core import day as days
from core.config import TIMEZONE
from core.errors import UserError

# ---------------------------------------------------------------------------
# The calendar (docs/specs/calendar.md, private): events read from the
# calendar's feed, the words of every answer, and what a day holds. Pure.
#
# An event is one happening: a repeating event is each of its happenings
# (worked out by recurring-ical-events, with its exceptions and the ones
# that were cancelled taken out). A timed event's start and end are UTC
# moments and are shown in Auckland time; an all-day one is a first and a
# last local day. Only what the hub needs is kept: a title and its times.
#
# What an event is called never goes to Claude: questions come with a day
# and the search words as said, and this file finds the event and writes
# the answer. The first line of an answer names no event (a phone may
# show it); the names come after.
# ---------------------------------------------------------------------------
TASK = "calendar"
ICON = "📅"
TITLE = "Calendar"
AHEAD_DAYS = 62  # how far ahead the copy reaches
BEHIND_DAYS = 1  # and back: yesterday, for an event that runs past midnight
SOON = timedelta(minutes=30)  # an event this close is worth a look (attention level 3)
STALE = timedelta(hours=6)  # a feed not read for this long needs a look
NO_TITLE = "(no title)"
DAY_SPAN, WEEK, NEXT_WEEK = "day", "week", "next_week"
SPANS = (DAY_SPAN, WEEK, NEXT_WEEK)


@dataclass(frozen=True)
class Event:
    key: str  # the event's id and its happening's start: one happening, once
    title: str
    start: datetime | None = None  # UTC, for a timed event
    end: datetime | None = None  # UTC
    first_day: date | None = None  # for an all-day event: its first local day
    last_day: date | None = None  # and its last (the same for a one-day event)
    origin: str = ""  # which calendar it came from ("link", "bot"): never the calendar's id
    ref: str = ""  # the event's id in that calendar, for the Bot calendar's events (to move or delete)
    series: str = ""  # for one happening of a repeating event in the Bot calendar: the series' id

    @property
    def repeats(self) -> bool:
        return bool(self.series)

    @property
    def mine(self) -> bool:
        """An event the bot added, in its own calendar: the only kind it may change."""
        return self.origin == "bot" and bool(self.ref)

    @property
    def all_day(self) -> bool:
        return self.start is None


# --- reading the feed -----------------------------------------------------------------------------------------
def _moment(value) -> datetime:
    """A start or end as a UTC moment: one with no zone is local (Auckland)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=TIMEZONE).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def parse(text: str, first: date, last: date) -> list[Event]:
    """Every happening from the start of `first` to the end of `last` (local days), in
    order. Raises ValueError for a feed that is not a calendar."""
    import icalendar
    import recurring_ical_events

    try:
        calendar = icalendar.Calendar.from_ical(text)
    except Exception as error:
        raise ValueError(f"not a calendar ({type(error).__name__})") from None
    if calendar.name != "VCALENDAR":
        raise ValueError("not a calendar")
    found = []
    for each in recurring_ical_events.of(calendar).between(days.start_of(first), days.start_of(last + timedelta(days=1))):
        if str(each.get("STATUS", "")).upper() == "CANCELLED":
            continue
        title = " ".join(str(each.get("SUMMARY") or "").split()) or NO_TITLE
        start = each.decoded("DTSTART")
        end = each.decoded("DTEND") if each.get("DTEND") is not None else None
        if end is None and each.get("DURATION") is not None:
            end = start + each.decoded("DURATION")
        key = f"{each.get('UID', '')}@{start.isoformat()}"
        if isinstance(start, datetime):
            begins = _moment(start)
            ends = _moment(end) if isinstance(end, datetime) else begins
            found.append(Event(key, title, begins, max(ends, begins)))
        else:
            last_day = (end - timedelta(days=1)) if isinstance(end, date) and not isinstance(end, datetime) and end > start else start
            found.append(Event(key, title, first_day=start, last_day=last_day))
    return ordered(found)


def week_line(by_day: list[tuple[date, list]]):
    """The calendar's line in the week of everything: next week's events counted by day
    ("Mon 2 · Wed 1 · Fri 3"), and the first one's time small. Never an event's name: this
    can reach a lock screen. `by_day` is (day, [each event's start, or None all day])."""
    from core import design, timeinput
    from core.weekly import Week

    shown = [(day, starts) for day, starts in by_day if starts]
    if not shown:
        return None
    line = "next week · " + " · ".join(f"{day:%a} {len(starts)}" for day, starts in shown)
    first_day, starts = shown[0]
    timed = sorted(each for each in starts if each is not None)
    small = f"first: {first_day:%a} {timeinput.format_moment(timed[0])}" if timed else f"first: {first_day:%a}, all day"
    return Week(line, None, None, small, design.QUIET)


def merged(events) -> list[Event]:
    """Every calendar's events as one: the same happening in two calendars (the same title, the same
    times) is shown once, the bot's own copy kept when there is one, as it is the one it can change."""
    kept: dict = {}
    for each in events:
        same = (" ".join(each.title.lower().split()), each.start, each.end, each.first_day, each.last_day)
        if same not in kept or (each.mine and not kept[same].mine):
            kept[same] = each
    return ordered(kept.values())


def clashes(events, start: datetime, end: datetime, leaving: str = "") -> list[Event]:
    """The timed events (from every calendar) that overlap a stretch of time, but the one being moved."""
    return [each for each in ordered(events) if not each.all_day and each.start < end and each.end > start and not (leaving and each.ref == leaving)]


def title_from(said: str, message: str) -> str:
    """A new event's title in the user's own words: the words extraction gave, as they stand in the
    message (its casing), the first letter made a capital. "" when they are not the message's words."""
    words = str(said or "").split()
    if not words:
        return ""
    text = " ".join(str(message or "").split())
    at = text.lower().find(" ".join(words).lower())
    if at >= 0:
        found = text[at:at + len(" ".join(words))]
    else:
        typed = text.lower().split()
        if not all(word.lower().strip(".,!?") in [each.strip(".,!?") for each in typed] for word in words):
            return ""
        found = " ".join(words)
    found = found.strip(" .,!?")
    return found[:1].upper() + found[1:]


def span_text(start: datetime, end: datetime, today: date) -> str:
    """ "Fri 16 Oct · `3:00 pm` to `4:00 pm` · 1 hour" """
    day = days.day_of(start)
    minutes = int((end - start).total_seconds() // 60)
    hours = f"{minutes // 60} hour{'s' if minutes // 60 != 1 else ''}"
    length = hours if minutes % 60 == 0 else f"{hours} {minutes % 60} minutes" if minutes >= 120 else f"{minutes} minutes"
    return f"{day_name(day, today)} · `{timeinput.format_moment(start)}` to `{timeinput.format_moment(end)}` · {length}"


NOT_MINE = "{icon} I can only change events I added, and **{title}** is on another calendar. Say “add …” and I'll add a new one."


def ordered(events) -> list[Event]:
    """All-day first, then by start, then by title."""
    return sorted(events, key=lambda each: (not each.all_day, each.start.timestamp() if each.start else 0, each.first_day or date.min, each.title.lower()))


# --- what a day holds -------------------------------------------------------------------------------------------
def on_day(events, day: date) -> list[Event]:
    """The events on a local day: all-day ones that cover it, timed ones that overlap it."""
    begin, end = days.start_of(day), days.start_of(day + timedelta(days=1))
    found = []
    for each in events:
        if each.all_day:
            if each.first_day <= day <= each.last_day:
                found.append(each)
        elif each.start < end and (each.end > begin or (each.end == each.start and each.start >= begin)):
            found.append(each)
    return ordered(found)


def coming(events, now: datetime) -> list[Event]:
    """Timed events still to start, soonest first."""
    return [each for each in ordered(events) if not each.all_day and each.start > now]


def when_text(event: Event, day: date) -> str:
    """When an event is on a day, as the hub writes it: "9:00 am to 10:00 am", "all day",
    "until 11:00 am" (it began the day before), "from 9:00 pm" (it ends after the day)."""
    if event.all_day:
        return "all day"
    begin, end = days.start_of(day), days.start_of(day + timedelta(days=1))
    starts_today, ends_today = event.start >= begin, event.end <= end
    start, finish = timeinput.format_moment(event.start), timeinput.format_moment(event.end)
    if starts_today and ends_today:
        return start if event.end == event.start else f"{start} to {finish}"
    if starts_today:
        return f"from {start}"
    if ends_today:
        return f"until {finish}"
    return "all day"


def day_name(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return f"{day:%a} {day.day} {day:%b}"


def count_text(count: int) -> str:
    return f"{count} event{'' if count == 1 else 's'}"


def event_line(event: Event, day: date) -> str:
    when = when_text(event, day)
    return f"{design.time(when) if when[0].isdigit() else when} · **{event.title}**"


# --- answers to questions (templates; the first line names no event) -----------------------------------------------
def day_answer(events, day: date, today: date) -> str:
    found = on_day(events, day)
    name = day_name(day, today)
    if not found:
        return f"{ICON} Nothing on {name.lower() if name in ('Today', 'Tomorrow') else name}."
    return "\n".join([f"{ICON} **{name}** · {count_text(len(found))}", *(event_line(each, day) for each in found)])


def span_days(span: str, today: date, said: date | None = None) -> list[date]:
    """The days a question covers: one day, the rest of this week (to Sunday), or next week (Monday to Sunday)."""
    if span == WEEK:
        return [today + timedelta(days=offset) for offset in range(7 - today.weekday())]
    if span == NEXT_WEEK:
        monday = today + timedelta(days=7 - today.weekday())
        return [monday + timedelta(days=offset) for offset in range(7)]
    return [said or today]


def week_answer(events, span_of: list[date], today: date, label: str) -> str:
    """A week: a day a heading, each day's first three events in full and "+N more" (the list
    rule, design.listed); a day with nothing is left out."""
    total = sum(len(on_day(events, day)) for day in span_of)
    if not total:
        return f"{ICON} Nothing on {label}."
    lines = [f"{ICON} **{label[:1].upper() + label[1:]}** · {count_text(total)}"]
    for day in span_of:
        found = on_day(events, day)
        if not found:
            continue
        listing = design.listed(found)
        lines.append(f"**{day_name(day, today)}**")
        lines += [event_line(each, day) for each in listing.shown]
        if listing.more:
            lines.append(design.small(design.more_line(listing.more)))
    return "\n".join(lines)


def next_matching(events, words: str, now: datetime) -> Event:
    """The next event (still to end) whose title fits the words, by core/names.py. Titles that
    fit and differ are said, never guessed; the same event repeating is its next happening."""
    upcoming = [each for each in ordered(events) if (each.end or days.start_of(each.last_day + timedelta(days=1))) > now] if events else []
    titles = sorted({each.title for each in upcoming})
    if not titles:
        raise UserError(f"{ICON} Nothing is on your calendar in the next {AHEAD_DAYS} days.")
    try:
        title = names.find(titles, words, lambda each: each)
    except names.Unknown:
        raise UserError(f"{ICON} Nothing like “{words}” is on your calendar in the next {AHEAD_DAYS} days.")
    except names.Ambiguous as which:
        raise UserError(f"{ICON} “{words}” could be {' or '.join(f'**{each}**' for each in which.candidates[:4])}: say which.")
    return next(each for each in upcoming if each.title == title)


def matching_on(events, words: str, day: date) -> Event:
    """The event on a day whose title fits the words (core/names.py): "work next Tuesday"."""
    there = on_day(events, day)
    titles = sorted({each.title for each in there})
    try:
        title = names.find(titles, words, lambda each: each) if titles else None
    except names.Unknown:
        title = None
    except names.Ambiguous as which:
        raise UserError(f"{ICON} “{words}” could be {' or '.join(f'**{each}**' for each in which.candidates[:4])}: say which.")
    if title is None:
        raise UserError(f"{ICON} Nothing like “{words}” is on your calendar on {day:%a} {day.day} {day:%b}.")
    return next(each for each in there if each.title == title)


def when_answer(event: Event, today: date) -> str:
    if event.all_day:
        day = event.first_day if event.first_day >= today else today
        return "\n".join([f"{ICON} Next one · {day_name(day, today)}, all day", f"**{event.title}**"])
    day = days.day_of(event.start)
    return "\n".join([f"{ICON} Next one · {day_name(day, today)}, {design.time(timeinput.format_moment(event.start))}", f"**{event.title}** · {when_text(event, day)}"])


def free_answer(events, moment: datetime, today: date) -> str:
    """Am I free then? What overlaps that moment (an all-day event does not count as busy)."""
    day = days.day_of(moment)
    said = f"{design.time(timeinput.format_moment(moment))} {day_name(day, today).lower() if day_name(day, today) in ('Today', 'Tomorrow') else 'on ' + day_name(day, today)}"
    busy = [each for each in on_day(events, day) if not each.all_day and each.start <= moment < max(each.end, each.start + timedelta(minutes=1))]
    if not busy:
        return f"{ICON} You're free at {said}."
    return "\n".join([f"{ICON} Not free at {said}", *(event_line(each, day) for each in busy)])


def read_time(said: str) -> time:
    """A time asked about: one that could be either (\"3\") is the one in the day (7 am to
    10 pm); one that is not either way is asked."""
    try:
        return timeinput.parse_time(str(said))
    except timeinput.AmbiguousTime as which:
        daytime = [each for each in which.options if time(7, 0) <= each <= time(22, 0)]
        if len(daytime) == 1:
            return daytime[0]
        raise UserError(f"Is that {' or '.join(timeinput.format_time(each) for each in which.options)}?")
    except Exception:
        raise UserError(f"“{said}” is not a time I can read.")


def _readings(said: str) -> list[time]:
    try:
        return [timeinput.parse_time(str(said))]
    except timeinput.AmbiguousTime as which:
        return list(which.options)
    except Exception:
        raise UserError(f"“{said}” is not a time I can read.")


def read_span(start_said: str, end_said: str) -> tuple[time, time]:
    """A start and an end said together ("9 to 5:30", "10 to 2"): of the readings, the one that
    starts and ends on the same day; else each read on its own (read_time)."""
    pairs = [(start, end) for start in _readings(start_said) for end in _readings(end_said) if start < end]
    if len(pairs) == 1:
        return pairs[0]
    daytime = [(start, end) for start, end in pairs if time(7, 0) <= start <= time(22, 0)]
    if len({start for start, _ in daytime}) == 1 and len(daytime) >= 1:
        return min(daytime, key=lambda pair: pair[1])
    return read_time(start_said), read_time(end_said)
