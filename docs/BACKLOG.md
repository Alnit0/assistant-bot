# Backlog

Things found and not yet finished: failed manual tests (copied here by the
`qa` skill), and anything noticed while working on something else and left for later. Remove
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
| "Stop all timers called tea" got "I don't have a timer called tea" (2026-10-07) | Claude answered from memory without looking. The live state now comes with every message, and `timer_control` with `all` and a label matches in code, any case, every match; `stop` is cancel | N51 |
| "Cancel all timers" cancelled four and asked for the rest again (2026-10-07) | One call each ran into the limit of 5 per message. `timer_control` takes several ids or `all` in one call | N52 |
| Plain-word requests took 7 to 10 seconds, 30 or more after a restart | Strict tool schemas off; state sent with the message; no closing request after a confirmed action; Live edits and log cards in the background; 👀 on receipt | N50 |
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

From the run of 2026-10-07, 22:53 to 22:58 (reported as "paused timers
gained time"):

| Finding | What changed | Retest |
|---|---|---|
| Paused timers seemed to gain time (dinner 24s, then 2m 50s) | Nothing gained time: both were frozen at the right figures (dinner paused at 22:55:21 with 2m 50s, breakfast at 22:55:23 with 3m 36s). The 22:54 "Your timers" message was a snapshot whose countdowns ran on to the old end times. The list is now live: one per channel, rewritten on every change | G16 |
| Was dev speed involved? | Not that evening: the bot restarted at 22:52 and dev mode was never on. But the check found a real fault: pausing read dev mode's speed of the moment, so a timer started at 1x and paused at 60x would have gained 60 times its time left. Each clock now keeps the speed it was started at | G17 |
| A timer whose time was up could be paused at 0s | It is finished instead, and `pause all` leaves it alone and says so | G17, G19 |
| "Resume my tea timer": "Tea's running again – 9m 21s left", but tea stayed paused | `timer_control` was never called: Claude read the list and reported a change. The check only knew replies opening with "Done". It now also catches a change reported as news with nothing run; read tools end by saying nothing was changed; control tools report the state read back after saving | N41 |
| "Pause all timers" asked which, took four calls and left the Pomodoro | `pause all` / `resume all` are typed words (so no Claude call when typed) and tools; they include the Pomodoro unless told otherwise and list what was done | G21, N40 |
| "I don't have a record of what the times were" | `timers_events` records every change with the time left; `timer_history` reads it | N42 |

## Gaps against the conversation standard (2026-10-10)

What is left. The golden conversations are `tests/test_golden.py`; the
ones marked `gap` there are 1c, 1d and 2a, all waiting on G1. G1, G3,
G4 and G7 are deferred until pills reminders work; G14 comes with
reminders. G9 and G13 (the old path, the old `pills` list) were removed
at step 4.

| # | Gap | Layer | Size |
|---|---|---|---|
| G1 | Questions on the card: a card that asks, with a button per likely answer, no Save until answered, one question at a time, and a typed answer accepted too (golden 1c, 1d, 2a) | core (card, confirm, contract) and pills | large |
| G3 | A correction straight after Save works only by the "pill changed last" guess, so it is marked ❓, and only for pills (golden 2b) | core and each task | medium |
| G4 | Task ties are asked too readily: the router sees two exchanges and no record of what I have or did lately | router | medium |
| G7 | Questions still sent as their own message: "Which timer? Say its name.", "Which one: A or B?" for pills, and a plan that can't be built | tasks, then G1 | medium |
| G14 | Privacy of notifications is untested: nothing notifies about a pill yet | pills stage 3 | with reminders |

Done: dev bugs are numbered D1, D2… with a "dev" tag and a live number
is never reused; and, in batch 1 (2026-10-10), G2 (a reply to an older
card), G5 (✅ on a message that needs nothing), G6 (a neutral "not
understood"), G8 (a name Claude works out for a pronoun is put back for
the code), G10 (card kinds are new, change, remove), G11 (12-hour times
in bug posts and `dev why`) and G12 (a looser redirect replaces the old
card).

**`task-check` (step 5), as now planned.** It audits one task against the
conversation standard as well as the task contract: each principle in
order, each context rule, each card rule and each always / never line,
pass or fail per item with the evidence; it runs the golden
conversations that involve the task, and proposes new ones for what the
task adds; and it writes a QA block where every step says what to
press and the block starts with `dev clock reset`. First use: timers,
bugs and pills.

**Also at step 5:** the `new-task` skill reads the "Scaling notes" in
`docs/ARCHITECTURE.md` first; and the task contract's `hint` line goes
(it is no longer shown anywhere since "not understood" became neutral).

## Left for later

- **Left over from removing the old path** (step 4, 2026-10-10), for step
  5: `docs/DEVELOPMENT.md` "How to add a task" and the `add-task` skill
  still describe parts of the old way and are rewritten then; the
  `pills_drafts` table is unused; the cost reports keep the `tools`
  route for rows logged before the removal.
- **A pill whose doses can't fit is refused, not fixed** (decided
  2026-10-10; look again with G1). A planned time after the latest time,
  or doses that can't all fit before it, is shown on the card as it was
  read, with the reason and no Save; one reply puts it right. When
  questions on the card exist (G1) this could offer the likely fixes as
  buttons instead.
- **R1 to R27 in `docs/TESTING.md` still describe the old pills plan**
  (a dropdown on the checklist, stages 3 to 6). Rewrite them from the
  spec's acceptance tests as the checklist and reminders are built.
- **"How long is left on tea?" shows whole minutes only** (asked for
  2026-10-10). Use the same format as the paused card ("4m 18s left"),
  so time remaining reads the same everywhere.
- **The outgoing check does not cover every message.** What the timers,
  archive, bugs, lab and dev tasks send with discord.py directly does not
  pass `core/outgoing.py`. All of it is written in code, so nothing
  internal should be in it; it joins the check when the gateway layer
  exists.
- **Schedules with days of the week, in core** (after pills reminders;
  asked for 2026-10-10). Certain days only, different times on different
  days, every N days, skipping a day; shared by every task. Checked
  against what is stored now: a pill's plan is columns on `pills_pills`
  (kind, times as a JSON list, doses a day, minimum gap, start and end
  date), what is due on a day is worked out from the plan when the day
  starts and kept as rows in the occurrence log, and the scheduler only
  holds one-off jobs. So days can be added without a rewrite: a new
  column (or a small JSON rule) by migration, and one function that says
  whether a plan applies on a given day; rows already logged are
  untouched. The one thing to do first is move that function and the
  plan's schedule fields from `tasks/pills/rules.py` into core, so
  reminders and later tasks share them.
- **A notes task** (possible future task): keep a note and recall it
  ("note: call the dentist about Thursday", "what did I note about the
  dentist?"). Today a note such as "note one" is only a row in the
  message log; nothing can list it back.
- **Pin, archive and delete in plain words** ("pin that", "archive that",
  "delete my last message") were built and taken out on 2026-10-10: it
  was too easy to act on the wrong message. Reactions (📌, 📦, 🗑️) and
  reply words do all three. If it comes back, a reply should be the only
  way to say which message.
- **`dev qa <block>`: step through a QA block in Discord** (asked for
  2026-10-10, not built). One step of `docs/QA-RUN.md` at a time with
  Pass / Fail buttons; on Fail the trace of the last messages
  (`core/trace.py`) is captured with a note; the results are recorded in
  `docs/TESTING.md` (status, date, notes) and the summary recounted.
- **Why one "make it 2" didn't stick on 2026-10-09 is not known.** At
  21:20:41 a plain message straight after a card went to the router;
  nothing in the log says why. It now works either way (the card goes
  with the message), and the log says for every message whether the
  open card stuck and what the bot's latest message was.
- **Timers still take a length as text** ("5m", "90s"), read by
  `core/durations.py`. Pills now get lengths as whole minutes
  (`actions.MINUTES`); timers need seconds and a bare "5" that the code
  takes as minutes, so they were left as they are (2026-10-10). To
  decide: a seconds type for timers, with their fixtures and golden
  conversations 3 and 4 re-recorded.
- **Some refusals are still a bare line, not a card** (2026-10-10). A
  part that can't be read, and doses that can't fit, now get a card with
  no Save. What contradicts itself does not yet: one time for two doses,
  a gap with no number of doses, a name already in use. They need a
  question on the card (G1, golden conversation 1d).
- **`core/durations.py` has the timers' limits in it** (5 seconds to 24
  hours, worded for timers), though pills and dev read lengths with it.
- **`reset` is a bare verb that is still a shortcut** (it clears the chat
  memory). It predates the rule that shortcuts carry their task's name
  and is not in `GENERIC_VERBS`; rename it when a second task wants a
  reset (noted 2026-10-09).
- **Pills setup and the way Claude is handed tools are due to be
  rebuilt** (2026-10-09). Until then the reply guards, the
  single-confirmation rule (`confirms_itself`) and the candidate buttons
  are interim, and the `pills` list with its dropdown stays as it is: it
  is not rewritten when a pill changes, so type `pills` again to see the
  current state. No setup features are to be added meanwhile.
- **The Edit buttons on a pill need Claude**, so they only lead anywhere
  in a channel where plain words reach it (#inbox).
- **More than 25 pills:** the list's dropdown shows the first 25 by name.
- **`python -m tasks.bugs.cli` always reads the live database.** It has
  no `--dev`, so a bug reported while testing on the dev database can't
  be read by Claude Code's `bug` skill (found 2026-10-09, stage 1 of
  pills).
- **Timer cards under a moved dev clock** show Discord's own countdown
  ("ends in…"), which goes by the real time: after `dev clock +2h` a
  running timer's card is wrong until it finishes. The timer itself ends
  on the bot's clock. Dev database only.
- **`dev reset-db` leaves cards behind in Discord** (timers, boards,
  panels) whose records are gone; pressing their buttons fails politely.
  A restart clears what is held in memory.

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

## Bugs: left for later

Built on 2026-10-09 and unit tested; the manual rows (P12 to P24, P28,
P29, M5) are ⬜ Untested in `docs/TESTING.md`.

- **Promote forum handling to core when another task needs it.** Posts,
  tags and persistent buttons live in `tasks/bugs/posts.py`, the only
  place in that task allowed to use discord.py.
- **Screenshots in a bug's post aren't recorded.** A note is the text of
  a message; one with only a picture has no text and is skipped. The
  picture stays in the post.
- **Writing in a closed post reopens it in Discord only.** Discord
  unarchives the post, and the note is saved, but the bug stays Fixed or
  Won't fix with its tag until you press Re-open.
- **A note from Claude Code doesn't update the card's count.** The
  command line writes to the database without the bot; the count catches
  up the next time you write a note or press a button.
- **Posts closed before Re-open existed keep their two buttons** until
  one is pressed, which puts the card right (and says "Already closed").
- **A report whose post can't be made leaves a record without a post**
  (Discord refusing after the forum was found). `bugs` lists it without a
  link.
- **Errors are read from `bot.log` only**, not the rotated files, so a
  report made just after the log rolled over (about every 1MB) may miss
  them.
- **A hand-made post in #bugs is ignored**: what is written there is
  neither saved nor sent to Claude.
- **Typed words wait for the post.** `bug` answers once the forum post
  and its four follow-up messages are sent (a few seconds).
- **`KEEP_CONFIRMATIONS` makes channels busier**, and most manual tests
  expect confirmations to vanish: run QA with it off (the run sheet says
  so).

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
- **The "done" check still goes by wording.** It knows a reply that
  opens with "Done" or ✅, a made-up tool note, and a change reported as
  news ("running again", "I've paused", "is now", "has been", "all
  three paused"). "Your tea timer is running, 9m left" after only a
  look reads like a description and gets through. The lasting answer is
  fewer chances to slip: the state given to Claude with each message, so
  the action is its first call (item 3 of the speed plan below).
- **Natural-language requests are slow, and the plan is waiting on four
  answers.** Proposed: timings on the card, state in the user turn, no
  second Claude call when the result is already shown, 👀 on receipt.
  Open: harness or manual timing; whether skipping the last call may cut
  a multi-step request short; lasting or self-deleting result line; 👀
  as well as typing. Since then, typed `pause all` / `resume all` need
  no Claude call at all.
- **Lists posted before this change are still snapshots.** Old "Your
  timers" messages aren't tracked and go on counting down; delete them.
- **Events start with this change.** Nothing before it is in
  `timers_events`, and Claude says so when asked.
- **Discord rate-limited the board** during the four-call pause (a 429
  on its edit, retried after 3s). `pause all` now refreshes once; a card,
  the board and each live list are still one edit each per change.
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
- **A false "it's running again" straight after a read is no longer
  caught** (2026-10-09). The wider honesty check now only questions a
  reply when no tool succeeded at all, so a true account after
  `timer_history` is not sent back; the price is the 22:56 case of
  2026-10-07 (`list_timers`, then "Tea's running again" with nothing
  resumed). Less likely now that the state comes with the message and
  the read tools are rarely called. A flat "Done" is still caught.
- **A request whose second step needs the first one's result stops
  after the first** ("start a timer and pin it"): a confirmed action
  ends the turn. Ask for the second step separately.
- **The speed-up is measured on Claude's side only** (benchmark with
  canned tools: 1.3 to 1.5s, one round trip). The live numbers in
  Discord, with the real sends, are N50 to N52.
- **Typed words still wait for their #bot-log card** and Live edits
  made from buttons are unchanged; only tool calls moved theirs to the
  background.
- **The prompt cache lasts 5 minutes**, so a message after a quiet
  spell rewrites it (about 1.7s instead of 1.3s). A 1-hour cache would
  cost double to write.
- **`pause all` through Claude and `timer_control` with `all` overlap**:
  the first includes the Pomodoro, the second is timers only.
