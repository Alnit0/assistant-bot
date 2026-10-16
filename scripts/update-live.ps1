<#
.SYNOPSIS
    Move live's own folder to another commit (an update or a roll back), then restart the service.

.DESCRIPTION
    Live runs from a folder of its own, on one committed version, so a reboot
    never loads work in progress (docs/LIVE-FOLDER.md). This script moves that
    folder to another commit:

      1. puts back docs\SELFTEST.md (the nightly self-test writes it here), then
         checks the folder is a clean clone (nothing changed by hand)
      2. fetches from origin, and checks the commit exists and is pushed (on
         origin/feature/pills): only pushed code ever runs as live
      3. writes the commit live is on now to data\live-versions.txt, for going back
      4. checks out the commit, detached (live never runs a branch that moves)
      5. installs requirements.txt into its .venv
      6. checks the code knows the database: a commit older than the database's
         last migration is refused (restore the backup taken before it instead)
      7. restarts the service, unless -NoRestart

    To roll back: run it with -Ref set to the commit before (the last line of
    data\live-versions.txt says which), or with -Back.

    Every step is printed before it is done; with -WhatIf nothing is done.
    Run it yourself, as Administrator for the restart. The bot never runs it.

.PARAMETER Target
    Live's own folder. The default is C:\Users\temp\projects\assistant-bot-live.

.PARAMETER Branch
    The pushed branch the commit must be on. The default is feature/pills.

.PARAMETER Ref
    The commit (or tag) to move to. A branch name is taken as the commit it points at now.

.PARAMETER Back
    Move to the commit live was on before the last move (from data\live-versions.txt).

.PARAMETER ServiceName
    The NSSM service. The default is assistant-bot.

.PARAMETER NoRestart
    Leave the service as it is (for a dry run, or to restart it yourself later).

.PARAMETER WhatIf
    Print every step and do none of them.

.EXAMPLE
    .\scripts\update-live.ps1 -Ref 5a28d56

.EXAMPLE
    .\scripts\update-live.ps1 -Back
#>
param(
    [string]$Target = "C:\Users\temp\projects\assistant-bot-live",
    [string]$Branch = "feature/pills",
    [string]$Ref = "",
    [switch]$Back,
    [string]$ServiceName = "assistant-bot",
    [switch]$NoRestart,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$script:Number = 0

function Say([string]$Text) { Write-Host $Text }

function Step([string]$What, [scriptblock]$Do) {
    $script:Number += 1
    if ($WhatIf) { Say "[$($script:Number)] WOULD: $What"; return }
    Say "[$($script:Number)] $What"
    & $Do
}

function GitHere([string[]]$Arguments) {
    # Named so: a function called Git would be what `git` means inside it, and call itself
    # git's progress on stderr is not an error (see setup-live-folder.ps1, Run)
    $was = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $said = & git.exe -C $Target @Arguments 2>$null } finally { $ErrorActionPreference = $was }
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
    return $said
}

$Target = [System.IO.Path]::GetFullPath($Target).TrimEnd('\')
if (-not (Test-Path (Join-Path $Target ".git"))) { throw "$Target is not a clone: make it with scripts\setup-live-folder.ps1 first." }
$Versions = Join-Path $Target "data\live-versions.txt"
$Python = Join-Path $Target ".venv\Scripts\python.exe"

if ($Back) {
    if (-not (Test-Path $Versions)) { throw "There is no ${Versions}: nothing to go back to." }
    $Ref = ((Get-Content $Versions | Where-Object { $_.Trim() }) | Select-Object -Last 1).Split(" ")[0]
    Say "Going back to $Ref, the commit live was on before the last move."
}
if (-not $Ref) { throw "Say which commit: -Ref <commit>, or -Back." }

$Now = (GitHere @("rev-parse", "--short", "HEAD")) -join ""
Say "Live's folder: $Target"
Say "  on now:  $Now"
Say "  move to: $Ref"
if ($WhatIf) { Say "  -WhatIf: nothing will be done; the steps are only printed." }
Say ""

Step "Put back docs\SELFTEST.md: the nightly self-test, which runs in this folder, writes its table there (its record stays in data\selftest)" {
    GitHere @("checkout", "--quiet", "--", "docs/SELFTEST.md") | Out-Null
}

Step "Check that $Target is clean: nothing in it changed by hand (git status)" {
    $changed = GitHere @("status", "--porcelain", "--untracked-files=no")
    if ($changed) { throw "Files in $Target were changed by hand:`n$($changed -join "`n")`nLive's folder only ever moves between commits. Look at them, then git checkout -- . in it." }
}

Step "Fetch from origin, and check that $Ref is a commit" {
    GitHere @("fetch", "--quiet", "origin") | Out-Null
    $script:Commit = (GitHere @("rev-parse", "--verify", "--short", "$Ref^{commit}")) -join ""
    Say "  $Ref is $($script:Commit)"
    $was = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & git.exe -C $Target merge-base --is-ancestor $script:Commit "origin/$Branch" 2>$null } finally { $ErrorActionPreference = $was }
    if ($LASTEXITCODE -ne 0) { throw "$Ref is not on origin/${Branch}: push it first. Live only runs pushed code." }
    Say "  it is pushed (on origin/$Branch)"
}

Step "Write the commit live is on now ($Now) to data\live-versions.txt, for going back" {
    Add-Content -Path $Versions -Value "$Now $(Get-Date -Format 'yyyy-MM-dd HH:mm') before moving to $Ref" -Encoding utf8
}

Step "Check out $Ref, detached: live runs one commit, never a branch that moves" {
    GitHere @("checkout", "--quiet", "--detach", $Ref) | Out-Null
}

Step "Install the packages that commit needs (pip install -r requirements.txt)" {
    & $Python -m pip install --quiet -r (Join-Path $Target "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
}

Step "Check that the code knows the database: at least as many migrations as the database has had" {
    # No double quotes in it: Windows PowerShell drops them from an argument passed to a program
    $check = @'
import sqlite3, sys
from core import migrations
done = sqlite3.connect(sys.argv[1]).execute('PRAGMA user_version').fetchone()[0]
known = len(migrations.MIGRATIONS)
print(f'database is at version {done}; this code knows {known} migrations')
sys.exit(0 if known >= done else 4)
'@
    # Live's database; in a dry-run folder (setup-live-folder.ps1 -DevOnly) only the dev one is there
    $Database = if (Test-Path (Join-Path $Target "data/assistant.db")) { "data/assistant.db" } else { "data/dev.db" }
    Push-Location $Target
    try { & $Python -c $check $Database | Out-Host; $code = $LASTEXITCODE } finally { Pop-Location }
    if ($code -eq 4) {
        GitHere @("checkout", "--quiet", "--detach", $Now) | Out-Null
        throw "The database is newer than ${Ref}: that code would refuse to start. Put back on $Now. To go back past a migration, restore the backup taken before it (data\backups) as well."
    }
    if ($code -ne 0) { throw "The check could not be run (exit code $code)." }
}

Step "Migrate a copy of the database with that code, before anything is restarted" {
    # Found 16 Oct: a migration put in the middle of the list stopped live at its start. The copy is a
    # temporary file; live's own database is only read. No double quotes: PowerShell drops them
    $trial = @'
import pathlib, sqlite3, sys, tempfile
from core import config, database
source = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
copy = pathlib.Path(tempfile.mkdtemp()) / 'copy.db'
target = sqlite3.connect(str(copy))
source.backup(target)
target.close()
config.DB_PATH = database.DB_PATH = copy
from core import migrations
from tasks import registry
registry.load()
migrations.migrate(registry.task_migrations())
print('a copy of the database migrated to version', sqlite3.connect(str(copy)).execute('PRAGMA user_version').fetchone()[0])
'@
    $Database = if (Test-Path (Join-Path $Target "data/assistant.db")) { "data/assistant.db" } else { "data/dev.db" }
    Push-Location $Target
    try { & $Python -c $trial $Database | Out-Host; $code = $LASTEXITCODE } finally { Pop-Location }
    if ($code -ne 0) {
        GitHere @("checkout", "--quiet", "--detach", $Now) | Out-Null
        throw "A copy of the database could not be migrated with ${Ref} (exit code $code): nothing was restarted. Put back on $Now."
    }
}

if (-not $NoRestart) {
    Step "Restart the service (nssm restart $ServiceName)" {
        & nssm restart $ServiceName | Out-Host
        Say ((& nssm status $ServiceName) -join "")
    }
}

Say ""
if ($WhatIf) { Say "Nothing was done." }
else {
    Say "Live's folder is on $Ref."
    if ($NoRestart) { Say "The service was not restarted: nssm restart $ServiceName when you are ready." }
    Say "Then check it: python -m core.instance_lock (from $Target), and the account line in logs\bot.log."
    Say "To go back: .\scripts\update-live.ps1 -Target $Target -Back"
}
