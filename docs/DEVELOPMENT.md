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
  - `llm.py`: Claude client, system prompt, history, cost estimates
  - `discord_utils.py`: #bot-log embeds and message helpers
- `skills/`: one folder per feature
  - `base.py`: the `Skill` base class
  - `registry.py`: finds, loads and dispatches to skills
  - `builtin/`: ping, reset, buttons, stats, help

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
- **`tools()` and `reactions()`** exist on the base class but are not used
  yet.
- **Turning skills on and off:** `ENABLED_SKILLS=builtin,greeter` in `.env`.
  Leave it empty to load everything. A disabled skill keeps its data.
- A command name can only belong to one skill; the second one to claim it
  is skipped and reported at startup.

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
message gets two replies.

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
- **Double replies:** the service and a test copy are both running
- **Service won't start:**
  `Get-Content logs\service-err.log -Tail 30`
- **Stuck in a Git viewer (`less`):** press `q`; `Esc` cancels prompts