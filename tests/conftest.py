"""Shared set-up for pytest. Run from the project root: python -m pytest

Importing `tests` first puts the made-up settings in place before anything
from core/ is loaded, so no test ever sees the real .env or the real database.
"""
import tests  # noqa: F401  isort: skip

import pytest

from core import backup, clock, database, devmode, live, migrations, scheduler, users
from tests import watchdog


@pytest.fixture(autouse=True)
def fails_fast_if_it_hangs(request):
    """A test that runs for more than a minute stops the run, saying which
    test it was and where it was stuck (tests/watchdog.py). A run once hung
    with nothing to say where (2026-10-13)."""
    capture = request.config.pluginmanager.getplugin("capturemanager")
    timer = watchdog.watch(request.node.nodeid, release=(lambda: capture.suspend_global_capture(in_=True)) if capture is not None else None)
    yield
    timer.cancel()


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


_migrated: dict[tuple, bytes] = {}  # a migrated, empty database for each set of migrations asked for
_connect = database.connect


def _fast_connect():
    """A connection that doesn't wait for the disk after every write: a test's
    database is thrown away, so nothing is lost if the machine stops."""
    conn = _connect()
    conn.execute("PRAGMA synchronous = OFF")
    return conn


@pytest.fixture(autouse=True)
def no_waiting_for_the_disk(monkeypatch):
    for module in (database, migrations, users, backup):
        monkeypatch.setattr(module, "connect", _fast_connect)


@pytest.fixture
def make_db(tmp_path, monkeypatch):
    """Make an empty, fully migrated database in a temporary folder.

    Call it with the task migrations the test needs, e.g.
    `make_db({"archive": store.MIGRATIONS})`. The owner (Discord id 1) exists.
    """

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
