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
    "HUB_CHANNEL_ID": "",
    "KEEP_CONFIRMATIONS": "false",  # the tests check that notes tidy themselves away
}.items():
    os.environ[name] = value
