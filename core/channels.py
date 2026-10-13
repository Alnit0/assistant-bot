from core import surface
from core.config import CHANNELS

# ---------------------------------------------------------------------------
# Which channels hold messages. A forum, a voice channel, a category and the
# like have no pins and no history to read, and asking for them raises. Any
# code that goes through channels, or reads pins or history from one it was
# not handed a message from, asks here first.
#
# Which kinds those are is the interface's to know (core/surface.py). New
# code asks by id (`ids`, `surface.place`); `holds_messages` and `named`
# take and give the interface's own channel objects, for the tasks that are
# the interface's own (docs/INTERFACE.md).
# ---------------------------------------------------------------------------


def holds_messages(channel) -> bool:
    """True for a channel whose pins and history can be read: a text or news
    channel, a thread (a forum's post is one) or a DM. False for a forum,
    voice, stage or category channel, and for None."""
    return surface.holds_messages(channel)


def ids() -> list[int]:
    """The ids of the channels named in .env that the bot can see and that
    hold messages, each once. The #bugs forum, for one, is left out."""
    return [channel_id for channel_id in sorted(set(CHANNELS.values())) if (found := surface.place(channel_id)) is not None and found.messages]


def named(client=None) -> list:
    """Those channels as the interface's own objects. A task that is the
    interface's own may hand its client in; with none, the door is asked."""
    look = client.get_channel if client is not None else surface.raw_place
    found = (look(channel_id) for channel_id in sorted(set(CHANNELS.values())))
    return [channel for channel in found if holds_messages(channel)]
