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
  - `config.py`: paths, settings from `.env`, validation, constants
  - `logging_setup.py`: terminal and rotating file logging
  - `database.py`: connections and the async database helpers
  - `migrations.py`: schema migrations, applied at startup
  - `users.py`, `permissions.py`: users and the `is_allowed` check
  - `context.py`: the `Context` object handed to skills
  - `backup.py`, `scheduler.py`: nightly backup and daily jobs
  - `debounce.py`: waits for a quiet period, then handles events together
  - `instance_lock.py`: makes sure only one copy of the bot runs
  - `llm.py`: Claude client, system prompt, history, cost estimates
  - `discord_utils.py`: #bot-log embeds and message helpers
- `skills/`: one folder per feature
  - `base.py`: the `Skill` base class
  - `registry.py`: finds, loads and dispatches to skills
  - `builtin/`: ping, reset, buttons, stats, help
  - `lab/`: `/lab` slash commands for trying out Discord features

Always run `main.py` (not the files in `core/` or `skills/`). Paths are
worked out from the project root, so it runs correctly from any working
directory.

## How to add a skill

1. Create a folder `skills/<name>/` with an `__init__.py`. The folder name
   is the skill's name (lower case, no spaces).
2. In it, subclass `Skill`, set `name` (same as the folder) and
   `description`, and expose one instance called `skill`:

```python
from core.context import Context
from skills.base import Command, Skill


async def hello(ctx: Context) -> None:
    await ctx.reply(f"👋 Hello, {ctx.user.display_name}!")


class GreeterSkill(Skill):
    name = "greeter"
    description = "Says hello"

    def commands(self) -> list[Command]:
        return [Command("hello", "say hello", hello)]


skill = GreeterSkill()
```

3. Restart the bot. The terminal and the "🟢 Bot started" card in #bot-log
   list the skills that loaded, and anything that was skipped and why.
   `help` picks up the new command automatically.

Things to know:

- **Commands** match the whole message (`hello`, not `hello there`). The
  registry logs the input, checks `is_allowed` and posts the #bot-log card;
  the handler only does the work.
- **Use the context**, not Discord: `ctx.reply(text)`,
  `ctx.reply_card(title, fields)`, `ctx.log(title, description)`, `ctx.user`.
- **Database:** return migration functions from `migrations()`, in order,
  and only ever add to the end. Prefix table names with the skill's name
  (`greeter_...`) and give every record a `user_id`. Query with
  `await ctx.db.run(func)`, where `func(conn)` does the SQLite work; it runs
  in a worker thread so the bot is never blocked.
- **Scheduled jobs:** return `DailyJob(name, at, func)` items from `jobs()`.
- **Reactions:** return `Reaction(emoji, handler)` items from `reactions()`.
  The handler runs when an allowed user adds that emoji to any message.
- **Slash commands:** return `app_commands.Group` or context menu objects
  from `app_commands()`. They are synced to our server at startup.
- **Other Discord events:** return `{"raw_reaction_add": handler, ...}` from
  `events()`. `startup(client)` runs once when the bot is connected.
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
  Leave it empty to load everything. A disabled skill keeps its data.
- A command name can only belong to one skill; the second one to claim it
  is skipped and reported at startup.

## Lab commands

`skills/lab/` is a test bench for Discord features. Everything is under the
`/lab` slash command, only works for the owner, and is logged to
`message_log` (kind `lab`) and #bot-log. To switch it off, leave `lab` out
of `ENABLED_SKILLS`; the slash commands disappear at the next start.

| Command | What it shows |
|---|---|
| `/lab react` | Posts a message with 📌 ⭐ 🔁 🗑️. React on it; after 15 quiet seconds it shows the final state and a timeline, then adds ✅ |
| `/lab buttons` | A counter, toggles, single and multi selects, a modal form, an ephemeral reply and a link button; plus persistent buttons that still work after a restart |
| `/lab pin [action:]` | `start` pins a status message that updates every minute (and resumes after a restart); `stop` unpins it. Pin changes anywhere are logged to #bot-log |
| `/lab chart [renderer:] [days:]` | Messages per day and cost per day as two charts, drawn by QuickChart (a web service) or matplotlib (on the server) |
| Archive | Right-click a message > Apps > **Archive message**, or react with 📦. Copies it to the archive channel under the author's name and avatar, with attachments, the original time and a link to where it was, then deletes the original |
| `/lab notify mode:` | A normal, silent, @mention or direct message |
| `/lab time` | Every dynamic timestamp style |
| `/lab thread` | A message with a thread started on it |
| `/lab poll [multiple:]` | A native poll that runs for an hour |
| `/lab file [days:]` | Daily stats from `message_log` as a CSV file |
| `/lab format` | Markdown, spoilers, ANSI colours, long message splitting |
| `/lab layout` | Components v2 (containers, sections, thumbnails) |
| `/lab countdown [seconds:] [step:]` | A self-editing message; reports rate limits |

Slash commands are synced to the server the inbox channel is in, every time
the bot starts. The "🟢 Bot started" card shows how many were synced.

**Permissions the bot's role needs** (a missing one gives a message, not a
crash): Send Messages, Embed Links, Attach Files, Read Message History,
Add Reactions, Create Public Threads, Send Messages in Threads, Create
Polls, Manage Messages, Pin Messages, Manage Webhooks.

**Troubleshooting:**

- **`/lab` doesn't appear:** check the "Slash commands" line on the start
  card. If the sync failed with "Missing Access", re-invite the bot with the
  `applications.commands` scope. Restarting Discord refreshes its list.
- **"The lab isn't for you":** your Discord ID isn't `OWNER_ID`.
- **`/lab countdown step:1`** is the easy way to see rate limiting: watch
  for "🚦 Rate limited" cards and the slow-edit count in the summary.
- **Archive does nothing or complains:** `ARCHIVE_CHANNEL_ID` must be set in
  `.env`, and the bot needs Manage Webhooks in the archive channel and
  Manage Messages where the original is. The original is only deleted after
  the copy has been posted; if anything fails it stays where it is. A failed
  📦 leaves a note in the channel for 20 seconds.
- **Archiving has no "are you sure?":** choosing the menu item or adding 📦
  is the confirmation. Only the owner's 📦 counts.
- **QuickChart fails:** it is a third-party web service
  (`quickchart.io`). It is sent dates, daily counts and daily cost only,
  never message text. Use `renderer: matplotlib` if it is down.
- **`/lab react` message never updates:** it only watches messages posted
  since the bot last started, and only counts the owner's reactions.
- **The interactive `/lab buttons` message stops working:** it expired
  (15 minutes) or the bot restarted. Only the second, persistent message is
  meant to survive. You now get "⌛ That button or form no longer works"
  and an "Interaction not answered" card in #bot-log, rather than Discord's
  silent "interaction failed".

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