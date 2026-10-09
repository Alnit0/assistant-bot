from core.actions import INTEGER, Action, Entry, Field, Proposal, Request, flag
from core.errors import UserError
from tasks.lab import state

# ---------------------------------------------------------------------------
# Two small demo tasks for trying out the router's way before any real task
# uses it: a shopping list and a packing list. They are offered to the router
# only on the dev database (`python main.py --dev`), and keep their lists in
# the lab's own table.
#
# Between them they exercise everything: a confirm card with a guess (❓) and
# a warning (⚠️) whose fix is applied, a reply that corrects a card, a card
# that can't be undone, actions that answer straight away, a question, and a
# genuine tie ("add socks" fits both lists).
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


def _find(items: list[dict], name: str) -> dict | None:
    wanted = name.strip().lower()
    exact = [item for item in items if item["item"].lower() == wanted]
    partial = [item for item in items if wanted in item["item"].lower()]
    found = exact or partial
    return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Shopping
# ---------------------------------------------------------------------------
async def shop_add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    item = data["item"]
    quantity = data.get("quantity", 1)
    warnings = []
    if quantity > MAX_QUANTITY:
        warnings.append(f"{quantity} is more than the list takes: {MAX_QUANTITY} at most")
        quantity = MAX_QUANTITY
    if quantity < 1:
        raise UserError("How many? It has to be at least 1.")
    on_list = _find(await _items("shopping", request.user.id), item)
    if on_list is not None:
        warnings.append(f"{on_list['item']} is already on the list (× {on_list['quantity']}): this adds to it")
    # Not said is a guess too: one, unless told otherwise
    assumed = "quantity" in guessed or "quantity" not in data
    return Proposal(
        lines=(f"**{item}** · {flag(f'× {quantity}', assumed)}",),
        data={"item": item, "quantity": quantity},
        warnings=tuple(warnings),
    )


async def shop_add_save(request: Request, data: dict) -> str:
    items = await _items("shopping", request.user.id)
    on_list = _find(items, data["item"])
    if on_list is not None:
        on_list["quantity"] = min(MAX_QUANTITY, on_list["quantity"] + data["quantity"])
        total = on_list["quantity"]
    else:
        items.append({"item": data["item"], "quantity": data["quantity"]})
        total = data["quantity"]
    await _save("shopping", request.user.id, items)
    return f"✅ Saved · 🛒 **{data['item']}** × {total} is on the shopping list"


async def shop_list(request: Request, data: dict, guessed: frozenset) -> str:
    items = await _items("shopping", request.user.id)
    if not items:
        return "🛒 The shopping list is empty."
    return "\n".join(["## 🛒 Shopping list", *[f"- **{item['item']}** × {item['quantity']}" for item in items]])


async def shop_tick(request: Request, data: dict, guessed: frozenset) -> str:
    items = await _items("shopping", request.user.id)
    found = _find(items, data["item"])
    if found is None:
        names = ", ".join(item["item"] for item in items) or "nothing"
        raise UserError(f"“{data['item']}” isn't on the shopping list. On it: {names}.")
    items.remove(found)
    await _save("shopping", request.user.id, items)
    # Name what is left: "1 left to buy" after "milk" read as if milk went from 3 to 1
    left = ", ".join(item["item"] for item in items)
    done = f"☑️ Ticked off **{found['item']}** × {found['quantity']}"
    return f"{done} · still to buy: {left}" if items else f"{done} · nothing left to buy"


async def shop_clear_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    items = await _items("shopping", request.user.id)
    if not items:
        raise UserError("The shopping list is already empty.")
    return Proposal(
        lines=(f"Clear the whole shopping list: {len(items)} item{'s' if len(items) != 1 else ''}.", "**This can't be undone.**"),
        data={},
        kind="clear",
        destructive=True,
        confirm_label="Clear for good",
    )


async def shop_clear_save(request: Request, data: dict) -> str:
    await _save("shopping", request.user.id, [])
    return "🗑️ The shopping list is cleared."


SHOPPING = Entry(
    name="shopping",
    icon="🛒",
    only_for=(
        "A demo shopping list, used for testing the bot: things to buy from a shop, ticking them off, and "
        "asking what is on it. Not things to pack for a trip, and not pills, timers or reminders."
    ),
    examples=("add milk to the shopping list", "what do I need to buy?", "got the bread"),
    hint="Try “add milk to the shopping list”.",
    actions=(
        Action(
            "demo_shop_add",
            "Put something on the shopping list. Example: \"add two cartons of oat milk\" -> item oat milk, quantity 2.",
            (
                Field("item", "What to buy, as the user named it, without the amount.", required=True),
                Field("quantity", "How many. If the user didn't say, give 1 and list quantity as guessed.", INTEGER),
            ),
            prepare=shop_add_card,
            apply=shop_add_save,
        ),
        Action(
            "demo_shop_list",
            "The user asks what is on the shopping list, or what they need to buy.",
            needs_card=False,
            run=shop_list,
        ),
        Action(
            "demo_shop_tick",
            "The user has bought something on the list, or wants one item taken off it. Example: \"got the milk\" -> item milk.",
            (Field("item", "Which item, as the user named it.", required=True),),
            needs_card=False,
            run=shop_tick,
        ),
        Action(
            "demo_shop_clear",
            "The user wants the whole shopping list emptied or deleted.",
            prepare=shop_clear_card,
            apply=shop_clear_save,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------
async def pack_add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    bag = data.get("bag", "checked")
    assumed = "bag" in guessed or "bag" not in data
    return Proposal(lines=(f"**{data['item']}** · {flag(f'{bag} bag', assumed)}",), data={"item": data["item"], "bag": bag})


async def pack_add_save(request: Request, data: dict) -> str:
    items = await _items("packing", request.user.id)
    if _find(items, data["item"]) is not None:
        raise UserError(f"{data['item']} is already on the packing list.")
    items.append({"item": data["item"], "bag": data["bag"]})
    await _save("packing", request.user.id, items)
    return f"✅ Saved · 🧳 **{data['item']}** goes in the {data['bag']} bag"


async def pack_list(request: Request, data: dict, guessed: frozenset) -> str:
    items = await _items("packing", request.user.id)
    if not items:
        return "🧳 The packing list is empty."
    return "\n".join(["## 🧳 Packing list", *[f"- **{item['item']}** · {item['bag']} bag" for item in items]])


PACKING = Entry(
    name="packing",
    icon="🧳",
    only_for=(
        "A demo packing list for a trip, used for testing the bot: things to put in a bag, and asking what "
        "is on it. Not things to buy, and not pills, timers or reminders."
    ),
    examples=("pack my passport in the carry-on", "what am I packing?"),
    hint="Try “pack my passport”.",
    actions=(
        Action(
            "demo_pack_add",
            "Put something on the packing list. Example: \"pack my passport in my hand luggage\" -> item passport, bag carry-on.",
            (
                Field("item", "What to pack, as the user named it.", required=True),
                Field("bag", "Which bag. If the user didn't say, give checked and list bag as guessed.", choices=BAGS),
            ),
            prepare=pack_add_card,
            apply=pack_add_save,
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
