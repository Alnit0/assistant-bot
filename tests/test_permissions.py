import asyncio

import pytest

from core import database, users
from core.permissions import is_allowed

ACTIONS = ["message", "keyword:stats", "reply:archive", "reaction:📦", "dev", "timers", ""]


@pytest.mark.parametrize("action", ACTIONS)
def test_the_owner_is_allowed_everything(owner, action):
    assert is_allowed(owner, action)


@pytest.mark.parametrize("action", ACTIONS)
def test_a_known_user_who_is_not_the_owner_is_allowed_nothing(stranger, action):
    assert not is_allowed(stranger, action)


@pytest.mark.parametrize("action", ACTIONS)
def test_someone_we_do_not_know_is_allowed_nothing(action):
    assert not is_allowed(None, action)


def _add_user(discord_id: int, role: str) -> None:
    conn = database.connect()
    try:
        conn.execute(
            "INSERT INTO users (discord_id, display_name, timezone, role, created_at) VALUES (?, 'X', 'UTC', ?, 'now')",
            (discord_id, role),
        )
        conn.commit()
    finally:
        conn.close()


def test_the_owner_from_settings_exists_with_the_owner_role(db):
    user = asyncio.run(users.get_user_by_discord_id(1))
    assert user is not None and user.role == users.ROLE_OWNER
    assert is_allowed(user, "anything")


def test_ensure_owner_can_run_again_without_duplicating(db):
    users.ensure_owner()
    conn = database.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        conn.close()


def test_anyone_else_marked_owner_is_demoted(db):
    _add_user(77, users.ROLE_OWNER)
    users.ensure_owner()
    impostor = asyncio.run(users.get_user_by_discord_id(77))
    assert impostor.role == users.ROLE_USER
    assert not is_allowed(impostor, "message")
    assert asyncio.run(users.get_user_by_discord_id(1)).role == users.ROLE_OWNER


def test_an_unknown_discord_id_is_nobody(db):
    assert asyncio.run(users.get_user_by_discord_id(424242)) is None


def test_lookups_are_remembered_including_not_one_of_ours(db, monkeypatch):
    asyncio.run(users.get_user_by_discord_id(1))
    asyncio.run(users.get_user_by_discord_id(424242))

    def no_database(discord_id):
        raise AssertionError("the answer should have come from the cache")

    monkeypatch.setattr(users, "_get_user_by_discord_id", no_database)
    assert asyncio.run(users.get_user_by_discord_id(1)).role == users.ROLE_OWNER
    assert asyncio.run(users.get_user_by_discord_id(424242)) is None


def test_clearing_the_cache_looks_again(db):
    assert asyncio.run(users.get_user_by_discord_id(77)) is None
    _add_user(77, users.ROLE_USER)
    assert asyncio.run(users.get_user_by_discord_id(77)) is None, "still the remembered answer"
    users.clear_user_cache()
    assert asyncio.run(users.get_user_by_discord_id(77)).discord_id == 77
