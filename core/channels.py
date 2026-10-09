import discord

from core import discord_utils
from core.config import CHANNELS

# ---------------------------------------------------------------------------
# Which channels hold messages. A forum, a voice channel, a category and the
# like have no pins and no history to read, and asking for them raises. Any
# code that goes through channels, or reads pins or history from one it was
# not handed a message from, asks here first.
# ---------------------------------------------------------------------------
MESSAGE_TYPES = frozenset(
    {
        discord.ChannelType.text,
        discord.ChannelType.news,
        discord.ChannelType.public_thread,
        discord.ChannelType.private_thread,
        discord.ChannelType.news_thread,
        discord.ChannelType.private,
        discord.ChannelType.group,
    }
)


def holds_messages(channel) -> bool:
    """True for a channel whose pins and history can be read: a text or news
    channel, a thread (a forum's post is one) or a DM. False for a forum,
    voice, stage or category channel, and for None."""
    return channel is not None and getattr(channel, "type", None) in MESSAGE_TYPES


def named(client: discord.Client | None = None) -> list:
    """The channels named in .env that the bot can see and that hold messages,
    each once. The #bugs forum, for one, is left out."""
    client = client or discord_utils.client
    if client is None:
        return []
    found = (client.get_channel(channel_id) for channel_id in sorted(set(CHANNELS.values())))
    return [channel for channel in found if holds_messages(channel)]
