"""The self-test: the dev bot run against real Discord in channels of its own.

Input is simulated (a typed message or a press is handed straight to the bot's
own entry points); output is real (posted, edited and deleted in Discord, then
read back from Discord and checked). `python -m selftest` runs it; see
docs/DEVELOPMENT.md, "The self-test".
"""
