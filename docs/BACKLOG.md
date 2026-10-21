# Backlog

Things found and not yet finished. **The list** below is the one place
that says what comes first; under it, **Details** keeps what was found,
where and why, as it was written at the time. An item leaves the list
when it is fixed and its tests pass, or when a line under "Removed" says
why it went.

Tidied on 2026-10-13: one list in three groups, timers apart and marked
low priority, nothing dropped without a reason.

## The list

### Next

Put in the order of the priorities of 2026-10-14 (the hub's look and
how it reads, then how well it understands, then everything else).
What was here and is done has gone: the QA of blocks 27 to 42 as one
run (the self-test covers most of them: `docs/QA-RUN.md` says which),
reminders on live, the scheduler, the clean-up and the briefing, and
the full self-test run.

1. **Live in its own folder, running a committed version** (question
   34, put on top by Alex on 2026-10-15: the next infrastructure job).
   **Prepared and dry-run on 2026-10-15** (`docs/LIVE-FOLDER.md`,
   `scripts\setup-live-folder.ps1 -Ref`, `scripts\update-live.ps1`):
   the switch-over waits for his go-ahead at a later restart. Live runs from the project folder today, so a restart
   loads whatever is in the working copy. On 2026-10-15 Windows Update
   restarted the PC twice overnight (00:23 and 00:26) and live came back
   on a batch's uncommitted, unreviewed changes; the 3 am self-test then
   ran on them too and failed five steps (D6). From its own folder on a
   commit (`scripts\setup-live-folder.ps1`), a reboot never loads work in
   progress. The merge of `feature/pills` into `main` comes with it once
   Alex has read `docs/REVIEW.md` and run QA blocks 53 to 55 (33).
2. **The hub's look.** Round 4 is live (2026-10-15). Next: his answers
   to questions 68 to 75, from the replay of a day in the hub
   (`python -m selftest.day`, posted in the Design forum): the order
   when a routine's card comes up mid-day, two Today counts, the same
   thing in three places, the briefing's boxes moving about.
3. **What the briefing shows**: whatever Alex's look at the real hub
   turns up.
4. **How well it understands**: a correction straight after Save for
   schedules, as pills have ("no, 7pm": question 8, yes, later); task
   ties asked too often (G4); "is the gym on tonight?" comes back as
   chat (x16, a known miss: chat hands it back, one request more).
5. **Personal routines reworked** with groups of steps, one button a
   group (question 63, to discuss first; `HABITS_ENABLED` stays off),
   and **gym onboarding** designed before gym is built (24 to 28). The
   calendar after: Google, read only, by its private link, names matched
   by code (29 to 32 answered; not built).

### Soon

- **"Will it rain?" with a card open (golden 28a)** goes to chat, every time, with the gym on and off (18 Oct,
  the router check): found, not tonight's. The card stays open either way.
- **Gym, next**: a photo of a handwritten log is read by the smart inbox's vision and sorted into a gym item
  in words, as any item is; worth a recorded check with a made-up photo. The sheet mirror waits for Alex's
  sheet (docs/GYM-SHEET-SETUP.md).

- **Round 6 in the hub itself** (17 Oct): `core/timeline.py` is the layout and its preview is posted; when Alex
  picks it, each card becomes a message in a fixed slot of the hub, rewritten in place, with the doses' cards
  moved by the existing rules, and the conversation tidy (10 minutes after an exchange; What's new and restart
  notes gone by noon). Gathered through the contract (`Entry.plan`, the Today lines), with the done line's
  names and times from each task.
- **The week view's past days** (17 Oct): the calendar's copy keeps yesterday to two months ahead, so this
  week's Monday seen on a Thursday has no events. Keeping a week back would fill it.
- **Pills in a plan for today** are the doses still to take; the week view's count for today shrinks as doses
  are taken. A count of the day's planned doses would read steadier.

- **The new hub tasks, left for later** (built 2026-10-15, off in live):
  self-test steps for to-dos, reminders and personal routines (none
  yet: the month's self-test spend was gone, and they are off); a
  card's question, with a button each, when a name fits two to-dos,
  reminders or steps (today it is said back in a line); a look back over
  days (`tally`) for to-dos and personal routines, so "how did the week
  go?" counts them; the pills card's page title made like theirs, or
  theirs like it (question 64).
- **A "flavour" status line when there is nothing to show** (asked
  2026-10-14, for later): when the attention model has nothing at
  levels 1 to 4, the status line is not blank but one light line: my
  streak ("🔥 5 days in a row"), the weather as a mood, a line in the
  bot's own voice late at night, or a countdown I set. Anything real always outranks
  it, and it changes at most a few times a day. It would be a level
  below "nothing" in `core/attention.py` (`docs/DESIGN.md`, "The
  status line", level 5), never a pill's name, and sent to Discord
  only when it reads differently, as the line is today.
- **Changing where an alert goes by words, with a card** (said
  2026-10-13): "send pill reminders to my phone only" shows a confirm
  card (`where · both → ntfy`) and Save changes it. The table stays in
  the code (`KINDS` in `core/notify.py`) as the default; what I change
  would be a row over it.
- **The offline card in the new look** ("I was offline when you sent
  this"): plain for now, to follow `CARDS_V2` (said 2026-10-13).
- **A routine's steps by words** (asked 2026-10-13, later): change
  their order, and take a step out. Today the steps and their order
  come from the code (tidy, briefing, checklist).

7. **Pills stage 4**: a correction said long after ("I took it at 9,
   not 10"), and G3 (a correction straight after Save rests on a guess).
8. **Show a streak**, with stage 4 (decided 2026-10-13): counted in
   days, one for all pills on the checklist, one a pill later in
   history. The logic is built. Also **the take-by line on the
   checklist** and a weekly summary.
9. **Yesterday's doses after midnight** ("After midnight, logging
   yesterday's doses").
10. **The rest of the cards in the new look**, and with it: one way to
    tick a dose off from a button (three near copies), `dev mock` on
    the design's own records, the old plain checklist retired.
11. **Costs**: shorten the router's rules and the tasks' "only for"
    lines with a live eval (`docs/COSTS.md`), if wanted: the router is
    US$0.0040 a message in words now (15 Oct), up from US$0.0026. Skipping the router for a message
    that names a pill was turned down (2026-10-13).
12. **Days of the week in the schedule model**, in core (wanted by gym
    if workouts go by weekday, and by reminders after pills). Comes
    with the scheduler (6a): one "which days" for both.
13. **G4**: task ties are asked too readily.
14. **A reaction made just before a stop is lost**: keep waiting
    reactions in the database.
16. **The outgoing check does not cover every message**, and **some
    refusals are still a bare line, not a card**.
17. **R5 to R22 and R25 in `docs/TESTING.md`** still describe the old
    pills flow.
18. **"Alex" and "Auckland, New Zealand" are hard-coded** in Claude's
    instructions.

### Later

- **A watch on live** (question 38, yes, later): a Windows scheduled
  task that pings Alex's phone if the `assistant-bot` service is down,
  rather than the dev bot always on. Also there, as an option: the dev
  bot as an always-on caretaker that reads only live's health
  (`docs/specs/attention.md`, section 8).
- **A live eval to shorten the router's rules** (question 40: not now),
  about NZ$0.70, the cost audit's last open item.
- **A read-only web page** (said 2026-10-14), reachable only over
  Tailscale: today's checklist, the week, the run log, costs, open
  bugs. It reads the database and the `design` records and needs no
  second interface (`docs/INTERFACE.md`, section 5.2, question 6:
  about 2 to 3 sittings). Nothing on the open internet, no signing in
  beyond the tailnet.
- **The rest of the door** (`docs/INTERFACE.md`, section 4): stage 3
  (`Context` and `main.py`'s events), 4 (the typed-word and reaction
  contract), 5 (`<#…>` and `<t:…>` through helpers), 6 (the old confirm
  buttons), 7 (archive), 8 (the bugs forum, the start card, the dev
  panel). Stages 1 and 2 are done.
- **Claude Code starting by itself when the PC boots** (said
  2026-10-14), in the project folder with remote control, so a
  restart of the PC never needs a Remote Desktop visit to bring it
  back.
- **A monthly reminder to run Windows updates by hand** (Alex,
  2026-10-15): a line in the briefing once a month, on a day and at a time
  Alex chooses, saying it is time to update the EliteDesk (and to stop
  live first, or let it restart itself). Since 15 Oct updates are paused
  and only restart the PC between midnight and 6 am; the pause can be
  set for 5 weeks at most, so the reminder is what keeps it from lapsing
  into an unplanned restart. Probably a reminder Alex sets in words
  ("remind me on the first Saturday of each month at 10am to update the
  PC", once reminders take monthly repeats from `core/recurrence.py`), or
  a What's new line the bot adds itself.
- **The calendar through the Google Calendar API, to add events** (Alex,
  2026-10-15): the route for the bot writing to the calendar. A Google
  Cloud service account, its key in live's `.env` folder only (never in a
  doc, a log or a commit), given read access to the main calendar and
  write access to a dedicated "Bot" calendar shared with it, and to
  nothing else: the bot can read everything and add or change only what
  is on its own calendar. It is a second source behind the calendar
  task's source interface (`source.py`), picked by a setting, so the
  rest of the task does not change; until then the task reads the
  private iCal link and writes nothing. Every added event is a confirm
  card first, as every change to one of Alex's things is.
- **A RAM upgrade, 8 to 16 GB** (said 2026-10-14), if memory keeps
  running short: live uses about 100 MB, a self-test takes up to about
  240 MB, and it stops under 1.9 GB free.

Wanted some day, or small and harmless as they are. In Details under
the same words.

- **A file sent with no words** goes to the router once gym is built
  and can read a plan (decided 2026-10-13); until then it is ignored.
- New things: a notes task; a reminders task ("remind me at 3 pm": a
  one-off job on the scheduler, once that is built); the nightly sweep
  (now the scheduler's clean-up, 6a); `dev qa <block>`; pin, archive and delete
  in plain words; bulk and cross-channel actions; `reset channel` for
  another channel by name; chat outside #inbox.
- Pills: a pill whose doses can't fit is refused, not fixed; the Edit
  buttons on a pill; more than 25 pills; pills setup and the way Claude
  is handed tools (the old note); what is left from stage 3.
- Channel reset and housekeeping, left as they are; `reset` is a bare
  verb that is still a shortcut.
- Reactions: unpinning by reply doesn't clear an applied 📌; a refused
  reaction is forgotten by a restart; only archive and delete are
  checked at once.
- Dev tools: the dev clock outlives the dev database; "🧪 dev test
  data" under every dev tool's reply; `dev reset-db` leaves cards
  behind; `dev cleanup off` leaves working buttons behind; `dev
  inspect` forgets Transient after a restart; the lab's own button
  colours; lab messages outside the lifecycle; tests in parallel.
- Bugs: everything under "Bugs: left for later" (forum handling to
  core, screenshots, a closed post written in, the card's count, old
  posts' buttons, a report with no post, rotated logs, hand-made posts,
  typed words waiting for the post).
- Core: forum handling and the lifecycle of typed words' #bot-log
  cards; switching task straight after an answer costs one more
  request; why one "make it 2" didn't stick on 2026-10-09;
  `python -m tasks.bugs.cli` always reads the live database;
  `KEEP_CONFIRMATIONS` makes channels busier.
- The word lists in Python (the table in Details): none may grow into
  the way something is understood.
- Manual retests still owed from 2026-10-07 (the table in Details).

### Timers (frozen 2026-10-14: they keep working, are never ported behind the door, and are scrapped if the bot ever leaves Discord)

Only touched when a core change breaks their tests.

- C8 and G7: "Which timer? Say its name." and the Pomodoro's restart
  question are still messages of their own.
- C14: lengths and several ids are handed over as text. C17: a set of
  words for "the session". C18: their own live lists and send helpers
  beside the core's.
- Two running timers with the same name both get the change; two
  timers with the same label look alike in a reply.
- What the timer reply fix left; timers still take a length as text;
  `core/durations.py` has the timers' limits in it.
- A Pomodoro left waiting for Start for more than 2 hours; an old
  paused timer never draws attention to itself; timer cards under a
  moved dev clock; Discord rate-limited the board; timer actions in
  plain words have no Undo button.
- The live check of 2026-10-13: "pause it" came back with the timer's
  id rather than `@that` (the code puts it right).

## Removed on 2026-10-13, and why

- **`tasks/keep` uses discord.py**: fixed on 2026-10-13. Its Discord
  calls were already in `core/pins.py`; only the names of two types
  were left, and they are gone.
- **One lock for two folders**: no longer needed as a change to the
  lock. Dev gets a bot token of its own (`.env.dev`), decided
  2026-10-13, so live in its own folder and dev in this one are two
  different bots.
- **`search_messages` only finds your own messages that the bot handled**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **Refs from a listing last for one message**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **Claude no longer remembers what it ran**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **The "done" check still goes by wording**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now); a confirmation is only ever written by a task's code after the change is read back.
- **Natural-language requests are slow, and the plan is waiting on four**: the plan was carried out (state with the message, no closing request, 👀 on receipt) and the path it sped up is gone.
- **Lists posted before this change are still snapshots**: a note about messages of 2026-10-07, not something to do.
- **Events start with this change**: a note about data from before 2026-10-07, not something to do.
- **Every chat message now carries the tools**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **A protected message deleted through Claude asks twice**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now); delete is by reaction or reply word only.
- **Proposals and button questions are held in memory**: confirm cards and their questions are kept in the database now (`confirm_cards`), and a Save cut off by a restart has a recovery.
- **Undo exists only where an action declares one**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **Reactions are not tools**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **Recent messages go to the API when Claude looks for a target**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **A false "it's running again" straight after a read is no longer**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **A request whose second step needs the first one's result stops**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now); several things in one message are one card a task now.
- **The speed-up is measured on Claude's side only**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **The prompt cache lasts 5 minutes**: measured and written up in `docs/COSTS.md` (section 2).
- **`pause all` through Claude and `timer_control` with `all` overlap**: it was about the old way of handing Claude tools, which was removed at step 4 on 2026-10-10 (Claude runs nothing now).
- **"Stop all timers called tea" got "I don't have a timer called tea" (2026-10-07)**: its retest (N51) was a test of the old tools path, which is gone.
- **"Cancel all timers" cancelled four and asked for the rest again (2026-10-07)**: its retest (N52) was a test of the old tools path, which is gone.
- **Plain-word requests took 7 to 10 seconds, 30 or more after a restart**: its retest (N50) was a test of the old tools path, which is gone.
- **Claude couldn't say what was running or how long was left ("check the channel above")**: its retest (N29) was a test of the old tools path, which is gone.
- **Pause, resume, cancel and extend searched the last 20 messages for the timer ("I don't see**: its retest (N30) was a test of the old tools path, which is gone.
- **"✅ Done." with no tool call and no timer; "Done." twice to `dev mode off` / `on`**: its retest (N31) was a test of the old tools path, which is gone.
- **"[Tool calls this turn: …]" at the end of replies**: its retest (N32) was a test of the old tools path, which is gone.
- **Claude couldn't switch dev mode on**: its retest (N33) was a test of the old tools path, which is gone.
- **"Look further back" could only see the last 20 messages**: its retest (N34) was a test of the old tools path, which is gone.
- **"Resume my tea timer": "Tea's running again – 9m 21s left", but tea stayed paused**: its retest was a test of the old tools path, which is gone.
- **"I don't have a record of what the times were"**: its retest (N42) was a test of the old tools path, which is gone.

## Details

What follows is kept as it was written, for the where and the why.

### Fixed in code, waiting for a manual retest

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
| `dev mode on` / `dev mode off` were not words | `dev mode on\|off` added | J32 |
| A Pomodoro asked for while one was going: card again, a note, the alert and Claude's reply; the lengths asked for ignored | Through Claude: one reply, nothing posted, and an offer to restart at those lengths. Typed: the card and one Restart question | H19, H21 |

From the run of 2026-10-07, 22:53 to 22:58 (reported as "paused timers
gained time"):

| Finding | What changed | Retest |
|---|---|---|
| Paused timers seemed to gain time (dinner 24s, then 2m 50s) | Nothing gained time: both were frozen at the right figures (dinner paused at 22:55:21 with 2m 50s, breakfast at 22:55:23 with 3m 36s). The 22:54 "Your timers" message was a snapshot whose countdowns ran on to the old end times. The list is now live: one per channel, rewritten on every change | G16 |
| Was dev speed involved? | Not that evening: the bot restarted at 22:52 and dev mode was never on. But the check found a real fault: pausing read dev mode's speed of the moment, so a timer started at 1x and paused at 60x would have gained 60 times its time left. Each clock now keeps the speed it was started at | G17 |
| A timer whose time was up could be paused at 0s | It is finished instead, and `pause all` leaves it alone and says so | G17, G19 |
| "Pause all timers" asked which, took four calls and left the Pomodoro | `pause all` / `resume all` are typed words (so no Claude call when typed) and tools; they include the Pomodoro unless told otherwise and list what was done | G21, N40 |

### Gaps against the conversation standard (2026-10-10)

What is left. The golden conversations are `tests/test_golden.py`; none
is marked `gap` any more: G1 (questions on the card) was built on
2026-10-12, and 1c, 1d and 2a pass. G14 (a notification never names a
pill) is built and tested with reminders, which are switched off until
they pass QA. G3 (a correction straight after Save) was built on
2026-10-13: core hands the task the card that was just saved
(`Request.just_saved`), so it is known and no longer marked ❓. G4 is deferred until then. G9 and G13 (the old path, the old `pills` list) were removed
at step 4.

| # | Gap | Layer | Size |
|---|---|---|---|
| G4 | Task ties are asked too readily: the router sees two exchanges and no record of what I have or did lately | router | medium |
| G7 | Questions still sent as their own message: only timers now ("Which timer? Say its name.", C8). The pills ones are on the card (C7, 2026-10-12) | timers | small |
| G22 | "More like the one about the water reform" is read as its topic (like_topic), not words of its headline: m29, a known miss since the news cards (21 Oct). Right while one story of that topic is up; with two the code may take the other | reading extraction | small |

Done: dev bugs are numbered D1, D2… with a "dev" tag and a live number
is never reused; and, in batch 1 (2026-10-10), G2 (a reply to an older
card), G5 (✅ on a message that needs nothing), G6 (a neutral "not
understood"), G8 (a name Claude works out for a pronoun is put back for
the code), G10 (card kinds are new, change, remove), G11 (12-hour times
in bug posts and `dev why`) and G12 (a looser redirect replaces the old
card).

### Found by `task-check` (2026-10-12)

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
**Fixed with G1, 2026-10-12:** C7 (every pills question is on the card:
which pill, which of two, morning or evening, the missing time, how many
a day). **Left, timers:** C8 (its question could go on a card now). **Until gym is built:** C19 (gym is the second
task that needs name matching: move it to core then). **Left, timers**
(a proof of concept that may be scrapped): C8, C14, C17 and C18.

| # | Task | What | Where | Rule | Layer | Size |
|---|---|---|---|---|---|---|
| C8 | timers | The same: "Which timer? Say its name.", and `pomo` with other lengths asks "Restart it as `50/10`?" in a message of its own | `tasks/timers/plain.py:152`, `tasks/timers/sessions.py:238-239` | The same (G7) | task, then core | medium |
| C14 | timers | Lengths are handed over as text ("5m", "50/10") and several ids as one text ("t12 t14") | `tasks/timers/plain.py:359`, `:457`; `tasks/timers/status.py:51-63`, `tasks/timers/pomodoro.py:55-79` | Contract: structured values (decided 2026-10-10 to leave) | schema, fixtures | medium |
| C17 | timers | Words Claude might send for "the session" are accepted as a set ("current", "it", "pomodoro"…) | `tasks/timers/control.py:22` | Word lists (not listed below until now) | schema (`@that`) | small |
| C18 | timers | Its own live lists ("Your timers", one a channel) beside `core/livelists.py`; its own send, edit and delete helpers beside `core/cards.py` | `tasks/timers/board.py:79-112`, `tasks/timers/store.py` (`timers_lists`), `tasks/timers/common.py:22-58` | Core or task: plumbing | core | medium |
| C19 | pills | "Which of my things does this name mean" (whole name, then part, then ask) and laying a reply over an open card are general, and live in the task | `tasks/pills/rules.py:541-568`, `tasks/pills/plain.py:69` | Core or task: a general tool. **Name matching moved to `core/names.py` on 2026-10-13**; laying a reply over an open card is still in the task, until a second task needs it | core | small |

Known gaps the run met again, already listed above: G1 (golden 1c, 1d,
2a), G3 (golden 2b passes only by the "pill changed last" guess), G14
(nothing notifies about a pill yet). One fixture has no recording
("how long left on tea?").

### Word lists and phrase patterns in Python (2026-10-10)

Language is Claude's job and rules are Python's (see the Scaling notes in
`docs/ARCHITECTURE.md`): these are safety nets, listed so that none grows
into the way something is understood. "Replace" says whether a change to
a schema could take its place.

| Where | What it reads | Why it is there | Replace with a schema change? |
|---|---|---|---|
| `routing.named_alone` | A task's name alone, or after "show", "list", "see", "open", "what are my" | Shows a list with no request at all | No: its point is to ask nothing |
| `routing.names_item` | One of my pills' or running timers' names, whole, in a message the router called "nothing" | A message that names one of my things is never dropped in silence | No: it checks the router, and only says whose the message is |
| `routing.named_destinations` | "to my pills", "on the shopping list" | A destination I name decides the task, whatever the router says | Partly: the router could return `named` beside the task; kept in code because the router got it wrong in QA |
| `routing.led_by` (`Entry.leads`) | A message starting with a task's own lead ("remind me", the reminders') | Outranks a named destination: "remind me to write in my diary" is a reminder (Alex, 15 Oct). With no destination named it decides nothing | Partly: the router gets it right alone; it only overrules `named_destinations` |
| `confirm.redirect` (`_NO`, `_FOR`) | "no, shopping", "I meant packing", "shopping instead" | Moves a card to another task with one request instead of two | Partly: the follow-up extraction already has `not_this`; this only saves the router's request |
| `confirm.is_correction` (`_CORRECTION`) | A message that starts "no, …" | Undoes the card's last change before applying the correction | Yes: a `corrects` yes/no in the follow-up's answer |
| `actions.as_references` (`_POINTING`, `_SMALL_WORDS`) | "it", "that", "this", "them", and whether the message names the thing | Puts back a name Claude worked out for a pronoun | No: it checks the schema's own `@that` |
| `nudges/birthdays.py` `tidy` | my, me, myself, I, mine; a trailing 's; a leading "my" | A birthday Claude named "My" or "Mum's" is still the user's own, or Mum (live, 19 Oct) | No: extraction is told the rule; approved as an exception (Alex, 19 Oct: a closed set of pronouns) |
| `actions.unstated` (`_is_stated`, `_NUMBER_WORDS`) | Whether a guessed value is in the message word for word | A value I stated is never marked ❓ | No: it checks `guessed` |
| `actions.unchosen` (`_HALF_MARKED`, `_PART_OF_DAY`) | am, pm, "morning", "evening", a 24-hour time | Takes back an am or pm Claude chose by itself | No: it checks the fixed form of a time |
| `actions.restated` (`_SAID_TIME`) | A time in the message with am or pm ("9pm", "9.15 AM") | Puts back the one time I stated when Claude handed over another in its place (found 2026-10-13: "9pm" answered with the card button's 8:00 pm) | No: it checks the fixed form of a time against the message |
| `actions.whole_part` (`_DANGLING_END`, `_DANGLING_START`) | "of", "and", "the", "at"… left hanging at an end of a leftover | A "Not included" part is whole words, never cut off mid-phrase ("dose 1 of") | No: it checks `not_included`, whose description now asks for whole parts |
| `actions.is_filler` (`_FILLER`) | "and", "also", "please", "too"… | Joining words are never reported as "Not included" | No: it checks `not_included` |
| `actions._number` (`_AS_A_NUMBER`) | A number that arrived as text ("62.5", "62,5") | A decimal that came as text is still read; anything else is refused | No: the schema already says number |
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

### Gym: what its spec would add to core (2026-10-12)

From the core or task rule (the spec is `docs/specs/gym.md`, section
12). **The first three were built on 2026-10-13** (`request.attachments`,
`actions.NUMBER`, `core/names.py`, with pills using the last); nothing
of the gym task itself is started until the questions on how Alex
trains are answered:

- Done: **attachments on a request** (plumbing).
- Done: **a decimal number in the contract**.
- Done: **name matching** moved out of pills (C19).
- **Days of the week in the schedule model**, only if workouts go by
  weekday (already listed below).
- Built inside the task, apart, until a second task needs them:
  reading a grid from a file, mapping headings to a fixed set of
  fields, and comparing two lists of records into `field · old → new`.

### Task check, 2026-10-13 (every task and the core, after the overnight batch)

Run by the checks of the `task-check` skill: the contract
(`actions.problems`: nothing), the scans for discord.py, the clock, the
day, 24-hour times, offers and word lists, and a read of what changed.
The tests and the golden conversations pass.

**Fixed (code only):** a reaction's `applied_at` and dev mode's expiry
took the time from `datetime.now` rather than `clock.real_now`; the
drawn checklist reached into the checklist's private list of listeners
(`checklist.tell_changed` now); the word-list table above gains the
number read from text; C19's name matching is in the core.

**Open, for Alex** (also in `docs/STATUS.md`):

| What | Where | Why it is not fixed here |
|---|---|---|
| The spend note is sent from `core/database.py` | `core/database.py`, `_say_if_over_the_daily_limit` | It works and is tested; a module for what is said about spend would be tidier |
| Three near copies of "tick a dose off from a button" | `checklist._pressed`, `reminders._done`, `sheet._done` | One would do; left until the old checklist goes |
| `dev mock` has its own records beside `core/design.py`'s | `tasks/dev/mock.py` | It shares the colours and spacing; sharing the records is a small job |
| Timers: C8, C14, C17, C18 as before | table above | Timers are low priority and left alone |

### Understanding check-up, 2026-10-14

Every message of mine to live from 7 to 14 October, read back from
the message log with its trace. About 30 were plain words since the
router went in (10 October). By cause:

| Cause | What was said (the pill as "Pill A") | What the bot did | Now |
|---|---|---|---|
| A change to something that is only on the open card was read as a change to a saved thing | "Make 11:30, 11am instead", with the new pill's card open | "⚠️ There are no pills yet." It took saving the card and two more messages | **Fixed 2026-10-14** in code (`Action.unsaved`) and in the prompt. Golden 2c |
| "It" straight after a log was not taken as the pill just logged | "I took it at 9am", a minute after "Taken my pill A" | "⚠️ Which pill? Say its name." | Fixed 2026-10-12. Golden 18, 18a, 18b |
| A time said straight after a log was read as another dose | "I took Pill A at 9am", after a log at 10:57 pm | "9:00 am is before the previous one"; it took "I didn't take Pill A" and saying it again | Fixed 2026-10-12. Golden 18c |
| When a dose is due was added up past midnight | (the reply to the late log) | "still to take today: dose 2 `1:57 am`" | Fixed 2026-10-11: a due time never passes the day's limit |
| A dose was closed as missed when its reminders ran out | "Took Pill A at 9:20", the first dose of the day | Logged as dose 2 | Fixed 2026-10-14. Golden 26 |
| A correction of which dose was read as a new dose | "That was dose 1" | A second log, of dose 1 | Fixed 2026-10-14. Golden 19, 19a, 20 |
| What I said contradicted itself and the bot chose | Three times with "3 hours apart", two of them 2½ hours apart | The third dose moved by half an hour, with a ⚠️ line | As the card rule has it. `docs/QUESTIONS.md`, 49 |
| Two timers with one name | "give tea more time" | Both changed, with a guessed amount | Known, timers frozen. Question 50 |
| An amount I said was marked as a guess | "Give it 2 more" | 2 minutes added, "❓ I guessed how much time to add" | Known, timers frozen. Question 50 |
| The task that had just answered was tried first | "end all timers", "clear channel", each minutes after the other task answered | Right in the end, at the cost of one more request | As built: for five minutes a message goes to the task that just answered |

Nothing got "I didn't understand that" in the week. Before the
router (7 to 10 October) about a hundred messages went through the
old way of asking Claude: it asked for a reply to a message where
words would do, could not see a timer's time left, said "Done" with
nothing done, and asked which of two things was meant. That path was
removed on the 10th; those sentences are timers', and timers are
frozen.

The golden set asked of the real API: 56 of 59 right before the fix,
57 of 59 after; the two that remain are old known misses (a name
handed over where "it" was said), which the code puts right.

### Left for later

- **Tests in parallel** (tried 2026-10-13): with pytest-xdist one full
  run took 30 s and the next hung at about 95%, so it is not used and
  not installed. The serial run is 56 s. Worth another look only if the
  suite grows slow again: find the test that blocks when two workers
  run at once.

- **A reaction made just before a stop is lost** (found checking
  restarts, 2026-10-12; left on Alex's word): the 30 seconds a reaction
  waits are kept in memory, so one made just before a restart is never
  acted on and gets no ✅. Take it off and put it on again. Keeping the
  waiting reactions in the database would fix it.
- Done 2026-10-13, behind `CARDS_V2`: reminders, the checklist and
  the confirm, question and asks-first cards in Components V2.
- **Cards not yet drawn the new way** (`CARDS_V2`): the reset card and
  the other destructive cards outside confirm cards, the "which task?"
  question, timers and sessions, a list shown on request, the dose's
  own message (not posted while the new look is on), the gym cards.
- **The take-by line on the checklist** (the spec has it on the
  checklist and the prompt): it is on the prompt only, until the
  checklist's redesign is settled.
- **Streaks**: the rule is built as pure logic (`core/streaks.py`,
  2026-10-13): only a missed dose breaks one, a skip never does. Still
  to do: showing one (where, and in what words) and the questions in
  `docs/STATUS.md`.

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
- **The section provider interface** (for a morning brief) is not built.
  Specified on 2026-10-13 as an optional summary in the task contract,
  with the briefing as its first user (6a). `core/hub.py` has the hub
  channel and the progress bar only.
- **After the self-test, fixed on 2026-10-13**: the name check against
  what was typed, "just now", job names in words and the check on the
  catch-up card, the reset card in the new look. **Not found:** why
  "add Testmag to my pills, twice a day at 8am" once came back with a
  pill that could not be used. Nine real requests offline gave the
  right answer every time; the raw answer is logged from now on
  ("Extraction for … fitted nothing … Claude called …"), and the trace
  has it for `dev why`. A fixture for it and for "pause testv" would
  be worth recording at the next live eval. **Left:** a card saved
  after `CARDS_V2` is switched on stays plain; `dev cost` shows a limit
  under a cent as US$0.00. (The timers' jobs were named the same day,
  as an allowed exception: "timer ending", "Pomodoro phase".)
- **The self-test's findings** (2026-10-13). With real requests, on two
  runs: "pause testv" (Testvit and Testvit forte both there) came back
  from Claude as `pill: "Testvit"` with nothing guessed, then as
  `pill: "@that"`; `core/names.py` was never shown "testv", so it
  never asked. "add Testmag to my pills, twice a day at 8am" came back
  once as a `pill_add` whose `pills` had no usable item ("🤔 I didn't
  understand that."). Smaller: the too-soon card says "0m after dose
  1" for a dose logged seconds before; the catch-up card names a job
  "pills remind"; the reset card and a card saved after `CARDS_V2` is
  switched on stay plain; `dev cost` shows a limit under a cent as
  US$0.00. Not tested by it: see "In the specs and not tested here" in
  the report.
- **Scheduler, clean-up, briefing** (specified 2026-10-13, not built).
  What was found while writing it, to carry into the build:
  - Three things book themselves today, each with its own code (the
    backup, the day rollover, the 6:00 am checklist), and the time of
    each is a constant. They move onto schedule rows one at a time
  - Pill reminders keep their one stored job and `reminders.decide`:
    only the job gains a key. Turning each nudge into a job of its own
    would count in the scheduler what is now worked out, which the
    pills rules forbid
  - The dev clock going back needs care once a run has a key: runs
    recorded for moments now in the future must not block the real ones
  - **Yesterday's checklist stays in the hub by design**
    (`checklist.close_past` writes it one last time, leaves it and
    drops its row; `checklist.post` removes earlier copies of the same
    day only). The clean-up changes that: the checklist is replaced by
    the next one. The old ones there now have no id kept and go only
    with `reset channel`
  - The transcript code of `reset channel` is in `tasks/channel`; the
    clean-up needs it in core
  - Tasks that still send with discord.py directly (timers, archive,
    bugs, lab, dev) would record no lifetime, so their messages are
    never tidied until the gateway layer exists
  - "Routine" comes to mean only a schedule with several steps
    (answered 2026-10-13). What `dev run` runs is renamed a handler,
    in the code (`devmode.ROUTINE_NAMES`, `register_routine`, the
    words of `dev run`) and in `CLAUDE.md`'s Words, when the engine is
    built
  - The briefing is edited in place when a section changes (answered
    2026-10-13): a task has to say when its summary may have changed,
    as a list shown on request is told
  - In the hub what is said goes once handled (answered 2026-10-13):
    my message and the reply are recorded as one exchange, which
    nothing does today
  - The router needs to tell "move the briefing to 7" (the schedule)
    from "move pill A to 9 pm" (pills): fixtures and a live eval at
    build time, to be costed and asked first
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

### Bugs: left for later

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

### Found in that run, left for later

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
- **Discord rate-limited the board** during the four-call pause (a 429
  on its edit, retried after 3s). `pause all` now refreshes once; a card,
  the board and each live list are still one edit each per change.
- **Timer actions through Claude have no Undo button** now that they go
  by id; ask it to resume or pause again instead.

### Tool calling: left for later

Built on 2026-10-07 and unit tested with a mocked Claude. First run against
the real API the same day: the schemas were accepted and the cache was
read on every message after the first (4,973 tokens, 6,996 with the dev tools).

- **Claude only chats in #inbox**, so the "dev tools in the dev channel"
  rule has no effect until chat is enabled there.
- **Typed words still wait for their #bot-log card** and Live edits
  made from buttons are unchanged; only tool calls moved theirs to the
  background.
