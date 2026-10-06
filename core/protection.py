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
