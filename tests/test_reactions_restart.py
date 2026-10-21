"""A reaction made just before a stop (BACKLOG, Soon 14; 22 Oct): the changes waiting out the quiet period are kept
in the database (reaction_waiting), so a 👍 made just before a restart is dealt with after it, once, checked as it is
now and with its undo. One older than the quiet period and ten minutes at the start is dropped and said in the log."""
import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

from core import clock, database, reactions
from tasks import registry
from tests.test_pills_reminders import world  # noqa: F401
from tests.test_registry import reactions_watched  # noqa: F401
from tests.test_thumbs_up import on, posted, reacted, thumbs  # noqa: F401

QUIET = 30.0


def waiting():
    return asyncio.run(database.run(reactions.db_waiting))


def stopped_with(*changes):
    """The bot stopped with these (payload, added, seconds ago) waiting: as the real path keeps them."""
    for payload, added, ago in changes:
        change = reactions.Change(payload.message_id, payload.channel_id, registry._emoji_key(payload.emoji), payload.user_id)
        asyncio.run(database.run(reactions.db_wait, change, None, added, clock.real_now() - timedelta(seconds=ago)))


def started(thumbs, monkeypatch):
    """The start: what was waiting waits out the quiet period again, then is dealt with as it would have been."""
    monkeypatch.setattr(registry, "_reaction_debouncer", SimpleNamespace(trigger=thumbs.debounced.append, delay=QUIET))
    asyncio.run(registry.resume_waiting())
    batch = list(thumbs.debounced)
    asyncio.run(registry._reactions_quiet(batch))
    return batch


def test_a_change_waiting_out_the_quiet_period_is_kept_and_let_go_once_dealt_with(thumbs, monkeypatch):
    message_id = posted(thumbs.world)
    asyncio.run(registry.reaction_changed(reacted("👍", message_id), True))
    ((payload, added, row_id),) = thumbs.debounced
    assert row_id is not None and [(each.message_id, each.emoji, each.added) for each in waiting()] == [(message_id, "👍", True)]
    asyncio.run(registry._reactions_quiet(thumbs.debounced))
    assert thumbs.world.yes == [("evening-routine", message_id)] and waiting() == [], "dealt with, and let go"


def test_a_thumbs_up_made_just_before_a_restart_is_applied_after_it_once(thumbs, monkeypatch):
    message_id = posted(thumbs.world)
    stopped_with((reacted("👍", message_id), True, 10))  # inside the quiet period when the bot stopped
    thumbs.debounced.clear()
    batch = started(thumbs, monkeypatch)
    assert len(batch) == 1 and batch[0][1] is True
    assert thumbs.world.yes == [("evening-routine", message_id)], "applied after the restart"
    assert ("✅", True) in thumbs.marks and waiting() == []
    thumbs.debounced.clear()
    asyncio.run(registry.resume_waiting())
    assert thumbs.debounced == [] and len(thumbs.world.yes) == 1, "once only: nothing is left to do again"


def test_one_made_long_before_the_restart_is_dropped_and_said_in_the_log(thumbs, monkeypatch, caplog):
    message_id = posted(thumbs.world)
    stopped_with((reacted("👍", message_id), True, QUIET + 11 * 60))  # past the quiet period and ten minutes
    thumbs.debounced.clear()
    with caplog.at_level(logging.INFO, logger="assistant"):
        batch = started(thumbs, monkeypatch)
    assert batch == [] and thumbs.world.yes == [] and waiting() == [], "never applied, and gone"
    assert any("too old to act on" in record.getMessage() for record in caplog.records)


def test_one_taken_off_again_before_the_restart_does_nothing(thumbs, monkeypatch):
    message_id = posted(thumbs.world)
    stopped_with((reacted("👍", message_id), True, 12), (reacted("👍", message_id), False, 8))
    thumbs.debounced.clear()
    batch = started(thumbs, monkeypatch)
    assert [added for _, added, _ in batch] == [True, False], "in the order they were made"
    assert thumbs.world.yes == [] and waiting() == [], "on and off again in the quiet period: nothing"


def test_what_is_kept_and_what_is_too_old_at_the_start():
    now = clock.real_now()
    made = lambda row, ago: reactions.Waiting(row, 5, 6, "👍", 7, True, now - timedelta(seconds=ago))
    kept, dropped = reactions.resumable([made(2, 5), made(1, QUIET + 9 * 60), made(3, QUIET + 10 * 60 + 1)], now, QUIET)
    assert [each.row_id for each in kept] == [1, 2], "oldest first"
    assert [each.row_id for each in dropped] == [3]
