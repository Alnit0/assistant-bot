# QA tonight

One ordered run of every block that is waiting (27 to 42 of
`docs/QA-RUN.md`), on the dev database. Written on 2026-10-13. The
steps are short forms of the ones in the run sheet: the block and step
are in brackets, for the full wording and for reporting.

**Six starts of the dev bot in all.** Parts 1 to 4 need only your
phone, with the PC running dev. Parts 5 to 8 each begin with something
typed at the PC.

**Report** as usual, by step number here or by test id: `12 pass`,
`31 fail: no second message`, `44 skip`.

## Before you start (at the PC)

- The service is stopped, and stays stopped for this run. Check:
  `nssm status assistant-bot` says `SERVICE_STOPPED`.
- `.env` as for any QA run: `KEEP_CONFIRMATIONS=false`, the hub set.
  No `REMINDERS_ENABLED`, `CARDS_V2` or `DAILY_SPEND_LIMIT` line.
- In a terminal in the project folder: `python main.py --dev`. Leave it
  running. The first start brings the dev database up to date (new
  tables and columns), which takes a moment.
- Dev mode off. Phone beside you.

The whole run sends about 60 messages to Claude: roughly 30 cents.

## Part 1. The lock screen and the sketches (phone only)

Nothing here is built: the buttons only say they are mock-ups. Type in
#inbox.

| # | Type or do | You should see | Block |
|---|---|---|---|
| 1 | `dev clock reset` | The clock is the real time | |
| 2 | Lock the phone. From the desktop (or ask someone): `dev mock reminder-v1-first`. No desktop: type it, lock at once, and read the notification afterwards | The lock screen shows "💊 Routine due · 11:12 am" and nothing else. **Say exactly what it showed** | 39.2, 33.1 |
| 3 | `dev mock reminder-v1` | That same line, with an amber box under it: Pill A, dose 2 of 3, when and why, and **Taken**, **Taken at…**, **Snooze 15m**, **Skip**. Say what the lock screen showed for this one too | 39.2 |
| 4 | `dev mock checklist-v2` | A heading and the date, then a box a pill: amber (due, with buttons), blue (any time), green (taken), red (missed), grey (skipped by the bot), a line, and Paused | 39.1 |
| 5 | Look at step 4 in each theme you use | Amber, blue, green, red and grey can be told apart. **Say which colour to change, if any** | 39.6 |
| 6 | `dev mock confirm-card-v2` then `dev mock question-card-v1` | A blurple box with two pills, `old → new`, ❓ on the guesses, **Save** and **Cancel**. Then a card that asks, with **8:00 am**, **8:00 pm**, **Cancel** and no Save | 39.3 |
| 7 | `dev mock too-soon-v2` then `dev mock reset-card-v2` | An amber box ending "**Log it anyway?**" with **Log it** and **Cancel**. Then a red box for the reset | 39.5, 39.4, 33.3 |
| 8 | `dev mock reminder-renudge-v2` then `dev mock reminder-missed-v2` | Two boxes: "Reminder 2 of 3" in amber, and the same one snoozed in grey. Then an amber pill box with "❌ dose 2 · missed" and a next dose | 33.2, 33.3 |
| 9 | `dev mock gym-import-v2` then `dev mock gym-change-v2` | "🏋️ Gym · new": three workouts, a line an exercise, the columns as read (one ❓). Then "🏋️ Gym · change": only what differs, `old → new`, ➕ and ➖ | 35.1, 35.2 |
| 10 | `dev mock gym-workout-v1` then `dev mock gym-logged-set-v2` | A workout: green (done), amber (the one you are on, with buttons), grey (to come), **Finish**. Then the line said after a set, and that exercise's box | 35.3, 35.4, 39.4 |

## Part 2. Timers and "it" (phone only)

| # | Type or do | You should see | Block |
|---|---|---|---|
| 11 | `timer 10s tea`, then `timer 10m eggs`. When tea rings, say `give it 5 more` | "➕ tea: 5m more"; eggs untouched | 27.1 |
| 12 | Say `pause everything`, then `resume it` | "⚠️ Which timer? Say its name." with a line for each | 27.2 |
| 13 | Say `give it 2 more` about tea by replying to tea's message; then reply `dev why` to your own reply | Tea gets 2 minutes. The trace shows `timers · timer_change` with "which" filled in, and no router request | 30.1, 31.1 |
| 14 | Say `cancel all my timers`; press the red **Cancel 2 timers** | "🚫 **Cancelled 2**" naming both | 31.2 |

## Part 3. Pills in plain words (phone only)

| # | Type or do | You should see | Block |
|---|---|---|---|
| 15 | Say `add pill X once a day`, **Save**. Say `add pill Y once a day`, **Save**. Type `pills` | Two cards saved; today's checklist with both, and a Taken / Skip message for each | 28 |
| 16 | Say `took my pill X`. Type `dev clock +10m`. Say `took the usual one`; press **Save** | "✅ **Pill X** · taken …" at once. Then a card "💊 Pills · change" with "**Pill Y** · taken … ❓"; Save ticks it off | 28.1 |
| 17 | Say `no I didn't` | "↩️ **Pill Y** · no longer ticked off", no card | 28.2 |
| 18 | Type `dev clock +1d`, then `pills`. Say `took my pill X`, then `took my pill Y`. Reply to the "✅ **Pill X** …" line with `it was 8am` | "✏️ **Pill X** · taken … → 8:00 am": Pill X, not Pill Y, and no card | 29.1 |
| 19 | Reply to that same Pill X line with `actually I didn't` | "↩️ **Pill X** · no longer ticked off" | 29.2 |
| 20 | Say `add Testpill at 8am with food`, **Save**. Say `Testpill no longer needs a time`, **Save** | A change card: `schedule · daily at 8:00 am → daily, any time` | 34.1 |
| 21 | Say `Testpill doesn't need to be with food any more`, **Save** | A change card: `notes · with food → none` | 34.2 |
| 22 | Say `add Testiron and Testiron forte to my pills, once a day`, **Save**. Say `I took testiron`, then `skip forte` | Testiron is logged (the whole name wins); Testiron forte is skipped (part of a name finds it) | 40.1, 40.2 |
| 23 | Say `pause testir`. Then press **Cancel** | A card asking which one, a button for each of the two, no Save | 40.3 |
| 24 | Send any picture with the words `what is this` | An ordinary answer from chat: the file changes nothing | 40.4 |
| 25 | Say `remove testiron and testiron forte`, **Remove**. Then say `add Testiron to my pills at 8` | Both gone. Then a card "**Testiron** · daily at ❔", "Is that 8 in the morning or the evening?", **8:00 am**, **8:00 pm**, **Cancel**, no Save | 40.5, 37.1 |
| 26 | Press **8:00 pm**. Then say `actually make it 8am`; press **Save** | The card reads "daily at `8:00 pm`" with Save. Then a fresh card with `8:00 am`; Save saves it | 37.2, 37.3 |
| 27 | Say `add Testmag to my pills, twice a day at 8am`. Then say `9pm`; press **Save** | A card with "2× daily", a ❔ line, "What time is the other dose?" and **8:00 pm**. After `9pm`: `8:00 am`, `9:00 pm` and Save | 37.4 |
| 28 | Say `add Testvit C and Testvit D to my pills`, **Save**. Say `pause testvit`. Press **Testvit C**, then **Cancel** | "Which one is “testvit”?" with a button each; then the pause card for Testvit C; Cancel removes it | 37.5 |
| 29 | Type `pills`. Wait six minutes (do Part 4 meanwhile), then say `took it`. Press a pill | "Which pill?" with a button for each still to take; after the press it is ticked off | 37.6 |
| 30 | Say `add pill  TESTIRON` (two spaces, capitals). Press **Cancel** if a card shows | Testiron as it is, or a change card for it: never a second pill | 32.3 |
| 31 | Say `remove testpill, testiron, testmag, testvit c and testvit d`, **Remove**. Leave Pill X and Pill Y | They are gone | 34.4, 37.7 |

## Part 4. Bugs and cost (phone only)

| # | Type or do | You should see | Block |
|---|---|---|---|
| 32 | Say `show my open bugs`. React 🐞 to any message of yours | "🐞 Logged as D<n>"; the list above gains it by itself | 32.1 |
| 33 | Take the 🐞 off and put it on again | "🐞 Already logged as D<n>", the same link: one bug | 34.3 |
| 34 | Open that bug's post in #bugs and press **Won't fix** | The list in the channel loses it again | 32.2 |
| 35 | `dev cost` | Under Today, a small line: "US$… of today's US$0.50 limit (…%)" | 42.1 |

## Part 5. Restarts (at the PC: two stops and starts)

| # | Type or do | You should see | Block |
|---|---|---|---|
| 36 | Say `add Otherpill`; don't press. Type `pills`. At the PC: Ctrl+C, then `python main.py --dev` | #bot-log: "🟢 Bot started" and no "🔁 Caught up after a restart" (one naming `tidy` is all right) | 36.1 |
| 37 | Press **Save** on the Otherpill card. Press **Taken** under the checklist for Pill X | Otherpill is saved. The checklist is the same one as before the restart, with Pill X ticked off | 36.2, 36.3 |
| 38 | `dev clock 5:58am`. At the PC: Ctrl+C, wait four minutes, `python main.py --dev` | One new checklist. #bot-log: one "🔁 Caught up after a restart" saying the checklist was posted late. No "Pills checklist not posted" | 36.4 |

## Part 6. Reminders on (at the PC: one start)

At the PC: Ctrl+C, then
`$env:REMINDERS_ENABLED = "true"; python main.py --dev`

| # | Type or do | You should see | Block |
|---|---|---|---|
| 39 | Look at #bot-log and the hub | Only "🟢 Bot started": no new checklist, no "🔁 Caught up" | 36.5 |
| 40 | `dev clock reset`. Say `remove otherpill, pill x and pill y`, **Remove**. Say `add Testrem to my pills at 3pm and 9pm, at least 4 hours apart, with food`, **Save**. `dev clock 2:59pm` | Nothing about Testrem beyond the card and the checklist | 36.6, 38.1 |
| 41 | Lock the phone. `dev clock 3:00pm` | Lock screen: "💊 Routine due · 3:00 pm", no pill name. In the hub: that line, "**Testrem** · dose 1 of 2", "Due `3:00 pm`", "with food", four buttons | 38.2 |
| 42 | Press **Snooze 15m**. `dev clock 3:15pm` | "Snoozed until 3:15 pm"; then a fresh message replaces it and the phone buzzes again | 38.3 |
| 43 | Press **Taken at…**, type `3:05pm`, submit | The message goes; the checklist shows dose 1 taken 3:05 pm | 38.4 |
| 44 | `dev clock 9:00pm`, `dev clock 9:15pm`, `dev clock 9:30pm`, `dev clock 9:45pm` | One prompt, replaced three times: "reminder 1 of 3", "2 of 3", "3 of 3". Only ever one message | 38.5 |
| 45 | `dev clock 10:00pm`. Then say `took testrem` | The message goes and the checklist shows ❌ missed. Then it is ticked off all the same | 38.6, 38.7 |
| 46 | Say `add Testgap to my pills at 3pm and 9pm, at least 4 hours apart`, **Save**. `dev clock 3:00pm`, press **Taken**. `dev clock 9:00pm`. On the reminder press **Taken at…**, type `5pm`, submit | A card: "**Testgap** (dose 2 of 2) · taken 5:00 pm", "⚠️ That's 2h after dose 1 … Log it anyway?", **Log it**, **Cancel**. Nothing ticked off; the reminder still there | 38.8 |
| 47 | Press **Cancel**. Then **Taken at…**, `5pm` again, and **Log it** | After Cancel the reminder stays. After Log it: taken 5:00 pm, the reminder goes | 38.9 |
| 48 | Say `remove testrem and testgap`, **Remove**. `dev clock reset` | Gone; the real time again | 38.10 |

Step 38.11 (reminders on with no hub) is optional and needs `.env`
edited: skip it tonight.

## Part 7. The new look and the spend line (at the PC: one start)

At the PC: Ctrl+C, then
`$env:CARDS_V2 = "true"; $env:DAILY_SPEND_LIMIT = "0.001"; python main.py --dev`
(reminders stay on: the terminal remembers).

| # | Type or do | You should see | Block |
|---|---|---|---|
| 49 | Say `add Testa to my pills at 8am, 11:30am and 3pm, at least 3 hours apart, not after 4pm, with food`. Look, then **Save** | A blurple box: "💊 Pills · new", the pill's line, **Save** and **Cancel** inside it, a small hint under it. And one card in #bot-log: "💰 Claude spend is over today's limit" | 41.1, 42.2 |
| 50 | Say `add Testb twice a day at 8`. Then **Cancel** | A blurple box ending with the question in bold, a button an answer, **Cancel**, no Save. No second 💰 card in #bot-log | 41.2, 42.3 |
| 51 | Say `add Testany once a day`, **Save**. `dev clock 7:55am`, then `pills` | One message: "💊 Today · 0 of 4 taken", the date, a box a pill. Testa amber with **Taken**, **Taken at…**, **Skip**; Testany blue, "any time", the same buttons. No separate message for Testany | 41.3 |
| 52 | Lock the phone. `dev clock 8:00am` | Lock screen: only "💊 Routine due · 8:00 am". In the hub: that line with an amber box naming Testa, four buttons | 41.4 |
| 53 | On the checklist, press **Taken** in Testa's box | The checklist stays and is rewritten: "✅ dose 1 · 8:00 am", "**Next:** dose 2"; the reminder goes | 41.5 |
| 54 | Press **Taken** in Testa's box again | An amber box: "⚠️ That's … after dose 1 … Log it anyway?", **Log it**, **Cancel**. Nothing ticked off. Press **Cancel** | 41.6 |
| 55 | Press **Skip** in Testany's box | Its box turns grey, "⏭️ skipped", no buttons | 41.7 |
| 56 | `dev cost` | "⚠️ over today's limit: US$… of US$0.00 (DAILY_SPEND_LIMIT)" | 42.3 |
| 57 | Say `remove testa and testany`, **Remove**. `dev clock reset` | Gone; the real time again | 41.8 |

## Part 8. Back to normal (at the PC: one start)

At the PC: Ctrl+C, then
`Remove-Item Env:REMINDERS_ENABLED, Env:CARDS_V2, Env:DAILY_SPEND_LIMIT; python main.py --dev`

| # | Type or do | You should see | Block |
|---|---|---|---|
| 58 | `pills`, then say `add Testlast once a day` and **Cancel** | The old look again: a plain checklist and a plain card (a message drawn the new way earlier may keep its box) | 41.8 |
| 59 | At the PC: Ctrl+C. Start the service when you want live back: `nssm start assistant-bot` | The live bot starts; its first start adds the new tables | |

## Added after this sheet was written

Block 43 of `docs/QA-RUN.md` (`took <pill>`, four steps, phone only)
was built on 2026-10-13 after your answers. It needs a start of the dev
bot from after that change; do it any time, on its own.

Block 44 (four sketches for the briefing, the schedule and the tidy;
`dev mock` only) was added the same day. Nothing in it is built; look
at them with the questions at the top of `docs/STATUS.md`.

## What the self-test has already run

`docs/SELFTEST.md` (2026-10-13) ran these with simulated typing and
presses and read the results back from Discord: steps 15 (the
checklist), 22, 23 (failed: see the report), 25 to 27, 35 to 39, 41 to
45, 49 to 58, and blocks 43 and 44 (that Discord accepts each sketch).
What it could not see is still yours and is listed at its end: the
lock screen (2, 3, 41, 52), the colours and the look (4 to 10, 49 to
55), timers (11 to 14), a picture (24), bugs (32 to 34) and step 29.
No step was marked passed in `docs/TESTING.md` from it.

## What this run does not cover

Blocks before 27 that are still to be reported (21, 22, 23 steps 5 to
7, 24 step 8, 25 steps 1, 2 and 6, and 26) are in `docs/QA-RUN.md`.
