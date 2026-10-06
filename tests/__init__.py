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
}.items():
    os.environ[name] = value
