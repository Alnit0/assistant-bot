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

Last updated: 2026-10-09

| Group | Feature | Tests | 🤖 | 👤 | ⬜ | ✅ | ❌ | ⏭️ |
|---|---|---|---|---|---|---|---|---|
| A | Builtin words and chat | 18 | 9 | 9 | 9 | 9 | 0 | 0 |
| B | Lab | 21 | 2 | 19 | 19 | 2 | 0 | 0 |
| C | Reactions | 12 | 7 | 5 | 5 | 7 | 0 | 0 |
| D | Archive and restore | 15 | 4 | 11 | 11 | 4 | 0 | 0 |
| E | Delete and protection | 12 | 3 | 9 | 9 | 3 | 0 | 0 |
| F | Pins | 4 | 0 | 4 | 4 | 0 | 0 | 0 |
| G | Timers | 21 | 8 | 13 | 13 | 8 | 0 | 0 |
| H | Pomodoro | 21 | 6 | 15 | 15 | 6 | 0 | 0 |
| J | Dev mode | 45 | 7 | 38 | 38 | 7 | 0 | 0 |
| K | Startup and housekeeping | 14 | 7 | 7 | 7 | 7 | 0 | 0 |
| L | Keep | 12 | 4 | 8 | 8 | 4 | 0 | 0 |
| M | Message lifecycle | 5 | 4 | 1 | 1 | 4 | 0 | 0 |
| N | Tool calling | 55 | 27 | 28 | 28 | 27 | 0 | 0 |
| P | Bugs | 29 | 14 | 15 | 15 | 14 | 0 | 0 |
| Q | Time, days, the occurrence log and cards | 9 | 8 | 1 | 1 | 8 | 0 | 0 |
| R | Pills | 39 | 2 | 37 | 37 | 2 | 0 | 0 |
| | **Total** | **332** | **112** | **220** | **220** | **112** | **0** | **0** |

Unless a test says otherwise: type in #inbox, as the owner, with dev mode
off and `KEEP_CONFIRMATIONS=false` (the tests expect confirmations to
tidy themselves away; M5 covers the setting). "Log card" means a card in
#bot-log.

## A. Builtin words and chat

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| A1 | 👤 Manual | Type `ping` | "🏓 Pong!" stays; your `ping` is deleted; log card | ⬜ Untested | | |
| A2 | 👤 Manual | Type `stats` (and `stat`) | All-time stats card stays; your word is deleted | ⬜ Untested | | |
| A3 | 👤 Manual | Type `help` | List of what works in this channel, grouped by task, including Dev | ⬜ Untested | | |
| A4 | 🤖 Auto | `help <task>` and `help <word>` | The task in full; one word with aliases, examples, where it works and its permission | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
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
| A16 | 🤖 Auto | Claude's instructions | Named from `ASSISTANT_NAME` (default Hive); include the registry's list. With tools: act when clearly asked, ask when unsure, propose when suggesting, never say something is done unless a tool it called for that message succeeded, never write tool notes as text, use the note that comes with each message for anything that changes, put every action in one response, never claim or offer what it has no tool for. With no tools: says it cannot act. The time is not in it at all: it goes with the user's words | ✅ Pass | 2026-10-09 | `tests/test_text.py, test_llm_tools.py` |
| A17 | 👤 Manual | Ask Claude: `Set a timer for 5 minutes` | A 5-minute timer starts, exactly as `timer 5m` would; your message stays; Claude adds one short line. A "🔧 Tool: timer" log card as well as "Message handled" | ⬜ Untested | |  |
| A18 | 👤 Manual | Ask Claude for something no tool does: `Email my landlord about the rent` | It says it can't do that; it does not claim or offer to. Nothing runs | ⬜ Untested | | Wording varies |

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
| G5 | 👤 Manual | Reply `pause`, then `resume` (or `unpause`), to a running timer | Shows "paused with … left", then runs again with the same time left | ⬜ Untested | | |
| G6 | 👤 Manual | Reply `+10m` (and `extend 5m`) to a running timer | End time moves out by that much | ⬜ Untested | | |
| G7 | 👤 Manual | Reply `cancel` to a running timer | Marked cancelled; no alert later; removed from the board | ⬜ Untested | | |
| G8 | 🤖 Auto | Durations: `1h30`, `2 hours`, `1:30`, `25`, `90s`, `1.5h`, with a label | Each reads as the right length; the rest is the label | ✅ Pass | 2026-10-07 | `tests/test_durations.py` |
| G9 | 👤 Manual | `timer` on its own, and `timers` | Lists your active timers across channels, marked as live, or "No active timers" | ⬜ Untested | | |
| G10 | 🤖 Auto | Bad durations: `banana`, `2s`, more than 24 hours | Refused with a reason (shortest is 5 seconds, longest 24 hours) | ✅ Pass | 2026-10-07 | `tests/test_durations.py` |
| G11 | 👤 Manual | Start `timer 2m`, restart the bot before it ends | Still fires on time; buttons work | ⬜ Untested | | |
| G12 | 👤 Manual | Start `timer 1m`, stop the bot for 3 minutes, start it | Alert at startup says it finished while the bot was offline | ⬜ Untested | | |
| G13 | 👤 Manual | Reply `cancel` to a message that isn't a timer | Not a command: treated as ordinary chat | ⬜ Untested | | |
| G14 | 🤖 Auto | Pause, resume and extend arithmetic | Time left is kept across pauses; extending adds to it | ✅ Pass | 2026-10-07 | `tests/test_pomodoro.py` |
| G15 | 🤖 Auto | Timer message and board text for each state | Running, paused, cancelled, finished; empty board says "No active timers" | ✅ Pass | 2026-10-07 | `tests/test_timer_text.py` |
| G16 | 👤 Manual | With two timers running, type `timers`; reply `pause` to one timer; look at the list. Then `timers` again | The list changes by itself: that timer reads "paused, … left" with no countdown, and stays so. The second `timers` puts a new list at the bottom and removes the old one: one list per channel | ⬜ Untested | | Failed 2026-10-07; fixed in code: the 22:54 list went on counting down after `pause all`, so dinner read 24s and breakfast about 1m while they were frozen at 2m 50s and 3m 36s |
| G17 | 🤖 Auto | Pausing freezes, resuming carries on | Time left is the same however long the pause; resume ends exactly that much later; pausing twice and `+` while paused add up. At dev speed too, and when the speed changes while a timer is going (each clock keeps the speed it started at). A timer whose time is already up is finished, never paused at 0s | ✅ Pass | 2026-10-07 | `tests/test_timer_freeze.py` |
| G18 | 🤖 Auto | What happened is recorded | Started, paused, resumed, extended, cancelled, finished, dismissed (and a session's phases, skips and stop), each with the time and what was left on the clock | ✅ Pass | 2026-10-07 | `tests/test_timer_freeze.py, test_timer_status.py` |
| G19 | 🤖 Auto | `pause all` / `resume all` | Every running (or paused) timer and the Pomodoro; `except pomodoro` or `timers only` leaves it out; a timer that has run out is left alone and named; the reply lists each one with the time left as saved; with nothing to do it says so and changes nothing | ✅ Pass | 2026-10-07 | `tests/test_timer_freeze.py, test_timer_status.py` |
| G20 | 🤖 Auto | The live "Your timers" list | A paused timer shows as paused with its time, not a countdown; one list per channel, the newest; it is a Live message; an empty one is not kept live | ✅ Pass | 2026-10-07 | `tests/test_timer_freeze.py` |
| G21 | 👤 Manual | With two timers and a Pomodoro running, type `pause all`; wait two minutes; `timers`; then `resume all` | "⏸️ Paused 3" naming each with its time left. Two minutes later the list shows the same times. "▶️ Resumed 3" with those same times, and each then counts down from there | ⬜ Untested | | |

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
| H19 | 👤 Manual | With a `pomo 50/10/30` session running or waiting for Start, ask Claude: `Start a Pomodoro timer for 25 minutes`, then `no` | One reply and nothing else new in the channel: it says a session is already going, with its lengths and where it is up to, and offers to restart it as 25/5. The session is unchanged until you agree | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| H20 | 🤖 Auto | A session is asked for while one is going | Other lengths than the session's are noticed (a long break that wasn't mentioned isn't compared). Through Claude nothing is posted or changed: it is told the session's state and, if the lengths differ, to offer a restart. Typed, Confirm stops the old session and starts one with the new lengths and the same label | ✅ Pass | 2026-10-07 | `tests/test_timer_status.py, test_toolcalls.py` |
| H21 | 👤 Manual | With `pomo 50/10/30 writing` going, type `pomo 25/5`; press **Cancel**; type it again and press **Confirm** | The card is shown again with one question under it: "**writing** is already going at 50m/10m/30m. Restart it as `25/5`?" (no "Already going" note as well). Cancel leaves the session alone; Confirm stops it and starts "writing" at 25/5 | ⬜ Untested | | |

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
| J19 | 👤 Manual | `dev jobs` | Pending jobs with id, task/kind and due time, including the nightly backup | ⬜ Untested | | |
| J20 | 👤 Manual | `dev run backup`; then `dev run sweep` | "💾 Backup saved" log card and a new file in `data/backups/`; sweep gets ⚠️ with "not built" on the log card | ⬜ Untested | | |
| J21 | 👤 Manual | `timer 10m`, then `dev fire next` | The timer finishes at once; confirmation names the job | ⬜ Untested | | |
| J22 | 👤 Manual | `dev seed 3`, then `dev clean` | Three sample messages tagged "🧪 dev test data", and a "🌱 Seeded 3…" line that stays (it is not a 5-second confirmation); clean removes them all, with any `dev inspect` / `dev jobs` output | ⬜ Untested | | |
| J23 | 👤 Manual | `dev seed 2`, pin one, `dev clean` | The pinned one stays | ⬜ Untested | | |
| J24 | 👤 Manual | `dev on`, restart the bot | Dev mode is off: normal debounce, no status; the old panel is removed at startup; a button on any panel left behind removes it | ⬜ Untested | | |
| J25 | 🤖 Auto | Dev defaults, on / off / reset, expiry | Off gives normal values; on gives 2s, 1x, verbose, quiet ignored for 1 hour; settings only count while on | ✅ Pass | 2026-10-07 | `tests/test_devmode.py` |
| J26 | 🤖 Auto | Dev setting values | `60`, `2.5`, `2s`, `60x`, `on`, `off` read correctly; out-of-range and nonsense refused with the usage, changing nothing | ✅ Pass | 2026-10-07 | `tests/test_devmode.py, test_dev_parsing.py` |
| J27 | 🤖 Auto | Speed arithmetic and `dev run` routines | 25m at 60x is 25 real seconds, and back; unknown and unbuilt routines refused | ✅ Pass | 2026-10-07 | `tests/test_devmode.py` |
| J28 | 👤 Manual | `dev cleanup off`, then a setting word such as `dev debounce 3`; then `dev cleanup on` | Panel shows clean-up off; your words and their confirmations stay on screen; after `dev cleanup on` they are tidied away again as normal | ⬜ Untested | |  |
| J29 | 👤 Manual | Reply `dev inspect` to a timer's alert, and to a running timer's message | The card's Lifecycle line says Alert for the first and Live for the second, each with what happens to it | ⬜ Untested | |  |
| J30 | 👤 Manual | `dev off` when dev mode is already off | "🛠️ Dev mode is already off." for 5 seconds; your word is deleted; no ⚠️ | ⬜ Untested | |  |
| J31 | 🤖 Auto | The clean-up setting | On by default and whenever dev mode is off; `dev cleanup off` stops every automatic deletion | ✅ Pass | 2026-10-07 | `tests/test_devmode.py, test_lifecycle.py` |
| J32 | 👤 Manual | Type `dev mode on`, then `dev mode off` | Same as `dev on` and `dev off` (J1, J3); Claude is not called | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| J33 | 👤 Manual | Type `dev status` while running a test copy from `.venv` | "🩺 Bot instances": "1 bot is running: PID …, started … (it holds the lock)", and a "Not counted" line for the `.venv` launcher. No ⚠️ line. `python -m core.instance_lock` in PowerShell prints the same | ⬜ Untested | | |
| J34 | 🤖 Auto | The bot's clock | The real time unless moved; refuses to move on the live database; only forward (`reset` is the one way back); keeps ticking from where it is put; the offset survives a restart and is never picked up by the live bot; an unreadable one is ignored; time jumped over is counted | ✅ Pass | 2026-10-09 | `tests/test_clock.py` |
| J35 | 🤖 Auto | `dev clock`, `dev reset-db` and their guards | A time is the next moment the clock reads it (past today's: tomorrow's); `+2h` adds; `reset` goes back; "6" is asked about, not guessed; on the live database moving the clock and wiping are refused with the reason and nothing changes, and only a file named as the dev database can be wiped; the status and panel say DEV DATABASE only with `--dev` | ✅ Pass | 2026-10-09 | `tests/test_dev_clock.py` |
| J36 | 👤 Manual | Stop the bot; start it with `python main.py --dev` | "👋 Online and ready… · 🧪 **DEV DATABASE**" in #inbox; the bot's status reads "🧪 DEV DATABASE"; the start card's Database field says `dev.db (DEV DATABASE)`; `stats` shows the dev database's own (empty at first) totals | ⬜ Untested | | |
| J37 | 👤 Manual | With `--dev`: `dev on` | The panel has a "🧪 **DEV DATABASE** · `dev.db`" line and a "Clock: … (the real time)" line; the status reads "🛠️ Dev mode · 🧪 DEV DATABASE" | ⬜ Untested | | |
| J38 | 👤 Manual | With `--dev`: `timer 30m`, then `dev clock +1h` | "🕰️ Clock: … (1h ahead)"; the timer finishes at once with its alert; the panel's Clock line shows 1h ahead; `dev clock` alone shows the same | ⬜ Untested | | |
| J39 | 👤 Manual | With `--dev`: `dev clock 6`, then `dev clock 6am` | The first gets ⚠️ ("6am or 6pm?" on the log card) and the clock stays; the second moves to the next 6:00 am, later than where it was | ⬜ Untested | | |
| J40 | 👤 Manual | With `--dev` and the clock moved: `dev off`, then restart with `python main.py --dev`, then `dev clock` | The clock is still as far ahead as before, through both; the start card has a Clock field | ⬜ Untested | | |
| J41 | 👤 Manual | With `--dev`: `dev clock reset` | "🕰️ Clock: … (the real time)" | ⬜ Untested | | |
| J42 | 👤 Manual | With `--dev`: `timer 10m`, then `dev reset-db`; press **Cancel**; again, press **Confirm** | Cancel: nothing changes (`timers` still lists it). Confirm: "🧹 `dev.db` wiped…"; `timers` and `stats` are empty; `dev jobs` shows only the backup and the day rollover; the clock is the real time | ⬜ Untested | | |
| J43 | 👤 Manual | Without `--dev` (the live database): `dev clock`, `dev clock +1h`, `dev reset-db` | The first shows the real time and says it can only be moved on the dev database; the other two get ⚠️, with the reason on the log card; nothing changes and no question is asked | ⬜ Untested | | |
| J44 | 👤 Manual | With `--dev`: say `set a timer for 1 minute`, then type `dev cost` | A card that stays: "## 💰 Cost · `dev.db`"; **Today** with the cost, the number of messages and how many went to Claude; the averages per message; a line counting messages by route (`shortcut`, `button`, `tools` with its cost); **This month** the same; "Most expensive task this month: **timers**"; the tokens and requests of the month | ⬜ Untested | | |
| J45 | 🤖 Auto | What each message cost | Every logged input gets its route as it arrives (typed words are shortcuts, presses are buttons, reactions are reactions; a tool call is part of its message, not one of its own); cached tokens cost a tenth to read and a quarter more to write, and an unknown model costs "unknown", not nothing; a message is recorded with its tasks and one row per request; today and the month split at midnight NZ by the real clock; averages per message and per message to Claude, with older messages whose requests weren't counted left out of that average; a message for two tasks is charged half to each; the migration gives what was already logged a route and its cache tokens; `dev cost` reports the database that is running | ✅ Pass | 2026-10-09 | `tests/test_costs.py` |

## K. Startup and housekeeping

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| K1 | 👤 Manual | Start the bot | "👋 Online and ready" in #inbox; "🟢 Bot started" log card listing tasks and synced slash commands, with no ⚠️ fields | ⬜ Untested | | |
| K2 | 👤 Manual | Start a second copy while one is running | The second logs an error and exits; no double replies | ⬜ Untested | | |
| K3 | 👤 Manual | Have another account message the bot and react 📦 | Ignored completely | ⬜ Untested | | |
| K4 | 👤 Manual | Make a word fail (e.g. `timer banana`) | Your message stays with ⚠️; details only on the log card | ⬜ Untested | | |
| K5 | 👤 Manual | Leave the bot running past 3am NZ | "💾 Backup saved" log card naming the database copy and the specs zip; newest 7 `assistant-*.db` and newest 7 `specs-*.zip` kept | ⬜ Untested | | |
| K6 | 👤 Manual | Stop the bot over 3am, start it later | The missed backup runs at startup | ⬜ Untested | | |
| K7 | 🤖 Auto | Permissions | Only the owner is allowed anything; someone else marked owner is demoted at startup; lookups are cached | ✅ Pass | 2026-10-07 | `tests/test_permissions.py` |
| K8 | 🤖 Auto | Registrations | Every task loads; every word, reply action and reaction has a description, an example, a channel and a permission | ✅ Pass | 2026-10-07 | `tests/test_registry.py` |
| K9 | 🤖 Auto | Scheduler | Jobs run when due, late ones at startup flagged late, interrupted ones recovered; the nightly backup books its successor | ✅ Pass | 2026-10-07 | `tests/test_scheduler.py` |
| K10 | 👤 Manual | Set `ASSISTANT_NAME=Marvin` in `.env`, restart, `buttons` and press **Wave** | "👋 Hello from Marvin!"; Claude also gives that name when asked | ⬜ Untested | | Needs a restart with the setting changed; skip otherwise |
| K11 | 🤖 Auto | Which tasks are loaded | `ENABLED_TASKS` lists them (any case, spaces ignored); if it is empty the old `ENABLED_SKILLS` is read instead, so an `.env` from before the rename still works; the new name wins; neither set loads them all | ✅ Pass | 2026-10-09 | `tests/test_registry.py` |
| K12 | 🤖 Auto | Start-up with a forum among the channels | Only text channels, threads and DMs are read for pins or history; forum, voice and category channels are skipped (the dev panel's sweep crashed on #bugs, 2026-10-09); a task that fails to start is reported and the rest still start | ✅ Pass | 2026-10-09 | `tests/test_channels.py` |
| K13 | 🤖 Auto | How many bots are running | The lock decides: held means one bot (with its PID and start time), a file left by a stopped bot means none, and looking never keeps the lock or turns a start away. Among processes, the `.venv` launcher and its child are one bot; a copy without the lock is flagged; `dev status` reports it | ✅ Pass | 2026-10-09 | `tests/test_instance_lock.py` |
| K14 | 🤖 Auto | Specs in the nightly backup | `docs/specs/` is zipped beside the database backup with its subfolders; no folder or an empty one makes no zip; the newest 7 zips are kept, counted apart from the database's; a specs copy that fails is reported and the database backup still is | ✅ Pass | 2026-10-09 | `tests/test_backup.py` |

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
| L6 | 🤖 Auto | The 📌 registration | A reaction of the keep task, any channel, not destructive, with an undo; every reaction that leaves its message can be undone | ✅ Pass | 2026-10-07 | `tests/test_keep.py, test_registry.py` |
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
| M1 | 🤖 Auto | The policy and which class a message is | Kept and Protected are never auto-deleted; the others may be once their information lives elsewhere; protection wins, then what a task declares, then transient, then command; anything else is Kept | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
| M2 | 🤖 Auto | Confirmations, notes and command messages | Self-delete after `CONFIRMATION_SECONDS` and the command is removed; with clean-up off they all stay; lasting replies never get a lifetime | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
| M3 | 🤖 Auto | What the timers task declares | A running timer or session is Live, its alert is an Alert, and a finished one's summary is ordinary Kept content | ✅ Pass | 2026-10-07 | `tests/test_lifecycle.py` |
| M4 | 🤖 Auto | `KEEP_CONFIRMATIONS` | On unless switched off; while on, confirmations and notes get no lifetime, and the command message is still removed | ✅ Pass | 2026-10-09 | `tests/test_lifecycle.py` |
| M5 | 👤 Manual | Set `KEEP_CONFIRMATIONS=true` (or remove the line), restart, then reply `pin` to a message, and react 📦 to a message in #archive | "📌 Pinned" stays in the channel and your `pin` is still deleted; the ⚠️ reason for the 📦 stays too. Reply `unpin` afterwards | ⬜ Untested | | |

## N. Tool calling

Claude can run the bot's registered words and reply actions as tools, in
#inbox. Typed words are unchanged and never go to Claude. The lab is never
offered; dev tools only while dev mode is on (apart from the switch itself).
Timers and the Pomodoro are read and changed by id, never by looking for
their messages. Claude's wording varies from
run to run: judge what happens, not the exact words.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| N1 | 🤖 Auto | Tool names and schemas | One tool per word and reply action; names the API accepts, all unique; every property required, no unions or optional properties, nothing else allowed; message actions take `targets`; everything but destructive tools takes `propose` | ✅ Pass | 2026-10-07 | `tests/test_tools.py` |
| N2 | 🤖 Auto | Checking a tool input | Wrong types, values outside the choices, missing and unknown arguments are each named; checked for every call, strict or not | ✅ Pass | 2026-10-07 | `tests/test_tools.py, test_toolcalls.py` |
| N3 | 🤖 Auto | A tool call reads as the typed word does | `timer`, `pomo` and the dev settings turn their arguments back into the same words the typed command has, and the real parsers accept them | ✅ Pass | 2026-10-07 | `tests/test_tools.py` |
| N4 | 🤖 Auto | Which tools are strict | None by default (`STRICT_TOOLS` off: it was slow). When on: Only tools with arguments; past the API's 20, the likeliest first and one warning in #bot-log; the real tool sets fit within the limit | ✅ Pass | 2026-10-09 | `tests/test_tools.py, test_toolcalls.py` |
| N5 | 🤖 Auto | Which tools are offered | Filtered by channel and permission; the lab never; dev only while dev mode is on or in the dev channel, except its on/off switch; nobody without permission gets any; the order never changes | ✅ Pass | 2026-10-07 | `tests/test_tools.py, test_toolcalls.py` |
| N6 | 🤖 Auto | Which message a message action acts on | A reply always wins; one listed ref acts; two to five are offered; none, an unlisted one or more than five is an error for Claude; only the last 20 messages can be reached | ✅ Pass | 2026-10-07 | `tests/test_tools.py, test_toolcalls.py` |
| N7 | 🤖 Auto | Previews, confirmations and the listing | One-line 80-character quotes; a confirmation quotes its target and links to it; the listing gives each message a ref, age and tags | ✅ Pass | 2026-10-07 | `tests/test_tools.py` |
| N8 | 🤖 Auto | Pending proposals | ok, yes, do it and the like agree; no, cancel, never mind decline; anything longer is neither; a proposal lasts 2 minutes, is taken once, is replaced by a newer one, and belongs to one user in one channel | ✅ Pass | 2026-10-07 | `tests/test_pending.py` |
| N9 | 🤖 Auto | The Claude loop (mocked Claude) | A plain answer calls nothing; a call is run and its result returned; several calls in a turn are answered in one message; failures and crashes go back as errors; at most 5 calls per message; a reply cut short runs nothing; history stays plain text, with no note of the tool calls | ✅ Pass | 2026-10-07 | `tests/test_llm_tools.py` |
| N10 | 🤖 Auto | Caching and cost | The system prompt is one cached block and, with the tools, the same bytes from message to message; the time and live state go after the user's words in the latest turn only and are not remembered; usage is summed over rounds; cached tokens are priced at 0.1x read and 1.25x written; tool tokens are counted once per set of tools | ✅ Pass | 2026-10-09 | `tests/test_llm_tools.py, test_toolcalls.py` |
| N11 | 🤖 Auto | What becomes of a call | A clear request runs at once; a proposal waits for ok; a destructive one asks with Confirm / Cancel and quotes its target; several candidates are offered as buttons; a described message is shown quoted, with Undo if it can be taken back | ✅ Pass | 2026-10-07 | `tests/test_toolcalls.py` |
| N12 | 🤖 Auto | Running and logging | A tool call runs the same handler as the typed word and is logged as `tool` with its input and outcome; refused calls are logged too; permission is checked again when it runs; your chat message is neither deleted nor marked ⚠️ | ✅ Pass | 2026-10-07 | `tests/test_toolcalls.py` |
| N13 | 🤖 Auto | Typed words never reach Claude | A typed word is dispatched by the registry and Claude is not called | ✅ Pass | 2026-10-07 | `tests/test_toolcalls.py` |
| N14 | 👤 Manual | Type `timer 10s` | Runs as always: your word is deleted, and there is no "Message handled" card (Claude was not called) | ⬜ Untested | |  |
| N15 | 👤 Manual | Ask Claude: `Set a timer` | It asks how long, and starts nothing | ⬜ Untested | |  |
| N16 | 👤 Manual | Ask Claude: `Would a pomodoro help? Suggest one but wait for my ok`, then reply `ok` | It proposes and nothing starts; after `ok` a session starts. No "Message handled" card for the `ok` | ⬜ Untested | | Wording varies |
| N17 | 👤 Manual | Get a proposal as in N16, then reply `no` | "👌 Left it: …" for 5 seconds; nothing starts | ⬜ Untested | |  |
| N18 | 👤 Manual | Get a proposal, wait over 2 minutes, then reply `ok` | Nothing starts: the `ok` goes to Claude as ordinary chat | ⬜ Untested | |  |
| N19 | 👤 Manual | Ask Claude: `Clear our conversation`; press **Cancel**; ask again and press **Confirm** | A question naming `reset` with Confirm and Cancel, nothing cleared yet; Cancel removes it; Confirm clears the memory and the question shows "✅ Done" | ⬜ Untested | |  |
| N20 | 👤 Manual | Reply to one of your own messages: `can you file this away for me?` | That message is archived, as reply `archive` does, with the usual "📦 Archived: link" for 5 seconds | ⬜ Untested | |  |
| N21 | 👤 Manual | Type a message about rent. Then, without replying: `pin the message about rent`. Press **Undo** | It is pinned; a confirmation quotes it with a link and an Undo button for 30 seconds; Undo unpins it | ⬜ Untested | |  |
| N22 | 👤 Manual | Type two messages about milk. Then: `archive the note about milk` | "Which message should I `archive`?" with both quoted and numbered buttons, plus "None of these"; pressing a number archives that one only | ⬜ Untested | |  |
| N23 | 👤 Manual | Without replying: `delete the message about rent`; press **Cancel** | Confirm / Cancel question that quotes the message; nothing deleted | ⬜ Untested | |  |
| N24 | 👤 Manual | Dev mode off: ask Claude `speed the timers up 60 times`. Then `dev on` and ask again | First it says it can't (or to type `dev speed 60`) and nothing changes. With dev mode on it runs and the panel shows 60x | ⬜ Untested | |  |
| N25 | 👤 Manual | Ask Claude: `run the lab chart` | It tells you to type `lab chart`; no chart is posted | ⬜ Untested | |  |
| N26 | 👤 Manual | Look at the "Message handled" card after N24 | Fields for Tools sent (count, how many strict, names), Tool tokens, Cache (read / written) and Tool calls with each outcome | ⬜ Untested | |  |
| N27 | 👤 Manual | Ask Claude: `Start six one-minute timers called a, b, c, d, e and f` | Five start; Claude says the sixth was not done | ⬜ Untested | |  |
| N28 | 👤 Manual | Ask Claude: `Set a timer for three days` | No timer; Claude explains the 24-hour limit; no ⚠️ on your message; a "Command failed" log card | ⬜ Untested | |  |
| N29 | 👤 Manual | Start two timers and a Pomodoro. Ask Claude: `Show my timers`, then `How long left on my Pomodoro?` | It answers from the live state: each timer's label and time left, and the session's phase, round and time left (or that it is waiting for Start) | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N30 | 👤 Manual | With a `tea` timer and a Pomodoro going, and neither on screen in the last 20 messages, ask without replying: `Pause the tea timer`, `Unpause the tea timer`, `Pause my pomodoro` | Each acts on the right one, found from the live list and not from the chat; a timer that has already ended is reported as ended | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N31 | 👤 Manual | Ask Claude for actions over several messages (`Start a timer for 20 minutes called testing`) and check each "done" against the channel and the log card | It only says something was done when a tool ran and succeeded for that message; otherwise it runs the tool, or says it has not | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N32 | 👤 Manual | Read Claude's replies after it has used tools a few times | No bracketed debug text in any reply; what was called is only on the "Message handled" log card | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N33 | 👤 Manual | Dev mode off, in #inbox: ask Claude `switch dev mode on`, then `turn dev mode off` | Dev mode goes on (panel posted), then off; the other dev tools are still only offered while it is on | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N34 | 👤 Manual | Ask Claude to pin a message of yours from more than 20 messages back (`Pin the message about rent`), then `Look further back` if it hasn't already; press **Confirm** | It finds the message and asks first: "Found further back…" with the message quoted, a link, and Confirm / Cancel. Nothing is pinned until Confirm. If nothing fits it says so | ⬜ Untested | | Failed 2026-10-07; fixed in code |
| N35 | 🤖 Auto | "Done" only when a tool did it (mocked Claude) | A reply that says done, with no tool having acted for that message, is not sent: Claude is told so once and either calls the tool or answers again; if it insists, the user is told nothing ran. Reading, proposing, waiting for Confirm and failing don't count as doing. Ordinary answers are never sent back; the first reply is kept for a #bot-log card | ✅ Pass | 2026-10-09 | `tests/test_llm_tools.py, test_toolcalls.py` |
| N36 | 🤖 Auto | No debug text in a reply | Nothing is added to a reply in the history; a bracketed tool note that Claude writes itself is taken out before it is sent or remembered; ordinary square brackets are left alone | ✅ Pass | 2026-10-07 | `tests/test_llm_tools.py` |
| N37 | 🤖 Auto | Reading state and acting by id | `list_timers` gives each timer's id, label, state, time left and channel, and the ones that ended in the last day; `get_pomodoro_status` gives phase, round, time left or "waiting for Start", and lengths. `timer_control` takes one id, several or `all` and an action, `pomodoro_control` an id or `current`; a wrong id or state is explained. None of them posts in the channel or takes a message; the timer reply actions are not offered to Claude | ✅ Pass | 2026-10-09 | `tests/test_timer_status.py, test_tools.py, test_toolcalls.py` |
| N38 | 🤖 Auto | Looking further back | `search_messages` matches the words given against your last 500 logged messages in the channel, up to 30 days old: most words first, then newest, one letter out still matches; messages that have gone are left out. Acting on a match asks with Confirm / Cancel and the message quoted; a recent message is still acted on at once with Undo | ✅ Pass | 2026-10-07 | `tests/test_tools.py, test_toolcalls.py` |
| N39 | 🤖 Auto | The dev mode switch | `dev mode on` and `dev mode off` are typed words; anything else after `dev mode` is not. Claude is offered that one dev tool in every channel, to the owner only, and it runs without a Confirm | ✅ Pass | 2026-10-07 | `tests/test_tools.py, test_registry.py` |
| N40 | 👤 Manual | With two timers and a Pomodoro running, ask Claude: `Pause all timers` | It acts at once, without asking which. One "⏸️ Paused 3" message names each timer and the Pomodoro with the time left; Claude adds at most a line | ⬜ Untested | | Failed 2026-10-07; fixed in code: it asked "which would you like me to pause first?", then paused the three timers one call each and left the Pomodoro running |
| N41 | 👤 Manual | With a paused `tea` timer, ask Claude: `Resume my tea timer`; then type `timers` | The timer's own message and the list show tea running, and the time Claude gives matches them | ⬜ Untested | | Failed 2026-10-07; fixed in code: it read the list, replied "Tea's running again – 9m 21s left" and resumed nothing |
| N42 | 👤 Manual | Pause a timer, then ask Claude: `What was left on it when I paused it?` | It answers from the record: the time of the pause and what was left | ⬜ Untested | | Failed 2026-10-07; fixed in code: "I don't have a record" |
| N43 | 🤖 Auto | A control tool reports what was saved | The result of `timer_control` and `pomodoro_control` ends with the state read back from the database; a change that didn't take is a failure for Claude to report, not a success | ✅ Pass | 2026-10-07 | `tests/test_timer_freeze.py, test_toolcalls.py` |
| N44 | 🤖 Auto | A change reported with nothing run (mocked Claude) | Only questioned when no tool succeeded at all: after a successful read the wording is let through (a flat "Done" is not). "Tea's running again", "I've paused it", "all three paused" with no action run are sent back to Claude once, and it then makes the call; describing how things are ("tea is paused, 9m left") is not sent back; a true account of an earlier message is asked about once and never overruled. Every read tool's result ends by saying nothing was changed | ✅ Pass | 2026-10-09 | `tests/test_llm_tools.py, test_toolcalls.py` |
| N45 | 🤖 Auto | Where the time went | Each request to Claude (time, model, tokens in, out, cache read and written, retries), each tool's time, the calls to Discord and their total, rate-limit waits and Claude retries (read from the libraries' logs) are recorded for the message being answered and nothing else; the card and the log line give the same numbers | ✅ Pass | 2026-10-07 | `tests/test_timing.py` |
| N46 | 👤 Manual | Ask Claude: `Set a timer for 5 minutes`, then look at its "Message handled" log card | A Timing field: the seconds to the reply and the number of round trips, one line per request to Claude, one per tool, the Discord time and call count, rate-limit waits and retries. `logs/bot.log` has a matching `Timing:` line | ⬜ Untested | | |
| N47 | 🤖 Auto | Live messages are updated in the background | Scheduling returns at once; several changes to one message are one edit, the latest; two edits of the same message are at least the interval apart; different messages don't wait for each other; a failed edit is logged and the next still runs; none of it counts in the turn's timing | ✅ Pass | 2026-10-09 | `tests/test_live.py` |
| N48 | 🤖 Auto | One round trip for a simple action | The live state lists every timer (each of two with the same label), the ones ended lately and the session, and is current after a change. When every call of a round acted and showed its confirmation the turn ends without a second request: a word's own message needs nothing more, a control tool's confirmation is the reply; a read, a failure (for the rest of the turn), a proposal or buttons go back to Claude | ✅ Pass | 2026-10-09 | `tests/test_llm_tools.py, test_toolcalls.py, test_timer_freeze.py, test_timer_status.py` |
| N49 | 🤖 Auto | Many timers in one call | `timer_control` with `all` cancels seven timers in one call; with a label it acts on every timer that has that word, whatever the case (Tea, tea 2) and no other (team, dinner); `stop` is cancel; several ids at once; pause all is about the running ones; one that can't be changed is named and the rest still are; a label nothing has, or an id that isn't there, changes nothing and is explained | ✅ Pass | 2026-10-09 | `tests/test_timer_freeze.py, test_timer_status.py` |
| N50 | 👤 Manual | Ask Claude: `Set a timer for 5 minutes`, watching the clock; then `Pause the timer` | 👀 appears on your message at once and goes when it is answered. The timer's message is there in under 4 seconds and Claude adds no line of its own. The pause is confirmed in one short message, also in under 4 seconds. Each log card's Timing shows 1 round trip | ⬜ Untested | | |
| N51 | 👤 Manual | Start timers `tea`, `Tea 2` and `dinner`, then ask: `Stop all timers called tea` | One message: "🚫 Cancelled 2" naming tea and Tea 2. Dinner is still running. The board and the timers' own messages show it within a few seconds | ⬜ Untested | | |
| N52 | 👤 Manual | Start six timers, then ask: `Cancel all timers` | One message naming all six; none is left and you are not asked to repeat the request. The log card shows one tool call and no rate-limit waits | ⬜ Untested | | |
| N53 | 🤖 Auto | One confirmation only | A tool that shows its own preview or Confirm card (`confirms_itself`) has no `propose` argument, is told so in its description, runs at once, and can't be put behind an "ok" even if Claude tries. An agreed proposal replays the stored call, field for field, never the user's words; what is shown and remembered about it is the tool's label, never its name or arguments | ✅ Pass | 2026-10-09 | `tests/test_toolcalls.py`, `tests/test_tools.py` |
| N54 | 🤖 Auto | Replies that must not reach you as they are | "I'm proposing… reply ok" with nothing waiting is sent back once (Claude then calls the tool) and overruled if repeated; "That ran when you said ok: …" with nothing run is caught as an unbacked done; a reply naming a tool is sent back once and the name removed; times in a reply are never rewritten (a timer's `05:00 left` and `08:30` stay as they are); the prompt states each rule | ✅ Pass | 2026-10-09 | `tests/test_llm_tools.py` |
| N55 | 🤖 Auto | Which task is meant | No typed shortcut is a bare generic verb, so "add milk" matches none; two tasks that both want "add <item>" can only claim it with their name, and the bare verb is reported; every tool says what it is only for; when Claude marks two tasks' tools as candidates nothing runs, the user gets a button per task, and the pick runs with Claude's structured input; a single candidate simply runs | ✅ Pass | 2026-10-09 | `tests/test_registry.py`, `tests/test_toolcalls.py`, `tests/test_tools.py` |

## P. Bugs

Needs `BUGS_CHANNEL_ID` set to a forum channel. "The post" is the bug's
post in #bugs.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| P1 | 🤖 Auto | Ids and where a report may be made | `B4`, `b4` and `4` are bug 4; a message inside a bug's post can't be reported; a channel is named if known | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P2 | 🤖 Auto | Which turn a reported message belongs to | Your own message by its id; a message of the bot's to what you sent before it (5 seconds' grace); its tool calls and timings with it; never the `bug` command itself; none if nothing was logged | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P3 | 🤖 Auto | Related errors from the log | Only warnings and errors inside the turn's window, with their tracebacks; a long run is cut short and says so; a half line at the start of the tail is dropped | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P4 | 🤖 Auto | What the post says | Title "B4 · start of the message"; the message, the ones before it, that turn, the errors, then the three questions; each part fits a Discord message; tags swap on closing and other tags are kept | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P5 | 🤖 Auto | The records | Numbered in order and open; found by post and by message; a closed one leaves the list; notes kept in order with who wrote them | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P6 | 🤖 Auto | Filing a report | Recorded with its post and link; the same message is not logged twice; nothing is recorded when there is no forum; the turn, errors and commit are captured | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P7 | 🤖 Auto | `bug` alone, as a reply, and 🐞 | Alone: the latest message with the five before it; reply: that message; 🐞: that message, with the line sent to its channel; the line is a lasting reply | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P8 | 🤖 Auto | Notes, `bugs` and `bugs export` | A message in a bug's post is saved and ticked with no reply; a post that isn't a bug's is left alone; the list links to posts; the export has everything in full | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P9 | 🤖 Auto | The instant reaction and claimed messages | 🐞 runs at once and is never debounced; taking it away does nothing; only 🐞 is instant; a message in #bugs is claimed before Claude; a stranger's is dropped | ✅ Pass | 2026-10-09 | `tests/test_registry.py` |
| P10 | 🤖 Auto | Owner only, and the command line | Every word, the reaction, notes and closing need the owner; `cli show` and `note` work and nothing closes a bug | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P11 | 🤖 Auto | A turn's timings are kept | The breakdown on the log card is stored as plain values with the message | ✅ Pass | 2026-10-09 | `tests/test_timing.py` |
| P12 | 👤 Manual | Ask Claude `Set a timer for 5 minutes`, then react 🐞 to the timer's message | At once, with no 30-second wait: "🐞 Logged as B<n>" in the channel, and it stays. B<n> is a link that opens the post. No ✅ is added to the message | ⬜ Untested | | |
| P13 | 👤 Manual | Open that post | Title "B<n> · ⏱️ …"; tag Open; the timer's message quoted with a jump link; the messages before it; "That turn" with your request, the tool call and a Timings line; "Related errors"; the commit; then the three questions. **Fixed** and **Won't fix** buttons under the first message | ⬜ Untested | | |
| P14 | 👤 Manual | Take the 🐞 off, then add it again | Taking it off does nothing. Adding it again: "🐞 Already logged as B<n>", and no second post | ⬜ Untested | | |
| P15 | 👤 Manual | Reply `bug` to another message | Your reply is deleted; "🐞 Logged as B<n>" stays; the post is about the message you replied to | ⬜ Untested | | |
| P16 | 👤 Manual | In #scratch, send a message, then type `bug` | Your `bug` is deleted; the post is about the message before it, from #scratch | ⬜ Untested | | |
| P17 | 👤 Manual | In #inbox, type `bug: the timer was wrong` | Not a command: it goes to Claude as chat, and no bug is logged | ⬜ Untested | | |
| P18 | 👤 Manual | In a bug's post, answer the questions in one or two messages | Each message gets ✅ and stays. The bot says nothing, and #bot-log has no "Message handled" card | ⬜ Untested | | |
| P19 | 👤 Manual | In #inbox, type `bugs` | "Open bugs (n)", one line each with a link, where it came from, the date and the number of notes. It stays | ⬜ Untested | | |
| P20 | 👤 Manual | Type `bugs export`, open `docs/BUGS.md`, run `git status` | The file has every open bug in full with its notes. Git does not list it | ⬜ Untested | | |
| P21 | 👤 Manual | Press **Won't fix** on a post | On the opening card the two buttons become one **Re-open** button and the foot reads "🚫 Won't fix · <time>, <date>". "✅ B<n> closed as Won't fix" in the post; the tag changes from Open; the post is archived (closed); `bugs` no longer lists it | ⬜ Untested | | |
| P22 | 👤 Manual | Restart the bot, then press **Fixed** on a post made before the restart, and **Re-open** on one closed before it | Both work: the first is closed as Fixed, tagged and archived, with Re-open on its card; the second is open again | ⬜ Untested | | |
| P23 | 👤 Manual | React 🐞 to a message inside a bug's post | ⚠️ on it at once and "That is already in a bug's post…"; no new bug | ⬜ Untested | | |
| P24 | 👤 Manual | Delete the forum's Fixed tag, restart the bot | The tag is back. Without Manage Channels: one error card in #bot-log, naming that permission and the missing tags | ⬜ Untested | | |
| P25 | 🤖 Auto | The forum's tags at start-up | Missing tags are asked for in one request at every start, keeping the forum's own; a missing permission is one warning naming Manage Channels, not one a tag; nothing is asked when all are there | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P26 | 🤖 Auto | The opening card | Its foot gives the status, when it last changed ("1:25pm, 9 Oct", NZ time) and the note count; the rest of the card is unchanged; a long message never pushes the foot off; a note rewrites the count in place, and a card that can't be reached doesn't lose the note | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P27 | 🤖 Auto | Closing, re-opening and history | Fixed / Won't fix: the press is answered first, the card gets Re-open, the tag is set and the post archived last. Re-open: unarchived first, the two buttons and the Open tag back. Each is added to the bug's history (export and command line). An old post's stale buttons are put right when pressed; fixed ids, no expiry, both views registered before connecting; someone else changes nothing | ✅ Pass | 2026-10-09 | `tests/test_bugs.py` |
| P28 | 👤 Manual | Press **Re-open** on a closed post, then type `bugs` | The post is open again (no longer archived) with the tag Open; the card has **Fixed** and **Won't fix** back and its foot reads "🟢 Open · <time>, <date>"; "🔄 B<n> re-opened" in the post; `bugs` lists it again | ⬜ Untested | | |
| P29 | 👤 Manual | Write two notes in an open bug's post, watching the opening card | The card's foot goes from "📝 No notes yet" to "📝 1 note", then "📝 2 notes", edited in place (no new message from the bot) | ⬜ Untested | | |

## Q. Time, days, the occurrence log and cards

Core foundations (pills stages 1 and 2). Nothing here has words of its own: the
manual test uses the dev clock on the dev database (`python main.py --dev`).

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| Q1 | 🤖 Auto | Times you type | `8pm`, `8 pm`, `8:30am`, `8.30 am`, `20:00`, `20.00`, `08:30`, `2030`, noon and midnight are read; `8`, `8:30`, `830` and `12` raise the question ("8am or 8pm?") with both readings; nonsense is refused with examples; every time is shown as `8:04 am` | ✅ Pass | 2026-10-09 | `tests/test_timeinput.py` |
| Q2 | 🤖 Auto | A time something was done at | Must be today, not in the future and not before the previous one, each refused with a short reason; a morning-or-evening time is settled when only one reading passes, still asked about when both do | ✅ Pass | 2026-10-09 | `tests/test_timeinput.py` |
| Q3 | 🤖 Auto | The day boundary | The day changes at midnight NZ whatever the UTC date; a local time on a day is a UTC moment; days are 23 and 25 hours long when the clocks change; "today" follows the bot's clock | ✅ Pass | 2026-10-09 | `tests/test_day.py` |
| Q4 | 🤖 Auto | The day rollover job | Exactly one is booked, for the end of today; listeners are told the day that ended and the day it is now, once, even after several days away; one failing is reported and the rest are still told; the next is always booked; a task that overrides `new_day` is a listener | ✅ Pass | 2026-10-09 | `tests/test_day.py` |
| Q5 | 🤖 Auto | The occurrence log | An occurrence starts pending with its plan and is never made twice or reset; done, skipped (by you or by the bot with a reason), missed, reopened and moved each record the values before and after; a change that changes nothing leaves no trace; changes made together are one change; taking the last one back restores everything it touched, is itself recorded, and is refused if anything changed again since; what is left pending from earlier days can be found; an item's history can be deleted for good | ✅ Pass | 2026-10-09 | `tests/test_occurrences.py` |
| Q6 | 🤖 Auto | The scheduler under a moved clock | Its time is the bot's clock; a jump runs everything that came due, each job booked by the one before included, in due order and not flagged late; a job already overdue before the jump is still late; jobs nobody handles don't keep the pass going | ✅ Pass | 2026-10-09 | `tests/test_scheduler.py` |
| Q7 | 👤 Manual | With `--dev`: `dev jobs`, then `dev clock 11:59pm`, `dev clock +2m`, `dev jobs` | First: a `core/day_rollover` job due at the coming midnight. After the two moves: it has run (a 🛠️ job card in #bot-log if verbose is on) and the next one is booked for the midnight after | ⬜ Untested | | |
| Q8 | 🤖 Auto | Cards (`core/cards.py`) | A component's id carries its task, action and argument, and buttons and dropdowns can't be mistaken for each other; cards Discord would refuse are refused with the reason; a press is answered first, then logged, then handled; a problem the presser can fix is told to them alone and anything else reported; someone else can't press; a form is the first answer and its submission comes back with what was typed | ✅ Pass | 2026-10-09 | `tests/test_cards.py` |
| Q9 | 🤖 Auto | Dates you type | today, tomorrow, "in 3 days", weekdays (always after today), "the 20th" (the next one, today included, skipping months without it), "20 Oct", "Oct 20", `20/10` day first, and ISO dates; nonsense refused with examples; a run of days shown as "10 to 16 Oct" | ✅ Pass | 2026-10-09 | `tests/test_timeinput.py` |

## R. Pills

R1 to R27 are the acceptance tests of the pills task, by the stage that builds
each one (see Notes); the rows after them were added with each stage.
Pills setup is due to be rebuilt, and R1 to R27 will be rewritten with it:
for now they describe what is built (stage 2) and what was planned. Run them on the dev database with the dev clock. A row joins
`docs/QA-RUN.md` when its stage is built; the 🤖 rows for each stage's logic
are added with it.

| ID | Type | Test | Expected result | Status | Date | Notes |
|---|---|---|---|---|---|---|
| R1 | 👤 Manual | Let the clock reach 6:00 am | The day's checklist appears in the hub without a notification, pills with no time listed first | ⬜ Untested | | Stage 3: not built yet |
| R2 | 👤 Manual | Choose a pill with no time from the checklist's dropdown | It shows ✅ and the time; the same message is edited, no new one | ⬜ Untested | | Stage 3: not built yet |
| R3 | 👤 Manual | Type that you took a pill, in plain words | The same result as using the dropdown | ⬜ Untested | | Stage 3: not built yet |
| R4 | 👤 Manual | Leave a pill with no time untaken until 8:00 pm | One reminder covering all of them, with the dropdown | ⬜ Untested | | Stage 3: not built yet |
| R5 | 👤 Manual | Let a pill with a fixed time come due | A prompt in the hub; the phone notification gives only a neutral label and the time, never the pill's name | ⬜ Untested | | Stage 4: not built yet |
| R6 | 👤 Manual | Press Taken on a prompt | The prompt goes; the checklist shows ✅ and the time | ⬜ Untested | | Stage 4: not built yet |
| R7 | 👤 Manual | Press Skip on a prompt | The prompt goes; the checklist shows ⏭️ | ⬜ Untested | | Stage 4: not built yet |
| R8 | 👤 Manual | Press Snooze on a prompt | The prompt stays and says until when; a fresh one arrives 15 minutes later | ⬜ Untested | | Stage 4: not built yet |
| R9 | 👤 Manual | Ignore a prompt completely | Three more nudges, then the prompt goes and the checklist shows ❌ missed | ⬜ Untested | | Stage 4: not built yet |
| R10 | 👤 Manual | Pill with a minimum gap of 3h: take dose 1 at 8:12 am | Dose 2 is due at 11:12 am and the checklist shows that time | ⬜ Untested | | Stage 5: not built yet |
| R11 | 👤 Manual | Then take dose 2 late, at 11:40 am | Dose 3 moves to 2:40 pm; the pill's configured plan is unchanged | ⬜ Untested | | Stage 5: not built yet |
| R12 | 👤 Manual | Take a dose only 2h after the one before | A question saying how long it has been and the minimum, with Log it / Cancel | ⬜ Untested | | Stage 5: not built yet |
| R13 | 👤 Manual | Look at a pending gap dose with plenty of day left | No take-by hint | ⬜ Untested | | Stage 5: not built yet |
| R14 | 👤 Manual | Look at the same dose within 2 hours of its take-by time | A ⚠️ take-by hint on its checklist line and its prompt | ⬜ Untested | | Stage 5: not built yet |
| R15 | 👤 Manual | Three doses, 2h apart: take dose 2 at 11:50 pm | Dose 3 is skipped by the bot straight away, with the reason; the streak is not broken | ⬜ Untested | | Stage 5: not built yet |
| R16 | 👤 Manual | Then correct dose 2 to 9:00 pm | Dose 3 is pending again, due 11:00 pm | ⬜ Untested | | Stage 5: not built yet |
| R17 | 👤 Manual | Add a pill “at 20:00” | The preview at once (no “I'm proposing… reply ok” first), and it and the saved pill show `8:00 pm` | ⬜ Untested | | Stage 2 |
| R18 | 👤 Manual | Add a pill “at 8” | Asked whether 8am or 8pm; nothing saved until answered | ⬜ Untested | | Stage 2 |
| R19 | 👤 Manual | Add a pill that is taken indefinitely | The preview at once; no dates are asked for or shown | ⬜ Untested | | Stage 2 |
| R20 | 👤 Manual | Use Taken at… with a time later than now | Refused with a short reason; nothing changes | ⬜ Untested | | Stage 4: not built yet |
| R21 | 👤 Manual | Say you didn't actually take a pill marked taken | It is pending again and the reply says what changed | ⬜ Untested | | Stage 5: not built yet |
| R22 | 👤 Manual | Say you took a dose at 9, not 10 | The time is corrected and later doses are worked out again | ⬜ Untested | | Stage 5: not built yet |
| R23 | 👤 Manual | Pause a pill | It moves to the ⏸️ Paused section of `pills` (and of the checklist, from stage 3) and is not prompted for | ⬜ Untested | | Stage 2 |
| R24 | 👤 Manual | Remove a pill | Asked to confirm; then gone from every list, with its history kept | ⬜ Untested | | Stage 2 |
| R25 | 👤 Manual | Reach the last day of a pill with an end date | It still appears that day and is listed as ended the day after | ⬜ Untested | | Stage 6: not built yet |
| R26 | 👤 Manual | Let midnight pass with a dose untouched | It shows ❌ missed; a fresh checklist arrives the next morning | ⬜ Untested | | Stage 6: not built yet |
| R27 | 👤 Manual | Restart the bot in the middle of a day | The checklist, any open prompts and today's due times are as they were | ⬜ Untested | | Stage 6: not built yet |
| R28 | 👤 Manual | `pills` with no pills yet | "## 💊 Pills" and how to add one; no dropdown; your word is deleted | ⬜ Untested | | Stage 2 |
| R29 | 👤 Manual | Say: `add course A, 3 times a day, at least 3 hours apart, with food, for 7 days starting tomorrow`; press **Save** | One step: the preview "💊 **Course A** · 3× daily, ≥3h apart · *with food* · <tomorrow> to <6 days later> · first dose when ready" with Save and Edit, no proposal, no "reply ok" and no extra line from Claude. After Save the same message reads "✅ Saved · 🗓️ **Course A** … · starts <tomorrow>" with no buttons | ⬜ Untested | | Stage 2. Failed 2026-10-09: a proposal in words, then a made-up run on "ok"; fixed, retest |
| R30 | 👤 Manual | Say `add night pill at 8pm`; press **Edit**; say `make it 9pm` | Edit adds a line saying to say what to change, buttons still there. After "make it 9pm" the old preview is gone and a new one shows `9:00 pm`; `pills` still doesn't list it | ⬜ Untested | | Stage 2 |
| R31 | 👤 Manual | With `--dev`: say `add zinc`, don't save, `dev clock +31m` | The preview disappears; `pills` doesn't list Zinc | ⬜ Untested | | Stage 2 |
| R32 | 👤 Manual | With a saved Evening pill: say `move the evening pill to 9pm`; press **Save** | "✏️ **Evening pill**" with "Now: … `8:00 pm`" and "New: … `9:00 pm`"; `pills` shows 8:00 pm until Save, then "✅ Updated · …" and 9:00 pm | ⬜ Untested | | Stage 2 |
| R33 | 👤 Manual | `pills`, pick a pill in the dropdown, press **Pause**, **Resume**, **Back** | The same message each time: the pill with Edit, Pause, Remove, Back; then "⏸️ … · paused" with Resume; then as before; then the list again | ⬜ Untested | | Stage 2 |
| R34 | 👤 Manual | Say `pause iron until the 20th`, then `pills`; then `resume iron` | "⏸️ **Iron** paused until 20 Oct." at once, with no question; Iron under ⏸️ Paused with "paused until 20 Oct"; then "▶️ **Iron** resumed." | ⬜ Untested | | Stage 2 |
| R35 | 👤 Manual | Say `delete iron and its history`; press **Delete for good** | A question that says its history goes too and can't be undone; then "🗑️ Deleted **Iron** and its history."; gone from `pills` | ⬜ Untested | | Stage 2 |
| R36 | 👤 Manual | Say `add magnesium`, restart the bot, then press **Save** on that preview | It is saved as if nothing had happened; `pills` lists it | ⬜ Untested | | Stage 2 |
| R37 | 🤖 Auto | Building a plan from what was said | Untimed, fixed and interval pills and courses with inclusive dates, each in its one-line wording; unclear times asked about one at a time and a bare gap never taken for hours; twenty kinds of nonsense refused with a short reason; an edit changes only what it names, `none` takes a value away, and changing the kind of schedule drops what belonged to the old one; active, upcoming, paused (ending by itself) and ended worked out from the day; the list in its three groups; a pill found by id, name or part of one, asked about when two fit | ✅ Pass | 2026-10-09 | `tests/test_pills_rules.py` |
| R38 | 🤖 Auto | Previews, the list and their buttons | Nothing is saved before Save, and Save can't be made to work while a time is unasked; the course sentence gives the course preview in one step, with nothing waiting for an ok; a changed preview replaces the old one and books one lapse; an unsaved preview lapses (deleted, or marked while clean-up is off); an edit shows old and new and changes nothing until Save; pause and resume act at once and tolerate repeats; remove asks and keeps the history, delete for good takes the doses of that pill only; buttons for a pill that has gone or is someone else's do nothing; every button on every card has an action; a tool call from Claude ends the turn on the preview with no closing line | ✅ Pass | 2026-10-09 | `tests/test_pills_plans.py` |
| R39 | 👤 Manual | Through block 16, read every reply from the bot | No reply says "I'm proposing" or "reply ok" for a pill; none shows a tool's name or how it was called (`pill_add …`); every time of day on a preview or list is written like `8:00 pm` | ⬜ Untested | | Stage 2. Failed 2026-10-09 on all three; fixed, retest. Claude's own wording of a time is asked for in the prompt, not enforced |
