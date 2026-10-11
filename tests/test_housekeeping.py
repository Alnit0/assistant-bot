"""Housekeeping leaves no trace (the conversation standard, principle 8): deleting, archiving,
pinning, unpinning and resetting a channel say at most one line that goes after about ten
seconds, whatever KEEP_CONFIRMATIONS says; the word that asked is deleted; #bot-log is the record.
Each is run through the registry as a real reply, with Discord replaced by lists."""
import asyncio
from types import SimpleNamespace

import pytest

from core import confirmations, context, devmode, lifecycle, pins, scheduler, tidy
from core.context import Context
from core.errors import UserError
from tasks import registry
from tasks.archive import messages as archive_messages

INBOX, ARCHIVE = 100, 200
TEN = lifecycle.HOUSEKEEPING_SECONDS


def run(coroutine):
    return asyncio.run(coroutine)


def booked():
    """The lines booked to be deleted: (the message, seconds from now, to the nearest)."""
    now = scheduler.utc_now()
    return [(job.payload["message"], round((job.due_at - now).total_seconds())) for job in run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND))]


class Channel:
    id = INBOX

    def __init__(self):
        self.sent = []  # (text, how long it stays: None is for good)

    async def send(self, text=None, **options):
        self.sent.append((text, options.get("delete_after")))
        return SimpleNamespace(id=9000 + len(self.sent))


class Mine:
    """My own message: the word I typed as a reply."""

    id = 60

    def __init__(self):
        self.deleted, self.reactions = False, []
        self.reference = SimpleNamespace(message_id=50, resolved=None)

    async def delete(self):
        self.deleted = True

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


def target(channel_id=INBOX):
    """The message replied to."""
    return SimpleNamespace(
        id=50, channel=SimpleNamespace(id=channel_id), guild=None, content="hello", attachments=[], embeds=[], pinned=False, reactions=[],
    )


@pytest.fixture
def chat(db, owner, monkeypatch, dev_off):
    seen = SimpleNamespace(owner=owner, channel=Channel(), mine=None, logged=[], target=target(), pinned=[])

    async def log_simple(title, description=None):
        seen.logged.append((title, description))

    async def log_error(title, details, user_text=None):
        seen.logged.append((title, details))

    async def fetch(self):
        return seen.target

    async def set_pinned(channel_id, message_id, pinned, reason):
        seen.pinned.append((message_id, pinned))

    async def archive_message(message, user_id=None):
        return "archived a message from #inbox", "https://discord.test/copy"

    async def delete_message(message):
        return "deleted a message in #inbox"

    monkeypatch.setattr(lifecycle, "keeps_confirmations", lambda: True)  # the default: confirmations stay
    monkeypatch.setattr(context, "log_simple", log_simple)
    monkeypatch.setattr(context, "log_error", log_error)
    monkeypatch.setattr(confirmations, "log_simple", log_simple)
    monkeypatch.setattr(Context, "fetch_reply_target", fetch)
    monkeypatch.setattr(pins, "set_pinned", set_pinned)
    monkeypatch.setattr(archive_messages, "archive_message", archive_message)
    monkeypatch.setattr(archive_messages, "delete_message", delete_message)
    registry.load()

    def reply(text):
        seen.mine = Mine()
        ctx = Context(user=owner, channel_id=INBOX, message_id=60, text=text, _channel=seen.channel, _message=seen.mine)
        assert run(registry.dispatch_reply_action(ctx)) is True
        return ctx

    def word(text):
        seen.mine = Mine()
        seen.mine.reference = None
        ctx = Context(user=owner, channel_id=INBOX, message_id=60, text=text, _channel=seen.channel, _message=seen.mine)
        assert run(registry.dispatch_keyword(ctx)) is True
        return ctx

    seen.reply, seen.word = reply, word
    return seen


# --- the rule itself --------------------------------------------------------------------------------
def test_a_housekeeping_line_goes_after_ten_seconds_whatever_keep_confirmations_says(monkeypatch):
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: True)
    for kept in (True, False):
        monkeypatch.setattr(lifecycle, "keeps_confirmations", lambda kept=kept: kept)
        assert lifecycle.tidy_after() == 10 and lifecycle.tidy_after(15) == 15 and lifecycle.tidy_after(3) == 10
    monkeypatch.setattr(lifecycle, "keeps_confirmations", lambda: True)
    assert lifecycle.delete_after() is None, "any other confirmation stays while they are kept"
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: False)
    assert lifecycle.tidy_after() is None, "only `dev cleanup off` keeps it, as it keeps everything"


def test_every_housekeeping_word_reply_and_reaction_is_marked_and_none_keeps_its_command():
    registry.load()
    marked = set()
    for task in registry.loaded_tasks():
        for item in [*task.keywords(), *task.reply_actions(), *task.reactions()]:
            if item.housekeeping:
                marked.add((task.name, item.name))
                assert not getattr(item, "keep_command", False)
    assert marked == {
        ("archive", "archive"), ("archive", "delete"), ("archive", "📦"), ("archive", "🗑️"),
        ("keep", "pin"), ("keep", "unpin"), ("keep", "📌"), ("channel", "reset channel"),
    }
    assert registry.problems() == []


def test_a_housekeeping_word_that_kept_its_command_would_be_refused_at_load(monkeypatch):
    from tasks.base import Keyword, Task

    async def handler(ctx):
        return None

    class Untidy(Task):
        name = "untidy"

    monkeypatch.setattr(registry, "_problems", [])
    registry._check_registration(Untidy(), "keyword", Keyword(["sweep up"], "x", handler, housekeeping=True, keep_command=True))
    assert registry.problems() == ["untidy: keyword sweep up is housekeeping, which leaves no trace: it can't keep its command"]


# --- each of them, as a real reply -------------------------------------------------------------------
@pytest.mark.parametrize(
    "said, line, title",
    [
        ("pin", "📌 Pinned", "↩️ Reply action: pin"),
        ("pin this", "📌 Pinned", "↩️ Reply action: pin"),
        ("unpin", "📌 Unpinned", "↩️ Reply action: unpin"),
        ("archive", "📦 Archived: https://discord.test/copy", "↩️ Reply action: archive"),
        ("delete", "🗑️ Deleted", "↩️ Reply action: delete"),
    ],
)
def test_it_says_one_line_that_goes_deletes_my_word_and_is_recorded_in_bot_log(chat, said, line, title):
    chat.reply(said)
    assert chat.channel.sent == [(line, None)], "one line, with no timer in memory to lose in a restart"
    assert booked() == [(9001, TEN)], "it is booked to go after ten seconds, though confirmations are kept"
    assert chat.mine.deleted and chat.mine.reactions == [], "my word is deleted too"
    assert [logged[0] for logged in chat.logged] == [title], "and #bot-log has it"


def test_a_word_that_is_not_housekeeping_still_follows_keep_confirmations(chat):
    chat.word("ping")
    assert chat.channel.sent[0][1] is None, "an ordinary reply stays"


def test_when_it_cannot_be_done_the_reason_goes_after_ten_seconds_and_my_word_stays_marked(chat):
    chat.target = target(channel_id=ARCHIVE)  # a copy in the archive can't be archived again
    chat.reply("archive")
    (said, _), = chat.channel.sent
    assert said.startswith("⚠️ ") and booked() == [(9001, TEN)]
    assert not chat.mine.deleted and chat.mine.reactions == ["⚠️"], "a failure is not housekeeping done: the ⚠️ is how I know"
    assert chat.logged[0][0] == "Command failed: archive"


# --- a protected message is asked about first ---------------------------------------------------------
class Interaction:
    def __init__(self, question):
        self.edits, self.deferred = [], False
        self.channel_id = INBOX
        self.message = SimpleNamespace(id=question.id, edit=self._edit, delete=self._delete)
        self.response = SimpleNamespace(defer=self._defer)
        self.gone = False

    async def _edit(self, **changes):
        self.edits.append(changes)

    async def _delete(self):
        self.gone = True

    async def _defer(self):
        self.deferred = True


def test_confirming_a_protected_delete_says_so_briefly_and_records_it(chat):
    chat.target.pinned = True
    chat.target.channel = chat.channel
    chat.reply("delete")
    (question, stays), = chat.channel.sent
    assert question.startswith("⚠️ That message is pinned.") and chat.mine.deleted, "asked first; my word is gone already"

    async def confirmed():
        return "🗑️ Deleted"

    async def pressing():
        prompt = confirmations._Prompt(chat.owner, question, confirmed)
        prompt.housekeeping = True
        pressed = Interaction(SimpleNamespace(id=9001))
        await prompt._finish(pressed, f"confirmed: {question}", confirmed)
        return pressed

    pressed = run(pressing())
    assert pressed.edits == [{"content": "🗑️ Deleted", "view": None}], "how it went, in place of the question"
    assert booked() == [(9001, TEN)], "for ten seconds, then nothing"
    assert chat.logged[-1][0] == "☑️ Confirmed" and chat.logged[-1][1].endswith("🗑️ Deleted")


def test_a_question_that_is_not_housekeeping_keeps_its_answer_while_confirmations_are_kept(chat):
    async def confirmed():
        return "done"

    async def pressing():
        prompt = confirmations._Prompt(chat.owner, "Sure?", confirmed)
        pressed = Interaction(SimpleNamespace(id=9001))
        await prompt._finish(pressed, "confirmed: Sure?", confirmed)
        return pressed

    assert run(pressing()).edits[0]["delete_after"] is None
    assert chat.logged[-1] == ("☑️ Confirmed", "Sure?\ndone"), "but it is recorded all the same"


def test_archive_asks_about_a_protected_message_as_housekeeping(monkeypatch, owner):
    asked = []

    async def ask(channel, user, question, on_confirm, housekeeping=False):
        asked.append(housekeeping)

    monkeypatch.setattr(confirmations, "ask", ask)
    pinned = target()
    pinned.pinned = True

    async def perform(message, user):
        raise UserError("never reached")

    assert run(archive_messages._run_or_ask(pinned, owner, "Delete", perform)) is None and asked == [True]


# --- a reaction that can't be done ---------------------------------------------------------------------
def test_a_refused_housekeeping_reaction_says_why_for_ten_seconds(chat, monkeypatch):
    sent = []

    async def send(text, **options):
        sent.append((text, options.get("delete_after")))
        return SimpleNamespace(id=1)

    async def mark(channel_id, message_id, emoji, add=True):
        pass

    monkeypatch.setattr(registry, "_mark", mark)
    monkeypatch.setattr(registry, "_partial_message", lambda channel_id, message_id: SimpleNamespace(channel=SimpleNamespace(send=send)))
    archive = next(task for task in registry.loaded_tasks() if task.name == "archive")
    box = next(reaction for reaction in archive.reactions() if reaction.housekeeping)
    payload = SimpleNamespace(message_id=50, channel_id=INBOX)
    run(registry._refuse_reaction(archive, box, payload, chat.owner, "That message is already in the archive."))
    assert sent == [("⚠️ That message is already in the archive.", None)] and booked() == [(1, TEN)]


def test_a_pointer_line_goes_after_ten_seconds_even_while_confirmations_are_kept(db, monkeypatch, dev_off):
    from core import discord_utils

    channel = Channel()
    monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: channel))
    monkeypatch.setattr(lifecycle, "keeps_confirmations", lambda: True)
    run(tidy.pointer(INBOX, "💊 Today's checklist is in <#400>."))
    assert channel.sent == [("💊 Today's checklist is in <#400>.", None)], "deleted by the stored job, not by a timer in memory"
    assert booked() == [(9001, TEN)]
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: False)  # `dev cleanup off` is the one thing that keeps it
    run(tidy.pointer(INBOX, "💊 Today's checklist is in <#400>."))
    assert len(booked()) == 1
