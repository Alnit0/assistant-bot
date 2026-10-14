"""Shared set-up for pytest. Run from the project root: python -m pytest

Importing `tests` first puts the made-up settings in place before anything
from core/ is loaded, so no test ever sees the real .env or the real database.
"""
import tests  # noqa: F401  isort: skip

import asyncio
import itertools
import os

import pytest

from core import backup, clock, database, devmode, live, migrations, scheduler, users
from interfaces import discord as discord_interface
from tests import fastdb, watchdog

# Discord is the interface the tests reach through the door (core/surface.py), as when the bot starts
discord_interface.bind()


@pytest.fixture(autouse=True)
def fails_fast_if_it_hangs(request):
    """A test that runs for more than a minute stops the run, saying which
    test it was and where it was stuck (tests/watchdog.py). A run once hung
    with nothing to say where (2026-10-13)."""
    capture = request.config.pluginmanager.getplugin("capturemanager")
    timer = watchdog.watch(request.node.nodeid, release=(lambda: capture.suspend_global_capture(in_=True)) if capture is not None else None)
    yield
    timer.cancel()


@pytest.fixture(scope="session")
def _every_scratch(tmp_path_factory):
    return tmp_path_factory.mktemp("scratch")


_scratch_numbers = itertools.count(1)


@pytest.fixture
def scratch(_every_scratch):
    """A folder of the test's own, made with one mkdir. pytest's `tmp_path` does far more for
    each test (a numbered folder under a lock, a link to the newest, its clean-up): about
    6 ms a test on this PC, and since every test gets a folder (`no_real_data_folder`) that
    was a sixth of the whole run (measured 2026-10-14). A test that wants `tmp_path` itself
    still asks for it."""
    mine = _every_scratch / f"t{next(_scratch_numbers)}"
    mine.mkdir()
    return mine


@pytest.fixture(autouse=True)
def no_real_data_folder(monkeypatch, scratch):
    tmp_path = scratch
    """Whatever reads the data folder by its path (the self-test's history, for
    one) finds an empty one of the test's own, never this PC's real runs."""
    from core import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    # And the database: a test that asks for none gets an empty file of its own, never this PC's
    # live one (on 2026-10-14 tests of the nightly run wrote 28 notes into it through new code)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "no-database-asked-for.db")


@pytest.fixture(autouse=True)
def the_pc_has_not_restarted(monkeypatch):
    """When this PC really started has nothing to do with a test's own clock: a
    test that wants a restart of the PC says when (core/restart.py)."""
    from core import restart

    monkeypatch.setattr(restart, "booted_at", lambda: None)


@pytest.fixture(autouse=True)
def no_waiting_between_edits(monkeypatch):
    """A live message is edited at most once every two seconds, and a test
    that changes one twice would sit through that wait for real. Nothing is
    being rate-limited here, so there is no wait (tests/test_live.py sets
    its own interval to test the holding back)."""
    monkeypatch.setattr(live, "MIN_INTERVAL", 0.0)


@pytest.fixture(autouse=True)
def no_schedules_unless_asked_for(monkeypatch):
    """The bot's own schedules (the backup, the end of the day, the pills
    checklist) are registered when their modules load, and the engine makes
    rows and books runs for them whenever it looks. A test gets none of that
    unless it asks: it sets `scheduler._standing` to the ones it is about."""
    monkeypatch.setattr(scheduler, "_standing", {})
    monkeypatch.setattr(scheduler, "_joins", {})
    monkeypatch.setattr(scheduler, "_routine_names", {})
    # Nor is anyone told that attention items or jobs changed, unless the test listens itself:
    # a surface registered by an earlier test (the status line) would act on a loop that is gone
    from core import attention

    monkeypatch.setattr(attention, "_listeners", [])
    monkeypatch.setattr(scheduler, "_after_run", [])
    monkeypatch.setattr(scheduler, "_on_trouble", [])
    monkeypatch.setattr(scheduler, "_on_worked", [])


_migrated: dict[tuple, bytes] = {}  # a migrated, empty database for each set of migrations asked for
# `TESTS_AS_ON_LIVE=1 python -m pytest -q`: every test with worker threads and with a connection
# opened and closed for each piece of work, as the bot runs. About twice as long; for when the
# database layer or the way work is handed to threads has changed
AS_ON_LIVE = bool(os.environ.get("TESTS_AS_ON_LIVE"))


async def _in_this_thread(func, /, *args, **kwargs):
    """`asyncio.to_thread`, without the thread: the loop is given its turn, as it is when the
    work goes to a thread, and the work is then done here."""
    await asyncio.sleep(0)
    return func(*args, **kwargs)


@pytest.fixture(autouse=True)
def no_thread_for_each_piece_of_work(request, monkeypatch):
    """The bot hands its blocking work (every database call) to a worker thread, so the event
    loop is never held up. In a test each `asyncio.run` then starts a thread pool and waits for
    its threads to end as the loop closes: about 2 ms a time, some 9,000 times a run (measured
    2026-10-14). Nothing is being kept responsive here, so the work is done in the test's own
    thread. A test that is about the threads themselves is marked `real_threads`."""
    if request.node.get_closest_marker("real_threads") is None and not AS_ON_LIVE:
        monkeypatch.setattr(asyncio, "to_thread", _in_this_thread)


@pytest.fixture(autouse=True)
def no_waiting_for_the_disk(request, monkeypatch):
    # A test that is about the file itself (it is copied, replaced or deleted while in use) is
    # marked `real_connections`: every connection is then opened and closed for real
    fast = fastdb.opened if AS_ON_LIVE or request.node.get_closest_marker("real_connections") is not None else fastdb.connect
    for module in (database, migrations, users, backup):
        monkeypatch.setattr(module, "connect", fast)
    yield
    fastdb.close_kept()


@pytest.fixture
def make_db(scratch, monkeypatch):
    """Make an empty, fully migrated database in a temporary folder.

    Call it with the task migrations the test needs, e.g.
    `make_db({"archive": store.MIGRATIONS})`. The owner (Discord id 1) exists.
    """

    tmp_path = scratch

    def make(task_migrations: dict[str, list] | None = None) -> None:
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
        # Migrating from nothing takes far longer than the test that follows: each set of
        # migrations is run once, and every later test starts from a copy of what it made
        key = tuple(sorted((name, tuple(id(each) for each in found)) for name, found in (task_migrations or {}).items()))
        key = (key, len(migrations.MIGRATIONS))
        if database.DB_PATH.exists():
            # Asked for again in the same test: the database it has is brought up to date
            migrations.migrate(task_migrations or {})
        elif key in _migrated:
            database.DB_PATH.write_bytes(_migrated[key])
        else:
            migrations.migrate(task_migrations or {})
            users.ensure_owner()
            _migrated[key] = database.DB_PATH.read_bytes()
        users.clear_user_cache()
        users.ensure_owner()

    yield make
    users.clear_user_cache()


@pytest.fixture
def db(make_db):
    """A temporary database with the core tables only."""
    make_db()


@pytest.fixture
def dev_off():
    """Dev mode off before and after the test."""
    devmode.disable()
    yield
    devmode.disable()


@pytest.fixture
def dev_clock():
    """A clock that may be moved, as on the dev database; the real time again afterwards."""
    clock.configure(shiftable=True)
    yield clock
    clock.configure(shiftable=False)


@pytest.fixture
def owner() -> users.User:
    return users.User(1, 1, "Owner", "Pacific/Auckland", users.ROLE_OWNER, "2026-01-01T00:00:00+00:00")


@pytest.fixture
def stranger() -> users.User:
    return users.User(2, 22, "Someone", "Pacific/Auckland", users.ROLE_USER, "2026-01-01T00:00:00+00:00")
