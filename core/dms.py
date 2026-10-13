import re
from dataclasses import replace

from core import config

# ---------------------------------------------------------------------------
# Direct messages to live (behind DMS_ENABLED, off unless switched on).
#
# With it on, a direct message from me (and from nobody else) is read as if
# it had been said in #inbox: the same typed words, the same plain words, the
# same cards. What differs is what a direct message is: a private channel
# whose latest line shows in the list of conversations and on a lock screen.
# So in a direct message:
#   - every reply is sent silently: nothing buzzes for an answer I asked for
#   - the first line of anything the bot says never names one of my things
#     (a pill): when it would, a neutral line goes first, the task's own
#     ("💊 Pills"), and the answer follows under it
#
# Off, a direct message is as it always was: not read for plain words.
# Only live: the dev bot keeps to its own channels and never reads one.
#
# What the bot sends by itself in a direct message (a pointer for a critical
# alert) is not this: that stays a short pointer with a link (DECISIONS.md).
# ---------------------------------------------------------------------------
_open: dict[int, dict[str, str]] = {}  # the direct messages being answered: {channel id: {a thing's name: its task's neutral line}}


def enabled() -> bool:
    return config.DMS_ENABLED and not config.DEV_DATABASE


def opened(channel_id: int, names: dict[str, str]) -> None:
    """A direct message of mine is being handled: this channel is one, and
    these are the names its first lines must not show."""
    _open[channel_id] = dict(names)


def is_dm(channel_id: int | None) -> bool:
    """Whether a channel is a direct message the bot is answering in."""
    return channel_id is not None and channel_id in _open


def names_in(line: str, names: dict[str, str]) -> str:
    """The neutral line of the first of my things named in a line, or "" if none is."""
    low = line.lower()
    for name in sorted(names, key=len, reverse=True):
        if name.strip() and re.search(rf"(?<!\w){re.escape(name.strip().lower())}(?!\w)", low):
            return names[name]
    return ""


def safe(text: str, names: dict[str, str]) -> str:
    """The text with a neutral first line put in front when its own first line
    names one of my things. Otherwise as it was."""
    first = text.split("\n", 1)[0]
    neutral = names_in(first, names)
    return f"{neutral}\n{text}" if neutral and first.strip() != neutral else text


def guard(channel_id: int | None, text: str) -> str:
    """`safe`, for what is about to be sent to a channel: only a direct message is touched."""
    return safe(text, _open[channel_id]) if is_dm(channel_id) and text else text


def guarded(channel_id: int | None, card):
    """A card whose words are safe to show first in a direct message."""
    if not is_dm(channel_id):
        return card
    text = guard(channel_id, card.text)
    return card if text == card.text else replace(card, text=text)
