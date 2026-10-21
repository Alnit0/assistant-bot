"""How a card looks (docs/DESIGN.md), in one place.

Every colour and every spacing value the bot's Components V2 cards use is in
the first block of this file: a change after a look on the phone is an edit
here and nowhere else. `dev mock` draws its sketches with the same values.

Pure: plain records in, plain records out. A task says what a card holds
(`item`, `standing`, `decision`); core/cards.py turns the records into a
message. Nothing here is used unless CARDS_V2 is on.
"""
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The values. Edit here.
# ---------------------------------------------------------------------------
# Colours, by name (also the names a sketch in docs/mockups/ uses)
COLOURS = {
    "amber": 0xFAA61A,
    "blue": 0x3498DB,
    "green": 0x57F287,
    "red": 0xED4245,
    "grey": 0x95A5A6,
    "blurple": 0x5865F2,
    "yellow": 0xFEE75C,
}

# A box's status, and the colour each one takes
DUE = "due"  # something to do now or next, with a time
ANY_TIME = "any_time"  # to do today, with no time it is due at
DONE = "done"  # finished
MISSED = "missed"  # its time passed, nothing was done, and nothing is left today
QUIET = "quiet"  # paused, to come, skipped, snoozed: nothing to do now
DECISION = "decision"  # a confirm card, a question
RISKY = "risky"  # a card that asks first because something is risky
DESTRUCTIVE = "destructive"  # can't be undone
ACCENTS = {
    DUE: "amber",
    ANY_TIME: "blue",
    DONE: "green",
    MISSED: "red",
    QUIET: "grey",
    DECISION: "blurple",
    RISKY: "amber",
    DESTRUCTIVE: "red",
}

# The most urgent first: a box with several things in it takes the colour of the
# first of these that is among them. Red for a miss only when nothing is left to do
URGENCY = (DESTRUCTIVE, RISKY, DUE, ANY_TIME, MISSED, DECISION, DONE, QUIET)

# Text: the type scale of round 3, the same on every card
PAGE_TITLE = "## "  # once a message
CARD_TITLE = "### "  # once a box, with the topic's progress
HEADING = PAGE_TITLE  # the first line of a standing message
CARD_HEADING = PAGE_TITLE  # the first line of a card that asks for a decision
SMALL = "-# "  # detail that is read second
WARNING = "⚠️"
ARROW = "→"  # between the old value and the new one of a change

# Progress: one dot a thing to do, solid for done and hollow for not done, then the count.
# "●●●●●○○ 5/7". Over MAX_DOTS things the dots are scaled to that many; the count stays exact
DOT_DONE = "●"
DOT_LEFT = "○"
MAX_DOTS = 10
# Where the day's total goes in the briefing: True, in its title ("## ☀️ Today ●●●○○ 3/5");
# False, a line of ordinary text under the date
DAY_TOTAL_IN_TITLE = True

# Separators: whether one draws a line, and whether it leaves a large gap
SEPARATOR_LINE = True
SEPARATOR_LARGE = False
# The one between sections of a standing message (today's items, then Paused)
SECTION_LINE = True
SECTION_LARGE = True

# Discord's limits for one message
MAX_COMPONENTS = 40  # every text, box, separator, row and button counts
MAX_TEXT = 4000  # all its text together
MAX_BUTTONS_IN_ROW = 5
# What each piece costs, for code that has to fit a message
BOX_COST = 2  # a box and its text
ROW_COST = 1  # a row, before its buttons


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Text:
    content: str


@dataclass(frozen=True)
class Separator:
    line: bool = SEPARATOR_LINE
    large: bool = SEPARATOR_LARGE


@dataclass(frozen=True)
class Row:
    """A row of buttons (core/cards.py `Button`s)."""

    buttons: tuple


@dataclass(frozen=True)
class Box:
    """One item, with the accent colour of its status."""

    status: str
    children: tuple  # Text, Separator, Row


def colour(status: str) -> int:
    """The accent colour of a status, as a number."""
    return COLOURS[ACCENTS[status]]


# Round 7 (DESIGN_ROUND=7, Alex, 21 Oct): the briefing as two messages of embeds, each embed's border saying
# what it is. A task still gives a status, never a colour: these are the hub's statuses for an embed
ROUTINE = "routine"  # comes round every day or week (work, a personal routine): blue
TAKEN = "taken"  # done or taken: green
DUE_NOW = "due_now"  # due, needs a look now: red
NOTABLE = "notable"  # an event worth noticing (one coming up, or all day): yellow
LATER = "later"  # later, not yet relevant: grey
PREPARED = "prepared"  # something the bot prepared for you: purple
TODOS = "todos"  # your to-dos: pink
TRACKING = "tracking"  # what you track (the diary): blue
EMBED_COLOURS = {
    ROUTINE: 0x5865F2, TAKEN: 0x57F287, DUE_NOW: 0xED4245, NOTABLE: 0xFEE75C, LATER: 0x4E5058,
    PREPARED: 0x9B59B6, TODOS: 0xEB459E, TRACKING: 0x5865F2,
}


def embed_colour(status: str) -> int:
    """An embed's border colour, as a number: a round 7 status, else a box's accent."""
    return EMBED_COLOURS[status] if status in EMBED_COLOURS else colour(status)


def section() -> Separator:
    """The separator between sections of a standing message."""
    return Separator(SECTION_LINE, SECTION_LARGE)


def hidden(text: str) -> str:
    """Words shown only when tapped (a spoiler): for an amount of money in a message others may glance at."""
    return f"||{text}||"


def share(done: int, total: int, out_of: int) -> int:
    """`done` of `total` as a part of `out_of`, to the nearest whole. Only a day with
    everything done reaches the top, and only one with nothing done is at 0."""
    if total <= 0 or done <= 0:
        return 0
    if done >= total:
        return out_of
    return min(out_of - 1, max(1, (2 * done * out_of + total) // (2 * total)))


def dots(done: int, total: int) -> str:
    """One dot a thing, solid for done: "●●○". More than MAX_DOTS things are shown as
    that many dots, scaled. The characters are the values at the top of this file."""
    done = max(0, min(done, total))
    cells = min(total, MAX_DOTS)
    filled = done if total <= MAX_DOTS else share(done, total, MAX_DOTS)
    return DOT_DONE * filled + DOT_LEFT * (cells - filled)


def progress(done: int, total: int) -> str:
    """How far along, as dots and the exact count: "●●●●●○○ 5/7". Never a percentage."""
    return f"{dots(done, total)} {done}/{total}"


def small(text: str) -> str:
    """A line of small text. One that is small already is left as it is."""
    return text if text.startswith(SMALL) else f"{SMALL}{text}"


def warning(text: str) -> str:
    """A warning: a ⚠️ line inside a box, never a colour of its own."""
    return text if text.startswith(WARNING) else f"{WARNING} {text}"


# ---------------------------------------------------------------------------
# The type scale (round 3): a message is read like a page
# ---------------------------------------------------------------------------
def page_title(text: str) -> str:
    """The page title, `## `: once a message, its first line."""
    return f"{PAGE_TITLE}{text}"


def card_title(text: str, done: int | None = None, total: int | None = None) -> str:
    """A box's title, `### `, with the topic's progress when it counts anything:
    "### 💊 Pills ●●○○○○ 2/6"."""
    return f"{CARD_TITLE}{text}" + (f" {progress(done or 0, total)}" if total else "")


def name(text: str) -> str:
    """An item's name, in bold."""
    return f"**{text}**"


def time(shown: str) -> str:
    """A time as it is shown: bold, never code. `shown` is already written
    ("8:00 am", core/timeinput.py)."""
    return f"**{shown}**"


def relative(moment) -> str:
    """A moment as Discord says it from now ("in 2 hours"), kept current by Discord itself."""
    return f"<t:{int(moment.timestamp())}:R>"


def when(shown: str, moment=None, now=None) -> str:
    """A time in bold, and how far off it is when that is still to come:
    "**5:00 pm** · in 2 hours"."""
    if moment is None or now is None or moment <= now:
        return time(shown)
    return f"{time(shown)} · {relative(moment)}"


def change(old: str, new: str) -> str:
    """A change: the old value struck through, the new one bold. "~~8:00 pm~~ → **9:00 pm**"."""
    return f"~~{old}~~ {ARROW} **{new}**"


def quote(text: str) -> str:
    """What I said, quoted on the card that answers it."""
    return "\n".join(f"> {line}" for line in text.splitlines() or [text])


_CODE = re.compile(r"\*\*`([^`\n]+)`\*\*|`([^`\n]+)`")
_FLAGS = ("❓", "❔")


def bold_times(text: str) -> str:
    """Times and values that older words write as code, in bold instead: the
    type scale has no code. Words with nothing in code are left as they are."""
    return _CODE.sub(lambda found: f"**{found[1] or found[2]}**", text)


def _plain_value(text: str) -> str:
    return text.replace("`", "").replace("**", "").strip()


def changed(line: str) -> str:
    """A line that says a change as `field · old → new` (the one format every
    card uses), drawn as `field · ~~old~~ → **new**`. What follows the new value
    after " · ", and a ❓ that marks a guess, stay as they were. A line with no
    arrow is returned as it is."""
    marker = f" {ARROW} "
    if marker not in line or line.startswith(SMALL):
        return line
    left, right = line.split(marker, 1)
    field, _, old = left.rpartition(" · ")
    if not field:
        return line  # "**Iron** → removed": a thing, not a field that changes
    prefix = f"{field} · "
    new, dot, rest = right.partition(" · ")
    flag = ""
    for mark in _FLAGS:
        if new.rstrip().endswith(mark):
            new, flag = new.rstrip().removesuffix(mark), f" {mark}"
    old, new = _plain_value(old), _plain_value(new)
    if not old or not new:
        return line
    return f"{prefix}{change(old, new)}{flag}" + (f" · {rest}" if dot else "")


def urgent(statuses) -> str:
    """The most urgent of some statuses: the colour of a box that holds them all."""
    found = set(statuses)
    return next((status for status in URGENCY if status in found), QUIET)


@dataclass(frozen=True)
class Entry:
    """One item in a topic's box: its words (name first), its status, and the
    buttons for what can be done to it now."""

    text: str
    status: str = QUIET
    row: tuple = ()


# ---------------------------------------------------------------------------
# Counting, for the limits
# ---------------------------------------------------------------------------
def count(pieces) -> int:
    """How many components Discord would count."""
    total = 0
    for piece in pieces:
        total += 1
        if isinstance(piece, Row):
            total += len(piece.buttons)
        elif isinstance(piece, Box):
            total += count(piece.children)
        elif not isinstance(piece, (Text, Separator)):
            total += 1  # a dropdown: its row and itself
    return total


def length(pieces) -> int:
    """How many characters of text there are."""
    total = 0
    for piece in pieces:
        if isinstance(piece, Text):
            total += len(piece.content)
        elif isinstance(piece, Box):
            total += length(piece.children)
    return total


def buttons(pieces) -> list:
    """Every button of a layout, in order."""
    found: list = []
    for piece in pieces:
        if isinstance(piece, Row):
            found += list(piece.buttons)
        elif isinstance(piece, Box):
            found += buttons(piece.children)
    return found


def texts(pieces) -> list[str]:
    """Every text of a layout, in order."""
    found: list[str] = []
    for piece in pieces:
        if isinstance(piece, Text):
            found.append(piece.content)
        elif isinstance(piece, Box):
            found += texts(piece.children)
    return found


def problem(pieces) -> str:
    """What Discord would refuse a layout for, or "" if it fits."""
    if not pieces:
        return "a layout with nothing in it"
    if count(pieces) > MAX_COMPONENTS:
        return f"{count(pieces)} components, and one message takes {MAX_COMPONENTS}"
    if length(pieces) > MAX_TEXT:
        return f"{length(pieces)} characters of text, and one message takes {MAX_TEXT}"
    for piece in pieces:
        if isinstance(piece, Box):
            if not piece.children:
                return "a box with nothing in it"
            if piece.status not in ACCENTS:
                return f"“{piece.status}” is not a status"
            if any(isinstance(child, Box) for child in piece.children):
                return "a box inside a box"
            inner = problem(piece.children)
            if inner:
                return inner
        elif isinstance(piece, Row) and not 1 <= len(piece.buttons) <= MAX_BUTTONS_IN_ROW:
            return f"a row of {len(piece.buttons)} buttons, and a row takes 1 to {MAX_BUTTONS_IN_ROW}"
        elif isinstance(piece, Text) and not piece.content.strip():
            return "a text with nothing in it"
    return ""


# ---------------------------------------------------------------------------
# Making a layout fit: a card is never refused for being too big
# ---------------------------------------------------------------------------
MORE = "…"


def _tidied(pieces) -> tuple:
    """Without what Discord refuses outright: empty texts, empty boxes, empty
    rows, and a row of more buttons than a row takes (the first ones stay)."""
    out: list = []
    for piece in pieces:
        if isinstance(piece, Text):
            if piece.content.strip():
                out.append(piece)
        elif isinstance(piece, Box):
            children = _tidied(piece.children)
            if children:
                out.append(Box(piece.status if piece.status in ACCENTS else QUIET, children))
        elif isinstance(piece, Row):
            if piece.buttons:
                out.append(Row(tuple(piece.buttons[:MAX_BUTTONS_IN_ROW])))
        else:
            out.append(piece)
    return tuple(out)


def _rows(pieces) -> int:
    return sum(1 if isinstance(piece, Row) else _rows(piece.children) if isinstance(piece, Box) else 0 for piece in pieces)


def _without_last_row(pieces) -> tuple:
    """The layout with its last row of buttons taken off."""
    out = list(pieces)
    for at in range(len(out) - 1, -1, -1):
        piece = out[at]
        if isinstance(piece, Row):
            del out[at]
            return tuple(out)
        if isinstance(piece, Box) and _rows(piece.children):
            out[at] = Box(piece.status, _without_last_row(piece.children))
            return tuple(out)
    return tuple(out)


def _flattened(pieces) -> tuple:
    """Each box's words as one text, with no rules: fewer components, the same words."""
    out: list = []
    for piece in pieces:
        if isinstance(piece, Box):
            words = "\n".join(texts(piece.children))
            rows = [child for child in piece.children if not isinstance(child, (Text, Separator))]  # its buttons and any dropdown
            out.append(Box(piece.status, (*([Text(words)] if words else []), *rows)))
        elif not isinstance(piece, Separator):
            out.append(piece)
    return tuple(out)


def cut(text: str, limit: int) -> str:
    """Text within a number of characters, whole lines kept where they can be,
    and a mark that something was left out."""
    if len(text) <= limit:
        return text
    lines, used, kept = text.split("\n"), 0, []
    for line in lines:
        if used + len(line) + 1 > limit - len(MORE) - 1:
            break
        kept.append(line)
        used += len(line) + 1
    if not kept:
        return text[: max(0, limit - len(MORE))] + MORE
    return "\n".join([*kept, MORE])


def _shortened(pieces, over: int) -> tuple:
    """The longest texts cut until the whole is `over` characters shorter."""
    longest = sorted(
        ((len(text), text) for text in texts(pieces)),
        reverse=True,
    )
    targets: dict[str, int] = {}
    for size, text in longest:
        if over <= 0:
            break
        keep = max(len(MORE) + 1, size - over)
        targets[text] = keep
        over -= size - keep

    def walk(parts) -> tuple:
        out: list = []
        for piece in parts:
            if isinstance(piece, Text) and piece.content in targets:
                out.append(Text(cut(piece.content, targets[piece.content])))
            elif isinstance(piece, Box):
                out.append(Box(piece.status, walk(piece.children)))
            else:
                out.append(piece)
        return tuple(out)

    return walk(pieces)


def fit(pieces) -> tuple:
    """A layout Discord will take, whatever it was given: nothing is ever left
    unposted for being too big. First the buttons go, the last first (the
    first row, the thing due next, stays longest); then the rules inside each
    box; then the longest texts are cut, with a mark; and last of all the
    whole message is its words in one text."""
    pieces = _tidied(pieces)
    if not problem(pieces):
        return pieces
    while _rows(pieces) > 1 and problem(pieces):
        pieces = _without_last_row(pieces)
    if problem(pieces) and count(pieces) > MAX_COMPONENTS:
        pieces = _flattened(pieces)
    while count(pieces) > MAX_COMPONENTS and _rows(pieces):
        pieces = _without_last_row(pieces)
    if length(pieces) > MAX_TEXT:
        pieces = _shortened(pieces, length(pieces) - MAX_TEXT)
    if not problem(pieces):
        return pieces
    words = "\n".join(texts(pieces)) or MORE
    return (Text(cut(words, MAX_TEXT)),)


# ---------------------------------------------------------------------------
# The shapes of docs/DESIGN.md
# ---------------------------------------------------------------------------
def item(status: str, name: str, *lines: str, row: tuple = ()) -> Box:
    """One item's box: its name and state at a glance, then whatever there is
    to say (the plan, what has happened, what is next, a warning or a hint,
    in that order: empty lines are left out), and its buttons in one row.
    A box with nothing to do has no buttons."""
    body = "\n".join([name, *(line for line in lines if line)])
    return Box(status, (Text(body), Row(tuple(row))) if row else (Text(body),))


def bolded(pieces) -> tuple:
    """A layout with every time written as code put in bold (`bold_times`)."""
    out: list = []
    for piece in pieces:
        if isinstance(piece, Text):
            out.append(Text(bold_times(piece.content)))
        elif isinstance(piece, Box):
            out.append(Box(piece.status, bolded(piece.children)))
        else:
            out.append(piece)
    return tuple(out)


def merged(boxes, later=()) -> list:
    """The boxes of one topic as one box: boxes separate topics, never items.
    A rule between items, a wider gap before the section after them (`later`,
    Paused), and the edge in the colour of the most urgent of them."""
    items = [box for box in boxes if isinstance(box, Box)]
    others = [piece for piece in boxes if not isinstance(piece, Box)]
    if not items and not later:
        return list(boxes)
    children: list = []
    for box in items:
        if children:
            children.append(Separator())
        children += box.children
    for at, box in enumerate(later):
        if children:
            children.append(section() if at == 0 else Separator())
        children += box.children
    return [*others, Box(urgent(box.status for box in [*items, *later]), tuple(children))]


def standing(title: str, context: str, boxes: list, later: list | tuple = (), hint: str = "", under: tuple = ()) -> tuple:
    """A standing message, in the round the cards are drawn in (`current`)."""
    if current() < 3:
        return _standing_r1(title, context, boxes, later, hint, under)
    return _standing_r3(title, context, boxes, later, hint, under)


def _standing_r3(title: str, context: str, boxes: list, later: list | tuple = (), hint: str = "", under: tuple = ()) -> tuple:
    """A standing message (shown every day, edited in place): the `## ` page
    title and one small line of context, then one box for the topic with a
    rule between its items (each `item` given), a wider gap before the section
    after them (Paused), and a hint under it all. `under` is lines that belong
    to the title (the day's progress)."""
    pieces: list = [Text("\n".join([page_title(title), *([small(context)] if context else []), *under]))]
    pieces += merged(boxes, later)
    if hint:
        pieces.append(Text(small(hint)))
    return bolded(pieces)


def topic(title: str, entries: list[Entry] | tuple = (), *, lines: list[str] | tuple = (), tail: str = "", status: str = "") -> Box:
    """One topic's box: its card title (`card_title`) and any lines under it,
    then its items with a rule between them, each with its buttons under it,
    and what is done collapsed into one small line at the bottom (`tail`).
    Its edge is the most urgent state of its items unless `status` says."""
    children: list = [Text("\n".join([title, *(line for line in lines if line)]))]
    for entry in entries:
        children += [Separator(), Text(entry.text)]
        if entry.row:
            children.append(Row(tuple(entry.row)))
    if tail:
        # One small line, or several (the relevance rule's: later, done, missed), each small
        children += [Separator(), Text("\n".join(small(line) for line in tail.split("\n") if line))]
    return Box(status or urgent(entry.status for entry in entries), tuple(children))


# ---------------------------------------------------------------------------
# The relevance rule (round 4: Alex's direction, docs/DESIGN-LOG.md). Every
# card shows each thing by how much it matters now: what can be done now is a
# full line with its button; the next thing coming up a full line with none;
# everything later today one small line of times; what is done one small
# line with a count; what was missed one small line with a count and its
# times; what is paused not at all. A task says what each thing is and how
# its line reads; this file decides how much of it shows.
# ---------------------------------------------------------------------------
NOW, COMING, FINISHED, GONE_BY, PAUSED = "now", "coming", "finished", "gone_by", "paused"
THING_STATES = (NOW, COMING, FINISHED, GONE_BY, PAUSED)


@dataclass(frozen=True)
class Thing:
    """One thing on a card, for the relevance rule."""

    text: str  # its full line, name first ("**Pill A** · dose 2 · **11:00 am**")
    state: str  # one of THING_STATES
    at: object = None  # when it is due, for the order of what is coming (None: after those with a time)
    when: str = ""  # its time as a small line says it ("2:00 pm"); empty with none
    status: str = DUE  # the colour of its full line, while it is one
    row: tuple = ()  # its buttons: shown only while it can be done now


@dataclass(frozen=True)
class Relevant:
    """What a card shows: the full lines, the small lines under them, and the counts."""

    entries: tuple
    small: tuple[str, ...]
    done: int
    missed: int
    later: int
    hidden: int


def relevant(things) -> Relevant:
    """Sort a card's things by the relevance rule (above)."""
    now = [thing for thing in things if thing.state == NOW]
    coming = sorted((thing for thing in things if thing.state == COMING), key=lambda thing: (thing.at is None, thing.at.timestamp() if thing.at is not None else 0))
    done = [thing for thing in things if thing.state == FINISHED]
    missed = [thing for thing in things if thing.state == GONE_BY]
    hidden = sum(thing.state == PAUSED for thing in things)
    entries = [Entry(thing.text, thing.status, tuple(thing.row)) for thing in now]
    if coming:
        # The next thing coming up: a full line, and no button until it can be done
        entries.append(Entry(coming[0].text, QUIET, ()))
    lines = []
    later = coming[1:]
    if later:
        timed = [thing.when for thing in later if thing.when]
        untimed = len(later) - len(timed)
        said = ", ".join(timed) + (f" and {untimed} more" if untimed and timed else f"{untimed} more" if untimed else "")
        lines.append(f"later today · {said}")
    if done:
        lines.append(f"✅ {len(done)} done")
    if missed:
        times = [thing.when for thing in missed if thing.when]
        lines.append(f"✕ {len(missed)} missed" + (f" · {', '.join(times)}" if times else ""))
    return Relevant(tuple(entries), tuple(lines), len(done), len(missed), len(later), hidden)


# ---------------------------------------------------------------------------
# A list card (round 4, Alex 15 Oct): a list of things with no time each,
# such as to-dos. The first few open ones in full, the rest one small line
# ("+4 more"), and one dropdown for what can be done to any open one, in
# place of a button under each. The dropdown holds Discord's most (25), the
# most relevant first; beyond that the card says to use words. The same rule
# for any list card to come.
# ---------------------------------------------------------------------------
LIST_FIRST = 3  # open things shown in full
MAX_MENU = 25  # options in one dropdown, Discord's most


@dataclass(frozen=True)
class Listed:
    """What a list card shows of its open things."""

    shown: tuple  # the first few, in full
    more: int  # how many after those, said in one small line
    menu: tuple  # those the dropdown holds, the most relevant first
    left_out: int  # how many the dropdown has no room for


def listed(open_things, in_menu=None, first: int = LIST_FIRST) -> Listed:
    """A list card's open things, the most relevant first, by the list rule
    (above). `in_menu`, if given, is what the dropdown offers (it may hold
    more than the card lists: to-dos for a later day)."""
    things = tuple(open_things)
    offered = things if in_menu is None else tuple(in_menu)
    return Listed(things[:first], max(0, len(things) - first), offered[:MAX_MENU], max(0, len(offered) - MAX_MENU))


def more_line(more: int) -> str:
    """The small line for the open things a list card does not show: "+4 more"."""
    return f"+{more} more" if more > 0 else ""


def menus(pieces) -> list:
    """Every dropdown of a layout (core/cards.py `Select`s), in order."""
    found: list = []
    for piece in pieces:
        if isinstance(piece, Box):
            found += menus(piece.children)
        elif hasattr(piece, "options"):
            found.append(piece)
    return found


def page(top: list[str] | tuple, boxes: list | tuple, foot: list[str] | tuple = ()) -> tuple:
    """A message of several topics (the briefing): the page title and the lines
    under it, a box a topic, then the lines at the foot."""
    pieces: list = [Text("\n".join(line for line in top if line)), *boxes]
    foot = [line for line in foot if line]
    if foot:
        pieces.append(Text("\n".join(foot)))
    return bolded(pieces)


def decision(
    heading: str,
    things: list[str] | tuple[str, ...],
    *,
    status: str = DECISION,
    context: str = "",
    warnings: list[str] | tuple[str, ...] = (),
    question: str = "",
    row: tuple = (),
    hint: str = "",
) -> tuple:
    """A card that asks for a decision, in the round the cards are drawn in (`current`)."""
    shape = _decision_r1 if current() < 3 else _decision_r3
    return shape(heading, things, status=status, context=context, warnings=warnings, question=question, row=row, hint=hint)


def _decision_r3(
    heading: str,
    things: list[str] | tuple[str, ...],
    *,
    status: str = DECISION,
    context: str = "",
    warnings: list[str] | tuple[str, ...] = (),
    question: str = "",
    row: tuple = (),
    hint: str = "",
) -> tuple:
    """A card that asks for a decision. `## icon Task · kind` as the page title
    (and a small line saying what it is about), then one box: the things with a
    rule between them, each change as old struck through → new bold, the
    warnings, the hint and the buttons. `things` are blocks of text.

    A card that asks a question is thin instead (`asking`), so several stack."""
    if question:
        return asking(question, heading, things, status=status, context=context, warnings=warnings, row=row, hint=hint)
    pieces: list = [Text(page_title(heading) + (f"\n{small(context)}" if context else ""))]
    children: list = []
    for thing in things:
        if thing:
            children += [*([Separator()] if children else []), Text(_changes(thing))]
    if warnings:
        children += [*([Separator()] if children else []), Text("\n".join(warning(each) for each in warnings))]
    if hint:
        children += [*([Separator()] if children else []), Text(small(hint))]
    if row:
        children.append(Row(tuple(row)))
    if children:
        pieces.append(Box(status, tuple(children)))
    return bolded(pieces)


def _changes(block: str) -> str:
    return "\n".join(changed(line) for line in bold_times(block).split("\n"))


def asking(
    question: str,
    heading: str,
    things: list[str] | tuple[str, ...] = (),
    *,
    status: str = DECISION,
    context: str = "",
    warnings: list[str] | tuple[str, ...] = (),
    row: tuple = (),
    hint: str = "",
) -> tuple:
    """A thin question card: one box, the question as its card title, what it
    is about small under it, what was understood, and the answers in one row.
    No page title and no rules, so two in a row read as a stack."""
    lines = [card_title(question), small(heading + (f" · {context}" if context else ""))]
    lines += [_changes(thing) for thing in things if thing]
    lines += [warning(each) for each in warnings]
    children: list = [Text("\n".join(lines))]
    if row:
        children.append(Row(tuple(row)))
    pieces: list = [Box(status, tuple(children))]
    if hint:
        pieces.append(Text(small(hint)))
    return bolded(pieces)


# ---------------------------------------------------------------------------
# Rounds: every round that was built stays selectable (docs/DESIGN-LOG.md), so
# "go back to round N" is a setting (DESIGN_ROUND) and a restart. Round 1 is
# the look built before round 3: a box an item, `# ` for a standing message,
# the heading inside a decision's box. Kept as it was; never restyled.
# ---------------------------------------------------------------------------
ROUNDS = (1, 3, 4, 5)  # the rounds that were built, oldest first (config's default stays the one that is shipped)
LATEST = ROUNDS[-1]
# Rounds drawn for a preview only (round 6, the timeline hub: core/timeline.py, 17 Oct). Chosen, the hub's own cards
# are drawn as the latest built round's: nothing of live's changes until one is built and shipped
PREVIEW_ROUNDS = (6,)
# Rounds built behind the setting and never the fallback (round 7: the briefing as embeds, 21 Oct). Everything
# but the briefing draws as round 5 in it; round 5 stays the default
CHOSEN_ROUNDS = (7,)
EMBEDS_ROUND = 7


def current() -> int:
    """The round the cards are drawn in: DESIGN_ROUND, or the latest if it names no round that was built."""
    from core import config  # read when drawn, so a test or a restart can change it

    wanted = getattr(config, "DESIGN_ROUND", LATEST)
    return wanted if wanted in ROUNDS or wanted in PREVIEW_ROUNDS or wanted in CHOSEN_ROUNDS else LATEST


def _standing_r1(title: str, context: str, boxes: list, later: list | tuple = (), hint: str = "", under: tuple = ()) -> tuple:
    """Round 1: `# icon Title · progress` and one small line of context, a box
    an item, then a separator and the boxes of the section after it (Paused),
    and a hint under it all."""
    pieces: list = [Text("\n".join([f"# {title}", *([small(context)] if context else []), *under]))]
    pieces += list(boxes)
    if later:
        pieces += [section(), *later]
    if hint:
        pieces.append(Text(small(hint)))
    return tuple(pieces)


def _decision_r1(
    heading: str,
    things: list[str] | tuple[str, ...],
    *,
    status: str = DECISION,
    context: str = "",
    warnings: list[str] | tuple[str, ...] = (),
    question: str = "",
    row: tuple = (),
    hint: str = "",
) -> tuple:
    """Round 1: one box, `## icon Task · kind` inside it, a separator, the
    things, a separator above the warning and the one question in bold, then
    the buttons. The hint goes under the box."""
    children: list = [Text(f"## {heading}" + (f"\n{small(context)}" if context else ""))]
    for thing in things:
        if thing:
            children += [Separator(), Text(thing)]
    asked = [warning(each) for each in warnings] + ([f"**{question}**"] if question else [])
    if asked:
        children += [Separator(), Text("\n".join(asked))]
    if row:
        children.append(Row(tuple(row)))
    pieces: list = [Box(status, tuple(children))]
    if hint:
        pieces.append(Text(small(hint)))
    return tuple(pieces)


def notifying(line: str, box: Box | None = None, hint: str = "") -> tuple:
    """A message that notifies: the one plain line that is safe on a lock
    screen, outside any box, and under it the box with the details."""
    pieces: list = [Text(line)]
    if box is not None:
        pieces.append(box)
    if hint:
        pieces.append(Text(small(hint)))
    return tuple(pieces)


def plain(text: str, rows: tuple = ()) -> tuple:
    """A message with no design of its own, as a layout: its text, then its
    rows of buttons. For rewriting a Components V2 message with a plain card
    (a message can become Components V2 and can never go back)."""
    # A dropdown (not a tuple of buttons) is passed on as it is: core/cards.py gives it a row
    return (Text(text), *(Row(tuple(row)) if isinstance(row, tuple) else row for row in rows))


# ---------------------------------------------------------------------------
# Reading a card back
# ---------------------------------------------------------------------------
def words(message) -> str:
    """What a message says. A Components V2 message has no text of its own:
    its words are in its components, and are read back out of them here, so
    a copy of a channel, an archived message and a bug report still hold
    what a card said. Takes anything shaped like a Discord message."""
    said = (getattr(message, "content", "") or "").strip()
    if said:
        return said
    found: list[str] = []

    def walk(parts) -> None:
        for part in parts or []:
            text = getattr(part, "content", None)
            if isinstance(text, str) and text.strip():
                found.append(text.strip())
            walk(getattr(part, "children", None))

    walk(getattr(message, "components", None))
    return "\n".join(found)
