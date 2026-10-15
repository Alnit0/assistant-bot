import asyncio
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from core import config
from tasks.calendar import rules
from tasks.calendar.rules import Event

# ---------------------------------------------------------------------------
# Where events come from, behind one small interface, several at once:
#
#   for each in sources():                every calendar CALENDAR_READ names
#       await each.events(first, last)    every happening on those local days
#       each.origin                       what the copy calls it ("link", "bot")
#       each.can_write                    only the Bot calendar, with CALENDAR_WRITE
#   bot()                                 the one calendar ever written to, or None
#
# `IcsSource` is the secret iCal address in live's .env (CALENDAR_ICS_URL)
# or, for the dev bot's self-test and the tests, a file of made-up events;
# `google.GoogleSource` is a calendar read through the Google Calendar API
# as the service account. CALENDAR_READ lists them, comma apart: `ics`, and
# `google:` with a calendar's id or the name of the setting that holds it
# (`google:CALENDAR_BOT_ID`). With CALENDAR_WRITE on the Bot calendar is
# read too, listed or not. No link, id or key is ever printed, logged or
# kept anywhere else: an error says what kind it was and nothing more.
# ---------------------------------------------------------------------------
TIMEOUT = 20  # seconds a fetch may take


class FetchFailed(Exception):
    """The feed could not be read. Its words never hold the link."""


LINK, BOT = "link", "bot"


@dataclass(frozen=True)
class IcsSource:
    """A calendar's iCal feed: a link (https) or a file of made-up events."""

    where: str
    origin: str = LINK
    can_write: bool = False

    async def events(self, first: date, last: date) -> list[Event]:
        text = await asyncio.to_thread(self._read)
        try:
            found = await asyncio.to_thread(rules.parse, text, first, last)
        except ValueError as error:
            raise FetchFailed(str(error)) from None
        return [replace(each, origin=self.origin) for each in found]

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
    """The iCal link's source, or None with no link set."""
    where = (config.CALENDAR_ICS_URL or "").strip()
    return IcsSource(where) if where else None


def _calendar_id(said: str) -> str:
    """A calendar's id as listed: itself, or the setting that holds it (CALENDAR_BOT_ID)."""
    said = said.strip()
    if said and said.upper() == said and "@" not in said:
        return str(getattr(config, said, "") or "").strip()
    return said


def bot():
    """The Bot calendar, the one ever written to: None without CALENDAR_BOT_ID set."""
    from tasks.calendar.google import GoogleSource

    found = (config.CALENDAR_BOT_ID or "").strip()
    return GoogleSource(found, BOT) if found else None


def sources() -> list:
    """Every calendar to read, in the order CALENDAR_READ lists them (`ics` when it is not
    set), each once; the Bot calendar too while writing is on."""
    from tasks.calendar.google import GoogleSource

    listed = [each.strip() for each in (config.CALENDAR_READ or "ics").split(",") if each.strip()]
    found, ids, extra = [], set(), 0
    for each in listed:
        kind, _, said = each.partition(":")
        if kind.lower() == "ics":
            link = current()
            if link is not None and LINK not in {getattr(one, "origin", "") for one in found}:
                found.append(link)
        elif kind.lower() == "google":
            calendar = _calendar_id(said)
            if calendar and calendar not in ids:
                ids.add(calendar)
                if calendar == (config.CALENDAR_BOT_ID or "").strip():
                    found.append(GoogleSource(calendar, BOT))
                else:
                    extra += 1
                    found.append(GoogleSource(calendar, f"google{extra}"))
    writer = bot()
    if config.CALENDAR_WRITE and writer is not None and writer.calendar_id not in ids:
        found.append(writer)
    return found
