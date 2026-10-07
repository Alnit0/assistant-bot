# Architecture map

Where everything is and how input flows through it. Read this before
exploring the code. **Update it in the same change whenever a file is added,
moved, renamed or changes what it is responsible for.**

For how to use the bot and each skill in detail, see `docs/DEVELOPMENT.md`;
for why things are the way they are, `docs/DECISIONS.md`.

## Top level

| Path | Responsibility |
|---|---|
| `main.py` | Entry point: creates the Discord client, wires Discord events to the registry, holds the Claude chat path (which hands Claude its tools) and the slash command tree |
| `core/` | Shared building blocks. Never imports from `skills/` |
| `skills/` | One folder per feature, loaded by `skills/registry.py` |
| `tests/` | Unit tests (pytest); never start the bot or touch real data |
| `docs/` | `ARCHITECTURE` (this), `DEVELOPMENT` (how to use and extend), `DECISIONS` (why), `TESTING` (test tracker), `QA-RUN` (manual run sheet), `BACKLOG` (found and not yet finished), `CHANGELOG` (what changed, by date), `CHEATSHEET` (commands) |
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
| `database.py` | `connect()`, the async `message_log` helpers (`log_received`, `log_result`, `recent_log` for looking further back), `run(func)` in a worker thread |
| `migrations.py` | Numbered schema migrations, core and per skill, applied at startup |
| `backup.py` | Nightly backup (a scheduler job that books its successor) and pre-migration snapshots |
| `users.py` | The `User` record, `ensure_owner()`, cached lookup by Discord id |
| `permissions.py` | `is_allowed(user, action)`: the one permission check |
| `errors.py` | `UserError`: a problem the user can fix |
| `context.py` | `Context` handed to skills: user, channel, args, `reply` (Kept) / `confirm` / `note` (Transient), database, #bot-log; `via_tool` says Claude is running it |
| `lifecycle.py` | The message lifecycle: the six classes and their policy, `classify(...)`, and `deletes(...)` / `delete_after()`, which everything that deletes a message by itself asks first (`dev cleanup off` says no) |
| `router.py` | Matches typed words and phrases, with typo tolerance; sets filler words aside for reply actions ("pin this") |
| `reactions.py` | Pure: which reaction changes count, which are checked at once, where they ended up, what to apply or undo; the `reaction_state` queries |
| `debounce.py` | `Debouncer(delay, callback)`: one quiet-period timer that hands over all collected events together |
| `protection.py` | Pure: is a message protected (pinned or 📌), is it kept, and the wording when Discord refuses a pin |
| `pins.py` | `set_pinned(...)`: native pin and unpin for skills that may not call Discord |
| `confirmations.py` | Buttons under a short message: `ask` (Confirm / Cancel), `choose` (which of a few), `offer_undo` (done, with Undo). In memory, with timeouts |
| `tools.py` | Pure: Claude's tools from registrations: names, strict-safe input schemas, input checking, which are sent as strict, which message a message action is aimed at, previews and the listing text, and matching a query against logged messages (`find_logged`) |
| `pending.py` | Proposals waiting for a short "ok": what counts as yes or no, two-minute expiry, one per user and channel (in memory) |
| `scheduler.py` | Database-backed jobs: `add_job`, a ticker that runs due ones, catch-up at startup (`job.is_late`) |
| `devmode.py` | Dev mode's in-memory state; other code asks it for values (`reaction_debounce()`, `speed()`, `is_verbose()`, `cleanup_enabled()`, `debug()`, `register_task()`) |
| `interactions.py` | Permission check and logging for slash commands and context menus |
| `llm.py` | Claude client; the system prompt (cached part, then the time); the tool loop (`ask_claude` runs the calls Claude makes, up to `MAX_TOOL_CALLS`); the honesty checks (`claims_done`, `scrub`: a "done" with nothing run is sent back once, a bracketed tool note is removed); per-channel history of what was said and nothing else; cost estimates including cache and tool tokens |
| `discord_utils.py` | #bot-log cards, `split_message`, `truncate`, `safe_reply`, `report_interaction_error` |

## `skills/`

| Path | Responsibility |
|---|---|
| `base.py` | The `Skill` base class with its hooks (including `message_class` and `tools_available`), and the self-describing `Keyword`, `ReplyAction`, `Reaction` records (the last two with an optional `validate`); `Param` describes an argument for Claude; `Tool` is a tool that isn't a word (reading state, acting by id) |
| `registry.py` | Discovers and loads skills; dispatches words, reply actions and reactions; refuses invalid ones at once; decides how each ends; asks skills what a message is (`declared_class()`); the single source of what the bot can do (`catalogue()`, `find()`, `capabilities_text()`, and `tools_for()` for Claude, which adds each skill's `tools()`); `run_tool()` runs a tool call down the same path as a typed word |
| `toolcalls.py` | Not a skill: what becomes of a tool call from Claude. Gathers the tools for a message, then decides per call: run now, wait for "ok", Confirm / Cancel, which-message buttons, quoted preview with Undo, or (for a message found further back) quoted and asked first. Also the `recent_messages` and `search_messages` tools, and whether anything was actually done this turn (`Turn.acted`) |
| `builtin/__init__.py` | `ping`, `reset`, `buttons`, `stats`, and `help` generated from the registry |
| `builtin/views.py` | The `buttons` test view |
| `archive/__init__.py` | Registers reply `archive` / `delete`, the 📦 and 🗑️ reactions, the context menu |
| `archive/rules.py` | Pure: what may be archived or deleted, names, embeds, wording |
| `archive/store.py` | The `archive_items` records |
| `archive/messages.py` | The Discord work: webhook repost, delete, confirmation, Restore button |
| `keep/__init__.py` | The 📌 reaction: keep (pin) and unkeep (unpin); reply `pin` / `unpin`, which act at once. All through `core/pins.py` |
| `timers/__init__.py` | Registers `timer`, `timers`, `pomo`, `pomo stats`, the reply actions and job handlers, and Claude's tools: `list_timers`, `get_pomodoro_status`, `timer_control`, `pomodoro_control` |
| `timers/status.py` | Pure: the live state of timers and the session in words for Claude, and the ids (`t12`, `p4`) the control tools take |
| `timers/durations.py`, `pomodoro.py` | Pure: duration parsing; Pomodoro phases, pause arithmetic, stats |
| `timers/store.py` | Everything timers remember (`timers_*` tables) |
| `timers/timers.py`, `sessions.py`, `board.py`, `common.py` | Timer messages, Pomodoro session cards, the pinned "Active timers" board, shared message helpers |
| `dev/__init__.py` | Registers the `dev …` words; `dev mode on\|off` is the one Claude is always offered |
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
`pomodoro`, `timer_text`, `timer_status`, `devmode`, `dev_parsing`, `lab`, `lifecycle`,
`permissions`, `scheduler`, `text`, `tools`, `pending`, `llm_tools` (the
Claude loop against a scripted stand-in), `toolcalls`.

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
   `registry.dispatch_keyword`: `core/router.py` matches the whole message
   (for a reply, also without filler words: "pin this"); the registration's
   channel is checked.
3. `registry._run`: logs the raw input (`message_log`), checks
   `is_allowed`, calls the handler, records the result, posts the #bot-log
   card. Success deletes the user's message (Consumed) and shows a
   self-deleting confirmation (Transient); failure leaves it with ⚠️ and
   puts the reason in #bot-log. A reply action's `validate` runs first: if
   the message can't be acted on, the reason is also shown briefly.
4. If neither matched: `registry.dispatch_expected` (a skill waiting for
   this user's next message), then, in #inbox only, Claude (see below). A
   typed word never gets this far, so it never costs an API call.
5. Every outcome is emitted to skills as `action_finished`.

**Chat → Claude → tools**

1. `toolcalls.answer_pending`: a short "ok" or "no" to something Claude
   proposed is settled here, without calling Claude.
2. `toolcalls.prepare`: `registry.tools_for(user, channel)` (channel,
   permission, each skill's `tools_available`), `core/tools.py` picks the
   strict ones, and the definitions are marked for caching.
3. `llm.ask_claude` sends the message with the tools. For each call Claude
   makes, `toolcalls.execute` checks the input, finds the target message
   for a message action (the reply, or a ref from `recent_messages` or
   `search_messages`), and decides: destructive, or found further back →
   `confirmations.ask`; `propose` → `core/pending.py`; several candidates
   → `confirmations.choose`; otherwise `registry.run_tool`, which goes
   through `_run` like a typed word (logged as `tool`, permission checked,
   #bot-log card). A skill's own tool (`Skill.tools()`) runs the same way
   and posts nothing: its result is for Claude to put into words.
4. Every result, failures included, goes back to Claude, which writes the
   reply. If that reply says "done" and no tool has done anything
   (`Turn.acted`), it goes back to Claude once before the user sees it,
   and a card in #bot-log records it. Only the reply's text is kept in
   the history. The "Message handled" card lists the tools sent, their
   tokens, cache use and the calls.

**Reaction → debouncer → actions**

1. `main.on_raw_reaction_add` / `remove` (never the bot's own) →
   `registry.reaction_changed`. A registered emoji being added is checked
   at once with the `Reaction`'s `validate`: an invalid one gets ⚠️ and a
   short self-deleting reason and goes no further. Everything else feeds
   the one `Debouncer`.
2. After `REACTION_DEBOUNCE` of quiet (or dev mode's value),
   `registry._reactions_quiet` uses `core/reactions.py` to keep only
   allowed users' changes, find where each ended up and compare with
   `reaction_state`.
3. New ones run the `Reaction.handler`; removed ones run its `undo`.
   Applied, non-destructive actions are recorded and marked ✅; a failure
   marks ⚠️ with the reason in #bot-log. `destructive=True` (📦, 🗑️) leaves
   nothing to record.

**Message lifecycle**

Every message is Kept, Live, Consumed, Transient, Alert or Protected (the
table is in `CLAUDE.md`). `core/lifecycle.py` holds the policy; the places
that delete by themselves (`Context.confirm` / `note` / `delete_command`,
`core/confirmations.py`, pin notices in `main.py`, timer alerts, the dev
panel) ask `lifecycle.deletes(...)` first, and `dev cleanup off` makes the
answer no. Skills say which of their messages are Live or an Alert through
`Skill.message_class`; `dev inspect` puts it together with
`lifecycle.classify`. Deleting because the user asked (archive, delete,
`dev clean`, Restore) doesn't go through the policy.

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
still use discord.py directly), bulk and cross-channel actions for Claude,
quiet hours, the sweep and the summary (`dev
quiet` changes nothing; `dev run sweep|summary` report "not built").
