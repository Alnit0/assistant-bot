"""#commands (tasks/builtin/commands.py, core/mirror.py): the pages written from the task
registry, and keeping the channel showing exactly those. Discord is a list of fake messages."""
import asyncio
import re
from types import SimpleNamespace

import discord
import pytest

from core import actions, discord_utils, mirror
from core.actions import Action
from tasks import registry
from tasks.base import ButtonNote, Keyword, Reaction, ReplyAction, Task
from tasks.builtin import commands
from tasks.pills import plain as pills_plain

COMMANDS = 500


def run(coroutine):
    return asyncio.run(coroutine)


async def nothing(*args):
    return None


@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


def page(name):
    """The page of one loaded task, by its heading."""
    return next(text for text in commands.pages() if text.splitlines()[0].endswith(f" {name}"))


# ---------------------------------------------------------------------------
# The pages (pure, from the registry)
# ---------------------------------------------------------------------------
def test_there_is_one_message_a_task_then_housekeeping_then_the_tasks_for_testing():
    titles = [text.splitlines()[0] for text in commands.pages() if text.startswith("## ")]
    assert titles == ["## ⚙️ Builtin", "## 🐞 Bugs", "## 💊 Pills", "## ⏱️ Timers", "## 🧹 Housekeeping", "## 🛠️ Dev", "## 🧪 Lab"]
    assert all(len(text) <= 2000 for text in commands.pages()), "each fits one Discord message"


def test_a_task_whose_ways_in_are_all_housekeeping_has_no_message_of_its_own():
    tidy = page("Housekeeping")
    for word in ("`archive`", "`delete`", "`pin`", "`unpin`", "`reset channel`", "“reset this channel”", "📦", "🗑️", "📌", "**↩️ Restore**"):
        assert word in tidy, word
    assert not any(text.startswith(("## 🔹 Archive", "## 🔹 Keep", "## 🧹 Channel")) for text in commands.pages())


def test_the_pills_page_is_grouped_by_purpose_and_names_no_real_pill():
    pills = page("Pills")
    lines = pills.splitlines()
    assert lines[0] == "## 💊 Pills"
    assert lines[1].startswith("Pills, vitamins, supplements and medicines you take: setting one up")
    assert [line for line in lines if line.startswith("**") and line.endswith("**")] == ["**Set up**", "**Each day**", "**See**", "**Buttons**"]
    each_day = lines[lines.index("**Each day**") + 1 : lines.index("**See**")]
    assert each_day[0].startswith("• `pills` (or `pill`) · today's checklist")
    assert each_day[1] == "• “took Pill A” · “had Pill A at 9 am” · “skip Pill B today” · “I didn't take Pill A”"
    assert "• “add Pill A at 8 am” · “add Pill B twice a day, at least 6 hours apart”" in lines
    assert "• **✅ Taken** · under today's checklist, for a dose with no set time: tick it off as taken now" in lines
    # Placeholder names only: none of the names the router's own examples use
    assert not re.search(r"\b(zinc|iron|vitamin d|magnesium|evening pill|course a)\b", pills.lower())


def test_every_name_said_for_a_pill_is_a_placeholder():
    for action in pills_plain.ACTIONS:
        assert action.say and action.purpose in actions.PURPOSES, action.name
        for phrase in action.say:
            assert "Pill A" in phrase or "Pill B" in phrase or "pill" not in phrase.lower().replace("my pills", ""), phrase


def test_the_timers_page_has_its_words_its_reply_words_and_its_buttons():
    timers = "\n".join(text for text in commands.pages() if "Timers" in text.splitlines()[0])
    assert "• `timer <duration> [label]` · start a timer" in timers
    assert "• “how long is left on tea?”" in timers
    assert "**Reply words**\n• `cancel` (or `stop`) · cancel that timer, or stop that Pomodoro session" in timers
    assert "• **▶️ Start** · on the Pomodoro card: start the phase that is waiting" in timers
    assert "**Set up**" not in timers, "a group with nothing in it is left out"


def test_what_a_task_is_for_is_its_only_for_line_written_for_a_person():
    class Thing(Task):
        name = "things"
        description = "Things: the fallback"
        only_for = "Things the user keeps (\"my zinc\" is one): adding and removing the user's things. Not pills. Only when the user says thing."

    assert commands.about(Thing()) == "Things you keep: adding and removing your things."
    Thing.only_for = ""
    assert commands.about(Thing()) == "Things: the fallback", "a task that takes no plain words is described by its description"


def test_a_page_too_long_for_one_message_is_split_and_the_rest_says_whose_it_is():
    dev = [text for text in commands.pages() if "Dev" in text.splitlines()[0]]
    assert len(dev) == 2 and dev[0].startswith("## 🛠️ Dev\n") and dev[1].startswith("-# 🛠️ Dev · continued\n• `dev ")
    assert "• `dev mock [<name>]` · post a card sketched in docs/mockups/<name>.txt" in "\n".join(dev)


def test_the_pages_are_built_from_what_is_registered_and_nothing_else():
    async def handler(ctx):
        return None

    class Made(Task):
        name = "made"
        icon = "🧶"
        only_for = "Knitting. Not sewing."

        def actions(self):
            return [
                Action("knit_add", "For Claude.", needs_card=False, run=handler, purpose=actions.SET_UP, say=("add a scarf",)),
                Action("knit_hidden", "For Claude: no `say`, so not listed.", needs_card=False, run=handler),
            ]

        def buttons(self):
            return [ButtonNote("✅ Done", "finish the row"), ButtonNote("🗑️ Unravel", "undo it all", housekeeping=True)]

    made = Made()
    entry = registry.TaskCapabilities(
        made,
        [Keyword("knit", "show the knitting", handler, examples=["knit"], purpose=actions.SEE), Keyword("knit wipe", "wipe it", handler, examples=["knit wipe"], housekeeping=True)],
        [ReplyAction("purl", "purl that row", handler, examples=["purl"])],
        [Reaction("🧶", "start a row", handler, examples=["react"])],
    )
    assert commands.build([entry]) == [
        "## 🧶 Made\nKnitting.\n**Set up**\n• “add a scarf”\n**See**\n• `knit` · show the knitting\n**Reply words**\n• `purl` · purl that row\n"
        "**Reactions**\n• 🧶 · start a row\n**Buttons**\n• **✅ Done** · finish the row",
        f"{commands.HOUSEKEEPING_TITLE}\n{commands.HOUSEKEEPING_ABOUT}\n**Words**\n• `knit wipe` · wipe it\n**Buttons**\n• **🗑️ Unravel** · undo it all",
    ]


# ---------------------------------------------------------------------------
# Keeping the channel showing exactly the pages (core/mirror.py)
# ---------------------------------------------------------------------------
def test_what_to_do_is_nothing_an_edit_or_a_rebuild():
    assert mirror.plan(["a", "b"], ["a", "b"]) == (mirror.SAME, [])
    assert mirror.plan(["a ", "b"], ["a", "b\n"]) == (mirror.SAME, []), "Discord trims what it stores"
    assert mirror.plan(["a", "b", "c"], ["a", "B", "C"]) == (mirror.EDIT, [1, 2])
    assert mirror.plan(["a"], ["a", "b"]) == (mirror.REBUILD, [])
    assert mirror.plan([], ["a"]) == (mirror.REBUILD, [])


class Message:
    def __init__(self, channel, message_id, content, author=1):
        self.channel, self.id, self.content, self.author = channel, message_id, content, SimpleNamespace(id=author)

    async def edit(self, content=None, suppress=False):
        self.channel.edits.append((self.id, content))
        self.content = content

    async def delete(self):
        self.channel.messages.remove(self)
        self.channel.deleted.append(self.id)


class Channel:
    def __init__(self, *contents, refuse=False):
        self.messages = [Message(self, 10 + number, content) for number, content in enumerate(contents)]
        self.edits, self.deleted, self.sent, self.refuse = [], [], [], refuse

    async def history(self, limit=None, oldest_first=False):
        if self.refuse:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), {"code": 50001, "message": "Missing Access"})
        for message in list(self.messages):
            yield message

    async def send(self, text, silent=False, suppress_embeds=False):
        self.sent.append((text, silent))
        self.messages.append(Message(self, 100 + len(self.sent), text))
        return self.messages[-1]


@pytest.fixture
def channel(monkeypatch):
    def use(found):
        monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: found, user=SimpleNamespace(id=1)))
        return found

    return use


def test_a_channel_that_reads_the_same_is_not_touched(channel):
    there = channel(Channel("one", "two"))
    assert run(mirror.sync(COMMANDS, ["one", "two"])) == "unchanged"
    assert (there.edits, there.deleted, there.sent) == ([], [], [])


def test_a_page_that_changed_is_edited_in_place(channel):
    there = channel(Channel("one", "two", "three"))
    assert run(mirror.sync(COMMANDS, ["one", "TWO", "three"])) == "1 edited"
    assert there.edits == [(11, "TWO")] and there.deleted == [] and there.sent == []


def test_more_or_fewer_pages_and_the_channel_is_written_again_in_order(channel):
    there = channel(Channel("one", "two"))
    someone_elses = Message(there, 99, "hello", author=7)
    there.messages.append(someone_elses)
    assert run(mirror.sync(COMMANDS, ["one", "two", "three"])) == "rebuilt: 3 messages"
    assert there.deleted == [10, 11] and there.sent == [("one", True), ("two", True), ("three", True)], "posted without a notification"
    assert someone_elses in there.messages, "only the bot's own messages are its to delete"


def test_an_empty_channel_is_filled(channel):
    there = channel(Channel())
    assert run(mirror.sync(COMMANDS, ["one"])) == "rebuilt: 1 message"
    assert there.sent == [("one", True)]


def test_a_channel_that_cannot_be_seen_or_written_is_said_not_raised(channel, monkeypatch):
    logged = []

    async def log_error(title, details, user_text=None):
        logged.append((title, details))

    monkeypatch.setattr(commands, "log_error", log_error)
    monkeypatch.setattr(commands, "log_simple", nothing)
    monkeypatch.setattr(commands, "COMMANDS_CHANNEL_ID", None)
    assert run(commands.update()) == "COMMANDS_CHANNEL_ID is not set" and logged == []
    monkeypatch.setattr(commands, "COMMANDS_CHANNEL_ID", COMMANDS)
    channel(None)
    assert run(commands.update()) == mirror.MISSING and logged[-1][0] == "#commands not updated"
    channel(Channel(refuse=True))
    assert run(commands.update()) == "refused by Discord"
    assert "Manage Messages" in logged[-1][1]


def test_start_up_writes_the_channel_once_and_leaves_it_alone_the_next_time(channel, monkeypatch):
    logged = []

    async def log_simple(title, description=None):
        logged.append((title, description))

    monkeypatch.setattr(commands, "log_simple", log_simple)
    monkeypatch.setattr(commands, "COMMANDS_CHANNEL_ID", COMMANDS)
    there = channel(Channel())
    wanted = commands.pages()
    assert run(commands.update()) == f"rebuilt: {len(wanted)} messages"
    assert [message.content for message in there.messages] == wanted
    assert logged == [("📖 #commands updated", f"<#{COMMANDS}>: rebuilt: {len(wanted)} messages.")]
    assert run(commands.update()) == "unchanged" and len(logged) == 1 and there.edits == [], "nothing changed: nothing touched, nothing said"
