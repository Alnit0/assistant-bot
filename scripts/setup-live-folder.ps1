<#
.SYNOPSIS
    Give the live bot a folder of its own, on main, and point the Windows service at it.

.DESCRIPTION
    Today the service runs from the folder the code is worked on in, so the live
    bot runs whatever branch is checked out there. This script makes a second
    folder for live:

      1. stops the service (so the database is not copied while it is written)
      2. clones the repository into the new folder, on the branch given (main)
      3. copies .env and data\ into it (not the lock, the dev database or its backups)
      4. makes its .venv and installs requirements.txt
      5. checks that the code in the new folder knows the copied database
      6. points the NSSM service at the new folder, keeping a note of the old settings
      7. starts the service, only with -Start

    Every step is printed before it is done. With -WhatIf nothing is done: the
    steps are only printed. With -Ref the new folder is put on that commit,
    detached: live runs one committed version (docs/LIVE-FOLDER.md), moved on
    later with scripts\update-live.ps1. With -DevOnly it is a dry run for the
    dev bot: a scratch folder with .env.dev and the dev database only, and the
    service is never read, stopped or changed.

    Run it yourself, in a Terminal opened as Administrator. Nothing here is run
    by the bot or by its tests.

.PARAMETER Target
    The new folder for live. It must not exist yet.

.PARAMETER Source
    The folder live runs from today (this repository). The default is the folder this script is in.

.PARAMETER Branch
    The branch live is to run. The default is main.

.PARAMETER ServiceName
    The NSSM service. The default is assistant-bot.

.PARAMETER RepoUrl
    Where to clone from. The default is the Source folder's `origin`.

.PARAMETER Ref
    A commit (or tag) to put the new folder on, detached, after the clone. Without it, the branch's newest commit.

.PARAMETER DevOnly
    A dry run for the dev bot: no service steps at all, live's database is not copied (only the dev one), and the
    target is a scratch folder. For trying the script without touching live.

.PARAMETER Start
    Start the service at the end. Without it the service is left stopped and the command to start it is printed.

.PARAMETER WhatIf
    Print every step and do none of them.

.EXAMPLE
    .\scripts\setup-live-folder.ps1 -WhatIf

.EXAMPLE
    .\scripts\setup-live-folder.ps1 -Target C:\Users\temp\projects\assistant-bot-live -Start
#>
param(
    [string]$Target = "",
    [string]$Source = "",
    [string]$Branch = "main",
    [string]$ServiceName = "assistant-bot",
    [string]$RepoUrl = "",
    [string]$Ref = "",
    [switch]$DevOnly,
    [switch]$Start,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

if (-not $Source) { $Source = Split-Path -Parent $PSScriptRoot }
$Source = (Resolve-Path $Source).Path.TrimEnd('\')
if (-not $Target) { $Target = "$Source-live" }
$Target = [System.IO.Path]::GetFullPath($Target).TrimEnd('\')

$script:Number = 0

function Say([string]$Text) { Write-Host $Text }

function Step([string]$What, [scriptblock]$Do) {
    # Print the step, then do it (unless -WhatIf). A step that fails stops the script.
    $script:Number += 1
    if ($WhatIf) {
        Say "[$($script:Number)] WOULD: $What"
        return
    }
    Say "[$($script:Number)] $What"
    & $Do
}

function Run([string]$Exe, [string[]]$Arguments) {
    # A program that must succeed: its exit code is checked, since PowerShell does not stop for one
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Need([string]$Program) {
    if (-not (Get-Command $Program -ErrorAction SilentlyContinue)) { throw "$Program is not on the PATH." }
}

# ---------------------------------------------------------------------------
# Before anything is touched
# ---------------------------------------------------------------------------
Say "Live folder for the service '$ServiceName'"
Say "  from:   $Source"
Say "  to:     $Target"
Say "  branch: $Branch"
if ($WhatIf) { Say "  -WhatIf: nothing will be done; the steps are only printed." }
Say ""

Need "git"
Need "nssm"
Need "python"

if (-not (Test-Path (Join-Path $Source ".env"))) { throw "There is no .env in $Source." }
if (-not (Test-Path (Join-Path $Source "data"))) { throw "There is no data folder in $Source." }
if (Test-Path $Target) { throw "$Target already exists. Choose another -Target, or remove it yourself first." }
if ($Target.StartsWith("$Source\", [System.StringComparison]::OrdinalIgnoreCase)) { throw "The new folder can't be inside the old one." }

if (-not $RepoUrl) {
    $RepoUrl = (& git -C $Source remote get-url origin)
    if ($LASTEXITCODE -ne 0 -or -not $RepoUrl) { throw "Could not read the origin of $Source. Give -RepoUrl." }
}
Say "  clone:  $RepoUrl"

if ($DevOnly) {
    Say "  -DevOnly: a dry run for the dev bot. The service is not read, stopped or changed; live's database is not copied."
    if (-not (Test-Path (Join-Path $Source ".env.dev"))) { throw "There is no .env.dev in ${Source}: the dev bot is what a dry run uses." }
}
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DevOnly) {
    if ($WhatIf) { Say "  note:   not running as Administrator. The real run needs it, for nssm." }
    else { throw "Run this in a Terminal opened as Administrator: nssm needs it." }
}

# The service as it is now. Read before anything changes, and kept for going back
$Settings = "Application", "AppParameters", "AppDirectory", "AppStdout", "AppStderr"
$Before = [ordered]@{}
$After = [ordered]@{}
if (-not $DevOnly) {
foreach ($name in $Settings) {
    $value = ""
    try { $value = ((& nssm get $ServiceName $name) -join "").Trim() } catch { $value = "" }
    $Before[$name] = $value
}
if (-not $Before["AppDirectory"]) { throw "Could not read the service '$ServiceName' with nssm. Is the name right, and is this an Administrator terminal?" }
Say ""
Say "The service now:"
foreach ($name in $Settings) { Say ("  {0,-14} {1}" -f $name, $Before[$name]) }
if (-not $Before["AppDirectory"].TrimEnd('\').Equals($Source, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The service runs from $($Before['AppDirectory']), not from $Source. Give -Source the folder it runs from."
}

# The same settings with the old folder swapped for the new one
foreach ($name in $Settings) {
    $value = $Before[$name]
    if ($value -and $value.StartsWith($Source, [System.StringComparison]::OrdinalIgnoreCase)) {
        $value = $Target + $value.Substring($Source.Length)
    }
    $After[$name] = $value
}
Say ""
Say "The service afterwards:"
foreach ($name in $Settings) { Say ("  {0,-14} {1}" -f $name, $After[$name]) }
Say ""
}

$TargetPython = Join-Path $Target ".venv\Scripts\python.exe"

# ---------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------
if (-not $DevOnly) {
Step "Stop the service '$ServiceName' (nssm stop), so the database is not copied while it is being written" {
    & nssm stop $ServiceName | Out-Host
    $status = ((& nssm status $ServiceName) -join "").Trim()
    if ($status -ne "SERVICE_STOPPED") { throw "The service did not stop (it says $status)." }
}

Step "Check that no other copy of the bot is running from $Source (python -m core.instance_lock)" {
    $sourcePython = Join-Path $Source ".venv\Scripts\python.exe"
    Push-Location $Source
    try { $said = (& $sourcePython -m core.instance_lock) -join "`n" } finally { Pop-Location }
    Say $said
    if ($said -notmatch "No bot is running") { throw "A copy of the bot is still running. Stop it (Ctrl + C in its terminal) and run this again." }
}
}

Step "Clone $RepoUrl into $Target on the branch $Branch (git clone --branch $Branch)" {
    Run "git" @("clone", "--branch", $Branch, $RepoUrl, $Target)
}

if ($Ref) {
    Step "Put $Target on the commit $Ref, detached: live runs one committed version, never a branch that moves" {
        Run "git" @("-C", $Target, "checkout", "--quiet", "--detach", $Ref)
    }
}

Step "Copy .env from $Source to $Target" {
    Copy-Item -Path (Join-Path $Source ".env") -Destination (Join-Path $Target ".env")
}

if (Test-Path (Join-Path $Source ".env.dev")) {
    Step "Copy .env.dev from $Source to $Target (the dev bot's settings: the nightly self-test runs from live's folder)" {
        Copy-Item -Path (Join-Path $Source ".env.dev") -Destination (Join-Path $Target ".env.dev")
    }
}

if ($DevOnly) {
Step "Copy only the dev database (data\dev.db) from $Source to ${Target}: live's is never copied in a dry run" {
    New-Item -ItemType Directory -Force -Path (Join-Path $Target "data") | Out-Null
    if (Test-Path (Join-Path $Source "data\dev.db")) { Copy-Item -Path (Join-Path $Source "data\dev.db") -Destination (Join-Path $Target "data\dev.db") }
}
} else {
Step "Copy data\ from $Source to $Target (the live database, its backups and exports; not bot.lock, dev.db, dev-clock.json or dev-backups)" {
    & robocopy (Join-Path $Source "data") (Join-Path $Target "data") /E /XF bot.lock dev.db dev-clock.json /XD dev-backups /NFL /NDL /NP | Out-Host
    # robocopy: 0 to 7 are kinds of success, 8 and above are failures
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path (Join-Path $Target "data\assistant.db"))) { throw "data\assistant.db did not arrive in $Target." }
}
}

Step "Make the logs folder in $Target (the old logs stay where they are)" {
    New-Item -ItemType Directory -Force -Path (Join-Path $Target "logs") | Out-Null
}

Step "Make the virtual environment in $Target\.venv (python -m venv)" {
    Run "python" @("-m", "venv", (Join-Path $Target ".venv"))
}

Step "Install the bot's packages into it (pip install -r requirements.txt)" {
    Run $TargetPython @("-m", "pip", "install", "--quiet", "-r", (Join-Path $Target "requirements.txt"))
}

Step "Check that the code on $Branch knows the copied database: it must have at least as many migrations as the database has had" {
    # No double quotes in it: Windows PowerShell drops them from an argument passed to a program
    $check = @'
import sqlite3, sys
from core import migrations
done = sqlite3.connect(sys.argv[1]).execute('PRAGMA user_version').fetchone()[0]
known = len(migrations.MIGRATIONS)
print(f'database is at version {done}; this code knows {known} migrations')
sys.exit(0 if known >= done else 4)
'@
    $Database = if ($DevOnly) { "data/dev.db" } else { "data/assistant.db" }
    Push-Location $Target
    try {
        & $TargetPython -c $check $Database | Out-Host
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -eq 4) {
        throw "The database is newer than the code on ${Branch}: the bot would refuse to start. Merge the work into $Branch first (or give -Branch), then remove $Target and run this again. The service has not been changed; start it with: nssm start $ServiceName"
    }
    if ($code -ne 0) { throw "The check could not be run (exit code $code). The service has not been changed; start it with: nssm start $ServiceName" }
}

if (-not $DevOnly) {
Step "Write the service's old settings to $Target\service-before.txt, for going back" {
    $lines = foreach ($name in $Settings) { "nssm set $ServiceName $name `"$($Before[$name])`"" }
    Set-Content -Path (Join-Path $Target "service-before.txt") -Value $lines -Encoding utf8
}

foreach ($name in $Settings) {
    if ($After[$name] -and $After[$name] -ne $Before[$name]) {
        $new = $After[$name]
        $setting = $name
        Step "Point the service at the new folder: nssm set $ServiceName $setting `"$new`"" {
            Run "nssm" @("set", $ServiceName, $setting, $new)
        }
    }
}

if ($Start) {
    Step "Start the service (nssm start $ServiceName)" {
        & nssm start $ServiceName | Out-Host
        Say ((& nssm status $ServiceName) -join "")
    }
}
}

# ---------------------------------------------------------------------------
# What is left for you
# ---------------------------------------------------------------------------
Say ""
if ($WhatIf) {
    Say "Nothing was done. Run it without -WhatIf, as Administrator, to do it."
} elseif ($DevOnly) {
    Say "Done: a dry run in $Target, for the dev bot. The service and live's data were not touched."
    Say "Try it: cd $Target; .venv\Scripts\python.exe -m selftest --stages todos (the dev bot, recorded answers)."
    Say "Then remove $Target."
} else {
    Say "Done. Live now runs from $Target on $Branch."
    if (-not $Start) { Say "The service is stopped. Start it with: nssm start $ServiceName" }
}
Say ""
Say "Afterwards:"
Say "  - To update live to a commit: .\scripts\update-live.ps1 -Target $Target -Ref <commit> (it restarts the service)"
Say "  - In $Source use only: python main.py --dev. Its data\assistant.db is now an old copy of live; leave it or delete it."
Say "  - The two folders each have their own lock (data\bot.lock), so the bot can no longer tell that live and a dev copy"
Say "    are both running: stop the dev copy before it would answer the same messages as live, or give it its own bot token."
Say "  - To go back: nssm stop $ServiceName; run the lines in $Target\service-before.txt; nssm start $ServiceName"
