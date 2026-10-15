# Advisor handover

**Read this first** when Alex starts a new chat with Claude (the advisor). It holds what the code and the other docs don't: how we work together, the thinking behind decisions, and what's open right now.

**Kept up to date by Claude Code** at the end of every batch (see "Maintaining this file" at the bottom). Last brought fully up to date: 15 Oct 2026, late evening.

Never write here: a real pill name, a real event name, a bot's display name, a location more precise than "Auckland", a token, topic, link or ID.

---

## 1. Who does what

- **Alex** owns the project and makes every decision. Final-year CS student, works full time, so he's often away from the PC and works from his phone.
- **The advisor** (Claude in claude.ai) designs with Alex, explains, reviews Claude Code's reports, and writes the prompts Alex sends to Claude Code.
- **Claude Code** builds, tests, commits and runs things on the EliteDesk.
- **The workflow:** Alex relays prompts from the advisor to Claude Code and pastes Claude Code's reports back. The advisor never talks to Claude Code directly.

## 2. How Alex likes to work

**Answers**
- Lead with the answer, then detail. Short paragraphs, bullets, headers, **bold** key points, numbered steps for instructions.
- UK spelling. **No em dashes**, and don't swap them for hyphens: rewrite the sentence.
- A TL;DR for long answers that aren't instructions.
- When he says "slow down" or seems lost: **one step at a time**, wait for "done" before the next.
- Explain new ideas in plain words first (analogies work well), jargon second.

**Prompts for Claude Code**
- Always complete and ready to paste. **No placeholders**, and never leave options (A/B) for him to delete: ask him first, then write one prompt.
- Mark prompts that should keep Claude Code's context with "(↪️ no clear)".
- **Always say up front** whether a prompt will commit, push, run a self-test, or ship to live.
- Batches run unattended: Claude Code decides and notes under "Decided" in docs/STATUS.md rather than stopping, unless live or data is at risk.
- Spend limits in NZ$: per run under NZ$0.40, a batch cap stated in the prompt.
- Self-tests run as the dev bot (live stays up), never between 3:15 and 4:30 am (the nightly run is at 3:30 am), and only with 1.9 GB free.
- The full test run is the very last step before every commit.

**Things he has pushed back on**
- Too many steps at once.
- Designs nobody has looked at on a phone (Claude Code designs blind; ask him for screenshots).
- Having to Remote Desktop into the EliteDesk.
- Anything important living only in #bot-log (he never reads it).

## 3. Priorities (set 14 Oct)

1. **What the hub shows and how it reads**: the briefing, the design, progress.
2. **How well the bot understands what he says.**
3. Everything else. **Notifications and ntfy are low priority.**

He is **not relying on the bot for reminders yet**. The hub is a daily overview he checks, plus a place to talk to the bot to do more.

## 4. Environment

- **The EliteDesk:** Windows 11, 8 GB RAM. Live runs as the NSSM service `assistant-bot` from **its own folder**, `C:\Users\temp\projects\assistant-bot-live` (since 15 Oct, 3:11 pm): a clone on one pushed commit, with its own `.env`, `data\`, `logs\` and `.venv`. It is on `85b0c4e` (shipped 15 Oct, 6:00 pm). The work folder `C:\Users\temp\projects\assistant-bot` is for development only.
- **Shipping:** only by `scripts\update-live.ps1 -Ref <commit>` from a pushed commit (it refuses one not on `origin/feature/pills`, puts back the self-test's report, installs packages, checks migrations, restarts); `-Back` returns to the commit before. Batch rule: ship at most once, before 9 pm, after the full test run and a dev-bot self-test, at least 10 minutes from any pill reminder; check the account, the hub and the bookings after.
- **The old backup:** the work folder still holds the `.env` and `data\` from before the switch-over. They go once Alex says live has had a good day in its own folder.
- **Branch:** all work is on `feature/pills`. Nothing is merged into `main` yet; `docs/REVIEW.md` is the checkpoint for that.
- **Two bots:** live, and the dev bot (own token in `.env.dev`). A lock a bot lets both run at once. Every start checks it logged in as the expected account and exits with code 4 if not; the service stops on exit 4 rather than looping.
- **Windows Update:** active hours 6 am to 12 am, updates paused until 19 Nov (the longest allowed). It restarted the PC twice on the night of 15 Oct; live in its own folder means a reboot only ever brings back the version shipped. A monthly reminder to update by hand is in the backlog.
- **Claude Code** runs on the EliteDesk, started with `claude --remote-control "assistant-bot"`. Alex drives it from the Claude app on his PC or phone. For a fresh start: `/clear`, never `/exit` (that needs a Remote Desktop visit). It pings his phone through ntfy hooks when it finishes or needs him (quiet 10 pm to 7 am).
- **`docs/NOW.md`:** what is happening now, 40 lines at most: the batch, steps done, in progress and next, drafts, what waits on Alex. Updated after every step, "Idle" at a batch's end. A SessionStart hook (`.claude/settings.json`, `scripts/now.ps1`) prints it at every start, resume, `/clear` and compact. Batches commit a checkpoint after each step, so a crash loses one step at most.
- **`/catchup`:** a read-only skill for a session's start or after a reboot: NOW.md, git, the last boot, live in its folder (service, commit, how far behind, account check, switches, the 6 am briefing) and new bugs, in four short parts.
- **Memory:** live about 100 MB; a full self-test adds about 240 MB at most. It won't start under 1.9 GB free.
- **Remote access:** Tailscale plus Remote Desktop, only when something is truly stuck.
- **Costs:** recorded in US$ (what Anthropic bills), shown in NZ$. Daily alert NZ$1.00; self-test cap NZ$3.50 a month (spent for October: recorded answers until November). **A normal day with every feature on is about NZ$0.10**, a busy one about NZ$0.25 (`docs/COSTS.md`, section 8). The router, on every message in words, is US$0.0040 and grows a little with each task. Buttons, dropdowns and typed words cost nothing. 15 Oct batches: NZ$0.25 and NZ$0.79 on understanding checks.

## 5. Principles behind the product

- **docs/CONVERSATION.md** is the standard: never claim something happened that didn't; specific in, exact out; where he points beats what's newest; fill gaps from context like a person would; show before acting (cards); guess when safe, ask when it matters; fewest steps; no clutter; consistent; private.
- **Language is Claude's job, rules are Python's.** Claude reads; code decides, sums and checks.
- **The hub is clean:** only what's relevant now. Finished things leave; the tidy runs at 6 am. **Anything he needs to know must reach him** through the briefing or a ping, never only #bot-log.
- **Privacy:** no pill or event names on the lock screen, the status line, notifications or committed files. Event names never go to Claude. Specs stay private (uncommitted).
- **Core vs task:** behaviour and plumbing in the core; one subject's knowledge in its task; a general tool moves to the core when a second task needs it.
- **New code never imports discord.py.** Tasks produce plain data; one interface layer draws it.
- **New features behind a switch, off by default.** A task whose switch is off is not loaded at all.
- **Timers are frozen:** they work, are never ported, and go if we leave Discord.

## 6. How it's built (one-paragraph tour)

Messages go through fast paths (buttons, exact typed words), then sticky follow-ups and replies, then the router (Claude picks a task, with hints from the code about names he typed), then extraction (Claude fills a strict schema), then Python checks, applies and replies from templates. A question never sticks to the task that just answered, and an open card takes only what could answer or change it. **The scheduler** runs everything timed: tasks give handlers and default schedules, schedules are rows he changes in words ("my schedule"), one engine runs them, a run log stops doubles and catches up after restarts. **The attention model** ranks what matters (1 problem, 2 due now, 3 next timed, 4 untimed, 5 nothing) for the status line, the briefing and pings; something carried over from an earlier day ranks after what fell due today. **The task contract** gives each task a summary (the briefing), attention items, Today card lines and a week line. **The self-test** drives the dev bot against real Discord, files its own bugs, and runs nightly at 3:30 am with recorded answers, then reads back the recorded understanding checks offline.

## 7. Design direction (round 4 live; round 5 built, waiting)

**The hub, top to bottom**
1. **Briefing (read):** posted at 6 am, edited in place all day.
2. **Task cards (do):** one message a task in a fixed order (pills, the Today card, reminders, personal routines, gym, to-dos), each with its buttons; a card with nothing for today is not there.
3. **The moment:** reminders, pings and conversation at the bottom, tidied once dealt with.

**Locked visual rules:** a box a topic, rules between items, the box edge the most urgent state in it; `##` page title, `###` card title with dots and a count (`●●○○○○ 2/6`, no bars, no percentages); bold names, small text for detail; times in bold with "in 2 hours"; changes struck through then bold; thin, stackable question cards; green for the positive action, red for destructive, blurple for other choices, grey only for Cancel.

**Round 4 (live since 15 Oct):** the relevance rule, used by every card (`design.relevant`): what can be done now in full with its button; the next thing in full, no button; the rest of the day one small line of times; done and missed a small line each with a count; paused not shown. One Taken a dose, logged at once, corrected by a reply with a time. **The list rule** for list cards (`design.listed`): the first three in full, "+N more", one dropdown. Personal routines in layout B: the Today card as the overview, and a card a routine from its start time or window.

**Round 5 (built 15 Oct behind `DESIGN_ROUND=5`, posted as "Design · Round 5", waiting on his yes):** from his feedback "there's a little bit of overlap with pills and calendar". The briefing becomes the morning overview: its title is the date with the day's dots ("☀️ Thursday 15 October ●●● 3/3"), so "Today" only means the Today card; Needs a look and Weather keep their boxes; every task with its own card is one line in one overview box, with no progress. A task card whose items are all done leaves the hub and comes back if something new is added (the pills checklist too, unless a dose was missed). No footer: the how-to is in help. With the suggested answers to questions 68 to 75, each marked in the post for his yes or no.

**The design loop** (`docs/DESIGN-LOG.md` is the record: each round, his feedback word for word, what changed)
- The Design forum has a post a round, tagged Live, Preview or Retired, drawn by the real code from made-up data (`python -m selftest.preview --post-round N`), plus other previews ("Design · …").
- **The day-in-the-hub replay** (`python -m selftest.day [--round N]`) runs the dev bot through one made-up day and reads the hub back at eight moments with the status line live would show; `--post` puts it in the forum. Use it for every round.
- Live changes only when he says "ship round N" (`DESIGN_ROUND=N` in live's `.env`, one restart). Every built round stays selectable (1, 3, 4, 5).
- At the start of any design batch, Claude Code reads his replies in each round's post (`--replies-round N`) and copies them word for word into the log.

## 8. Decisions worth remembering

- **Doses are flexible:** planned times are a guide; a late dose stays open and is only missed when it can no longer fit the day. A log without a dose number goes to the earliest open dose. "That was dose N" moves today's log and never adds one.
- **Pill reminders:** at the dose's time, then again 15, 30 and 45 minutes later if left (each a fresh message in place of the last), then they stop; one "last chance" 30 minutes before the dose stops fitting the day. Failed posts retry (1, 2, 5 minutes, then every 5) and never post twice. **The lock-screen line is "💊 Dose due · 2:14 pm"**, repeats "· 2nd reminder", "· 3rd reminder", "· last reminder"; never a pill's name ("Routine due" and "reminder 1 of 3" until 15 Oct).
- **Quiet hours** (10 pm to 7 am) hold non-urgent problems for the briefing and a 7 am ping. Pill reminders and his own reminders always get through. Nothing goes to ntfy.
- **Questions about his day** ("what's left today?", "what's on tonight?", "what's next?", "how did I go this week?", "will it rain?") are answered from data, never by chat and never with a made-up number; the code works out a part of the day and puts things in time order across tasks.
- **A question never sticks** to the task that just answered or to an open card. A correction still sticks.
- **To-dos** (live): a day if given, Done by the dropdown or words, overdue carried over at level 2.
- **Reminders he sets** (live; `nudges` in code): once or repeating, in the hub with Done and Snooze (10 minutes, 1 hour, tomorrow). "done" straight after one went off, or "done the bins", ticks it off. A thing said with a time ("gym at 6", "dentist Friday 3pm") is a reminder; "remind me to …" with no time is a reminder whose card asks when.
- **Personal routines** (live; `habits` in code, layout B): his checklists on chosen days, groups of steps, at a time, any time or in a window, fresh each day.
- **The Today card** (live): today's routines, reminders as notes, events and to-dos, by the relevance rule.
- **The calendar** (live): read only from the secret iCal link in live's `.env`; event names never go to Claude; on the Today card, in the briefing and the status line (an event within 30 minutes, its time only). Writing, later, through a service account and a calendar of the bot's own.
- **Direct messages** are on: he can talk to the bot in a DM.
- **The diary** (built, off): his words about his day, one entry a diary day (to 4:00 am), a mood on a small scale that can change (each entry keeps its scale; `DIARY_MOOD` off keeps none), one gentle ask at 9 pm, a streak with no warnings. Its words stay in the database: no line, log, notification or status line shows them (`Entry.private`).
- **The weekly summary:** pills only, Sunday 7 pm (live). **For everything**, behind `WEEKLY_ALL` (built, off): one card, a box a task (pills taken, late, missed, streak; to-dos done and open; routines as dots; next week's events by day, times only).
- **Cross-task understanding** (15 Oct): 44 golden conversations where a message could fit more than one task, recorded from the real router and extraction; fixes went into the tasks' own lines, never the router's rules. Every self-test run reads them back offline (step u.01).
- **The status line** picks the single most important thing; overdue to-dos no longer hold it over a dose due now.
- **What's new** (`core/whatsnew.py`): a batch can leave a few lines for one morning's briefing.
- **The golden conversations run at noon** on a test clock, never by the real time of day.
- **The test suite** runs in about 40 seconds; `TESTS_AS_ON_LIVE=1` about 80.

## 9. Open threads (update every batch)

**Waiting on Alex**
- **Round 5:** his yes or no on "Design · Round 5", item by item (questions 68 to 75 are marked there). Ready to ship: the latest commit, then `DESIGN_ROUND=5` in live's `.env`.
- **The weekly summary for everything:** his look at "Design · Weekly summary"; for this Sunday, ship then `WEEKLY_ALL=true`, before 7 pm.
- **Gym onboarding:** questions 76 to 79 from "Design · Gym onboarding sketches" (which way in; whether the sheet or the bot holds the plan). Nothing of gym is built.
- **The diary** (built 15 Oct, `DIARY_ENABLED` off): his look at "Design · Diary" and questions 80 to 85 (ask time, the 4 am day, where to write, the ask by DM, the mood scale, whether a feeling with no request should be kept).
- **Live's own folder:** his word that it has had a good day, so the work folder's old `.env` and `data\` can be deleted.
- **Bugs B2 and B5:** both fixed in what live runs (a note on each); only he presses Fixed.
- **QA block 54** (direct messages, by hand): the self-test cannot send a DM.
- **docs/QUESTIONS.md:** 63 (routines with groups, to discuss) and 24 to 28 (gym) besides the above.
- **Windows updates:** by hand before 19 Nov.
- **A latest time for his timed pill**, so the day's schedule and the last-chance nudge fit his real day.
- **`docs/REVIEW.md`**, before the merge into `main`.

**Ready when he wants**
- Calendar stage 2: being told before an event.
- A watch on live (a scheduled task that pings his phone if the service is down).
- Claude Code starting by itself when the EliteDesk boots.
- A read-only web page over Tailscale (history, charts).
- A RAM upgrade (8 to 16 GB) if memory keeps biting.

## 10. Private specs, in short

- **Pills:** doses per day, planned times, minimum gap, latest time. A dose is due at the later of its planned time and the previous dose plus the gap.
- **Scheduler:** handlers, schedule rows, one engine, run log; routines of steps; missed-run rules; local time with daylight saving handled.
- **Briefing:** one card from each task's summary; edited in place.
- **Attention:** the five-level ranking, shared by the status line, the briefing and pings.
- **Calendar:** read only from the secret iCal link; a source interface so the Google Calendar API (a service account, writing only to its own calendar) can come later.
- **Gym:** drafted, waiting on his choice of how a plan comes in.

---

## Maintaining this file

Claude Code: at the end of every batch, update sections 4, 7, 8 and 9 to match what changed (environment, design, decisions, open threads), and anything else now out of date. Keep it under about 250 lines, in the same plain style. Never add a pill or event name, a bot's display name, a precise location, or any secret. Commit it with the batch.
