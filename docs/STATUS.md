# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-12

## Questions for Alex

- **The design's colours** are not final until you have looked at
  them on your phone (block 39, step 6). `docs/DESIGN.md` is marked as
  waiting for that.
- **The lock screen** (waits for your phone; block 39, step 2, the
  same as block 33, step 1): the sketches put
  "💊 Routine due · 11:12 am" as the message's first line. If your
  phone shows something else for a card of this kind, the prompt has
  to be a plain message with buttons instead: say which you see.
- **Gym** waits for your answers on how you train (the spec's section
  16). No gym code is started until then. The three core additions
  are approved (attachments on a request, a decimal number in the
  contract, name matching moved out of pills) and are stage 1 of the
  gym build, so they wait with it.

Answered on 2026-10-12, the design pass: any time and still to take is
blue; a card that asks first because something is risky is amber;
confirm and question cards blurple, destructive ones red;
`reminder-v1-first` stays; the old sketches go, and the six with no
new version are redrawn as v2 (done). None of the colours is final
until the check on the phone. A pill's box is red only when a dose
was missed and nothing is left to take today; with a dose still to
come it is amber and the missed dose is a ❌ line.

Answered on 2026-10-12, reminders and questions on the card: kept as
built, with three changes made (reminders stay a plain message and are
converted with the checklist's redesign; Taken at… with a time that
needs asking shows the "Log it anyway?" card; reminders on with no hub
is said once in #bot-log). The fallback wording for a Save cut off
inside the save itself ("✅ Saved." with "checked after a restart"
under it) is fine as it is.

Answered on 2026-10-12 and done or parked: C7 (done with G1), C12,
C15 and C16 (done, block 34), C19 (moves with gym), the timers
findings (left), the reminder and gym mock-ups (as sketched, to be
looked at in blocks 33 and 35), a reset cut off (keeps asking again),
the "not posted" line (only real problems are logged now), lost
reactions (left, in the backlog), streaks (after reminders).

## Background batch (unattended, on `feature/pills`)

One commit an item, pushed, each with a block in `docs/QA-RUN.md`
marked "waiting for QA". One live eval was run, the one approved (the
pills fixtures, US$0.13). The service was not restarted: the live bot
is still on "Send a reply to a task's message to that task". The next
restart adds three tables and three columns (`timers_messages`,
`pills_lines`, `pills_prompts`, `occurrences.cause`,
`confirm_cards.confirmation`, `confirm_cards.question`). Reminders stay
off after it unless `.env` says otherwise.

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

9. Done: the gym spec (`docs/specs/gym.md`, private) and four
   mock-ups in `docs/mockups/` (block 35). No code. "Not now" in the
   standard says new tasks are allowed and gym is next.

12. Done: pill reminders (block 38), switched off: `REMINDERS_ENABLED`
    is off unless set, and off means nothing is ever sent.
11. Done: questions on the card (G1, block 37). Golden 1c, 1d and 2a
    pass, so no golden conversation is a gap any more; every pills
    question is on the card (C7).
10. Done: restarts (block 36). What survives one is a section of
    `docs/ARCHITECTURE.md`, with what reminders will need; on start
    the bot catches up and says so once in #bot-log; a Save or a reset
    cut off half way is put right without being done twice; a message
    it was in the middle of gets ⚠️. Timers left out.

On your answers of 2026-10-12: C12 (`show_existing`, declared by
bugs), C15 (a `cause` in the occurrence log) and C16 (a `clear` list
when changing a pill) are done (block 34). The pills fixtures were
recorded live for C16, the one run approved: US$0.13, 60 of 61.

### Reminders (stage 3): built, switched off

`tasks/pills/reminders.py`, behind `REMINDERS_ENABLED` (off unless set
in `.env`). All seven steps of the build plan are in: when a prompt is
due, the prompt and its buttons, one stored job, snooze and three
reminders, missed and nothing after the latest time, too soon on a
card, and the notification that never names a pill. Tested offline on
the dev clock (`tests/test_pills_reminders.py`); block 38 is the QA.
To try it live: `REMINDERS_ENABLED=true` in `.env`, then restart.

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
- Tests: `python -m pytest -q` passes. No golden conversation is
  marked as a gap (1c, 1d and 2a pass since questions on the card).
  The live evals of 2026-10-12: pills 56 of 57, general 12 of 12,
  golden 37 of 39 (not run again since the router's rule on reports
  was reworded); each miss is a known one that the code covers. The
  pills fixtures were recorded again on 2026-10-12: 57 of 59, with one
  known miss ("took the usual one" is now right as recorded: the code
  decides). Recorded again the same day for the `clear` list: 60 of 61,
  the miss a known one ("and zinc once a day").
  One timers fixture has no recording yet.
- Live eval spend to date: about US$4.17.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.
Exceptions asked for: channel reset (2026-10-11, needed before going
live), and on 2026-10-12 the bot's nickname and status line, the
#commands channel and `dev mock`. New tasks are allowed again from
2026-10-12: gym is next, spec and mock-ups first, nothing built until
the spec is approved.

## Recently done

- Restarts (2026-10-12): the bot catches up at start and says so once.
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
2. QA of the background batch: blocks 27 to 39 (`docs/QA-RUN.md`), and
   the questions at the top of this file.
3. The Components V2 design: the style guide (`docs/DESIGN.md`) and
   its thirteen sketches (blocks 33, 35 and 39) wait for the check
   on your phone: the colours and the lock screen. Nothing real is converted yet: the checklist's redesign
   is the first, and the reminders with it.
4. Pills reminders: QA with block 38, then switch them on live
   (`REMINDERS_ENABLED=true`, restart). Then corrections and
   questions (stage 4), then streaks.
5. Gym: waits for the answers on how you train; then its core
   additions (approved), then the task.

## Open decisions

- Of the `task-check` findings: C7 is done with G1; C19 waits for gym
  (the second task that needs name matching); the timers ones (C8,
  C14, C17, C18) are left.
- Deferred until pills reminders work: G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25.
