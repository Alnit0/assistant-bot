"""Tidying messages in plain words (tasks/archive/plain.py): which message an id means,
what is done at once and what asks first, and every word said."""
import asyncio
from types import SimpleNamespace

import pytest

from core import actions, pins
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.archive import messages, plain

CHANNEL = 100


def message(message_id, content, bot=False, pinned=False, author=None):
    return SimpleNamespace(
        id=message_id, content=content, pinned=pinned, reactions=[], embeds=[], attachments=[],
        author=SimpleNamespace(display_name=author or ("Hive" if bot else "Sam"), bot=bot),
        jump_url=f"https://discord.com/channels/1/{CHANNEL}/{message_id}", channel=SimpleNamespace(id=CHANNEL), guild=None,
    )


@pytest.fixture
def world(owner, monkeypatch):
    found = [
        message(503, "✅ Saved · 🛒 milk × 2 is on the shopping list", bot=True),
        message(502, "add 2 milk"),
        message(501, "The invoice from the plumber is $240, due on the 20th", pinned=True),
    ]
    made = SimpleNamespace(found=found, pinned=[], archived=[], deleted=[], owner=owner)

    async def recent(request):
        return list(made.found)

    async def set_pinned(channel_id, message_id, pinned, reason):
        made.pinned.append((message_id, pinned))

    async def archive_message(target, user_id=None):
        made.archived.append(target.id)
        return f"archived {target.id}", f"https://discord.com/channels/1/900/{target.id + 1000}"

    async def delete_message(target):
        made.deleted.append(target.id)
        return f"deleted {target.id}"

    async def fetch(data):
        return [item for item in made.found if str(item.id) in data["messages"]]

    monkeypatch.setattr(plain, "recent", recent)
    monkeypatch.setattr(pins, "set_pinned", set_pinned)
    monkeypatch.setattr(messages, "archive_message", archive_message)
    monkeypatch.setattr(messages, "delete_message", delete_message)
    monkeypatch.setattr(messages, "check_archivable", lambda target: None)
    monkeypatch.setattr(messages, "check_deletable", lambda target: None)
    monkeypatch.setattr(plain, "_fetch", fetch)
    made.request = lambda **more: Request(owner, CHANNEL, "said", message_id=504, **more)
    return made


def run(coroutine):
    return asyncio.run(coroutine)


# --- the contract ---------------------------------------------------------------------
def test_tidying_messages_is_one_entry_and_only_delete_always_asks():
    registry.load()
    entry = actions.entry("messages")
    assert entry is not None and (entry.icon, entry.title) == ("🗂️", "Messages")
    assert "Not for what a message is about" in entry.only_for
    assert [(action.name, action.needs_card, action.card_if is not None) for action in entry.actions] == [
        ("message_archive", True, True), ("message_pin", False, False), ("message_delete", True, False),
    ]
    assert actions.problems([entry]) == [] and registry.problems() == []
    assert actions.entry("archive") is None and actions.entry("keep") is None, "one place for the router to send them"


# --- which message is meant -------------------------------------------------------------
def test_the_state_lists_the_last_messages_as_the_channel_reads_with_short_ids(world):
    state = run(plain.state(world.request(replied_to=502)))
    assert state.heading == "The last messages in this channel, in the order they were sent: the last line is the newest (use these ids)"
    assert state.lines == (
        "m3: Sam (the user): The invoice from the plumber is $240, due on the 20th · pinned",
        "m2: Sam (the user): add 2 milk · the user replied to this one",
        "m1: Hive (the bot): ✅ Saved · 🛒 milk × 2 is on the shopping list",
    ), "as the channel reads, the newest at the bottom"


def test_a_message_with_no_text_says_what_it_holds():
    card = message(1, "")
    card.embeds = [object()]
    files = message(2, "")
    files.attachments = [object()]
    assert [plain.said(card), plain.said(files), plain.said(message(3, ""))] == ["(a card)", "(files)", "(no text)"]
    assert plain.said(message(4, "a " * 200)).endswith("…") and len(plain.said(message(4, "a " * 200))) == plain.QUOTE


def test_ids_become_messages_each_once_and_a_bad_id_is_named(world):
    picked, bad = plain.pick(world.found, ["m2", "M1", "m2", "m9", "the first"])
    assert [item.id for item in picked] == [502, 503] and bad == ["m9", "the first"]


def test_a_reply_always_means_the_message_replied_to_whatever_claude_said(world):
    assert [item.id for item in run(plain.chosen(world.request(replied_to=501), {"which": "newest"}))] == [501]


def test_the_code_not_claude_finds_the_newest_and_the_users_own_last(world):
    def ids(**data):
        return [item.id for item in run(plain.chosen(world.request(), data))]

    assert ids(which="newest") == [503] and ids(which="newest", count=2) == [503, 502]
    assert ids(which="mine") == [502], "the newest the user wrote, not the bot's reply after it"
    assert ids(which="mine", count=2) == [502, 501]
    assert ids(which="named", ids=["m3"]) == [501]


def test_with_no_message_found_it_says_how_to_point_at_one(world):
    with pytest.raises(UserError, match="couldn't tell which message"):
        run(plain.chosen(world.request(), {"which": "named", "ids": ["m9"]}))


# --- pin and unpin: at once ------------------------------------------------------------------
def test_pin_acts_at_once_and_quotes_the_message_with_a_link(world):
    said = run(plain.pin(world.request(), {"which": "mine", "action": "pin"}, frozenset()))
    assert world.pinned == [(502, True)]
    assert said == f"📌 Pinned\n> add 2 milk · [jump](https://discord.com/channels/1/{CHANNEL}/502)"
    said = run(plain.pin(world.request(), {"which": "named", "ids": ["m3"], "action": "unpin"}, frozenset()))
    assert world.pinned[-1] == (501, False) and said.splitlines()[0] == "📌 Unpinned"


def test_a_guess_at_which_message_is_flagged_but_never_on_a_reply(world):
    said = run(plain.pin(world.request(), {"which": "named", "ids": ["m2"], "action": "pin"}, frozenset({"ids"})))
    assert said.splitlines()[1].endswith("❓")
    replied = run(plain.pin(world.request(replied_to=502), {"which": "newest", "action": "pin"}, frozenset({"which"})))
    assert "❓" not in replied and world.pinned[-1] == (502, True)


# --- archive: at once unless protected --------------------------------------------------------
def test_archive_acts_at_once_and_gives_the_link_to_the_copy(world):
    assert run(plain.archive_asks(world.request(), {"which": "newest", "count": 2})) is False
    said = run(plain.archive(world.request(), {"which": "newest", "count": 2}, frozenset()))
    assert world.archived == [503, 502]
    assert said.splitlines()[0] == "📦 Archived: https://discord.com/channels/1/900/1503"
    assert said.splitlines()[1].startswith("> ✅ Saved · 🛒 milk × 2")


def test_archiving_a_pinned_message_asks_first_with_a_card(world):
    assert run(plain.archive_asks(world.request(), {"which": "named", "ids": ["m3"]})) is True
    proposal = run(plain.archive_card(world.request(), {"which": "named", "ids": ["m3"]}, frozenset()))
    assert proposal.lines == (f"> The invoice from the plumber is $240, due on the 20th · [jump](https://discord.com/channels/1/{CHANNEL}/501)",)
    assert proposal.warnings == (
        "“The invoice from the plumber is $240, d…” is pinned", "Archiving moves it to the archive channel, with a Restore button",
    )
    assert (proposal.kind, proposal.destructive, proposal.confirm_label) == ("archive", False, "Archive anyway")
    assert proposal.data == {"channel": CHANNEL, "messages": ["501"]} and world.archived == []
    assert run(plain.archive_saved(world.request(), proposal.data)) == "📦 Archived: https://discord.com/channels/1/900/1501"


def test_when_no_message_is_found_archive_says_so_itself(world):
    assert run(plain.archive_asks(world.request(), {"which": "named", "ids": ["m9"]})) is False
    with pytest.raises(UserError, match="couldn't tell which message"):
        run(plain.archive(world.request(), {"which": "named", "ids": ["m9"]}, frozenset()))


# --- delete: always a card --------------------------------------------------------------------
def test_delete_is_always_a_card_that_cannot_be_undone_and_nothing_goes_before_it_is_pressed(world):
    proposal = run(plain.delete_card(world.request(), {"which": "mine"}, frozenset({"which"})))
    assert proposal.lines == (f"> add 2 milk · [jump](https://discord.com/channels/1/{CHANNEL}/502) ❓",)
    assert (proposal.kind, proposal.destructive, proposal.confirm_label) == ("delete", True, "Delete for good")
    assert proposal.warnings == ("Deleting can't be undone",) and world.deleted == []
    assert run(plain.delete_saved(world.request(), proposal.data)) == "🗑️ Deleted"
    assert world.deleted == [502]


def test_deleting_several_names_each_and_says_which_are_protected(world):
    proposal = run(plain.delete_card(world.request(), {"which": "named", "ids": ["m1", "m3"]}, frozenset()))
    assert len(proposal.lines) == 2 and proposal.confirm_label == "Delete 2 for good"
    assert proposal.warnings[0].endswith("is pinned") and proposal.warnings[-1] == "Deleting can't be undone"
    assert run(plain.delete_saved(world.request(), proposal.data)) == "🗑️ Deleted 2 messages"


def test_a_message_that_may_not_be_deleted_is_refused_in_the_tasks_words(world, monkeypatch):
    def refuse(target):
        raise UserError("Messages in #bot-log stay where they are.")

    monkeypatch.setattr(messages, "check_deletable", refuse)
    with pytest.raises(UserError, match="stay where they are"):
        run(plain.delete_card(world.request(), {"which": "newest"}, frozenset()))
