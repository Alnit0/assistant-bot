# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- In hand, uncommitted: docs only (the speed rule in `CLAUDE.md`, core
  or task in the Scaling notes, one backlog line).
- Pills stage 1 (the schedule model in core) is not started: it waits
  for v7 of the pills spec, which is not on disk (the file is v6).
- Tests: `python -m pytest -q` passed at the last commit. Golden
  conversations 1c, 1d and 2a are marked as gaps (they need questions on
  the card, G1).
- Live eval spend to date: about US$2.57.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.

## Recently done

- One path for every message: the old way (Claude with every tool) and
  the demo lists are removed; `pills` is a read-only Live list.
- A task's name on its own shows its list; chat has no access to data
  and never offers; internal labels are never sent.
- Remarks get no reply; 👀 and ⚠️ on a message are its status.
- Batch 1 of the conversation gaps (G2, G5, G6, G8, G10, G11, G12).
- The conversation standard is `docs/CONVERSATION.md`, with its golden
  conversations replayed in `tests/test_golden.py`.

## Next up

1. Pills, in the order of the spec's section 15, with a pause for QA
   after each: (1) the schedule model in core (doses a day, planned
   times, minimum gap, latest time, when a dose is due), with existing
   pill setup moved onto it; (2) the checklist; (3) reminders. 2 and 3
   start on a go.
2. Step 5, after pills reminders: write the standard into the task
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
