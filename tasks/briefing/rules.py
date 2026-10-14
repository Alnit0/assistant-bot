from datetime import date

from core import design
from core.attention import Item
from core.summaries import Section

# ---------------------------------------------------------------------------
# The briefing's words and how it is drawn. Pure. It holds no section's own
# words: each is its task's (core/summaries.py), and the briefing only puts
# them in order under one heading.
#
# The order is not the briefing's either: it is the one ranking's
# (core/attention.py), the same the status line shows the top of. What is
# wrong and needs me (level 1) is a box on top; then what quiet hours held
# back overnight, if anything; then a section a task, the task whose item
# stands highest first, and those with nothing ranked after, as they were.
# ---------------------------------------------------------------------------
TASK = "briefing"
ICON = "☀️"
HEADING = f"{ICON} Today"
NOTHING = f"{ICON} Nothing on today."
UP_TO_DATE = f"{ICON} The briefing above is up to date."
NEEDS = "⚠️ **Needs a look**"
NEWS = "🆕 **What's new**"
HELD = "🌙 **Held back overnight**"
FOOT = "always up to date · tick things off on their own message · say “my schedule” to change when this is posted"


def date_line(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B}"


def notice(at: str) -> str:
    """The one line a briefing that notifies is first posted as: what the phone
    shows. It names nothing of mine."""
    return f"{ICON} Morning briefing · {at}"


def ordered(sections: list[Section], order: list[str]) -> list[Section]:
    """The sections in the ranking's order. `order` is the tasks of the ranked
    items, the highest first: a task comes where its best item stands, and one
    with nothing ranked comes after those, in the order it was given."""
    place: dict[str, int] = {}
    for at, name in enumerate(order):
        place.setdefault(name, at)
    return sorted(sections, key=lambda section: place.get(section.task, len(order)))


def problem(item: Item) -> str:
    """A level 1 item as the briefing says it: its icon, its bug if one was
    filed, and what is wrong in words."""
    return f"{item.icon or '⚠️'} {f'{item.bug} · ' if item.bug else ''}{item.what}"


def held(line: str, times: int = 1) -> str:
    """One alert quiet hours held back: the neutral line it was posted as, and
    how often it was asked for if more than once."""
    return line if times <= 1 else f"{line} · {times} times"


def held_note(hours: str) -> str:
    return f"quiet hours ({hours}): posted without a sound"


def _name(section: Section) -> str:
    glance = section.summary.glance if section.summary is not None else ""
    return f"{section.icon} **{section.title}**" + (f" · {glance}" if glance else "")


def _lines(section: Section) -> list[str]:
    """A section's lines under its name: what it says, then its hint and the
    line about the day before, both small."""
    if section.summary is None:
        return [design.small(f"⚠️ {section.problem or 'couldn’t be read'}")]
    said = section.summary
    return [*said.lines, *(design.small(line) for line in (said.hint, said.before) if line)]


def progress(sections: list[Section]) -> tuple[str, ...]:
    """The day so far, from what each task says is done out of what it has: the
    whole day as dots and a count ("●●●●●○○ 5/7", core/design.py), and one
    small line a task ("💊 2/3 · 🏋️ 0/1"), in the order the tasks were given.
    Nothing when no task has anything to count. It knows no task: the numbers
    are theirs."""
    counted = [(each.icon, each.summary.done or 0, each.summary.total) for each in sections if each.summary is not None and each.summary.total]
    if not counted:
        return ()
    done, total = sum(each[1] for each in counted), sum(each[2] for each in counted)
    return (design.progress(done, total), design.small(" · ".join(f"{icon} {some}/{of}" for icon, some, of in counted)))


def _top(day: date, so_far: tuple[str, ...]) -> tuple[str, list[str]]:
    """The title and the lines under it, with the day's progress where the design
    puts it: the total in the title or on a line of its own under the date
    (`design.DAY_TOTAL_IN_TITLE`), then the small line a task."""
    if not so_far:
        return HEADING, [design.small(date_line(day))]
    total, tasks = so_far
    if design.DAY_TOTAL_IN_TITLE:
        return f"{HEADING} {total}", [design.small(date_line(day)), tasks]
    return HEADING, [design.small(date_line(day)), total, tasks]


# --- questions about the day, answered in words from a template (DAY_QUESTIONS) ---------------
YESTERDAY, WEEK = "yesterday", "week"
MAX_LEFT = 8  # lines of what is left; the rest are counted
NOTHING_YESTERDAY = f"{ICON} Nothing was on yesterday."
NOTHING_THIS_WEEK = f"{ICON} Nothing was on this week."


def short_date(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def left(sections: list[Section]) -> str:
    """ "what's left today?": the day's dots and count, then each thing still to
    do in its task's own words, under the task's icon. Every number is a
    task's; with nothing to count it says there is nothing on."""
    counted = [(each.summary.done or 0, each.summary.total) for each in sections if each.summary is not None and each.summary.total]
    if not counted:
        return NOTHING
    so_far = design.progress(sum(done for done, _ in counted), sum(total for _, total in counted))
    lines = [f"{each.icon} {line}" for each in sections if each.summary is not None for line in each.summary.left]
    if not lines:
        return f"{ICON} **Nothing left today** · {so_far}"
    shown = lines[:MAX_LEFT] + ([f"…and {len(lines) - MAX_LEFT} more"] if len(lines) > MAX_LEFT else [])
    return "\n".join([f"{ICON} **Left today** · {so_far}", *shown])


def yesterday(day: date, tallies: list, sections: list[Section]) -> str:
    """ "how did I go yesterday?": yesterday's dots and count from each task's
    record of that day (`tallies`), and the line each task says about the day
    before in today's summary (`sections`)."""
    lines = [f"{each.icon} {each.summary.before}" for each in sections if each.summary is not None and each.summary.before]
    if not tallies and not lines:
        return NOTHING_YESTERDAY
    head = f"{ICON} **Yesterday** · {short_date(day)}"
    if tallies:
        head += f" · {design.progress(sum(each.done for each in tallies), sum(each.total for each in tallies))}"
    return "\n".join([head, *(lines or [f"{each.icon} {each.done}/{each.total}" for each in tallies])])


def week(days: list[tuple[date, list]], today: date) -> str:
    """ "how is this week going?": Monday to today, from each task's record of
    each day: the week's dots and count, one small line a task, and a line a
    day that had anything in it."""
    by_task: dict[str, list[int]] = {}
    lines = []
    for day, tallies in days:
        if not tallies:
            continue
        for each in tallies:
            sums = by_task.setdefault(each.icon, [0, 0])
            sums[0], sums[1] = sums[0] + each.done, sums[1] + each.total
        so_far = design.progress(sum(each.done for each in tallies), sum(each.total for each in tallies))
        lines.append(f"`{day:%a} {day.day}` {so_far}" + (" · today" if day == today else ""))
    if not lines:
        return NOTHING_THIS_WEEK
    first = days[0][0]
    span = short_date(today) if first == today else f"{first:%a} {first.day} – {short_date(today)}"
    whole = design.progress(sum(done for done, _ in by_task.values()), sum(total for _, total in by_task.values()))
    tasks = design.small(" · ".join(f"{icon} {done}/{total}" for icon, (done, total) in by_task.items()))
    return "\n".join([f"{ICON} **This week** · {span} · {whole}", tasks, *lines])


MAX_NOTES = 3
SPEND_ICON = "💸"


def spend_line(you: str, testing: str, total: str) -> str:
    """Yesterday's Claude spend in one line, the amounts behind a spoiler: "you" is
    the bot's own use, "testing" the self-tests. The amounts come written (NZ$)."""
    return f"{SPEND_ICON} Yesterday: " + design.hidden(f"{total} · you {you} · testing {testing}")


def worth_knowing(notes: tuple[str, ...]) -> list[str]:
    """What is worth knowing and needs nothing done, each in one small line: the
    latest three, and the rest counted."""
    shown = [design.small(f"🗒️ {note}") for note in notes[-MAX_NOTES:]]
    return [*([design.small(f"🗒️ …and {len(notes) - MAX_NOTES} more before")] if len(notes) > MAX_NOTES else []), *shown]


def text(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = ()) -> str:
    """The briefing as a plain message (the old look, and what is logged).
    `so_far` is the day's progress (`progress`), at the top."""
    title, under = _top(day, so_far)
    lines = [f"## {title}", *under]
    if problems:
        lines += ["", NEEDS, *problems]
    if news:
        lines += ["", NEWS, *news]
    if held_back:
        lines += ["", HELD, *held_back, *([design.small(held_note(hours))] if hours else [])]
    for section in sections:
        lines += ["", _name(section), *_lines(section)]
    if spend:
        lines += ["", spend]
    if notes:
        lines += ["", *worth_knowing(notes)]
    lines += ["", design.small(FOOT)]
    return "\n".join(lines)


def _layout_r1(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = ()) -> tuple:
    """Round 1 (kept as it was built): a standing message, a box a task in the
    colour of its status, and no buttons. What needs a look is a box of its own
    on top, then what was held back overnight."""
    boxes = []
    if problems:
        boxes.append(design.item(design.MISSED, NEEDS, *problems))
    if news:
        boxes.append(design.item(design.QUIET, NEWS, *news))
    if held_back:
        boxes.append(design.item(design.QUIET, HELD, *held_back, *([design.small(held_note(hours))] if hours else [])))
    boxes += [
        design.item(section.summary.status if section.summary is not None and section.summary.status else design.QUIET, _name(section), *_lines(section))
        for section in sections
    ]
    title, under = _top(day, so_far)
    pieces = design.standing(title, "", boxes, under=tuple(under))
    under = [*([spend] if spend else []), *worth_knowing(notes)]
    return (*pieces, *([design.Text("\n".join(under))] if under else []), design.Text(design.small(FOOT)))


def _counts(section: Section) -> bool:
    return section.summary is not None and bool(section.summary.total)


def in_page_order(sections: list[Section]) -> list[Section]:
    """The order of the boxes on the page: first what sets the scene and counts
    nothing (the weather), then the day's things in the ranking's order, which
    puts the next timed thing first. Each keeps the order it was given in."""
    return [*(each for each in sections if not _counts(each)), *(each for each in sections if _counts(each))]


def _box(section: Section) -> design.Box:
    """One task's box: its card title (with its dots when it counts anything),
    then what it says, its hint and the line about the day before, small."""
    said = section.summary
    if said is None:
        return design.topic(design.card_title(f"{section.icon} {section.title}"), lines=[design.small(f"⚠️ {section.problem or 'couldn’t be read'}")], status=design.QUIET)
    heading = design.card_title(f"{section.icon} {section.title}", said.done, said.total)
    lines = [*([said.glance] if said.glance and not said.total else []), *said.lines, *(design.small(line) for line in (said.hint, said.before) if line)]
    return design.topic(heading, lines=lines, status=said.status or design.QUIET)


def layout(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = ()) -> tuple:
    """The briefing as a page (docs/DESIGN.md, round 3): the page title with the
    day's progress, then a box a topic: what needs a look (only when something
    is wrong, red, a rule between problems), what was held back overnight,
    then each task's box in page order (`in_page_order`). Under the boxes the
    spend line behind a spoiler, what is worth knowing, and the foot. No
    buttons: things are ticked off on their own message.

    In round 1 of the design (DESIGN_ROUND=1) it is `_layout_r1`."""
    if design.current() < 3:
        return _layout_r1(sections, day, problems, held_back, hours, notes, spend, so_far, news)
    boxes = []
    if problems:
        boxes.append(design.topic(design.card_title(NEEDS.replace("**", "")), [design.Entry(each, design.MISSED) for each in problems], status=design.MISSED))
    if news:
        # What changed overnight, for this morning only (core/whatsnew.py): a rule between items
        boxes.append(design.topic(design.card_title(NEWS.replace("**", "")), [design.Entry(each, design.QUIET) for each in news], status=design.QUIET))
    if held_back:
        boxes.append(design.topic(design.card_title(HELD.replace("**", "")), lines=[*held_back, *([design.small(held_note(hours))] if hours else [])], status=design.QUIET))
    boxes += [_box(section) for section in in_page_order(sections)]
    title, under = _top(day, so_far)
    foot = [*([spend] if spend else []), *worth_knowing(notes), design.small(FOOT)]
    return design.page([design.page_title(title), *under], boxes, foot)
