import json
import logging
from dataclasses import dataclass

from core import actions, costs, llm
from core.actions import NONE, NOT_THIS, Action, Entry, Invalid
from core.config import STRICT_SCHEMAS

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Extraction: one request for one task. Claude is given only that task's
# actions and must call exactly one of them, filled in, or `none`. It writes
# no prose: nothing it says is read, only the call. Code checks the call
# against the action's schema (core/actions.py) whatever the API promised.
#
# Every detail gets a best guess, never a question: what was guessed is
# listed in `guessed`, and the task shows it flagged with ❓ for the user to
# accept or correct.
#
# A follow-up (a reply to an open card) is the same request with the card's
# current data added, and one more way out: `not_this`, when the message has
# nothing to do with the card.
# ---------------------------------------------------------------------------
MAX_TOKENS = 700


@dataclass(frozen=True)
class Extracted:
    """What extraction made of a message for one task."""

    entry: Entry
    action: Action | None = None  # None: nothing fitted (see `reason`) or it wasn't about the card
    data: dict | None = None
    guessed: frozenset = frozenset()
    # What the user asked for that is not in `data`: said on the card or in the reply
    not_included: tuple[str, ...] = ()
    not_this: bool = False
    reason: str = ""  # why nothing fitted, or what was wrong with what came back. For the log

    @property
    def fitted(self) -> bool:
        return self.action is not None

    def as_log(self) -> dict:
        """What was extracted, for message_log."""
        if self.action is None:
            return {"task": self.entry.name, "action": NOT_THIS if self.not_this else NONE, "reason": self.reason}
        logged = {"task": self.entry.name, "action": self.action.name, "data": self.data, "guessed": sorted(self.guessed)}
        if self.not_included:
            logged["not_included"] = list(self.not_included)
        return logged


def rules(entry: Entry) -> str:
    return (
        f"You turn one message from the user of a personal assistant bot into one action of its "
        f"{entry.name} task ({entry.only_for}). You answer only by calling exactly one tool. Write no text: "
        "nothing you write is read, and the bot's own code tells the user what happened.\n"
        "- Pick the one action that fits and fill in its fields from the user's words.\n"
        "- A message can ask for several things at once (\"add honey, jam and 5 eggs\"). A field that is a "
        "list of items takes ALL of them, each as its own item, in the order they were said. Never keep "
        "only the first.\n"
        f"- Nothing may be dropped. Anything the user asked of THIS task that you cannot put into the action "
        f"goes in `{actions.NOT_INCLUDED}`, word for word, and the user is told. Leave it empty when "
        "everything is covered. A part of the message that is plainly for something else is not yours to "
        "report when you are told it is being handled elsewhere.\n"
        "- Never ask a question and never leave a detail out because it is unclear: give your best guess, "
        f"and name what you guessed in `{actions.GUESSED}`. The user is shown each guess marked for them to "
        "accept or correct, so a marked guess is always better than nothing.\n"
        "- A guess is a value you chose between readings: a time that could be morning or evening, a "
        "vague amount (\"a few\"), something implied but not said. A field the user simply didn't mention "
        "is NOT a guess: leave it out and its default applies (no amount means one). Never list a default, "
        "and never list a field the user stated outright.\n"
        "- Copy names and wording as the user gave them. Follow each field's description for its form.\n"
        "- \"It\", \"that\", \"this one\" and \"them\" mean what the user mentioned LAST: the last thing they "
        "named, not the first on a list. Use what they have said so far to find it. If you cannot tell "
        f"which is meant, take the last one named and list it in `{actions.GUESSED}` (by its place, e.g. "
        "`items[0]`), so the user sees the guess.\n"
        "- Take ids and existing names from the state given with the message, when there is one.\n"
        f"- Only if no action fits at all, or the message makes no sense for this task, call `{NONE}`."
    )


FOLLOW_UP_RULES = (
    "\n- A card is open, waiting for the user to accept it or say what to change. If the message is a "
    "correction or an addition to that card, call the card's action again.\n"
    "- The lines already on the card are shown to you so that you know what \"it\" or \"the eggs\" "
    "means. They are KEPT by the bot's code: they are not yours to send back. For a field that is a list "
    "of items, return ONLY the changes THIS message makes: the item it changes, the one it removes, the "
    "ones it adds. An item this message does not name or point at must not be in your answer at all: "
    "sending a line back unchanged would add it a second time. Do no sums: the code works out the "
    "totals. \"Make the eggs 6\" is eggs alone, set to 6; \"remove the jam\" is jam alone, removed; "
    "\"add 3 milk\" is milk alone, 3 more. \"and jam\", \"also jam\", \"plus jam\", \"jam too\" and "
    "\"jam as well\" are jam alone, whatever is on the card: \"and\", \"also\", \"plus\" and \"too\" "
    "never mean repeat the card.\n"
    "- Every other field of the card goes back as it stands on the card, changed only where the message "
    f"changes it. A field the user has now stated is no longer a guess: leave it out of `{actions.GUESSED}`.\n"
    "- If the message asks for a different action of this task, call that action.\n"
    f"- If the message is not about the card or this task at all, call `{NOT_THIS}`: the card is then "
    "left as it is and the message is read afresh."
)


AFTER_LIST_RULES = (
    "\n- The user has just been shown this task's list, and the message came straight after it, so a "
    "short request that names no task (\"add milk\") is for this task: fill it in as usual.\n"
    f"- If the message is plainly for something else, call `{NOT_THIS}` and it is read afresh."
)


def system_blocks(entry: Entry, follow_up: bool = False, after_list: bool = False) -> list[dict]:
    """The instructions for this task: fixed text, marked for caching."""
    text = rules(entry) + (FOLLOW_UP_RULES if follow_up else "") + (AFTER_LIST_RULES if after_list else "")
    return [{"type": "text", "text": text, "cache_control": llm.CACHED}]


def tools(entry: Entry, follow_up: bool = False, strict: bool | None = None) -> list[dict]:
    """The task's actions as tools, and the ways of saying none of them fits."""
    strict = STRICT_SCHEMAS if strict is None else strict
    found = [actions.tool(action, strict) for action in entry.actions]
    found.append(actions.NONE_TOOL)
    if follow_up:
        found.append(actions.NOT_THIS_TOOL)
    # Cache everything up to and including the last tool definition
    found[-1] = {**found[-1], "cache_control": llm.CACHED}
    return found


@dataclass(frozen=True)
class OpenCard:
    """The card a follow-up is about: what it would save, and how it came to be."""

    action: str
    data: dict
    guessed: tuple[str, ...] = ()
    said: str = ""  # everything the user has said about it, oldest first, one message a line
    # The user's last message about it, when that change was a mistake they are
    # now correcting ("No, …"): it has been undone, and `data` is the card before it
    undone: str = ""


def standing(card: OpenCard) -> str:
    """A request as it stands on a card, corrections included, for the task it is
    being moved to ("no, packing"): what was asked, and what it had become."""
    first = card.said.split("\n")[0]
    return (
        f"{first}\n\n(That request was first put on a card of another task and corrected there. As it "
        f"stood on that card: {json.dumps(card.data, ensure_ascii=False, sort_keys=True)}. Carry over "
        "EVERY item on it. A detail this task has no place for (an amount, say) is left off the item; the "
        "item itself is never left out.)"
    )


def user_turn(
    message: str, state: str = "", card: OpenCard | None = None, earlier: str = "", elsewhere: str = ""
) -> str:
    """What changes from message to message: the task's state, the open card
    and the message. Never part of the cached blocks. `elsewhere` says what
    other parts of the message are being dealt with by something else."""
    parts = []
    if state:
        parts.append(f"The task's state, read just now:\n{state}")
    if card is not None:
        lines = ["The open card:", f"- action: {card.action}"]
        # A list of items is shown as the card's lines, to be read and not sent
        # back: only this message's changes are wanted, and code applies them
        rest = {}
        for name, value in sorted(card.data.items()):
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                lines.append(f"- `{name}`, the lines already on the card (kept by the bot's code: do NOT send them back):")
                lines += [f"  {place}. " + ", ".join(f"{key}: {item[key]}" for key in item) for place, item in enumerate(value, 1)]
            else:
                rest[name] = value
        if rest:
            lines.append(f"- data: {json.dumps(rest, ensure_ascii=False, sort_keys=True)}")
        lines.append(f"- still guessed: {', '.join(card.guessed) or 'nothing'}")
        said = [line for line in card.said.split("\n") if line.strip()]
        if said:
            lines.append("- what the user has said about it, oldest first: " + " | ".join(said))
        if card.undone:
            lines.append(
                f"- the user's last change (\"{card.undone}\") was a mistake and has been UNDONE: what is above "
                "is the card as it was before it. The message below says what they meant instead: apply that, "
                "and nothing of the undone change."
            )
        parts.append("\n".join(lines))
    if elsewhere:
        parts.append(
            f"Other parts of this message are being handled elsewhere ({elsewhere}). They are not this task's: "
            f"do not act on them, and do not list them in `{actions.NOT_INCLUDED}`."
        )
    if earlier:
        parts.append(
            f"Just before this, the user asked: {earlier}\n"
            "They were shown a card from a different task, and the message below came next. If it only says "
            "which task or list the earlier request was meant for (\"no, shopping\", \"I meant the other "
            "list\"), fill in the action from the EARLIER request: the words that redirect it are never an "
            "item, a name or any other value. If the message below is a request of its own, use it and "
            "ignore the earlier one."
        )
    parts.append(f"The message:\n{message}")
    if card is not None and any("do NOT send them back" in line for line in parts[1 if state else 0].split("\n")):
        # Last, where it is read last: the commonest slip is the card coming back with the change
        parts.append(
            "Answer with the changes this message makes and nothing else. A line of the card that the message "
            "does not name or point at stays out of your answer."
        )
    return "\n\n".join(parts)


def read(entry: Entry, called: tuple[str, dict] | None, follow_up: bool = False) -> Extracted:
    """What a tool call from extraction means, checked in code. A call that
    doesn't fit its schema is "nothing fitted", with the reason kept."""
    if called is None:
        return Extracted(entry, reason="extraction returned no tool call")
    name, raw = called
    said = raw.get("reason", "") if isinstance(raw, dict) else ""
    if name == NOT_THIS and follow_up:
        return Extracted(entry, not_this=True, reason=str(said))
    if name in (NONE, NOT_THIS):
        return Extracted(entry, reason=str(said) or "nothing fitted")
    action = entry.action(name)
    if action is None:
        return Extracted(entry, reason=f"`{name}` is not an action of {entry.name}")
    try:
        checked = actions.validate(action, raw)
    except Invalid as error:
        return Extracted(entry, reason=f"{name}: {error}")
    return Extracted(entry, action, checked.data, checked.guessed, checked.not_included)


async def extract(
    entry: Entry, message: str, state: str = "", card: OpenCard | None = None, earlier: str = "",
    after_list: bool = False, elsewhere: str = "",
) -> Extracted:
    """Ask Claude to fill in one of this task's actions. One request.

    With `card`, the message is a follow-up to that open card. With
    `after_list`, it came straight after this task's list was shown. Either
    way Claude may answer `not_this`."""
    follow_up = card is not None or after_list
    called = await llm.call_tool(
        system_blocks(entry, card is not None, after_list),
        user_turn(message, state, card, earlier, elsewhere),
        tools(entry, follow_up),
        choice={"type": "any"},
        purpose=costs.PURPOSE_EXTRACTION,
        task=entry.name,
        max_tokens=MAX_TOKENS,
    )
    found = read(entry, called, follow_up)
    if not found.fitted and not found.not_this:
        log.info("Extraction for %s fitted nothing: %s", entry.name, found.reason)
    return found
