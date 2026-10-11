"""Channel reset (tasks/channel, core/clearing.py): which messages go and how, the card, both
buttons, and every task putting its live messages back. Discord is a list of fake messages."""
import asyncio
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

from core import cards, clearing, clock, confirm, database, day, discord_utils, hub, live, livelists, llm
from core.actions import Request, Shown
from core.clearing import Found, Scan
from core.errors import UserError
from tasks import channel as channel_task
from tasks import registry
from tasks.channel import rules
from tasks.pills import checklist, plain as pills_plain
from tasks.pills import store as pills_store
from tasks.timers import board, sessions, timers
from tasks.timers import store as timers_store

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
INBOX, HUB = 100, 400


def message(message_id, days_old=0, protected=False, **said):
    return Found(message_id, NOW - timedelta(days=days_old), protected, "pinned" if protected else "", **said)


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


# ---------------------------------------------------------------------------
# What goes, and how (pure)
# ---------------------------------------------------------------------------
MIXED = [message(1), message(2, protected=True), message(3), message(4, days_old=20), message(5, days_old=30, protected=True), message(6)]


def test_delete_all_takes_everything_pinned_and_marked_included():
    todo = rules.plan(MIXED, keep_protected=False, now=NOW)
    assert todo.bulk == ((1, 2, 3, 6),) and todo.single == (4, 5) and todo.kept == 0
    assert todo.ids == {1, 2, 3, 4, 5, 6}


def test_delete_all_unpinned_leaves_what_is_pinned_or_marked():
    todo = rules.plan(MIXED, keep_protected=True, now=NOW)
    assert todo.bulk == ((1, 3, 6),) and todo.single == (4,) and todo.kept == 2
    assert todo.ids == {1, 3, 4, 6}


def test_messages_under_14_days_go_a_hundred_at_a_time_and_older_ones_singly():
    many = [message(number) for number in range(1, 251)] + [message(899, days_old=13.9), message(900, days_old=13.97), message(901, days_old=14.1)]
    todo = rules.plan(many, False, NOW)
    assert [len(batch) for batch in todo.bulk] == [100, 100, 51] and todo.single == (900, 901), "a little inside the 14 days, to be safe"
    assert rules.plan([message(1)], False, NOW) == rules.Plan((), (1,), 0), "one message is no batch"
    assert rules.plan([], False, NOW) == rules.Plan((), (), 0)


def test_the_card_that_is_asking_is_never_touched_or_counted():
    todo = rules.plan(MIXED, False, NOW, leave=frozenset({3}))
    assert 3 not in todo.ids and rules.counts(MIXED, NOW, frozenset({3})) == (5, 2, 2)
    assert rules.counts(MIXED, NOW) == (6, 2, 2)


def test_the_words():
    assert rules.card_text("<#100>", 134, 3, 0).splitlines() == [
        "🧹 Channel · reset", "134 messages in <#100>, 3 of them pinned or 📌", "⚠️ This can't be undone",
    ]
    assert rules.card_text("<#100>", 134, 3, 40).splitlines()[2] == (
        "⏳ 40 of them are over 14 days old and can only be deleted one at a time: that will be slow, about 1 minute"
    )
    assert "about 4 minutes" in rules.slow_text(200) and rules.slow_text(1).startswith("⏳ 1 of them is over")
    assert rules.cannot_text("<#100>", ("Manage Messages",)) == (
        "🧹 Channel · reset\n⚠️ I can't reset <#100>: my role needs **Manage Messages** in this channel. Nothing was deleted."
    )
    assert "**Read Message History** and **Manage Messages**" in rules.cannot_text("<#100>", ("Read Message History", "Manage Messages"))
    assert rules.done_text(131) == "🧹 Channel reset: 131 messages deleted · a copy was saved"
    assert rules.done_text(1, saved=False) == "🧹 Channel reset: 1 message deleted"
    assert rules.working_text(131, 0) == "🧹 Deleting 131 messages…"
    assert rules.working_text(131, 40) == "🧹 Deleting 131 messages (40 of them one at a time: this will be slow)…"
    assert rules.log_text("<#100>", 131, 3, 0) == "131 messages deleted in <#100> · 3 pinned or 📌 kept"
    assert rules.log_text("<#100>", 130, 0, 4) == "130 messages deleted in <#100> · nothing kept · 4 could not be deleted"
    assert rules.log_text("<#100>", 5, 0, 0, "inbox-2026-10-12-010000.txt").endswith("nothing kept · copy saved as `inbox-2026-10-12-010000.txt`")


def test_the_transcript_has_who_when_what_what_was_pinned_and_links_to_attachments():
    found = [
        message(3, author="Assistant", content="🏓 Pong!"),
        message(1, days_old=2, protected=True, author="Alnit0", content="shopping list:\nmilk\neggs"),
        Found(2, NOW - timedelta(days=1), True, "marked 📌", "Alnit0", "the boarding pass", ("https://cdn.example/pass.pdf", "https://cdn.example/seat.png")),
        message(4, author="Assistant", content=""),
    ]
    assert rules.transcript("inbox", found, NOW).splitlines() == [
        "#inbox · saved 2026-10-12 1:00 am · 4 messages",
        "",
        "[2026-10-10 1:00 am] Alnit0 (pinned): shopping list:",
        "    milk",
        "    eggs",
        "[2026-10-11 1:00 am] Alnit0 (marked 📌): the boarding pass",
        "    attachment: https://cdn.example/pass.pdf",
        "    attachment: https://cdn.example/seat.png",
        "[2026-10-12 1:00 am] Assistant: 🏓 Pong!",
        "[2026-10-12 1:00 am] Assistant:",
    ], "oldest first, in NZ time, whatever order Discord gave them in"
    assert rules.file_name("inbox", NOW) == "inbox-2026-10-12-010000.txt"
    assert rules.file_name("🍃 My Hub!", NOW) == "my-hub-2026-10-12-010000.txt" and rules.file_name("🍃", NOW).startswith("channel-")


# ---------------------------------------------------------------------------
# The Discord work (core/clearing.py), on a fake channel
# ---------------------------------------------------------------------------
def http_error(status, code=0):
    return discord.HTTPException(SimpleNamespace(status=status, reason="No"), {"code": code, "message": "No"})


def not_found():
    return discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), {"code": 10008, "message": "Unknown Message"})


class FakeChannel:
    type = discord.ChannelType.text
    mention = "<#100>"
    name = "inbox"

    def __init__(self, messages=(), allowed=("read_message_history", "manage_messages"), refuse_bulk=False, stuck=(), vanished=()):
        self.messages = list(messages)
        self.guild = SimpleNamespace(me="me")
        self.allowed, self.refuse_bulk, self.stuck, self.vanished = allowed, refuse_bulk, set(stuck), set(vanished)
        self.bulk, self.singles, self.sent = [], [], []

    def permissions_for(self, member):
        return SimpleNamespace(**{name: name in self.allowed for name in ("read_message_history", "manage_messages")})

    async def history(self, limit=None):
        for each in self.messages:
            yield each

    async def delete_messages(self, messages, reason=None):
        if self.refuse_bulk:
            raise http_error(400, 50034)
        self.bulk.append([each.id for each in messages])

    def get_partial_message(self, message_id):
        channel = self

        async def delete():
            if message_id in channel.vanished:
                raise not_found()
            if message_id in channel.stuck:
                raise http_error(403)
            channel.singles.append(message_id)

        return SimpleNamespace(delete=delete)

    async def send(self, text, delete_after=None):
        self.sent.append((text, delete_after))
        return SimpleNamespace(id=7000 + len(self.sent))


def real(message_id, pinned=False, marked=False, days_old=0, content="", attachments=(), embeds=()):
    reactions = [SimpleNamespace(emoji="📌", count=1)] if marked else []
    return SimpleNamespace(
        id=message_id, pinned=pinned, reactions=reactions, created_at=NOW - timedelta(days=days_old), content=content,
        author=SimpleNamespace(display_name="Alnit0"), attachments=[SimpleNamespace(url=url) for url in attachments], embeds=list(embeds),
    )


@pytest.fixture
def discord_channel(monkeypatch):
    def use(channel):
        monkeypatch.setattr(discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: channel))
        return channel

    return use


def test_a_scan_reads_every_message_and_which_are_pinned_or_marked(discord_channel):
    discord_channel(FakeChannel([real(1), real(2, pinned=True), real(3, marked=True)]))
    found = run(clearing.scan(INBOX))
    assert found.mention == "<#100>" and found.missing == ()
    assert [(each.id, each.protected) for each in found.messages] == [(1, False), (2, True), (3, True)]
    assert [each.why for each in found.messages] == ["", "pinned", "marked 📌"] and found.name == "inbox"


def test_a_scan_keeps_what_each_message_says_for_the_transcript(discord_channel):
    card = SimpleNamespace(title="💾 Backup saved", description="assistant.db")
    discord_channel(FakeChannel([real(1, content="hello", attachments=("https://cdn.example/a.png",)), real(2, embeds=(card,))]))
    first, second = run(clearing.scan(INBOX)).messages
    assert (first.author, first.content, first.attachments) == ("Alnit0", "hello", ("https://cdn.example/a.png",))
    assert second.content == "[💾 Backup saved]\n[assistant.db]", "a card with no text of its own is kept by its title and body"


def test_a_missing_permission_is_named_and_nothing_is_read(discord_channel):
    discord_channel(FakeChannel([real(1)], allowed=("read_message_history",)))
    assert run(clearing.scan(INBOX)) == Scan(INBOX, "<#100>", missing=("Manage Messages",), name="inbox")
    discord_channel(FakeChannel([real(1)], allowed=()))
    assert run(clearing.scan(INBOX)).missing == ("Read Message History", "Manage Messages")


def test_a_place_with_no_messages_to_clear_is_refused(discord_channel):
    forum = FakeChannel()
    forum.type = discord.ChannelType.forum
    discord_channel(forum)
    with pytest.raises(UserError, match="isn't a channel whose messages I can clear"):
        run(clearing.scan(INBOX))


def test_deleting_in_bulk_then_singly_and_what_is_gone(discord_channel):
    channel = discord_channel(FakeChannel(vanished={8}, stuck={9}))
    gone = run(clearing.delete(INBOX, [[1, 2, 3], [4, 5]], [7, 8, 9]))
    assert channel.bulk == [[1, 2, 3], [4, 5]] and channel.singles == [7]
    assert gone == {1, 2, 3, 4, 5, 7, 8}, "one that had already gone is gone; one that can't be deleted is not"


def test_a_batch_discord_refuses_is_done_one_by_one(discord_channel):
    channel = discord_channel(FakeChannel(refuse_bulk=True))
    assert run(clearing.delete(INBOX, [[1, 2]], [3])) == {1, 2, 3}
    assert channel.bulk == [] and channel.singles == [3, 1, 2]


def test_the_closing_line_is_booked_to_go_after_ten_seconds_even_while_confirmations_are_kept(discord_channel, monkeypatch, db):
    from core import devmode, lifecycle, scheduler, tidy

    channel = discord_channel(FakeChannel())
    monkeypatch.setattr(lifecycle, "keeps_confirmations", lambda: True)
    before = scheduler.utc_now()
    run(clearing.note(INBOX, "🧹 Channel reset: 3 messages deleted", 10))
    (job,) = run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND))
    assert job.payload == {"channel": INBOX, "message": 7001} and 9 <= (job.due_at - before).total_seconds() <= 11
    assert channel.sent == [("🧹 Channel reset: 3 messages deleted", None)], "deleted by the stored job, not by a timer in memory"
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: False)  # `dev cleanup off` is the one thing that keeps it
    run(clearing.note(INBOX, "🧹 Channel reset: 3 messages deleted", 10))
    assert len(run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND))) == 1, "nothing more is booked"


# ---------------------------------------------------------------------------
# Asking, and both buttons
# ---------------------------------------------------------------------------
@pytest.fixture
def world(make_db, monkeypatch, owner, tmp_path):
    make_db({"pills": pills_store.MIGRATIONS, "timers": timers_store.MIGRATIONS})
    monkeypatch.setattr(channel_task, "EXPORT_DIR", tmp_path / "exports")  # never the real data folder
    seen = SimpleNamespace(
        owner=owner, sent=[], deleted=[], edited=[], notes=[], logged=[], cleared=[], next_id=5000, exports=tmp_path / "exports",
        messages=[
            message(1, author="Alnit0", content="one"), message(2, protected=True, author="Alnit0", content="keep me"),
            message(3, author="Assistant", content="three"), message(4, days_old=20, author="Alnit0", content="an old one"), message(5),
        ],
        missing=(), again=[], asked_again=[],
    )

    async def reposted(channel_id, gone):
        seen.asked_again.append((channel_id, set(gone)))
        return list(seen.again)

    async def scan(channel_id):
        return Scan(channel_id, f"<#{channel_id}>", () if seen.missing else tuple(seen.messages), seen.missing, name="inbox")

    async def delete(channel_id, bulk, single):
        ids = {each for batch in bulk for each in batch} | set(single)
        seen.messages = [each for each in seen.messages if each.id not in ids]
        seen.deleted += sorted(ids)
        return ids

    async def note(channel_id, text, seconds):
        seen.notes.append((channel_id, text, seconds))

    async def send(channel_id, card, silent=False):
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def remove(channel_id, message_id):
        seen.messages = [each for each in seen.messages if each.id != message_id]
        seen.deleted.append(message_id)
        return True

    async def edit(channel_id, message_id, card):
        seen.edited.append((message_id, card.text))
        return True

    async def log_simple(title, description=None):
        seen.logged.append((title, description))

    async def cleared(channel_id, gone):
        seen.cleared.append((channel_id, set(gone)))

    monkeypatch.setattr(clearing, "scan", scan)
    monkeypatch.setattr(clearing, "delete", delete)
    monkeypatch.setattr(clearing, "note", note)
    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "delete", remove)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(channel_task, "log_simple", log_simple)
    monkeypatch.setattr(registry, "channel_cleared", cleared)
    monkeypatch.setattr(registry, "reposted", reposted)
    monkeypatch.setattr(clock, "real_now", lambda: NOW)
    monkeypatch.setattr(llm, "_exchanges", {})
    live.reset()
    return seen


ASKED = 6  # the id of my own message that asks, in the tests below


class Press:
    def __init__(self, user, channel_id, message_id, asked_by=ASKED):
        self.user, self.arg, self.channel_id, self.message_id = user, f"{channel_id}:{asked_by or 0}", channel_id, message_id
        self.shown, self.removed = [], False

    async def update(self, card):
        self.shown.append(card)

    async def remove(self):
        self.removed = True


def ask(world, channel_id=INBOX):
    """Ask in plain words: the card that comes back, as the message it is."""
    world.messages.append(message(ASKED, author="Alnit0", content="reset this channel"))  # my own message, in the channel
    asking = Request(world.owner, channel_id, "reset this channel", message_id=ASKED)
    shown = run(channel_task.reset_asked(asking, {}, frozenset()))
    assert shown == Shown(f"asked before resetting <#{channel_id}>")
    return world.sent[-1]


def test_asking_always_shows_a_card_with_the_counts_and_three_buttons(world):
    posted = ask(world)
    assert posted.card.text.splitlines() == [
        "🧹 Channel · reset",
        "5 messages in <#100>, 1 of them pinned or 📌",
        "⏳ 1 of them is over 14 days old and can only be deleted one at a time: that will be slow, about 1 minute",
        "⚠️ This can't be undone",
    ]
    (row,) = posted.card.rows
    assert [(button.label, button.action, button.arg) for button in row] == [
        ("Delete all", "all", "100:6"), ("Delete all unpinned", "unpinned", "100:6"), ("Cancel", "cancel", "100:6"),
    ], "each button carries the channel and the message that asked"
    assert [(button.label, button.style, button.emoji) for button in row] == [
        ("Delete all", cards.DANGER, "🗑️"), ("Delete all unpinned", cards.PRIMARY, "📌"), ("Cancel", cards.SECONDARY, "↩️"),
    ], "red for what destroys, blurple for the other choice, grey for Cancel alone"
    assert world.deleted == [], "nothing is deleted by asking"


def test_the_card_lists_what_will_be_posted_again(world):
    world.again = ["Active timers: Pomodoro waiting to start", "Today's pills checklist"]
    posted = ask(world)
    assert posted.card.text.splitlines() == [
        "🧹 Channel · reset",
        "5 messages in <#100>, 1 of them pinned or 📌",
        "⏳ 1 of them is over 14 days old and can only be deleted one at a time: that will be slow, about 1 minute",
        "♻️ Posted again afterwards:",
        "• Active timers: Pomodoro waiting to start",
        "• Today's pills checklist",
        "⚠️ This can't be undone",
    ]
    assert world.asked_again == [(INBOX, {1, 2, 3, 4, 5, ASKED})], "the tasks are asked about everything that is there"


def test_with_nothing_to_post_again_the_card_says_nothing_about_it(world):
    assert "♻️" not in ask(world).card.text
    assert rules.card_text("<#100>", 3, 0, 0) == "🧹 Channel · reset\n3 messages in <#100>, 0 of them pinned or 📌\n⚠️ This can't be undone"


def test_what_the_timers_would_post_again_is_said_in_a_line(world):
    def timer(label, message_id, status=timers_store.RUNNING):
        made = timers_store.Timer(
            user_id=world.owner.id, discord_user_id=1, channel_id=INBOX, label=label, duration_s=300, status=status,
            ends_at=clock.now() + timedelta(minutes=5), message_id=message_id, remaining_s=120 if status == timers_store.PAUSED else None,
        )
        return run(timers_store.add_timer(made))

    assert run(board.reposted(INBOX, {11, 12})) == [], "nothing is going"
    timer("tea", 11), timer("dinner", 12, timers_store.PAUSED), timer("old", 13, timers_store.CANCELLED)
    assert run(board.reposted(INBOX, {11, 99})) == ["Active timers: tea, dinner (paused)"]
    assert run(board.reposted(INBOX, {98, 99})) == [], "none of their messages is going: nothing to post again"
    assert run(board.reposted(HUB, {11, 12})) == [], "another channel"
    waiting = SimpleNamespace(state=timers_store.WAITING)
    running = SimpleNamespace(state=timers_store.RUNNING)
    assert board.again_text([], [waiting]) == "Active timers: Pomodoro waiting to start"
    assert board.again_text([], [running]) == "Active timers: Pomodoro running"


def test_every_task_is_asked_what_it_would_post_again_and_one_failing_is_left_out(monkeypatch):
    monkeypatch.undo()

    class Says:
        name = "says"

        async def reposted(self, channel_id, gone):
            return [f"{len(gone)} of mine"]

    class Broken:
        name = "broken"

        async def reposted(self, channel_id, gone):
            raise RuntimeError("no")

    monkeypatch.setattr(registry, "_tasks", [Broken(), Says()])
    assert run(registry.reposted(INBOX, {1, 2})) == ["2 of mine"]


def test_with_nothing_pinned_or_marked_delete_all_unpinned_is_not_offered(world):
    world.messages = [each for each in world.messages if not each.protected]
    posted = ask(world)
    assert posted.card.text.splitlines()[1] == "4 messages in <#100>, 0 of them pinned or 📌"
    assert [button.label for button in posted.card.rows[0]] == ["Delete all", "Cancel"], "it would do the same as Delete all"


def test_the_typed_word_asks_the_same_and_does_not_count_itself(world):
    posted = []

    async def reply(text, view=None):
        posted.append(text)
        return SimpleNamespace(id=77)

    ctx = SimpleNamespace(user=world.owner, channel_id=INBOX, message_id=5, reply=reply)
    assert run(channel_task.reset_word(ctx)) == "asked before resetting <#100>"
    assert posted[0].splitlines()[1] == "4 messages in <#100>, 1 of them pinned or 📌", "the word itself is tidied away: not one of them"


def test_delete_all_deletes_everything_and_the_card_then_says_so_and_tells_every_task(world):
    posted = ask(world)
    world.messages.append(message(posted.id))  # the card is in the channel too
    press = Press(world.owner, INBOX, posted.id)
    assert run(channel_task.on_all(press)) == "🧹 Channel reset: 5 messages deleted · a copy was saved"
    assert [card.text for card in press.shown] == ["🧹 Deleting 5 messages (1 of them one at a time: this will be slow)…"]
    assert world.deleted[:5] == [1, 2, 3, 4, 5] and set(world.deleted[5:]) == {ASKED, posted.id}, "pinned and 📌 included; my message and the card last"
    assert world.messages == [], "no trace of the reset: nothing is left in the channel at all"
    assert world.notes == [(INBOX, "🧹 Channel reset: 5 messages deleted · a copy was saved", 10)], "only the line that goes after ten seconds"
    assert world.cleared == [(INBOX, {1, 2, 3, 4, 5, ASKED, posted.id})]
    assert world.logged == [("🧹 Channel reset", "5 messages deleted in <#100> · nothing kept · copy saved as `inbox-2026-10-12-010000.txt`")]
    assert llm.exchanges_for(INBOX) == [("(pressed Delete all)", "🧹 Channel reset: 5 messages deleted · a copy was saved")]
    # The copy: everything that was there, the card apart, written before anything went
    (saved,) = world.exports.iterdir()
    assert saved.name == "inbox-2026-10-12-010000.txt"
    assert saved.read_text(encoding="utf-8").splitlines() == [
        "#inbox · saved 2026-10-12 1:00 am · 6 messages",
        "",
        "[2026-09-22 12:00 am] Alnit0: an old one",  # before the clocks went forward
        "[2026-10-12 1:00 am] Alnit0: one",
        "[2026-10-12 1:00 am] Alnit0 (pinned): keep me",
        "[2026-10-12 1:00 am] Assistant: three",
        "[2026-10-12 1:00 am] unknown:",
        "[2026-10-12 1:00 am] Alnit0: reset this channel",  # my own message may be in the copy
    ]


def test_delete_all_unpinned_leaves_the_pinned_and_marked_ones(world):
    posted = ask(world)
    world.messages.append(message(posted.id))
    assert run(channel_task.on_unpinned(Press(world.owner, INBOX, posted.id))) == "🧹 Channel reset: 4 messages deleted · a copy was saved"
    assert [each.id for each in world.messages] == [2], "the pinned one is still there"
    assert world.cleared == [(INBOX, {1, 3, 4, 5, ASKED, posted.id})], "tasks are told what went: what was kept is not posted again"
    assert world.logged[0][1].startswith("4 messages deleted in <#100> · 1 pinned or 📌 kept · copy saved as `inbox-")
    (saved,) = world.exports.iterdir()
    assert "Alnit0 (pinned): keep me" in saved.read_text(encoding="utf-8"), "the copy is of the whole channel, what is kept included"


def test_if_the_copy_cannot_be_saved_nothing_is_deleted(world, monkeypatch):
    reported = []

    def refuse(folder, name, text):
        raise OSError("disk full")

    async def log_error(title, details, user_text=None):
        reported.append((title, details))

    monkeypatch.setattr(channel_task, "_write", refuse)
    monkeypatch.setattr(channel_task, "log_error", log_error)
    posted = ask(world)
    press = Press(world.owner, INBOX, posted.id)
    assert run(channel_task.on_all(press)) == "not saved, nothing deleted"
    assert world.deleted == [] and world.cleared == [] and world.notes == [] and len(world.messages) == 6, "my message included"
    assert press.shown[-1].text == (
        "🧹 Channel · reset\n⚠️ I couldn't save a copy of this channel first, so nothing was deleted. The reason is in #bot-log."
    )
    assert [[button.label for button in row] for row in press.shown[-1].rows] == [["Cancel"]]
    assert reported == [("Channel reset stopped: no copy could be saved", "OSError('disk full')")]


def test_what_is_deleted_is_what_is_there_when_the_button_is_pressed(world):
    posted = ask(world)
    world.messages += [message(posted.id), message(50), message(51)]  # two more arrived after the card
    assert run(channel_task.on_all(Press(world.owner, INBOX, posted.id))) == "🧹 Channel reset: 7 messages deleted · a copy was saved"
    assert "8 messages" in next(world.exports.iterdir()).read_text(encoding="utf-8").splitlines()[0], "and so is the copy, with my own message in it"


def test_cancel_removes_the_card_and_my_message_and_nothing_else(world):
    posted = ask(world)
    press = Press(world.owner, INBOX, posted.id)
    assert run(channel_task.on_cancel(press)) == "cancelled" and press.removed, "the card goes"
    assert world.deleted == [ASKED], "and so does the message that asked: no trace of the question either"
    assert [each.id for each in world.messages] == [1, 2, 3, 4, 5] and world.notes == [] and world.exports.exists() is False


def test_cancel_after_the_typed_word_has_nothing_more_to_delete(world):
    # The word was tidied away by the registry already (it is housekeeping): deleting it again is harmless
    press = Press(world.owner, INBOX, 900, asked_by=None)
    assert run(channel_task.on_cancel(press)) == "cancelled" and press.removed and world.deleted == []


def test_a_missing_permission_is_said_on_the_card_instead_of_failing(world):
    world.missing = ("Manage Messages",)
    posted = ask(world)
    assert posted.card.text == (
        "🧹 Channel · reset\n⚠️ I can't reset <#100>: my role needs **Manage Messages** in this channel. Nothing was deleted."
    )
    assert [[button.label for button in row] for row in posted.card.rows] == [["Cancel"]]
    # And if it goes missing between the card and the press
    press = Press(world.owner, INBOX, posted.id)
    assert run(channel_task.on_all(press)) == "missing Manage Messages"
    assert "my role needs **Manage Messages**" in press.shown[0].text and world.deleted == [] and world.cleared == []
    assert press.shown[0].rows[0][0].arg == "100:6", "Cancel on it still knows which message asked"


def test_an_empty_channel_is_said_in_a_line_with_no_card(world):
    world.messages = [message(ASKED)]  # nothing there but my own message asking
    said = run(channel_task.reset_asked(Request(world.owner, INBOX, "reset this channel", message_id=ASKED), {}, frozenset()))
    assert said == Shown("nothing to delete") and world.sent == []
    assert world.notes == [(INBOX, "🧹 <#100> is already empty: there is nothing to delete.", 10)], "said for a moment"
    assert world.deleted == [ASKED], "and my message goes too: no trace"


def test_the_word_carries_the_tasks_name_is_exact_and_leaves_reset_alone():
    registry.load()
    kind, task, keyword = registry.find("reset channel")
    assert (kind, task.name, keyword.exact, keyword.channels) == ("keyword", "channel", True, "any")
    assert keyword.housekeeping and not keyword.keep_command, "the typed word is tidied away by the registry"
    assert registry._keyword_router.match("reset channel").entry is not registry._keyword_router.match("reset").entry
    assert registry._keyword_router.match("reset chanel") is None, "a destructive word is never matched by a typo"
    assert registry.find("reset")[1].name == "builtin"
    entry = next(each for each in task.entries())
    assert (entry.icon, entry.examples) == ("🧹", ("reset this channel", "clean up this channel"))
    assert [(action.name, action.needs_card) for action in entry.actions] == [("channel_reset", False)]


# ---------------------------------------------------------------------------
# Putting live messages back: nothing orphaned, nothing twice
# ---------------------------------------------------------------------------
def test_todays_checklist_and_its_taken_skip_messages_are_posted_again_and_the_records_follow(world, monkeypatch):
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    request = Request(world.owner, INBOX, "said")
    proposal = run(pills_plain.add_card(request, {"pills": [{"name": "Zinc"}, {"name": "Evening pill", "times": ["8:00 pm"]}]}, frozenset()))
    run(pills_plain.add_save(request, proposal.data))
    run(checklist.post(world.owner.id))
    old = [each.id for each in world.sent]
    today_ = day.today()
    assert [m.message_id for m in run(database.run(pills_store.db_messages, world.owner.id, today_))] == old and len(old) == 2

    run(checklist.channel_cleared(HUB, set(old)))
    fresh = world.sent[2:]
    assert [each.card.text.splitlines()[0] for each in fresh] == ["## 💊 Pills · ▱▱▱▱▱ 0 of 2", "💊 **Zinc**"] and all(each.silent for each in fresh)
    assert [button.label for button in fresh[1].card.rows[0]] == ["Taken", "Skip"]
    records = run(database.run(pills_store.db_messages, world.owner.id, today_))
    assert [m.message_id for m in records] == [each.id for each in fresh], "the records point at the new messages, and only those"

    # The new Taken button works, and changes the new checklist
    pressed = SimpleNamespace(user=world.owner, arg=str(records[1].occurrence_id), channel_id=HUB, message_id=records[1].message_id, remove=Press(None, 0, 0).remove)
    assert run(checklist.on_taken(pressed)).startswith("✅ **Zinc** · taken")
    assert world.edited[-1][0] == fresh[0].id and "✅ **Zinc**" in world.edited[-1][1]


def test_a_checklist_that_was_kept_or_is_in_another_channel_is_not_posted_twice(world, monkeypatch):
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    request = Request(world.owner, INBOX, "said")
    proposal = run(pills_plain.add_card(request, {"pills": [{"name": "Zinc"}]}, frozenset()))
    run(pills_plain.add_save(request, proposal.data))
    run(checklist.post(world.owner.id))
    run(checklist.channel_cleared(HUB, {1, 2, 3}))  # the hub was reset, but the checklist was pinned and kept
    run(checklist.channel_cleared(INBOX, {each.id for each in world.sent}))  # another channel was reset
    assert len(world.sent) == 2


def test_running_timers_get_their_cards_back_and_point_at_them(world):
    def timer(label, message_id, status=timers_store.RUNNING):
        made = timers_store.Timer(
            user_id=world.owner.id, discord_user_id=1, channel_id=INBOX, label=label, duration_s=300, status=status,
            ends_at=clock.now() + timedelta(minutes=5), message_id=message_id,
        )
        return run(timers_store.add_timer(made))

    tea, kept, done = timer("tea", 11), timer("dinner", 12), timer("old", 13, timers_store.CANCELLED)
    posted = []

    async def send(text, view=None):
        posted.append(text)
        return SimpleNamespace(id=900 + len(posted))

    assert run(timers.repost(INBOX, {11, 13, 99}, send)) == 1
    assert len(posted) == 1 and posted[0].startswith("⏱️ **tea** · 5m · ends ")
    assert run(timers_store.get_timer(tea.id)).message_id == 901, "the timer answers to its new card"
    assert run(timers_store.get_timer(kept.id)).message_id == 12, "its card was kept: left alone, not posted twice"
    assert run(timers_store.get_timer(done.id)).message_id == 13, "a timer that is over has no card to put back"
    assert run(timers_store.timer_by_message(901)).label == "tea" and run(timers_store.timer_by_message(11)) is None
    assert run(sessions.repost(INBOX, {11}, send)) == 0, "no session going: nothing to post"


def test_every_task_is_told_and_one_failing_does_not_stop_the_others(monkeypatch):
    monkeypatch.undo()
    told = []

    class Fine:
        name = "fine"

        async def channel_cleared(self, channel_id, gone):
            told.append((channel_id, gone))

    class Broken:
        name = "broken"

        async def channel_cleared(self, channel_id, gone):
            raise RuntimeError("no")

    reported = []

    async def log_error(title, details, user_text=None):
        reported.append(title)

    monkeypatch.setattr(registry, "_tasks", [Broken(), Fine()])
    monkeypatch.setattr(registry, "log_error", log_error)
    run(registry.channel_cleared(INBOX, {1}))
    assert told == [(INBOX, {1})] and reported == ["Not re-posted after a channel reset: broken"]


def test_open_cards_and_lists_that_went_are_forgotten(world):
    def add_card(conn):
        conn.execute(
            "INSERT INTO confirm_cards (user_id, channel_id, message_id, kind, task, action, data, guessed, said, status, created_at) "
            "VALUES (?, ?, 700, 'card', 'pills', 'pill_add', '{}', '[]', 'add zinc', 'open', '2026-10-11T00:00:00+00:00')",
            (world.owner.id, INBOX),
        )

    run(database.run(add_card))
    run(livelists.placed(world.owner.id, "pills", INBOX, 701, "pills"))
    assert run(confirm.latest_open(world.owner.id, INBOX)) is not None
    run(confirm.forget({700, 701}))
    run(livelists.forget({700, 701}))
    assert run(confirm.latest_open(world.owner.id, INBOX)) is None, "no later message is taken as being about a card that is gone"
    assert run(livelists.by_message(701)) is None
