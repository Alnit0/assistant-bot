"""Live messages are brought up to date in the background: at once, one edit
however many changes asked for it, and never more often than the interval."""
import asyncio

import pytest

from core import live, timing


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    live.reset()
    monkeypatch.setattr(live, "MIN_INTERVAL", 0.05)
    yield
    live.reset()


# --- when an edit may run -----------------------------------------------------
@pytest.mark.parametrize(
    "last, now, expected",
    [(None, 100.0, 0.0), (99.5, 100.0, 1.5), (98.0, 100.0, 0.0), (90.0, 100.0, 0.0), (100.0, 100.0, 2.0)],
)
def test_two_edits_of_one_message_are_kept_the_interval_apart(last, now, expected):
    assert live.wait_needed(last, now, 2.0) == expected


# --- scheduling ---------------------------------------------------------------
def test_scheduling_returns_at_once_and_the_edit_follows():
    ran = []

    async def refresh():
        ran.append("board")

    async def go():
        live.schedule("board", refresh)
        before = list(ran)
        await live.settle()
        return before

    assert asyncio.run(go()) == [] and ran == ["board"]


def test_several_changes_in_a_row_are_one_edit_and_then_one_more():
    ran = []

    async def go():
        for number in range(5):

            async def refresh(number=number):
                ran.append(number)

            live.schedule("board", refresh)
            await asyncio.sleep(0)
        await live.settle()

    asyncio.run(go())
    # The first runs straight away; the four that came while it was held back are one, the latest
    assert ran == [0, 4]


def test_the_second_edit_waits_for_the_interval():
    times = []

    async def refresh():
        times.append(asyncio.get_running_loop().time())

    async def go():
        live.schedule("board", refresh)
        await asyncio.sleep(0.01)
        live.schedule("board", refresh)
        await live.settle()

    asyncio.run(go())
    assert len(times) == 2 and times[1] - times[0] >= 0.045


def test_different_messages_do_not_wait_for_each_other():
    ran = []

    async def go():
        for key in ("board", "list", "timer 1"):

            async def refresh(key=key):
                ran.append(key)

            live.schedule(key, refresh)
        await asyncio.sleep(0.01)
        return list(ran)

    assert sorted(asyncio.run(go())) == ["board", "list", "timer 1"]


def test_a_failed_edit_is_not_raised_and_the_next_one_still_runs():
    ran = []

    async def broken():
        raise RuntimeError("Discord said no")

    async def fine():
        ran.append("ok")

    async def go():
        live.schedule("board", broken)
        await live.settle()
        live.schedule("board", fine)
        await live.settle()

    asyncio.run(go())
    assert ran == ["ok"]


# --- anything else that can follow the reply ----------------------------------
def test_background_work_runs_and_its_failure_is_swallowed():
    ran = []

    async def card():
        ran.append("card")

    async def broken():
        raise RuntimeError("no")

    async def go():
        live.background(card())
        live.background(broken())
        await live.settle()

    asyncio.run(go())
    assert ran == ["card"]


def test_what_runs_in_the_background_is_not_counted_as_the_users_wait():
    async def go() -> timing.Turn:
        turn = timing.start()

        async def refresh():
            timing.record_discord(1.0)

        live.schedule("board", refresh)
        live.background(refresh())
        await live.settle()
        timing.record_discord(0.25)  # the turn itself is still being timed
        return turn

    turn = asyncio.run(go())
    assert (turn.discord_calls, turn.discord_seconds) == (1, 0.25)
