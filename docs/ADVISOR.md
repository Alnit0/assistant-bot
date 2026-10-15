# Advisor handover

**Read this first** when Alex starts a new chat with Claude (the advisor). It holds what the code and the other docs don't: how we work together, the thinking behind decisions, and what's open right now.

**Kept up to date by Claude Code** at the end of every batch (see "Maintaining this file" at the bottom).

Never write here: a real pill name, a bot's display name, a location more precise than "Auckland", a token, topic or ID.

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
- Always complete and ready to paste. **No placeholders** like `<paste here>`, and never leave options (A/B) for him to delete: ask him first, then write one prompt.
- Mark prompts that should keep Claude Code's context with "(↪️ no clear)".
- **Always say up front** whether a prompt will commit, push, run a self-test, or restart live.
- Batches run unattended: tell Claude Code to decide and note under "Decided" in docs/STATUS.md rather than stop, unless live or data is at risk.
- Spend limits go in NZ$: per run under NZ$0.40, a batch cap stated in the prompt.
- Self-tests run as the dev bot (live stays up), never between 3:15 and 4:30 am (the nightly run at 3:30 am, moved from 3:00 on 15 Oct so it no longer starts with the backup).
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

- **The EliteDesk:** Windows 11, 8 GB RAM. Runs the live bot as the NSSM service `assistant-bot` from `C:\Users\temp\projects\assistant-bot`.
- **Branch:** all work is on `feature/pills`. Nothing is merged into `main` yet; `docs/REVIEW.md` is the checkpoint for that.
- **Two bots:** live, and the dev bot (own token in `.env.dev`). A per-bot lock lets both run at once. Every start checks it logged in as the expected account (`BOT_USER_ID`) and exits with code 4 if not; the service stops on exit 4 rather than looping.
- **Claude Code** runs on the EliteDesk, started with `claude --remote-control "assistant-bot"` in the project folder. Alex controls it from the Claude desktop app on his PC or phone.
  - For a fresh start: `/clear`, never `/exit` (that ends the process and needs a Remote Desktop visit to restart).
  - It pings Alex's phone through ntfy hooks when it finishes or needs him: priority 5 by day, quiet 10 pm to 7 am.
- **Memory:** live uses about 100 MB; a full self-test's own processes peak at about 180 MB (the dev bot about 120), taking at most about 240 MB off what's free. Chrome and VS Code left open on the EliteDesk were what ran it short. The self-test won't start under 1.9 GB free.
- **Remote access:** Tailscale plus Remote Desktop, only when something is truly stuck.
- **Reboots:** Windows Update restarted the EliteDesk twice on the night of 15 Oct (00:23 and 00:26), cutting a batch off. Live came back by itself, but from the project folder, so on the batch's uncommitted work; the 3 am self-test ran on it too. Live in its own folder on a commit is the fix (backlog, Next 5).
- **`docs/NOW.md`:** what is happening now (40 lines at most): the batch, steps done, in progress and next, drafts and worktrees, what waits on Alex. Claude Code updates it after every step and resets it to Idle at a batch's end; a SessionStart hook in the committed `.claude/settings.json` (`scripts/now.ps1`) prints it at every start, resume, `/clear` and compact. Batches commit a checkpoint after each finished step (push at the end), so a crash loses one step at most; drafts live in `docs/drafts/` (committed) or `docs/specs/` (private), never only in a scratchpad.
- **`/catchup`:** a Claude Code skill Alex runs at a session's start or after a reboot (works through remote control): reads `docs/NOW.md` first, git, the last boot, live (service, account check, switches, the 6 am briefing) and new bugs, reports in four short parts, then waits. Read only.
- **Live's look:** `CARDS_V2=true` and `DESIGN_ROUND=3` in live's `.env` since 15 Oct, 8:59 am: the hub is in round 3.
- **Costs:** recorded in US$ (what Anthropic bills), shown in NZ$ at a daily rate. Daily alert NZ$1.00; self-test cap NZ$3.50 a month (spent for October, so self-tests use recorded answers until November). 15 Oct: the batch spent NZ$0.25 on understanding checks for the new tasks. A heavy build day cost about NZ$2.30; a normal day should be well under NZ$0.50.

## 5. Principles behind the product

- **docs/CONVERSATION.md** is the standard. In short: never claim something happened that didn't; specific in, exact out; where he points beats what's newest; fill gaps from context like a person would; show before acting (cards); guess when safe, ask when it matters; fewest steps; no clutter; consistent; private.
- **Language is Claude's job, rules are Python's.** Claude reads; code decides and checks.
- **The hub is clean:** only what's relevant now. Finished things leave; the tidy runs at 6 am. #bot-log stays as a just-in-case record, but **anything he needs to know must also reach him** through the briefing or a ping.
- **Privacy:** no pill names on the lock screen, the status line, notifications or committed files. Specs stay private (uncommitted).
- **Core vs task:** how the bot behaves and the plumbing go in the core; one subject's knowledge goes in its task; a general tool moves to the core when a second task needs it.
- **New code never imports discord.py.** Tasks produce plain data; one interface layer turns it into Discord. Keeps a future web app possible.
- **Timers are frozen:** they work, are never ported, and go if we leave Discord.

## 6. How it's built (one-paragraph tour)

Messages go through fast paths (buttons, exact shortcuts), then sticky follow-ups and replies, then the router (Claude picks a task), then extraction (Claude fills a strict schema), then Python checks, applies and replies from templates. A question never sticks to the task that just answered, and an open card takes only what could answer or change it: anything else goes to the router and the card stays open. **The scheduler** runs everything timed: tasks register handlers, schedules are database rows Alex can change by words ("my schedule"), one engine runs them, and a run log prevents doubles and catches up after restarts. **The attention model** ranks what matters (1 problem, 2 due now, 3 next timed, 4 untimed, 5 nothing) and feeds the status line, the briefing and pings. **The notify service** routes alerts; the bot's ntfy is off. **The self-test** drives the dev bot against real Discord, files its own bugs, and runs nightly at 3:30 am with recorded answers.

## 7. Design direction (round 3 built and live since 15 Oct)

**The hub, top to bottom**
1. **Briefing (read):** posted at 6 am, edited in place all day. Page title, then a box per topic: Needs a look (only if something's wrong), weather, today's overview in time order. A spoiler line for yesterday's spend.
2. **Task cards (do):** one message per task, fixed order (pills, then reminders, personal routines, gym, to-dos), each with its buttons; a card with nothing for today is not there.
3. **The moment:** reminders, pings and conversation appear at the bottom and are tidied once dealt with.

**Inside a card:** ordered by time: due or overdue first, then coming up, then any time, then done collapsed into one small line.

**The status line:** the single most important thing, e.g. `💊 2/6 · 12pm`, `⚠️ B14 · backup failed`, `🌅 6am`. Later, a "flavour" line when nothing matters (streak, a playful line, a countdown).

**Visual rules (round 3 brief)**
- **Boxes separate topics**, never sections within one topic. Horizontal rules separate items inside a box. The box edge colour is the most urgent state in it.
- **Type scale, like a webpage:** `##` page title once per message; `###` card title with progress; **bold** item names; normal text for values; `-#` small text for details.
- **Progress is dots**, `●` done and `○` to do, with a count (`●●○○○○ 2/6`). **No block bars** (they rendered badly) and no percentages. More than 10 things: 10 dots scaled, exact count after.
- **Times in bold, never inline code.** Discord timestamps for "in 2 hours".
- **Changes:** `~~8:00 pm~~ → **9:00 pm**`.
- **Thin question cards**, stackable.
- **Buttons:** green for the positive action, red for destructive, blurple for other choices, grey only for Cancel (with ↩️). Buttons only on what can be acted on now.
- No placeholder tasks.

**The design loop** (`docs/DESIGN-LOG.md` is the record: every round, what is locked, Alex's feedback word for word, and the changes it led to)
- Each round is a post of its own in the Design forum ("Round N", tagged 🟢 Live, 🟡 Preview or ⚪ Retired), drawn by the real code from made-up data (`python -m selftest.preview --post-round N`). No real pill names. Rounds 1 to 4 before 15 Oct are in the old design-options post of the bugs forum.
- Live changes only when Alex says "ship round N" (`DESIGN_ROUND=N`, one restart). Every round that was built stays selectable, so "go back to round N" is the same setting. Today: round 1 (the look before), round 3 and round 4 (live from 15 Oct).
- At the start of any batch that touches the design, Claude Code reads his replies in each round's post (`--replies-round N`, as the dev bot), copies them word for word into the log, and turns them into a numbered list of changes. Locked parts (rules inside boxes, a box a topic, dots with a count, thin question cards, changes struck through then bold) change only if he names them.

**Round 4 (live from 15 Oct):** the relevance rule, locked: what can be done now in full with its button; the next thing in full, no button; the rest of the day one small line of times; done and missed a small line each with a count; paused not shown. It is `design.relevant` over `design.Thing`s, so every card uses the same rule. One Taken button a dose, logged at once, corrected by a reply with a time. Skip is said in words. **The list rule** for any list card (to-dos first): the first three open things in full, "+N more", and one dropdown for what can be done to any of them (25 at most, then words), never a button each (`design.listed`).

**Ideas for later:** a webhook persona per task (an animal each, matching the server's theme); avatar changes for day and night; the channel topic as a second status spot; private replies that only he sees, for button confirmations.

## 8. Decisions worth remembering

- **Doses are flexible:** planned times are a guide. A late dose stays open and is only missed when it can no longer fit the day. A log without a dose number goes to the earliest open dose. One "last chance" nudge 30 minutes before a dose stops fitting.
- **"That was dose N"** corrects today's log (moves it, keeps the time) and never adds a dose.
- **Failed pill reminders retry** (1, 2, 5 minutes, then every 5) and never post twice. No ntfy fallback.
- **Quiet hours** (10 pm to 7 am) hold non-urgent problems for the briefing and a 7 am ping. Pill reminders always get through.
- **The bot names itself** from `BOT_NAME`; the only suffix is the dev bot's "· testing" during a self-test.
- **Commits:** Claude Code commits and pushes when asked in a prompt; `main` will be the reviewed version.
- **History is not rewritten** for the old "part of the city" wording (low risk).
- **Questions about his day** ("what's left today?", "how did I go this week?", "will it rain?") are answered from data by the briefing and weather tasks, never by chat and never with a made-up number. Behind `DAY_QUESTIONS` and `DAY_PROGRESS`, both on for live.
- **A question never sticks** (14 Oct): not to the task that just answered, and not to an open card, which takes only what answers or changes it and stays open. A correction still sticks.
- **Round 3 is the hub's design** (15 Oct, live): a message reads like a page, a box a topic, dots with a count, times bold with "in 2 hours", changes struck through then bold, thin question cards, a card too big for one message made to fit. Its picks are in docs/STATUS.md under "Decided (round 3)" and wait on his phone review.
- **Three hub tasks built to his defaults and switched off** (15 Oct, pending his review, questions 51 to 66): to-dos (`TODOS_ENABLED`: a day if given, Done by button or words, overdue carried over at level 2, today's at level 4), reminders he sets (`NUDGES_ENABLED`: once or repeating, posted in the hub with Done and Snooze for 10 minutes, 1 hour or tomorrow, through quiet hours, never twice, retried like pill reminders, late after a restart; never ntfy) and personal routines (`HABITS_ENABLED`: his checklists on chosen days, starting afresh each day). In docs they are "Reminders" and "Personal routines"; the code folders are `nudges` and `habits`.
- **A task whose switch is off is not loaded**: out of help, #commands and the router.
- **What's new** (`core/whatsnew.py`): a batch leaves a few lines for one morning's briefing (`python -m core.whatsnew add "…" --on <day>`), shown once in a box under Needs a look and gone after the tidy. Reuse it at the end of any batch Alex should hear about.
- **His answers of 15 Oct** (one line each in docs/STATUS.md, Decided): round 3 settled the design picks; the suggestions kept for alerts, quiet hours, mornings, pills and the new tasks; the nightly self-test at 3:30 am (no self-test between 3:15 and 4:30 am); `WEEKLY_SUMMARY` on; direct messages on once QA block 54 passes; gym in kilograms; the calendar Google, read only, by its private link, names matched by code and never sent to Claude (not built); a reminder's lock-screen line neutral; task cards with no `##` page title.
- **The golden conversations run at noon** (15 Oct): they had gone by the real time of day and broke when a run crossed midnight.
- **A question gets the answer itself, where it is asked** (15 Oct): "what pills are left?" had been answered with only a pointer to the hub. Now the doses still to take, in time order, the first line naming no pill; a pointer may follow an answer, never replace it (golden 29). A DM while DMs are off gets one line saying so.
- **A reply to a pill line corrects the day that line is about** (15 Oct): "actually I didn't" to last night's line after midnight makes that dose missed and leaves today alone.
- **To-dos have their own self-test stage** (start 7, recorded answers, 9 of 9).
- **Alex tested everything at once** (15 Oct): routines merged the day they were built, with layout B (the Today card, and a card a routine from its start) the default; the self-test gained start 9 (reminders, routines, the Today card). The Design forum has one post a round, tagged Live, Preview or Retired.
- **Round 4 shipped the day it was previewed** (15 Oct): he picked Taken at once (question 67), asked for the list rule on to-dos at once rather than in round 5, and said ship it. Every self-test start but 8 is pinned to round 3, so live's own `DESIGN_ROUND` never decides a step.
- **The test suite runs in about 40 seconds** (it had grown to nearly two minutes). `TESTS_AS_ON_LIVE=1` runs the same tests with real threads and connections, about 80 seconds.

## 9. Open threads (update every batch)

**Waiting on Alex**
- **Round 3 on his phone:** it is live; his feedback (in the design-options post) goes into docs/DESIGN-LOG.md as round 4. His first piece, from question 64, is done: task cards have no `##` page title.
- **docs/QUESTIONS.md:** three left after his answers of 15 Oct: 11 (his lock-screen screenshot of a pill reminder is on its way), 63 (personal routines reworked with groups of steps, one button a group: to discuss), 24 to 28 under "Gym onboarding" (he designs how a plan is set up first).
- **QA block 54 by hand** (top of docs/QA-RUN.md): direct messages go on only once it has passed; the self-test cannot send a DM.
- **The private Google Calendar link,** for live's `.env` only. Never in a doc, a commit or a message.
- **A latest time for his timed pill,** so the day's schedule and the last-chance nudge fit his real day.
- **`docs/REVIEW.md` and QA blocks 53 to 55,** before the merge into `main` and live's own folder (the next infrastructure job).
- **Bugs:** 2 open on live, both from before 12 Oct. Only he closes a live bug (he presses Fixed).

**Ready when he wants**
- Everything built on 15 Oct is live from 1:32 pm that day: round 4, to-dos, reminders, personal routines (layout B), the Today card, the weekly summary and DMs. If one misbehaves, its switch goes off and live restarts (`data/env-before-2026-10-15-restart` is the `.env` before).
- Live in its own folder on a committed version: prepared and dry-run (docs/LIVE-FOLDER.md, `scripts\update-live.ps1`, with `-Back` to roll back); the switch-over is his go-ahead at a later restart.
- Personal routines reworked (groups, windows, nudges), a shared repeat system and a Today card: asked on 15 Oct, to be built on `feature/routines`, off in live. His message was cut off at its fourth point (the preview, "Also show the Today card with a…"): ask him for the rest.
- A watch on live (a Windows scheduled task that pings his phone if the service is down): later.
- A `/fix-bugs` skill for Claude Code; later, an overnight scheduled fix run on a separate branch.
- Claude Code starting by itself when the EliteDesk boots.
- A read-only web page over Tailscale (history, charts).
- A RAM upgrade (8 to 16 GB) if memory keeps biting.

## 10. Private specs, in short

- **Pills:** doses per day, planned times, minimum gap, latest time. A dose is due at the later of its planned time and the previous dose plus the gap.
- **Scheduler:** handlers, schedule rows, one engine, run log; routines; missed-run rules; local time with daylight saving handled.
- **Briefing:** one card built from each task's summary section; edited in place.
- **Attention:** the five-level ranking above, shared by status line, briefing and pings.
- **Gym and calendar:** drafted, waiting on Alex's answers.

---

## Maintaining this file

Claude Code: at the end of every batch, update sections 4, 8 and 9 to match what changed (environment, new decisions, open threads), and anything else now out of date. Keep it under about 250 lines, in the same plain style. Never add a pill name, a bot's display name, a precise location, or any secret. Commit it with the batch.
