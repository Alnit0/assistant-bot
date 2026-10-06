from core.reactions import emoji_key

# ---------------------------------------------------------------------------
# Protected messages: pinned ones, and ones somebody has marked with 📌. They
# are exempt from clean-up and sweeps, and archiving or deleting one asks
# for confirmation first (see core/confirmations.py).
# ---------------------------------------------------------------------------
PROTECT_EMOJI = "📌"


def protection(message) -> str | None:
    """Why a message is protected ("pinned", "marked 📌"), or None if it isn't."""
    if getattr(message, "pinned", False):
        return "pinned"
    for reaction in getattr(message, "reactions", None) or []:
        if emoji_key(reaction.emoji) == PROTECT_EMOJI and reaction.count > 0:
            return f"marked {PROTECT_EMOJI}"
    return None


def is_protected(message) -> bool:
    return protection(message) is not None


def is_kept(applied) -> bool:
    """Whether a message is kept, given the reaction actions applied to it (reactions.db_applied)."""
    return any(emoji == PROTECT_EMOJI for _, emoji, _ in applied)


# ---------------------------------------------------------------------------
# Why Discord wouldn't pin or unpin a message, in words for the #bot-log card
# (the pinning itself is in core/pins.py)
# ---------------------------------------------------------------------------
PIN_LIMIT_CODE = 30003  # "Maximum number of pins reached"
UNKNOWN_MESSAGE_CODE = 10008
SYSTEM_MESSAGE_CODE = 50021  # "Cannot execute action on a system message"


def message_gone(code: int | None) -> bool:
    return code == UNKNOWN_MESSAGE_CODE


def pin_problem(status: int | None, code: int | None, pinning: bool = True) -> str:
    """What to tell the user when Discord refuses to pin (or unpin) a message."""
    verb = "pin" if pinning else "unpin"
    if code == PIN_LIMIT_CODE:
        return (
            "That channel has as many pinned messages as Discord allows. Unpin one there, "
            f"then take your {PROTECT_EMOJI} off and add it again."
        )
    if message_gone(code):
        return "That message has gone."
    if code == SYSTEM_MESSAGE_CODE:
        return f"Discord doesn't allow that kind of message to be {verb}ned."
    if status == 403:
        return f"Discord wouldn't let me {verb} it. I need Pin Messages (or Manage Messages) in that channel."
    return f"Discord refused to {verb} it (status {status}, code {code})."
