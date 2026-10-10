# Architecture map

Where everything is and how input flows through it. Read this before
exploring the code. **Update it in the same change whenever a file is added,
moved, renamed or changes what it is responsible for.**

For how to use the bot and each task in detail, see `docs/DEVELOPMENT.md`;
for why things are the way they are, `docs/DECISIONS.md`.

## Top level

| Path | Responsibility |
|---|---|
| `main.py` | Entry point (`--dev` runs it on the dev database): creates the Discord client, wires Discord events to the registry, hands every plain message to `core/conversation.py`, keeps the 👀 / ⚠️ status reactions on the user's message, and holds the slash command tree |
| `core/` | Shared building blocks. Never imports from `tasks/` |
| `tasks/` | One folder per feature, loaded by `tasks/registry.py` |
| `tests/` | Unit tests (pytest); never start the bot or touch real data. `tests/demo.py` holds two demo lists (shopping and packing) that the conversation tests, the golden conversations and the fixtures use: they are test fixtures, never offered by the bot |
| `evals/` | Fixtures for the router and extraction, the demo lists' included (`fixtures/*.json`: a sentence and what it must come out as, with what the real API last returned), the code that judges them (`fixtures.py`), and the live eval that asks the real API and reports accuracy, time and cost (`python -m evals.live --live`) |
| `docs/specs/` | Private task specs (gitignored, never committed or quoted in public docs); zipped by the nightly backup |
| `docs/` | `STATUS` (where the work stands: read first), `CONVERSATION` (the standard for how the bot talks, with its golden conversations), `ARCHITECTURE` (this), `DEVELOPMENT` (how to use and extend), `DECISIONS` (why), `TESTING` (test tracker), `QA-RUN` (manual run sheet), `BACKLOG` (found and not yet finished), `CHANGELOG` (what changed, by date), `CHEATSHEET` (commands) |
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
| `durations.py` | Pure: lengths of time, for every task that reads one (timers, pills, dev). `parse_duration` reads the short forms people type (`25m`, `1h30`, `1.5h`, `2 hours`, `1:30`) and, as a safety net, the way people say them ("3 hours apart", "2 and a half hours", "an hour and a half"); `split_duration` takes a length off the front of typed words and leaves the label, reading the short forms only; `format_duration` shows one |
| `timeinput.py` | Pure: dates the user types (`parse_date`: tomorrow, friday, the 20th, 20 Oct; shown by `format_date` / `format_dates`) and times the user types (12-hour, 24-hour, noon / midnight), `AmbiguousTime` with both readings when it could be morning or evening, the checks on a time given for something already done (today, not in the future, not before the previous one), and the one way times are shown (`format_time`: "8:04 am") |
| `schedule.py` | Pure: the schedule model, one shape for everything with a schedule. A `Schedule` is how many a day, a planned time for each (or for the first ones, or none: any time), a minimum gap and a latest time of day; only the first is required. `dues` says when each of a day's is due, from the plan and what was done so far: the later of its planned time and the one before, done, plus the gap (a `Due` also says why: planned, after the one before, any time, or waiting for one not yet done). `limit` is the day's limit (the latest time, or the end of the day) and `spaced` moves planned times apart to keep the gap, saying what moved. Days of the week come here later |
| `occurrences.py` | The occurrence log: expected things on a day (`occurrences`) with their state (pending, done, skipped, missed), plan, due time, actual time and automatic-skip reason, and every change to them (`occurrence_events`, values before and after). Changes made together share a change id: `db_last_change` finds the user's last one and `db_revert` takes it back |
| `trace.py` | What happened to one message, step by step, for `dev why` and bug reports: any code leaves a note while a message is handled (`note`: a check that fired or was skipped), `core/conversation.py` keeps them with the route's reason, the router's answer, the card before and after and how much state was sent (`message_log.trace`), and `lines` / `block` put a logged message into a few plain lines that can be copied whole. Imports nothing from core |
| `logging_setup.py` | Terminal and rotating file logging |
| `instance_lock.py` | Single-instance lock on `data/bot.lock`, taken first thing at startup, and the source of truth for what is running: `holder()` asks the lock, `instances()` counts bot processes without the `.venv` launcher, `status()` puts both into words (`python -m core.instance_lock`, `dev status`) |
| `database.py` | `connect()`, `wipe_dev()` (deletes the dev database and refuses any other), the async `message_log` helpers (`log_received`, `log_result`, `recent_log` for looking further back), `run(func)` in a worker thread |
| `migrations.py` | Numbered schema migrations, core and per task, applied at startup |
| `backup.py` | Nightly backup (a scheduler job that books its successor): the database, and `docs/specs/` as a zip beside it; pre-migration snapshots |
| `users.py` | The `User` record, `ensure_owner()`, cached lookup by Discord id |
| `permissions.py` | `is_allowed(user, action)`: the one permission check |
| `errors.py` | `UserError`: a problem the user can fix |
| `context.py` | `Context` handed to tasks for a typed word, reply action or reaction: user, channel, args, `reply` (Kept) / `confirm` / `note` (Transient), database, #bot-log; `posted` counts what a handler put in the channel; `parent_channel_id` is the forum or channel a post or thread hangs off. Everything it sends passes `core/outgoing.py` |
| `lifecycle.py` | The message lifecycle: the six classes and their policy, `classify(...)`, and `deletes(...)` / `delete_after()`, which everything that deletes a message by itself asks first (`dev cleanup off` says no). `KEEP_CONFIRMATIONS` makes `delete_after()` leave every Transient message in place |
| `router.py` | Matches typed words and phrases, with typo tolerance; sets filler words aside for reply actions ("pin this"); `GENERIC_VERBS` are the verbs no shortcut may be on its own (add, edit, remove, pause…) |
| `reactions.py` | Pure: which reaction changes count, which are checked at once, where they ended up, what to apply or undo; the `reaction_state` queries |
| `debounce.py` | `Debouncer(delay, callback)`: one quiet-period timer that hands over all collected events together |
| `protection.py` | Pure: is a message protected (pinned or 📌), is it kept, and the wording when Discord refuses a pin |
| `channels.py` | Which channels hold messages: `holds_messages(channel)` (text, news, threads, DMs; not forum, voice or category) and `named()`, the channels from `.env` that do. Asked before reading pins or history from a channel no message came from |
| `pins.py` | `set_pinned(...)`: native pin and unpin for tasks that may not call Discord |
| `actions.py` | The contract for plain words: an `Entry` (a task as the router knows it: name, icon, "only for", examples), its `Action`s (the fields Claude fills in; `prepare` + `apply` for one that needs a card, `run` for one that acts at once, all three with `card_if` for one that only sometimes asks first) and the `Proposal` a card shows. A direct action returns its reply, a `LiveReply`, or `Shown` when it posted its own message. A field may be a list of items (`ITEMS`, with `item_fields`), so one request can hold several things; an item says what to do with it (`change_field()`: add, set, remove) and `merge_items` applies a message's changes to an open card, doing the sums. Builds each action's strict schema (every one also has `guessed` and `not_included`), checks what Claude returned against it (`validate`: an item that doesn't fit is left out and named, never dropped unseen), and names what is missing from a task's contract (`problems`). A reference ("it") comes back as `REFERENCE` and is resolved in code (`point_at`; a card keeps what was mentioned last under `LAST`); `as_references` puts a name Claude worked out for a pronoun back as a reference; `unstated` drops any guess whose value the user said outright; a length of time is asked for as whole minutes (`MINUTES`) and a time of day in one fixed form (`TIME`, `TIMES`), the same for every task: `validate` reads a length that comes as words all the same and passes on what it can't read as text, never dropping the item, and `unchosen` takes back an am or pm the message doesn't support; a card's kind is one of `KINDS`; a `Proposal` with `can_save` off is a card with Cancel only, until a reply puts right what its warning names; an action that saves has a `verify` that reads the change back. A task's state for extraction is a `State` (a heading and a line a thing), cut by `shown_state` to `STATE_LINES`, the lines the message could mean first. Holds the catalogue the registry sets. Pure apart from leaving trace notes |
| `routing.py` | The router: one request that says which task a message is for, from the message, what is on screen and the catalogue (never an action or schema). `parse` reads its answer in code: task(s), a tie, chat, or nothing (no reply at all: a remark, a note, a thank-you). `named_destinations` reads a destination the message names ("to my pills") in code, and `with_named` lets it overrule the router |
| `extraction.py` | Extraction: one request for one task, given only that task's actions, which must call exactly one (or `none`; in a follow-up, `not_this`) with a `guessed` list. In a follow-up it gives only the items the message is about, never a total. After the request, code checks what came back: a name worked out for a pronoun is put back, a morning or evening Claude chose by itself is taken back, and a guess that was said outright is no longer one. `read` turns the call into the action, its data and its guesses, or "nothing fitted" with the reason |
| `confirm.py` | Confirm cards: guess, show, confirm. Renders a `Proposal` (task and kind of change, every line, ❓ and ⚠️, Save / Cancel), keeps it as a row (`confirm_cards`) so it survives a restart, replaces one card with its correction (keeping everything said about it and what it was before its last change, so "No, …" can undo that change: `is_correction`), expires it after 30 minutes, and runs the task's `apply` on Save, then its `verify`: the confirmation is only shown if the change reads back from the database, and what the press did is added to the conversation. Also the question asked on a tie, and the rule for when a message sticks to the open card (`sticks`) |
| `livelists.py` | Live lists: the latest copy of a list a user asked to see is kept up to date in place. `show` (or a direct action returning `actions.LiveReply`) posts it and records where it is (`live_lists`); `changed(user_id, key, render)` rewrites that copy in the background through `core/live.py`. Older copies are left as they were. A list also remembers its task and when it was shown: while it is the bot's latest message and under five minutes old, a short message is for that task (`sticks`) |
| `outgoing.py` | The last check on what the bot sends through `cards.py` and `context.py`: an internal label ("(nothing)", an action's name, the pronoun marker, chat's sentinel) is taken out and reported, never sent (`clean`); and a reply never ends with an offer or "want me to…?" (`without_offer`). Pure |
| `conversation.py` | A message in plain words, cheapest first: about the open card (extraction only), anything else (router, then extraction per task), or chat (a plain reply, no tools). Moves a card's items to another task in code on "no, packing", and drops from "Not included" what another card or the plain answer covers (`uncovered`). Hands what was extracted to the task's own code, which writes every word shown; logs the route, tasks, what was extracted, the outcome and each request's cost |
| `cards.py` | Buttons, dropdowns and forms for tasks that may not use discord.py: a task writes a `Card` of plain records (`Button`, `Select`, `Form`) and registers what each action does; the component's id (`card.b:<task>:<action>:<arg>`) carries everything, so cards work after a restart. `handle` answers every press first, checks `is_allowed`, logs it in `message_log` (kind `card`), shows a `UserError` to the presser alone and reports anything else. `post` / `send` / `edit` / `delete` put cards in channels |
| `confirmations.py` | Buttons under a short message: `ask` (Confirm / Cancel) and `choose` (which of a few), for the tasks that still use discord.py directly (archive, timers, dev). In memory, with timeouts |
| `scheduler.py` | Database-backed jobs: `add_job`, a ticker that runs due ones until none is left (`run_all_due`), catch-up at startup (`job.is_late`). Its time is the clock's: when the dev clock jumps, `wake()` runs what came due in order, and time jumped over is not lateness |
| `devmode.py` | Dev mode's in-memory state (the dev clock is not part of it: `clock.py`); other code asks it for values (`reaction_debounce()`, `speed()`, `is_verbose()`, `cleanup_enabled()`, `debug()`, `register_task()`) |
| `interactions.py` | Permission check and logging for slash commands and context menus |
| `llm.py` | The Claude client, with two kinds of request and nothing else: `call_tool` (one request that must come back as a tool call: the router and extraction) and `ask_claude` (plain chat: no tools, no access to the user's data, told so, and told never to offer). Two memories per channel, kept apart: chat's own questions and answers (`history_for`), and what was said and shown (`exchanges_for`), which only the router reads. `ABOUT_DATA` is what chat answers when a message is about the user's data after all |
| `timing.py` | Where the time goes while one message is answered: each request to Claude (and what it was for), each tool, the calls to Discord, rate-limit waits and retries (read from the libraries' logs). One `Turn` per message, found through a context variable; `summary_lines` is the breakdown on the "Message handled" card, and `as_dict` the same as plain values, kept in `message_log.timing` |
| `live.py` | Work nobody should wait for: `schedule(key, refresh)` brings one Live message up to date in the background, one edit however many changes asked for it and at most one every 2 seconds per message; `background(...)` runs anything else after the reply. What they do is not counted in the turn's timing |
| `discord_utils.py` | Binds the client and times every call it makes to Discord; #bot-log cards, `split_message`, `truncate`, `safe_reply`, `report_interaction_error` |

## `tasks/`

| Path | Responsibility |
|---|---|
| `base.py` | The `Task` base class with its hooks (including `message_class`, `new_day`, and for plain words `icon`, `only_for`, `examples`, `show`, `actions()` and `action_state()`), and the self-describing `Keyword`, `ReplyAction`, `Reaction` records (the last two with an optional `validate`). `Reaction.instant` skips the quiet period (🐞 only); `Task.claim(ctx)` takes a message because of where it was sent |
| `registry.py` | Discovers and loads tasks; dispatches words, reply actions and reactions; refuses invalid ones at once; decides how each ends; asks tasks what a message is (`declared_class()`); the single source of what the bot can do (`catalogue()`, `find()`, `capabilities_text()`), and sets the router's catalogue from each task's entries (`actions.set_catalogue`) and the names that may never be sent as text (`outgoing.set_internal_names`). `dispatch_claimed` hands an unmatched message to the task that claims it; an `instant` reaction is applied the moment it is added |
| `builtin/__init__.py` | `ping`, `reset`, `buttons`, `stats`, and `help` generated from the registry |
| `builtin/views.py` | The `buttons` test view |
| `archive/__init__.py` | Registers reply `archive` / `delete`, the 📦 and 🗑️ reactions, the context menu |
| `archive/rules.py` | Pure: what may be archived or deleted, names, embeds, wording |
| `archive/store.py` | The `archive_items` records |
| `archive/messages.py` | The Discord work: webhook repost, delete, confirmation, Restore button |
| `bugs/__init__.py` | Registers `bug` (word and reply), the instant 🐞 reaction, `bugs`, `bugs export`; files a report; claims what is written in a bug's post and saves it as a note. In plain words: `bug_report` ("that's a bug": the last thing before my message, with what I said was wrong as its first note) and `bug_list` |
| `bugs/rules.py` | Pure: ids, what may be reported, a message as plain values (`Snapshot`, `Report`), which logged turn it belongs to, which log lines go with it, and all the wording (post, title, tags, list, `docs/BUGS.md`) |
| `bugs/store.py` | The `bugs_items` and `bugs_notes` records, the history in `bugs_events`, and the channel's recent `message_log` rows for finding the turn |
| `bugs/capture.py` | Puts a report together: the turn, the errors from the tail of `logs/bot.log`, the commit the bot started on. No Discord |
| `bugs/posts.py` | The Discord work, and the only discord.py in the task: reading the reported message, the forum post with its tags, and the opening card: rewritten in place with the status, when it changed and the note count; persistent buttons under it, Fixed / Won't fix on an open bug (tag and archive) and Re-open on a closed one (unarchive, tag Open) |
| `bugs/cli.py` | `python -m tasks.bugs.cli list \| show B4 \| note B4 "…"` for Claude Code's `bug` skill: reads and adds notes straight from the database, never closes a bug |
| `keep/__init__.py` | The 📌 reaction: keep (pin) and unkeep (unpin); reply `pin` / `unpin`, which act at once. All through `core/pins.py` |
| `pills/__init__.py` | Registers `pills` (the read-only Live list) and the task's plain-words entry; works in #inbox and the hub |
| `pills/plain.py` | Setting pills up in plain words: `pill_add`, `pill_edit`, `pill_pause`, `pill_resume`, `pill_remove`, `pill_delete` (each a confirm card, each taking a list of pills) and `pill_list` (read-only, Live). Reads what was said into a plan with `rules.build`, never asking: a time that could be morning or evening is taken as the morning (a latest time as the evening) and flagged, and a planned time moved to keep the gap is a ⚠️ line on the card. Never stopping at the first thing wrong (`settle`): a part that can't be read is a ❔ line with the reason beside everything that was understood, doses that can't fit are a ⚠️ line, and either way the card has no Save until a reply puts it right. A reply's change is laid over the card in code (`overlay`). No discord.py, no Context |
| `pills/rules.py` | Pure: a pill's `Plan` (its name, dose and notes, its `Schedule` from `core/schedule.py`, and optionally a course's dates), building one from a `Request` in the user's words (`build`, which settles a time by the times around it when only one reading keeps them in order, raises `TimeQuestion` for one that could still be morning or evening, moves a planned time that is closer to the one before than the gap and says so, and refuses a schedule that can't fit in a day with `DoesNotFit`, which carries the plan as read so the card can show it, and a part that can't be read with `Unreadable`, which names the part), what a pill is on a day (`status_on`: active, upcoming, paused, ended), which pill a name means (`find`), and all the wording (one-line summary, the card's lines, old-and-new for an edit, the list, the live state for Claude) |
| `pills/doses.py` | Pure: what the day's limit means for a dose, from its schedule alone: whether a dose due then still fits (`fits`), and the time a dose must be taken by for those after it to fit (`take_by`). Not used by the bot yet: the checklist and reminders will |
| `pills/store.py` | The `pills_pills` records and every change to a plan or status (`pills_changes`). (`pills_drafts` is a table of the old previews: no code uses it now) |
| `timers/__init__.py` | Registers `timer`, `timers`, `pause all`, `resume all`, `pomo`, `pomo stats`, the reply actions and job handlers, and the task's plain-words entry |
| `timers/plain.py` | Timers and the Pomodoro in plain words: `timer_start` (a list), `timer_change` (at once; cancelling several asks first with a card), `timer_all`, `timer_list`, `timer_history`, `pomo_start`, `pomo_change`, `pomo_status`, `pomo_stats`, and what extraction is told (every timer and the session with their ids). Posts through `sender(channel_id)`, so the same code runs for a message and a button |
| `timers/control.py` | Changing timers and the session by id, for plain words and for `pause all` / `resume all`: `change_timers` (one id, several, or `all`), `change_session`, `change_all`. What they report is read back from the database after the change |
| `timers/status.py` | Pure: a timer's and the session's state in words, the ids (`t12`, `p4`), several ids in one argument, label matching, and the wording of what a change or `pause all` did |
| `timers/pomodoro.py` | Pure: Pomodoro phases, pause arithmetic, stats (lengths are read by `core/durations.py`) |
| `timers/store.py` | Everything timers remember (`timers_*` tables), including each clock's own speed, the events of every timer and session, and the live lists |
| `timers/timers.py`, `sessions.py`, `board.py`, `common.py` | Timer messages, Pomodoro session cards, the pinned "Active timers" board and the live "Your timers" lists (both rewritten on every change, in the background through `core/live.py`), shared message helpers |
| `dev/__init__.py` | Registers the `dev …` words; `dev mode on\|off` is the one Claude is always offered |
| `dev/panel.py` | The pinned dev panel (with the clock, and "DEV DATABASE" when started with `--dev`), its persistent buttons, the bot's status ("🛠️ Dev mode", "🧪 DEV DATABASE") |
| `dev/clockwords.py` | Pure: what `dev clock <time> \| +<duration> \| reset` moves the clock to (a time is the next moment the clock reads it), and the clock in words |
| `dev/tools.py` | `dev inspect`, `dev status`, `dev jobs`, `dev run`, `dev fire next`, `dev seed`, `dev clean`, `dev cost`, `dev why` (the trace of my last messages), `dev reset-db` (asks, then wipes the dev database and rebuilds it empty) |
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
`permissions`, `scheduler`, `text` (and the chat prompt and plain chat), `outgoing` (nothing internal sent, no offers), `bugs`, `instance_lock`, `backup` (the specs zip), `clock`,
`day` (the boundary and the rollover job), `timeinput`, `schedule` (when each dose is due: the worked example), `occurrences`,
`dev_clock` (`dev clock`, `dev reset-db` and their guards), `actions` (the contract and the checking), `routing` (the router, extraction and the replayed fixtures), `conversation` (a message end to end, confirm cards; on the demo lists of `tests/demo.py`), `livelists`, `costs` (routes, prices, the roll-up and `dev cost`), `trace` (notes, a message in lines, `dev why`), `cards`,
`pills_rules`, `pills_doses`, `timers_plain` and `pills_plain`
(each task's actions in plain words), `golden` (the golden conversations of the conversation standard, end to end, replayed from `evals/fixtures/golden.json`; the ones the bot can't hold yet are marked as gaps), `channels`
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

**Plain words → router → extraction → the task's code** (the one way for
every message that is no shortcut)

1. `main.on_message`, for a message that is no shortcut, in #inbox or the
   hub: 👀 on it, then `conversation.handle`. When that returns the 👀
   comes off (⚠️ in its place if it failed).
1a. **Just a name?** A task's or list's name on its own ("pills", "my
   shopping list": `routing.named_alone`) runs that task's `show` action:
   its list, Live, with no request.
2. **A redirect?** With a card open, a bare "no, shopping"
   (`confirm.redirect`) sends the request on that card to the other
   task's extraction, without the redirect's own words, and the new card
   replaces the old: one request.
2b. **Straight after a list?** If the bot's latest message is the Live copy
   of a list shown in the last five minutes and the message is short
   (`livelists.sticks`), it goes to that list's task's extraction, which
   may still answer `not_this`.
2a. **Follow-up?** If there is an open confirm card and the message is a
   reply to it, or the card is the bot's latest message there and under
   five minutes old (`confirm.sticks`), the message goes straight to that
   task's extraction with the card's data: one request. `not_this` sends
   it on to the router instead.
3. **Router** (`routing.route`): one request with the catalogue. It
   answers with the task(s), a tie, or chat, and, with a task, any part
   of the message that is for no task (`chat_part`): that part gets a
   plain answer first, then the task's card or reply.
4. **Chat:** a plain reply from Claude, which has no tools and no access
   to the user's data (`llm.ask_claude`); a closing offer is trimmed
   (`outgoing.without_offer`). If chat answers that the message is about
   the user's data after all, the router is asked again, told so, and
   the owning task answers; if no task owns it, one neutral line.
4a. **Nothing:** a remark, a note or a thank-you gets no reply.
5. **A tie:** `confirm.ask_which` posts a button per task; the pick runs
   extraction for that task on what was said (`conversation.on_pick`).
6. **Extraction** (`extraction.extract`), one request per task chosen.
   What comes back is checked against the action's schema in code. If
   the router chose the open card's task, extraction is given the card
   as well, so a correction is understood even when it didn't stick. A
   correction (the same action, about the same thing) replaces its card;
   anything else leaves it open.
6a. **Nothing is dropped unseen.** Whatever extraction says it could not
   put into the action (`not_included`), an item that failed validation,
   and an item lost when a card moves to another task, is added to the
   card as "⚠️ Not included: …" (or said after a reply).
7. **The task's code** (`conversation.act`): an action that needs a card
   has `prepare` build a `Proposal` and `confirm.show` post it; Save runs
   `apply` on exactly that data. Any other action has `run` do it and
   return the reply. Nothing Claude wrote is shown.
8. The log row gets the route (`follow-up`, `router`, `chat`), the tasks,
   what was extracted, the outcome, and one `llm_calls` row per request.

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
   the commit the bot started on and the turn's trace (`core/trace.py`:
   what `dev why` shows for it).
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

1. "add iron at 8" (in #inbox or the hub) is routed to pills, and
   extraction fills in `pill_add` with the name and the time as it was
   said. `plain.add_card` has `rules.build` turn that into a `Plan`.
2. The confirm card shows the plan on a line with **Save** and **Cancel**.
   A time that could be morning or evening is taken as the morning and
   marked ❓ (to become a question on the card: see the backlog, G1).
   Planned times closer together than the gap are moved apart, with a
   ⚠️ line saying which dose moved.
3. A reply changes the card: the change is laid over what the card holds
   (`plain.overlay`), the old card is deleted and a fresh one posted.
4. **Save** builds the plan again, checks the name and writes the pill in
   one transaction; `add_check` then reads it back, and only then is
   "✅ Saved" shown. Edit, pause, resume, remove and delete are the same:
   a card each, read back before it is confirmed.
5. `pills`, "my pills" and "show all my pills" show the same read-only
   list, Live: it is rewritten in place when a pill changes.

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
| `users`, `message_log` (every input, with its route, tasks, what was extracted, its trace, requests, tokens, cost and time), `llm_calls` (one row per request to Claude), `confirm_cards` (open confirm cards and tie questions), `live_lists` (where the latest copy of each list shown on request is), `scheduled_jobs`, `reaction_state`, `skill_migrations`, `occurrences`, `occurrence_events` | core (`core/migrations.py`, version in `PRAGMA user_version`) |
| `archive_items` | archive |
| `bugs_items`, `bugs_notes`, `bugs_events` (each closing and re-opening) | bugs |
| `pills_pills`, `pills_drafts` (left from the old previews; unused), `pills_changes` (every plan and status change); doses will be rows of `occurrences` with task `pills` | pills |
| `timers_timers`, `timers_pomodoros`, `timers_focus_log`, `timers_boards`, `timers_events`, `timers_lists` | timers |
| `lab_state`, `lab_tour_runs`, `lab_tour_results` | lab |

Backups go to `data/backups/` nightly at 3am NZ (newest 7 `assistant-*.db`
kept, and the newest 7 `specs-*.zip` of `docs/specs/` taken with them);
`pre-migration-*.db` snapshots are never auto-deleted. The dev database's
go to `data/dev-backups/`, so they never push a real backup out.

## Scaling notes

How the bot is meant to grow. The `new-task` skill reads this first.

- **Shared core blocks over task-specific code.** What two tasks need
  belongs in `core/`: the router, extraction and confirm cards, live
  lists, the occurrence log, the day boundary, time input, the schedule
  model, the scheduler,
  cards and traces. A task holds its own rules, wording and tables, and
  as little else as it can.
- **Core or task: how to decide.** In this order:
  1. How the bot behaves or talks (cards, references, lifecycle,
     wording rules) → core.
  2. Plumbing (the database, the scheduler, the clock, channels,
     traces) → core.
  3. Knowledge about one subject (what a pill is, its rules and its
     words) → the task.
  4. A general tool: core if it is clearly general; otherwise build it
     in the task, cleanly separated (a module of its own that knows
     nothing of the task's subject), and move it to core when a second
     task needs it.
- **What tasks do, so far** (an observation, to revisit): every task
  captures something from me, delivers something to me, or both, and
  most involve time. Timers capture a length and deliver an alert; pills
  capture a plan and will deliver reminders and a checklist; bugs
  capture a report. A new task probably fits the same shape, and what it
  needs for time (when, how often, on which days) should come from core.
- **The router keeps the cost of a message flat.** It sees one line a
  task, never an action or a schema, so a message costs the same with 5
  tasks or 50: one small request to choose, one to fill in.
- **Claude understands; Python acts and replies.** Claude says which task
  and fills in the fields, and never resolves a reference, does a sum or
  writes a word the user reads. Code validates, saves, reads the change
  back, and writes every confirmation.
- **Dev and live are kept apart.** A separate database (`--dev`), the dev
  clock only there, dev bugs numbered and tagged
  apart. Nothing that is for testing can touch the live data.
- **Every capability follows `docs/CONVERSATION.md`.** How the bot talks
  is one standard for every task, checked by its golden conversations
  and, per task, by `task-check`.

## Not built yet

Questions on the card, corrections straight after Save, fewer task ties
and questions that are still sent as their own message: see the gap list
in `docs/BACKLOG.md` (G1, G3, G4, G7), deferred until pills reminders
work. The pills checklist, reminders, corrections and questions (stages 2 to 4
of the pills build order).

The gateway layer (`main.py` and `builtin`'s view still use discord.py
directly), bulk and cross-channel actions for Claude,
quiet hours, the sweep and the summary (`dev
quiet` changes nothing; `dev run sweep|summary` report "not built"), and
to-dos (the list of things to do: called "to-dos" so it is never confused
with the tasks in `tasks/`).
