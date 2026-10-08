import discord

from core import discord_utils
from core.errors import UserError
from core.protection import message_gone, pin_problem

# ---------------------------------------------------------------------------
# Native Discord pins, for tasks that may not call Discord themselves. The
# wording of a refusal is decided in core/protection.py. Discord's "pinned a
# message" notice is deleted by main.py, like every other one.
# ---------------------------------------------------------------------------


async def set_pinned(channel_id: int, message_id: int, pinned: bool, reason: str) -> None:
    """Pin or unpin a message. Raises UserError, with the reason, if Discord refuses.

    Pinning one that is already pinned (or unpinning one that isn't) is fine.
    Unpinning a message that no longer exists is fine too: there is nothing left to unpin.
    """
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client else None
    if channel is None:
        raise UserError("I can't see the channel that message is in.")
    message = channel.get_partial_message(message_id)
    try:
        if pinned:
            await message.pin(reason=reason)
        else:
            await message.unpin(reason=reason)
    except discord.HTTPException as error:
        if not pinned and message_gone(error.code):
            return
        raise UserError(pin_problem(error.status, error.code, pinning=pinned)) from error
