import logging

import discord

from core import discord_utils

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A channel that shows exactly a given list of messages, and nothing else of
# the bot's: #commands. The channel itself is the record of what is there, so
# nothing is stored: the bot's messages in it are read, and
#   they read the same            nothing is touched
#   as many, some different       those are edited in place
#   more or fewer                 all of them go and the list is posted again,
#                                 so the order is right
# Messages from anyone else are left alone.
# ---------------------------------------------------------------------------
SAME, EDIT, REBUILD = "unchanged", "edited", "rebuilt"
MISSING = "channel not found"
LOOK_BACK = 200


class Refused(Exception):
    """Discord would not let the channel be read or written (a missing permission, say)."""


def plan(have: list[str], want: list[str]) -> tuple[str, list[int]]:
    """What to do to turn the messages there (`have`, oldest first) into `want`:
    (SAME | EDIT | REBUILD, the positions to edit). Pure."""
    if len(have) != len(want):
        return REBUILD, []
    different = [position for position, (old, new) in enumerate(zip(have, want)) if old.strip() != new.strip()]
    return (EDIT, different) if different else (SAME, [])


async def sync(channel_id: int | None, texts: list[str]) -> str:
    """Make the bot's messages in a channel read `texts`, in order. Returns what
    was done, in words ("unchanged", "2 edited", "rebuilt: 6 messages", or
    MISSING). Raises Refused if Discord won't allow it."""
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client is not None and channel_id else None
    if channel is None:
        return MISSING
    try:
        mine = [message async for message in channel.history(limit=LOOK_BACK, oldest_first=True) if message.author.id == client.user.id]
        what, positions = plan([message.content for message in mine], texts)
        if what == SAME:
            return SAME
        if what == EDIT:
            for position in positions:
                await mine[position].edit(content=texts[position], suppress=True)
            return f"{len(positions)} {EDIT}"
        for message in mine:
            try:
                await message.delete()
            except discord.NotFound:
                pass
        for text in texts:
            await channel.send(text, silent=True, suppress_embeds=True)
    except discord.HTTPException as error:
        raise Refused(str(error)) from error
    return f"{REBUILD}: {len(texts)} message{'' if len(texts) == 1 else 's'}"
