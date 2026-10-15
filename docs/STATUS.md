# Status

Where the work stands, in one page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.
No history is kept here: what changed is `docs/CHANGELOG.md`, and this
file as it stood until midday on 2026-10-14 (every batch, every answer,
all of "Decided overnight") is `docs/archive/STATUS-2026-10-14.md`.

**Updated:** 2026-10-15

## Live restarted at 3:03 pm, 15 Oct, with the calendar on

From `cc759a3` (clean, pushed, full test run passed), with no pill
reminder booked or open. `CALENDAR_ENABLED=true` in live's `.env` (the
link was there already). Checked after: the account check passed; the
calendar's table was made, with a copy of the database saved before; the
first read worked (47 events kept, no failure) and the next is booked 15
minutes on; the Today card is in place with today's event, and the
briefing's line reads "1 event · first 9:00 am"; the link is in no log.
What's new for 16 Oct: four lines (round 4, what is on, the Design
forum, the calendar).

## Decided (2026-10-15, the calendar)

Built on `feature/pills` behind `CALENDAR_ENABLED`, read only, from the
secret iCal link in live's `.env` (`CALENDAR_ICS_URL`).

1. **A source behind a small interface** (`tasks/calendar/source.py`):
   the iCal link today, the Google Calendar API through a service
   account later (`docs/BACKLOG.md`). An error never holds the link.
2. **Read on start-up and every 15 minutes**, one run booked at a time
   (`scheduler.ensure`). A failed read keeps the last good copy; after 6
   hours of failing it is a problem in Needs a look.
3. **The copy** is a title and times, yesterday to two months ahead,
   replaced whole on each good read. No place, no description.
4. **Events go nowhere near Claude**: the state says only how many there
   are, `item_names` is empty, and extraction gets the day, a span or the
   search words; `core/names.py` finds the event and the answer is a
   template whose first line names no event (a phone may show it).
5. **The Today card**: all-day events in one small line at the top,
   events that are over in one small line ("📅 2 earlier today"), one on
   now in full ("on now · until 4:00 pm"), the next in full and the rest
   as times, with to-dos, routines and reminders. Events are not counted
   in its dots. With every event over and nothing else on, no card.
6. **The briefing's line**: "3 events · first 9:00 am" (or "all day").
7. **Attention**: an event starting in the next 30 minutes is level 3,
   the status line its time only ("9am"); an event on now adds nothing.
8. **Questions**: "am I free at 3?" with no am or pm reads the one in the
   day (7 am to 10 pm) and says which it read; an all-day event is not
   busy. A week is a day a heading, each day by the list rule.
9. **Routing**: with the calendar on, the briefing's routing line hands
   a coming day or week of events to the calendar: "what's on this
   week?" went to the briefing in the first recorded run.
10. **Understanding checks recorded**: 15 of 15, US$0.106 for two runs
    (about NZ$0.18). Self-test start 10 (stage `calendar`) reads a file
    of made-up events that come round every day, never the link (every
    other start blanks it): 5 of 5. Found on the way: the self-test
    sorted its starts by name, so p10 would have run before p2; now by
    number.

## Live restarted again at 1:41 pm, 15 Oct (for the #commands names)

From `056572d` (clean, pushed, full test run passed), 33 minutes clear of
the 2:14 pm pill reminder; no switch changed. The account check passed,
and #commands now heads them 📝 To-dos, ⏰ Reminders and 🔁 Personal
routines (3 messages edited); help uses the same titles. What's new for
16 Oct is now three true lines (round 4, what is on, the Design forum):
the four from before were out of date and are gone. The Routines layout
preview post has a reply with A and B side by side at 7:10 am, 8:30 pm
part done and all done, each labelled, with its length on a phone.

## Live restarted at 1:32 pm, 15 Oct (Alex: test everything now)

From `e06d30f` (clean, pushed, full test run passed), 42 minutes clear of
the next pill reminder (2:14 pm). Switched on in live's `.env` (a copy of
the one before is `data/env-before-2026-10-15-restart`): `DESIGN_ROUND=4`,
`TODOS_ENABLED`, `WEEKLY_SUMMARY`, `DMS_ENABLED`, `NUDGES_ENABLED`,
`HABITS_ENABLED`, `TODAY_CARD` (routines in layout B, the default). The
nightly self-test's row moved to 3:30 am while live was stopped.

Checked after: the account check passed (live's own account); the
migrations for to-dos, reminders and routines applied, with a copy of the
database saved before; the pills checklist redrawn in round 4; no Today
card (nothing on today: hidden while empty); the nightly self-test booked
for 3:30 am and the weekly summary for Sunday 7 pm; #commands lists
to-dos, reminders and routines. Two things found and fixed in code:
- **#commands headed them "Todos", "Nudges" and "Habits"** (the folders'
  names): it now uses each task's title (To-dos, Reminders, Personal
  routines), and help does too. Live shows the fix from its next restart.
- **`preview --ship 4` left Round 3 tagged Live**: over HTTP alone a post's
  tag names are not filled in. It reads the tag ids now; run again, Round
  3 is Retired and Round 4 Live.
Also fixed: a self-test start that stops was counted as nothing failed.
Six What's new lines are queued for 16 Oct (the four from before, and two
on round 4 and on what went on, with an example of each). DMs: QA item 0
by hand (the self-test cannot send one).

## Decided (2026-10-15, routines, shared repeats and the Today card)

Built on `feature/routines` and merged into `feature/pills` the same
day, when Alex asked to test everything at once: on in live from that
restart (`HABITS_ENABLED`, `NUDGES_ENABLED`, `TODAY_CARD`). Preview:
"Routines layout preview" in the Design forum.

1. **One repeat engine** (`core/recurrence.py`): once, every day,
   weekdays, weekends, chosen days, every N days, monthly on a date (a
   date a month lacks is its last day) and monthly on the Nth weekday (the
   last too). Local time, so daylight saving never moves one. Reminders
   ask it now; their tests pass unchanged. To-dos later.
2. **Routines follow round 4, not the earlier brief's buttons**: the
   brief said every step shown with its buttons under it, and the queue
   said the relevance rule and `design.listed` for any list. So a
   routine's card is the first three open items in full, "+N more", and
   one Done dropdown; a routine still to come has no dropdown (it can be
   ticked in words), and a finished one folds to a line.
3. **A step inside a group, said in words, ticks its group** ("did serum"
   ticks Skincare): a group's steps are a guide, not ticked one by one.
4. **A time that has come is due, not overdue**; only a window that closes
   undone is overdue.
5. **Attention**: any time is level 4; at a time is the next timed thing
   (level 3), then due (level 2); a window is quiet while open and, closed
   undone, level 2 only with a nudge. The brief also says Needs a look;
   that box holds level 1 (problems) only, so an overdue routine shows in
   the status line and on the Today card instead. Alex agreed (question
   68): an overdue routine stays out of Needs a look, which is for things
   that are wrong.
6. **Layout B is the default** (Alex, question 69): the Today card as the
   overview, and a card a routine from its time or window (any time: from
   the morning) until it is done, posted by a run booked at its start, in
   a hub slot of its own (`hubcard` gained `slot`). `ROUTINES_LAYOUT=a`
   brings back the one card. Group steps always show in full; the first
   three is items only. Not built yet: the nudge messages themselves (the
   setting is kept and shown).
7. **The Today card** (`core/today.py`, `tasks/today`, `TODAY_CARD`):
   timed things by the relevance rule, any time after them by the list
   rule, reminders as notes (a note whose time has gone is not shown), no
   buttons, and one small line when all is done.
8. **A time with no am or pm** is asked about, never guessed; a window
   past midnight is not offered yet.
10. **Self-test start 9, stage `hub`**: a reminder set and gone off
    (Done), a routine with a window (no card before its start, its own
    card with the dropdown at the start, Skincare picked, the rest in
    words, the card tidied away) and the Today card naming it; recorded
    answers. Before tonight's restart: to-dos 9 of 9, round 4 9 of 9 and
    start 9 5 of 5, as the dev bot, US$0. Step 8.05 had assumed no to-dos
    from start 7: it now compares with the card before the pick. Found: a
    start that crashes is not counted as a failure in the summary (it said
    0 failed); to fix next.
9. **The extraction fixtures are recorded** from the real API: 15 of 15
   on the second run, US$0.083 for both (about NZ$0.14). The first run
   found two fixtures with the wrong state and one trap whose meaning had
   changed: "move the morning routine to 7am" can now be a personal
   routine, so the trap names the bot's own morning checklist instead.

## Decided (2026-10-15, Alex's answers on round 4)

1. **Question 67: variant 2.** Taken logs at once; a reply with a time to
   the line it leaves corrects it. Variant 1 (the pop-up) and its setting
   `TAKEN_BUTTON` are removed. A reminder's Taken leaves the same line.
2. **To-dos in round 4** by the list rule (`design.listed`, the same for
   any list card to come): the first three open to-dos in full (overdue,
   then today's, then any day's), a small "+N more" for the rest, and
   one Done dropdown for every open to-do (a later day's too) in place of
   a button each. It holds 25 at most, the most pressing first, and then
   a small line says to use words. Done by words and undo as before.
3. **Ship round 4:** `feature/round-4` merged into `feature/pills`, live
   on `DESIGN_ROUND=4` from tonight's restart. Back is `DESIGN_ROUND=3`.
4. **The self-test pins the round:** every start but 8 runs on round 3,
   whatever live's `.env` says, and to-dos, reminders and personal
   routines are off unless a start turns them on. Start 8 checks round 4.
5. **What's new for tomorrow:** one Taken button now, reply with a time if
   you took it earlier; skip by words.
6. **Commit messages** go in a file for `git commit -F` (or in single
   quotes), so the shell expands nothing: `2bfc403` had US$0 turned into
   a path. Left as it is, not rewritten. One line in CLAUDE.md.
7. **The to-dos self-test (start 7) runs in round 4**, as live will:
   Done is picked in the dropdown (7.07, 7.09) and the card counts what
   is done (“✅ 1 done”). 9 of 9 as the dev bot, recorded answers, NZ$0.00.
   Start 8 keeps its own to-dos check (four to-dos, “+1 more”).
8. **Design previews: one forum post a round** (Alex, 15 Oct). The dev
   bot may make channels, and the old previews sat in its bugs forum, so
   a forum of its own was made: Design (`DESIGN_FORUM_ID` in `.env.dev`),
   with tags 🟢 Live, 🟡 Preview and ⚪ Retired. Posted: Round 1
   (Retired), Round 3 (Live) and Round 4 (Preview); tonight's restart
   runs `--ship 4`. The old design-options post is left as it is, with
   his feedback in it.

## Round 4 of the design (2026-10-15, built)

Built on `feature/round-4` (worktree `../assistant-bot-round4`). From his
feedback and a friend's (word for word in `docs/DESIGN-LOG.md`): less
that is no longer relevant, paused and missed out of the way, one Taken
button, fewer buttons.

1. **The relevance rule** is locked and lives in `core/design.py`
   (`relevant`, `Thing`): what can be done now in full with its button;
   the next thing in full with no button; the rest of the day one small
   line of times; done and missed a small line each with a count; paused
   not shown. The pills card, the reminders card and the to-dos card use
   it in round 4.
2. **One Taken button a dose**, built in two variants for question 67
   (a pop-up with the time filled in, or taken at once); variant 2 was
   chosen. A reminder has Taken and Snooze.
3. **Skip is said in words**, and "undo that" puts a skipped dose back
   ("not skipped after all").
4. **The Round 4 preview** is posted in the design-options post: the
   pills card in the morning is 5 lines and 2 buttons where round 3 has
   13 and 15; midday 7 and 1 where round 3 has 9 and 6.
5. **Tests:** `tests/test_round4.py`; self-test start 8 (stage `round4`),
   7 of 7 as the dev bot with recorded answers, NZ$0.00.

## Decided (2026-10-15, the daytime batch)

1. **"What pills are left" was in #inbox** (live's message 570, 10:42
   am): the router chose pills, extraction chose `pill_today`, which
   posted the checklist in the hub and replied with only a pointer. Now
   `pill_today` answers where it was asked: a first line with no pill
   name (the day's dots and how many are left), then each dose still to
   take in time order with its time in bold and "in 2 hours", and a
   small pointer to the hub's checklist after it (not in the hub, not
   in a DM). Asking posts nothing in the hub; `pills` (the word) is
   still the checklist.
2. **The other replies that point somewhere were checked**: `pills` and
   "brief me" are asked-for views, not questions; "what's on today?" in
   the hub brings the briefing right above up to date (it is the
   answer), and anywhere else posts a copy where it was asked. Left as
   they are.
3. **A direct message while `DMS_ENABLED` is off** gets one silent line
   ("Direct messages aren't on yet: write to me in #inbox for now.")
   and nothing else, only if it is Alex's; anyone else's, and any on the
   dev bot, gets nothing.
4. **The understanding review, 14 days of Alex's messages to live**
   (5 to 15 October, read from live's own database, no requests to
   Claude, pill names masked). 207 were plain words. The 173 before 10
   October went through the old way of asking Claude, which is gone:
   the check-up of 14 October summed them up and they are not replayed.
   **34 went through the router as it is now; 8 of them went wrong:**
   - four were already fixed, each with a golden conversation in his
     words: a change to a pill only on an open card ("Make 11:30, 11am
     instead", 2c), "I took it at 9am" asking which pill (18), "I took
     Pill A at 9am" read as a second dose (18c), "That was dose 1" (19)
   - two are the timers' (both teas extended, "2 more" marked a guess):
     left, as timers are frozen (question 50)
   - one was a guess marked inside ("at 11:12" read as the morning) but
     never shown: the dose was logged at the right time
   - **one is new: "What pills are left"** (step 1 above), now golden
     29 with his words, recorded from the real API (2 of 2, US$0.014)
     and a self-test step (3.05b) that replays it at no cost
   No router rule was added: the fix was the action's own description
   and code.
5. **To-dos have a self-test stage of their own** (`todos`, start 7,
   `TODOS_ENABLED` on for the dev bot only): empty and no card; add;
   add with a day; "what's on my to-do list?" answered in place; done
   by words; undo; done by the button; carried over as overdue two days
   on; all done. Every answer is recorded, so the nightly run replays
   it at no cost, and runs it when to-do code changes. Run once as the
   dev bot: 9 of 9 (NZ$0.00). The first try failed three steps on the
   test's own checks (button labels carry their emoji; with everything
   done the card stays as one green line, as designed: only a day with
   nothing has no card); it opened D7 and closed it on the second run.
6. **A reply to a pill line corrects the day that line is about.**
   "Actually I didn't", replied to last night's line just after
   midnight, makes that night's dose missed (its day is over, so there
   is nothing left to take: not "to take" again), and today's is not
   touched. A reply with a time ("I took it at 10:30") puts that
   night's time right, the half of the day nearest when it was logged.
   Anything else replied to an earlier day's line says so, and changes
   nothing. Two tests in the golden file.
7. **Live in its own folder is prepared, not switched over**
   (`docs/LIVE-FOLDER.md`). `scripts\update-live.ps1` moves live's folder
   to a commit, detached, or back to the one before (`-Back`); the setup
   script gained `-Ref` (one commit, not a branch), copies `.env.dev`
   too (live starts the nightly self-test from its own folder) and
   `-DevOnly` (a dry run: no service steps, the dev database only). The
   dry run, into a scratch folder: set up on one commit, moved forward
   and back, and the to-dos self-test from it, 9 of 9; the scratch folder
   is removed, and live's service and folder were never touched. It found
   two faults, fixed: the setup script's migration check could never
   have run (Windows PowerShell drops double quotes from an argument to a
   program), and a helper of the new script called itself.
8. **Spend for the batch: US$0.039 (about NZ$0.07)**: golden 29 from the
   real API (US$0.014), and the dry run's self-test (US$0.025), which
   asked the real API because a scratch folder has no record of the
   month's self-test spend. The other self-tests used recorded answers
   (NZ$0.00).

## Decided (2026-10-15, Alex's answers to QUESTIONS.md)

One line a question. Settled by round 3 shipping (his feedback in the
design-options post replaces them):

- 12 Round 1 letters for the checklist and reminder: settled by round 3.
- 13 Titles, items, small details, rules between items: settled by round 3.
- 14 A change as ~~old~~ → **new**: settled by round 3.
- 15 The thin question card, stacked too: settled by round 3.
- 21 Turn the new look on: settled (on since 8:59 am).
- 45 The day's total in the title or a line: settled by round 3 (in the title, as built).
- 46 Dots in the old look's checklist title: settled (it goes with the old look).
- 47 Build the type scale as sketched: settled by round 3.
- 48 The total under a dated title: settled by round 3.

Accepted as suggested:

- 1 A problem between 10 pm and 7 am posts nothing until one ping at 7 am: kept.
- 2 That ping repeats each morning while Needs a look is not empty: kept.
- 3 Dev mode left on and the self-test's month spent are shown, never pinged: kept.
- 6 ntfy stays off until `NTFY_BOT_TOPIC` is added; then pill reminders go to both: kept.
- 7 A dose of last night with no time said is proposed at its planned time (11:59 pm with none): kept.
- 8 "No, 7pm" straight after Save for schedules too: yes, later (backlog).
- 9 A restart is unexpected only if the PC restarted or the bot crashed: accepted.
- 10 No start card ("Online and ready"; a card only if a task could not start): kept.
- 22 A bug's forum post, the archived copy, the dev panel, #commands and help stay in the old look: kept.
- 33 Merge `feature/pills` into `main` after REVIEW.md and QA blocks 53 to 55: yes, when he has.
- 34 Live in its own folder on a committed version: yes, top of the backlog, the next infrastructure job; not today.
- 35 Weather for Auckland at 5:50 am, refreshed every 3 hours to 8 pm: kept.
- 36 A failed exchange-rate fetch is not an alert: kept.
- 37 The nightly self-test moves to 3:30 am, and every rule with it.
- 38 A watch on live as a Windows scheduled task that pings his phone: yes, later (backlog).
- 39 The golden conversations that failed just after midnight: chased now.
- 40 A live eval to shorten the router's rules (about NZ$0.70): not now.
- 41 #commands' words for Taken and Skip in the new look: done now.
- 42 Mornings as built (same time at weekends, no empty briefing, yesterday as counts, no buttons): kept.
- 43 The last-chance nudge at 11:30 pm with sound for a pill with no latest time: kept.
- 44 "Stops fitting the day" is the first dose still to come that would no longer fit: kept.
- 49 A contradiction is fixed on the card with a ⚠️ line, not asked: kept.
- 50 The two timer misreads wait until timers are kept or scrapped: kept.
- 51 A to-do with no day is for any day: kept.
- 52 An overdue to-do keeps its day and stays on top until done or moved: kept.
- 53 The same words twice are not added twice: kept.
- 54 Ticking a to-do off by words is done at once, with undo: kept.
- 55 Twelve to-dos listed, the rest counted, later ones in one small line: kept.
- 56 Reminders' switch `NUDGES_ENABLED`, folder `tasks/nudges`: kept.
- 57 A reminder time with no day: today if still to come, else tomorrow with ❓: kept.
- 59 Done and Snooze take a reminder out of the hub at once: kept.
- 60 Snooze offers 10 minutes, 1 hour and tomorrow: kept.
- 61 Personal routines' switch `HABITS_ENABLED`, folder `tasks/habits`, `my routines`: kept.
- 62 Twelve steps at most, ticks starting again at midnight: kept.
- 64 One `##` a message, as its page title; only the hub's task cards, under the briefing, have none (a ### card title only): the pills card made to match. Cards that ask and lists shown on request keep theirs (confirmed the same day).
- 65 A card with nothing in the morning is posted when it first has something: kept.
- 66 Switch on to-dos first, then personal routines, then reminders: to-dos at this evening's restart.

Answered:

- 4 `WEEKLY_SUMMARY` on in live (Sunday 7 pm): at this evening's restart.
- 5 `DMS_ENABLED` on in live at this evening's restart, so Alex can run QA block 54 (item 0 of his short list), which the self-test cannot; a direct message from any account but his is ignored before anything is read, logged or asked of Claude (a test says so).
- 23 Gym uses kilograms for everything.
- 29 The calendar is Google Calendar.
- 30 Read only, to begin with.
- 31 Connected by its private read-only link, no sign-in (the link goes in live's `.env` only).
- 32 Event names are matched by code and never sent to Claude.
- 58 A reminder's lock-screen line stays neutral.

Still open: 11 (his lock-screen screenshot is on its way), 63 (personal
routines reworked with groups: to discuss; `HABITS_ENABLED` stays off),
24 to 28 (under "Gym onboarding": he designs onboarding first; nothing
of gym is built). The calendar is not built yet either.

## Later on 2026-10-15

- **`docs/NOW.md`** is what is happening now, at most 40 lines, updated
  after every step of a batch and reset to Idle at its end. A
  SessionStart hook (`.claude/settings.json`, committed; `scripts/now.ps1`)
  prints it at every start, resume, `/clear` and compact; `/catchup`
  reads it first. Batches now commit a checkpoint after each finished
  step, and drafts live in `docs/drafts/` or `docs/specs/`, never only
  in a scratchpad (CLAUDE.md, kept under 10 KB).
- **Live is to be restarted once this evening** (between 6 pm and
  9 pm, clear of the pill reminders) so it loads the What's new box for
  tomorrow's 6 am briefing; the three new tasks stay off. The result is
  written here when it is done.

## Round 3 is live (2026-10-15, 8:59 am)

**The hub is in the round 3 design.** `CARDS_V2=true` and `DESIGN_ROUND=3`
were added to live's `.env` and live was restarted once at 8:59 am (the
next pill reminder was 11:07). It came up as its own account; the
briefing and the pills checklist were redrawn in place, read back from
Discord as Components V2. Before it: the full tests (2889 passed), the
commit, and a self-test as the dev bot with recorded answers, 122 of 123 steps
passed, none failed, one skipped as usual (NZ$0.00), which marked D6 and D3 fixed by itself. The preview is the
"Round 3 built" message in the design options post: **please look on your
phone** and reply there. To go back: `DESIGN_ROUND=1` (the look before it)
or `CARDS_V2=false` (the plain look), and a restart.

## Built on 2026-10-15, switched off in live

**Three new hub tasks**, each behind its own switch, off by default and
off in live (`.env` was not touched for them):

| Task | Switch | Words to see it |
|---|---|---|
| To-dos | `TODOS_ENABLED` | `my to-dos` |
| Reminders you set yourself | `NUDGES_ENABLED` | `my reminders` |
| Personal routines | `HABITS_ENABLED` | `my routines` |

`REMINDERS_ENABLED` is still the pills' reminders, untouched. Each task
has its card in the hub under the pills card (reminders, personal
routines, then to-dos), a section in the briefing and its items in the
one ranking (the status line and Needs a look work with no special
case). The real router and extraction were asked 36 natural phrasings,
35 right and the one miss a safe reading ("move that to 6" read as 6 pm,
marked as a guess); the answers are recorded for the tests to replay.
Spend: US$0.14 (NZ$0.25). **To look at**: the "New hub tasks preview" in
the design-options post, and questions 51 to 66 in `docs/QUESTIONS.md`.

**Also**: a task whose switch is off is not loaded (out of help,
#commands and the router); a **What's new** box for one morning's
briefing (`core/whatsnew.py`), not loaded in live until its next restart,
so it is not in tomorrow's 6 am briefing unless live is restarted
before then; `/catchup` for Claude Code; the design loop
(`docs/DESIGN-LOG.md`, `python -m selftest.preview --round N` and
`--replies`).

**Not done**: the prompt about `docs/NOW.md` and a SessionStart hook,
which `/catchup` follows, never reached this session: `/catchup` reads
`docs/NOW.md` when there is one and `docs/STATUS.md` until then. No
self-test steps for the three tasks yet (the month's self-test spend is
gone; `docs/BACKLOG.md`).

## Decided (2026-10-15, the new hub tasks)

17. **Built tonight against the rule "spec first, nothing built until it
    is approved"**: you asked for the build with your defaults, so the
    specs (`docs/specs/todos.md`, `reminders.md`, `routines.md`) were
    written first and the build follows them, everything open to change
    (questions 51 to 66).
18. **The folders are `todos`, `nudges` and `habits`**: `nudges` because
    `REMINDERS_ENABLED` and `tasks/pills/reminders.py` are the pills';
    `habits` because "routine" in code is the scheduler's. What you read
    is "To-dos", "Reminders", "Personal routines" (a new `title` a task
    can give).
19. **A task's card comes after the pills checklist**: steps of the
    morning routine can now run after its own handler (`scheduler.AFTER`),
    each task joining at its place in the order. Gym's place (+30) is
    kept for it.
20. **A card that has nothing for today is not posted, and one that gets
    something mid-day is posted then**, at the bottom of the hub, until
    the next morning puts it in order (question 65).
21. **Ticking a to-do or a step off is a log, done at once**, as a pill
    taken is; adding, changing and removing are cards that only Save
    writes.
22. **A name that fits two to-dos, reminders or steps is said back in a
    line ("“call” could be Call Ryan or Call Mum: say which"), not
    guessed**. A card's question would be better and is in the backlog.
23. **Reminders are booked one occurrence at a time** as engine jobs with
    a run key; each claimed in `nudges_fired` before it is posted, which
    is what makes "never twice" hold across a retry and a restart.
24. **"Late" means the bot was off**: time the dev clock jumps over is
    not counted, as for every job.
25. **The reminders card has no buttons**: nothing on it can be done
    before its time; what goes off carries Done and Snooze.
26. **Personal routines tick by a button for each routine's next step**
    (question 63), and a routine is at most twelve steps.
27. **What's new lines are kept under 7:30 am of their day**, outside the
    night the briefing lists as held back, so live's code from before
    them never shows them as alerts.
28. **Help leaving out a task whose switch is off is done by not loading
    it at all**, which also keeps it out of #commands, the router, its
    jobs and its cards.

## Overnight, 2026-10-15: the reboot

**Windows Update restarted the EliteDesk twice** (00:23 and 00:26). The
night's batch stopped part-way, with the round 3 design built but not
committed. Live came back by itself at 00:26, as its own account, on
the working copy (those uncommitted changes, with `CARDS_V2` still off,
so the old look). The 6 am routine ran in full and the briefing posted.
The 3 am self-test ran on the same working copy, whose phase 5 still
looked for the old briefing's words: five steps failed and it opened
D6 and re-opened D3. Not a fault of the bot. Fixed in the self-test's
checks the same morning. That live can load unreviewed work on a
reboot is now in `docs/BACKLOG.md` (Next, 5).

## Decided (2026-10-15, round 3 of the design)

Choices the prompts did not settle. Each is yours to overturn.

1. **A box is a Components V2 container, not an embed**, as the cards
   already were. So Discord's limits are those of Components V2 (40
   components and 4,000 characters a message), not 10 embeds and 6,000.
2. **The most urgent state, for a box's edge**: destructive, risky,
   due, any time, missed, decision, done, quiet. A miss makes a box red
   only when nothing in it is left to do, as the rule for a pill was.
3. **The day's total stays in the briefing's title** (R3-A, as built),
   with the date small under it: question 45 is still yours.
4. **The briefing's pills box is a summary** (the next dose, the
   streak, the line about yesterday), not each pill: the pills card
   right under it lists each one.
5. **The weather is the first task box in the briefing**: a box that
   counts nothing sets the scene, then the counted tasks in the
   ranking's order. No task is named in code for it.
6. **A time still to come has "in 2 hours" after it; one gone by has
   not.** An overdue dose reads "dose 2 · due **11:04 am**".
7. **A pill with only a miss left stays an item** ("missed · was due
   **9:00 am**", no buttons), after any time; it is not folded into
   the small line, which holds what is done, paused or not today.
8. **Every dose still to take keeps its buttons**, coming up included:
   taking one early is allowed, and asks first when too soon. When a
   card would not fit, the buttons go first and the next dose due
   keeps its own.
9. **Lists** (my pills, the week, a day looked back on, open bugs, my
   schedule) **are one box with a rule between items**, the edge the
   most urgent state in it. Statuses per item are no longer colours;
   each item keeps its mark (✅ ❌ ⏭️).
10. **A change is drawn only for the one format, `field · old → new`.**
    "**Iron** → removed" has no field and is left as it is.
11. **Times a task writes in code** (in summary lines shared with the
    old look) **are drawn bold**, so the old look is untouched.
12. **The hub's order was already briefing, then the pills card**, as
    the 6 am routine posts them, with what comes later under them. With
    no gym or to-dos card yet, nothing was changed for the order.
13. **The status line is unchanged.**
14. **The look before round 3 is "round 1"** (rounds 2 and 3 were
    sketches until now) and stays one setting away: `DESIGN_ROUND=1`.
    Proved by running the old tests against it: all passed but two that
    looked at a function that moved.
15. **The preview's made-up morning is 7:30 am**, when you are likely to
    look: its "in 2 hours" are real Discord timestamps, so they read
    right then and drift after.
16. **The self-test's phase 3 and 5 checks** now read the round 3
    wording (one box a topic, `### 💊 Pills ●○○ 1/6`, `~~old~~ →
    **new**`).

## Priorities (Alex, 2026-10-14)

The hub is a daily overview I check, plus a place to talk to the bot
and do more. I am not relying on the bot for reminders yet. So, most
important first, when work is chosen, ordered or cut short:

1. **What the hub shows and how it reads**: the briefing, the design,
   progress.
2. **How well it understands what I say.**
3. Everything else.

Notifications and ntfy are low priority.

## Decided (the batch of 2026-10-14, afternoon)

Choices the batch's prompt did not settle. Each is yours to overturn.
(The night before's 32 are in the archive.)

**Item 1, the day's progress, and the design messages that came in
while it was being built**

1. **Behind a switch, `DAY_PROGRESS`**, off unless set, as every new
   feature is. It goes on for live with the restart at the end of
   the batch.
2. **A dose taken or skipped counts as done**, as the checklist's own
   count has it, so a day can end with every dot solid. A missed
   dose is not done.
3. **The total is built in the briefing's title** ("☀️ Today ●●●●●○○
   5/7", your example), with the date and then the small line a task
   under it. As a line of normal text it is one value in
   `core/design.py` (`DAY_TOTAL_IN_TITLE`). Question 45.
4. **More than ten things**: ten dots to the nearest, but all solid
   only when everything is done and all hollow only when nothing is.
5. **"Everywhere" was taken at its word**: the block bar is also gone
   from the lab's countdown. **Not changed**: the old-look
   checklist's "▰▰▱▱▱ 2 of 5", which is a different bar and goes with
   the old look (question 46); and per-item dots ("Pill A ●●○") are
   what the drawn checklist already has, so nothing was added there.
6. **The four block-bar sketches are deleted from the repo; the
   messages already posted for them in the forum are left**, above
   round 3. Say if you want them deleted there too.
7. **Round 3 is one folder**: the two dot sketches (R3-A in the title,
   R3-B in normal text) and the five of the type scale. Posted in
   the design-options post, in that order.
8. **Questions 16 to 20 are gone as answered** (progress marks, the
   total, the block bar, the custom-emoji bar): dots. 45 to 48 are
   new.
9. **The type scale is a draft and nothing of it is built.** Five
   things the sketches had to decide are listed in `docs/DESIGN.md`
   (the day's total moves under a title that holds the date; a
   one-card message has both a page and a card title; what notifies
   has no page title; the briefing's pills box lists each pill; a
   relative time in a sketch is a real timestamp).

**Item 2, questions about my day**

10. **Behind one switch, `DAY_QUESTIONS`**, off unless set; on for live
    with the restart at the end of the batch.
11. **The day's questions belong to the briefing task**, which answers
    them from what each task hands in and still knows no task. "What's
    on today?" is the briefing itself, as it was.
12. **Yesterday and the week are read from each task's record of the
    day** (a new `tally` in the contract), not from today's summary:
    a summary is built from how the pills are set up now, which could
    give a wrong number for a day that has passed.
13. **"This week?" is Monday to today**, a line a day with dots and a
    count. The pills' own week ("show my week", a mark a dose) is
    unchanged and still the pills task's.
14. **Straight after you log a pill, "what's left today?" showed the
    checklist.** Overturned the same afternoon: a question never
    sticks to the task that just answered (golden 27, 27a).
15. **Weather answers only from the forecast it keeps**, and nothing is
    fetched to answer. "Tomorrow" says only today's forecast is kept.
    "This afternoon" is 12 to 6, "this evening" and "tonight" 6 to
    midnight, "this morning" 6 to 12; "will it rain?" with no part
    named is the hours still to come today.
16. **How warm a part of the day is needs the temperature by the hour,
    which the fetch now asks for.** Until the first fetch after the
    restart, an answer about the afternoon has no temperature rather
    than a made-up one.
17. **Weather is now a line in the router's catalogue** (last night it
    was kept out so no prompt changed): about US$0.0002 more on each
    routed message. A question costs about half a US cent.
18. **The golden conversations are 21 to 25** (with 23a, "and this
    week?"), recorded from the real API: 33 requests, 33 right,
    NZ$0.18.

**Item 3, the understanding check-up** (what was found is in
`docs/BACKLOG.md`, "Understanding check-up, 2026-10-14")

19. **"My messages to live from the past week" was read as the message
    log of live's database, 7 to 14 October**: 484 rows, of which
    about 30 are plain words since the router went in on the 10th.
    The hundred before that went through the old way of asking
    Claude, which is gone: they were read, and are summed up, not
    replayed.
20. **One misread was still open, and is fixed in code and in the
    prompt**: a change to a pill that is only on the card. The others
    had been fixed since they happened; each now has a golden
    conversation (2c, 18c and 26 are new).
21. **No golden conversation for the two timer misreads**: timers are
    frozen and may be scrapped, and a golden conversation that must
    fail would stand in the list for nothing. Question 50.
22. **A contradiction in what you said is still put right with a ⚠️
    line, not asked about.** The standard can be read either way:
    question 49.
23. **In the fixtures and tests the pill is "Pill A"**: what the real
    API returned is kept as it was but for the name.
24. **`python -m evals.live --part 1/2`** is new: half of a fixture
    file a run, so no run came near NZ$0.40 (the dearest was
    NZ$0.23).
25. **One pills fixture now accepts either of two actions** ("add
    iron…" when iron is there): its own note already said both end
    in the same card. With that the pills fixtures are 62 of 62.

**The end of the batch**

26. **`DAY_PROGRESS` and `DAY_QUESTIONS` are on for live** (two lines
    added to `.env`). To turn either off: set it to false, restart.
27. **Live was restarted twice, not once** (3:03 pm and 3:07 pm). The
    first start showed a fault from this morning's #commands change:
    the first time its text really changed, the edit in place raised
    (a partial message can't be told to hide link previews) and
    #commands was left as it was. Fixed, with test fakes that now take
    only what discord.py takes, and live restarted on the fix:
    "#commands: 1 edited", no error.
28. **#commands does not list the weather questions until the next
    restart.** A task that is only talked to had no page there; the fix
    is committed, and I did not restart live a third time for it.
29. **How warm an afternoon is will be said from the 5:50 pm refresh
    on**: the forecast kept before the restart has no temperature by
    the hour.
30. **The test suite took 1 min 57 s.** Brought to 36 seconds the same
    afternoon, with the same tests (`docs/DECISIONS.md`, "The test
    suite").

**The small fixes after the batch**

31. **What counts as a question is the task's own reading of it**: an
    action that only shows or says something. No list of question
    words. "And this week?" after the answer about yesterday now
    goes by the router too (golden 23a says so).
32. **An open card takes only what could answer or change it** (your
    answer, the same afternoon): a question typed while a card is
    open goes to the router, and the card stays open and answerable
    (golden 28, 28a, recorded from the real API, 4 of 4, NZ$0.03).
    A new request for the card's own task ("took my zinc" with a
    pills card open) is still done by that task without the router,
    as before: it already leaves the card as it is. After the
    answer, a typed answer to the card goes by the router, which is
    shown the card; a reply to the card or its buttons go straight
    to it.
33. **No self-test step for it**: a step's one recorded answer is
    given to every task that reads the message, so the step could not
    tell the old behaviour from the new. Golden 27 and 27a are
    recorded from the real API.
34. **The `end-of-task` skill was reordered** to match the new rule:
    docs, then the full test run, then the commit.

## Where things stand

- **Branch `feature/pills`**: everything is committed and pushed;
  nothing is merged into `main`.
- **Live** was last restarted at 8:59 am on 2026-10-15, on the round 3
  commit, with `CARDS_V2` on: the hub is in the round 3 look. Before
  that, Windows Update had restarted the PC twice (00:23 and 00:26) and
  live came back by itself on the working copy. Nothing needs a look.
- **The morning routine ran as booked on its first morning** (live's
  run log, 2026-10-14): the exchange rate, the weather fetch, the tidy,
  the briefing, the checklist, and a needs-a-look check with nothing
  to say.
- **Tests**: offline 2889 passed, 1 skipped, in about 40 seconds. The
  last full self-test (2026-10-15, 8:44 am, the dev bot with live up,
  recorded answers): 122 of 123, none failed, one skipped for needing
  real requests; it marked D6 and D3 fixed. The golden
  conversations asked of the real API: 57 of 59, the two misses old
  known ones that the code puts right; 27, 27a, 28 and 28a recorded
  since, 9 of 9.
- **Spend on the day's batch**: NZ$1.10 (US$0.62), all of it live
  evals; the dearest run NZ$0.23. The self-test's month (NZ$3.50) is
  spent: recorded answers until November.
- **Bugs**: 2 open on live (`bugs`), both from before 12 Oct. The
  self-test's D6 and D3 (3 am, its own checks behind the new look) are
  marked fixed by its 8:44 am run.

## Switched on (live's `.env`)

- **On**: `CARDS_V2` with `DESIGN_ROUND=3` (since 2026-10-15, 8:59 am), `BRIEFING_ENABLED`, `DAY_PROGRESS`, `DAY_QUESTIONS`,
  `WEATHER_ENABLED`, `HUB_TIDY`, `REMINDERS_ENABLED`,
  `QUIET_HOURS_ENABLED` (10:00 pm to 7:00 am), `NIGHTLY_SELFTEST`.
- **Off**: `WEEKLY_SUMMARY`,
  `DMS_ENABLED`, `NOTIFY_NTFY` (nothing goes to ntfy).
- **Each day**: midnight the end of the day; 3:00 am the backup; 3:30 am
  the nightly self-test (from the evening restart of 15 Oct); 5:30 am the exchange rate; 5:50 am the weather
  fetch; 6:00 am the morning routine (tidy, briefing, checklist);
  7:00 am the needs-a-look check; 8:50 am the weather refresh, then
  every three hours to 8:00 pm.

## Waiting on you

1. **The round 3 look, on your phone**: reply in the design-options post
   with what to change; it goes into `docs/DESIGN-LOG.md` word for word
   as round 4.
2. **A lock-screen screenshot of a pill reminder** (question 11).
3. **The private Google Calendar link**, for live's `.env` only.
4. **Two things to talk through**: personal routines with groups of
   steps (63), and gym onboarding (24 to 28).
5. **`docs/REVIEW.md` and QA blocks 53 to 55**, before the merge into
   `main` and live's own folder (33, 34).

## Next

In the order of the priorities; the full list is `docs/BACKLOG.md`.

1. **The hub's look**: round 4 from your feedback on round 3 (the design
   loop, `docs/DESIGN-LOG.md`), and #commands' words for the buttons.
2. **The new hub tasks**: switched on in the order you choose, with
   self-test steps for each, after your answers to 51 to 66.
3. **What the briefing shows**: whatever your look at the hub turns
   up; the answers about your day, once you have read a few.
4. **Understanding**: the two golden conversations that failed once
   near midnight (question 39); a correction straight after Save for
   schedules (question 8); task ties asked too often (G4).
5. **Then**: the merge and live's own folder (so a reboot never loads unreviewed work); gym once its answers are
   in; the calendar after its four; a flavour status line (backlog).

## Standing

- Nothing is added unasked. New tasks are allowed (gym is next), spec
  and sketches first. Timers are frozen and may be scrapped.
- Open questions are `docs/QUESTIONS.md` and nowhere else.
