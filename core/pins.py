from core import surface
from core.errors import UserError
from core.protection import message_gone, pin_problem

# ---------------------------------------------------------------------------
# Pins, through the door (core/surface.py), for tasks that may not call the
# interface themselves. The wording of a refusal is decided in core/protection.py. Discord's "pinned a
# message" notice is deleted by main.py, like every other one.
# ---------------------------------------------------------------------------


async def set_pinned(channel_id: int, message_id: int, pinned: bool, reason: str) -> None:
    """Pin or unpin a message. Raises UserError, with the reason, if Discord refuses.

    Pinning one that is already pinned (or unpinning one that isn't) is fine.
    Unpinning a message that no longer exists is fine too: there is nothing left to unpin.
    """
    if surface.place(channel_id) is None:
        raise UserError("I can't see the channel that message is in.")
    try:
        await surface.pin(channel_id, message_id, pinned, reason)
    except surface.Failed as error:
        if not pinned and message_gone(error.code):
            return
        raise UserError(pin_problem(error.status, error.code, pinning=pinned)) from error
