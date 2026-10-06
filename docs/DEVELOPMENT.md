# Development guide

## Environment

- **Server:** Windows 11 mini PC, always on, reachable over Tailscale
- **Access:** Remote Desktop for anything graphical, SSH for terminal work
- **Editor:** VS Code with Remote SSH, connected to the server
- **Repo location on server:** `C:\Users\<user>\projects\assistant-bot`

## First-time setup

1. Clone the repo
2. Create the virtual environment: `python -m venv .venv`
3. Activate it: `.\.venv\Scripts\Activate.ps1`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in real values
6. Run: `python main.py`

VS Code is configured (`.vscode/settings.json`) to activate `.venv`
automatically in new terminals. Check the prompt starts with `(.venv)`.

## Project layout

- `main.py`: entry point. Creates the Discord client, wires events, starts the bot
- `core/`: shared building blocks. Never imports from `skills/`
  - `config.py`: paths, settings from `.env`, validation, constants, channel names
  - `logging_setup.py`: terminal and rotating file logging
  - `instance_lock.py`: makes sure only one copy of the bot runs
  - `database.py`: connections and the async database helpers
  - `migrations.py`: schema migrations, applied at startup
  - `users.py`, `permissions.py`: users and the `is_allowed` check
  - `router.py`: decides whether a message is a registered word (with typo tolerance)
  - `context.py`: the `Context` object handed to skills
  - `interactions.py`: permission check and logging for slash commands and menus
  - `errors.py`: `UserError`, for problems the user can fix
  - `scheduler.py`: stored jobs that run at a moment in the future, with catch-up
  - `backup.py`: nightly backup (a scheduler job) and pre-migration snapshots
  - `debounce.py`: waits for a quiet period, then handles events together
  - `reactions.py`: what to apply or undo once reactions have settled
  - `protection.py`, `confirmations.py`: pinned and 📌-marked messages, and
    asking before acting on them
  - `llm.py`: Claude client, system prompt, history, cost estimates
  - `discord_utils.py`: #bot-log embeds, message helpers, safe replies
- `skills/`: one folder per feature
  - `base.py`: the `Skill` base class and the `Keyword`, `ReplyAction`, `Reaction` records
  - `registry.py`: finds and loads skills, dispatches to them, and knows everything
    the bot can do (for `help` and for Claude)
  - `builtin/`: ping, reset, buttons, stats, help
  - `archive/`: archive or delete a message (reply, 📦 / 🗑️ reaction, context
    menu), with a Restore button on archived copies
  - `lab/`: `lab …` words for trying out Discord features
  - `timers/`: short timers and Pomodoro sessions
- `tests/`: unit tests (`python -m unittest`)

Always run `main.py` (not the files in `core/` or `skills/`). Paths are
worked out from the project root, so it runs correctly from any working
directory.

## How to talk to the bot

There are three main ways in, and one fallback. `help` lists what works in
the channel you are in; `help <skill or word>` gives details.

| Way in | Example | Where |
|---|---|---|
| **A word on its own** | `stats`, `clear chat`, `lab chart 30` | Mostly #inbox; `lab …` and `help` anywhere |
| **Reply to a message with a word** | reply `archive` or `delete` | Anywhere |
| **A reaction** | 📦 or 🗑️ on a message | Anywhere |
| Slash command (fallback) | `/lab chart`, Apps > Archive message | Anywhere |

- **The whole message must be the word or phrase.** `stats` runs stats;
  `stats please` is a message for Claude. Case and a full stop at the end
  don't matter.
- **Small typos are forgiven:** one wrong, missing, extra or swapped letter,
  in words of five letters or more (`statss`, `lab buttns`). The bot says
  `Read as: stats` when it has corrected something. Destructive words
  (`reset` and its aliases, `delete`) must be spelled exactly.
- **Anything else in #inbox goes to Claude.** Outside #inbox the bot only
  reacts to registered words, reply actions and reactions.
- **Words and reply actions tidy up after themselves.** When one works, the
  message you typed is deleted. If it had nothing lasting to show, you get a
  short confirmation ("📦 Archived: link") that deletes itself after 5
  seconds (`CONFIRMATION_SECONDS` in `.env`). Lasting output, such as the
  stats card or the help text, stays.
- **When one fails, your message stays and gets a ⚠️ reaction.** Nothing is
  said in the channel; the reason (including "Usage: …" for a wrong
  argument) is on a card in #bot-log.
- **Reactions wait 30 seconds** (`REACTION_DEBOUNCE` in `.env`). The bot
  then acts once, on where your reactions ended up: add one and remove it
  in time and nothing happens. Only your reactions count.
- **After a reaction is acted on** the message gets ✅, and taking your
  reaction away later undoes it and removes the ✅. Archive and delete are
  the exception: the message is gone, so they can only be cancelled within
  the 30 seconds. If a reaction fails, the message gets ⚠️ and the reason is
  in #bot-log.
- **Reactions made while the bot is off are not seen.**
- **"X pinned a message" notices are deleted** wherever they appear.
- **Claude knows the list too.** The same list `help` shows is added to its
  instructions, so "what can you do?" gets an accurate answer. Claude can't
  run them itself; it tells you what to type.

## How to add a skill

1. Create a folder `skills/<name>/` with an `__init__.py`. The folder name
   is the skill's name (lower case, no spaces).
2. In it, subclass `Skill`, set `name` (same as the folder) and
   `description`, and expose one instance called `skill`:

```python
from core.context import Context
from skills.base import Keyword, Skill


async def hello(ctx: Context) -> None:
    await ctx.reply(f"👋 Hello, {ctx.user.display_name}!")


class GreeterSkill(Skill):
    name = "greeter"
    description = "Says hello"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["hello", "hi there"],          # the word, then any aliases
                "say hello",                    # description: required
                hello,
                examples=["hello"],
            ),
        ]


skill = GreeterSkill()
```

3. Restart the bot. The terminal and the "🟢 Bot started" card in #bot-log
   list the skills that loaded, anything that was skipped and why, and any
   registration with no description. `help` picks up the new word
   automatically, and so does Claude.

**What a skill can register.** Each one must describe itself:

| Hook | Record | The user… |
|---|---|---|
| `keywords()` | `Keyword(words, description, handler)` | types the word on its own. `handler(ctx)` |
| `reply_actions()` | `ReplyAction(words, description, handler)` | replies to a message with the word. `handler(ctx, target)` |
| `reactions()` | `Reaction(emoji, description, handler)` | adds the emoji to a message. `handler(payload, user)` |

Fields they share:

- **`description`** (required) and **`examples`**: shown by `help` and given
  to Claude. A missing description is reported in #bot-log at startup.
- **`channels`**: where it works. `"inbox"` (the default for keywords),
  `"any"` (the default for reply actions and reactions), or a list of names
  from `.env`: inbox, bot-log, archive, reminders, gym, admin, documents.
- **`permission`**: the action name passed to `is_allowed`. Defaults to
  `keyword:<word>`, `reply:<word>` or `reaction:<emoji>`.

Keywords and reply actions also take:

- **`takes_args=True`** and **`usage="[days]"`**: accept extra words after
  the phrase; they arrive as `ctx.args`. Without it the message must be the
  phrase and nothing else.
- **`exact=True`**: no typo correction. Use it for anything destructive.
- **`accepts=`** (keywords): a function that looks at the arguments and can
  say "not mine", so the message goes to Claude instead. `help` uses it so
  that "help me write an email" isn't treated as a help request.
- **`keep_command=True`**: leave the user's message in place after the
  action works. By default the core deletes it.

Things to know:

- **The registry does the bookkeeping.** It logs the input, checks
  `is_allowed`, posts the #bot-log card and records the result. The handler
  only does the work. What it returns is recorded as the reply; return
  `None` to record what was sent.
- **How a handler ends is decided by the core**, the same for every word
  and reply action. On success the user's message is deleted (unless
  `keep_command`). If the result is something to keep, send it with
  `ctx.reply`. If there is nothing lasting to show, call
  `ctx.confirm("📦 Archived: <link>")`: it deletes itself after
  `CONFIRMATION_SECONDS`. A handler that shows nothing at all gets a plain
  "✅ Done: <word>" confirmation.
- **Raise `UserError("…")`** (`core/errors.py`) for problems the user can
  fix, such as bad arguments. Any failure leaves the user's message in
  place with a ⚠️ reaction; the message you raised goes on the #bot-log
  card, not in the channel.
- **Use the context**, not Discord: `ctx.reply(text)`,
  `ctx.reply_card(title, fields)`, `ctx.log(title, description)`,
  `ctx.user`, `ctx.args`, `ctx.channel_name`.
- **Database:** return migration functions from `migrations()`, in order,
  and only ever add to the end. Prefix table names with the skill's name
  (`greeter_...`) and give every record a `user_id`. Query with
  `await ctx.db.run(func)`, where `func(conn)` does the SQLite work; it runs
  in a worker thread so the bot is never blocked.
- **Reactions that can be undone:** give the `Reaction` an `undo` handler;
  the core runs it when the user takes the reaction away, and looks after
  the ✅ and ⚠️ markers and the record of what is applied
  (`core/reactions.py`). Set `destructive=True` when the message won't
  exist afterwards. Never post a note in the channel about a failure.
- **Before archiving, deleting or clearing a message**, check
  `core.protection.is_protected(message)` (pinned or 📌-marked) and, if so,
  ask with `core.confirmations.ask(channel, user, question, on_confirm)`.
  Call `ctx.shown(...)` so the core doesn't add a "Done" on top of the
  question.
- **Doing something later:** book a job with
  `await scheduler.add_job(self.name, "kind", due_at, payload, user_id)`
  (`core/scheduler.py`) and return `{"kind": handler}` from `job_handlers()`.
  The handler gets a `Job` (`payload`, `user_id`, `due_at`, `is_late`).
  Jobs are stored in `scheduled_jobs`, so they survive a restart; one that
  came due while the bot was off runs at the next start with `job.is_late`
  set, and the handler decides what to say about that. `cancel_job` and
  `reschedule_job` change a job that hasn't run. Keep the job's id with your
  own record and ignore a job that no longer matches it.
- **Replies that aren't fixed words:** give a `ReplyAction` a `pattern`
  (a regular expression; its groups become `ctx.args`), as `+10m` does.
- **Reply words that only sometimes apply:** give a `ReplyAction` an
  `applies_to` check. The timers skill uses it so that `cancel` replied to
  an ordinary message is not treated as a command.
- **Slash commands are a fallback.** Return `app_commands.Group` or context
  menu objects from `app_commands()`; they are synced to our server at
  startup. In the command's check, call `interactions.check_allowed` and
  `interactions.begin` (`core/interactions.py`); the core then logs how it
  ended. Have the typed word and the slash command call the same function
  (see `Run` in `skills/lab/common.py`).
- **Other Discord events:** return `{"raw_reaction_add": handler, ...}` from
  `events()`. `startup(client)` runs once when the bot is connected.
- **Knowing what just happened:** ask for the `action_finished` event to be
  told after every word, reply action, reaction and chat, with a
  `registry.ActionResult` (kind, name, status, user, channel).
- **Waiting for an answer:** `registry.expect_message(channel_id, user_id,
  handler, timeout)` hands that user's next message in that channel to
  `handler(ctx)`, once, and keeps it away from Claude. Words and reply
  actions are still tried first. It is forgotten at restart.
- **Buttons that must survive a restart:** give them a fixed `custom_id`, no
  timeout, and register the view with `client.add_view(...)` in
  `setup(client)`, which runs before the bot connects.
- **Answer every button, select and form within 3 seconds**, as the first
  thing the handler does; log to the database afterwards. Anything left
  unanswered after 2 seconds is logged, reported in #bot-log, and the user
  is told the button no longer works.
- **Don't pass `self.view` back from a `DynamicItem`.** It is discord.py's
  bare copy of the message, and its other buttons have no handlers. Build
  the full view again and send that (see `build_panel` in
  `skills/lab/buttons.py`).
- **`tools()`** exists on the base class but is not used yet.
- **Turning skills on and off:** `ENABLED_SKILLS=builtin,greeter` in `.env`.
  Leave it empty to load everything. A disabled skill keeps its data, and
  its words, slash commands and help entries disappear.
- A word, reply word or emoji can only belong to one skill; the second one
  to claim it is skipped and reported at startup.

## Archive and delete

`skills/archive/` moves messages out of the way. It only works for the
owner.

| Way in | What happens |
|---|---|
| Reply `archive` (or `box`, `file away`) | The message is copied to the archive channel under its author's name and avatar, with attachments, the original time and a link to where it was. Then the original and your reply are deleted, and "📦 Archived: link" shows for 5 seconds |
| Reply `delete` (or `remove`) | The message and your reply are deleted for good, and "🗑️ Deleted" shows for 5 seconds. Must be spelled exactly |
| React 📦 | Same as replying `archive`, after 30 seconds. Remove the 📦 in time to cancel |
| React 🗑️ | Same as replying `delete`, after 30 seconds. Remove the 🗑️ in time to cancel |
| Apps > **Archive message** | Same as replying `archive` (fallback) |
| **Restore** button on an archived copy | Reposts the message to the channel it came from (author's name and avatar, attachments, original time), then removes the archived copy |

- **Undoing.** A 📦 or 🗑️ can be taken back by removing the reaction within
  the 30 seconds. After that an archived message comes back with its
  **Restore** button, which keeps working after a restart. A deleted
  message is gone.
- **Pinned and 📌-marked messages are asked about first**, whichever way you
  go about it: "⚠️ That message is pinned. Archive it anyway?" with
  **Confirm** and **Cancel**. Anyone's 📌 counts. The question removes itself
  if you cancel or don't answer within two minutes, and stops working if
  the bot restarts while it is waiting.
- **Otherwise there is no "are you sure?".** The word or the reaction is
  the confirmation. Archive only deletes the original after the copy, with
  every attachment, has been posted.
- **When it fails** nothing is moved or deleted. A reply gets ⚠️ on your
  reply; a reaction gets ⚠️ on the message itself. The reason is in
  #bot-log, never in the channel.
- **Restore without Manage Webhooks** in the original channel still works:
  the bot posts the message itself, headed "**Name** wrote:".
- **Where the Restore button sits:** on the archived copy if Discord accepts
  a button on the webhook message; otherwise on a small bot message
  directly beneath it.
- **It refuses** messages already in the archive channel, messages in
  #bot-log, and (for archive) messages with nothing to copy or a file too
  big to re-upload.
- **It needs** `ARCHIVE_CHANNEL_ID` in `.env`, Manage Webhooks in the archive
  channel, and Manage Messages wherever the original is.

## Timers and Pomodoro

`skills/timers/` is for short timers and focus sessions. Everything is
typed (there are no slash commands), works in any channel, and survives a
restart. Date-based reminders are a separate, future skill.

| Type | What happens |
|---|---|
| `timer 25m`, `timer 1h30 laundry`, `timer 2 hours` | Starts a timer. The label is optional and defaults to "Timer" |
| `timers` (or `timer` on its own) | Lists your active timers and the current Pomodoro, in every channel |
| `pomo` | Starts a session: 25 minutes of focus, 5-minute breaks, a 15-minute break after 4 rounds |
| `pomo 50/10`, `pomo 50/10/30` | Custom focus/break lengths; the third number sets the long break (otherwise 15) |
| `pomo deep work`, `pomo 50/10 writing` | Anything else is the label |
| `pomo auto`, `pomo manual` | Whether phases start by themselves, for this session |
| `pomo stats` | Completed focus time today and this week |

**Durations** are read by code, not by Claude: `90s`, `25m`, `1h30`,
`1h 30m`, `1.5h`, `2 hours`, `45 min`, `1:30` (hours and minutes). A bare
number is minutes. From 5 seconds to 24 hours.

**A timer** posts one message with a live "ends in…" time. Reply to it with
`pause`, `resume`, `cancel` or `+10m` (also `+ 10 min`, `extend 10m`). When
it finishes, that message is edited to say so and you are @mentioned in a
new message with **+5 min**, **Restart** and **Dismiss**. Pressing any of
them, or replying `ok` (or `done`, `dismiss`) to the alert, clears the alert
away; the original message stays as the record.

**A Pomodoro session** is one card, edited in place, showing the phase,
round, label and a live time, with **Pause/Resume**, **Skip** and **Stop**.

- **At each phase end** you are @mentioned with **Start** and **Skip**, and
  the next phase's clock only starts when you press **Start**. `pomo auto`
  (or `POMO_AUTO_CONTINUE=true` in `.env`) starts phases by themselves.
- **Each alert is cleared once you respond to it:** Start, Skip, the **OK**
  button on auto-mode alerts, or a reply of `ok` / `done`. Replying `ok`
  only acknowledges; it doesn't start the phase.
- **Skip** moves straight on to the next phase. A skipped focus round is
  not counted in the stats; only ones that run to the end are.
- **One session at a time.** Stop the current one before starting another.
- **The same reply words work on the card:** `pause`, `resume`, `stop`,
  `+10m` (adds to the current phase).
- **After a long break** the rounds start again from 1.

**The board.** Each channel where a timer has been started has one pinned
"Active timers" message, rewritten on every change and reading "No active
timers" when empty. Discord's "pinned a message" notice is deleted. The
board carries a 📌 reaction, which marks it as exempt from the (future)
nightly sweep.

**Restarts and downtime.** Timers, sessions and their due moments are in
the database, and the buttons are found again by their ids. If something
finished while the bot was off, you are told at the next start that it
finished late. After downtime a session always waits for **Start**, even
in auto mode.

**Things to know:**

- **Times use Discord's live timestamps**, so messages are only edited when
  something changes, not every second.
- **Nothing visible happens for `cancel`, `pause` and the like replied to a
  message that isn't a timer:** those words are only commands on timer
  messages, so elsewhere they are ordinary chat.
- **The bot needs Pin Messages** (or Manage Messages) to pin the board and
  to remove the pin notice. Without it the board still works, unpinned,
  and #bot-log says so.
- **`10 min walk`** is read as ten minutes labelled "walk", because "min"
  is a unit.
- **For a quick try-out** use seconds: `timer 10s tea`, `pomo 30s/10s`.

## Lab commands

`skills/lab/` is a test bench for Discord features. Type `lab …` in any
channel, or use `/lab …` as a fallback: both run the same code. It only
works for the owner, and every use is logged to `message_log` and #bot-log.
To switch it off, leave `lab` out of `ENABLED_SKILLS`.

| Type | What it shows |
|---|---|
| `lab react` | Posts a message with 🔴 🟢 🔵 🟡 (plain colours, so they never trigger a real action). React on it; after 15 quiet seconds it shows the final state and a timeline, then adds ✅ |
| `lab buttons` | A counter, toggles, single and multi selects, a modal form, an ephemeral reply and a link button; plus persistent buttons that still work after a restart |
| `lab pin [start\|stop]` | Pins a status message that updates every minute (and resumes after a restart); `stop` unpins it. Pin changes anywhere are logged to #bot-log |
| `lab chart [quickchart\|matplotlib] [days]` | Messages per day and cost per day as two charts, drawn by QuickChart (a web service) or matplotlib (on the server) |
| `lab notify <normal\|silent\|mention\|dm\|all> [delay <seconds>]` | A normal, silent, @mention or direct message (the DM is a short pointer with a link back to a marker message in the channel, as real DMs will be). `all` sends the four in that order, 5 seconds apart. `delay 90` waits first (up to an hour), so you can lock your phone: `lab notify all delay 90` |
| `lab time` | Every dynamic timestamp style |
| `lab thread` | A message with a thread started on it |
| `lab poll [multiple]` | A native poll that runs for an hour |
| `lab file [days]` | Daily stats from `message_log` as a CSV file |
| `lab format` | Markdown, spoilers, ANSI colours, long message splitting |
| `lab layout` | Components v2 (containers, sections, thumbnails) |
| `lab countdown [seconds] [step]` | A self-editing message; reports rate limits |
| `lab tour [new\|stop]` | A guided run through the interactive tests on one card. Typed only; see below |
| `lab channels [delay <seconds>]` | Test messages across four channels, timing your reply in each. Typed only; see below |

Arguments in square brackets are optional; a wrong one gets a ⚠️ on your
message and the usage line in #bot-log. The slash versions take the same
options by name (`/lab chart renderer: days:`) and add a private "done"
note; the typed versions show the same note for 5 seconds.

A delayed `lab notify` is answered straight away and sent in the
background. It is held in memory only, so restarting the bot before it
fires cancels it. What was sent is logged when it finishes.

### `lab tour`: the guided test run

Type `lab tour` (best in #inbox, since two steps need it). One card appears
and is edited in place as you go, with **Pass**, **Fail**, **Skip**,
**Back** and **Stop** buttons.

| Step | What you do | Passes by itself when… |
|---|---|---|
| 1. Plain-word shortcut | Type `ping` or `stats` in #inbox | a plain word runs |
| 2. Buttons | `lab buttons`, then press Count, flip a toggle, use a select, submit the Form | all four have been used |
| 3. Reactions and debounce | `lab react`, react, wait 15 seconds | the quiet period ends and the summary is posted |
| 4. Reply "archive" | Reply `archive` to a message | the archive worked and your reply was cleaned up |
| 5. 📦 reaction | React 📦 to a message | it is archived after the 30-second wait |
| 6. Pinned dashboard | `lab pin`, watch a minute tick, `lab pin stop` | never: it ticks the boxes, you press **Pass** |
| 7. Chart | `lab chart` | never: you judge whether it reads well |
| 8. Claude chat and reset | Message Claude in #inbox, then `reset` | Claude answered and then memory was cleared |

- **Steps tick themselves** as the bot notices each thing happen. Steps
  that are a matter of judgement (6 and 7) tick their boxes but wait for
  your verdict. **Back** reopens the previous step if you disagree with an
  automatic pass.
- **Fail** opens a small form for a short note; the note appears on the
  card and in the results.
- **The card gets buried** as you type test messages. Type `lab tour` again
  to bring it back down to the bottom.
- **It is resumable.** The run is saved after every change, so after a
  restart the buttons still work and `lab tour` carries on at the same
  step. `lab tour new` abandons the current run and starts again;
  `lab tour stop` ends it early.
- **Results** are saved in `lab_tour_runs` and `lab_tour_results`, the card
  turns into a summary, and the same summary is posted to #bot-log.

### `lab channels`: notifications across channels

`lab channels delay 60` waits a minute (lock your phone), then posts one
test message in each of four channels, 5 seconds apart, each asking you to
reply there:

| Channel | Style |
|---|---|
| #reminders | normal |
| #gym | @mention |
| #admin | silent |
| #inbox | cross-channel link: a link to the #reminders test, to tap and come back from |

- **Reply with anything in each channel.** Your next message there is the
  reply being timed: it gets a ✅ and is not passed on to Claude. Words such
  as `help` still work and don't count as the reply.
- **Results:** when you have replied everywhere, or 10 minutes after the
  last message, a card is posted where you typed the command (and logged to
  #bot-log) with each channel's response time, or "no reply".
- **Claude history check:** the card also reports whether Claude's
  conversation history is kept separately per channel. It is checked on the
  real history store. Claude only chats in #inbox today, so the other
  channels' histories are empty.
- **A channel that isn't set in `.env`** or that the bot can't see is
  reported on the card; the others still run.
- **One test at a time, and it is held in memory:** restarting the bot
  cancels a test in progress.

Slash commands are synced to the server the inbox channel is in, every time
the bot starts. The "🟢 Bot started" card shows how many were synced.

**Permissions the bot's role needs** (a missing one gives a message, not a
crash): Send Messages, Embed Links, Attach Files, Read Message History,
Add Reactions, Create Public Threads, Send Messages in Threads, Create
Polls, Manage Messages, Pin Messages, Manage Webhooks.

**Troubleshooting:**

- **Your message got a ⚠️:** it was understood but failed. The reason is on
  the latest "Command failed" card in #bot-log.
- **A word does nothing:** check `help` in that channel. Plain words such as
  `stats` only work in #inbox; the message must be the word and nothing
  else; and only the owner is listened to.
- **A word went to Claude instead:** it wasn't an exact match or a
  one-letter typo of a word with five or more letters.
- **`/lab` doesn't appear:** check the "Slash commands" line on the start
  card. If the sync failed with "Missing Access", re-invite the bot with the
  `applications.commands` scope. Restarting Discord refreshes its list.
- **"The lab isn't for you":** your Discord ID isn't `OWNER_ID`.
- **`lab countdown 30 1`** is the easy way to see rate limiting: watch for
  "🚦 Rate limited" cards and the slow-edit count in the summary.
- **QuickChart fails:** it is a third-party web service
  (`quickchart.io`). It is sent dates, daily counts and daily cost only,
  never message text. Use `lab chart matplotlib` if it is down.
- **`lab react` message never updates:** it only watches messages posted
  since the bot last started, and only counts the owner's reactions.
- **The interactive `lab buttons` message stops working:** it expired
  (15 minutes) or the bot restarted. Only the second, persistent message is
  meant to survive. You get "⌛ That button or form no longer works" and an
  "Interaction not answered" card in #bot-log.

## Day-to-day workflow

1. Stop the service (Terminal as Admin): `nssm stop assistant-bot`
2. Make changes and test: `python main.py`
3. Stop the test run: `Ctrl + C`
4. Review: `git status` then `git diff`
5. Commit and push:
```powershell
   git add .
   git commit -m "Describe the change"
   git push
```
6. Start the service: `nssm start assistant-bot`

**Never run the service and a test copy at the same time**, or every
message gets two replies. The bot now refuses: a second copy logs "Another
copy of the bot is already running (PID …)" and exits with code 3. The lock
is `data/bot.lock`; it frees itself when the bot stops, even after a crash,
so the file never needs deleting.

Run this once (Terminal as Admin), so the service stops instead of retrying
every few seconds when a test copy is already running:

```powershell
nssm set assistant-bot AppExit 3 Exit
```

To see what is running:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine
```

One bot shows as **two** `python.exe` lines with the same start time: the
`.venv` launcher and the real Python it starts. That is one copy, not two.

## Tests

```powershell
python -m unittest
```

The tests in `tests/` cover the pure logic: duration parsing, Pomodoro
phase order and pause arithmetic, the word router, and the scheduler
(including catch-up and the nightly backup). They never start the bot or
talk to Discord or Claude, they use made-up settings instead of `.env`, and
anything that needs a database gets a temporary one, so they are safe to
run while the bot is running.

## Service commands (Terminal as Admin)

```powershell
nssm status assistant-bot
nssm start assistant-bot
nssm stop assistant-bot
nssm restart assistant-bot
nssm edit assistant-bot
```

## Dependencies

After installing a package, update the list:
```powershell
pip freeze > requirements.txt
```

## Troubleshooting

- **`ModuleNotFoundError`:** wrong Python. Check the prompt shows `(.venv)`,
  or run `python -c "import sys; print(sys.executable)"`
- **Scripts disabled when activating:**
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- **Double replies:** the service and a test copy are both running (only
  possible if one of them is older code from before the instance lock)
- **"Another copy of the bot is already running":** stop the other one first
  (`Ctrl + C` in its terminal, or `nssm stop assistant-bot`)
- **Errors 10062 "Unknown interaction" or 40060 "already been
  acknowledged":** two copies answered the same button or command, or the
  bot took over 3 seconds to answer. They are logged as warnings
- **Service won't start:**
  `Get-Content logs\service-err.log -Tail 30`
- **Stuck in a Git viewer (`less`):** press `q`; `Esc` cancels prompts