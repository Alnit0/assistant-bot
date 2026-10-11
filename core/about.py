from pathlib import Path

from core import clock
from core.config import BASE_DIR

# ---------------------------------------------------------------------------
# What is running: when this copy of the bot started and which commit its code
# was at. Read once, when the bot starts (`dev status` shows it): a commit
# made later is not what is running until the next restart.
# ---------------------------------------------------------------------------
UNKNOWN = "unknown"


def commit(root: Path = BASE_DIR) -> str:
    """The branch and short commit the code is at ("feature/pills @ ad5c1a6"),
    read from `.git` itself, so git need not be installed. "unknown" if it
    can't be read. Changes not committed don't show."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7] or UNKNOWN  # a detached HEAD is the commit itself
        ref = head.removeprefix("ref: ")
        branch = ref.removeprefix("refs/heads/")
        loose = git / ref
        if loose.exists():
            return f"{branch} @ {loose.read_text(encoding='utf-8').strip()[:7]}"
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {ref}"):
                return f"{branch} @ {line.split()[0][:7]}"
    except OSError:
        pass
    return UNKNOWN


STARTED = clock.real_now()  # really: uptime is never the dev clock's
COMMIT = commit()
