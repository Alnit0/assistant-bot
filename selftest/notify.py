"""A ping on my phone when a nightly self-test has a failing step (ntfy).

The topic is in `.env.notify` (`NTFY_TOPIC=<topic>`, or the topic alone on a
line). It is a secret: it is never printed, logged or returned. Whatever goes
wrong (no file, no network, ntfy down) nothing is said and nothing is raised.
"""
import base64
import urllib.request
from pathlib import Path

from core import config

FILE = config.BASE_DIR / ".env.notify"
PRIORITY = "5"
TITLE = "❌ Self-test failed"


def _topic(path: Path) -> str:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]
    except OSError:
        return ""
    lines = [line for line in lines if line and not line.startswith("#")]
    for line in lines:
        name, found, value = line.partition("=")
        if found and name.strip() == "NTFY_TOPIC":
            return value.strip().strip('"').strip("'")
    bare = [line for line in lines if "=" not in line and " " not in line]
    return bare[0] if bare else ""


def wanted(line: dict) -> bool:
    """Only a run with a failing step, or one that did not finish. A night
    with everything passing says nothing on the phone."""
    return line.get("failed", "0") not in ("0", "") or bool(line.get("note"))


def words(line: dict) -> str:
    """What the ping says: what ran, and which steps failed."""
    if line.get("note"):
        return f"{line['ran']}: {line['note']}"
    return f"{line['failed']} of {line['steps']} steps failed ({line['ran']}): {line['failed_steps']}"[:300]


def send(body: str, title: str = TITLE, path: Path | None = None, post=None) -> bool:
    """Post to ntfy. True if it went. Never raises, and never says the topic."""
    topic = _topic(path or FILE)
    if not topic:
        return False
    try:
        request = urllib.request.Request(
            f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), method="POST",
            headers={
                # A header holds ASCII only: the title goes as RFC 2047, which ntfy reads
                "Title": "=?UTF-8?B?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?=",
                "Priority": PRIORITY, "Tags": "test_tube", "Content-Type": "text/plain; charset=utf-8",
            },
        )
        (post or urllib.request.urlopen)(request, timeout=8)
        return True
    except Exception:
        return False
