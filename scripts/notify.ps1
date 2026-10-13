# Phone notifications for Claude Code, through ntfy (https://ntfy.sh).
#
# Run by the hooks in .claude/settings.local.json:
#   -Kind finished   Claude Code has finished a response   (priority 3)
#   -Kind waiting    Claude Code is waiting for you        (priority 5)
#
# The topic is NTFY_TOPIC in .env.notify, beside this folder. It is a secret:
# it is never printed, logged or put in the command line. Whatever goes wrong
# (no file, no topic, ntfy not reachable) this says nothing and exits 0: a
# notification must never get in the way of the work.
#
# Kept in plain ASCII on purpose: Windows PowerShell reads a script without a
# byte order mark as ANSI, so the emoji are made from their code points.
param(
    [ValidateSet('finished', 'waiting')]
    [string]$Kind = 'finished',
    [string]$Text = ''
)

$ErrorActionPreference = 'Stop'
try {
    $root = Split-Path -Parent $PSScriptRoot
    $file = Join-Path $root '.env.notify'
    if (-not (Test-Path $file)) { exit 0 }
    $topic = ''
    foreach ($line in [System.IO.File]::ReadAllLines($file)) {
        if ($line -match '^\s*NTFY_TOPIC\s*=\s*(.+?)\s*$') { $topic = $Matches[1].Trim('"').Trim("'") }
    }
    if (-not $topic) {
        # The file may hold the topic alone, on one line, with no name in front
        foreach ($line in [System.IO.File]::ReadAllLines($file)) {
            $bare = $line.Trim()
            if ($bare -and -not $bare.StartsWith('#') -and $bare -notmatch '[=\s]') { $topic = $bare; break }
        }
    }
    if (-not $topic) { exit 0 }

    # What the hook was told, as JSON on standard input (nothing, when run by hand)
    $told = $null
    try {
        if ([Console]::IsInputRedirected) {
            $reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
            # Never waited for long: run by hand, nothing may ever arrive
            $reading = $reader.ReadToEndAsync()
            if ($reading.Wait(3000)) {
                $raw = $reading.Result
                if ($raw -and $raw.Trim()) { $told = $raw | ConvertFrom-Json }
            }
        }
    } catch { $told = $null }

    if ($Kind -eq 'waiting') {
        $title = [char]::ConvertFromUtf32(0x23F8) + [char]::ConvertFromUtf32(0xFE0F) + ' Claude Code needs you'
        $priority = '5'
        $body = 'Waiting for you.'
        if ($told -and $told.message) { $body = [string]$told.message }
    } else {
        $title = [char]::ConvertFromUtf32(0x2705) + ' Claude Code finished'
        $priority = '3'
        $body = 'Finished.'
        if ($told -and $told.last_assistant_message) {
            # The first line of the summary that says something, without its Markdown
            foreach ($line in ([string]$told.last_assistant_message -split "`n")) {
                $clean = ($line -replace '[`*_#>]', '').Trim()
                if ($clean) { $body = $clean; break }
            }
        }
    }
    if ($Text) { $body = $Text }
    if ($body.Length -gt 300) { $body = $body.Substring(0, 299) + [char]0x2026 }

    # A header may only hold ASCII: the title goes as RFC 2047, which ntfy reads
    $encoded = '=?UTF-8?B?' + [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($title)) + '?='
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $null = Invoke-WebRequest -Uri ("https://ntfy.sh/" + $topic) -Method Post -UseBasicParsing -TimeoutSec 8 `
        -Headers @{ Title = $encoded; Priority = $priority; Tags = 'computer' } `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'text/plain; charset=utf-8'
} catch {
    # Silently: no topic, no network, ntfy down. Nothing is worth interrupting for
}
exit 0
