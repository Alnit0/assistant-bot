import re

from core import livelists
from core.actions import ADD, CHANGE, INTEGER, ITEMS, REMOVE, SET, Action, Entry, Field, LiveReply, Proposal, Request, State
from core.actions import LAST, change_field, flag, is_guessed, is_reference, merge_items, point_at
from core.errors import UserError
from tasks.lab import state

# ---------------------------------------------------------------------------
# Two small demo tasks for trying out the router's way before any real task
# uses it: a shopping list and a packing list. They are offered to the router
# only on the dev database (`python main.py --dev`), and keep their lists in
# the lab's own table.
#
# Between them they exercise everything: one card for several items; adding
# to, setting and removing what is already there, shown before -> after; a
# warning (⚠️) whose fix is applied; a genuine guess (❓: "a few eggs"); a
# reply that corrects a card; a card that can't be undone; actions that
# answer straight away; a Live list; and a tie ("add socks" fits both).
#
# No discord.py: the lists are plain values and every word comes from here.
# ---------------------------------------------------------------------------
MAX_QUANTITY = 20
BAGS = ("carry-on", "checked")


def _key(kind: str, user_id: int) -> str:
    return f"demo:{kind}:{user_id}"


async def _items(kind: str, user_id: int) -> list[dict]:
    return (await state.get(_key(kind, user_id)) or {}).get("items", [])


async def _save(kind: str, user_id: int, items: list[dict]) -> None:
    await state.put(_key(kind, user_id), {"items": items}, user_id)


def singular(name: str) -> str:
    """A name with its last word in the singular, lower case, for telling
    whether two names are the same thing: "Eggs" and "egg", "loaves" and
    "loaf", "tomatoes" and "tomato". Only for comparing: what is shown and
    kept is always the name as it was typed."""
    words = re.sub(r"\s+", " ", name.strip().lower()).split(" ")
    last = words[-1]
    if last.endswith("ves") and len(last) > 4:
        last = last[:-3] + "f"
    elif last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif re.search(r"(ch|sh|ss|x|z|o)es$", last):
        last = last[:-2]
    elif last.endswith("s") and not last.endswith(("ss", "us", "is")) and len(last) > 3:
        last = last[:-1]
    return " ".join([*words[:-1], last])


def same_item(one: str, other: str) -> bool:
    return singular(one) == singular(other)


def _find(items: list[dict], name: str, loosely: bool = False) -> dict | None:
    """The item a name means: the same thing, singular or plural ("milk" finds
    "milks"). With `loosely`, for ticking off, part of a name will do if only
    one item has it ("milk" finds "oat milk")."""
    same = [item for item in items if same_item(item["item"], name)]
    if same:
        return same[0]
    if loosely:
        wanted = singular(name)
        partial = [item for item in items if wanted in singular(item["item"])]
        if len(partial) == 1:
            return partial[0]
    return None


def _shopping_text(items: list[dict]) -> str:
    if not items:
        return "🛒 The shopping list is empty."
    return "\n".join(["## 🛒 Shopping list", *[f"- **{item['item']}** × {item['quantity']}" for item in items]])


def _packing_text(items: list[dict]) -> str:
    if not items:
        return "🧳 The packing list is empty."
    return "\n".join(["## 🧳 Packing list", *[f"- **{item['item']}** · {item['bag']} bag" for item in items]])


def _list_changed(kind: str, user_id: int) -> None:
    """The list changed: the copy last shown on request is brought up to date in place."""
    text = _shopping_text if kind == "shopping" else _packing_text

    async def render() -> str:
        return text(await _items(kind, user_id))

    livelists.changed(user_id, kind, render)


def _count(number: int, noun: str = "item") -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


# ---------------------------------------------------------------------------
# Shopping
# ---------------------------------------------------------------------------
def _changes(request: Request, data: dict, saved: list[dict], amount: str | None) -> tuple[list[dict], list[str], str | None, str | None]:
    """What a card holds once this message is taken in: the open card's items
    (if it corrects one) with the message's changes merged in by code. Also
    the names it was asked to remove that are nowhere, the item mentioned last
    (for the next "it"), and the item an "it" was taken to be when that was a
    guess.

    "It" is resolved here, never by Claude: the last thing mentioned on the
    card. With no card there is nothing mentioned to go by, so it is taken as
    the newest thing on the list and flagged."""
    previous = request.previous or {}
    pending = previous.get("items", [])
    last = previous.get(LAST) or (pending[-1]["item"] if pending else None)
    taken_as = None
    if last is None and saved and any(is_reference(change.get("item")) for change in data["items"]):
        last = taken_as = saved[-1]["item"]
    asked = point_at(data["items"], "item", last)
    merged, nowhere = merge_items(
        pending, asked, amount=amount, same=same_item, exists=lambda name: _find(saved, name) is not None,
        said=request.text,
    )
    return merged, nowhere, (asked[-1]["item"] if asked else last), taken_as


def _guessed_names(data: dict, guessed: frozenset, *fields: str) -> set[str]:
    """The items of this message that Claude guessed at: the item itself ("it"
    when it wasn't clear which), or one of these fields of it."""
    return {
        singular(item["item"])
        for index, item in enumerate(data["items"])
        if is_guessed(guessed, "items", index) or any(is_guessed(guessed, "items", index, name) for name in fields)
    }


async def shop_change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """One card for everything asked for: a line an item. Something already on
    the list shows what it is now and what it will be (5 → 7)."""
    saved = await _items("shopping", request.user.id)
    changes, nowhere, last, taken_as = _changes(request, data, saved, "quantity")
    unsure = _guessed_names(data, guessed, "quantity") | ({singular(taken_as)} if taken_as else set())
    lines, items = [], []
    warnings = [f"{name} isn't on the list: nothing to remove" for name in nowhere]
    for change in changes:
        name, what, amount = change["item"], change.get(CHANGE, ADD), change.get("quantity", 1)
        there = _find(saved, name)
        mark = singular(name) in unsure
        if what == REMOVE:
            lines.append(flag(f"{there['item']} · × {there['quantity']} → removed", mark))
            items.append({"item": there["item"], CHANGE: REMOVE})
            continue
        if amount < 1:
            raise UserError(f"How many {name}? It has to be at least 1 (or say to remove it).")
        # Python does the sum: adding is on top of what is there, setting replaces it
        before = there["quantity"] if there is not None else None
        after = before + amount if what == ADD and before is not None else amount
        if after > MAX_QUANTITY:
            warnings.append(f"{name}: {after} is more than the list takes, {MAX_QUANTITY} at most")
            amount, after = amount - (after - MAX_QUANTITY), MAX_QUANTITY
        if before is None:
            lines.append(f"{name} · {flag(f'× {after}', mark)}")
        elif before == after:
            lines.append(f"{name} · {flag(f'× {after}', mark)}")
            warnings.append(f"{name} is already × {before}: nothing changes")
        else:
            lines.append(f"{name} · {flag(f'{before} → {after}', mark)}")
        items.append({"item": name, "quantity": amount, CHANGE: what})
    if not items:
        raise UserError(f"{', '.join(nowhere)} isn't on the shopping list.")
    # "new" while nothing on the list is touched: an amount set on a card not yet saved is still new
    new = all(item.get(CHANGE) != REMOVE and _find(saved, item["item"]) is None for item in items)
    return Proposal(lines=tuple(lines), data={"items": items, LAST: last}, warnings=tuple(warnings), kind="new" if new else "change")


async def shop_change_save(request: Request, data: dict) -> str:
    """Save: apply each change to the list as it is now. The sums are done here."""
    items = await _items("shopping", request.user.id)
    added = changed = removed = 0
    last = ""
    for change in data["items"]:
        there = _find(items, change["item"])
        what = change.get(CHANGE, ADD)
        if what == REMOVE:
            if there is not None:
                items.remove(there)
                removed += 1
                last = f"**{there['item']}** removed from the shopping list"
            continue
        if there is None:
            total = min(MAX_QUANTITY, change["quantity"])
            items.append({"item": change["item"], "quantity": total})
            added += 1
        else:
            total = change["quantity"] if what == SET else there["quantity"] + change["quantity"]
            there["quantity"] = total = min(MAX_QUANTITY, total)
            there["item"] = change["item"]  # the name as it was typed this time
            changed += 1
        last = f"**{change['item']}** × {total} is on the shopping list"
    await _save("shopping", request.user.id, items)
    _list_changed("shopping", request.user.id)
    if added + changed + removed == 1:
        return f"✅ Saved · 🛒 {last}"
    if not changed and not removed:
        return f"✅ Saved · 🛒 {_count(added)} added to the shopping list"
    parts = [f"{number} {word}" for number, word in ((added, "added"), (changed, "changed"), (removed, "removed")) if number]
    return f"✅ Saved · 🛒 shopping list updated: {', '.join(parts)}"


async def shop_change_check(request: Request, data: dict) -> str:
    """Read the list back: what was removed is gone, what was set has that
    amount, what was added is there with at least that many."""
    items = await _items("shopping", request.user.id)
    wrong = []
    for change in data["items"]:
        there, what = _find(items, change["item"]), change.get(CHANGE, ADD)
        if what == REMOVE:
            if there is not None:
                wrong.append(f"{change['item']} is still on the list")
        elif there is None:
            wrong.append(f"{change['item']} is not on the list")
        elif what == SET and there["quantity"] != min(MAX_QUANTITY, change["quantity"]):
            wrong.append(f"{change['item']} is × {there['quantity']}, not × {change['quantity']}")
        elif what == ADD and there["quantity"] < min(MAX_QUANTITY, change["quantity"]):
            wrong.append(f"{change['item']} is only × {there['quantity']}")
    return "; ".join(wrong)


async def shop_list(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    # A list shown on request is Live: this copy is rewritten in place when the list changes
    return LiveReply("shopping", _shopping_text(await _items("shopping", request.user.id)))


async def shop_tick(request: Request, data: dict, guessed: frozenset) -> str:
    items = await _items("shopping", request.user.id)
    ticked, missing = [], []
    for asked in data["items"]:
        found = _find(items, asked["item"], loosely=True)
        if found is None:
            missing.append(asked["item"])
        else:
            items.remove(found)
            ticked.append(found)
    if not ticked:
        names = ", ".join(item["item"] for item in items) or "nothing"
        raise UserError(f"“{', '.join(missing)}” isn't on the shopping list. On it: {names}.")
    await _save("shopping", request.user.id, items)
    _list_changed("shopping", request.user.id)
    # Name what is left: "1 left to buy" after "milk" read as if milk went from 3 to 1
    left = ", ".join(item["item"] for item in items)
    done = "☑️ Ticked off " + ", ".join(f"**{item['item']}** × {item['quantity']}" for item in ticked)
    said = f"{done} · still to buy: {left}" if items else f"{done} · nothing left to buy"
    # Nothing is dropped without a word
    return said + (f"\n⚠️ Not on the list: {', '.join(missing)}" if missing else "")


async def shop_clear_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    items = await _items("shopping", request.user.id)
    if not items:
        raise UserError("The shopping list is already empty.")
    return Proposal(
        lines=(f"Clear the whole shopping list: {_count(len(items))}.", "**This can't be undone.**"),
        data={},
        kind="clear",
        destructive=True,
        confirm_label="Clear for good",
    )


async def shop_clear_save(request: Request, data: dict) -> str:
    await _save("shopping", request.user.id, [])
    _list_changed("shopping", request.user.id)
    return "🗑️ The shopping list is cleared."


_NAME = (
    "exactly as the user named it, without the amount and without a leading a, an, the, my or some: keep "
    "their spelling and their singular or plural (\"milks\" stays milks, \"an egg\" is egg, \"a hat\" is hat)."
)

async def shop_clear_check(request: Request, data: dict) -> str:
    left = await _items("shopping", request.user.id)
    return f"{_count(len(left))} still on the shopping list" if left else ""


async def _shopping_state(request: Request) -> State:
    # A line an item: only what the message could mean is sent when the list is long
    items = await _items("shopping", request.user.id)
    return State("On the shopping list now", tuple(f"{item['item']} × {item['quantity']}" for item in items))


async def _packing_state(request: Request) -> State:
    items = await _items("packing", request.user.id)
    return State("On the packing list now", tuple(f"{item['item']} ({item['bag']} bag)" for item in items))


SHOPPING = Entry(
    name="shopping",
    icon="🛒",
    live_state=_shopping_state,
    only_for=(
        "A demo shopping list, used for testing the bot: things to buy from a shop, changing or removing "
        "them, ticking them off, and asking what is on it. Not things to pack for a trip, and not pills, "
        "timers or reminders."
    ),
    examples=("add milk to the shopping list", "what do I need to buy?", "got the bread"),
    hint="Try “add milk to the shopping list”.",
    actions=(
        Action(
            "demo_shop_change",
            "Add things to the shopping list, change how many of something, or remove something from it. "
            "Examples: \"add honey, jam and 5 eggs\" -> items honey; jam; eggs with quantity 5. \"make the "
            "eggs 7\" -> eggs, quantity 7, change set. \"add 3 more milk\" -> milk, quantity 3, change add. "
            "\"remove the jam\" or \"take jam off the list\" -> jam, change remove. Use this, not the "
            "bought one, when the user says to remove or take off rather than that they got it.",
            (
                Field(
                    "items",
                    "Each thing the message is about, one item each, in the order said.",
                    ITEMS,
                    required=True,
                    item_fields=(
                        Field("item", f"What it is, {_NAME}", required=True),
                        Field(
                            "quantity",
                            "The number the user said, if they said one. Leave out if they didn't: one is "
                            "assumed, and that is not a guess. For a vague amount (\"a few\", \"some\", \"a "
                            "couple of\") give your best number and list it as guessed. Never add it to "
                            "anything yourself.",
                            INTEGER,
                        ),
                        change_field(),
                    ),
                ),
            ),
            prepare=shop_change_card,
            apply=shop_change_save,
            verify=shop_change_check,
        ),
        Action(
            "demo_shop_list",
            "The user asks what is on the shopping list, or what they need to buy.",
            needs_card=False,
            run=shop_list,
        ),
        Action(
            "demo_shop_tick",
            "The user has BOUGHT one or more things on the list (\"got the milk and the eggs\", \"bought "
            "bread\") -> items milk; eggs. Only for things bought, not for removing something unbought.",
            (
                Field(
                    "items",
                    "Each thing bought, one item each.",
                    ITEMS,
                    required=True,
                    item_fields=(Field("item", f"Which item, {_NAME}", required=True),),
                ),
            ),
            needs_card=False,
            run=shop_tick,
        ),
        Action(
            "demo_shop_clear",
            "The user wants the whole shopping list emptied or deleted.",
            prepare=shop_clear_card,
            apply=shop_clear_save,
            verify=shop_clear_check,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------
async def pack_change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    saved = await _items("packing", request.user.id)
    changes, nowhere, last, taken_as = _changes(request, data, saved, None)
    unsure = _guessed_names(data, guessed, "bag") | ({singular(taken_as)} if taken_as else set())
    lines, items = [], []
    warnings = [f"{name} isn't on the packing list: nothing to remove" for name in nowhere]
    for change in changes:
        name, what = change["item"], change.get(CHANGE, ADD)
        there = _find(saved, name)
        mark = singular(name) in unsure
        if what == REMOVE:
            lines.append(flag(f"{there['item']} · {there['bag']} bag → removed", mark))
            items.append({"item": there["item"], CHANGE: REMOVE})
            continue
        if there is None:
            bag = change.get("bag", "checked")  # no bag said: checked, and that is no guess
            lines.append(f"{name} · {flag(f'{bag} bag', mark)}")
            items.append({"item": name, "bag": bag, CHANGE: ADD})
        elif "bag" in change and change["bag"] != there["bag"]:
            lines.append(f"{name} · {flag(there['bag'] + ' bag → ' + change['bag'] + ' bag', mark)}")
            items.append({"item": name, "bag": change["bag"], CHANGE: SET})
        else:
            warnings.append(f"{there['item']} is already on the packing list ({there['bag']} bag): left as it is")
    if not items:
        raise UserError("That is all on the packing list already." if not nowhere else f"{', '.join(nowhere)} isn't on the packing list.")
    new = all(item[CHANGE] == ADD for item in items)
    return Proposal(lines=tuple(lines), data={"items": items, LAST: last}, warnings=tuple(warnings), kind="new" if new else "change")


async def pack_change_save(request: Request, data: dict) -> str:
    items = await _items("packing", request.user.id)
    added = changed = removed = 0
    last = ""
    for change in data["items"]:
        there = _find(items, change["item"])
        if change[CHANGE] == REMOVE:
            if there is not None:
                items.remove(there)
                removed += 1
                last = f"**{there['item']}** removed from the packing list"
        elif there is None:
            items.append({"item": change["item"], "bag": change["bag"]})
            added += 1
            last = f"**{change['item']}** goes in the {change['bag']} bag"
        elif change[CHANGE] == SET and there["bag"] != change["bag"]:
            there["bag"] = change["bag"]
            changed += 1
            last = f"**{there['item']}** moved to the {change['bag']} bag"
    if not added + changed + removed:
        raise UserError("That is all on the packing list already.")
    await _save("packing", request.user.id, items)
    _list_changed("packing", request.user.id)
    if added + changed + removed == 1:
        return f"✅ Saved · 🧳 {last}"
    if not changed and not removed:
        return f"✅ Saved · 🧳 {_count(added)} added to the packing list"
    parts = [f"{number} {word}" for number, word in ((added, "added"), (changed, "changed"), (removed, "removed")) if number]
    return f"✅ Saved · 🧳 packing list updated: {', '.join(parts)}"


async def pack_change_check(request: Request, data: dict) -> str:
    items = await _items("packing", request.user.id)
    wrong = []
    for change in data["items"]:
        there = _find(items, change["item"])
        if change[CHANGE] == REMOVE:
            if there is not None:
                wrong.append(f"{change['item']} is still on the packing list")
        elif there is None:
            wrong.append(f"{change['item']} is not on the packing list")
        elif change[CHANGE] == SET and there["bag"] != change["bag"]:
            wrong.append(f"{change['item']} is in the {there['bag']} bag")
    return "; ".join(wrong)


async def pack_list(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    return LiveReply("packing", _packing_text(await _items("packing", request.user.id)))


PACKING = Entry(
    name="packing",
    icon="🧳",
    live_state=_packing_state,
    only_for=(
        "A demo packing list for a trip, used for testing the bot: things to put in a bag, moving or removing "
        "them, and asking what is on it. Not things to buy, and not pills, timers or reminders."
    ),
    examples=("pack my passport in the carry-on", "what am I packing?"),
    hint="Try “pack my passport”.",
    actions=(
        Action(
            "demo_pack_change",
            "Put things on the packing list, move something to the other bag, or remove something from it. "
            "Examples: \"pack my passport in my hand luggage and a hat\" -> items passport with bag carry-on; "
            "hat. \"put the hat in the carry-on\" -> hat, bag carry-on, change set. \"don't pack the hat\" -> "
            "hat, change remove.",
            (
                Field(
                    "items",
                    "Each thing the message is about, one item each, in the order said.",
                    ITEMS,
                    required=True,
                    item_fields=(
                        Field("item", f"What it is, {_NAME}", required=True),
                        Field(
                            "bag",
                            "Which bag, if the user said. Leave out if they didn't: checked is assumed, and "
                            "that is not a guess.",
                            choices=BAGS,
                        ),
                        change_field(),
                    ),
                ),
            ),
            prepare=pack_change_card,
            apply=pack_change_save,
            verify=pack_change_check,
        ),
        Action(
            "demo_pack_list",
            "The user asks what is on the packing list.",
            needs_card=False,
            run=pack_list,
        ),
    ),
)

ENTRIES = [SHOPPING, PACKING]
