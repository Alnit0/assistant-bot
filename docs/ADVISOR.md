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
- Self-tests run as the dev bot (live stays up), never between 2:45 and 4:00 am (the nightly run).
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
- **Costs:** recorded in US$ (what Anthropic bills), shown in NZ$ at a daily rate. Daily alert NZ$1.00; self-test cap NZ$3.50 a month (spent for October). A heavy build day cost about NZ$2.30; a normal day should be well under NZ$0.50.

## 5. Principles behind the product

- **docs/CONVERSATION.md** is the standard. In short: never claim something happened that didn't; specific in, exact out; where he points beats what's newest; fill gaps from context like a person would; show before acting (cards); guess when safe, ask when it matters; fewest steps; no clutter; consistent; private.
- **Language is Claude's job, rules are Python's.** Claude reads; code decides and checks.
- **The hub is clean:** only what's relevant now. Finished things leave; the tidy runs at 6 am. #bot-log stays as a just-in-case record, but **anything he needs to know must also reach him** through the briefing or a ping.
- **Privacy:** no pill names on the lock screen, the status line, notifications or committed files. Specs stay private (uncommitted).
- **Core vs task:** how the bot behaves and the plumbing go in the core; one subject's knowledge goes in its task; a general tool moves to the core when a second task needs it.
- **New code never imports discord.py.** Tasks produce plain data; one interface layer turns it into Discord. Keeps a future web app possible.
- **Timers are frozen:** they work, are never ported, and go if we leave Discord.

## 6. How it's built (one-paragraph tour)

Messages go through fast paths (buttons, exact shortcuts), then sticky follow-ups and replies, then the router (Claude picks a task), then extraction (Claude fills a strict schema), then Python checks, applies and replies from templates. A question never sticks to the task that just answered, and an open card takes only what could answer or change it: anything else goes to the router and the card stays open. **The scheduler** runs everything timed: tasks register handlers, schedules are database rows Alex can change by words ("my schedule"), one engine runs them, and a run log prevents doubles and catches up after restarts. **The attention model** ranks what matters (1 problem, 2 due now, 3 next timed, 4 untimed, 5 nothing) and feeds the status line, the briefing and pings. **The notify service** routes alerts; the bot's ntfy is off. **The self-test** drives the dev bot against real Discord, files its own bugs, and runs nightly at 3 am with recorded answers.

## 7. Design direction (agreed, not all built)

**The hub, top to bottom**
1. **Briefing (read):** posted at 6 am, edited in place all day. Page title, then a box per topic: Needs a look (only if something's wrong), weather, today's overview in time order. A spoiler line for yesterday's spend.
2. **Task cards (do):** one message per task, fixed order (pills, then gym, then to-dos), each with its buttons.
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
- **The test suite runs in about 40 seconds** (it had grown to nearly two minutes). `TESTS_AS_ON_LIVE=1` runs the same tests with real threads and connections, about 80 seconds.

## 9. Open threads (update every batch)

**Waiting on Alex**
- **Design round 3:** in the design-options forum post, with the day's dots in the title (R3-A) or as a line of text (R3-B). The picks are questions 12 to 15, 21, 22 and 45 to 48; the type scale is a draft in docs/DESIGN.md until he says what to change. Ask him for phone screenshots and fine-tune from those.
- **docs/QUESTIONS.md:** 45 open questions with suggested answers; he can reply "yes to all except…".
- **A latest time for his timed pill,** so the day's schedule and last-chance nudge fit his real day (questions 43 and 44 are about the nudge without one).
- **Gym:** a first build waits on six answers (questions 23 to 28): kilograms for everything; the plan as a `.csv`; next workout in turn or fixed weekdays; today's workout posted in the hub; posted only when asked or by itself; logging a whole exercise at once or set by set. Sixteen more are in its spec. He has the plan in a spreadsheet he'll attach.
- **Calendar:** stage 1 waits on four answers (29 to 32): which calendar; read only to begin with; access by the private read-only link or by signing in; whether event titles may be given to Claude.
- **His short QA list** at the top of docs/QA-RUN.md: eleven checks only he can do (looks, colours, lock screen, how things read), most useful first.
- **Bugs:** 2 open on live. Only he closes a bug (he presses Fixed).

**Ready when he wants**
- Switch `CARDS_V2` on once the design is settled.
- A `/fix-bugs` skill for Claude Code; later, an overnight scheduled fix run on a separate branch.
- Claude Code starting by itself when the EliteDesk boots.
- A read-only web page over Tailscale (history, charts).
- Merging `feature/pills` into `main` after reading `docs/REVIEW.md`; then live in its own folder on `main`.
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
