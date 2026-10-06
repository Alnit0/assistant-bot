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
    that hands over all collected events together. `delay` may be a function
  - `devmode.py`: dev mode's in-memory state (off after a restart). Other code
    asks it for values and gets the normal one when it is off:
    `reaction_debounce()`, `speed()`, `real_seconds()`, `is_verbose()`,
    `quiet_hours_ignored()`. `await devmode.debug(title, lines)` posts a debug
    card to #bot-log only when verbose is on; `register_task(name, fn)` makes
    a background task runnable with `dev run <name>`
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
    `REACTION_DEBOUNCE` seconds of quiet (`.env`, default 30). The registry
    compares where the owner's reactions ended up with what is applied
    (`core/reactions.py`, table `reaction_state`): it applies new ones and
    adds ✅, and runs `undo` and removes ✅ when one is taken away. A failure
    adds ⚠️ with details in #bot-log. `destructive=True` reactions (📦, 🗑️)
    leave nothing to mark or undo
  - `core/protection.py` says whether a message is pinned or 📌-marked;
    `core/confirmations.py` asks before acting on one (Confirm / Cancel,
    two-minute timeout, held in memory)
  - The core deletes every "pinned a message" notice (`main.py`)
  - `keep/`: the 📌 reaction. Keeping pins the message natively; removing the
    owner's 📌 unpins it (`undo`), whoever pinned it. The 📌 itself is what
    protects it. Pins go through `core/pins.py` (`set_pinned`), so the skill
    makes no Discord calls; the wording of a refusal (pin limit, message
    gone, no permission) is `pin_problem` in `core/protection.py`. A refused
    pin is a `UserError`, so the message gets ⚠️ and is not recorded as applied
  - `builtin/`: ping, reset (clear, clear chat, wipe), buttons, stats (stat),
    and `help [skill or word]`, which is generated from the registry at request
    time and filtered by enabled skills, channel and permission
  - `archive/`: reply `archive` / `delete`, the 📦 and 🗑️ reactions and the
    "Archive message" context menu. The rules (what may be archived or
    deleted, names, embeds, wording) are in `rules.py` and the records in
    `store.py`, both without Discord calls; `messages.py` does the Discord work. Reposts through a webhook, then deletes;
    every way in asks first if the message is protected. Archived copies
    carry a persistent Restore button (`archive_items` table) that reposts
    to the original channel and removes the copy
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
  - `dev/`: dev mode's words (all start with `dev`, typed only, permission
    `dev`), its pinned panel with persistent buttons (`dev:panel:*`), the
    "🛠️ Dev mode" status and the tools (`dev inspect` as a reply, `dev jobs`,
    `dev run`, `dev fire next`, `dev seed`, `dev clean`). Uses discord.py
    directly, like `lab`, `archive` and `timers`. Quiet hours, the sweep and
    the summary don't exist yet, so `dev quiet` changes nothing and `dev run
    sweep|summary` report "not built". See "Dev mode" in `docs/DEVELOPMENT.md`
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
    `lab_tour_runs` and `lab_tour_results`, `scheduled_jobs`, `reaction_state`,
    the archive skill's `archive_items`, and the timers
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
- Unit tests live in `tests/` and run with `python -m pytest` (pytest is in
  `requirements-dev.txt`). New tests are plain pytest functions; the older
  `unittest` classes stay as they are and pytest runs them too. Fixtures are
  in `tests/conftest.py` (`make_db`, `db`, `dev_off`, `owner`, `stranger`).
  Tests use a temporary database and made-up settings, never the real ones
- Keep decisions apart from Discord calls so they can be unit tested: put
  the logic in a module that doesn't call Discord (as `core/reactions.py`,
  `core/protection.py`, `skills/archive/rules.py` and `store.py`,
  `skills/timers/durations.py` and `pomodoro.py` do) and have the
  Discord-facing code call it. New logic needs tests in the same change
- Run `python -m pytest` before suggesting a commit, and report the result
  (passed, failed and skipped counts, and any failure) in the end-of-task
  summary. Don't suggest a commit over a failing run without saying so
- Tests are tracked in `docs/TESTING.md` (grouped by feature, each with an
  ID such as A1, a type, a status and a summary table at the top). 🤖 Auto
  rows are logic covered by pytest; 👤 Manual rows are only for
  Discord-facing behaviour:
  - New features add their tests to `docs/TESTING.md`: 🤖 rows for the logic,
    👤 rows as ⬜ Untested
  - When a change affects an existing feature, reset its 👤 tests to
    ⬜ Untested, and set its 🤖 rows from the pytest run
  - When I report results (e.g. "A1 pass, A2 fail: reason"), update the
    table (status, date, notes) and the summary, and copy failures into
    `docs/BACKLOG.md` (create it if it doesn't exist)

- At the end of every task, finish with the suggested commit as ONE
  ready-to-paste PowerShell command in a code block:
  - Title: short, present tense, under 50 characters
  - Body: 2 to 4 bullet points on what changed and why, each on its
    own line
  - Title and body as two -m arguments, each in single quotes; escape
    any apostrophe by doubling it ('')
  - Then "git push" on its own line
  Example:

      git commit -m 'Add dev mode and test tracker' -m '- Add dev mode with a pinned panel and inspection tools
      - Split archive logic into testable modules
      - Add docs/TESTING.md with Auto and Manual tests'
      git push

  Do not commit unless asked.

## Interaction rules (apply to every skill)

Input
- Typed plain words are the main way in; no slash needed. Unmatched
  messages go to Claude. Slash commands are a hidden fallback only.
- Replying to a message with an action word (archive, keep, save,
  delete, remind <when>) applies it to that message.
- Help is generated from the registry; every keyword, reply action and
  reaction must have a description, examples, channels and permission.

Reactions
- Only the owner's reactions count; the bot ignores its own.
- Every reaction action is reversible: removing the reaction undoes it.
  Destructive actions (archive, delete) are reversible only within the
  debounce window. After that, archived copies carry a persistent
  "Restore" button that reposts to the original channel.
- Reaction actions are debounced globally (REACTION_DEBOUNCE, default
  30s); the bot acts once on the final state of MY reactions compared
  with what was last applied, then adds ✅. When nothing is active on a
  message, the ✅ is removed.
- Archive and delete (by reply, reaction or menu) ask for confirmation
  if the message is pinned, 📌-reacted or saved.
- A failed reaction action adds ⚠️ to the message, with details in
  #bot-log; no temporary notes in the channel.
- Everything else (messages, buttons, jobs) acts immediately.

Cleanliness
- Edit messages in place rather than posting new ones. Exception:
  anything that must notify me (timer done, Pomodoro phase changes,
  reminders) posts a new message; that alert is deleted once
  acknowledged (button or reply), and the original is updated.
- On success, delete the user's command or reply message and show a
  brief confirmation that deletes itself; on failure, keep it and add ⚠️.
- Pinned or 📌-reacted messages are exempt from cleanup and sweeps.
- Delete Discord's "pinned a message" system notices.
- Lab skill tests are exempt from these cleanup rules.

Notifications
- Levels: silent, normal, urgent (@mention in channel), critical (DM).
- DMs only for critical alerts and ignored high-priority nudges; they
  are short pointers with a jump link back into the server.
- Quiet hours hold non-critical alerts; repeats are grouped.

Interactions
- Acknowledge every interaction within 3 seconds (defer first if slow).
- Persistent buttons use stable custom_ids and survive restarts.
- Error handlers check whether the interaction was already answered.


