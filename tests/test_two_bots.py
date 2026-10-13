"""Live and the test bot side by side from one folder (a lock, a log and channels each), the
status of a self-test that had to stop live, and what I said while the bot was off."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import cards, channels, clock, config, database, identity, instance_lock, missed
from core.instance_lock import Holder, Process
from selftest import __main__ as runner


def run(coroutine):
    return asyncio.run(coroutine)


# --- which bot this is ---------------------------------------------------------------------------------------------
def _settings(tmp_path, live: str, dev: str | None):
    (tmp_path / ".env").write_text(live, encoding="utf-8")
    if dev is not None:
        (tmp_path / ".env.dev").write_text(dev, encoding="utf-8")
    return config.test_bot_settings(tmp_path)


def test_a_token_of_its_own_in_env_dev_makes_the_dev_bot_a_second_bot(tmp_path):
    live = "DISCORD_TOKEN=live-token\nINBOX_CHANNEL_ID=1\n"
    assert _settings(tmp_path, live, None) == {}, "no .env.dev: --dev is live's own account"
    assert _settings(tmp_path, live, "DISCORD_TOKEN=\nINBOX_CHANNEL_ID=7\n") == {}, "no token in it"
    assert _settings(tmp_path, live, "DISCORD_TOKEN=live-token\n") == {}, "live's token again is not a second bot"
    own = _settings(tmp_path, live, "DISCORD_TOKEN=test-token\nINBOX_CHANNEL_ID=7\nHUB_CHANNEL_ID=\n")
    assert own == {"DISCORD_TOKEN": "test-token", "INBOX_CHANNEL_ID": "7", "HUB_CHANNEL_ID": ""}


def test_the_test_bot_takes_no_channel_from_live_s_settings():
    own = {"DISCORD_TOKEN": "t", "INBOX_CHANNEL_ID": "7", "ARCHIVE_CHANNEL_ID": ""}
    now_set = {"DISCORD_TOKEN", "INBOX_CHANNEL_ID", "ARCHIVE_CHANNEL_ID", "GYM_CHANNEL_ID", "HUB_CHANNEL_ID", "ANTHROPIC_API_KEY", "CLAUDE_MODEL"}
    assert config.not_inherited(now_set, own, set()) == {"ARCHIVE_CHANNEL_ID", "GYM_CHANNEL_ID", "HUB_CHANNEL_ID"}, "only what .env.dev names is its own; everything that is not a channel still comes from .env"
    assert config.not_inherited(now_set, own, {"HUB_CHANNEL_ID"}) == {"ARCHIVE_CHANNEL_ID", "GYM_CHANNEL_ID"}, "one set in the terminal (the self-test's) is kept"


def test_each_bot_keeps_to_its_own_channels(monkeypatch):
    own = {"DISCORD_TOKEN": "t", "INBOX_CHANNEL_ID": "7", "HUB_CHANNEL_ID": "8", "BUGS_CHANNEL_ID": "50", "DEV_CHANNEL_ID": ""}
    assert config.other_bot_channels(own, {1, 2, 50}) == {7, 8}, "a forum both post in stays live's too"
    assert config.other_bot_channels({}, {1, 2}) == frozenset(), "no test bot: nothing is off limits"
    # Live: everywhere in the server but the test bot's channels and their threads
    monkeypatch.setattr(config, "SEPARATE_BOT", False)
    monkeypatch.setattr(config, "NOT_MINE", frozenset({7, 8}))
    assert config.mine(1) and config.mine(999) and config.mine(123, parent_id=1)
    assert not config.mine(7) and not config.mine(123, parent_id=8)
    # The test bot: only its own channels and their threads
    monkeypatch.setattr(config, "SEPARATE_BOT", True)
    monkeypatch.setattr(config, "CHANNELS", {"inbox": 7, "hub": 8})
    assert config.mine(7) and config.mine(123, parent_id=8)
    assert not config.mine(1) and not config.mine(999) and not config.mine(123, parent_id=1) and not config.mine(None)


def test_live_s_settings_are_what_they_were():
    assert not config.SEPARATE_BOT and config.LOG_FILE.name == "bot.log" and instance_lock.LOCK_PATH == instance_lock.LIVE_LOCK
    assert instance_lock.LIVE_LOCK.name == "bot.lock" and instance_lock.TEST_LOCK.name == "bot-dev.lock"


# --- a lock a bot ----------------------------------------------------------------------------------------------------
def test_the_two_locks_are_held_at_once_and_each_says_only_who_holds_it(tmp_path, monkeypatch):
    live, test = tmp_path / "bot.lock", tmp_path / "bot-dev.lock"
    monkeypatch.setattr(instance_lock, "_lock_fd", None)
    instance_lock.acquire(live)
    first = instance_lock._lock_fd
    try:
        assert instance_lock.holder(live) is not None and instance_lock.holder(test) is None, "live running does not make the test bot's lock taken"
        instance_lock.acquire(test)  # would exit if the lock were the folder's
        second = instance_lock._lock_fd
        try:
            assert instance_lock.holder(live) is not None and instance_lock.holder(test) is not None
        finally:
            import os

            os.close(second)
        assert instance_lock.holder(test) is None and instance_lock.holder(live) is not None, "one stopping leaves the other's lock alone"
    finally:
        import os

        os.close(first)


def test_the_status_counts_both_bots_and_neither_is_a_stray():
    venv = r'"C:\\bot\\.venv\\Scripts\\python.exe" main.py'
    dev = r'"C:\\bot\\.venv\\Scripts\\python.exe" main.py --dev'
    live, test = Holder(5001, "2026-10-13 15:37:55"), Holder(6001, "2026-10-13 16:00:00")
    processes = [Process(5000, 900, venv), Process(5001, 5000, venv), Process(6000, 900, dev), Process(6001, 6000, dev)]
    lines = instance_lock.status_text(live, processes, test).splitlines()
    assert lines[0] == "1 bot is running: PID 5001, started 2026-10-13 15:37:55 (it holds the lock)."
    assert lines[1] == "The test bot is running too: PID 6001, started 2026-10-13 16:00:00 (its own lock, data/bot-dev.lock)."
    assert not any("without the lock" in line for line in lines), "the test bot holds a lock of its own"
    alone = instance_lock.status_text(None, processes[2:], test).splitlines()
    assert alone[:2] == ["Live is not running: nothing holds its lock (data/bot.lock).", "The test bot is running: PID 6001, started 2026-10-13 16:00:00 (its own lock, data/bot-dev.lock)."]
    assert "without the lock" in instance_lock.status_text(live, processes, None), "a second main.py with no lock of its own is still said"


# --- the self-test: the test bot's, or live's account with live stopped ---------------------------------------------
def test_with_a_test_bot_the_self_test_looks_at_its_lock_and_never_at_live_s(monkeypatch, capsys):
    asked = []

    def holder(path):
        asked.append(path.name)
        return Holder(7, "now") if path == instance_lock.TEST_LOCK else None

    monkeypatch.setattr(runner.instance_lock, "holder", holder)
    monkeypatch.setattr(runner.config, "test_bot_token", lambda: "test-token")
    monkeypatch.setattr(sys, "argv", ["selftest", "--stages", "briefing"])
    assert runner.separate() and runner.token() == "test-token"
    assert runner.main() == 3 and asked == ["bot-dev.lock"], "live's lock is not even asked about: live running is no reason to stop"
    assert "The test bot is already running (PID 7)" in capsys.readouterr().out


def test_without_a_test_bot_the_self_test_is_live_s_account_and_refuses_while_live_runs(monkeypatch, capsys):
    asked = []

    def holder(path):
        asked.append(path.name)
        return Holder(8016, "now")

    monkeypatch.setattr(runner.instance_lock, "holder", holder)
    monkeypatch.setattr(runner.config, "test_bot_token", lambda: None)
    monkeypatch.setattr(sys, "argv", ["selftest", "--stages", "briefing"])
    assert not runner.separate() and runner.token() == config.TOKEN
    assert runner.main() == 3 and asked == ["bot.lock"]
    out = capsys.readouterr().out
    assert "A bot is running (PID 8016)" in out and "there is no test bot" in out and "Stop it first" in out


def test_the_status_of_a_self_test_that_stopped_live_comes_first_and_says_when_live_is_back():
    assert runner.back_about(datetime(2026, 10, 13, 15, 58), 15) == "4:15 pm", "the run's length and a little over"
    none = timedelta(0)
    trouble = [("core", "nightly_backup", "failed")]
    assert identity.status_line(True, 60, "x", none, trouble, True, "4:15 pm") == "🧪 Self-test running · back about 4:15 pm", "before trouble, dev mode and everything else"
    assert identity.status_line(True, 60, "", none) == "🧪 DEV database", "no self-test: as it was"
    assert config.SELFTEST_BACK == "", "and never on a bot that is not a self-test's"


# --- what I said while the bot was off -------------------------------------------------------------------------------
NOW = datetime(2026, 10, 13, 3, 0, tzinfo=timezone.utc)
INBOX, HUB, COMMANDS = 100, 400, 300


def _message(message_id, minutes_ago, text="took zinc", bot=False, channel_id=INBOX, files=0):
    return SimpleNamespace(
        id=message_id, created_at=NOW - timedelta(minutes=minutes_ago), content=text, author=SimpleNamespace(bot=bot, id=1),
        channel=SimpleNamespace(id=channel_id), jump_url=f"https://discord.test/{message_id}", attachments=[object()] * files,
    )


class _Channel:
    def __init__(self, channel_id, messages):
        self.id, self.name, self._messages, self.sent = channel_id, f"c{channel_id}", messages, []

    def history(self, limit=None, after=None, oldest_first=None):
        async def found():
            for message in sorted(self._messages, key=lambda each: each.created_at):
                if after is None or message.created_at > after:
                    yield message

        return found()

    async def fetch_message(self, message_id):
        import discord

        for message in self._messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(SimpleNamespace(status=404, reason="gone"), "gone")

    async def send(self, text, **kwargs):
        self.sent.append(text)


@pytest.fixture
def off(db, owner, monkeypatch):
    """A bot starting at NOW that last noted it was running 40 minutes before."""
    on = SimpleNamespace(cards=[], taken=[], inbox=_Channel(INBOX, []), hub=_Channel(HUB, []), owner=owner)

    async def send(channel_id, card, **kwargs):
        on.cards.append((channel_id, card))
        return 9000 + len(on.cards)

    async def sender(message):
        return None if message.author.bot or not message.content.strip() else owner

    async def take(message, user):
        on.taken.append((message.id, user.id))

    monkeypatch.setattr(clock, "real_now", lambda: NOW)
    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(missed, "CHANNELS", {"inbox": INBOX, "hub": HUB, "commands": COMMANDS, "dev": INBOX})
    monkeypatch.setattr(channels, "named", lambda client=None: [on.inbox, on.hub, _Channel(COMMANDS, [_message(1, 5)])])
    monkeypatch.setattr(missed.discord_utils, "client", SimpleNamespace(get_channel=lambda channel_id: {INBOX: on.inbox, HUB: on.hub}.get(channel_id)))
    monkeypatch.setattr(missed, "_seen", set())
    missed.setup(sender, take)
    run(database.run(missed.db_note_alive, NOW - timedelta(minutes=40)))
    return on


def test_the_card_quotes_the_message_and_asks_with_two_buttons():
    shown = missed.card(77, "took   zinc\nand iron", NOW - timedelta(minutes=10), "https://discord.test/77", files=2)
    lines = shown.text.splitlines()
    assert lines[0].startswith("📭 **I was offline when you sent this** · ") and lines[0].endswith("[the message](https://discord.test/77)")
    assert lines[1:] == ["> took zinc and iron", "> 📎 2 files"]
    (row,) = shown.rows
    assert [(button.label, button.action, button.arg) for button in row] == [("Handle it now", "handle", "77"), ("Ignore", "ignore", "77")]
    cards.check(shown)  # Ignore is the grey way out; Handle it now is blurple
    assert missed.quote("x" * 500).endswith("…") and len(missed.quote("x" * 500)) < 310 and missed.quote("") == "> (no text)"
    assert missed.to_read({"inbox": 1, "dev": 1, "hub": 4, "commands": 3}) == [1, 4], "each channel once, and never #commands"


def test_a_first_start_has_nothing_to_go_on_and_reads_nothing(db, owner, monkeypatch):
    posted = []

    async def send(channel_id, card, **kwargs):
        posted.append(card)

    monkeypatch.setattr(clock, "real_now", lambda: NOW)
    monkeypatch.setattr(cards, "send", send)
    assert run(missed.look()) == 0 and posted == []
    assert run(database.run(missed.db_alive)) == NOW, "but from now on it knows when it was last running"


def test_each_message_of_mine_sent_while_it_was_off_gets_a_card_and_nothing_is_done(off):
    off.inbox._messages += [
        _message(10, 90, "before it stopped"), _message(11, 30, "took zinc"), _message(12, 20, "a bot's line", bot=True),
        _message(13, 10, "add milk"), _message(14, 5, "   "),
    ]
    off.hub._messages += [_message(21, 15, "pills", channel_id=HUB)]
    assert run(missed.look()) == 3
    assert [(channel_id, card.text.splitlines()[1]) for channel_id, card in off.cards] == [(INBOX, "> took zinc"), (HUB, "> pills"), (INBOX, "> add milk")], "oldest first, each in the channel it was said in"
    assert off.taken == [], "never acted on without asking"
    assert run(missed.look()) == 0 and len(off.cards) == 3, "a second start before I answer asks nothing twice"


def test_one_the_bot_saw_or_logged_is_not_asked_about(off):
    off.inbox._messages += [_message(11, 30, "logged before the stop"), _message(12, 0.2, "arrived as it started"), _message(13, 10, "missed")]

    run(database.log_received("logged before the stop", "chat", 11, INBOX, user_id=off.owner.id))
    missed.saw(12)
    assert run(missed.look()) == 1 and off.cards[0][1].text.splitlines()[1] == "> missed"


def test_after_a_long_stop_only_the_latest_get_a_card_and_the_rest_are_counted(off):
    off.inbox._messages += [_message(100 + n, 39 - n, f"message {n}") for n in range(25)]
    assert run(missed.look()) == missed.MAX_CARDS
    assert off.cards[0][1].text.splitlines()[1] == "> message 5" and off.cards[-1][1].text.splitlines()[1] == "> message 24"
    assert off.inbox.sent == ["📭 5 earlier messages of yours from while I was offline have no card: scroll up, and send again what still matters."]
    assert missed.latest([1, 2, 3], 5) == ([1, 2, 3], 0) and "1 earlier message of yours" in missed.more_line(1) and " has no card" in missed.more_line(1)


class _Press:
    def __init__(self, user, arg, channel_id=INBOX):
        self.user, self.arg, self.channel_id, self.did = user, arg, channel_id, []

    async def remove(self):
        self.did.append("removed")

    async def say(self, text):
        self.did.append(text)


def test_handle_it_now_takes_the_message_as_if_just_sent_once(off):
    off.inbox._messages.append(_message(11, 30, "took zinc"))
    run(missed.look())
    press = _Press(off.owner, "11")
    assert run(missed.on_handle(press)) == "handled message 11, sent while the bot was off"
    assert press.did == ["removed"] and off.taken == [(11, off.owner.id)], "the card goes, and the message is handled"
    again = _Press(off.owner, "11")
    assert "already answered" in run(missed.on_handle(again)) and off.taken == [(11, off.owner.id)] and again.did == ["removed"], "a second press does not do it twice"


def test_ignore_removes_the_card_and_nothing_else_and_a_message_that_has_gone_is_said(off):
    off.inbox._messages += [_message(11, 30, "took zinc"), _message(12, 20, "add milk")]
    run(missed.look())
    press = _Press(off.owner, "11")
    assert run(missed.on_ignore(press)) == "ignored message 11, sent while the bot was off" and press.did == ["removed"] and off.taken == []
    assert "already answered" in run(missed.on_handle(_Press(off.owner, "11"))) and off.taken == [], "ignored stays ignored"
    off.inbox._messages.clear()  # I deleted the other one meanwhile
    gone = _Press(off.owner, "12")
    assert run(missed.on_handle(gone)) == "message 12 has gone" and gone.did == ["removed", "That message has gone, so there is nothing to handle."] and off.taken == []
    stranger = _Press(SimpleNamespace(id=off.owner.id + 99), "12")
    assert "already answered" in run(missed.on_handle(stranger)) and off.taken == [], "only the one it was sent by"


def test_reading_back_never_holds_up_a_start(off, monkeypatch):
    async def broken():
        raise RuntimeError("Discord is down")

    monkeypatch.setattr(missed, "_look", broken)
    assert run(missed.look()) == 0


# --- the bot itself: what it takes, and from where -----------------------------------------------------------------
def test_the_bot_takes_only_my_words_in_a_channel_that_is_its_own(monkeypatch, owner):
    import main

    async def who(discord_id):
        return owner if discord_id == 1 else None

    monkeypatch.setattr(main, "get_user_by_discord_id", who)
    monkeypatch.setattr(main, "is_allowed", lambda user, action: user is owner)
    monkeypatch.setattr(main, "my_channel", lambda channel_id, parent_id=None: channel_id == INBOX or parent_id == INBOX)
    mine = _message(1, 1)
    assert run(main._sender(mine)) is owner
    assert run(main._sender(_message(2, 1, bot=True))) is None, "a bot's, its own included"
    assert run(main._sender(_message(3, 1, channel_id=HUB))) is None, "said in the other bot's channel"
    assert run(main._sender(_message(4, 1, text="  "))) is None, "nothing in it"
    stranger = _message(5, 1)
    stranger.author = SimpleNamespace(bot=False, id=2)
    assert run(main._sender(stranger)) is None
    thread = _message(6, 1, channel_id=777)
    thread.channel = SimpleNamespace(id=777, parent_id=INBOX)
    assert run(main._sender(thread)) is owner, "a thread is its parent's"

    taken, seen = [], []

    async def take(message, user):
        taken.append(message.id)

    monkeypatch.setattr(main, "_take", take)
    monkeypatch.setattr(main.missed, "saw", seen.append)
    for message in (mine, _message(3, 1, channel_id=HUB)):
        message.type = None
        run(main.on_message(message))
    assert taken == [1] and seen == [1], "and one that arrived is never asked about after a restart"


# --- the token really used decides, and a start never inherits live's -------------------------------------------------
def test_which_bot_a_process_is_follows_the_token_it_will_log_in_with_not_what_the_files_say():
    own = {"DISCORD_TOKEN": "dev-token", "INBOX_CHANNEL_ID": "7"}
    assert config.is_test_bot(True, own, "dev-token")
    assert not config.is_test_bot(True, own, "live-token"), "live's token was already in the environment: this is live's account, and it takes live's lock"
    assert not config.is_test_bot(False, own, "dev-token") and not config.is_test_bot(True, {}, "dev-token") and not config.is_test_bot(True, own, None)


def test_a_process_started_from_here_is_given_nothing_the_settings_files_put_in_the_environment():
    environ = {"PATH": "x", "DISCORD_TOKEN": "live-token", "INBOX_CHANNEL_ID": "1", "SELFTEST": "1"}
    assert config.clean_environment(environ, {"PATH", "SELFTEST"}) == {"PATH": "x", "SELFTEST": "1"}
    child = config.environment_for_child()
    assert ("DISCORD_TOKEN" in child) == ("DISCORD_TOKEN" in config._SET_BEFORE), "live's token goes to a child only if it was set in the terminal"
    assert "PATH" in child or "Path" in child


def test_a_start_of_the_self_test_logs_in_as_the_dev_bot_when_there_is_one():
    """Through the launcher's own environment, in a real process: what went wrong on 2026-10-13."""
    import subprocess

    if config.test_bot_token() is None:
        pytest.skip("no dev bot on this machine (.env.dev has no token of its own)")
    from dotenv import dotenv_values

    # As the launcher's is when it is really run: the tests' own made-up settings are not in it
    in_files = set(dotenv_values(config.BASE_DIR / ".env")) | set(dotenv_values(config.BASE_DIR / ".env.dev"))
    env = {name: value for name, value in config.environment_for_child().items() if name not in in_files}
    env.update({"SELFTEST": "1", "INBOX_CHANNEL_ID": "7", "HUB_CHANNEL_ID": "8", "BOT_LOG_CHANNEL_ID": "9", "COMMANDS_CHANNEL_ID": ""})
    code = "from core import config, instance_lock; print(config.SEPARATE_BOT, config.TOKEN == config.test_bot_token(), instance_lock.LOCK_PATH.name, sorted(config.CHANNELS))"
    done = subprocess.run([sys.executable, "-c", code, "--dev"], cwd=config.BASE_DIR, env=env, capture_output=True, text=True, timeout=60)
    assert done.stdout.split()[:3] == ["True", "True", "bot-dev.lock"], done.stdout + done.stderr
    assert "gym" not in done.stdout and "archive" not in done.stdout, "and it has none of live's channels"
    # And with live's token forced on it, it is live's account: live's lock, so it can never run beside live
    forced = subprocess.run([sys.executable, "-c", code, "--dev"], cwd=config.BASE_DIR, env={**env, "DISCORD_TOKEN": "not-the-dev-bot's"}, capture_output=True, text=True, timeout=60)
    assert forced.stdout.split()[:3] == ["False", "False", "bot.lock"], forced.stdout + forced.stderr


def test_the_launcher_hands_a_start_a_clean_environment_and_the_start_refuses_to_be_live(monkeypatch, tmp_path):
    seen = {}

    def started(command, env=None, **kwargs):
        seen.update(env=env, command=command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "WORK", tmp_path)
    monkeypatch.setattr(runner.subprocess, "run", started)
    monkeypatch.setattr(runner.config, "test_bot_token", lambda: "dev-token")
    monkeypatch.setenv("DISCORD_TOKEN", "live-token-from-env-file")
    monkeypatch.setattr(config, "_SET_BEFORE", {"PATH"})
    runner.run_phase("p1", {"CARDS_V2": "false"}, {"hub": 8, "inbox": 7}, False, 0.2, {}, "s")
    assert "DISCORD_TOKEN" not in seen["env"], "the start reads .env.dev for itself"
    assert seen["env"]["SELFTEST_SEPARATE"] == "1" and seen["env"]["INBOX_CHANNEL_ID"] == "7" and seen["command"][-4:-2] == ["selftest.phase", "--dev"]
