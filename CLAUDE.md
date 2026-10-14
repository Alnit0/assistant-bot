# CLAUDE.md

The short form. **The rules in full, with reasons and examples, are
`docs/RULES.md`**: read the bracketed section before working in an
area; where the two differ, RULES.md is right.

## Project

A personal AI assistant used through Discord, running 24/7 on a home
server (Windows 11 mini PC, 8 GB). Python 3.14, discord.py, the
Anthropic API, SQLite. One user, built to be multi-user ready.

## Priorities

Most important first, when work is chosen, ordered or cut short (the
hub is my daily overview and a place to talk to the bot; I don't rely
on it for reminders yet):

1. What the hub shows and how it reads: the briefing, the design,
   progress
2. How well it understands what I say
3. Everything else

Notifications and ntfy are low priority.

## Words

- **Task**: one of the bot's features, a folder under `tasks/`.
  **Skill**: only a Claude Code Skill (`.claude/skills/`). **To-dos**:
  the planned list of things to do, never "tasks"
- **Job**: something the scheduler runs; **handler**: what a task says
  to do for a kind of job, never when; **schedule**: a row saying when
  (`core/timetable.py`); **routine**: a schedule with several steps
- An asyncio task is `asyncio.Task`; never name a variable `task` for one
- The bots are **live** and **the dev bot**, never a display name
- **Status line**: the text under a bot's name. **Presence**: the
  online dot. **Nickname**: the name

## Read first

- `docs/NOW.md` first (the SessionStart hook prints it): the batch,
  steps done, in progress and next, drafts, worktrees, what waits on
  me. At most 40 lines, updated after every step, reset to "Idle, last
  batch was…" at a batch's end. History is `docs/STATUS.md`; open
  questions are `docs/QUESTIONS.md` only
- `docs/CONVERSATION.md` is the standard for how the bot talks. It
  outranks this file and every spec: say so when one conflicts
- `docs/ARCHITECTURE.md` is the map: read it before exploring, update
  it in the same change when a file is added, moved or changes its job
- Before working in an area: `docs/DESIGN.md` (how a card looks),
  `docs/INTERFACE.md` (the line to Discord), `docs/DECISIONS.md`
  (before changing architecture), `docs/COSTS.md` (before changing a
  prompt or a schema), `docs/DEVELOPMENT.md` (how to use and extend)
- `docs/specs/` is private: read it, never commit it, never quote it
  in a commit or a public doc
- Procedures are skills: `new-task`, `task-check`, `qa`, `end-of-task`,
  `bug`, and `catchup` (`/catchup`: read-only report at a session's start
  or after a reboot, then wait)

## Never

- Commit or push unless the full test run passed as **the very last
  step before the commit, with no edit of any kind between the two**
  (code, tests, docs, fixtures). If anything changes, run it again.
  Save the output to a file and check the exit code; never pipe it.
  No Co-Authored-By line; no double quote in a commit message
- Commit `.env`, `.env.dev`, `.env.notify`, `data/`, `logs/`, `.venv/`
  or `docs/specs/`; print or log a token, a topic, or the weather's place
- Start `main.py` while the service runs. Stop live for a self-test.
  Pass `--anyway`. Give the dev bot one of my channels, or create one
- Weaken the account check (`core/account.py`), the dev clock's guard
  or `dev reset-db`'s
- Put a pill's name in a notification, a status line or a direct
  message's first line
- Import discord.py in a new task or new core code [Structure]
- Let anything I need to know reach me only through #bot-log
- Add a word list or phrase pattern in Python as the way something is
  understood; add a bare-verb shortcut; touch timer code (frozen)
- Close a bug (I press Fixed), except the self-test's own
- Edit an old migration; block the event loop; hard-code the
  assistant's name or a list of commands or tasks

## How the bot is built [Structure, One way in]

- `core/` never imports from `tasks/` or `interfaces/`.
  `tasks/registry.py` is the one source of what the bot can do
- **Plain words go one way** (`core/conversation.py`): the router picks
  a task (or chat, or nothing), extraction fills in one of its
  actions, and the task's own code does it and writes every word.
  Claude runs nothing. A task's plain-words code is `plain.py` and
  takes a `Request`, never a Context
- **The task contract** (`core/actions.py`): icon, "only for" line,
  examples, actions with fields, `identity` and `on_repeat`, a
  `verify` that reads a change back before it is confirmed, and
  optionally a `summary` (the briefing) and `attention` items (a
  summary alone is fine: weather)
- Claude hands over structured values (`actions.MINUTES`, `NUMBER`,
  `TIME`, `ITEMS`, `REFERENCE`, `DECLINES`); Python does every sum and
  resolves every "it". Names are matched by `core/names.py`, never guessed
- A task never asks in a message of its own: a `Question` on its card.
  Every change to one of my things is a confirm card; only Save writes
- **New code gives plain data to the interface layer**: `core/cards.py`
  (a card), `Context` (a reply), `core/surface.py` (anything else;
  errors `surface.Gone` / `Failed`). Discord's own is
  `interfaces/discord/`; files still importing discord.py are a
  shrinking list in `tests/test_interface.py`
- Everything sent passes `core/outgoing.py`. How a card looks is
  `core/design.py`: a task gives a status, never a colour
- Permissions through `is_allowed(user, action)`. Every record has a
  `user_id`. Task tables are prefixed with the task's name. Schema
  changes are appended migrations. Database calls are awaited
- Logic apart from Discord calls, with tests in the same change

## Time and jobs [Time and jobs]

- The time is `core/clock.py` (`clock.now()`, `config.now_nz()`), never
  `datetime.now()`. The day is `core/day.py`, never `.date()`. Times
  are read and shown by `core/timeinput.py` ("8:04 am")
- **Only the engine knows when** (`core/scheduler.py`): a task gives a
  default schedule and a handler, never books its own next run or
  reads the clock to decide. A run has a key: nothing runs twice. A
  schedule change calls `scheduler.book()`
- A restart loses and repeats nothing (`core/restart.py`); a start
  says nothing in a channel, an unasked restart one catch-up line
- A job never does nothing in silence (`scheduler.note`), has a name
  in words (`scheduler.label`), and a real problem is
  `scheduler.report`. One that raises is run once more a minute
  later: a handler must be safe to run twice
- Nothing may depend on a job having run to be right

## Pills [Pills]

The rules are `docs/specs/pills.md` and RULES.md. Never broken: a
plan never changes unseen; today's checklist is one message written
from the occurrence log, never the record; when a dose is due is
worked out, never stored; a late log, a dose too soon, a time out of
order and a missed dose logged as taken ask first; reminders never
name a pill in what notifies, one prompt a dose, nothing after a
pill's latest time; reminders running out never makes a dose missed;
"that was dose N" moves the log and never adds one.

## Messages, alerts and money [Messages and channels, Notifications]

- Every message has a lifecycle class (`core/lifecycle.py`) and, in
  the hub, a lifetime (`core/messages.py`). Edit in place; delete only
  what lives somewhere else; pinned or 📌 is never swept
- Archive, pin and delete are reactions or reply words, never plain
  words (`reset channel` asks first). Reactions are debounced and
  reversible; 🐞 is the one instant one [Reactions]
- **What needs me** is level 1 of the one ranking
  (`core/attention.py`): "Needs a look", the status line, a ping
  (`core/alerts.py`); a new problem is an item with `PROBLEM`. Not
  urgent: `notify.worth_knowing(line)`. #bot-log stays a record
- **An alert leaves the bot one way**, `core/notify.py`: its kind's
  line in `KINDS` says Discord, ntfy or both, and whether it gets
  through quiet hours (only reminders do). A task never reads the
  quiet hours or the ntfy settings. What a phone shows is neutral
- **Money is shown in NZ$ and recorded in US$** (`core/money.py`):
  `costs.money` for what I read, `costs.usd` for the record
- Answer a press within 3 seconds; buttons survive a restart

## Conventions

- Windows paths and PowerShell; the working copy is CRLF (patch it
  through a script that keeps line endings)
- UK spelling. Short, mobile-friendly replies. Moments in UTC,
  schedules as local time + `Pacific/Auckland`
- Secrets in `.env`; a new setting gets a placeholder in `.env.example`
  and a line in `tests/__init__.py`
- New features behind a switch, off by default, unless I say otherwise
- Anything outward-facing (sending, deleting data) needs my confirmation

## Running and testing [Running and testing]

- `python -m pytest -q` (about 40 seconds; never `-n`): related tests
  while working, the full suite last before a commit (see Never);
  `TESTS_AS_ON_LIVE=1` after a database-layer change. Made-up settings,
  no real data. A test over a minute stops the run: look into it
- The golden conversations (`tests/test_golden.py`) pass before a commit
- Which bots run: `python -m core.instance_lock`, never a process count
- **The self-test** (`python -m selftest`): the dev bot, live left up,
  1.9 GB free at least; if "logged in as" is not the dev bot, stop it.
  Recorded answers unless prompts, schemas or routing changed. Read its
  summary and `data/selftest/history.csv` (logs only for a failure);
  edit nothing while it runs; it sets every switch itself
- **Spend: at most NZ$0.40 a run before asking me**; say what each
  run cost, in NZ$
- At the end of work, `end-of-task`: docs (STATUS, ARCHITECTURE,
  DEVELOPMENT, TESTING, QA-RUN, CHANGELOG; ADVISOR at a batch's end),
  the full test run, the commit. Commit only when asked (a batch says)
- **In a batch, a checkpoint commit after each finished step** whose
  full test run passed (push at the end): a crash loses one step at
  most. Drafts live in `docs/drafts/` (committed) or `docs/specs/`
  (private), never only in a scratchpad
