import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import clock, config
from core.errors import UserError

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# 👍 on a message that asks one simple yes (Alex, 21 Oct): a dose's reminder
# (Taken), a dose with no time's own message (Taken), a reminder that went
# off (Done), an expiry (Done), a routine's own card (all of it done). It does
# what that message's own button does, through the same handler, as if it
# were pressed: every check a press has (a dose too soon asks first, on the
# card) is there.
#
# A card says what a 👍 on it means (`Card.thumbs_up`, a Button), and
# core/cards.py notes it here when the card is sent, again when it is
# rewritten (or forgets it when the new card asks nothing), and forgets it
# when the message is deleted: no task touches this registry. So a thing done
# another way first (typed, or pressed) has taken its card away or rewritten
# it, and a 👍 after that is nothing; the first one wins and the next is
# nothing too, as the entry goes the moment it is taken.
#
# In memory only: a restart forgets them, and the next reminder or card
# drawn notes them again. An entry lasts LIFETIME. The reaction itself is the
# builtin task's (tasks/builtin): checked at once, acted on after the quiet
# period, ✅ added, and taking it away undoes it where the action said how
# (`Press.offer_undo`). Behind THUMBS_UP: off, no card notes anything.
#
# A 👍 that is a signal is a kind of its own (21 Oct, the morning news's
# cards: "liked or read"): no yes is asked, nothing is confirmed, and it is
# silent (no ✅, nothing said). Adding it runs `on`, taking it away runs
# `off`, as often as he likes; it lasts as long as its message. A task notes
# its messages (`signal`) when it posts them and again when the bot starts
# (it keeps them in its own tables), and forgets them when they go.
# ---------------------------------------------------------------------------
THUMBS_UP = "👍"
LIFETIME = timedelta(hours=24)
FORM_NEEDS_A_PRESS = "That one needs its button: a reaction can't fill in a form."
NO_UNDO = "Taking the 👍 away can't undo this one: say “undo that”."


def enabled() -> bool:
    return bool(config.THUMBS_UP)


@dataclass(frozen=True)
class Pending:
    message_id: int
    channel_id: int | None
    button: object  # a cards.Button: the task, the action and its argument a 👍 runs
    until: datetime


@dataclass(frozen=True)
class Signal:
    channel_id: int | None
    on: object  # a cards.Button: what a 👍 notes
    off: object  # and what taking it away does


_pending: dict[int, Pending] = {}
_undo: dict[int, tuple[int | None, object]] = {}  # a message a 👍 was applied to: (its channel, the undo button)
_signals: dict[int, Signal] = {}


def register(message_id: int | None, channel_id: int | None, button, now: datetime | None = None) -> None:
    """A message that a 👍 confirms, for LIFETIME (a card rewritten with the same yes keeps its first time)."""
    if message_id is None or button is None or not enabled():
        return
    now = now or clock.now()
    was = _pending.get(message_id)
    until = was.until if was is not None and was.button == button else now + LIFETIME
    _pending[message_id] = Pending(message_id, channel_id, button, until)


def drop(message_id: int | None) -> None:
    """The message is gone, or asks nothing now."""
    _pending.pop(message_id, None)


def follow(message_id: int | None, channel_id: int | None, card) -> None:
    """A card was rewritten in place: what a 👍 on it means now, or nothing."""
    if getattr(card, "thumbs_up", None) is not None:
        register(message_id, channel_id, card.thumbs_up)
    else:
        drop(message_id)


def pending(message_id: int | None, now: datetime | None = None) -> Pending | None:
    """The yes a message waits for, or None: never noted, done already, or older than LIFETIME (then forgotten)."""
    found = _pending.get(message_id) if message_id is not None else None
    if found is not None and (now or clock.now()) >= found.until:
        drop(message_id)
        return None
    return found


def tracked(message_id: int | None) -> bool:
    return pending(message_id) is not None or is_signal(message_id)


def reset() -> None:
    _pending.clear()
    _undo.clear()
    _signals.clear()


# --- a 👍 that is a signal ----------------------------------------------------------------------------------------
def signal(message_id: int | None, channel_id: int | None, on, off) -> None:
    """A message a 👍 on is a signal: `on` when it is added, `off` when it is taken away (cards.Buttons)."""
    if message_id is None or not enabled():
        return
    _signals[message_id] = Signal(channel_id, on, off)


def forget_signal(message_id: int | None) -> None:
    _signals.pop(message_id, None)


def is_signal(message_id: int | None) -> bool:
    """A message whose 👍 is a signal: it is applied silently, with no ✅."""
    return message_id is not None and message_id in _signals


async def signalled(message_id: int, user, added: bool) -> str | None:
    """A 👍 added to a signal's message, or taken away: its `on` or its `off`, run as a press. None when
    the message is no signal's (or its task is not loaded): nothing is done."""
    from core import cards
    from core.permissions import is_allowed

    found = _signals.get(message_id)
    button = (found.on if added else found.off) if found is not None else None
    registered = cards.action_for(button.task, button.action) if button is not None else None
    if registered is None:
        return None
    if not is_allowed(user, registered.permission):
        raise UserError("That isn't yours.")
    press = ReactionPress(user, button.task, button.action, button.arg, found.channel_id, message_id)
    return await registered.handler(press) or "noted"


async def confirm(message_id: int, user) -> str | None:
    """A 👍 on a message: its button's action, run as a press of it. None when the message waits for no yes
    (never noted, done already, expired): nothing is done and nothing is said. A UserError from the action
    is raised (the reaction gets ⚠️), and the yes is noted again so another try can work."""
    from core import cards

    if is_signal(message_id):
        return await signalled(message_id, user, True)
    found = pending(message_id)
    if found is None:
        return None
    drop(message_id)  # the first one wins: a second, at once or later, finds nothing
    button = found.button
    registered = cards.action_for(button.task, button.action)
    if registered is None:
        return None  # its task is not loaded any more
    from core.permissions import is_allowed

    if not is_allowed(user, registered.permission):
        raise UserError("That isn't yours to confirm.")
    press = ReactionPress(user, button.task, button.action, button.arg, found.channel_id, message_id)
    try:
        said = await registered.handler(press)
    except UserError:
        _pending.setdefault(message_id, found)
        raise
    if press.undo is not None:
        _undo[message_id] = (found.channel_id, press.undo)
    return said or (press.shown[-1] if press.shown else "done")


async def undo(message_id: int, user) -> str:
    """The 👍 was taken away after it was applied: what the action said would undo it, run as a press."""
    from core import cards

    if is_signal(message_id):
        return await signalled(message_id, user, False) or "undone"
    channel_id, button = _undo.pop(message_id, (None, None))
    registered = cards.action_for(button.task, button.action) if button is not None else None
    if registered is None:
        raise UserError(NO_UNDO)
    press = ReactionPress(user, button.task, button.action, button.arg, channel_id, message_id)
    return await registered.handler(press) or "undone"


class _Answer:
    """What a press made by a reaction answers through: the message rewritten, said, or taken away in the
    channel, as there is no interaction to answer."""

    def __init__(self, channel_id: int | None, message_id: int | None):
        self.channel_id, self.message_id = channel_id, message_id

    def done(self) -> bool:
        return True

    async def defer(self) -> None:
        return None

    async def update(self, card) -> None:
        from core import cards

        await cards.edit(self.channel_id, self.message_id, card)

    async def say(self, text: str) -> None:
        """Said to the presser alone, for a press; for a reaction, a short note that goes by itself."""
        from core import cards, lifecycle, tidy

        note = await cards.send(self.channel_id, cards.Card(text), silent=True)
        await tidy.later(self.channel_id, note, lifecycle.delete_after())

    async def open_form(self, form) -> None:
        raise UserError(FORM_NEEDS_A_PRESS)

    async def remove(self) -> None:
        from core import cards

        await cards.delete(self.channel_id, self.message_id)


def _press_class():
    from core import cards

    class _ReactionPress(cards.Press):
        """A press of a message's yes button, made by a 👍 on it."""

        @property
        def _answer(self):
            return _Answer(self.channel_id, self.message_id)

    return _ReactionPress


def ReactionPress(user, task: str, action: str, arg: str, channel_id: int | None, message_id: int | None):  # noqa: N802
    return _press_class()(user, task, action, arg, channel_id, message_id)
