from dataclasses import dataclass

from core import cards, config
from core.actions import Field

# ---------------------------------------------------------------------------
# The diary's mood scale: one small definition, so that it can become another
# number of levels, a score, tags, or be switched off (DIARY_MOOD) without
# touching the rest of the diary. Each entry keeps the name of the scale its
# mood was recorded on, so an old entry still reads right after a change:
# add the new scale to SCALES, point CURRENT at it, keep the old one listed.
#
# How words map to a level is said to extraction (`field`): Claude names a
# level only when the words make the mood clear, and Python checks it is one
# of the scale's.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    key: str  # what is stored: "good"
    label: str  # what is read: "Good"
    emoji: str  # "😊"


@dataclass(frozen=True)
class Scale:
    name: str  # stored with each entry: "three"
    levels: tuple[Level, ...]
    style: str  # the buttons' colour (core/cards.py): blurple, an ordinary choice
    words: str  # what extraction is told about mapping words to a level


THREE = Scale(
    "three",
    (Level("good", "Good", "😊"), Level("ok", "OK", "😐"), Level("bad", "Bad", "😞")),
    cards.PRIMARY,
    "The mood of the day, only when the user's words make it clear: good (a good, happy, great day), ok (fine, alright, "
    "mixed, so-so), bad (a rough, hard, awful or sad day). Leave it out when the words don't say how the day felt.",
)
SCALES = {each.name: each for each in (THREE,)}  # every scale ever used, so old entries still read
CURRENT = THREE
NO_MOOD = "·"  # a day with no mood, in a row of emoji


def on() -> bool:
    """Whether the diary asks for and shows a mood at all (DIARY_MOOD, on unless set off)."""
    return bool(getattr(config, "DIARY_MOOD", True))


def level(scale: str | None, key: str | None) -> Level | None:
    """The level an entry's mood stands for, on the scale it was recorded on."""
    found = SCALES.get(scale or "")
    return next((each for each in found.levels if each.key == key), None) if found is not None and key else None


def shown(scale: str | None, key: str | None) -> str:
    """ "😊 Good", or "" for no mood. A level of a scale no longer known is shown by its key."""
    found = level(scale, key)
    return f"{found.emoji} {found.label}" if found is not None else (str(key) if key else "")


def emoji(scale: str | None, key: str | None) -> str:
    found = level(scale, key)
    return found.emoji if found is not None else NO_MOOD


def checked(key) -> str | None:
    """A level of the current scale that extraction gave, or None for anything else."""
    key = str(key or "").strip().lower()
    return key if any(each.key == key for each in CURRENT.levels) else None


def field(required: bool = False) -> Field:
    return Field("mood", CURRENT.words, choices=tuple(each.key for each in CURRENT.levels), required=required)


def buttons(task: str, action: str, day: str) -> tuple:
    """A button a level, for a day ("2026-10-15"): the press says which."""
    return tuple(cards.Button(each.label, task, action, f"{day}:{each.key}", emoji=each.emoji, style=CURRENT.style) for each in CURRENT.levels)
