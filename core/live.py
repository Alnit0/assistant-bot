import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from core import timing

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Work that nobody should wait for.
#
# A Live message (the timers board, a timer's own message, a session card) is
# rewritten whenever what it shows changes. Doing that before answering makes
# the user wait for edits they aren't looking at, and several changes in a row
# edit the same message again and again until Discord rate-limits it.
#
# `schedule(key, refresh)` asks for one message to be brought up to date:
# - it returns at once; the edit happens in the background
# - asked again before the edit has run, the requests become one
# - the same message is edited at most once every MIN_INTERVAL seconds
# `refresh` must read what to show when it runs, not when it was scheduled,
# so the edit that does happen always shows how things stand.
#
# `background(coroutine)` is for anything else that can follow the reply (a
# #bot-log card, say). No Discord calls here: the callers bring their own.
# ---------------------------------------------------------------------------
MIN_INTERVAL = 2.0  # seconds between two edits of the same message
SLOW_INTERVAL = 30.0  # for a message many things change (the briefing): at most one edit this often
_slow: set = set()
_every: dict[object, float] = {}  # a key's own interval between edits (`schedule(..., every=)`)

Refresh = Callable[[], Awaitable[None]]

_pending: dict[object, Refresh] = {}
_last: dict[object, float] = {}  # when each key's refresh last began (time.monotonic)
_workers: dict[object, asyncio.Task] = {}
_background: set[asyncio.Task] = set()


def wait_needed(last: float | None, now: float, interval: float | None = None) -> float:
    """How long to hold a refresh back so that two of the same message are at
    least `interval` apart (MIN_INTERVAL unless given). Nothing if it has
    never run, or not lately."""
    if last is None:
        return 0.0
    if interval is None:
        interval = MIN_INTERVAL  # read when asked, so a test can make it nothing
    return max(0.0, last + interval - now)


def _dev_bot() -> bool:
    """The dev bot (the self-test, a day in the hub) on its own clock: the briefing is redrawn as often as any
    live message, or every step would wait half a minute for it (17 Oct: the day's replay ran out of time)."""
    from core import config

    return bool(config.SEPARATE_BOT)


def schedule(key, refresh: Refresh, slow: bool = False, every: float | None = None) -> None:
    """Bring one live message up to date soon, in the background. `key` names
    the message (("board", channel_id)); the latest `refresh` for a key wins.
    `slow`: at most one edit every SLOW_INTERVAL, the rest coalesced; `every`:
    at most one edit that often, in seconds (the week view: a minute)."""
    if slow:
        _slow.add(key)
    if every is not None:
        _every[key] = every
    _pending[key] = refresh
    worker = _workers.get(key)
    if worker is None or worker.done():
        _workers[key] = _spawn(_work(key))


async def _work(key) -> None:
    # Runs until nothing more has been asked for this key
    while key in _pending:
        interval = _every.get(key) if key in _every and MIN_INTERVAL > 0 and not _dev_bot() else SLOW_INTERVAL if key in _slow and MIN_INTERVAL > 0 and not _dev_bot() else None
        wait = wait_needed(_last.get(key), time.monotonic(), interval)
        if wait > 0:
            await asyncio.sleep(wait)
        refresh = _pending.pop(key, None)
        if refresh is None:
            break
        _last[key] = time.monotonic()
        try:
            await refresh()
        except Exception:
            log.exception("Could not update a live message: %s", key)


def background(coroutine: Awaitable) -> asyncio.Task:
    """Run something after the reply instead of before it. A failure is logged,
    never raised: nobody is waiting for it."""

    async def run() -> None:
        try:
            await coroutine
        except Exception:
            log.exception("Background work failed")

    return _spawn(run())


def _spawn(coroutine) -> asyncio.Task:
    async def detached() -> None:
        # Its own copy of the context: what it does is no longer part
        # of the time the user waited
        timing.stop()
        await coroutine

    spawned = asyncio.get_running_loop().create_task(detached())
    _background.add(spawned)  # the loop only keeps a weak reference
    spawned.add_done_callback(_background.discard)
    return spawned


async def settle() -> None:
    """Wait for everything scheduled so far to finish (shutdown, and tests).

    Work left over from an event loop that has gone can never finish here, and
    work that finished as its loop closed never had its clean-up run: both are
    dropped, not waited for. (Waiting for them made this spin for ever, now
    and then, in tests that run one loop after another: found 2026-10-13.)"""
    here = asyncio.get_running_loop()
    while _background:
        waiting = [task for task in _background if not task.done() and task.get_loop() is here]
        _background.intersection_update(waiting)
        if not waiting:
            break
        await asyncio.gather(*waiting, return_exceptions=True)


def reset() -> None:
    """Forget everything (tests: each has its own event loop)."""
    _pending.clear()
    _last.clear()
    _workers.clear()
    _background.clear()
