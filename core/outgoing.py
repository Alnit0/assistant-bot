import logging
import re

from core import trace

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The last check on what the bot says, run on every message it sends through
# core/cards.py and core/context.py.
#
# Two things must never reach the user, whoever wrote the text:
#
#   internal labels   "(nothing)", an action's name ("pill_add"), the marker
#                     for a pronoun ("@that"), a sentinel of the chat prompt.
#                     One showing up is a bug in the code that built the text;
#                     it is taken out, logged, and noted in the trace.
#   offers            a reply never ends by offering to do something or by
#                     asking "want me to…?": the bot does it, or it doesn't.
#
# Pure apart from the log line and the trace note.
# ---------------------------------------------------------------------------
# Never words of the bot's, wherever they appear
_FIXED = ("(nothing)", "[[about-my-data]]", "@that", "not_this", "not_included", "_last")
_names: set[str] = set()

_OFFER = re.compile(
    r"(?:^|(?<=[.!?…])\s+|\n+)"
    r"(?:(?:want|would you like|shall|should|do you want|can|could|may)\b[^.!?\n]*\b(?:me|i)\b[^.!?\n]*\?"
    r"|(?:is there\s+)?anything else\b[^.!?\n]*\?"
    r"|anything (?:else )?i can (?:help|do)\b[^.!?\n]*\?"
    r"|(?:just\s+)?let me know\b[^.!?\n]*[.!]?"
    r"|(?:how|what) (?:else )?can i help\b[^.!?\n]*\?"
    r"|(?:happy|glad) to help\b[^.!?\n]*[.!]?"
    r"|(?:want|need|like) (?:to|me to|a hand)\b[^.!?\n]*\?)\s*$",
    re.IGNORECASE,
)


# How a chat reply opens when it is acknowledging something the user said they
# did. Chat is told never to (it can record nothing); this catches one that
# slips through, so it is never sent: the message goes back to the router
_ACKNOWLEDGES = re.compile(
    r"^\W*(?:got it|noted|done|logged|recorded|understood|ok(?:ay)?[,.!]? (?:got it|noted|done)"
    r"|i(?:'ve| have)? (?:noted|logged|recorded|updated|marked|saved)"
    r"|so you (?:took|had|did|finished)|thanks for (?:letting me know|the update))\b",
    re.IGNORECASE,
)


def acknowledges(text: str) -> bool:
    """Whether a chat reply opens by acknowledging something the user did ("Got
    it. So you took it about 2 hours ago."). Pure."""
    return _ACKNOWLEDGES.search(text or "") is not None


def set_internal_names(names) -> None:
    """The names that are the code's own and never the user's to read: every
    action of every task. Set by the registry when the tasks are loaded."""
    _names.clear()
    _names.update(name for name in names if "_" in name)  # "none" is a word; "pill_add" never is


def leaks(text: str) -> list[str]:
    """The internal labels in a text, if any."""
    found = [label for label in _FIXED if label in text]
    found += sorted(name for name in _names if re.search(rf"(?<![\w`]){re.escape(name)}(?![\w`])", text))
    return found


def without_offer(text: str) -> str:
    """A reply without a closing offer or "want me to…?": what was asked is done
    or answered, and that is where a reply ends."""
    trimmed = text
    for _ in range(2):  # "…? Just let me know." is two of them
        shorter = _OFFER.sub("", trimmed).rstrip()
        if shorter == trimmed or not shorter:
            break
        trimmed = shorter
    return trimmed


def clean(text: str) -> str:
    """A text as it may be sent: internal labels taken out (and reported).
    Returns "" if nothing is left to say."""
    found = leaks(text)
    if not found:
        return text
    log.error("An internal label was about to be sent to the user: %s in %r", ", ".join(found), text[:200])
    trace.note(f"outgoing check: internal label(s) taken out before sending: {', '.join(found)}")
    for label in found:
        text = re.sub(rf"`?{re.escape(label)}`?", "", text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip(" ·:,-")).strip()
