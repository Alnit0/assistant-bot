---
name: catchup
description: Catch up at the start of a session or after a reboot - where the work stands, git, whether the PC restarted, live, and new bugs - then report in four short parts and wait. Read only. Use when Alex types /catchup.
---

# Catch up

Read only: no edits, restarts, commits, pushes, bug closing, self-tests,
test runs or requests to Claude. Alex reads the answer on his phone, so
keep it short. Never print a token or an ntfy topic, a bot's display name
or a real pill name. Use the `.venv` Python. In this order:

1. **Where we were**: `docs/NOW.md` first (the batch, its steps done,
   in progress and next, drafts and worktrees). Open `docs/STATUS.md` only
   if NOW.md points there.
2. **Git**: `git status -sb` (branch, uncommitted, ahead of the remote),
   `git worktree list` (each worktree's branch, and `git -C <path>
   status -s` for uncommitted work there).
3. **Reboot or cut off**: `(Get-CimInstance Win32_OperatingSystem).LastBootUpTime`.
   A boot after the last commit, or uncommitted work with no session
   running, means a batch was cut off: say what it had done (the diff's
   file names) and what it had not.
4. **Live** (it runs from its own folder, `C:\Users\temp\projects\assistant-bot-live`,
   on one pushed commit: everything below is read there, not here):
   - `Get-Service assistant-bot` (running or not), and `python -m
     core.instance_lock` run in live's folder (which bots, since when)
   - the commit live runs: `git -C ..\assistant-bot-live rev-parse --short
     HEAD`, and the last line of its `data\live-versions.txt`; say how
     far behind `origin/feature/pills` it is
   - the account check: the last "Account checked" line in live's
     `logs/bot.log` (passed or not; say "live's own account", never its
     name)
   - the switches: `Select-String ..\assistant-bot-live\.env -Pattern '^[A-Z_]*(ENABLED|CARDS_V2|DESIGN_ROUND|DAY_[A-Z]*|TODAY_CARD)='`
     (names and values only, nothing else from `.env`: never a link or a token)
   - today's 6 am briefing: the run log, read only, e.g. `sqlite3` on
     live's `file:data/assistant.db?mode=ro`, table `scheduled_jobs`,
     `skill = 'briefing' AND kind = 'post'`, today's `local_at`, its
     status and note
5. **Bugs**: `python -m tasks.bugs.cli list` (live) and the same with
   `--dev` (the self-test's). Anything opened or re-opened since the last
   session, one line each in plain words.
6. **Report**, in this shape and nothing more:

   **Where we were**: one or two lines
   **Live**: one line (up or down, its account check, the look it is in,
   whether the briefing posted)
   **Needs attention**: only if something does, a line each
   **Recommend**: one option, and whether it would commit, push, restart
   live or run a self-test

7. **Stop and wait** for Alex's go-ahead. Do nothing else.
