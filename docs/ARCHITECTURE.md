# Architecture map

Where everything is and how input flows through it. Read this before
exploring the code. **Update it in the same change whenever a file is added,
moved, renamed or changes what it is responsible for.**

For how to use the bot and each task in detail, see `docs/DEVELOPMENT.md`;
for why things are the way they are, `docs/DECISIONS.md`.

## Top level

| Path | Responsibility |
|---|---|
| `main.py` | Entry point (`--dev` runs it on the dev database): creates the Discord client, wires Discord events to the registry, holds the Claude chat path (which hands Claude its tools) and the slash command tree |
| `core/` | Shared building blocks. Never imports from `tasks/` |
| `tasks/` | One folder per feature, loaded by `tasks/registry.py` |
| `tests/` | Unit tests (pytest); never start the bot or touch real data |
| `docs/specs/` | Private task specs (gitignored, never committed or quoted in public docs); zipped by the nightly backup |
| `docs/` | `ARCHITECTURE` (this), `DEVELOPMENT` (how to use and extend), `DECISIONS` (why), `TESTING` (test tracker), `QA-RUN` (manual run sheet), `BACKLOG` (found and not yet finished), `CHANGELOG` (what changed, by date), `CHEATSHEET` (commands) |
| `.claude/skills/` | Procedures for Claude Code: `add-task`, `qa`, `end-of-task`, `bug` (fix a reported bug from its id) |
| `.env`, `.env.example` | Secrets and settings (`.env` is gitignored); every setting has a placeholder in `.env.example` |
| `data/` | `assistant.db`, `bot.lock`, `backups/`; with `--dev`: `dev.db`, `dev-backups/`, `dev-clock.json` (all gitignored) |
| `logs/` | `bot.log` (rotating), `service-*.log` (gitignored) |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini` | Dependencies (dev adds pytest) and test settings |

## `core/`

| File | Responsibility |
|---|---|
| `config.py` | Paths, settings from `.env` and their validation, constants, the `CHANNELS` name-to-id map (with `hub`, from `HUB_CHANNEL_ID`); `DEV_DATABASE` (started with `--dev`), which picks the database and backup folder; `DAY_BOUNDARY`; `now_nz()` (the bot's clock) and `real_now_nz()` |
| `clock.py` | What time it is: `now()` is the real time plus the dev clock's offset, `real_now()` never moves. The clock can only be moved on the dev database, only forward (`advance`, `advance_to`; `reset` goes back), and its offset is kept in `data/dev-clock.json` across restarts. `skipped_between` is the time a jump passed over. Imports nothing from core |
| `costs.py` | What each message cost and how it was handled: the routes (`button`, `shortcut`, `reaction`, `follow-up`, `router`, `chat`, and `tools` for the old way of sending every tool), the price of a request including cached tokens, recording a message's route, tasks and each request to Claude (`db_record`), and adding it up by day, month, route and task for `dev cost` (`split`, `report`). Pure apart from the functions that take a connection |
| `day.py` | The day boundary for every task (`DAY_BOUNDARY`, midnight NZ): `today()`, `day_of(moment)`, `at(day, time)`, `start_of` / `end_of` (UTC, daylight-saving safe), and the rollover job, which tells every `on_new_day` listener (a task's `new_day`) the day that ended and the day it is now, then books the next |
| `timeinput.py` | Pure: dates the user types (`parse_date`: tomorrow, friday, the 20th, 20 Oct; shown by `format_date` / `format_dates`) and times the user types (12-hour, 24-hour, noon / midnight), `AmbiguousTime` with both readings when it could be morning or evening, the checks on a time given for something already done (today, not in the future, not before the previous one), and the one way times are shown (`format_time`: "8:04 am") |
| `occurrences.py` | The occurrence log: expected things on a day (`occurrences`) with their state (pending, done, skipped, missed), plan, due time, actual time and automatic-skip reason, and every change to them (`occurrence_events`, values before and after). Changes made together share a change id: `db_last_change` finds the user's last one and `db_revert` takes it back |
| `logging_setup.py` | Terminal and rotating file logging |
| `instance_lock.py` | Single-instance lock on `data/bot.lock`, taken first thing at startup, and the source of truth for what is running: `holder()` asks the lock, `instances()` counts bot processes without the `.venv` launcher, `status()` puts both into words (`python -m core.instance_lock`, `dev status`) |
| `database.py` | `connect()`, `wipe_dev()` (deletes the dev database and refuses any other), the async `message_log` helpers (`log_received`, `log_result`, `recent_log` for looking further back), `run(func)` in a worker thread |
| `migrations.py` | Numbered schema migrations, core and per task, applied at startup |
| `backup.py` | Nightly backup (a scheduler job that books its successor): the database, and `docs/specs/` as a zip beside it; pre-migration snapshots |
| `users.py` | The `User` record, `ensure_owner()`, cached lookup by Discord id |
| `permissions.py` | `is_allowed(user, action)`: the one permission check |
| `errors.py` | `UserError`: a problem the user can fix |
| `context.py` | `Context` handed to tasks: user, channel, args, `reply` (Kept) / `confirm` / `note` (Transient), database, #bot-log; `via_tool` says Claude is running it; `posted` counts what a handler put in the channel; `parent_channel_id` is the forum or channel a post or thread hangs off |
| `lifecycle.py` | The message lifecycle: the six classes and their policy, `classify(...)`, and `deletes(...)` / `delete_after()`, which everything that deletes a message by itself asks first (`dev cleanup off` says no). `KEEP_CONFIRMATIONS` makes `delete_after()` leave every Transient message in place |
| `router.py` | Matches typed words and phrases, with typo tolerance; sets filler words aside for reply actions ("pin this"); `GENERIC_VERBS` are the verbs no shortcut may be on its own (add, edit, remove, pause…) |
| `reactions.py` | Pure: which reaction changes count, which are checked at once, where they ended up, what to apply or undo; the `reaction_state` queries |
| `debounce.py` | `Debouncer(delay, callback)`: one quiet-period timer that hands over all collected events together |
| `protection.py` | Pure: is a message protected (pinned or 📌), is it kept, and the wording when Discord refuses a pin |
| `channels.py` | Which channels hold messages: `holds_messages(channel)` (text, news, threads, DMs; not forum, voice or category) and `named()`, the channels from `.env` that do. Asked before reading pins or history from a channel no message came from |
| `pins.py` | `set_pinned(...)`: native pin and unpin for tasks that may not call Discord |
| `cards.py` | Buttons, dropdowns and forms for tasks that may not use discord.py: a task writes a `Card` of plain records (`Button`, `Select`, `Form`) and registers what each action does; the component's id (`card.b:<task>:<action>:<arg>`) carries everything, so cards work after a restart. `handle` answers every press first, checks `is_allowed`, logs it in `message_log` (kind `card`), shows a `UserError` to the presser alone and reports anything else. `post` / `send` / `edit` / `delete` put cards in channels |
| `confirmations.py` | Buttons under a short message: `ask` (Confirm / Cancel), `choose` (which of a few), `offer_undo` (done, with Undo). In memory, with timeouts |
| `tools.py` | Pure: Claude's tools from registrations: names, strict-safe input schemas, input checking, which are sent as strict, which message a message action is aimed at, previews and the listing text, and matching a query against logged messages (`find_logged`) |
| `pending.py` | Proposals waiting for a short "ok" (only ever for actions with no preview of their own): what counts as yes or no, two-minute expiry, one per user and channel (in memory) |
| `scheduler.py` | Database-backed jobs: `add_job`, a ticker that runs due ones until none is left (`run_all_due`), catch-up at startup (`job.is_late`). Its time is the clock's: when the dev clock jumps, `wake()` runs what came due in order, and time jumped over is not lateness |
| `devmode.py` | Dev mode's in-memory state (the dev clock is not part of it: `clock.py`); other code asks it for values (`reaction_debounce()`, `speed()`, `is_verbose()`, `cleanup_enabled()`, `debug()`, `register_task()`) |
| `interactions.py` | Permission check and logging for slash commands and context menus |
| `llm.py` | Claude client (short timeout, two retries); the system prompt (one cached block, the same for every message); `turn_note` (the time and the tasks' live state, sent after the user's words in the latest turn only); the tool loop (`ask_claude` runs the calls Claude makes, up to `MAX_TOOL_CALLS`, and ends the turn without a closing request when `closing` says the tools have already told the user); the honesty checks (`claims_done`, `claims_change`, `scrub`: a "done" with nothing done, or a reported change with no tool having succeeded, is sent back once; a bracketed tool note is removed); per-channel history of what was said and nothing else; cost estimates including cache and tool tokens |
| `timing.py` | Where the time goes while one message is answered: each request to Claude (and what it was for), each tool, the calls to Discord, rate-limit waits and retries (read from the libraries' logs). One `Turn` per message, found through a context variable; `summary_lines` is the breakdown on the "Message handled" card, and `as_dict` the same as plain values, kept in `message_log.timing` |
| `live.py` | Work nobody should wait for: `schedule(key, refresh)` brings one Live message up to date in the background, one edit however many changes asked for it and at most one every 2 seconds per message; `background(...)` runs anything else after the reply. What they do is not counted in the turn's timing |
| `discord_utils.py` | Binds the client and times every call it makes to Discord; #bot-log cards, `split_message`, `truncate`, `safe_reply`, `report_interaction_error` |

## `tasks/`

| Path | Responsibility |
|---|---|
| `base.py` | The `Task` base class with its hooks (including `message_class`, `tools_available` and `new_day`), and the self-describing `Keyword`, `ReplyAction`, `Reaction` records (the last two with an optional `validate`); `Param` describes an argument for Claude; `Tool` is a tool that isn't a word (reading state, acting by id). `Task.live_state(ctx)` is what a task tells Claude about its state with every message. `Reaction.instant` skips the quiet period (🐞 only); `Task.claim(ctx)` takes a message because of where it was sent |
| `registry.py` | Discovers and loads tasks; dispatches words, reply actions and reactions; refuses invalid ones at once; decides how each ends; asks tasks what a message is (`declared_class()`); the single source of what the bot can do (`catalogue()`, `find()`, `capabilities_text()`, and `tools_for()` for Claude, which adds each task's `tools()`); `run_tool()` runs a tool call down the same path as a typed word. `live_state(ctx)` gathers the tasks' state for Claude; a tool call's #bot-log card follows in the background. `dispatch_claimed` hands an unmatched message to the task that claims it; an `instant` reaction is applied the moment it is added |
| `toolcalls.py` | Not a task: what becomes of a tool call from Claude. Gathers the tools for a message, then decides per call: run now, wait for "ok", Confirm / Cancel, which-message buttons, quoted preview with Undo, (for a message found further back) quoted and asked first, or, for calls Claude marked `candidate` because tools of different tasks fit equally, held until the round ends and offered as one button per task (`end_round`). What waits is always the call with its structured input; the user is shown a word as typed or a tool's `label`, never its name. Also the `recent_messages` and `search_messages` tools, and whether anything was actually done this turn (`Turn.acted`). `closing(turn)` says after each round whether every call acted and showed the user its own confirmation, so the turn can end there |
| `builtin/__init__.py` | `ping`, `reset`, `buttons`, `stats`, and `help` generated from the registry |
| `builtin/views.py` | The `buttons` test view |
| `archive/__init__.py` | Registers reply `archive` / `delete`, the 📦 and 🗑️ reactions, the context menu |
| `archive/rules.py` | Pure: what may be archived or deleted, names, embeds, wording |
| `archive/store.py` | The `archive_items` records |
| `archive/messages.py` | The Discord work: webhook repost, delete, confirmation, Restore button |
| `bugs/__init__.py` | Registers `bug` (word and reply), the instant 🐞 reaction, `bugs`, `bugs export`; files a report; claims what is written in a bug's post and saves it as a note |
| `bugs/rules.py` | Pure: ids, what may be reported, a message as plain values (`Snapshot`, `Report`), which logged turn it belongs to, which log lines go with it, and all the wording (post, title, tags, list, `docs/BUGS.md`) |
| `bugs/store.py` | The `bugs_items` and `bugs_notes` records, the history in `bugs_events`, and the channel's recent `message_log` rows for finding the turn |
| `bugs/capture.py` | Puts a report together: the turn, the errors from the tail of `logs/bot.log`, the commit the bot started on. No Discord |
| `bugs/posts.py` | The Discord work, and the only discord.py in the task: reading the reported message, the forum post with its tags, and the opening card: rewritten in place with the status, when it changed and the note count; persistent buttons under it, Fixed / Won't fix on an open bug (tag and archive) and Re-open on a closed one (unarchive, tag Open) |
| `bugs/cli.py` | `python -m tasks.bugs.cli list \| show B4 \| note B4 "…"` for Claude Code's `bug` skill: reads and adds notes straight from the database, never closes a bug |
| `keep/__init__.py` | The 📌 reaction: keep (pin) and unkeep (unpin); reply `pin` / `unpin`, which act at once. All through `core/pins.py` |
| `pills/__init__.py` | Registers `pills` (the list) and Claude's tools `pill_add`, `pill_edit`, `pill_pause`, `pill_remove`; works in #inbox and the hub |
| `pills/rules.py` | Pure: a pill's `Plan` (untimed, fixed times, or so many a day with a minimum gap; optionally a course with dates), building one from a `Request` in the user's words (`build`, which raises `TimeQuestion` for a time that could be morning or evening), what a pill is on a day (`status_on`: active, upcoming, paused, ended), which pill a name means (`find`), and all the wording (one-line summary, old-and-new for an edit, the list, the live state for Claude) |
| `pills/store.py` | The `pills_pills` records, the drafts behind open previews (`pills_drafts`) and every change to a plan or status (`pills_changes`) |
| `pills/plans.py` | Setting pills up, with no discord.py: the tools' handlers, the preview, list, pill and remove cards (`core/cards.py`), what each button does, and the job that lets an unsaved preview lapse |
| `timers/__init__.py` | Registers `timer`, `timers`, `pause all`, `resume all`, `pomo`, `pomo stats`, the reply actions and job handlers, and Claude's tools: `list_timers`, `get_pomodoro_status`, `timer_history`, `timer_control`, `pomodoro_control` |
| `timers/control.py` | The handlers of those tools, and `pause all` / `resume all`. What they report is read back from the database after the change. `timer_control` takes one id, several, or `all` (with an optional label), so a bulk request is one call; `live_state` is what Claude is told with every message |
| `timers/status.py` | Pure: the live state of timers and the session in words for Claude, the ids (`t12`, `p4`) the control tools take, the event history and what `pause all` did; several ids in one argument, label matching, and the live state text |
| `timers/durations.py`, `pomodoro.py` | Pure: duration parsing; Pomodoro phases, pause arithmetic, stats |
| `timers/store.py` | Everything timers remember (`timers_*` tables), including each clock's own speed, the events of every timer and session, and the live lists |
| `timers/timers.py`, `sessions.py`, `board.py`, `common.py` | Timer messages, Pomodoro session cards, the pinned "Active timers" board and the live "Your timers" lists (both rewritten on every change, in the background through `core/live.py`), shared message helpers |
| `dev/__init__.py` | Registers the `dev …` words; `dev mode on\|off` is the one Claude is always offered |
| `dev/panel.py` | The pinned dev panel (with the clock, and "DEV DATABASE" when started with `--dev`), its persistent buttons, the bot's status ("🛠️ Dev mode", "🧪 DEV DATABASE") |
| `dev/clockwords.py` | Pure: what `dev clock <time> \| +<duration> \| reset` moves the clock to (a time is the next moment the clock reads it), and the clock in words |
| `dev/tools.py` | `dev inspect`, `dev status`, `dev jobs`, `dev run`, `dev fire next`, `dev seed`, `dev clean`, `dev cost`, `dev reset-db` (asks, then wipes the dev database and rebuilds it empty) |
| `lab/__init__.py`, `common.py` | The `lab …` test bench; `common.py` has the `Run` adapters that let one `run_*` function serve a typed word and `/lab` |
| `lab/buttons.py`, `react.py`, `status.py`, `charts.py`, `data.py`, `misc.py`, `channels.py`, `tour.py`, `state.py`, `ratelimits.py` | One Discord feature each: components, reaction timeline, pinned status, charts and their data, notifications / polls / formatting, cross-channel test, the guided tour, the lab's key/value table, rate-limit watching |

Only `lab`, `archive`, `timers`, `dev` and `bugs` (in `posts.py` alone)
use discord.py directly; that moves behind a gateway layer later. Other tasks go through `Context` and
core helpers; `pills` gets its buttons and dropdowns from `core/cards.py`.

## `tests/`

`conftest.py` has the fixtures (`make_db`, `db`, `dev_off`, `owner`,
`stranger`); `helpers.py` has `DatabaseTestCase`; `__init__.py` sets made-up
settings before `core` loads. One `test_*.py` per area: `router`,
`registry` (loading, help, capabilities), `reactions`, `reaction_keys`,
`debounce`, `live`, `keep`, `archive_rules`, `archive_store`, `durations`,
`pomodoro`, `timer_text`, `timing`, `timer_status`, `timer_freeze` (pause, resume and events against a
database with the clock under test control), `devmode`, `dev_parsing`, `lab`, `lifecycle`,
`permissions`, `scheduler`, `text`, `tools`, `pending`, `llm_tools` (the
Claude loop against a scripted stand-in), `toolcalls`, `bugs`, `instance_lock`, `backup` (the specs zip), `clock`,
`day` (the boundary and the rollover job), `timeinput`, `occurrences`,
`dev_clock` (`dev clock`, `dev reset-db` and their guards), `costs` (routes, prices, the roll-up and `dev cost`), `cards`,
`pills_rules`, `pills_plans` (records, previews, buttons, and a tool call
all the way through the registry), `channels`
(channel types, the dev panel's start-up sweep, a task failing to start).

## Data flows

**Startup** (`main.py`): `core/config.py` reads `--dev` (which database)
and hands the clock its stored offset → logging → `instance_lock.acquire()`
→ `registry.load()` → `migrate(registry.task_migrations())` →
`ensure_owner()` → connect. `setup_hook` runs each task's `setup`
(persistent views); `on_ready` syncs slash commands, runs each task's
`startup`, books the backup and the day rollover and starts the scheduler.

**Message → router → task**

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
4. If neither matched: `registry.dispatch_expected` (a task waiting for
   this user's next message), then `registry.dispatch_claimed` (a task
   that takes the message because of where it was sent: a note in a bug's
   post), then, in #inbox only, Claude (see below). A typed word never
   gets this far, so it never costs an API call.
5. Every outcome is emitted to tasks as `action_finished`.

**Chat → Claude → tools**

1. `toolcalls.answer_pending`: a short "ok" or "no" to something Claude
   proposed is settled here, without calling Claude.
2. `toolcalls.prepare`: `registry.tools_for(user, channel)` (channel,
   permission, each task's `tools_available`), `core/tools.py` picks the
   strict ones, and the definitions are marked for caching.
3. `llm.ask_claude` sends the message with the tools. For each call Claude
   makes, `toolcalls.execute` checks the input, finds the target message
   for a message action (the reply, or a ref from `recent_messages` or
   `search_messages`), and decides: destructive, or found further back →
   `confirmations.ask`; `propose` → `core/pending.py`; several candidates
   → `confirmations.choose`; otherwise `registry.run_tool`, which goes
   through `_run` like a typed word (logged as `tool`, permission checked,
   #bot-log card). A task's own tool (`Task.tools()`) runs the same way
   and posts nothing: its result is for Claude to put into words.
4. Every result, failures included, goes back to Claude, which writes the
   reply. A reply that offers an "ok" with no proposal waiting, or names
   a tool, is sent back once like an unbacked "done"; whatever is sent
   has tool names taken out. Times are not rewritten: tools give them
   already formatted (`8:00 pm`). If that reply says "done" and no tool has done anything
   (`Turn.acted`), it goes back to Claude once before the user sees it,
   and a card in #bot-log records it. Only the reply's text is kept in
   the history. The "Message handled" card lists the tools sent, their
   tokens, cache use, the calls and where the time went (`core/timing.py`).
5. Speed: the message gets 👀 at once (removed when answered). The time
   and `registry.live_state` go with the user's words as a note, so the
   system prompt and tools stay byte-identical (cached) and a simple
   request needs no read first. When every call of a round acted and
   showed its own confirmation (`toolcalls.closing`), the turn ends
   there: one request to Claude, not two. Board, list and card edits
   and the tool's log card follow in the background (`core/live.py`).

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
4. The exception: a `Reaction` with `instant=True` (🐞) never reaches the
   debouncer. Once valid it runs straight away through
   `dispatch_reaction`, nothing is recorded or marked ✅, and taking it
   away does nothing.

**Bug report → forum post → notes**

1. 🐞 on a message, `bug` as a reply to it, or `bug` alone (the latest
   message in the channel): `tasks/bugs` takes the message and the five
   before it as plain `Snapshot`s. A message that already has an open bug
   is pointed to instead.
2. `capture.build` finds the turn in `message_log` (`rules.pick_turn`:
   the user's message by id, the bot's by time; the tool calls are rows
   against the same message, the timings are in `message_log.timing`),
   reads the warnings and errors around it from `logs/bot.log`, and adds
   the commit the bot started on.
3. The record is saved (`bugs_items`; its id is the number in "B4"), then
   `posts.create_post` opens a post in the #bugs forum (`BUGS_CHANNEL_ID`)
   tagged Open, with the context, the three questions and the Fixed /
   Won't fix buttons. The channel gets "🐞 Logged as B4" (Kept), linking
   to the post, and a typed `bug` is deleted (Consumed).
4. Anything the owner writes in that post is claimed by `Task.claim`,
   saved in `bugs_notes` and ticked ✅. Nothing there reaches Claude.
5. Fixed or Won't fix sets the status and the tag, archives the post, and
   rewrites the opening card: status, time, and one Re-open button in
   place of the two. Re-open undoes that (unarchive first, then the card,
   then the Open tag). Each is a row in `bugs_events`. A note also
   rewrites the card, for its count.
   Claude Code's `bug` skill reads a bug with `tasks/bugs/cli.py` and adds
   a "fix ready, needs retest" note; it never closes one.

**Setting up a pill**

1. "add evening pill at 20:00" (in #inbox) reaches Claude, which calls
   `pill_add` directly (it has no `propose`: the preview is the one
   confirmation) with the name and the time as it was said. `plans.add_tool`
   has `rules.build` turn that `Request` into a `Plan`; anything that
   can't be one is refused with a reason for Claude to pass on.
2. The request is kept as a draft (`pills_drafts`) and the preview is
   posted as the answer: the plan on one line with **Save** and **Edit**.
   The turn ends there, with no closing reply from Claude. A job lets the
   draft lapse after 30 minutes.
3. A time that could be morning or evening ("at 8") posts the question
   instead, with a button for each reading; the answer settles that time
   in the draft and the preview follows.
4. **Save** builds the plan again, checks the name, writes the pill (or
   the edit) and removes the draft in one transaction, and the preview
   becomes one line. **Edit** asks what to change; saying it reaches
   Claude, which calls the tool again with the draft's id, and the new
   preview replaces the old.
5. `pill_edit` is the same against an existing pill, with the old and new
   plan shown. `pill_pause` acts at once. `pill_remove` posts a Confirm
   card; deleting a pill with its history is a separate, stronger one.
6. `pills` posts the list with one dropdown; picking a pill rewrites the
   message as that pill with Edit, Pause or Resume, Remove and Back.
   Every press comes through `cards.handle`.

**Message lifecycle**

Every message is Kept, Live, Consumed, Transient, Alert or Protected (the
table is in `CLAUDE.md`). `core/lifecycle.py` holds the policy; the places
that delete by themselves (`Context.confirm` / `note` / `delete_command`,
`core/confirmations.py`, pin notices in `main.py`, timer alerts, the dev
panel) ask `lifecycle.deletes(...)` first, and `dev cleanup off` makes the
answer no. Tasks say which of their messages are Live or an Alert through
`Task.message_class`; `dev inspect` puts it together with
`lifecycle.classify`. Deleting because the user asked (archive, delete,
`dev clean`, Restore) doesn't go through the policy.

**Scheduler → job handlers**

1. A task books a job with `scheduler.add_job(task, kind, due_at,
   payload, user_id)`; it is a row in `scheduled_jobs` (due moment in UTC).
2. The ticker (every 15 seconds, and woken for the next due job) runs due
   jobs through the handler registered for `(task, kind)`, which
   `registry.load()` collects from each task's `job_handlers()`.
3. Jobs missed while offline run at startup with `job.is_late`.
4. A pass goes on until nothing more runs, so a job booked by another and
   already due is not left for the next tick.

**Time, the dev clock and the day**

1. Everything time-based asks `core/clock.py` (through
   `scheduler.utc_now()` or `config.now_nz()`). Records of what really
   happened ask `real_now()`: log cards, `message_log`, the instance lock,
   bug reports, dev mode's expiry.
2. `dev clock` (dev database only) moves the clock ahead and wakes the
   scheduler: every job that came due on the way runs in due order, not
   flagged late. The offset is saved, so a restart keeps the bot's time.
3. At `DAY_BOUNDARY` the `core/day_rollover` job calls each task's
   `new_day(ended, started)` and books the next. After days away (or a
   jump of several days) it runs once, and the two dates say how long.
4. What is expected on a day lives in the occurrence log
   (`core/occurrences.py`); a task makes today's with `db_ensure` (asking
   twice never resets one) and changes them through `db_change`.

**Buttons, selects, slash commands**: persistent views are registered in
each task's `setup`; slash commands and menus live in the `CommandTree` in
`main.py` and are logged by `core/interactions.py`. Handlers answer first
and log second; `main.on_interaction` reports any left unanswered after 2
seconds.

## Database (`data/assistant.db`; `data/dev.db` with `--dev`)

| Tables | Owner |
|---|---|
| `users`, `message_log` (every input, with its route, tasks, requests, tokens, cost and time), `llm_calls` (one row per request to Claude), `scheduled_jobs`, `reaction_state`, `skill_migrations`, `occurrences`, `occurrence_events` | core (`core/migrations.py`, version in `PRAGMA user_version`) |
| `archive_items` | archive |
| `bugs_items`, `bugs_notes`, `bugs_events` (each closing and re-opening) | bugs |
| `pills_pills`, `pills_drafts` (previews waiting for Save), `pills_changes` (every plan and status change); doses will be rows of `occurrences` with task `pills` | pills |
| `timers_timers`, `timers_pomodoros`, `timers_focus_log`, `timers_boards`, `timers_events`, `timers_lists` | timers |
| `lab_state`, `lab_tour_runs`, `lab_tour_results` | lab |

Backups go to `data/backups/` nightly at 3am NZ (newest 7 `assistant-*.db`
kept, and the newest 7 `specs-*.zip` of `docs/specs/` taken with them);
`pre-migration-*.db` snapshots are never auto-deleted. The dev database's
go to `data/dev-backups/`, so they never push a real backup out.

## Not built yet

The gateway layer (the Claude chat path in `main.py` and `builtin`'s view
still use discord.py directly), bulk and cross-channel actions for Claude,
quiet hours, the sweep and the summary (`dev
quiet` changes nothing; `dev run sweep|summary` report "not built"), and
to-dos (the list of things to do: called "to-dos" so it is never confused
with the tasks in `tasks/`).
