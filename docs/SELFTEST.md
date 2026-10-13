# Self-test

Written by `python -m selftest`: the dev bot run against real Discord in
channels of its own (#selftest-hub, #selftest-inbox, #selftest-log), on an
empty copy of the dev database, with the dev clock. What is typed and
pressed is simulated (handed straight to the bot's own entry points); what
the bot posts, edits and deletes is real, and is read back from Discord and
from the database before a step passes. How it works and what it can't
see: `docs/DEVELOPMENT.md`, "The self-test".

**Run:** 2026-10-13 13:00, 10 min 45 s
**Result:** 81 passed, 1 failed, 0 broke, 0 skipped, of 82 steps
**Requests to Claude:** real for 24 steps · US$0.1304 spent

## What failed

| Step | What | Expected | What happened | From |
|---|---|---|---|---|
| 1.07 | A typed answer: “add Testmag to my pills, twice a day at 8am”, then “9pm” | A card asking for the other dose's time with no Save; after “9pm” a card with 8:00 am and 9:00 pm and Save. Then Cancel removes it | the second card: 💊 Pills · new **Testmag** · 2× daily, any time ❔ times · 9:00 pm is 1 time for 2 doses a day What time is the other dose? -# or type your answer with ['9:00 am', '↩️ Cancel'] | T27 (37.4) |

## Discoveries

What is worth a look whether or not its step passed.

**Odd, though the step passed**

- 2.12: Yesterday's checklist stays in the hub after midnight and after the next morning's is posted. That is what the code does today; the clean-up spec replaces it
- 3.03: A card posted in the old look and saved with CARDS_V2 on stays a plain message: its confirmation is not drawn the new way. Harmless, but the two looks sit side by side after a switch

**Warnings and errors in `logs/bot.log` during the run**

- `WARNING assistant: Claude spend today is US$0.1178, over the daily limit of US$0.001`

**Slow steps** (12 seconds or more; a step is mostly waiting for Discord, and each input is given about a second to settle)

- 3.14 Every sketch in docs/mockups (19) posted with `dev mock`: 63s
- 1.08 Names: “add Testvit and Testvit forte”, “I took testvit”, “skip forte”: 20s
- 3.13d Pause and resume: “pause the evening checklist”, Save; then “turn the evening checklist back on”, Save: 18s
- 1.10c Add: “also post the pills checklist at 6 pm”, then Save: 13s
- 1.07 A typed answer: “add Testmag to my pills, twice a day at 8am”, then “9pm”: 13s
- 4.07 The spend line: two messages to Claude with the limit at US$0.001: 12s

The whole run took 10 min 45 s, 75 seconds of it with the bot off on purpose.

**In the specs and not tested here**

- Pills: a course with a start and an end, pausing until a date and coming back by itself, a pill whose doses can't fit, more than a handful of pills on one checklist, a dose skipped by the bot for want of time
- Pills: “no, …” undoing a change, a correction straight after Save becoming a change card, a reply to a line meaning that dose (the test replies to nothing)
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

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`. Took 224s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 1.01 | The dev bot starts in the test channels | ✅ pass | “🟢 Bot started” in #selftest-log naming dev.db, and “👋 Online and ready” in #selftest-inbox |  |  | asked |
| 1.01b | The schedules the engine made at start | ✅ pass | Three rows, each once: Nightly backup and End of the day (the bot's own, locked) and Pills checklist at 6:00 am every day in the hub, silent; each with exactly one run booked, with a key | End of the day 00:00, Nightly backup 03:00, Pills checklist 06:00 |  | scheduler stage 1 |
| 1.02 | The dev clock is moved to tomorrow, 5:50 am | ✅ pass | The clock reads 5:50 am tomorrow; the day rolled over with nothing posted in the hub | Wed 14 Oct 05:50 |  | asked |
| 1.02b | Midnight and 3:00 am went by on the way | ✅ pass | The end of the day and the nightly backup each ran once from their schedules, for those local times, and each is booked again for the next day; “💾 Backup saved” is in #selftest-log (the copy is in the run's own folder) | backup assistant-2026-10-14_055000.db |  | scheduler stage 1 |
| 1.03 | “add Testa to my pills at 8am, 11am and 2pm, at least 3 hours apart, not after 4pm, with food”, then Save | ✅ pass | A card “💊 Pills · new” naming Testa with Save and Cancel; after Save the pill exists and the card is its confirmation | ✅ Saved · 💊 **Testa** · 3× daily · `8:00 am`, `11:00 am`, `2:00 pm` · at least 3h apart · not after `4:00 pm` · *with fo | real request | T49, golden 1 |
| 1.04 | “add Testany to my pills once a day”, then Save | ✅ pass | A card “💊 Pills · new” naming Testany with Save and Cancel; after Save the pill exists and the card is its confirmation | ✅ Saved · 💊 **Testany** · daily, any time | real request | T15 |
| 1.05 | A question on the card: “add Testiron to my pills at 8” | ✅ pass | A card with “daily at ❔”, the question morning or evening, a button for 8:00 am and 8:00 pm, Cancel, and no Save | 8:00 am / 8:00 pm / ↩️ Cancel | real request | T25 (37.1) |
| 1.06 | The answer is pressed: 8:00 pm, then Save | ✅ pass | The same message is rewritten with 8:00 pm and Save; Save adds Testiron at 8:00 pm |  |  | T26 (37.2) |
| 1.07 | A typed answer: “add Testmag to my pills, twice a day at 8am”, then “9pm” | ❌ fail | A card asking for the other dose's time with no Save; after “9pm” a card with 8:00 am and 9:00 pm and Save. Then Cancel removes it | the second card: 💊 Pills · new **Testmag** · 2× daily, any time ❔ times · 9:00 pm is 1 time for 2 doses a day What time is the other dose? -# or type your answer with ['9:00 am', '↩️ Cancel'] | real request | T27 (37.4) |
| 1.07b | The same request with an empty place where the second time would go | ✅ pass | What Claude understood is still used: a card for Testmag asking for the other dose's time, never “I didn't understand that”. Cancel removes it |  | recorded answer | self-test of 2026-10-13, fix 2 |
| 1.08 | Names: “add Testvit and Testvit forte”, “I took testvit”, “skip forte” | ✅ pass | The whole name wins: Testvit is taken, not Testvit forte. Part of a name finds the only fit: Testvit forte is skipped | {'Testvit': 'done', 'Testvit forte': 'skipped'} | real request | T22 (40.1, 40.2) |
| 1.09 | A name that fits two: “pause testv” | ✅ pass | A card asking which one, a button for each of the two, no Save. Cancel removes it | Testvit / Testvit forte / ↩️ Cancel | real request | T23 (40.3) |
| 1.09b | “pause testv” when Claude does not pass the name on as typed (completed to a whole name) | ✅ pass | The code checks what was typed: “testv” fits two pills, so the card still asks which one, with a button each and no Save |  | recorded answer | self-test of 2026-10-13, fix 1 |
| 1.09c | “pause testv” when Claude does not pass the name on as typed (handed over as “it”) | ✅ pass | The code checks what was typed: “testv” fits two pills, so the card still asks which one, with a button each and no Save |  | recorded answer | self-test of 2026-10-13, fix 1 |
| 1.10 | “remove testvit and testvit forte”, then Remove | ✅ pass | A remove card with a red Remove; after it both are gone |  | real request | T25 (40.5) |
| 1.10b | `my schedule` | ✅ pass | A list, with no request to Claude: “🗓️ My schedule”, Pills checklist every day at 6:00 am in #hub, silent, with its next run; the bot's own in one small line; a plain message with CARDS_V2 off |  |  | scheduler stage 2 (schedule-list-v2) |
| 1.10c | Add: “also post the pills checklist at 6 pm”, then Save | ✅ pass | A card “🗓️ Schedule · new”: Evening pills checklist, every day at 6:00 pm, #hub, silent, its next run, and “also every day at 6:00 am”. After Save the schedule exists, its run for 6:00 pm today is booked, and the list shown before is brought up to date in place |  | real request | scheduler stage 2 |
| 1.10d | Move: “move the evening checklist to 6:30pm”, then Save | ✅ pass | A change card: **Evening pills checklist**, `time · 6:00 pm → 6:30 pm`, and “Next after this: … today 6:30 pm”. After Save the run booked for 6:00 pm is gone and one for 6:30 pm is booked |  | real request | scheduler stage 2 (schedule-change-v1) |
| 1.11 | 6:00 am: today's checklist | ✅ pass | One checklist in the hub, posted without a notification, naming Testa, Testany and Testiron; a Taken / Skip message under it for Testany (no time) | ## 💊 Pills · ▱▱▱▱▱ 0 of 5 |  | asked; 36, T15 |
| 1.11b | The run log for the 6:00 am checklist | ✅ pass | One run for today's 6:00 am, done, with its key and a line saying what it decided; tomorrow's 6:00 am booked once | s3@2026-10-14T06:00#1 · posted, or already there, or nothing to take today (the log |  | scheduler stage 1 |
| 1.11c | `dev jobs` | ✅ pass | What is booked next (the backup, the end of the day, the checklist) and how the last run of each ended, from the engine's run log |  |  | scheduler stage 1 |
| 1.12 | `pills` typed in #selftest-inbox | ✅ pass | A fresh copy at the bottom of the hub; the old checklist and its messages are gone |  |  | T15, R48 |
| 1.13 | `took testany`: the typed shortcut | ✅ pass | At once “✅ **Testany** · taken …”, the checklist shows it, Testany's own message goes, and no request to Claude is made | ✅ **Testany** · taken 6:00 am · still to take today: Testa (dose 1 of 3) `8:00 a |  | 43.1 |
| 1.14 | `took testany` again | ✅ pass | Not the shortcut any more (nothing is left today): it is read as plain words, and the answer says it is already taken. Nothing changes | ✅ **Testany** · taken 6:00 am already | real request | 43.2 |
| 1.15 | 8:00 am: the reminder for Testa | ✅ pass | One new message in the hub that notifies. Its first line is “💊 Routine due · 8:00 am” and names no pill; it was posted as that line and written in after (an edit); under it Testa, dose 1 of 3, with Taken, Taken at…, Snooze 15m, Skip | 💊 Routine due · 8:00 am |  | T41 (38.2), asked |
| 1.16 | Taken is pressed on the reminder | ✅ pass | The reminder goes; dose 1 is taken; the checklist shows it |  |  | 38.4 |
| 1.17 | Too soon: `took testa` a minute after dose 1 | ✅ pass | A card “⚠️ That's … after dose 1 … Log it anyway?” with Log it and Cancel; nothing is ticked off. Cancel removes it | ⚠️ That's just now: dose 1 was taken 8:00 am. The gap is at least 3h. Log it anyway? |  | 43.3, T46 |
| 1.18 | The next reminder, and Snooze 15m | ✅ pass | When dose 2 falls due a reminder is posted; Snooze rewrites the same message with “Snoozed until …” | -# 💤 Snoozed until 11:15 am |  | T42 (38.3) |
| 1.19 | 15 minutes later the reminder is posted again | ✅ pass | A new message takes the place of the snoozed one (so the phone buzzes again); only ever one prompt |  |  | T42 (38.3) |
| 1.20 | Taken at… on the reminder, with a time typed | ✅ pass | A form opens; with the time sent, the reminder goes and dose 2 is taken at that time | taken at 11:10 am |  | T43 (38.4) |
| 1.21 | A correction in words: “actually dose 2 of testa was at …” | ✅ pass | One line with the old time → the new one, and no second dose logged | ✏️ **Testa** (dose 2 of 3) · taken 11:10 am → 11:06 am · still to take today: Testa (dose 3 of 3) `2:06 pm`, T | real request | asked; pills stage 4 |
| 1.22 | A question about my data: “what pills do I have left today?” | ✅ pass | The pills task answers (the checklist, or a line pointing at it); my message is left with no ⚠️ |  | real request | fixture |
| 1.23 | The clock is moved to 20 seconds before dose 3 falls due, and a card is left open: “add Otherpill once a day” | ✅ pass | A card with Save, not pressed (asked for now, so that it has not expired by the restart) |  | real request | T36 (36.1) |
| 1.24 | The bot is cut off in the middle of answering a message, seconds before dose 3 falls due | ✅ pass | The process ends with my message still marked 👀 and its log row still “received”. Checked after the restart (2.01 to 2.05) |  |  | asked; T38 (36.4) |

## Start 2: the same settings, after 75 seconds off. The catch-up, then the rest of the day and the next morning

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`. Took 70s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 2.01 | The catch-up after the restart is said once | ✅ pass | One new “🔁 Caught up after a restart” in #selftest-log. It says my message was cut off and that something ran late or was posted, and names no pill | 🔁 Caught up after a restart / • “what is the capital of France?” was cut off by the stop and never answered: marked ⚠️, say it again / • Ran late, as the bot was off when they were due: pill reminder (1m late) |  | asked; T38 (36.4) |
| 2.02 | The message that was cut off | ✅ pass | ⚠️ in place of 👀 on it: it was never answered, so I say it again |  |  | 36 (restarts) |
| 2.03 | Dose 3's reminder fell due while the bot was off | ✅ pass | Exactly one reminder in the hub, posted once at start, with the neutral first line; not one for each minute missed |  |  | asked; restarts |
| 2.04 | The checklist after the restart | ✅ pass | The same message as before the stop, brought up to date in place: no second copy |  |  | T37 (36.3) |
| 2.04b | The schedules after the restart | ✅ pass | The same three rows as before the stop (none made again), no run booked twice, and the 6:00 am checklist was not posted a second time |  |  | scheduler stage 1 |
| 2.05 | A card from before the restart: Save is pressed | ✅ pass | Otherpill is saved: the button still works and applies exactly what the card showed |  |  | T37 (36.2) |
| 2.06 | Left alone, the reminder is posted again (1 of 3) | ✅ pass | A new message in place of the old, saying “reminder 1 of 3”; only ever one |  |  | T44 (38.5) |
| 2.07 | Left alone, the reminder is posted again (2 of 3) | ✅ pass | A new message in place of the old, saying “reminder 2 of 3”; only ever one |  |  | T44 (38.5) |
| 2.08 | Left alone, the reminder is posted again (3 of 3) | ✅ pass | A new message in place of the old, saying “reminder 3 of 3”; only ever one |  |  | T44 (38.5) |
| 2.09 | After the third reminder the dose is missed | ✅ pass | The reminder goes, the dose is missed, and the checklist shows ❌ |  |  | T45 (38.6) |
| 2.10 | A missed dose logged as taken: `took testa` | ✅ pass | The typed shortcut, with no request to Claude, and it asks first: a card “Dose 3 was missed (due …). Log it as taken now?” with Log it and Cancel; nothing is ticked off until Log it | ⚠️ Dose 3 was missed (due 2:06 pm). Log it as taken now? |  | T45 (38.7); asked 2026-10-13 |
| 2.11 | 8:00 pm: Testiron's reminder, and Skip | ✅ pass | A reminder for Testiron; Skip takes it down and the dose is skipped |  |  | 38 |
| 2.11b | The schedule I added ran at the time I moved it to | ✅ pass | One run of the checklist for 6:30 pm, done, and none for 6:00 pm; the hub still has one checklist for the day (it was brought up to date, not posted again) |  |  | scheduler stage 2 |
| 2.12 | Midnight: the day is closed | ✅ pass | Nothing of yesterday is left open; Otherpill, never touched, is missed. Yesterday's checklist is written one last time and left in the hub (as the code does today; the clean-up spec changes this) | yesterday's checklist is still in the hub |  | pills 29; scheduler spec 18.2 |
| 2.13 | 6:00 am the next day: a fresh checklist | ✅ pass | A new message for the new day with every dose still to take; one checklist for today |  |  | asked; 23 |
| 2.14 | Left for the next start, in the old look: an open change card and a reminder | ✅ pass | A change card “dose · … → 2 tablets” with Save, and at 8:00 am a reminder for Testa |  | real request | asked: switching looks |

## Start 3: `CARDS_V2` on. Every card posted and edited in the new look, and the old look's messages edited under it

Settings: `CARDS_V2=true`, `REMINDERS_ENABLED=true`. Took 192s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 3.01 | A clean restart with CARDS_V2 on | ✅ pass | No new catch-up card about pills or a checklist (one naming only `tidy` is all right), and no second checklist |  |  | T39 (36.5) |
| 3.02 | An old-look reminder, Snooze pressed with the new look on | ✅ pass | Discord accepts the edit: the same message now says “Snoozed until …” | the message is Components V2 afterwards |  | asked: switching looks |
| 3.03 | An old-look card, Save pressed with the new look on | ✅ pass | Discord accepts the edit: the card becomes its confirmation and Testa's dose is 2 tablets | the message is plain afterwards |  | asked: switching looks |
| 3.04 | The old-look checklist, rewritten with the new look on (`took testany`) | ✅ pass | The checklist kept for today shows Testany taken. Either the same message turned into the new look in place, or it was replaced by one message: never two | the same message, edited; it is Components V2 |  | asked: switching looks |
| 3.05 | `pills` with the new look on | ✅ pass | One message: “💊 Today · n of m taken”, the date, a box a pill with its status colour (green for Testany, taken; grey or amber for the rest), and no separate message for a dose with no time | # 💊 Today · 1 of 6 taken · boxes 0x3498db, 0x57f287, 0xfaa61a, 0xfaa61a |  | T51 (41.3) |
| 3.06 | Taken is pressed in Testa's box on the checklist | ✅ pass | The checklist stays and is rewritten in place: dose 1 has ✅; the reminder for it goes |  |  | T53 (41.5) |
| 3.07 | Taken pressed again in Testa's box: too soon | ✅ pass | An amber box “⚠️ That's … after dose 1 … Log it anyway?” with Log it and Cancel; nothing ticked off. Cancel |  |  | T54 (41.6) |
| 3.08 | Skip is pressed in Otherpill's box | ✅ pass | Its box turns grey and says skipped, with no buttons for it |  |  | T55 (41.7) |
| 3.09 | A question card in the new look: “add Testb to my pills at 8” | ✅ pass | A blurple box ending with the question, a button an answer and Cancel, no Save. The answer rewrites it in place with Save. Cancel removes it |  | real request | T50 (41.2) |
| 3.10 | A remove card in the new look: “remove otherpill”, then Remove | ✅ pass | A box with a red Remove; after it Otherpill is gone | box colour 0x5865f2 | real request | T57 (41.8) |
| 3.10b | A pill with no time is added with the new look on: “add Testlate once a day” | ✅ pass | After Save the drawn checklist gains a blue box for Testlate, any time, with its buttons, in place; no separate message for it |  | real request | T51 (41.3) |
| 3.11 | A reminder in the new look | ✅ pass | When dose 2 falls due: posted as the one neutral line and drawn after (an edit), an amber box naming Testa, four buttons. Left up for the next start |  |  | T52 (41.4) |
| 3.12 | Left for the next start, in the new look: an open change card | ✅ pass | A blurple change card “dose · 2 tablets → 3 tablets” with Save |  | real request | asked: switching back |
| 3.13 | The reset card in the new look: `reset channel`, then Cancel | ✅ pass | A red box (Components V2) with the channel under the heading, the count, that it can't be undone, and a red Delete all inside it; Cancel removes it and deletes nothing | drawn, colours ['0xed4245'] |  | 39.4; self-test of 2026-10-13, fix 5 |
| 3.13b | `my schedule` in the new look | ✅ pass | One drawn message: the heading, a box a schedule with the next to run amber and the other grey, and no buttons |  |  | scheduler stage 2 (schedule-list-v2) |
| 3.13c | Days and notify: “make the evening checklist notify, and only on weekdays”, then Save | ✅ pass | A blurple change card with `days · every day → Mon to Fri` and `notify · silent → notifies`; after Save the schedule is so |  | real request | scheduler stage 2 (schedule-change-v1) |
| 3.13d | Pause and resume: “pause the evening checklist”, Save; then “turn the evening checklist back on”, Save | ✅ pass | `paused · no → until you turn it back on`, and nothing is booked for it while paused; then `paused · … → on` and its next run is booked again |  | real request | scheduler stage 2 |
| 3.13e | Remove: “remove the evening checklist”, then Remove | ✅ pass | A card `… → removed` with a red Remove; after it the schedule is gone from the list, nothing is booked for it, and the 6:00 am one is untouched |  | real request | scheduler stage 2 |
| 3.14 | Every sketch in docs/mockups (19) posted with `dev mock` | ✅ pass | Discord accepts each one as a Components V2 message (the reminder's first line alone is plain text) | 19 posted |  | T2 to T10, block 44 |
| 3.15 | The checklist sketch's colours | ✅ pass | Its boxes carry the values of core/design.py for amber, blue, green, red and grey (how they look is yours to judge) |  |  | T4 (39.1) |

## Start 4: `CARDS_V2` off again, and a tiny spend limit. The new look's messages edited under the old, and the spend line

Settings: `CARDS_V2=false`, `REMINDERS_ENABLED=true`, `DAILY_SPEND_LIMIT=0.001`. Took 81s; the process ended with 0.

| Step | What | Result | Expected | Saw | Claude | From |
|---|---|---|---|---|---|---|
| 4.01 | A new-look reminder, Snooze pressed with the new look off | ✅ pass | Discord accepts the edit, and the message stays Components V2 (one can never go back to plain text): it now says “Snoozed until …” |  |  | asked: switching back; T58 |
| 4.02 | A new-look card, Save pressed with the new look off | ✅ pass | Discord accepts the edit: the card becomes its confirmation and Testa's dose is 3 tablets |  |  | asked: switching back |
| 4.03 | The new-look checklist after a start with the new look off | ✅ pass | The same message, still Components V2 (it can never go back to plain text), now holding the old look's words; and the Taken / Skip message for Testlate (no time) is back under it | ## 💊 Pills · ▰▰▱▱▱ 2 of 6 |  | asked: switching back |
| 4.03b | `took testlate` with the new look off, on the checklist that was drawn | ✅ pass | Discord accepts the edit of the Components V2 message from the old look's code: it shows Testlate taken, and Testlate's own message goes |  |  | asked: switching back |
| 4.04 | `pills` with the new look off | ✅ pass | A fresh checklist in the old look (a plain message), in place of the drawn one | ## 💊 Pills · ▰▰▱▱▱ 3 of 6 |  | T58 (41.8) |
| 4.05 | A new card with the new look off: “add Testlast once a day”, then Cancel | ✅ pass | A plain card with Save and Cancel; Cancel removes it |  | real request | T58 (41.8) |
| 4.05b | The reset card with the new look off: `reset channel`, then Cancel | ✅ pass | A plain message with the same words and buttons; Cancel removes it |  |  | T58; self-test of 2026-10-13, fix 5 |
| 4.06 | `dev cost` | ✅ pass | Under Today a small line with what was spent against DAILY_SPEND_LIMIT, the limit of a tenth of a cent written as US$0.001 | -# ⚠️ over today's limit: US$0.1178 of US$0.001 (DAILY_SPEND_LIMIT) |  | T35, T56 (42.1, 42.3) |
| 4.07 | The spend line: two messages to Claude with the limit at US$0.001 | ✅ pass | One “💰 Claude spend is over today's limit” in #selftest-log after the first, and no second one after the second |  | real request | T49, T50 (42.2, 42.3) |
| 4.07a | The bot's own is not changed by words: “move the backup to 4am” | ✅ pass | One line saying the nightly backup is the bot's own and isn't changed here; no card, and it still runs at 3:00 am |  | real request | scheduler stage 2 |
| 4.07b | `dev run backup` | ✅ pass | A handler run by hand, outside its schedule: “▶️ Ran: core.nightly_backup”, a second “Backup saved”, a run of its own in the log, and the night's backup still booked |  |  | scheduler stage 1 |
| 4.08 | `dev clock reset` | ✅ pass | The clock is the real time again, and the standing jobs are booked for the real day | checklist booked for 2026-10-14T06:00 |  | T57 |

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
| QA-TONIGHT 59 | Live after its restart: the test starts the service and checks the lock and the start card; that it behaves is yours |
| Block 44 | The four new sketches (briefing, schedule list, schedule change, tidy): whether they are what you want. The test only checks Discord accepts them |
| Wording everywhere | Every line the bot says is checked for the words that matter (a name, a time, a mark), not for whether it reads well |
| Real presses | Every press in this run was simulated: the handler behind the button was called and it edited the real message. That Discord delivers a real tap to that handler is checked by discord.py's own routing and by you pressing one |

## The test's channels and data

- The category `selftest` and its three channels are left in place, holding the last run. Every run empties them first.
- To empty them now: `python -m selftest --clear`. To delete them and the category: `python -m selftest --remove` (the next run makes them again). Both work over HTTP, with live running.
- `data/dev.db` and the dev clock are as they were before the run: they are moved aside for it and put back after.
- The run's own database and each start's results are kept in `data/selftest/run-20261013-130023/` (never in git). Delete the folder when you like.

