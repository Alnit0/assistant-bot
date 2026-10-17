from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from core import design, timeinput
from core.cards import Button

# ---------------------------------------------------------------------------
# Round 6, the timeline hub (behind DESIGN_ROUND=6; a preview: live stays on
# round 5). Pure: what the hub would show, from the day's items and the time.
#
#   the header      the briefing: the date with the day's dots; one small line
#                   with the weather and what is next; one faint line of what
#                   is done today (name and time); Needs a look only for a
#                   real problem. No other boxes
#   a card an item  in time order: doses, personal routines, events, timed
#                   reminders, to-dos with a planned time, the diary (from
#                   6 pm), what is due all day, and free time of 90 minutes or
#                   more outside events (with how many to-dos would fit). Its
#                   emoji, title and time; a line or two; its own button only
#                   when it can be acted on now
#   doses           a card each at its time; later ones marked planned; one
#                   that moved shows the old time struck through and the new
#                   in bold, with why ("dose 1 was taken at 9:15 am")
#   a long event    at its start; while on, "on now · until 5:00 pm · 2h left";
#                   what falls during it comes after it in time order; free
#                   time is never shown inside it; over, it joins the done line
#   done            leaves its card for the done line. To-dos with no time are
#                   one card at the end. Each card is one message in a fixed
#                   slot, rewritten in place, never posted again
# ---------------------------------------------------------------------------
DOSE, ROUTINE, EVENT, REMINDER, TODO, DIARY, DUE, GAP = "dose", "routine", "event", "reminder", "todo", "diary", "due", "gap"
GAP_FROM = 90  # minutes: a free gap this long or longer gets a card
TODO_SLOT = 45  # minutes a to-do takes in a gap, with its buffer: how many would fit
FREE_ICON = "🌿"
DONE_ICON = "✅"


@dataclass(frozen=True)
class Item:
    kind: str
    icon: str
    title: str
    at: datetime | None = None
    until: datetime | None = None
    details: tuple[str, ...] = ()
    done: bool = False
    done_at: datetime | None = None
    button: str = ""  # its one button, when it can be acted on now (Taken, Done, Write)
    planned: datetime | None = None  # a dose that moved: the time it was planned for
    why: str = ""  # why it moved
    later: bool = False  # a later dose: planned, not due yet
    all_day: bool = False


@dataclass(frozen=True)
class Header:
    day: date
    done: int
    total: int
    weather: str = ""
    problems: tuple[str, ...] = ()


def _t(moment: datetime) -> str:
    return timeinput.format_moment(moment)


def _left(until: datetime, now: datetime) -> str:
    minutes = max(0, int((until - now).total_seconds() // 60))
    hours, rest = divmod(minutes, 60)
    return (f"{hours}h" + (f" {rest}m" if rest else "")) if hours else f"{rest} min"


def is_over(item: Item, now: datetime) -> bool:
    """Done, or an event that has ended."""
    if item.done:
        return True
    return item.kind == EVENT and item.at is not None and (item.until or item.at) <= now


def next_line(items: list[Item], now: datetime) -> str:
    coming = sorted((each for each in items if not is_over(each, now) and each.at is not None and each.at > now and each.kind != GAP), key=lambda each: each.at)
    return f"next: {coming[0].icon} {coming[0].title} {_t(coming[0].at)}" if coming else "nothing more with a time today"


def done_line(items: list[Item], now: datetime) -> str:
    """The faint line of what is done today, in time order: "✅ Pill B 7:05 am · Standup 9:00 am"."""
    finished = []
    for each in items:
        if not is_over(each, now) or each.kind == GAP:
            continue
        when = each.done_at or each.until or each.at
        finished.append((when, f"{each.title} {_t(when)}" if when else each.title))
    finished.sort(key=lambda pair: pair[0] or now)
    return f"{DONE_ICON} " + " · ".join(text for _, text in finished) if finished else ""


def gaps(items: list[Item], now: datetime, end: datetime, todos: int) -> list[Item]:
    """Free time of 90 minutes or more from now to the day's end, never inside an event or anything timed."""
    busy = sorted((each.at, each.until or each.at + timedelta(minutes=15)) for each in items if each.at is not None and not each.all_day and each.kind != GAP and not is_over(each, now) or (each.kind == EVENT and each.at is not None and each.until is not None and each.until > now))
    found, at = [], now
    for begin, finish in busy:
        if begin - at >= timedelta(minutes=GAP_FROM):
            found.append((at, begin))
        at = max(at, finish)
    if end - at >= timedelta(minutes=GAP_FROM):
        found.append((at, end))
    cards = []
    for begin, finish in found:
        minutes = int((finish - begin).total_seconds() // 60)
        fits = min(todos, minutes // TODO_SLOT)
        room = f"room for {fits} to-do{'' if fits == 1 else 's'}" if fits else "no to-dos waiting"
        cards.append(Item(GAP, FREE_ICON, "Free", begin, finish, (f"until {_t(finish)} · {_left(finish, begin)} · {room}",)))
    return cards


def card(item: Item, now: datetime, task_buttons: bool = True) -> tuple:
    """One item's card: a box with its emoji, title and time; a line or two; its button if it can be acted on now."""
    when = "all day" if item.all_day or item.at is None else _t(item.at)
    lines = [design.card_title(f"{item.icon} {item.title} · {when}")]
    status = design.QUIET
    if item.kind == EVENT and item.at is not None and item.until is not None and item.at <= now < item.until:
        lines.append(f"on now · until {design.time(_t(item.until))} · {_left(item.until, now)} left")
        status = design.DUE
    elif item.planned is not None and item.at is not None and item.planned != item.at:
        lines.append(f"{design.change(_t(item.planned), _t(item.at))}")
        if item.why:
            lines.append(design.small(item.why))
    lines += list(item.details)
    if item.later:
        lines.append(design.small("planned"))
    if item.at is not None and item.at <= now and not item.later and item.kind in (DOSE, REMINDER, ROUTINE, TODO):
        status = design.DUE
    if item.kind == GAP:
        status = design.ANY_TIME
    row = (Button(item.button, "preview", "none", item.title[:20], style="success" if item.button in ("Taken", "Done") else "primary"),) if item.button and task_buttons else ()
    children = [design.Text("\n".join(lines))]
    if row:
        children.append(design.Row(row))
    return design.fit((design.Box(status, tuple(children)),))


def header(head: Header, items: list[Item], now: datetime) -> tuple:
    """The briefing: the date with the day's dots, weather and what is next, the done line; Needs a look only for a problem."""
    top = [design.page_title(f"{head.day:%a} {head.day.day} {head.day:%b} {design.progress(head.done, head.total)}")]
    top.append(design.small(" · ".join(each for each in (head.weather, next_line(items, now)) if each)))
    done = done_line(items, now)
    if done:
        top.append(design.small(done))
    boxes = []
    if head.problems:
        boxes.append(design.topic(design.card_title("⚠️ Needs a look"), lines=list(head.problems), status=design.MISSED))
    return design.fit(design.page(top, boxes))


def hub(head: Header, items: list[Item], now: datetime, end: datetime, untimed: list[str] = ()) -> list[tuple]:
    """The whole hub at a moment: the header, then one message an item in time order (free gaps among them),
    then the to-dos with no time in one card."""
    showing = [each for each in items if not is_over(each, now)]
    showing += gaps(items, now, end, len(untimed))
    showing.sort(key=lambda each: (not each.all_day, each.at or now, each.kind == GAP))
    messages = [header(head, items, now), *(card(each, now) for each in showing)]
    if untimed:
        lines = [design.card_title(f"📝 To-dos · {len(untimed)}"), *untimed[:3]]
        if len(untimed) > 3:
            lines.append(design.small(f"+{len(untimed) - 3} more"))
        messages.append(design.fit((design.Box(design.ANY_TIME, (design.Text("\n".join(lines)), design.Row((Button("Done: pick one", "preview", "none", "todos", style="primary"),)))),)))
    return messages


def one_pills_card(doses: list[Item], now: datetime) -> tuple:
    """The variant: one pills card that moves to the next dose's place, for comparison."""
    waiting = [each for each in doses if not each.done]
    done = [each for each in doses if each.done]
    if not waiting:
        return design.fit((design.Box(design.DONE, (design.Text(design.small(f"💊 Pills · all {len(done)} taken")),)),))
    first = waiting[0]
    lines = [design.card_title(f"💊 Pills · {_t(first.at)} · {len(done)} of {len(doses)} taken"), f"next: **{first.title}**"]
    if first.planned is not None and first.planned != first.at:
        lines += [design.change(_t(first.planned), _t(first.at)), design.small(first.why)]
    lines.append(design.small("then " + " · ".join(f"{each.title} {_t(each.at)}" for each in waiting[1:4])) if len(waiting) > 1 else design.small("the last today"))
    row = (Button("Taken", "preview", "none", "pill", style="success"),) if first.at <= now else ()
    children = [design.Text("\n".join(lines)), *([design.Row(row)] if row else [])]
    return design.fit((design.Box(design.DUE if first.at <= now else design.QUIET, tuple(children)),))
