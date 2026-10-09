# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-10

## Branch and state

- Branch `feature/router`, not to be merged before the old path is
  removed (step 4).
- Last commit: the golden conversations as an acceptance test. In hand,
  uncommitted and waiting for the retest (block 18 of `docs/QA-RUN.md`):
  the standard moved to `docs/CONVERSATION.md`, this page, and batch 1
  of the conversation gaps.
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d and
  2a are marked as gaps (they need questions on the card, G1).
- Live eval spend to date: about US$2.30.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.

## Recently done

- Timers, bugs and pills setup work in plain words on the router's way.
- Every change is read back from the database before it is confirmed.
- "It" and "that" are resolved in code; what is stated always wins; a
  message that needs nothing gets no reply.
- Dev bugs are numbered D1, D2… with a "dev" tag.
- The conversation standard is `docs/CONVERSATION.md`, with its golden
  conversations replayed in `tests/test_golden.py`.
- Batch 1 of the gaps: a reply to an older card, ✅ on a message that
  needs nothing, a neutral "not understood", pronouns always resolved in
  code, one vocabulary for card kinds, 12-hour times in bug posts and
  `dev why`, a looser redirect replacing the old card.

## Next up

1. The retest of batch 1, then its commit.
2. Step 4 (G9, G13): remove the old path and the demo tasks. Pause.
3. Step 5: write the standard into the task contract and docs, and
   replace the `add-task` skill with `new-task` and `task-check`; run
   `task-check` on timers, bugs and pills.
4. Pills stages 3 to 6: reminders, the checklist, tracking.

## Open decisions

- Deferred until pills reminders work: G1 (questions on the card), G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- Live eval: only at a pause, only for the tasks whose fixtures changed,
  and asked first for any run over US$0.25.
