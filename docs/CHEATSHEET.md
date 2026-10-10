# Command cheat sheet

Quick reference for running, managing and developing the assistant bot.

---

## Where to type what

| You want to... | Type it in |
|---|---|
| Run commands (`git`, `python`, `pip`) | **PowerShell** (normal terminal) |
| Manage the service (`nssm`) | **Terminal (Admin)** |
| Ask for code changes in plain English | **Claude Code** |

**How to tell them apart**

- **PowerShell:** a line starting with `PS C:\...>`
- **Claude Code:** its own interface with an input box
- **Admin:** the window title says **Administrator**

---

## Opening terminals

| Action | How |
|---|---|
| Normal terminal | Right-click Start → **Terminal** |
| Admin terminal | Right-click Start → **Terminal (Admin)** → Yes |
| Terminal in VS Code | **Ctrl + Shift + `** (or Terminal → New Terminal) |
| New tab in Windows Terminal | **Ctrl + Shift + T** |

---

## Getting around

```powershell
cd $env:USERPROFILE\projects\assistant-bot   # go to the project
pwd                                          # where am I?
Get-ChildItem                                # list files (or: ls)
cd ..                                        # up one folder
```

- **Tab** completes file and folder names
- **Up arrow** repeats previous commands
- **Ctrl + C** cancels whatever is running

---

## Virtual environment

```powershell
.\.venv\Scripts\Activate.ps1                     # turn it on
python -c "import sys; print(sys.executable)"    # check: path should include .venv
deactivate                                       # turn it off
```

- Prompt starting with **(.venv)** means it's active
- VS Code activates it automatically in new terminals

**Packages**

```powershell
python -m pip install <package>          # install one
python -m pip install -r requirements.txt  # install everything listed
pip freeze > requirements.txt            # save the current list
```

---

## Running the bot (testing)

```powershell
nssm stop assistant-bot    # (Admin) stop the service first!
python main.py             # run a test copy
```

- **Ctrl + C** stops the test copy
- **Never run the service and a test copy at once** (double replies, errors)

---

## The service (always-on bot)

All need **Terminal (Admin)**.

```powershell
nssm status assistant-bot     # running?
nssm start assistant-bot      # start
nssm stop assistant-bot       # stop
nssm restart assistant-bot    # restart (after code or .env changes)
nssm edit assistant-bot       # change settings in a window
```

**Keep it off, even after reboots**

```powershell
nssm stop assistant-bot
nssm set assistant-bot Start SERVICE_DEMAND_START
```

**Turn auto-start back on**

```powershell
nssm set assistant-bot Start SERVICE_AUTO_START
nssm start assistant-bot
```

**When to restart:** code changes, `.env` changes, new packages.
**No restart needed:** docs, README, `.gitignore`.

---

## Checking for duplicate bot copies

```powershell
python -m core.instance_lock      # how many bots are running (doesn't start one)
```

- Says "1 bot is running: PID …" or "No bot is running", service included
- It asks the lock (`data/bot.lock`), which only one bot can hold, so it
  is right even when the process list looks like two
- In Discord: `dev status` says the same

**Checking by hand**

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Select-Object ProcessId, ParentProcessId, CommandLine
Stop-Process -Id <ProcessId>      # stop a specific one
```

- **One bot is two lines.** Started from `.venv`, `python.exe main.py`
  shows twice: the launcher, and the real Python it starts
- **Use ParentProcessId to tell:** if one line's ParentProcessId is the
  other line's ProcessId, they are the same bot. The child is the real one
  (its PID is the one in `data\bot.lock`)
- **Two bots** would be two lines whose ParentProcessId is *not* another
  `main.py` line. The lock stops that: the second copy exits by itself
- **Nothing listed:** no bot is running (service included)

---

## Tests

```powershell
pip install -r requirements-dev.txt   # once: adds pytest
python -m pytest                      # run all the unit tests
python -m pytest -k archive           # only tests with "archive" in the name
```

- Safe while the bot is running: no Discord, no real database, no `.env`
- Run before every commit
- `docs/TESTING.md` tracks them (🤖 Auto) and the by-hand tests (👤 Manual)

---

## Logs

```powershell
Get-Content logs\bot.log -Tail 30            # last 30 lines
Get-Content logs\bot.log -Tail 30 -Wait      # follow live (Ctrl + C to stop)
Get-Content logs\service-err.log -Tail 30    # service errors
```

---

## Git: the daily loop

```powershell
git status                      # what's changed?
git diff                        # line-by-line changes
git add .                       # stage everything (respects .gitignore)
git status                      # check: no .env, data/, logs/
git commit -m "Describe change" # save a snapshot locally
git push                        # upload to GitHub
```

**add** = pack the box → **commit** = seal and label it → **push** = ship it

**Writing commit messages:** short, present tense, what and why.
`"Add Pomodoro timer"`, not `"added stuff"`

---

## Git: looking around

```powershell
git log --oneline          # recent commits
git show --stat            # files in the last commit
git diff --staged          # what's about to be committed
git ls-files               # every file Git tracks
git branch                 # list branches (* = current)
git remote -v              # where pushes go
```

**Stuck in a viewer?** Press **q**. **Esc** cancels prompts inside it.

---

## Git: branches

```powershell
git switch -c my-feature          # create a branch and move to it
git push -u origin my-feature     # first push of a new branch
git switch main                   # go back to main
git merge my-feature              # bring a branch into main (run while on main)
git push                          # upload the merged main
git branch -d my-feature          # delete a merged branch
```

---

## Git: syncing between machines

```powershell
git pull     # download commits made elsewhere (do this before starting work)
```

---

## Git: undoing things

```powershell
git restore <file>             # discard changes to a file (careful!)
git restore .                  # discard ALL uncommitted changes (careful!)
git restore --staged <file>    # unstage, keeping your changes
git revert <commit-id>         # safely undo a commit with a new commit
```

---

## Dev mode (typed in Discord)

For testing: shorter waits, debug cards in #bot-log, and a few tools. Owner
only, any channel, no slash. It is off after every restart.

| Type | What it does |
|---|---|
| `dev on` | On, with the dev defaults: debounce 2s, speed 1x, verbose on, quiet hours ignored, off again after 1 hour |
| `dev off` | Off: normal settings back, panel removed |
| `dev mode on` / `dev mode off` | The same, typed or asked of Claude |
| `dev` | Show the panel again at the bottom of the channel |
| `dev reset` | Dev settings back to the dev defaults |
| `dev debounce 0` | Seconds before reactions are acted on (0 = at once) |
| `dev speed 60` | Timers and Pomodoro run 60 times faster (`timer 5m` takes 5s) |
| `dev verbose on` / `off` | Debug cards in #bot-log |
| `dev quiet on` / `off` | Quiet hours apply / are ignored |
| `dev cleanup off` / `on` | Stop / resume all automatic deletion (commands, confirmations, alerts) |
| `dev expire 30m` | Switch itself off after this long |
| reply `dev inspect` | What the bot knows about that message, including its lifecycle class |
| `dev status` | How many bots are running: the one holding the lock, and any stray (the `.venv` launcher isn't counted) |
| `dev jobs` | Pending scheduler jobs |
| `dev run backup` | Run a maintenance routine now (`sweep` and `summary` aren't built yet) |
| `dev fire next` | Run the next pending job now |
| `dev seed 5` | Post 5 sample messages, tagged as test data |
| `dev clean` | Delete the test data and dev tool output in this channel |
| `dev clock` | Show the bot's clock |
| `dev clock 5:59am` | **Dev database only.** Move the clock ahead to the next 5:59 am; everything due on the way runs in order |
| `dev clock +2h` | **Dev database only.** Move it ahead by a duration |
| `dev clock reset` | Back to the real time (the only way back) |
| `dev cost` | What the messages cost: today, this month, the average per message, the most expensive task |
| `dev why`, `dev why 3` | Why the bot did what it did with my last message (or last n, up to 10): a copyable block each |
| `dev reset-db` | **Dev database only.** Wipe `dev.db` after asking; the clock goes back too |

- **Dev database:** stop the service, then `python main.py --dev`. Same
  bot and channels, but `data/dev.db`; the status, the hello and the panel
  say **DEV DATABASE**. The clock stays where you put it through `dev off`
  and restarts
- Any setting word switches dev mode on first if it is off
- The pinned panel has **+1 hour**, **Reset** and **Disable** buttons
- The bot's status shows **🛠️ Dev mode** while it is on

---

## Pills (typed in Discord, #inbox or the hub)

| Type or say | What it does |
|---|---|
| `pills` (or "my pills") | The list of every pill: read-only, and kept up to date in place |
| "add vitamin D, once a day" | A card with **Save** / **Cancel** straight away; nothing is added until Save |
| "add evening pill at 20:00" | A pill at a fixed time (shown as `8:00 pm`) |
| "add course A, 3 times a day, at least 3 hours apart, with food, for 7 days starting tomorrow" | A course with a minimum gap and dates |
| "add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm, without food" | Planned times, a minimum gap and a latest time together |
| "move the evening pill to 9pm" | A card: schedule · old → new, to save |
| "pause iron until the 20th" / "resume iron" | A card to save; the 20th is the day it is taken again |
| "remove iron" | Asks first; its history is kept |
| "delete iron and its history" | A separate question; can't be undone |

- "At 8" is taken as 8:00 am and marked ❓; say "8pm" to correct the card
- A card nobody saves disappears after 30 minutes
- There is never an "ok" step: the card's **Save** is the one confirmation
- Everything works in #inbox and in the hub

## Seeing what the bot did (`.env`)

| Setting | What it does |
|---|---|
| `KEEP_CONFIRMATIONS=true` (the default) | Confirmations ("📦 Archived"), "Read as: …" notes and ⚠️ reasons stay in the channel instead of deleting themselves |
| `KEEP_CONFIRMATIONS=false` | They delete themselves after `CONFIRMATION_SECONDS`, as before |

- Your command words are deleted either way; only the bot's notes stay
- Restart the bot after changing it
- `dev cleanup off` is the stronger, temporary switch: nothing at all is
  deleted until dev mode ends

---

## Bugs (typed in Discord)

| Do | What happens |
|---|---|
| React 🐞 to a message | Logged at once: "🐞 Logged as B4" with a link to its post in #bugs. Removing the 🐞 does nothing |
| Reply `bug` to a message | The same, for that message |
| Type `bug` on its own | The same, for the latest thing in that channel |
| Write in the bug's post | Saved as a note, ticked ✅. The bot doesn't answer |
| Press **Fixed** / **Won't fix** on the post | Tags it and archives the post; the card shows the status and time, and a **Re-open** button |
| Press **Re-open** | Unarchives the post, tag back to Open, the two buttons back |
| `bugs` | The open bugs, with links |
| `bugs export` | Writes them in full to `docs/BUGS.md` (not in git) |

- `bug: some text` is not a command; notes go in the post
- Needs `BUGS_CHANNEL_ID` in `.env`: a **forum** channel where the bot may
  Create Posts, Send Messages in Threads and Manage Threads (and Manage
  Channels, once, to make the tags Open, Fixed and Won't fix)
- In Claude Code: `fix B4` (or `/bug B4`) reads the bug, writes a failing
  test, fixes it and notes "fix ready, needs retest". You still press Fixed
- By hand: `python -m tasks.bugs.cli list` and `python -m tasks.bugs.cli show B4`

---

## Claude Code

**Starting**

```powershell
cd $env:USERPROFILE\projects\assistant-bot
claude               # new session
claude --continue    # resume the last conversation
claude --resume      # pick a past conversation from a list
claude --version     # check it's installed
```

**Inside Claude Code**

| Action | How |
|---|---|
| Plan mode (no edits until approved) | **Shift + Tab** until it shows plan mode |
| Run a shell command | Start the line with `!` (e.g. `!git status`) |
| Clear the conversation (fresh start) | `/clear` |
| Interrupt it | **Esc** |
| Exit | `/exit` (or **Ctrl + C** twice) |
| See commands | `/help` |

**Good habits**

- Stop the service before asking for changes that need testing
- Plan mode for anything multi-file
- One stage at a time, commit after each
- `/clear` between unrelated pieces of work
- It reads `CLAUDE.md` automatically

**If you get `529 Overloaded`:** wait a minute, then type `continue`.

---

## Remote access

```powershell
ssh <user>@hive          # terminal on the server
mstsc                    # Remote Desktop (enter: hive)
```

- Both work from anywhere with **Tailscale** connected
- SSH sessions for admin accounts usually have admin rights; if `nssm` says access denied, use Remote Desktop → Terminal (Admin)

---

## Quick troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Wrong Python: activate `.venv`, or check `sys.executable` |
| Scripts disabled when activating | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `'claude' is not recognized` | Add `%USERPROFILE%\.local\bin` to PATH, open a new terminal |
| Double replies / "Unknown interaction" | Two bot copies running: check processes, stop extras |
| Service won't start | `Get-Content logs\service-err.log -Tail 30` |
| `git add` can't find a file | Check its location with `Get-ChildItem`; it may be in a subfolder |
| LF/CRLF warnings | Harmless; add `.gitattributes` with `* text=auto eol=lf` to silence |
| Slash commands missing in Discord | Restart the Discord app |

---

## Typical workflow, start to finish

1. `nssm stop assistant-bot` (Admin)
2. `git pull` (if you've worked elsewhere)
3. Ask Claude Code for the change (plan mode)
4. `python -m pytest`, then `python main.py` to test by hand, **Ctrl + C** when done
5. `git status` → `git add .` → `git commit -m "..."` → `git push`
6. `nssm start assistant-bot` (Admin)
