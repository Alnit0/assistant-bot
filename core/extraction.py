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
    not_this: bool = False
    reason: str = ""  # why nothing fitted, or what was wrong with what came back. For the log

    @property
    def fitted(self) -> bool:
        return self.action is not None

    def as_log(self) -> dict:
        """What was extracted, for message_log."""
        if self.action is None:
            return {"task": self.entry.name, "action": NOT_THIS if self.not_this else NONE, "reason": self.reason}
        return {"task": self.entry.name, "action": self.action.name, "data": self.data, "guessed": sorted(self.guessed)}


def rules(entry: Entry) -> str:
    return (
        f"You turn one message from the user of a personal assistant bot into one action of its "
        f"{entry.name} task ({entry.only_for}). You answer only by calling exactly one tool. Write no text: "
        "nothing you write is read, and the bot's own code tells the user what happened.\n"
        "- Pick the one action that fits and fill in its fields from the user's words.\n"
        "- Never ask a question and never leave a detail out because it is unclear: give your best guess, "
        f"and list the name of every field you guessed or assumed in `{actions.GUESSED}`. The user is shown "
        "each guess marked for them to accept or correct, so a marked guess is always better than nothing.\n"
        "- Do not list a field the user stated outright.\n"
        "- Copy names and wording as the user gave them. Follow each field's description for its form.\n"
        "- Take ids and existing names from the state given with the message, when there is one.\n"
        f"- Only if no action fits at all, or the message makes no sense for this task, call `{NONE}`."
    )


FOLLOW_UP_RULES = (
    "\n- A card is open, waiting for the user to accept it or say what to change. If the message is a "
    "correction or an addition to that card, call the card's action again with ALL of its data: every "
    "field as it stands on the card, changed only where the message changes it. A field the user has now "
    f"stated is no longer a guess: leave it out of `{actions.GUESSED}`; keep the ones still guessed.\n"
    "- If the message asks for a different action of this task, call that action.\n"
    f"- If the message is not about the card or this task at all, call `{NOT_THIS}`."
)


def system_blocks(entry: Entry, follow_up: bool = False) -> list[dict]:
    """The instructions for this task: fixed text, marked for caching."""
    text = rules(entry) + (FOLLOW_UP_RULES if follow_up else "")
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
    said: str = ""  # what the user first asked for


def user_turn(message: str, state: str = "", card: OpenCard | None = None, earlier: str = "") -> str:
    """What changes from message to message: the task's state, the open card
    and the message. Never part of the cached blocks."""
    parts = []
    if state:
        parts.append(f"The task's state, read just now:\n{state}")
    if card is not None:
        lines = [
            "The open card:",
            f"- action: {card.action}",
            f"- data: {json.dumps(card.data, ensure_ascii=False, sort_keys=True)}",
            f"- still guessed: {', '.join(card.guessed) or 'nothing'}",
        ]
        if card.said:
            lines.append(f"- it came from the user saying: {card.said}")
        parts.append("\n".join(lines))
    if earlier:
        parts.append(f"Just before this, the user said: {earlier}")
    parts.append(f"The message:\n{message}")
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
        data, guessed = actions.validate(action, raw)
    except Invalid as error:
        return Extracted(entry, reason=f"{name}: {error}")
    return Extracted(entry, action, data, guessed)


async def extract(
    entry: Entry, message: str, state: str = "", card: OpenCard | None = None, earlier: str = ""
) -> Extracted:
    """Ask Claude to fill in one of this task's actions. One request."""
    follow_up = card is not None
    called = await llm.call_tool(
        system_blocks(entry, follow_up),
        user_turn(message, state, card, earlier),
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
