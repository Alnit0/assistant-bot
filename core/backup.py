import asyncio
import logging
import sqlite3
from pathlib import Path

from core.config import BACKUP_DIR, BACKUP_KEEP, now_nz
from core.database import connect
from core.discord_utils import log_error, log_simple

log = logging.getLogger("assistant")

NIGHTLY_PREFIX = "assistant-"


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
