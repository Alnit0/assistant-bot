"""Unit tests. Run from the project root: python -m unittest discover tests

They never start the bot, never talk to Discord or Claude, and never touch
data/assistant.db: anything that needs a database gets a temporary one.
"""
import logging
import os

# Tests provoke errors on purpose; keep the bot's own logging out of the results
logging.disable(logging.CRITICAL)

# core/config.py insists on these being set. Tests must not use the real ones,
# and values already in the environment win over .env.
for name, value in {
    "DISCORD_TOKEN": "test-token",
    "OWNER_ID": "1",
    "INBOX_CHANNEL_ID": "100",
    "BOT_LOG_CHANNEL_ID": "",
    "ANTHROPIC_API_KEY": "test-key",
    # Optional settings too, so a test never passes or fails because of the real .env
    "CLAUDE_MODEL": "claude-haiku-4-5",
    "ASSISTANT_NAME": "",
    "ENABLED_TASKS": "",
    "ENABLED_SKILLS": "",  # the old name, still read as a fallback
    "CONFIRMATION_SECONDS": "",
    "REACTION_DEBOUNCE": "",
    "POMO_AUTO_CONTINUE": "",
    "ARCHIVE_CHANNEL_ID": "200",
    "REMINDERS_CHANNEL_ID": "",
    "GYM_CHANNEL_ID": "",
    "ADMIN_CHANNEL_ID": "",
    "DOCUMENTS_CHANNEL_ID": "",
    "DEV_CHANNEL_ID": "",
    "BUGS_CHANNEL_ID": "300",
    "HUB_CHANNEL_ID": "400",
    "COMMANDS_CHANNEL_ID": "",
    "KEEP_CONFIRMATIONS": "false",  # the tests check that notes tidy themselves away
    "DAILY_SPEND_LIMIT_NZD": "0.50",
    "SELFTEST_MONTHLY_LIMIT_NZD": "2",
    "WEATHER_ENABLED": "false",  # on by default: the weather tests switch it on
    "WEATHER_LAT": "",
    "WEATHER_LON": "",
    "WEATHER_SOURCE": "",
    "USD_TO_NZD": "1",  # one for one, so the amounts in the tests read the same: tests/test_money.py has the real sums
    "CARDS_V2": "",  # off, as it is unless set: the design tests switch it on
    "REMINDERS_ENABLED": "",  # off, as it is unless set: the reminder tests switch it on
    # Every other switch too: off, whatever this PC's own .env has turned on (tests/test_settings.py)
    "BRIEFING_ENABLED": "",
    "DAY_PROGRESS": "",
    "WEEKLY_SUMMARY": "",
    "DMS_ENABLED": "",
    "NIGHTLY_SELFTEST": "",
    "HUB_TIDY": "",
    "QUIET_HOURS_ENABLED": "",
    "QUIET_HOURS": "",
    "NOTIFY_NTFY": "",
    "NTFY_BOT_TOPIC": "",
}.items():
    os.environ[name] = value
