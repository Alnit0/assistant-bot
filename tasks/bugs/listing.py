from core import livelists
from core.cards import Card
from tasks.bugs import rules, store

# ---------------------------------------------------------------------------
# The list of open bugs, shown on request (`bugs`, "show my open bugs"). It is
# Live (core/livelists.py): the latest copy is rewritten in place when a bug
# is logged, closed or re-opened, or gets a note. No Discord.
# ---------------------------------------------------------------------------
KEY = "bugs"
TASK = "bugs"


async def text(user_id: int) -> str:
    return rules.list_text(await store.open_items(user_id))


async def card(user_id: int) -> Card:
    """The list as a card: its words, and the same list drawn (CARDS_V2)."""
    items = await store.open_items(user_id)
    return Card(rules.list_text(items), (), rules.list_layout(items))


def changed(user_id: int | None) -> None:
    """The open bugs changed: the list last shown on request follows, in place."""
    if user_id is None:
        return

    async def render() -> Card:
        return await card(user_id)

    livelists.changed(user_id, KEY, render)
