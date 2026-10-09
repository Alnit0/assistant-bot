import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from core import instance_lock
from core.instance_lock import Holder, Process
from tasks import registry
from tasks.dev import tools

VENV = r'"C:\Users\temp\projects\assistant-bot\.venv\Scripts\python.exe" main.py'
# One bot started from the virtual environment: the launcher (5516) and the
# real interpreter it starts (15084), both with the same command line
LAUNCHER = Process(5516, 900, VENV)
REAL = Process(15084, 5516, VENV)
PYTEST = Process(7000, 900, r'"C:\...\.venv\Scripts\python.exe" -m pytest -q')
NOTE = "PID 15084, started 2026-10-09 13:02:11"


# --- the lock is the source of truth ----------------------------------------------
@pytest.fixture
def held(tmp_path):
    """A lock file held the way a running bot holds it, by this very process."""
    path = tmp_path / "bot.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    assert instance_lock._try_lock(fd)
    os.lseek(fd, 0, os.SEEK_SET)  # the lock itself sits far past the note
    os.write(fd, NOTE.encode("utf-8"))
    yield path, fd
    try:
        os.close(fd)
    except OSError:
        pass


def test_no_lock_file_means_no_bot(tmp_path):
    assert instance_lock.holder(tmp_path / "bot.lock") is None


def test_a_held_lock_names_the_bot(held):
    path, _ = held
    assert instance_lock.holder(path) == Holder(15084, "2026-10-09 13:02:11")


def test_a_file_left_by_a_bot_that_stopped_is_not_a_running_bot(held):
    path, fd = held
    os.close(fd)  # the bot stops: the system lets go of the lock, the file and its note stay
    assert path.read_text(encoding="utf-8") == NOTE
    assert instance_lock.holder(path) is None


def test_asking_does_not_keep_the_lock(held):
    path, fd = held
    os.close(fd)
    assert instance_lock.holder(path) is None
    again = os.open(path, os.O_RDWR)
    try:
        assert instance_lock._try_lock(again), "a bot can still start after someone has looked"
    finally:
        os.close(again)


@pytest.mark.parametrize(
    "text, expected",
    [(NOTE, Holder(15084, "2026-10-09 13:02:11")), ("", Holder(None, "")), ("garbage", Holder(None, ""))],
)
def test_the_holders_note_is_read(text, expected):
    assert instance_lock.parse_note(text) == expected


def test_a_start_is_not_turned_away_by_someone_looking(tmp_path, monkeypatch):
    # holder() in another process has the lock for an instant: the first try fails
    tries = []
    real = instance_lock._try_lock

    def busy_once(fd):
        tries.append(fd)
        return len(tries) > 1 and real(fd)

    monkeypatch.setattr(instance_lock, "_try_lock", busy_once)
    monkeypatch.setattr(instance_lock.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(instance_lock, "_lock_fd", None)
    instance_lock.acquire(tmp_path / "bot.lock")
    try:
        assert len(tries) == 2
        assert (tmp_path / "bot.lock").read_text(encoding="utf-8").startswith(f"PID {os.getpid()}, started ")
    finally:
        os.close(instance_lock._lock_fd)


def test_a_second_copy_still_gives_up_and_exits(held, monkeypatch):
    path, _ = held
    monkeypatch.setattr(instance_lock.time, "sleep", lambda seconds: None)
    with pytest.raises(SystemExit) as stopped:
        instance_lock.acquire(path)
    assert stopped.value.code == instance_lock.EXIT_ALREADY_RUNNING


# --- counting processes: the launcher is not a second bot ---------------------------
def test_the_launcher_and_its_child_are_one_bot():
    assert instance_lock.instances([LAUNCHER, REAL]) == [REAL]


def test_a_bot_started_without_a_launcher_is_one_bot():
    assert instance_lock.instances([Process(400, 1, "/usr/bin/python3 main.py")]) == [Process(400, 1, "/usr/bin/python3 main.py")]


def test_two_real_bots_are_two():
    other_launcher, other = Process(6000, 900, VENV), Process(6001, 6000, VENV)
    assert instance_lock.instances([LAUNCHER, REAL, other_launcher, other]) == [REAL, other]


def test_other_python_processes_are_not_bots():
    assert instance_lock.instances([PYTEST, Process(1, 0, "python -m core.instance_lock"), Process(2, 0, "python domain.py")]) == []
    assert instance_lock.instances([]) == []


def test_the_process_list_is_read_whether_it_has_none_one_or_several():
    one = {"ProcessId": 15084, "ParentProcessId": 5516, "CommandLine": VENV}
    assert instance_lock.parse_processes("") == []
    assert instance_lock.parse_processes(json.dumps(one)) == [REAL]
    assert instance_lock.parse_processes(json.dumps([one, {"ProcessId": 4, "ParentProcessId": 0, "CommandLine": None}])) == [
        REAL,
        Process(4, 0, ""),
    ]


# --- what is said ---------------------------------------------------------------------
LOCK = Holder(15084, "2026-10-09 13:02:11")


def test_one_bot_with_its_launcher_is_reported_as_one():
    assert instance_lock.status_text(LOCK, [LAUNCHER, REAL, PYTEST]) == (
        "1 bot is running: PID 15084, started 2026-10-09 13:02:11 (it holds the lock).\n"
        "Not counted: PID 5516, the .venv launcher (the parent of the real process)."
    )


def test_no_lock_and_no_process_is_no_bot():
    assert instance_lock.status_text(None, [PYTEST]) == "No bot is running: nothing holds the lock (data/bot.lock)."


def test_a_copy_running_without_the_lock_is_flagged_but_not_counted_as_the_bot():
    text = instance_lock.status_text(LOCK, [LAUNCHER, REAL, Process(6000, 900, VENV), Process(6001, 6000, VENV)])
    lines = text.splitlines()
    assert lines[0].startswith("1 bot is running: PID 15084")
    assert lines[1].startswith("⚠️ PID 6001 is running main.py without the lock")
    assert lines[2] == "Not counted: PID 5516, 6000, the .venv launcher (the parent of the real process)."


def test_a_process_with_no_lock_holder_is_flagged():
    lines = instance_lock.status_text(None, [LAUNCHER, REAL]).splitlines()
    assert lines[0].startswith("No bot is running") and lines[1].startswith("⚠️ PID 15084 is running main.py without the lock")


def test_the_lock_still_answers_when_processes_cannot_be_listed():
    assert instance_lock.status_text(LOCK, None).splitlines() == [
        "1 bot is running: PID 15084, started 2026-10-09 13:02:11 (it holds the lock).",
        "The process list couldn't be read; the lock is what counts.",
    ]


# --- dev status -------------------------------------------------------------------------
def test_dev_status_is_a_word_for_the_owner_anywhere(owner, stranger):
    registry.load()
    kind, task, word = registry.find("dev status")
    assert (kind, task.name, word.name) == ("keyword", "dev", "dev status")
    assert registry.works_in(word, 999) and not word.takes_args
    assert registry.is_allowed(owner, word.permission) and not registry.is_allowed(stranger, word.permission)


def test_dev_status_replies_with_the_count(monkeypatch):
    monkeypatch.setattr(instance_lock, "status", lambda: instance_lock.status_text(LOCK, [LAUNCHER, REAL]))
    replies = []

    async def reply(text):
        replies.append(text)

    recorded = asyncio.run(tools.status(SimpleNamespace(reply=reply)))
    assert replies[0].startswith("🩺 **Bot instances**\n1 bot is running: PID 15084")
    assert replies[0].endswith(tools.TAG) and recorded.startswith("1 bot is running")
