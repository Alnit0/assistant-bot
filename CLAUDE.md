# CLAUDE.md

Guidance for AI assistants working on this repository.

## Project

A personal AI assistant, used through Discord, running 24/7 on a home server
(Windows 11 mini PC). Python bot using discord.py and the Anthropic API, with
SQLite for storage. Single user for now, designed to be multi-user ready.

## Current state

- Entry point: `main.py` (creates the Discord client, wires events, starts the bot)
- `core/` package (shared building blocks; never imports from `skills/`):
  - `config.py`: paths, settings from `.env`, validation, constants, `now_nz()`
  - `logging_setup.py`: terminal and rotating file logging
  - `database.py`: `connect()`, the async `message_log` helpers, and `run()`
  - `migrations.py`: numbered schema migrations (core and skills), applied at startup
  - `context.py`: the `Context` passed to skills (user, channel, reply helpers,
    database access, #bot-log), so skills don't see `discord.Message`
  - `users.py`: the `User` record, `ensure_owner()`, lookup by Discord id
  - `permissions.py`: `is_allowed(user, action)`, the one permission check
  - `backup.py`: nightly database backup and pre-migration snapshots
  - `scheduler.py`: small in-memory scheduler for daily jobs (to be expanded)
  - `debounce.py`: `Debouncer(delay, callback)`, one global quiet-period timer
    that hands over all collected events together
  - `llm.py`: Claude client, system prompt, conversation history, cost estimates
  - `discord_utils.py`: #bot-log embeds, `split_message`, `truncate`
- `skills/` package (stage 3; see "How to add a skill" in `docs/DEVELOPMENT.md`):
  - `base.py`: the `Skill` base class with its hooks (`commands`, `tools`, `jobs`,
    `migrations`, `reactions`) and the `Command` / `Tool` / `Reaction` records
  - `registry.py`: discovers the packages in `skills/`, loads the enabled ones at
    startup, dispatches commands and checks `is_allowed` for each
  - `builtin/`: the first skill (ping, reset, buttons, stats, help). `help` lists
    the commands of every loaded skill
  - `lab/`: test bench for Discord features behind `/lab` slash commands
    (owner only), plus an "Archive message" context menu and 📦 reaction. The
    one skill allowed to use discord.py directly. See "Lab commands" in
    `docs/DEVELOPMENT.md`
  - Hooks wired so far: `commands`, `migrations`, `jobs`, `reactions`,
    `app_commands` (slash commands and context menus), `events`, `setup`
    (before connecting: persistent views) and `startup` (once ready).
    `tools()` is declared but nothing calls it yet
  - Buttons, selects and forms must be answered first, logged second.
    `on_interaction` in `main.py` logs and reports any left unanswered after
    2 seconds. Known users are cached in `core/users.py`, so permission
    checks don't wait on the database
  - Slash commands live in an `app_commands.CommandTree` in `main.py` and are
    synced at startup to the server the inbox channel is in
  - Commands match the whole message exactly; anything else goes to Claude
  - `ENABLED_SKILLS` in `.env` picks which skills load (empty = all). A skill that
    fails to load is skipped and reported at startup, not fatal
  - The Claude chat path is still in `main.py` and still uses `discord.Message`;
    `builtin` still uses a `discord.ui.View` for its buttons (gateway stage)
- Runs as a Windows service via NSSM, named `assistant-bot`
- Logs: `logs/bot.log` (rotating), `logs/service-*.log` (service output)
- Database: `data/assistant.db`
  - Tables: `users`, `message_log` (records every input, with a `user_id`),
    `skill_migrations`, and `lab_state` (the lab skill's own key/value table)
  - Schema version is `PRAGMA user_version`. To change the schema, append a
    function to `MIGRATIONS` in `core/migrations.py`; never edit an old one
  - Skills keep their own migration lists (`Skill.migrations()`), tracked per
    skill in the `skill_migrations` table. Skill tables are prefixed with the
    skill's name
  - Database calls from the event loop are `async` (run in a worker thread
    with `asyncio.to_thread`, one connection per call). Always `await` them
- Backups: `data/backups/`, nightly at 3am NZ time, newest 7 kept
  (`assistant-*.db`). `pre-migration-*.db` snapshots are never auto-deleted
- Permissions: only the owner (`OWNER_ID`, role `owner`) is allowed anything.
  Check with `is_allowed`, never by comparing against `OWNER_ID`
- Discord channels: #inbox (main), #bot-log (activity cards), #archive
  (`ARCHIVE_CHANNEL_ID`, optional), plus reserved channels for future skills
  (#reminders, #gym, #admin, #documents)

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