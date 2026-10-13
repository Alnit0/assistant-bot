import asyncio
import json
import logging
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time

from core import clock, config, database, scheduler, timeinput, timetable

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Money as I see it: New Zealand dollars.
#
# Anthropic bills in US dollars, so that is what is recorded, everywhere and
# for good (llm_calls, message_log, the self-test's history). Whatever I read
# (dev cost, a ping, the briefing, the status line) is shown in NZ$, at the
# latest rate the bot has:
#
#   fetched   once a day, as a scheduled job of the bot's own, from a free
#             public source that needs no key (Frankfurter: the European
#             Central Bank's reference rates), and kept (`exchange_rates`)
#   failing   the last rate that was fetched
#   none yet  USD_TO_NZD in .env (1.70 unless set)
#
# A fetch that fails is not a problem to be told about: the last known rate
# is used and the run's line says so. `dev cost` says which rate is in use
# and from when. Limits are set in round NZ$ (DAILY_SPEND_LIMIT_NZD,
# SELFTEST_MONTHLY_LIMIT_NZD) and compared in US$ at the rate of the moment.
# The dev bot never fetches: it uses what live last kept, or the setting.
# ---------------------------------------------------------------------------
SOURCE = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=NZD"
SOURCE_NAME = "Frankfurter (ECB)"
TIMEOUT = 8
JOB_TASK, JOB_KIND = "core", "exchange_rate"
LABEL = "exchange rate"
DEFAULT = timetable.Default("Exchange rate", time(5, 30), locked=True)
SANE = (0.5, 5.0)  # a rate outside this is not believed


@dataclass(frozen=True)
class Rate:
    value: float  # NZ$ for one US$
    fetched_at: datetime | None = None  # None: the setting, nothing fetched yet


_rate: Rate | None = None


def current() -> Rate:
    """The rate in use: the last one fetched, else the setting."""
    return _rate if _rate is not None else Rate(config.USD_TO_NZD)


def nzd(usd: float) -> float:
    return usd * current().value


def usd(nz: float) -> float:
    return nz / current().value


def shown(usd_amount: float | None, places: int = 2) -> str:
    """A US$ amount as I read it: "NZ$0.42"."""
    return f"NZ${nzd(usd_amount):.{places}f}" if usd_amount is not None else "unknown"


def said() -> str:
    """Which rate is in use and from when, for `dev cost`."""
    rate = current()
    if rate.fetched_at is None:
        return f"US$1 = NZ${rate.value:.4f} (USD_TO_NZD in .env: no rate has been fetched yet)"
    local = rate.fetched_at.astimezone(config.TIMEZONE)
    return f"US$1 = NZ${rate.value:.4f} ({SOURCE_NAME}, fetched {local.day} {local:%b} at {timeinput.format_time(local.time())})"


# --- kept -----------------------------------------------------------------------------------------------------------------
def db_latest(conn: sqlite3.Connection) -> Rate | None:
    row = conn.execute("SELECT usd_to_nzd, fetched_at FROM exchange_rates ORDER BY fetched_at DESC LIMIT 1").fetchone()
    return Rate(row[0], datetime.fromisoformat(row[1])) if row else None


def db_keep(conn: sqlite3.Connection, value: float, now: datetime) -> None:
    conn.execute(
        "INSERT INTO exchange_rates (day, usd_to_nzd, fetched_at, source) VALUES (?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET usd_to_nzd = excluded.usd_to_nzd, fetched_at = excluded.fetched_at",
        (f"{now.astimezone(config.TIMEZONE):%Y-%m-%d}", value, now.isoformat(), SOURCE_NAME),
    )


async def load() -> Rate:
    """At start: take up the last rate that was fetched, if there is one. Never raises."""
    global _rate
    try:
        _rate = await database.run(db_latest)
    except Exception:
        log.exception("Could not read the last exchange rate")
    return current()


def load_from(path) -> Rate:
    """The same, for a process that is not the bot (the self-test's launcher reads live's database). Never raises."""
    global _rate
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            _rate = db_latest(conn)
        finally:
            conn.close()
    except Exception:
        _rate = None
    return current()


# --- fetched --------------------------------------------------------------------------------------------------------------
def read(body: bytes) -> float:
    """The rate in the source's answer. Raises ValueError for one that is missing or not believable."""
    try:
        value = float(json.loads(body)["rates"]["NZD"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"no NZD rate in the answer ({error!r})") from error
    if not SANE[0] <= value <= SANE[1]:
        raise ValueError(f"a rate of {value} is not believable")
    return value


def _get() -> bytes:
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "assistant-bot (personal use)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return answer.read()


async def fetch() -> Rate:
    """Fetch today's rate and keep it. Raises on any failure: the caller says what is used instead."""
    global _rate
    value = read(await asyncio.to_thread(_get))  # off the event loop
    now = clock.real_now()  # money is real: never the dev clock
    await database.run(db_keep, value, now)
    _rate = Rate(value, now)
    return _rate


async def fetch_job(job: scheduler.Job) -> None:
    """Scheduler handler, once a day. A fetch that fails is not a failed job to be told about: the last known rate goes on being used."""
    if config.DEV_DATABASE:
        scheduler.note(job, f"not fetched: the dev bot uses what it has ({said()})")
        return
    try:
        rate = await fetch()
    except Exception as error:
        log.warning("The exchange rate could not be fetched (%r): %s stays in use", error, said())
        scheduler.note(job, f"could not be fetched ({type(error).__name__}): {said()} stays in use")
        return
    scheduler.note(job, f"fetched: US$1 = NZ${rate.value:.4f}")
    log.info("Exchange rate fetched: US$1 = NZ$%.4f", rate.value)


def setup() -> None:
    scheduler.register_handler(JOB_TASK, JOB_KIND, fetch_job, LABEL, housekeeping=True)
    scheduler.default_schedule(JOB_TASK, JOB_KIND, DEFAULT)
