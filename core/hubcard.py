import logging
from collections.abc import Awaitable, Callable

from core import cards, database, hub, livelists, messages
from core.cards import Card

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A task's own card in the hub (docs/DESIGN.md, the hub): one message a task,
# posted fresh under the briefing and the pills checklist by the morning
# routine, edited in place all day, and never there on a day with nothing for
# it (no placeholder cards). What it says is the task's (`render`); where it
# is and that there is only one is this file's.
#
#   await hubcard.post(TASK, user_id, render)      the morning: a fresh copy, the old one goes
#   hubcard.changed(TASK, user_id, render)         something changed: edited in place, in the
#                                                  background; gone when there is nothing today,
#                                                  posted when there was none and now there is
#
# `render` is `async () -> Card | None`, read when it runs, so the edit that
# happens shows how things stand. No Discord here: cards and the door do it.
# A task with more than one card (a personal routine's own, in layout B) gives
# each a `slot` of its own; the card still belongs to the task, so a message
# that follows it goes to that task.
# ---------------------------------------------------------------------------
Render = Callable[[], Awaitable["Card | None"]]
# Each task's place in the hub's order and how its card is drawn for a user (`order`): round 5
# (question 68) posts the cards that belong under one again under it when it comes up mid-day
_orders: dict[str, tuple[int, Callable[[int], Render]]] = {}


def order(task: str, place: int, render_for: Callable[[int], Render]) -> None:
    """Say where a task's card goes in the hub's order (core/hub.py, CARDS_ORDER), and how to draw it."""
    _orders[task] = (place, render_for)


async def _keep_order(task: str, user_id: int) -> None:
    """Round 5: the cards placed after this task's, posted again under it, in order."""
    from core import design

    if design.current() < 5 or task not in _orders:
        return
    mine = _orders[task][0]
    for later, (place, render_for) in sorted(_orders.items(), key=lambda each: each[1][0]):
        if place > mine and await database.run(livelists.db_get, user_id, key(later)) is not None:
            await post(later, user_id, render_for(user_id), keep_order=False)


def key(task: str) -> str:
    """The card's place among the Live lists, and its slot in the hub: one a task."""
    return f"{task}:hub"


async def post(task: str, user_id: int, render: Render, channel_id: int | None = None, slot: str = "", keep_order: bool = True) -> int | None:
    """A fresh copy of the task's card at the bottom of the hub, in place of the
    one that was there. None (and the old one taken away) with nothing to show."""
    channel_id = channel_id or hub.channel_id()
    if channel_id is None:
        return None
    shown = await render()
    if shown is None:
        await remove(task, user_id, slot)
        return None
    message_id = await cards.send(channel_id, shown, silent=True)
    if message_id is None:
        return None
    # One a slot in the hub: the newer one replaces the older (core/messages.py, with the tidy on)
    where = key(slot or task)
    old = await database.run(livelists.db_get, user_id, where)
    await messages.record(message_id, channel_id, lifetime=messages.REPLACED, slot=where, task=task)
    await livelists.placed(user_id, where, channel_id, message_id, task)
    if old is not None and old.message_id != message_id:
        await cards.delete(old.channel_id, old.message_id)
    if keep_order:
        await _keep_order(task, user_id)
    return message_id


async def remove(task: str, user_id: int, slot: str = "") -> bool:
    """Take the task's card away: there is nothing for it today. True if there was one."""
    old = await database.run(livelists.db_get, user_id, key(slot or task))
    if old is None:
        return False
    await cards.delete(old.channel_id, old.message_id)
    await livelists.forget({old.message_id})
    return True


async def refresh(task: str, user_id: int, render: Render, slot: str = "") -> str:
    """Bring the card up to date now: "edited", "posted" (there was none and now
    there is something to show), "removed" (nothing to show), or "" (nothing to do)."""
    shown = await render()
    there = await database.run(livelists.db_get, user_id, key(slot or task))
    if shown is None:
        return "removed" if there is not None and await remove(task, user_id, slot) else ""
    if there is not None and await cards.edit(there.channel_id, there.message_id, shown):
        return "edited"
    posted = await post(task, user_id, render, slot=slot)
    return "posted" if posted is not None else ""


def changed(task: str, user_id: int, render: Render, slot: str = "") -> None:
    """What the card shows has changed: brought up to date in the background,
    several changes close together being one edit (core/live.py)."""
    from core import live

    live.schedule(("hubcard", slot or task, user_id), lambda: refresh(task, user_id, render, slot))
