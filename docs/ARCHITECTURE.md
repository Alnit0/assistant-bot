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
| `selftest/` | The self-test (`python -m selftest`, with live stopped): the dev bot run against real Discord in channels of its own, on an empty dev database with the dev clock. `__main__.py` makes the channels, sets the dev database aside and starts the bot once a phase; `phase.py` is one start with the steps run inside it; `phases.py` the steps; `harness.py` what a step can do (type, press, move the clock, read Discord and the database back, a recorded or a real answer from Claude); `discordside.py` the stand-ins for a typed message and a press; `report.py` and `onlyyou.py` write `docs/SELFTEST.md`. Nothing in the bot imports it | `stages.py`: the three stages a run is cut into (day, briefing, tidy), which of them a changed file touches, the commit each last passed on, and the free-memory check before a run. `record.py`: what lasts of a run (a line in `data/selftest/history.csv`, the table in `docs/SELFTEST.md`, the words of the one message in #selftest-log). `bugs.py`: a failing step is a dev bug in the forum, noted when it fails again and marked Fixed when it passes (`data/selftest/bugs.json` says which step has which).
| `evals/` | Fixtures for the router and extraction, the demo lists' included (`fixtures/*.json`: a sentence and what it must come out as, with what the real API last returned), the code that judges them (`fixtures.py`), and the live eval that asks the real API and reports accuracy, time and cost (`python -m evals.live --live`) |
| `docs/specs/` | Private task specs (gitignored, never committed or quoted in public docs); zipped by the nightly backup |
| `docs/` | `STATUS` (where the work stands: read first), `CONVERSATION` (the standard for how the bot talks, with its golden conversations), `ARCHITECTURE` (this), `DEVELOPMENT` (how to use and extend), `DECISIONS` (why), `TESTING` (test tracker), `QA-RUN` (manual run sheet), `QA-TONIGHT` (one ordered run of the blocks that are waiting, written 2026-10-13), `SELFTEST` (the last self-test's report, written by `python -m selftest`), `BACKLOG` (found and not yet finished), `CHANGELOG` (what changed, by date), `CHEATSHEET` (commands), `COSTS` (what the requests to Claude cost, the caching and what is sent); `mockups/` holds card sketches for `dev mock` |
| `.claude/skills/` | Procedures for Claude Code: `new-task` (a new task, from the interview to the build), `task-check` (audit a task against the standard and the contract), `qa`, `end-of-task`, `bug` (fix a reported bug from its id) |
| `.env`, `.env.example` | Secrets and settings (`.env` is gitignored); every setting has a placeholder in `.env.example` |
| `data/` | `assistant.db`, `bot.lock`, `backups/`, `exports/` (a transcript of each channel that was reset; zipped by the nightly backup); with `--dev`: `dev.db`, `dev-backups/`, `dev-clock.json` (all gitignored) |
| `logs/` | `bot.log` (rotating), `service-*.log` (gitignored) |
| `scripts/` | `setup-live-folder.ps1`: run by hand, once, to give the live bot a folder of its own on `main` and point the NSSM service at it (prints each step first; `-WhatIf` only prints). Nothing in the bot uses it |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini` | Dependencies (dev adds pytest) and test settings |

## `core/`

| File | Responsibility |
|---|---|
| `config.py` | Paths, settings from `.env` and their validation, constants, the `CHANNELS` name-to-id map (with `hub`, from `HUB_CHANNEL_ID`, and `commands`, from `COMMANDS_CHANNEL_ID`); `EXPORTS_DIR` and `MOCKUPS_DIR`; `DEV_DATABASE` (started with `--dev`), which picks the database and backup folder; `DAY_BOUNDARY`; `now_nz()` (the bot's clock) and `real_now_nz()` |
| `clock.py` | What time it is: `now()` is the real time plus the dev clock's offset, `real_now()` never moves. The clock can only be moved on the dev database, only forward (`advance`, `advance_to`; `reset` goes back), and its offset is kept in `data/dev-clock.json` across restarts. `skipped_between` is the time a jump passed over. Imports nothing from core |
| `about.py` | What is running: when this copy started (`STARTED`, the real time) and the branch and commit its code was at (`COMMIT`, read from `.git` itself when the bot starts). `dev status` shows both |
| `identity.py` | Who the bot is seen to be: its nickname in the server (the base name on live, "<base> · DEV" on the dev database; #bot-log says so once if Change Nickname is missing) and its status line ("🟢 Live · up 7h · next: nightly backup 3:00 am", "🧪 DEV database · clock +13h", or "⚠️ <job> failed · see #bot-log" until that job next works), looked at again every five minutes and only sent when it reads differently. The words are pure (`nickname`, `status_line`, `next_job`) |
| `costs.py` | What each message cost and how it was handled: the routes (`button`, `shortcut`, `reaction`, `follow-up`, `router`, `chat`, and `tools` for the old way of sending every tool), the price of a request including cached tokens, recording a message's route, tasks and each request to Claude (`db_record`), and adding it up by day, month, route and task for `dev cost` (`split`, `report`). Pure apart from the functions that take a connection |
| `day.py` | The day boundary for every task (`DAY_BOUNDARY`, midnight NZ): `today()`, `day_of(moment)`, `at(day, time)`, `start_of` / `end_of` (UTC, daylight-saving safe), and the rollover job, which tells every `on_new_day` listener (a task's `new_day`) the day that ended and the day it is now, then books the next |
| `durations.py` | Pure: lengths of time, for every task that reads one (timers, pills, dev). `parse_duration` reads the short forms people type (`25m`, `1h30`, `1.5h`, `2 hours`, `1:30`) and, as a safety net, the way people say them ("3 hours apart", "2 and a half hours", "an hour and a half"); `split_duration` takes a length off the front of typed words and leaves the label, reading the short forms only; `format_duration` shows one |
| `timeinput.py` | Pure: dates the user types (`parse_date`: tomorrow, friday, the 20th, 20 Oct; shown by `format_date` / `format_dates`) and times the user types (12-hour, 24-hour, noon / midnight), `AmbiguousTime` with both readings when it could be morning or evening, the checks on a time given for something already done (today, not in the future, not before the previous one), and the one way times are shown (`format_time`: "8:04 am") |
| `schedule.py` | Pure: the schedule model, one shape for everything with a schedule. A `Schedule` is how many a day, a planned time for each (or for the first ones, or none: any time), a minimum gap and a latest time of day; only the first is required. `dues` says when each of a day's is due, from the plan and what was done so far: the later of its planned time and the one before, done, plus the gap (a `Due` also says why: planned, after the one before, any time, or waiting for one not yet done). `limit` is the day's limit (the latest time, or the end of the day) and `spaced` moves planned times apart to keep the gap, saying what moved. Days of the week come here later |
| `hub.py` | Pure: the hub channel (`channel_id()`, from `HUB_CHANNEL_ID`) and how the day's cards are written there, the same for every task: the progress bar (`progress_bar`: "▰▰▱▱▱ 2 of 5") |
| `occurrences.py` | The occurrence log: expected things on a day (`occurrences`) with their state (pending, done, skipped, missed), plan, due time, actual time, and for what the bot closed its `cause` (a word for code, the task's own) and its reason (the words shown: code never reads them), and every change to them (`occurrence_events`, values before and after). Changes made together share a change id: `db_last_change` finds the user's last one and `db_revert` takes it back |
| `trace.py` | What happened to one message, step by step, for `dev why` and bug reports: any code leaves a note while a message is handled (`note`: a check that fired or was skipped), `core/conversation.py` keeps them with the route's reason, the router's answer, the card before and after and how much state was sent (`message_log.trace`), and `lines` / `block` put a logged message into a few plain lines that can be copied whole. Imports nothing from core |
| `logging_setup.py` | Terminal and rotating file logging |
| `account.py` | Is this the account it is meant to be? Every start asks Discord who its token is, over HTTP only, before the lock, the database and the gateway (`check`), and compares it with `BOT_USER_ID` (Tanuki's in `.env`, Testu's in `.env.dev`): a wrong account, or no id set, logs why and exits with code 4 having touched nothing; once connected it looks again and disconnects at once (`still_right`) |
| `instance_lock.py` | Single-instance lock on `data/bot.lock`, taken first thing at startup, and the source of truth for what is running: `holder()` asks the lock, `instances()` counts bot processes without the `.venv` launcher, `status()` puts both into words (`python -m core.instance_lock`, `dev status`) | The lock is one a bot: `bot.lock` for live's account, `bot-dev.lock` for the dev bot (a token of its own in `.env.dev`), so the two run at the same time; the status counts both.
| `database.py` | `connect()`, `wipe_dev()` (deletes the dev database and refuses any other), the async `message_log` helpers (`log_received`, `log_result`, `recent_log` for looking further back), `run(func)` in a worker thread |
| `migrations.py` | Numbered schema migrations, core and per task, applied at startup |
| `backup.py` | Nightly backup (a scheduler job that books its successor): the database, and `docs/specs/` and `data/exports/` each as a zip beside it; pre-migration snapshots. A backup that could not be saved whole is recorded as a failed job |
| `users.py` | The `User` record, `ensure_owner()`, cached lookup by Discord id, and `get_user` by our own id |
| `missed.py` | What I said while the bot was off. A note that the bot is running, twice a minute (`bot_alive`, real time); on start every named channel that holds messages (but #commands) is read back to that note, and each message of mine not seen or logged gets a card, “I was offline when you sent this”, with Handle it now (taken by `main._take` as if just sent) and Ignore; one card a message ever (`missed_messages`), the latest 20 after a long stop, nothing acted on without the press |
| `restart.py` | Starting again after a restart or a crash (see **What survives a restart**). Its lines for #bot-log pass the same check as everything the bot says (`checked`: no internal label, no job by its kind). `catch_up()`, once from `on_ready`: every input still "received" in `message_log` from before this start was cut off half way, so it is marked interrupted, a message of mine gets ⚠️ in place of 👀, and a button press is put right by its task if the task said how (`on_cut_off`); then the scheduler's own catch-up runs. A task that does something late at start says so with `caught_up`, and everything goes in one message in #bot-log ("🔁 Caught up after a restart"); with nothing to say, nothing is posted. Keeps no state of its own |
| `permissions.py` | `is_allowed(user, action)`: the one permission check |
| `errors.py` | `UserError`: a problem the user can fix |
| `context.py` | `Context` handed to tasks for a typed word, reply action or reaction: user, channel, args, `reply` (Kept) / `confirm` / `note` (Transient), database, #bot-log; `posted` counts what a handler put in the channel; `parent_channel_id` is the forum or channel a post or thread hangs off. Everything it sends passes `core/outgoing.py`. With `housekeeping` set (by the registry, from the registration) what `confirm` and `note` say always tidies itself away |
| `lifecycle.py` | The message lifecycle: the six classes and their policy, `classify(...)`, and `deletes(...)` / `delete_after()`, which everything that deletes a message by itself asks first (`dev cleanup off` says no). `KEEP_CONFIRMATIONS` makes `delete_after()` leave every Transient message in place, except housekeeping's: `tidy_after()` is how long a line about deleting, archiving, pinning or resetting stays (about 10 seconds), kept confirmations or not |
| `router.py` | Matches typed words and phrases, with typo tolerance; sets filler words aside for reply actions ("pin this"); `GENERIC_VERBS` are the verbs no shortcut may be on its own (add, edit, remove, pause…) |
| `reactions.py` | Pure: which reaction changes count, which are checked at once, where they ended up, what to apply or undo; the `reaction_state` queries |
| `debounce.py` | `Debouncer(delay, callback)`: one quiet-period timer that hands over all collected events together |
| `protection.py` | Pure: is a message protected (pinned or 📌), is it kept, and the wording when Discord refuses a pin |
| `channels.py` | Which channels hold messages: `holds_messages(channel)` (text, news, threads, DMs; not forum, voice or category) and `named()`, the channels from `.env` that do. Asked before reading pins or history from a channel no message came from |
| `clearing.py` | Emptying a channel, for tasks that may not call Discord: `scan` reads every message (who wrote it, what it says, links to its attachments, and whether it is pinned or 📌), or says which permission is missing; `delete` removes the ones asked for, a hundred at a time where Discord allows and one by one otherwise, and says which are gone; `note` posts the closing line that tidies itself away |
| `mirror.py` | A channel that shows exactly a given list of messages (#commands): `sync(channel, texts)` reads the bot's messages there and leaves them alone if they read the same, edits in place the ones that differ, or writes the list again when there are more or fewer. Nothing is stored: the channel is the record. `plan` is the pure half |
| `tidy.py` | Deleting a line later in a way that survives a restart: `later(channel, message, seconds)` books a scheduler job, and the job deletes the message. Every housekeeping line goes this way; a line whose time came while the bot was off is deleted when it starts. `pointer(channel, text)` posts a line that only says where to look ("Today's checklist is in #hub") and books it to go the same way |
| `pins.py` | `set_pinned(...)`: native pin and unpin for tasks that may not call Discord |
| `actions.py` | The contract for plain words: an `Entry` (a task as the router knows it: name, icon, "only for", examples, and its `identity` and `on_repeat` for adding what is already there: `core/repeats.py`), its `Action`s (the fields Claude fills in; `prepare` + `apply` for one that needs a card, `run` for one that acts at once, all three with `card_if` for one that only sometimes asks first) and the `Proposal` a card shows, which may carry one `Question` (its words and a `Choice` for each likely answer: a label and the action's data with that answer in it). A direct action returns its reply, a `LiveReply`, or `Shown` when it posted its own message. A field may be a list of items (`ITEMS`, with `item_fields`), so one request can hold several things, and an item may hold a list of words from a fixed set (`LIST` with `choices`: the settings to clear from a pill); an item says what to do with it (`change_field()`: add, set, remove) and `merge_items` applies a message's changes to an open card, doing the sums. Builds each action's strict schema (every one also has `guessed` and `not_included`), checks what Claude returned against it (`validate`: an item that doesn't fit is left out and named, never dropped unseen), and names what is missing from a task's contract (`problems`). A reference ("it") comes back as `REFERENCE` and is resolved in code (`point_at`; a card keeps what was mentioned last under `LAST`); `as_references` puts a name Claude worked out for a pronoun back as a reference; `unstated` drops any guess whose value the user said outright; a length of time is asked for as whole minutes (`MINUTES`) and a time of day in one fixed form (`TIME`, `TIMES`), the same for every task: `validate` reads a length that comes as words all the same and passes on what it can't read as text, never dropping the item, and `unchosen` takes back an am or pm the message doesn't support; a decline names its kind (`DECLINES`: already so, can't, unclear) in the `none` tool, and for "already so" what it is about, so code never reads the reason's words; an `Entry` may carry `already`, the task's own line for what is already so, and `names`, the names of the user's things it holds; a card's kind is one of `KINDS`; a `Proposal` with `can_save` off is a card with Cancel only, until a reply puts right what its warning names; an action that saves has a `verify` that reads the change back; for #commands an action may say which group it goes in (`purpose`, one of `PURPOSES`) and what one might type for it (`say`, placeholder names only). A task's state for extraction is a `State` (a heading and a line a thing), cut by `shown_state` to `STATE_LINES`, the lines the message could mean first. Holds the catalogue the registry sets. Pure apart from leaving trace notes |
| `names.py` | Pure. (Its `words` are also what the router's hint is made of: `routing.name_hints`, a word typed that starts a word of the name of something a task holds, from four letters, given to the router with the task and never the name; the router still decides.) What was typed is read beside what Claude handed over (`said_about`: the parts of a message that are words of a thing's name, or the start of one; `unclear`: the question to ask when such a part fits more than one thing, whatever name or "it" Claude returned). And: which of a task's things a name means (`find`: an id such as "pl3" if the task has them, then the whole name, then part of one). More than one fit is `Ambiguous` with the candidates, never a guess; none is `Unknown`; nothing named is `Unnamed`. The task writes the words. Used by pills (`rules.find`) |
| `streaks.py` | Pure: a streak worked out from rows of the occurrence log (`streak`, `by_item`): days in a row with something done and nothing missed. Only a missed occurrence breaks one; a skip (by hand or by the bot, whatever its cause), a day with nothing expected and what is still waiting today neither break nor add. Nothing is stored or shown yet |
| `repeats.py` | Adding something that is already there, for every task. A task declares its `identity` (the fields that make two items the same) and `on_repeat` (update, add_to_amount, allow_another, ask, show_existing); this file does the matching (`find`, `key`), says what a request to add comes to (`decide`: new, same, change, more, another, question, existing), checks the declaration (`problems`: `ask` is refused until cards can ask; an identity may name `MESSAGE`, the message a thing is about, which is no field) and writes the words every task says about it (`already`, `there_line`, `logged_already`, `change_line`: `field · old → new`). Pure |
| `routing.py` | The router: one request that says which task a message is for, from the message, what is on screen and the catalogue (never an action or schema). `parse` reads its answer in code: task(s), a tie, chat, or nothing (no reply at all: a remark, a note, a thank-you). `named_destinations` reads a destination the message names ("to my pills") in code, and `with_named` lets it overrule the router; `names_item` says whether a message names one of the user's things, whole; the router also marks a message that reports something done (`Route.reports`), which is never chat |
| `extraction.py` | Extraction: one request for one task, given only that task's actions, which must call exactly one (or `none`; in a follow-up, `not_this`) with a `guessed` list. In a follow-up it gives only the items the message is about, never a total. After the request, code checks what came back: a name worked out for a pronoun is put back, a morning or evening Claude chose by itself is taken back, and a guess that was said outright is no longer one. `read` turns the call into the action, its data and its guesses, or "nothing fitted" with the kind of decline and the reason |
| `confirm.py` | Confirm cards: guess, show, confirm, and ask: a `Proposal` with a `question` is drawn with the question under what was understood, a blurple button an answer and Cancel, and no Save; the question is kept with the card (`confirm_cards.question`), `on_answer` makes the card again in place from the answer's data (or runs the action at once when it no longer needs a card), and `answered_in_words` takes the card away when a typed answer was acted on. Renders a `Proposal` (task and kind of change, every line, ❓ and ⚠️, Save / Cancel), keeps it as a row (`confirm_cards`) so it survives a restart, replaces one card with its correction (keeping everything said about it and what it was before its last change, so "No, …" can undo that change: `is_correction`), expires it after 30 minutes, and runs the task's `apply` on Save, then its `verify`: the confirmation is only shown if the change reads back from the database, and what the press did is added to the conversation. Also the question asked on a tie, and the rule for when a message sticks to the open card (`sticks`) |
| `livelists.py` | Live lists: the latest copy of a list a user asked to see is kept up to date in place. `show` (or a direct action returning `actions.LiveReply`) posts it and records where it is (`live_lists`); `changed(user_id, key, render)` rewrites that copy in the background through `core/live.py`. Older copies are left as they were. A list also remembers its task and when it was shown: while it is the bot's latest message and under five minutes old, a short message is for that task (`sticks`) |
| `outgoing.py` | The last check on what the bot sends through `cards.py` and `context.py`: an internal label ("(nothing)", an action's name, the pronoun marker, chat's sentinel) is taken out and reported, never sent (`clean`); a reply never ends with an offer or "want me to…?" (`without_offer`); and a chat reply that opens by acknowledging something done is caught (`acknowledges`) and never sent. Pure |
| `conversation.py` | A message in plain words, cheapest first: about the open card (extraction only), anything else (router, then extraction per task), or chat (a plain reply, no tools). Moves a card's items to another task in code on "no, packing", and drops from "Not included" what another card or the plain answer covers (`uncovered`). When extraction declines, says the line for that kind of decline, and "didn't understand" only when that is what happened: for "already so" the task's own line (`Entry.already`), with core's plain one (`DECLINED`) as the fallback. A message the router calls "nothing" that names one of the user's things (`Entry.names`) goes to the task that holds it instead of being dropped. Hands what was extracted to the task's own code, which writes every word shown; logs the route, tasks, what was extracted, the outcome and each request's cost |
| `design.py` | Pure: how a card looks as Components V2 (`docs/DESIGN.md`). Every colour and spacing value (`COLOURS`, `ACCENTS` by status, the separators), the records of a layout (`Text`, `Box`, `Separator`, `Row`), the shapes (`item`, `standing`, `decision`, `notifying`, `plain`), the limits (`count`, `problem`) and `words`, which reads a drawn card's text back for an archive, a saved copy or a bug report |
| `cards.py` | Buttons, dropdowns and forms for tasks that may not use discord.py: a task writes a `Card` of plain records (`Button`, `Select`, `Form`) and registers what each action does; the component's id (`card.b:<task>:<action>:<arg>`) carries everything, so cards work after a restart. `handle` answers every press first, checks `is_allowed`, logs it in `message_log` (kind `card`), shows a `UserError` to the presser alone and reports anything else. `post` / `send` / `edit` / `delete` put cards in channels. Holds the rule for button colours (green the positive main action, red destructive, blurple every other choice, grey Cancel only, made with `cancel()`): `check` refuses a card that breaks it, and `colour_problem` judges any button by plain values |
| `confirmations.py` | Buttons under a short message: `ask` (Confirm / Cancel) and `choose` (which of a few), for the tasks that still use discord.py directly (archive, timers, dev). In memory, with timeouts. What was confirmed is recorded in #bot-log; asked as `housekeeping`, the line saying how it went always goes after about 10 seconds |
| `messages.py` | Message lifetimes and the tidy that keeps the hub clean, behind `HUB_TIDY` (off: nothing is recorded and nothing is deleted by it). `record` notes a message with its lifetime (replaced, by `slot`: a newer one takes the older one's place at once; day; expiry; kept; with none said, one in the hub lasts the day and one elsewhere has no row); `begin` / `handled` tie what the bot posts in the hub to the message of mine it answers, and both go 2 minutes after the reply; `card_opened` / `card_closed` make them wait for a confirm card and go with it; `remove` is the only place a message is deleted by lifetime (pinned or 📌 kept and not tried again, a copy to `data/exports/tidy-<channel>-<day>.txt` first and nothing deleted without it, three tries, #bot-log only for a failure, nothing with `dev cleanup off`); `tidy` and its two handlers: the morning tidy, first step of the morning routine, and the expiry job |
| `summaries.py` | A summary from each task that has one (the contract's `summary`: `actions.Summary`), gathered for whatever shows them: `gather` (in the catalogue's order, each with a time limit; one that fails or is slow is a section saying it couldn't be read, with the reason in #bot-log; one with nothing to say is left out), `trimmed` (three lines, a length), and `changed` / `on_change`, by which a task says its summary may have changed and whoever shows summaries is told. Knows nothing of the briefing |
| `timetable.py` | Schedules: when the bot does things by itself, as rows that are the user's to change (`schedules`, `schedule_steps`): a wall-clock time in a zone, the days of the week, silent or notify, a channel by its role, on / paused (until a day) / removed, a missed-run rule, and one or more steps (handler names, in order: several make a routine). Pure: `next_occurrence`, `last_occurrence`, `between` (worked out each time from the local date, the time and the zone, so daylight saving never shifts one: a time that doesn't exist runs at the moment the clocks jump to, one that happens twice at the first), `run_key`, `days_text`. Called "timetable" because `schedule.py` is taken |
| `scheduler.py` | **The engine: the only part that knows when.** Each look it makes sure every schedule's next occurrence is booked (`book`: a run for each step, by its key; a default is made into a row once, a locked one follows the code, a run booked for a time the schedule no longer says is taken out), runs what is due, and records how each run ended with its one line (`note`). Of several occurrences the bot was off for only the latest runs, told how many were passed over; a schedule's rule may set one aside as too late (`MISSED`, never trouble). `clock_went_back` frees the keys of runs from a clock that was ahead; `fire` and `run_now` are `dev fire next` and `dev run`, each a run of its own. Each kind of job has a name in words, given when its handler is registered (`register_handler(..., label)`, a task's `job_labels`; `label`), which is what the status line, the start's message and an error card say; `in_words` puts one written the code's way back in words. Database-backed jobs: `add_job`, a ticker that runs due ones until none is left (`run_all_due`), catch-up at startup (`catch_up`: jobs left running by a crash go back in the queue and everything overdue runs, `job.is_late`, before the ticker starts). Standing jobs, the ones booked for "the next time the clock reads X": `ensure` books one or moves one that is booked too late, never one that is overdue; `keep_booked` registers how each is booked and `rebook_standing` books them all again when the clock has gone back or the jobs were wiped. Its time is the clock's: when the dev clock jumps, `wake()` runs what came due in order, and time jumped over is not lateness. How a job ended is kept with it (done, failed, skipped): one that raises has failed, a handler says the rest with `report(job, FAILED \| SKIPPED)`, and `troubled()` names each kind of job whose latest run did not work |
| `devmode.py` | Dev mode's in-memory state (the dev clock is not part of it: `clock.py`); other code asks it for values (`reaction_debounce()`, `speed()`, `is_verbose()`, `cleanup_enabled()`, `debug()`, `register_task()`) |
| `interactions.py` | Permission check and logging for slash commands and context menus |
| `llm.py` | The Claude client, with two kinds of request and nothing else: `call_tool` (one request that must come back as a tool call: the router and extraction) and `ask_claude` (plain chat: no tools, no access to the user's data, told so, and told never to offer). Two memories per channel, kept apart: chat's own questions and answers (`history_for`), and what was said and shown (`exchanges_for`), which only the router reads. `ABOUT_DATA` is what chat answers when a message is about the user's data after all, or reports something the user did (chat can record nothing and must not acknowledge it). `task_answered` / `answering_task` keep which task's own code answered last in each channel, for five minutes: a short message that follows is that task's first |
| `timing.py` | Where the time goes while one message is answered: each request to Claude (and what it was for), each tool, the calls to Discord, rate-limit waits and retries (read from the libraries' logs). One `Turn` per message, found through a context variable; `summary_lines` is the breakdown on the "Message handled" card, and `as_dict` the same as plain values, kept in `message_log.timing` |
| `live.py` | Work nobody should wait for: `schedule(key, refresh)` brings one Live message up to date in the background, one edit however many changes asked for it and at most one every 2 seconds per message; `background(...)` runs anything else after the reply. What they do is not counted in the turn's timing |
| `discord_utils.py` | Binds the client and times every call it makes to Discord; #bot-log cards, `split_message`, `truncate`, `safe_reply`, `report_interaction_error` |

## `tasks/`

| Path | Responsibility |
|---|---|
| `base.py` | The `Task` base class with its hooks (including `message_class`, `owns_message` (which messages are its own: a reply to one is its to read first), `new_day`, and for plain words `icon`, `only_for`, `examples`, `show`, `identity`, `on_repeat`, `actions()`, `action_state()`, `already_so()` and `item_names()`; and `channel_cleared`, for putting its live messages back after a channel reset), and the self-describing `Keyword`, `ReplyAction`, `Reaction` records (the last two with an optional `validate`; any of them may be `housekeeping`, which leaves no trace in the channel). For #commands a `Keyword` has a `purpose`, a task lists its buttons as `ButtonNote`s (`buttons()`), and `testing` marks a task that is not for every day; `reposted` says what a channel reset would post again. `Reaction.instant` skips the quiet period (🐞 only); `Task.claim(ctx)` takes a message because of where it was sent |
| `registry.py` | Discovers and loads tasks; dispatches words, reply actions and reactions; refuses invalid ones at once; decides how each ends; asks tasks what a message is (`declared_class()`); the single source of what the bot can do (`catalogue()`, `find()`, `capabilities_text()`), and sets the router's catalogue from each task's entries (`actions.set_catalogue`) and the names that may never be sent as text (`outgoing.set_internal_names`). `dispatch_claimed` hands an unmatched message to the task that claims it; an `instant` reaction is applied the moment it is added |
| `builtin/__init__.py` | `ping`, `reset`, `buttons`, `stats`, and `help` generated from the registry |
| `builtin/views.py` | The `buttons` test view |
| `builtin/commands.py` | #commands: the pages a person reads, built from the registry and nothing else (`build`: one message a task with its ways in grouped by purpose, one for housekeeping, the testing tasks last; `about` writes a task's "only for" line for a person), and `update`, run when the bot starts, which hands them to `core/mirror.py` |
| `archive/__init__.py` | Registers reply `archive` / `delete`, the 📦 and 🗑️ reactions, the context menu |
| `archive/rules.py` | Pure: what may be archived or deleted, names, embeds, wording |
| `archive/store.py` | The `archive_items` records |
| `archive/messages.py` | The Discord work: webhook repost, delete, confirmation, Restore button |
| `bugs/__init__.py` | Registers `bug` (word and reply), the instant 🐞 reaction, `bugs`, `bugs export`; claims what is written in a bug's post and saves it as a note. No discord.py |
| `bugs/filing.py` | Logging a bug and saving a note, for every way in: nothing is said to be logged or saved until it is read back. No Discord |
| `bugs/listing.py` | The list of open bugs as a Live list (`core/livelists.py`): rewritten in place when a bug is logged, closed, re-opened or gets a note |
| `bugs/plain.py` | In plain words: `bug_report` ("that's a bug": the last thing before my message, with what I said was wrong as its first note) and `bug_list` |
| `bugs/rules.py` | Pure: ids, what may be reported, a message as plain values (`Snapshot`, `Report`), which logged turn it belongs to, which log lines go with it, and all the wording (post, title, tags, list, `docs/BUGS.md`) |
| `bugs/store.py` | The `bugs_items` and `bugs_notes` records, the history in `bugs_events`, and the channel's recent `message_log` rows for finding the turn |
| `bugs/capture.py` | Puts a report together: the turn, the errors from the tail of `logs/bot.log`, the commit the bot started on. No Discord |
| `bugs/posts.py` | The Discord work, and the only discord.py in the task: reading the reported message, the forum post with its tags, and the opening card: rewritten in place with the status, when it changed and the note count; persistent buttons under it, Fixed / Won't fix on an open bug (tag and archive) and Re-open on a closed one (unarchive, tag Open) |
| `bugs/cli.py` | `python -m tasks.bugs.cli list \| show B4 \| note B4 "…"` for Claude Code's `bug` skill: reads and adds notes straight from the database, never closes a bug |
| `briefing/__init__.py` | The briefing, behind `BRIEFING_ENABLED` (off: no actions, no words, no handler, and it joins no routine). One card of every task's summary: `briefing.post`, a step of the hub's morning routine in front of the checklist (`scheduler.join_routine`), posts it without a notification, or as one neutral line written in after when its schedule says notify, and takes the one before it away once the new one is up; `brief me` / `briefing` and "what's on today?" bring the hub's copy up to date in place (a pointer line that goes), or give a Live copy elsewhere; `summary_changed` rewrites every copy in place when a task says its summary changed. It keeps nothing: where its messages are is `live_lists` |
| `briefing/rules.py` | Pure: the briefing as text and as a layout (a standing message, a box a task in the colour of its status, small lines for the hint and the day before, no buttons) |
| `schedule/__init__.py` | My schedule: the task that is only the conversation over the core's engine. The typed words `my schedule` and `schedule`, and four actions: show (the list, Live), change (one or more schedules: time, days with add / set / remove, pause with an optional end or resume, silent or notify, channel), add (another schedule for a handler that has a default) and remove |
| `schedule/plain.py` | Its code, with no discord.py: which schedule a name means (`core/names.py`, what was typed checked too; the card's own "s3"; "it" only when there is one it could be), the change card (`field · old → new` a schedule, what the open card held kept, and "Next after this" from the engine), add (a question on the card when no time was said; one I removed comes back as the same row) and remove (the row is kept as removed). Every save calls `scheduler.book()` and brings the list up to date |
| `schedule/rules.py` | Pure: the list as text and as a layout (a box a schedule, the next to run amber, paused ones together, the bot's own in a small line, no buttons), the change lines, reading days and a pause's end, and what an added schedule is called |
| `channel/__init__.py` | Channel reset: `reset channel` (any channel) and "reset this channel" in plain words post the card that asks (the counts, how slow it will be, what the tasks will post again afterwards (`registry.reposted`), that it can't be undone; Delete all, Delete all unpinned, Cancel). The message that asked and the card go with the rest, or both on Cancel. A press reads the channel again, writes a transcript of it to `data/exports/` (no copy, no deleting), deletes through `core/clearing.py`, forgets the open cards and lists that went, tells every task (`registry.channel_cleared`), says so in a line and in #bot-log. No discord.py |
| `channel/rules.py` | `card_layout`: the asking card as a red box for the new look. Pure: which messages go in bulk and which singly (14 days by the real clock), what is kept, the counts, the transcript and its file name, and every word of the card and the closing lines |
| `keep/__init__.py` | The 📌 reaction: keep (pin) and unkeep (unpin); reply `pin` / `unpin`, which act at once. All through `core/pins.py` |
| `pills/__init__.py` | Registers `pills` (today's checklist, fresh), the task's plain-words entry, the 6:00 am job, the end-of-day work, the Taken / Skip buttons and what kind of message each of its own is; works in #inbox and the hub |
| `pills/plain.py` | Pills in plain words. Setting up: `pill_add`, `pill_edit`, `pill_pause`, `pill_resume`, `pill_remove`, `pill_delete` (each a confirm card, each taking a list of pills) and `pill_list` (read-only, Live). Today: `pill_log` ("took my zinc", "had pill A at 9", "skip magnesium", "I didn't take zinc": done at once, read back, said in a line with what is left; a dose logged after its pill's latest time is asked about first, on a card; a time given for a dose just logged corrects it, old → new; "it" is the pill of the message I replied to, a dose's own or the checklist, and otherwise the pill logged last; a pill Claude guessed at is shown on a card with ❓ first, never logged straight away) and `pill_today` (a fresh checklist). Reads what was said into a plan with `rules.build`, never asking: a time that could be morning or evening is taken as the morning (a latest time as the evening) and flagged, and a planned time moved to keep the gap is a ⚠️ line on the card. Never stopping at the first thing wrong (`settle`): a part that can't be read is a ❔ line with the reason beside everything that was understood, doses that can't fit are a ⚠️ line, and either way the card has no Save until a reply puts it right. A reply's change is laid over the card in code (`overlay`). Adding a pill that is already there is never a second pill: with nothing to change it is said in a line with the pill shown and no card; otherwise the add card shows the change to it, old → new, and Save edits that pill. That line (`already_text`) is the one end of every way of finding that nothing would change: adding what is there (`add_asks`), a change that changes nothing (`edit_asks`), and extraction declining as already so (`already_so`). No discord.py, no Context |
| `pills/rules.py` | Pure: a pill's `Plan` (its name, dose and notes, its `Schedule` from `core/schedule.py`, and optionally a course's dates), building one from a `Request` in the user's words (`build`, which settles a time by the times around it when only one reading keeps them in order, raises `TimeQuestion` for one that could still be morning or evening, moves a planned time that is closer to the one before than the gap and says so, and refuses a schedule that can't fit in a day with `DoesNotFit`, which carries the plan as read so the card can show it, and a part that can't be read with `Unreadable`, which names the part), what a pill is on a day (`status_on`: active, upcoming, paused, ended), which pill a name means (`find`), and all the wording (one-line summary, the card's lines, old-and-new for an edit, the list, the live state for Claude) |
| `pills/today.py` | Pure: the day's doses and the checklist as it is written. A `Dose` is a pill, its occurrence and when it is due today (from `core/schedule.py` and what was taken, worked out each time); `wanted` says which doses a pill has on a day, `doses` puts them in the checklist's order (no time first, then by today's due time), `checklist`, `line`, `dose_text` and `left_text` write them |
| `pills/checklist.py` | The daily checklist, with no discord.py: `post` puts a fresh copy in the hub without a notification, with a Taken / Skip message under it for each dose with no time, and takes the old one away; `refresh` (and `changed`, in the background) brings it up to date in place and posts it again if it has gone; `mark` changes a dose through the occurrence log and reads it back, and `correct` changes the time of one already ticked off; `db_settle` closes what can no longer be taken today every time the day is looked at (`doses.outcomes`), and a job a minute after a pill's latest time looks again; the buttons; the 6:00 am job (a standing job), the post on a late start, and the end of a day (`close_past`: untouched doses are missed, single messages go, the old checklist is written one last time), which the rollover asks for and so does everything that looks at today, so a day is closed even if no job ran |
| `pills/sheet.py` | Today's checklist as Components V2, drawn only when `CARDS_V2` is on: a box a pill in the colour of what is still to do (`status`), the buttons of its next dose inside it, Paused apart; made to fit 40 components by dropping buttons, then folding what is done (`layout`). Its three buttons (Taken, Taken at…, Skip) rewrite the checklist and never remove it; Taken too soon asks first on the same card as saying it |
| `pills/shortcut.py` | The one typed shortcut for logging: `took <pill>`. `claims` takes the message only when what follows is the exact name of one of my pills with a dose still to take; `took` then does what saying it does, through the `pill_log` action's own code (asking first on a card when that would), with no request to Claude |
| `pills/summary.py` | Pills in a few lines for the briefing, from what the checklist itself works out: the checklist's own count, the colour of what is still to do, the next dose with a time, how many have no time, and yesterday in one line from the occurrence log (what the bot set aside is not counted). Reads only |
| `pills/reminders.py` | Reminders, behind `REMINDERS_ENABLED` (off unless set: off, nothing is ever sent or booked, and a prompt left up is removed; on with no hub to post in, that is said once in #bot-log). A dose with a time gets a message of its own at that time: posted as one neutral line ("💊 Routine due · 11:12 am": what the phone shows, never a pill's name), then the pill, the dose, why it is due then, its note, a take-by line when that is within two hours, and the buttons are written into it (an edit notifies nobody). Taken, Skip, Taken at… (a one-box form, the time checked as a time said is; one that is too soon or after the latest time gets the same "Log it anyway?" card through `core/confirm.py`) and Snooze 15m. Left alone it is posted again every 15 minutes, three times, each a fresh message in place of the last, then the dose is missed for good (`cause` ignored). `decide` (pure) says what to do for a dose from what is kept and the clock; `run` does it for everyone and books one job (`pills/remind`) for the next moment; it is called at start, by the job, at a day's end, when a latest time passes and whenever a dose or a plan changes. No discord.py |
| `pills/doses.py` | Pure: what the day's limit means for a dose, from its schedule alone: whether a dose due then still fits (`fits`), and the time a dose must be taken by for those after it to fit (`take_by`). `outcomes` says what becomes of each dose still open as the day goes on: skipped by the bot, with the reason, the moment it can never be in time; missed once the limit has passed if it had its time, or if nothing was taken all day; open again if a correction makes room. `take_by` is not used by the bot yet: reminders will |
| `pills/store.py` | The `pills_pills` records, every change to a plan or status (`pills_changes`), and where the checklist's messages are (`pills_messages`). (`pills_drafts` is a table of the old previews: no code uses it now) |
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
| `dev/mock.py` | `dev mock`: a card sketched in `docs/mockups/<name>.txt` read into plain records (`parse`: containers, text, separators, rows of buttons; every mistake with its line number) and built as a Components V2 message (`layout`), whose buttons only say they are a mock-up. Knows nothing of any task |
| `dev/tools.py` | `dev inspect`, `dev status`, `dev jobs`, `dev run`, `dev fire next`, `dev seed`, `dev clean`, `dev cost`, `dev why` (the trace of my last messages), `dev reset-db` (asks, then wipes the dev database and rebuilds it empty) |
| `lab/__init__.py`, `common.py` | The `lab …` test bench; `common.py` has the `Run` adapters that let one `run_*` function serve a typed word and `/lab` |
| `lab/buttons.py`, `react.py`, `status.py`, `charts.py`, `data.py`, `misc.py`, `channels.py`, `tour.py`, `state.py`, `ratelimits.py` | One Discord feature each: components, reaction timeline, pinned status, charts and their data, notifications / polls / formatting, cross-channel test, the guided tour, the lab's key/value table, rate-limit watching |

Only `lab`, `archive`, `timers`, `dev` and `bugs` (in `posts.py` alone)
use discord.py directly; that moves behind a gateway layer later. Other tasks go through `Context` and
core helpers; `pills` gets its buttons and dropdowns from `core/cards.py`.

## `tests/`

`conftest.py` has the fixtures (`make_db`, `db`, `dev_off`, `owner`,
`stranger`) and gives every test a time limit (`watchdog.py`: one that
runs over a minute stops the run with its name and where each thread
was); `helpers.py` has `DatabaseTestCase`; `__init__.py` sets made-up
settings before `core` loads. One `test_*.py` per area: `router`,
`registry` (loading, help, capabilities), `reactions`, `reaction_keys`,
`debounce`, `live`, `keep`, `archive_rules`, `archive_store`, `durations`,
`pomodoro`, `timer_text`, `timing`, `timer_status`, `timer_freeze` (pause, resume and events against a
database with the clock under test control), `devmode`, `dev_parsing`, `lab`, `lifecycle`,
`permissions`, `scheduler`, `text` (and the chat prompt and plain chat), `outgoing` (nothing internal sent, no offers), `bugs`, `instance_lock`, `backup` (the specs and exports zips), `clock`,
`day` (the boundary and the rollover job), `timeinput`, `schedule` (when each dose is due: the worked example), `occurrences`,
`dev_clock` (`dev clock`, `dev reset-db` and their guards), `actions` (the contract and the checking), `routing` (the router, extraction and the replayed fixtures), `conversation` (a message end to end, confirm cards; on the demo lists of `tests/demo.py`), `livelists`, `costs` (routes, prices, the roll-up and `dev cost`), `trace` (notes, a message in lines, `dev why`), `cards`,
`pills_rules`, `pills_doses`, `pills_today`, `pills_checklist`, `pills_reminders` (reminders on the dev clock through the real scheduler: the neutral line, the buttons, the reminders, missed, the latest time, a restart), `pills_day` (two whole days on a moved clock, through the real scheduler), `timers_plain` and `pills_plain`
(each task's actions in plain words), `golden` (the golden conversations of the conversation standard, end to end, replayed from `evals/fixtures/golden.json`; the ones the bot can't hold yet are marked as gaps), `channels`
(channel types, the dev panel's start-up sweep, a task failing to start), `channel` (channel reset: what goes and how, the card and both buttons, the Discord work on a fake channel, and the checklist and timers being posted again), `housekeeping` (each housekeeping word as a real reply: one line that goes, the word deleted, #bot-log), `buttons` (the colour of every button there is, on cards and in discord.py views, and a line deleted by its stored job after a restart), `identity` (the nickname and the status line), `commands` (the #commands pages and keeping the channel showing them), `mock` (`dev mock`: reading a sketch, its mistakes by line, the V2 message), `restart` (the bot stopped and started again: the checklist with the bot off at 6:00 am, doses and logs, old buttons, the reset card, and a message, a Save, a reset or a job cut off half way), `repeats` (which things are the same, what a repeat comes to, the words).

## Data flows

**Startup** (`main.py`): `core/config.py` reads `--dev` (which database)
and hands the clock its stored offset → logging → `instance_lock.acquire()`
→ `registry.load()` → `migrate(registry.task_migrations())` →
`ensure_owner()` → connect. `setup_hook` runs each task's `setup`
(persistent views); `on_ready` syncs slash commands, runs each task's
`startup` (builtin's brings #commands up to date), books the backup and
the day rollover, starts the scheduler, and sets the nickname and the
status line (`core/identity.py`).

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
1a. **Just a name?** A task's or list's name on its own, or a plain
   request to see it ("pills", "my shopping list", "show all my pills",
   "what are my pills": `routing.named_alone`) runs that task's `show`
   action: its list, Live, with no request.
2. **A redirect?** With a card open, a bare "no, shopping"
   (`confirm.redirect`) sends the request on that card to the other
   task's extraction, without the redirect's own words, and the new card
   replaces the old: one request.
2b. **Straight after a list?** If the bot's latest message is the Live copy
   of a list shown in the last five minutes and the message is short
   (`livelists.sticks`), it goes to that list's task's extraction, which
   may still answer `not_this`.
2c. **Straight after a task answered?** If a task's own code answered in
   this channel in the last five minutes (`llm.answering_task`) and the
   message is short, it goes to that task's extraction first, told so
   (`after_answer`). Anything but an action sends it on to the router.
2d. **A reply to a message a task posted?** A Discord reply to a dose's
   Taken / Skip message, a timer's card, a checklist (`Entry.owns`, from
   `Task.owns_message`) goes to that task's extraction first, told so
   (`replied`), however old the message. Anything but an action sends it
   on to the router. A task I name in the message still decides. A
   direct action whose reply is about things of the task's own returns
   `actions.Answer(text, placed)`: the task is told which message said
   so and records it (timers: `timers_messages`; pills: `pills_lines`),
   so a reply to that line is the task's too. A card's Save may return
   one as well (`confirm.on_save`): the saved card is then the line.
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
   saved in `bugs_notes` (no ✅: the card's count shows it). Nothing there reaches Claude.
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
   A time that could be morning or evening is asked about on the card
   (`Proposal.question`): ❔ in its place, a button for each reading, and
   no Save until it is answered by a press (`confirm.on_answer` makes
   the card again in place) or by typing.
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

**The daily checklist**

1. At 6:00 am the `pills/checklist` job (or the bot starting later than
   that) makes sure each of today's doses has its occurrence
   (`checklist.db_sync`: one per dose the plan calls for, never a second)
   and posts the checklist in the hub without a notification, with a
   message of its own under it, Taken and Skip, for each dose that has no
   time. Where they are is kept in `pills_messages`.
2. A dose is marked by its button or by saying so ("took my zinc":
   `plain.log_doses`). Both go through `checklist.mark`: the occurrence
   log is changed, read back, and only then is anything said. The dose's
   own message goes and the checklist is edited in place.
3. The checklist is written from scratch every time
   (`today.checklist`): the pills, the day's occurrences, and when each
   dose is due today, which `core/schedule.py` works out from the plan
   and what was taken. A pill added, changed, paused or removed today
   shows at once (`checklist.changed`, in the background).
4. The word `pills` (or "what's left to take today?") posts a fresh copy
   at the bottom and takes the old one and its messages away.
5. When the day ends (`Task.new_day`) what nobody touched is marked
   missed, the single messages are deleted, and the old checklist is
   written one last time and left where it is.

**Channel reset**

1. `reset channel`, or "reset this channel" in plain words: `clearing.scan`
   reads the channel and the card shows the counts. If the bot's role
   lacks Read Message History or Manage Messages the card says so and has
   Cancel only.
2. **Delete all** or **Delete all unpinned**: the channel is read again
   and written, whole, to a text file in `data/exports/`
   (`rules.transcript`: author, time, content, pinned or 📌, links to
   attachments). If that fails nothing is deleted. Then `rules.plan` splits what goes into batches of a hundred (under 14
   days old) and singles (older), and `clearing.delete` does it. The card
   shows the work and goes last.
3. Open confirm cards and Live lists that went are forgotten
   (`confirm.forget`, `livelists.forget`). A closing line is posted, and
   `registry.channel_cleared` tells every task which messages are gone:
   pills posts today's checklist and its Taken / Skip messages again,
   timers the cards of running timers and sessions and the board, dev
   its panel. Each points its records at the new messages; a message
   that was kept is left alone.

**Message lifecycle**

Every message is Kept, Live, Consumed, Transient, Alert or Protected (the
table is in `docs/DEVELOPMENT.md`). `core/lifecycle.py` holds the policy; the places
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
   `dev clock reset` is the one move back: the standing jobs (the
   rollover, the backup, the pills checklist), which were booked for the
   time the clock read then, are booked again for the real time
   (`scheduler.rebook_standing`).
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

## What survives a restart

A restart is the service being restarted or the process dying: the
same thing to the code. Everything that matters is in the database, and
on start `core/restart.py` catches up, says what it did once in
#bot-log, never posts a second copy of anything and never says a thing
was done that wasn't. `tests/test_restart.py` stops and starts the bot
for each row marked ✔. Timers are left out (a proof of concept).

| What | Where it is kept | After a restart |
|---|---|---|
| Pills, their plans, every dose and when it was taken | `pills_pills`, `occurrences`, `occurrence_events` | As they were. A dose is never made twice or reset (`db_ensure`) ✔ |
| Today's checklist and each dose's Taken / Skip message | `pills_messages` (the message ids) | Found again and brought up to date in place: no second copy. One that has gone from the channel is posted again ✔ |
| The 6:00 am checklist, with the bot off at 6 | `scheduled_jobs` (the job is still waiting) | The overdue job posts it at start, once. Start-up leaves it to the job when one is waiting, and posts it itself only when none is. Said in the start's message ✔ |
| A day that ended while the bot was off | `scheduled_jobs` (the rollover), and `checklist.close_past` whatever happens | Closed at start as it stood: what was taken stays taken, the rest is missed or set aside; today starts from the plan ✔ |
| Every line said about a pill or a dose | `pills_lines` | A reply to one still means that pill and dose ✔ |
| Buttons made with `core/cards.py` (Taken, Skip, Save, Cancel, the reset card, the tie question) | Nothing: the button's id carries its task, action and record | Work as before: the handler is found again by name ✔ |
| An open confirm card | `confirm_cards`, and its expiry in `scheduled_jobs` | Save applies exactly what it showed. One that expired while the bot was off goes at start, and can no longer save ✔ |
| The reset card | Nothing: the channel is read again when a button is pressed | Counts and deletes what is there then ✔ |
| A list shown on request (Live) | `live_lists` | Still rewritten in place |
| A bug's post and its buttons | `bugs_items`; the buttons are persistent views | Work as before |
| Jobs (backup, rollover, 6:00 am, tidy, expiry) | `scheduled_jobs` | Each that came due runs at start, late, in due order; one left running by a crash runs again. Listed in the start's message ✔ |
| The dev clock (dev database only) | A file beside the dev database | Still moved |

**Cut off half way.** Every input is written to `message_log` as
"received" before it is handled and given its outcome after, so a row
still "received" from before this start is something the bot was in the
middle of. At start each is marked "interrupted" (so it is found once)
and:

| What was cut off | What happens at start |
|---|---|
| A message of mine | ⚠️ in place of 👀 on it, as on any message that failed; I say it again ✔ |
| Save on a confirm card | Nothing is applied twice. The change is read back (the action's `verify`): if it is there the card is closed and gets the normal confirmation (kept in `confirm_cards.confirmation` the moment the change is applied) with "-# checked after a restart" under it; if not, the card is left open as it was ✔ |
| A channel reset | Nothing more is deleted. The card, left saying "Deleting…", asks again for what is still there; if only its own two messages were left, they go ✔ |
| Any other press (Taken, Skip…) | Reported, and nothing else: what the press had already written is in the database and shows on the checklist at start; pressing again is safe ✔ |
| A job | Runs again from the start. Every job is written to be run twice |

**Lost, by design or not yet handled**

- What was said lately (`llm`'s histories and exchanges, which task
  just answered): the five-minute follow-up starts again, so "it"
  straight after a restart goes to the router ✔
- A reaction made in the 30 seconds before the stop (the debounce is in
  memory): it is not acted on and gets no ✅. Take it off and put it on
  again. Reactions made while the bot is off are not seen at all
- A task waiting for my next message (`registry.expect_message`), and
  dev mode
- A message sent to Discord and not yet recorded when the bot died (the
  checklist between being posted and its id being stored): a few
  milliseconds wide, and it would leave a second copy. Not handled

**Pills reminders across a restart** (`tasks/pills/reminders.py`,
tested in `tests/test_pills_reminders.py`):

- What is kept about a prompt is a row (`pills_prompts`: when it was
  first and last posted, how many reminders have gone, a snooze) and
  one stored job for the next moment anything is due. No time is kept
  in memory
- What to do is worked out each time from the day's doses, that row
  and the clock (`reminders.decide`), never from how many jobs ran. At
  start a dose that is due gets one prompt: the first if it was never
  asked, the next in its turn if it was. Reminders that fell while the
  bot was off are not counted against me, and never sent in a burst
- Nothing is posted after a pill's latest time, however late the bot
  starts, and a prompt still up then is taken down
- A prompt's buttons carry the dose's id: they work after a restart. A
  press cut off is an ordinary cut-off press: the dose is in the
  database or it isn't, and the next look rewrites or removes the prompt
- What was posted at start is said once in the start's message, with a
  count and no pill's name

## Database (`data/assistant.db`; `data/dev.db` with `--dev`)

| Tables | Owner |
|---|---|
| `users`, `message_log` (every input, with its route, tasks, what was extracted, its trace, requests, tokens, cost and time), `llm_calls` (one row per request to Claude), `spend_notices` (the days #bot-log was told the daily spend limit was passed: one row a day, so it is said once), `confirm_cards` (open confirm cards and tie questions), `live_lists` (where the latest copy of each list shown on request is), `scheduled_jobs` (the run log: one row a run, pending until it runs, with its key, the schedule and step it belongs to, the local time it stands for and the line saying what it decided), `schedules` and `schedule_steps` (when things run by themselves: core/timetable.py), `bot_alive` and `missed_messages` (when the bot last noted it was running, and the messages of mine sent while it was off that it asked about: core/missed.py), `bot_messages` (the messages that have a lifetime, with `HUB_TIDY` on: core/messages.py; a row is kept after its message has gone), `reaction_state`, `skill_migrations`, `occurrences`, `occurrence_events` | core (`core/migrations.py`, version in `PRAGMA user_version`) |
| `archive_items` | archive |
| `bugs_items`, `bugs_notes`, `bugs_events` (each closing and re-opening) | bugs |
| `pills_pills`, `pills_drafts` (left from the old previews; unused), `pills_changes` (every plan and status change), `pills_messages` (where today's checklist and each dose's own message are), `pills_lines` (every line said about a pill or a dose: a reply to one says which is meant), `pills_prompts` (each reminder that is up: its message, when it was first and last posted, how many times it was posted again, a snooze); doses are rows of `occurrences` with task `pills` | pills |
| `timers_timers`, `timers_pomodoros`, `timers_focus_log`, `timers_boards`, `timers_events`, `timers_lists`, `timers_messages` (every message about a timer or session: a reply to one says which is meant) | timers |
| `lab_state`, `lab_tour_runs`, `lab_tour_results` | lab |

Backups go to `data/backups/` nightly at 3am NZ (newest 7 `assistant-*.db`
kept, and the newest 7 `specs-*.zip` of `docs/specs/` and `exports-*.zip` of
`data/exports/` taken with them);
`pre-migration-*.db` snapshots are never auto-deleted. The dev database's
go to `data/dev-backups/`, so they never push a real backup out.

## Design

How a card looks is `docs/DESIGN.md`: one style for every task
(headings, small text, a box an item with an accent colour for its
status, separators, the button colours), written for Components V2. Its
colours are not final until they are checked on the phone (block 39 of
`docs/QA-RUN.md`), and every one of them is in `core/design.py`.

A `Card` (`core/cards.py`) may carry a `layout` beside its text and
rows. With `CARDS_V2` on, `cards.send`, `edit`, `post` and a press's
`update` draw the layout (no text beside it); off, or with no layout,
the message is the text and rows it always was. Built this way: the
pills checklist (`tasks/pills/sheet.py`), the reminder
(`reminders.card`: still posted first as the one neutral line, plain,
then drawn by an edit), and the confirm card, the question card and
the card that asks first (`confirm.render`; `Proposal.risky` makes it
amber, `destructive` red). The sketches in `docs/mockups/` are posted
with `dev mock`.

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
- **Language is Claude's job; rules are Python's.** Python never
  interprets free text that Claude could have handed over structured: a
  length of time comes as minutes, a time of day in one form, a kind of
  decline as one of a few named kinds. When code finds itself reading
  wording, the fix is a field in the schema, not another pattern. Word
  lists and phrase patterns in Python are safety nets only: they check
  what Claude returned, catch a form that arrived anyway, or save a
  request for something that needs no understanding (a typed word, a
  list's name). The ones that exist are listed in `docs/BACKLOG.md`,
  each with whether a schema change could replace it.
- **Dev and live are kept apart.** A separate database (`--dev`), the dev
  clock only there, dev bugs numbered and tagged
  apart. Nothing that is for testing can touch the live data.
- **Every capability follows `docs/CONVERSATION.md`.** How the bot talks
  is one standard for every task, checked by its golden conversations
  and, per task, by `task-check`.

## Not built yet

Corrections straight after Save, fewer task ties and the timers' question
that is still sent as its own message: see the gap list in
`docs/BACKLOG.md` (G3, G4, G7). Pills corrections and questions (stage 4 of the
pills build order), streaks, and the take-by line on the checklist. Reminders are built
and switched off (`REMINDERS_ENABLED`) until they pass QA.

Of the scheduler's spec (`docs/specs/scheduler.md`), stage 1 is built
(2026-10-13): the engine, schedules as rows, the run log and its keys
(pruned once a day by the end of the day, `scheduler.prune`: a
housekeeping run after 30 days, any other after a year, never one that
is waiting),
and the backup, the end of the day and the 6:00 am checklist moved
onto it with nothing that shows changed; stage 2, changing a schedule
by words (`tasks/schedule`); and stage 3, the briefing with its summary
in the task contract, behind `BRIEFING_ENABLED`; and stage 4, message
lifetimes with the tidy that keeps the hub clean, behind `HUB_TIDY`
(off, yesterday's checklist is still left in the hub).

The gateway layer (`main.py` and `builtin`'s view still use discord.py
directly), bulk and cross-channel actions for Claude,
quiet hours and the weekly summary (`dev
quiet` changes nothing), and
to-dos (the list of things to do: called "to-dos" so it is never confused
with the tasks in `tasks/`).
