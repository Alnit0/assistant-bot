# Test tracker

Every test of the bot, grouped by feature.

**Type:**

- 🤖 **Auto**: decision logic, checked by `python -m pytest`. One row stands
  for a group of unit tests; Notes names the file in `tests/`. Claude Code
  sets the status from the latest run.
- 👤 **Manual**: Discord-facing behaviour (what appears, gets edited, pinned,
  deleted or notified), done by hand in Discord. You report the result.

**Status:** ⬜ Untested · ✅ Pass · ❌ Fail · ⏭️ Skipped

**How to report manual results:** tell Claude Code, e.g. `A1 pass, A2 fail:
reply came twice, A3 skip: no archive channel`. It updates the tables and
the summary, and copies failures into `docs/BACKLOG.md`.

**Rules:** a new feature adds its tests here: 🤖 rows for its logic (with
the unit tests), 👤 rows as ⬜ Untested for what only shows in Discord. A
change to an existing feature resets that feature's 👤 rows to ⬜ Untested;
its 🤖 rows follow the next pytest run. A 🤖 pass says the decision is
right, not that Discord shows it: the 👤 rows cover that.

## Summary

Last updated: 2026-10-07

| Group | Feature | Tests | 🤖 | 👤 | ⬜ | ✅ | ❌ | ⏭️ |
|---|---|---|---|---|---|---|---|---|
| A | Builtin words and chat | 17 | 9 | 8 | 8 | 9 | 0 | 0 |
| B | Lab | 21 | 2 | 19 | 19 | 2 | 0 | 0 |
| C | Reactions | 12 | 7 | 5 | 5 | 7 | 0 | 0 |
| D | Archive and restore | 15 | 4 | 11 | 11 | 4 | 0 | 0 |
| E | Delete and protection | 12 | 3 | 9 | 9 | 3 | 0 | 0 |
| F | Pins | 4 | 0 | 4 | 4 | 0 | 0 | 0 |
| G | Timers | 15 | 4 | 11 | 11 | 4 | 0 | 0 |
| H | Pomodoro | 18 | 5 | 13 | 13 | 5 | 0 | 0 |
| J | Dev mode | 31 | 4 | 27 | 27 | 4 | 0 | 0 |
| K | Startup and housekeeping | 10 | 3 | 7 | 7 | 3 | 0 | 0 |
| L | Keep | 12 | 4 | 8 | 8 | 4 | 0 | 0 |
| M | Message lifecycle | 3 | 3 | 0 | 0 | 3 | 0 | 0 |
| | **Total** | **170** | **48** | **122** | **122** | **48** | **0** | **0** |

Unless a test says otherwise: type in #inbox, as the owner, with dev mode
off. "Log card" means a card in #bot-log.

## A. Builtin words and chat

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| A1 | 👤 Manual | Type `ping` | "🏓 Pong!" stays; your `ping` is deleted; log card | ⬜ Untested | | |
| A2 | 👤 Manual | Type `stats` (and `stat`) | All-time stats card stays; your word is deleted | ⬜ Untested | | |
| A3 | 👤 Manual | Type `help` | List of what works in this channel, grouped by skill, including Dev | ⬜ Untested | | |
| A4 | 🤖 Auto | `help <skill>` and `help <word>` | The skill in full; one word with aliases, examples, where it works and its permission | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| A5 | 🤖 Auto | `help` outside #inbox | Lists only what works in that channel; no #inbox-only words | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| A6 | 🤖 Auto | `statss` (one-letter typo, 5+ letters) | Read as `stats`, and flagged as corrected | ✅ Pass | 2026-10-07 | `tests/test_router.py, test_registry.py` |
| A7 | 🤖 Auto | `stats please` | Not a command: the whole message must be the phrase | ✅ Pass | 2026-10-07 | `tests/test_router.py` |
| A8 | 🤖 Auto | `rest`, `resett`, `delet` | Not matched: destructive words must be spelled exactly | ✅ Pass | 2026-10-07 | `tests/test_router.py, test_registry.py` |
| A9 | 👤 Manual | Send Claude a message, then a follow-up that relies on it | Both answered; the second shows it remembers; "Message handled" log card with tokens and cost | ⬜ Untested | | |
| A10 | 👤 Manual | Type `reset`, then ask Claude what you said before | "🧹 Conversation memory cleared." for 5 seconds; Claude no longer remembers | ⬜ Untested | | |
| A11 | 👤 Manual | Type `buttons` and tap one | Button test message appears and answers the tap | ⬜ Untested | | |
| A12 | 👤 Manual | Type `ping` in a channel other than #inbox | Nothing happens (no reply, no Claude) | ⬜ Untested | | |
| A13 | 🤖 Auto | `help me write an email` | Not a help request: goes to Claude | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| A14 | 🤖 Auto | Long replies, embed fields and cost estimates | Split at line breaks within 2000 characters; long fields cut with …; cost per million tokens, "Unknown" for an unpriced model | ✅ Pass | 2026-10-07 | `tests/test_text.py` |
| A15 | 🤖 Auto | Conversation memory per channel | `reset` clears only the channel it is typed in | ✅ Pass | 2026-10-07 | `tests/test_text.py` |
| A16 | 🤖 Auto | Claude's instructions | Named from `ASSISTANT_NAME` (default Hive); include the registry's list; always say it has no tools, can't act and must never offer to | ✅ Pass | 2026-10-07 | `tests/test_text.py` |
| A17 | 👤 Manual | Ask Claude: `Set a timer for 5 minutes` | It doesn't claim or offer to do it: it tells you to type `timer 5m`. No timer starts | ⬜ Untested | |  |

## B. Lab

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| B1 | 👤 Manual | `lab react`, add and remove some colours, wait 15 seconds | Message shows the final state and a timeline, then gets ✅ | ⬜ Untested | | |
| B2 | 👤 Manual | `lab buttons`: Count, a toggle, both selects, the Form, the ephemeral reply | Each answers at once and the message updates in place | ⬜ Untested | | |
| B3 | 👤 Manual | Restart the bot, press a button on the persistent `lab buttons` message | Still works; the non-persistent message says "⌛ That button or form no longer works" | ⬜ Untested | | |
| B4 | 👤 Manual | `lab pin`, wait a minute, `lab pin stop` | Status message pinned and updated each minute; `stop` unpins it; pin changes logged | ⬜ Untested | | |
| B5 | 👤 Manual | `lab chart`, then `lab chart matplotlib 14` | Two charts each time (messages per day, cost per day), readable on a phone | ⬜ Untested | | |
| B6 | 👤 Manual | `lab notify all` | Normal, silent, @mention and DM arrive in that order, 5 seconds apart; the DM is a short pointer with a link back | ⬜ Untested | | |
| B7 | 👤 Manual | `lab notify mention delay 30`, lock the phone | Answered at once; the @mention arrives about 30 seconds later and notifies | ⬜ Untested | | |
| B8 | 👤 Manual | `lab time` | Every dynamic timestamp style, in local time | ⬜ Untested | | |
| B9 | 👤 Manual | `lab thread` | A message with a thread started on it and a first message inside | ⬜ Untested | | |
| B10 | 👤 Manual | `lab poll`, then `lab poll multiple` | Native polls; the second allows several answers | ⬜ Untested | | |
| B11 | 👤 Manual | `lab file` | A CSV of daily stats is attached | ⬜ Untested | | |
| B12 | 👤 Manual | `lab format` | Markdown, spoilers and ANSI colours render; the long message is split cleanly | ⬜ Untested | | |
| B13 | 👤 Manual | `lab layout` | Components v2 layout renders (containers, sections, thumbnails) | ⬜ Untested | | |
| B14 | 👤 Manual | `lab countdown 30 1` | Message counts down by editing itself; summary reports edits and any rate limiting | ⬜ Untested | | |
| B15 | 👤 Manual | `lab tour`, work through all 8 steps | Steps tick themselves; Pass, Fail (with note), Skip and Back work; summary on the card and in #bot-log | ⬜ Untested | | |
| B16 | 👤 Manual | Start `lab tour`, restart the bot, type `lab tour` | Carries on at the same step; buttons still work | ⬜ Untested | | |
| B17 | 👤 Manual | `lab channels delay 30`, reply in each channel | One test message per channel in the right style; results card with response times | ⬜ Untested | | |
| B18 | 👤 Manual | `/lab chart`, and `lab chart abc` | Slash version does the same with a private "done" note; the bad argument gets ⚠️ and a usage line on the log card | ⬜ Untested | | |
| B19 | 🤖 Auto | Lab arguments: choices, numbers in range, `delay 90`, leftovers | Read correctly; a wrong one gives the usage line | ✅ Pass | 2026-10-07 | `tests/test_lab.py` |
| B20 | 🤖 Auto | Daily stats and the CSV | One line per day, zeros for days with nothing logged | ✅ Pass | 2026-10-07 | `tests/test_lab.py` |
| B21 | 👤 Manual | `lab channels delay 30`, then `lab channels` again straight away | The second says a channel test is already running (for 5 seconds); no ⚠️, and only one test runs | ⬜ Untested | |  |

## C. Reactions

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| C1 | 👤 Manual | React 📦 on a message and wait 30 seconds | Nothing for 30 seconds, then it is archived | ⬜ Untested | | |
| C2 | 🤖 Auto | Reaction added then removed within the quiet period | Nothing to apply, nothing to undo | ✅ Pass | 2026-10-07 | `tests/test_reactions.py` |
| C3 | 🤖 Auto | Reaction added, removed, added again | Applied once, on where it ended up | ✅ Pass | 2026-10-07 | `tests/test_reactions.py` |
| C4 | 👤 Manual | React 📦 on two messages a few seconds apart | Both handled together, 30 seconds after the last reaction | ⬜ Untested | | |
| C5 | 🤖 Auto | Someone who isn't allowed reacts 📦 | Ignored before any decision is made | ✅ Pass | 2026-10-07 | `tests/test_reaction_keys.py` |
| C6 | 👤 Manual | React 📦 on a message that can't be archived (e.g. in #bot-log) | At once, with no 30-second wait: the message gets ⚠️, the reason shows in the channel for 5 seconds, and there is a "Reaction refused" log card. Nothing more happens later | ⬜ Untested | | |
| C7 | 🤖 Auto | An emoji nothing is registered for (👍), or one that doesn't work in that channel | Ignored | ✅ Pass | 2026-10-07 | `tests/test_reaction_keys.py` |
| C8 | 👤 Manual | React 📦 while the bot is stopped, then start it | Not acted on (reactions made while off are not seen) | ⬜ Untested | | |
| C9 | 🤖 Auto | Debounce timer | One batch after the quiet period; each change restarts the wait; cancel drops the batch; a change during handling starts a new batch | ✅ Pass | 2026-10-07 | `tests/test_debounce.py, test_devmode.py` |
| C10 | 🤖 Auto | Applied reactions and undo | Removing an applied reaction undoes it; what is applied survives a restart; emoji compared without the invisible style character | ✅ Pass | 2026-10-07 | `tests/test_reactions.py` |
| C11 | 🤖 Auto | Checking a reaction the moment it is added | An invalid one is refused and never debounced; valid ones, ones with no check, unknown emoji and other people's go on as before; removing a refused one clears its ⚠️ | ✅ Pass | 2026-10-07 | `tests/test_registry.py, test_reaction_keys.py` |
| C12 | 👤 Manual | Remove the 📦 from C6 | The ⚠️ is removed; nothing else happens | ⬜ Untested | |  |

## D. Archive and restore

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| D1 | 👤 Manual | Reply `archive` to a text message | Copy in #archive under the author's name and avatar, with the original time and a link back; original and your reply deleted; "📦 Archived: link" for 5 seconds | ⬜ Untested | | |
| D2 | 👤 Manual | Reply `archive` to a message with an image and a file | Attachments are on the archived copy | ⬜ Untested | | |
| D3 | 👤 Manual | Reply `box`, and `file away` | Both archive, as `archive` does | ⬜ Untested | | |
| D4 | 👤 Manual | React 📦 and wait | Same result as D1, with no reply to clean up | ⬜ Untested | | |
| D5 | 👤 Manual | Apps > **Archive message** on a message | Same result as D1, with a private confirmation | ⬜ Untested | | |
| D6 | 👤 Manual | Press **Restore** on an archived copy | Reposted to the original channel with name, avatar, attachments and time; the archived copy is removed | ⬜ Untested | | |
| D7 | 👤 Manual | Archive a message, restart the bot, press **Restore** | Still works | ⬜ Untested | | |
| D8 | 🤖 Auto | Archive a message already in #archive, in #bot-log, with nothing to copy, or with a file too big | Refused with the reason; nothing moved | ✅ Pass | 2026-10-07 | `tests/test_archive_rules.py` |
| D9 | 👤 Manual | Reply `archive` to one of the bot's own messages | Archived like any other | ⬜ Untested | | |
| D10 | 👤 Manual | Type `archive` on its own (not as a reply) | Not an action; goes to Claude in #inbox | ⬜ Untested | | |
| D11 | 🤖 Auto | Archive record life cycle | Created, copy noted, found by original, copy or button message; restored once only; discarded if the copy fails | ✅ Pass | 2026-10-07 | `tests/test_archive_store.py` |
| D12 | 🤖 Auto | Webhook names, copied embeds, restore fallback text | "discord" and "clyde" masked, 80 characters at most; only the message's own embeds; "**Name** wrote:" within 2000 characters | ✅ Pass | 2026-10-07 | `tests/test_archive_rules.py` |
| D13 | 👤 Manual | Reply `archive` to an archived copy in #archive | At once: your reply stays with ⚠️, "That message is already in the archive." shows for 5 seconds, and there is a log card | ⬜ Untested | |  |
| D14 | 🤖 Auto | Filler words on a reply | `pin this`, `pin me`, `please archive it`, `delete this` are read as the action; `delet this` and `pin this to the wall` are not; typed words are unchanged (`ping me` is chat) | ✅ Pass | 2026-10-07 | `tests/test_router.py, test_registry.py` |
| D15 | 👤 Manual | Reply `please archive this` to a message | Archived, as `archive` does | ⬜ Untested | |  |

## E. Delete and protection

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| E1 | 👤 Manual | Reply `delete` to a message | Message and your reply deleted; "🗑️ Deleted" for 5 seconds | ⬜ Untested | | |
| E2 | 🤖 Auto | Reply `delet` | Not treated as delete (exact word) | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| E3 | 👤 Manual | React 🗑️ and wait 30 seconds | Message deleted | ⬜ Untested | | |
| E4 | 👤 Manual | React 🗑️, remove it within 30 seconds | Nothing happens | ⬜ Untested | | |
| E5 | 👤 Manual | Reply `delete` to a pinned message | "⚠️ That message is pinned. Delete it anyway?" with Confirm and Cancel; nothing deleted yet | ⬜ Untested | | |
| E6 | 👤 Manual | Press **Confirm** on that question | Message deleted; the question shows the outcome, then removes itself | ⬜ Untested | | |
| E7 | 👤 Manual | Ask again and press **Cancel**; ask again and wait two minutes | Question removed both times; message untouched | ⬜ Untested | | |
| E8 | 👤 Manual | Add 📌 to a message, then reply `archive` and react 🗑️ on it | Both ask for confirmation first (as "pinned" once the 📌 has been acted on, "marked 📌" before) | ⬜ Untested | | |
| E9 | 👤 Manual | Apps > **Archive message** on a pinned message | Asks for confirmation first | ⬜ Untested | | |
| E10 | 🤖 Auto | Protection rules | Pinned or 📌 by anyone protects; a removed 📌 doesn't | ✅ Pass | 2026-10-07 | `tests/test_reactions.py` |
| E11 | 🤖 Auto | Delete refusals and the confirmation question | Archive and #bot-log messages aren't deleted on request; the question names the reason and the action | ✅ Pass | 2026-10-07 | `tests/test_archive_rules.py` |
| E12 | 👤 Manual | React 🗑️ on an archived copy in #archive | At once: ⚠️ on the copy and "Messages in the archive stay there…" for 5 seconds; nothing is deleted. Removing the 🗑️ removes the ⚠️ | ⬜ Untested | |  |

## F. Pins

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| F1 | 👤 Manual | Pin any message by hand | Discord's "pinned a message" notice is deleted | ⬜ Untested | | |
| F2 | 👤 Manual | Let the bot pin something (`timer 1m`, `lab pin`) | The pin notice is deleted | ⬜ Untested | | |
| F3 | 👤 Manual | Pin a message in a channel other than #inbox | The notice is deleted there too | ⬜ Untested | | |
| F4 | 👤 Manual | Pin and unpin with `lab pin` running | Pin changes are logged to #bot-log | ⬜ Untested | | |

## G. Timers

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| G1 | 👤 Manual | `timer 10s tea` | Timer message with a live "ends in…" time; your word is deleted; pinned "Active timers" board lists it | ⬜ Untested | | |
| G2 | 👤 Manual | Wait for it to finish | Original edited to "finished"; a new message @mentions you with +5 min, Restart and Dismiss; board updated | ⬜ Untested | | |
| G3 | 👤 Manual | Press **Dismiss** (or reply `ok` to the alert) | Alert deleted; original stays as the record | ⬜ Untested | | |
| G4 | 👤 Manual | Press **+5 min**, and on another finished timer **Restart** | Alert cleared; timer running again for 5 minutes, or its full length | ⬜ Untested | | |
| G5 | 👤 Manual | Reply `pause`, then `resume`, to a running timer | Shows "paused with … left", then runs again with the same time left | ⬜ Untested | | |
| G6 | 👤 Manual | Reply `+10m` (and `extend 5m`) to a running timer | End time moves out by that much | ⬜ Untested | | |
| G7 | 👤 Manual | Reply `cancel` to a running timer | Marked cancelled; no alert later; removed from the board | ⬜ Untested | | |
| G8 | 🤖 Auto | Durations: `1h30`, `2 hours`, `1:30`, `25`, `90s`, `1.5h`, with a label | Each reads as the right length; the rest is the label | ✅ Pass | 2026-10-07 | `tests/test_durations.py` |
| G9 | 👤 Manual | `timer` on its own, and `timers` | Lists your active timers across channels, or "No active timers" | ⬜ Untested | | |
| G10 | 🤖 Auto | Bad durations: `banana`, `2s`, more than 24 hours | Refused with a reason (shortest is 5 seconds, longest 24 hours) | ✅ Pass | 2026-10-07 | `tests/test_durations.py` |
| G11 | 👤 Manual | Start `timer 2m`, restart the bot before it ends | Still fires on time; buttons work | ⬜ Untested | | |
| G12 | 👤 Manual | Start `timer 1m`, stop the bot for 3 minutes, start it | Alert at startup says it finished while the bot was offline | ⬜ Untested | | |
| G13 | 👤 Manual | Reply `cancel` to a message that isn't a timer | Not a command: treated as ordinary chat | ⬜ Untested | | |
| G14 | 🤖 Auto | Pause, resume and extend arithmetic | Time left is kept across pauses; extending adds to it | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |
| G15 | 🤖 Auto | Timer message and board text for each state | Running, paused, cancelled, finished; empty board says "No active timers" | ✅ Pass | 2026-10-07 | `tests/test_timer_text.py` |

## H. Pomodoro

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| H1 | 👤 Manual | `pomo 30s/10s` | One session card with phase, round, label, live time and Pause, Skip, Stop; listed on the board | ⬜ Untested | | |
| H2 | 👤 Manual | Let the focus phase end | @mention alert with Start and Skip; the break does not start by itself; card says it is waiting | ⬜ Untested | | |
| H3 | 👤 Manual | Press **Start** | Alert cleared; break running on the card | ⬜ Untested | | |
| H4 | 👤 Manual | `pomo auto 30s/10s`, let a phase end | Next phase starts by itself; alert has OK and Skip; OK clears it | ⬜ Untested | | |
| H5 | 👤 Manual | Press **Pause**, then **Resume** | Card shows the time left while paused, then carries on | ⬜ Untested | | |
| H6 | 👤 Manual | Press **Skip** during focus | Moves to the break; that focus round is not counted | ⬜ Untested | | |
| H7 | 👤 Manual | Press **Stop** | Card shows "stopped after n focus rounds", no buttons; removed from the board | ⬜ Untested | | |
| H8 | 👤 Manual | Reply `pause`, `resume`, `+10m`, `stop` to the card | Same as the buttons; `+10m` adds to the current phase | ⬜ Untested | | |
| H9 | 👤 Manual | `pomo` while a session is running (same channel) | The running session's card is shown again at the bottom and the old one is removed; "Already going" note for 5 seconds; your word is deleted; the session itself is unchanged | ⬜ Untested | | |
| H10 | 👤 Manual | `pomo 50/10/30 writing`, then stop it | Card shows the label "writing" and the custom lengths | ⬜ Untested | | |
| H11 | 👤 Manual | Complete a focus round, then `pomo stats` | Today and this week include that round | ⬜ Untested | | |
| H12 | 👤 Manual | Stop the bot during a phase until after it ends, start it | Alert says it ended while offline; the next phase waits for Start, even in auto | ⬜ Untested | | |
| H13 | 🤖 Auto | Phase order | Focus, short break, …, long break after the last round, then round 1 again; skipping follows the same order | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |
| H14 | 🤖 Auto | `pomo` arguments | `50/10`, `50/10/30`, `auto` / `manual`, units, label; bad lengths refused | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |
| H15 | 🤖 Auto | Whether the next phase starts by itself | Only in auto mode, and never after downtime | ✅ Pass | 2026-10-07 | `tests/test_timer_text.py` |
| H16 | 🤖 Auto | Focus stats | Only completed focus rounds count; NZ days; weeks start on Monday | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |
| H17 | 👤 Manual | `pomo` in another channel while a session is running | A pointer with a link to the card for 5 seconds; the card stays where it is | ⬜ Untested | |  |
| H18 | 🤖 Auto | Where an already-running session is shown | Its card again in its own channel; a pointer from anywhere else | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |

## J. Dev mode

Any channel. Check the bot's status in the member list.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| J1 | 👤 Manual | `dev on` | Panel posted and pinned with debounce 2s, speed 1x, verbose on, quiet hours ignored, clean-up on, each against its normal value, and a live expiry an hour away; no pin notice; "Dev mode on" log card | ⬜ Untested | | |
| J2 | 👤 Manual | Look at the bot's status | Shows "🛠️ Dev mode" | ⬜ Untested | | |
| J3 | 👤 Manual | `dev off` | Panel unpinned and deleted; status cleared; "Dev mode off" log card with the reason | ⬜ Untested | | |
| J4 | 👤 Manual | With dev mode on, type some messages, then `dev` | Panel moves to the bottom of the channel, still pinned; one panel only | ⬜ Untested | | |
| J5 | 👤 Manual | With dev mode off, type `dev` | ⚠️; log card says dev mode is off | ⬜ Untested | | |
| J6 | 👤 Manual | With dev mode off, `dev speed 10` | Dev mode switches on and the panel shows speed 10x, other settings at dev defaults | ⬜ Untested | | |
| J7 | 👤 Manual | `dev debounce 0`, then react 📦 on a message | Panel edited in place; the message is archived at once | ⬜ Untested | | |
| J8 | 👤 Manual | `dev debounce 5`, react 📦 and remove it within 5 seconds | Nothing happens | ⬜ Untested | | |
| J9 | 👤 Manual | `dev speed 60`, then `timer 5m` | Timer says 5m and finishes in about 5 seconds | ⬜ Untested | | |
| J10 | 👤 Manual | `dev speed 60`, `pomo 25/5`, let focus end, then `pomo stats` | Phase ends in about 25 seconds; the round is not added to the stats | ⬜ Untested | | |
| J11 | 👤 Manual | With verbose on: type `ping`, react 📦, let a timer finish | 🛠️ debug cards in #bot-log for each: trigger and timing; where the reactions ended up; the job | ⬜ Untested | | |
| J12 | 👤 Manual | `dev verbose off`, repeat J11 | No 🛠️ debug cards; panel shows verbose off | ⬜ Untested | | |
| J13 | 👤 Manual | `dev quiet on`, then `dev quiet off` | Panel shows "respected", then "ignored" (no other effect yet) | ⬜ Untested | | |
| J14 | 👤 Manual | `dev expire 1m` and wait | Panel shows the new expiry; after a minute dev mode switches itself off as in J3, reason "expired" | ⬜ Untested | | |
| J15 | 👤 Manual | `dev reset` after changing settings | Panel back to the dev defaults with a fresh hour | ⬜ Untested | | |
| J16 | 👤 Manual | Panel buttons: **+1 hour**, **Reset**, **Disable** | Expiry moves out an hour; settings reset; dev mode off as in J3 | ⬜ Untested | | |
| J17 | 👤 Manual | Add 📌 to a message, wait for its ✅, then reply `dev inspect` to it | Lifecycle: Protected…; Pinned: yes; Protected from clean-up: pinned; Kept: yes; "Reactions on it" lists 📌 and ✅; Reactions applied: 📌; Archive record: none | ⬜ Untested | | |
| J18 | 👤 Manual | Reply `dev inspect` to an archived copy in #archive | Archive record line shows where it came from and when | ⬜ Untested | | |
| J19 | 👤 Manual | `dev jobs` | Pending jobs with id, skill/kind and due time, including the nightly backup | ⬜ Untested | | |
| J20 | 👤 Manual | `dev run backup`; then `dev run sweep` | "💾 Backup saved" log card and a new file in `data/backups/`; sweep gets ⚠️ with "not built" on the log card | ⬜ Untested | | |
| J21 | 👤 Manual | `timer 10m`, then `dev fire next` | The timer finishes at once; confirmation names the job | ⬜ Untested | | |
| J22 | 👤 Manual | `dev seed 3`, then `dev clean` | Three sample messages tagged "🧪 dev test data", and a "🌱 Seeded 3…" line that stays (it is not a 5-second confirmation); clean removes them all, with any `dev inspect` / `dev jobs` output | ⬜ Untested | | |
| J23 | 👤 Manual | `dev seed 2`, pin one, `dev clean` | The pinned one stays | ⬜ Untested | | |
| J24 | 👤 Manual | `dev on`, restart the bot | Dev mode is off: normal debounce, no status; the old panel is removed at startup; a button on any panel left behind removes it | ⬜ Untested | | |
| J25 | 🤖 Auto | Dev defaults, on / off / reset, expiry | Off gives normal values; on gives 2s, 1x, verbose, quiet ignored for 1 hour; settings only count while on | ✅ Pass | 2026-10-07 | `tests/test_devmode.py` |
| J26 | 🤖 Auto | Dev setting values | `60`, `2.5`, `2s`, `60x`, `on`, `off` read correctly; out-of-range and nonsense refused with the usage, changing nothing | ✅ Pass | 2026-10-07 | `tests/test_devmode.py, test_dev_parsing.py` |
| J27 | 🤖 Auto | Speed arithmetic and `dev run` tasks | 25m at 60x is 25 real seconds, and back; unknown and unbuilt tasks refused | ✅ Pass | 2026-10-07 | `tests/test_devmode.py` |
| J28 | 👤 Manual | `dev cleanup off`, then a setting word such as `dev debounce 3`; then `dev cleanup on` | Panel shows clean-up off; your words and their confirmations stay on screen; after `dev cleanup on` they are tidied away again as normal | ⬜ Untested | |  |
| J29 | 👤 Manual | Reply `dev inspect` to a timer's alert, and to a running timer's message | The card's Lifecycle line says Alert for the first and Live for the second, each with what happens to it | ⬜ Untested | |  |
| J30 | 👤 Manual | `dev off` when dev mode is already off | "🛠️ Dev mode is already off." for 5 seconds; your word is deleted; no ⚠️ | ⬜ Untested | |  |
| J31 | 🤖 Auto | The clean-up setting | On by default and whenever dev mode is off; `dev cleanup off` stops every automatic deletion | ✅ Pass | 2026-10-07 | `tests/test_devmode.py, test_lifecycle.py` |

## K. Startup and housekeeping

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| K1 | 👤 Manual | Start the bot | "👋 Online and ready" in #inbox; "🟢 Bot started" log card listing skills and synced slash commands, with no ⚠️ fields | ⬜ Untested | | |
| K2 | 👤 Manual | Start a second copy while one is running | The second logs an error and exits; no double replies | ⬜ Untested | | |
| K3 | 👤 Manual | Have another account message the bot and react 📦 | Ignored completely | ⬜ Untested | | |
| K4 | 👤 Manual | Make a word fail (e.g. `timer banana`) | Your message stays with ⚠️; details only on the log card | ⬜ Untested | | |
| K5 | 👤 Manual | Leave the bot running past 3am NZ | "💾 Backup saved" log card; newest 7 `assistant-*.db` kept | ⬜ Untested | | |
| K6 | 👤 Manual | Stop the bot over 3am, start it later | The missed backup runs at startup | ⬜ Untested | | |
| K7 | 🤖 Auto | Permissions | Only the owner is allowed anything; someone else marked owner is demoted at startup; lookups are cached | ✅ Pass | 2026-10-07 | `tests/test_permissions.py` |
| K8 | 🤖 Auto | Registrations | Every skill loads; every word, reply action and reaction has a description, an example, a channel and a permission | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| K9 | 🤖 Auto | Scheduler | Jobs run when due, late ones at startup flagged late, interrupted ones recovered; the nightly backup books its successor | ✅ Pass | 2026-10-07 | `tests/test_scheduler.py` |
| K10 | 👤 Manual | Set `ASSISTANT_NAME=Marvin` in `.env`, restart, `buttons` and press **Wave** | "👋 Hello from Marvin!"; Claude also gives that name when asked | ⬜ Untested | | Needs a restart with the setting changed; skip otherwise |

## L. Keep

Any channel. 📌 from you keeps a message: it is pinned, clean-ups leave it
alone, and archive and delete ask first (E8). Replying `pin` pins at once.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| L1 | 👤 Manual | React 📌 on a message and wait 30 seconds | Nothing for 30 seconds, then it is pinned and gets ✅; no "pinned a message" notice left behind; "📌 Reaction: keep" log card | ⬜ Untested | | |
| L2 | 👤 Manual | Remove your 📌 from a kept message and wait | It is unpinned and its ✅ is removed; "📌 Reaction removed: keep" log card | ⬜ Untested | | |
| L3 | 👤 Manual | React 📌 and remove it within the wait | Nothing happens: not pinned, no ✅ | ⬜ Untested | | |
| L4 | 👤 Manual | Keep a message, restart the bot, then remove your 📌 | Unpinned and its ✅ removed after the wait | ⬜ Untested | | |
| L5 | 👤 Manual | React 📌 in a channel that is at Discord's pin limit; then unpin one, take the 📌 off and add it again | The message gets ⚠️, isn't pinned and nothing is said in the channel; the log card says the channel is full and what to do. The second time it is pinned, and ✅ replaces the ⚠️ | ⬜ Untested | | Needs a full channel; skip if there isn't one |
| L6 | 🤖 Auto | The 📌 registration | A reaction of the keep skill, any channel, not destructive, with an undo; every reaction that leaves its message can be undone | ✅ Pass | 2026-10-07 | `tests/test_keep.py, test_registry.py` |
| L7 | 🤖 Auto | Keeping and unkeeping | Keeping pins, unkeeping unpins; unkeeping a message that has gone is fine; a message counts as kept once 📌 is applied | ✅ Pass | 2026-10-07 | `tests/test_keep.py` |
| L8 | 🤖 Auto | Discord refuses to pin or unpin | Pin limit, message gone, kind of message that can't be pinned, no permission: each fails with a reason the user can act on | ✅ Pass | 2026-10-07 | `tests/test_keep.py` |
| L9 | 👤 Manual | Reply `pin` to a message | Pinned at once (no wait); your reply is deleted; "📌 Pinned" for 5 seconds; no "pinned a message" notice left behind | ⬜ Untested | |  |
| L10 | 👤 Manual | Reply `pin this`, and `pin me`, to a message | Each pins it, as `pin` does | ⬜ Untested | |  |
| L11 | 👤 Manual | Reply `unpin` to a pinned message | Unpinned at once; "📌 Unpinned" for 5 seconds | ⬜ Untested | |  |
| L12 | 🤖 Auto | Pinning by reply | `pin`, `keep`, `save` pin and `unpin`, `unkeep` unpin, in any channel; a refusal by Discord confirms nothing | ✅ Pass | 2026-10-07 | `tests/test_keep.py` |

## M. Message lifecycle

Every message has a class (Kept, Live, Consumed, Transient, Alert,
Protected; the table is in `CLAUDE.md`). What shows in Discord is covered
by J28 and J29.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| M1 | 🤖 Auto | The policy and which class a message is | Kept and Protected are never auto-deleted; the others may be once their information lives elsewhere; protection wins, then what a skill declares, then transient, then command; anything else is Kept | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
| M2 | 🤖 Auto | Confirmations, notes and command messages | Self-delete after `CONFIRMATION_SECONDS` and the command is removed; with clean-up off they all stay; lasting replies never get a lifetime | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
| M3 | 🤖 Auto | What the timers skill declares | A running timer or session is Live, its alert is an Alert, and a finished one's summary is ordinary Kept content | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
