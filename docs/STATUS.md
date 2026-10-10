# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- In hand, uncommitted and paused for QA (block 19 of
  `docs/QA-RUN.md`): pills stage 1, the schedule model in core
  (`core/schedule.py`) with pill setup moved onto it. Starting the bot
  runs one pills migration.
- Tests: `python -m pytest -q` passes (1714). Golden conversations 1c,
  1d and 2a are marked as gaps (they need questions on the card, G1).
  One new pills fixture (the Pill A sentence) is not recorded yet, so
  its replay is skipped until a live eval of `pills.json` is run.
- Live eval spend to date: about US$2.57.

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

1. QA of pills stage 1 (block 19), then its commit.
2. Pills, in the order of the spec's section 15, with a pause for QA
   after each: (2) the daily checklist; (3) reminders; then corrections
   and questions. Each starts on a go.
3. Step 5, after pills reminders: write the standard into the task
   contract and docs, drop the contract's unused `hint`, and replace the
   `add-task` skill with `new-task` (which reads the Scaling notes
   first) and `task-check`; run `task-check` on timers, bugs and pills.

## Open decisions

- Pills: what the card should do with a planned time after the latest
  time (today the pill is refused with the reason; see the backlog).
- Pills: whether the live eval of `pills.json` is run now (the action's
  wording and one fixture changed).
- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25.
