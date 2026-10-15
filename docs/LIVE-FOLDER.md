# Live in its own folder, on a committed version

**Status: live runs from its own folder since 15 Oct, 3:11 pm**, on
`6a942d8`. The originals in the work folder (`.env`, `.env.dev`,
`data\`) are kept as a backup until Alex confirms all is well.

How it went: the setup script stopped live and then stopped at the
clone, because its output was redirected and Windows PowerShell treats a
program's progress on stderr as an error then (live was started again
from the work folder at once, about a minute down; both scripts now
take stderr as output). The switch-over was then done in two halves, so
live was down for well under a minute: the clone, the commit, the
`.venv` and the packages while live ran; then, stopped, `.env`,
`.env.dev` and `data\` copied (the database the same size both sides),
the migration check (25 of 25), the service's settings written to
`service-before.txt` and pointed at the new folder, and started. Then
the account check, today's logs and doses, the calendar read, and the
bookings (3:30 am self-test, 6 am routine, Sunday 7 pm summary) were
all there, and the self-test from live's folder passed 28 of 28.

Since then: `update-live.ps1` takes live's folder as its default
`-Target`, refuses a commit that is not on `origin/feature/pills`, and
puts back `docs\SELFTEST.md` (the nightly self-test rewrites it in live's
folder) before it checks nothing was changed by hand.

## Why

Live runs from the folder the work is done in
(`C:\Users\temp\projects\assistant-bot`), so a restart loads whatever is on
disk there. On 15 October Windows Update restarted the PC twice overnight
and live came back on a batch's uncommitted, unreviewed changes; the 3 am
self-test ran on them too. In a folder of its own, on one commit, a reboot
only ever brings back the version that was chosen.

## The two folders

| Folder | What runs from it | Moves when |
|---|---|---|
| `C:\Users\temp\projects\assistant-bot-live` | live (the NSSM service `assistant-bot`), and the nightly self-test it starts | Alex says so: `scripts\update-live.ps1` puts it on a commit |
| `C:\Users\temp\projects\assistant-bot` | Claude Code's work, the tests, the dev bot when a self-test is run by hand | every edit |

Live's folder is a clone of the repository, checked out **detached** on one
commit (never a branch, which would move with a `git pull`). Nothing in it
is ever edited by hand: the update script refuses to run if anything is.

## What lives where

- **`.env`** (live's settings and secrets): copied once into live's folder
  by the setup script; from then on live's own copy is the one to change.
  Never committed.
- **`.env.dev`**: copied too, since live starts the nightly self-test as
  the dev bot from its own folder.
- **`data\`** (the database, its backups, exports, the self-test's history
  and what it has passed): live's folder has its own, copied once at the
  switch-over while the service is stopped. The work folder's copy becomes
  an old snapshot. `data\selftest` must go with it: without it the
  self-test cannot see the month's spend and asks the real API (the dry
  run did, for US$0.03).
- **`logs\`**: a new, empty one in live's folder; the old logs stay.
- **`.venv\`**: live's folder has its own, made by the setup script and
  brought up to date by every update.

## Making it (once)

As Administrator, with live's service able to stop for a few minutes:

```
.\scripts\setup-live-folder.ps1 -Target C:\Users\temp\projects\assistant-bot-live -Branch feature/pills -Ref <commit> -Start
```

It stops the service, clones, puts the folder on `<commit>`, copies `.env`,
`.env.dev` and `data\` (not the lock or the dev database), makes the
`.venv`, checks the code knows the database's migrations, writes the
service's old settings to `service-before.txt`, points the NSSM service at
the new folder (application, directory and log files) and starts it.
`-WhatIf` prints every step and does none. `-DevOnly` is the dry run: a
scratch folder for the dev bot, with no service steps at all and only the
dev database.

After it: check `python -m core.instance_lock` from live's folder, and the
"Account checked" line in its `logs\bot.log`.

## Updating to a new commit

Only on Alex's word, and only to a commit whose full test run passed and
that is pushed:

```
.\scripts\update-live.ps1 -Target C:\Users\temp\projects\assistant-bot-live -Ref <commit>
```

It checks nothing was changed by hand, fetches, writes the commit live is
on now to `data\live-versions.txt`, checks out `<commit>` detached,
installs `requirements.txt`, checks the code knows the database (a commit
older than the database's last migration is refused, and the folder is put
back), and restarts the service. `-NoRestart` leaves the restart for later.

## Rolling back

```
.\scripts\update-live.ps1 -Target C:\Users\temp\projects\assistant-bot-live -Back
```

It moves to the commit before the last move (the last line of
`data\live-versions.txt`) and restarts. Migrations only go forward: going
back past one is refused, and needs the backup taken before it as well
(`data\backups`, made every night at 3:00 am).

To go back to running from the work folder altogether: stop the service,
run the lines in `service-before.txt` (live's folder), start it.

## Things to know after the switch-over

- The two folders have their own locks (`data\bot.lock`), so the lock can
  no longer tell that two copies of live are running: never start
  `python main.py` without `--dev` in the work folder. The dev bot has its
  own token and is never a second live.
- Claude Code keeps working in the work folder; a restart of live no longer
  picks up its work. Shipping is an update to a commit.
- The nightly self-test runs from live's folder, so it tests what live
  runs.

## The dry run (2026-10-15)

`setup-live-folder.ps1 -DevOnly` into a scratch folder, on commit 34366f2:
clone, `.env` and `.env.dev`, the dev database only, `.venv`, migrations
checked (25 of 25); the service was never read or changed. Then
`update-live.ps1 -NoRestart` to 5a28d56 and `-Back` to 34366f2, both
recorded in `data\live-versions.txt`. Then the to-dos self-test stage from
the scratch folder as the dev bot: 9 of 9. The scratch folder was removed.

What the dry run found and fixed: Windows PowerShell drops double quotes
from an argument passed to a program, so the migration check in the setup
script (written before) could never have run; and a helper named `Git`
called itself. Both scripts parse and both ran end to end.
