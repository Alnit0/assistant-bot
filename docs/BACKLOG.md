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

## Found by `task-check` (2026-10-12)

The first run of the skill, on timers, bugs and pills, in the standard's
own order of importance. "Size" is how big the fix looks.

Decided 2026-10-12. **Fixed:** C1 and C2 (refusals written for me), C3
(timers read back), C5 (a reply to a dose's message), C6 (a guessed pill
goes on a card), C9 (no ✅ on a note in a bug's post) and C11 (12-hour
text, not Discord's clock). **Fixed in the background batch of
2026-10-12:** C4 (a bug and a note are read back), C10 ("show my open
bugs" is a Live list), C13 (a pill's name is compared as core compares
names) and C20 (the bugs task's plain words are in `plain.py`, and only
`posts.py` uses discord.py). **Fixed on Alex's answers, 2026-10-12:**
C12 (`show_existing` in the contract, declared by bugs), C15 (the
occurrence log keeps a `cause` beside the reason) and C16 (a pill's
settings are taken away by a `clear` list, never the word "none").
**Until G1:** C7 and C8. **Until gym is built:** C19 (gym is the second
task that needs name matching: move it to core then). **Left, timers**
(a proof of concept that may be scrapped): C8, C14, C17 and C18.

| # | Task | What | Where | Rule | Layer | Size |
|---|---|---|---|---|---|---|
| C7 | pills | Questions sent as a line of their own: "Which pill?", "Which one: A or B?", "What is the pill called?", "How many times a day?", "Is the gap 3 hours or 3 minutes?" | `tasks/pills/rules.py:221`, `:262`, `:301`, `:550`, `:564`; `tasks/pills/plain.py:792` | Never: a question as a separate message (G7, then G1) | task, then core | medium |
| C8 | timers | The same: "Which timer? Say its name.", and `pomo` with other lengths asks "Restart it as `50/10`?" in a message of its own | `tasks/timers/plain.py:152`, `tasks/timers/sessions.py:238-239` | The same (G7) | task, then core | medium |
| C14 | timers | Lengths are handed over as text ("5m", "50/10") and several ids as one text ("t12 t14") | `tasks/timers/plain.py:359`, `:457`; `tasks/timers/status.py:51-63`, `tasks/timers/pomodoro.py:55-79` | Contract: structured values (decided 2026-10-10 to leave) | schema, fixtures | medium |
| C17 | timers | Words Claude might send for "the session" are accepted as a set ("current", "it", "pomodoro"…) | `tasks/timers/control.py:22` | Word lists (not listed below until now) | schema (`@that`) | small |
| C18 | timers | Its own live lists ("Your timers", one a channel) beside `core/livelists.py`; its own send, edit and delete helpers beside `core/cards.py` | `tasks/timers/board.py:79-112`, `tasks/timers/store.py` (`timers_lists`), `tasks/timers/common.py:22-58` | Core or task: plumbing | core | medium |
| C19 | pills | "Which of my things does this name mean" (whole name, then part, then ask) and laying a reply over an open card are general, and live in the task | `tasks/pills/rules.py:541-568`, `tasks/pills/plain.py:69` | Core or task: a general tool. **Move it to core when gym is built**: gym is the second task that needs it (exercise names), decided 2026-10-12 | core | medium |

Known gaps the run met again, already listed above: G1 (golden 1c, 1d,
2a), G3 (golden 2b passes only by the "pill changed last" guess), G14
(nothing notifies about a pill yet). One fixture has no recording
("how long left on tea?").

## Word lists and phrase patterns in Python (2026-10-10)

Language is Claude's job and rules are Python's (see the Scaling notes in
`docs/ARCHITECTURE.md`): these are safety nets, listed so that none grows
into the way something is understood. "Replace" says whether a change to
a schema could take its place.

| Where | What it reads | Why it is there | Replace with a schema change? |
|---|---|---|---|
| `routing.named_alone` | A task's name alone, or after "show", "list", "see", "open", "what are my" | Shows a list with no request at all | No: its point is to ask nothing |
| `routing.names_item` | One of my pills' or running timers' names, whole, in a message the router called "nothing" | A message that names one of my things is never dropped in silence | No: it checks the router, and only says whose the message is |
| `routing.named_destinations` | "to my pills", "on the shopping list" | A destination I name decides the task, whatever the router says | Partly: the router could return `named` beside the task; kept in code because the router got it wrong in QA |
| `confirm.redirect` (`_NO`, `_FOR`) | "no, shopping", "I meant packing", "shopping instead" | Moves a card to another task with one request instead of two | Partly: the follow-up extraction already has `not_this`; this only saves the router's request |
| `confirm.is_correction` (`_CORRECTION`) | A message that starts "no, …" | Undoes the card's last change before applying the correction | Yes: a `corrects` yes/no in the follow-up's answer |
| `actions.as_references` (`_POINTING`, `_SMALL_WORDS`) | "it", "that", "this", "them", and whether the message names the thing | Puts back a name Claude worked out for a pronoun | No: it checks the schema's own `@that` |
| `actions.unstated` (`_is_stated`, `_NUMBER_WORDS`) | Whether a guessed value is in the message word for word | A value I stated is never marked ❓ | No: it checks `guessed` |
| `actions.unchosen` (`_HALF_MARKED`, `_PART_OF_DAY`) | am, pm, "morning", "evening", a 24-hour time | Takes back an am or pm Claude chose by itself | No: it checks the fixed form of a time |
| `actions.whole_part` (`_DANGLING_END`, `_DANGLING_START`) | "of", "and", "the", "at"… left hanging at an end of a leftover | A "Not included" part is whole words, never cut off mid-phrase ("dose 1 of") | No: it checks `not_included`, whose description now asks for whole parts |
| `actions.is_filler` (`_FILLER`) | "and", "also", "please", "too"… | Joining words are never reported as "Not included" | No: it checks `not_included` |
| `actions._structured` (`_BETWEEN_TIMES`) | Times sent as one text ("8am, 8pm") | A list of times that arrived as text is still read | Already replaced (`TIMES`); this is the net under it |
| `core/durations.py` spoken forms | "3 hours apart", "an hour and a half", number words | A length that arrived as words is still read | Already replaced for pills (`MINUTES`). Timers still take "5m" as text: left so for now (decided 2026-10-10), a seconds type would replace it |
| `core/timeinput.py` times | `8pm`, `20:00`, `noon`, `midnight` | Reads the fixed form, and any other that arrives | Already replaced (`TIME`); also reads what I type into a form |
| `core/timeinput.py` dates | "tomorrow", "friday", "the 20th", "20 Oct", "in 3 days" | The only reader of dates: they still come as I said them | Yes: a structured date (a weekday, a day of the month, a number of days from today). Not an ISO date from Claude: it doesn't know today |
| `pills/rules.py` `_COUNT`, `_COUNT_WORDS`, `_days` | "twice", "3 times a day", "7 days" | Text for a number that should be a number | Already replaced (`per_day` and `days` are integers) |
| `pills/rules.py` `_TIME_SEPARATOR` | "8am, 8pm", "8 and 20:00" | The times of a request, joined up inside the task | Already replaced (`TIMES`) |
| `timers/pomodoro.py` `parse_session` | "50/10", "50 and 10" in `lengths` | A session's lengths, handed over as text | Yes: focus and break as two `MINUTES` fields |
| `livelists.sticks` | A message of 8 words or fewer after a list | Sends a short follow-up to the list's task first | No: it is a length, not a wording; extraction can still say `not_this` |
| `outgoing.acknowledges` (`_ACKNOWLEDGES`) | "Got it", "Noted", "Done", "So you took…" at the start of a chat reply | Chat is told never to acknowledge something I did; this stops one that slips through from being sent | No: chat's reply has no schema. The router's `reports_doing` is the structured half |
| `outgoing.without_offer` (`_OFFER`) | "want me to…?", "anything else?" at the end of a chat reply | Plain chat is free text, and is told not to offer; this trims one that slips through | No: chat's reply has no schema |
| `timers/control.py` `_THE_SESSION` | "current", "it", "pomodoro", "session" as the session's id | Whatever Claude sends for "the session" still finds it | Yes: `@that`, as for timers (C17) |
| `core/router.py` (`GENERIC_VERBS`, fillers), `timers/control.py` (`_SCOPE_WORDS`…) | Typed words: `pause all timers`, "pin this" | Typed shortcuts never go to Claude, by design | No |

## Gym: what its spec would add to core (2026-10-12)

From the core or task rule, for a yes before any of it is built (the
spec is `docs/specs/gym.md`, section 12):

- **Attachments on a request** (plumbing): a message's files reach a
  task's plain-words code, and the router is told a file is attached.
- **A decimal number in the contract**: a weight is 62.5; today a field
  is text, a whole number or minutes.
- **Name matching** moves out of pills (C19): gym is the second task
  that needs it.
- **Days of the week in the schedule model**, only if workouts go by
  weekday (already listed below).
- Built inside the task, apart, until a second task needs them:
  reading a grid from a file, mapping headings to a fixed set of
  fields, and comparing two lists of records into `field · old → new`.

## Left for later

- **Two running timers with the same name both get the change** (found
  live, 2026-10-12; **low priority**: timers are a proof of concept and
  may be scrapped): with two called "tea", "give tea more time" adds to
  both. Later: a second timer with a name already running becomes "tea
  2", then "tea 3", shown that way everywhere. Skipped in the background
  batch of 2026-10-12 on Alex's word.
- **Left by the timer reply fix** (2026-10-12):
  - **Pills lines not recorded as a pill's**: the line after Remove or
    Delete for good (the pill has gone), and a line that only says a
    pill couldn't be found.
- **Left by the task-check fixes** (2026-10-12):
  - **One fixture is not recorded**: "how long left on tea?" (timers).
  - **A reply to the checklist only says which pill when one pill is on
    it.** With several, "it" is still the pill logged last, or the bot
    asks which. A reply to a dose's own Taken / Skip message is exact.
  - **A reply to a bug's "🐞 Logged as B4" line, or to a card that has
    been saved or cancelled, is still the router's to place**: bugs
    declares no message of its own, and a closed card belongs to none.
  - **A timer that didn't save can't be shown in Discord**: C3 is
    covered by unit tests only.
  - **The archive's "Originally posted" and the dev tools' job times are
    still Discord's own timestamps.** Doses, timers and bug posts are
    ours now.
- **From the small batch of 2026-10-12** (identity, #commands, mock-ups):
  - **One fixture is not recorded.** "how long left on tea?" is now the
    action `timer_left`; its fixture in `evals/fixtures/timers.json` has
    no recording, so its replay is skipped until the timers fixtures are
    run live once (one request).
  - **`dev clean` does not remove a mock-up.** A Components V2 message
    has no text to carry the test-data mark. Delete one with 🗑️.
  - **The reset card lists what "Delete all" would post again.** With
    "Delete all unpinned" a pinned board is kept, not posted again; the
    line reads the same either way.
  - **#commands reads the bot's last 200 messages there**, shows a
    plain-words action only by what one might type (its description is
    written for Claude), and writes what a task is for from its "only
    for" line by rule, which reads a little stiffly for some tasks.
  - **The status shows dev mode in front of the line** ("🛠️ Dev mode ·
    🟢 Live · …"), as the old status did. Not asked for either way.
  - **The header of `docs/QA-RUN.md` still counts the tests as of
    2026-10-10.**
- **Left over from removing the old path** (step 4, 2026-10-10): the
  `pills_drafts` table is unused; the cost reports keep the `tools`
  route for rows logged before the removal; "How to add a task" in
  `docs/DEVELOPMENT.md` still says in places that Claude is given a
  word's description.
- **A pill whose doses can't fit is refused, not fixed** (decided
  2026-10-10; look again with G1). A planned time after the latest time,
  or doses that can't all fit before it, is shown on the card as it was
  read, with the reason and no Save; one reply puts it right. When
  questions on the card exist (G1) this could offer the likely fixes as
  buttons instead.
- **R5 to R22 and R25 in `docs/TESTING.md` still describe the old pills
  plan** (stages 4 to 6). Rewrite them from the acceptance tests as
  reminders and corrections are built. (R1 to R4, R23, R26 and R27 were
  rewritten with the checklist, 2026-10-10.)
- **The lab's buttons keep their own colours** (2026-10-11). The lab is
  the bench for Discord's own features, and its toggles use grey for
  "off" on purpose; the colour rule was applied everywhere else.
- **Housekeeping, left as it is** (2026-10-11): `reset` (it clears the
  chat's memory and says so for 5 seconds, or for good while
  confirmations are kept) and `dev clean` are not counted as
  housekeeping. Say if they should be.
- **Channel reset, left as it is** (2026-10-11):
  - In plain words it works where the bot listens (#inbox and the hub);
    everywhere else it is the typed `reset channel`.
  - A finished timer's alert that was waiting to be dismissed, and a
    Pomodoro phase notice, are not posted again: only what is still
    running is. A "Your timers" list that went is forgotten, not
    re-posted.
  - The timers board and the dev panel coming back are covered by the
    manual test only (their code is discord.py); the checklist and the
    timer cards have unit tests.
  - Attachments are not downloaded with the transcript, only their
    links, and Discord's links die with the message. Download them too
    if that is ever needed.
  - The router's catalogue gained an entry. Only the new fixtures were
    run live (6 of 6); a full live eval has not been run since.
- **The dev clock outlives the dev database.** Its offset is in
  `data/dev-clock.json`: deleting `dev.db` by hand (not `dev reset-db`)
  leaves the clock where it was, so a "fresh" database can start a day
  ahead without saying so (seen in QA, 2026-10-10). The dev panel shows
  the clock, but only when dev mode is on. Worth a line on the start
  card when the clock is moved.
- **"🧪 dev test data" under every dev tool's reply** (asked about
  2026-10-12). It is the mark `dev clean` looks for, and is put on
  `dev jobs`, `dev status` and `dev inspect` as well as on seeded
  samples, so on the live bot it reads as if the jobs were test data.
  They are not. To do if wanted: a second mark, "🧪 dev tool", for
  tool output, with `dev clean` removing both.
- **After midnight, logging yesterday's doses** (asked for 2026-10-12).
  "I took it at 9pm" said at 12:30 am means yesterday. Until about
  4:00 am, a time later than now refers to yesterday's checklist, shown
  on a card first. Today it is refused ("hasn't happened yet").
- **Switching task straight after an answer costs one more request**
  (2026-10-12): a short message within five minutes of a task's answer
  goes to that task first, and only on to the router if it says the
  message isn't its own. A follow-up to the same task costs one request
  fewer than before.
- **Left for pills stage 3, with reminders**: there is no take-by hint,
  and taking a dose sooner than the gap is not asked about (it is logged
  as the next dose). A timed dose has no buttons until it has a prompt:
  until then it is ticked off by saying so. (Automatic skips and the
  latest time ending a pill's day were brought forward, 2026-10-12.)
- **Left for pills stage 4**: "I took it at 9, not 10" said long after
  with no dose number, and "undo that". (Correcting the dose just
  logged, "it" for the pill logged last, and correcting any dose by its
  number were brought forward, 2026-10-12.)
- **A Pomodoro left waiting for Start for more than 2 hours ends
  itself**, with a line in #bot-log (asked for 2026-10-12).
- **`reset channel` from #inbox for another channel by name** ("reset
  #bot-log"); forum channels are excluded with a plain reason (asked for
  2026-10-12).
- **The section provider interface** (for a morning brief) is not built:
  nothing would use it yet. `core/hub.py` has the hub channel and the
  progress bar only.
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
  takes as minutes, so they stay as text for now (decided 2026-10-10).
  When it is done: a seconds type for timers, with their fixtures and
  golden conversations 3 and 4 re-recorded.
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
