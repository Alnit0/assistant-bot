# Review: everything on `feature/pills` since `main`

Written 2026-10-13, for reading before the branch is merged. Nothing
here is merged: `main` is where it was on 2026-10-09 (the last commit
there keeps the specs private).

The branch is about 120 commits over five days. Roughly a third of what
changed is the bot itself (`core/`, `tasks/`, `main.py`), a third is
tests, and the rest is docs, mock-ups and the self-test.

How to read this: part 1 is what you would notice using the bot, part 2
is what changed underneath, part 3 is what could go wrong. Each switch is
listed with whether live has it on today.

## 1. What you'd notice

### On live today, with no switch to turn on

- **Plain words go one way.** Every message that is not a typed word
  goes to the router, which picks a task (or chat, or nothing); that
  task fills in one action, and its own code does it and writes every
  word. The old path is gone. Chat answers general questions only and
  never claims to have done something.
- **A card before anything is saved.** Adding or changing one of your
  things shows a confirm card with the kind of change and
  `field · old → new`; only Save writes it. A question the bot has is on
  that card, one at a time, with a button for each likely answer, and a
  typed answer works too. "No, …" straight after undoes the mistake;
  "no, shopping" sends it to the other task.
- **Reactions are the status.** 👀 while it works, ⚠️ for a problem. A
  remark gets no reply; something about one of your things is never met
  with silence.
- **Several things in one message**, and set / add / remove, are
  handled together, one card a task, and nothing you said is dropped
  without being told.
- **Pills.** Setting a pill up by words; a plan with times, a minimum
  gap, a latest time, notes and (new) certain days of the week; today's
  checklist as one message edited in place, with a fresh copy at 6:00 am;
  logging by saying it, by `took <the pill's exact name>` or by pressing;
  a late log, a dose too soon, a time out of order and a missed dose
  logged as taken all ask first. A dose of last night can be logged
  after midnight. "What did I take yesterday?", the week and a streak
  are answered from the record.
- **Pill reminders** (`REMINDERS_ENABLED`, **on** since 2026-10-13). A
  dose that is due posts one neutral line in the hub ("💊 Routine due ·
  12:00 pm"), and the pill is written in after, so a lock screen never
  shows which pill. Up to three reminders, 15 minutes apart, then the
  dose is missed. Taken, Taken at…, Skip and Snooze are on the prompt.
- **The status line under the bot's name** shows the one thing most
  worth a look: "💊 due 12pm", "💊 2/5 · 12pm", "💊 missed 9am", "💊 all
  5 taken", "⚠️ B14 · backup failed", "🌅 6am", or nothing.
- **My schedule.** "my schedule" lists what the bot does by itself and
  when; you can move, pause, change the days of, add and remove a
  schedule by words, each with a card.
- **After a restart** the bot catches up, says so once in #bot-log, and
  repeats nothing. What you sent while it was off gets a card ("I was
  offline when you sent this") with Handle it now and Ignore: nothing is
  acted on without asking.
- **Bugs.** 🐞 on a message, the word `bug`, or saying so files a post
  in the #bugs forum. The bot now files its own too: a job that did not
  work (one bug a kind of job, a note when it repeats and when it works
  again) and its memory use going over 300 MB or growing for a day.
- **Channel reset** (`reset channel`), which always asks first, and
  housekeeping that leaves no trace in a channel.
- **`dev` words** grew: `dev why`, `dev cost` (with the day's and the
  self-test's spend), `dev jobs`, `dev status` (with memory use).

### Behind a switch, off on live today

| Switch | What you would see with it on |
|---|---|
| `CARDS_V2` | The new look (Components V2): the checklist, reminders, confirm and question cards, the lists, the week, bugs, the reset card. Waiting for your check of the colours on the phone |
| `BRIEFING_ENABLED` | One "☀️ Today" card in the hub each morning, a section a task, edited in place all day. Now in the ranking's order, with what needs a look on top and what quiet hours held back overnight |
| `HUB_TIDY` | A clean hub: what you say there and the reply go once handled, nothing of a past day stays, a copy is saved first, pinned is kept |
| `WEEKLY_SUMMARY` | On Sunday at 7:00 pm, the week's pills in the hub |
| `DMS_ENABLED` | You can talk to live in a direct message as in #inbox: only you, silent replies, never a pill's name in a first line |
| `NOTIFY_NTFY` | Alerts pushed to your phone through ntfy as well as Discord, neutral words only; tapping opens the Discord message. Needs `NTFY_BOT_TOPIC` |

`QUIET_HOURS_ENABLED` is **on** since 2026-10-13: between 10:00 pm and
6:00 am an alert is posted without a sound and listed in the morning's
briefing until it is dealt with. A pill reminder always gets through,
with its sound, and it is the only thing that pings today, so nothing
you would notice has changed yet.

`NIGHTLY_SELFTEST` is **on** in `.env` from tonight's restart: at
3:00 am the dev bot runs the stages that changed (everything on
Sundays), with live left running; your phone is pinged only if a step
fails; nothing runs on a night with no new commits.

### Outside Discord

- **Two bots.** Live, and the dev bot with its own token, database,
  lock, log and channels. The self-test runs as the dev bot and never
  stops live.
- **Phone notifications from Claude Code** through ntfy ("finished",
  "needs you"), quiet at night.
- **Names.** Each bot takes its name from `BOT_NAME`; the dev bot shows
  "· testing" during a self-test.

## 2. What changed underneath

- **One way in** (`core/conversation.py`, `core/router.py`,
  `core/extraction.py`, `core/confirm.py`): router, then extraction,
  then the task's own code. Claude runs nothing and has no tools.
- **The task contract** (`core/actions.py`): every task declares its
  icon, what it is only for, examples, actions with their fields, what
  makes two items the same and what repeating one means, a `verify`
  that reads a change back, and optionally a summary and attention
  items. A task that breaks the contract is refused at start.
- **Structured values.** Claude hands over minutes, numbers, times,
  lists, references and declines in fixed forms; Python does every sum
  and resolves every "it". A name Claude hands over is checked against
  what you typed; a time you stated wins over one Claude substituted.
- **The standard and its tests.** `docs/CONVERSATION.md` is the
  standard for how the bot talks; its golden conversations are replayed
  offline in every test run and must pass before a commit.
- **The scheduler** (`core/scheduler.py`, `core/timetable.py`): one
  engine; a schedule is a row; a run has a key so nothing runs twice; a
  run log, pruned daily; routines with ordered steps. The backup, the
  end of the day and the 6:00 am checklist moved onto it.
- **Time** (`core/clock.py`, `core/day.py`): one clock, one idea of the
  day, a dev clock that refuses to work on the live database.
- **Pills** (`tasks/pills/`): the schedule model, doses as rows of the
  occurrence log, due times worked out and never stored, the checklist
  written from those rows, reminders decided from the database and the
  clock.
- **Messages** (`core/lifecycle.py`, `core/messages.py`,
  `core/livelists.py`, `core/outgoing.py`): every message has a class
  and, in the hub, a lifetime; lists shown on request stay live;
  everything sent is checked on the way out.
- **Cards** (`core/cards.py`, `core/design.py`): plain records with
  actions registered by name, so a button works after a restart; how a
  card looks is in one file.
- **Attention** (`core/attention.py`, `core/health.py`,
  `core/identity.py`): tasks and the core hand in items, the core ranks
  them once, and the status line, the briefing and pings each show a
  slice of that one ranking.
- **Notify** (`core/notify.py`): the one way an alert leaves the bot.
  Each kind is set to Discord, ntfy or both in one table; quiet hours
  and the level come from the ranking. Pill reminders are its first
  user.
- **Which bot is this** (`core/account.py`, `core/instance_lock.py`,
  `core/config.py`): a start asks Discord which account its token is,
  compares it with `BOT_USER_ID`, and exits having touched nothing if it
  is the wrong one; only then is the lock taken. A child process gets a
  clean environment.
- **The self-test** (`selftest/`): the dev bot against real Discord,
  about 110 steps in three stages, recorded answers by default, a
  history, a summary message, a dev bug for the first failing step of a
  stage, a memory stop line, a monthly spend cap.
- **Costs** (`core/costs.py`, `docs/COSTS.md`): cost logged a message,
  the cached part of a prompt shared across every kind of request, an
  alert when a day passes `DAILY_SPEND_LIMIT`.
- **Database.** New core tables: schedules, the run log, occurrences,
  confirm cards, live lists, bot messages, missed messages, spend
  notices, held alerts. Pills tables and their migrations. Migrations
  only ever append; a snapshot is saved before an upgrade.
- **Tests.** About 2,700 offline tests in about a minute, each on a
  copy of one migrated database; a watchdog stops a test that hangs.
- **Docs.** `STATUS`, `ARCHITECTURE`, `DEVELOPMENT`, `DECISIONS`,
  `DESIGN`, `TESTING`, `QA-RUN`, `COSTS`, `BACKLOG`, `SELFTEST`,
  `CHANGELOG`, and the project skills in `.claude/skills/`.

## 3. Risks

**Before merging**

1. **Size.** 120 commits and most of the bot rewritten since `main`.
   There is no going back commit by commit in any useful way: the fall
   back is the branch point and a database backup from before it.
   Live has run from this branch throughout, so `main` is the part
   that is untested, not this.
2. **The database only goes forward.** Many migrations since `main`.
   A snapshot is taken before each upgrade and the nightly backup is
   the other copy; going back to `main`'s code means restoring one.
3. **Manual QA is behind.** `docs/TESTING.md` has many manual rows
   still untested, and `docs/QA-RUN.md` blocks 27 onwards have not all
   been run on the phone. The offline tests and the self-test cover
   the logic; they do not cover how it feels or looks.
4. **The new look has not been checked on the phone.** `CARDS_V2`
   stays off until the colours are approved; both looks are kept and
   tested, which doubles the surface.

**In daily use**

5. **Reminders are on.** They are the one thing that pings you. A wrong
   plan, a clock change or a missed restart shows here first. The
   guards: one prompt a dose, nothing after a pill's latest time, the
   state in the database, and a late start catches up without posting
   twice.
6. **Quiet hours hold everything but a pill reminder.** That is one
   word in the table (`through`) for each kind: a future kind that
   must wake you (an early flight) has to be marked, or it waits for
   the briefing.
7. **ntfy is someone else's server.** A push carries only neutral
   words and a link, but the topic is the only secret: anyone who
   learns it can read and send. A failed push is logged and nothing
   else; a kind set to ntfy only would then tell you nothing, which is
   why pill reminders are set to both.
8. **Claude decides the route.** A message can still go to the wrong
   task or be read wrongly. The net: a card before every save, the
   checks on names and times, the golden conversations. Word lists
   used as a net are listed in `docs/BACKLOG.md` and must not grow.
9. **Cost.** Every plain message is one or two requests to Claude.
   The daily alert stops nothing. The self-test is capped by the month
   (US$2) and uses recorded answers unless prompts, schemas or routing
   changed.
10. **One PC, 8 GB.** Live and the dev bot share it. The self-test
    refuses to start under 1.9 GB free; the nightly run at 3:00 am is
    the first thing to be stopped if memory is short, and it says so.
11. **Two bots, one folder.** A wrong token in the wrong file is
    caught by the account check, but only if `BOT_USER_ID` in each file
    is right. Live and development still share the working folder: a
    half-finished edit is what live starts from at its next restart.
    The script that gives live its own folder on `main` is written and
    not yet used.
12. **Timers are frozen** as a proof of concept and may be scrapped;
    they still run and are still tested.
13. **Switch combinations.** Five switches off on live (the hub tidy
    went on on 2026-10-14) means the
    combination live runs is the best tested one; turning several on
    together (the briefing, the tidy and the new look) has been
    self-tested on the dev bot but not lived with.

**Not done, by decision**

- Gym is designed (mock-ups) and not built. Calendar is a spec only.
- Archive, pin and delete stay reactions or reply words, never plain
  words.
- The dev bot as an always-on caretaker of live is in the backlog.
