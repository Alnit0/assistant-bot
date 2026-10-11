import asyncio
import logging
import sqlite3
import zipfile
from pathlib import Path

from core import scheduler
from core.config import BACKUP_DIR, BACKUP_KEEP, BACKUP_TIME, EXPORTS_DIR, SPECS_DIR, now_nz
from core.database import connect
from core.discord_utils import log_error, log_simple

log = logging.getLogger("assistant")

NIGHTLY_PREFIX = "assistant-"
SPECS_PREFIX = "specs-"
EXPORTS_PREFIX = "exports-"

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


def _prune(pattern: str) -> None:
    """Delete all but the newest BACKUP_KEEP backups matching `pattern`."""
    # The timestamp in the name sorts oldest first
    backups = sorted(BACKUP_DIR.glob(pattern))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink()
        log.info("Removed old backup: %s", old.name)


def backup_database() -> Path:
    """Take a nightly backup, then delete all but the newest BACKUP_KEEP. Blocking."""
    target = BACKUP_DIR / f"{NIGHTLY_PREFIX}{now_nz():%Y-%m-%d_%H%M%S}.db"
    _copy_database(target)
    _prune(f"{NIGHTLY_PREFIX}*.db")
    return target


def _zip_folder(folder: Path, prefix: str) -> Path | None:
    """Zip everything in a folder next to the database backup, keeping the newest
    BACKUP_KEEP with that prefix. None if there is nothing to copy. Blocking."""
    files = sorted(path for path in folder.rglob("*") if path.is_file()) if folder.is_dir() else []
    if not files:
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"{prefix}{now_nz():%Y-%m-%d_%H%M%S}.zip"
    temporary = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(folder).as_posix())
    temporary.replace(target)
    _prune(f"{prefix}*.zip")
    return target


def backup_specs() -> Path | None:
    """Zip the private spec sheets next to the database backup, keeping the newest
    BACKUP_KEEP. None if there are none to copy. Blocking.

    docs/specs/ is gitignored, so this is the only other copy of it.
    """
    return _zip_folder(SPECS_DIR, SPECS_PREFIX)


def backup_exports() -> Path | None:
    """Zip the transcripts of the channels that were reset (data/exports/) the
    same way. They are in no other place: the messages themselves are gone."""
    return _zip_folder(EXPORTS_DIR, EXPORTS_PREFIX)


def snapshot_before_migration(version: int) -> Path:
    """Copy the database before a schema upgrade. Kept until deleted by hand. Blocking."""
    target = BACKUP_DIR / f"pre-migration-v{version}-{now_nz():%Y-%m-%d_%H%M%S}.db"
    _copy_database(target)
    return target


async def run_nightly_backup() -> bool:
    """Scheduled job: back up the database and report to #bot-log. False if any
    part of it could not be saved (each failure has its own card there)."""
    try:
        path = await asyncio.to_thread(backup_database)
    except Exception as error:
        log.exception("Nightly backup failed")
        await log_error("Backup failed", repr(error))
        return False
    size_kb = path.stat().st_size / 1024
    log.info("Backup saved: %s (%.0f KB)", path.name, size_kb)
    lines = [f"{path.name} ({size_kb:.0f} KB)"]
    complete = True
    # The specs and the exports are separate copies: failing to take one doesn't undo the database's
    for what, take in (("Specs", backup_specs), ("Exports", backup_exports)):
        try:
            saved = await asyncio.to_thread(take)
        except Exception as error:
            log.exception("%s backup failed", what)
            await log_error(f"{what} backup failed", repr(error))
            complete = False
        else:
            if saved is not None:
                log.info("%s backup saved: %s", what, saved.name)
                lines.append(f"{saved.name} ({saved.stat().st_size / 1024:.0f} KB)")
    await log_simple("💾 Backup saved", "\n".join(lines))
    return complete


# ---------------------------------------------------------------------------
# Scheduling: one job in the scheduler at a time, which books the next when it runs
# ---------------------------------------------------------------------------
async def schedule_next_backup() -> None:
    """Make sure a nightly backup is booked, for the next BACKUP_TIME on the NZ clock."""
    due_at = scheduler.next_run(BACKUP_TIME, now_nz())
    await scheduler.ensure(JOB_TASK, JOB_KIND, due_at)
    log.info("Next nightly backup: %s", due_at.isoformat())


scheduler.keep_booked(f"{JOB_TASK}/{JOB_KIND}", schedule_next_backup)


async def nightly_backup_job(job: scheduler.Job) -> None:
    """Scheduler handler: back up now, then book tomorrow's.

    If the bot was off at backup time this runs late, at the next start.
    """
    if job.is_late:
        log.info("Nightly backup is running %.0f minutes late", job.late_by / 60)
    try:
        if await run_nightly_backup() is False:
            # Said in #bot-log already; recorded too, so the bot's status shows it until a backup works
            scheduler.report(job, scheduler.FAILED)
    finally:
        await schedule_next_backup()
