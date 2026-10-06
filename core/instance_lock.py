import logging
import os
import sys
from pathlib import Path

from core.config import DATA_DIR, now_nz

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Single-instance lock
#
# Two copies of the bot would both answer every message and button press. To
# prevent that, the running copy holds an operating-system lock on this file
# for as long as it lives. The system releases the lock itself when the
# process ends, however it ends, so a crash can never leave a stale lock
# behind (unlike a file that merely records a PID).
# ---------------------------------------------------------------------------
LOCK_PATH = DATA_DIR / "bot.lock"
EXIT_ALREADY_RUNNING = 3  # lets the Windows service be told not to retry (see DEVELOPMENT.md)

# The locked byte sits far past the file's text, so a copy that is refused can
# still read who holds the lock
_LOCK_OFFSET = 1 << 20

# Kept open for the life of the process: closing it would release the lock
_lock_fd: int | None = None


def _try_lock(fd: int) -> bool:
    os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def acquire(path: Path = LOCK_PATH) -> None:
    """Claim the lock, or log a clear error and exit if another copy holds it.

    Blocking: runs at startup, before the event loop.
    """
    global _lock_fd
    fd = os.open(path, os.O_RDWR | os.O_CREAT)

    if not _try_lock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        holder = os.read(fd, 200).decode("utf-8", errors="replace").strip() or "details unknown"
        os.close(fd)
        log.error(
            "Another copy of the bot is already running (%s). Stop it first "
            "(Ctrl+C in its terminal, or: nssm stop assistant-bot). This copy will now exit.",
            holder,
        )
        sys.exit(EXIT_ALREADY_RUNNING)

    # Ours. Note who we are, for the message a refused copy shows
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, f"PID {os.getpid()}, started {now_nz():%Y-%m-%d %H:%M:%S}".encode("utf-8"))
    _lock_fd = fd
