from datetime import date, datetime

from core import day as days
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


def info(item: Item) -> str:
    """A line only worth knowing (a fix shipped, closing Mon): its bug and its words, no warning."""
    return f"{f'{item.bug} · ' if item.bug else ''}{item.what}"


def held(line: str, times: int = 1) -> str:
    """One alert quiet hours held back: the neutral line it was posted as, and
    how often it was asked for if more than once."""
    return line if times <= 1 else f"{line} · {times} times"


def held_note(hours: str) -> str:
    return f"quiet hours ({hours}): posted without a sound"


def _title(section: Section) -> str:
    """The box's name: the task's title, or the summary's own heading for a box placed low."""
    return section.summary.heading if section.summary is not None and section.summary.heading else section.title


def _low(section: Section) -> bool:
    return section.summary is not None and section.summary.low


def low_last(sections: list[Section]) -> list[Section]:
    """Those placed low (`Summary.low`: birthdays coming up) after everything else, each keeping its order."""
    return [*(each for each in sections if not _low(each)), *(each for each in sections if _low(each))]


def _name(section: Section) -> str:
    glance = section.summary.glance if section.summary is not None else ""
    return f"{section.icon} **{_title(section)}**" + (f" · {glance}" if glance else "")


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


# A part of the day asked about ("what's on tonight?"), as local hours [from, until), and how it is said.
# NEXT is "what's next?": the first thing still to come. Claude names the part; the code does the rest
MORNING, AFTERNOON, EVENING, TONIGHT, NEXT = "morning", "afternoon", "evening", "tonight", "next"
PARTS = {MORNING: (0, 12, "this morning"), AFTERNOON: (12, 17, "this afternoon"), EVENING: (17, 24, "this evening"), TONIGHT: (17, 24, "tonight")}


def _things(sections: list[Section]) -> list[tuple[str, datetime | None]]:
    """Each thing still to do, (its line under its task's icon, when it is due or None), in time
    order across tasks: what has a time by its time, then what has none, each task's as it gave them."""
    found = []
    for each in sections:
        if each.summary is None:
            continue
        moments = each.summary.left_at if len(each.summary.left_at) == len(each.summary.left) else (None,) * len(each.summary.left)
        found += [(f"{each.icon} {line}", moment) for line, moment in zip(each.summary.left, moments)]
    timed = sorted((pair for pair in found if pair[1] is not None), key=lambda pair: pair[1])
    return [*timed, *(pair for pair in found if pair[1] is None)]


def left(sections: list[Section], part: str = "", now: datetime | None = None) -> str:
    """ "what's left today?": the day's dots and count, then each thing still to
    do in its task's own words, under the task's icon, in time order. For a part
    of the day ("tonight") only what is due in it, and what has no time in one
    small line; "next" is the first thing still to come. Every number is a
    task's; with nothing to count it says there is nothing on."""
    counted = [(each.summary.done or 0, each.summary.total) for each in sections if each.summary is not None and each.summary.total]
    things = _things(sections)
    if not counted and not things:
        return NOTHING
    so_far = f" · {design.progress(sum(done for done, _ in counted), sum(total for _, total in counted))}" if counted else ""
    untimed = [line for line, moment in things if moment is None]
    if part == NEXT:
        coming = [(line, moment) for line, moment in things if moment is not None and (now is None or moment >= now)]
        if not coming:
            return f"{ICON} **Nothing else at a time today**{so_far}" + (f"\n-# {len(untimed)} with no time" if untimed else "")
        rest = len(things) - 1
        return "\n".join([f"{ICON} **Next**{so_far}", coming[0][0], *([f"-# then {rest} more today"] if rest > 0 else [])])
    if part in PARTS:
        start, end, said = PARTS[part]
        lines = [line for line, moment in things if moment is not None and start <= days.local_time(moment).hour < end]
        title = f"Left {said}"
        if not lines:
            return f"{ICON} **Nothing at a time {said}**{so_far}" + (f"\n-# {len(untimed)} with no time, any time today" if untimed else "")
        small = [f"-# and {len(untimed)} with no time, any time today"] if untimed else []
    else:
        lines, title, small = [line for line, _ in things], "Left today", []
        if not lines:
            return f"{ICON} **Nothing left today**{so_far}"
    shown = lines[:MAX_LEFT] + ([f"…and {len(lines) - MAX_LEFT} more"] if len(lines) > MAX_LEFT else [])
    return "\n".join([f"{ICON} **{title}**{so_far}", *shown, *small])


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


def text(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = (), info: tuple[str, ...] = ()) -> str:
    """The briefing as a plain message (the old look, and what is logged).
    `so_far` is the day's progress (`progress`), at the top. `info`: lines only
    worth knowing, small and last in Needs a look, or on their own one small line."""
    title, under = _top(day, so_far)
    lines = [f"## {title}", *under]
    if problems:
        lines += ["", NEEDS, *problems, *(design.small(each) for each in info)]
    elif info:
        lines += ["", design.small(" · ".join(info))]
    if news:
        lines += ["", NEWS, *news]
    if held_back:
        lines += ["", HELD, *held_back, *([design.small(held_note(hours))] if hours else [])]
    for section in low_last(sections):
        lines += ["", _name(section), *_lines(section)]
    if spend:
        lines += ["", spend]
    if notes:
        lines += ["", *worth_knowing(notes)]
    lines += ["", design.small(FOOT)]
    return "\n".join(lines)


def _layout_r1(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = (), info: tuple[str, ...] = ()) -> tuple:
    """Round 1 (kept as it was built): a standing message, a box a task in the
    colour of its status, and no buttons. What needs a look is a box of its own
    on top, then what was held back overnight."""
    boxes = []
    if problems:
        boxes.append(design.item(design.MISSED, NEEDS, *problems, *(design.small(each) for each in info)))
    elif info:
        boxes.append(design.item(design.QUIET, design.small(" · ".join(info))))
    if news:
        boxes.append(design.item(design.QUIET, NEWS, *news))
    if held_back:
        boxes.append(design.item(design.QUIET, HELD, *held_back, *([design.small(held_note(hours))] if hours else [])))
    boxes += [
        design.item(section.summary.status if section.summary is not None and section.summary.status else design.QUIET, _name(section), *_lines(section))
        for section in low_last(sections)
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
    return low_last([*(each for each in sections if not _counts(each)), *(each for each in sections if _counts(each))])


def _box(section: Section) -> design.Box:
    """One task's box: its card title (with its dots when it counts anything),
    then what it says, its hint and the line about the day before, small."""
    said = section.summary
    if said is None:
        return design.topic(design.card_title(f"{section.icon} {section.title}"), lines=[design.small(f"⚠️ {section.problem or 'couldn’t be read'}")], status=design.QUIET)
    heading = design.card_title(f"{section.icon} {_title(section)}", said.done, said.total)
    lines = [*([said.glance] if said.glance and not said.total else []), *said.lines, *(design.small(line) for line in (said.hint, said.before) if line)]
    return design.topic(heading, lines=lines, status=said.status or design.QUIET)


OVERVIEW = "🗓️ The day"


def _overview_box(sections: list[Section], aside: str = "") -> design.Box | None:
    """Round 5: one small box, a line a task that has a card of its own in the hub, what the
    day holds for it and not how far it has got. In the order each task says it comes, the same every day."""
    from core import actions

    # Question 72: the same order every day, each task's own place (Entry.place), never the ranking's
    loaded = [entry.name for entry in actions.in_place()]
    sections = sorted(sections, key=lambda each: loaded.index(each.task) if each.task in loaded else len(loaded))
    lines = [f"{each.icon} **{each.title}** · {each.summary.overview}" for each in sections if each.summary is not None and each.summary.overview]
    if aside:
        lines.append(design.small(aside))  # only worth knowing, with nothing wrong: one small line here
    if not lines:
        return None
    return design.topic(design.card_title(OVERVIEW), lines=lines, status=design.QUIET)


def _layout_r5(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = (), info: tuple[str, ...] = ()) -> tuple:
    """Round 5 (Alex, 15 Oct: "a little bit of overlap with pills and calendar"): the briefing is the
    morning overview. Its page title is the date with the day's dots, so "Today" is only ever the
    Today card; what needs a look and the weather stay boxes; every task with a card of its own is
    one line in one small overview box, with no progress (its card has it); no footer (the how-to
    is in help)."""
    boxes = []
    if problems:
        entries = [design.Entry(each, design.MISSED) for each in problems] + [design.Entry(design.small(each), design.QUIET) for each in info]
        boxes.append(design.topic(design.card_title(NEEDS.replace("**", "")), entries, status=design.MISSED))
    if news:
        boxes.append(design.topic(design.card_title(NEWS.replace("**", "")), [design.Entry(each, design.QUIET) for each in news], status=design.QUIET))
    if held_back:
        boxes.append(design.topic(design.card_title(HELD.replace("**", "")), lines=[*held_back, *([design.small(held_note(hours))] if hours else [])], status=design.QUIET))
    boxes += [_box(section) for section in sections if (section.summary is None or not section.summary.overview) and not _low(section)]
    overview = _overview_box(sections, "" if problems else " · ".join(info))
    if overview is not None:
        boxes.append(overview)
    boxes += [_box(section) for section in sections if _low(section)]  # below the day's things
    title = f"{ICON} {date_line(day)}" + (f" {so_far[0]}" if so_far else "")
    foot = [*([spend] if spend else []), *worth_knowing(notes)]
    return design.page([design.page_title(title)], boxes, foot)


def layout(sections: list[Section], day: date, problems: tuple[str, ...] = (), held_back: tuple[str, ...] = (), hours: str = "", notes: tuple[str, ...] = (), spend: str = "", so_far: tuple[str, ...] = (), news: tuple[str, ...] = (), info: tuple[str, ...] = ()) -> tuple:
    """The briefing as a page (docs/DESIGN.md, round 3): the page title with the
    day's progress, then a box a topic: what needs a look (only when something
    is wrong, red, a rule between problems), what was held back overnight,
    then each task's box in page order (`in_page_order`). Under the boxes the
    spend line behind a spoiler, what is worth knowing, and the foot. No
    buttons: things are ticked off on their own message.

    In round 1 of the design (DESIGN_ROUND=1) it is `_layout_r1`."""
    if design.current() < 3:
        return _layout_r1(sections, day, problems, held_back, hours, notes, spend, so_far, news, info)
    if design.current() >= 5:
        return _layout_r5(sections, day, problems, held_back, hours, notes, spend, so_far, news, info)
    boxes = []
    if problems:
        entries = [design.Entry(each, design.MISSED) for each in problems] + [design.Entry(design.small(each), design.QUIET) for each in info]
        boxes.append(design.topic(design.card_title(NEEDS.replace("**", "")), entries, status=design.MISSED))
    elif info:
        boxes.append(design.topic(design.card_title(NEEDS.replace("**", "")), lines=[design.small(" · ".join(info))], status=design.QUIET))
    if news:
        # What changed overnight, for this morning only (core/whatsnew.py): a rule between items
        boxes.append(design.topic(design.card_title(NEWS.replace("**", "")), [design.Entry(each, design.QUIET) for each in news], status=design.QUIET))
    if held_back:
        boxes.append(design.topic(design.card_title(HELD.replace("**", "")), lines=[*held_back, *([design.small(held_note(hours))] if hours else [])], status=design.QUIET))
    boxes += [_box(section) for section in in_page_order(sections)]
    title, under = _top(day, so_far)
    foot = [*([spend] if spend else []), *worth_knowing(notes), design.small(FOOT)]
    return design.page([design.page_title(title), *under], boxes, foot)
