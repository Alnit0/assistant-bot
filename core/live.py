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

Refresh = Callable[[], Awaitable[None]]

_pending: dict[object, Refresh] = {}
_last: dict[object, float] = {}  # when each key's refresh last began (time.monotonic)
_workers: dict[object, asyncio.Task] = {}
_background: set[asyncio.Task] = set()


def wait_needed(last: float | None, now: float, interval: float = MIN_INTERVAL) -> float:
    """How long to hold a refresh back so that two of the same message are at
    least `interval` apart. Nothing if it has never run, or not lately."""
    if last is None:
        return 0.0
    return max(0.0, last + interval - now)


def schedule(key, refresh: Refresh) -> None:
    """Bring one live message up to date soon, in the background. `key` names
    the message (("board", channel_id)); the latest `refresh` for a key wins."""
    _pending[key] = refresh
    worker = _workers.get(key)
    if worker is None or worker.done():
        _workers[key] = _spawn(_work(key))


async def _work(key) -> None:
    # Runs until nothing more has been asked for this key
    while key in _pending:
        wait = wait_needed(_last.get(key), time.monotonic())
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
        # This task's own copy of the context: what it does is no longer part
        # of the time the user waited
        timing.stop()
        await coroutine

    task = asyncio.get_running_loop().create_task(detached())
    _background.add(task)  # the loop only keeps a weak reference
    task.add_done_callback(_background.discard)
    return task


async def settle() -> None:
    """Wait for everything scheduled so far to finish (shutdown, and tests)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


def reset() -> None:
    """Forget everything (tests: each has its own event loop)."""
    _pending.clear()
    _last.clear()
    _workers.clear()
    _background.clear()
