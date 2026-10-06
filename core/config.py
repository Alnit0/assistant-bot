import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths (relative to the project root, so the Windows service works from any folder)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "assistant.db"
BACKUP_DIR = DATA_DIR / "backups"

LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
INBOX_CHANNEL_ID = os.getenv("INBOX_CHANNEL_ID")
BOT_LOG_CHANNEL_ID = os.getenv("BOT_LOG_CHANNEL_ID")
ARCHIVE_CHANNEL_ID = os.getenv("ARCHIVE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

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
    sys.exit(f"Missing settings in .env: {', '.join(missing)}")

OWNER_ID = int(OWNER_ID)
INBOX_CHANNEL_ID = int(INBOX_CHANNEL_ID)
BOT_LOG_CHANNEL_ID = int(BOT_LOG_CHANNEL_ID) if BOT_LOG_CHANNEL_ID else None
ARCHIVE_CHANNEL_ID = int(ARCHIVE_CHANNEL_ID) if ARCHIVE_CHANNEL_ID else None

# Skills to load: comma-separated names in .env, or None (empty or missing) for all
ENABLED_SKILLS = [
    name.strip().lower() for name in os.getenv("ENABLED_SKILLS", "").split(",") if name.strip()
] or None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TIMEZONE_NAME = "Pacific/Auckland"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
MAX_HISTORY = 10  # number of recent messages (yours and the bot's) sent to Claude
MAX_TOKENS = 1024  # maximum length of each Claude reply
DISCORD_LIMIT = 2000  # Discord's maximum message length
EMBED_FIELD_LIMIT = 1000  # Discord allows 1024 characters per embed field
BUTTON_TIMEOUT = 300  # seconds before test buttons expire
BACKUP_TIME = time(3, 0)  # nightly database backup, NZ local time
BACKUP_KEEP = 7  # number of nightly backups to keep

# Approximate prices in USD per million tokens: (input, output).
# Check Anthropic's pricing page and update if they change.
MODEL_PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}


def now_nz() -> datetime:
    return datetime.now(TIMEZONE)
