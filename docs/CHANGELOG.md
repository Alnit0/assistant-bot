# Changelog

What changed, newest first. One entry per task, as one to three bullets on
what changed for the user. Entries before 2026-10-07's last one were
backfilled from the git log.

## 2026-10-09

- **A message with a question and a request gets both.** "What's the
  capital of France, and add milk to the shopping list" now answers the
  question and then shows the card; before, the question was dropped.
- **A new way of handling plain words, ready to try on the dev database.**
  A small "router" works out which task a message is for; the task's own
  code then shows a card with its best reading (guesses marked ❓, problems
  ⚠️ with the fix applied) and saves only when you press Save. Say what to
  change and the card is replaced. Every confirmation is written by the
  bot's code, never by Claude. Two demo lists (shopping 🛒 and packing 🧳)
  exist on the dev database to try it with; timers, bugs and pills move
  to it next. Nothing changes on the live bot yet.
- If your `data\dev.db` is from before this evening, delete it once: it
  remembers a pills table that no longer exists and the dev bot won't
  start with it.
- **`dev cost` shows what the bot costs.** Today and this month: the
  total, how many messages went to Claude and how many were handled
  without it (shortcuts, buttons, reactions), the average cost, requests
  and seconds per message, and the most expensive task. Every message is
  now logged with how it was handled; what was already logged is counted
  too.
- **Adding a pill is one step again.** Asking for one shows its preview
  straight away: no more "I'm proposing… reply ok" before it. That "ok"
  is now only for things the bot suggests that have no preview of their
  own. Replies no longer show how the bot did something, and the bot is
  told to write times of day as `8:00 pm` (its cards and previews always
  do).
- **"Add …" is never guessed between tasks.** A bare "add" is not a
  shortcut; when more than one kind of thing could be meant you get a
  button for each.
- **Set up your pills by saying so.** In #inbox: "add vitamin D, once a
  day", "add evening pill at 20:00", "add course A, 3 times a day, at
  least 3 hours apart, with food, for 7 days starting tomorrow". You get
  a one-line preview with **Save** and **Edit**; nothing is added until
  you press Save. "At 8" is asked about (8am or 8pm?) rather than
  guessed, and a pill with no end is never asked for dates.
- **`pills` lists them** (in use, paused, ended) with a dropdown to pick
  one, then Edit, Pause / Resume and Remove. Changing one by words ("move
  the evening pill to 9pm") shows the old and new plan to save. "Pause
  iron until the 20th" acts at once; removing asks first and keeps the
  history; "delete iron and its history" is a separate, final question.
- Nothing reminds you yet: the daily checklist and prompts are the next
  stages.
- **A dev database and a clock you can move.** `python main.py --dev`
  runs the bot on `data/dev.db`, with "DEV DATABASE" in its status, its
  hello and the dev panel. There, `dev clock 5:59am`, `dev clock +2h` and
  `dev clock reset` move the bot's time (forward only; reset goes back)
  and everything that came due on the way runs in order. `dev reset-db`
  wipes it after asking. On the live database both are refused with the
  reason, so real history is never touched.
- **Foundations for pills and reminders** (nothing new to type yet): one
  midnight day boundary for every task, one reader for typed times that
  asks "8am or 8pm?" instead of guessing and always shows `8:04 am`, and
  a log of what is expected each day with every change kept.
- **The scheduler runs chained jobs in one pass**, so a job booked by
  another and already due no longer waits up to 15 seconds.
- **Specs are private and backed up.** `docs/specs/` stays out of git, so
  the nightly backup now zips it beside the database copy
  (`specs-*.zip`, newest 7 kept) and names both on the log card.
  `dev run backup` does the same.
- **A hub channel can be set** with `HUB_CHANNEL_ID` in `.env`; nothing
  posts there yet.
- **One bot is counted as one.** `python -m core.instance_lock` (and
  `dev status` in Discord) says how many bots are running by asking the
  lock, and no longer takes the `.venv` launcher and the Python it starts
  for two copies. The cheat sheet shows how to tell them apart by
  ParentProcessId.
- **A closed bug can be re-opened.** Pressing Fixed or Won't fix swaps
  both buttons on the post's opening card for one **Re-open** button, and
  the card's foot shows the status and when it changed ("✅ Fixed ·
  1:25pm, 9 Oct"). Re-open unarchives the post, puts the Open tag and the
  two buttons back, and is kept in the bug's history with every closing
  (shown by `bugs export`).
- **The opening card counts the notes** ("📝 2 notes"), updated in place
  each time you write one.
- **Dev mode starts again with a #bugs forum set.** Its start-up sweep
  for an old panel read the pins of every channel in `.env` and failed on
  the forum, which has none. Forum, voice and category channels are now
  skipped everywhere pins or history are read.
- **The forum's tags are created in one go at every start** while any is
  missing. If the bot lacks Manage Channels you get one warning in
  #bot-log naming it, not one per tag.
- **Report a bug with 🐞 or `bug`.** React 🐞 to a message, reply `bug` to
  it, or type `bug` on its own for the latest thing in the channel. It is
  logged at once (no 30-second wait) and the channel gets "🐞 Logged as
  B4", linking to the bug's post in the new #bugs forum. The post holds
  the message, the five before it, that turn's tool calls, timings and
  log errors, and the commit, then asks three questions. What you write
  there is saved as a note and ticked ✅; nothing in #bugs goes to
  Claude. Press **Fixed** or **Won't fix** to tag and archive it. `bugs`
  lists the open ones; `bugs export` writes them to `docs/BUGS.md`. Needs
  `BUGS_CHANNEL_ID` (a forum channel) in `.env`.
- **Confirmations now stay.** `KEEP_CONFIRMATIONS` (on by default) leaves
  "📦 Archived" and the other self-deleting notes in the channel, so you
  can see what the bot did. Your command words are still tidied away. Set
  it to `false` for the old behaviour.
- **Claude Code can fix a bug from its id** (the `bug` skill: "fix B4").
  It reads what was captured, reproduces it with a failing test, fixes
  it, and leaves "fix ready, needs retest" on the bug, which `bugs`
  shows. Closing it stays with you.
- **The bot's features are now called tasks, not skills.** `skills/` is
  `tasks/`, the base class is `Task`, the setting is `ENABLED_TASKS` (an
  `.env` that still says `ENABLED_SKILLS` goes on working). "Skill" now
  only means a Claude Code Skill in `.claude/skills/`; the planned list
  of things to do will be "to-dos". `dev run` runs "routines". Nothing
  you type has changed. Earlier entries below keep the old word.
- **Asking in plain words is fast.** "Set a timer for 5 minutes" took 7
  to 10 seconds, and 30 or more after a restart; Claude's part is now
  about 1.5 seconds. Your message gets 👀 the moment it arrives. Claude
  is told what is running with every message, so it acts in one step,
  and when the action has shown its own confirmation it adds nothing.
  The board, lists and cards catch up a moment after the reply.
- **"Cancel all timers" and "stop all timers called tea" work in one
  go.** Any number of timers, by name whatever the case (tea, Tea 2),
  with one message naming each. "Stop" means cancel. Before, it stopped
  after four and said there was no timer called tea.
- A request to Claude that hangs is given up after 15 seconds and
  retried twice, and retries show on the log card.

## 2026-10-07

- **The log card says where the time went.** "Message handled" has a
  Timing field: the seconds until the reply, each request to Claude (time,
  tokens, cache), each tool, the time spent calling Discord, rate-limit
  waits and retries. `bot.log` gets the same on a `Timing:` line. Nothing
  is faster yet: this is the measurement the speed-up work starts from.
- **The "Your timers" list is live.** It was a snapshot whose countdowns
  ran on after a pause, which made paused timers look as if they had
  gained time (they hadn't). There is now one list per channel, rewritten
  whenever a timer changes.
- **`pause all` and `resume all`**, typed or asked for: every timer and the
  Pomodoro (add `except pomodoro` to leave it), with a reply naming each
  one and its time left. Claude can also tell you what happened to a
  timer and when ("what was left on dinner when I paused it?").
- Fixes: a timer keeps the speed it was started at, so changing `dev
  speed` mid-run no longer changes its time left; a timer whose time is up
  can't be paused; Claude saying "running again" without resuming
  anything is caught, and its timer tools report what was actually saved.
- **Claude tells the truth about what it did.** It was copying a
  "[Tool calls this turn: …]" note that the bot added to its own earlier
  replies, and saying "Done" without doing anything. The note is gone, any
  it writes is removed, and a "done" with nothing run is sent back to it
  (and logged in #bot-log) before you see it.
- **It can see your timers.** "Show my timers" and "how long left on my
  Pomodoro?" are answered from the live state, and "pause the tea timer",
  "unpause it", "skip this break" act on the right one wherever its
  message is. Asking for a Pomodoro while one is going gets one reply and
  an offer to restart at the lengths you asked for (typed `pomo 25/5`
  asks the same with a button).
- `dev mode on` / `dev mode off` work, typed or asked for. "Look further
  back" searches your older messages in the channel and asks before
  acting on what it finds. Reply `unpause` works like `resume`.
- **Claude can now do things.** Ask in plain words ("set a timer for 5
  minutes", "file that away") and it runs the same actions you can type:
  every word and reply action is offered to it as a tool, filtered by
  channel and permission (never the lab; dev tools only in dev mode).
  Typed words still run directly, without Claude.
- It acts at once on a clear request, asks when unsure, and when it is
  only suggesting it waits for your `ok` (2 minutes). Destructive actions
  always ask with Confirm / Cancel. A message you describe rather than
  reply to is shown quoted, with Undo where possible, and if several fit
  you pick with buttons. At most 5 tool calls per message.
- Every tool call is logged, and the "Message handled" card shows the
  tools sent, their token cost, cache use and each call's outcome.
- **QA findings.** Every message now has a lifecycle class (Kept, Live,
  Consumed, Transient, Alert, Protected) and one policy decides what is
  deleted; `dev cleanup off` stops all automatic deletion and `dev inspect`
  shows a message's class. Seed instructions now stay.
- Reactions and reply actions that can't work (archiving in #bot-log, say)
  are refused at once with ⚠️ and a short reason, instead of after the
  30-second wait. Reply `pin` / `unpin` are new, and replies accept filler
  words ("pin this", "please archive it").
- `pomo` while a session runs shows its card again instead of failing. The
  assistant's name is the `ASSISTANT_NAME` setting, and Claude is told it
  has no tools and must never offer to do something itself.
- Add `DEV_CHANNEL_ID`: a scratch channel for manual testing, known to the
  bot as `dev`. The QA run sheet now uses it instead of #documents.
- Add `docs/ARCHITECTURE.md` (a map of every file and the main data flows),
  trim `CLAUDE.md` to the essentials and move the procedures into project
  skills (`add-skill`, `qa`, `end-of-task`). Add this changelog.
- **Keep:** 📌 is now a reaction. It pins the message and protects it;
  taking it off unpins. A full channel gets ⚠️ with the reason in #bot-log.
  `dev inspect` shows "Kept".
- Add the QA run sheet (`docs/QA-RUN.md`): the manual tests in ordered
  blocks.
- **Dev mode:** `dev on` gives faster waits, debug cards in #bot-log, a
  pinned panel and inspection tools. Tests now run with pytest, and
  `docs/TESTING.md` tracks every Auto and Manual test.
- **Reactions and archive brought into line with the interaction rules:**
  reactions act on where they ended up, get ✅ when applied, are undone on
  removal and get ⚠️ on failure. Archive and delete ask before touching
  pinned or 📌-marked messages. New 🗑️ reaction, a Restore button on
  archived copies, and all pin notices are deleted. Timer and Pomodoro
  alerts clear when acknowledged.
- Add the interaction rules (input, reactions, cleanliness, notifications,
  interactions) that every skill follows.
- **Timers and Pomodoro:** `timer`, `timers`, `pomo` and `pomo stats`, with
  reply actions (`cancel`, `pause`, `resume`, `+10m`) and one pinned "Active
  timers" board per channel. They survive restarts and report late finishes.
- Reply actions can match a pattern (`+10m`) and decline messages that
  aren't theirs, so words like `cancel` only act where they apply.
- **Scheduler** is now database-backed: jobs survive restarts and are
  caught up after downtime.
- Lab: `lab tour` (a guided, resumable test run), `lab channels`
  (notifications across channels) and delayed `lab notify`.
- Commands tidy up after themselves: a word or reply that works is
  deleted, with a short self-deleting confirmation; one that fails stays
  and gets ⚠️.
- **Typed words, reply actions and reactions** replace slash commands as
  the main way in, with typo tolerance, debounced reactions and a `help`
  generated from what is registered.
- Only one copy of the bot can run (a lock on `data/bot.lock`); interaction
  error handling no longer raises.

## 2026-10-06

- Fix persistent lab buttons; report buttons and forms that nothing
  answered.
- **Archive:** move a message to the archive channel under its author's
  name and avatar, with attachments and a link back. Add `/lab chart`.
- **Lab:** a test bench for Discord features (reactions, buttons, forms,
  pinned status, notifications), with slash commands and a reusable
  debouncer in the core.
- **Skills system:** features live in `skills/`, are discovered by a
  registry and get a `Context` instead of a Discord message.
- Add schema migrations, the users table, one permission check, async
  database calls and nightly backups.
- Split `bot.py` into the `core` package.
- Add `CLAUDE.md`, the development guide and the decisions log.

## 2026-10-05

- Add placeholders for all planned channel ids.
- Connect the Claude API, with short-term conversation memory.
- First proof of concept: the bot replies in #inbox.
