# Self-test

Written by `python -m selftest`: the dev bot run against real Discord in
channels of its own (#selftest-hub, #selftest-inbox, #selftest-log), on an
empty copy of the dev database, with the dev clock. What is typed and
pressed is simulated (handed straight to the bot's own entry points); what
the bot posts, edits and deletes is real, and is read back from Discord and
from the database before a step passes. How it works and what it can't
see: `docs/DEVELOPMENT.md`, "The self-test".

**Run:** 2026-10-19 11:07, 18 min 30 s
**Result:** 149 passed, 0 failed, 0 broke, 1 skipped, of 150 steps
**Requests to Claude:** none real: every language step used a recorded answer · US$0.0000 spent

<!-- run history: written by python -m selftest -->
## Run history

The latest 15 of 67 runs, newest first. All of them, a line a run, are in
`data/selftest/history.csv` (never rewritten). The first step to fail in a stage is a bug in the forum until it passes again.

| Run | Commit | What ran | Passed | Failed | Failed steps | Spend | Took |
|---|---|---|---|---|---|---|---|
| 2026-10-19 11:41 | `9b9a078` | day | 97 of 98 | 0 | · | US$0.0000 (recorded) | 11 min 11 s |
| 2026-10-19 11:07 | `77790c7` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 30 s |
| 2026-10-19 10:16 | `6af0a76` | hub, calendar | 11 of 11 | 0 | · | US$0.0000 (recorded) | 1 min 51 s |
| 2026-10-19 09:47 | `3d129f3` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 34 s |
| 2026-10-18 00:53 | `7f79c34` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 45 s |
| 2026-10-18 00:14 | `1e2a8c2` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 44 s |
| 2026-10-17 21:46 | `37eb01a` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 53 s |
| 2026-10-17 02:04 | `4745dd1` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 37 s |
| 2026-10-17 01:42 | `d3137ac` | full | 148 of 150 | **1** | 2.12d | US$0.0000 (recorded) | 18 min 31 s |
| 2026-10-16 15:04 | `a699f74` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 22 min 48 s |
| 2026-10-16 13:38 | `3096e99` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 58 s |
| 2026-10-16 13:11 | `0c34ef0` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 46 s |
| 2026-10-16 12:29 | `99bf62f` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 47 s |
| 2026-10-16 12:06 | `846540a` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 18 min 45 s |
| 2026-10-16 11:42 | `e2ccd68` | full | 149 of 150 | 0 | · | US$0.0000 (recorded) | 19 min 01 s |

<!-- end of run history -->

## What failed

Nothing.

## Discoveries

What is worth a look whether or not its step passed.

**Odd, though the step passed**

- 2.12: Yesterday's checklist stays in the hub after midnight and after the next morning's is posted. That is what the code does today; the clean-up spec replaces it
- 3.03: A card posted in the old look and saved with CARDS_V2 on stays a plain message: its confirmation is not drawn the new way. Harmless, but the two looks sit side by side after a switch

**Warnings and errors in `logs/dev-bot.log` during the run**

- ×10 `WARNING discord.state: Guilds intent seems to be disabled. This may cause state related issues.`
- `WARNING assistant: Pills reminders: dose 19 could not be posted (try 1): 503 Service Unavailable (the self-test's own: the post went through). Tried again at 8:01 pm`
- ×5 `WARNING assistant: No handler for weather/fetch jobs; they will wait`
- ×5 `WARNING assistant: No handler for weather/refresh jobs; they will wait`

**Slow steps** (12 seconds or more; a step is mostly waiting for Discord, and each input is given about a second to settle)

- 3.14 Every sketch in docs/mockups (19) posted with `dev mock`: 62s
- 6.01 A start with HUB_TIDY on: 17s
- 6.06 The same, then Save: 16s
- 3.13d Pause and resume: “pause the evening checklist”, Save; then “turn the evening checklist back on”, Save: 16s
- 7.08 Carry over: two days on, Call Ryan (for the day before) was never done: 15s
- 9.05 Done: pick Skincare in the dropdown, then “did brush teeth and floss”: 15s
- 6.09 The next morning at 6:00: 14s
- 1.08 Names: “add Testvit and Testvit forte”, “I took testvit”, “skip forte”: 13s
- 6.03 I say something in the hub and get a reply: `took testany`: 13s
- 6.05 Something I say in the hub that leads to a card, then Cancel: 13s

The whole run took 18 min 30 s, 75 seconds of it with the bot off on purpose.

**In the specs and not tested here**

- Direct messages to live (`DMS_ENABLED`): the dev bot never reads one and cannot write as you; its parts are tested offline (`tests/test_two_bots.py`)
- The nightly self-test (`NIGHTLY_SELFTEST`): the dev bot cannot start a self-test of itself; its parts are tested offline (`tests/test_nightly.py`)
- Messages sent while the bot was off (“I was offline when you sent this”): a bot cannot write as you while another is stopped; block 50 of `docs/QA-RUN.md`
- Pills: a course with a start and an end, pausing until a date and coming back by itself, a pill whose doses can't fit, more than a handful of pills on one checklist, a dose skipped by the bot for want of time
- Pills: “no, …” undoing a change, a reply to a line meaning that dose (the test replies to nothing)
- Reminders: nothing sent after a pill's latest time when the bot starts late; reminders on with no hub channel; a channel reset while a reminder is up
- Restarts: a Save cut off half way through the save itself, and a channel reset cut off (the test cuts off a typed message only)
- The standard: no reply to a remark, chat never acknowledging, task ties, several things in one message for two tasks. The golden conversations cover these offline (`tests/test_golden.py`), with recorded answers
- Reactions (📌, 📦, 🗑️, 🐞), reply words (`pin`, `archive`, `bug`), slash commands and context menus: a bot cannot make them as you
- Timers, bugs, archive, keep and lab: they post with discord.py directly or need your reactions
- Notifications themselves: whether the phone buzzed, and what it showed
- The nightly backup (its job is cancelled for the run, so the test's database is never backed up over the dev database's own backups), quiet hours, the daily spend card on the real day boundary
- The scheduler, clean-up and briefing specs, and gym: nothing of them is built
- Live: only that the service came back and holds the lock

## Start 1: the old look, reminders on. A day of pills up to the afternoon, then the bot is cut off mid-message

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`. Took 217s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 1.01 | The dev bot starts in the test channels and says nothing about it | ✅ pass | On the dev database, with no “Online and ready” in #selftest-inbox and no start card in #selftest-log: a start leaves no trace |  |  | asked |
| 1.01a | The dev bot's status line and nickname during a self-test | ✅ pass | The status line says how far the run is: 🧪, steps done (of all, once that is known), the minutes left, and ❌ with a count once a step has failed. The nickname ends “· testing” | 🧪 1/149 · 22m |  | attention spec, part 2 |
| 1.01b | The schedules the engine made at start | ✅ pass | Six rows, each once: Nightly backup, End of the day, Exchange rate and the bugs' 9:00 am round (the bot's own, locked), Pills checklist at 6:00 am every day in the hub, silent, and the Needs-a-look check at 7:00 am; each with exactly one run booked, with a key | Bugs with a fix shipped 09:00, End of the day 00:00, Exchange rate 05:30, Needs-a-look check 07:00, Nightly backup 03:00, Pills checklist 06:00 |  | scheduler stage 1 |
| 1.02 | The dev clock is moved to tomorrow, 5:50 am | ✅ pass | The clock reads 5:50 am tomorrow; the day rolled over with nothing posted in the hub | Tue 20 Oct 05:50 |  | asked |
| 1.02b | Midnight and 3:00 am went by on the way | ✅ pass | The end of the day and the nightly backup each ran once from their schedules, for those local times, and each is booked again for the next day; “💾 Backup saved” is in #selftest-log (the copy is in the run's own folder) | backup assistant-2026-10-20_055000.db |  | scheduler stage 1 |
| 1.03 | “add Testa to my pills at 8am, 11am and 2pm, at least 3 hours apart, not after 4pm, with food”, then Save | ✅ pass | A card “💊 Pills · new” naming Testa with Save and Cancel; after Save the pill exists and the card is its confirmation | ✅ Saved · 💊 **Testa** · 3× daily · `8:00 am`, `11:00 am`, `2:00 pm` · at least 3h apart · not after `4:00 pm` · *with fo | recorded answer | T49, golden 1 |
| 1.04 | “add Testany to my pills once a day”, then Save | ✅ pass | A card “💊 Pills · new” naming Testany with Save and Cancel; after Save the pill exists and the card is its confirmation | ✅ Saved · 💊 **Testany** · daily, any time | recorded answer | T15 |
| 1.04b | Straight after that Save: “no, I meant 9pm” | ✅ pass | A change card for Testany, the pill just saved: any time → 9:00 pm, with Save and Cancel and no ❓ (it is known, not guessed). Cancel leaves the pill as it was | schedule · daily, any time → daily at `9:00 pm` | recorded answer | golden 2b (G3) |
| 1.04c | Days of the week: “add Testdays to my pills on weekdays only” | ✅ pass | A card “💊 Pills · new” naming Testdays, Mon to Fri, with Save. Cancel: nothing is saved | **Testdays** · Mon to Fri, any time | recorded answer | asked 2026-10-13 (stage 3) |
| 1.05 | A question on the card: “add Testiron to my pills at 8” | ✅ pass | A card with “daily at ❔”, the question morning or evening, a button for 8:00 am and 8:00 pm, Cancel, and no Save | 8:00 am / 8:00 pm / ↩️ Cancel | recorded answer | T25 (37.1) |
| 1.06 | The answer is pressed: 8:00 pm, then Save | ✅ pass | The same message is rewritten with 8:00 pm and Save; Save adds Testiron at 8:00 pm |  |  | T26 (37.2) |
| 1.07 | A typed answer: “add Testmag to my pills, twice a day at 8am”, then “9pm” | ✅ pass | A card asking for the other dose's time with no Save; after “9pm” a card with 8:00 am and 9:00 pm and Save. Then Cancel removes it |  | recorded answer | T27 (37.4) |
| 1.07b | The same request with an empty place where the second time would go | ✅ pass | What Claude understood is still used: a card for Testmag asking for the other dose's time, never “I didn't understand that”. Cancel removes it |  | recorded answer | self-test of 2026-10-13, fix 2 |
| 1.07c | A change to a pill that is only on the open card, read as a change to a saved pill | ✅ pass | “add Testnew at 8am, 11:30am and 2pm, at least 3 hours apart”, not saved; then “make 11:30, 11am instead”, handed over as a change to a saved pill (as it was on live): the card is replaced with 8:00 am, 11:00 am and 2:00 pm, still a new pill with Save. Never a line saying there is no such pill. Cancel removes it | **Testnew** · 3× daily · `8:00 am`, `11:00 am`, `2:00 pm` | recorded answer | the week's messages, 2026-10-11; golden 2c |
| 1.08 | Names: “add Testvit and Testvit forte”, “I took testvit”, “skip forte” | ✅ pass | The whole name wins: Testvit is taken, not Testvit forte. Part of a name finds the only fit: Testvit forte is skipped | {'Testvit': 'done', 'Testvit forte': 'skipped'} | recorded answer | T22 (40.1, 40.2) |
| 1.09 | A name that fits two: “pause testv” | ✅ pass | A card asking which one, a button for each of the two, no Save. Cancel removes it | Testvit / Testvit forte / ↩️ Cancel | recorded answer | T23 (40.3) |
| 1.09b | “pause testv” when Claude does not pass the name on as typed (completed to a whole name) | ✅ pass | The code checks what was typed: “testv” fits two pills, so the card still asks which one, with a button each and no Save |  | recorded answer | self-test of 2026-10-13, fix 1 |
| 1.09c | “pause testv” when Claude does not pass the name on as typed (handed over as “it”) | ✅ pass | The code checks what was typed: “testv” fits two pills, so the card still asks which one, with a button each and no Save |  | recorded answer | self-test of 2026-10-13, fix 1 |
| 1.10 | “remove testvit and testvit forte”, then Remove | ✅ pass | A remove card with a red Remove; after it both are gone |  | recorded answer | T25 (40.5) |
| 1.10b | `my schedule` | ✅ pass | A list, with no request to Claude: “🗓️ My schedule”, Pills checklist every day at 6:00 am in #hub, silent, with its next run and its last; the Needs-a-look check at 7:00 am; the bot's own a small line each with its last run; a plain message with CARDS_V2 off |  |  | scheduler stage 2 (schedule-list-v2) |
| 1.10c | Add: “also post the pills checklist at 6 pm”, then Save | ✅ pass | A card “🗓️ Schedule · new”: Evening pills checklist, every day at 6:00 pm, #hub, silent, its next run, and “also every day at 6:00 am”. After Save the schedule exists, its run for 6:00 pm today is booked, and the list shown before is brought up to date in place |  | recorded answer | scheduler stage 2 |
| 1.10d | Move: “move the evening checklist to 6:30pm”, then Save | ✅ pass | A change card: **Evening pills checklist**, `time · 6:00 pm → 6:30 pm`, and “Next after this: … today 6:30 pm”. After Save the run booked for 6:00 pm is gone and one for 6:30 pm is booked |  | recorded answer | scheduler stage 2 (schedule-change-v1) |
| 1.11 | 6:00 am: today's checklist | ✅ pass | One checklist in the hub, posted without a notification, naming Testa, Testany and Testiron; a Taken / Skip message under it for Testany (no time) | ## 💊 Pills · ▱▱▱▱▱ 0 of 5 |  | asked; 36, T15 |
| 1.11d | What live's status line would read now (6:00 am, nothing taken, Testa due at 8:00 am) | ✅ pass | The top attention item is the next dose with a time, in its short form: 💊, taken/all, and “8am”. No pill is named | 💊 0/5 · 8am |  | attention spec, part 2 |
| 1.11a | With BRIEFING_ENABLED off, the morning is as it always was | ✅ pass | No briefing in the hub, and the 6:00 am schedule is the checklist alone, under its own name |  |  | scheduler stage 3: off |
| 1.11b | The run log for the 6:00 am checklist | ✅ pass | One run for today's 6:00 am, done, with its key and a line saying what it decided; tomorrow's 6:00 am booked once | s6@2026-10-20T06:00#1 · posted, or already there, or nothing to take today (the log |  | scheduler stage 1 |
| 1.11c | `dev jobs` | ✅ pass | What is booked next (the backup, the end of the day, the checklist) and how the last run of each ended, from the engine's run log |  |  | scheduler stage 1 |
| 1.12 | `pills` typed in #selftest-inbox | ✅ pass | A fresh copy at the bottom of the hub; the old checklist and its messages are gone |  |  | T15, R48 |
| 1.13 | `took testany`: the typed shortcut | ✅ pass | At once “✅ **Testany** · taken …”, the checklist shows it, Testany's own message goes, and no request to Claude is made | ✅ **Testany** · taken 6:00 am · still to take today: Testa (dose 1 of 3) `8:00 a |  | 43.1 |
| 1.14 | `took testany` again | ✅ pass | Not the shortcut any more (nothing is left today): it is read as plain words, and the answer says it is already taken. Nothing changes | ✅ **Testany** · taken 6:00 am already | recorded answer | 43.2 |
| 1.15 | 8:00 am: the reminder for Testa | ✅ pass | One new message in the hub that notifies. Its first line is “💊 Dose due · 8:00 am” and names no pill; it was posted as that line and written in after (an edit); under it Testa, dose 1 of 3, with Taken, Taken at…, Snooze 15m, Skip | 💊 Dose due · 8:00 am |  | T41 (38.2), asked |
| 1.15b | With the 8:00 am dose due and not taken, live's status line would say so | ✅ pass | The top attention item is the dose that is due: “💊 due 8am” | 💊 due 8am |  | attention spec, part 2 |
| 1.16 | Taken is pressed on the reminder | ✅ pass | The reminder goes; dose 1 is taken; the checklist shows it |  |  | 38.4 |
| 1.17 | Too soon: `took testa` a minute after dose 1 | ✅ pass | A card that says dose 1 was already logged and asks in so many words: “⚠️ You already logged dose 1 at … Add another dose?” with Log it and Cancel; nothing is ticked off. Cancel removes it | ⚠️ You already logged dose 1 at 8:00 am. That's just now. The gap is at least 3h. Add another dose? |  | 43.3, T46; asked 2026-10-14 |
| 1.17b | “that was dose 2”, about the dose just logged | ✅ pass | A correction of that log, with no card open: a change card “Testa · dose 1 → dose 2 · taken …” with what becomes of dose 1 under it, Save and Cancel. Nothing is logged a second time, and nothing changes until Save. Cancel | **Testa** · dose 1 → dose 2 · taken 8:00 am | recorded answer | golden 19; asked 2026-10-14 |
| 1.18 | The next reminder, and Snooze 15m | ✅ pass | When dose 2 falls due a reminder is posted; Snooze rewrites the same message with “Snoozed until …” | -# 💤 Snoozed until 11:15 am |  | T42 (38.3) |
| 1.19 | 15 minutes later the reminder is posted again | ✅ pass | A new message takes the place of the snoozed one (so the phone buzzes again); only ever one prompt |  |  | T42 (38.3) |
| 1.20 | Taken at… on the reminder, with a time typed | ✅ pass | A form opens; with the time sent, the reminder goes and dose 2 is taken at that time | taken at 11:10 am |  | T43 (38.4) |
| 1.21 | A correction in words: “actually dose 2 of testa was at …” | ✅ pass | One line with the old time → the new one, and no second dose logged | ✏️ **Testa** (dose 2 of 3) · taken 11:10 am → 11:06 am · still to take today: Testa (dose 3 of 3) `2:06 pm`, T | recorded answer | asked; pills stage 4 |
| 1.22 | A question about my data: “what pills do I have left today?” | ✅ pass | The pills task answers (the checklist, or a line pointing at it); my message is left with no ⚠️ |  | recorded answer | fixture |
| 1.23 | The clock is moved to 20 seconds before dose 3 falls due, and a card is left open: “add Otherpill once a day” | ✅ pass | A card with Save, not pressed (asked for now, so that it has not expired by the restart) |  | recorded answer | T36 (36.1) |
| 1.24 | The bot is cut off in the middle of answering a message, seconds before dose 3 falls due | ✅ pass | The process ends with my message still marked 👀 and its log row still “received”. Checked after the restart (2.01 to 2.05) |  |  | asked; T38 (36.4) |

## Start 2: the same settings, after 75 seconds off. The catch-up, then the rest of the day and the next morning

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`. Took 107s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 2.01 | The catch-up after the restart is said once | ✅ pass | One new “🔁 Caught up after a restart” in #selftest-log. It says my message was cut off and that something ran late or was posted, and names no pill | 🔁 Caught up after a restart / • “what is the capital of France?” was cut off by the stop and never answered: marked ⚠️, say it again / • Ran late, as the bot was off when they were due: pill reminder (1m late) |  | asked; T38 (36.4) |
| 2.02 | The message that was cut off | ✅ pass | ⚠️ in place of 👀 on it: it was never answered, so I say it again |  |  | 36 (restarts) |
| 2.03 | Dose 3's reminder fell due while the bot was off | ✅ pass | Exactly one reminder in the hub, posted once at start, with the neutral first line; not one for each minute missed |  |  | asked; restarts |
| 2.04 | The checklist after the restart | ✅ pass | The same message as before the stop, brought up to date in place: no second copy |  |  | T37 (36.3) |
| 2.04b | The schedules after the restart | ✅ pass | The same three rows as before the stop (none made again), no run booked twice, and the 6:00 am checklist was not posted a second time |  |  | scheduler stage 1 |
| 2.05 | A card from before the restart: Save is pressed | ✅ pass | Otherpill is saved: the button still works and applies exactly what the card showed |  |  | T37 (36.2) |
| 2.06 | Left alone, the reminder is posted again (1 of 3) | ✅ pass | A new message in place of the old, its first line ending “2nd reminder”; only ever one |  |  | T44 (38.5) |
| 2.07 | Left alone, the reminder is posted again (2 of 3) | ✅ pass | A new message in place of the old, its first line ending “3rd reminder”; only ever one |  |  | T44 (38.5) |
| 2.08 | Left alone, the reminder is posted again (3 of 3) | ✅ pass | A new message in place of the old, its first line ending “last reminder”; only ever one |  |  | T44 (38.5) |
| 2.09 | After the third reminder the reminders stop, and the dose is still to take | ✅ pass | The reminder goes and no other is posted. The dose is not missed (it can still be taken today): the checklist still shows it to take, with no ❌ |  |  | T45 (38.6); asked 2026-10-14 |
| 2.09b | Half an hour before Testa's latest time: one last chance | ✅ pass | At 3:30 pm one more message, which notifies: “💊 Last chance today · take by 4:00 pm”, with no pill in that line; under it the pill, the dose and why. Taken, Taken at… and Skip, no Snooze. Only the one | 💊 Last chance today · take by 4:00 pm |  | asked 2026-10-14 |
| 2.10 | Past Testa's latest time the dose is missed; logged as taken then: `took testa` | ✅ pass | At 4:00 pm dose 3 is missed. The typed shortcut, with no request to Claude, asks first: a card “Dose 3 was missed (due …). … Log it as taken now?” with Log it and Cancel; nothing is ticked off until Log it | ⚠️ Dose 3 was missed (due 2:06 pm). That's after the latest time, 4:00 pm. Log it as taken now? |  | T45 (38.7); asked 2026-10-13 |
| 2.10b | 8:00 pm: Discord takes Testiron's reminder and still answers that it failed | ✅ pass | The job does not fail and nothing is posted again at once. A minute later the hub is read first: the line that went through is found and the pill is written into it. One reminder in the hub, never two |  |  | asked 2026-10-14 |
| 2.11 | Testiron's reminder, and Skip | ✅ pass | A reminder for Testiron; Skip takes it down and the dose is skipped |  |  | 38 |
| 2.11b | The schedule I added ran at the time I moved it to | ✅ pass | One run of the checklist for 6:30 pm, done, and none for 6:00 pm; the hub still has one checklist for the day (it was brought up to date, not posted again) |  |  | scheduler stage 2 |
| 2.12 | Midnight: the day is closed | ✅ pass | Nothing of yesterday is left open; Otherpill, never touched, is missed. Yesterday's checklist is written one last time and left in the hub (as the code does today; the clean-up spec changes this) | yesterday's checklist is still in the hub |  | pills 29; scheduler spec 18.2 |
| 2.12b | Just after midnight: “took otherpill last night at 11” | ✅ pass | Yesterday's missed dose is logged as taken at 11:00 pm, and the line says “yesterday”. (If the day had to be worked out from the time, it is asked first on a card: Log it) | ✅ **Otherpill** · taken 11:00 pm · yesterday · still to take today: Otherpill, Testany, Testa (dose 1 of 3) `8:00 am`, Testa (dose 2 of 3) ` | recorded answer | asked 2026-10-13 (stage 3) |
| 2.12c | “what did I take yesterday?” | ✅ pass | A reply from the record: “Yesterday”, the date, the count, and a line a dose, with Otherpill taken at 11:00 pm | 💊 **Yesterday** · Tue 20 Oct · 6 of 8 taken · 2 skipped | recorded answer | asked 2026-10-13 (stage 4) |
| 2.12d | “show my week” | ✅ pass | The week so far, a line a day up to today with a mark a dose, and the count for the week | 💊 **This week** · Mon 19 – Sun 25 Oct · 6 of 14 taken · 2 skipped / `Mon 19` nothing to take / `Tue 20` ✅✅✅✅⏭️✅⏭️✅ 6 of 8 | recorded answer | asked 2026-10-13 (stage 4) |
| 2.13 | 6:00 am the next day: a fresh checklist | ✅ pass | A new message for the new day with every dose still to take; one checklist for today |  |  | asked; 23 |
| 2.14 | Left for the next start, in the old look: an open change card and a reminder | ✅ pass | A change card “dose · … → 2 tablets” with Save, and at 8:00 am a reminder for Testa |  | recorded answer | asked: switching looks |

## Start 3: `CARDS_V2` on. Every card posted and edited in the new look, and the old look's messages edited under it

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`. Took 199s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 3.01 | A clean restart with CARDS_V2 on | ✅ pass | No new catch-up card about pills or a checklist (one naming only `tidy` is all right), and no second checklist |  |  | T39 (36.5) |
| 3.02 | An old-look reminder, Snooze pressed with the new look on | ✅ pass | Discord accepts the edit: the same message now says “Snoozed until …” | the message is Components V2 afterwards |  | asked: switching looks |
| 3.03 | An old-look card, Save pressed with the new look on | ✅ pass | Discord accepts the edit: the card becomes its confirmation and Testa's dose is 2 tablets | the message is plain afterwards |  | asked: switching looks |
| 3.04 | The old-look checklist, rewritten with the new look on (`took testany`) | ✅ pass | The checklist kept for today shows Testany taken. Either the same message turned into the new look in place, or it was replaced by one message: never two | the same message, edited; it is Components V2 |  | asked: switching looks |
| 3.05 | `pills` with the new look on | ✅ pass | One message, one box: “### 💊 Pills” with dots and a count (no page title), a pill an item, Testany (taken) in the small line at the bottom, and no separate message for a dose with no time | ### 💊 Pills ●○○○○○ 1/6 · boxes 0xfaa61a |  | T51 (41.3) |
| 3.05b | “What pills are left” in #selftest-inbox (golden 29) | ✅ pass | The answer itself, there: a first line naming no pill (“💊 **n left today** · dots and count”), then a dose a line with its time in bold; no new checklist in the hub, and no pointer in its place | 💊 **5 left today** · ●○○○○○ 1/6 | recorded answer | Alex, 15 Oct |
| 3.06 | Taken is pressed in Testa's box on the checklist | ✅ pass | The checklist stays and is rewritten in place: dose 1 has ✅; the reminder for it goes |  |  | T53 (41.5) |
| 3.07 | Taken pressed again in Testa's box: too soon | ✅ pass | An amber box “⚠️ You already logged dose 1 at … Add another dose?” with Log it and Cancel; nothing ticked off. Cancel |  |  | T54 (41.6); asked 2026-10-14 |
| 3.08 | Skip is pressed in Otherpill's box | ✅ pass | Its box turns grey and says skipped, with no buttons for it |  |  | T55 (41.7) |
| 3.09 | A question card in the new look: “add Testb to my pills at 8” | ✅ pass | A blurple box ending with the question, a button an answer and Cancel, no Save. The answer rewrites it in place with Save. Cancel removes it |  | recorded answer | T50 (41.2) |
| 3.10 | A remove card in the new look: “remove otherpill”, then Remove | ✅ pass | A box with a red Remove; after it Otherpill is gone | box colour 0x5865f2 | recorded answer | T57 (41.8) |
| 3.10b | A pill with no time is added with the new look on: “add Testlate once a day” | ✅ pass | After Save the drawn checklist gains Testlate, any time, with its buttons, in place; no separate message for it |  | recorded answer | T51 (41.3) |
| 3.11 | A reminder in the new look | ✅ pass | When dose 2 falls due: posted as the one neutral line and drawn after (an edit), an amber box naming Testa, four buttons. Left up for the next start |  |  | T52 (41.4) |
| 3.12 | Left for the next start, in the new look: an open change card | ✅ pass | A blurple change card “dose · 2 tablets → 3 tablets” with Save |  | recorded answer | asked: switching back |
| 3.13 | The reset card in the new look: `reset channel`, then Cancel | ✅ pass | A red box (Components V2) with the channel under the heading, the count, that it can't be undone, and a red Delete all inside it; Cancel removes it and deletes nothing | drawn, colours ['0xed4245'] |  | 39.4; self-test of 2026-10-13, fix 5 |
| 3.13b | `my schedule` in the new look | ✅ pass | One drawn message: the page title, one amber box (the next to run is in it) with a rule between schedules, and no buttons |  |  | scheduler stage 2 (schedule-list-v2) |
| 3.13b2 | The lists that were plain, in the new look: `my pills`, “show my week”, `bugs` | ✅ pass | Each is one drawn message (Components V2) with the same words: a page title, one box with a rule between items (a pill; a day of the week; “No open bugs.”), and no buttons | ## 💊 Pills / ## 💊 This week · 8 of 15 taken · 3 skipped / ## 🐞 Open bugs | recorded answer | stage 5 (2026-10-13) |
| 3.13c | Days and notify: “make the evening checklist notify, and only on weekdays”, then Save | ✅ pass | A blurple change card with `days · every day → Mon to Fri` and `notify · silent → notifies`; after Save the schedule is so |  | recorded answer | scheduler stage 2 (schedule-change-v1) |
| 3.13d | Pause and resume: “pause the evening checklist”, Save; then “turn the evening checklist back on”, Save | ✅ pass | `paused · no → until you turn it back on`, and nothing is booked for it while paused; then `paused · … → on` and its next run is booked again |  | recorded answer | scheduler stage 2 |
| 3.13e | Remove: “remove the evening checklist”, then Remove | ✅ pass | A card `… → removed` with a red Remove; after it the schedule is gone from the list, nothing is booked for it, and the 6:00 am one is untouched |  | recorded answer | scheduler stage 2 |
| 3.14 | Every sketch in docs/mockups (19) posted with `dev mock` | ✅ pass | Discord accepts each one as a Components V2 message (the reminder's first line alone is plain text) | 19 posted |  | T2 to T10, block 44 |
| 3.15 | The checklist sketch's colours | ✅ pass | Its boxes carry the values of core/design.py for amber, blue, green, red and grey (how they look is yours to judge) |  |  | T4 (39.1) |

## Start 4: `CARDS_V2` off again, and a tiny spend limit. The new look's messages edited under the old, and the spend line

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`, `DAILY_SPEND_LIMIT_NZD=0.001`, `USD_TO_NZD=1.70`. Took 62s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 4.01 | A new-look reminder, Snooze pressed with the new look off | ✅ pass | Discord accepts the edit, and the message stays Components V2 (one can never go back to plain text): it now says “Snoozed until …” |  |  | asked: switching back; T58 |
| 4.02 | A new-look card, Save pressed with the new look off | ✅ pass | Discord accepts the edit: the card becomes its confirmation and Testa's dose is 3 tablets |  |  | asked: switching back |
| 4.03 | The new-look checklist after a start with the new look off | ✅ pass | The same message, still Components V2 (it can never go back to plain text), now holding the old look's words; and the Taken / Skip message for Testlate (no time) is back under it | ## 💊 Pills · ▰▰▱▱▱ 2 of 6 |  | asked: switching back |
| 4.03b | `took testlate` with the new look off, on the checklist that was drawn | ✅ pass | Discord accepts the edit of the Components V2 message from the old look's code: it shows Testlate taken, and Testlate's own message goes |  |  | asked: switching back |
| 4.04 | `pills` with the new look off | ✅ pass | A fresh checklist in the old look (a plain message), in place of the drawn one | ## 💊 Pills · ▰▰▱▱▱ 3 of 6 |  | T58 (41.8) |
| 4.05 | A new card with the new look off: “add Testlast once a day”, then Cancel | ✅ pass | A plain card with Save and Cancel; Cancel removes it |  | recorded answer | T58 (41.8) |
| 4.05b | The reset card with the new look off: `reset channel`, then Cancel | ✅ pass | A plain message with the same words and buttons; Cancel removes it |  |  | T58; self-test of 2026-10-13, fix 5 |
| 4.06 | `dev cost` | ✅ pass | Under Today a small line with what was spent against DAILY_SPEND_LIMIT_NZD, the limit of a tenth of a cent written as NZ$0.001, and which exchange rate is in use | -# NZ$0.0000 of today's NZ$0.001 limit (0%) |  | T35, T56 (42.1, 42.3) |
| 4.07 | The spend line in #bot-log when the limit is passed | ⏭️ skipped |  | needs real requests to Claude with money left: run with --claude |  | T49, T50 (42.2, 42.3) |
| 4.07a | The bot's own is not changed by words: “move the backup to 4am” | ✅ pass | One line saying the nightly backup is the bot's own and isn't changed here; no card, and it still runs at 3:00 am |  | recorded answer | scheduler stage 2 |
| 4.07b | `dev run backup` | ✅ pass | A handler run by hand, outside its schedule: “▶️ Ran: core.nightly_backup”, a second “Backup saved”, a run of its own in the log, and the night's backup still booked |  |  | scheduler stage 1 |
| 4.08 | `dev clock reset` | ✅ pass | The clock is the real time again, and the standing jobs are booked for the real day | checklist booked for 2026-10-20T06:00 |  | T57 |

## Start 5: `BRIEFING_ENABLED` on (the starts before it had it off). The morning routine, “brief me”, and the briefing kept up to date in place

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `BRIEFING_ENABLED=true`, `DAY_PROGRESS=true`, `DAY_QUESTIONS=true`, `WEEKLY_SUMMARY=true`, `WEATHER_ENABLED=true`, `WEATHER_SOURCE=C:\Users\temp\projects\assistant-bot\tests\fixtures\weather_drizzle.json`. Took 86s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 5.01 | A start with BRIEFING_ENABLED on | ✅ pass | The 6:00 am schedule is the same row, now called Morning routine, with two steps: the briefing, then the pills checklist; both are booked for the next 6:00 am |  |  | scheduler stage 3 |
| 5.01b | A fresh day, 9:00 am: the morning routine ran at 6:00 on the way | ✅ pass | One briefing in the hub and the checklist under it, both without a notification; the routine's two steps each ran once for 6:00 am, the briefing first; it has the line about yesterday | ### 💊 Pills ○○○○○○ 0/6 / -# Yesterday: 3 of 6 taken · 2 missed · 1 skipped |  | scheduler stage 3 |
| 5.01c | Weather in the briefing, from a recorded forecast | ✅ pass | With WEATHER_ENABLED on: two schedules of its own, Weather fetch at 5:50 am and Weather refresh at 8:50 am; the briefing has a Weather section with the low and high, the sky, the rain and the wind, read from what was fetched (the network is never asked: WEATHER_SOURCE is a recorded forecast) | ### 🌤️ Weather |  | item 7 |
| 5.02 | `brief me` in #selftest-inbox | ✅ pass | With no request to Claude, a copy there: “☀️ Today”, the date, a Pills box (### 💊 Pills, its dots and count) with the next dose; drawn, in the colour of its status, with no buttons | -# 💊 0/6 / ### 🌤️ Weather |  | scheduler stage 3 (briefing-v2) |
| 5.03 | `brief me` in the hub | ✅ pass | Nothing new is posted: the briefing that is there is brought up to date in place, and a line says so |  |  | scheduler stage 3 |
| 5.03b | “what's on today?” in plain words | ✅ pass | The router sends it to the briefing, which answers with its card there; my message is left with no ⚠️ |  | recorded answer | scheduler stage 3 |
| 5.03c | “what's left today?” in plain words | ✅ pass | With DAY_QUESTIONS on, the briefing task answers in one message from the day's own data: “☀️ **Left today**”, the day's dots and count as the checklist counts them, then a line a dose still to take. No card, and my message is left with no ⚠️ | ☀️ **Left today** · ○○○○○○ 0/6 | recorded answer | asked 2026-10-14 (questions about my day); golden 21 |
| 5.03d | “how did I go yesterday?” in plain words | ✅ pass | The briefing task answers from the record of that day: “☀️ **Yesterday**”, its date, its dots and count, and the pills task's own line about the day before. With nothing recorded for yesterday (a run of this stage alone) it says so, and gives no number | ☀️ **Yesterday** · Wed 21 Oct · ●●●●●○○ 5/7 / 💊 Yesterday: 3 of 6 taken · 2 missed · 1 skipped | recorded answer | asked 2026-10-14 (questions about my day); golden 23 |
| 5.03e | “will it rain?” in plain words | ✅ pass | The weather task answers from the forecast it keeps (the recorded one), with no request to the network: the highest chance in the hours still to come and roughly when, and when it was updated | 🌤️ 61% chance of rain for the rest of today, most likely between 1pm and 5pm. | recorded answer | asked 2026-10-14 (questions about my day); golden 24 |
| 5.03f | “what's the weather this afternoon?” in plain words | ✅ pass | The weather task answers for that part of the day: “**This afternoon**”, the chance of rain in those hours, and the day's wind small under it. No temperature is said: the recorded forecast has none by the hour | 🌤️ **This afternoon** / 61% chance of rain this afternoon, most likely between 1pm and 5pm. | recorded answer | asked 2026-10-14 (questions about my day); golden 25 |
| 5.04 | A dose is ticked off: `took testany` | ✅ pass | The briefing in the hub is edited in place: the Pills box's count goes up by one; no new briefing is posted, there or in #selftest-inbox | 0 → 1 dealt with, in place |  | scheduler stage 3 |
| 5.04b | The day's progress at the top of the briefing | ✅ pass | With DAY_PROGRESS on: the day's total in the title as a dot a thing to do and the count (“☀️ Today ●○○○○○ 1/6”), no percentage, and under the date one small line a task (“💊 1/6”), with the numbers the checklist itself counts; it moved in place with the dose just ticked off | ## ☀️ Today ●○○○○○ 1/6 / -# Thursday 22 October / -# 💊 1/6 |  | asked 2026-10-14 (day progress) |
| 5.06 | `my schedule` with a routine in it | ✅ pass | Morning routine, every day at 6:00 am, with its steps numbered: 1. briefing, 2. pills checklist |  |  | scheduler stage 3 |
| 5.06b | With WEEKLY_SUMMARY on: its schedule, and the summary when it runs | ✅ pass | A schedule “Weekly pills summary”, Sunday at 7:00 pm in the hub, silent. Run now, it posts the week in the hub: “Your week”, the count, a line a day | ## 💊 Your week · 10 of 27 taken · 7 missed · 5 skipped |  | asked 2026-10-13 (stage 4) |
| 5.07 | The next morning at 6:00: the routine again | ✅ pass | A new briefing, then the checklist under it; yesterday's briefing is gone; one briefing in the hub; the line about yesterday counts the dose ticked off at 5.04 | -# Yesterday: 1 of 6 taken · 5 missed |  | scheduler stage 3 |
| 5.07b | With HUB_TIDY off, nothing has a lifetime and nothing was tidied | ✅ pass | No message has been recorded, and yesterday's checklist is still in the hub beside today's (as the code has always left it) |  |  | scheduler stage 4: off |
| 5.08 | `dev clock reset` | ✅ pass | The clock is the real time again |  |  | housekeeping |

## Start 6: `HUB_TIDY` on as well (off until now). What is said in the hub goes once handled, pinned stays, yesterday goes in the morning, and a copy is saved first

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `BRIEFING_ENABLED=true`, `HUB_TIDY=true`. Took 113s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 6.01 | A start with HUB_TIDY on | ✅ pass | The morning routine has three steps: the tidy, the briefing, the pills checklist. Nothing that was in the hub before has a lifetime, and none of it is touched | the tidy's line: 1 removed · 8 old messages left alone |  | scheduler stage 4 |
| 6.02 | This morning's briefing and checklist have a slot each | ✅ pass | Both are recorded as “replaced” (briefing, pills.checklist): one of each at a time |  |  | scheduler stage 4 |
| 6.03 | I say something in the hub and get a reply: `took testany` | ✅ pass | The line is there; 2 minutes later my message and the reply are both gone, with nothing said about it; the checklist and the briefing stay |  |  | scheduler stage 4 |
| 6.04 | A copy was saved first | ✅ pass | The exports folder (the run's own, never data/exports) has a tidy file for the hub, for that day, with my words and the reply in it | tidy-selftest-hub-2026-10-25.txt |  | scheduler stage 4 |
| 6.05 | Something I say in the hub that leads to a card, then Cancel | ✅ pass | The card waits; on Cancel the card and my message both go at once |  | recorded answer | scheduler stage 4 |
| 6.06 | The same, then Save | ✅ pass | On Save my message goes at once and the card becomes its confirmation, which goes 2 minutes later; the pill is saved all the same |  | recorded answer | scheduler stage 4 |
| 6.07 | Pinned stays | ✅ pass | A reply I pin inside its 2 minutes is still there afterwards; what I typed goes |  |  | scheduler stage 4 |
| 6.08 | The same exchange in #selftest-inbox | ✅ pass | Nothing goes after 2 minutes: the hub's rule is the hub's. The line that reports the change is recorded to last the day |  |  | scheduler stage 4 |
| 6.09 | The next morning at 6:00 | ✅ pass | The tidy runs first: yesterday's checklist and briefing are gone and today's are there, one of each; yesterday's line in #selftest-inbox is gone; the reply I had pinned (and unpinned since) is left, being kept; nothing in #selftest-log | the tidy's line: 3 removed |  | scheduler stage 4 |
| 6.10 | `dev clock reset` | ✅ pass | The clock is the real time again |  |  | housekeeping |

## p7

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `BRIEFING_ENABLED=true`, `HUB_TIDY=true`, `TODOS_ENABLED=true`, `DESIGN_ROUND=4`. Took 89s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 7.01 | To-dos are on, and the list is empty | ✅ pass | `my to-dos` says there is nothing on it, and there is no to-dos card in the hub (a card with nothing for today is not there) |  |  | to-dos (15 Oct) |
| 7.02 | Add a to-do: “add buy stamps”, then Save | ✅ pass | A 📝 To-dos · new card with **Buy stamps** · any day; after Save the card in the hub appears with it and one Done dropdown holding it (round 4: no button under each) | ### 📝 To-dos ○ 0/1 | recorded answer | to-dos (15 Oct); the list rule (round 4) |
| 7.03 | Add one with a day: “add call Ryan tomorrow”, then Save | ✅ pass | The card says **Call Ryan** · tomorrow; after Save it is on the list for tomorrow, and not on today's card |  | recorded answer | to-dos (15 Oct) |
| 7.04 | A question: “what's on my to-do list?” | ✅ pass | The answer there, in #selftest-inbox: both to-dos, Call Ryan for tomorrow; nothing posted in the hub in its place |  | recorded answer | to-dos (15 Oct); a question is answered where it is asked |
| 7.05 | Done by words: “I bought the stamps” | ✅ pass | Ticked off at once, no card: one line “✅ **Buy stamps** · done”, and the hub card counts it in its small line (“✅ 1 done”) |  | recorded answer | to-dos (15 Oct) |
| 7.06 | Undo: “undo that” | ✅ pass | Buy stamps is back on the list, not done, and in the card's Done dropdown again |  | recorded answer | to-dos (15 Oct) |
| 7.07 | Done by the dropdown on the hub card: pick Buy stamps | ✅ pass | The card is edited in place: “✅ 1 done” in its small line, and Buy stamps gone from the dropdown (Call Ryan, for tomorrow, still in it) |  |  | to-dos (15 Oct); the list rule (round 4) |
| 7.08 | Carry over: two days on, Call Ryan (for the day before) was never done | ✅ pass | 9:00 am two days on: the morning routine has posted the to-dos card, and Call Ryan is on it overdue, amber, “from yesterday”; Buy stamps, done two days ago, is not | ### 📝 To-dos ○ 0/1 |  | to-dos (15 Oct) |
| 7.09 | All done: pick Call Ryan in the dropdown | ✅ pass | The card stays, edited in place: green, every dot solid, “✅ 1 done” in its one small line and no dropdown or button left (a card is only away on a day with nothing for it: 7.01) |  |  | to-dos (15 Oct); the list rule (round 4) |

## p8

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `DESIGN_ROUND=4`, `TODOS_ENABLED=true`. Took 55s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 8.01 | `pills` in round 4 | ✅ pass | One box: a dose that can be taken now has one button, Taken (no Taken at…, no Skip); the rest of the day, what is done and what was missed are small lines | ### 💊 Pills ●●●○○○○ 3/7 / **Testhub** · any time / **Testa** · dose 2 of 3 · **11:00 am** / -# later today · 2:00 pm, 8:00 pm |  | round 4 (15 Oct) |
| 8.02 | Taken logs the dose at once, and a reply with a time puts it right | ✅ pass | No pop-up: the dose is taken now and a line says so, “reply to this with a time to put it right”; a reply to that line with a time two minutes earlier moves it (old time → new time) | taken: [('Testhub', 1)]; ✏️ **Testhub** · taken 9:00 am → 8:58 am · still to take today: Testa (dose 2 of 3) `11:00 am`, Testa (dose 3 of 3) `2:0 | recorded answer | round 4, question 67: variant 2 |
| 8.03a | “add Testskip to my pills once a day”, then Save | ✅ pass | A card “💊 Pills · new” naming Testskip with Save and Cancel; after Save the pill exists and the card is its confirmation | ✅ Saved · 💊 **Testskip** · daily, any time | recorded answer | set up for 8.03 |
| 8.03 | Skip is said in words, and “undo that” puts it back | ✅ pass | “skip testskip”: Testskip's dose is skipped, one line says so; “undo that”: it is back, not skipped |  | recorded answer | round 4: Skip in words only |
| 8.04 | To-dos in round 4: the first three, “+1 more”, and one Done dropdown | ✅ pass | Four to-dos added: the card shows three in full, a small “+1 more”, no Done button under each, and one dropdown “✅ Done: pick one” holding all four | ### 📝 To-dos ●○○○○ 1/5 / **Buy stamps** / **Call the dentist** / **Book the WOF** / -# +1 more | recorded answer | round 4: the list rule (15 Oct) |
| 8.05 | Pick one in the Done dropdown | ✅ pass | Picking “Water the plants”: it is done, and the card is rewritten in place with one more done, no “+1 more”, and the dropdown one shorter |  |  | round 4: the list rule (15 Oct) |

## p9

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `DESIGN_ROUND=4`, `TODOS_ENABLED=true`, `NUDGES_ENABLED=true`, `HABITS_ENABLED=true`, `TODAY_CARD=true`. Took 59s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 9.01 | Set a reminder: “remind me at <in 20 minutes> to call the bank”, then Save | ✅ pass | A ⏰ card with Save; after Save it is booked for that time | 9:20 am | recorded answer | reminders (15 Oct) |
| 9.02 | It goes off in the hub, and Done deals with it | ✅ pass | At its time a reminder in the hub whose first line names nothing (“⏰ Reminder · <time>”), with Done and Snooze; Done takes the buttons away |  |  | reminders (15 Oct) |
| 9.03 | Make a routine with a window: “make a testevening routine <in 30 minutes> to <in 3 hours>: brush teeth, floss, skincare: cleanser, toner, serum”, then Save | ✅ pass | A card naming the window and the 3 items, the group with its steps; after Save no card of its own yet (its window is still to come) |  | recorded answer | personal routines, layout B (15 Oct) |
| 9.04 | Its window starts: its own card, and the Today card | ✅ pass | A 🔁 Testevening card in the hub with the first three items, Skincare's steps as a guide, and one Done dropdown; the 📅 Today card names it | ### 🔁 Testevening ○○○ 0/3 / -# 9:50 am to 12:20 pm / **Brush teeth** / **Floss** |  | personal routines, layout B; the Today card (15 Oct) |
| 9.05 | Done: pick Skincare in the dropdown, then “did brush teeth and floss” | ✅ pass | The pick ticks the whole group (“✅ 1 done” on the card); the words tick the rest, and the routine's card is tidied away |  | recorded answer | personal routines (15 Oct) |

## p10

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`, `DESIGN_ROUND=4`, `TODAY_CARD=true`, `CALENDAR_ENABLED=true`, `CALENDAR_ICS_URL=C:\Users\temp\projects\assistant-bot\tests\fixtures\calendar_selftest.ics`. Took 30s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 10.01 | The feed is read at start-up | ✅ pass | A read booked at start-up runs: the copy holds the made-up events, and the feed it read is the fixture, not a link | 192 events kept |  | calendar (15 Oct) |
| 10.02 | “what's on tomorrow?” | ✅ pass | In place: a first line with the day and a count and no event's name, then the made-up events with their times |  | recorded answer | calendar (15 Oct) |
| 10.03 | “when is the dentist?” | ✅ pass | The next Test dentist: the first line says when and names nothing, the second names it |  | recorded answer | calendar (15 Oct) |
| 10.04 | “am I free at 6:30 pm tomorrow?” | ✅ pass | Not free: Test gym is on then |  | recorded answer | calendar (15 Oct) |
| 10.05 | The Today card has today's events | ✅ pass | The 📅 Today card in the hub: an event in full, or those that are over in one small line | ### 📅 Today / 📅 **Test dentist** / **3:00 pm** · <t:1792548000:R> / -# 📅 1 earlier today |  | calendar and the Today card (15 Oct) |

## The cross-task conversations, as Claude last answered them (offline: no request sent, no bot started)

Settings: . Took 4s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| u.01 | The cross-task conversations, as last recorded | ✅ pass | Every cross-task golden conversation reads as it did when recorded: the router's task and extraction's action, as the bot's own code reads them | 186 recorded answers read back right | recorded answer | asked (15 Oct): the cross-task golden conversations |

## Only you can check

| Where | What |
|---|---|
| QA-TONIGHT 2, 3 (39.2, 33.1) | What the lock screen shows for a reminder as first posted and once written in. The test checks the message was posted as the neutral line and edited after; what the phone shows for it only you can see |
| QA-TONIGHT 4, 5 (39.1, 39.6) | The checklist sketch's colours in each theme you use, and whether amber, blue, green, red and grey can be told apart. The test checks each box's accent value against `core/design.py`, not how it looks |
| QA-TONIGHT 6 to 10 (39.3 to 39.5, 33, 35) | How each sketch reads: layout, spacing, whether the wording is right. The test checks Discord accepts every sketch and that it posts as Components V2 |
| QA-TONIGHT 41, 52 (38.2, 41.4) | The lock screen for a real reminder, old look and new |
| QA-TONIGHT 42 (38.3) | That the phone buzzes again when a reminder is posted again. The test checks it is a new message and the old one is gone |
| QA-TONIGHT 49 to 55 (block 41) | How the new look reads on the phone: the boxes, the hint under a card, the buttons inside a pill's box. The test checks what each message holds and that presses edit it in place |
| QA-TONIGHT 11 to 14 (blocks 27, 30, 31) | Timers: not in the self-test. They post with discord.py directly and are a proof of concept |
| QA-TONIGHT 24 (40.4) | A picture sent with words: the test cannot attach a file as you |
| QA-TONIGHT 32 to 34 (32.1, 32.2, 34.3) | Bugs: 🐞 as a reaction of yours, and Won't fix in the #bugs forum. A bot cannot react as you, and the forum is live's |
| QA-TONIGHT 29 (37.6) | “took it” six minutes after anything else: the wait is real time, not the dev clock's |
| QA-TONIGHT 59 | Live after its restart: the test starts the service and checks the lock and the log; that it behaves is yours |
| Block 44 | The four new sketches (briefing, schedule list, schedule change, tidy): whether they are what you want. The test only checks Discord accepts them |
| Wording everywhere | Every line the bot says is checked for the words that matter (a name, a time, a mark), not for whether it reads well |
| Real presses | Every press in this run was simulated: the handler behind the button was called and it edited the real message. That Discord delivers a real tap to that handler is checked by discord.py's own routing and by you pressing one |

## The test's channels and data

- The category `selftest` and its three channels are left in place, holding the last run. Every run empties them first.
- To empty them now: `python -m selftest --clear`. To delete them and the category: `python -m selftest --remove` (the next run makes them again). Both work over HTTP, with live running.
- `data/dev.db` and the dev clock are as they were before the run: they are moved aside for it and put back after.
- The run's own database and each start's results are kept in `data/selftest/run-20261019-110725/` (never in git). Delete the folder when you like.

