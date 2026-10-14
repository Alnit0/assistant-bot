"""How a card looks (docs/DESIGN.md), in one place.

Every colour and every spacing value the bot's Components V2 cards use is in
the first block of this file: a change after a look on the phone is an edit
here and nowhere else. `dev mock` draws its sketches with the same values.

Pure: plain records in, plain records out. A task says what a card holds
(`item`, `standing`, `decision`); core/cards.py turns the records into a
message. Nothing here is used unless CARDS_V2 is on.
"""
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

# Text
HEADING = "# "  # the first line of a standing message
CARD_HEADING = "## "  # the first line of a card that asks for a decision
SMALL = "-# "  # detail that is read second
WARNING = "⚠️"

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
# The shapes of docs/DESIGN.md
# ---------------------------------------------------------------------------
def item(status: str, name: str, *lines: str, row: tuple = ()) -> Box:
    """One item's box: its name and state at a glance, then whatever there is
    to say (the plan, what has happened, what is next, a warning or a hint,
    in that order: empty lines are left out), and its buttons in one row.
    A box with nothing to do has no buttons."""
    body = "\n".join([name, *(line for line in lines if line)])
    return Box(status, (Text(body), Row(tuple(row))) if row else (Text(body),))


def standing(title: str, context: str, boxes: list, later: list | tuple = (), hint: str = "", under: tuple = ()) -> tuple:
    """A standing message (shown every day, edited in place): `# icon Title ·
    progress` and one small line of context, a box an item, then a separator
    and the boxes of the section after it (Paused), and a hint under it all.
    `under` is lines that belong to the heading (the day's progress)."""
    pieces: list = [Text("\n".join([f"{HEADING}{title}", *([small(context)] if context else []), *under]))]
    pieces += list(boxes)
    if later:
        pieces += [section(), *later]
    if hint:
        pieces.append(Text(small(hint)))
    return tuple(pieces)


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
    """A card that asks for a decision, in one box: `## icon Task · kind` (and a
    small line saying what it is about), a separator, the things, a separator
    above the warning and the one question, then the buttons. The hint goes
    under the box. `things` are blocks of text: one separator between each."""
    children: list = [Text(f"{CARD_HEADING}{heading}" + (f"\n{small(context)}" if context else ""))]
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
