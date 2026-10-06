import asyncio
from types import SimpleNamespace

import discord
import pytest

from core import discord_utils, pins
from core.errors import UserError
from core.protection import PROTECT_EMOJI, is_kept, pin_problem
from skills import keep, registry

CHANNEL, MESSAGE = 300, 10
PAYLOAD = SimpleNamespace(channel_id=CHANNEL, message_id=MESSAGE)


def refusal(status: int, code: int) -> discord.HTTPException:
    """The error discord.py raises when Discord says no."""
    return discord.HTTPException(SimpleNamespace(status=status, reason="No"), {"code": code, "message": "No"})


class FakeMessage:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def pin(self, reason=None):
        self.calls.append(("pin", reason))
        if self.error:
            raise self.error

    async def unpin(self, reason=None):
        self.calls.append(("unpin", reason))
        if self.error:
            raise self.error


@pytest.fixture
def discord_message(monkeypatch):
    """Put a fake message behind core/pins.py. Call it with the error Discord should give."""

    def make(error=None) -> FakeMessage:
        message = FakeMessage(error)
        channel = SimpleNamespace(get_partial_message=lambda message_id: message)
        client = SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == CHANNEL else None)
        monkeypatch.setattr(discord_utils, "client", client)
        return message

    return make


# --- the registration ------------------------------------------------------
def test_the_pin_emoji_is_a_reaction_that_can_be_undone():
    registry.load()
    kind, skill, reaction = registry.find(PROTECT_EMOJI)
    assert (kind, skill.name) == ("reaction", "keep")
    assert reaction.handler is keep.keep and reaction.undo is keep.unkeep
    assert not reaction.destructive, "a kept message is still there, so it is marked ✅ and can be undone"
    assert registry.works_in(reaction, 999), "any channel"


# --- keeping and unkeeping -------------------------------------------------
def test_keeping_pins_the_message(discord_message):
    message = discord_message()
    reply = asyncio.run(keep.keep(PAYLOAD, None))
    assert [call[0] for call in message.calls] == ["pin"]
    assert reply == "kept and pinned a message in <#300>"


def test_unkeeping_unpins_it(discord_message):
    message = discord_message()
    reply = asyncio.run(keep.unkeep(PAYLOAD, None))
    assert [call[0] for call in message.calls] == ["unpin"]
    assert reply == "unkept and unpinned a message in <#300>"


def test_a_full_channel_is_a_problem_the_user_can_fix(discord_message):
    discord_message(refusal(400, 30003))
    with pytest.raises(UserError, match="as many pinned messages as Discord allows"):
        asyncio.run(keep.keep(PAYLOAD, None))


def test_keeping_a_message_that_has_gone_fails(discord_message):
    discord_message(refusal(404, 10008))
    with pytest.raises(UserError, match="That message has gone."):
        asyncio.run(keep.keep(PAYLOAD, None))


def test_unkeeping_a_message_that_has_gone_is_nothing_to_worry_about(discord_message):
    discord_message(refusal(404, 10008))
    assert asyncio.run(keep.unkeep(PAYLOAD, None)).startswith("unkept")


def test_unkeeping_without_permission_fails(discord_message):
    discord_message(refusal(403, 50013))
    with pytest.raises(UserError, match="wouldn't let me unpin it"):
        asyncio.run(keep.unkeep(PAYLOAD, None))


def test_a_channel_the_bot_cannot_see(discord_message):
    discord_message()
    with pytest.raises(UserError, match="can't see the channel"):
        asyncio.run(pins.set_pinned(12345, MESSAGE, True, "test"))


# --- what the user is told -------------------------------------------------
def test_the_pin_limit_says_how_to_get_past_it():
    text = pin_problem(400, 30003)
    assert "Unpin one there" in text
    assert f"take your {PROTECT_EMOJI} off and add it again" in text


@pytest.mark.parametrize(
    "status, code, pinning, expected",
    [
        (404, 10008, True, "That message has gone."),
        (403, 50021, True, "Discord doesn't allow that kind of message to be pinned."),
        (403, 50013, True, "Discord wouldn't let me pin it. I need Pin Messages (or Manage Messages) in that channel."),
        (403, 50013, False, "Discord wouldn't let me unpin it. I need Pin Messages (or Manage Messages) in that channel."),
        (500, 0, True, "Discord refused to pin it (status 500, code 0)."),
        (500, 0, False, "Discord refused to unpin it (status 500, code 0)."),
    ],
)
def test_other_refusals(status, code, pinning, expected):
    assert pin_problem(status, code, pinning) == expected


# --- kept or not -----------------------------------------------------------
def test_a_message_is_kept_once_the_pin_reaction_has_been_applied():
    assert is_kept({(MESSAGE, PROTECT_EMOJI, 1)})
    assert is_kept({(MESSAGE, "⭐", 1), (MESSAGE, PROTECT_EMOJI, 1)})
    assert not is_kept({(MESSAGE, "⭐", 1)})
    assert not is_kept(set())
