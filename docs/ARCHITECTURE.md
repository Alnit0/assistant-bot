# Architecture map

Where everything is and how input flows through it. Read this before
exploring the code. **Update it in the same change whenever a file is added,
moved, renamed or changes what it is responsible for.**

For how to use the bot and each skill in detail, see `docs/DEVELOPMENT.md`;
for why things are the way they are, `docs/DECISIONS.md`.

## Top level

| Path | Responsibility |
|---|---|
| `main.py` | Entry point: creates the Discord client, wires Discord events to the registry, holds the Claude chat path and the slash command tree |
| `core/` | Shared building blocks. Never imports from `skills/` |
| `skills/` | One folder per feature, loaded by `skills/registry.py` |
| `tests/` | Unit tests (pytest); never start the bot or touch real data |
| `docs/` | `ARCHITECTURE` (this), `DEVELOPMENT` (how to use and extend), `DECISIONS` (why), `TESTING` (test tracker), `QA-RUN` (manual run sheet), `CHANGELOG` (what changed, by date), `CHEATSHEET` (commands) |
| `.claude/skills/` | Procedures for Claude Code: `add-skill`, `qa`, `end-of-task` |
| `.env`, `.env.example` | Secrets and settings (`.env` is gitignored); every setting has a placeholder in `.env.example` |
| `data/` | `assistant.db`, `bot.lock`, `backups/` (gitignored) |
| `logs/` | `bot.log` (rotating), `service-*.log` (gitignored) |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini` | Dependencies (dev adds pytest) and test settings |

## `core/`

| File | Responsibility |
|---|---|
| `config.py` | Paths, settings from `.env` and their validation, constants, the `CHANNELS` name-to-id map, `now_nz()` |
| `logging_setup.py` | Terminal and rotating file logging |
| `instance_lock.py` | Single-instance lock on `data/bot.lock`, taken first thing at startup |
| `database.py` | `connect()`, the async `message_log` helpers (`log_received`, `log_result`), `run(func)` in a worker thread |
| `migrations.py` | Numbered schema migrations, core and per skill, applied at startup |
| `backup.py` | Nightly backup (a scheduler job that books its successor) and pre-migration snapshots |
| `users.py` | The `User` record, `ensure_owner()`, cached lookup by Discord id |
| `permissions.py` | `is_allowed(user, action)`: the one permission check |
| `errors.py` | `UserError`: a problem the user can fix |
| `context.py` | `Context` handed to skills: user, channel, args, `reply` / `confirm` / `note`, database, #bot-log |
| `router.py` | Matches typed words and phrases, with typo tolerance |
| `reactions.py` | Pure: which reaction changes count, where they ended up, what to apply or undo; the `reaction_state` queries |
| `debounce.py` | `Debouncer(delay, callback)`: one quiet-period timer that hands over all collected events together |
| `protection.py` | Pure: is a message protected (pinned or 📌), is it kept, and the wording when Discord refuses a pin |
| `pins.py` | `set_pinned(...)`: native pin and unpin for skills that may not call Discord |
| `confirmations.py` | Confirm / Cancel question before acting on a protected message (in memory, two-minute timeout) |
| `scheduler.py` | Database-backed jobs: `add_job`, a ticker that runs due ones, catch-up at startup (`job.is_late`) |
| `devmode.py` | Dev mode's in-memory state; other code asks it for values (`reaction_debounce()`, `speed()`, `is_verbose()`, `debug()`, `register_task()`) |
| `interactions.py` | Permission check and logging for slash commands and context menus |
| `llm.py` | Claude client, system prompt (with the registry's capability list), per-channel history, cost estimates |
| `discord_utils.py` | #bot-log cards, `split_message`, `truncate`, `safe_reply`, `report_interaction_error` |

## `skills/`

| Path | Responsibility |
|---|---|
| `base.py` | The `Skill` base class with its hooks, and the self-describing `Keyword`, `ReplyAction`, `Reaction` records |
| `registry.py` | Discovers and loads skills; dispatches words, reply actions and reactions; decides how each ends; the single source of what the bot can do (`catalogue()`, `find()`, `capabilities_text()`) |
| `builtin/__init__.py` | `ping`, `reset`, `buttons`, `stats`, and `help` generated from the registry |
| `builtin/views.py` | The `buttons` test view |
| `archive/__init__.py` | Registers reply `archive` / `delete`, the 📦 and 🗑️ reactions, the context menu |
| `archive/rules.py` | Pure: what may be archived or deleted, names, embeds, wording |
| `archive/store.py` | The `archive_items` records |
| `archive/messages.py` | The Discord work: webhook repost, delete, confirmation, Restore button |
| `keep/__init__.py` | The 📌 reaction: keep (pin) and unkeep (unpin), through `core/pins.py` |
| `timers/__init__.py` | Registers `timer`, `timers`, `pomo`, `pomo stats`, the reply actions and job handlers |
| `timers/durations.py`, `pomodoro.py` | Pure: duration parsing; Pomodoro phases, pause arithmetic, stats |
| `timers/store.py` | Everything timers remember (`timers_*` tables) |
| `timers/timers.py`, `sessions.py`, `board.py`, `common.py` | Timer messages, Pomodoro session cards, the pinned "Active timers" board, shared message helpers |
| `dev/__init__.py` | Registers the `dev …` words |
| `dev/panel.py` | The pinned dev panel, its persistent buttons, the "🛠️ Dev mode" status |
| `dev/tools.py` | `dev inspect`, `dev jobs`, `dev run`, `dev fire next`, `dev seed`, `dev clean` |
| `lab/__init__.py`, `common.py` | The `lab …` test bench; `common.py` has the `Run` adapters that let one `run_*` function serve a typed word and `/lab` |
| `lab/buttons.py`, `react.py`, `status.py`, `charts.py`, `data.py`, `misc.py`, `channels.py`, `tour.py`, `state.py`, `ratelimits.py` | One Discord feature each: components, reaction timeline, pinned status, charts and their data, notifications / polls / formatting, cross-channel test, the guided tour, the lab's key/value table, rate-limit watching |

Only `lab`, `archive`, `timers` and `dev` use discord.py directly; that
moves behind a gateway layer later. Other skills go through `Context` and
core helpers.

## `tests/`

`conftest.py` has the fixtures (`make_db`, `db`, `dev_off`, `owner`,
`stranger`); `helpers.py` has `DatabaseTestCase`; `__init__.py` sets made-up
settings before `core` loads. One `test_*.py` per area: `router`,
`registry` (loading, help, capabilities), `reactions`, `reaction_keys`,
`debounce`, `keep`, `archive_rules`, `archive_store`, `durations`,
`pomodoro`, `timer_text`, `devmode`, `dev_parsing`, `lab`, `permissions`,
`scheduler`, `text`.

## Data flows

**Startup** (`main.py`): logging → `instance_lock.acquire()` →
`registry.load()` → `migrate(registry.skill_migrations())` →
`ensure_owner()` → connect. `setup_hook` runs each skill's `setup`
(persistent views); `on_ready` syncs slash commands, runs each skill's
`startup`, books the backup and starts the scheduler.

**Message → router → skill**

1. `main.on_message`: deletes "pinned a message" notices; ignores bots and
   anyone `is_allowed(user, "message")` refuses; builds a `Context`.
2. `registry.dispatch_reply_action` (only if the message is a reply), then
   `registry.dispatch_keyword`: `core/router.py` matches the whole message;
   the registration's channel is checked.
3. `registry._run`: logs the raw input (`message_log`), checks
   `is_allowed`, calls the handler, records the result, posts the #bot-log
   card. Success deletes the user's message and shows a self-deleting
   confirmation; failure leaves it with ⚠️ and puts the reason in #bot-log.
4. If neither matched: `registry.dispatch_expected` (a skill waiting for
   this user's next message), then, in #inbox only, Claude (`core/llm.py`).
5. Every outcome is emitted to skills as `action_finished`.

**Reaction → debouncer → actions**

1. `main.on_raw_reaction_add` / `remove` (never the bot's own) →
   `registry.reaction_changed`, which feeds the one `Debouncer` if the
   emoji is registered.
2. After `REACTION_DEBOUNCE` of quiet (or dev mode's value),
   `registry._reactions_quiet` uses `core/reactions.py` to keep only
   allowed users' changes, find where each ended up and compare with
   `reaction_state`.
3. New ones run the `Reaction.handler`; removed ones run its `undo`.
   Applied, non-destructive actions are recorded and marked ✅; a failure
   marks ⚠️ with the reason in #bot-log. `destructive=True` (📦, 🗑️) leaves
   nothing to record.

**Scheduler → job handlers**

1. A skill books a job with `scheduler.add_job(skill, kind, due_at,
   payload, user_id)`; it is a row in `scheduled_jobs` (due moment in UTC).
2. The ticker (every 15 seconds, and woken for the next due job) runs due
   jobs through the handler registered for `(skill, kind)`, which
   `registry.load()` collects from each skill's `job_handlers()`.
3. Jobs missed while offline run at startup with `job.is_late`.

**Buttons, selects, slash commands**: persistent views are registered in
each skill's `setup`; slash commands and menus live in the `CommandTree` in
`main.py` and are logged by `core/interactions.py`. Handlers answer first
and log second; `main.on_interaction` reports any left unanswered after 2
seconds.

## Database (`data/assistant.db`)

| Tables | Owner |
|---|---|
| `users`, `message_log`, `scheduled_jobs`, `reaction_state`, `skill_migrations` | core (`core/migrations.py`, version in `PRAGMA user_version`) |
| `archive_items` | archive |
| `timers_timers`, `timers_pomodoros`, `timers_focus_log`, `timers_boards` | timers |
| `lab_state`, `lab_tour_runs`, `lab_tour_results` | lab |

Backups go to `data/backups/` nightly at 3am NZ (newest 7 `assistant-*.db`
kept); `pre-migration-*.db` snapshots are never auto-deleted.

## Not built yet

The gateway layer (the Claude chat path in `main.py` and `builtin`'s view
still use discord.py directly), Claude tool calling (`Skill.tools()` is
declared, nothing calls it), quiet hours, the sweep and the summary (`dev
quiet` changes nothing; `dev run sweep|summary` report "not built").
