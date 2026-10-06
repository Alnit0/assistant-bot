# CLAUDE.md

Guidance for AI assistants working on this repository.

## Project

A personal AI assistant, used through Discord, running 24/7 on a home server
(Windows 11 mini PC). Python bot using discord.py and the Anthropic API, with
SQLite for storage. Single user for now, designed to be multi-user ready.

## Current state

- Entry point: `main.py` (creates the Discord client, wires events, starts the bot)
- `core/` package (stage 1 of the refactor; `skills/` is still planned):
  - `config.py`: paths, settings from `.env`, validation, constants, `now_nz()`
  - `logging_setup.py`: terminal and rotating file logging
  - `database.py`: SQLite setup and the `message_log` helpers
  - `llm.py`: Claude client, system prompt, conversation history, cost estimates
  - `discord_utils.py`: #bot-log embeds, `split_message`, `truncate`
  - `views.py`: the `TestButtons` view
  - `commands.py`: ping, reset, buttons, stats, help
- Runs as a Windows service via NSSM, named `assistant-bot`
- Logs: `logs/bot.log` (rotating), `logs/service-*.log` (service output)
- Database: `data/assistant.db` (`message_log` table records every input)
- Discord channels: #inbox (main), #bot-log (activity cards), plus reserved
  channels for future skills (#reminders, #gym, #admin, #documents)

## Planned architecture

- `core/`: config, database and migrations, Claude client and tool loop,
  Discord gateway, scheduler, confirmations, logging
- `skills/`: self-contained features that register tools, commands,
  scheduled jobs and database tables with the core
- Skills never call Discord directly; they go through the gateway
- Every record has a `user_id`; permissions go through one central check

## Conventions

- Python 3.14, virtual environment in `.venv/`
- Windows paths and PowerShell commands (the server runs Windows)
- UK spelling in all user-facing text and docs
- Keep bot replies short and mobile-friendly
- Claude interprets language; code does date and time maths
- Times: moments stored in UTC; schedules stored as local time + `Pacific/Auckland`
- Log raw input before processing it
- Anything outward-facing (sending emails, deleting data) needs user confirmation
- Never block the async event loop with slow synchronous work

## Secrets and data

- All secrets live in `.env` (gitignored). Never hardcode or print them
- When adding a setting, add a placeholder to `.env.example` too
- Never commit `.env`, `data/`, `logs/` or `.venv/`

## Workflow

- See `docs/DEVELOPMENT.md` for commands and the day-to-day workflow
- See `docs/DECISIONS.md` before changing architecture or tools
- Commit messages: short, present tense, describing what and why