# CLAUDE.md

Guidance for AI assistants working on this repository.

## Project

A personal AI assistant, used through Discord, running 24/7 on a home server
(Windows 11 mini PC). Python bot using discord.py and the Anthropic API, with
SQLite for storage. Single user for now, designed to be multi-user ready.

## Current state

- Entry point: `main.py` (creates the Discord client, wires events, starts the bot)
- `core/` package (shared building blocks; never imports from `skills/`):
  - `config.py`: paths, settings from `.env`, validation, constants, the
    `CHANNELS` name-to-id map, `now_nz()`
  - `logging_setup.py`: terminal and rotating file logging
  - `database.py`: `connect()`, the async `message_log` helpers, and `run()`
  - `migrations.py`: numbered schema migrations (core and skills), applied at startup
  - `context.py`: the `Context` passed to skills (user, channel, arguments, reply
    helpers, database access, #bot-log), so skills don't see `discord.Message`
  - `router.py`: matches typed words and phrases, with typo tolerance
  - `interactions.py`: permission check and logging for slash commands and menus
  - `errors.py`: `UserError`
  - `users.py`: the `User` record, `ensure_owner()`, lookup by Discord id
  - `permissions.py`: `is_allowed(user, action)`, the one permission check
  - `backup.py`: nightly database backup and pre-migration snapshots
  - `scheduler.py`: database-backed scheduler. Jobs live in `scheduled_jobs`
    (due moments in UTC); a ticker runs due ones every 15 seconds and wakes
    exactly for the next one. Skills book jobs with `add_job` and provide
    `job_handlers()`. Jobs missed while offline run at startup with
    `job.is_late`. The nightly backup is a job that books its own successor
  - `debounce.py`: `Debouncer(delay, callback)`, one global quiet-period timer
    that hands over all collected events together
  - `instance_lock.py`: the single-instance lock, taken first thing at startup
  - `llm.py`: Claude client, system prompt (with the registry's capability list
    passed in by `main.py`), conversation history, cost estimates
  - `discord_utils.py`: #bot-log embeds, `split_message`, `truncate`
- `skills/` package (see "How to talk to the bot" and "How to add a skill" in
  `docs/DEVELOPMENT.md`):
  - How the user reaches a skill, in order of preference: a **word** typed on
    its own (`stats`, `lab chart 30`), a **reply action** (reply to a message
    with `archive` or `delete`), a **reaction** (📦). Slash commands and
    context menus stay registered as a fallback only
  - `base.py`: the `Skill` base class and the self-describing records
    `Keyword`, `ReplyAction` and `Reaction`. Every registration needs a
    `description`; it also carries `examples`, `channels` and `permission`. A
    missing description is reported in #bot-log at startup
  - `registry.py`: discovers the packages in `skills/`, loads the enabled ones,
    dispatches words, reply actions and reactions (channel and `is_allowed`
    checks, logging), and is the single source of what the bot can do:
    `catalogue()`, `find()` and `capabilities_text()` feed `help` and Claude's
    system prompt. Never hard-code a list of commands anywhere
  - `core/router.py` matches words: the whole message must be the phrase
    (extra words only with `takes_args`); one-letter typos are forgiven in
    words of 5+ letters unless the registration is `exact` (use `exact` for
    anything destructive). Everything else in #inbox goes to Claude
  - Keywords default to #inbox; reply actions and reactions to any channel.
    Chat with Claude only happens in #inbox
  - Reactions are acted on through one core `Debouncer` after
    `REACTION_DEBOUNCE_SECONDS` (15) of quiet; removing the reaction in time
    cancels it
  - `builtin/`: ping, reset (clear, clear chat, wipe), buttons, stats (stat),
    and `help [skill or word]`, which is generated from the registry at request
    time and filtered by enabled skills, channel and permission
  - `archive/`: reply `archive` / `delete`, the 📦 reaction and the "Archive
    message" context menu. Reposts through a webhook, then deletes
  - `lab/`: test bench for Discord features. Each command is one `run_*`
    function reached by a typed word (`lab chart`) and by `/lab chart`
    through the `Run` adapters in `skills/lab/common.py`. See "Lab commands"
    in `docs/DEVELOPMENT.md`
  - `lab` and `archive` are the only skills allowed to use discord.py
    directly (`ctx.channel`, `ctx.author`, raw messages); that goes behind the
    gateway layer later
  - The registry decides how every word and reply action ends. Success: the
    user's command message is deleted (unless `keep_command=True`); lasting
    output uses `ctx.reply`, a "done" uses `ctx.confirm`, which deletes itself
    after `CONFIRMATION_SECONDS` (`.env`, default 5). Failure: the message
    stays and gets a ⚠️ reaction; details go to #bot-log, never the channel
  - Raise `UserError` (`core/errors.py`) for problems the user can fix; its
    message goes on the #bot-log card
  - The registry emits `action_finished` (a `registry.ActionResult`) to skills
    after every word, reply action, reaction and chat, and
    `registry.expect_message(...)` lets a skill claim a user's next message
    in a channel (after words and reply actions, before Claude)
  - Claude's conversation history is one list per channel
    (`llm.history_for(channel_id)`); `reset` clears only the channel it is
    typed in. Claude still only chats in #inbox
  - `lab tour` (guided, resumable test run) and `lab channels` (cross-channel
    notification test) are typed only, with no slash command
  - `timers/`: short timers and Pomodoro, typed only (`timer`, `timers`,
    `pomo`, `pomo stats`; reply `cancel`, `pause`, `resume`, `+10m`). Pure
    logic is in `durations.py` and `pomodoro.py` (unit-tested); all state is in
    the database; one pinned "Active timers" board per channel. Uses
    discord.py directly for cards and buttons, like `lab` and `archive`. See
    "Timers and Pomodoro" in `docs/DEVELOPMENT.md`
  - Reply actions can have a `pattern` (for `+10m`) and an `applies_to` check
    (so `cancel` only acts on timer messages). Arguments keep their capitals
  - Hooks wired: `keywords`, `reply_actions`, `reactions`, `migrations`,
    `jobs`, `app_commands`, `events`, `setup` (before connecting: persistent
    views) and `startup` (once ready). `tools()` is declared but nothing calls
    it yet
  - Slash commands and menus are logged by `core/interactions.py`
    (`check_allowed`, `begin`, then `finish` / `fail` from `main.py`). They
    live in an `app_commands.CommandTree` in `main.py`, synced at startup to
    the server the inbox channel is in
  - Buttons, selects and forms must be answered first, logged second.
    `on_interaction` in `main.py` logs and reports any left unanswered after
    2 seconds. User lookups are cached in `core/users.py` (including "not one
    of ours"), so permission checks don't wait on the database
  - Reply from error handlers with `safe_reply` and report failures with
    `report_interaction_error` (both in `core/discord_utils.py`): they never
    raise, and treat Discord codes 10062 and 40060 as a warning, not an error
  - `ENABLED_SKILLS` in `.env` picks which skills load (empty = all). A skill that
    fails to load is skipped and reported at startup, not fatal
  - The Claude chat path is still in `main.py` and still uses `discord.Message`;
    `builtin` still uses a `discord.ui.View` for its buttons (gateway stage)
- Runs as a Windows service via NSSM, named `assistant-bot`
- Logs: `logs/bot.log` (rotating), `logs/service-*.log` (service output)
- Database: `data/assistant.db`
  - Tables: `users`, `message_log` (records every input, with a `user_id`),
    `skill_migrations`, and the lab skill's own `lab_state` (key/value),
    `lab_tour_runs` and `lab_tour_results`, `scheduled_jobs`, and the timers
    skill's `timers_timers`, `timers_pomodoros`, `timers_focus_log` and
    `timers_boards`
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
- `skills/`: self-contained features that register tools, words, reply actions,
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
- Notifications stay in the server. Urgent items @mention the user in their
  own channel. DMs are only for critical alerts and for escalating a
  high-priority nudge that was ignored, and are short pointers with a jump
  link to the server message: no content, buttons or actions in DMs

## Secrets and data

- All secrets live in `.env` (gitignored). Never hardcode or print them
- When adding a setting, add a placeholder to `.env.example` too
- Never commit `.env`, `data/`, `logs/` or `.venv/`

## Workflow

- See `docs/DEVELOPMENT.md` for commands and the day-to-day workflow
- See `docs/DECISIONS.md` before changing architecture or tools
- Commit messages: short, present tense, describing what and why
- Only one copy of the bot may run at a time. `core/instance_lock.py` enforces
  it with a lock on `data/bot.lock`; a second copy logs an error and exits
- When testing, never leave a bot process running in the background after you
  finish. Stop anything you started and confirm nothing is left:
  `Get-CimInstance Win32_Process -Filter "Name like 'python%'"`. One running
  bot shows as two `python.exe` processes (the `.venv` launcher and its child)
- Prefer checks that import the code without starting the bot. Never start
  `main.py` while the user's own copy or the service is running
- Unit tests live in `tests/` (standard `unittest`): run `python -m unittest`.
  Put logic that can be tested without Discord in pure modules (as
  `skills/timers/durations.py` and `pomodoro.py` do) and add tests with it.
  Tests use a temporary database and made-up settings, never the real ones