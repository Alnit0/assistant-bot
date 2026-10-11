# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-12

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
- In hand, uncommitted, from going live (three parts, a pause after
  each): **part 1, the bugs from real use**, is committed. Its retest
  (block 23 of `docs/QA-RUN.md`) failed at step 2, silently: a time
  said straight after a log went to plain chat, which acknowledged it.
  Fixed and uncommitted: a follow-up goes to the task that just
  answered, and chat never acknowledges something done. The rerun
  found one more: a stated dose number was ignored. Fixed and
  uncommitted with it: a dose named by its number is that dose, a
  leftover is never cut off mid-phrase, and a report nothing tracks
  gets "I can't log that yet." Steps 5 to 7 of block 23 retest these.
  Part 2 (polish) and part 3 (the checklist redesign, mock-ups first)
  wait for it.
- In hand, uncommitted, a live bug of 2026-10-12: the 6:00 am
  checklist didn't post, because one had been asked for at 1:29 am.
  Fixed: the morning's post is a fresh copy, and a morning with no
  post says why in the log and #bot-log. `dev status` now says what is
  running. **The live bot must be restarted on this code for
  tomorrow's 6:00 am.**
- Tests: `python -m pytest -q` passes. Golden conversations 1c, 1d
  and 2a are marked as gaps (they need questions on the card, G1).
  The live evals of 2026-10-12: pills 56 of 57, general 12 of 12,
  golden 37 of 39 (not run again since the router's rule on reports
  was reworded); each miss is a known one that the code covers.
- Live eval spend to date: about US$3.91.

## Current goal

Make the bot talk the way `docs/CONVERSATION.md` says, then get pills
reminders working: reminders, the daily checklist and tracking are what
matter most.

## Scope freeze

No new features, tools or dev commands until pills reminders work
(2026-10-10). Fixes and the agreed steps only. Nothing is added unasked.
One exception was asked for on 2026-10-11, needed before going live:
channel reset.

## Recently done

- From the first night live: due times that never pass the day's limit
  or creep, doses that can't fit skipped by the bot, a late log asked
  about on a card, and a time said straight after logging taken as a
  correction.
- Button colours are one rule (green, red, blurple, grey for Cancel
  only), applied to every button and enforced by `core/cards.py`.
- Housekeeping leaves no trace: delete, archive, pin, unpin and channel
  reset say one line that goes after about 10 seconds (by a stored job,
  so also after a restart), the typed word goes too, and #bot-log is
  the record.
- Channel reset: `reset channel` empties the channel after asking on a
  card (all, or all but pinned and 📌), saves a transcript first, and
  every task puts its live messages back.
- Pills stage 2: today's checklist in the hub at 6:00 am, edited in
  place, with Taken / Skip for doses with no time, logging by message,
  `pills` for a fresh copy, changes during the day, the end of the
  day, and nothing doubled by a restart.

## Next up

1. The retest of part 1 (block 23), then its commit. Blocks 21 and 22
   are still to be reported.
2. Part 2, small polish: what the reset card will post again, pointer
   messages that tidy themselves away, and `data/exports` in the
   nightly backup. (The result line that stayed, the hidden button,
   the no-trace rule and button colours are already done.)
3. Part 3: the checklist redesigned with Discord's Components V2,
   mock-ups first through a `dev mock` tool; the real checklist is
   not converted until the mock-ups are approved. Then reminders.
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
