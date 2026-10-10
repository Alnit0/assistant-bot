# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/router`, not to be merged before the old path is
  removed (step 4).
- Last commit: no reply to remarks, reactions as status. In hand,
  uncommitted and waiting for the retest (block 18 of `docs/QA-RUN.md`):
  the six QA findings (a name shows its list, chat has no data, nothing
  internal is sent, no offers) and step 4, the removal of the old path
  and the demo lists.
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d and
  2a are marked as gaps (they need questions on the card, G1).
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

1. The retest of block 18, then its commit.
2. Merging `feature/router`: the old path is gone, so it can be.
3. Step 5: write the standard into the task contract and docs, drop the
   contract's unused `hint`, and replace the `add-task` skill with
   `new-task` (which reads the Scaling notes first) and `task-check`;
   run `task-check` on timers, bugs and pills.
4. Pills stages 3 to 6: reminders, the checklist, tracking.

## Open decisions

- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- Pill names in `docs/CONVERSATION.md`: the answer came back unfilled
  ("none are real / replace X"), so none was changed. Waiting to hear.
- After pills reminders: schedules with days of the week, in core (see
  the backlog); a notes task is a possible future task.
- Live eval: only at a pause, only for the tasks whose fixtures changed,
  and asked first for any run over US$0.25.
