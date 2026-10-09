"""The occurrence log (core/occurrences.py): expected things on a day, with every change recorded."""
from datetime import date, datetime, time, timedelta

import pytest

from core import database, occurrences as log
from core.config import TIMEZONE
from core.errors import UserError

DAY = date(2026, 10, 9)
TASK = "pills"


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


NOW = nz(2026, 10, 9, 12, 0)


@pytest.fixture
def conn(db):
    connection = database.connect()
    yield connection
    connection.close()


def make(conn, item_id=7, seq=1, day=DAY, planned=None, due=None):
    return log.db_ensure(conn, 1, TASK, item_id, day, seq, planned, due, now=NOW)


def kinds(conn, occurrence_id):
    return [event.kind for event in log.db_history(conn, occurrence_id)]


# ---------------------------------------------------------------------------
# Making them
# ---------------------------------------------------------------------------
def test_an_occurrence_starts_pending_with_its_plan(conn):
    due = nz(2026, 10, 9, 20, 0)
    made = make(conn, planned=time(20, 0), due=due)
    assert (made.user_id, made.task, made.item_id, made.day, made.seq) == (1, TASK, 7, DAY, 1)
    assert (made.planned_time, made.due_at, made.state) == (time(20, 0), due, log.PENDING)
    assert made.is_pending and made.actual_at is None and not made.automatic and made.reason is None
    assert kinds(conn, made.id) == [log.CREATED]


def test_one_with_no_time_has_no_plan_and_no_due_moment(conn):
    made = make(conn)
    assert made.planned_time is None and made.due_at is None


def test_asking_again_gives_the_same_one_as_it_now_is(conn):
    first = make(conn, planned=time(8, 0), due=nz(2026, 10, 9, 8, 0))
    log.db_done(conn, first.id, nz(2026, 10, 9, 8, 4), log.BUTTON, now=NOW)
    # A restart, or the morning job running late: the plan may even have changed since
    again = make(conn, planned=time(9, 0), due=nz(2026, 10, 9, 9, 0))
    assert again.id == first.id
    assert again.state == log.DONE, "never reset"
    assert again.planned_time == time(8, 0), "history is not rewritten"
    assert kinds(conn, first.id) == [log.CREATED, log.MARKED_DONE]


def test_a_days_occurrences_come_by_item_and_number(conn):
    make(conn, item_id=9)
    make(conn, item_id=7, seq=2)
    make(conn, item_id=7, seq=1)
    make(conn, item_id=7, day=DAY + timedelta(days=1))
    log.db_ensure(conn, 1, "other", 7, DAY, now=NOW)
    assert [(o.item_id, o.seq) for o in log.db_for_day(conn, 1, TASK, DAY)] == [(7, 1), (7, 2), (9, 1)]
    assert [(o.item_id, o.seq) for o in log.db_for_day(conn, 1, TASK, DAY, item_id=9)] == [(9, 1)]
    assert len(log.db_between(conn, 1, TASK, DAY, DAY + timedelta(days=1), item_id=7)) == 3


# ---------------------------------------------------------------------------
# Changing them
# ---------------------------------------------------------------------------
def test_done_records_when_and_what_changed(conn):
    made = make(conn)
    taken = nz(2026, 10, 9, 8, 4)
    done = log.db_done(conn, made.id, taken, log.BUTTON, now=NOW)
    assert (done.state, done.actual_at) == (log.DONE, taken)
    event = log.db_history(conn, made.id)[-1]
    assert (event.kind, event.source, event.at) == (log.MARKED_DONE, log.BUTTON, NOW)
    assert event.before == {"state": "pending", "actual_at": None}
    assert event.after == {"state": "done", "actual_at": "2026-10-08T19:04:00.000000+00:00"}


def test_a_skip_by_the_bot_carries_its_reason(conn):
    mine, bots = make(conn, seq=1), make(conn, seq=2)
    assert not log.db_skip(conn, mine.id, log.BUTTON, now=NOW).automatic
    skipped = log.db_skip(conn, bots.id, log.AUTOMATIC, automatic=True, reason="not enough time", now=NOW)
    assert (skipped.state, skipped.automatic, skipped.reason) == (log.SKIPPED, True, "not enough time")


def test_missed_is_always_the_bots_conclusion(conn):
    missed = log.db_miss(conn, make(conn).id, now=NOW)
    assert (missed.state, missed.automatic) == (log.MISSED, True)
    assert log.db_history(conn, missed.id)[-1].source == log.AUTOMATIC


def test_reopening_clears_what_was_recorded(conn):
    made = make(conn)
    log.db_skip(conn, made.id, log.AUTOMATIC, automatic=True, reason="not enough time", now=NOW)
    reopened = log.db_reopen(conn, made.id, log.MESSAGE, now=NOW)
    assert (reopened.state, reopened.actual_at, reopened.automatic, reopened.reason) == (log.PENDING, None, False, None)
    assert kinds(conn, made.id) == [log.CREATED, log.MARKED_SKIPPED, log.REOPENED]


def test_moving_the_due_time_leaves_the_plan_alone(conn):
    made = make(conn, planned=time(11, 0), due=nz(2026, 10, 9, 11, 0))
    moved = log.db_move(conn, made.id, nz(2026, 10, 9, 11, 40), now=NOW)
    assert moved.due_at == nz(2026, 10, 9, 11, 40)
    assert moved.planned_time == time(11, 0)
    assert log.db_history(conn, made.id)[-1].kind == log.MOVED


def test_a_change_that_changes_nothing_leaves_no_trace(conn):
    made = make(conn, due=nz(2026, 10, 9, 11, 0))
    log.db_move(conn, made.id, nz(2026, 10, 9, 11, 0), now=NOW)
    log.db_reopen(conn, made.id, log.MESSAGE, now=NOW)
    assert kinds(conn, made.id) == [log.CREATED]


def test_only_known_fields_and_states_can_be_set(conn):
    made = make(conn)
    with pytest.raises(ValueError):
        log.db_change(conn, made.id, log.CORRECTED, log.MESSAGE, state="eaten")
    with pytest.raises(ValueError):
        log.db_change(conn, made.id, log.CORRECTED, log.MESSAGE, day=DAY)
    with pytest.raises(LookupError):
        log.db_done(conn, 999, NOW, log.BUTTON)


# ---------------------------------------------------------------------------
# The last change, and taking it back
# ---------------------------------------------------------------------------
def test_changes_made_together_are_one_change(conn):
    first, second = make(conn, seq=1), make(conn, seq=2, due=nz(2026, 10, 9, 13, 0))
    log.db_done(conn, first.id, nz(2026, 10, 9, 10, 0), log.BUTTON, now=NOW)
    # A correction, and what it moved
    change = log.new_change_id()
    log.db_change(conn, first.id, log.CORRECTED, log.MESSAGE, change_id=change, actual_at=nz(2026, 10, 9, 9, 0), now=NOW)
    log.db_move(conn, second.id, nz(2026, 10, 9, 12, 0), change_id=change, now=NOW)

    last = log.db_last_change(conn, 1, TASK)
    assert [(event.occurrence_id, event.kind) for event in last] == [(first.id, log.CORRECTED), (second.id, log.MOVED)]
    assert {event.change_id for event in last} == {change}


def test_what_the_bot_did_by_itself_is_not_the_users_last_change(conn):
    first, second = make(conn, seq=1), make(conn, seq=2)
    log.db_done(conn, first.id, nz(2026, 10, 9, 10, 0), log.BUTTON, now=NOW)
    log.db_miss(conn, second.id, now=NOW)
    assert [event.occurrence_id for event in log.db_last_change(conn, 1, TASK)] == [first.id]
    assert log.db_last_change(conn, 1, "other") == []


def test_taking_a_change_back_restores_everything_it_touched(conn):
    first, second = make(conn, seq=1), make(conn, seq=2, due=nz(2026, 10, 9, 13, 0))
    log.db_done(conn, first.id, nz(2026, 10, 9, 10, 0), log.BUTTON, now=NOW)
    change = log.new_change_id()
    log.db_change(conn, first.id, log.CORRECTED, log.MESSAGE, change_id=change, actual_at=nz(2026, 10, 9, 9, 0), now=NOW)
    log.db_move(conn, second.id, nz(2026, 10, 9, 12, 0), change_id=change, now=NOW)

    reverted = log.db_revert(conn, change, log.MESSAGE, now=NOW)

    assert {o.id for o in reverted} == {first.id, second.id}
    assert log.db_get(conn, first.id).actual_at == nz(2026, 10, 9, 10, 0)
    assert log.db_get(conn, second.id).due_at == nz(2026, 10, 9, 13, 0)
    event = log.db_history(conn, first.id)[-1]
    assert (event.kind, event.note) == (log.REVERTED, change), "the history keeps the mistake and its undoing"


def test_undoing_twice_takes_back_the_change_before_not_the_undo(conn):
    made = make(conn)
    log.db_done(conn, made.id, nz(2026, 10, 9, 10, 0), log.BUTTON, now=NOW)
    log.db_change(conn, made.id, log.CORRECTED, log.MESSAGE, actual_at=nz(2026, 10, 9, 9, 0), now=NOW)

    log.db_revert(conn, log.db_last_change(conn, 1, TASK)[0].change_id, log.MESSAGE, now=NOW)
    assert log.db_get(conn, made.id).actual_at == nz(2026, 10, 9, 10, 0)

    log.db_revert(conn, log.db_last_change(conn, 1, TASK)[0].change_id, log.MESSAGE, now=NOW)
    assert log.db_get(conn, made.id).state == log.PENDING

    assert log.db_last_change(conn, 1, TASK) == [], "nothing left to take back"


def test_a_change_overtaken_by_a_later_one_cannot_be_taken_back(conn):
    made = make(conn)
    log.db_done(conn, made.id, nz(2026, 10, 9, 10, 0), log.BUTTON, now=NOW)
    first = log.db_last_change(conn, 1, TASK)[0].change_id
    log.db_change(conn, made.id, log.CORRECTED, log.MESSAGE, actual_at=nz(2026, 10, 9, 9, 0), now=NOW)

    with pytest.raises(UserError, match="changed again since"):
        log.db_revert(conn, first, log.MESSAGE, now=NOW)
    assert log.db_get(conn, made.id).actual_at == nz(2026, 10, 9, 9, 0), "nothing was changed"
    with pytest.raises(UserError, match="nothing to take back"):
        log.db_revert(conn, "no-such-change", log.MESSAGE, now=NOW)


# ---------------------------------------------------------------------------
# For the new day, and for deleting an item for good
# ---------------------------------------------------------------------------
def test_what_is_still_pending_from_earlier_days(conn):
    old = make(conn, day=DAY - timedelta(days=3))
    yesterday_done = make(conn, day=DAY - timedelta(days=1))
    log.db_done(conn, yesterday_done.id, NOW, log.BUTTON, now=NOW)
    yesterday = make(conn, day=DAY - timedelta(days=1), seq=2)
    make(conn, day=DAY)
    assert [o.id for o in log.db_pending_before(conn, TASK, DAY)] == [old.id, yesterday.id]


def test_deleting_an_item_takes_its_occurrences_and_their_history(conn):
    gone, kept = make(conn, item_id=7), make(conn, item_id=8)
    log.db_done(conn, gone.id, NOW, log.BUTTON, now=NOW)
    assert log.db_delete_item(conn, TASK, 7) == 1
    assert log.db_get(conn, gone.id) is None
    assert log.db_history(conn, gone.id) == []
    assert kinds(conn, kept.id) == [log.CREATED]


def test_the_async_calls_do_the_same(db):
    import asyncio

    async def scenario():
        made = await log.ensure(1, TASK, 7, DAY, planned_time=time(8, 0))
        await database.run(log.db_done, made.id, NOW, log.BUTTON)
        change = (await log.last_change(1, TASK))[0].change_id
        await log.revert(change, log.MESSAGE)
        return await log.get(made.id), await log.for_day(1, TASK, DAY), await log.history(made.id)

    occurrence, today, events = asyncio.run(scenario())
    assert occurrence.state == log.PENDING
    assert [o.id for o in today] == [occurrence.id]
    assert [event.kind for event in events] == [log.CREATED, log.MARKED_DONE, log.REVERTED]
