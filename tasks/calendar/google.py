import asyncio
import json
import time as clock_time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from core import config
from tasks.calendar import rules
from tasks.calendar.rules import Event

# ---------------------------------------------------------------------------
# A calendar read (and, for the Bot calendar only, written) through the
# Google Calendar API, as the service account whose key is at
# GOOGLE_SA_KEY_PATH (live's .env; the key is never read into a log, a
# message or anything committed). The same interface as the iCal link
# (source.py): `events(first, last)`, `can_write`.
#
# Writing is allowed in one place only: a calendar whose id is
# CALENDAR_BOT_ID, with CALENDAR_WRITE on. Every write checks both here, so
# no other calendar is ever written to, whatever asks.
#
# No id, address or key is ever in an error's words: what kind of failure
# it was, and the status code.
# ---------------------------------------------------------------------------
API = "https://www.googleapis.com/calendar/v3/calendars/"
SCOPE = "https://www.googleapis.com/auth/calendar"
TIMEOUT = 20
_token: dict = {}  # the access token and when it expires, kept in memory only


class FetchFailed(Exception):
    """A read or a write did not work. Its words never hold an id or a key."""


class NotAllowed(Exception):
    """A write to a calendar that is not the Bot calendar, or with CALENDAR_WRITE off."""


def _send(method: str, url: str, body: bytes | None, headers: dict) -> tuple[int, bytes]:
    """One HTTP request: (status, body). The one place that reaches Google; tests replace it. With
    GOOGLE_CALENDAR_FAKE set (the dev bot's replay, never live) a file stands in for it."""
    if config.GOOGLE_CALENDAR_FAKE:
        return _fake(method, url, body)
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _fake(method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
    """The Calendar API as a JSON file of calendars and their events (made-up, for the replay)."""
    from pathlib import Path

    where = Path(config.GOOGLE_CALENDAR_FAKE)
    kept = json.loads(where.read_text(encoding="utf-8")) if where.exists() else {"calendars": {}, "next": 0}
    path = urllib.parse.urlparse(url).path.split("/calendars/", 1)[-1].split("/")
    calendar_id, ref = urllib.parse.unquote(path[0]), (urllib.parse.unquote(path[2]) if len(path) > 2 else "")
    found = kept["calendars"].setdefault(calendar_id, {})
    payload = json.loads(body) if body else {}
    status, answer = 200, {}
    if method == "GET" and not ref:
        answer = {"items": list(found.values())}
    elif method == "POST":
        kept["next"] += 1
        answer = found[f"e{kept['next']}"] = {"id": f"e{kept['next']}", "status": "confirmed", **payload}
    elif ref not in found:
        status = 404
    elif method == "GET":
        answer = found[ref]
    elif method == "PATCH":
        found[ref].update(payload)
        answer = found[ref]
    elif method == "DELETE":
        del found[ref]
        status, answer = 204, None
    where.write_text(json.dumps(kept), encoding="utf-8")
    return status, (json.dumps(answer).encode() if answer is not None else b"")


def _access_token() -> str:
    """A token for the service account, made by signing a request with its key (blocking)."""
    if config.GOOGLE_CALENDAR_FAKE:
        return "made-up"
    if _token.get("value") and _token.get("until", 0) > clock_time.time() + 60:
        return _token["value"]
    from google.auth import crypt, jwt

    path = (config.GOOGLE_SA_KEY_PATH or "").strip()
    if not path:
        raise FetchFailed("no service account key is set")
    try:
        with open(path, encoding="utf-8") as file:
            account = json.load(file)
        signer = crypt.RSASigner.from_service_account_info(account)
    except Exception as error:
        raise FetchFailed(f"the service account key could not be read ({type(error).__name__})") from None
    now = int(clock_time.time())
    claims = {"iss": account["client_email"], "scope": SCOPE, "aud": account["token_uri"], "iat": now, "exp": now + 3600}
    assertion = jwt.encode(signer, claims).decode()
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}).encode()
    try:
        status, raw = _send("POST", account["token_uri"], body, {"Content-Type": "application/x-www-form-urlencoded"})
    except Exception as error:
        raise FetchFailed(f"Google could not be reached ({type(error).__name__})") from None
    if status != 200:
        raise FetchFailed(f"Google refused the service account ({status})")
    found = json.loads(raw)
    _token.update(value=found["access_token"], until=clock_time.time() + int(found.get("expires_in", 3600)))
    return _token["value"]


def _call(method: str, path: str, query: dict | None = None, payload: dict | None = None) -> dict:
    """An API call, blocking: its answer as JSON (empty for a delete). Raises FetchFailed."""
    url = path + (("?" + urllib.parse.urlencode(query)) if query else "")
    headers = {"Authorization": f"Bearer {_access_token()}", "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        status, raw = _send(method, url, body, headers)
    except Exception as error:
        raise FetchFailed(f"Google could not be reached ({type(error).__name__})") from None
    if status == 401:
        _token.clear()
    if status >= 300:
        raise FetchFailed(f"Google answered {status}")
    return json.loads(raw) if raw else {}


def _moment(value: str) -> datetime:
    found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (found if found.tzinfo else found.replace(tzinfo=config.TIMEZONE)).astimezone(timezone.utc)


def to_event(item: dict, origin: str) -> Event | None:
    """One API event as the task keeps it; None for a cancelled one. Pure."""
    if item.get("status") == "cancelled":
        return None
    title = " ".join(str(item.get("summary") or "").split()) or rules.NO_TITLE
    start, end = item.get("start") or {}, item.get("end") or {}
    ref = str(item.get("id") or "")
    series = str(item.get("recurringEventId") or "")  # one happening of a repeating event (singleEvents)
    if "dateTime" in start:
        begins = _moment(start["dateTime"])
        ends = _moment(end["dateTime"]) if "dateTime" in end else begins
        return Event(f"{origin}:{ref}@{begins.isoformat()}", title, begins, max(ends, begins), origin=origin, ref=ref, series=series)
    if "date" in start:
        first = date.fromisoformat(start["date"])
        last = date.fromisoformat(end["date"]) - timedelta(days=1) if "date" in end else first
        return Event(f"{origin}:{ref}@{first.isoformat()}", title, first_day=first, last_day=max(last, first), origin=origin, ref=ref, series=series)
    return None


def local_time(moment: datetime) -> dict:
    """A start or an end as the API takes it for a repeating event: the local time and its zone, so
    Google keeps the time of day through daylight saving (9:00 am stays 9:00 am)."""
    return {"dateTime": moment.astimezone(config.TIMEZONE).replace(tzinfo=None).isoformat(), "timeZone": str(config.TIMEZONE)}


@dataclass(frozen=True)
class GoogleSource:
    calendar_id: str = field(repr=False)  # never in a log, even by accident
    origin: str = ""  # what the copy calls this calendar ("bot", "google1"): never its id

    @property
    def can_write(self) -> bool:
        bot = (config.CALENDAR_BOT_ID or "").strip()
        return bool(config.CALENDAR_WRITE) and bool(bot) and self.calendar_id == bot

    def _path(self, *more: str) -> str:
        return API + "/".join([urllib.parse.quote(self.calendar_id, safe=""), *(urllib.parse.quote(each, safe="") for each in more)])

    async def events(self, first: date, last: date) -> list[Event]:
        from core import day as days

        def read() -> list[Event]:
            found, page = [], None
            for _ in range(20):
                query = {"timeMin": days.start_of(first).isoformat(), "timeMax": days.start_of(last + timedelta(days=1)).isoformat(), "singleEvents": "true", "orderBy": "startTime", "maxResults": "250"}
                if page:
                    query["pageToken"] = page
                answer = _call("GET", self._path("events"), query)
                found += [each for each in (to_event(item, self.origin) for item in answer.get("items", [])) if each is not None]
                page = answer.get("nextPageToken")
                if not page:
                    break
            return rules.ordered(found)

        return await asyncio.to_thread(read)

    def _writable(self) -> None:
        if not self.can_write:
            raise NotAllowed("only the Bot calendar is ever written to, and only with CALENDAR_WRITE on")

    async def add(self, title: str, start: datetime, end: datetime) -> Event:
        self._writable()
        body = {"summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        made = await asyncio.to_thread(_call, "POST", self._path("events"), None, body)
        return to_event(made, self.origin)

    # --- a repeating event: the series itself, as the API keeps it -------------------------------------------
    async def insert(self, body: dict) -> dict:
        """A new event as the API takes it (a series: with `recurrence`); the API's answer."""
        self._writable()
        return await asyncio.to_thread(_call, "POST", self._path("events"), None, body)

    async def patch(self, ref: str, body: dict) -> dict:
        """A change to a series, or to one of its happenings (which becomes an exception); the answer."""
        self._writable()
        return await asyncio.to_thread(_call, "PATCH", self._path("events", ref), None, body)

    async def raw(self, ref: str) -> dict | None:
        """A series or a happening as the API keeps it, or None if it is gone."""
        try:
            return await asyncio.to_thread(_call, "GET", self._path("events", ref))
        except FetchFailed:
            return None

    async def move(self, ref: str, start: datetime, end: datetime) -> Event:
        self._writable()
        body = {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        moved = await asyncio.to_thread(_call, "PATCH", self._path("events", ref), None, body)
        return to_event(moved, self.origin)

    async def delete(self, ref: str) -> None:
        self._writable()
        await asyncio.to_thread(_call, "DELETE", self._path("events", ref))

    async def get(self, ref: str) -> Event | None:
        """One event read back, or None if it is gone (for checking a change before it is confirmed)."""
        try:
            found = await asyncio.to_thread(_call, "GET", self._path("events", ref))
        except FetchFailed:
            return None
        return to_event(found, self.origin)
