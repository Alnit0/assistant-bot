import asyncio
import logging
import time

from core.discord_utils import log_simple

COOLDOWN = 10  # seconds between #bot-log cards, so reporting can't feed itself


class RateLimitMonitor(logging.Handler):
    """Notices discord.py's "we are being rate limited" warnings.

    discord.py handles rate limits itself by waiting and retrying, and only
    tells us through its log. This counts those warnings and passes them on to
    #bot-log.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.count = 0
        self._last_card = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if "rate limit" not in message.lower():
                return
            self.count += 1
            if time.monotonic() - self._last_card < COOLDOWN:
                return
            self._last_card = time.monotonic()
            # discord.py logs this from inside the event loop, so we can post from here
            asyncio.get_running_loop().create_task(log_simple("🚦 Rate limited", message))
        except Exception:
            self.handleError(record)


monitor = RateLimitMonitor()


def install() -> None:
    """Start listening. Safe to call more than once."""
    logger = logging.getLogger("discord.http")
    if monitor not in logger.handlers:
        logger.addHandler(monitor)
