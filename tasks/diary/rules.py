from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from core import day as days
from core import design
from tasks.diary import mood

# ---------------------------------------------------------------------------
# The diary's rules and words. Pure. No line here ever holds what was written,
# but the one answer that is asked for it (`day_answer` with `words`): what
# can reach a lock screen, a log or the status line names no text.
# ---------------------------------------------------------------------------
TASK = "diary"
ICON = "📔"
TITLE = "Diary"
DAY_ENDS = time(4, 0)  # a diary day runs to 4:00 am: just after midnight is still the evening before
ASK_AT = time(21, 0)  # the evening ask, a schedule like any other ("my schedule" moves it)
ASK = f"{ICON} How was today?"
ASK_WORDS = f"{ICON} How was today? A few words, if you like."


@dataclass(frozen=True)
class Entry:
    id: int
    user_id: int
    day: date
    text: str  # as sent, every message of the day, a blank line between: only ever shown when asked for
    mood_scale: str | None = None
    mood: str | None = None
    mood_before: str | None = None  # what the mood was before the last change, for undo
    scale_before: str | None = None
    notes: int = 0  # how many messages it holds

    @property
    def has_mood(self) -> bool:
        return bool(self.mood)


def diary_day(moment: datetime) -> date:
    """The diary day a moment belongs to: the local day, which starts at 4:00 am."""
    local = days.local_time(moment)
    day = days.day_of(moment)
    return day - timedelta(days=1) if local < DAY_ENDS else day


def streak(written: set[date], today: date) -> int:
    """Days in a row with an entry, back from today (or from yesterday, today not written yet)."""
    day = today if today in written else today - timedelta(days=1)
    count = 0
    while day in written:
        count += 1
        day -= timedelta(days=1)
    return count


def short(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def saved_line(entry: Entry, run: int, added: bool = False) -> str:
    """ "📔 Saved · 😊 Good · streak 4": what was written is never in it."""
    parts = [f"{ICON} {'Added to today' if added else 'Saved'}"]
    if mood.on() and entry.has_mood:
        parts.append(mood.shown(entry.mood_scale, entry.mood))
    if run >= 2:
        parts.append(f"streak {run}")
    return " · ".join(parts)


def mood_line(entry: Entry) -> str:
    """ "📔 Mood · ~~😐 OK~~ → **😊 Good**" """
    now = mood.shown(entry.mood_scale, entry.mood)
    before = mood.shown(entry.scale_before, entry.mood_before)
    return f"{ICON} Mood · {design.change(before, now)}" if before else f"{ICON} Mood · {now}"


def day_answer(entry: Entry | None, day: date, today: date, words: bool) -> str:
    """One day: its mood and how many notes; the words themselves only when asked for."""
    head = f"{ICON} **{_day_name(day, today)}**"
    if entry is None:
        return f"{head} · nothing written"
    said = [head, *([mood.shown(entry.mood_scale, entry.mood)] if mood.on() and entry.has_mood else []), f"{entry.notes} note{'' if entry.notes == 1 else 's'}" if entry.text else "mood only"]
    lines = [" · ".join(said)]
    if words and entry.text:
        lines += [f"> {line}" if line else ">" for line in entry.text.splitlines()]
    elif entry.text:
        lines.append(design.small("say “what did I write …” for the words"))
    return "\n".join(lines)


def span_answer(entries: list[Entry], span: list[date], today: date, label: str) -> str:
    """A week or a month: how many days were written, the moods counted, a day a line (no words)."""
    by_day = {each.day: each for each in entries if each.day in span}
    written = [day for day in span if day in by_day]
    head = f"{ICON} **{label}** · {len(written)} of {len(span)} days"
    if mood.on():
        counts = _counted(list(by_day.values()))
        if counts:
            head += " · " + " · ".join(counts)
    if not written:
        return f"{head}\nNothing written."
    rows = [f"{short(day)} · {mood.emoji(by_day[day].mood_scale, by_day[day].mood) if mood.on() else '✓'}" for day in written]
    return "\n".join([head, *rows, design.small("say “what did I write on …” for a day's words")])


def mood_answer(entries: list[Entry], span: list[date], label: str) -> str:
    """ "how was my mood this month?": the moods counted, then one emoji a day."""
    by_day = {each.day: each for each in entries if each.day in span}
    counts = _counted(list(by_day.values()))
    head = f"{ICON} **{label}** · " + (" · ".join(counts) if counts else "no moods recorded")
    row = "".join(mood.emoji(by_day[day].mood_scale, by_day[day].mood) if day in by_day else mood.NO_MOOD for day in span)
    return "\n".join([head, row])


def week_emoji(entries: list[Entry], span: list[date]) -> str:
    by_day = {each.day: each for each in entries}
    return " ".join(mood.emoji(by_day[day].mood_scale, by_day[day].mood) if day in by_day and mood.on() else ("✓" if day in by_day else mood.NO_MOOD) for day in span)


def _counted(entries: list[Entry]) -> list[str]:
    found: dict[str, int] = {}
    for each in entries:
        if each.has_mood:
            key = mood.emoji(each.mood_scale, each.mood)
            found[key] = found.get(key, 0) + 1
    order = [level.emoji for level in mood.CURRENT.levels]
    return [f"{key} {found[key]}" for key in sorted(found, key=lambda each: order.index(each) if each in order else len(order))]


def _day_name(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return short(day)


def week_of(day: date) -> list[date]:
    """Monday up to the day: the days of the week so far."""
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=ahead) for ahead in range(day.weekday() + 1)]


def month_of(day: date) -> list[date]:
    first = day.replace(day=1)
    return [first + timedelta(days=ahead) for ahead in range((day - first).days + 1)]
