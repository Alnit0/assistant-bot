# QA run sheet

One pass through 188 of the 212 👤 Manual tests in `docs/TESTING.md` that are
⬜ Untested (as of 2026-10-10); the other 24 are for pills stages not built yet
(group R) or need a setup of their own, and join as each can be run. Blocks share setup and each one leaves things
ready for the next, so run them in order.

**Time:** about 3¼ hours at the keyboard, plus two nights for the backup
tests (block 12).

| Block | What | Dev mode | Tests | Minutes |
|---|---|---|---|---|
| 1 | Start-up | off | 3 | 5 |
| 2 | Builtin words and chat | off | 12 | 9 |
| 3 | Reactions at the real 30 seconds | off | 6 | 5 |
| 4 | Pins | off | 4 | 5 |
| 5 | Dev mode switch and panel | on and off | 14 | 12 |
| 6 | Archive, delete, keep and protection | on, debounce 2s | 28 | 27 |
| 7 | Timers and dev tools | on, speed 1x then 60x | 16 | 16 |
| 8 | Pomodoro | on, speed 60x then 1x | 14 | 13 |
| 9 | Lab tour and restarts | on, then off (restart) | 13 | 27 |
| 10 | Rest of the lab | off | 8 | 8 |
| 11 | Phone notifications | off | 5 | 11 |
| 12 | Overnight backups | off | 2 | 2 nights |
| 14 | Bugs and kept confirmations | off (two restarts) | 16 | 21 |
| 15 | Dev database and clock | `--dev`, on and off (three restarts) | 10 | 13 |
| 17 | Traces: `dev why` and bug reports | `--dev`, off (one restart) | 3 | 5 |
| 18 | Retest: one path for every message | `--dev`, off (one restart) | 9 | 12 |
| 21 | Pills: the daily checklist | `--dev`, off (two restarts) | 13 | 20 |
| 22 | Channel reset, housekeeping that leaves no trace, and button colours | `--dev`, off then on (two restarts) | 8 | 15 |
| 23 | Retest: the main pill, late at night | `--dev`, off (one restart) | 7 | 12 |
| 24 | Small backlog batch: identity, #commands, mock-ups, the reset card | live, off (two restarts) | 9 | 15 |
| 25 | Retest: the `task-check` fixes (a guessed pill, replies, plain refusals, 12-hour times) | `--dev`, off (one restart) | 6 | 12 |
| | **Total** | | **191** (F2 is split over blocks 4 and 7, counted in 7) | **about 3¼ hours** |

Blocks 14 to 23 need nothing from the others (19 and 20, the first pills blocks, passed on 2026-10-10 and are no longer here) (13 and 16 tested the old way of asking Claude, which is gone): run them any time after
block 1, and before the overnight block if that suits.

**Tonight:** `docs/QA-TONIGHT.md` is one ordered run of every block
that is waiting (27 to 42), with as few restarts as it can have. The
blocks below keep the full wording.

## Before you start

- **Run a test copy, not the service**, so restarts are quick. Terminal as
  Admin: `nssm stop assistant-bot`. Leave the bot stopped; block 1 starts it.
- **`.env`:** `REACTION_DEBOUNCE=30`, `CONFIRMATION_SECONDS=5`,
  `POMO_AUTO_CONTINUE=false`, `KEEP_CONFIRMATIONS=false` (the expected
  results assume confirmations tidy themselves away; block 14 switches it
  on at the end), and `ARCHIVE_CHANNEL_ID`, `REMINDERS_CHANNEL_ID`,
  `GYM_CHANNEL_ID`, `ADMIN_CHANNEL_ID`, `DEV_CHANNEL_ID` and
  `BUGS_CHANNEL_ID` all set.
- **#bugs** is a forum channel where the bot may Create Posts, Send
  Messages in Threads, Manage Threads and Manage Channels (the last only
  to make its tags).
- **Discord on the desktop** with #inbox, #bot-log and #archive to hand.
- **The scratch channel:** the one set as `DEV_CHANNEL_ID` in `.env`. Called
  **#scratch** below. Ordinary messages there don't go to Claude, so they
  make clean targets.
- **Also needed:** an image and a small file (D2), a second Discord account
  in the server (K3, otherwise skip it), and your phone for block 11.
- **Marking:** tick the Tests column as you go, then report to Claude Code,
  e.g. `A1 pass, A2 fail: reply came twice, K3 skip: no second account`.
- "Log card" means a card in #bot-log. "Within 5 seconds" confirmations
  delete themselves.
- **If you want to see everything that was sent**, `dev cleanup off` stops
  all automatic deletion until `dev cleanup on` or `dev off`. Leave it on
  for this sheet: the expected results assume the normal tidying.

## 1. Start-up

**As soon as the bot is up:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode: off (it always is after a start).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | In the project folder: `python main.py` | "👋 Online and ready" in #inbox; "🟢 Bot started" log card listing tasks and synced slash commands, no ⚠️ fields | K1 |
| 2 | In a second terminal: `python main.py` | It logs "Another copy of the bot is already running (PID …)" and exits. Step 1 of block 2 then gets one reply, not two | K2 |
| 3 | From the second account: type `ping` in #inbox and react 📦 on any message. Wait 35 seconds | No reply, no archive, nothing from Claude. Remove that 📦 afterwards | K3 |

## 2. Builtin words and chat

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode: off. In #inbox unless it says otherwise.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `ping` | "🏓 Pong!" stays; your `ping` is deleted; log card | A1 |
| 2 | `stats`, then `stat` | All-time stats card stays each time; your word is deleted | A2 |
| 3 | `help` | What works in #inbox, grouped by task, including Dev | A3 |
| 4 | `buttons`, tap one | Button test message appears and answers the tap | A11 |
| 5 | `My test word is kiwifruit.` then `What was my test word?` | Both answered; the second says kiwifruit; "Message handled" log card with tokens and cost | A9 |
| 6 | Reply `cancel` to Claude's last answer | Not a command: Claude answers it as chat; no ⚠️ | G13 |
| 7 | `archive` (not as a reply) | Not an action: Claude answers | D10 |
| 8 | `reset`, then `What was my test word?` | "🧹 Conversation memory cleared." for 5 seconds; Claude no longer knows | A10 |
| 9 | `timer banana` | Your message stays and gets ⚠️; the reason is only on the log card | K4 |
| 10 | Reply `delete` to that `timer banana` message | It and your reply are deleted; "🗑️ Deleted" for about 10 seconds | E1 |
| 11 | In #scratch: `ping` | Nothing: no reply, no Claude. **Leave the message there** (target for block 6) | A12 |
| 12 | Back in #inbox: `Set a timer for 5 minutes` | A 5-minute timer starts, exactly as `timer 5m` would; your message stays; Claude adds one short line. A "🔧 Tool: timer" log card as well as "Message handled". Reply `cancel` to the timer | A17 |

## 3. Reactions at the real 30 seconds

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode: off, so the debounce is the real `REACTION_DEBOUNCE`. In #scratch,
type four messages first: `one`, `two`, `three`, `keep me`.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | React 📦 on `one` and time it | Nothing for 30 seconds, then it is archived | C1 |
| 2 | Look at the copy in #archive | Your name and avatar, original time, link back; original gone | D4 |
| 3 | React 📦 on `two`, and about 5 seconds later on `three` | Both archived together, 30 seconds after the second reaction | C4 |
| 4 | React 📦 on any card in #bot-log | At once, with no 30-second wait: the card gets ⚠️, the reason shows in the channel for about 10 seconds, and there is a "Reaction refused" log card. Nothing more happens later | C6 |
| 5 | Remove your 📦 from that card | The ⚠️ is removed; nothing else happens | C12 |
| 6 | React 📌 on `keep me` and time it | Nothing for 30 seconds, then it is pinned and gets ✅; no "pinned a message" notice left behind; "📌 Reaction: keep" log card. **Leave it kept** (target for block 9) | L1 |

Leaves three archived copies in #archive (used in blocks 6 and 9) and the
kept `keep me` (used in block 9).

## 4. Pins

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode: off.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | In #scratch: `lab pin`. Note the time | Status message pinned; no "pinned a message" notice left behind | F2 (first half) |
| 2 | In #inbox: pin the "🏓 Pong!" by hand, then unpin it | The pin notice is deleted; both changes on log cards | F1, F4 |
| 3 | In #scratch: type `pin me` and pin it by hand. **Leave it pinned** (target for block 6) | The notice is deleted there too; log card | F3 |
| 4 | A minute after step 1, look at the status message, then `lab pin stop` | It was updated on the minute; `stop` unpins it; the unpin is logged | B4 |

## 5. Dev mode switch and panel

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Starts and ends with dev mode off. Watch the bot's status in
the member list.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `dev` | ⚠️ on your message; log card says dev mode is off. Delete the message by hand | J5 |
| 2 | `dev on` | Panel posted and pinned: debounce 2s, speed 1x, verbose on, quiet hours ignored, clean-up on, each against its normal value, live expiry an hour away; no pin notice; "Dev mode on" log card | J1 |
| 3 | Look at the bot's status | "🛠️ Dev mode" | J2 |
| 4 | Type `a`, then `b`, then `dev` | Panel moves to the bottom, still pinned; only one panel | J4 |
| 5 | `dev quiet on`, then `dev quiet off` | Panel shows "respected", then "ignored" | J13 |
| 6 | `dev debounce 9`, `dev verbose off`, then `dev reset` | Panel back to 2s, 1x, verbose on, ignored, with a fresh hour | J15 |
| 7 | `dev speed 5`, then on the panel: **+1 hour**, **Reset**, **Disable** | Expiry moves out an hour; speed back to 1x; then panel unpinned and deleted, status cleared, "Dev mode off" log card | J16 |
| 8 | `dev speed 10` | Dev mode switches on; panel shows 10x and the other settings at dev defaults | J6 |
| 9 | `dev off` | Panel unpinned and deleted; status cleared; "Dev mode off" log card with the reason | J3 |
| 10 | `dev expire 1m`, wait a minute | Panel shows the new expiry; then dev mode switches itself off as in step 9, reason "expired" | J14 |
| 11 | `dev cleanup off`, then `dev debounce 3` | Dev mode switches on; panel shows clean-up off; both of your words and their confirmations stay on screen | J28 (first half) |
| 12 | `dev cleanup on`, then `dev off`, then `dev off` again | Words are tidied away again as normal. The second `dev off`: "🛠️ Dev mode is already off." for 5 seconds, your word deleted, no ⚠️. Delete what step 11 left behind by hand | J28 (second half), J30 |
| 13 | `dev mode on`, then `dev mode off` | Same as `dev on` and `dev off`: the panel is posted and pinned, then unpinned and deleted, with the status and log cards as in steps 2 and 9. No "Message handled" card: Claude is not called | J32 |
| 14 | `dev status`, then `python -m core.instance_lock` in PowerShell | "🩺 **Status**": "🧪 **Dev** bot · database `dev.db`" (on live: "🟢 **Live** bot · database `assistant.db`"), "Up … · code at feature/pills @ … when it started", "Clock: … (the real time)", a "Next …" line for each kind of job, then "**Bot instances**": "1 bot is running: PID …, started … (it holds the lock)", and a "Not counted" line for the `.venv` launcher. No ⚠️ line. `python -m core.instance_lock` in PowerShell prints the same | J33 |

## 6. Archive, delete, keep and protection

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Dev mode: **`dev on`** (debounce 2s, verbose on); the steps
change the debounce where a test needs it.

Targets already there: your `ping` (block 2) and the pinned `pin me`
(block 4).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `dev on` | Panel as before | |
| 2 | Reply `archive` to your `ping` | Copy in #archive under your name and avatar, original time, link back; original and reply deleted; "📦 Archived: link" for about 10 seconds | D1 |
| 3 | Post a message with the image and the file attached; reply `archive` to it | Both attachments are on the archived copy | D2 |
| 4 | In #archive: press **Restore** on that copy | Reposted to #scratch with name, avatar, attachments and time; the archived copy is removed | D6 |
| 5 | `dev seed 6` | Six sample messages tagged "🧪 dev test data" (oat milk, weekly review, dentist, article link, car registration, gym) | |
| 6 | Reply `box` to "Buy oat milk…" | Archived like any other, though it is the bot's own message | D3, D9 |
| 7 | Reply `file away` to "Idea: a weekly review…" | Archived | D3 |
| 8 | Right-click "Dentist said…" > Apps > **Archive message** | Archived, with a private confirmation | D5 |
| 9 | In #archive: reply `dev inspect` to one of the copies | Card's "Archive record" line says where it came from and when | J18 |
| 10 | `dev debounce 0`, then react 📦 on "https://example.com…" | Panel edited in place; the message is archived at once | J7 |
| 11 | `dev debounce 5`; react 📦 on "Remember to renew…" and remove it within 5 seconds | Nothing happens | J8 |
| 12 | Still at 5 seconds: react 📌 on the same message and remove it within 5 seconds | Nothing happens: not pinned, no ✅ | L3 |
| 13 | `dev debounce 10`; react 🗑️ on the same message and remove it within 10 seconds | Nothing happens (the 30-second window, shortened) | E4 |
| 14 | `dev debounce 2`; react 🗑️ on it again and wait | Deleted after 2 seconds | E3 |
| 15 | Reply `delete` to the pinned `pin me` | "⚠️ That message is pinned. Delete it anyway?" with Confirm and Cancel; nothing deleted | E5 |
| 16 | Press **Cancel** | Question removed; message untouched | E7 (first half) |
| 17 | Right-click `pin me` > Apps > **Archive message**, then **Cancel** | Asks for confirmation first | E9 |
| 18 | Add 📌 to `pin me` and wait for its ✅ (2 seconds); reply `dev inspect` to it | Lifecycle: Protected…; Pinned: yes; Protected from clean-up: pinned; Kept: yes; "Reactions on it" lists 📌 and ✅; Reactions applied: 📌; Archive record: none | J17 |
| 19 | Reply `delete` to `pin me` again and **don't answer**. Note the time | Question appears | |
| 20 | Meanwhile: add 📌 to "Gym: 3 x 8 squats…" (it is pinned and gets ✅ after 2 seconds); reply `archive` to it, **Cancel**; then react 🗑️ on it, wait 2 seconds, **Cancel**. Remove the 🗑️ | Both ask for confirmation first; message untouched | E8 |
| 21 | Two minutes after step 19, look at the question | Removed by itself; `pin me` untouched | E7 (second half) |
| 22 | Reply `delete` to `pin me` once more, press **Confirm** | Message deleted; the question shows the outcome, then removes itself | E6 |
| 23 | `dev seed 3`, then `dev clean` | Three tagged samples appear, and a "🌱 Seeded 3…" line that stays (not a 5-second confirmation); clean removes them all and the `dev inspect` card. The kept "Gym…" stays | J22 |
| 24 | `dev seed 2`, pin one by hand, `dev clean` | The pinned one stays; the other goes | J23 |
| 25 | Remove your 📌 from "Gym…" and wait 2 seconds | It is unpinned and its ✅ is removed; "📌 Reaction removed: keep" log card | L2 |
| 26 | `dev seed 2`; reply `please archive this` to "Buy oat milk…" | Archived, as `archive` does | D15 |
| 27 | Reply `pin` to "Idea: a weekly review…" | Pinned at once (no wait); your reply is deleted; "📌 Pinned" for about 10 seconds; no "pinned a message" notice left behind | L9 |
| 28 | Reply `unpin` to it | Unpinned at once; "📌 Unpinned" for about 10 seconds | L11 |
| 29 | Reply `pin this` to it, then `unpin`; then `pin me`, then `unpin` | Each `pin …` pins it, as `pin` does | L10 |
| 30 | In #archive: reply `archive` to one of the copies | At once: your reply stays with ⚠️, "That message is already in the archive." shows for about 10 seconds, and there is a log card. Delete your reply by hand | D13 |
| 31 | Still in #archive: react 🗑️ on that copy, then remove the 🗑️ | At once: ⚠️ on the copy and "Messages in the archive stay there…" for about 10 seconds; nothing is deleted. Removing the 🗑️ removes the ⚠️ | E12 |
| 32 | Tidy up: unpin the one from step 24, `dev clean`; in #archive, `dev clean` | #scratch has no test data; the `dev inspect` card in #archive is gone | |
| 33 | Only if you have a channel that is at Discord's pin limit (otherwise report `L5 skip`): react 📌 on a message there. Then unpin one, take the 📌 off and add it again | The message gets ⚠️, isn't pinned and nothing is said in the channel; the log card says the channel is full and what to do. The second time it is pinned, and ✅ replaces the ⚠️ | L5 |

Leaves dev mode on, and archived copies in #archive (needed for block 9).

## 7. Timers and dev tools

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Dev mode: on, debounce 2s, verbose on, speed 1x to start.
First press **+1 hour** on the panel so it lasts through block 9.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `timers` | "No active timers" | G9 (first half) |
| 2 | `timer 10s tea` | Timer message with a live "ends in…"; your word is deleted; pinned "Active timers" board lists it; no pin notice | G1, F2 (second half) |
| 3 | Wait 10 seconds | Original edited to "finished"; a new message @mentions you with +5 min, Restart and Dismiss; board updated | G2 |
| 4 | Press **Dismiss** | Alert deleted; original stays | G3 |
| 5 | `timer 10s a`, then `timer 10s b`; let both finish. Reply `dev inspect` to a's alert | Two alerts; the inspect card's Lifecycle line says Alert, with what happens to it | J29 (first half) |
| 6 | On a's alert press **+5 min**; on b's press **Restart** | Each alert cleared; a runs for 5 minutes, b for its full 10 seconds. When b finishes, reply `ok` to its alert: alert deleted | G4, G3 |
| 7 | Reply `pause` to timer a, then `resume` | "paused with … left", then running again with the same time left | G5 |
| 8 | Reply `+10m` to it, then `extend 5m` | End time moves out by 10, then 5 more minutes | G6 |
| 9 | `timer`; then reply `dev inspect` to timer a's message | Lists timer a; the inspect card's Lifecycle line says Live | G9 (second half), J29 (second half) |
| 10 | Reply `cancel` to timer a | Marked cancelled; off the board; no alert later | G7 |
| 11 | `timer 10m`, then `dev jobs` | Pending jobs with id, task/kind and due time: the timer and the nightly backup | J19 |
| 12 | `dev fire next` | The timer finishes at once; "🔥 Fired job #…" names it. Dismiss the alert | J21 |
| 13 | `dev run backup`, then `dev run sweep` | "💾 Backup saved" log card and a new file in `data\backups\`; the sweep gets ⚠️ with "not built" on the log card. Delete the ⚠️ message by hand | J20 |
| 14 | `dev speed 60`, then `timer 5m` | Timer says 5m and finishes in about 5 seconds; a 🛠️ debug card for the job in #bot-log. Dismiss the alert | J9, J11 (job) |
| 15 | `ping` in #inbox; in #scratch `dev seed 2` and react 📦 on one | 🛠️ debug cards: the word with trigger and timing; the reaction batch with where it ended up | J11 |
| 16 | `dev verbose off`; `ping` in #inbox, react 📦 on the other seeded message, `timer 5m` | Panel shows verbose off; no 🛠️ cards for any of the three. Dismiss the alert, `dev clean` | J12 |

Step 12 only fires the timer if nothing else is pending sooner: make sure
no other timer or Pomodoro is running.

Leaves dev mode on at speed 60x, verbose off.

## 8. Pomodoro

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Dev mode: on. Speed 60x for step 2 only, then 1x, because
focus rounds only count in the stats at 1x.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `pomo stats` | Note today's figure | |
| 2 | `pomo 25/5`; let focus end; `pomo stats` | Card says 25m; phase ends in about 25 seconds; stats unchanged. Reply `ok` to the alert, press **Stop** | J10 |
| 3 | `dev speed 1` | Panel shows 1x | |
| 4 | `pomo 50/10/30 writing` | Card shows the label "writing" and the 50/10/30 lengths | H10 |
| 5 | `pomo`; then in #inbox: `pomo` | In #scratch the card is shown again at the bottom and the old one is removed, with an "Already going" note for 5 seconds; your word is deleted and the session is unchanged. In #inbox: a pointer with a link to the card for 5 seconds; the card stays in #scratch | H9, H17 |
| 6 | `pomo 25/5`; press **Cancel**; type it again and press **Confirm** | The card is shown again with one question under it: "**writing** is already going at 50m/10m/30m. Restart it as `25/5`?" (no "Already going" note as well). Cancel leaves the session alone; Confirm stops it and starts "writing" at 25/5 | H21 |
| 7 | Reply to the card: `pause`, `resume`, `+10m`, `stop` | Same as the buttons; `+10m` adds 10 minutes to the current phase; `stop` ends it | H8 |
| 8 | `pomo 30s/10s` | One card with phase, round, label, live time and Pause, Skip, Stop; listed on the board | H1 |
| 9 | Wait 30 seconds | @mention alert with Start and Skip; the break doesn't start; card says it is waiting | H2 |
| 10 | `pomo stats` | Today and this week now include that round | H11 |
| 11 | Press **Start** | Alert cleared; break running on the card | H3 |
| 12 | When the break ends, press **Start**; then **Pause**, then **Resume** | Card shows the time left while paused, then carries on | H5 |
| 13 | Press **Skip** during that focus round; `pomo stats` | Moves to the break; stats unchanged | H6 |
| 14 | Press **Stop** | "stopped after 1 focus rounds", no buttons; off the board | H7 |
| 15 | `pomo auto 30s/10s`; let focus end | The break starts by itself; alert has OK and Skip; **OK** clears it. Then **Stop** | H4 |

Leaves dev mode on at 1x, nothing running.

## 9. Lab tour and restarts

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Two restarts cover every restart test. Dev mode is on going in and is
switched off by the first restart, which is itself a test.

**Before the first restart**

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | In #inbox: `lab tour` | One card with Pass, Fail, Skip, Back and Stop | B15 |
| 2 | Tour step 1: `ping` | Step ticks itself | |
| 3 | Tour step 2: `lab buttons`; press Count, flip a toggle, use both selects, submit the Form, try the ephemeral reply | Each answers at once and the message updates in place; step ticks itself. **Leave both messages** | B2 |
| 4 | Tour step 3: `lab react`; add and remove some colours; wait 15 seconds | Message shows the final state and a timeline, then gets ✅; step ticks itself | B1 |
| 5 | Check the dev panel is still pinned in #scratch (`dev on` there if it expired) | | |
| 6 | In #scratch: `timer 2m`, then straight away stop the bot (`Ctrl + C`) and start it (`python main.py`) | Start card as in K1 | |

**After the first restart** (dev mode off)

| # | Do | Expect | Tests |
|---|---|---|---|
| 7 | Look at #scratch and the bot's status | Dev mode is off: no status, the old panel is gone. (If a panel was left behind, any button on it removes it) | J24 |
| 8 | Wait for the 2 minutes to be up; press **Dismiss** | The timer fires on time; the button works | G11 |
| 9 | Press a button on the persistent `lab buttons` message, then one on the other | Persistent one still works; the other says "⌛ That button or form no longer works" | B3 |
| 10 | In #archive: press **Restore** on a copy made before the restart | Still works: reposted to #scratch, copy removed | D7 |
| 11 | In #scratch: remove your 📌 from `keep me` (kept in block 3) and wait 30 seconds | Unpinned and its ✅ removed: what was applied before the restart is still known | L4 |
| 12 | In #inbox: `lab tour` | Carries on at step 4; the buttons still work | B16 |
| 13 | Tour step 4: reply `archive` to any message you don't need | Step ticks itself | |
| 14 | Tour step 5: react 📦 on another | Archived after the full 30 seconds (the normal debounce is back, which completes J24); step ticks itself | |
| 15 | Tour step 6: press **Skip**, then **Back**; then `lab pin`, wait a minute, `lab pin stop`, **Pass** | Skip and Back work; boxes tick; Pass moves on | |
| 16 | Tour step 7: `lab chart`; press **Fail** and enter a note; then **Back** and **Pass** | The note shows on the card; Back reopens the step | |
| 17 | Tour step 8: send Claude a message, then `reset` | Step ticks itself; the card becomes a summary, also posted to #bot-log | B15 |

**Second restart: three minutes of downtime**

| # | Do | Expect | Tests |
|---|---|---|---|
| 18 | In #scratch: type `offline`, then `timer 1m`, then `pomo auto 1m/30s`. Stop the bot (`Ctrl + C`) | | |
| 19 | While it is stopped: react 📦 on `offline`. Optional: set `ASSISTANT_NAME=Marvin` in `.env` (for step 23). Wait 3 minutes. Start the bot | | |
| 20 | Look at #scratch | Timer alert says it finished while the bot was offline | G12 |
| 21 | Look at the Pomodoro | Alert says the phase ended while offline; the next phase waits for **Start**, even though it is auto | H12 |
| 22 | Wait 35 seconds, look at `offline` | Not archived. Remove the 📦, dismiss the alert, **Stop** the session | C8 |
| 23 | Only if you set the name in step 19 (otherwise report `K10 skip`): in #inbox, `buttons` and press **Wave**; ask Claude its name | "👋 Hello from Marvin!"; Claude says Marvin. Put `.env` back afterwards (it takes effect at the next start) | K10 |

## 10. Rest of the lab

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Dev mode: off. Each is one word and a look.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `lab time` | Every dynamic timestamp style, in local time | B8 |
| 2 | `lab thread` | A message with a thread started on it and a first message inside | B9 |
| 3 | `lab poll`, then `lab poll multiple` | Native polls; the second allows several answers | B10 |
| 4 | `lab file` | A CSV of daily stats is attached | B11 |
| 5 | `lab format` | Markdown, spoilers and ANSI colours render; the long message is split cleanly | B12 |
| 6 | `lab layout` | Components v2 layout renders (containers, sections, thumbnails) | B13 |
| 7 | `lab countdown 30 1` | Counts down by editing itself; summary reports edits and any rate limiting | B14 |
| 8 | `/lab chart`, then `lab chart abc` | Slash version posts the charts with a private "done" note; the bad argument gets ⚠️ and a usage line on the log card | B18 |

## 11. Phone notifications

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode: off. **Close Discord on the desktop** (or let it go idle): Discord
holds back phone notifications while the desktop app is active. Type
everything from the phone, in #scratch.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `lab chart`, then `lab chart matplotlib 14` | Two charts each time (messages per day, cost per day), readable on the phone | B5 |
| 2 | `lab notify all` | Normal, silent, @mention and DM arrive in that order, 5 seconds apart; the DM is a short pointer with a link back | B6 |
| 3 | `lab notify mention delay 30`, lock the phone | Answered at once; about 30 seconds later the @mention arrives and the phone notifies | B7 |
| 4 | `lab channels delay 30`, then `lab channels` again straight away; lock the phone; then reply with anything in #reminders, #gym, #admin and #inbox | The second says a channel test is already running (for 5 seconds), with no ⚠️. One test message per channel: normal, @mention, silent, and a link to the #reminders one. Each reply gets ✅; one results card with response times appears in #scratch | B17, B21 |

## 12. Overnight backups

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Two separate nights. Dev mode: off.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Night one: leave the bot running past 3am NZ. Check in the morning | "💾 Backup saved" log card naming the database copy and the specs zip; the newest 7 `assistant-*.db` and `specs-*.zip` kept in `data\backups\` | K5 |
| 2 | Night two: stop the bot before 3am, start it in the morning | The missed backup runs at startup, with its own log card | K6 |

## 14. Bugs and kept confirmations

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Dev mode off. "The post" is the bug's post in #bugs. Each 🐞 or `bug` makes
a real post: close them as you go (steps 10 to 12) or afterwards.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Ask Claude `Set a timer for 5 minutes`, then react 🐞 to the timer's message | At once, with no 30-second wait: "🐞 Logged as B<n>" in the channel, and it stays. B<n> is a link that opens the post. No ✅ is added to the message | P12 |
| 2 | Open that post | Title "B<n> · ⏱️ …"; tag Open; the timer's message quoted with a jump link; the messages before it; "That turn" with your request, the tool call and a Timings line; "Related errors"; the commit; then the three questions. **Fixed** and **Won't fix** buttons under the first message | P13 |
| 3 | Take the 🐞 off, then add it again | Taking it off does nothing. Adding it again: "🐞 Already logged as B<n>", and no second post. Cancel the timer | P14 |
| 4 | Reply `bug` to another message | Your reply is deleted; "🐞 Logged as B<n>" stays; the post is about the message you replied to | P15 |
| 5 | In #scratch, send a message, then type `bug` | Your `bug` is deleted; the post is about the message before it, from #scratch | P16 |
| 6 | In #inbox, type `bug: the timer was wrong` | Not a command: it goes to Claude as chat, and no bug is logged | P17 |
| 7 | In step 1's post, answer the questions in two messages, watching the opening card | Each message gets ✅ and stays. The bot says nothing, and #bot-log has no "Message handled" card. The card's foot goes from "📝 No notes yet" to "📝 1 note", then "📝 2 notes", edited in place (no new message from the bot) | P18, P29 |
| 8 | React 🐞 to one of your messages in that post | ⚠️ on it at once and "That is already in a bug's post…"; no new bug. Take the 🐞 off | P23 |
| 9 | In #inbox, type `bugs`; then `bugs export`, open `docs/BUGS.md` and run `git status` | "Open bugs (3)", one line each with a link, where it came from, the date and the number of notes; it stays. The file has every open bug in full with its notes, and git does not list it | P19, P20 |
| 10 | Press **Won't fix** on step 5's post, then type `bugs` | On the opening card the two buttons become one **Re-open** button and the foot reads "🚫 Won't fix · <time>, <date>". "✅ B<n> closed as Won't fix" in the post; the tag changes from Open; the post is archived (closed); `bugs` no longer lists it | P21 |
| 11 | Press **Re-open** on that post, then type `bugs`. Press **Won't fix** again | The post is open again (no longer archived) with the tag Open; the card has **Fixed** and **Won't fix** back and its foot reads "🟢 Open · <time>, <date>"; "🔄 B<n> re-opened" in the post; `bugs` lists it again | P28 |
| 12 | Delete the forum's Fixed tag (Edit Channel, Tags). Restart the bot (`Ctrl + C`, `python main.py`). Look at the forum's tags, then press **Fixed** on step 4's post and **Re-open** on step 5's | The tag is back. Without Manage Channels: one error card in #bot-log, naming that permission and the missing tags. Both buttons from before the restart work: the first is closed as Fixed, tagged and archived, with Re-open on its card; the second is open again | P24, P22 |
| 13 | Set `KEEP_CONFIRMATIONS=true` in `.env` (or remove the line) and restart. Reply `pin` to a message, and react 📦 to a message in #archive | "📌 Pinned" stays in the channel and your `pin` is still deleted; the ⚠️ reason for the 📦 stays too. Reply `unpin` afterwards, and press Fixed or Won't fix on step 1's post | M5 |

## 15. Dev database and clock

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Stop the bot first (`Ctrl + C`). Steps 2 to 10 run on the dev database, so
nothing here touches your real history. `dev verbose` on helps for step 8.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Start the bot normally (`python main.py`): `dev clock`, `dev clock +1h`, `dev reset-db`. Stop it again | The first shows the real time and says it can only be moved on the dev database; the other two get ⚠️, with the reason on the log card; nothing changes and no question is asked | J43 |
| 2 | Start it with `python main.py --dev` | "👋 Online and ready… · 🧪 **DEV DATABASE**" in #inbox; the bot's status reads "🧪 DEV DATABASE"; the start card's Database field says `dev.db (DEV DATABASE)`; `stats` shows the dev database's own (empty at first) totals | J36 |
| 3 | `dev on` | The panel has a "🧪 **DEV DATABASE** · `dev.db`" line and a "Clock: … (the real time)" line; the status reads "🛠️ Dev mode · 🧪 DEV DATABASE" | J37 |
| 4 | `timer 30m`, then `dev clock +1h` | "🕰️ Clock: … (1h ahead)"; the timer finishes at once with its alert; the panel's Clock line shows 1h ahead; `dev clock` alone shows the same. Dismiss the alert | J38 |
| 5 | `dev clock 6`, then `dev clock 6am` | The first gets ⚠️ ("6am or 6pm?" on the log card) and the clock stays; the second moves to the next 6:00 am, later than where it was | J39 |
| 6 | `dev off`, then `Ctrl + C` and `python main.py --dev` again, then `dev clock` | The clock is still as far ahead as before, through both; the start card has a Clock field | J40 |
| 7 | `dev clock reset` | "🕰️ Clock: … (the real time)" | J41 |
| 8 | `dev jobs`, then `dev clock 11:59pm`, `dev clock +2m`, `dev jobs` | First: a `core/day_rollover` job due at the coming midnight. After the two moves: it has run (a 🛠️ job card in #bot-log if verbose is on) and the next one is booked for the midnight after | Q7 |
| 9 | In #inbox say `set a timer for 1 minute`, then type `dev cost` | A card that stays: "## 💰 Cost · `dev.db`"; **Today** with the cost, the number of messages and how many went to Claude; the averages per message; a line counting messages by route (`shortcut`, `button`, `tools` with its cost); **This month** the same; "Most expensive task this month: **timers**"; the tokens and requests of the month | J44 |
| 10 | `timer 10m`, then `dev reset-db`; press **Cancel**; again, press **Confirm** | Cancel: nothing changes (`timers` still lists it). Confirm: "🧹 `dev.db` wiped…"; `timers` and `stats` are empty; `dev jobs` shows only the backup and the day rollover; the clock is the real time. Delete the orphaned timer message by hand, then `dev off` and stop the bot | J42 |

## 17. Traces: `dev why` and bug reports

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), in #inbox, dev mode off.
Restart the bot first: it adds a column to the message log.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add butter`; then, pressing nothing, `and jam`. Type `dev why`, then `dev why 3`. Press nothing | One block in a code box that can be copied whole: "#<n> · <time> · chat · ok", "said: and jam", "route: follow-up (card … is open and the message sticks to it…)", "router: not asked", an "extraction:" line with what came back, "python:" lines for each check (sticky, correction, restatement, merge), "card before:" and "card after:", "shown:", and "cost: US$… · 1 request(s)". `dev why 3` posts three blocks, oldest first; the `dev why` words themselves are never among them | J47 |
| 2 | React 🐞 to the card the bot posted; open the new post in #bugs. Then press **Cancel** on the card | The post in #bugs has a **Trace** section between "That turn" and "Related errors": the same block `dev why` shows for the message of mine that the card answered | P31 |
| 3 | Type `dev cost` | The card ends with "-# List context sent to extraction this month: … of … lines over … messages, … (at most 20 a task a message)" | J48 |

## 18. Retest: one path for every message

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), in #inbox, dev mode off.
Restart the bot first. The old way of asking Claude is gone, and so are
the demo shopping and packing lists: these steps use pills and timers.
Every step ends by saying what to press. If a result looks wrong, reply
to your message with `dev why` and paste the block when you report it.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add iron at 8pm`; press **Save**. Then say `my pills`; then reply to `my pills` with `dev why`. Press nothing more | The pills list itself ("## 💊 Pills" and Iron), with no buttons and no words about it. The `dev why` block reads "route: shortcut (the message is just the name of pills…)", "router: not asked" and "cost: US$0.0000 · 0 request(s)" | S46 |
| 2 | Say `which pills do I take?`. Press nothing | The same list, from the bot's own code: not a sentence about your pills, and no "want to add anything?" after it | S47 |
| 3 | Say `what's the capital of France?`; then reply to it with `dev why`. Press nothing | A plain answer that ends with the answer: no offer, no "anything else?". The block reads "route: chat" and "router: chat", with a router and a chat request in the cost line | S48 |
| 4 | Say `shopping is boring`; then `that was quick`. Press nothing | No reply to either. The 👀 appears and goes, and nothing is left on the messages | S42 |
| 5 | Say `set a timer for 5 minutes called tea`; then `how long is left on tea?`; then `my timers`; then `cancel it`. Press nothing | The timer's own message; then the "Your timers" list (not a sentence from Claude); the list again for `my timers`, at no cost; then tea is cancelled at once, said in one line | S49 |
| 6 | Type `pills`; then say `pause iron`; press **Save** | The word shows the same read-only list: no dropdown and no buttons. After Save ("⏸️ **Iron** paused.") that list moves Iron under "⏸️ Paused", edited in place | S50 |
| 7 | Say `add zinc to my pills`; then, pressing nothing, `and magnesium`; press **Cancel** | One card with zinc and magnesium, and no "Not included" line | S52 |
| 8 | Say `add milk to the shopping list`. Press nothing | No shopping card: the demo lists are no longer part of the bot. A short plain answer, "🤔 I didn't understand that.", or nothing; never a card and never "added" | S51 |
| 9 | On a fresh `dev.db`, or replying to a message sent before the last `dev reset-db`: reply to it with `dev why 5`. Press nothing | One plain line: "🔎 Nothing is logged for that message: it is from before this database was started…". No ⚠️ on your message | S44 |

## 21. Pills: the daily checklist

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off, with
`HUB_CHANNEL_ID` set in `.env` to a channel the bot can post in. Type in
#inbox unless a step says the hub. The pills table gains one more table
when the bot starts. The steps move the dev clock: it only goes forward,
so run them in order, and `dev clock reset` afterwards. Nothing notifies
you in this block: reminders are the next stage. Every step ends by
saying what to press.

After the `dev clock reset` above, type `dev clock` and `dev jobs` once:
the clock should read the real time, with `core/day_rollover` due at the
coming midnight and `pills/checklist` at the next 6:00 am. (On
2026-10-10 the clock was still a day ahead from an earlier run when the
bot started, and both were booked a day late; the reset now books them
again.)

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Restart the bot. Say `remove pill A`; press **Remove** (skip this if there is no Pill A). Then say `add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm, without food`; press **Save** | One card, "💊 Pills · new", with two lines: "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm`" and "At least 3h apart · not after `4:00 pm` · *without food*". No ❓ and no ⚠️. Save: "✅ Saved · 💊 **Pill A** · …" | R40 |
| 2 | Make sure there is a pill with no time: say `add zinc to my pills`; **Save** (skip if Zinc is there). Then `dev clock 5:59am`, then `dev clock +2m`. Press nothing | Today's checklist appears in the hub without a notification: "## 💊 Pills · ▱▱▱▱▱ 0 of N", the doses with no time first, then the timed ones by time. Under it, one message with **Taken** and **Skip** for each dose with no time, and none for a timed dose | R1 |
| 3 | Type something in the hub, then type `pills` there. Then type `pills` in #inbox | A fresh copy of the checklist at the bottom of the hub, with its Taken / Skip messages under it; the old checklist and its messages are gone. Typed in #inbox instead: the same, and "💊 Today's checklist is in #hub" where you typed | R48 |
| 4 | Say `I've taken my Zinc today`. Press nothing; then reply to your message with `dev why` | Never silence: "✅ **Zinc** · taken <time> · …", and Zinc is ticked off on the checklist. The `dev why` block shows it went to pills (if the router said nothing needed doing, a line says the message names 'Zinc') | R50 |
| 5 | Say `add magnesium and copper to my pills`; press **Save** | The checklist gains "💊 **Copper**" and "💊 **Magnesium**" and the total goes up by two, edited in place; a Taken / Skip message for each appears under it | R49 |
| 6 | Press **Taken** on Magnesium's message | That message is deleted. The checklist is edited in place: the dose shows ✅ and "taken" with the time, and the bar moves. No new checklist | R2 |
| 7 | Press **Skip** on Copper's message | The message is deleted; the checklist shows ⏭️ … skipped, and it counts in the bar | R4 |
| 8 | `dev clock 9:00am`. Say `add course A to my pills, 3 times a day, at least 3 hours apart`; press **Save**. Then say `had course A at 8:12`. Then say `I didn't take course A` | After Save the checklist shows Course A three times, dose 1 with no time (and its own message) and doses 2 and 3 "after dose …". Then "✅ **Course A** (dose 1 of 3) · taken 8:12 am · still to take today: … (dose 2 of 3) `11:12 am` …", and the checklist shows dose 2 at `11:12 am`. Then "↩️ **Course A** (dose 1 of 3) · no longer ticked off · …": dose 1 is pending again, with its Taken / Skip message back | R51 |
| 9 | Say `took my course A` (so that one dose is ticked off). Then say `pause copper`; press **Save**. Then say `my pills` | Dose 1 of Course A is ✅. Copper's line leaves the checklist and the count, and Copper is under "### ⏸️ Paused" (it was skipped, so it has no message to delete). `my pills` is the read-only list of every pill, with Copper under ⏸️ Paused | R23, S50 |
| 10 | Say `took my pill A`. Press nothing | "✅ **Pill A** (dose 1 of 3) · taken 9:0… am · still to take today: …" with dose 2 at the later of `11:30 am` and three hours after the time taken. (A timed dose has no buttons yet: that comes with reminders) | R3 |
| 11 | Restart the bot (still `--dev`); type `dev jobs`. Then say `took my pill A` again | No second checklist and no second set of messages in the hub. `dev jobs` shows one `pills/checklist` job, for the next 6:00 am. The second dose of Pill A is ticked off on the same checklist message | R27 |
| 12 | `dev clock 11:59pm`, then `dev clock +2m`. Look at the hub; then `dev clock 6:00am` | The untouched doses show ❌ missed on yesterday's checklist, which is otherwise left as it was; their own messages are deleted. `dev clock 6:00am` then posts a fresh checklist for the new day, everything pending | R26 |

## 22. Channel reset, housekeeping that leaves no trace, and button colours

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off unless a step
says otherwise. Restart the bot first. **Use a test channel for steps 1
to 3**: everything in it is deleted, and it can't be undone. Step 4 is in
the hub, so run it only where the hub is a test channel too. Put a dozen
messages in the test channel first, pin one by hand and react 📌 to
another (wait for its ✅). Every step ends by saying what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | In a test channel with a dozen messages, one of them pinned and one marked 📌: type `reset channel`. Then press **Cancel** | Your word is deleted and a card appears: "🧹 Channel · reset", "N messages in #channel, 2 of them pinned or 📌", "⚠️ This can't be undone", with **Delete all** (red), **Delete all unpinned** and **Cancel**. Nothing is deleted. Cancel removes the card: with your word already gone, nothing of the question is left. (Asked in plain words in #inbox, `reset this channel`, Cancel deletes that message of yours too) | U4 |
| 2 | Type `reset channel` again; press **Delete all unpinned** | The card shows "🧹 Deleting N messages…", then everything goes except the pinned and the 📌 message. \"🧹 Channel reset: N messages deleted · a copy was saved\" (it goes after 10 seconds, also while `KEEP_CONFIRMATIONS` is on), and a "🧹 Channel reset" card in #bot-log saying 2 were kept and naming the copy. In `data\exports\` there is a `<channel>-<date>-<time>.txt` with every message that was there, oldest first, the pinned and 📌 ones marked | U5 |
| 3 | Type `reset channel` once more; press **Delete all** | Every message goes, the pinned and the 📌 one too. The closing line and the #bot-log card as before, with nothing kept | U6 |
| 4 | In the hub, with today's checklist posted (`pills`), a timer running (`timer 10m tea`) and dev mode on there (`dev on`): say `reset this channel`; press **Delete all**. Then press **Taken** on a pill's message, and reply `cancel` to the tea timer | The card, then everything goes. Afterwards, once each and nothing twice: today's checklist with its Taken / Skip messages, the tea timer's card, the pinned "Active timers" board and the pinned dev panel. Taken ticks the pill off on the new checklist; `cancel` cancels the timer on its new card | U7 |
| 5 | Only if you can change the bot's role (otherwise report `U8 skip`): take Manage Messages away from it in a test channel; type `reset channel` there. Give the permission back | A card that says "⚠️ I can't reset #channel: my role needs **Manage Messages** in this channel. Nothing was deleted." with **Cancel** only. No ⚠️ on your message and nothing in the channel is touched | U8 |
| 6 | With `KEEP_CONFIRMATIONS` on (the default; restart after setting it): send `a`, `b` and `c`. Reply `pin` to `a`, then `unpin`. Reply `archive` to `b`. Reply `delete` to `c`. Wait 15 seconds after each | Each time: one short line ("📌 Pinned", "📌 Unpinned", "📦 Archived: link", "🗑️ Deleted") that is gone after about 10 seconds, though confirmations are kept; your reply word is deleted; a card in #bot-log for each. Afterwards nothing in the channel says any of it happened | M7 |
| 7 | Reply `pin` to a message, and within 5 seconds stop the bot (Ctrl + C). Wait 20 seconds, then start it again | "📌 Pinned" is still there while the bot is off, and is deleted within a few seconds of it starting: a restart doesn't leave the line behind | M8 |
| 8 | Look at the buttons as you go: say `add zinc to my pills` (don't press); say `remove zinc` on a saved pill (don't press); type `pills` in the hub; let a timer finish (`timer 10s tea`); in a test channel with nothing pinned or 📌, type `reset channel` | **Save** is green and **Cancel** grey with ↩️. **Remove** is red. **Taken** is green and **Skip** blurple. On the timer's alert **+5 min**, **Restart** and **Dismiss** are all blurple: nothing but Cancel is grey anywhere. The reset card has **Delete all** (red) and **Cancel** only: no "Delete all unpinned" when nothing is pinned or 📌 | Q14 |

## 23. Retest: the main pill, late at night

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off, with the hub
set. Restart the bot first. The steps move the dev clock forward, so run
them in order. "Pill A" stands for your main pill: use the same times.
Every step ends by saying what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | With `--dev`: `dev clock reset`. Make sure the main pill is there (say `add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm`; **Save**). `dev clock 10:57pm`. Type `pills`. Then say `Taken my pill A`; press **Log it** | The checklist shows the three doses ❌ missed, with no times. Then a card "💊 Pills · change": "**Pill A** (dose 1 of 3) · taken 10:57 pm" and "⚠️ That's after the latest time, 4:00 pm. Log it anyway?", with **Log it** (green) and **Cancel**. Log it: "✅ **Pill A** (dose 1 of 3) · taken 10:57 pm · nothing left to take today": no dose promised for 1:57 am. On the checklist dose 1 is ✅ and doses 2 and 3 read "⏭️ … skipped automatically: not enough time before 4:00 pm" | R56 |
| 2 | Straight after: say `I took it at 9am`. Then reply to that message of yours with `dev why`. Then say `it was 9:15am actually`. Press nothing | No "Which pill?", no refusal, and never an answer like "Got it": "✏️ **Pill A** (dose 1 of 3) · taken 10:57 pm → 9:00 am · nothing left to take today". The `dev why` block says the message went to pills first because pills had just answered, with "router: not asked" and one request. Then "✏️ … taken 9:00 am → 9:15 am · …". The checklist shows dose 1 taken 9:15 am, dose 2 ❌ missed (it was due after noon) and dose 3 still skipped automatically | R57 |
| 3 | `dev clock 9:00am` (the next day: a new checklist is posted on the way). Say `took my pill A`. Then `dev clock 12:40pm`, look; `dev clock 1:05pm`, look; `dev clock 4:02pm`, look. Press nothing | Dose 1 ✅ 9:00 am, dose 2 `12:00 pm`, dose 3 `3:00 pm`. At 12:40 pm nothing has moved: dose 2 still `12:00 pm`, dose 3 still `3:00 pm`. At 1:05 pm dose 3 is ⏭️ skipped automatically (dose 2 can no longer be in time for it); dose 2 still `12:00 pm`. At 4:02 pm dose 2 is ❌ missed, changed by the bot without your asking | R58 |
| 4 | Say `I took pill A at 8:30am`. Press nothing | "✏️ **Pill A** (dose 1 of 3) · taken 9:00 am → 8:30 am · …": a time earlier than the dose last taken puts that dose right, and is not a second dose | R59 |
| 5 | Say `I took dose 2 of pill A at 12:15pm`. Then `I took dose 1 of pill A at 8:45am`. Press nothing | "✅ **Pill A** (dose 2 of 3) · taken 12:15 pm · …" (it was ❌ missed). Then "✏️ **Pill A** (dose 1 of 3) · taken 8:30 am → 8:45 am · …": dose 1, not dose 2, and no "Not included" line | R61 |
| 6 | Say `I took dose 1 of pill A at 12:15pm`. Press **Cancel** | A card: "**Pill A** (dose 1 of 3) · taken 8:45 am → 12:15 pm" and "⚠️ That's the same time as dose 2, taken 12:15 pm. Log it anyway?", with **Log it** and **Cancel**. After Cancel the checklist still shows dose 1 taken 8:45 am | R62 |
| 7 | Say `I went for a run at 7 this morning`. Then `shopping is boring`. Then `dev clock reset` | "I can't log that yet." to the first: no "Got it", and not silence. No reply at all to the second | S57 |

## 24. Small backlog batch, on the live bot

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the **live** bot, dev mode off. Before you start: make a #commands
channel that only the bot can write in, put its id in `.env` as
`COMMANDS_CHANNEL_ID`, and restart the service on this code. Use a test
channel for step 5. Nothing here changes a pill or a dose. Every step
ends by saying what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Look at the bot in the member list, now and five minutes later. Press nothing | Its nickname is its base name, with no "· DEV". Its status reads "🟢 Live · up 0m · next: …" naming the next job and its time, and a few minutes later the uptime has moved on | K19 |
| 2 | Read #commands. Then restart the service once more and look again. Press nothing | One message a task (Builtin, Bugs, Pills, Timers), then Housekeeping, Dev and Lab; pills are only ever "Pill A" and "Pill B". #bot-log has "📖 #commands updated". After the second restart nothing in the channel changed and there is no second card | K21 |
| 3 | In #inbox: type `pills`. Wait 15 seconds. Press nothing | The checklist is posted in the hub. In #inbox "💊 Today's checklist is in #hub." appears and is gone within about 10 seconds; your word is deleted; nothing is left | M10 |
| 4 | `timer 5m tea`; say `how long is left on tea?`. Reply `pause` to the timer; ask again. Then reply `cancel` to it | "⏱️ **tea** · 4m 18s left" (minutes and seconds, no list posted). Paused: "⏸️ **tea** · paused with 4m 5s left", the same words as the first line of the timer's card | G23 |
| 5 | In a test channel: type `pomo` and don't press Start. Type `reset channel`; press **Cancel**. Then press **Stop** on the session | The card has "♻️ Posted again afterwards:" and "• Active timers: Pomodoro waiting to start" above "⚠️ This can't be undone". After Cancel nothing changed | U10 |
| 6 | Type `dev mock`. Then `dev mock checklist-v2`, and press **Taken** on it. Then `dev mock reset-card-v2` and `dev mock confirm-card-v2` | The list names `checklist-v2`, `confirm-card-v2` and `reset-card-v2`. Each sketch is posted as one message with boxed sections, an accent colour down the side, headings, small text and coloured buttons; your word is deleted. A button answers "🧪 Mock-up: this button does nothing yet." to you alone, and nothing changes | J51 |
| 7 | Type `dev mock nothing`. Press nothing | "🧪 There is no mock-up called `nothing`." with the list of the ones there are; nothing else is posted | J52 |
| 8 | Tomorrow morning: look at "💾 Backup saved" in #bot-log, and at the bot's status. Press nothing | The card lists `assistant-….db`, `specs-….zip` and, if a channel was ever reset, `exports-….zip`. The status is "🟢 Live · …", not a ⚠️ line | K22 |
| 9 | Only when you next run the dev database (otherwise report `K20 skip`): `python main.py --dev`; look at the bot. `dev clock +13h`; look again. Stop it and start the live bot | The dev bot has its own plain name (no "· DEV") and the status "🧪 DEV database"; after the clock moves, "🧪 DEV database · clock +13h". Live's name does not change | K20 |

## 25. Retest: the `task-check` fixes

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off, with the hub
set. Restart the bot first. Set up two pills with no set time: say `add
pill X once a day` and press **Save**, then `add pill Y once a day` and
press **Save**. Type `pills`. (That a timer which didn't save is never
confirmed can't be shown from Discord: it is covered by the unit tests.)
Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `took the usual one`. Press **Cancel** (with two pills never logged it asks which pill instead: that passes too) | Never ticked off at once. A card "💊 Pills · change" with the dose and ❓, **Save** and **Cancel**; after Cancel the checklist is unchanged | R66 |
| 2 | Say `took my pill X`. Then reply to **Pill Y**'s Taken / Skip message with `took it`; then reply `dev why` to that reply of yours. Press nothing | "✅ **Pill X** · taken …", then "✅ **Pill Y** · taken …": the pill whose message you replied to, not the one logged just before. The trace says "reply to pills' message: it goes to pills first", with no router request | R67 |
| 3 | `timer 10m tea`; say `give tea more time`. Press nothing | Either a plain line that ends "Say how much time to add, e.g. 10 minutes.", or the time is added with the amount it guessed marked ❓ ("❓ I guessed how much time to add."). Never `duration`, "tell the user" or an id like t12 | G25 |
| 4 | Look at the tea timer's message; type `pomo` and look at its card. Press **Stop**, and reply `cancel` to the tea timer | "ends in 9 minutes (8:04 pm)" and "Ends in 25 minutes (8:19 pm)": the time in brackets is 12-hour with am or pm, whatever your Discord is set to | G26 |
| 5 | React 🐞 to any message; open the post in #bugs and write `a note`. Press nothing. Then `dev clock reset` | No ✅ on your note and no reply; the count on the post's opening card goes up by one. The card's first line gives the time as "8:04 pm, 12 Oct" | P34 |
| 6 | `timer 10m tea`, then `timer 10m eggs`; send three other messages; then reply to the **tea** timer's message with `give it 2 more`. Then reply `dev why` to that reply of yours. Reply `cancel` to both timers | Tea gets 2 more minutes, eggs is untouched. The trace says "reply to timers' message: it goes to timers first" and shows no router request | S59 |

## 26. Retest: a reply to a line about a timer, and "which timer?"

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the live bot or the dev database, after a restart (it adds one table).
Dev mode off. Start three timers: `timer 10m tea`, `timer 10m dinner`,
`timer 10m eggs`. Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `pause the dinner timer`, then `give eggs 1 more`. Reply to the line "⏸️ Paused: dinner …" with `Give it 2 more`; then reply `dev why` to that reply of yours. Press nothing | "➕ Added 2m to dinner" (with or without "❓ I guessed how much time to add."); tea and eggs are untouched. The trace says "reply to timers' message: it goes to timers first" and shows no router request | G29 |
| 2 | Say `pause everything`, then `resume everything`, then `give it 2 more`. Press nothing | "⚠️ Which timer? Say its name." with a line for tea, dinner and eggs. No timer changes | G30 |
| 3 | Reply to the **tea** timer's own message with `pause this`; then, with no reply, say `give it 5 more minutes`. Press nothing | Tea is paused, then tea gets 5 more minutes: "it" is the timer the last line was about | T23, T3 |
| 4 | Say `cancel it`. Then `cancel all my timers` and press the red **Cancel 2 timers**. Then `dev clock reset` | Tea is cancelled at once, with no card. Then a card for the other two, and both are cancelled | T5 |

## 27. "It" after the bot's latest message (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off. Every step
says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `timer 10s tea`, then `timer 10m eggs`. When tea's alert rings, say `give it 5 more`. Press nothing | Tea runs again for 5 minutes ("➕ tea: 5m more"); eggs is untouched | G31 |
| 2 | Say `pause everything`, then `resume it`. Press nothing. Then reply `cancel` to both timers | "⚠️ Which timer? Say its name." with a line for each: the line before was about both | G30 |

## 28. An unnamed pill needs an anchor (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), dev mode off, with the hub
set and two pills with no set time (say `add pill X once a day`, press
**Save**; `add pill Y once a day`, press **Save**). Type `pills`. Every
step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `took my pill X`. Then `dev clock +10m`. Say `took the usual one`; press **Save** | "✅ **Pill X** · taken …" at once. Ten minutes on, a card "💊 Pills · change" with "**Pill Y** · taken … ❓", **Save** and **Cancel**: Pill Y is the one with a dose left. Save ticks it off | R69 |
| 2 | Straight after, say `no I didn't`. Press nothing. Then `dev clock reset` | "↩️ **Pill Y** · no longer ticked off", at once and with no card: the bot's last pills message was about Pill Y | R69 |

## 29. A reply to a line about a pill (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, after a restart (it adds one table), dev mode off,
with the two pills of block 28 and nothing ticked off (`dev clock +1d`
gives a fresh day). Type `pills`. Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `took my pill X`, then `took my pill Y`. Reply to the line "✅ **Pill X** · taken …" with `it was 8am`. Press nothing | "✏️ **Pill X** · taken … → 8:00 am": Pill X's dose is corrected, not Pill Y's, and there is no card | R71 |
| 2 | Reply to that same "✅ **Pill X** …" line with `actually I didn't`; then reply `dev why` to that reply of yours. Then `dev clock reset` | "↩️ **Pill X** · no longer ticked off". The trace says "reply to pills' message: it goes to pills first" and shows no router request | R71 |

## 30. `dev why` and "it" (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `timer 10m tea`; say `give it 2 more`; reply `dev why` to that message of yours. Then reply `cancel` to the timer | The extraction line reads `timers · timer_change {"which":"it","action":"extend","duration":"2m"}`: the action's name is there and "which" is not empty. Nothing about an "internal label" appears in #bot-log or the log | J54 |

## 31. The last two timer lines (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `set a timer for a few minutes called tea`, then `timer 10m eggs`. Reply to the line "❓ I guessed the length: …" with `give it 2 more`; then reply `dev why` to that reply of yours | Tea gets 2 more minutes, eggs is untouched. The trace says "reply to timers' message: it goes to timers first" and shows no router request | G32 |
| 2 | Say `cancel all my timers`; press the red **Cancel 2 timers** | "🚫 **Cancelled 2**" naming tea and eggs | G32 |

## 32. Bugs: a Live list (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Every step says what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `show my open bugs` and keep it in view. React 🐞 to any message of yours. Press nothing | "🐞 Logged as B<n>" with its link; the list above gains that bug by itself, with no new list posted | P36 |
| 2 | Open that bug's post in #bugs and press **Won't fix** | Back in the channel, the list has lost that bug again | P36 |
| 3 | Say `add pill  ZINC` (two spaces, capitals) with a pill called Zinc already there; press **Cancel** if a card shows | Zinc as it is, or a change card for Zinc: never a second pill called ZINC | R72 |

## 33. Reminder mock-ups (waiting for QA)

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

## 34. Taking a setting away, and a bug logged twice (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. You need a pill with a time and a
note: say `add Testpill at 8am with food` and press **Save**.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `Testpill no longer needs a time`. Press **Save** | A change card for Testpill with `schedule · daily at 8:00 am → daily, any time`. After Save, `pills` shows it with no time | R74 |
| 2 | Say `Testpill doesn't need to be with food any more`. Press **Save** | A change card with `notes · with food → none`. After Save the note is gone | R74 |
| 3 | React 🐞 to any message of yours. Take the 🐞 off, then put it on again. Then open the bug's post and press **Won't fix** | "🐞 Logged as B<n>", then "🐞 Already logged as B<n>" with the same link: one bug, not two | P37 |
| 4 | Say `remove Testpill`. Press **Remove** | Testpill is gone | |

## 35. Gym mock-ups (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. These are sketches: the buttons only
say they are mock-ups, and nothing of gym is built. The spec is
`docs/specs/gym.md`; its questions are at the top of `docs/STATUS.md`.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev mock gym-import-v2` | A card "🏋️ Gym · new": three workouts with their exercises a line each, which column was read as what (one marked ❓), the columns not used, **Save** and **Cancel** | J56 |
| 2 | Type `dev mock gym-change-v2` | A card "🏋️ Gym · change": only what differs, as `field · old → new`, ➕ for a new exercise and ➖ for one gone | J56 |
| 3 | Type `dev mock gym-workout-v1` | Today's workout: a group an exercise with its sets as dots, the plan, what is logged, last time's sets, and the buttons on the exercise you are on | J56 |
| 4 | Type `dev mock gym-logged-set-v2` | The line said after a set is logged, and that exercise's group as it then stands | J56 |

Say what to change in any of them, and answer the gym questions in
`docs/STATUS.md` (or in the spec, section 16).

## 36. Restarts (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev` in a terminal, with the
service's own bot left alone: stop the dev bot with Ctrl+C). Dev mode
off. You need one pill: say `add Testpill` and press **Save** if you
have none.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Otherpill`. Don't press. Stop the bot (Ctrl+C) and start it again. Look at #bot-log | "🟢 Bot started" and no "🔁 Caught up after a restart": nothing was missed. (If the bot was off for over a minute while a line was waiting to be tidied away, one naming `tidy` is right) | K24 |
| 2 | Press **Save** on the Otherpill card from before the restart | Saved: `pills` lists Otherpill. The card worked although the bot restarted | K24 |
| 3 | Type `pills`. Stop and start the bot. Press **Taken** under the checklist for Testpill | The same checklist as before the restart (no second one), and Testpill is ticked off on it | K24 |
| 4 | Type `dev clock 5:58am`. Stop the bot, wait four minutes, start it | One new checklist in the hub. In #bot-log one "🔁 Caught up after a restart" saying the checklist was posted and the bot was off at 6:00 am, and the jobs that ran late. No "Pills checklist not posted" message | K24 |
| 5 | Stop and start the bot once more | No new checklist, no "🔁 Caught up" message and no "Pills checklist not posted": #bot-log has only "🟢 Bot started" | K24 |
| 6 | Type `dev clock reset`; say `remove Otherpill`, press **Remove** | The clock is the real time again and Otherpill is gone | |

## 37. Questions on the card (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Testiron to my pills at 8` | A card: "💊 Pills · new", "**Testiron** · daily at ❔", "Is that 8 in the morning or the evening?", and the buttons **8:00 am**, **8:00 pm** (blurple) and **Cancel**. No Save | S61 |
| 2 | Press **8:00 pm** | The same card now reads "daily at `8:00 pm`" with **Save** and **Cancel** | S61 |
| 3 | Say `actually make it 8am`. Press **Save** | A fresh card replaces it with `8:00 am`; Save saves it | S61 |
| 4 | Say `add Testmag to my pills, twice a day at 8am`. Then say `9pm`. Press **Save** | A card with "2× daily", a ❔ line about the one time, "What time is the other dose?" and the button **8:00 pm**. After `9pm` a fresh card with `8:00 am`, `9:00 pm` and Save | S61 |
| 5 | Say `add Testvit C and Testvit D to my pills`, press **Save**. Say `pause testvit`. Press **Testvit C**, then **Cancel** | A card asking "Which one is “testvit”?" with a button for each. After the press: the pause card for Testvit C with Save. Cancel removes it | R76 |
| 6 | Type `pills`. Wait six minutes, then say `took it`. Press a pill | A card "Which pill?" with a button for each pill still to take. After the press the card says it was ticked off, and the checklist shows it | R76 |
| 7 | Say `remove testiron, testmag, testvit c and testvit d`, press **Remove** | They are gone | |

## 38. Pill reminders (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

Reminders are off unless switched on. For this block start the dev bot
with them on, in PowerShell (the service's own bot is left alone):
`$env:REMINDERS_ENABLED = "true"; python main.py --dev`. Dev mode off.
Have your phone locked beside you for step 2. The clock is moved with
`dev clock`; each move runs whatever came due.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Testrem to my pills at 3pm and 9pm, at least 4 hours apart, with food`. Press **Save**. Type `dev clock 2:59pm` | Nothing yet: no message about Testrem beyond the card and the checklist | R78 |
| 2 | Type `dev clock 3:00pm`. Look at the lock screen, then at the hub | The lock screen says "💊 Routine due · 3:00 pm" and nothing about Testrem. In the hub the message reads: that line, "**Testrem** · dose 1 of 2", "Due `3:00 pm`", "with food", and **Taken**, **Taken at…**, **Snooze 15m**, **Skip** | R78 |
| 3 | Press **Snooze 15m**. Type `dev clock 3:15pm` | The message gains "Snoozed until 3:15 pm". After the move a fresh message takes its place (the old one is gone) and the phone buzzes again with the same neutral line | R78 |
| 4 | Press **Taken at…**, type `3:05pm`, submit | The message goes; the checklist shows Testrem dose 1 taken 3:05 pm, and dose 2 at `9:00 pm` | R78 |
| 5 | Type `dev clock 9:00pm`, then `dev clock 9:15pm`, `dev clock 9:30pm`, `dev clock 9:45pm` | A prompt at 9:00 pm, then three more, each replacing the last: "reminder 1 of 3", "2 of 3", "3 of 3", with a line saying when the next comes. Only ever one message for the dose | R78 |
| 6 | Type `dev clock 10:00pm` | The message goes and the checklist shows ❌ Testrem (dose 2 of 2) · missed | R78 |
| 7 | Say `took testrem`; look, then press **Log it** | A card that asks first: "⚠️ Dose 2 was missed (due 9:00 pm). Log it as taken now?" with **Log it** and **Cancel**, and nothing ticked off yet. After Log it: "taken 10:00 pm" | R78, R85 |
| 8 | Say `add Testgap to my pills at 3pm and 9pm, at least 4 hours apart`, **Save**. Type `dev clock 3:00pm` (the next day's), press **Taken**. Type `dev clock 9:00pm`. On the 9:00 pm reminder press **Taken at…**, type `5pm`, submit | A card in the hub: "💊 Pills · change", "**Testgap** (dose 2 of 2) · taken 5:00 pm", "⚠️ That's 2h after dose 1, taken 3:00 pm. The gap is at least 4h. Log it anyway?", with **Log it** and **Cancel**. Nothing is ticked off yet and the reminder is still there | R78 |
| 9 | Press **Cancel** on that card. Then **Taken at…** again, `5pm`, and this time **Log it** | After Cancel: the card goes, the reminder stays. After Log it: the card says dose 2 was taken 5:00 pm, the reminder goes and the checklist shows it | R78 |
| 10 | Say `remove testrem and testgap`, press **Remove**; type `dev clock reset`; stop the dev bot | Gone; the clock is the real time | |
| 11 | Only if you want to see it: start the dev bot with reminders on and `HUB_CHANNEL_ID` taken out of `.env` for that run, then put it back | #bot-log says once "💊 Pill reminders can't be sent": reminders are on and the hub can't be found. No reminder is sent anywhere else | R78 |

To switch reminders on for the live bot: add `REMINDERS_ENABLED=true`
to `.env` and restart the service. To switch them off again: remove
the line (or set it to false) and restart; any reminder that is up is
removed.

## 39. The design pass (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off, on your phone as well as the desktop
(and in dark and light themes if you use both). These are sketches: the
buttons only say they are mock-ups. The style guide is `docs/DESIGN.md`.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev mock checklist-v2` | A heading and the date, then a box an item: amber (due, with its buttons), blue (any time, still to take), green (taken), red (missed), grey (skipped by the bot), a separator, and Paused | J57 |
| 2 | Lock your phone and type `dev mock reminder-v1-first` from the desktop; then `dev mock reminder-v1` | The lock screen shows "💊 Routine due · 11:12 am" for the first. The second is that line with an amber box under it naming the pill, with four buttons. Say what the lock screen showed for each | J57 |
| 3 | Type `dev mock confirm-card-v2`, then `dev mock question-card-v1` | A blurple box: two pills with `field · old → new`, ❓ on the guesses, Save and Cancel. Then a card that asks, with **8:00 am**, **8:00 pm** and **Cancel**, and no Save | J57 |
| 4 | Type `dev mock reset-card-v2`, then `dev mock gym-workout-v1` | A red box for the reset. Then a workout: green (done), amber (the exercise you are on, with its buttons), grey (to come), and Finish | J57 |

| 5 | Type `dev mock too-soon-v2` | An amber box: "💊 Pills · change", the dose and its time, a ⚠️ line saying why, "**Log it anyway?**", **Log it** and **Cancel** | J57 |
| 6 | Look at the colours on your phone, in each theme you use: amber, blue, green, red, grey and blurple | Each can be told from the others, and each status still has its mark and its words. Say which, if any, to change | J57 |

The colours chosen so far (any time and still to take is blue; a card
that asks first because something is risky is amber) are not final
until step 6 is done. The other redrawn sketches are in blocks 33 and
35. Say what to change in any of them, or in the style guide.

## 40. Core pieces for any task (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Nothing here should look different
from before: naming a pill now goes through the core.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Testiron and Testiron forte to my pills, once a day`, press **Save**. Then say `I took testiron` | The first is logged: the whole name wins over part of one | S62 |
| 2 | Say `skip forte` | Testiron forte is skipped: part of a name finds it when only one fits | S62 |
| 3 | Say `pause testir` | A card that asks which one, with a button for each of the two pills, and no Save | S62 |
| 4 | Press **Cancel**. Send a picture or any file with the words `what is this` | An ordinary answer from chat, as before: the file changes nothing yet | S64 |
| 5 | Say `remove testiron and testiron forte`, press **Remove** | Both gone | |

## 41. The new look, switched on (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Put `CARDS_V2=true` and
`REMINDERS_ENABLED=true` in `.env` and start the dev bot. Do block 39
(the sketches and the colours on your phone) before this one.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Testa to my pills at 8am, 11:30am and 3pm, at least 3 hours apart, not after 4pm, with food`, press **Save**. Before pressing, look at the card | A blurple box: "💊 Pills · new", a line under it, the pill's line, then **Save** and **Cancel** inside the box, and "or tell me what to change" in small text under it | S65 |
| 2 | Say `add Testb twice a day at 8`. Press nothing yet | A blurple box that ends with the question in bold and a button for each answer, **Cancel**, and no Save. Press **Cancel** | S65 |
| 3 | Say `add Testany once a day`, **Save**. Type `dev clock 7:55am` then `pills` | One message: "💊 Today · 0 of 4 taken" and the date, then a box a pill: Testa amber with "Due"/"Next" and **Taken**, **Taken at…**, **Skip**; Testany blue, "any time", with the same three buttons. No separate message for Testany | R79 |
| 4 | Lock your phone. Type `dev clock 8:00am` | The lock screen shows only "💊 Routine due · 8:00 am". In the hub: that line with an amber box under it naming Testa, with four buttons | R80 |
| 5 | On the checklist (not the reminder), press **Taken** in Testa's box | The checklist stays where it is and is rewritten: Testa shows "✅ dose 1 · 8:00 am" and "**Next:** dose 2"; the reminder goes | R79 |
| 6 | Press **Taken** in Testa's box again straight away | An amber box: "💊 Pills · change", the dose, "⚠️ That's … after dose 1 … Log it anyway?", **Log it** and **Cancel**. Nothing is ticked off. Press **Cancel** | R79, S65 |
| 7 | Press **Skip** in Testany's box | Testany's box turns grey with "⏭️ skipped" and has no buttons | R79 |
| 8 | Say `remove testa and testany`, press **Remove**. Type `dev clock reset`. Stop the dev bot, take `CARDS_V2` out of `.env` (or set it to false) and start it; type `pills` | Everything is the old look again: a plain checklist, plain cards | J59, J60 |

## 42. The daily spend line (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database. Steps 2 and 3 send two messages to Claude (about
one cent in all): skip them if you'd rather not.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev cost` | Under "Today", a small line: "US$… of today's US$0.50 limit (…%)" | J61 |
| 2 | Stop the dev bot, put `DAILY_SPEND_LIMIT=0.001` in `.env`, start it. Say `what pills do I have?` | The answer as usual, and one card in #bot-log: "💰 Claude spend is over today's limit", with what was spent and the limit | K25 |
| 3 | Say `what pills do I have?` again, then type `dev cost` | No second card in #bot-log. `dev cost` shows "⚠️ over today's limit: US$… of US$0.00 (DAILY_SPEND_LIMIT)" | K25, J61 |
| 4 | Stop the dev bot and take `DAILY_SPEND_LIMIT` out of `.env` again | | |

## 43. `took <pill>` (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. You need a pill with no set time:
say `add Testzinc once a day` and press **Save**.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `took testzinc`. Press nothing | At once: "✅ **Testzinc** · taken …", your message stays, and the checklist shows it. `dev cost` afterwards shows no new message to Claude | R81 |
| 2 | Type `took testzinc` again | An ordinary answer in the bot's usual words that it is already taken: nothing is left today, so this one went to Claude as before | R81 |
| 3 | Say `add Testgap at 8am and 11am, at least 3 hours apart`, **Save**. Type `took testgap`, then at once `took testgap` again. Press **Cancel** | The first is ticked off. The second gives the card "⚠️ That's … after dose 1 … Log it anyway?" with **Log it** and **Cancel**; nothing more is ticked off | R81 |
| 4 | Say `remove testzinc and testgap`, press **Remove** | Gone | |

## 44. Sketches: briefing, schedule, tidy (waiting for QA)

In the dev channel, on either database. Nothing here is built: these
are sketches posted by `dev mock`, and their answers are the questions
at the top of `docs/STATUS.md`.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `dev mock briefing-v2` | "☀️ Today" with the date (no "as of": it is kept up to date in place); an amber Pills box with the count, the next dose and a line about yesterday; grey placeholder boxes for Gym, Calendar and To-dos; no buttons | J62 |
| 2 | Type `dev mock schedule-list-v2` | "🗓️ My schedule": the morning routine in amber with its three steps (tidy, briefing, checklist), where it posts, silent, its next and last run; a grey box for a second schedule; Paused under a separator; small lines for the bot's own and for pill times; no buttons | J62 |
| 3 | Type `dev mock schedule-change-v1` | A blurple card "🗓️ Schedule · change": two schedules, each `field · old → new`, ❓ on the guess, when each next runs, **Save** and **Cancel** | J62 |
| 4 | Type `dev mock cleanup-v1` | What #bot-log would be told when a tidy went wrong: a channel a box, what was removed, kept and left, and why. Its last line says a tidy with nothing wrong posts nothing | J62 |

## 45. After the self-test: names, "just now", the reset card (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, dev mode off. Steps 1 to 3 send about four
messages to Claude (two cents).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Say `add Testvit and Testvit forte to my pills, once a day`, **Save**. Say `took my testvit`, then at once `pause testv` | Testvit is ticked off (the whole name wins). Then a card "Which one is “testv”?" with **Testvit**, **Testvit forte** and **Cancel**, and no Save | R84, S67, S68 |
| 2 | Press **Testvit forte**, then **Cancel** | The card becomes the pause card for Testvit forte, with Save: it is not asked again. Cancel removes it | R84 |
| 3 | Say `add Testgap at 8am and 11am, at least 3 hours apart`, **Save**. Type `took testgap`, then at once `took testgap` again. Press **Cancel** | The second gives "⚠️ That's just now: dose 1 was taken …. The gap is at least 3h." and "Log it anyway?"; never "0m after" | R83, S68 |
| 4 | With `CARDS_V2=true` (stop the dev bot, `$env:CARDS_V2 = "true"; python main.py --dev`): type `reset channel` in #inbox, look, press **Cancel** | A red box: "🧹 Channel · reset", the channel in small text, the count in bold, "⚠️ **This can't be undone**", and **Delete all** (red) and **Cancel** inside it | L14, S68 |
| 5 | Say `remove testvit, testvit forte and testgap`, **Remove**. Stop the dev bot and take `CARDS_V2` out again (`Remove-Item Env:CARDS_V2`) | Gone | |

The catch-up card's wording (a job named in words, no "pills/…") is
checked by the self-test's step 2.01 and by `tests/test_restart.py`:
there is nothing to do by hand.

## 46. The scheduler, stage 1: nothing should look different (waiting for QA)

On the live bot, over a day. There is nothing new to see; this is the
check that nothing went missing. The self-test runs the same on the dev
clock.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Look at the hub the morning after the restart | Today's checklist, posted at 6:00 am, once | K29 |
| 2 | Look at #bot-log the same morning | "💾 Backup saved" from 3:00 am, once. No "🔁 Caught up" unless the bot really was off | K29 |
| 3 | Type `dev jobs` | Pending: the nightly backup, the end of the day and the pills checklist, each once, each "for" its local time. Then "Last run of each", with ✅ and a line | J68 |
| 4 | Look at the bot's status line | "🟢 Live · up … · next: …" naming the next job in words, as before | K29 |

## 47. My schedule (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database. About six messages to Claude (three cents).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `my schedule` | "🗓️ My schedule": Pills checklist, every day at 6:00 am, #hub, silent, its next run and its last; a small line for the bot's own (end of the day, nightly backup) | S70 |
| 2 | Say `also post the pills checklist at 6 pm`, look, **Save** | A card "🗓️ Schedule · new": **Evening pills checklist**, every day at 6:00 pm, where and when next, "also every day at 6:00 am". After Save the list from step 1 gains it by itself | S71 |
| 3 | Say `move the evening checklist to 6:30pm and only on weekdays`, **Save** | A change card: `time · 6:00 pm → 6:30 pm`, `days · every day → Mon to Fri`, and "Next after this: …" | S71 |
| 4 | Say `pause the evening checklist until Monday`, **Save**; look at the list | `paused · no → until Mon …`; the list shows it under ⏸️ Paused | S71 |
| 5 | Say `move the checklist to 7`. Press **Cancel** | A card asking "Which one is “checklist”?" with a button for each of the two, and no Save | S71 |
| 6 | Say `move the backup to 4am` | One line: the nightly backup is the bot's own and isn't changed here | S71 |
| 7 | Say `remove the evening checklist`, **Remove** | Gone from the list; the 6:00 am one is as it was | S71 |
| 8 | With `CARDS_V2=true`: type `my schedule` | The same list drawn: a box a schedule, the next to run amber, no buttons. Compare with `dev mock schedule-list-v2` | S72 |

## 48. The briefing (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, started with the briefing on:
`$env:BRIEFING_ENABLED = "true"; python main.py --dev`. You need a pill
or two (`add Testbrief once a day`, **Save**). One message to Claude.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `my schedule` | "Morning routine", every day at 6:00 am, with "1. briefing" and "2. pills checklist" | S73 |
| 2 | Type `brief me` in #inbox | "☀️ Today", the date, a Pills section: the count, the next dose if one has a time, "to take any time", and yesterday's line if there was anything yesterday. No buttons | S73 |
| 3 | Type `brief me` in the hub, twice | The first posts it there. The second posts nothing: a line "The briefing above is up to date." that goes after about ten seconds | S73 |
| 4 | Type `took testbrief` | The briefing in the hub changes by itself: one more taken. No new message | S73 |
| 5 | `dev clock 5:59am`, then `dev clock 6:00am` | A new briefing, then the checklist under it, with no notification; the old briefing is gone; "Yesterday: 1 of 1 taken" | S73 |
| 6 | Say `what's on today?` in #inbox | The briefing again, there | S73 |
| 7 | With `CARDS_V2=true` as well: `brief me` in #inbox. Compare with `dev mock briefing-v2` | A box a task in the colour of its status; nothing says "as of" | S74 |
| 8 | Stop the dev bot, `Remove-Item Env:BRIEFING_ENABLED`, start it, type `my schedule` | "Pills checklist" again, alone; no briefing is posted the next morning | S73 |

## 49. A clean hub (waiting for QA)

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database, started with both on:
`$env:BRIEFING_ENABLED = "true"; $env:HUB_TIDY = "true"; python main.py --dev`.
You need a pill with no time (`add Testtidy once a day`, **Save**) and
today's checklist in the hub (`pills`).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Type `my schedule` | The morning routine has three steps: 1. morning tidy, 2. briefing, 3. pills checklist | K31 |
| 2 | In the hub, type `took testtidy`. Wait a little over two minutes | "✅ **Testtidy** · taken …" appears; then your message and that line both go by themselves, with nothing said. The checklist and the briefing stay | K31 |
| 3 | In the hub, say `add Testcard once a day`. Wait three minutes. Then press **Cancel** | The card stays while it is open, however long. On Cancel the card and your message go at once | K31 |
| 4 | Say the same again, press **Save**. Wait two minutes | Your message goes at once; the "✅ Saved" line stays two minutes, then goes. `pills` shows Testcard | K31 |
| 5 | In the hub, type `took testcard`, and pin the bot's reply within two minutes | After two minutes your message is gone and the pinned reply is still there | K31 |
| 6 | In #inbox, type `took testtidy` on a day it is still to take (or any dose) | Nothing goes after two minutes there | K31 |
| 7 | `dev clock 5:59am`, then `dev clock 6:00am` | Yesterday's checklist and briefing go; today's briefing, then today's checklist. Yesterday's "✅ … taken" line in #inbox is gone. Nothing in #bot-log about it | K31 |
| 8 | Look in `data\exports` on the PC | A file `tidy-<hub's name>-<date>.txt` with what was removed | K31 |
| 9 | Stop the dev bot, remove both settings (`Remove-Item Env:BRIEFING_ENABLED, Env:HUB_TIDY`), start it | Nothing is tidied any more; `my schedule` shows "Pills checklist" alone | K31 |

## 50. Messages sent while live was off (waiting for QA)

On live. It needs live to have been running on this code for at least
a minute before it is stopped.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | In a Terminal as Admin: `nssm stop assistant-bot`. In #inbox type `took <a pill>` and, a little later, `what is the capital of Peru`. In the hub type `pills`. Then `nssm start assistant-bot` | Nothing is answered while it is off. On start, under what you wrote in each channel, a card a message: "📭 **I was offline when you sent this** · `<time>` · the message", your words quoted, **▶️ Handle it now** and **↩️ Ignore**. No dose is logged and nothing is answered yet | R86 |
| 2 | Press **Handle it now** on the `took` card | The card goes, and the dose is logged as if you had just typed it (or its card asks first, if it is now late) | R86 |
| 3 | Press **Ignore** on the question's card | The card goes. Nothing else happens | R86 |
| 4 | Leave the hub's card. `nssm restart assistant-bot` | No second card for `pills`: the one that is there still works. Press **Handle it now**: the checklist is shown | R86 |
| 5 | Type something in #selftest-inbox | Live does not answer: that channel is the dev bot's | R87 |

## When you finish

- Stop the test copy (`Ctrl + C`) and check nothing is left running:
  `python -m core.instance_lock` ("No bot is running")
- Start the service (Terminal as Admin): `nssm start assistant-bot`
- Report the results to Claude Code so `docs/TESTING.md` gets updated.
