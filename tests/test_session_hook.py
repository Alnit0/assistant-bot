"""The SessionStart hook (.claude/settings.json, scripts/now.ps1): every Claude Code session starts by reading docs/NOW.md."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_hook_runs_on_startup_resume_clear_and_compact_and_is_in_the_committed_settings():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    (start,) = settings["hooks"]["SessionStart"]
    assert set(start["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}
    (hook,) = start["hooks"]
    assert hook["type"] == "command" and "scripts/now.ps1" in hook["command"] and (ROOT / "scripts" / "now.ps1").exists()


def test_now_md_is_short():
    lines = (ROOT / "docs" / "NOW.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 40, f"docs/NOW.md is {len(lines)} lines: 40 at most (history is docs/STATUS.md)"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="no PowerShell on this machine")
def test_the_script_prints_now_md_and_never_fails():
    ran = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "now.ps1")],
        capture_output=True, timeout=30, cwd=ROOT,
    )
    said = ran.stdout.decode("utf-8", errors="replace")
    assert ran.returncode == 0 and "# Now" in said and said.startswith("docs/NOW.md")


def test_claude_md_stays_under_10_kb():
    size = len((ROOT / "CLAUDE.md").read_bytes())
    assert size < 10 * 1024, f"CLAUDE.md is {size} bytes: keep it under 10 KB (the rules in full are docs/RULES.md)"
