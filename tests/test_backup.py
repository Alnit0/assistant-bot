"""The nightly backup's copy of the private spec sheets (docs/specs/)."""
import asyncio
import zipfile
from datetime import datetime

import pytest

from core import backup
from core.config import TIMEZONE


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Temporary specs and backup folders, and a clock the test can move."""
    specs, backups = tmp_path / "specs", tmp_path / "backups"
    specs.mkdir()
    monkeypatch.setattr(backup, "SPECS_DIR", specs)
    monkeypatch.setattr(backup, "BACKUP_DIR", backups)
    clock = {"now": datetime(2026, 10, 9, 3, 0, tzinfo=TIMEZONE)}
    monkeypatch.setattr(backup, "now_nz", lambda: clock["now"])
    return specs, backups, clock


def test_specs_are_zipped_next_to_the_database_backups(folders):
    specs, backups, _ = folders
    (specs / "pills.md").write_text("Task spec: Pills", encoding="utf-8")
    (specs / "drafts").mkdir()
    (specs / "drafts" / "hub.md").write_text("Hub", encoding="utf-8")

    target = backup.backup_specs()

    assert target == backups / "specs-2026-10-09_030000.zip"
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["drafts/hub.md", "pills.md"]
        assert archive.read("pills.md").decode("utf-8") == "Task spec: Pills"
    assert not list(backups.glob("*.tmp"))


def test_no_specs_means_no_backup(folders, monkeypatch):
    specs, backups, _ = folders
    assert backup.backup_specs() is None  # the folder is empty
    monkeypatch.setattr(backup, "SPECS_DIR", specs / "missing")
    assert backup.backup_specs() is None  # there is no folder
    assert not backups.exists()


def test_only_the_newest_specs_backups_are_kept(folders):
    specs, backups, clock = folders
    (specs / "pills.md").write_text("x", encoding="utf-8")
    backups.mkdir()
    (backups / "assistant-2026-10-01_030000.db").write_text("db", encoding="utf-8")

    for day in range(1, backup.BACKUP_KEEP + 3):
        clock["now"] = datetime(2026, 10, day, 3, 0, tzinfo=TIMEZONE)
        backup.backup_specs()

    kept = sorted(path.name for path in backups.glob("specs-*.zip"))
    assert len(kept) == backup.BACKUP_KEEP
    assert kept[0] == "specs-2026-10-03_030000.zip"
    # Database backups are counted separately
    assert (backups / "assistant-2026-10-01_030000.db").exists()


def test_a_failed_specs_backup_still_reports_the_database_backup(folders, monkeypatch):
    _, backups, _ = folders
    backups.mkdir()
    database_copy = backups / "assistant-2026-10-09_030000.db"
    database_copy.write_text("db", encoding="utf-8")
    cards, errors = [], []

    def broken():
        raise OSError("disk full")

    async def log_simple(title, text):
        cards.append((title, text))

    async def log_error(title, text):
        errors.append(title)

    monkeypatch.setattr(backup, "backup_database", lambda: database_copy)
    monkeypatch.setattr(backup, "backup_specs", broken)
    monkeypatch.setattr(backup, "log_simple", log_simple)
    monkeypatch.setattr(backup, "log_error", log_error)

    asyncio.run(backup.run_nightly_backup())

    assert errors == ["Specs backup failed"]
    assert cards == [("💾 Backup saved", "assistant-2026-10-09_030000.db (0 KB)")]
