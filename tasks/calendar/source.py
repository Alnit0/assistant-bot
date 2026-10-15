import asyncio
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core import config
from tasks.calendar import rules
from tasks.calendar.rules import Event

# ---------------------------------------------------------------------------
# Where events come from, behind one small interface, so the private iCal
# link can later be swapped for the Google Calendar API through a service
# account (docs/BACKLOG.md) without the rest of the task changing.
#
#   source = current()
#   await source.events(first, last)   every happening on those local days
#   source.can_write                   False: the iCal link is read only
#
# Today there is one: `IcsSource`, the secret iCal address in live's .env
# (CALENDAR_ICS_URL) or, for the dev bot's self-test and the tests, a file
# of made-up events. The link is never printed, logged or kept anywhere
# else: an error says what kind it was and nothing of the address.
# ---------------------------------------------------------------------------
TIMEOUT = 20  # seconds a fetch may take


class FetchFailed(Exception):
    """The feed could not be read. Its words never hold the link."""


@dataclass(frozen=True)
class IcsSource:
    """A calendar's iCal feed: a link (https) or a file of made-up events."""

    where: str
    can_write: bool = False

    async def events(self, first: date, last: date) -> list[Event]:
        text = await asyncio.to_thread(self._read)
        try:
            return await asyncio.to_thread(rules.parse, text, first, last)
        except ValueError as error:
            raise FetchFailed(str(error)) from None

    def _read(self) -> str:
        if not self.where.lower().startswith("https://"):
            try:
                return Path(self.where).read_text(encoding="utf-8")
            except OSError as error:
                raise FetchFailed(f"the file could not be read ({type(error).__name__})") from None
        try:
            request = urllib.request.Request(self.where, headers={"User-Agent": "assistant-bot"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                return answer.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            raise FetchFailed(f"the calendar answered {error.code}") from None
        except Exception as error:
            raise FetchFailed(f"the calendar could not be reached ({type(error).__name__})") from None


def current() -> IcsSource | None:
    """The source the settings name, or None with no link set."""
    where = (config.CALENDAR_ICS_URL or "").strip()
    return IcsSource(where) if where else None
