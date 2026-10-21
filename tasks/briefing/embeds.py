from datetime import date, datetime

from core import design, timeinput
from core import day as days
from core.actions import DOSE, EVENT, MISSED, PREPARED, ROUTINE, SKIPPED, TAKEN, TODO, TRACKING, DayItem
from core.cards import MAX_EMBEDS, Card, Embed

# ---------------------------------------------------------------------------
# Round 7 of the hub (DESIGN_ROUND=7, Alex, 21 Oct): the briefing as two
# messages of embeds, each embed's border colour saying what it is. Pure:
# from the day's items as the tasks hand them over (`Entry.day_items`) and
# the time. It knows kinds of things, never whose they are.
#
#   message 1   "🗓️ **Wednesday 21 October**" as its text, then an embed a
#               thing in time order: events (repeating ones blue, the rest
#               yellow; all day, and those coming up, with a title and their
#               days), doses (grey later, red due, green taken with the time,
#               grey skipped or missed), routines (blue; green once done).
#               At the same time: events, then doses, then routines. All-day
#               first, what has no time after the timed things, what is
#               coming up last. Over ten (a message's limit), the tenth is one
#               grey embed of the rest, a line each
#   message 2   no text: the to-dos in one pink embed (☐ open, ☑ done),
#               what is tracked (the diary's streak) in blue, and what the
#               bot prepared in purple: the morning news as one line, "📰 8
#               stories in #news", linking to its first card. None with none
#               of them: it is not sent
# ---------------------------------------------------------------------------
DATE_ICON = "🗓️"
DOSE_ICON = "💊"
ROUTINE_ICON = "🌙"
EVENT_ICON = "🎉"  # an all-day or coming-up event's title
TODOS_TITLE = "☑️ To-dos"
OPEN_BOX, DONE_BOX = "☐", "☑"
TODOS_SHOWN = 15  # to-dos listed in full, then "+N more"
MORE_TITLE = "More today"
NOTHING_ELSE = "Nothing else today."  # message 2 once all of it has gone, rewritten in place
ORDER = {EVENT: 0, DOSE: 1, ROUTINE: 2}  # at the same time


def heading(today: date) -> str:
    return f"{DATE_ICON} **{today:%A} {today.day} {today:%B}**"


def _t(moment: datetime) -> str:
    return timeinput.format_moment(moment)


def _day(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _coming(item: DayItem, today: date) -> bool:
    """An event on a later day (the hub lists it as coming up)."""
    first = item.first_day if item.at is None else days.day_of(item.at)
    return item.kind == EVENT and first is not None and first > today


def _all_day_today(item: DayItem, today: date) -> bool:
    return item.kind == EVENT and item.at is None and not _coming(item, today)


def _sort_key(item: DayItem, today: date) -> tuple:
    """All day first, then by time (events, doses, routines at the same time), what has no time, what is coming up."""
    if _coming(item, today):
        return (3, item.at.timestamp() if item.at is not None else days.start_of(item.first_day).timestamp(), 0, item.text.lower())
    if _all_day_today(item, today):
        return (0, 0.0, 0, item.text.lower())
    if item.at is None:
        return (2, 0.0, ORDER.get(item.kind, 9), item.text.lower())
    return (1, item.at.timestamp(), ORDER.get(item.kind, 9), item.text.lower())


def _days_text(first: date, last: date) -> str:
    return f"{_day(first)} · all day" if last == first else f"{_day(first)} to {_day(last)} · all day"


def event_embed(item: DayItem, today: date) -> Embed:
    """A timed event today on one line ("9:00 am · Work · until 5:00 pm"), blue when it repeats and yellow when
    it is notable; an all-day one or one coming up with its name as the title and its days below, yellow."""
    if _coming(item, today) or item.at is None:
        if item.at is None:
            when = _days_text(item.first_day, item.last_day or item.first_day)
        else:
            when = f"{_day(days.day_of(item.at))} · {_t(item.at)}" + (f" to {_t(item.until)}" if item.until is not None and item.until > item.at else "")
        return Embed(when, f"{EVENT_ICON} {item.text}", design.NOTABLE)
    line = f"{_t(item.at)} · {item.text}" + (f" · until {_t(item.until)}" if item.until is not None and item.until > item.at else "")
    return Embed(line, status=design.ROUTINE if item.repeats else design.NOTABLE)


def dose_state(item: DayItem, now: datetime) -> tuple[str, str]:
    """A dose's square and words, and its status: later (grey), due (red), taken (green, with the time)."""
    if item.state == TAKEN:
        return ("🟩 Taken" + (f" {_t(item.done_at)}" if item.done_at is not None else ""), design.TAKEN)
    if item.state == SKIPPED:
        return ("⏭️ Skipped", design.LATER)
    if item.state == MISSED:
        return ("⬛ Missed", design.LATER)
    if item.at is not None and item.at <= now:
        return ("🟥 Due", design.DUE_NOW)
    return ("⬜ Later", design.LATER)


def dose_embed(item: DayItem, now: datetime) -> Embed:
    said, status = dose_state(item, now)
    when = _t(item.at) if item.at is not None else "any time"
    return Embed(f"{when} · {DOSE_ICON} {item.text} · {said}", status=status)


def routine_embed(item: DayItem) -> Embed:
    when = _t(item.at) if item.at is not None else "any time"
    if item.state == TAKEN:
        return Embed(f"{when} · {ROUTINE_ICON} {item.text} · 🟩 Done", status=design.TAKEN)
    return Embed(f"{when} · {ROUTINE_ICON} {item.text}", status=design.ROUTINE)


def _said(embed: Embed) -> str:
    return "\n".join(each for each in (embed.title, embed.description) if each)


def your_day(items: list[DayItem], today: date, now: datetime) -> Card:
    """Message 1: the date as its text, then an embed a thing of the day in time order."""
    timeline = sorted((each for each in items if each.kind in ORDER), key=lambda each: _sort_key(each, today))
    drawn = []
    for each in timeline:
        if each.kind == EVENT:
            drawn.append(event_embed(each, today))
        elif each.kind == DOSE:
            drawn.append(dose_embed(each, now))
        else:
            drawn.append(routine_embed(each))
    if len(drawn) > MAX_EMBEDS:
        rest = drawn[MAX_EMBEDS - 1:]
        drawn = drawn[:MAX_EMBEDS - 1] + [Embed("\n".join(_said(each).replace("\n", " · ") for each in rest), MORE_TITLE, design.LATER)]
    top = heading(today)
    return Card("\n".join([top, *(_said(each) for each in drawn)]), embeds=tuple(drawn), heading=top)


def everything_else(items: list[DayItem]) -> Card | None:
    """Message 2, with no text of its own: the to-dos in one embed, then what is tracked. None with neither."""
    drawn = []
    todos = [each for each in items if each.kind == TODO]
    if todos:
        lines = [f"{DONE_BOX if each.state == TAKEN else OPEN_BOX} {each.text}" for each in todos[:TODOS_SHOWN]]
        if len(todos) > TODOS_SHOWN:
            lines.append(design.small(design.more_line(len(todos) - TODOS_SHOWN)))
        drawn.append(Embed("\n".join(lines), TODOS_TITLE, design.TODOS))
    drawn += [Embed(f"{each.icon} {each.text}".strip(), status=design.TRACKING) for each in items if each.kind == TRACKING]
    # What the bot prepared (the morning news's line), last and purple, its title the link to where it is
    drawn += [Embed("", each.text, design.PREPARED, url=each.link) for each in items if each.kind == PREPARED]
    if not drawn:
        return None
    return Card("\n".join(_said(each) for each in drawn), embeds=tuple(drawn))


def nothing_else() -> Card:
    """Message 2 when what it held has all gone during the day: it is rewritten, never left saying what is not so."""
    return Card(NOTHING_ELSE, embeds=(Embed(NOTHING_ELSE, status=design.LATER),))
