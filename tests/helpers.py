import tempfile
import unittest
from pathlib import Path

from core import backup, database, migrations, users


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    """A test with its own empty, fully migrated database in a temporary folder."""

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        folder = Path(self._folder.name)
        self._real = (database.DB_PATH, backup.BACKUP_DIR)
        database.DB_PATH = folder / "test.db"
        backup.BACKUP_DIR = folder / "backups"
        migrations.migrate(self.skill_migrations())
        users.ensure_owner()

    def tearDown(self):
        database.DB_PATH, backup.BACKUP_DIR = self._real
        self._folder.cleanup()

    def skill_migrations(self) -> dict[str, list]:
        """Override to add a skill's tables."""
        return {}

    def query(self, sql: str, values: tuple = ()) -> list[tuple]:
        conn = database.connect()
        try:
            return conn.execute(sql, values).fetchall()
        finally:
            conn.close()
