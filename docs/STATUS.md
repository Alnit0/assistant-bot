# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/pills`, with `feature/router` merged into it (step 4
  passed its retest and is committed: the old path is removed).
- Pills stage 1 is committed: the schedule model in core
  (`core/schedule.py`) with pill setup moved onto it.
- Committed: lengths and times handed over structured, and cards with
  no Save for what can't be read or can't fit. Block 19 was rerun:
  10 of 11 passed, with two findings.
- In hand, uncommitted, for those findings: adding a pill that is
  already there (said in a line, or a change card), a decline that
  names its kind instead of "didn't understand", and "show all my
  pills" as the free list shortcut. Block 20, step 1 half-passed (the
  plain "already how it is" line was said): every way of finding that
  nothing would change now ends in the task's own line. Paused for the
  retest of block 20 of `docs/QA-RUN.md` (4 steps).
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d
  and 2a are marked as gaps (they need questions on the card, G1).
  The pills live eval of 2026-10-10: 40 of 41; the miss is a known one
  that the code covers.
- Live eval spend to date: about US$3.06.

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

1. The retest (block 20), then the commit of what is in hand.
2. Pills stage 2, the daily checklist, with dose logging by message
   (the go is given). With it: logging examples in pills' router
   entry; a message that names one of my pills or timers is never
   routed as "nothing"; a golden conversation, "I've taken my Zinc
   today" ticks Zinc off today's checklist. Then a QA block.
3. Pills stage 3, reminders, then corrections and questions, each on
   a go.
4. Step 5, after pills reminders: write the standard into the task
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
