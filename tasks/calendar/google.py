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
# The bot's own marker on an event it keeps for another task (a birthday's yearly all-day event): a private
# extended property, never the title. Such an event is shown by that task alone, never as a calendar item
# (the hub, the Today card, the timeline, #calendar's days, the answers): Google Calendar shows it, and its own
# notification is set there. Alex, 19 Oct
HIDDEN = "assistant_hidden"


def hidden(item: dict) -> bool:
    """Whether an API event carries the bot's marker. Pure."""
    return bool(((item.get("extendedProperties") or {}).get("private") or {}).get(HIDDEN))
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
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.split("/calendars/", 1)[-1].split("/")
    calendar_id, ref = urllib.parse.unquote(path[0]), (urllib.parse.unquote(path[2]) if len(path) > 2 else "")
    found = kept["calendars"].setdefault(calendar_id, {})
    changed = kept.setdefault("exceptions", {}).setdefault(calendar_id, {})  # a series' happenings changed or cancelled
    payload = json.loads(body) if body else {}
    status, answer = 200, {}
    if method == "GET" and not ref:
        query = dict(urllib.parse.parse_qsl(parsed.query))
        low, high = (datetime.fromisoformat(query[name]) for name in ("timeMin", "timeMax")) if "timeMin" in query else (None, None)
        items = []
        for each in found.values():
            items += _happenings(each, changed, low, high) if each.get("recurrence") and low is not None else [each]
        answer = {"items": items}
    elif method == "POST":
        kept["next"] += 1
        answer = found[f"e{kept['next']}"] = {"id": f"e{kept['next']}", "status": "confirmed", **payload}
    elif ref not in found and _happening(found, changed, ref) is not None:
        # One happening of a series, by its own id: changing it makes an exception, as the API does
        if method == "PATCH":
            changed.setdefault(ref, {}).update(payload)
        elif method == "DELETE":
            changed.setdefault(ref, {})["status"] = "cancelled"
        answer = _happening(found, changed, ref) if method != "DELETE" else None
        status = 204 if method == "DELETE" else 200
    elif ref not in found:
        status = 404
    elif method == "GET":
        answer = found[ref]
    elif method == "PATCH":
        found[ref].update(payload)
        answer = found[ref]
    elif method == "DELETE":
        del found[ref]
        for each in [key for key in changed if key.startswith(f"{ref}_")]:
            del changed[each]
        status, answer = 204, None
    where.write_text(json.dumps(kept), encoding="utf-8")
    return status, (json.dumps(answer).encode() if answer is not None else b"")


def _series_start(item: dict) -> tuple[datetime, timedelta, bool]:
    """A series' first start as a moment (an all-day one at midnight UTC), its length, and whether it is all day."""
    from zoneinfo import ZoneInfo

    start, end = item["start"], item["end"]
    if "date" in start and "dateTime" not in start:
        first = datetime.fromisoformat(start["date"]).replace(tzinfo=timezone.utc)
        return first, datetime.fromisoformat(end["date"]).replace(tzinfo=timezone.utc) - first, True
    zone = ZoneInfo(start.get("timeZone") or str(config.TIMEZONE))
    first = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
    first = first if first.tzinfo else first.replace(tzinfo=zone)
    last = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
    last = last if last.tzinfo else last.replace(tzinfo=zone)
    return first, last - first, False


def _instance(item: dict, moment: datetime, length: timedelta, all_day: bool, changed: dict) -> dict:
    """One happening of a series as the API answers it with singleEvents, its exception applied."""
    ref = f"{item['id']}_{moment.astimezone(timezone.utc):%Y%m%d}" if all_day else f"{item['id']}_{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
    when = ({"date": moment.date().isoformat()}, {"date": (moment + length).date().isoformat()}) if all_day else (
        {"dateTime": moment.isoformat()}, {"dateTime": (moment + length).isoformat()})
    found = {"id": ref, "recurringEventId": item["id"], "status": "confirmed", "summary": item.get("summary", ""), "start": when[0], "end": when[1],
             **{key: item[key] for key in ("location", "description") if key in item}}
    found.update(changed.get(ref, {}))
    return found


def _happenings(item: dict, changed: dict, low: datetime, high: datetime) -> list[dict]:
    """A series' happenings from `low` to `high` (the made-up Google of the dev bot only), as the API expands an
    RRULE in the series' own time zone, with its exceptions; cancelled ones left out."""
    from dateutil import rrule as dateutil_rrule

    if item.get("status") == "cancelled":
        return []
    first, length, all_day = _series_start(item)
    line = next((each for each in item["recurrence"] if each.startswith("RRULE:")), "")
    if all_day and "UNTIL=" in line and "T" not in line.split("UNTIL=", 1)[1].split(";")[0]:
        line = line.replace(line.split("UNTIL=", 1)[1].split(";")[0], line.split("UNTIL=", 1)[1].split(";")[0] + "T000000Z")
    rule = dateutil_rrule.rrulestr(line, dtstart=first)
    found = []
    for moment in rule.between(low - length, high, inc=True):
        each = _instance(item, moment, length, all_day, changed)
        if each["status"] != "cancelled":
            found.append(each)
    return found


def _happening(found: dict, changed: dict, ref: str) -> dict | None:
    """One happening of a series by its id ("e3_20261110T030000Z"), or None if it is no happening of one."""
    master_id, _, stamp = ref.rpartition("_")
    item = found.get(master_id)
    if item is None or not item.get("recurrence") or not stamp:
        return None
    first, length, all_day = _series_start(item)
    try:
        moment = datetime.strptime(stamp, "%Y%m%d").replace(tzinfo=timezone.utc) if all_day else datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    for each in _happenings({**item, "status": "confirmed"}, {}, moment - timedelta(seconds=1), moment + timedelta(seconds=1)):
        if each["id"] == ref:
            return _instance(item, datetime.fromisoformat(each["start"].get("dateTime") or each["start"]["date"] + "T00:00:00+00:00"), length, all_day, changed)
    return None


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
    if item.get("status") == "cancelled" or hidden(item):
        return None  # cancelled, or kept by another task (`HIDDEN`): never a calendar item
    title = " ".join(str(item.get("summary") or "").split()) or rules.NO_TITLE
    start, end = item.get("start") or {}, item.get("end") or {}
    ref = str(item.get("id") or "")
    series = str(item.get("recurringEventId") or "")  # one happening of a repeating event (singleEvents)
    location = " ".join(str(item.get("location") or "").split())
    if "dateTime" in start:
        begins = _moment(start["dateTime"])
        ends = _moment(end["dateTime"]) if "dateTime" in end else begins
        return Event(f"{origin}:{ref}@{begins.isoformat()}", title, begins, max(ends, begins), origin=origin, ref=ref, series=series, location=location)
    if "date" in start:
        first = date.fromisoformat(start["date"])
        last = date.fromisoformat(end["date"]) - timedelta(days=1) if "date" in end else first
        return Event(f"{origin}:{ref}@{first.isoformat()}", title, first_day=first, last_day=max(last, first), origin=origin, ref=ref, series=series, location=location)
    return None


def details(location: str = "", description: str = "") -> dict:
    """An event's location and description as the API takes them: only those that were said. Pure."""
    return {**({"location": location} if location else {}), **({"description": description} if description else {})}


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

    async def add(self, title: str, start: datetime, end: datetime, location: str = "", description: str = "") -> Event:
        self._writable()
        body = {"summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}, **details(location, description)}
        made = await asyncio.to_thread(_call, "POST", self._path("events"), None, body)
        return to_event(made, self.origin)

    async def add_all_day(self, title: str, first: date, last: date, location: str = "", description: str = "") -> Event:
        """An all-day event from its first local day to its last (the API's end is the day after)."""
        self._writable()
        body = {"summary": title, "start": {"date": first.isoformat()}, "end": {"date": (last + timedelta(days=1)).isoformat()}, **details(location, description)}
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

    async def move_all_day(self, ref: str, first: date, last: date) -> Event:
        """An all-day event to other days (the API's end is the day after its last)."""
        self._writable()
        body = {"start": {"date": first.isoformat()}, "end": {"date": (last + timedelta(days=1)).isoformat()}}
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
