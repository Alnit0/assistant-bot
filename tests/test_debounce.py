import asyncio

from core.debounce import Debouncer

QUIET = 0.05  # seconds: short, so the tests are quick


def collector():
    batches = []

    async def collect(events):
        batches.append(events)

    return batches, collect


def test_events_are_handed_over_together_after_the_quiet_period():
    async def scenario():
        batches, collect = collector()
        debouncer = Debouncer(QUIET, collect)
        debouncer.trigger("a")
        debouncer.trigger("b")
        assert debouncer.pending == 2
        assert batches == [], "nothing happens straight away"
        await asyncio.sleep(QUIET * 3)
        return batches, debouncer.pending

    assert asyncio.run(scenario()) == ([["a", "b"]], 0)


def test_each_event_restarts_the_wait():
    async def scenario():
        batches, collect = collector()
        debouncer = Debouncer(QUIET, collect)
        debouncer.trigger("a")
        await asyncio.sleep(QUIET * 0.6)
        debouncer.trigger("b")
        await asyncio.sleep(QUIET * 0.6)
        waiting = list(batches)  # more than QUIET since "a", but not since "b"
        await asyncio.sleep(QUIET * 2)
        return waiting, batches

    assert asyncio.run(scenario()) == ([], [["a", "b"]])


def test_cancel_forgets_what_was_collected():
    async def scenario():
        batches, collect = collector()
        debouncer = Debouncer(QUIET, collect)
        debouncer.trigger("a")
        debouncer.cancel()
        await asyncio.sleep(QUIET * 3)
        return batches, debouncer.pending

    assert asyncio.run(scenario()) == ([], 0)


def test_events_after_a_batch_start_a_new_one():
    async def scenario():
        batches, collect = collector()
        debouncer = Debouncer(QUIET, collect)
        debouncer.trigger("a")
        await asyncio.sleep(QUIET * 3)
        debouncer.trigger("b")
        await asyncio.sleep(QUIET * 3)
        return batches

    assert asyncio.run(scenario()) == [["a"], ["b"]]


def test_an_event_arriving_while_the_callback_runs_is_not_lost():
    async def scenario():
        batches = []
        debouncer = None

        async def slow(events):
            batches.append(events)
            if events == ["a"]:
                debouncer.trigger("b")
                await asyncio.sleep(QUIET * 2)

        debouncer = Debouncer(QUIET, slow)
        debouncer.trigger("a")
        await asyncio.sleep(QUIET * 6)
        return batches

    assert asyncio.run(scenario()) == [["a"], ["b"]]


def test_a_failing_callback_does_not_stop_later_batches():
    async def scenario():
        batches = []

        async def flaky(events):
            batches.append(events)
            if len(batches) == 1:
                raise RuntimeError("first batch goes wrong")

        debouncer = Debouncer(QUIET, flaky)
        debouncer.trigger("a")
        await asyncio.sleep(QUIET * 3)
        debouncer.trigger("b")
        await asyncio.sleep(QUIET * 3)
        return batches

    assert asyncio.run(scenario()) == [["a"], ["b"]]


def test_a_zero_delay_acts_at_once():
    async def scenario():
        batches, collect = collector()
        Debouncer(0, collect).trigger("a")
        await asyncio.sleep(0.01)
        return batches

    assert asyncio.run(scenario()) == [["a"]]
