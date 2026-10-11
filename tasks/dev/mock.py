import re
from dataclasses import dataclass
from pathlib import Path

import discord

from core import cards
from core.config import MOCKUPS_DIR
from core.context import Context
from core.discord_utils import report_interaction_error, safe_reply
from core.permissions import is_allowed
from core.users import get_user_by_discord_id

# ---------------------------------------------------------------------------
# dev mock: a card sketched in a text file, posted as a real Components V2
# message, so a design can be looked at in Discord before any of it is built.
#
# The sketches are docs/mockups/<name>.txt. The format, a line at a time:
#
#   ┃ …              a line inside a Container; lines that follow each other
#                    are one Container, and a blank line ends it
#   ┃ accent: amber  the Container's accent colour (its first line)
#   [label: colour]  a button; several on one line are one row. A mock-up's
#                    buttons do nothing but say so
#   ---              a separator
#   anything else    text, as Discord writes it: "# " and "## " headings,
#                    "-# " subtext, **bold**
#
# Text, buttons and separators work inside a Container and outside one. A
# mistake is reported with the number of the line it is on.
#
# This file has the reading (pure: text in, plain records out) and, at the
# bottom, the discord.py that turns the records into a message.
# ---------------------------------------------------------------------------
BAR = "┃"
ACCENTS = {
    "green": 0x57F287, "red": 0xED4245, "amber": 0xFAA61A, "yellow": 0xFEE75C, "blurple": 0x5865F2,
    "blue": 0x3498DB, "grey": 0x95A5A6, "gray": 0x95A5A6,
}
# The colours a button can be, by the names of the rule for button colours (core/cards.py)
BUTTON_STYLES = {"green": cards.SUCCESS, "red": cards.DANGER, "blurple": cards.PRIMARY, "grey": cards.SECONDARY, "gray": cards.SECONDARY}
MAX_COMPONENTS = 40  # Discord's limit for one message, everything counted
MAX_TEXT = 4000  # and for all its text together
ID_PREFIX = "dev:mock:"
PRESSED = "🧪 Mock-up: this button does nothing yet."

_BUTTON = re.compile(r"\[([^\[\]]*)\]")
_ACCENT = re.compile(r"accent\s*:\s*(.*)", re.IGNORECASE)
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


class MockError(ValueError):
    """Something in a sketch can't be read. `line` is where (1 is the first line)."""

    def __init__(self, line: int, problem: str):
        super().__init__(f"line {line}: {problem}")
        self.line, self.problem = line, problem


@dataclass(frozen=True)
class Text:
    content: str


@dataclass(frozen=True)
class Separator:
    pass


@dataclass(frozen=True)
class Button:
    label: str
    style: str  # one of cards' styles


@dataclass(frozen=True)
class Row:
    buttons: tuple[Button, ...]


@dataclass(frozen=True)
class Container:
    children: tuple  # of Text, Separator, Row
    accent: str = ""  # a name in ACCENTS, or none


def _buttons(line: str, number: int) -> Row:
    found = []
    for inside in _BUTTON.findall(line):
        label, colon, colour = (part.strip() for part in inside.rpartition(":"))
        if not colon or not label:
            raise MockError(number, f"a button is written [label: colour], not [{inside}]")
        style = BUTTON_STYLES.get(colour.lower())
        if style is None:
            raise MockError(number, f"“{colour}” is not a button colour: use {', '.join(sorted(set(BUTTON_STYLES) - {'gray'}))}")
        # The same rule as every real button: grey is for Cancel alone
        wrong = cards.colour_problem(label.removeprefix(cards.CANCEL_EMOJI).strip(), style, cards.CANCEL_EMOJI if label.startswith(cards.CANCEL_EMOJI) else None)
        if wrong:
            raise MockError(number, wrong)
        if len(label) > cards.MAX_LABEL:
            raise MockError(number, f"a button's label is at most {cards.MAX_LABEL} characters")
        found.append(Button(label, style))
    if _BUTTON.sub("", line).strip():
        raise MockError(number, "buttons go on a line of their own, with no other text beside them")
    if len(found) > cards.MAX_BUTTONS_IN_ROW:
        raise MockError(number, f"a row has at most {cards.MAX_BUTTONS_IN_ROW} buttons, not {len(found)}")
    return Row(tuple(found))


def _pieces(lines: list[tuple[int, str]]) -> list:
    """Lines of text, buttons and separators as records: text lines that follow
    each other are one Text."""
    pieces: list = []
    words: list[str] = []

    def flush() -> None:
        if words:
            pieces.append(Text("\n".join(words)))
            words.clear()

    for number, line in lines:
        stripped = line.strip()
        if stripped == "---":
            flush()
            pieces.append(Separator())
        elif stripped.startswith("[") and stripped.endswith("]"):
            flush()
            pieces.append(_buttons(stripped, number))
        elif stripped:
            words.append(line.rstrip())
    flush()
    return pieces


def parse(text: str) -> list:
    """A sketch as records, top to bottom: Text, Separator, Row and Container.
    Raises MockError, which names the line."""
    blocks: list[tuple[bool, list[tuple[int, str]]]] = []  # (inside a container, its lines)
    for number, line in enumerate(text.lstrip("﻿").splitlines(), start=1):
        barred = line.lstrip().startswith(BAR)
        content = line.lstrip()[len(BAR):].removeprefix(" ") if barred else line
        if not line.strip():
            blocks.append((False, []))  # a blank line ends whatever came before
        elif blocks and blocks[-1][0] == barred and blocks[-1][1]:
            blocks[-1][1].append((number, content))
        else:
            blocks.append((barred, [(number, content)]))

    found: list = []
    for barred, lines in blocks:
        if not lines:
            continue
        if not barred:
            for number, line in lines:
                if _ACCENT.fullmatch(line.strip()):
                    raise MockError(number, f"an accent belongs to a container: start the line with {BAR}")
            found += _pieces(lines)
            continue
        accent = ""
        first_number, first = lines[0]
        named = _ACCENT.fullmatch(first.strip())
        if named:
            accent = named[1].strip().lower()
            if accent not in ACCENTS:
                raise MockError(first_number, f"“{named[1].strip()}” is not an accent colour: use {', '.join(sorted(set(ACCENTS) - {'gray'}))}")
            lines = lines[1:]
        for number, line in lines:
            if _ACCENT.fullmatch(line.strip()):
                raise MockError(number, "the accent is the first line of its container")
        children = _pieces(lines)
        if not children:
            raise MockError(first_number, "this container has nothing in it")
        found.append(Container(tuple(children), accent))

    if not found:
        raise MockError(1, "the sketch is empty")
    last = max(1, len(text.splitlines()))
    if count(found) > MAX_COMPONENTS:
        raise MockError(last, f"that makes {count(found)} components, and one message takes {MAX_COMPONENTS} (text, buttons, rows, separators and containers all count)")
    if length(found) > MAX_TEXT:
        raise MockError(last, f"that is {length(found)} characters of text, and one message takes {MAX_TEXT}")
    return found


def count(pieces) -> int:
    """How many components Discord would count."""
    total = 0
    for piece in pieces:
        total += 1
        if isinstance(piece, Row):
            total += len(piece.buttons)
        elif isinstance(piece, Container):
            total += count(piece.children)
    return total


def length(pieces) -> int:
    total = 0
    for piece in pieces:
        if isinstance(piece, Text):
            total += len(piece.content)
        elif isinstance(piece, Container):
            total += length(piece.children)
    return total


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------
def names(folder: Path | None = None) -> list[str]:
    """The sketches there are, by name."""
    folder = folder or MOCKUPS_DIR
    return sorted(path.stem for path in folder.glob("*.txt")) if folder.is_dir() else []


def read(name: str, folder: Path | None = None) -> str | None:
    """A sketch's text, or None if there is none of that name. Only a plain
    name is looked for, never a path."""
    folder = folder or MOCKUPS_DIR
    name = name.strip().lower().removesuffix(".txt")
    path = folder / f"{name}.txt"
    if not _NAME.fullmatch(name) or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def list_text(found: list[str]) -> str:
    if not found:
        return "🧪 No mock-ups yet: put a sketch in `docs/mockups/<name>.txt`."
    return "\n".join(["🧪 **Mock-ups** · `dev mock <name>` posts one here", *(f"• `{name}`" for name in found)])


# ---------------------------------------------------------------------------
# Discord's side
# ---------------------------------------------------------------------------
_DISCORD_STYLES = {
    cards.PRIMARY: discord.ButtonStyle.primary,
    cards.SECONDARY: discord.ButtonStyle.secondary,
    cards.SUCCESS: discord.ButtonStyle.success,
    cards.DANGER: discord.ButtonStyle.danger,
}


class MockButton(discord.ui.DynamicItem[discord.ui.Button], template=r"dev:mock:(?P<number>\d+)"):
    """A mock-up's button: whichever it is, it only says that it is one. The id
    is fixed, so one on a mock-up from before a restart still answers."""

    def __init__(self, number: int, label: str = "mock-up", style: discord.ButtonStyle = discord.ButtonStyle.primary):
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"{ID_PREFIX}{number}"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(int(match["number"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            user = await get_user_by_discord_id(interaction.user.id)
            if not is_allowed(user, "dev"):
                await safe_reply(interaction, "That isn't yours to press.")
                return
            await safe_reply(interaction, PRESSED)
        except Exception as error:
            await report_interaction_error(interaction, error, "Mock-up button failed")


def layout(pieces) -> discord.ui.LayoutView:
    """The records as a Components V2 message."""
    numbers = iter(range(1, MAX_COMPONENTS + 1))

    def built(piece):
        if isinstance(piece, Text):
            return discord.ui.TextDisplay(piece.content)
        if isinstance(piece, Separator):
            return discord.ui.Separator()
        if isinstance(piece, Row):
            return discord.ui.ActionRow(*(MockButton(next(numbers), button.label, _DISCORD_STYLES[button.style]) for button in piece.buttons))
        return discord.ui.Container(
            *(built(child) for child in piece.children),
            accent_colour=discord.Colour(ACCENTS[piece.accent]) if piece.accent else None,
        )

    view = discord.ui.LayoutView(timeout=None)
    for piece in pieces:
        view.add_item(built(piece))
    return view


async def mock(ctx: Context) -> str:
    """`dev mock`: the list. `dev mock <name>`: that sketch, posted here. A
    sketch that can't be read is said in a line, with the line number."""
    if not ctx.args:
        await ctx.reply(list_text(names()))
        return f"listed {len(names())} mock-up(s)"
    name = " ".join(ctx.args).strip().lower().removesuffix(".txt")
    text = read(name)
    if text is None:
        # Not a failure of the word: said in a line, with what there is
        await ctx.reply(f"🧪 There is no mock-up called `{name}`.\n{list_text(names())}")
        return f"no mock-up called {name}"
    try:
        pieces = parse(text)
    except MockError as error:
        await ctx.reply(f"⚠️ `docs/mockups/{name}.txt`, line {error.line}: {error.problem}")
        return f"mock-up {name} not posted: {error}"
    await ctx.channel.send(view=layout(pieces), silent=True)
    ctx.shown(f"mock-up: {name}")
    return f"posted the mock-up {name} ({count(pieces)} components)"
