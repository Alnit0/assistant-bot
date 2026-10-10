# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- Pills stage 1 is committed: the schedule model in core
  (`core/schedule.py`) with pill setup moved onto it.
- In hand, uncommitted, after block 19 step 2 failed (a gap handed over
  as "3 hours apart" was refused): lengths of time and times of day now
  come from Claude structured; `core/durations.py` reads spoken lengths
  as a safety net; a part that can't be read, or doses that can't fit,
  get a card with the reason and no Save. Block 19 is to be rerun from
  the start (it has steps 10 and 11 now).
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d
  and 2a are marked as gaps (they need questions on the card, G1).
  The live evals of 2026-10-10 with the new schema: pills 36 of 37,
  golden 29 of 31; every miss is a known one that the code covers.
- Live eval spend to date: about US$2.90.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.

## Recently done

- Pills stage 1: one schedule model for every pill (doses a day, planned
  times, minimum gap, latest time) and when each dose is due, in core,
  with the spec's worked example as unit tests; the cards, the list and
  the database moved onto it.
- One path for every message: the old way (Claude with every tool) and
  the demo lists are removed; `pills` is a read-only Live list.
- A task's name on its own shows its list; chat has no access to data
  and never offers; internal labels are never sent.
- Remarks get no reply; 👀 and ⚠️ on a message are its status.
- The conversation standard is `docs/CONVERSATION.md`, with its golden
  conversations replayed in `tests/test_golden.py`.

## Next up

1. The rerun of block 19 (pills stage 1) from the start, then the
   commit of what is in hand.
2. Pills, in the order of the spec's section 15, with a pause for QA
   after each: (2) the daily checklist; (3) reminders; then corrections
   and questions. Each starts on a go.
3. Step 5, after pills reminders: write the standard into the task
   contract and docs, drop the contract's unused `hint`, and replace the
   `add-task` skill with `new-task` (which reads the Scaling notes
   first) and `task-check`; run `task-check` on timers, bugs and pills.

## Open decisions

- Whether timers' lengths should come structured too (they need
  seconds; see the backlog).
- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25.
