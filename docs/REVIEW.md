# Review: everything on `feature/pills` since `main`

Brought up to date on 2026-10-14 (first written 2026-10-13), for
reading before the branch is merged. Nothing here is merged: `main` is
where it was on 2026-10-09.

The branch is 135 commits over six days. Roughly a third of what
changed is the bot itself (`core/`, `tasks/`, `interfaces/`,
`main.py`), a third is tests, and the rest is docs, sketches and the
self-test.

Part 1 is what you would notice using the bot, part 2 what changed
underneath, part 3 what could go wrong. What changed since the first
version of this review is marked **(new)**.

## 1. What you'd notice

### On live today

- **Plain words go one way.** Every message that is not a typed word
  goes to the router, which picks a task (or chat, or nothing); that
  task fills in one action, and its own code does it and writes every
  word. Chat answers general questions only and never claims to have
  done something.
- **A card before anything is saved.** Adding or changing one of your
  things shows a confirm card with the kind of change and
  `field · old → new`; only Save writes it. A question is on that
  card, one at a time, a button for each likely answer. "No, …"
  straight after undoes the mistake.
- **Reactions are the status.** 👀 while it works, ⚠️ for a problem. A
  remark gets no reply.
- **Pills.** A plan with times, a minimum gap, a latest time, notes
  and days of the week; today's checklist as one message edited in
  place; logging by saying it, by `took <the pill's exact name>` or by
  pressing; anything doubtful asks first. Yesterday, the week and a
  streak are answered from the record.
- **Pill reminders** ping you at any hour, with a neutral line on the
  lock screen ("💊 Routine due · 12:00 pm").
- **(new) The hub holds what matters.** Each morning at 6:00 am: the
  tidy (yesterday's messages go, a copy saved), then the briefing,
  then the checklist. The briefing is one "☀️ Today" card, edited in
  place all day:
  - "⚠️ Needs a look" on top, with a bug's id, for anything wrong: a
    job that failed, reminders that can't be sent, spend or memory
    over its limit;
  - a section a task: pills, and **weather** ("14° to 20° · drizzle",
    "61% rain after 1pm · wind 15 km/h N"), kept current through the
    day;
  - "💸 Yesterday: NZ$…" with the amounts hidden until tapped;
  - small "🗒️" lines for what is worth knowing: an unexpected restart,
    a self-test that did not run.
- **(new) You are told when something needs you.** By day the bot
  mentions you in the hub with one line ("⚠️ B14 · backup failed at
  3:00 am"), which goes once it is dealt with. Between 10:00 pm and
  7:00 am it waits; at 7:00 am one ping if anything is waiting. You no
  longer need to read #bot-log, which is unchanged.
- **(new) Costs are in NZ$** wherever you see them, at a rate fetched
  each morning. The daily alert is at NZ$1.00.
- **(new) A start says nothing**: no "Online and ready", no start
  card. If the PC restarted or the bot crashed, one line says so.
- **The status line under the bot's name** shows the one thing most
  worth a look: "💊 due 12pm", "⚠️ B14 · backup failed", "🌅 6am".
- **My schedule** lists what the bot does by itself and when, **(new)**
  with every line's last run and whether it worked. Yours to move:
  the morning routine, the 7:00 am check, the weather fetch and
  refresh. The bot's own: backup, end of day, exchange rate, the
  nightly self-test.
- **After a restart** the bot catches up and repeats nothing. What
  you sent while it was off gets a card that asks before acting.
- **Bugs.** 🐞, the word `bug`, or saying so. The bot files its own
  for a job that did not work and for its memory use.

### The switches

| Switch | On live | What it is |
|---|---|---|
| `REMINDERS_ENABLED` | **on** | Pill reminders |
| `QUIET_HOURS_ENABLED` | **on** | 10:00 pm to 7:00 am: only pill reminders ping |
| `HUB_TIDY` | **on (new)** | The hub is cleared each morning and after each exchange |
| `BRIEFING_ENABLED` | **on (new)** | The briefing |
| `WEATHER_ENABLED` | **on (new)** | The weather section |
| `NIGHTLY_SELFTEST` | **on** | At 3:00 am the dev bot tests what changed; your phone is pinged only if a step fails |
| `CARDS_V2` | off | The new look. Waiting for your picks (design round 2) |
| `WEEKLY_SUMMARY` | off | Sunday 7:00 pm, the week's pills |
| `DMS_ENABLED` | off | Talking to the bot in a direct message |
| `NOTIFY_NTFY` | off | Alerts pushed to your phone through ntfy. The bot sends nothing there |

### Outside Discord

- **Two bots.** Live, and the dev bot with its own token, database,
  lock, log and channels. The self-test runs as the dev bot and never
  stops live.
- **Phone notifications from Claude Code** through ntfy, quiet at night.
- **(new) Design round 2**: 13 sketches in the design-options post.
- **(new) One list of open questions**: `docs/QUESTIONS.md`.

## 2. What changed underneath

- **One way in** (`core/conversation.py`, `router.py`,
  `extraction.py`, `confirm.py`): router, extraction, the task's own
  code. Claude runs nothing and has no tools.
- **The task contract** (`core/actions.py`): what a task is, what its
  actions take, what repeating one means, a `verify` that reads a
  change back, and optionally a summary and attention items.
- **Structured values.** Claude hands over minutes, numbers, times,
  lists, references; Python does every sum. A name or a time you
  stated wins over what Claude substituted.
- **The standard and its tests.** `docs/CONVERSATION.md`; its golden
  conversations are replayed offline in every test run.
- **The scheduler** (`core/scheduler.py`, `timetable.py`): one engine;
  a schedule is a row; a run has a key; a run log; routines.
- **Time** (`core/clock.py`, `day.py`): one clock, one idea of the day.
- **Pills** (`tasks/pills/`): doses as rows of the occurrence log, due
  times worked out and never stored.
- **Messages** (`core/lifecycle.py`, `messages.py`, `livelists.py`,
  `outgoing.py`): a class and a lifetime for every message.
- **Attention** (`core/attention.py`, `health.py`, `identity.py`): one
  ranking; the status line, the briefing and pings each show a slice.
- **Notify and alerts** (`core/notify.py`, **(new)** `core/alerts.py`):
  an alert leaves the bot one way; where each kind goes, and whether it
  gets through quiet hours, is one table.
- **(new) Money** (`core/money.py`): US$ recorded, NZ$ shown; the rate
  is a daily job with the last known rate and a setting behind it.
- **(new) One door to Discord** (`core/surface.py`,
  `interfaces/discord/`): new code may not import discord.py; a test
  holds the list of files that still do, and it only gets shorter.
  Core went from 16 such files to 5. Timers are frozen.
- **(new) Weather** (`tasks/weather/`): the first task built on the
  plain-data side only, with nothing for the router.
- **Which bot is this** (`core/account.py`): a start asks Discord
  which account its token is before anything else.
- **The self-test** (`selftest/`): the dev bot against real Discord,
  about 115 steps, recorded answers by default, a history, a dev bug
  for a failing step, a monthly cap. **(new)** It sets every switch
  itself, so live's settings never decide a step.
- **Database.** New core tables since `main`: schedules, the run log,
  occurrences, confirm cards, live lists, bot messages, missed
  messages, spend notices, held alerts, **(new)** needs-a-look,
  exchange rates; the weather's forecasts. Migrations only append; a
  snapshot is saved before an upgrade.
- **Tests.** About 2,730 offline tests in under two minutes. **(new)**
  They set every switch themselves and read no real data folder.
- **Docs.** **(new)** `CLAUDE.md` is the short form and
  `docs/RULES.md` the rules in full; `QUESTIONS.md`, `INTERFACE.md`,
  this file.

## 3. Risks

**Before merging**

1. **Size.** 135 commits and most of the bot rewritten since
   `main`. The way back is the branch point and a database backup from
   before it. Live has run from this branch throughout.
2. **The database only goes forward.** A snapshot is taken before each
   upgrade, and the nightly backup is the other copy.
3. **Manual QA is behind.** About 250 manual rows are untested;
   QA-RUN blocks 27 onwards, and all of 53 to 56 from the last two
   nights, have not been run on the phone.
4. **The new look has not been approved.** Both looks are kept and
   tested until `CARDS_V2` goes on.

**In daily use**

5. **(new) Much went live in one night**: the hub tidy, the briefing,
   the weather, the pings and NZ$. Each was self-tested on the dev
   bot; none has been lived with. If the morning is wrong, the three
   switches (`BRIEFING_ENABLED`, `WEATHER_ENABLED`, `HUB_TIDY`) turn
   each off again with a restart.
6. **(new) The bot now pings you for its own problems.** A job that
   fails every night would ping every morning at 7:00 until fixed.
   That is the point, but a false alarm is now loud. Dev mode and the
   self-test's month never ping.
7. **(new) The hub is cleared every morning.** A copy is saved to
   `data/exports/` first and pinned messages stay, but anything you
   meant to keep there must be pinned.
8. **Reminders are on**, and are the one thing that gets through
   quiet hours.
9. **(new) Two more outside services**, both free and without a key:
   Open-Meteo (weather) and Frankfurter (the exchange rate). Each
   failing is handled (the section says so; the last rate is used),
   but each is someone else's server, asked from your PC.
10. **ntfy** carries only neutral words, and the bot's side of it is
    off.
11. **Claude decides the route.** The net: a card before every save,
    the checks on names and times, the golden conversations.
12. **Cost.** The daily alert stops nothing. The self-test is capped
    by the month (NZ$3.50); October's is spent, so it runs on recorded
    answers until November.
13. **One PC, 8 GB.** The self-test refuses to start under 1.9 GB free.
14. **Two bots, one folder.** A half-finished edit is what live
    starts from at its next restart. The script that gives live its
    own folder on `main` is written and not used.
15. **(new) An unexpected stop is only recognised** as the PC
    restarting or a crash with an error. A kill from Task Manager
    reads as planned.
16. **Timers are frozen**: they work, are tested, and will not be
    carried over if the bot ever leaves Discord.

**Not done, by decision**

- Gym is designed and not built. Calendar is a spec only. Both wait
  for answers in `docs/QUESTIONS.md`.
- The rest of the door to Discord (stages 3 to 8 of
  `docs/INTERFACE.md`) and the read-only web page over Tailscale are
  in the backlog.
- Archive, pin and delete stay reactions or reply words.
