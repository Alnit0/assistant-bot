import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("assistant")


class Debouncer:
    """Collects events and hands them over together once things go quiet.

    Global: there is one timer for everything passed to trigger(), whatever it
    is about. Each new event restarts the timer; after `delay` seconds with no
    new events the callback gets the whole batch, in the order they arrived.
    """

    def __init__(
        self,
        delay: float,
        callback: Callable[[list], Awaitable[None]],
        name: str = "debouncer",
    ):
        self.delay = delay
        self.name = name
        self._callback = callback
        self._events: list = []
        self._timer: asyncio.Task | None = None

    @property
    def pending(self) -> int:
        """How many events are waiting for the quiet period to end."""
        return len(self._events)

    def trigger(self, event=None) -> None:
        """Record an event and restart the quiet period. Call from the event loop."""
        self._events.append(event)
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.create_task(self._wait(), name=f"debounce: {self.name}")

    def cancel(self) -> None:
        """Forget everything collected so far without calling the callback."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._events = []

    async def _wait(self) -> None:
        await asyncio.sleep(self.delay)
        # Quiet period over. Let go of the timer first, so an event arriving
        # while the callback runs starts a new batch rather than cancelling it
        events, self._events = self._events, []
        self._timer = None
        try:
            await self._callback(events)
        except Exception:
            log.exception("Debouncer callback failed: %s", self.name)
