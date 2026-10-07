# Backlog

Things found and not yet finished: failed manual tests (copied here by the
`qa` skill), and anything noticed during a task and left for later. Remove
an item once it is fixed and its tests pass.

## Fixed in code, waiting for a manual retest

From the QA findings of 2026-10-07. Each is done and unit tested; the rows
in `docs/TESTING.md` are ⬜ Untested until they are run in Discord.

| Finding | What changed | Retest |
|---|---|---|
| Useful messages (seed instructions) deleted themselves; no single rule for what is deleted | One lifecycle policy (`core/lifecycle.py`); `dev cleanup on\|off`; the class shown by `dev inspect` | J22, J28, J29 |
| An invalid reaction or reply action sat through the debounce before failing | Checked at once: ⚠️ plus a short self-deleting reason; only valid actions are debounced | C6, C12, D13, E12 |
| Replying `pin` (or `pin me`, `pin this`) did nothing | There was no `pin` reply action: `pin` / `unpin` added, and filler words accepted on every reply action | L9, L10, L11, D15 |
| "Hive" was hard-coded | `ASSISTANT_NAME` setting | K10 |
| `pomo` while a session runs was an error | It re-shows the card (or points to it from another channel); `dev off` when off and a second `lab channels` no longer fail either | H9, H17, J30, B21 |
| Claude offered to do things it has no tool for | Its instructions always say it has no tools and must never offer to act | A17 |

From the first run of tool calling against the real API (2026-10-07,
18:34 to 18:51):

| Finding | What changed | Retest |
|---|---|---|
| Claude couldn't say what was running or how long was left ("check the channel above") | `list_timers` and `get_pomodoro_status` read the live state from the database | N29 |
| Pause, resume, cancel and extend searched the last 20 messages for the timer ("I don't see a Pomodoro session" while one ran); no `unpause` | `timer_control` and `pomodoro_control` act by the id the read tools give; the reply actions are no longer offered to Claude; `unpause` added as a reply word | N30 |
| "✅ Done." with no tool call and no timer; "Done." twice to `dev mode off` / `on` | Nothing is added to Claude's replies in the history (it was copying the note); a "done" with nothing run is sent back to it once, then overruled, with a #bot-log card | N31 |
| "[Tool calls this turn: …]" at the end of replies | The note is gone from the history, and any that Claude writes is taken out before sending | N32 |
| `dev mode on` / `dev mode off` were not words | `dev mode on\|off` added | J32 |
| Claude couldn't switch dev mode on | The switch is offered to it always (owner only); the other dev tools still only while dev mode is on | N33 |
| "Look further back" could only see the last 20 messages | `search_messages` looks through your logged messages in the channel (500, 30 days) and asks before acting on a match | N34 |
| A Pomodoro asked for while one was going: card again, a note, the alert and Claude's reply; the lengths asked for ignored | Through Claude: one reply, nothing posted, and an offer to restart at those lengths. Typed: the card and one Restart question | H19, H21 |

## Left for later

- **"Alex" and "Auckland, New Zealand" are still hard-coded** in Claude's
  system prompt (`core/llm.py`). They belong with the user record (name,
  time zone) once there is more than one user.
- **Unpinning by reply doesn't clear an applied 📌.** If a message was kept
  with 📌 and is then unpinned by replying `unpin`, the 📌 and its ✅ stay
  and `dev inspect` still says "Kept: yes". Removing the 📌 puts it right.
- **A refused reaction is forgotten by a restart.** The ⚠️ added when a
  reaction is refused is cleared when the reaction is taken off, but only
  while the bot remembers refusing it (in memory). After a restart the ⚠️
  has to be removed by hand.
- **Only archive and delete are checked at once.** Other reactions and
  reply actions have no `validate` yet (📌 at the pin limit still fails
  after the wait, since only Discord knows the channel is full).
- **`dev cleanup off` leaves working buttons behind.** Alerts and old
  Pomodoro cards that would have been deleted stay with their buttons;
  pressing one puts things right but can look odd. It also leaves a second,
  unpinned dev panel when the panel is re-shown.
- **Lab messages are outside the lifecycle.** Lab tests are exempt from the
  clean-up rules, so they don't declare a class and read as Kept.
- **`dev inspect` forgets Transient after a restart.** Which notes were
  self-deleting is held in memory (the last 500), so one left on screen by
  `dev cleanup off` reads as Kept after a restart.
- **The nightly sweep is not built.** Kept messages are never removed
  automatically until it is; when built it must skip Protected ones.

## Found in that run, left for later

- **Bulk and cross-channel actions** ("archive all messages in #dev"):
  Claude can only act on one message at a time, in the channel it is
  chatting in. Wanted: it works out which messages, says how many, and
  nothing happens until a Confirm that shows the count.
- **An old paused timer never draws attention to itself.** Timer 3
  ("tea", started 13:41 on 2026-10-07) was paused by a reply at 13:47
  with 4s left, given `+10m`, and never resumed: it sat on the board all
  day and was taken for the evening's "tea" timer, which had finished. It
  is still paused. Timers 7, 8 and 9 have finished with their alerts
  never dismissed. Something should nudge about these, or expire them.
- **Two timers with the same label** look alike in a reply; Claude is
  told to ask which when a label fits more than one.
- **`search_messages` only finds your own messages that the bot handled**
  (chat, typed words that stayed). The bot's replies have no row of their
  own in `message_log`, so "archive what you said about Spain" finds
  nothing further back than the last 20. A fallback to Discord's own
  history (slower: 100 messages a request) would cover it.
- **Refs from a listing last for one message.** "yes" to "delete m3?"
  costs a refused call and a second listing before it works.
- **Claude no longer remembers what it ran**, only what it said. It reads
  timers afresh each time; for anything else ("undo that pin") it has
  its own words to go on, or a new listing.
- **The "done" check goes by wording** (a reply opening with "Done" or
  ✅, or carrying a made-up tool note). "Your timer is running" with
  nothing run would get through; the #bot-log card for the check shows
  how often the narrow one fires, which says whether to widen it.
- **Timer actions through Claude have no Undo button** now that they go
  by id; ask it to resume or pause again instead.

## Tool calling: left for later

Built on 2026-10-07 and unit tested with a mocked Claude. First run against
the real API the same day: the schemas were accepted and the cache was
read on every message after the first (4,973 tokens, 6,996 with the dev tools).

- **Every chat message now carries the tools**, used or not ("Tool tokens"
  on the card). If that cost matters, the next step is to send them only
  when the message looks like a request.
- **A protected message deleted through Claude asks twice**: Claude's
  Confirm / Cancel, then the existing "That message is pinned" question.
- **Proposals and button questions are held in memory.** A restart forgets
  a pending "ok", an Undo button and a "Which message?" question.
- **Undo exists only where an action declares one**: pin, unpin and
  archive. Cancelling a timer or extending one cannot be undone.
- **Claude only chats in #inbox**, so the "dev tools in the dev channel"
  rule has no effect until chat is enabled there.
- **Reactions are not tools.** Claude tells you which one to add.
- **Recent messages go to the API when Claude looks for a target**: up to
  20 one-line previews from the channel when it calls `recent_messages`,
  and up to 5 older ones when it calls `search_messages`.
