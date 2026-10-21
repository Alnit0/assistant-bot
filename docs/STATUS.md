# Status

Where the work stands, in one page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.
No history is kept here: what changed is `docs/CHANGELOG.md`, and this
file as it stood until midday on 2026-10-14 (every batch, every answer,
all of "Decided overnight") is `docs/archive/STATUS-2026-10-14.md`.

**Updated:** 2026-10-17 (evening)

## The morning news (21 Oct, evening; a batch, not shipped)

The daily read and the planned News headlines as one task, on
tasks/reading (Alex: "it makes sense to only have one set of news
generated"). Step 1 done: the feeds and reading them.

### Decided (21 Oct, the morning news)

- **Live's switch is already on:** live's `.env` has `READING_ENABLED=true`
  (the daily read has been running there, not off as the docs said). Left as
  it is (not to be touched in this batch), so the morning news goes live the
  moment live is next updated to this batch's code: Alex's call, said in the
  report.
- **Feeds kept, 39** (`tasks/reading/feeds.json`, checked from the home
  server on 21 Oct): NZ politics RNZ Politics, NZ Herald Politics, Newsroom,
  1News, RNZ National; NZ housing and money interest.co.nz, RNZ Business, NZ
  Herald Business, NZ Herald Personal Finance, Newsroom Business, Reserve
  Bank of New Zealand; world news BBC World, The Guardian World, Al Jazeera,
  NPR World, ABC News (Australia), DW, RNZ World, France 24; world politics
  Politico, NPR Politics, The Guardian Politics, The Guardian US Politics,
  BBC US and Canada, BBC Politics; tech Ars Technica, The Verge, TechCrunch,
  The Register, BBC Technology, Engadget; AI TechCrunch AI, The Verge AI, Ars
  Technica AI, MIT Technology Review AI, The Guardian AI; the wildcard The
  New Stack, InfoQ, BleepingComputer.
- **Feeds dropped:** The Spinoff (its feeds answer 404), The Post (not a
  feed), Good Returns and OneRoof (broken XML), Stuff (no dates in its feed),
  VentureBeat AI (refuses with 429), The Conversation's politics and DevClass
  (nothing in the last 24 hours), 1News Business (404), NZ Herald Property
  (empty), interest.co.nz's section feeds (404, 410). The old starter list
  went but for Ars Technica, The Verge and The Register: personal blogs,
  article sites and Hacker News, not news.
- **interest.co.nz** writes its dates as "20th Oct 26, 3:59pm" in NZ time:
  the feed reader reads that too (with it, the main NZ money feed had none
  in the window). DW is RSS 1.0, read now too.
- **Paid articles, in Python:** an item whose feed tags it premium,
  subscriber, paywall or members only (NZ Herald and Newsroom tag theirs
  "premium"), or whose link has `/premium/`, is dropped before Claude sees
  anything; a chosen article's page that reads as a paywall
  (`rules.readable`) falls back to its feed snippet for the TL;DR, as the
  link is still the outlet's own. 25 of 919 items were dropped this way on
  21 Oct.
- **The same story from several outlets** is one (most of the shorter
  headline's telling words in the other, three at least); how many outlets
  carried it is kept and given to Claude as a sign of the day's biggest
  news. Tracking parameters come off every link.
- **What goes to Claude:** the newest 12 of each feed and 35 of each topic
  (200 on 21 Oct), each headline with its feed snippet cut to 40 words.

## 👍 as yes (21 Oct, evening; pushed, not restarted)

Behind `THUMBS_UP` (off unless set): `core/thumbsup.py`, an in-memory
registry fed by `core/cards.py` from `Card.thumbs_up`; the 👍 reaction is
the builtin task's, through the existing reaction path (checked at once,
the quiet period, ✅, undo; `Reaction.tracks` ignores an untracked message
in silence). Five cards ask one yes: a dose's reminder and a dose with no
time's message (Taken), a reminder that went off and an expiry's nudge
(Done), a routine's own card (`habits.all_done`, undo `all_undo`). With it
on, a routine has no dropdown (both layouts) and its own card is a plain
embed that stays green with 🟩 Done for the day. Not given one: the
checklist and the lists (several things on one message), confirm cards
(Save stays a press). Text is unchanged: a typed taken or done that deals
with the thing takes its card away or rewrites it, and the 👍 after it is
nothing; a 👍 first, then typed taken, is what typing after a press always
was (the pills rule asks before a second log).

## Round 7: the briefing as embeds (21 Oct, afternoon; not restarted)

Built behind `DESIGN_ROUND=7` (docs/DESIGN-LOG.md, round 7): two messages
of embeds, `tasks/briefing/embeds.py`, from each task's new `day_items`
(calendar, pills, personal routines, to-dos, diary); `cards.Embed` and
`Card.embeds`/`heading`, drawn by `interfaces/discord/render.py`; the
colours in `design.EMBED_COLOURS`. The second message is its own Live copy
(`briefing:hub2`), rewritten in place, gone the next morning. Also: the old
calendar emoji is 🗓️ in every tracked file (a test scans them), and the calendar's own
week-view answers are its events alone (`weekview.gather(only=...)`); the
week view in #calendar keeps doses and routines. Not restarted (Alex
restarts by hand); live's `.env` is as it was, so it stays on round 5 until
`DESIGN_ROUND=7` is set there.

## What's on over any span (21 Oct, afternoon)

Alex: the calendar lookup knew a day, this week and next week only.
`calendar_show` now takes a span of day, week (with a day: that week, Monday
to Sunday), next_week, month (`month` as said, else this one: a month with no
year is this one or the next of that name), next_month, year (`year`), next_year,
or a range (`day` and `until` as said, the last read on or after the first,
up to two years). Python works out every day (`rules.span_of`,
`timeinput.parse_month` and `parse_year`). The copy (yesterday to 62 days
ahead) answers a span it covers; any other span reads every calendar for it
there and then (`plain._read_span`: one that fails is a small line, all failing
is said). The answer is in date order (`rules.in_span`: all-day first on a day,
a multi-day event once): by day up to 7 days (the week's layout), by week up to
62 (a "Week of" heading, a date), one list longer, 25 in full then "+N more".
With the week view on, a day, this week and next week keep its layout. A week's
count is now of events, not of event-days. Checks: every calendar check 85 of
85 (12 new phrasings, routers too), US$0.154.

## All-day events (21 Oct, midday)

Live, 11:08 am: "Add an all day event 21 and 22 November, <a hen/stag do>"
reached the calendar, which could not add an all-day event and, with no
time, asked "What time?" in a message of its own (not a question on a
card, against CLAUDE.md). "All day" then went to the router as a new
message, and extraction said "Not included: All day". Fixed: `calendar_add`
takes `all_day` and `last_day` (an all-day event over 1 to 31 days, the
API's end the day after; a repeating one is said to be not yet possible);
with no time the card asks "At what time?" with an All day button, and a
typed answer is read against the card (`request.previous` keeps its title
and days). Two causes found on the way: a title typed with a curly
apostrophe ("Jo’s") is handed back straight ("Jo's"), so `title_from`
folds them; and `conversation._in_common`, which decides whether a
follow-up is about the open card, compared titles exactly (case and
apostrophe), so "All day" restating the title was taken as a request of
its own. It now compares words whatever their case, spacing or apostrophe.
Checks: the new 7 of 7 (w25 to w27, made-up names), every calendar check
61 of 63 (the two misses: "work starts at 8:30 from next week" to the plan
task, from a longer routing line, put right and 3 of 3 since; "am I free
at 3" read as 3:00 pm, as on the code before).

Then (Alex, 21 Oct, after midday): moving and deleting one, refused before
with the line meant for another calendar. `_mine` takes the bot's own
all-day events (a repeating all-day one is said, never changed); a move is
to a new first day keeping its number of days, or to a last day said
(`calendar_move.last_day`), a time for one said; a delete is its red card;
undo puts either back (`calendar_changes.detail`: all_day, before, after).
Every calendar write check 53 of 53 (with w28, w29), US$0.104.

## "Delete the gym plan" was declined (19 Oct, after 11:36 am)

Live: said a minute after the first import was saved, so the gym read it
first (its own answer, without the router), extraction said it can't: the
actions said "a kept plan", which Claude read as never the active one
("No action deletes the active plan"). Not routing: the router sends these
to the gym (checked again: 7 of 7, with "Delete the gym plan" and "switch
to the previous plan" in #gym). Fixed in the actions' words: any of the
user's plans, the active one included; "the gym plan" with none named is
the active one (switching with none named is the other, or asks which); "my
gym plan" (its workouts) apart from "my gym plans" (the list). A card's
answer names its plan by id. Checks: every gym extraction 23 of 23 (with
the live case after an answer), routers 7 of 7, US$0.086 (NZ$0.15).

## Shipped (19 Oct, 11:27 am): #gym listens, and gym plan versions

Live on `3fab84c` (from `f2c8b78`), one restart with no card waiting. The
self-test before it: 150 steps, none failed. Checked: live's own account;
the gym migration applied; no errors. Live had no gym plan imported yet,
so nothing was carried over: the first logbook sent in #gym is the first
version.

## Gym plan versions (19 Oct, midday)

As Alex asked: each CSV or XLSX imported is a plan of its own, named
"YYYY-MM-DD — <split> <weeks>-week" and made active, the one before kept;
show, switch and delete in words; the log separate, each session with the
plan active then. Recorded checks: every gym extraction again (the schema
changed) 20 of 20 once three plan names were accepted as Claude gave them
(from the state, which Python's match finds the same); routers 9 of 9; the
import's three logbooks again twice (the split, then sharper). About
US$0.15 (NZ$0.27). 14 tests.

### Decided (19 Oct, gym plans)

- **The database keeps the plans; the JSON files are copies.** The rules
  keep every record in SQLite with a user_id and appended migrations, so
  `gym_plans` is where a plan is; `data/gym/plans/<day>.json` is written as
  Alex described (name, uploaded, active, exercises) whenever a plan is
  added, switched or deleted, and never read back. A second plan on the
  same day is `<day>-2.json`. The dev bot's go to `data/dev-gym/plans`.
- **Switching and deleting are cards** (every change is), and the
  confirmation is in Alex's words: "✅ <name> is now your active plan." with
  "<n> exercises across <d> days, <w> weeks." Importing says the same.
- **The split is Claude's** (in the importer's existing words request, no
  new one); the weeks are Python's: the logbook's own week numbers, else the
  dated sessions' span rounded up. With no weeks, the name has none.
- **Switching starts the rotation at the plan's first workout.**
- **The same logbook sent again is not logged twice**: a session already
  in the log (its day and workout) is left out. Before, it was added again.
- **The plan kept before** became the first version at the migration,
  named from its workouts (`split_of`, mechanical: a trailing number or
  letter dropped) and its log's weeks, dated the day of the migration.
- **Matching a plan is Python's**: the words' tokens against the name and
  the month it came; two that fit equally are a question on the card.

## #gym listens (19 Oct, late morning; ships at the next restart)

Live gap: the bot read plain words only in #inbox, the hub and direct
messages. Now a task may name its own channel (`Entry.home`; the gym's is
#gym): the bot reads there, the router is told a message there is most
likely the gym's (`routing.home_line`), and anything else is routed as
anywhere. A CSV or XLSX sent there is the gym's import at once
(`Entry.home_files`), with no router. Router checks in #gym: 6 of 6
(gh1 to gh6), US$0.029 (NZ$0.05). 7 tests.

### Decided (19 Oct, #gym)

- **A hint, not a shortcut**: a message in #gym still goes through the
  router (one request, as anywhere), with one line saying where it was
  sent; nothing is decided in code, so a question or another task's
  request is answered normally.
- **The weight tracker has no home of its own**: "weighed 82.4" in #gym
  is routed as anywhere (it is plainly the weight's).
- **Replies in #gym are not swept**: the conversation tidy is the hub's.

## Shipped (19 Oct, 10:20 am): Alex's answers

Live on `f2c8b78` (from `a41e8aa`), one restart with no card waiting. The
self-test before it: the 11 touched steps, none failed. Checked: live's own
account, no errors, every event up to date (his own renamed), the pinned
list redrawn: "**Your birthday** · Tue 20 Oct · tomorrow", and the same
line in the briefing's Upcoming birthdays box.

## Alex's answers (19 Oct, late morning)

- The 20 Oct row named Alex is his own birthday now (`mine`, shown "Your
  birthday"): one row in live's database, with his yes; its event is
  renamed and the list redrawn at the next start.
- The pronoun list in `birthdays.tidy` is an approved exception (RULES.md,
  and the word-list table in BACKLOG.md).
- "I was born on 3 June 1995" routes to birthdays (an example in its
  entry) and is his own birthday with the year. Every birthday extraction
  checked again against the schema with the name not required: 13 of 13;
  the routers for bd1, bd2, bd7 and bd9: 4 of 4. US$0.075 (NZ$0.13 of
  NZ$0.15). `evals.live --extractions` runs only the extraction checks.

## Shipped (19 Oct, 10:08 am): birthdays reworked, and cards that wait a day

Live on `a41e8aa` (from `8f78b5f`), one restart with no card waiting, the
next pill reminder at 11:18 am. The self-test before it: 150 steps, none
failed. Checked: live's own account; the nudges migration applied; no
errors; every birthday's event renamed and marked at the start; the pinned
Birthdays list posted in #calendar (after Discord's rate limit). Not done:
the 20 Oct row is named Alex, not "My" (Alex had saved it again), so the
migration left it a person; marking it his own needs a write to live's
database, which was not allowed. Spend this batch: US$0.058 (NZ$0.10).

## A card that had "gone" on Save (19 Oct, morning; ships at the next restart)

Live, 9:33 am: Save on a repeating Work event took 5.8 seconds (the Bot
calendar's write); the card showed nothing meanwhile, a second tap 6
seconds later found it saved and said "the card has gone and nothing was
saved" over the confirmation. The event was saved (the calendar's change
log has it). Not a restart (none since 1:14 am), an expiry or the tidy.
Fixed: a Save still going after a second says ⏳ Saving… with no buttons; a
second press meanwhile does nothing; a press after Save shows what Save
said. As Alex asked: a card waits 24 hours (a week at a time in #guide, or
pinned or 📌), the hub's morning tidy never takes a waiting card (it took
any hub message from a day that was over), and an expired card offers
Redo, the task's extraction on what was said (one request; the router is
not asked again), once.

## Birthdays reworked (19 Oct, morning; ships at the next restart)

Alex's rework (his words in DESIGN-LOG): no posts or pings; the briefing's
small grey 🎂 Upcoming birthdays box from 14 days; one pinned 🎂 Birthdays
list in #calendar; the Bot calendar's events marked and never a calendar
item; the weekly line. With it the live bug "my birthday is 20 October"
saved as a person called My, fixed after extraction and in the data by an
appended migration (every kept name tidied; each event renamed and marked
at the next start, once the Bot calendar can be written to). Recorded
checks: 11 of 12 new or changed (bd9's router a known miss), US$0.058
(NZ$0.099 of NZ$0.10).

### Decided (19 Oct, birthdays)

- **Tidying a name in Python** (Alex asked for it after extraction): the
  rules forbid a word list as the way something is understood, so
  extraction is told the rule (`_WHO`: the name alone; the user's own is
  "me") and Python's `tidy` is a safety net only: the spaces, a trailing
  's, a leading "my", a capital, and what is left of my, me, myself, I or
  mine is the user's own. CLAUDE.md's rule and this request conflict on
  that one small list: said here.
- **The name is not required on birthday_add**: a required name is turned
  into "it" by `as_references` when the message points ("it's my birthday
  on 20 October"). A missing name asks whose. This was changed after the
  checks were recorded (the cap was reached); the recorded answers all
  have the name.
- **"I was born on 3 June 1995"** routes to nothing (a statement): a known
  miss in the fixture, not fixed, since the cap was reached. Its extraction
  is right once routed; "my birthday is…" routes correctly.
- **The heads-up is each birthday's own** (14 days unless changed in
  words: "tell me 5 days before Mum's birthday"); the posts' "days before"
  are gone from what extraction is told.
- **1 day to go reads "tomorrow"** in the box and the list.
- **The weekly summary's birthdays line is new**: there was none to keep,
  so the next 14 days after the week are one line.
- **The plan no longer lists a birthday** (Alex: only the box and the
  list). The calendar's reader leaves out any event with the bot's marker,
  so the marker is checked in one place for every surface.
- **Also fixed**, found by the suite on a Monday: "last Tuesday" said on a
  Tuesday read as today (now a week ago), and the weekly wishlist line
  missed a wish made on Monday morning (UTC still Sunday).

## Shipped (18 Oct, 1:14 am): the gym's add-ons and the bedtime nudge

Live on `8f78b5f` (from `55e3695`) with `GYM_WEIGHT=true` and
`BEDTIME_ENABLED=true` (live's `.env` as it was:
`data\env-before-2026-10-18-weight-bedtime`), one restart, the next pill
reminder at 8:00 am. Checked: live's own account; the bedtime's and the
gym's three migrations applied; no errors; the hub as it was; 25
bookings. The bedtime sends nothing until Alex sets one. The self-test
before it: 149 of 150, none failed. Overnight spend in all: about
US$0.44 (NZ$0.75) of the gym's NZ$1.00, its add-ons' NZ$0.40 and the
bedtime's NZ$0.20.

## Shipped (18 Oct, 12:35 am): the gym

Live on `55e3695` (from `e9997d1`) with `GYM_ENABLED=true` (live's
`.env` as it was: `data\env-before-2026-10-18-gym`), one restart, the
next pill reminder at 8:00 am. Checked: live's own account; the gym's
migration applied; openpyxl installed; no errors; the hub as it was;
25 bookings. The self-test before it: 149 of 150, none failed. What's
new for 18 Oct: send your gym spreadsheet; say starting a workout.

## Overnight batch, 17 to 18 Oct (unattended, from 11:45 pm): the gym

1. **The gym task** (`tasks/gym`, `GYM_ENABLED`): import, the rotation,
   the workout card in #gym (🥋_gym: live can post there), the Log
   form, Finish with bests, suggestions, undo; a session described in
   words; swaps and plan changes; questions; the briefing's line, the
   weekly target, the week view; the sheet mirror (`GYM_SHEET`, off).
   19 tests on made-up logbooks (`tests/gym_files.py`).
2. **Recorded checks**: the gym's router and extraction 29 of 29 (the
   note on the right exercise after one description change, 3 of 3);
   the import's two requests on the made-up CSV, workbook and wide
   layout, all three right after the mapping got room for every heading
   (`evals/gym_import.py`, replayed by `test_gym_import_recorded`); the
   router over every task's conversations with the gym on 72 of 73 (the
   miss the same with it off). Golden conversations gy1, gy9, gy15,
   gy16 end to end. About US$0.27 (NZ$0.46) of NZ$1.00.
3. **Design · Gym** posted; it found a bug, fixed with tests: the real
   API gives a note with no target a target of 0 kg, which became the
   suggestion; 0 is none now.
4. **The gym's add-ons** (asked overnight, lowest priority): the weight
   tracker (`GYM_WEIGHT`), training insights, the pain tracker (gym
   notes and the diary). 10 tests; recorded checks 13 of 15 then 8 of 8
   after the gym's description named pain and training; the gym's own
   router 14 of 14 and the diary's fixtures 25 of 25 after it. US$0.14
   (about NZ$0.24 of NZ$0.40).
5. **The bedtime nudge** (`tasks/bedtime`, `BEDTIME_ENABLED`; asked
   overnight, lowest priority): 9 tests; recorded checks 10 of 10,
   US$0.03 (about NZ$0.05 of NZ$0.20).

## Decided (2026-10-18, overnight: the gym)

- **What words mean is Claude's, values Python's**: Alex asked for
  notes about dumbbells to mark a per-hand weight and pain words to
  flag an exercise; the rules forbid a word list in Python, so Claude
  reads each note (pain, per hand, a target weight like "go up to
  40-45kg") and each set's purpose (to failure or not) and each
  exercise's kind (for its weight step); at import in one request for
  all the distinct words, and for a note typed in the Log form in one
  small request. Python reads every number.
- **The plan is each workout as last done**, in the order the workouts
  were first seen; the log is every dated session. A DNF workout, or
  one with nothing done, is planned and not done: in the plan, not in
  the log, counted on the card. The rotation goes on after the last
  workout logged.
- **The queue**: finishing a workout sends it to the back, wherever it
  was; so "do Lower 2 instead" leaves the head of the queue next, as
  asked. "Skip" sends one to the back. Off-plan leaves it as it was.
  One session open at a time: starting another finishes the open one
  as it stands.
- **The Log form**: Discord's forms hold five boxes, so up to four
  sets are a box each (the suggestion filled in, "40 kg × "), and more
  are one long box, a line a set; the note is the last box. A box left
  as it was filled in is a set not done.
- **The card's buttons**: a Log button on each exercise not logged; if
  that is more than one message holds, one dropdown instead.
- **Suggested weight**: double progression from the last to-failure
  set (else the last working set): at the top of the range +2.5 kg
  (barbell, dumbbell), +5 kg (machine, cable); 5 or more over the top,
  Epley's estimate for the top of the range, rounded down to the step;
  a note's target first; under or in the range, the same. Warm-ups
  about half. Each exercise may have its own step ("bench steps are
  2.5").
- **Bests**: the heaviest weight for a target rep range, and the most
  reps at a weight, working sets only; a first time is no best.
- **Nicknames**: Python matches the whole name, part of one, and a
  plural ("laterals"); an initialism ("RDLs") is Claude's to hand over
  as the plan names it, from the state it is given.
- **Weight is a private entry of the gym** (as birthdays are of
  reminders): no weight in a log, no attention item, so never on the
  lock screen or the status line. The trend is exponentially smoothed,
  each weigh-in moving it a tenth of the way (the Hacker's Diet way).
- **Muscle groups and swaps are config tables** by exercise name (as
  Alex asked), with Claude only for a name the table doesn't know, kept
  so it is asked once. A stall is no gain in the top set's weight, then
  reps, over 3 sessions against the one before; an imbalance is one
  side half as much again as the other over 4 weeks.
- **Pain from the diary**: the diary's own extraction now says when its
  words speak of pain and where; the gym keeps the day and the body
  part only, never the words. No medical advice: a count, a swap to try,
  and from 3 times on one exercise "worth checking with a physio or
  doctor".
- **The bedtime's rows are Alex's schedules**: saving a bedtime makes a
  Wind down and a Bedtime row for each time and its days (the old ones
  removed), so "my schedule" shows and moves them; a bedtime before
  4:00 am is the next morning's run. Until one is set nothing runs.
- **"Goodnight" quietens the bot's own nudges for the night**: the
  wind-down, the bedtime line and the diary's ask. Pill reminders keep
  their rules, and reminders Alex set himself still come: they are his
  own asks, like a pill's.
- **The diary's ask folds into the wind-down** when the wind-down comes
  within 30 minutes after the ask's time: the ask steps aside and the
  wind-down carries its question and buttons (and a reply to it is the
  entry, as before). An ask after the wind-down is folded the same way,
  having been asked there already.
- **Tomorrow's first thing** is the first event (a planned gym session
  is one) or the first dose, from every task's day.
- **The grid reader is core** (`core/grid.py`): the smart inbox reads
  XLSX with it too, and a gym logbook sent there goes to the gym's own
  import card.

## Shipped (17 Oct, 11:10 pm)

Live on `e9997d1` (from `e127088`), one restart, no pill reminder before
the 6 am checklist. Checked: live's own account, no errors, #commands
unchanged, the hub as it was (nothing posted by the start), all 24
bookings there (12:01 am Week view, 3:00 am backup, 3:30 am nightly, the
6 am routine, 9 am renewals and birthdays, 9 pm diary ask).

## Shipped with it (17 Oct, late)

- **A day and no time is a to-do** (Alex's rule): "I need to call the
  bank on Friday" is a to-do for Friday, "call the bank Friday at 10" a
  reminder. In code after extraction: reminders' `prepare` hands the
  request to the to-dos' add (`actions.HandOff`, core shows that task's
  card; the smart inbox too). Golden tests x45, x46 and "remind me …";
  the inbox's i1 (renew rego by Friday) is a to-do now. Recorded checks
  x5, x45, x46: 6 of 6, US$0.02 (about NZ$0.04).
- **The dev bot's own status line** is its last self-test and this
  month's self-test spend ("✅ 149/150 · NZ$3.64 of NZ$3.50", the clock
  after it when moved); live's line never shows any of it.

## Shipped (17 Oct, 10:07 pm)

Live on `e127088` with `PLAN_MY_DAY`, `BIRTHDAYS_ENABLED`, `WEEK_VIEW`
and `CALENDAR_CHANNEL_ID` (🗓️_calendar) added (live's `.env` as it was:
`data\env-before-2026-10-17-evening`), one restart, no pill reminder due
before morning. Checked: live's own account; the task migrations
(reminders 3, plan 1, week 1) applied, no errors; #calendar has this week
pinned and next week below; every booking there (12:01 am Week view, 3:00
am backup, 3:30 am nightly, 5:30 am read pick, 6 am briefing and cards,
9 am renewals, birthdays and bugs, 9 pm diary ask, Sunday 7 pm summary).
What's new for 18 Oct: plan my day, birthdays, ✍️ Write, the week in
#calendar. The dev-bot self-test before it: 149 of 150, none failed,
recorded answers. Batch spend US$0.27 (about NZ$0.46).

## Evening batch, 17 Oct (unattended, from 8:30 pm)

1. **Plan my day** (`core/planning.py`, `tasks/plan`, `PLAN_MY_DAY`):
   "plan my day", "plan tomorrow", "replan", "what should I do now?";
   to-dos placed around what is fixed, a card with Save, Put it on my
   calendar and Cancel, changes in words before saving, the times on
   the Today card. 21 tests.
2. **Birthdays** (`tasks/nudges/birthdays.py`, `BIRTHDAYS_ENABLED`):
   "Mum's birthday 12 March", "Sam 3 June 1995", gift notes, a quiet
   line from 14 days, posts 3 days before and on the day, the Bot
   calendar's yearly all-day event, upcoming and when. 16 tests.
3. **The diary, asked mid-batch**: the 9 pm ask is "📔 How was today?"
   with ✍️ Write (a form, one long box) and the three moods; a reply to
   the ask is the entry; a mood with no words offers "Add a few words"
   once; a Write on a written day appends. Every surface shows only the
   streak and whether today is written; the week says days written out
   of 7. Nothing is deleted. Tests updated and 10 more.
4. **Recorded checks**: plan and birthdays 26 of 28, then 9 of 9; the
   inbox's birthday 1 of 1; the router over every task's cross-task and
   golden conversations 70 of 71 (x5, below). US$0.26 (NZ$0.44).
5. **The status line is Alex's own things only** (asked mid-batch, from
   a screenshot of live: self-test spend · NZ$3.64): `attention.Item.dev`
   for dev mode, a self-test's result or bug and the nightly, and
   `top_mine` never picks one; the self-test's spend over its cap is a
   small line in the week's summary only. Which runs took it over: the
   15 runs with real requests on 13 and 14 Oct (13 full self-tests at
   about US$0.15 each, while the self-test was being built), US$2.06,
   NZ$3.64 at today's rate; the one at 1:47 am on 14 Oct crossed
   NZ$3.50, and nothing has spent since. The cap already only stops real
   requests: every run goes ahead on recorded answers, the nightly too.
6. **The diary is never on the Today card**: its one line is in the
   briefing's The day ("📔 streak 5 · written today", "· not yet" from
   6 pm).
7. **The week view in #calendar** (`tasks/week`, `core/weekview.py`,
   `WEEK_VIEW`): this week pinned (a box a day, today highlighted, past
   days faint), next week below (a line a day), edited in place at most
   once a minute; "my week" anywhere, and the calendar's "this week",
   "next week" and "what's on Thursday" in the same layout. Live can
   view, send, read, edit and pin in `🗓️_calendar` (checked from
   Discord's own answer): nothing to grant. 10 tests.
8. **Previews**: "Design · Plan my day and birthdays" (16 cards, the
   diary's Write and the week view too) and "Design · Round 6 timeline"
   (`core/timeline.py`, `DESIGN_ROUND=6` a preview round). Phone screens,
   round 5's real hub (a day run by the dev bot tonight, 43 of 43) at
   7:30 am, 12 pm and 9 pm: 3.5, 2.5, 4.5; round 6 at 7 am, 12 pm and
   8 pm: 2.5, 2.1, 1.4 (a busy day of 18 items: 2.8, 2.4, 1.6). Alex's
   words are in `docs/DESIGN-LOG.md`. The day replay no longer stops when
   started after 4 pm the day before its Sunday.

## Decided (2026-10-17, evening)

- **Plan my day's engine is core, its words a task**: the router routes
  only to tasks, so `tasks/plan` is the conversation over
  `core/planning.py` (as the schedule task is over the scheduler); no
  hub card, no job, no ping. Every task hands its day over through a
  new contract hook, `plan` (`Entry.plan`, a `planning.Piece` each).
- **What is fixed, and how long it takes**: an event its own span; a
  dose with a time or a timed reminder 5 minutes; a personal routine at
  a time its first 30 minutes, one in a window the first 30 minutes of
  it (the rest of the window stays free); an any-time routine is not
  planned around. Expiries due that day, and birthdays, are all day.
  Today's doses are when each is due now; tomorrow's their planned times.
- **The free block** is 30 minutes, counted without the buffers; a gap
  under 15 minutes is not shown. Starts are on 5-minute marks.
- **A time with no am or pm**: the reading inside the window; a start
  takes the morning, an end the evening; when both fit, the earlier, ❓.
- **Lengths are kept** (`plan_lengths`): Claude's estimate the first
  time, so a replan places the same lengths; one the user says wins and
  is kept as said.
- **Put it on my calendar** is a second card first (core's new
  `Proposal.also`): Save there keeps the plan and adds the blocks.
  Planning the day again takes the day's earlier blocks off, and the
  plan's own blocks are never planned around. A block on the calendar
  is not also a "planned" line on the Today card (the calendar's line
  is there).
- **A day with nothing that fits** is a card with Cancel only and the
  reason; after 10:00 pm "plan my day" says to plan tomorrow.
- **A plan never pings**: nothing is booked by it; the reminders the
  things already have are all there is.
- **Birthdays are a private entry of the reminders task**: in reminders
  as asked, and an entry of their own to the router so that, like the
  diary, a name or a gift note is never in a log (the message log, its
  reply and what was extracted, #bot-log, a Save's log line, a job's
  note). This also keeps the diary's replies and extractions out of the
  log from now on. Behind `BIRTHDAYS_ENABLED`, turned on in live's
  `.env` at the ship with `PLAN_MY_DAY`, since the what's-new lines ask
  to try them.
- **29 February is the 28th** in a year without one, for the posts and
  on the calendar (the last day of February every year).
- **Timing in words**: "tell me 5 days before" changes the days posted
  before (the day itself is always posted); "a month before" changes
  the quiet line's 14 days. A post missed while the bot was off is
  posted late, once, at the nearest stage reached.
- **Done** on a birthday's post takes it away (the day's own post still
  comes); Snooze is the reminders' (10 minutes, 1 hour, tomorrow).
- **A gift note is a card**, as every change to one of my things is.
- **In a plan**, a birthday is all day; one on the Bot calendar comes
  from the calendar only, never twice.
- **The diary's Write is a form** (`cards.Form` with a long box, drawn
  in `interfaces/discord/render.py` only); Discord allows 4,000
  characters in it. A form's words are never logged
  (`cards.register(..., private=True)`), nor is a reply to the ask
  (claimed by the diary, a note logged in its place).
- **A reply to the ask is the entry, in code**: the diary claims a
  reply to its ask's message (kept in memory, read again at start for
  the last two diary days), so no request to Claude and no routing
  change: no recorded checks needed for the diary.
- **"Not yet" from 6 pm**, as before; with no streak the line is "not
  yet" alone, and "no streak" only when there is nothing else to say.
- **"My diary" and "show this week's diary"** still show a mood a day:
  they are Alex asking. Every surface he does not ask for shows none.
- **The ask without moods** (`DIARY_MOOD` off) is the same question
  with Write alone.
- **x5, "I need to call the bank on Friday"**: Alex's answer (17 Oct,
  late) is a to-do for that day; with a time, a reminder. Decided: the
  router may keep picking reminders (it does, every time), and the rule
  is the reminders' own code after extraction, read from the values (a
  day, no time, no "in 20 minutes", no repeat), never from the words.
  Said as "remind me …" (the reminders' own lead), it stays a reminder
  whose card asks the time. The hand-off is core's (`actions.HandOff`),
  so any task may hand a request to another this way; the router's
  fixture for x5 now expects reminders, the card a to-do.
- **The week view reads what a plan reads** (`Entry.plan`): one
  contract for both. A `Piece` that comes every day says so (`fold`:
  doses, routines) and is counted, never listed. To-dos are not in it.
  The calendar's copy keeps yesterday to two months ahead, so a day of
  this week before yesterday shows only what the other tasks have.
- **The calendar's week and day answers use the week view's layout**
  with it on, so "this week", "next week" and "what's on Thursday" show
  reminders, birthdays and expiries too, with no routing change; the
  router's recorded answers for them already pick the calendar.
- **At most one edit a minute** is core's live-message queue with its
  own interval (`every`), so the changes coalesce; the bot's own 12:01
  am schedule (locked) draws today on and, on Mondays, the new week.
  The first post is silent; an edit never notifies. Nothing is said in
  #calendar but the two messages (and Discord's own "pinned" line).
- **Round 6 is a layout, not yet the hub**: built and tested as
  `core/timeline.py`, drawn from the replay's made-up day; the hub's own
  messages in fixed slots and the conversation tidy wait for Alex to
  pick it (BACKLOG, Soon). Round 5's side is the real hub at the
  replay's nearest moments (7:30 am, 12 pm, 9 pm), said in the post.
- **Dev items still in Needs a look**: the rules keep self-test bugs and
  the nightly there (Claude Code deals with them); only the status line
  leaves them out. The spend over the cap is in neither.

## Shipped (17 Oct, 2:25 am)

Live on `98697d4` with `SMART_INBOX=true` (live's `.env` as it was is
`data\env-before-2026-10-17-smart-inbox`), one restart, no pill
reminder near it. Checked: the account, migrations 28 (inbox_kept) and
29 (wishes) applied, no errors, every booking (3:00 am backup, 3:30 am
nightly, 5:30 am read pick, 6 am briefing and cards, 9 am renewals and
bugs, 9 pm diary ask, Sunday 7 pm summary), the briefing's Needs a look
(B2 fix ready, B5 closing Mon). What's new for 17 Oct: "Send several
things at once, or a screenshot, and it sorts them". Nothing set back.
The dev-bot self-test before it: 149 of 150, no step failed (the first
run failed 2.12d by its own check on a Monday's week: fixed). Batch spend
US$0.26 (about NZ$0.45 of NZ$1.00).

## Overnight batch, 17 Oct (unattended)

1. **The smart inbox** (`core/smartinbox.py`, `SMART_INBOX`): several
   things in one message (the router's new `several`), or a photo,
   screenshot, PDF or CSV in #inbox or a DM, sorted onto one card, each
   item read by its own task; Save all, Cancel, a line fixed in words,
   Undo (`Action.undo`). Recorded checks: 14 conversations, US$0.26.
   Preview "Design · Smart inbox" posted.
2. **A fix shipped from the command line shows within a minute**
   (`tasks/bugs/watch.py`).
3. **Expiry phrasings e3 and e6** recorded, both right.
4. **A day in the hub** with an expiry, a repeating Bot calendar event,
   a fix shipped then closed from outside the bot (each in Needs a look
   within a minute) and the smart inbox (words, then a screenshot);
   posted as "Everything on, 17 Oct". It found three bugs, fixed with
   tests: a message with a file and no words was dropped before it was
   read (`main._sender`); a whole date after a weekday ("Thursday 5
   November 2026") could not be read; the briefing's 30-second redraw
   held every dev-bot step for half a minute (live only now).
5. **Brainstorm** (`docs/BRAINSTORM.md`, 48 ideas, from Claude's own
   knowledge, no web search), "Design · Brainstorm" posted with the top
   10, the wishlist (`core/wishes.py`) and the `suggest` skill.

## Decided (2026-10-17, overnight)

- **The smart inbox is behind `SMART_INBOX`** (off by default, the
  rule for new features), turned on in live's `.env` at the ship, since
  the what's-new line says to use it.
- **Only the router's `several` sends a message to the inbox**: two
  tasks without it still get a card each, as before, and an answer
  recorded before `several` existed says no, so every older golden
  conversation reads as it did.
- **A question is never an item**: the chat part is answered first and
  left out; a question the sorting still finds is answered as any.
- **An unclear item, or a task's own question, is asked on the card**;
  Save saves the rest ("Save 3") and says what it leaves out.
- **Undo is each action's own `undo`**: to-dos, reminders, expiries,
  the calendar and the diary have one; a pill log does not (it is
  undone on the checklist, as ever), and the card says so.
- **Files are read only in #inbox and a DM**; a file with no words
  elsewhere is left alone at no cost. Nothing of a file is kept but a
  gym plan's rows (`inbox_kept`); what a file held is a placeholder in
  every log and trace.
- **A gym plan is recognised by Claude, not by a word list** (the
  sorting's own destination `gym_plan`), as the rules ask.
- **"i1" accepted with "renew rego by Friday" as a reminder** (asking
  its time on the card): question 94 asks whether it should always be a
  to-do.
- **The briefing's half-minute redraw is live's only**: the dev bot
  redraws at the usual 2 seconds, or its replay runs out of time.
- **The wishlist keeps no message words**: task and why only; Alex's
  own wishes in his own words.

## Shipped (16 Oct, 1:16 am)

Live on `7daa77c` with `CALENDAR_WRITE=true` and
`CALENDAR_READ=ics,google:CALENDAR_BOT_ID` (live's `.env` as it was is
`data\env-before-2026-10-16-calendar-write`), one restart, no pill
reminder near it. Checked: the account, the calendar's migration, the
hub, the calendar (47 events from the link as before, the Bot calendar
read through Google, nothing failing), every booking (3:30 am self-test,
5:30 am reading pick, 6 am routine, 8 am pill reminder, 9 pm diary ask,
Sunday 7 pm summary). What's new for 16 Oct: "say add dentist Friday 3pm
to try it", its words checked live first (w12, right). Nothing set back.
Batch spend US$0.34 (about NZ$0.58 of NZ$1.50).

## Overnight batch, 16 Oct

1. **The calendar from several sources, and adding to the Bot calendar.**
   `CALENDAR_READ` lists the calendars (`ics`, `google:<id or setting>`);
   each is read through its source, its part of the copy kept apart, and
   the events shown as one, each happening once. Writing, behind
   `CALENDAR_WRITE`, only ever to the Bot calendar: add (a card with the
   title in Alex's own words, the day, the time, the length, an hour
   unless said, and what it clashes with in every calendar), move and
   delete (the bot's own events only; delete a red card), and undo after
   each. One on another calendar is never changed: it is said so, and an
   add offered. 16 tests on a fake Google API; recorded checks 24 of 25
   (the miss a title that was still his own words); x9 and x10 ("gym at
   6", "dentist Friday 3pm") are the calendar's now. One real check of
   the code on the Bot calendar: 0, 1, 0 events, read back, gone.
   `docs/GOOGLE-SETUP.md`.

2. **A day in the hub, everything on.** `python -m selftest.day` now
   runs a Sunday with every switch live has (round 5, the diary, the
   daily read, the week of everything) and calendar writing: the 5:30
   am pick, 👎 then Another one, the dentist added to the Bot calendar
   and moved, the diary's 9 pm ask and an entry, the 7 pm summary. Its
   made-up sources: `READING_SOURCE` (feeds and pages) and
   `GOOGLE_CALENDAR_FAKE` (a file in place of Google), the dev bot's
   only; a job's request has a recorded answer by purpose
   (`h.background`). 37 steps, none failed. Fixed: the week of
   everything counted a personal routine over all seven days, even
   days before it was made (Morning 1/7 when made the day before). Two
   design choices to `docs/QUESTIONS.md` (91, 92). Posted as a reply in
   "Design · A day in the hub", titled Round 5 with everything on.
3. **Understanding across all tasks.** 34 golden conversations (router)
   and 7 (extraction) in `evals/fixtures/spanning.json`: the diary
   against remarks and to-dos, the daily read against reminders and the
   calendar, adding to the calendar against reminders and to-dos, undo
   and corrections straight after each, and questions about the day
   across everything. First run 37 of 41; fixed: the diary keeps what
   was done today too, and gives both tasks beside another's report,
   never a tie (its own line); a destination named by a task's title
   ("to my to-dos") is read, and with two in one clause the last is
   where it goes (Python); a time with no am or pm is the code's to
   read. Then 10 of 10. The nightly self-test now replays every newer
   file (crosstask, spanning, calendar_write, diary, reading): 157
   recorded answers, all right.

4. **Health check.** Live, with every feature on: 110 MB private
   (129 MB working set), far under 300 MB. The dev bot in a full
   self-test: 105 MB at its peak. The full test run: about 45 seconds,
   under the 60-second line, so nothing was changed. The full dev-bot
   self-test: 150 of 150 on recorded answers, 157 understanding answers
   read back right. Spend for the batch so far: US$0.33 (about NZ$0.55
   of NZ$1.50).

## The daily read (15 Oct, late night; built, off, a preview)

`tasks/reading`, behind `READING_ENABLED` (off): one article a day,
AI usage, programming and tech news balanced over a week. The sources
are `tasks/reading/feeds.json` (sixteen, each checked to work), with
any added or removed in words. At 5:30 am the feeds are read, new
articles' pages read to their text (paywalls and teasers skipped),
and Claude picks one for the day's theme with a TL;DR from its text;
with no text there is no TL;DR. Its card comes after the to-dos at
6 am (the title a link, the source, the reading time, the TL;DR small,
👍 and 👎); the briefing's overview has one line. In words: another,
shorter, deeper, save for later (a to-do with the link), the week, the
profile, more or less of something, a source. A failing source is
quiet; every source failing 3 days running is in Needs a look. The
Sunday summary has a line. Tests: 25. Recorded checks: 17 of 17
(US$0.071); one real pick on the real feeds (US$0.005). Posted as
"Design · Daily read"; questions 86 to 90.

## Shipped (15 Oct, 10:34 pm)

Live on `9caace7` with `DESIGN_ROUND=5`, `WEEKLY_ALL=true` and
`DIARY_ENABLED=true` (live's `.env` as it was is
`data\env-before-2026-10-15-ship-r5`), one restart, no pill reminder
near it. Checked: the account (live's), the diary's two migrations,
the hub in round 5 (the date as the briefing's title, the finished
checklist gone, Alex using it straight after), the bookings (3:30 am
self-test, 6 am routine, the diary ask at 9 pm from 16 Oct, the Sunday
7 pm summary). The full self-test before it: 150 of 150 on recorded
answers. Design forum: Round 5 Live, Round 4 Retired. What's new for
16 Oct: four lines. Nothing set back.

## Bug from live: when doses were taken (15 Oct, late night; ships at the next restart)

"When did I take my pills today" (message #576) was read as what is
left. A new action, `pill_taken` (`tasks/pills/taken.py`): each taken
dose and its time, then skipped and missed, for today, yesterday or a
named day, narrowed by a pill, a dose number or a part of the day; when
a pill was last taken; `also_left` adds what is left. `pill_today` and
`pill_history` say what is theirs. Golden 30 is the exact message;
30a to 30g the phrasings, 9 of 9 after `pill_history` was told a named
day is not its (yesterday may go either way: both list each dose's
time). Spend US$0.041.

## Alex's answers: the order, the diary's misses (15 Oct, late night)

1. **One order, said by each task** (`Task.place`, `Entry.place`; no
   list in the core): pills 10, the Today card 15, reminders 20,
   personal routines 30, the gym 40 (later), calendar 50, diary 60,
   to-dos 70. The briefing's overview, the hub's cards (their morning
   order is `hub.CARDS_ORDER` plus the place), help and the week of
   everything all follow it. The router's catalogue keeps the load order,
   so its cached prompt does not move.
2. **Question 85, yes:** with the diary on, a message only about the day
   or a feeling is kept in today's entry (`Entry.keeps`; the router is
   told of it only when a task keeps something, `routing.KEEPS`), with
   the quiet line ("📔 Saved · 😞 Bad") and an Undo button. Every write
   now has an Undo: it takes the entry back as it was before that
   message, its mood too (a migration adds the undo columns).
3. **"Remind me ..." is a reminder** even when it names the diary
   (`Entry.leads`, reminders declare "remind me"): it outranks a named
   destination (`routing.stated`).
4. **"Bought the milk"** ticks off the open to-do: the hint the router
   gets for a word of a name now says a thing done is a report.
5. **Recorded checks:** d2, d11 and d12 no longer known misses; new
   router checks d22 ("I'm so tired today", the diary), d23 and d24
   (remarks, still nothing); a to-do done extraction for d11. Live: 18
   of 19, then 5 of 5 after the router's "I'm tired" example moved into
   the keeps rule. Spend US$0.106 (about NZ$0.18 of NZ$0.30).
6. Questions 80 to 84 answered with the suggestions, 85 yes: gone from
   `docs/QUESTIONS.md`.

## Round 5, the known miss, the advisor handover, a diary (15 Oct, late; nothing shipped)

1. **Round 5**, behind `DESIGN_ROUND=5`, posted as "Design · Round 5" with
   a yes or no asked item by item: the briefing as the morning overview
   (the date with the dots as its title, Needs a look and Weather boxes,
   one overview box with a line a task and no progress, no footer), cards
   all done leave the hub, and the suggested answers to 68 to 75. The day
   in the hub run in round 4 and round 5 (33 of 33 each), side by side.
2. **The known miss** (x16, "is the gym on tonight?"): the calendar now
   gives this week's event names to the code's own name matching, so
   the router is hinted that the word typed is one of its events; a
   hint now also takes a whole word of three letters of a name of one
   or two words ("gym"; never "the"), as "gym" was too short for one.
   Checked live with the hint sent: x16 the calendar, x9 ("gym at 6")
   and x10 still reminders, 3 of 3. No longer a known miss.
3. **The advisor handover** rewritten to match today.
4. **A diary** (`tasks/diary`, behind `DIARY_ENABLED`, off; `DIARY_MOOD`
   on): an entry a diary day to 4:00 am, messages appended, a mood on a
   small scale (`tasks/diary/mood.py`, each entry keeping its scale), the
   mood by words or buttons with undo, one evening ask at 9 pm, a streak,
   the Today card's line, the briefing's line, the week's moods, reading
   back and deleting. Its words stay in the database: the message log,
   #bot-log, errors, the log file and the router's memory keep a note in
   their place (`Entry.private`). Understanding checks: 18 of 21 right,
   three known misses. Posted as "Design · Diary"; questions 80 to 85.
5. Spend: about NZ$0.20 of NZ$0.40 (the diary checks NZ$0.18, the
   known miss NZ$0.02).

## Previews: the week of everything, gym onboarding (15 Oct, late)

1. **The Sunday summary for everything**, behind `WEEKLY_ALL` (off; it
   needs `WEEKLY_SUMMARY` on as well, which live has): one card, a box a
   task, each with one line for the week and the detail small. Pills:
   taken, late (half an hour after its time), missed, skipped, the
   streak. To-dos: done this week, still open, the oldest. Routines: days
   done each, as dots. Calendar: next week counted by day, the first
   time, never a name. Posted as "Design · Weekly summary" (a busy and
   a quiet week). Not on live: it ships with the next update.
2. **Gym onboarding sketches**, no code: A (attach the sheet or paste
   its rows), B (a short guided setup), C (the plan in one message),
   each with logging and changing later, in
   `docs/drafts/gym-onboarding.md` and posted as "Design · Gym
   onboarding sketches". Questions 76 to 79.
3. No requests to Claude: NZ$0.00 of the NZ$0.30 cap.

## A day in the hub, cross-task understanding, a cost check (15 Oct, evening)

1. **A day in the hub** (`python -m selftest.day`): the dev bot on an
   empty dev database, every switch live has on, a made-up day set up in
   words with recorded answers (Pill A to Pill D, six to-dos, two
   reminders, two routines, a calendar file of made-up events), the
   clock walked from 6 am to midnight stopping at each job, the hub read
   back at 8 moments with the status line live would show; 33 of 33
   steps. Posted in the Design forum as "Design · A day in the hub".
   Fixed (with tests): overdue to-dos held the status line all day over
   every dose and reminder that came due; the line after Taken stayed in
   the hub all day (three of them by night); the briefing's reminders
   box listed what was done, and its calendar line said "first 9:00 am"
   all day; the pills box said "Next" for a dose long due. Choices are
   questions 68 to 75.
2. **Cross-task understanding**: 44 conversations (39 router and 19
   extraction fixtures, `evals/fixtures/crosstask.json`), 6 end to end.
   First run: 15 of 55 wrong. Kinds: a time said with a thing ("gym at
   6", "dentist Friday 3pm") went to to-dos and the calendar; questions
   about part of the day went to the calendar or chat; two things done in
   one message lost the second; "remind me to buy milk" was declined for
   having no time; "done" for a reminder had no action at all; "undo
   that" after a pill was declined; "that was at 9" after a to-do became a
   rename. Fixed: three "only for" lines and four descriptions (no router
   rule), `nudge_done`, `day_left` by part of the day in time order across
   tasks, name hints that allow an ending ("stretches"), and the fixtures'
   own expectations where they were wrong (3). After: 57 of 58 right;
   the one left is a known miss ("is the gym on tonight?" comes back as
   chat; chat then hands it back to the router). Every self-test run reads them back (step u.01).
3. **Cost**: a normal day about NZ$0.10, a busy one NZ$0.25, against
   the NZ$1.00 alert (`docs/COSTS.md`, section 8). Nothing changed.
4. **Lock-screen line**: "💊 Dose due · 2:14 pm", repeats "· 2nd
   reminder" to "· last reminder" (question 11 closed; see Decided).
5. **Shipped** at 6:00 pm: live's folder on `85b0c4e` (from
   `6a942d8`) by `scripts\update-live.ps1`, after the full test run
   (3197 passed) and the full self-test (150 of 150, recorded answers).
   No pill reminder was booked that evening. Checked: the account, the
   checklist brought up to date in place, no warning but the usual one,
   every booking (midnight, 3 am backup, 3:30 am self-test, 6 am
   routine, 7 am check, Sunday summary). Spend NZ$0.79 of NZ$1.00.

## D1, closing bugs in words, questions 91 and 92 (16 Oct, morning)

- **D1 was the 3:30 am nightly self-test on the 1:16 am code:** 20 of
  150 steps failed (1.01b on, 5.01, 6.01 and after). The bot was not
  at fault: the self-test says every switch for each of its starts so
  that live's `.env` never decides a step, but its list had no line for
  the switches added this week (the diary, the daily read, calendar
  writing and the Google calendars). Run from live's folder, the dev bot
  took them from live's `.env`: the schedules had two rows more than
  the steps expect, and the daily read pick failed in the dev bot with
  no feeds, which then topped the status line steps. Fixed: the list says
  them all, and a test fails when a switch in `.env.example` is missing
  from it. Live's own 5:30 am pick worked (one feed of 16 unreadable).
- **Closing bugs in words:** "close B2", "close B2 and B5", "B5 is
  fixed", in #inbox or a DM: closed as fixed at once, each post as after
  Fixed, one line with an Undo. Only the owner; a self-test's D bug is
  never closed by words on live.
- **Needs a look says a bug in a few words of its own:** "B5 · fix ready
  to check", "D1 · nightly check failed, 20 steps"; never the report's
  text (it can hold an emoji or a pill's name).
- **Question 91:** the Sunday summary is posted at the bottom of the hub
  as a one-off and goes at the next morning's tidy; the replay's order
  check no longer counts a moment's message.
- **Question 92:** the Today card says "Diary · not yet" only from 6 pm
  (to the end of the diary day, 4 am); a 6 pm schedule of the bot's own
  draws the card again then.

## Repeating events in the Bot calendar (16 Oct, midday; ships at the next restart)

- Made in words with the shared repeat engine (every weekday, chosen
  days, every 2 weeks, monthly on a date, until a day, N times) and
  saved as a real Google recurrence: the card shows the pattern, the
  time, the start, the next three dates and its end. One day cancelled
  or moved, this and following (the series split, the past unchanged),
  every time, ended from a day (past kept), deleted completely on a red
  card; "just that day, or from then on?" when it could be either; a
  card first and undo after, each. Only ever the Bot calendar.
- 21 tests on a fake Google that expands a series as the API does
  (daylight saving, a series ended in the past, exceptions); 17 new
  golden conversations, 16 of 17 on the first run (rent on the 1st went
  to reminders, fair for a payment: the fixture is a book club now),
  then 2 of 2. NZ$0.13. The older calendar fixtures were not run again
  (it would have passed the NZ$0.20 cap): their recorded answers replay.
- Found on the way: "9 to 5:30" asked "Is that 9 9:00 am or 9:00 pm?";
  a start and an end said together are now read together (the reading
  that ends the same day), and the question no longer says the time
  twice. A day's length over two hours reads "8 hours 30 minutes".

## Bugs close by themselves (16 Oct, late morning)

- A bug I reported, once its fix is live and a golden test replaying my
  exact messages passes on live's code, is marked fix shipped and closes
  by itself three days later, unless I say reopen B5 or report the same
  words again (then it stays open with a note). Meanwhile Needs a look
  has one quiet line, "B5 · fix shipped, closing Mon", only when
  something else is there too. Close by words still works any time.
- B5 is covered: two golden tests replay its two messages and pass. It
  is marked once this code is live (the mark runs on live's code, at
  the next restart). B2 can't be: its report holds none of Alex's words
  (only the bot's reply), so it waits for close B2 or Fixed.

## Needs a look as it is now (16 Oct, afternoon; ships at the next restart)

- **The nightly's count is reset by a ship:** only a failure on a night
  after the last ship (`data\live-versions.txt`) counts, so the 1:59 pm
  "two nights in a row" (one cause, fixed and shipped) is not said again.
  A ship is taken to carry the fix for what failed before it.
- **A nightly failure leaves Needs a look** once its bug is closed, or,
  with no bug on record, once a ship came after it.
- **Pings are transient:** each goes when what it points at is dealt
  with, or at the next morning's tidy, whichever is first.
- **Severity:** only real problems are ⚠️ and red; what is only worth
  knowing ("B5 · fix shipped, closing Mon") is small and last, and on its
  own one small line in the overview, no box. The briefing is redrawn on
  every change (a bug opened, closed, reopened or marked shipped, a
  nightly result, a restart) at most once every 30 seconds.
- **B posts:** four extra B posts of 10 Oct (two B1, a B2, a B3), filed by
  a dev database before dev bugs had their own letter and held by no
  database, were closed with a note; Alex's real B1 to B5 untouched, none
  renumbered (no two share a number). B bugs can be filed only in live's
  folder now; close B2 acts on live's own B2, found by its number in
  live's database.

## Live down for a minute (16 Oct, 1:31 pm)

The ship of `dbbdcc8` stopped live at its start: the two ping migrations
had been put in the middle of the core list (before
`_create_exchange_rates`), so live's database, at version 25, ran the
seed without its table. Put back with `-Back` at 1:32 pm, about a
minute down; every database stayed at version 25 (each migration runs
in a transaction). Fixed: the two appended at the end, a test that pins
the order of the 25 live has, and the update script now migrates a copy
of the database with the new code before it restarts anything (it
refuses the broken order, and passes the fixed one: version 27).

## Decided (2026-10-16, midday)

- **Expiries in reminders** (not a task of their own): "Kiwa domain
  expires 3 March, yearly", "passport expires June 2031" (a month alone
  is its 1st, said on the card), "rego due 14 Nov, every year". Told 30,
  7 and 1 day before ("remind me 60 days before" changes it): quiet in
  the briefing's overview line, then the day before posted like a
  reminder with Done and Snooze, held by quiet hours, never ntfy, the
  phone showing "🔁 Renewal due · 3 Mar". Renewed in words or by Done:
  one cycle on from its own date (31 Jan monthly is 28 Feb then 31 Mar;
  29 Feb yearly is 28 Feb, then 29 Feb in a leap year), the new date said,
  Undo; with no cycle it is done. "What's expiring soon?": 90 days. Gone
  by: one line in Needs a look, never a ping. 14 tests. Recorded checks
  against reminders, to-dos and the calendar: 11 of 15 first, three of
  the misses the fixtures' own (a state that had them already; "60" as
  text), one real ("renew the passport", a to-do, went to reminders: a
  line in the reminders' description), then 5 of 5; US$0.11, about
  NZ$0.19. Two extraction fixtures (e3, e6) are left without a recorded
  answer: asking again would have passed the NZ$0.20 cap.

- **The daily read, practical** (Alex: "very academic, maybe too high
  level"): for a working web developer curious about AI; how-tos, tool
  tips, worked examples, I built X with Y, plain-English news. Claude
  rates every candidate for difficulty (1 beginner to 5 research) and
  practicality (1 to 5); the pick is from difficulty 2 to 3 with
  practicality 4 or more ("easier", "harder", "more practical" move it),
  asked once more from those in range when the first is not; both kept
  with the read. The TL;DR ends "After reading, you will be able to …".
- **Sources:** dropped Latent Space, Hugging Face blog, Eugene Yan
  (research-level) and Dan Luu (long essays, and the one that failed:
  6.6 MB, over the 3 MB cap); added Addy Osmani, GitHub blog, Vercel
  blog, Kent C. Dodds, Frontend Masters blog, each read through the
  code. A feed over the cap is now read up to the cut (Vercel's is 3.9
  MB), newest first, so nothing new is lost.

- **The range fix:** live's log at 11:05 showed "a stated time was put
  back (7:00 pm → 10:00 pm)": in "… 7 to 10pm" the stated-time check
  counted only times with am or pm, took Claude's 7 pm for one never
  said, and swapped in 10 pm. A time said without am or pm now counts
  as said. Make, put and book are adding ("book lunch with Sam Thursday
  at 1"), the verb not part of the title: 6 of 6, US$0.03.

- **The 12:06 pm ping** was the 3:30 am nightly's failure again: closing
  its D1 took the bug's id off the item, and pings were kept by bug id,
  so it looked new. Now a problem pings once, ever, by a key that lasts
  (`alerts_pinged`), and self-test bugs never ping, but for the nightly
  failing two nights in a row (once, known by the first night).

- **Duplicate D numbers:** D1 to D3 were each used twice: the work
  folder's self-test (D1 to D13, all closed) and the nightly, which runs
  in live's folder on a dev database of its own (D1 to D3, open). One
  letter a counter now: B live, D the work folder, N the nightly (live's
  folder is told by `data\live-versions.txt`). The nightly's D1 to D3
  were closed with a pointer to the earlier post of the same number, and
  its step list emptied, so its next bug is N4. Nothing closed was
  renumbered.
- **Pills show exact times only** (Alex): no relative countdown on the
  pills card, pill reminders or "what's left today?"; every other
  countdown stays. The 11:43 card's timestamp was right (11:51 am): it
  was drawn at 11:22, and the phone had not brought "in …" up to date.

- The calendar switched to Google only (`CALENDAR_READ=google:CALENDAR_MAIN_ID,google:CALENDAR_BOT_ID`,
  the iCal link removed from live's `.env`, its copy in
  `data\env-before-2026-10-16-google-only`). The feed's Work series had
  no end (no UNTIL; Google last changed it there in March 2020) while
  Google ended it on 5 Aug 2022: the feed was wrong, not our reading
  (the reader stops a series at its UNTIL, checked).
- A repeating event's day field is the happening meant ("next
  Tuesday"); for a change from a day on it is where the series is cut
  ("from 1 November"), found by its name, not by a happening that day.
- "Starts at 8:30" for an event at 9:00 am is the reading nearer its own
  time; "9 to 5:30" is the reading that ends the same day.
- Ending a series before its first happening is refused with "say
  delete": an end with nothing kept is a delete, on its red card.
- The repeat engine's pace and end fields are offered to the calendar
  only, so reminders' and routines' prompts are unchanged.

## Decided (2026-10-16, late morning)

- The self-test runs a step once more (after 10 s) when it failed while
  Discord answered 5xx or a rate limit, and marks it Discord unavailable
  if it fails so again: no D bug, not counted as failed, said in the
  summary. Its stage is not marked passed, so it runs again next time.
  Steps that fail later because of a card left open by it are still
  failures: they saw no Discord error themselves.

- Fix shipped is marked by Claude Code with `tasks.bugs.cli shipped`, run
  in live's folder only (its data folder has `live-versions.txt`): there
  the tests run on the code live runs, so passing there is the fix being
  live. Only golden tests (`tests/test_golden.py`) count, and each of
  his messages in the report must be in the named tests' own code word
  for word (case and spacing aside).
- His own messages are those no bot wrote (each captured message now
  records that); in a report from before, those not by the reported
  message's author (a reaction or reply is on the bot's).
- The same problem again is a new report holding one of his messages of
  the shipped bug word for word: no word lists, no guessing.
- The post is told, and the closing done, by a round of the bot's own at
  9:00 am, so it is safe to run twice and survives a restart. The
  closing day is the shipped day plus three.

## Decided (2026-10-16, morning)

- Closing by words closes as Fixed, never Won't fix: that stays the
  post's button.
- The status line keeps its shortest form for a bug (`B5 · retest`,
  `D1 · self-test failed`); the longer plain words are Needs a look's.
- After every ship, the next nightly self-test's result is checked and
  reported, its failed steps and why (RULES.md, Running and testing).

## Decided (2026-10-16, overnight)

- The calendars are listed in one setting, `CALENDAR_READ`, each as
  `ics` or `google:` with an id or the name of the setting that holds
  it, so an id need not be written twice. Unset, it is `ics`: live reads
  as before until the setting says otherwise.
- With writing on, the Bot calendar is read whether listed or not:
  what the bot adds must show.
- Each calendar's part of the copy is kept apart (`origin`): one that
  fails keeps its last good part, and the others are read as usual. A
  calendar no longer listed leaves the copy.
- The same happening in two calendars is one: the same title (any case
  or spacing) and the same times. The bot's own copy is kept when there
  is one, as it is the one it can change.
- Google is reached with `google-auth` (pure Python, with four small
  packages) only to sign the token request; the calls themselves are
  urllib, as the other sources are. No `requests`.
- Only the Bot calendar is written to: the source checks its id against
  `CALENDAR_BOT_ID` and `CALENDAR_WRITE` on every write, whoever asks.
- A new event's title is the user's own words: the words extraction
  gave, as they stand in the message; words he did not say are never a
  title.
- An event said with a day and a time and no "remind me" is the
  calendar's while writing is on ("dentist Friday 3pm"); "remind me
  about the dentist Friday" is a reminder. The reminders' and the
  calendar's own lines say so, each only while writing is on.
- Moving keeps the length unless one is said; an all-day event is not
  added or moved in words yet.
- The replay's day is a Sunday, set up at 4 pm the day before (the
  clock goes there straight, not through every job of the night), so
  the week of everything runs at 7 pm.
- The replay's made-up sources are settings of the dev bot's own
  (`READING_SOURCE`, `GOOGLE_CALENDAR_FAKE`), as `WEATHER_SOURCE` is:
  never set on live.
- A destination named twice in one clause: the last is where it goes
  ("add write in my diary to my to-dos"); parts joined by "and" or a
  comma keep one each.
- The real check ran the task's own Google code from the work folder
  with live's key and Bot calendar id read from live's `.env` (never
  printed), not through the dev bot, which has no key.

## Decided (2026-10-15, late night: the daily read)

- The read lives on a small card of its own (after the to-dos), with
  one line in the briefing's overview: round 5's overview is a line a
  task with the detail on the task's card, and buttons never go on the
  briefing.
- "Save it for later" is a confirm card, and Save writes through the
  to-dos task's own store and its own word that it changed: the one
  write from one task into another's list, at Alex's word.
- The theme of the day is the one furthest behind its share of the
  week so far, so a week stays balanced however the weights move; a
  theme with nothing new that day falls back to the others' articles.
- A page is read for its text only (inside `<article>`, `<main>` or the
  body). Under 250 words, or with paywall words on it, it is not an
  article: never offered to Claude, so a TL;DR is always from text.
- 👍 and 👎 move the theme's weight a step (within half and double);
  words make a card, as any change to my things does.
- The pick is one request with the text of up to five articles, about
  450 words each (about US$0.004 a day).
- The paywall words are a net for reading pages, not for understanding
  what Alex says, so they are not in the word lists of
  `docs/BACKLOG.md`.

## Decided (2026-10-15, late night: Alex's answers)

- 80: the diary's evening ask is at 9:00 pm. 81: the diary day ends at
  4:00 am. 82: he writes in #inbox and DMs; the hub only holds the
  evening ask and its buttons. 83: the ask is not sent by DM. 84: the
  mood scale stays Good, OK and Bad, to be looked at again after two
  weeks of use (about 30 Oct). 85: yes, a feeling with no request is
  kept by the diary when it is on.
- The order is a number on each task (10 apart, room for the gym at 40)
  rather than a list of names anywhere: a task that says none comes
  after every one that does, in load order.
- The Today card keeps its place under the pills checklist (15): Alex's
  order names the task cards, not the Today card.
- The router's catalogue keeps the load order: reordering it would move
  the cached prompt for no gain in understanding.
- "Remind me" outranks only a destination named in so many words ("in
  my diary"). With none named, the router reads the message as before,
  so "remind me to take my zinc at 8pm" stays a pill's time: a reminder
  of one would put a pill's name on the lock screen. A phrase in Python,
  declared by the task at Alex's word; listed with the word lists in
  `docs/BACKLOG.md`.
- The keeps rule is said only when a task keeps something, so with the
  diary off the router's prompt is the one it had, less the "I'm tired"
  example, which now lives in the keeps rule.
- Undo after a write takes back the words and the mood said with them;
  a mood chosen afterwards by button is undone on its own.
- Questions 68 to 75 stay in `docs/QUESTIONS.md` until Alex says yes or
  no item by item, though round 5 ships with the suggested answers.

## Decided (2026-10-15, evening batch)

- The day replay is a start of its own (`selftest/day.py`), not part of
  the nightly run: it takes about 7 minutes and is for design rounds.
- A snapshot in the post is a header reply (time, status line, what
  happened since, what the hub shows changed) followed by copies of the
  hub's messages: one Discord message holds 40 components at most, and
  a whole hub is more.
- Among things due now, one carried over from an earlier day
  (`Item.carried`, overdue to-dos) comes after what fell due today at a
  time of its own. Its level stays 2, as decided for to-dos.
- The line after Taken goes 30 minutes after, as long as a card waits; a
  time said in words still corrects the dose after that.
- The briefing's reminders box keeps one that went off and is waiting,
  then those still to come; the rest is "✅ N earlier today". The
  calendar line is "next", "on now until" or "all over".
- `Summary.left_at`: when each thing left is due, so "what's left today?"
  is in time order across tasks (untimed last; the pills test's order
  changed with it) and a part of today is worked out by the code.
- A reminder that went off is the hub's latest answer: a short message
  straight after goes to reminders first (one extraction more for a
  question then; it still goes to the router).
- The understanding fixes are prompt lines only: no router rule. The
  router now costs US$0.0040 a request (3,300 tokens, 11 tasks).
- The nightly self-test reads the recorded answers back offline, not with
  pytest: live's folder has no test tools.
- Round 5 is gated by `design.current() >= 5` everywhere, the
  behaviour changes too (questions 73 and 75), so one setting ships or
  takes back the whole round.
- The overview's order is the catalogue's (the order tasks are
  loaded in): fixed, and no list of tasks in the code.
- A card's place in the hub is said by the task (`hubcard.order`);
  round 5 posts the cards that come after a card again under it when it
  comes up mid-day.
- A pills checklist all taken or skipped is deleted from Discord but
  its record kept, so the day still counts as posted; a dose to take
  again posts it afresh.
- The diary's words: with any private task loaded, the log file logs a
  message's length, not its words. A task nothing sticks to
  (`Entry.sticks`): a short message after an entry is read afresh, so a
  pill or a to-do is never taken as more diary.
- The diary's read-back takes a day gone by (`timeinput.parse_past_date`:
  "last Tuesday", "yesterday").
- "remind me to write in my diary at 9pm" is kept as a diary entry,
  because a destination named in so many words decides in code: left as
  it is (a known miss, d12).
- The week of everything goes through the task contract (`Entry.week`),
  as the briefing does with `summary`, and the pills task's Sunday job
  posts it when `WEEKLY_ALL` is on, so its schedule stays the one there
  is. Late is half an hour after a dose's time.
- In the gym sketches, a whole exercise as planned is one tap (Done as
  planned), and pasted rows are read as a `.csv` would be: both are
  suggestions (questions 78, 79), not built.
- Two self-test steps were wrong, not the bot: 3.07 looked for "Today" in
  the checklist, whose page title went with question 64 (it failed the
  same way on the commit before this batch, checked in a worktree); 8.03
  skipped Testlate, which a full run has taken by then (start 8 was only
  ever run alone). 3.07 now looks for the card title, 8.03 has a pill of
  its own.
- The checkpoint commit holds steps 1 and 2 together: their fixes share
  files (reminders, the briefing).
- Question 11 closed (Alex's lock-screen screenshot of 15 Oct named no
  pill). It read "💊 Routine due · 2:14 pm · reminder 1 of 3" at 2:29 pm.
  Not late: the run log and live's log show the reminder posted at
  2:14:01, on time (between the restarts of 1:41 and 3:03), and posted
  again at 2:29:01 as the first of three repeats, a fresh message in
  place of the first; deleting the first takes its notification off the
  phone, so the lock screen showed only the 2:29 one. The 2:44 one was
  not needed: the dose was dealt with at 2:37.
- "reminder 1 of 3" meant the first of three repeats, not dose 1 of 3. A
  dose with a time is posted at its time, again 15, 30 and 45 minutes
  later if left, then it goes (and a last chance 30 minutes before it
  stops fitting the day). Now said as "2nd reminder", "3rd reminder",
  "last reminder", in the line and in the card's small line.
- "Routine" was the bot's own word, never a pill's. Every pill reminder's
  lock-screen line is now "💊 Dose due · 2:14 pm" (with "· 2nd reminder"
  and so on when posted again); it never names a pill or a routine. The
  sketches, the tests and the docs say the same.

## Live in its own folder, Windows Update, two old bugs (15 Oct, afternoon)

1. **Live runs from `C:\Users\temp\projects\assistant-bot-live`**
   since 3:11 pm, on `6a942d8` (everything pushed then). The setup
   script stopped live and then stopped itself at the clone (its output
   was redirected, and Windows PowerShell takes git's progress on stderr
   as an error); live was started again from the work folder at once,
   about a minute down. Then the switch-over in two halves: clone,
   commit, `.venv` and packages while live ran; stopped for well under a
   minute for `.env`, `.env.dev`, `data\` (the database the same size
   both sides), the migration check (25 of 25), and the service pointed
   at the new folder. Checked: the account check, today's 34 logged
   messages and 3 doses, the calendar read (47 events), the bookings
   (3:30 am self-test, 6 am routine, Sunday 7 pm summary), and the
   self-test from live's folder, 28 of 28. The work folder's `.env` and
   `data\` stay as a backup until Alex says all is well.
2. **`scripts\update-live.ps1`** is how code ships from now on: live's
   folder by default, a commit that must be on `origin/feature/pills`,
   `-Back` for the one before. It puts back `docs\SELFTEST.md`, which
   the nightly self-test now rewrites in live's folder, before checking
   nothing was changed by hand. Not used yet: nothing since has changed
   the code live runs.
3. **Windows Update**: active hours were automatic (Windows's guess) and
   nothing was paused. Set from this Administrator terminal, no prompt
   at the machine: active hours 6 am to 12 am (18 hours, the most
   allowed), and updates (quality and feature) paused for 35 days, until
   19 Nov 3:43 pm, the longest allowed. Backlog: a monthly reminder in
   the briefing to update by hand.
4. **B2 and B5**, the two open live bugs: B2 was a test of bug reporting
   (it worked); what it caught, the bot offering help in answer to a
   remark, was fixed when the router began to give words only to
   questions and requests. B5 was "I took dose 1 of Pill A at 9am"
   logged as dose 2 with "Not included: dose 1 of"; fixed in the QA of 12
   Oct, with a golden test of those very messages. Both checked against
   the code live runs (33 tests) and given a note; there is no command
   to close a bug, so they wait for Alex's Fixed.

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
   events that are over in one small line ("🗓️ 2 earlier today"), one on
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
