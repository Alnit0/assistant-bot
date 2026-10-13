"""The line between the bot and its interface (docs/INTERFACE.md): who may import discord.py, and the door
(core/surface.py) the core reaches Discord through."""
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from core import cards, discord_utils, surface
from core.cards import Card
from interfaces.discord import surface as discord_surface

ROOT = Path(__file__).resolve().parent.parent
IMPORTS = re.compile(r"^\s*(import discord\b|from discord\b)", re.MULTILINE)

# The files that imported discord.py when the rule was made (2026-10-14). The list only ever
# gets shorter: a file leaves it when it is moved behind the door, and nothing is added to it.
CORE_STILL = {"confirmations.py", "context.py", "conversation.py", "discord_utils.py", "interactions.py"}
TASKS_STILL = {
    "base.py", "registry.py",  # the typed-word and reaction contract (stage 4)
    "archive/__init__.py", "archive/messages.py",
    "bugs/posts.py",
    "builtin/views.py",
    "dev/__init__.py", "dev/mock.py", "dev/panel.py", "dev/tools.py",
    # Discord's own, for good: lab exists to try Discord, and timers are frozen (never ported)
    "lab/__init__.py", "lab/buttons.py", "lab/channels.py", "lab/charts.py", "lab/common.py", "lab/misc.py", "lab/react.py", "lab/status.py", "lab/tour.py",
    "timers/__init__.py", "timers/board.py", "timers/common.py", "timers/sessions.py", "timers/timers.py",
}


def importing(folder: str) -> set[str]:
    base = ROOT / folder
    return {path.relative_to(base).as_posix() for path in base.rglob("*.py") if IMPORTS.search(path.read_text(encoding="utf-8"))}


def run(coroutine):
    return asyncio.run(coroutine)


# --- the rule -------------------------------------------------------------------------------------------------------------
def test_no_new_core_code_imports_discord_py():
    new = importing("core") - CORE_STILL
    assert not new, f"core code goes through the door (core/surface.py), never discord.py: {sorted(new)}"


def test_no_new_task_imports_discord_py():
    new = importing("tasks") - TASKS_STILL
    assert not new, f"a task produces plain data (cards, replies) and never imports discord.py: {sorted(new)}"


def test_the_lists_only_get_shorter():
    assert CORE_STILL <= importing("core") and TASKS_STILL <= importing("tasks"), "a file that no longer imports discord.py comes off its list"


def test_the_core_never_reaches_for_the_interface_itself():
    for path in (ROOT / "core").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import interfaces\b|from interfaces\b)", text, re.MULTILINE), f"{path.name} imports the interface: it is bound, not imported"
        if path.name not in CORE_STILL:
            assert "discord_utils.client" not in text, f"{path.name} holds the client: ask the door"
    for folder in ("pills", "briefing", "schedule", "channel", "keep"):
        for path in (ROOT / "tasks" / folder).rglob("*.py"):
            assert "interfaces" not in path.read_text(encoding="utf-8"), f"{folder}/{path.name} reaches for the interface"


def test_the_plain_half_of_a_card_holds_nothing_of_discord():
    text = (ROOT / "core" / "cards.py").read_text(encoding="utf-8")
    assert "discord.ui" not in text and "Interaction" not in text
    assert not hasattr(cards, "view") and not hasattr(cards, "layout_view"), "how a card is drawn is the interface's (interfaces/discord/render.py)"


# --- the door -------------------------------------------------------------------------------------------------------------
class Partial:
    def __init__(self, channel, message_id):
        self.channel, self.id = channel, message_id

    async def delete(self):
        if self.id in self.channel.gone:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), {"code": 10008, "message": "Unknown Message"})
        if self.id in self.channel.stuck:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), {"code": 50013, "message": "Missing Permissions"})
        self.channel.deleted.append(self.id)

    async def edit(self, **kwargs):
        self.channel.edits.append((self.id, kwargs))

    async def pin(self, reason=None):
        self.channel.pinned.append(self.id)

    async def add_reaction(self, emoji):
        self.channel.reactions.append((self.id, emoji))


class Channel:
    def __init__(self, channel_id=400, kind=discord.ChannelType.text, server=True):
        self.id, self.name, self.type, self.mention = channel_id, "hub", kind, f"<#{channel_id}>"
        self.guild = SimpleNamespace(id=7, me=SimpleNamespace(nick="Bot", name="bot", guild_permissions=SimpleNamespace(change_nickname=True))) if server else None
        self.sent, self.deleted, self.edits, self.pinned, self.reactions, self.gone, self.stuck = [], [], [], [], [], set(), set()

    async def send(self, text=None, **kwargs):
        self.sent.append((text, kwargs))
        return SimpleNamespace(id=9000 + len(self.sent))

    def get_partial_message(self, message_id):
        return Partial(self, message_id)

    def permissions_for(self, member):
        return SimpleNamespace(read_message_history=True, manage_messages=False)


@pytest.fixture
def hub(monkeypatch):
    channel = Channel()
    monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: channel if channel_id == 400 else None, user=SimpleNamespace(id=1)))
    return channel


def test_a_place_is_a_plain_record_and_one_that_cannot_be_seen_is_none(hub):
    assert surface.place(400) == surface.Place(400, "hub", "<#400>", messages=True, server=True)
    assert surface.place(123) is None and surface.place(None) is None
    assert surface.me() == 1 and surface.connected()
    assert surface.link(400, 9001) == "https://discord.com/channels/7/400/9001" and surface.link(123, 9001) == ""
    assert surface.lacking(400, ("read_message_history", "manage_messages")) == ("manage_messages",)


def test_a_forum_is_a_place_that_holds_no_messages(monkeypatch):
    forum = Channel(500, discord.ChannelType.forum)
    monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: forum))
    assert surface.place(500).messages is False and not surface.holds_messages(forum) and not surface.holds_messages(None)


def test_text_is_sent_and_a_place_that_is_not_there_gets_nothing(hub):
    assert run(surface.send(400, "hello")) == 9001 and hub.sent == [("hello", {})]
    run(surface.send(400, "quietly", silent=True, suppress_embeds=True))
    assert hub.sent[-1] == ("quietly", {"silent": True, "suppress_embeds": True})
    assert run(surface.send(123, "nowhere")) is None


def test_discord_s_errors_stop_at_the_door(hub):
    hub.gone.add(5)
    hub.stuck.add(6)
    with pytest.raises(surface.Gone):
        run(surface.delete(400, 5))
    with pytest.raises(surface.Failed) as refused:
        run(surface.delete(400, 6))
    assert not isinstance(refused.value, surface.Gone) and (refused.value.status, refused.value.code) == (403, 50013), "with Discord's status and code, for the words of a refusal"
    run(surface.delete(400, 7))
    assert hub.deleted == [7]
    with pytest.raises(surface.Failed):
        run(surface.delete(123, 7))  # a place that can't be found


def test_pins_reactions_and_edits_go_by_ids(hub):
    run(surface.pin(400, 5, True, "kept"))
    run(surface.react(400, 5, "⚠️"))
    run(surface.edit(400, 5, "new words", suppress_embeds=True))
    assert hub.pinned == [5] and hub.reactions == [(5, "⚠️")] and hub.edits == [(5, {"content": "new words", "suppress": True})]


def test_with_no_interface_bound_nothing_is_found_and_nothing_raises_until_it_must(monkeypatch):
    monkeypatch.setattr(surface, "_backend", None)
    assert not surface.bound() and not surface.connected() and surface.me() is None
    assert surface.place(400) is None and surface.link(400, 1) == "" and surface.name(400) is None
    assert run(surface.send(400, "x")) is None, "nowhere to send: as a place that can't be seen"
    assert run(cards.send(400, Card("x"))) is None and run(cards.delete(400, 1)) is False
    with pytest.raises(surface.Failed):
        run(surface.delete(400, 1))


def test_the_discord_interface_gives_every_verb_the_door_has():
    verbs = [name for name, value in vars(surface).items() if callable(value) and not name.startswith("_") and name not in ("bind", "bound", "dataclass", "Failed", "Gone", "Refused", "Place", "Name")]
    missing = [name for name in verbs if not hasattr(discord_surface, name)]
    assert not missing, f"the door has verbs Discord does not answer: {missing}"


def test_a_card_reaches_discord_through_the_door(hub, monkeypatch):
    async def no_record(*args, **kwargs):
        pass

    monkeypatch.setattr(cards.messages, "record", no_record)
    card = Card("✅ Saved", ((cards.Button("Undo", "pills", "undo", "5"),),))
    assert run(cards.send(400, card)) == 9001
    text, more = hub.sent[-1]
    assert text == "✅ Saved" and more["silent"] is False and more["view"].children[0].item.custom_id == "card.b:pills:undo:5"
    assert run(cards.edit(400, 9001, Card("✅ Done"))) is True and hub.edits[-1] == (9001, {"content": "✅ Done", "view": None})
    hub.gone.add(9001)
    assert run(cards.delete(400, 9001)) is False, "already gone: best effort"
