# Changelog

What changed, newest first. One entry per task, as one to three bullets on
what changed for the user. Entries before 2026-10-07's last one were
backfilled from the git log.

## 2026-10-15

- The hub's round 3 design is built, behind `CARDS_V2`: a message reads
  like a page (a page title, a card title with the topic's dots and
  count, bold names, small details), one box a topic with a rule
  between items, times in bold with "in 2 hours", a change struck
  through then bold, thin question cards that stack, and a card too big
  for one message made to fit rather than refused.
- The pills card puts what is due or overdue first, then what is coming,
  then any time, with what is done, paused or not today in one small
  line; the briefing has a box a topic, Needs a look on top only when
  something is wrong.
- The look before it stays one setting away (`DESIGN_ROUND=1`), and
  `docs/DESIGN-LOG.md` keeps every round, what is locked and Alex's
  feedback word for word; `python -m selftest.preview` posts the real
  cards from made-up data for a look on the phone.

## 2026-10-14

- `docs/ADVISOR.md`, the advisor's handover, checked against the repo and
  kept up to date at the end of every batch.
- A question asked while a card is open ("what's left today?",
  "will it rain?") gets its own answer, and the card stays open with
  its buttons working. Before, the card's task answered it.
- A question always gets its own answer: "what's left today?" or
  "will it rain?" straight after you log a pill is answered by the
  day or the weather, not taken as a follow-up to the pill. A
  correction straight after ("it was 9pm actually") still is.
- The tests run in about 40 seconds (they had grown to nearly two
  minutes), with the same tests and the same checks.

- #commands is edited in place without an error when its text has
  really changed (the first such edit, at a restart, failed and left
  it as it was), and it now lists a task that is only talked to: the
  weather questions appear there from the next restart.

- A change to a pill that is still only on the card, not saved yet
  ("make 11:30, 11am instead"), changes the card. It used to answer
  "There are no pills yet" when it was read as a change to a saved
  pill.
- The week's own messages to live were read back and every misread
  one is now a golden conversation (2c, 18c and 26 are new; 18, 19
  and 20 were there). The golden set, asked of the real API: 56 of 59
  before, 57 of 59 after, the two left being old known misses that
  the code puts right.

- Ask about your day and get an answer from the data, never a guess:
  "what's left today?", "how did I go yesterday?", "and this week?".
  One message each, with the day's dots and count. Behind
  `DAY_QUESTIONS`.
- Ask about the weather: "will it rain?", "what's the weather this
  afternoon?". The weather task answers from the forecast it keeps:
  the chance of rain in the hours still to come and roughly when.
- Golden conversations 21 to 25 are these questions.

- The briefing shows the day's progress at the top: a dot a thing to
  do and the count, in its title ("☀️ Today ●●●●●○○ 5/7"), and one
  small line a task ("💊 2/3"), kept up to date in place as things
  are done. Behind `DAY_PROGRESS`.
- Progress is dots everywhere and never a percentage. The block bar
  is gone, with its sketches; two sketches of the dots (in the title,
  in normal text) are in the design-options post as round 3.
- Round 3 also has five sketches of a type scale (a message as a
  page: one box a topic, a card title with dots, times in bold): a
  draft in `docs/DESIGN.md`, nothing in the real cards changed.

- Docs only: `docs/STATUS.md` is one page again (where things stand,
  what is switched on, what waits on you, what is next), with its
  history in `docs/archive/`. `docs/QA-RUN.md` opens with the ten
  checks only you can do and says for every block whether the
  self-test covers it; four out-of-date blocks are retired.

- A pill reminder that Discord refuses is tried again after 1, 2 and
  5 minutes, then every 5, and is never posted twice. The last-chance
  nudge too.
- Any other scheduled job that fails with an error is tried once more
  a minute later before it counts as failed.

- #commands is brought up to date by editing its messages in place.
  A message is added or deleted only when the number of sections
  changes; the lot is never deleted and posted again.

- A bug the bot or the self-test files itself no longer asks you the
  three questions. A bug you report still does.

- A dose is no longer marked missed when its reminders run out: after
  the third reminder nothing more is sent and it stays to take. It is
  missed only once it can no longer be taken today.
- "That was dose 1", said after a dose was logged, moves that log to
  dose 1 with its time, on a change card. It never adds a second log.
- A card that would add a dose within an hour of the last one says
  so: "You already logged dose 2 at 9:20 am. Add another dose?"
- A dose whose reminders went unanswered gets one last-chance nudge,
  30 minutes before it stops fitting the day: "💊 Last chance today ·
  take by 6:00 pm".
- "That was dose N" moves only today's logs unasked; for an earlier
  day the card says so and asks which day.

- Weather in the briefing: today's low and high, a word for the sky,
  the chance of rain and roughly when, and the wind. Fetched at
  5:50 am and kept current through the day.

- Costs are in NZ$ wherever you see them (`dev cost`, pings, the
  briefing, the status line), at a rate fetched each morning. The
  daily alert is at NZ$1.00 and the self-test's month at NZ$3.50.
- The briefing has one line for yesterday's spend, hidden until
  tapped: "💸 Yesterday: ||NZ$0.42 · you NZ$0.12 · testing NZ$0.30||".

- What needs you now reaches you: it is in the briefing's "⚠️ Needs a
  look" box with its bug, and by day the bot pings you in the hub
  with one line. Between 10:00 pm and 7:00 am it waits, and at 7:00 am
  you get one ping if anything is waiting. Restarts and the like are
  a small line at the foot of the briefing.
- "My schedule" says for every line when it last ran and whether it
  worked.

- The hub tidy is on: what you say in the hub and the reply go once
  handled, nothing of a past day stays, and each morning starts with
  the tidy, then the checklist. The hub was cleared once to begin
  with (a copy is in `data/exports/`).

- A start says nothing any more: no "👋 Online and ready" in #inbox and
  no "🟢 Bot started" card. A restart you asked for leaves no trace; if
  the PC restarted or the bot crashed, #bot-log says so in one line,
  with what was caught up.

- Nothing you would see: the bot's core now reaches Discord through
  one door, and new code may no longer use discord.py directly
  (`docs/INTERFACE.md`). Timers are frozen as they are.

## 2026-10-13

- Quiet hours are on (10:00 pm to 6:00 am). A pill reminder always
  gets through, with its sound; anything else waits, and the briefing
  lists it in the morning until it is dealt with.

- Alerts can also reach your phone through ntfy, switched off until
  you turn it on (`NOTIFY_NTFY`, with `NTFY_BOT_TOPIC`): neutral words
  only, and tapping opens the Discord message. Pill reminders are the
  first to use it; where each kind of alert goes is one table.
- The briefing is in the same order as the status line: what needs a
  look on top, then what quiet hours held back overnight, then a
  section a task.

- Direct messages to the bot, switched off until you turn them on
  (`DMS_ENABLED`): only yours, read like #inbox, answered silently,
  and never with a pill's name in the first line.

- The status line also says a missed dose ("💊 missed 9am"), a day
  with everything taken ("💊 all 5 taken", until 8:00 pm) and dev mode
  left on. A job that fails files its own bug, and so does the bot's
  memory use if it goes over 300 MB or keeps growing; `dev status`
  shows the memory.

- The self-test costs less: recorded answers unless prompts, schemas
  or routing changed (or it is the Sunday full run), nothing on a
  night with no new commits, and a monthly cap (`SELFTEST_MONTHLY_LIMIT`,
  US$2) shown in `dev cost`.

- The status line under the bot's name now shows the one thing to look
  at first: "💊 due 12pm", "💊 2/5 · 12pm", "⚠️ backup failed", "🌅
  6am", or nothing. No more "🟢 Live · up 7h". During a self-test the
  dev bot's reads "🧪 41/103 · 6m".

- Design options to look at on your phone: two or three sketches of
  each main card, posted by the dev bot in its forum. Nothing in the
  real cards changes until you pick.

- With `CARDS_V2` on, more is drawn in the new look: the list of your
  pills, yesterday and the week, the weekly summary, the open bugs,
  the "I was offline" card and the "which task?" question.

- Pills, looking back: "what did I take yesterday?", "show my week",
  and a streak in days in the briefing's pills section. A weekly
  summary on Sunday evening, switched off until you turn it on
  (`WEEKLY_SUMMARY`).

- Pills: a pill can be taken on certain days of the week ("weekdays
  only", "Mon Wed Fri"), and "took zinc last night at 11" after
  midnight logs yesterday's dose (asking first when the day or the
  time is not plain).

- "No, I meant 9pm" straight after Save changes what was just saved,
  on a change card (old → new), and no longer counts as a guess.

- A nightly self-test, switched off until you turn it on
  (`NIGHTLY_SELFTEST`): at 3:00 am the dev bot tests what changed, and
  everything on Sundays. Your phone is pinged only if a step fails.

- Each bot is called what you named it (`BOT_NAME` in its settings
  file). The dev bot shows "· testing" during a self-test; the "· DEV"
  marker is gone.

- Every start of either bot checks which Discord account it is before
  doing anything, and exits untouched if it is the wrong one.

- Live and the dev bot run at the same time: the self-test no longer
  stops live. The dev bot keeps to its own channels (#selftest-…).
- What you say while live is off is asked about when it is back ("I
  was offline when you sent this": Handle it now, or Ignore), never
  acted on by itself.

- A self-test run leaves a record that lasts: a line in
  `data/selftest/history.csv`, a table of the latest runs in
  `docs/SELFTEST.md`, one summary message in #selftest-log, and a dev
  bug in the forum for each failing step, marked Fixed when the step
  passes again.

- The briefing's pills section only reads now: the day's doses are
  made as the day before ends. The run log no longer grows for ever
  (housekeeping runs are kept 30 days, the rest a year). Nothing you
  would see changes.
- The self-test runs only the stages a change touches (`--full` for
  everything), and checks free memory before it starts.

- A clean hub, switched off until you turn it on (`HUB_TIDY`): what
  you say there and the reply go 2 minutes after the reply, yesterday's
  checklist goes when today's is posted, pinned stays, and a copy of
  what is removed is saved first.

- A briefing, switched off until you turn it on (`BRIEFING_ENABLED`):
  one card in the hub each morning, above the checklist, saying what
  today holds and how yesterday went, kept up to date in place; and
  `brief me`.

- `my schedule` shows what the bot does by itself and when, and you
  can change it by saying so: move it, pause it, pick the days, make
  it silent or not, add another time, remove one. Each is a card first.

- Nothing you see changes: the nightly backup, the end of the day and
  the 6:00 am checklist now run from one scheduler with schedules kept
  as rows. `dev jobs` also shows how the last run of each job ended,
  and `dev run` runs any of them by name.

- Logging a dose that was missed asks first ("Dose 1 was missed (due
  11:12 am). Log it as taken now?") and shows what it does to the next
  dose's time. `took <pill>` works for a missed dose too.
- `dev cost` writes a limit under a cent to three places.

- A shortened name that fits two pills ("pause testv") is asked about
  on the card, even when Claude filled the name in by itself.
- Too soon after a dose just logged reads "just now", not "0m after".
- Jobs are named in words wherever you see them ("pill reminder", "end
  of the day"), and the catch-up card after a restart no longer shows
  the code's own names.
- The channel reset card is drawn as a red box in the new look.
- Part of a pill's name in a message ("pause testv") is pointed out to
  the router as a hint, so it is less likely to go to another task.
- Timers' jobs are named in words too ("timer ending").

- A self-test: `python -m selftest` runs the dev bot against real
  Discord in channels of its own (a day of pills on the dev clock, a
  restart in the middle, every card in both looks) and writes
  `docs/SELFTEST.md`. Nothing changes in the bot itself.

- Nothing changes in the bot: the scheduler, the clean-up and the
  briefing are specified, with four sketches to look at (`dev mock
  briefing-v2`, `schedule-list-v2`, `schedule-change-v1`,
  `cleanup-v1`). The standard and the design guide now say the hub
  holds only what is relevant now.

- `took <pill>` (the pill's exact name and nothing else) ticks the
  next dose off at once, with no wait and no cost. Anything more is
  read as before.
- The dev bot can have a token and channels of its own (`.env.dev`).

- One ordered QA run of everything that is waiting
  (`docs/QA-TONIGHT.md`).

- The backlog is one prioritised list (Next, Soon, Later, with timers
  apart as low priority); what was dropped is listed with why.

- A check of every task and the core against the standard after the
  night's changes: nothing for the user to see; two records now take
  the real time from the one clock.

- A script, ready to run by hand, that gives the live bot a folder of
  its own on `main` (`scripts\setup-live-folder.ps1`). Not run.

- A list of phrases that always went to the same task, as candidates
  for free shortcuts (`docs/COSTS.md`). None is added.

- A daily spend line: when a day's requests to Claude cost more than
  `DAILY_SPEND_LIMIT` (US$0.50 unless set), #bot-log says so once.
  `dev cost` shows today's spend against the limit.

- What the bot's requests to Claude cost is measured and written up
  (`docs/COSTS.md`). A message read for pills or timers costs about a
  tenth less: the schemas no longer repeat two long descriptions, and
  every kind of request to a task shares the same cached part.

- Streaks can be worked out (only a missed dose breaks one; a skip
  never does). Nothing shows one yet.

- A new look, switched off (`CARDS_V2` in `.env`): today's pills
  checklist as one message with a box a pill and its buttons inside
  it, and the reminder, the confirm card, the question card and the
  "Log it anyway?" card drawn as coloured boxes. Off, nothing looks
  different. Every colour and spacing is in one file
  (`core/design.py`).

- The tests run in about a minute instead of eleven (the same tests):
  nothing for the user to see.

- Three core pieces any task can use, with nothing changed in what the
  bot says: a message's files reach a task (`request.attachments`; the
  router is told their names), a field can be a number that need not
  be whole (`actions.NUMBER`, 62.5), and working out which of my things
  a name means is in the core (`core/names.py`), with pills using it.

## 2026-10-12

- A design pass for Components V2: a shared style guide
  (`docs/DESIGN.md`) and seven sketches to look at with `dev mock`
  (`checklist-v2`, `reminder-v1`, `reminder-v1-first`,
  `confirm-card-v2`, `question-card-v1`, `reset-card-v2`,
  `gym-workout-v1`). Nothing the bot posts has changed.
- The design's colours are chosen: a dose for any time that is still
  to take is blue, a card that asks first because something is risky
  is amber, confirm and question cards blurple, destructive ones red.
  The five sketches with a new version are removed (`checklist`,
  `confirm-card`, `reset-card`, `reminder`, `gym-today`).
- The other six sketches are redrawn in that style and the old ones
  removed: `too-soon-v2` (the amber example), `reminder-renudge-v2`,
  `reminder-missed-v2`, `gym-import-v2`, `gym-change-v2` and
  `gym-logged-set-v2`. Every sketch now has its version in its name.
  The colours are not final until they are checked on the phone.
- A pill's box is red only when a dose was missed and nothing is left
  to take today; with a dose still to come it is amber, and the missed
  dose is a ❌ line (`reminder-missed-v2`).

- **Pill reminders**, switched off until tested (`REMINDERS_ENABLED`
  in `.env`). On: a message at each timed dose's time with Taken, Taken
  at…, Snooze 15m and Skip; three reminders 15 minutes apart if left,
  then missed; nothing after a pill's latest time; the phone only ever
  shows "💊 Routine due" and the time.
- Saying a dose was taken before its gap has passed now asks first
  ("That's 2h after dose 1 … Log it anyway?").

- **Questions are on the card.** "Add iron at 8" asks "Is that 8 in the
  morning or the evening?" with a button for each, and there is no Save
  until it is answered, by a press or by typing. The same for a missing
  time, how many a day, which of two pills a name means, and "took it"
  when nothing says which pill. No pills question is sent as a message
  of its own any more.

- #bot-log no longer says "Pills checklist not posted" when the
  checklist is simply there or there is nothing to take: only when it
  could not be posted. A Save finished across a restart shows its
  normal confirmation with "checked after a restart" under it.

- After a restart or a crash the bot catches up and says so once in
  #bot-log ("🔁 Caught up after a restart"): the checklist if it was
  off at 6:00 am, a day closed late, jobs run late. A message it was
  in the middle of gets ⚠️; a Save or a channel reset cut off half way
  is put right without being done twice.

- Gym, the next task, has a spec (private) and four mock-ups to look
  at with `dev mock`: `gym-import`, `gym-change`, `gym-today` and
  `gym-logged-set`. Nothing of it is built.

- A pill's setting is taken away by saying so ("iron no longer needs a
  time", "the evening pill doesn't need to be with food any more"):
  the word "none" is no longer read as an instruction. Nothing else
  changes to look at: a bug report for a message that has one, and a
  dose the bot set aside, behave as before, now by declaration and by
  a stored cause. (Task-check findings C12, C15 and C16.)

- Mock-ups for pills reminders, to look at with `dev mock`: `reminder`,
  `reminder-renudge` (with the snoozed prompt), `reminder-missed` and
  `too-soon`. Nothing of reminders is built yet.

- **Bugs**: "Logged as B4" and "your note is saved" are only said once
  read back; "show my open bugs" is a Live list that follows new bugs,
  notes and closes. A pill's name is compared whatever the case or
  spacing. (Task-check findings C4, C10, C13 and C20.)

- The last two timer lines are the timers' too: the line that points
  out a guessed length, and the card once it has cancelled several.

- `dev why` shows "it" where I said "it" or "that" (it showed an empty
  value), keeps the action's name, and no longer logs an error each
  time it is used.

- **Every line about a pill or a dose is that pill's**, as for timers:
  "✅ Zinc · taken 9:00 am", a correction, a card once saved. A reply
  to one means that pill and that dose ("it was 8am", "actually I
  didn't"), with no router request, whatever was logged since.

- **A pill I don't name is only logged straight away with an anchor**: a
  reply, or a dose logged in the last five minutes. Otherwise ("took
  the usual one", "it" hours later) the pill the bot picked is shown on
  a card with ❓, and Save logs it.

- The standard now says what "it" means without a reply: the last thing
  I mentioned, or the subject of the bot's latest task message in the
  last five minutes, and never a message with no single subject.

- **Every message about a timer is that timer's.** Not only its card and
  its alert: the line that says it was paused or given more time, and
  the one that answers how long is left. A reply to any of them means
  that timer ("Give it 2 more" as a reply to "⏸️ Paused: dinner").
- **A timer that was guessed is never changed.** With several going and
  nothing to say which is meant (no name, no reply, nothing said about
  one timer in the last five minutes), the bot asks "Which timer? Say
  its name." and lists them. With one going it acts at once.
- `dev why` says "reply to timers' message" when a reply went to a task
  without the router.

- **A reply to a message the bot posted for a task goes to that task
  first**, in code: a dose's Taken / Skip message, a timer's card, the
  checklist. The router is only asked if the task says the reply isn't
  its own. It works however old the message is.
- **A pill that was guessed is never logged straight away.** It is shown
  on a card with ❓, Save and Cancel. A name that is exact, or that only
  one pill fits, still logs at once.
- **A reply says which pill.** "took it" as a reply to a dose's message
  ticks off that pill and that dose, not the pill logged last.
- **Timers confirm only what was saved**, as pills does, and their
  refusals are plain lines for me ("I can't find that timer. Say its
  name."), with nothing written for Claude in them.
- **Times are ours, 12-hour**: a timer's and a Pomodoro phase's end time
  and a bug post's time no longer follow Discord's settings ("ends in 9
  minutes (8:04 pm)").
- **No ✅ on a note in a bug's post**: the count on the post's card
  shows it was saved.
- **Step 5: the standard is in the docs and the skills.** Nothing about
  how a task behaves changed. `CLAUDE.md` is under half its length and
  points to `docs/CONVERSATION.md` and the Scaling notes instead of
  repeating them. Every task now declares what adding something that is
  already there means (`identity`, `on_repeat`), with the matching and
  the words in core; the unused `hint` line is gone.
- **Two new skills for Claude Code**, in place of `add-task`: `new-task`
  (interview, contract, spec, approval, build) and `task-check` (an
  audit of one task against the standard). Its first run, on timers,
  bugs and pills, found 20 things, listed in `docs/BACKLOG.md`.
- **The status warns only about real problems.** The 6:00 am checklist
  shows as "⚠️ pills checklist skipped · see #bot-log" only when the
  hub can't be found; "already posted" and "nothing to take" are
  normal mornings. A failure reads "failed", a skip "skipped".
- **The bot says which one it is.** Its nickname is its base name on
  live and "<base> · DEV" on the dev database, and its status reads
  "🟢 Live · up 7h · next: nightly backup 3:00 am", "🧪 DEV database ·
  clock +13h", or "⚠️ nightly backup failed · see #bot-log" until that
  job next works.
- **#commands** (`COMMANDS_CHANNEL_ID`): what the bot can do, written
  from the task registry, one message a task, and brought up to date
  at start-up only when it would read differently.
- **`dev mock <name>`** posts a card sketched in `docs/mockups/` as a
  Components V2 message; `dev mock` lists the sketches. Two new ones:
  `reset-card` and `confirm-card`.
- **The reset card says what will be posted again** ("Active timers:
  Pomodoro waiting to start"). **Pointer lines go by themselves**
  ("Today's checklist is in #hub", after about 10 seconds). **The
  nightly backup zips `data/exports/`** beside the specs.
- **"How long is left on tea?"** is answered to the second, in the
  paused card's words: "⏱️ **tea** · 4m 18s left".
- **The 6:00 am checklist always posts.** On 12 October it didn't: the
  checklist had been asked for at 1:29 am, so the job found today's
  already there, brought it up to date in place and said nothing. The
  morning's post is now a fresh copy at the bottom of the hub, whatever
  was posted in the night.
- **A morning with no post says why**, in the log and in #bot-log
  ("💊 Pills checklist not posted: there is nothing to take today").
- **`dev status` says what is running**: live or dev, the database,
  uptime, the commit, the clock, and the next run of each job, above
  the count of bots.
- **A dose named by its number is that dose.** "I took dose 1 of Pill A
  at 9am" corrects dose 1 (old → new) whatever was logged since, and
  "dose 2 at 12:15pm" logs or corrects dose 2. A time that breaks the
  order or the gap is asked about on a card first.
- **"Not included" is never cut off mid-phrase** ("dose 1 of").
- **Something done that nothing keeps track of** ("I went for a run at
  7") gets "I can't log that yet." instead of silence.
- **A follow-up goes to the task that just answered.** For five minutes
  after a task logs, changes or answers something, a short message is
  taken as being about that: "I took it at 9pm", "I had it at 9pm" and
  "it was 9pm actually" straight after logging a pill all correct that
  dose.
- **Chat no longer says "Got it" to something you did.** It can record
  nothing, so it never acknowledges; such a message goes to the task
  that keeps track of it, or gets "I didn't understand that".
- **No more doses "due" at 1:57 am.** A dose is shown at its planned
  time unless the gap from one you really took pushes it later, and
  never past the day's limit. One that can no longer be taken today is
  skipped by the bot with the reason, or marked missed if it had its
  time; the checklist shows that a minute after a pill's latest time.
- **Logging after a pill's latest time asks first**, on a card.
- **"I took it at 9am" straight after logging corrects that dose**
  (old → new) instead of asking which pill or refusing it as a second
  dose.

## 2026-10-11

- **Button colours mean the same everywhere.** Green is the main yes
  (Save, Taken), red is what destroys (Delete for good, Remove, Delete
  all), blurple is every other choice (Skip, Dismiss, Restart, the
  answers to a question), and grey is Cancel alone, now written ↩️.
  Nothing you are meant to choose is grey any more.
- **A housekeeping line really goes after 10 seconds**, also if the bot
  is restarted in between: it is deleted by a stored job.
- **"Delete all unpinned" is only offered when something is pinned or
  📌.**
- **Housekeeping leaves no trace.** Deleting, archiving, pinning,
  unpinning and resetting a channel now say one short line that goes
  after about 10 seconds, even with `KEEP_CONFIRMATIONS` on; the word
  you typed goes too, and #bot-log keeps the record. Before, "📦
  Archived", "🗑️ Deleted", "📌 Pinned" and "📌 Unpinned" stayed in the
  channel.
- **A channel reset removes its own card and your message**, on Delete
  and on Cancel alike.
- **Confirming a protected delete or archive** is now recorded in
  #bot-log.
- **`reset channel` empties the channel you are in.** It always asks
  first, with how many messages there are and how many are pinned or 📌;
  **Delete all** removes everything, **Delete all unpinned** keeps the
  pinned and 📌 ones. It can't be undone. "Reset this channel" in plain
  words does the same.
- **What is live is put back afterwards**: today's pills checklist and
  its Taken / Skip messages, running timers, the dev panel.
- **A copy is saved first.** The channel is written to a text file in
  `data\exports\` before anything is deleted, and the closing line says
  so. If it can't be written, nothing is deleted.

## 2026-10-10

- **`dev clock reset` no longer strands midnight and 6:00 am.** If the
  bot was started with the dev clock still ahead from an earlier run,
  the day rollover and the pills checklist were booked a day late, and
  going back to the real time left them there: the day never ended and
  no new checklist came. They are now booked again whenever the clock
  goes back.
- **A day that is over is closed whenever the bot next looks at today**,
  so yesterday's untouched pills are marked missed even if the midnight
  job never ran.
- **The daily pills checklist.** At 6:00 am, without a notification, the
  hub gets today's checklist: a progress bar, a line for every dose
  (those with no time first, then by time), and paused pills in their own
  section. It is one message, kept up to date in place.
- **Tick a pill off by button or by saying so.** Each dose with no time
  has its own Taken / Skip message under the checklist. "Took my zinc",
  "had pill A at 9", "skip magnesium today" and "I didn't take zinc" do
  the same from chat, and the reply says what is left.
- **`pills` now posts a fresh copy of today's checklist**; "my pills"
  still lists every pill. What nobody touched by midnight is marked
  missed.
- **A message that names one of your pills or timers is never met with
  silence**, whatever the bot first took it for.
- **Adding a pill you already have is no longer "I didn't understand".**
  With the same details the bot says it is already in your pills and
  shows it; with other details you get a change card for it (old → new).
  A change that changes nothing ("move iron to 8am" when it is at 8am)
  gets the same line, however the bot came to find that out.
- **"I didn't understand that" now only means that.** When your message
  was understood and nothing could be done, the bot says which: it is
  already so, or it isn't something it can do yet.
- **"Show all my pills", "list my pills" and "what are my pills"** show
  the list at no cost, like "my pills".
- **"At least 3 hours apart" can no longer be refused for its wording.**
  Lengths of time now reach the bot's code as a number of minutes and
  times of day in one fixed form, so nothing depends on how they were
  said. Lengths that arrive as words are read all the same ("3 hrs",
  "2 and a half hours", "an hour and a half").
- **Something that can't be read is shown, not refused.** The card has
  everything that was understood, marks the part it couldn't read with
  ❔ and the reason, and has no Save until you say it again.
- **A bare "at 8" stays yours to settle.** If morning or evening wasn't
  said, a choice made for you is taken back and the card marks it ❓.
- **A pill that can't fit in a day gets a card, not just a refusal.** A
  planned time after the latest time, or doses that can't all fit, is
  shown as it was read with the reason and no Save; say what to change
  ("not after 6pm") and the card is replaced, with Save back.
- **One kind of schedule for every pill.** A pill can now have planned
  times, a minimum gap and a latest time together ("at 8am, 11:30 and
  3pm, at least 3 hours apart, not after 4pm"); the card writes out each
  one. "Untimed" now reads "any time" and "≥3h apart" reads "at least 3h
  apart". Pills already saved are unchanged.
- **Planned times closer than the gap are moved apart**, and the card
  says which dose moved. In a list of times, one that only makes sense
  as the morning is no longer marked ❓.
- Underneath: when each dose is due is now worked out in one place
  (`core/schedule.py`), ready for the checklist and reminders.
- **One way of handling what you say.** The old path, where Claude was
  given every tool and wrote its own replies, is gone: every message is
  routed, and the bot's own code does the work and the talking. No more
  "I'm waiting for you to confirm" or "want to add anything else?".
- **A list's name shows the list.** "pills", "my pills", "timers" or
  "show my timers" on its own shows that list, Live, at no cost.
- **Chat knows nothing about your data.** A question about your pills or
  timers is answered by that task; plain chat only answers general
  questions, and never offers to do things.
- **`pills` is a plain list.** The dropdown and the Save / Edit previews
  are gone; say what to change and you get a card.
- **The demo shopping and packing lists have left the bot.** They are
  only test fixtures now.
- **Remarks get no reply.** Only a question or a request is answered in
  words; "shopping is boring" is left alone.
- **Reactions show status.** 👀 while the bot works, gone when it is
  done; ⚠️ in its place if it went wrong, with a line only when you can
  do something about it. ✅ is no longer used to say "received".
- **"And" is never "Not included"**, nor any other joining word.
- **`dev why` on a message with no log** says so in a line instead of
  leaving a bare ⚠️.
- **A reply to an older card changes that card**, not the newest one.
- **A note or a thank-you gets ✅** on it and no words; a message the bot
  can't make sense of gets one neutral line, with no task's instructions.
- **Cards say new, change or remove** on their first line, for every
  task; a loosely worded "that belongs on the shopping list" replaces
  the old card instead of leaving two; times in bug posts and `dev why`
  are 12-hour.
- **The conversation standard is `docs/CONVERSATION.md`**, and
  `docs/STATUS.md` says where the work stands.
- **The conversation standard has an acceptance test.** Its golden
  conversations are replayed with every test run; nothing changed in how
  the bot behaves. What it can't do yet is listed in `docs/BACKLOG.md`.
- **Dev bugs are D1, D2… with a "dev" tag.** Bugs logged while testing
  on the dev database no longer look like real ones in #bugs. Real bugs
  stay B1, B2… and a number is never used twice.
- **"Saved" and "Deleted" are only said once they are true.** Every
  change is read back from the database before it is confirmed, and what
  a button did is now part of the conversation: after "Delete for good"
  the bot no longer says it is still waiting for you to confirm.
- **"It" and "that" mean what you'd expect.** A reply says which thing
  you mean, for everything; without one it is the last thing you
  mentioned, never something the bot said. The bot's code works this out.
- **What you state always wins.** "Add zinc to my pills" goes to pills
  whatever card is open, and a dose, time or amount you gave is never
  marked ❓.
- **No reply when there is nothing to do.** A note to yourself or a
  thank-you is left alone.
- **One format for a change on every card:** `field · old → new`.
- **Pin, archive and delete in plain words are gone**; reactions and reply
  words do them as before.
- **Timers, bugs and pills work in plain words the new way.** One small request works out which task a message is for, one
  fills in the details, and the bot's own code does it and writes every
  word: "set a timer for 5 minutes", "that's a bug", "add iron at 8".
  A single timer action happens at once; cancelling several timers and
  any change to a pill ask first with a card.
- **Pills never ask before the card.** "Add iron at 8" shows `8:00 am` ❓;
  say "8pm" and the card is replaced.
- **`dev why` says why.** `dev why` (or `dev why 3`) posts a copyable
  block for each of your last messages: the route and why, what the
  router and extraction returned, each check the bot ran, the card before
  and after, and the cost. A 🐞 report now carries the same trace.
- **A long list no longer makes every message dearer.** At most 20 lines
  of a list go to Claude with a message, the ones it could mean first;
  `dev cost` shows how much was sent and held back.
- **"And jam" no longer adds the butter again.** After "add butter", a
  follow-up such as "and jam", "also jam" or "plus jam" adds only what it
  names; what is already on the card stays as it was.

## 2026-10-09

- **Set, add and remove.** "Make the eggs 7" sets the amount and "add 3
  milk" adds to it; "remove the jam" works on a card and on the saved
  list. A change to something already on the list shows before → after
  ("eggs · 5 → 7"), and the bot does the sums itself (2 + 3 was coming
  out as 3, and "make the eggs 7" as 12).
- **"It" is the last thing mentioned,** marked ❓ when that is a guess;
  and "No, 2 bread rolls" undoes the wrong change as well as making the
  right one.
- **"Not included" only for what nothing covers.** Two cards from one
  message no longer list each other's part.
- **Several things in one go.** "Add honey, jam, peanut butter, rubbish
  bags and 5 eggs" makes one card with a line for each and one Save;
  before, only the first was kept. Replies change the card: "make the
  eggs 6", "remove the jam", "add milk too", and "no, packing" moves the
  lot to a packing card.
- **Nothing is dropped without a word.** What can't go on a card is said
  on it: "⚠️ Not included: …".
- **❓ only for real guesses.** One of something, when you gave no amount,
  is no longer marked; "a few eggs" is.
- **A list on screen sets the context.** Straight after "what am I
  packing?", "add milk" is for the packing list.
- **A list you ask for stays up to date.** The latest copy of a list
  shown on request is edited in place whenever the list changes; ask
  again and the new copy takes over. (On the demo lists for now; the
  pills checklist will work the same way.)
- **"No, shopping" only moves the card.** It was being saved as an item
  called "shopping". A correction such as "make it 2" also reaches its
  card when the bot has said something else in between, and "add jam
  too" straight after a card makes a second card instead of replacing
  the first.
- **Names stay as you typed them**, and "milk" and "milks" are the same
  item when adding or ticking off.
- **A message with a question and a request gets both.** "What's the
  capital of France, and add milk to the shopping list" now answers the
  question and then shows the card; before, the question was dropped.
- **A new way of handling plain words, ready to try on the dev database.**
  A small "router" works out which task a message is for; the task's own
  code then shows a card with its best reading (guesses marked ❓, problems
  ⚠️ with the fix applied) and saves only when you press Save. Say what to
  change and the card is replaced. Every confirmation is written by the
  bot's code, never by Claude. Two demo lists (shopping 🛒 and packing 🧳)
  exist on the dev database to try it with; timers, bugs and pills move
  to it next. Nothing changes on the live bot yet.
- If your `data\dev.db` is from before this evening, delete it once: it
  remembers a pills table that no longer exists and the dev bot won't
  start with it.
- **`dev cost` shows what the bot costs.** Today and this month: the
  total, how many messages went to Claude and how many were handled
  without it (shortcuts, buttons, reactions), the average cost, requests
  and seconds per message, and the most expensive task. Every message is
  now logged with how it was handled; what was already logged is counted
  too.
- **Adding a pill is one step again.** Asking for one shows its preview
  straight away: no more "I'm proposing… reply ok" before it. That "ok"
  is now only for things the bot suggests that have no preview of their
  own. Replies no longer show how the bot did something, and the bot is
  told to write times of day as `8:00 pm` (its cards and previews always
  do).
- **"Add …" is never guessed between tasks.** A bare "add" is not a
  shortcut; when more than one kind of thing could be meant you get a
  button for each.
- **Set up your pills by saying so.** In #inbox: "add vitamin D, once a
  day", "add evening pill at 20:00", "add course A, 3 times a day, at
  least 3 hours apart, with food, for 7 days starting tomorrow". You get
  a one-line preview with **Save** and **Edit**; nothing is added until
  you press Save. "At 8" is asked about (8am or 8pm?) rather than
  guessed, and a pill with no end is never asked for dates.
- **`pills` lists them** (in use, paused, ended) with a dropdown to pick
  one, then Edit, Pause / Resume and Remove. Changing one by words ("move
  the evening pill to 9pm") shows the old and new plan to save. "Pause
  iron until the 20th" acts at once; removing asks first and keeps the
  history; "delete iron and its history" is a separate, final question.
- Nothing reminds you yet: the daily checklist and prompts are the next
  stages.
- **A dev database and a clock you can move.** `python main.py --dev`
  runs the bot on `data/dev.db`, with "DEV DATABASE" in its status, its
  hello and the dev panel. There, `dev clock 5:59am`, `dev clock +2h` and
  `dev clock reset` move the bot's time (forward only; reset goes back)
  and everything that came due on the way runs in order. `dev reset-db`
  wipes it after asking. On the live database both are refused with the
  reason, so real history is never touched.
- **Foundations for pills and reminders** (nothing new to type yet): one
  midnight day boundary for every task, one reader for typed times that
  asks "8am or 8pm?" instead of guessing and always shows `8:04 am`, and
  a log of what is expected each day with every change kept.
- **The scheduler runs chained jobs in one pass**, so a job booked by
  another and already due no longer waits up to 15 seconds.
- **Specs are private and backed up.** `docs/specs/` stays out of git, so
  the nightly backup now zips it beside the database copy
  (`specs-*.zip`, newest 7 kept) and names both on the log card.
  `dev run backup` does the same.
- **A hub channel can be set** with `HUB_CHANNEL_ID` in `.env`; nothing
  posts there yet.
- **One bot is counted as one.** `python -m core.instance_lock` (and
  `dev status` in Discord) says how many bots are running by asking the
  lock, and no longer takes the `.venv` launcher and the Python it starts
  for two copies. The cheat sheet shows how to tell them apart by
  ParentProcessId.
- **A closed bug can be re-opened.** Pressing Fixed or Won't fix swaps
  both buttons on the post's opening card for one **Re-open** button, and
  the card's foot shows the status and when it changed ("✅ Fixed ·
  1:25pm, 9 Oct"). Re-open unarchives the post, puts the Open tag and the
  two buttons back, and is kept in the bug's history with every closing
  (shown by `bugs export`).
- **The opening card counts the notes** ("📝 2 notes"), updated in place
  each time you write one.
- **Dev mode starts again with a #bugs forum set.** Its start-up sweep
  for an old panel read the pins of every channel in `.env` and failed on
  the forum, which has none. Forum, voice and category channels are now
  skipped everywhere pins or history are read.
- **The forum's tags are created in one go at every start** while any is
  missing. If the bot lacks Manage Channels you get one warning in
  #bot-log naming it, not one per tag.
- **Report a bug with 🐞 or `bug`.** React 🐞 to a message, reply `bug` to
  it, or type `bug` on its own for the latest thing in the channel. It is
  logged at once (no 30-second wait) and the channel gets "🐞 Logged as
  B4", linking to the bug's post in the new #bugs forum. The post holds
  the message, the five before it, that turn's tool calls, timings and
  log errors, and the commit, then asks three questions. What you write
  there is saved as a note and ticked ✅; nothing in #bugs goes to
  Claude. Press **Fixed** or **Won't fix** to tag and archive it. `bugs`
  lists the open ones; `bugs export` writes them to `docs/BUGS.md`. Needs
  `BUGS_CHANNEL_ID` (a forum channel) in `.env`.
- **Confirmations now stay.** `KEEP_CONFIRMATIONS` (on by default) leaves
  "📦 Archived" and the other self-deleting notes in the channel, so you
  can see what the bot did. Your command words are still tidied away. Set
  it to `false` for the old behaviour.
- **Claude Code can fix a bug from its id** (the `bug` skill: "fix B4").
  It reads what was captured, reproduces it with a failing test, fixes
  it, and leaves "fix ready, needs retest" on the bug, which `bugs`
  shows. Closing it stays with you.
- **The bot's features are now called tasks, not skills.** `skills/` is
  `tasks/`, the base class is `Task`, the setting is `ENABLED_TASKS` (an
  `.env` that still says `ENABLED_SKILLS` goes on working). "Skill" now
  only means a Claude Code Skill in `.claude/skills/`; the planned list
  of things to do will be "to-dos". `dev run` runs "routines". Nothing
  you type has changed. Earlier entries below keep the old word.
- **Asking in plain words is fast.** "Set a timer for 5 minutes" took 7
  to 10 seconds, and 30 or more after a restart; Claude's part is now
  about 1.5 seconds. Your message gets 👀 the moment it arrives. Claude
  is told what is running with every message, so it acts in one step,
  and when the action has shown its own confirmation it adds nothing.
  The board, lists and cards catch up a moment after the reply.
- **"Cancel all timers" and "stop all timers called tea" work in one
  go.** Any number of timers, by name whatever the case (tea, Tea 2),
  with one message naming each. "Stop" means cancel. Before, it stopped
  after four and said there was no timer called tea.
- A request to Claude that hangs is given up after 15 seconds and
  retried twice, and retries show on the log card.

## 2026-10-07

- **The log card says where the time went.** "Message handled" has a
  Timing field: the seconds until the reply, each request to Claude (time,
  tokens, cache), each tool, the time spent calling Discord, rate-limit
  waits and retries. `bot.log` gets the same on a `Timing:` line. Nothing
  is faster yet: this is the measurement the speed-up work starts from.
- **The "Your timers" list is live.** It was a snapshot whose countdowns
  ran on after a pause, which made paused timers look as if they had
  gained time (they hadn't). There is now one list per channel, rewritten
  whenever a timer changes.
- **`pause all` and `resume all`**, typed or asked for: every timer and the
  Pomodoro (add `except pomodoro` to leave it), with a reply naming each
  one and its time left. Claude can also tell you what happened to a
  timer and when ("what was left on dinner when I paused it?").
- Fixes: a timer keeps the speed it was started at, so changing `dev
  speed` mid-run no longer changes its time left; a timer whose time is up
  can't be paused; Claude saying "running again" without resuming
  anything is caught, and its timer tools report what was actually saved.
- **Claude tells the truth about what it did.** It was copying a
  "[Tool calls this turn: …]" note that the bot added to its own earlier
  replies, and saying "Done" without doing anything. The note is gone, any
  it writes is removed, and a "done" with nothing run is sent back to it
  (and logged in #bot-log) before you see it.
- **It can see your timers.** "Show my timers" and "how long left on my
  Pomodoro?" are answered from the live state, and "pause the tea timer",
  "unpause it", "skip this break" act on the right one wherever its
  message is. Asking for a Pomodoro while one is going gets one reply and
  an offer to restart at the lengths you asked for (typed `pomo 25/5`
  asks the same with a button).
- `dev mode on` / `dev mode off` work, typed or asked for. "Look further
  back" searches your older messages in the channel and asks before
  acting on what it finds. Reply `unpause` works like `resume`.
- **Claude can now do things.** Ask in plain words ("set a timer for 5
  minutes", "file that away") and it runs the same actions you can type:
  every word and reply action is offered to it as a tool, filtered by
  channel and permission (never the lab; dev tools only in dev mode).
  Typed words still run directly, without Claude.
- It acts at once on a clear request, asks when unsure, and when it is
  only suggesting it waits for your `ok` (2 minutes). Destructive actions
  always ask with Confirm / Cancel. A message you describe rather than
  reply to is shown quoted, with Undo where possible, and if several fit
  you pick with buttons. At most 5 tool calls per message.
- Every tool call is logged, and the "Message handled" card shows the
  tools sent, their token cost, cache use and each call's outcome.
- **QA findings.** Every message now has a lifecycle class (Kept, Live,
  Consumed, Transient, Alert, Protected) and one policy decides what is
  deleted; `dev cleanup off` stops all automatic deletion and `dev inspect`
  shows a message's class. Seed instructions now stay.
- Reactions and reply actions that can't work (archiving in #bot-log, say)
  are refused at once with ⚠️ and a short reason, instead of after the
  30-second wait. Reply `pin` / `unpin` are new, and replies accept filler
  words ("pin this", "please archive it").
- `pomo` while a session runs shows its card again instead of failing. The
  assistant's name is the `ASSISTANT_NAME` setting, and Claude is told it
  has no tools and must never offer to do something itself.
- Add `DEV_CHANNEL_ID`: a scratch channel for manual testing, known to the
  bot as `dev`. The QA run sheet now uses it instead of #documents.
- Add `docs/ARCHITECTURE.md` (a map of every file and the main data flows),
  trim `CLAUDE.md` to the essentials and move the procedures into project
  skills (`add-skill`, `qa`, `end-of-task`). Add this changelog.
- **Keep:** 📌 is now a reaction. It pins the message and protects it;
  taking it off unpins. A full channel gets ⚠️ with the reason in #bot-log.
  `dev inspect` shows "Kept".
- Add the QA run sheet (`docs/QA-RUN.md`): the manual tests in ordered
  blocks.
- **Dev mode:** `dev on` gives faster waits, debug cards in #bot-log, a
  pinned panel and inspection tools. Tests now run with pytest, and
  `docs/TESTING.md` tracks every Auto and Manual test.
- **Reactions and archive brought into line with the interaction rules:**
  reactions act on where they ended up, get ✅ when applied, are undone on
  removal and get ⚠️ on failure. Archive and delete ask before touching
  pinned or 📌-marked messages. New 🗑️ reaction, a Restore button on
  archived copies, and all pin notices are deleted. Timer and Pomodoro
  alerts clear when acknowledged.
- Add the interaction rules (input, reactions, cleanliness, notifications,
  interactions) that every skill follows.
- **Timers and Pomodoro:** `timer`, `timers`, `pomo` and `pomo stats`, with
  reply actions (`cancel`, `pause`, `resume`, `+10m`) and one pinned "Active
  timers" board per channel. They survive restarts and report late finishes.
- Reply actions can match a pattern (`+10m`) and decline messages that
  aren't theirs, so words like `cancel` only act where they apply.
- **Scheduler** is now database-backed: jobs survive restarts and are
  caught up after downtime.
- Lab: `lab tour` (a guided, resumable test run), `lab channels`
  (notifications across channels) and delayed `lab notify`.
- Commands tidy up after themselves: a word or reply that works is
  deleted, with a short self-deleting confirmation; one that fails stays
  and gets ⚠️.
- **Typed words, reply actions and reactions** replace slash commands as
  the main way in, with typo tolerance, debounced reactions and a `help`
  generated from what is registered.
- Only one copy of the bot can run (a lock on `data/bot.lock`); interaction
  error handling no longer raises.

## 2026-10-06

- Fix persistent lab buttons; report buttons and forms that nothing
  answered.
- **Archive:** move a message to the archive channel under its author's
  name and avatar, with attachments and a link back. Add `/lab chart`.
- **Lab:** a test bench for Discord features (reactions, buttons, forms,
  pinned status, notifications), with slash commands and a reusable
  debouncer in the core.
- **Skills system:** features live in `skills/`, are discovered by a
  registry and get a `Context` instead of a Discord message.
- Add schema migrations, the users table, one permission check, async
  database calls and nightly backups.
- Split `bot.py` into the `core` package.
- Add `CLAUDE.md`, the development guide and the decisions log.

## 2026-10-05

- Add placeholders for all planned channel ids.
- Connect the Claude API, with short-term conversation memory.
- First proof of concept: the bot replies in #inbox.
