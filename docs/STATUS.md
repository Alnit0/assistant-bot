# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-12

## Questions for Alex

- **C7 (pills questions as their own message)** waits for G1, which
  needs your say on how a card asks. I'd put each question on the card
  with a button an answer.
- **C12 (bugs: a message that already has an open bug)**: the contract
  has no word for "show the one there". I'd add a fifth `on_repeat`,
  `show_existing`, and declare it for bugs. Say yes or name it.
- **C15 (pills: whether the bot skipped a dose is read from the
  reason's wording)**: I'd add a `cause` column to the occurrence log
  beside the reason. It touches the dose rules, so I left it for a go.
- **C16 (pills: taking a setting away is the word "none")**: I'd add a
  `clear` list of settings to the action. It changes what Claude is
  asked for, so the pills fixtures need a live run (about US$0.13).
- **C19 (pills: "which of my things does this name mean" lives in the
  task)**: I'd leave it until a second task needs it, as the finding
  says. Confirm, or say to move it to core now.
- **C8, C14, C17, C18 (timers)**: left alone, as timers may be
  scrapped. Say if any should be done anyway.
- **Reminder mock-ups** (block 33): are the four right as sketched?
  Three things I had to choose: the re-nudge says "Reminder 2 of 3"
  with the time of the last one; a snoozed prompt turns grey and says
  "Snoozed until …"; a missed dose is a ❌ line in its pill's group on
  the checklist, with when it was due.
- **The lock screen**: the sketches put "💊 Routine due · 11:12 am" as
  the message's first line. Whether a phone shows that line for a
  Components V2 message can only be seen on your phone (block 33, step
  1). If it shows something else, the prompt has to be a plain message
  with buttons instead: say which you see.
- **"Item 10 (restarts)"**: your note during the batch said to leave
  timers out of item 10, but the queue I was given ends at item 8 and
  has nothing about restarts. Nothing was done for it. Send the item
  and I will leave timers out of it.

## Background batch (unattended, on `feature/pills`)

One commit an item, pushed, each with a block in `docs/QA-RUN.md`
marked "waiting for QA". No live evals were run and the service was
not restarted: the live bot is still on "Send a reply to a task's
message to that task".

1. Done: the standard says what "it" means without a reply (block 27).
2. Done: an unnamed pill is only logged straight away with an anchor;
   otherwise the pill the code picked is on a card with ❓ (block 28).
   The recorded "took the usual one" fixture passes.
3. Done: every line about a pill or a dose is recorded as that pill's,
   and a reply to one means that pill and that dose (block 29).
4. Done: `dev why` shows a reference as "it", is sent as it is, and
   logs no error (block 30).
5. Done: the guessed-length line and the bulk-cancel line are recorded
   as the timers' (block 31).
6. Skipped on your word (timers may be scrapped): numbering a second
   timer of the same name. In the backlog, low priority. From here on
   timer code is only touched if a core change breaks its tests.
7. Done: task-check findings C4, C10, C13 and C20 (block 32). The rest
   are in the questions above.
8. Done: mock-ups for the reminder, the re-nudge, the missed line and
   the too-soon card in `docs/mockups/` (block 33), and the build plan
   below. No code for reminders was written.

### Stage 3 build plan (reminders), for a go

Each step ends with its tests and a QA block on `--dev` with `dev
clock`; nothing is started until the mock-ups are approved.

1. **When a prompt is due** (pure, no Discord): from `schedule.dues`
   and the day's doses, which timed dose needs a prompt now, its
   take-by time when that is within two hours, and nothing after the
   pill's latest time. Tests on the Pill A worked example.
2. **The prompt** as its own message in the hub, one a dose, recorded
   like a dose's Taken / Skip message (`pills_messages`, a new kind) so
   it survives a restart and a channel reset. Taken, Taken at… (a
   one-box form), Skip: each goes through the same code as saying it,
   the prompt is deleted and the checklist follows.
3. **Standing job** (`scheduler.ensure`, `keep_booked`): one job for
   the next prompt due, booked again from the plan after every change.
   What it decided goes in the log each time; a skip says so in
   #bot-log.
4. **Snooze and re-nudges**: 15 minutes, up to three, each a fresh copy
   that replaces the one before (never two prompts for a dose), then
   missed. Prompts ignore quiet hours.
5. **Missed and automatic skips** on the checklist, through
   `doses.outcomes` as today; no reminder after the day's limit.
6. **Too soon**: a dose logged before the gap has passed asks first on
   the card (it already asks for a dose out of order or after the
   latest time: the same card, one more reason).
7. **Privacy**: the notification never names a pill (G14), checked by
   a test on the first line of every prompt.

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- Pills stage 1 is committed: the schedule model in core
  (`core/schedule.py`) with pill setup moved onto it.
- Committed: lengths and times handed over structured, cards with no
  Save for what can't be read or can't fit, a pill that is already
  there, declines that name their kind. Blocks 19 and 20 passed
  (one row, R40, still needs a database with no Pill A).
- Committed: pills stage 2, the daily checklist with dose logging by
  message, and standing jobs that follow the clock. Block 21 is
  still to be reported.
- Committed: channel reset, and housekeeping that leaves no trace.
- Committed: housekeeping lines deleted by a stored job, and the rule
  for button colours. Live since 2026-10-11.
- Committed: part 1 of the work from going live (the bugs from real
  use: follow-ups to the task that just answered, dose numbers, "I
  can't log that yet."), and the 6:00 am checklist as a fresh post.
  Steps 5 to 7 of block 23 (`docs/QA-RUN.md`) are still to be reported.
- Committed: the batch of small backlog items (nickname and status
  line, #commands, `dev mock`, the reset card, pointer lines, exports
  in the backup, time left on a timer). Block 24 passed on the live
  bot, bar step 8 (the morning's backup card, K22), still to be
  reported, and K20, untested until the dev database is next run.
- Committed: the status warns only about real problems (the 6:00 am
  checklist counts as skipped only when the hub can't be found).
- Committed: step 5 of the routing spec (`CLAUDE.md` tidied, `identity`
  and `on_repeat` in the contract, the skills `new-task` and
  `task-check`, and the first `task-check`: C1 to C20 in the backlog).
- Committed and live: the task-check fixes chosen (C1, C2, C3, C5, C6,
  C9, C11). Block 25: steps 3 to 5 passed; steps 1 and 2 are to be run
  on the dev database.
- Committed and live: a reply to a message a task posted goes to that
  task first, in code, with the pills fixtures recorded live.
- Committed (not yet live: the service was not restarted): **every
  message about a timer is recorded as that timer's** (found live: a reply to "⏸️ Paused: dinner"
  went to the router), and **a guessed timer is never acted on** ("Which
  timer? Say its name."). Block 26 is its retest.
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d
  and 2a are marked as gaps (they need questions on the card, G1).
  The live evals of 2026-10-12: pills 56 of 57, general 12 of 12,
  golden 37 of 39 (not run again since the router's rule on reports
  was reworded); each miss is a known one that the code covers. The
  pills fixtures were recorded again on 2026-10-12: 57 of 59, with one
  known miss ("took the usual one" is now right as recorded: the code
  decides).
  One timers fixture has no recording yet.
- Live eval spend to date: about US$4.04.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.
Exceptions asked for: channel reset (2026-10-11, needed before going
live), and on 2026-10-12 the bot's nickname and status line, the
#commands channel and `dev mock`.

## Recently done

- The timer reply fix (2026-10-12): the lines a timer answers with are
  its messages too, and no timer is picked by a guess.
- A reply to a task's message goes to that task first (2026-10-12).
- The task-check fixes (2026-10-12): C1, C2, C3, C5, C6, C9, C11.
- Step 5 (2026-10-12): the standard written into `CLAUDE.md`, the task
  contract and the skills; `task-check` run on timers, bugs and pills.
- A batch of small items (2026-10-12): the bot says which one it is
  (nickname and status line), #commands is written from the registry,
  `dev mock` posts a sketched card, the reset card says what comes
  back, pointer lines go by themselves, exports are in the backup, and
  time left on a timer is said to the second.
- From the first night live: due times that never pass the day's limit
  or creep, doses that can't fit skipped by the bot, a late log asked
  about on a card, and a time said straight after logging taken as a
  correction.

## Next up

1. Block 26 (four steps, live or dev), and steps 1, 2 and 6 of block 25
   on the dev database. Step 8 of block 24 (tomorrow's backup card).
   Blocks 21 and 22, and steps 5 to 7 of block 23, are still to be
   reported.
2. QA of the background batch: blocks 27 to 33 (`docs/QA-RUN.md`), and
   the questions at the top of this file.
3. The checklist redesigned with Discord's Components V2: look at
   `dev mock checklist` and the reminder sketches (block 33) and say
   what to change; nothing real is converted until they are approved.
4. Pills stage 3, reminders, on a go: the build plan is above. Then
   corrections and questions.

## Open decisions

- Of the `task-check` findings: C7 waits for G1; C12, C15, C16 and
  C19 wait for an answer (see the questions at the top); the timers
  ones (C8, C14, C17, C18) are left.
- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25.
