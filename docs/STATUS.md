# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- Pills stage 1 is committed: the schedule model in core
  (`core/schedule.py`) with pill setup moved onto it.
- Committed: lengths and times handed over structured, cards with no
  Save for what can't be read or can't fit, a pill that is already
  there, declines that name their kind. Blocks 19 and 20 passed
  (one row, R40, still needs a database with no Pill A).
- In hand, uncommitted and paused for QA (block 21 of
  `docs/QA-RUN.md`): pills stage 2, the daily checklist, with dose
  logging by message. Starting the bot runs one pills migration, and
  it needs `HUB_CHANNEL_ID` to post by itself.
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d
  and 2a are marked as gaps (they need questions on the card, G1).
  The live evals of 2026-10-10: pills 50 of 51, golden 32 of 33; each
  miss is a known one that the code covers.
- Live eval spend to date: about US$3.35.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.

## Recently done

- Pills stage 2: today's checklist in the hub at 6:00 am, edited in
  place, with Taken / Skip for doses with no time, logging by message,
  `pills` for a fresh copy, changes during the day, the end of the
  day, and nothing doubled by a restart.
- A message that names one of my pills or timers is never dropped as
  a remark (golden conversation 17).
- Adding what is already there, and declines that name their kind.
- Lengths and times handed over structured; cards with no Save.
- Pills stage 1: one schedule model for every pill, and when each
  dose is due, in core.
- One path for every message: the old way (Claude with every tool) and
  the demo lists are removed; `pills` is a read-only Live list.
- A task's name on its own shows its list; chat has no access to data
  and never offers; internal labels are never sent.
- Remarks get no reply; 👀 and ⚠️ on a message are its status.
- The conversation standard is `docs/CONVERSATION.md`, with its golden
  conversations replayed in `tests/test_golden.py`.

## Next up

1. QA of pills stage 2 (block 21), then its commit.
2. Pills stage 3, reminders (prompts at each dose's time, snooze,
   re-nudges, missed, take-by, automatic skips, the latest time, the
   too-soon question), on a go. Then corrections and questions.
3. Step 5, after pills reminders: write the standard into the task
   contract and docs, drop the contract's unused `hint`, and replace the
   `add-task` skill with `new-task` (which reads the Scaling notes
   first) and `task-check`; run `task-check` on timers, bugs and pills.

## Open decisions

- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25.
