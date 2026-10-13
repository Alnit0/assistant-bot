# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-13

## Questions for Alex

**From the fixes after the self-test (2026-10-13):**

- **The suite's hang was not found.** Six full runs in a row passed
  with nothing stalling. A test that runs over a minute now stops the
  run with its name and where it was stuck, so the next one says so.
- **A full self-test is needed to see the fixes in Discord** (the new
  steps are written and have not run: live stayed up). Say when.
- **What is still yours** is the list at the end of `docs/SELFTEST.md`:
  the lock screen, the colours as they look, the wording, the sketches.

Answered on 2026-10-13, after the self-test: the code checks a name
Claude hands over against what was typed and asks when it fits more
than one pill, and Claude is told not to complete names; Claude hands
over what it understood, so the card asks for a missing time; under a
minute the too-soon card says "just now"; every job has a name in
words wherever you see it, and the catch-up card is checked for
internal labels; the reset card is built in the new look. All done
(block 45). Then: part of a pill's name is a hint for the router, not a
decision (a word of four letters or more that starts a word of a
name; the router still decides); and the timers' jobs have names in
words ("timer ending", "Pomodoro phase"), the one thing touched in
timers. Both done, and live restarted on all of it.

**Still open from the scheduler, clean-up and briefing specs** (drafts
of 2026-10-13; nothing is built until you answer these and approve):

- **The sketches `briefing-v2` and `schedule-list-v2`** replace v1 of
  each. The two v1 files stay until you have checked the v2s in block
  44 (`docs/QA-RUN.md`), and go when you say they are right.
- **Weekends:** the same time every day (assumed), or later on
  Saturday and Sunday?
- **Silent or notify:** the morning routine silent (assumed), or
  should the briefing notify?
- **A morning with nothing in it:** no briefing (assumed), or one that
  says so?
- **Yesterday's line:** counts only, "5 of 6 taken · 1 missed"
  (assumed), or naming what was missed?
- **Anything else first thing:** a streak, the weather, what the bot
  did overnight? And the order of sections once gym, calendar and
  to-dos exist (assumed: in that order after pills)?
- **Buttons in the briefing:** none (assumed), so doses are ticked off
  in one place.
- **Clean-up:** a tidy with nothing wrong says nothing in #bot-log (assumed)? On a day
  with nothing to take, yesterday's checklist still goes in the
  morning (assumed)? The tidy is the routine's first step (assumed),
  or a schedule of its own at 5:55 am?
- **The scheduler:** a schedule moved to a later time after it ran
  today does not run again today (assumed). "my schedule" lists what
  the bot posts by itself, not each pill's dose times (assumed). The
  backup and the new day are listed and not changed by words
  (assumed).
- **APScheduler or our own engine:** I recommend our own (the dev
  clock, a key a run, the run log and rows you can change are what we
  need most, and APScheduler has none of them). Say if you want the
  library anyway.
- **Yesterday's checklist is still in the hub because the code leaves
  it there on purpose**: at the end of a day it is written one last
  time and left, and its id is then forgotten; the morning post only
  removes earlier copies of the same day. Not a failed job. The old
  ones there now can only go with `reset channel` in the hub: no id is
  kept for them.

Answered on 2026-10-13, the specs: you talk in the hub, and what you
say there and the bot's reply are tidied once handled (2 minutes after
the reply, or when its card is saved, cancelled or expires; pinned
stays). The morning routine is tidy, briefing, checklist, so the
checklist is the newest message. The briefing is edited in place when
a section changes and always shows now, with no new posts. Lines that
report a change go at the end of the day outside the hub. "Routine"
means only a schedule with several steps: what `dev run` runs becomes
a handler, renamed in the code and in `CLAUDE.md` when the scheduler
is built (not before: no code was to change). Also right, as assumed:
after Save your message and the card go at once and the confirmation 2
minutes later; in the hub a message of yours that failed keeps its ⚠️
until the morning tidy, and one that needed no reply goes 2 minutes
after it was handled; "brief me" in the hub brings the briefing up to
date in place and answers with a pointer line that goes by itself; a
briefing missed while the bot was off is posted however late.

**From before:**

- **The design's colours** are not final until you have looked at
  them on your phone (`docs/QA-TONIGHT.md`, steps 2 to 5).
- **The lock screen**: say exactly what it shows for a card of this
  kind (steps 2 and 3 there). If it is not the neutral line, the
  prompt has to stay a plain message with buttons.
- **Gym** waits for your answers on how you train (the spec's section
  16). The three core pieces are built.
- **The dev bot**: when you have made it, put its token and channels in
  `.env.dev` ("A bot of its own for dev" in `docs/DEVELOPMENT.md`).
- **Still open from the cost audit** (`docs/COSTS.md`): shorten the
  router's rules with a full live eval (about US$0.30 to US$0.50)? A
  model with a lower caching minimum, so the router and chat cache?
- **Still open from the task check**: #commands says Taken and Skip
  are "under today's checklist"; with the new look they are in the
  pill's own box. The words are yours, once `CARDS_V2` stays on.
- **The service was stopped** when I looked on 2026-10-13 (not by me).
  `nssm start assistant-bot` when you want live back.

Answered on 2026-10-13: on the drawn checklist each pill's next dose
keeps its buttons before it is due; a dose with no time has no message
of its own there; a removal that keeps its history is a blurple box
with a red button. A streak is counted in days, one for all pills
shown on the checklist and one a pill later in history, and showing it
waits for stage 4. Dev gets a bot token of its own (`.env.dev`,
built). The router is not skipped for a message that names a pill.
"took `<exact pill name>`" with nothing else is a typed shortcut
(built); no other shortcut. `tasks/keep` no longer uses discord.py
(done). A file sent with no words goes to the router only once gym is
built (in the backlog).

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

## The self-test (2026-10-13)

`python -m selftest` (live stopped first) runs the dev bot against real
Discord in channels of its own and writes `docs/SELFTEST.md`: 63 steps
over four starts, about nine minutes. It covers what a bot can do of
`docs/QA-TONIGHT.md` parts 3 and 5 to 8 and of blocks 40 to 44; the
rest is listed there as yours. Live was stopped from 9:31 am to 10:20
am for it and is back. No row of `docs/TESTING.md` was marked passed
from it: its presses are simulated, so your manual rows stay yours.

## Fixes after the self-test (2026-10-13)

Six things, asked for after the run, with tests and self-test steps
for the first five (the steps have not run: live stayed up).

1. A name Claude hands over is checked against what was typed
   (`core/names.py`: `said_about`, `unclear`). "pause testv" with
   Testvit and Testvit forte asks which, whatever Claude made of it.
   Claude is also told never to complete a name.
2. "twice a day at 8am": the cause was not reproduced (9 of 9 real
   requests offline gave the right card, before and after). What
   Claude sent the one time it failed was not kept, so it is now
   logged whenever nothing fits. An empty place in a list of times no
   longer loses the pill, and Claude is told to hand over what it
   understood and leave out what was not said.
3. "just now" under a minute on the too-soon card.
4. Every job has a name in words (`scheduler.label`): "pill
   reminder", "end of the day", "a card's expiry". The catch-up card
   is checked like everything the bot says; a Save or a press that was
   cut off is said in words, with the code's names in the log file.
5. The reset card is drawn as a red box with `CARDS_V2` on.
6. A per-test time limit (`tests/watchdog.py`).
7. A hint for the router (`routing.name_hints`): a word I typed that
   starts a word of the name of something a task holds, from four
   letters. The router is given the word and the task, never the name,
   and still decides. Not tried with real requests: whether it now
   sends "pause testv" to pills is for the next live eval or self-test.
8. The timers' two jobs are named in words.

The two language steps rerun with real requests, offline from Discord:
"twice a day at 8am" 5 of 5; "pause testv" straight after a pills
answer 5 of 5 (Claude now hands over "testv" as typed). US$0.084 in
all, the diagnosis included.

## The scheduler, stage by stage (started 2026-10-13)

Built from `docs/specs/scheduler.md` and `docs/specs/briefing.md`, a
stage at a time, each with offline tests, a commit and a self-test run.

1. **Done: the engine, with nothing that shows changed.** Handlers,
   schedules as rows (`core/timetable.py`), one engine
   (`core/scheduler.py`), the run log with a key a run, missed-run
   rules, one-off jobs. The nightly backup, the end of the day and the
   6:00 am checklist run from schedules; pill reminders keep their one
   job, now with a key. `dev jobs`, `dev run`, `dev fire next`, `dev
   clock` and the status line use it. "Routine" means only a schedule
   with several steps.
2. **Done: changing the schedule by words** (`tasks/schedule`). `my
   schedule` shows the list (free), and move, pause with or without an
   end, resume, days of the week, silent or notify, channel, add and
   remove are each a card that only Save writes. #commands gains a
   "🗓️ Schedule" message at the next start. Not built in this stage,
   because there is nothing yet to use it on: changing the order of a
   routine's steps, and taking a step out of a routine (they come with
   the briefing, when the first routine exists).
3. **Done: the briefing, behind `BRIEFING_ENABLED` (off).** An
   optional summary in the task contract (`core/summaries.py`), which
   pills provides; one briefing a day in the hub as the first step of
   the morning routine, edited in place when a section changes; `brief
   me` brings it up to date. To turn it on: `BRIEFING_ENABLED=true` in
   `.env`, then restart. The 6:00 am schedule is then called "Morning
   routine" (briefing, pills checklist); off again, it is the checklist
   alone under its own name.
4. **Done: clean-up, behind `HUB_TIDY` (off).** Message lifetimes
   (`core/messages.py`), the morning tidy as the routine's first step,
   a copy to `data/exports/` first, pinned kept, and what you say in
   the hub tidied 2 minutes after the reply or with its card. Messages
   with no lifetime recorded are left alone. To turn it on:
   `HUB_TIDY=true` in `.env`, then restart; the old checklists in the
   hub from before it need one `reset channel` there.

The first start on this code adds two tables and five columns
(`schedules`, `schedule_steps`; on `scheduled_jobs`: `run_key`,
`schedule_id`, `step`, `local_at`, `note`), makes the three schedules
and replaces the jobs that were waiting for the backup, the end of the
day and the checklist with their schedules' own runs, in one change.

## A missed dose asks first (2026-10-13)

A dose the bot marked missed and then logged as taken is asked about
on the amber card: "Dose 1 was missed (due 11:12 am). Log it as taken
now?", with a small line for what it does to the next dose's time
(`next: dose 2 · 11:30 am → 12:40 pm`). Said in words, typed as `took
<pill>` (still free) or pressed, it is the one check. `dev cost` writes
a limit under a cent to three places.

Answered on 2026-10-13, and kept as it is: "took pill A" logs the
current dose (with dose 1 missed and dose 2 waiting, that is dose 2). A
missed dose is only logged when it is named ("dose 1 of pill A") or
when nothing else is left.

## Specs drafted on 2026-10-13: scheduler, clean-up, briefing

Spec and mock-ups only; no code. `docs/specs/scheduler.md` (handlers,
schedules as rows, one engine, a run log, a key a run, routines,
changing it by words, clean-up and message lifetimes, the comparison
with APScheduler, and how today's 6:00 am checklist and pill reminders
move over with nothing you see changing) and `docs/specs/briefing.md`
(a summary in the task contract, one card edited in place, pills
now). Both are draft 2, with the answers of the same day worked in.
Sketches: `briefing-v2`, `schedule-list-v2`, `schedule-change-v1`,
`cleanup-v1` (block 44). The hub's principle is in the standard and the design
guide. Core and task are set out in each spec: the engine, lifetimes,
the tidy, the summary in the contract and the gathering are core; the
words for changing a schedule are a small task, `schedule`; the
briefing task holds only its sections' order and its own words.

## Overnight batch of 2026-10-13 (unattended, on `feature/pills`)

One commit an item, pushed. All eleven items are done:

1. Core pieces for any task: a message's files on the request, a
   number that need not be whole, name matching in the core (block 40).
2. The new look behind `CARDS_V2`, off by default (block 41): the
   checklist, the reminder and the confirm, question and asks-first
   cards. Every colour and spacing is in `core/design.py`.
3. Streaks as pure logic (`core/streaks.py`). Nothing shows one.
5. The tests run in about a minute, from 10 minutes 55 (the same tests).
6. A task check of every task and the core; code-only findings fixed.
7. `scripts\setup-live-folder.ps1`, prepared and only run with
   `-WhatIf`.
8. The backlog is one prioritised list.
9. `docs/COSTS.md`: every kind of request measured, the cached part
   shared, two repeated descriptions out of every schema. Two live
   checks, US$0.19 in all (allowed up to US$0.25): pills 60 of 61 as
   before, timers 36 of 37.
10. The daily spend line (`DAILY_SPEND_LIMIT`, block 42).
11. Candidates for free shortcuts, in `docs/COSTS.md`. None added.
4. The full suite and the golden conversations pass, and
   `docs/QA-TONIGHT.md` is one ordered run of blocks 27 to 42.

The service was not restarted by me, and was found stopped. Its next
start adds four tables and three columns (`timers_messages`,
`pills_lines`, `pills_prompts`, `spend_notices`, `occurrences.cause`,
`confirm_cards.confirmation`, `confirm_cards.question`). Reminders and
the new look stay off after it unless `.env` says otherwise.

## Background batch of 2026-10-12

One commit an item, pushed, each with a block in `docs/QA-RUN.md`
marked "waiting for QA". One live eval was run, the one approved (the
pills fixtures, US$0.13).

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

- The overnight batch of 2026-10-13: see above.
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

The order is the list at the top of `docs/BACKLOG.md`. First:

1. `docs/QA-TONIGHT.md`: one run of blocks 27 to 42, the lock screen
   and the sketches first, `CARDS_V2` and `REMINDERS_ENABLED` last.
   Blocks before 27 that are still to be reported: 21, 22, 23 (steps 5
   to 7), 24 (step 8), 25 (steps 1, 2 and 6) and 26.
2. The questions at the top of this file.
3. The phone check of the design, then `CARDS_V2` on for good; block
   38, then reminders on live (`REMINDERS_ENABLED=true`, restart).
4. `feature/pills` into `main`, then live's own folder.
5. Gym: waits for the answers on how you train; the core pieces are
   built.
6. The scheduler, clean-up and the briefing: the specs wait for your
   answers and approval; then the build order in the scheduler's spec.

## Open decisions

- Of the `task-check` findings: C7 is done with G1; C19's name
  matching is in the core (2026-10-13); the timers ones (C8,
  C14, C17, C18) are left.
- Deferred until pills reminders work: G3
  (corrections after Save), G4 (task ties asked too often), G7 (questions
  sent as their own message). G14 (privacy of notifications) comes with
  reminders.
- After pills reminders: schedules with days of the week, in core (now
  part of the scheduler's spec: one "which days" for a pill and for a
  schedule); a notes task is a possible future task.
- Live eval: only when asked, or at a pause where fixtures changed; only
  for the tasks whose fixtures changed, and asked first for any run over
  US$0.25. That is a limit for one run, not for a day (said 2026-10-13,
  now in `CLAUDE.md`); `DAILY_SPEND_LIMIT` is the bot's daily alert.
