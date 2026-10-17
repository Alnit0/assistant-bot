import asyncio
import json
import logging
import time as clock_time
import urllib.parse

from core import config
from tasks.gym import rules

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The spreadsheet mirror, behind GYM_SHEET (off until Alex shares a sheet:
# docs/GYM-SHEET-SETUP.md). Every logged set is appended to his Google Sheet in
# his logbook's own columns, through the service account the calendar uses
# (GOOGLE_SA_KEY_PATH), as the sheet with GYM_SHEET_ID. A write that fails is
# logged and nothing else: the bot's own record is the database.
# No id or key in any error.
# ---------------------------------------------------------------------------
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets/"
COLUMNS = ("Date", "Week", "Day", "Exercise", "Sets", "Reps", "Reps Achieved", "Weight", "Objective", "Notes")
_token: dict = {}


def on() -> bool:
    return bool(config.GYM_SHEET) and bool((config.GYM_SHEET_ID or "").strip()) and bool((config.GOOGLE_SA_KEY_PATH or "").strip())


def row(session, each: rules.DoneSet, note_text: str = "") -> list[str]:
    """One set as a row of Alex's logbook. Pure."""
    name = f"{each.exercise} ({each.set_type})"
    reps = rules.range_text(each.low, each.high) if each.low is not None else ""
    return [f"{session.day.day}/{session.day.month}/{session.day.year}", "", session.name, name, "1", reps,
            "" if each.reps is None else str(each.reps), "" if each.weight is None else f"{each.weight:g}kg", each.purpose, note_text]


def _access_token() -> str:
    from core import day as days  # noqa: F401  (kept apart from the calendar's token: another scope)
    from google.auth import crypt, jwt

    if _token.get("value") and _token.get("until", 0) > clock_time.time() + 60:
        return _token["value"]
    with open(config.GOOGLE_SA_KEY_PATH, encoding="utf-8") as file:
        account = json.load(file)
    signer = crypt.RSASigner.from_service_account_info(account)
    now = int(clock_time.time())
    assertion = jwt.encode(signer, {"iss": account["client_email"], "scope": SCOPE, "aud": account["token_uri"], "iat": now, "exp": now + 3600}).decode()
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}).encode()
    from tasks.calendar import google

    status, raw = google._send("POST", account["token_uri"], body, {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise RuntimeError(f"Google refused the service account ({status})")
    found = json.loads(raw)
    _token.update(value=found["access_token"], until=clock_time.time() + int(found.get("expires_in", 3600)))
    return _token["value"]


def _append(rows: list[list[str]]) -> None:
    from tasks.calendar import google

    url = API + urllib.parse.quote(config.GYM_SHEET_ID.strip(), safe="") + "/values/" + urllib.parse.quote("A1", safe="") + ":append?valueInputOption=USER_ENTERED"
    status, _ = google._send("POST", url, json.dumps({"values": rows}).encode(), {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"})
    if status >= 300:
        raise RuntimeError(f"Google answered {status}")


async def mirror(session, sets: list[rules.DoneSet], note) -> None:
    """Append these sets to the sheet, when the mirror is on. Never raises."""
    if not on() or not sets:
        return
    rows = [row(session, each, note.text if note is not None and index == len(sets) - 1 else "") for index, each in enumerate(sets)]
    try:
        await asyncio.to_thread(_append, rows)
    except Exception as error:
        log.warning("Gym sheet: the sets could not be written (%s)", type(error).__name__)
