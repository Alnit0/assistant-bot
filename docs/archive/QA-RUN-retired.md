# QA run sheet: retired blocks

Blocks taken out of `docs/QA-RUN.md` on 2026-10-14 because they were
out of date, with their wording as it was. Each says why it went.
Nothing here is to be run.

## 17. Traces: `dev why` and bug reports

**Retired 2026-10-14.** Its steps use the demo shopping list (`add
butter`, `and jam`), which went with the old path (block 18, step 8).

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), in #inbox, dev mode off.
Restart the bot first: it adds a column to the message log.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add butter`; then, pressing nothing, `and jam`. Type `dev why`, then `dev why 3`. Press nothing | One block in a code box that can be copied whole: "#<n> · <time> · chat · ok", "said: and jam", "route: follow-up (card … is open and the message sticks to it…)", "router: not asked", an "extraction:" line with what came back, "python:" lines for each check (sticky, correction, restatement, merge), "card before:" and "card after:", "shown:", and "cost: US$… · 1 request(s)". `dev why 3` posts three blocks, oldest first; the `dev why` words themselves are never among them | J47 |
| 2 | React 🐞 to the card the bot posted; open the new post in #bugs. Then press **Cancel** on the card | The post in #bugs has a **Trace** section between "That turn" and "Related errors": the same block `dev why` shows for the message of mine that the card answered | P31 |
| 3 | Type `dev cost` | The card ends with "-# List context sent to extraction this month: … of … lines over … messages, … (at most 20 a task a message)" | J48 |

## 33. Reminder mock-ups

**Retired 2026-10-14.** It says nothing of reminders is built. They are
built and on for live (block 38, the self-test's 1.15 to 2.11). The lock
screen is now checked on a real reminder: the short list, 6.

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off, with your phone locked beside you for
step 1. These are sketches: the buttons only say they are mock-ups.
Nothing here is built yet.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Lock your phone and type `dev mock reminder-v1-first` from the desktop; then `dev mock reminder-v1` (the same as block 39, step 2: do it once) | The lock screen says "💊 Routine due · 11:12 am" and never the pill's name. The second message: the pill and dose, when it is due and why, the note, and Taken, Taken at…, Snooze 15m, Skip | J55 |
| 2 | Type `dev mock reminder-renudge-v2` | Two cards: a re-nudge ("Reminder 2 of 3", when it was first asked and when the last one comes), and the same prompt while snoozed ("Snoozed until 11:27 am") | J55 |
| 3 | Type `dev mock reminder-missed-v2`, then `dev mock too-soon-v2` | An amber box on the checklist (a dose is still to come) with dose 2 marked ❌ missed and when it was due; then an amber card that says the dose is too soon after the last and asks "Log it anyway?", with **Log it** and **Cancel** | J55 |

Say what to change in any of them (wording, order, colours, buttons).

## 42. The daily spend line

**Retired 2026-10-14.** The setting is `DAILY_SPEND_LIMIT_NZD` now and
the amounts are in NZ$. The line in `dev cost` is the self-test's 4.06;
the card in #bot-log (4.07) only runs with real requests.

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database. Steps 2 and 3 send two messages to Claude (about
one cent in all): skip them if you'd rather not.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev cost` | Under "Today", a small line: "US$… of today's US$0.50 limit (…%)" | J61 |
| 2 | Stop the dev bot, put `DAILY_SPEND_LIMIT=0.001` in `.env`, start it. Say `what pills do I have?` | The answer as usual, and one card in #bot-log: "💰 Claude spend is over today's limit", with what was spent and the limit | K25 |
| 3 | Say `what pills do I have?` again, then type `dev cost` | No second card in #bot-log. `dev cost` shows "⚠️ over today's limit: US$… of US$0.00 (DAILY_SPEND_LIMIT)" | K25, J61 |
| 4 | Stop the dev bot and take `DAILY_SPEND_LIMIT` out of `.env` again | | |

## 44. Sketches: briefing, schedule, tidy

**Retired 2026-10-14.** Sketches of the briefing, the schedule list and
the tidy, from before they were built. All three are built and on for
live: look at the real ones (the short list, 1).

In the dev channel, on either database. Nothing here is built: these
are sketches posted by `dev mock`, and their answers are the questions
at the top of `docs/STATUS.md`.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev mock briefing-v2` | "☀️ Today" with the date (no "as of": it is kept up to date in place); an amber Pills box with the count, the next dose and a line about yesterday; grey placeholder boxes for Gym, Calendar and To-dos; no buttons | J62 |
| 2 | Type `dev mock schedule-list-v2` | "🗓️ My schedule": the morning routine in amber with its three steps (tidy, briefing, checklist), where it posts, silent, its next and last run; a grey box for a second schedule; Paused under a separator; small lines for the bot's own and for pill times; no buttons | J62 |
| 3 | Type `dev mock schedule-change-v1` | A blurple card "🗓️ Schedule · change": two schedules, each `field · old → new`, ❓ on the guess, when each next runs, **Save** and **Cancel** | J62 |
| 4 | Type `dev mock cleanup-v1` | What #bot-log would be told when a tidy went wrong: a channel a box, what was removed, kept and left, and why. Its last line says a tidy with nothing wrong posts nothing | J62 |

