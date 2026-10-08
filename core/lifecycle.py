from collections import deque
from dataclasses import dataclass
from enum import Enum

from core import devmode
from core.config import CONFIRMATION_SECONDS, KEEP_CONFIRMATIONS

# ---------------------------------------------------------------------------
# Message lifecycle: what becomes of each message, the bot's or the user's.
#
# Every message is one of six classes. The rule of thumb: only delete a message
# when its information now lives somewhere else. Anything that deletes a
# message by itself asks here first, so `dev cleanup off` can stop all of it.
#
# Removing something because the user asked (archive, delete, `dev clean`,
# Restore) isn't auto-deletion and doesn't come through here.
# ---------------------------------------------------------------------------


class MessageClass(Enum):
    KEPT = "Kept"
    LIVE = "Live"
    CONSUMED = "Consumed"
    TRANSIENT = "Transient"
    ALERT = "Alert"
    PROTECTED = "Protected"


@dataclass(frozen=True)
class Policy:
    examples: str
    what_happens: str
    auto_delete: bool  # may the bot ever remove one of these by itself?


POLICY: dict[MessageClass, Policy] = {
    MessageClass.KEPT: Policy(
        "chats with Claude and its replies, help, explanations, lists, stats, seed instructions, results to read",
        "never auto-deleted (until the future nightly sweep); only removed by you (archive, delete)",
        auto_delete=False,
    ),
    MessageClass.LIVE: Policy(
        "dev panel, timer board, Pomodoro card",
        "edited in place; when finished it collapses to a one-line summary (and is then Kept), "
        "or is removed if it has no lasting value",
        auto_delete=True,
    ),
    MessageClass.CONSUMED: Policy(
        "your command words: reply actions, settings, shortcuts whose result is posted",
        "deleted once actioned successfully; kept with ⚠️ if it failed",
        auto_delete=True,
    ),
    MessageClass.TRANSIENT: Policy(
        "short confirmations, invalid-action reasons",
        "deletes itself after a few seconds (stays while KEEP_CONFIRMATIONS is on)",
        auto_delete=True,
    ),
    MessageClass.ALERT: Policy(
        "timer done, Pomodoro phase change, reminders",
        "stays until acknowledged, then deleted, with the original updated",
        auto_delete=True,
    ),
    MessageClass.PROTECTED: Policy(
        "📌-reacted or pinned messages",
        "never auto-deleted; archive and delete ask for confirmation",
        auto_delete=False,
    ),
}


def may_auto_delete(message_class: MessageClass, cleanup_on: bool = True) -> bool:
    """Whether the bot may remove a message of this class by itself."""
    return cleanup_on and POLICY[message_class].auto_delete


def classify(
    *,
    protected: bool = False,
    declared: MessageClass | None = None,
    transient: bool = False,
    command: bool = False,
) -> MessageClass:
    """The class of one message, from what is known about it.

    `protected`: pinned or marked 📌, which overrides everything else.
    `declared`: what the task that owns the message says it is (Live, Alert).
    `transient`: a self-deleting note of ours that is still on screen.
    `command`: a message of the user's that ran a word or a reply action.
    Anything else is content, and content is Kept.
    """
    if protected:
        return MessageClass.PROTECTED
    if declared is not None:
        return declared
    if transient:
        return MessageClass.TRANSIENT
    if command:
        return MessageClass.CONSUMED
    return MessageClass.KEPT


def describe(message_class: MessageClass) -> str:
    """One line for `dev inspect`: "Kept: never auto-deleted ..."."""
    return f"{message_class.value}: {POLICY[message_class].what_happens}"


# ---------------------------------------------------------------------------
# What the rest of the code asks. Dev mode's `dev cleanup off` says no to all.
# ---------------------------------------------------------------------------
def deletes(message_class: MessageClass) -> bool:
    """Whether to go ahead and remove a message of this class right now."""
    return may_auto_delete(message_class, devmode.cleanup_enabled())


def keeps_confirmations() -> bool:
    """True while KEEP_CONFIRMATIONS is on: Transient messages stay where they are,
    so what the bot did can be read back. Nothing else is affected."""
    return KEEP_CONFIRMATIONS


def delete_after(seconds: float = CONFIRMATION_SECONDS) -> float | None:
    """How long a Transient message stays (for discord.py's `delete_after`), or None to leave it."""
    if keeps_confirmations():
        return None
    return seconds if deletes(MessageClass.TRANSIENT) else None


# The ids of our recent self-deleting notes, so `dev inspect` can name one that
# was left on screen. In memory: a restart forgets them, and they read as Kept.
_transient: deque[int] = deque(maxlen=500)


def note_transient(message_id: int | None) -> None:
    if message_id is not None:
        _transient.append(message_id)


def is_transient(message_id: int) -> bool:
    return message_id in _transient
