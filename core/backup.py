import asyncio
import logging
import sqlite3
from pathlib import Path

from core import scheduler
from core.config import BACKUP_DIR, BACKUP_KEEP, BACKUP_TIME, now_nz
from core.database import connect
from core.discord_utils import log_error, log_simple

log = logging.getLogger("assistant")

NIGHTLY_PREFIX = "assistant-"

# How the nightly backup is known to the scheduler
JOB_TASK = "core"
JOB_KIND = "nightly_backup"


def _copy_database(target: Path) -> None:
    """Copy the live database to target using SQLite's backup API (safe while in use)."""
    BACKUP_DIR.mkdir(exist_ok=True)
    # Write to a temporary name first, so a half-finished copy never looks like a backup
    temporary = target.with_name(target.name + ".tmp")
    source = connect()
    try:
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    temporary.replace(target)


def backup_database() -> Path:
    """Take a nightly backup, then delete all but the newest BACKUP_KEEP. Blocking."""
    target = BACKUP_DIR / f"{NIGHTLY_PREFIX}{now_nz():%Y-%m-%d_%H%M%S}.db"
    _copy_database(target)

    # The timestamp in the name sorts oldest first
    backups = sorted(BACKUP_DIR.glob(f"{NIGHTLY_PREFIX}*.db"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink()
        log.info("Removed old backup: %s", old.name)
    return target


def snapshot_before_migration(version: int) -> Path:
    """Copy the database before a schema upgrade. Kept until deleted by hand. Blocking."""
    target = BACKUP_DIR / f"pre-migration-v{version}-{now_nz():%Y-%m-%d_%H%M%S}.db"
    _copy_database(target)
    return target


async def run_nightly_backup() -> None:
    """Scheduled job: back up the database and report to #bot-log."""
    try:
        path = await asyncio.to_thread(backup_database)
    except Exception as error:
        log.exception("Nightly backup failed")
        await log_error("Backup failed", repr(error))
        return
    size_kb = path.stat().st_size / 1024
    log.info("Backup saved: %s (%.0f KB)", path.name, size_kb)
    await log_simple("💾 Backup saved", f"{path.name} ({size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Scheduling: one job in the scheduler at a time, which books the next when it runs
# ---------------------------------------------------------------------------
async def schedule_next_backup() -> None:
    """Make sure a nightly backup is booked, for the next BACKUP_TIME on the NZ clock."""
    if await scheduler.pending_jobs(JOB_TASK, JOB_KIND):
        return
    due_at = scheduler.next_run(BACKUP_TIME, now_nz())
    await scheduler.add_job(JOB_TASK, JOB_KIND, due_at)
    log.info("Next nightly backup: %s", due_at.isoformat())


async def nightly_backup_job(job: scheduler.Job) -> None:
    """Scheduler handler: back up now, then book tomorrow's.

    If the bot was off at backup time this runs late, at the next start.
    """
    if job.is_late:
        log.info("Nightly backup is running %.0f minutes late", job.late_by / 60)
    try:
        await run_nightly_backup()
    finally:
        await schedule_next_backup()
