import logging

import discord

from core import discord_utils, lifecycle
from core.database import log_received, log_result
from core.discord_utils import safe_reply
from core.lifecycle import MessageClass
from core.permissions import is_allowed
from core.users import get_user_by_discord_id

log = logging.getLogger("assistant")

TASK = "timers"
PERMISSION = "timers"

# This task uses discord.py directly for its cards, buttons, pins and
# mentions, like the lab and archive tasks. That moves behind the gateway
# layer when it exists.


def channel_for(channel_id: int):
    client = discord_utils.client
    return client.get_channel(channel_id) if client else None


def mention(discord_user_id: int) -> str:
    return f"<@{discord_user_id}>"


PING = discord.AllowedMentions(users=True)


async def edit_message(channel_id: int, message_id: int | None, **changes) -> bool:
    """Edit one of our messages. False if it has gone or can't be reached."""
    channel = channel_for(channel_id)
    if channel is None or message_id is None:
        return False
    try:
        await channel.get_partial_message(message_id).edit(**changes)
    except discord.HTTPException as error:
        log.info("Could not edit message %s: %s", message_id, error)
        return False
    return True


async def delete_message(
    channel_id: int, message_id: int | None, message_class: MessageClass = MessageClass.ALERT
) -> None:
    """Delete one of our messages, if it is still there: an alert that has been
    dealt with, unless told it is something else. Left alone while clean-up is off."""
    channel = channel_for(channel_id)
    if channel is None or message_id is None or not lifecycle.deletes(message_class):
        return
    try:
        await channel.get_partial_message(message_id).delete()
    except discord.HTTPException:
        pass


async def owner_pressed(interaction: discord.Interaction, owner_user_id: int) -> bool:
    """Button check: allowed to use timers, and it is their timer or session."""
    user = await get_user_by_discord_id(interaction.user.id)
    if not is_allowed(user, PERMISSION) or user.id != owner_user_id:
        await safe_reply(interaction, "That one isn't yours.")
        return False
    interaction.extras["user_id"] = user.id
    return True


async def log_press(interaction: discord.Interaction, what: str, outcome: str) -> None:
    """Record a button press in message_log (input first, then what happened)."""
    row_id = await log_received(
        what,
        TASK,
        interaction.message.id if interaction.message else None,
        interaction.channel_id,
        user_id=interaction.extras.get("user_id"),
    )
    await log_result(row_id, reply=outcome, status="ok")
