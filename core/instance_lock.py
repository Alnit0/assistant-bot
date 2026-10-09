import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import DATA_DIR, real_now_nz

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
ACQUIRE_TRIES = 3
ACQUIRE_WAIT = 0.2  # seconds between tries

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


def _read_note(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    return os.read(fd, 200).decode("utf-8", errors="replace").strip()


def acquire(path: Path = LOCK_PATH) -> None:
    """Claim the lock, or log a clear error and exit if another copy holds it.

    Blocking: runs at startup, before the event loop.
    """
    global _lock_fd
    fd = os.open(path, os.O_RDWR | os.O_CREAT)

    # More than one try: `holder()` in another process takes the lock for an
    # instant to see whether anyone has it, and that must not turn a start away
    for attempt in range(ACQUIRE_TRIES):
        if _try_lock(fd):
            break
        if attempt < ACQUIRE_TRIES - 1:
            time.sleep(ACQUIRE_WAIT)
    else:
        note = _read_note(fd) or "details unknown"
        os.close(fd)
        log.error(
            "Another copy of the bot is already running (%s). Stop it first "
            "(Ctrl+C in its terminal, or: nssm stop assistant-bot). This copy will now exit.",
            note,
        )
        sys.exit(EXIT_ALREADY_RUNNING)

    # Ours. Note who we are, for the message a refused copy shows
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, f"PID {os.getpid()}, started {real_now_nz():%Y-%m-%d %H:%M:%S}".encode("utf-8"))
    _lock_fd = fd


# ---------------------------------------------------------------------------
# How many bots are running?
#
# The lock is the answer: at most one process can hold it, and that process is
# the bot. The list of processes is only a cross-check, and it misleads when
# read by eye: started from the virtual environment, one bot is TWO python
# processes with the same command line, `.venv\Scripts\python.exe` (a launcher)
# and the real interpreter it starts. The launcher is the other one's parent,
# so a process that is the parent of another bot process is not counted.
#
#     python -m core.instance_lock        (the bot is not started by this)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Holder:
    """Who holds the lock, as it wrote itself down when it took it."""

    pid: int | None
    started: str  # NZ time, as text


@dataclass(frozen=True)
class Process:
    pid: int
    parent_pid: int
    command: str


_NOTE = re.compile(r"PID (\d+), started (.+)")
_BOT_COMMAND = re.compile(r"""(^|[\s"'\\/])main\.py(["'\s]|$)""")


def parse_note(text: str) -> Holder:
    found = _NOTE.search(text)
    return Holder(int(found.group(1)), found.group(2).strip()) if found else Holder(None, "")


def holder(path: Path = LOCK_PATH) -> Holder | None:
    """The bot that holds the lock right now, or None if no bot is running.

    Asked of the lock itself, so a file left behind by a bot that has stopped
    is never taken for a running one. Blocking, but brief.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return None
    try:
        # If we can take it, nobody had it. Closing the file gives it straight back
        if _try_lock(fd):
            return None
        return parse_note(_read_note(fd))
    finally:
        os.close(fd)


def is_bot(process: Process) -> bool:
    return _BOT_COMMAND.search(process.command) is not None


def instances(processes: list[Process]) -> list[Process]:
    """The bots among these processes, each counted once: a launcher that is
    only the parent of the real interpreter is left out."""
    bots = [process for process in processes if is_bot(process)]
    parents = {process.parent_pid for process in bots}
    return [process for process in bots if process.pid not in parents]


def parse_processes(output: str) -> list[Process]:
    """What `list_processes` asked PowerShell for, as processes. One process comes
    back as an object, several as a list, none as nothing at all."""
    if not output.strip():
        return []
    rows = json.loads(output)
    rows = rows if isinstance(rows, list) else [rows]
    return [
        Process(int(row["ProcessId"]), int(row["ParentProcessId"] or 0), row.get("CommandLine") or "") for row in rows
    ]


def list_processes() -> list[Process] | None:
    """The python processes on this machine, or None if they can't be listed.
    Blocking (about a second): call it from a worker thread."""
    try:
        if os.name == "nt":
            script = (
                "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
                "Select-Object ProcessId, ParentProcessId, CommandLine | ConvertTo-Json -Compress"
            )
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=20,
            )
            return parse_processes(done.stdout) if done.returncode == 0 else None
        done = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True, timeout=20)
        rows = [line.split(None, 2) for line in done.stdout.splitlines()]
        return [Process(int(row[0]), int(row[1]), row[2]) for row in rows if len(row) == 3 and "python" in row[2]]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        log.info("Could not list the running processes: %s", error)
        return None


def status_text(lock: Holder | None, processes: list[Process] | None) -> str:
    """How many bots are running, in words. The lock decides; the processes
    are there to catch a copy that is running without it."""
    running = instances(processes or [])
    launchers = [process for process in (processes or []) if is_bot(process) and process not in running]
    strays = [process for process in running if lock is None or process.pid != lock.pid]

    if lock is None:
        lines = ["No bot is running: nothing holds the lock (data/bot.lock)."]
    else:
        who = f"PID {lock.pid}, started {lock.started}" if lock.pid else "details unknown"
        lines = [f"1 bot is running: {who} (it holds the lock)."]
    for process in strays:
        lines.append(
            f"⚠️ PID {process.pid} is running main.py without the lock: starting up, or about to exit. "
            "If it is still there in a few seconds, stop it."
        )
    if launchers:
        lines.append(
            f"Not counted: PID {', '.join(str(process.pid) for process in launchers)}, "
            "the .venv launcher (the parent of the real process)."
        )
    if processes is None:
        lines.append("The process list couldn't be read; the lock is what counts.")
    return "\n".join(lines)


def status() -> str:
    """The lock and the process list together. Blocking."""
    return status_text(holder(), list_processes())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(status())
