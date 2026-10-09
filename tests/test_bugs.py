import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import database
from core.errors import UserError
from core.permissions import is_allowed
from tasks import bugs
from tasks.bugs import capture, cli, posts, rules, store

INBOX, BUGS, ELSEWHERE = 100, 300, 999
AT = datetime(2026, 10, 9, 1, 0, 30, tzinfo=timezone.utc)  # 14:00:30 in Auckland
URL = "https://discord.com/channels/1/300/7000"


def snap(message_id=5001, content="⏱️ Timer set for 50m", author="Hive", at=AT) -> rules.Snapshot:
    return rules.Snapshot(message_id, author, content, at.isoformat(), f"https://discord.com/channels/1/100/{message_id}")


def report(**values) -> rules.Report:
    defaults = dict(
        source=rules.REACTION,
        channel_id=INBOX,
        channel="#inbox",
        target=snap(),
        preceding=[snap(4999, "set a timer for 5 minutes", "Alex", AT - timedelta(seconds=4))],
        turn=None,
        errors=[],
        commit="03c7d23",
        reported_at="2026-10-09T01:01:00.000000+00:00",
    )
    return rules.Report(**{**defaults, **values})


# --- ids and where ------------------------------------------------------------
@pytest.mark.parametrize("text, number", [("B4", 4), ("b12", 12), (" 7 ", 7)])
def test_an_id_is_read_with_or_without_its_letter(text, number):
    assert rules.parse_id(text) == number
    assert rules.bug_id(4) == "B4"


@pytest.mark.parametrize("text", ["", "I4", "B", "B4x", "four"])
def test_anything_else_is_not_an_id(text):
    with pytest.raises(UserError):
        rules.parse_id(text)


def test_a_post_in_the_forum_is_known_by_its_parent():
    assert rules.in_bugs_forum(BUGS)
    assert not rules.in_bugs_forum(INBOX) and not rules.in_bugs_forum(None)


def test_a_message_inside_a_bugs_post_cannot_be_reported():
    rules.check_reportable(SimpleNamespace(channel=SimpleNamespace(id=INBOX)))
    rules.check_reportable(SimpleNamespace(channel=SimpleNamespace(id=7, parent_id=ELSEWHERE)))
    with pytest.raises(UserError, match="already in a bug's post"):
        rules.check_reportable(SimpleNamespace(channel=SimpleNamespace(id=7, parent_id=BUGS)))


def test_a_channel_is_named_if_we_know_it():
    assert rules.channel_label(INBOX) == "#inbox"
    assert rules.channel_label(ELSEWHERE) == "<#999>"


# --- a message as plain values --------------------------------------------------
def test_a_snapshot_keeps_who_what_when_and_where():
    message = SimpleNamespace(
        id=5, author=SimpleNamespace(display_name="Alex"), content=" hello ", created_at=AT, jump_url="https://x/5",
        embeds=[], attachments=[],
    )
    assert rules.snapshot(message) == rules.Snapshot(5, "Alex", "hello", AT.isoformat(), "https://x/5")


def test_a_card_and_files_are_put_into_words():
    message = SimpleNamespace(
        content="", embeds=[SimpleNamespace(title="💬 Message handled", description=None)], attachments=[1, 2]
    )
    assert rules.message_text(message) == "[card] 💬 Message handled\n[2 attachments]"
    assert rules.message_text(SimpleNamespace(content="")) == "(no text)"


def test_a_report_survives_being_stored():
    original = report(turn={"kind": "chat"}, errors=["ERROR x"])
    assert rules.Report.from_json(original.to_json()) == original


# --- which turn a message belongs to ---------------------------------------------
def row(row_id, kind, content, message_id, seconds_before, **more) -> dict:
    received = (AT - timedelta(seconds=seconds_before)).astimezone(timezone(timedelta(hours=13)))
    base = dict(
        id=row_id, received_at=received.isoformat(), kind=kind, content=content, discord_message_id=message_id,
        reply=None, status="ok", error=None, duration_s=None, timing=None,
    )
    return {**base, **more}


ROWS = [  # newest first, as the store hands them over
    row(14, "command", "bug", 4100, -20),
    row(13, "reaction", "reaction: 📌", 5001, -10),
    row(12, "tool", 'tool: timer {"duration": "50m"}', 4000, 3, reply="timer 1 started for 50m"),
    row(
        11, "chat", "set a timer for 5 minutes", 4000, 4, reply="Done", duration_s=2.5,
        timing=json.dumps({"total_s": 2.5, "claude": [], "tools": []}),
    ),
    row(10, "command", "ping", 3000, 600, reply="🏓 Pong!"),
]


def test_a_message_of_the_users_is_found_by_its_id():
    turn = rules.pick_turn(ROWS, 3000, AT)
    assert (turn["kind"], turn["input"], turn["reply"], turn["tools"]) == ("command", "ping", "🏓 Pong!", [])


def test_a_message_of_the_bots_belongs_to_what_was_sent_before_it():
    turn = rules.pick_turn(ROWS, 5001, AT, exclude_message_id=4100)
    assert turn["input"] == "set a timer for 5 minutes" and turn["duration_s"] == 2.5
    assert turn["timing"] == {"total_s": 2.5, "claude": [], "tools": []}
    assert turn["tools"] == [
        {"call": 'timer {"duration": "50m"}', "result": "timer 1 started for 50m", "status": "ok", "error": None}
    ]


def test_the_bug_command_itself_is_never_the_turn():
    late = AT + timedelta(minutes=5)
    assert rules.pick_turn(ROWS, 9999, late)["input"] == "bug"
    assert rules.pick_turn(ROWS, 9999, late, exclude_message_id=4100)["input"] == "set a timer for 5 minutes"


def test_clocks_a_few_seconds_apart_still_find_the_turn():
    # Discord stamped the reply two seconds before our clock logged the message
    assert rules.pick_turn(ROWS, 5001, AT - timedelta(seconds=6))["input"] == "set a timer for 5 minutes"
    assert rules.pick_turn(ROWS, 5001, AT - timedelta(seconds=30))["input"] == "ping"


def test_no_turn_is_found_when_nothing_was_logged_before():
    assert rules.pick_turn(ROWS, 5001, AT - timedelta(hours=1)) is None
    assert rules.pick_turn([], 5001, AT) is None


# --- which log lines go with it -------------------------------------------------
LOG = """\
2026-10-09 13:59:00,100 ERROR assistant: too early
2026-10-09 14:00:26,500 INFO assistant: Received: set a timer for 5 minutes
2026-10-09 14:00:27,900 WARNING discord.http: We are being rate limited.
2026-10-09 14:00:28,200 ERROR assistant: Command failed: timer
Traceback (most recent call last):
  File "tasks/timers/durations.py", line 40, in parse
ValueError: bad duration

2026-10-09 14:00:29,000 INFO assistant: Timing: total 2.31s
2026-10-09 14:05:00,000 ERROR assistant: too late
""".splitlines()


def test_only_warnings_and_errors_in_the_window_are_kept_with_their_tracebacks():
    found = rules.related_errors(LOG, datetime(2026, 10, 9, 14, 0, 21), datetime(2026, 10, 9, 14, 1, 0))
    assert found == [
        "2026-10-09 14:00:27,900 WARNING discord.http: We are being rate limited.",
        "2026-10-09 14:00:28,200 ERROR assistant: Command failed: timer",
        "Traceback (most recent call last):",
        '  File "tasks/timers/durations.py", line 40, in parse',
        "ValueError: bad duration",
    ]


def test_a_long_run_of_errors_is_cut_short_and_says_so():
    found = rules.related_errors(LOG, datetime(2026, 10, 9, 13, 0), datetime(2026, 10, 9, 15, 0), limit=2)
    assert found[:2] == [LOG[0], LOG[2]] and found[2] == "… and 5 more lines"


def test_the_window_is_the_turn_with_a_little_either_side():
    turn = {"received_at": "2026-10-09T14:00:26+13:00", "duration_s": 2.5}
    start, end = rules.log_window(turn, AT)
    assert start == datetime.fromisoformat("2026-10-09T14:00:21+13:00")
    assert end == datetime.fromisoformat("2026-10-09T14:00:58.500+13:00")
    assert rules.log_window(None, AT) == (AT - timedelta(seconds=60), AT + timedelta(seconds=60))


def test_the_log_tail_is_read_from_the_end(tmp_path):
    path = tmp_path / "bot.log"
    path.write_bytes(b"first line\nsecond line\nthird line\n")
    assert capture.read_log_tail(path) == ["first line", "second line", "third line"]
    assert capture.read_log_tail(path, max_bytes=15) == ["third line"], "a line cut in half is left out"
    assert capture.read_log_tail(tmp_path / "missing.log") == []


# --- wording -----------------------------------------------------------------
def test_a_title_is_the_id_and_the_start_of_the_message():
    assert rules.title(4, "⏱️ Timer set\nfor 50m") == "B4 · ⏱️ Timer set for 50m"
    assert len(rules.title(4, "x" * 500)) <= rules.TITLE_LIMIT
    assert rules.title(4, "   ") == "B4 · (no text)"


def test_the_line_left_in_the_channel_links_to_the_post():
    assert rules.logged_text(4, URL) == f"🐞 Logged as [B4]({URL})"
    assert rules.logged_text(4, URL, existing=True) == f"🐞 Already logged as [B4]({URL})"
    assert rules.logged_text(4, None) == "🐞 Logged as B4"


def test_closing_says_which_way():
    assert rules.closed_text(4, rules.FIXED) == "✅ B4 closed as Fixed"
    assert rules.closed_text(4, rules.WONTFIX, already=True) == "Already B4 is closed as Won't fix"


def test_the_post_opens_with_the_message_and_ends_with_the_questions():
    turn = rules.pick_turn(ROWS, 5001, AT, exclude_message_id=4100)
    parts = rules.post_sections(4, report(turn=turn, errors=["2026-10-09 14:00:28,200 ERROR assistant: boom"]))
    assert parts[0].startswith("🐞 **B4** · from #inbox · <t:1791507660:f> · by a 🐞 reaction · commit `03c7d23`")
    assert "**Message**\nHive, 14:00 · [jump](https://discord.com/channels/1/100/5001)\n> ⏱️ Timer set for 50m" in parts[0]
    assert parts[1] == "**Before it**\n`14:00` **Alex**: set a timer for 5 minutes"
    assert parts[2].startswith("**That turn**\nInput (chat): `set a timer for 5 minutes`\nOutcome: ok in 2.5s")
    assert '🔧 `timer {"duration": "50m"}` (ok) timer 1 started for 50m' in parts[2]
    assert "Timings: 2.50s to the reply" in parts[2]
    assert parts[3] == "**Related errors**\n```\n2026-10-09 14:00:28,200 ERROR assistant: boom\n```"
    assert parts[4] == rules.QUESTIONS
    for question in ("What did you expect?", "What happened instead?", "Has it happened before?"):
        assert question in rules.QUESTIONS


def test_a_report_with_nothing_found_says_so():
    parts = rules.post_sections(1, report(preceding=[]))
    assert parts[1].endswith("Nothing before it in the channel.")
    assert parts[2].endswith("No logged turn was found for this message.")
    assert parts[3].endswith("None in the log around that time.")


def test_every_part_of_the_post_fits_in_a_discord_message():
    long = report(
        target=snap(content="x" * 5000),
        preceding=[snap(4990 + number, "y" * 3000) for number in range(5)],
        errors=["2026-10-09 14:00:28,200 ERROR assistant: " + "z" * 200] * 60,
    )
    assert all(len(part) <= 2000 for part in rules.post_sections(1, long))


def test_tags_are_swapped_for_the_new_status_and_others_are_kept():
    assert rules.tags_after(["Open", "timers"], rules.FIXED) == ["timers", "Fixed"]
    assert rules.tags_after(["fixed"], rules.WONTFIX) == ["Won't fix"]
    assert rules.missing_tags(["open", "Urgent"]) == ["Fixed", "Won't fix"]
    assert rules.missing_tags(["Open", "Fixed", "Won't fix"]) == []


# --- the store ----------------------------------------------------------------
@pytest.fixture
def bugs_db(make_db):
    make_db({"bugs": store.MIGRATIONS})


def test_bugs_are_numbered_in_order_and_start_open(bugs_db):
    first = asyncio.run(store.add(1, report()))
    second = asyncio.run(store.add(1, report(target=snap(5002, "another"))))
    assert (first, second) == (1, 2)
    item = asyncio.run(store.get(first))
    assert (item.status, item.summary, item.user_id) == (rules.OPEN, "⏱️ Timer set for 50m", 1)
    assert item.report == report() and item.thread_id is None and item.closed_at is None
    assert asyncio.run(store.get(99)) is None


def test_a_bug_is_found_by_its_post_and_by_its_message(bugs_db):
    number = asyncio.run(store.add(1, report()))
    asyncio.run(store.set_post(number, 7000, URL))
    assert asyncio.run(store.by_thread(7000)).post_url == URL
    assert asyncio.run(store.by_thread(7001)) is None
    assert asyncio.run(store.open_for(1, INBOX, 5001)).id == number
    assert asyncio.run(store.open_for(1, INBOX, 5002)) is None
    assert asyncio.run(store.open_for(2, INBOX, 5001)) is None, "someone else's report is not yours"


def test_a_closed_bug_leaves_the_list_and_its_message_can_be_reported_again(bugs_db):
    number = asyncio.run(store.add(1, report()))
    other = asyncio.run(store.add(1, report(target=snap(5002, "another"))))
    asyncio.run(store.set_status(number, rules.WONTFIX))
    assert [item.id for item in asyncio.run(store.open_items(1))] == [other]
    closed = asyncio.run(store.get(number))
    assert closed.status == rules.WONTFIX and closed.closed_at is not None
    assert asyncio.run(store.open_for(1, INBOX, 5001)) is None
    assert asyncio.run(store.open_items(2)) == []


def test_notes_are_kept_in_order_with_who_wrote_them(bugs_db):
    number = asyncio.run(store.add(1, report()))
    asyncio.run(store.add_note(number, 1, rules.OWNER, "I asked for 5 minutes", 8001))
    assert asyncio.run(store.get(number)).fix_ready is False
    asyncio.run(store.add_note(number, 1, rules.CLAUDE_CODE, f"{rules.FIX_READY}: minutes parsed as tens"))
    notes = asyncio.run(store.notes(number))
    assert [(note.author, note.content) for note in notes] == [
        (rules.OWNER, "I asked for 5 minutes"),
        (rules.CLAUDE_CODE, "fix ready, needs retest: minutes parsed as tens"),
    ]
    item = asyncio.run(store.get(number))
    assert (item.note_count, item.fix_ready) == (2, True)


def test_the_turn_is_read_from_the_message_log(bugs_db):
    async def scene():
        chat = await database.log_received("set a timer for 5 minutes", "chat", 4000, INBOX, user_id=1)
        await database.log_result(chat, reply="Done", status="ok", duration_s=2.5, timing='{"total_s": 2.5}')
        tool = await database.log_received('tool: timer {"duration": "50m"}', "tool", 4000, INBOX, user_id=1)
        await database.log_result(tool, reply="timer 1 started", status="ok")
        await database.log_received("elsewhere", "chat", 4500, ELSEWHERE, user_id=1)
        return await store.recent_log(INBOX)

    rows = asyncio.run(scene())
    assert [entry["kind"] for entry in rows] == ["tool", "chat"]
    turn = rules.pick_turn(rows, 4000, AT)
    assert turn["timing"] == {"total_s": 2.5} and turn["tools"][0]["result"] == "timer 1 started"


# --- the list and the export -----------------------------------------------------
def test_the_list_links_each_open_bug_to_its_post(bugs_db):
    assert rules.list_text([]) == "🐞 No open bugs."
    first = asyncio.run(store.add(1, report()))
    asyncio.run(store.set_post(first, 7000, URL))
    asyncio.run(store.add_note(first, 1, rules.CLAUDE_CODE, rules.FIX_READY))
    asyncio.run(store.add(1, report(target=snap(5002, "another"))))
    lines = rules.list_text(asyncio.run(store.open_items(1))).splitlines()
    assert lines[0] == "**Open bugs (2)**"
    assert lines[1].startswith(f"• [B1]({URL}) · ⏱️ Timer set for 50m · #inbox · ")
    assert lines[1].endswith(" · 1 note · 🔧 fix ready, needs retest")
    assert lines[2].startswith("• B2 · another · #inbox · ")


def test_the_export_has_everything_captured_and_the_notes(bugs_db):
    number = asyncio.run(store.add(1, report(target=snap(content="x" * 900))))
    asyncio.run(store.set_post(number, 7000, URL))
    asyncio.run(store.add_note(number, 1, rules.OWNER, "I asked for 5 minutes"))
    text = rules.export_text(asyncio.run(store.with_notes(1)), AT)
    assert text.startswith("# Open bugs\n\nWritten by `bugs export` on 2026-10-09 14:00 (NZ): 1 open bug.")
    assert "## B1 · " in text and f"- Post: {URL}" in text and "- Commit: `03c7d23`" in text
    assert "> " + "x" * 900 in text, "nothing is shortened in the file"
    for heading in ("### Message", "### Before it", "### That turn", "### Related errors", "### Notes"):
        assert heading in text
    assert "(owner): I asked for 5 minutes" in text
    assert rules.export_text([], AT).rstrip().endswith("0 open bugs. Not in git: it holds Discord messages.")


# --- capturing and filing ---------------------------------------------------------
@pytest.fixture
def filing(bugs_db, monkeypatch, owner):
    """Stand-ins for Discord and the log around `bugs._file`."""
    made = SimpleNamespace(posts=[], forum_error=None)

    def forum():
        if made.forum_error:
            raise UserError(made.forum_error)

    async def create_post(number, filed):
        made.posts.append((number, filed))
        return 7000 + number, f"{URL}{number}"

    async def commit():
        return "03c7d23"

    monkeypatch.setattr(posts, "forum", forum)
    monkeypatch.setattr(posts, "create_post", create_post)
    monkeypatch.setattr(capture, "git_commit", commit)
    monkeypatch.setattr(capture, "read_log_tail", lambda: LOG)
    return made


def test_a_report_is_recorded_with_its_post(filing, owner):
    text = asyncio.run(bugs._file(owner, INBOX, snap(), [snap(4999, "before")], rules.REACTION))
    assert text == f"🐞 Logged as [B1]({URL}1)"
    number, filed = filing.posts[0]
    assert (number, filed.source, filed.channel, filed.commit) == (1, rules.REACTION, "#inbox", "03c7d23")
    assert filed.turn is None and [item.content for item in filed.preceding] == ["before"]
    item = asyncio.run(store.get(1))
    assert (item.thread_id, item.post_url, item.report.target.message_id) == (7001, f"{URL}1", 5001)


def test_the_same_message_is_not_logged_twice(filing, owner):
    asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.REACTION))
    again = asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.REPLY))
    assert again == f"🐞 Already logged as [B1]({URL}1)"
    assert len(filing.posts) == 1 and len(asyncio.run(store.open_items(owner.id))) == 1


def test_nothing_is_recorded_when_there_is_no_forum(filing, owner):
    filing.forum_error = "BUGS_CHANNEL_ID isn't set in .env, so there is nowhere to log bugs."
    with pytest.raises(UserError, match="BUGS_CHANNEL_ID"):
        asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.WORD))
    assert asyncio.run(store.open_items(owner.id)) == []


def test_the_turn_and_its_errors_are_captured_with_the_report(filing, owner, monkeypatch):
    # The log's clock is this machine's: say it is Auckland's for the test
    auckland = timezone(timedelta(hours=13))
    monkeypatch.setattr(capture, "_log_clock", lambda moment: moment.astimezone(auckland).replace(tzinfo=None))

    async def recent(channel_id):
        return ROWS

    monkeypatch.setattr(store, "recent_log", recent)
    asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.WORD, exclude_message_id=4100))
    filed = filing.posts[0][1]
    assert filed.turn["input"] == "set a timer for 5 minutes"
    assert filed.errors[1] == "2026-10-09 14:00:28,200 ERROR assistant: Command failed: timer"
    assert "ValueError: bad duration" in filed.errors and not any("too" in line for line in filed.errors)


def test_the_commit_is_read_once_and_remembered(monkeypatch):
    reads = []
    monkeypatch.setattr(capture, "_commit", None)
    monkeypatch.setattr(capture, "read_commit", lambda: reads.append(1) or "abc1234")
    assert asyncio.run(capture.git_commit()) == "abc1234"
    assert asyncio.run(capture.git_commit()) == "abc1234"
    assert len(reads) == 1


# --- the handlers ------------------------------------------------------------------
class FakeCtx:
    def __init__(self, user, channel_id=INBOX, parent=None, text="bug", recent=()):
        self.user, self.channel_id, self.parent_channel_id = user, channel_id, parent
        self.text, self.message_id = text, 4100
        self._recent = list(recent)
        self.replied, self.confirmed, self.ticked = [], [], 0

    async def recent_messages(self, limit):
        return self._recent[:limit]

    async def reply(self, text):
        self.replied.append(text)

    async def confirm(self, text):
        self.confirmed.append(text)

    async def acknowledge(self, emoji="✅"):
        self.ticked += 1


def discord_message(message_id, content, seconds_before=0, channel=None):
    return SimpleNamespace(
        id=message_id, content=content, author=SimpleNamespace(display_name="Hive"),
        created_at=AT - timedelta(seconds=seconds_before), jump_url=f"https://x/{message_id}", embeds=[], attachments=[],
        channel=channel or SimpleNamespace(id=INBOX),
    )


def test_bug_on_its_own_reports_the_latest_message_with_the_five_before_it(filing, owner):
    recent = [discord_message(5010 - number, f"message {number}", number) for number in range(8)]  # newest first
    ctx = FakeCtx(owner, recent=recent)
    asyncio.run(bugs.report_latest(ctx))
    assert ctx.replied == [f"🐞 Logged as [B1]({URL}1)"], "the line stays: it is a reply, not a confirmation"
    filed = filing.posts[0][1]
    assert (filed.source, filed.target.content) == (rules.WORD, "message 0")
    assert [item.content for item in filed.preceding] == [f"message {number}" for number in (5, 4, 3, 2, 1)]


def test_bug_in_an_empty_channel_or_inside_a_post_is_refused(filing, owner):
    with pytest.raises(UserError, match="nothing in this channel"):
        asyncio.run(bugs.report_latest(FakeCtx(owner)))
    with pytest.raises(UserError, match="already in a bug's post"):
        asyncio.run(bugs.report_latest(FakeCtx(owner, channel_id=7001, parent=BUGS)))
    assert filing.posts == []


def test_bug_as_a_reply_reports_that_message(filing, owner, monkeypatch):
    async def preceding(message, count=rules.PRECEDING):
        return [snap(4999, "before")]

    monkeypatch.setattr(posts, "preceding", preceding)
    ctx = FakeCtx(owner)
    asyncio.run(bugs.report_reply(ctx, discord_message(5001, "⏱️ Timer set for 50m")))
    filed = filing.posts[0][1]
    assert (filed.source, filed.target.message_id, filed.preceding[0].content) == (rules.REPLY, 5001, "before")
    assert ctx.replied == [f"🐞 Logged as [B1]({URL}1)"]


def test_the_reaction_reports_the_message_and_leaves_the_line_in_its_channel(filing, owner, monkeypatch):
    sent = []

    async def fetch(channel_id, message_id):
        return discord_message(message_id, "⏱️ Timer set for 50m")

    async def preceding(message, count=rules.PRECEDING):
        return []

    async def send(channel_id, text):
        sent.append((channel_id, text))

    monkeypatch.setattr(posts, "fetch_message", fetch)
    monkeypatch.setattr(posts, "preceding", preceding)
    monkeypatch.setattr(posts, "send", send)
    payload = SimpleNamespace(channel_id=INBOX, message_id=5001)
    asyncio.run(bugs.report_reaction(payload, owner))
    asyncio.run(bugs.report_reaction(payload, owner))
    assert sent == [(INBOX, f"🐞 Logged as [B1]({URL}1)"), (INBOX, f"🐞 Already logged as [B1]({URL}1)")]
    assert filing.posts[0][1].source == rules.REACTION


def test_what_is_written_in_a_post_is_saved_as_a_note_and_ticked(filing, owner):
    asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.REACTION))
    ctx = FakeCtx(owner, channel_id=7001, parent=BUGS, text="I expected 5 minutes, it set 50")
    assert bugs.task.claim(ctx) is bugs.save_note
    assert asyncio.run(bugs.save_note(ctx)) == "note saved for B1"
    assert ctx.ticked == 1 and ctx.replied == [], "a tick, and no reply"
    assert [note.content for note in asyncio.run(store.notes(1))] == ["I expected 5 minutes, it set 50"]


def test_a_post_that_is_not_a_bugs_is_left_alone(filing, owner):
    ctx = FakeCtx(owner, channel_id=7999, parent=BUGS, text="my own post")
    assert asyncio.run(bugs.save_note(ctx)) == "not a bug's post: left alone"
    assert ctx.ticked == 0
    assert bugs.task.claim(FakeCtx(owner)) is None, "an ordinary channel is not claimed"


def test_bugs_lists_and_export_writes_the_file(filing, owner, monkeypatch, tmp_path):
    monkeypatch.setattr(bugs, "EXPORT_FILE", tmp_path / "BUGS.md")
    asyncio.run(bugs._file(owner, INBOX, snap(), [], rules.REACTION))
    ctx = FakeCtx(owner)
    asyncio.run(bugs.list_bugs(ctx))
    assert ctx.replied[0].startswith("**Open bugs (1)**\n• [B1](")
    assert asyncio.run(bugs.export(ctx)) == "exported 1 open bugs to BUGS.md"
    assert ctx.confirmed == ["📝 Wrote 1 open bug to docs/BUGS.md"]
    assert (tmp_path / "BUGS.md").read_text(encoding="utf-8").startswith("# Open bugs")


# --- registrations ----------------------------------------------------------------
def test_reporting_works_anywhere_and_the_lists_only_in_the_inbox():
    words = {keyword.name: keyword for keyword in bugs.task.keywords()}
    assert set(words) == {"bug", "bugs", "bugs export"}
    assert words["bug"].channels == "any" and not words["bug"].takes_args, "a note after the word is not a command"
    assert words["bugs"].channels == "inbox" and words["bugs export"].channels == "inbox"
    (reply,), (reaction,) = bugs.task.reply_actions(), bugs.task.reactions()
    assert reply.name == "bug" and reply.validate is rules.check_reportable and not reply.takes_args
    assert reaction.emoji == "🐞" and reaction.instant and reaction.undo is None


def test_only_the_owner_may_report_list_or_close(owner, stranger):
    items = [*bugs.task.keywords(), *bugs.task.reply_actions(), *bugs.task.reactions()]
    for permission in [item.permission for item in items] + [posts.PERMISSION, "message:bugs"]:
        assert is_allowed(owner, permission), permission
        assert not is_allowed(stranger, permission), permission


# --- the command line (for the Claude Code skill) ------------------------------------
def test_the_command_line_shows_a_bug_and_takes_a_note_but_never_closes(bugs_db):
    number = asyncio.run(store.add(1, report()))
    assert cli.run(["list"]).startswith("**Open bugs (1)**")
    shown = cli.run(["show", "B1"])
    assert shown.startswith("## B1 · ⏱️ Timer set for 50m") and "### Notes\n\nNone yet." in shown
    assert cli.run(["note", "b1", "fix ready, needs retest:", "minutes parsed as tens"]) == "Note added to B1."
    item = asyncio.run(store.get(number))
    assert item.status == rules.OPEN and item.fix_ready
    assert "(claude-code): fix ready, needs retest: minutes parsed as tens" in cli.run(["show", "1"])


@pytest.mark.parametrize("args", [[], ["close", "B1", "fixed"], ["show"], ["note", "B1"], ["note", "B1", " "]])
def test_the_command_line_explains_itself(bugs_db, args):
    asyncio.run(store.add(1, report()))
    with pytest.raises(UserError, match="Usage"):
        cli.run(args)


def test_the_command_line_says_when_there_is_no_such_bug(bugs_db):
    with pytest.raises(UserError, match="no bug B9"):
        cli.run(["show", "B9"])


# --- the forum's tags at start-up ---------------------------------------------------
class FakeForum:
    def __init__(self, tags, error=None):
        self.available_tags = [SimpleNamespace(name=name) for name in tags]
        self.error, self.edits = error, []

    async def edit(self, available_tags):
        self.edits.append([tag.name for tag in available_tags])
        if self.error:
            raise self.error


@pytest.fixture
def tag_cards(monkeypatch):
    cards = []

    async def card(title, details, user_text=None):
        cards.append((title, details))

    monkeypatch.setattr(posts, "log_error", card)
    return cards


def use_forum(monkeypatch, found: FakeForum) -> FakeForum:
    monkeypatch.setattr(posts, "forum", lambda: found)
    return found


def test_missing_tags_are_created_in_one_request_at_every_start(tag_cards, monkeypatch):
    found = use_forum(monkeypatch, FakeForum(["Urgent", "open"]))
    asyncio.run(posts.ensure_tags())
    assert found.edits == [["Urgent", "open", "Fixed", "Won't fix"]], "the forum's own tags are kept"
    assert tag_cards == []
    # Still missing at the next start (the request was refused, say): asked again
    asyncio.run(posts.ensure_tags())
    assert len(found.edits) == 2


def test_nothing_is_asked_when_the_tags_are_all_there(tag_cards, monkeypatch):
    found = use_forum(monkeypatch, FakeForum(["Open", "Fixed", "Won't fix"]))
    asyncio.run(posts.ensure_tags())
    assert found.edits == [] and tag_cards == []


def test_a_missing_permission_is_one_warning_that_names_it(tag_cards, monkeypatch):
    import discord

    refused = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
    found = use_forum(monkeypatch, FakeForum([], error=refused))
    asyncio.run(posts.ensure_tags())
    assert len(found.edits) == 1 and len(tag_cards) == 1, "one request and one warning for three tags"
    title, details = tag_cards[0]
    assert title == "Bugs: the forum's tags are missing"
    assert "**Manage Channels**" in details and "Open, Fixed, Won't fix" in details


def test_another_refusal_is_one_warning_with_discords_reason(tag_cards, monkeypatch):
    import discord

    refused = discord.HTTPException(SimpleNamespace(status=500, reason="Server Error"), "try later")
    use_forum(monkeypatch, FakeForum(["Open"], error=refused))
    asyncio.run(posts.ensure_tags())
    assert len(tag_cards) == 1
    assert "Manage Channels" not in tag_cards[0][1] and "tried again at the next start" in tag_cards[0][1]


def test_no_forum_set_is_not_worth_a_warning_but_a_wrong_channel_is(tag_cards, monkeypatch):
    def unusable():
        raise UserError("BUGS_CHANNEL_ID must be a forum channel.")

    monkeypatch.setattr(posts, "forum", unusable)
    asyncio.run(posts.ensure_tags())
    assert tag_cards == [("Bugs: the forum can't be used", "BUGS_CHANNEL_ID must be a forum channel.")]
    tag_cards.clear()
    monkeypatch.setitem(posts.CHANNELS, "bugs", None)
    asyncio.run(posts.ensure_tags())
    assert tag_cards == []
