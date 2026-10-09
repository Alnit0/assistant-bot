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
- **Job**: something the scheduler runs later. **Routine**: what `dev run`
  runs (backup). An asyncio task is always written `asyncio.Task`; don't
  name a variable holding one `task`
- The database keeps two old names, which no migration has renamed: the
  `skill_migrations` table and the `skill` column of `scheduled_jobs`

## Where things are

- **`docs/ARCHITECTURE.md` is the map:** every folder and key file with its
  responsibility, the main data flows and the database tables. Read it
  before exploring the code. Update it in the same change whenever a file
  is added, moved, renamed or changes responsibility
- `docs/DEVELOPMENT.md`: how to use and extend the bot, task by task
- `docs/DECISIONS.md`: read before changing architecture or tools
- `docs/TESTING.md` (test tracker) and `docs/QA-RUN.md` (manual run sheet)
- `docs/specs/` holds the task specs and is private (gitignored; the nightly
  backup is its other copy). Read them, but never commit them, and never
  quote them in commit messages or public docs (everything else in `docs/`)
- Procedures are project skills in `.claude/skills/`:
  - `add-task`: adding or extending anything under `tasks/`
  - `qa`: test tracker, run sheet, and recording reported results
  - `end-of-task`: the closing checklist and commit command
  - `bug`: fixing a reported bug from its id (B4) or a pasted exchange
- Runtime: Windows service `assistant-bot` (NSSM); logs in `logs/`;
  database `data/assistant.db`; backups in `data/backups/`
- `python main.py --dev` runs the same bot on the dev database
  (`data/dev.db`, backups in `data/dev-backups/`): the only place test
  data, `dev clock` and `dev reset-db` are allowed

## Architecture rules

- `core/` never imports from `tasks/`
- `tasks/registry.py` is the single source of what the bot can do (`help`,
  Claude's system prompt and Claude's tools all read it). Never hard-code a
  list of commands or a tool definition
- A typed shortcut carries its task's name ("pill add", `timer 5m`): a
  bare generic verb (add, edit, remove, pause, list…; `core/router.py`
  `GENERIC_VERBS`) is never registered as a word, so "add milk" always
  goes to Claude. Every `Tool` says what it is `only_for` (what tells it
  apart from similar tools in other tasks) and has a `label` in plain
  words; the registry reports one that doesn't
- A tool that shows its own preview or Confirm card sets
  `confirms_itself`: it then has no `propose` argument and can never be
  put behind an "ok". What waits for a button or an "ok" is the call
  itself (tool and structured input), never the user's words
- The user is never shown a tool's name or arguments: a word is shown as
  it would be typed, a `Tool` by its `label`
- Claude runs words and reply actions as tools generated from their
  registrations. A word that takes arguments lists them as `params`; a
  reversible reply action sets `undo`. Tool calls run through
  `registry.run_tool`, never by calling a handler directly
- Ways in, in order of preference: a typed word, a reply action, a
  reaction. Slash commands and context menus are a fallback only
- Every keyword, reply action and reaction needs a description, examples,
  channels and permission. Destructive words are `exact`
- Tasks don't call Discord directly; they use `Context` and core helpers.
  Buttons, dropdowns and forms come from `core/cards.py` (a `Card` of plain
  records, actions registered by name, the record's id in the component's
  id so it works after a restart); `pills` is built this way.
  Only `lab`, `archive`, `timers`, `dev` and `bugs` (in `bugs/posts.py`
  only) may use discord.py, until the gateway layer exists
- The registry decides how every action ends; handlers use `ctx.reply`
  (lasting: Kept) or `ctx.confirm` (self-deleting: Transient) and raise
  `UserError` for problems the user can fix. Code that deletes a message
  by itself checks `lifecycle.deletes(...)` first
- Not every channel holds messages: #bugs is a forum. Code that goes
  through channels (`CHANNELS`), or reads pins or history from a channel
  no message came from, uses `core/channels.py` (`named()`,
  `holds_messages(channel)`), which skips forum, voice and category
  channels
- A task's `startup` failing is logged and shown on the start card; the
  other tasks still start. Keep it that way
- The assistant's name comes from `ASSISTANT_NAME`; never hard-code it
- A pill's plan never changes unseen: adding or editing makes a draft and a
  preview (Save / Edit), and only Save writes it. Removing asks first.
  Keep setup simple: it is rare, and due to be rebuilt
  Claude's pill tools hand over times and dates as the user said them;
  code reads them, and asks rather than guesses
- Permissions go through `is_allowed(user, action)`, never a comparison
  with `OWNER_ID`. Only the owner is allowed anything
- Every record has a `user_id`. Task tables are prefixed with the task's
  name
- Schema changes: append a migration (`core/migrations.py`, or the task's
  `migrations()`); never edit an old one
- Database calls from the event loop are `async`. Always `await` them
- The time comes from `core/clock.py`, never from `datetime.now()` or
  `time.time()`: `scheduler.utc_now()` or `clock.now()` for a moment,
  `config.now_nz()` for NZ time. They follow the dev clock. Only records of
  what really happened (log cards, `message_log`, the instance lock, bug
  reports, dev mode's expiry) use `clock.real_now()` / `real_now_nz()`
- The day comes from `core/day.py` (`today()`, `day_of()`, `at()`,
  `end_of()`), never from a datetime's own `.date()`. Work at the end of a
  day goes in `Task.new_day`, not a job of the task's own at midnight
- Times the user types are read by `core/timeinput.py` and shown with its
  `format_time` ("8:04 am"). An ambiguous time is asked about, never guessed
- Expected things with a state on a day (doses, later reminders and
  routines) are rows in the occurrence log (`core/occurrences.py`), changed
  only through its `db_change` family so every change leaves an event
- The dev clock and `dev reset-db` must refuse to work on the live
  database. Never weaken those guards (`clock.shiftable()`,
  `database.wipe_dev()`)
- A confirmation is only sent after the change has been read back from
  the database and matches: every action with an `apply` has a `verify`
  (the registry refuses one without), and a direct action re-reads inside
  `run`. If it doesn't match, the user is told it didn't save, never that
  it did. What a button press did is added to the conversation
  (`llm.remember`), so the next message is never answered as if the card
  were still waiting
- Archive, pin and delete are done by reaction or reply word only: they are
  not asked for in plain words
- Keep decisions apart from Discord calls so they can be unit tested: logic
  in a module with no Discord calls, called by the Discord-facing code. New
  logic needs tests in the same change

## Conventions

- Python 3.14, virtual environment in `.venv/`
- Windows paths and PowerShell commands (the server runs Windows)
- UK spelling in all user-facing text and docs
- Keep bot replies short and mobile-friendly
- Claude interprets language; code does date and time maths
- Times are shown as `8:04 am` everywhere (12-hour, a space, lower case)
- Times: moments stored in UTC; schedules stored as local time + `Pacific/Auckland`
- Log raw input before processing it
- Anything outward-facing (sending emails, deleting data) needs user confirmation
- Never block the async event loop with slow synchronous work

## Secrets and data

- All secrets live in `.env` (gitignored). Never hardcode or print them
- When adding a setting, add a placeholder to `.env.example` too
- Never commit `.env`, `data/`, `logs/`, `.venv/` or `docs/specs/`

## Running and testing

- Only one copy of the bot may run at a time (`core/instance_lock.py`).
  Never start `main.py` while the user's own copy or the service is running.
  That includes `python main.py --dev`: it is the same bot on another database
- Prefer checks that import the code without starting the bot. Never leave
  a bot process running; confirm with `python -m core.instance_lock`,
  which asks the lock (the source of truth) and says how many bots are
  running. Don't count `python.exe` lines: one bot is two of them (the
  `.venv` launcher and its child, linked by ParentProcessId)
- Routine test run: `python -m pytest -q`. Tests use a temporary database
  and made-up settings, never the real ones
- At the end of every piece of work, follow the `end-of-task` skill: tests, docs,
  then the suggested commit command. Do not commit unless asked
- A suggested commit message never contains a double quote: it breaks the
  command in PowerShell. Use plain words, or a single quote doubled (`''`)

## Interaction rules (apply to every task)

Input
- Typed plain words are the main way in; no slash needed. Unmatched
  messages go to Claude (in #inbox only). Slash commands are a hidden
  fallback only.
- Replying to a message with an action word (archive, pin, keep, save,
  unpin, delete, remind <when>) applies it to that message. Filler words
  are fine on a reply ("pin this", "please archive it").
- "No, <task or list>" said to a card only re-routes that card: the
  request on it is read again for the other task, and the words of the
  redirect are never saved as anything. A correction replaces its card;
  a request for another thing altogether gets a card of its own and
  leaves the first one open.
- One request can hold several things ("add honey, jam and 5 eggs"). An
  action that could ever be asked for in the plural takes a list of items
  (`actions.ITEMS`), never a single one. One card per task lists every
  item, with one Save; different tasks in one message get one card each.
  A reply replaces the card: "make the eggs 6", "remove the jam", "add
  milk too", and "no, packing" moves every item to a packing card.
- Set or add: "make the eggs 7" and "make it 2" set the amount; "add 3
  milk" adds to it. Claude only says which (`actions.change_field()`:
  add, set, remove) and the number I said; Python does every sum
  (`actions.merge_items` on a card, the task's `apply` on Save). A card
  that changes something already on the list shows before → after
  ("eggs · 5 → 7").
- Remove: any task that keeps a list takes "remove the jam", on an open
  card (the line goes) and on the saved list (a card for the change,
  "jam · × 1 → removed"). Removing what is nowhere is said, never
  ignored.
- What "it", "that" or "this one" points at is worked out by Python,
  never by Claude, which only says that a reference was used
  (`actions.REFERENCE`). A Discord reply says it outright: the message
  replied to is what I mean, for everything (a card, a timer, "make it
  2", and `dev why 3` as a reply is the 3 messages up to and including
  that one). Without a reply it is the last thing I mentioned (a card
  keeps it), or my own newest message; never one of the bot's. If there
  is nothing it could mean, the bot says so.
- What I state always wins. A destination I name ("to my pills", "on the
  shopping list") decides the task outright, whatever is on screen
  (`routing.named_destinations`). Anything I state (a dose, a time, an
  amount, a note) is used exactly and never marked ❓
  (`actions.unstated`). Context only fills in what I left out.
- A message that asks nothing and needs nothing done ("note one",
  "thanks", "ok") gets no reply at all.
- One format for a change on every card: `field · old → new` ("eggs · 5 →
  7", "schedule · daily at `8:00 pm` → daily at `9:00 pm`", "Iron · active
  → paused until 20 Oct", "jam · × 1 → removed").
- A correction undoes the mistake: "No, …" straight after a change to a
  card reverts that change and then applies the correction, so nothing
  of the wrong change is left. A card keeps what it was before its last
  change (`confirm_cards.previous`) for this.
- Nothing is ever dropped without a word. Whatever part of a message
  can't be put on a card or done is said on it: "⚠️ Not included: …".
  Only for a part that nothing covers: what another task's card or the
  plain answer deals with is not listed (`conversation.uncovered`).
  This holds in code too: an item that fails validation, or is lost when
  a card moves to another task, is reported, never discarded.
- ❓ marks a genuine guess only: a time that could be morning or evening,
  a vague amount, a task or field Claude was unsure of. A value left at
  its default (one of something, when no amount was said) is not a guess
  and is never flagged, so ❓ still means something on a card with
  several lines. Code flags with `actions.is_guessed`, never because a
  field was absent.
- A list shown on request counts as context, like an open card: while it
  is the bot's latest message in the channel and under 5 minutes old, a
  short message that follows goes to that list's task ("add milk" after
  "what am I packing?" is for packing). The card names its task, so
  "no, shopping" still corrects it.
- Names are kept exactly as I typed them. Singular and plural of a name
  are the same item when adding to or ticking off a list.
- A message with several parts gets every part dealt with: each task's
  card or reply, and a plain answer for anything in it that is for no
  task ("what's the capital of France, and add milk").
- Asking Claude in plain words works too (#inbox): it runs the same
  actions as tools. It acts on a clear request, asks when unsure, and waits
  for "ok" (2 minutes) when it is only suggesting. Destructive actions always
  ask with Confirm / Cancel.
- One confirmation only. An action that shows its own preview or question
  (a pill's Save / Edit preview, a Confirm card) is called directly: no
  "I'm proposing… reply ok" first. The "ok" is only for actions with no
  preview of their own, and only when Claude is suggesting something I
  didn't ask for. Saying "ok" runs exactly what was proposed.
- Which task is meant: Claude decides from the channel, the recent
  conversation, what I already have and my wording. If more than one
  task fits equally it asks with a button per task and never guesses.
  A typed shortcut names its task ("pill add"); a bare "add …" is never
  a shortcut.
- Replies never show tool names or how a tool was called. Times of day
  are written `8:00 pm`, never `20:00`: every tool and card formats them
  that way itself, and replies are not rewritten afterwards (a timer's
  "05:00 left" is a length of time). A message it picks without my reply is shown
  quoted with a jump link, with Undo if reversible; if several fit, it
  offers buttons instead of guessing. At most 5 tool calls per message.
  Typed words never go through Claude.
- Commands are idempotent: asking for a single-instance thing that
  already exists shows it again instead of failing (`pomo` while a
  session runs re-shows its card; `dev off` when off just says so).
- Bugs are reported with 🐞 on a message or the word `bug` (as a reply:
  that message; alone: the latest exchange in the channel), or by saying
  so ("that's a bug": my own last message, or the one I replied to). A
  note is kept only when I type one: "that's a bug: it was slow" keeps
  "it was slow" as the bug's first note; 🐞 and the word `bug` take none.
  Each bug gets a post in the #bugs forum, and what I write there is
  saved as a note with ✅. Nothing in #bugs is sent to Claude. Claude Code never closes
  a bug: I press Fixed or Won't fix on the post.
- Help is generated from the registry; every keyword, reply action and
  reaction must have a description, examples, channels and permission.

Reactions
- Only the owner's reactions count; the bot ignores its own.
- Every reaction action is reversible: removing the reaction undoes it.
  Destructive actions (archive, delete) are reversible only within the
  debounce window. After that, archived copies carry a persistent
  "Restore" button that reposts to the original channel.
- Eligibility is checked at once, for reactions and reply actions alike
  (e.g. archiving in #bot-log): an invalid action gets ⚠️ plus a short
  self-deleting reason, with no wait. Only valid actions are debounced.
- Reaction actions are debounced globally (REACTION_DEBOUNCE, default
  30s); the bot acts once on the final state of MY reactions compared
  with what was last applied, then adds ✅. When nothing is active on a
  message, the ✅ is removed.
- Archive and delete (by reply, reaction or menu) ask for confirmation
  if the message is pinned, 📌-reacted or saved.
- A reaction action that fails when it runs adds ⚠️ to the message, with
  details in #bot-log; no temporary notes in the channel.
- Exception: 🐞 (report a bug) is instant (`Reaction.instant`). It is not
  debounced, adds no ✅, and removing it does nothing: the report gets a
  post in #bugs and is closed there with Fixed or Won't fix. No other
  reaction may skip the debounce.
- Everything else (messages, buttons, jobs) acts immediately.

Cleanliness
- Every message, the bot's or mine, has a lifecycle class
  (`core/lifecycle.py`). Anything that deletes a message by itself asks
  the policy first:

  | Class | Examples | What happens |
  |---|---|---|
  | Kept | Chats with Claude and its replies, help, explanations, lists, stats, seed instructions, results you'll want to read | Never auto-deleted (until the future nightly sweep); only removed by me (archive, delete) |
  | Live | Dev panel, timer board, Pomodoro card | Edited in place; when finished, collapses to a one-line summary (becomes Kept), or is removed if it has no lasting value (e.g. the dev panel) |
  | Consumed | My command words: reply actions (archive, pin), settings (dev debounce 1), shortcuts whose result is posted | Deleted once actioned successfully; kept with ⚠️ if it failed |
  | Transient | Short confirmations ("📦 Archived"), invalid-action reasons | Delete themselves after a few seconds; stay while `KEEP_CONFIRMATIONS` is on (the default) |
  | Alert | Timer done, Pomodoro phase change, reminders | Stay until acknowledged, then deleted, with the original updated |
  | Protected | 📌-reacted or pinned messages | Never auto-deleted; archive/delete ask for confirmation |

- Rule of thumb: only delete a message when its information now lives
  somewhere else. `dev cleanup off` disables all auto-deletion.
- `KEEP_CONFIRMATIONS` (`.env`, default true) keeps every Transient
  message in place, so what the bot did can be read back. It changes
  nothing else: command messages are still Consumed, and a question left
  unanswered still goes. Send them through `ctx.confirm`, `ctx.note` or
  `lifecycle.delete_after()`, which ask the setting.
- A list shown on request is a Live message (`core/livelists.py`): when
  its data changes, by any route, the latest copy is edited in place.
  Asking again posts a fresh copy, which becomes the Live one; older
  copies are left as they were. A task shows the list with
  `actions.LiveReply(key, text)` (or `livelists.show`) and calls
  `livelists.changed(user_id, key, render)` wherever the data changes.
  The pills checklist uses the same helper.
- A reply that reports a change names what changed and what is left
  ("☑️ Ticked off milk × 3 · still to buy: eggs"), never a bare count
  that could be read as the item's own.
- Edit messages in place rather than posting new ones. Exception:
  anything that must notify me (timer done, Pomodoro phase changes,
  reminders) posts a new message; that alert is deleted once
  acknowledged (button or reply), and the original is updated.
- On success, delete the user's command or reply message and show a
  brief confirmation that deletes itself; on failure, keep it and add ⚠️.
- Pinned or 📌-reacted messages are exempt from cleanup and sweeps.
- Delete Discord's "pinned a message" system notices.
- Lab task tests are exempt from these cleanup rules.

Notifications
- Levels: silent, normal, urgent (@mention in channel), critical (DM).
- Notifications stay in the server. DMs only for critical alerts and
  ignored high-priority nudges; they are short pointers with a jump link
  back into the server: no content, buttons or actions in DMs.
- Quiet hours hold non-critical alerts; repeats are grouped.

Interactions
- Acknowledge every interaction within 3 seconds (defer first if slow).
- Persistent buttons use stable custom_ids and survive restarts.
- Error handlers check whether the interaction was already answered.
