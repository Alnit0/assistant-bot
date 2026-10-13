# Status

Where the work stands, in under a page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.

**Updated:** 2026-10-13

## Questions for Alex

Answered on 2026-10-13, the self-test's record: a Fixed bug whose
step fails again is re-opened, and a Won't fix gets a note and stays
closed; only the first step to fail in a stage gets a bug, with the
steps that failed after it listed inside as probably following from it
(built); the summaries stay in #selftest-log; no backfill of the
earlier runs; run folders are pruned to the last 10, plus any with a
failure for 30 days (built: it happens after the next run); the
self-test marks Fixed only bugs it opened itself (built, and checked
against the bug's own record, not only the list of numbers).

**From the attention model and the status line (2026-10-13; the spec
is `docs/specs/attention.md`, the status line is built from it):**

- **Its self-test did not finish, and has not been run again.** The
  run after this item (as the dev bot, 1.6 GB of memory free at the
  start) was stopped by the PC after five steps, all passing, for low
  memory. The first new step (the dev bot's status line during a
  run) had passed; the two that check what live's line would read
  (1.11d, 1.15b) have not run in Discord. Say when to run it:
  `python -m selftest --claude` with more memory free. Until a run
  passes, **live's status line reads "⚠️ self-test did not finish"**:
  that is the new level 1 item doing its job, and it clears with the
  next passing run.
- **The memory check let it start at 1.6 GB** (the line is 1.5 GB) and
  it was stopped anyway. Should the line be higher, 2 GB say?
- **A bug for a system problem.** "⚠️ B14 · backup failed" needs a
  bug to exist, and nothing files one for a failed job today, so it
  reads "⚠️ backup failed". Should a failed job file a bug by itself,
  as a failing self-test step does?
- **Bugs at level 1**: only a bug with a fix ready to retest ("⚠️ B4 ·
  retest") is handed in. Every open bug, or none, instead?
- **The dev bot outside a self-test** keeps "🧪 DEV database · clock
  +13h". Or the same attention line as live?
- **A missed dose** is not a level 1 problem: it is in the briefing's
  line about yesterday. Or should it show as "💊 missed" for the rest
  of the day?
- **"🌅 6am"** shows whenever nothing else is left, during the day
  too. Only in the evening instead? And with the morning routine
  paused the line is blank.
- **Several things due at once** show only the soonest, with no "+2".
- **"🛠️ Dev mode"** is still said in front of live's line.
- **"backup failed"**: the job is called "nightly backup"; on the
  status line "nightly " is dropped, to match your example.
- **Quiet hours** (`QUIET_HOURS`, 10:00 pm to 6:00 am) are a setting
  that nothing uses yet: pings are not on the model. Should the
  6:00 am briefing list what was held back overnight?
- **The dev bot as caretaker** is in the spec as a later option, with
  what it costs (a second process all day, about 100 to 150 MB; the
  self-test could not then start the dev bot itself; long-lived state
  on the dev side). A Windows scheduled task that pings your phone
  when the service is down would buy the same for almost nothing.

**From the unattended batch of 2026-10-13 (six stages, all built;
every self-test run as the dev bot with live left up; US$1.08 spent on
seven runs, each under US$0.17):**

- **Design options are waiting for your picks** (stage 6): a post
  "🎨 Design options · 2026-10-13" in the dev bot's forum
  (#selftest-bugs), 15 sketches of the five cards, option A of each
  being the card as built. Reply there with a letter for each. I put
  them in the forum, not in the dev bot's other channels, because
  those are emptied at the start of every self-test. Nothing in the
  real cards changes until you pick.
- **One real fault was found and fixed by the self-test**: to a typed
  "9pm", in answer to a card whose button offered 8:00 pm, Claude
  handed over 8:00 pm. Code now puts back a time you stated
  (`actions.restated`). It was the first bug the self-test filed (D1)
  and marked Fixed by itself.
- **The new switches, all off** (set in `.env`, then restart live):
  `NIGHTLY_SELFTEST=true` (the 3:00 am self-test), `WEEKLY_SUMMARY=true`
  (Sunday 7:00 pm in the hub). `CARDS_V2=true` draws the new cards too.

- **Nightly self-test** (stage 1, built behind `NIGHTLY_SELFTEST`,
  off). To turn it on: `NIGHTLY_SELFTEST=true` in `.env`, restart
  live. Decided without you, say if wrong: it uses **recorded answers**
  (a night costs nothing; real requests would be about US$0.15 a full
  run); a run that **could not start** (low memory, no dev bot) is said
  in #bot-log and does **not** ping your phone (you said only for a
  failing step; a run that did not finish does ping); a night with
  nothing changed leaves one line in the self-test's log channel; a
  night the bot was off for is skipped after three hours. It runs at
  the same time as the nightly backup (3:00 am): say if it should be
  later.

- **Corrections straight after Save** (stage 2, G3): built for pills.
  Other tasks' cards can use the same thing (`Request.just_saved`) but
  none does yet: after saving a schedule, "no, 7pm" still asks which
  schedule when there is more than one. Say if you want it there too.
- **Days of the week** (stage 3). On a day a pill is not taken, the
  checklist lists it at the bottom under "🗓️ Not today" with its days,
  uncounted (as paused pills are listed). You said "shown on the
  checklist": say if you meant something else (its days on its line on
  the days it is taken, say). The words: "Mon to Fri at `8:00 am`",
  "Mon, Wed, Fri, any time", "2× a day, Sat, Sun, any time".
  Different times on different days are not built.
- **Last night's dose** (stage 3). Decided without you: only "taken"
  can be logged for yesterday, and only the day before; with no time
  given the card proposes the planned time, or **11:59 pm** for a pill
  with no time (a made-up time, shown before it is saved: say what it
  should be); the "not come yet" reading stops at 4:00 am; an explicit
  "last night at 11" is logged without the missed-dose card, though
  that dose is by then marked missed.

- **History, the streak and the weekly summary** (stage 4, the
  summary behind `WEEKLY_SUMMARY`, off; to turn it on:
  `WEEKLY_SUMMARY=true` in `.env`, restart live). Decided without
  you, all of it things you see, so say what to change:
  - **The week is Monday to Sunday**, the one today is in, for "show
    my week" and for the summary alike (not the last seven days).
  - **The summary is Sunday at 7:00 pm**, in the hub, silent. Move it
    with `my schedule`.
  - **The streak is said from two days up**, as "🔥 Streak · 5 days",
    as a line of the briefing's pills section, at the end of the week
    and in the summary. The briefing spec had said no streak in the
    briefing; you asked for it there now, so it is there.
  - **A day's line in the week** is `` `Tue 13` ✅✅❌ 2 of 3 ``: one
    mark a dose, in the pills' own order, without their names.
  - Only **yesterday** and **the week** can be asked for; "what did I
    take on Monday" is not built. No history for one pill alone, and no
    streak a pill ("one a pill later in history" was the earlier plan).

- **The remaining cards in the new look** (stage 5, behind `CARDS_V2`
  as before). Drawn now: my pills, a day and the week looked back on,
  the weekly summary, open bugs, the "I was offline" card, the "which
  task?" question. **Not done, each needing a pass of its own**: a
  bug's post in the forum, the archived copy with Restore and the dev
  panel (built with discord.py directly, rewritten by their own
  buttons), #commands and `help` (pages of text), and timers (left as
  they are). Say which of those you want. Colours I chose, not final
  like the rest: every box in "my pills" is grey (nothing in a list is
  waiting to be done); a day of the week is red if a dose was missed,
  blue while one is still to take, green otherwise; a bug is amber
  when a fix is ready to retest. The offline card's heading is "📭 I
  was offline when you sent this" and its question "Handle it now?";
  the tie card's heading is "❔ One question".

**From the two bots (2026-10-13):**

- **The self-test's channels are found only by the ids in `.env.dev`**
  now (you renamed the category): never by name, and nothing is ever
  created. A missing id or a deleted channel stops the run with a
  message. `--remove` deletes the four channels and leaves the
  category.
- **A self-test ran as live's account beside live for eight minutes** (16:32
  to 16:40): its starts inherited live's token from the launcher.
  Nothing reached a real channel and live handled nothing in that
  time; the nickname it changed is put back. Fixed, with a hard guard:
  every start checks its account against `BOT_USER_ID` before the
  lock, and exits untouched if it is the wrong one (`core/account.py`).
- **`BOT_USER_ID` is now needed in `.env`** (I added live's id, and
  the dev bot's to `.env.dev`): a start without it does not start. If
  the service ever exits with code 4 it is this check, and the service
  does not retry on it (`AppExit 4 Exit`, set 2026-10-13).
- **Live no longer acts in the dev bot's channels**, so that two bots
  never answer one message. Anything you type there is for the dev
  bot, when it is running.
- **The dev bot has no name of its own in what it says**:
  `ASSISTANT_NAME` is empty in `.env.dev`, so it calls itself what live
  does. Its nickname in Discord is its own (`BOT_NAME`).
- **Nicknames** (2026-10-13): each bot takes `BOT_NAME` from its
  settings file on start; the dev bot is "Name · testing" during a
  self-test; "· DEV" is gone. If a self-test is stopped before its end
  the dev bot stays "· testing" until its next start or the next run.
- **The status "🧪 Self-test running · back about <time>"** is shown
  only in the fallback (no dev bot), by the self-test's own bot on
  live's account, since a stopped bot has no status. With the dev bot
  live is never stopped, so you will not normally see it.
- **Reactions made while live was off are not read back**, only
  messages. In the backlog already ("lost reactions").

Answered on 2026-10-13, the two bots: the service does not retry
after a wrong-account exit (`AppExit 4 Exit`, set); the dev bot's bug
forum stays separate; the dev bot registers no slash commands (built,
and the two it had registered are removed); the offline card's plain
look is fine for now and follows `CARDS_V2` later (in the backlog);
the bots are "live" and "the dev bot" everywhere, never a display
name.

**From the scheduler build (2026-10-13):**

- **The run log is pruned by the end of the day, not by the tidy.**
  The spec said the tidy; the tidy is behind `HUB_TIDY`, so with it off
  nothing would ever be pruned. The end of the day always runs. Say if
  you want it in the tidy all the same.
- **With the summary read-only, the briefing's pills section depends
  on the end-of-day job having made the day's rows.** If that job has
  not run for today (it always runs first on a start, however late),
  the section is left out until the checklist is posted or shown. That
  is the trade you chose; it is the one place something waits on a job.
- **What is still yours** is the list at the end of `docs/SELFTEST.md`:
  the lock screen, the colours as they look, the wording, the sketches,
  and blocks 46 to 49 of `docs/QA-RUN.md`.

Answered on 2026-10-13, after the build: the self-test is run again
after these fixes; a routine's step order and taking a step out are
later (in the backlog); the run log is pruned (built); lines that
report a change outside the hub are fine as they are; a schedule you
add named by its part of the day is fine; the pills summary is
read-only and the new-day job makes the dose rows (built); the v1
sketches go once the v2s are checked in block 44. The PC has 8 GB:
free memory is checked before a self-test, and the self-test runs only
the stages a change touches, with `--full` for everything (built).

**Built on these assumptions; say if any is wrong:**

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
- **Our own engine, not APScheduler** (the dev clock, a key a run,
  the run log and rows you can change are what we need most).
- **Yesterday's checklist stays in the hub while `HUB_TIDY` is off.**
  On, it goes when today's is posted. The old ones there now have no
  id kept for them: one `reset channel` in the hub clears them.

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
