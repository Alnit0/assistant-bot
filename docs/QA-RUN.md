# QA run sheet

One pass through 177 of the 208 👤 Manual tests in `docs/TESTING.md` that are
⬜ Untested (as of 2026-10-10); the other 31 are for pills stages not built yet
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
| 19 | Pills: one schedule model | `--dev`, off (one restart) | 11 | 13 |
| 20 | Retest: a pill that is already there, and list names | `--dev`, off (one restart) | 3 | 4 |
| | **Total** | | **177** (F2 is split over blocks 4 and 7, counted in 7) | **about 3¼ hours** |

Blocks 14 to 20 need nothing from the others (20 follows 19) (13 and 16 tested the old way of asking Claude, which is gone): run them any time after
block 1, and before the overnight block if that suits.

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
| 10 | Reply `delete` to that `timer banana` message | It and your reply are deleted; "🗑️ Deleted" for 5 seconds | E1 |
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
| 4 | React 📦 on any card in #bot-log | At once, with no 30-second wait: the card gets ⚠️, the reason shows in the channel for 5 seconds, and there is a "Reaction refused" log card. Nothing more happens later | C6 |
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
| 14 | `dev status`, then `python -m core.instance_lock` in PowerShell | "🩺 Bot instances": "1 bot is running: PID …, started … (it holds the lock)", and a "Not counted" line for the `.venv` launcher. No ⚠️ line. `python -m core.instance_lock` in PowerShell prints the same | J33 |

## 6. Archive, delete, keep and protection

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

In #scratch. Dev mode: **`dev on`** (debounce 2s, verbose on); the steps
change the debounce where a test needs it.

Targets already there: your `ping` (block 2) and the pinned `pin me`
(block 4).

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | `dev on` | Panel as before | |
| 2 | Reply `archive` to your `ping` | Copy in #archive under your name and avatar, original time, link back; original and reply deleted; "📦 Archived: link" for 5 seconds | D1 |
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
| 27 | Reply `pin` to "Idea: a weekly review…" | Pinned at once (no wait); your reply is deleted; "📌 Pinned" for 5 seconds; no "pinned a message" notice left behind | L9 |
| 28 | Reply `unpin` to it | Unpinned at once; "📌 Unpinned" for 5 seconds | L11 |
| 29 | Reply `pin this` to it, then `unpin`; then `pin me`, then `unpin` | Each `pin …` pins it, as `pin` does | L10 |
| 30 | In #archive: reply `archive` to one of the copies | At once: your reply stays with ⚠️, "That message is already in the archive." shows for 5 seconds, and there is a log card. Delete your reply by hand | D13 |
| 31 | Still in #archive: react 🗑️ on that copy, then remove the 🗑️ | At once: ⚠️ on the copy and "Messages in the archive stay there…" for 5 seconds; nothing is deleted. Removing the 🗑️ removes the ⚠️ | E12 |
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

## 19. Pills: one schedule model

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), in #inbox, dev mode off.
Restart the bot first: the pills table changes when it starts (a
"pre-migration" backup is taken by itself). Nothing here needs the clock
moved: the checklist and reminders are not built yet, so no dose comes
due. Every step ends by saying what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | Restart the bot, then say `my pills`. Press nothing | The bot starts with no ⚠️ on the start card. Every pill is listed with the schedule it had: a pill with no time reads "daily, any time", one with a gap "…, at least 3h apart, first dose when ready" | R39 |
| 2 | Say `add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm, without food`; press **Save** | One card, "💊 Pills · new", with two lines: "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm`" and "At least 3h apart · not after `4:00 pm` · *without food*". No ❓ and no ⚠️. Save: "✅ Saved · 💊 **Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm` · at least 3h apart · not after `4:00 pm` · *without food*" | R40 |
| 3 | Say `add pill C to my pills, 3 times a day at 8am, 11:30am and 2pm, at least 3 hours apart`; press **Cancel** | A card whose first line ends "`8:00 am`, `11:30 am`, `2:30 pm`", with "⚠️ 11:30 am to 2:00 pm is under 3h: the third dose moves to 2:30 pm". Cancel: nothing is saved | R41 |
| 4 | Say `pill A can be taken until 5pm`; press **Save**. Then `my pills` | A card "💊 Pills · change": "**Pill A**", then "schedule · … not after `4:00 pm` → … not after `5:00 pm`", the times and the gap unchanged. Save: "✅ Updated · …"; the list shows `5:00 pm` | R42 |
| 5 | Say `add course A, 3 times a day, at least 3 hours apart, with food, for 7 days starting tomorrow`; press **Cancel** | One card: "**Course A** · 3× daily, at least 3h apart, first dose when ready · *with food* · <tomorrow to six days later>". Cancel: the card goes and nothing is saved | T9 |
| 6 | Say `add iron at 8`; then, pressing nothing, `8pm`; press **Save** | A card "💊 Pills · new" with "**Iron** · daily at `8:00 am` ❓" and no question first. After "8pm" it is replaced by one with `8:00 pm` and no ❓ (one dose, not two). Save: "✅ Saved · 💊 **Iron** · daily at `8:00 pm`" | T8 |
| 7 | Say `move iron to 9pm`; press **Save** | A card "💊 Pills · change": "**Iron**", then "schedule · daily at `8:00 pm` → daily at `9:00 pm`". Save: "✅ Updated · 💊 **Iron** · daily at `9:00 pm`" | T10 |
| 8 | Say `add magnesium, 2 tablets at 9pm with food`; press **Cancel** | One card: "**magnesium** (2 tablets) · daily at `9:00 pm` · *with food*" with no ❓ anywhere: what was stated is used exactly | T26 |
| 9 | Say `show all my pills` and keep it in view; then `remove iron`; press **Remove** | The list, with no buttons. Then a card "💊 Pills · remove" with "**Iron** · … → removed" that says its history is kept; Remove: "🗑️ Removed **Iron**. Its history is kept." and the list above loses Iron, edited in place | T12 |
| 10 | Say `add pill D to my pills, at 8am and 5pm, not after 4pm`; then, pressing nothing, `not after 6pm`; press **Cancel** | A card with "**Pill D** · daily at `8:00 am`, `5:00 pm`", "Not after `4:00 pm`" and "⚠️ Pill D can't be saved yet: A dose at 5:00 pm would be after the latest time, 4:00 pm." It has **Cancel** only, no Save. After the reply it is replaced by one with "Not after `6:00 pm`", no ⚠️, and **Save** and **Cancel**. Cancel: nothing is saved | R43 |
| 11 | With Iron no longer on the list, say `add zinc to my pills`; press **Save**. Then say `pause zinc until whenever`; then, pressing nothing, `until friday`; press **Cancel** | After Save zinc is added. Then a card "💊 Pills · change" with "**Zinc** · active → paused until ❔" and "❔ until · I can't read “whenever” as a date. …". It has **Cancel** only, no Save, and there is no bare ⚠️ line in the channel. After the reply it is replaced by one with "paused until" and a date, with **Save** and **Cancel** | R44 |

## 20. Retest: a pill that is already there, and list names

**First:** type `dev clock reset` (the bot's clock is the real time again; harmless when it already is).

On the dev database (`python main.py --dev`), in #inbox, dev mode off.
Restart the bot first. Pill A is saved as in block 19, step 2 (not after
`5:00 pm` if step 4 was saved: then expect that in step 1, and step 2
changes it back to something else of your choosing). Every step ends by
saying what to press.

| # | Do | Expect | Tests |
|---|---|---|---|
| 1 | With Pill A saved as in R40: say `add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm, without food` again. Press nothing | No card and no "I didn't understand that": "💊 **Pill A** is already in your pills with these settings" with the pill's line under it. Still one Pill A in `my pills` | R45 |
| 2 | With Pill A saved: say `add pill A to my pills, not after 5pm, with food`; press **Save** | A card "💊 Pills · change": "**Pill A** · already in your pills", then "notes · without food → with food" and "schedule · … not after `4:00 pm` → … not after `5:00 pm`". Save: "✅ Updated · 💊 **Pill A** · …". Still one Pill A | R46 |
| 3 | Say `show all my pills`; reply to it with `dev why`. Then say `list my pills`, then `what are my pills?`. Press nothing more | The pills list each time, with no words about it. The `dev why` block reads "route: shortcut", "router: not asked" and "cost: US$0.0000 · 0 request(s)" | S54 |

## When you finish

- Stop the test copy (`Ctrl + C`) and check nothing is left running:
  `python -m core.instance_lock` ("No bot is running")
- Start the service (Terminal as Admin): `nssm start assistant-bot`
- Report the results to Claude Code so `docs/TESTING.md` gets updated.
