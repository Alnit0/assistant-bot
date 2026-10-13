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
    second Discord application, the test bot, which can run beside live. {}
    with no such file, no token in it, or live's own token again."""
    path = base / ".env.dev"
    if not path.exists():
        return {}
    own = {name: (value or "").strip() for name, value in dotenv_values(path).items()}
    live_token = (dotenv_values(base / ".env").get("DISCORD_TOKEN") or "").strip()
    return own if own.get("DISCORD_TOKEN") and own["DISCORD_TOKEN"] != live_token else {}


def not_inherited(now_set: set[str], own: dict[str, str], set_before: set[str]) -> set[str]:
    """The channel settings the test bot must not take from `.env`: a channel
    is its own only when `.env.dev` (or the terminal) names it. Anything else
    would be one of live's channels, and it would answer there too."""
    return {name for name in now_set if name.endswith("_CHANNEL_ID") and name not in set_before and not own.get(name)}


def other_bot_channels(own: dict[str, str], mine: set[int]) -> frozenset[int]:
    """The test bot's channels, as live sees them: not live's to answer in.
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
# This process is the test bot: another Discord account than live's, so the two can run
# at the same time. It has a lock and a log file of its own, and only its own channels
SEPARATE_BOT = DEV_DATABASE and bool(_TEST_BOT)
if SEPARATE_BOT:
    for _name in not_inherited(set(os.environ), _TEST_BOT, _SET_BEFORE):
        os.environ.pop(_name)
LOG_FILE_NAME = "dev-bot.log" if SEPARATE_BOT else "bot.log"
LOG_FILE = LOG_DIR / LOG_FILE_NAME


def test_bot_token() -> str | None:
    """The test bot's token, for the self-test's own calls to Discord. None
    when there is no test bot. Never logged or shown."""
    return _TEST_BOT.get("DISCORD_TOKEN") or None

TOKEN = os.getenv("DISCORD_TOKEN")
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
    sys.exit(f"Missing settings in {'.env.dev (the test bot takes no channel from .env)' if SEPARATE_BOT else '.env'}: {', '.join(missing)}")

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

# Two bots in one server each see everything said in it. The test bot listens only in
# its own channels (and their threads); live listens everywhere but in the test bot's
NOT_MINE: frozenset[int] = frozenset() if DEV_DATABASE else other_bot_channels(_TEST_BOT, set(CHANNELS.values()))


def mine(channel_id: int | None, parent_id: int | None = None) -> bool:
    """Whether what happens in this channel is this bot's to act on."""
    if SEPARATE_BOT:
        own = set(CHANNELS.values())
        return channel_id in own or parent_id in own
    return channel_id not in NOT_MINE and parent_id not in NOT_MINE


# A self-test that had to stop live (there is no test bot) runs as live's own account:
# its status says so, with when live is expected back (core/identity.py)
SELFTEST_BACK = (os.getenv("SELFTEST_BACK") or "").strip() if os.getenv("SELFTEST") == "1" and not SEPARATE_BOT else ""

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
REMINDERS_ENABLED = flag(os.getenv("REMINDERS_ENABLED"), False)
# The briefing (tasks/briefing): one card a day in the hub that says what today holds, kept up
# to date in place, and "brief me". Off unless set: off, nothing of it exists
BRIEFING_ENABLED = flag(os.getenv("BRIEFING_ENABLED"), False)
# Message lifetimes and the tidy that keeps the hub clean (core/messages.py): what is said in
# the hub goes once handled, nothing of a past day stays there, and yesterday's checklist goes
# when today's is posted. Off unless set: off, nothing is recorded and nothing is deleted by it
HUB_TIDY = flag(os.getenv("HUB_TIDY"), False)

# What a day's requests to Claude may cost, in US dollars, before #bot-log is told (once a
# day). Nothing is stopped: it only says so. 0 switches the note off
try:
    DAILY_SPEND_LIMIT = float(os.getenv("DAILY_SPEND_LIMIT") or 0.50)
except ValueError:
    sys.exit("DAILY_SPEND_LIMIT in .env must be a number of US dollars, e.g. 0.50")

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
