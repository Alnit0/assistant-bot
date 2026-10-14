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
# ---------------------------------------------------------------------------
Render = Callable[[], Awaitable["Card | None"]]


def key(task: str) -> str:
    """The card's place among the Live lists, and its slot in the hub: one a task."""
    return f"{task}:hub"


async def post(task: str, user_id: int, render: Render, channel_id: int | None = None) -> int | None:
    """A fresh copy of the task's card at the bottom of the hub, in place of the
    one that was there. None (and the old one taken away) with nothing to show."""
    channel_id = channel_id or hub.channel_id()
    if channel_id is None:
        return None
    shown = await render()
    if shown is None:
        await remove(task, user_id)
        return None
    message_id = await cards.send(channel_id, shown, silent=True)
    if message_id is None:
        return None
    # One a task in the hub: the newer one replaces the older (core/messages.py, with the tidy on)
    old = await database.run(livelists.db_get, user_id, key(task))
    await messages.record(message_id, channel_id, lifetime=messages.REPLACED, slot=key(task), task=task)
    await livelists.placed(user_id, key(task), channel_id, message_id, task)
    if old is not None and old.message_id != message_id:
        await cards.delete(old.channel_id, old.message_id)
    return message_id


async def remove(task: str, user_id: int) -> bool:
    """Take the task's card away: there is nothing for it today. True if there was one."""
    old = await database.run(livelists.db_get, user_id, key(task))
    if old is None:
        return False
    await cards.delete(old.channel_id, old.message_id)
    await livelists.forget({old.message_id})
    return True


async def refresh(task: str, user_id: int, render: Render) -> str:
    """Bring the card up to date now: "edited", "posted" (there was none and now
    there is something to show), "removed" (nothing to show), or "" (nothing to do)."""
    shown = await render()
    there = await database.run(livelists.db_get, user_id, key(task))
    if shown is None:
        return "removed" if there is not None and await remove(task, user_id) else ""
    if there is not None and await cards.edit(there.channel_id, there.message_id, shown):
        return "edited"
    posted = await post(task, user_id, render)
    return "posted" if posted is not None else ""


def changed(task: str, user_id: int, render: Render) -> None:
    """What the card shows has changed: brought up to date in the background,
    several changes close together being one edit (core/live.py)."""
    from core import live

    live.schedule(("hubcard", task, user_id), lambda: refresh(task, user_id, render))
