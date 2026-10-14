# Prints docs/NOW.md into a Claude Code session when it starts, resumes, is
# cleared or is compacted (the SessionStart hook in .claude/settings.json), so
# every session begins knowing what is happening now. Reads one file; changes
# nothing; never fails the session.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$now = Join-Path (Split-Path -Parent $PSScriptRoot) "docs\NOW.md"
if (Test-Path $now) {
    "docs/NOW.md (what is happening now; run /catchup for the rest):"
    ""
    Get-Content -Path $now -Raw -Encoding utf8
} else {
    "There is no docs/NOW.md: run /catchup."
}
exit 0
