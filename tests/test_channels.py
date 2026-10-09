import asyncio
from types import SimpleNamespace

import discord
import pytest

from core import channels
from tasks import registry
from tasks.dev import panel
from tasks.lab import status

INBOX, ARCHIVE, BUGS = 100, 200, 300  # the test settings' channels; #bugs is a forum
BOT = 77


def channel(kind: discord.ChannelType, channel_id: int = 1, **more):
    return SimpleNamespace(type=kind, id=channel_id, **more)


class Client:
    """A stand-in for the Discord client that knows some channels."""

    def __init__(self, *known):
        self.known = {item.id: item for item in known}
        self.user = SimpleNamespace(id=BOT)

    def get_channel(self, channel_id):
        return self.known.get(channel_id)


# --- which channels hold messages ------------------------------------------------
@pytest.mark.parametrize(
    "kind",
    [
        discord.ChannelType.text,
        discord.ChannelType.news,
        discord.ChannelType.public_thread,  # a forum's post is one of these
        discord.ChannelType.private_thread,
        discord.ChannelType.private,
    ],
)
def test_text_channels_threads_and_dms_hold_messages(kind):
    assert channels.holds_messages(channel(kind))


@pytest.mark.parametrize(
    "kind",
    [
        discord.ChannelType.forum,
        discord.ChannelType.voice,
        discord.ChannelType.stage_voice,
        discord.ChannelType.category,
        discord.ChannelType.media,
    ],
)
def test_forums_voice_channels_and_categories_do_not(kind):
    assert not channels.holds_messages(channel(kind))


def test_nothing_and_the_unknown_do_not_either():
    assert not channels.holds_messages(None)
    assert not channels.holds_messages(SimpleNamespace(id=1))


def test_the_named_channels_leave_out_the_forum_and_what_cannot_be_seen():
    inbox, forum = channel(discord.ChannelType.text, INBOX), channel(discord.ChannelType.forum, BUGS)
    assert channels.named(Client(inbox, forum)) == [inbox], "#archive isn't visible and #bugs is a forum"
    assert channels.named(Client()) == []


def test_with_no_client_there_are_no_channels(monkeypatch):
    monkeypatch.setattr(channels.discord_utils, "client", None)
    assert channels.named() == []


# --- the dev panel's start-up sweep (the crash: 'ForumChannel' has no 'pins') ------
class Pinned:
    """A text channel with pins. A forum stand-in has no `pins` at all, as in discord.py."""

    def __init__(self, channel_id, messages, error=None):
        self.type, self.id = discord.ChannelType.text, channel_id
        self._messages, self._error = messages, error

    async def pins(self):
        if self._error:
            raise self._error
        for message in self._messages:
            yield message


def pinned_message(message_id, author_id, content):
    return SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id), content=content)


@pytest.fixture
def sweep(monkeypatch):
    seen = SimpleNamespace(deleted=[], cards=[])

    async def delete(found, message_id):
        seen.deleted.append((found.id, message_id))

    async def card(title, description=None):
        seen.cards.append(title)

    monkeypatch.setattr(panel, "_delete", delete)
    monkeypatch.setattr(panel, "log_simple", card)
    return seen


def test_the_sweep_skips_the_forum_and_still_clears_an_old_panel(sweep, monkeypatch):
    old = pinned_message(9, BOT, f"{panel.TITLE}\nDebounce 2s")
    inbox = Pinned(INBOX, [old, pinned_message(10, BOT, "📋 Active timers"), pinned_message(11, 5, panel.TITLE)])
    forum = channel(discord.ChannelType.forum, BUGS)  # no `pins`: reading it would raise AttributeError
    monkeypatch.setattr(panel, "_client", Client(inbox, forum))
    asyncio.run(panel.clear_stale())
    assert sweep.deleted == [(INBOX, 9)], "only the bot's own panel goes"
    assert sweep.cards == ["🛠️ Dev mode off"]


def test_the_sweep_carries_on_past_a_channel_discord_refuses(sweep, monkeypatch):
    refused = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
    inbox = Pinned(INBOX, [], error=refused)
    archive = Pinned(ARCHIVE, [pinned_message(9, BOT, panel.TITLE)])
    monkeypatch.setattr(panel, "_client", Client(inbox, archive))
    asyncio.run(panel.clear_stale())
    assert sweep.deleted == [(ARCHIVE, 9)]


def test_the_lab_does_not_read_pins_from_a_forum(monkeypatch):
    cards = []

    async def card(title, description=None):
        cards.append(title)

    monkeypatch.setattr(status, "log_simple", card)
    forum = channel(discord.ChannelType.forum, BUGS, mention="<#300>")
    asyncio.run(status.on_pins_update(forum, None))
    asyncio.run(status._remember_pins(forum))
    assert cards == [] and BUGS not in status._pins


# --- one task failing at start-up doesn't stop the rest ------------------------------
def test_a_task_that_fails_to_start_is_reported_and_the_others_still_start(monkeypatch):
    started = []

    class Fine:
        def __init__(self, name):
            self.name = name

        async def startup(self, client):
            started.append(self.name)

    class Broken(Fine):
        async def startup(self, client):
            raise AttributeError("'ForumChannel' object has no attribute 'pins'")

    monkeypatch.setattr(registry, "_tasks", [Fine("archive"), Broken("dev"), Fine("timers")])
    monkeypatch.setattr(registry, "_problems", [])
    asyncio.run(registry.startup(None))
    assert started == ["archive", "timers"], "the task after the broken one still starts"
    assert len(registry.problems()) == 1
    assert registry.problems()[0].startswith("dev: startup failed: AttributeError(")
