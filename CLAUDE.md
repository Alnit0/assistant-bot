# CLAUDE.md

Guidance for AI assistants working on this repository.

## Project

A personal AI assistant, used through Discord, running 24/7 on a home server
(Windows 11 mini PC). Python bot using discord.py and the Anthropic API, with
SQLite for storage. Single user for now, designed to be multi-user ready.

## Words

- **Task**: one of the bot's features, a folder under `tasks/` (timers,
  archive, keep, …) with a `Task` object. Called "skills" until 2026-10-09
- **Skill**: only a Claude Code Skill, a procedure in `.claude/skills/`
- **To-dos**: the planned list of things to do. Never "tasks"
- **Job**: something the scheduler runs later; one run of one is a row
  of the run log. **Handler**: what a task says to do for a kind of job
  (`pills.checklist`), never when. **Schedule**: a row saying when a
  handler runs (`core/timetable.py`; in the code "timetable", since
  `core/schedule.py` is how often a thing is done in a day).
  **Routine**: a schedule with several steps, and nothing else (until
  2026-10-13 it also meant what `dev run` runs: that is a handler). An
  asyncio task is always written `asyncio.Task`; don't name a variable
  holding one `task`
- The database keeps two old names, which no migration has renamed: the
  `skill_migrations` table and the `skill` column of `scheduled_jobs`

## Read first

- **`docs/STATUS.md` is where the work stands** (branch and state, the
  current goal, the scope freeze, what is next, open decisions). Read it
  at the start of every session, before anything else. The `end-of-task`
  skill updates it at the end of every task
- **`docs/CONVERSATION.md` is the standard for how the bot talks**: its
  principles in their priority order, its context rules, its card rules
  and its always / never list. Every change must follow it. On how the
  bot converses it outranks this file, the routing spec and every task
  spec: if one of them conflicts with it, it wins; say so, and list the
  conflict for me. This file does not repeat it
- **`docs/ARCHITECTURE.md` is the map:** every folder and key file with
  its responsibility, the main data flows and the database tables. Read
  it before exploring the code, and update it in the same change
  whenever a file is added, moved, renamed or changes responsibility.
  Its **Scaling notes** say how the bot grows (what belongs in core and
  what in a task; Claude understands, Python acts and replies; language
  is Claude's job, rules are Python's). Read them before adding anything
- `docs/DEVELOPMENT.md`: how to use and extend the bot, task by task
- `docs/DECISIONS.md`: read before changing architecture
- `docs/DESIGN.md`: how a card looks (headings, small text, accent
  colours by status, separators, buttons), its colours waiting for a
  check on the phone. Built behind `CARDS_V2` (off by default) for the
  pills checklist, the reminder, the confirm, question and
  asks-first cards, and the channel reset card
- `docs/TESTING.md` (test tracker) and `docs/QA-RUN.md` (manual run sheet)
- `docs/COSTS.md`: what each request to Claude costs and why; read it
  before changing a prompt or a schema
- `docs/specs/` holds the task specs and is private (gitignored; the
  nightly backup is its other copy). Read them, but never commit them,
  and never quote them in commit messages or public docs (everything
  else in `docs/`)
- Procedures are project skills in `.claude/skills/`:
  - `new-task`: a new task, from the interview to the build
  - `task-check`: audit a task against the standard and the contract
  - `qa`: test tracker, run sheet, and recording reported results
  - `end-of-task`: the closing checklist and commit command
  - `bug`: fixing a reported bug from its id (B4) or a pasted exchange
- Runtime: Windows service `assistant-bot` (NSSM); logs in `logs/`;
  database `data/assistant.db`; backups in `data/backups/`
- `python main.py --dev` runs the same bot on the dev database
  (`data/dev.db`, backups in `data/dev-backups/`): the only place test
  data, `dev clock` and `dev reset-db` are allowed

## Golden conversations

- The standard's golden conversations **must pass before I am asked to
  commit.** They are `tests/test_golden.py`, replayed offline from
  `evals/fixtures/golden.json` and part of `python -m pytest -q`. One
  marked `gap` is a conversation the bot can't hold yet: it must fail
  until that is built, and the summary names every gap (none at
  present). A golden conversation that passed and now fails blocks the
  commit
- A new golden conversation in the standard gets its fixtures and its
  test in the same change. A task's own conversations are checked
  against the standard by the `task-check` skill

## Architecture rules

### Structure

- `core/` never imports from `tasks/`
- `tasks/registry.py` is the single source of what the bot can do
  (`help`, #commands, the list chat is given of what can be typed, and
  the router's catalogue all read it). Never hard-code a list of
  commands or of tasks
- **New tasks and new core code never import discord.py.** They
  produce plain data (a `Card`, text, a `Request` in) and go through
  the interface layer: `core/cards.py` for a card (plain records,
  actions registered by name, the record's id in the component's id so
  it works after a restart), `Context` for a reply, and **the door,
  `core/surface.py`**, for everything else the core does to the place
  it is used through (send, edit, delete, fetch, history, pin, react,
  the status line, the name). The core never holds the client, never
  calls a method on one of the interface's objects and never catches
  one of its errors: what goes wrong comes back as `surface.Gone` or
  `surface.Failed`. Everything that is Discord's lives in
  `interfaces/discord/` (bound at start, never imported by core or by a
  task). `docs/INTERFACE.md` has the plan and what is still to move
- The files that still import discord.py are a list that only gets
  shorter (`tests/test_interface.py`): in core, `context.py`,
  `discord_utils.py`, `interactions.py`, `confirmations.py` and one
  line of `conversation.py`; in tasks, `base.py` and `registry.py`
  (the typed-word and reaction contract), `archive`, `dev`,
  `bugs/posts.py`, `builtin/views.py`, and for good `lab` (it exists to
  try Discord) and `timers` (frozen: they keep working, are never
  ported, and are scrapped if the bot ever leaves Discord). Never add
  to it; `task-check` looks
- Keep decisions apart from Discord calls so they can be unit tested:
  logic in a module with no Discord calls, called by the Discord-facing
  code. New logic needs tests in the same change
- Permissions go through `is_allowed(user, action)`, never a comparison
  with `OWNER_ID`. Only the owner is allowed anything
- Every record has a `user_id`. Task tables are prefixed with the task's
  name
- Schema changes: append a migration (`core/migrations.py`, or the task's
  `migrations()`); never edit an old one
- Database calls from the event loop are `async`. Always `await` them
- The assistant's name comes from `ASSISTANT_NAME`; never hard-code it
- A task's `startup` failing is logged and shown on the start card; the
  other tasks still start. Keep it that way

### One way in for plain words

- `core/conversation.py`: the router says which task (or chat, or
  nothing), extraction fills in one of that task's actions, and the
  task's own code does it and writes every word. Claude runs nothing and
  has no tools. Which of my things a name means is `core/names.py`
  (never guessed: more than one fit is asked about, and a name Claude
  hands over is checked against what I typed: `names.unclear`); a message's files
  are `request.attachments`. A task's plain-words code is its `plain.py` and takes a
  `Request`, never a Context
- Plain chat (`llm.ask_claude`) answers general questions only. It is
  given its own earlier answers and nothing a task said or holds
  (`llm.exchanges_for` is for the router alone). Anything about my data
  goes to the task that owns it (`llm.ABOUT_DATA` hands it back)
- Everything sent through `core/cards.py` and `core/context.py` passes
  `core/outgoing.py` first (no internal label, no closing offer, no
  acknowledgement from chat)
- **The task contract** (`core/actions.py`, `Entry` and `Action`;
  `actions.problems` refuses a task that breaks it): an icon, an "only
  for" line, examples, its actions with their fields, and what adding
  something that is already there means: `identity` (the fields that
  make two items the same) and `on_repeat` (update, add_to_amount,
  allow_another, show_existing, ask). `core/repeats.py` does the matching and writes
  the words; whether a thing exists is for Python to find out, never a
  reason for Claude to decline. An action that saves has a `verify`
  that reads the change back before anything is confirmed. A task may
  also give a `summary` (an `actions.Summary` for a user and a day: a
  glance, a status, up to three lines): it then appears in the briefing
  with no change there (`core/summaries.py`). A summary only reads,
  asks Claude nothing, and its task says when it may have changed
  (`summaries.changed`)
- Ways in, in order of preference: a typed word, a reply action, a
  reaction. Slash commands and context menus are a fallback only. Every
  keyword, reply action and reaction needs a description, examples,
  channels and permission; destructive words are `exact`. A typed
  shortcut carries its task's name ("pill add"): a bare generic verb
  (`core/router.py`, `GENERIC_VERBS`) is never registered, so "add
  milk" always goes to the router. The one exception, asked for:
  `took <a pill's exact name>` and nothing else
  (`tasks/pills/shortcut.py`); a keyword may be a bare verb only with
  `claims`, which looks first and takes the message only when the rest
  is exactly one of the task's own things. Add no other without being
  asked. Typed words never go through Claude
- The registry decides how every action ends; handlers use `ctx.reply`
  (lasting: Kept) or `ctx.confirm` (self-deleting: Transient) and raise
  `UserError` for problems the user can fix
- A task never asks in a message of its own. What it has to know
  before it can save is a `Question` on its card (`Proposal.question`),
  with each likely answer as a `Choice` holding the action's data with
  that answer in it; core shows it, takes the press or the typed answer
  and makes the card again
- Claude hands over structured values, never my words for code to
  parse: whole minutes (`actions.MINUTES`), a number that need not be
  whole (`actions.NUMBER`), a time of day in one form
  (`actions.TIME`, `TIMES`), a list of items (`actions.ITEMS`) for
  anything that could be plural, add / set / remove
  (`actions.change_field()`), what to take away as a list of settings
  (never a word such as "none" as a value), a reference as `actions.REFERENCE`, a
  decline as one of `actions.DECLINES`. Dates still come as I said
  them. Python does every sum and resolves every "it". Code is the
  safety net (`core/durations.py`, `core/timeinput.py`,
  `actions.unchosen`, `as_references`, `unstated`): the word lists that
  exist are listed in `docs/BACKLOG.md`, and none may grow into the way
  something is understood

### Where the standard lives in the code

| Rule of `docs/CONVERSATION.md` | In code |
|---|---|
| A confirmation only after the change is read back | `Action.verify`; a direct action re-reads inside `run`; `llm.remember` records what a button did |
| What I state wins | `routing.named_destinations`, `actions.unstated`, `actions.restated` (a time) |
| A reply, "it", "that" | `actions.REFERENCE`, `as_references`, `point_at`; `Request.replied_to`; a card keeps `LAST` |
| An open card, a list just shown, the task that just answered, a reply to a message a task posted | `confirm.sticks`, `livelists.sticks`, `llm.task_answered` (`after_answer`), `Task.owns_message` (`replied`), `actions.Answer` |
| Several things in one message; set, add, remove | `actions.ITEMS`, `merge_items`; one card a task |
| Nothing dropped | `not_included`, `conversation.uncovered`, `actions.is_filler`, `whole_part` |
| ❓ a genuine guess only; ❔ and no Save for what can't be read | `actions.is_guessed`; `Proposal.can_save` |
| Card: kind of change, `field · old → new` | `actions.KINDS`, `repeats.change_line` |
| "No, …" undoes the mistake; "no, shopping" re-routes | `confirm.is_correction`, `confirm_cards.previous`; `confirm.redirect` |
| A correction straight after Save is about what was saved | `llm.just_saved`, `confirm.just_saved`, `Request.just_saved` (`actions.Saved`); the task reads it (`plain.just_saved_pill`) |
| Declines; "that is already so" | `actions.DECLINES`, `conversation.DECLINED`, `Task.already_so`, `core/repeats.py` |
| No reply to a remark; never silence for one of my things | the router's "nothing"; `Task.item_names`, `routing.names_item`; part of a name is a hint for the router and never a decision (`routing.name_hints`) |
| A name on its own shows the list, Live | `routing.named_alone`, the task's `show` action, `core/livelists.py` |
| Chat never acknowledges something done | `llm.ABOUT_DATA`, `Route.reports`, `conversation.CANT_LOG`, `outgoing.acknowledges` |
| Reactions are the status (👀, ⚠️; ✅ is reserved) | `main.py`; `conversation.what_i_can_do` |
| Housekeeping leaves no trace; a pointer line goes | `housekeeping=True`, `lifecycle.tidy_after`, `core/tidy.py` (`pointer`) |
| Button colours | `cards.check`, `cards.colour_problem`, `cards.cancel()` |
| Questions on the card: one at a time, a blurple button an answer, no Save until answered, a typed answer too | `actions.Question`, `Choice`, `Proposal.question`; `confirm.render`, `on_answer`, `answered_in_words` |

### Time and jobs

- The time comes from `core/clock.py`, never from `datetime.now()` or
  `time.time()`: `scheduler.utc_now()` or `clock.now()` for a moment,
  `config.now_nz()` for NZ time. They follow the dev clock. Only records
  of what really happened (log cards, `message_log`, the instance lock,
  bug reports, dev mode's expiry) use `clock.real_now()` / `real_now_nz()`
- The day comes from `core/day.py` (`today()`, `day_of()`, `at()`,
  `end_of()`), never from a datetime's own `.date()`. Work at the end of
  a day goes in `Task.new_day`, not a job of the task's own at midnight
- Times the user types are read by `core/timeinput.py` and shown with its
  `format_time` ("8:04 am"), everywhere; a timer's "05:00 left" is a
  length of time
- **Only the engine knows when** (`core/scheduler.py`). Something that
  happens "every day at X" is a schedule: its task gives a default
  (`scheduler.default_schedule`, a `timetable.Default`) and a handler
  that says what to do, and never books its own next run, reads the
  clock to decide whether to run, or keeps the time as a constant that
  is consulted again. The default is made into a row once; after that
  the row is mine (a `locked` one, the bot's own, follows the code)
- A run has a key (its schedule, the local date and time it stands for,
  its step), so nothing runs twice. A one-off job is `add_job`, with a
  `key` when booking it twice would matter. Whatever changes a schedule
  calls `scheduler.book()` after
- A restart loses nothing that matters and repeats nothing
  (`core/restart.py`; "What survives a restart" in
  `docs/ARCHITECTURE.md`): state is in the database, a job is safe to
  run twice, and on start the bot catches up, says so once in #bot-log
  (`restart.caught_up`), never posts a second copy and never says a
  thing was done that wasn't. A press that must not be left half done
  has a recovery (`restart.on_cut_off`)
- Nothing may depend on a job having run to be right: a day that is over
  is closed by the rollover and, failing that, by whatever looks at
  today next (`checklist.close_past`)
- A job has a name in words, given with its handler
  (`scheduler.register_handler(..., label)`, `Task.job_labels`). Its
  kind is the code's own word and is never shown to me: anything I
  read names a job with `scheduler.label`
- A job never does nothing in silence: what it decided and why goes in
  the log every time. #bot-log is for real problems only: one that
  failed or skipped for a real problem says so there and with
  `scheduler.report`; a morning with nothing to do says nothing there
- What I said while the bot was off is never acted on by itself
  (`core/missed.py`): on start each such message in the bot's channels
  gets a card, "I was offline when you sent this", with Handle it now
  and Ignore. One card a message, ever
- Expected things with a state on a day (doses, later reminders and
  routines) are rows in the occurrence log (`core/occurrences.py`),
  changed only through its `db_change` family
- The dev clock and `dev reset-db` must refuse to work on the live
  database. Never weaken those guards (`clock.shiftable()`,
  `database.wipe_dev()`)

### Pills

The rules are in `docs/specs/pills.md` and the Pills section of
`docs/DEVELOPMENT.md`. The ones that must never be broken:

- A pill's plan never changes unseen: every change is a confirm card,
  and only Save writes it
- Today's checklist is one message, edited in place, and never the
  record: a dose is a row of the occurrence log, and the checklist is
  written again from the pills and those rows (`tasks/pills/today.py`,
  `checklist.py`). The 6:00 am post is a fresh copy
  (`checklist.morning_copy`)
- When a dose is due is worked out from the plan and what was taken
  (`schedule.dues`), never stored, and never depends on what time it is
  now. Whether it can still be taken is a separate question
  (`doses.outcomes`)
- A late log, a dose taken before the gap has passed, a time that
  breaks the order or the gap, and a missed dose logged as taken
  ("Dose 1 was missed (due 11:12 am). Log it as taken now?", with what
  it does to the next dose's time), ask first on a card: said, typed
  as `took <pill>` or pressed, through the one check
  (`plain.asked_about`). A time for the dose
  just logged, or a dose named by its number, corrects that dose (old →
  new), never a second one
- A dose of the day before is logged after midnight only as taken
  (`plain._yesterday`). Said in so many words with a time that reads
  one way ("took zinc last night at 11") it is done at once and its
  line says "yesterday"; when the day or the time had to be worked out
  (a time that has not come yet, before 4:00 am; "at 8" with no
  morning or evening; no time at all) it asks first on a card. Which
  day I said is handed over by Claude as a value (`day`), never worked
  out from the time
- A pill may be taken on certain days of the week only
  (`Schedule.days`, `rules.is_taken_on`): no dose is expected on its
  other days, and it is listed under the checklist with its days ("Not
  today"), never counted. The days come as a list (`weekdays`)
- Looking back is read from the occurrence log and writes nothing
  (`tasks/pills/history.py`): a day that is over, the week (Monday to
  Sunday), and the streak, counted in days, one for all pills, broken
  only by a missed dose, shown from two days up. The weekly summary is
  behind `WEEKLY_SUMMARY`: a schedule (Sunday 7:00 pm, the hub), never
  a job of the task's own
- Reminders (`tasks/pills/reminders.py`) are behind `REMINDERS_ENABLED`:
  off, nothing is ever sent. What notifies never names a pill: the
  message is posted as the neutral line and the pill is written in
  after. One prompt a dose; what to do next is worked out from the
  database and the clock (`reminders.decide`), never counted in memory;
  nothing is sent after a pill's latest time

### Messages and channels

- Every message has a lifecycle class (`core/lifecycle.py`: Kept, Live,
  Consumed, Transient, Alert, Protected; the table is in
  `docs/DEVELOPMENT.md`). Code that deletes a message by itself checks
  `lifecycle.deletes(...)` first. Only delete a message when its
  information now lives somewhere else. Pinned or 📌 messages are never
  swept. `KEEP_CONFIRMATIONS` keeps Transient messages, never
  housekeeping's
- How a card looks is `core/design.py` and nowhere else: a task gives
  a box its status (due, done, missed…), never a colour, and builds a
  layout with `design.item`, `standing`, `decision` or `notifying`. A
  `Card` always has its plain text and rows as well: that is what is
  drawn with `CARDS_V2` off, and what is logged
- With `HUB_TIDY` on, a message in the hub has a lifetime
  (`core/messages.py`: replaced, day, expiry, kept). A task says so
  with `messages.record(message_id, channel_id, lifetime=, slot=)`
  after it sends: a `slot` for a thing there is one of at a time (the
  checklist, the briefing), `messages.DAY` for a line that reports a
  change outside the hub. With nothing said, one in the hub lasts the
  day and one elsewhere is never touched. Only `core/messages.py`
  deletes by lifetime: a copy to `data/exports/` first, pinned or 📌
  kept, nothing said in the channel, #bot-log only for a failure
- Edit in place rather than posting again. What must notify me (timer
  done, a phase change, reminders) posts a new message, deleted once
  acknowledged. A list shown on request is Live (`core/livelists.py`:
  `actions.LiveReply`, `livelists.changed`)
- A reply that reports a change names what changed and what is left
  ("☑️ Ticked off milk × 3 · still to buy: eggs")
- Archive, pin and delete are done by reaction or reply word only, never
  in plain words. The one exception is `reset channel`, which always
  asks first on a card
- A task that keeps a message live in a channel implements
  `Task.channel_cleared` (and `reposted`, for the card that asks)
- Not every channel holds messages: #bugs is a forum. Code that goes
  through channels uses `core/channels.py` (`named()`,
  `holds_messages(channel)`)
- Names are kept exactly as I typed them; singular and plural of a name
  are the same item on a list. Commands are idempotent: asking for a
  single-instance thing that exists shows it again
- Lab task tests are exempt from the clean-up rules

### Reactions

- Only the owner's reactions count; the bot ignores its own
- Eligibility is checked at once (`validate`): an invalid action gets ⚠️
  and a short self-deleting reason. Valid ones are debounced globally
  (`REACTION_DEBOUNCE`, default 30s): the bot acts once on the final
  state of my reactions, then adds ✅
- Every reaction action is reversible: removing the reaction undoes it.
  Archive and delete only within the debounce window; after that the
  archived copy has a Restore button. Both ask first if the message is
  pinned, 📌-reacted or saved
- 🐞 is the one instant reaction (`Reaction.instant`): no debounce, no ✅,
  no undo. No other reaction may skip the debounce
- A reaction action that fails adds ⚠️, with details in #bot-log

### Bugs

- 🐞 on a message, the word `bug` (as a reply: that message; alone: the
  latest exchange), or saying so ("that's a bug: it was slow" keeps "it
  was slow" as the first note). Each bug gets a post in the #bugs forum;
  what I write there is saved as a note. Nothing in #bugs is sent to
  Claude
- The bot files a bug for a problem of its own (a job that did not
  work, its memory use: `core/health.py` asks, `tasks/bugs/system.py`
  files): one for each kind of problem, a note on the open one when it
  repeats, never a second. It never closes one
- Claude Code never closes a bug: I press Fixed or Won't fix on the post.
  The one exception is the self-test's own bugs (`selftest/bugs.py`),
  and only a bug the self-test opened itself: the first step to fail in
  a stage is a dev bug (D number) with what was expected and seen and
  the steps that failed after it, noted when it fails again, and marked
  Fixed by the self-test when the step passes again

### Notifications and interactions

- Levels: silent, normal, urgent (@mention in channel), critical (DM).
  Quiet hours hold non-critical alerts; repeats are grouped
- **An alert leaves the bot one way: `core/notify.py`**
  (`notify.post(kind, channel, card, user_id=, item=, key=, private=)`).
  A task says its kind ("pills.reminder") and the attention item it is
  about, and never decides where it goes: each kind is set to Discord,
  ntfy or both in the one table there (`KINDS`), and a new kind is
  added there. Behind `NOTIFY_NTFY`, with the bot's own topic
  (`NTFY_BOT_TOPIC` in `.env`: a secret, never printed, logged or put
  in an error). Only live pushes; the dev bot never does
- What a phone shows is neutral: the kind's fixed title and the one
  line posted first, which names nothing of mine (`private` is the
  names it must not show; a line that does is not pushed). Tapping
  opens the Discord message
- Quiet hours (`QUIET_HOURS`, in force only with
  `QUIET_HOURS_ENABLED`) are the notify service's and nobody else's:
  in them an alert of any level is posted without a sound, never
  pushed, and kept (`held_alerts`) for the briefing to list until its
  task says it is dealt with (`notify.dealt_with`). The one way
  through is a kind marked `through` in the table: a pill reminder
  always notifies, with its sound. A level 1 alert, when there is
  one, is held like the rest. A task never reads the quiet hours
  itself
- Notifications stay in the server. A DM the bot sends by itself, and
  a push, is a short pointer with a link: no content, buttons or
  actions
- A direct message I send to live is read only with `DMS_ENABLED`
  (`core/dms.py`): mine alone, as #inbox, every reply silent, and never
  with one of my things' names (a pill's) in a first line: a neutral
  line goes first. The dev bot never reads one
- Acknowledge every interaction within 3 seconds (defer first if slow).
  Persistent buttons use stable custom_ids and survive restarts. Error
  handlers check whether the interaction was already answered

## Conventions

- Python 3.14, virtual environment in `.venv/`
- Windows paths and PowerShell commands (the server runs Windows)
- UK spelling in all user-facing text and docs
- Keep bot replies short and mobile-friendly
- Times: moments stored in UTC; schedules stored as local time +
  `Pacific/Auckland`
- Log raw input before processing it
- Anything outward-facing (sending emails, deleting data) needs user
  confirmation
- Never block the async event loop with slow synchronous work

## Secrets and data

- All secrets live in `.env` (gitignored). Never hardcode or print them
- When adding a setting, add a placeholder to `.env.example` too
- `.env.dev` (read first with `--dev`, if it is there) gives the dev
  bot a token and channels of its own. Secret like `.env`
- Never commit `.env`, `.env.dev`, `data/`, `logs/`, `.venv/` or `docs/specs/`

## Running and testing

- One copy of each bot may run at a time, and the lock is one a bot
  (`core/instance_lock.py`): live's account has `data/bot.lock`, the
  dev bot (a token of its own in `.env.dev`) has `data/bot-dev.lock`,
  so the two run side by side from this folder. Never start `main.py`
  while the user's own copy or the service is running; `python main.py
  --dev` is the dev bot while `.env.dev` has its own token, and live's
  own account on another database (so never beside live) when it has
  not
- The two bots are **live** and **the dev bot**. Call them that in
  code, docs and messages, never by a display name (I rename bots in
  Discord freely) and never "the test bot": an account is told apart
  by its id (`BOT_USER_ID`), not its name. Every start asks
  Discord who its token is before anything else (`core/account.py`)
  and exits, having touched nothing, unless it is the account in
  `BOT_USER_ID` (`.env` for live, `.env.dev` for the dev bot); the lock is
  taken only after that. Never weaken that check. A process that
  starts a bot gives it `config.environment_for_child()`, never its
  own environment, which holds live's token. When a self-test starts,
  read its "logged in as" line in the first seconds: if it does not
  say "the dev bot" with the dev bot's id, stop it at once. The dev
  bot registers no slash commands, and its bugs have a forum of their
  own
- Three words: the **status line** is the custom status text under a
  bot's name, the **presence** is the online dot (Discord sets it,
  the bot never does), the **nickname** is the name. Use them so, in
  docs and code
- One attention model (`core/attention.py`): tasks hand the core
  attention items through their contract (`Task.attention`: what,
  when, urgency, whether I can act, a link or a bug's id, and the
  short pieces for the status line), the core's own parts register a
  provider (`core/health.py`), and the core ranks them once
  (`attention.ranked`: a problem, due now, next today, useful,
  nothing). The status line shows the top item (`core/identity.py`);
  the briefing takes its order and what is on top from it
  (`tasks/briefing`), and a ping its level (`core/notify.py`). No surface
  ranks anything itself, and a task never says a rank. The status line
  is icon, numbers and short times joined by " · ", never a pill's
  name, blank when there is nothing; it is brought up to date when a
  state changes (`attention.changed()`), never by a ticker
- A bot's nickname is `BOT_NAME` in its settings file, set by me, and
  taken on every start. A suffix only for a real state, always "Name ·
  state": the dev bot is "Name · testing" during a self-test and its
  plain name again after. Live keeps its plain name; its states are in
  the status line. Nothing else renames a bot, there is no "· DEV"
  marker, and a bot's name is never written where a person reads
- Two bots in one server both see everything: each acts only in its own
  channels (`config.mine`). The dev bot takes no channel from `.env`,
  only what `.env.dev` names (the self-test's channels); live leaves
  those alone. The self-test finds its channels by those ids alone,
  never by name, and never creates a channel or a category: a missing
  one stops the run, and I am told. Never give the dev bot one of my real channels
- Prefer checks that import the code without starting the bot. Never
  leave a bot process running; confirm with `python -m
  core.instance_lock`, which asks the lock (the source of truth) and
  says how many bots are running. Don't count `python.exe` lines: one
  bot is two of them (the `.venv` launcher and its child)
- `python -m selftest` starts the dev bot against real Discord
  (`docs/DEVELOPMENT.md`, "The self-test"). Only when I ask. It runs
  as the dev bot, with live left running: never stop live for it.
  Only if `.env.dev` has no token of its own is it live's account:
  then live must be stopped for it, started again after, and checked
  (its status says "🧪 Self-test running · back about <time>"
  meanwhile). Real requests
  to Claude are the exception: answers are recorded unless prompts,
  schemas or routing changed since the last real run, it is the Sunday
  full run, or I ask (`--claude`), and never once the month's self-test
  spend is over `SELFTEST_MONTHLY_LIMIT`. When you run one yourself,
  read its one-line summary and the history
  (`data/selftest/history.csv`) and open logs only for a failure. With
  nothing said it runs only the stages (day, briefing, tidy) touched by
  what changed since each last passed; `--full` is the whole run, about
  fifteen minutes. The PC has 8 GB: it says how much memory is free
  before it starts and stops there when that is low; tell me, and
  never pass `--anyway` without my say. Nothing else is edited or run
  while it is going
- The nightly self-test (`core/nightly.py`, behind `NIGHTLY_SELFTEST`)
  is live starting `python -m selftest --nightly` at 3:00 am as a
  process of its own: the dev bot runs it; nothing on a weeknight with
  no new commits since every stage passed, real requests only on the
  Sunday full run or when prompts, schemas or routing changed. Live
  never waits for it and never reports its steps; a run that could not
  start is a real problem and is said in #bot-log. The phone is pinged
  only for a failing step (`selftest/notify.py`; the topic is never
  printed)
- A test that runs for more than a minute stops the run with its name
  and where it was stuck (`tests/watchdog.py`, exit code 70). Look
  into it; never raise the limit to get past it
- Routine test run: `python -m pytest -q` (about a minute). Tests use a
  temporary database and made-up settings, never the real ones. Don't
  run them in parallel (`-n`): a run hung that way
- Speed: while working, run only the tests related to what is being
  changed (`python -m pytest -q tests/test_x.py`); run the full suite
  once, at the end. Live evals only when I ask, or at a pause where
  fixtures changed
- Spending on Claude: **US$0.25 is the most one run may cost before
  asking me**, each run counted by itself (a live eval, a self-test
  with `--claude`, a rerun of language steps). It is not a limit for
  the day: several runs a day are fine, each under it, and a run that
  would go over it is asked about first. Say what each run cost.
  `DAILY_SPEND_LIMIT` is something else: the bot's own alert in
  #bot-log when a day's spend passes it, which stops nothing
- At the end of every piece of work, follow the `end-of-task` skill:
  tests, docs, then the suggested commit command. Do not commit unless
  asked
- Never commit or push unless the test run before it passed. In
  PowerShell, stop the chain on failure: check `$LASTEXITCODE`, or use
  `&&` in PowerShell 7. Never pipe a test run whose exit code gates a
  commit: if the output must be shortened, save it to a file and check
  the exit code first (or use `set -o pipefail` in Bash)
- A suggested commit message never contains a double quote: it breaks
  the command in PowerShell. Use plain words, or a single quote doubled
  (`''`)
