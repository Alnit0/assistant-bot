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
- Procedures are project skills in `.claude/skills/`:
  - `add-task`: adding or extending anything under `tasks/`
  - `qa`: test tracker, run sheet, and recording reported results
  - `end-of-task`: the closing checklist and commit command
  - `bug`: fixing a reported bug from its id (B4) or a pasted exchange
- Runtime: Windows service `assistant-bot` (NSSM); logs in `logs/`;
  database `data/assistant.db`; backups in `data/backups/`

## Architecture rules

- `core/` never imports from `tasks/`
- `tasks/registry.py` is the single source of what the bot can do (`help`,
  Claude's system prompt and Claude's tools all read it). Never hard-code a
  list of commands or a tool definition
- Claude runs words and reply actions as tools generated from their
  registrations. A word that takes arguments lists them as `params`; a
  reversible reply action sets `undo`. Tool calls run through
  `registry.run_tool`, never by calling a handler directly
- Ways in, in order of preference: a typed word, a reply action, a
  reaction. Slash commands and context menus are a fallback only
- Every keyword, reply action and reaction needs a description, examples,
  channels and permission. Destructive words are `exact`
- Tasks don't call Discord directly; they use `Context` and core helpers.
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
- Permissions go through `is_allowed(user, action)`, never a comparison
  with `OWNER_ID`. Only the owner is allowed anything
- Every record has a `user_id`. Task tables are prefixed with the task's
  name
- Schema changes: append a migration (`core/migrations.py`, or the task's
  `migrations()`); never edit an old one
- Database calls from the event loop are `async`. Always `await` them
- Keep decisions apart from Discord calls so they can be unit tested: logic
  in a module with no Discord calls, called by the Discord-facing code. New
  logic needs tests in the same change

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

## Running and testing

- Only one copy of the bot may run at a time (`core/instance_lock.py`).
  Never start `main.py` while the user's own copy or the service is running
- Prefer checks that import the code without starting the bot. Never leave
  a bot process running; confirm with `python -m core.instance_lock`,
  which asks the lock (the source of truth) and says how many bots are
  running. Don't count `python.exe` lines: one bot is two of them (the
  `.venv` launcher and its child, linked by ParentProcessId)
- Routine test run: `python -m pytest -q`. Tests use a temporary database
  and made-up settings, never the real ones
- At the end of every piece of work, follow the `end-of-task` skill: tests, docs,
  then the suggested commit command. Do not commit unless asked

## Interaction rules (apply to every task)

Input
- Typed plain words are the main way in; no slash needed. Unmatched
  messages go to Claude (in #inbox only). Slash commands are a hidden
  fallback only.
- Replying to a message with an action word (archive, pin, keep, save,
  unpin, delete, remind <when>) applies it to that message. Filler words
  are fine on a reply ("pin this", "please archive it").
- Asking Claude in plain words works too (#inbox): it runs the same
  actions as tools. It acts on a clear request, asks when unsure, and waits
  for "ok" (2 minutes) when it is only suggesting. Destructive actions always
  ask with Confirm / Cancel. A message it picks without my reply is shown
  quoted with a jump link, with Undo if reversible; if several fit, it
  offers buttons instead of guessing. At most 5 tool calls per message.
  Typed words never go through Claude.
- Commands are idempotent: asking for a single-instance thing that
  already exists shows it again instead of failing (`pomo` while a
  session runs re-shows its card; `dev off` when off just says so).
- Bugs are reported with 🐞 on a message or the word `bug` (as a reply:
  that message; alone: the latest exchange in the channel). No note is
  taken in the channel (`bug: text` is not a command): each bug gets a
  post in the #bugs forum, and what I write there is saved as a note
  with ✅. Nothing in #bugs is sent to Claude. Claude Code never closes
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
