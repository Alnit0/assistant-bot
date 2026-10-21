import logging
from dataclasses import dataclass

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The door to the interface: the one way the core reaches the place the bot
# is used through (Discord, today the only one).
#
# The core says what to show and what to do as plain data and plain verbs:
# send this text there, rewrite that card, delete that message, pin it, put
# this status line up. It never holds the interface's client, never calls a
# method on one of its objects and never catches one of its errors: what
# goes wrong comes back as `Gone` (it is not there any more) or `Failed`
# (it could not be done, with the interface's status and code if it has
# them).
#
# The interface says it is there with `bind` (interfaces/discord does, when
# the bot starts; the tests' conftest does too). With nothing bound, nothing
# can be found: a place is None, a send returns None, and a verb that must
# act raises `Failed`.
#
# A place is known by its id and a message by its place's id and its own
# (`channel_id`, `message_id`: the names the database has). What `fetch`
# and `history` hand back are the interface's own messages, to be READ by
# attribute only (id, content, author, created_at, pinned, reactions,
# attachments, jump_url) and handed back to the interface untouched: to
# change one, use a verb with its ids. (They become plain records when the
# typed-word contract does: docs/INTERFACE.md, stages 3 and 4.)
#
# docs/INTERFACE.md has the whole plan. The rule it serves: new core code
# and new tasks never import discord.py.
# ---------------------------------------------------------------------------


class Failed(Exception):
    """The interface could not do it."""

    def __init__(self, text: str = "", status: int | None = None, code: int | None = None):
        super().__init__(text)
        self.status = status
        self.code = code


class Gone(Failed):
    """What it was about is not there any more (a deleted message)."""


class Refused(Failed):
    """The interface would not let this bot in at all (a token it refuses)."""


@dataclass(frozen=True)
class Place:
    """Somewhere messages may be: a channel, a thread, a direct message."""

    id: int
    name: str
    mention: str  # how it is written in a sentence so that it can be tapped
    messages: bool  # whether it holds messages at all (a forum does not)
    server: bool  # whether it is a place of the server (not a direct message)


@dataclass(frozen=True)
class Name:
    """The bot's own name where it is used."""

    current: str
    can_change: bool


NOTHING_BOUND = "no interface is bound: nothing can be reached"
_backend = None


def bind(backend) -> None:
    """The interface says it is there. Called once, before anything is sent."""
    global _backend
    _backend = backend


def bound() -> bool:
    return _backend is not None


def _door():
    if _backend is None:
        raise Failed(NOTHING_BOUND)
    return _backend


# --- finding out (never raises) ---------------------------------------------------------------------------------------
def connected() -> bool:
    """Whether the interface is up at all."""
    return _backend is not None and _backend.connected()


def me() -> int | None:
    """The bot's own account there, or None before it is connected."""
    return _backend.me() if _backend is not None else None


def place(channel_id: int | None) -> Place | None:
    """A place the bot can see, or None."""
    return _backend.place(channel_id) if _backend is not None and channel_id else None


def raw_place(channel_id: int | None):
    """The interface's own object for a place, for a task that is the interface's own
    (docs/INTERFACE.md). New code asks `place`."""
    return _backend.raw_place(channel_id) if _backend is not None and channel_id else None


def holds_messages(raw) -> bool:
    """Whether one of the interface's own places holds messages. False for None."""
    return _backend is not None and raw is not None and _backend.holds_messages(raw)


def lacking(channel_id: int, permissions: tuple[str, ...]) -> tuple[str, ...]:
    """Which of these permissions (the interface's own names) the bot lacks in a place."""
    return _backend.lacking(channel_id, permissions) if _backend is not None else tuple(permissions)


def mention(account_id: int | None) -> str:
    """A person as the interface writes them so that they are told (a ping). "" if it can't."""
    return _backend.mention(account_id) if _backend is not None and account_id else ""


def link(channel_id: int | None, message_id: int | None) -> str:
    """Where a message is, as a link the interface opens. "" if it can't be said."""
    return _backend.link(channel_id, message_id) if _backend is not None and channel_id and message_id else ""


# --- messages ---------------------------------------------------------------------------------------------------------
async def send(channel_id: int | None, text: str, *, silent: bool = False, suppress_embeds: bool = False) -> int | None:
    """Post plain text in a place. The new message's id, or None if the place can't be found."""
    if place(channel_id) is None:
        return None
    return await _door().send(channel_id, text, silent=silent, suppress_embeds=suppress_embeds)


async def edit(channel_id: int, message_id: int, text: str, *, suppress_embeds: bool = False) -> None:
    """Rewrite a message's text in place. Raises Gone or Failed."""
    await _door().edit(channel_id, message_id, text, suppress_embeds=suppress_embeds)


async def delete(channel_id: int, message_id: int) -> None:
    """Delete one message. Raises Gone if it had gone already, Failed if it can't be done."""
    await _door().delete(channel_id, message_id)


async def delete_many(channel_id: int, message_ids: list[int], reason: str = "") -> None:
    """Delete several messages in one request, where the interface can. Raises Failed for the lot."""
    await _door().delete_many(channel_id, list(message_ids), reason)


async def fetch(channel_id: int, message_id: int):
    """One message, to read. Raises Gone or Failed."""
    return await _door().fetch(channel_id, message_id)


async def history(channel_id: int, *, limit: int | None = None, after=None, oldest_first: bool = False) -> list:
    """The messages of a place, to read: the newest first unless said. Raises Failed."""
    return await _door().history(channel_id, limit=limit, after=after, oldest_first=oldest_first)


async def pin(channel_id: int, message_id: int, pinned: bool, reason: str = "") -> None:
    """Pin or unpin. Raises Gone or Failed."""
    await _door().pin(channel_id, message_id, pinned, reason)


async def react(channel_id: int, message_id: int, emoji: str) -> None:
    """Put the bot's own reaction on a message. Raises Gone or Failed."""
    await _door().react(channel_id, message_id, emoji)


async def unreact(channel_id: int, message_id: int, emoji: str) -> None:
    """Take the bot's own reaction off a message. Raises Gone or Failed."""
    await _door().unreact(channel_id, message_id, emoji)


async def make_place(beside: int, name: str, reason: str = "") -> int:
    """A text channel of this name in the same category as `beside` (#news beside the hub): the one
    there already, or a new one. Its id. Raises Failed (a bot that may not make channels, for one)."""
    return await _door().make_place(beside, name, reason)


# --- cards (core/cards.py is who asks) -------------------------------------------------------------------------------
def drawn(card):
    """A card as the interface draws it, to hand to a reply. None for one with nothing to press."""
    return _door().drawn(card)


async def send_card(channel_id: int, card, text: str, *, silent: bool = False) -> int | None:
    """Post a card in a place: `text` is its words as checked on the way out. None if the place can't be found."""
    if place(channel_id) is None:
        return None
    return await _door().send_card(channel_id, card, text, silent=silent)


async def edit_card(channel_id: int, message_id: int, card, plain) -> None:
    """Rewrite a card in place: `plain` is the same card as words and rows only. Raises Gone or Failed."""
    await _door().edit_card(channel_id, message_id, card, plain)


def answer(source):
    """What a press is answered through: the interface's own event, wrapped
    (`done`, `defer`, `say`, `update`, `open_form`, `remove`, `fail`, and
    who pressed, where and on what)."""
    return _door().answer(source)


# --- the bot itself ---------------------------------------------------------------------------------------------------
async def status(line: str) -> None:
    """Put the status line up; "" clears it. Raises Failed."""
    await _door().status(line)


def name(channel_id: int | None) -> Name | None:
    """The bot's name in the server a place is in, or None if that can't be found."""
    return _backend.name(channel_id) if _backend is not None and channel_id else None


async def rename(channel_id: int, wanted: str, reason: str = "") -> None:
    """Change the bot's name there. Raises Failed."""
    await _door().rename(channel_id, wanted, reason)


async def who(token: str) -> tuple[int, str]:
    """The account a token belongs to: (id, name), asked without connecting.
    Raises Refused for a token that is not let in, Failed or OSError when the
    interface can't be asked."""
    return await _door().who(token)
