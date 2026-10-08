"""Shared set-up for pytest. Run from the project root: python -m pytest

Importing `tests` first puts the made-up settings in place before anything
from core/ is loaded, so no test ever sees the real .env or the real database.
"""
import tests  # noqa: F401  isort: skip

import pytest

from core import backup, database, devmode, migrations, users


@pytest.fixture
def make_db(tmp_path, monkeypatch):
    """Make an empty, fully migrated database in a temporary folder.

    Call it with the task migrations the test needs, e.g.
    `make_db({"archive": store.MIGRATIONS})`. The owner (Discord id 1) exists.
    """

    def make(task_migrations: dict[str, list] | None = None) -> None:
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
        migrations.migrate(task_migrations or {})
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
def owner() -> users.User:
    return users.User(1, 1, "Owner", "Pacific/Auckland", users.ROLE_OWNER, "2026-01-01T00:00:00+00:00")


@pytest.fixture
def stranger() -> users.User:
    return users.User(2, 22, "Someone", "Pacific/Auckland", users.ROLE_USER, "2026-01-01T00:00:00+00:00")
