import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values, load_dotenv

from core import clock

# ---------------------------------------------------------------------------
# Paths (relative to the project root, so the Windows service works from any folder)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
# `python main.py --dev` runs the same bot on a database of its own, which may
# be filled with test data, wiped (`dev reset-db`) and have its clock moved
# (`dev clock`). The live database is never any of those
DEV_DATABASE = "--dev" in sys.argv[1:]
DEV_DB_NAME = "dev.db"
DB_PATH = DATA_DIR / (DEV_DB_NAME if DEV_DATABASE else "assistant.db")
BACKUP_DIR = DATA_DIR / ("dev-backups" if DEV_DATABASE else "backups")
# How far ahead the dev clock is, so a restart of the dev bot keeps its time
DEV_CLOCK_FILE = DATA_DIR / "dev-clock.json"
# Private spec sheets: gitignored, so the nightly backup is their only copy
SPECS_DIR = BASE_DIR / "docs" / "specs"
# The transcript of each channel that was reset (tasks/channel): in data/, never in
# git, so the nightly backup zips it beside the specs
EXPORTS_DIR = DATA_DIR / "exports"
# Sketches of cards, posted with `dev mock <name>` (tasks/dev/mock.py)
MOCKUPS_DIR = BASE_DIR / "docs" / "mockups"

LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def env_files(dev: bool, base: Path) -> list[Path]:
    """The settings files to read, first wins. With `--dev`, `.env.dev` (if
    there is one) comes before `.env`, so the dev bot can have a token and
    channels of its own and take everything else from `.env`. A value set in
    the terminal beats both."""
    found = [base / ".env"]
    if dev and (base / ".env.dev").exists():
        found.insert(0, base / ".env.dev")
    return found


def test_bot_settings(base: Path) -> dict[str, str]:
    """What `.env.dev` sets, when it gives the dev bot a token of its own: a
    second Discord application, the dev bot, which can run beside live. {}
    with no such file, no token in it, or live's own token again."""
    path = base / ".env.dev"
    if not path.exists():
        return {}
    own = {name: (value or "").strip() for name, value in dotenv_values(path).items()}
    live_token = (dotenv_values(base / ".env").get("DISCORD_TOKEN") or "").strip()
    return own if own.get("DISCORD_TOKEN") and own["DISCORD_TOKEN"] != live_token else {}


def not_inherited(now_set: set[str], own: dict[str, str], set_before: set[str]) -> set[str]:
    """The channel settings the dev bot must not take from `.env`: a channel
    is its own only when `.env.dev` (or the terminal) names it. Anything else
    would be one of live's channels, and it would answer there too."""
    return {name for name in now_set if name.endswith("_CHANNEL_ID") and name not in set_before and not own.get(name)}


def other_bot_channels(own: dict[str, str], mine: set[int]) -> frozenset[int]:
    """The dev bot's channels, as live sees them: not live's to answer in.
    One that is live's own too (a forum both post in) stays live's."""
    theirs = {int(value) for name, value in own.items() if name.endswith("_CHANNEL_ID") and value.isdigit()}
    return frozenset(theirs - mine)


# The first file to set a name keeps it: load_dotenv never overrides what is set
_SET_BEFORE = set(os.environ)
ENV_FILES = env_files(DEV_DATABASE, BASE_DIR)
_TEST_BOT = test_bot_settings(BASE_DIR)
for _env_file in ENV_FILES:
    load_dotenv(_env_file)
DEV_ENV = BASE_DIR / ".env.dev" in ENV_FILES  # the dev bot has settings of its own
def is_test_bot(dev: bool, own: dict[str, str], token: str | None) -> bool:
    """Whether this process is the dev bot. Judged by the token it will
    really log in with, never by what the files say: a token already in the
    environment beats `.env.dev`, and a process that then logged in as live
    while holding the dev bot's lock would run beside live as live (it
    happened, 2026-10-13: the self-test's starts inherited live's token)."""
    return dev and bool(own) and bool(token) and token == own.get("DISCORD_TOKEN")


def clean_environment(environ: dict[str, str], set_before: set[str]) -> dict[str, str]:
    """The environment as it was before any settings file was read: what a
    process started from here must be given, so that it reads the files for
    itself (`.env.dev` first, with `--dev`) instead of inheriting this
    process's values, live's token among them."""
    return {name: value for name, value in environ.items() if name in set_before}


def environment_for_child() -> dict[str, str]:
    return clean_environment(dict(os.environ), _SET_BEFORE)


# This process is the dev bot: another Discord account than live's, so the two can run
# at the same time. It has a lock and a log file of its own, and only its own channels
SEPARATE_BOT = is_test_bot(DEV_DATABASE, _TEST_BOT, os.getenv("DISCORD_TOKEN"))
if SEPARATE_BOT:
    for _name in not_inherited(set(os.environ), _TEST_BOT, _SET_BEFORE):
        os.environ.pop(_name)
LOG_FILE_NAME = "dev-bot.log" if SEPARATE_BOT else "bot.log"
LOG_FILE = LOG_DIR / LOG_FILE_NAME


def test_bot_id() -> int | None:
    """The dev bot's account id (BOT_USER_ID in `.env.dev`), for a process that is not it."""
    value = _TEST_BOT.get("BOT_USER_ID") or ""
    return int(value) if value.isdigit() else None


def test_bot_token() -> str | None:
    """The dev bot's token, for the self-test's own calls to Discord. None
    when there is no dev bot. Never logged or shown."""
    return _TEST_BOT.get("DISCORD_TOKEN") or None

TOKEN = os.getenv("DISCORD_TOKEN")
# The account this start is meant to log in as: live's id in .env, the dev bot's in .env.dev.
# Checked against Discord before the lock is taken (core/account.py). For the dev bot it is
# only ever .env.dev's: live's id from .env would be the wrong answer, and is not taken
_BOT_USER_ID = ((_TEST_BOT.get("BOT_USER_ID") or "") if SEPARATE_BOT else (os.getenv("BOT_USER_ID") or "")).strip()
EXPECTED_BOT_ID = int(_BOT_USER_ID) if _BOT_USER_ID.isdigit() else None
OWNER_ID = os.getenv("OWNER_ID")
INBOX_CHANNEL_ID = os.getenv("INBOX_CHANNEL_ID")
BOT_LOG_CHANNEL_ID = os.getenv("BOT_LOG_CHANNEL_ID")
ARCHIVE_CHANNEL_ID = os.getenv("ARCHIVE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
# What the assistant calls itself, in chat and wherever its name is shown
ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME") or "").strip() or "Hive"

missing = [
    name
    for name, value in {
        "DISCORD_TOKEN": TOKEN,
        "OWNER_ID": OWNER_ID,
        "INBOX_CHANNEL_ID": INBOX_CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }.items()
    if not value
]
if missing:
    sys.exit(f"Missing settings in {'.env.dev (the dev bot takes no channel from .env)' if SEPARATE_BOT else '.env'}: {', '.join(missing)}")

OWNER_ID = int(OWNER_ID)
INBOX_CHANNEL_ID = int(INBOX_CHANNEL_ID)
BOT_LOG_CHANNEL_ID = int(BOT_LOG_CHANNEL_ID) if BOT_LOG_CHANNEL_ID else None
ARCHIVE_CHANNEL_ID = int(ARCHIVE_CHANNEL_ID) if ARCHIVE_CHANNEL_ID else None
# The hub: where the day's regular cards and prompts are posted (pills first)
HUB_CHANNEL_ID = int(os.getenv("HUB_CHANNEL_ID")) if os.getenv("HUB_CHANNEL_ID") else None
# #commands: what the bot can do, written from the task registry and kept up to date
# at start-up (tasks/builtin/commands.py). Only the bot posts there
COMMANDS_CHANNEL_ID = int(os.getenv("COMMANDS_CHANNEL_ID")) if os.getenv("COMMANDS_CHANNEL_ID") else None

# Every channel we know by name, for "where does this work?" rules. Only the
# ones set in .env appear.
CHANNELS: dict[str, int] = {
    name: int(value)
    for name, value in {
        "inbox": os.getenv("INBOX_CHANNEL_ID"),
        "bot-log": os.getenv("BOT_LOG_CHANNEL_ID"),
        "archive": os.getenv("ARCHIVE_CHANNEL_ID"),
        "reminders": os.getenv("REMINDERS_CHANNEL_ID"),
        "gym": os.getenv("GYM_CHANNEL_ID"),
        "admin": os.getenv("ADMIN_CHANNEL_ID"),
        "documents": os.getenv("DOCUMENTS_CHANNEL_ID"),
        "dev": os.getenv("DEV_CHANNEL_ID"),
        # A forum channel: one post per reported bug (tasks/bugs)
        "bugs": os.getenv("BUGS_CHANNEL_ID"),
        "hub": os.getenv("HUB_CHANNEL_ID"),
        "commands": os.getenv("COMMANDS_CHANNEL_ID"),
    }.items()
    if value
}

# Two bots in one server each see everything said in it. The dev bot listens only in
# its own channels (and their threads); live listens everywhere but in the dev bot's
NOT_MINE: frozenset[int] = frozenset() if DEV_DATABASE else other_bot_channels(_TEST_BOT, set(CHANNELS.values()))


def mine(channel_id: int | None, parent_id: int | None = None) -> bool:
    """Whether what happens in this channel is this bot's to act on."""
    if SEPARATE_BOT:
        own = set(CHANNELS.values())
        return channel_id in own or parent_id in own
    return channel_id not in NOT_MINE and parent_id not in NOT_MINE


# A self-test that had to stop live (there is no dev bot) runs as live's own account:
# its status says so, with when live is expected back (core/identity.py)
SELFTEST_BACK = (os.getenv("SELFTEST_BACK") or "").strip() if os.getenv("SELFTEST") == "1" and not SEPARATE_BOT else ""

# The bot's nickname in the server: set by me, used on start (core/identity.py). The dev
# bot's is only ever .env.dev's: it never takes live's name
BOT_NAME = ((_TEST_BOT.get("BOT_NAME") or "") if SEPARATE_BOT else (os.getenv("BOT_NAME") or "")).strip()
# A real state the nickname shows, as "Name · state". There is one: the dev bot while a
# self-test runs. Live keeps its plain name; what it is doing is in its status line
NAME_STATE = "testing" if SEPARATE_BOT and os.getenv("SELFTEST") == "1" else ""


def test_bot_name() -> str:
    """The dev bot's own name (BOT_NAME in `.env.dev`), for a process that is not it."""
    return (_TEST_BOT.get("BOT_NAME") or "").strip()


# How long a "done" confirmation stays in the channel before deleting itself
try:
    CONFIRMATION_SECONDS = float(os.getenv("CONFIRMATION_SECONDS") or 5)
except ValueError:
    sys.exit("CONFIRMATION_SECONDS in .env must be a number of seconds, e.g. 5")

# Leave confirmations and other self-deleting notes in the channel, so what the
# bot did can be read back. On unless switched off
def flag(value: str | None, default: bool) -> bool:
    """An on/off setting as written in .env; empty or missing is the default."""
    value = (value or "").strip().lower()
    return value in ("1", "true", "yes", "on") if value else default


KEEP_CONFIRMATIONS = flag(os.getenv("KEEP_CONFIRMATIONS"), True)

# Pill reminders: a message at each dose's time. Off unless switched on: off, no reminder is ever sent
# Cards drawn as Components V2 (docs/DESIGN.md; core/design.py). Off unless
# set: off, every card looks as it always has
CARDS_V2 = flag(os.getenv("CARDS_V2"), False)
# Which round of the design the cards are drawn in, with CARDS_V2 on (docs/DESIGN-LOG.md): 3, the
# type scale; 1, the look built before it (a box an item). Live changes round only when Alex says so
DESIGN_ROUND = int(os.getenv("DESIGN_ROUND") or 3)
REMINDERS_ENABLED = flag(os.getenv("REMINDERS_ENABLED"), False)
# Three hub tasks, each off unless set (2026-10-15): to-dos (tasks/todos), reminders Alex sets
# himself (tasks/nudges: REMINDERS_ENABLED above is the pills' own) and personal routines
# (tasks/habits: "routine" in code is the scheduler's). Off, the task is not loaded at all
TODOS_ENABLED = flag(os.getenv("TODOS_ENABLED"), False)
NUDGES_ENABLED = flag(os.getenv("NUDGES_ENABLED"), False)
HABITS_ENABLED = flag(os.getenv("HABITS_ENABLED"), False)
# The briefing (tasks/briefing): one card a day in the hub that says what today holds, kept up
# to date in place, and "brief me". Off unless set: off, nothing of it exists
BRIEFING_ENABLED = flag(os.getenv("BRIEFING_ENABLED"), False)
# The day's progress at the top of the briefing: a dot a thing to do and the count
# ("●●●●●○○ 5/7"), and a small line a task ("💊 2/3"). Off unless set: off, the briefing
# reads as it did
DAY_PROGRESS = flag(os.getenv("DAY_PROGRESS"), False)
# Questions about my day answered from what the tasks keep, in words from a template: what is
# left today, how yesterday or the week went (the briefing task), and the weather (the weather
# task). Off unless set: off, neither task offers them
DAY_QUESTIONS = flag(os.getenv("DAY_QUESTIONS"), False)
def hours(text: str | None, default: tuple[time, time]) -> tuple[time, time]:
    """A stretch of the day as written in .env ("22:00-06:00"): (from, to)."""
    try:
        start, end = (part.strip() for part in (text or "").split("-", 1))
        return time.fromisoformat(start), time.fromisoformat(end)
    except ValueError:
        return default


# Quiet hours apply to pings only (the status line is silent): in them only a level 1
# item pings, and the rest waits for the briefing (core/attention.py). Read and shown
# now; used when pings move onto the attention model
QUIET_HOURS = hours(os.getenv("QUIET_HOURS"), (time(22, 0), time(7, 0)))
# Until this time of day a day with everything taken says so on the status line
# ("💊 all 5 taken"); after it the line looks ahead to the morning ("🌅 6am")
try:
    STATUS_DONE_UNTIL = time.fromisoformat((os.getenv("STATUS_DONE_UNTIL") or "20:00").strip())
except ValueError:
    sys.exit("STATUS_DONE_UNTIL in .env must be a time of day on the 24-hour clock, e.g. 20:00")
# Live's own memory use is a problem over this many MB (core/health.py)
try:
    MEMORY_LIMIT_MB = float(os.getenv("MEMORY_LIMIT_MB") or 300)
except ValueError:
    sys.exit("MEMORY_LIMIT_MB in .env must be a number of megabytes, e.g. 300")
# Weather in the briefing (tasks/weather): on unless switched off. Where it is for is
# WEATHER_LAT and WEATHER_LON (never in anything committed, never logged). WEATHER_SOURCE,
# if set, is a file with a recorded forecast read in place of the network (the self-test's)
WEATHER_ENABLED = flag(os.getenv("WEATHER_ENABLED"), True)
try:
    WEATHER_LAT = float(os.getenv("WEATHER_LAT")) if (os.getenv("WEATHER_LAT") or "").strip() else None
    WEATHER_LON = float(os.getenv("WEATHER_LON")) if (os.getenv("WEATHER_LON") or "").strip() else None
except ValueError:
    sys.exit("WEATHER_LAT and WEATHER_LON in .env must be numbers, e.g. -41.29 and 174.78")
WEATHER_SOURCE = (os.getenv("WEATHER_SOURCE") or "").strip()
# Money is shown in NZ$ and recorded in US$ (core/money.py). The rate is fetched once a day;
# until one has been, this is it
try:
    USD_TO_NZD = float(os.getenv("USD_TO_NZD") or 1.70)
except ValueError:
    sys.exit("USD_TO_NZD in .env must be a number, e.g. 1.70")
if USD_TO_NZD <= 0:
    sys.exit("USD_TO_NZD in .env must be more than 0, e.g. 1.70")
# What the self-test may spend on real requests in a calendar month, in NZ dollars. Over
# it, runs use recorded answers only and live says so (core/health.py)
try:
    SELFTEST_MONTHLY_LIMIT_NZD = float(os.getenv("SELFTEST_MONTHLY_LIMIT_NZD") or 3.50)
except ValueError:
    sys.exit("SELFTEST_MONTHLY_LIMIT_NZD in .env must be a number of NZ dollars, e.g. 3.50")
# The weekly pills summary (tasks/pills/history.py): on Sunday evening the week is posted
# in the hub. Off unless switched on
WEEKLY_SUMMARY = flag(os.getenv("WEEKLY_SUMMARY"), False)
# The notify service (core/notify.py). NOTIFY_NTFY: alerts whose kind says so are also
# pushed to the phone through ntfy, to the bot's own topic (NTFY_BOT_TOPIC: a secret, never
# printed or logged). Off, or with no topic, nothing is pushed and Discord notifies as ever
NOTIFY_NTFY = flag(os.getenv("NOTIFY_NTFY"), False)
NTFY_BOT_TOPIC = (os.getenv("NTFY_BOT_TOPIC") or "").strip()
# Quiet hours in force: in QUIET_HOURS an alert is posted without a sound and listed by the
# morning's briefing, unless its kind gets through (a pill reminder: core/notify.py). Off
# unless switched on: off, nothing is held
QUIET_HOURS_ENABLED = flag(os.getenv("QUIET_HOURS_ENABLED"), False)
# Direct messages to live (core/dms.py): with it on, a direct message from the owner is
# read like #inbox, answered silently, and never with a pill's name in a first line
DMS_ENABLED = flag(os.getenv("DMS_ENABLED"), False)
# The nightly self-test (core/nightly.py): at 3:30 am live starts a self-test as the dev
# bot. Off unless switched on
NIGHTLY_SELFTEST = flag(os.getenv("NIGHTLY_SELFTEST"), False)
# Message lifetimes and the tidy that keeps the hub clean (core/messages.py): what is said in
# the hub goes once handled, nothing of a past day stays there, and yesterday's checklist goes
# when today's is posted. Off unless set: off, nothing is recorded and nothing is deleted by it
HUB_TIDY = flag(os.getenv("HUB_TIDY"), False)

# What a day's requests to Claude may cost, in NZ dollars, before I am told (once a day).
# Nothing is stopped: it only says so. 0 switches it off
try:
    DAILY_SPEND_LIMIT_NZD = float(os.getenv("DAILY_SPEND_LIMIT_NZD") or 1.00)
except ValueError:
    sys.exit("DAILY_SPEND_LIMIT_NZD in .env must be a number of NZ dollars, e.g. 1.00")

# Quiet time before reactions are acted on. Removing a reaction within it cancels
try:
    REACTION_DEBOUNCE_SECONDS = float(os.getenv("REACTION_DEBOUNCE") or 30)
except ValueError:
    sys.exit("REACTION_DEBOUNCE in .env must be a number of seconds, e.g. 30")

# Pomodoro: start each phase by itself (true), or wait for Start to be pressed (false)
POMO_AUTO_CONTINUE = (os.getenv("POMO_AUTO_CONTINUE") or "").strip().lower() in ("1", "true", "yes", "on")

def names_in(*values: str | None) -> list[str] | None:
    """The comma-separated names in the first of `values` that has any, or None."""
    for value in values:
        names = [name.strip().lower() for name in (value or "").split(",") if name.strip()]
        if names:
            return names
    return None


# Tasks to load: comma-separated names in .env, or None (empty or missing) for all.
# Tasks were called skills until 2026-10-09: the old setting is still read if the
# new one is empty, so an existing .env goes on working
ENABLED_TASKS = names_in(os.getenv("ENABLED_TASKS"), os.getenv("ENABLED_SKILLS"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TIMEZONE_NAME = "Pacific/Auckland"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
MAX_HISTORY = 10  # number of recent messages (yours and the bot's) sent to Claude
MAX_TOKENS = 1024  # maximum length of each Claude reply
# Whether the action schemas of the router's way are sent to the API as `strict`.
# Off until measured as cheap for the small per-task sets: what comes back is
# checked in code either way (core/actions.py)
STRICT_SCHEMAS = False
CLAUDE_TIMEOUT = 15.0  # seconds one request to Claude may take before it is given up (and retried)
CLAUDE_CONNECT_TIMEOUT = 3.0
CLAUDE_RETRIES = 2  # so the worst case is three attempts
DISCORD_LIMIT = 2000  # Discord's maximum message length
EMBED_FIELD_LIMIT = 1000  # Discord allows 1024 characters per embed field
BUTTON_TIMEOUT = 300  # seconds before test buttons expire
BACKUP_TIME = time(3, 0)  # nightly database backup, NZ local time
BACKUP_KEEP = 7  # number of nightly backups to keep
# When one day ends and the next begins, NZ local time, for every task (core/day.py)
DAY_BOUNDARY = time(0, 0)

# Approximate prices in USD per million tokens: (input, output).
# Check Anthropic's pricing page and update if they change.
MODEL_PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}


clock.configure(shiftable=DEV_DATABASE, store=DEV_CLOCK_FILE)


def now_nz() -> datetime:
    """The time in NZ as the bot sees it: the real time, unless the dev clock
    has been moved (core/clock.py). Use this for anything time-based."""
    return clock.now().astimezone(TIMEZONE)


def real_now_nz() -> datetime:
    """The real time in NZ, whatever the dev clock says: for records of what
    really happened (log cards, message_log, the instance lock)."""
    return clock.real_now().astimezone(TIMEZONE)
