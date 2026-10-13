"""The tests' own settings (tests/__init__.py): no test passes or fails because of what this PC's .env says."""
import re
from pathlib import Path

import tests
from core import config

ROOT = Path(tests.__file__).resolve().parent.parent


def test_every_switch_is_set_by_the_tests_themselves_so_the_real_env_never_decides():
    switches = re.findall(r'= flag\(os\.getenv\("([A-Z_]+)"\)', (ROOT / "core" / "config.py").read_text(encoding="utf-8"))
    made_up = (ROOT / "tests" / "__init__.py").read_text(encoding="utf-8")
    missing = [name for name in switches if f'"{name}"' not in made_up]
    assert len(switches) >= 9 and not missing, f"add these to tests/__init__.py, or a test will follow the real .env: {missing}"


def test_with_nothing_set_every_new_switch_is_off():
    assert not any((config.BRIEFING_ENABLED, config.WEEKLY_SUMMARY, config.DMS_ENABLED, config.NIGHTLY_SELFTEST, config.HUB_TIDY, config.QUIET_HOURS_ENABLED, config.NOTIFY_NTFY))
    assert config.NTFY_BOT_TOPIC == "" and not config.CARDS_V2 and not config.REMINDERS_ENABLED


def test_a_test_that_asks_for_no_database_never_has_the_real_one():
    from core import database

    assert database.DB_PATH.name == "no-database-asked-for.db" and database.DB_PATH != config.BASE_DIR / "data" / "assistant.db"
    assert not (config.DATA_DIR / "assistant.db").exists(), "the data folder is the test's own too"
