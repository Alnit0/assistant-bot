"""`dev clock`, `dev reset-db` and the dev database (--dev): the words and their guards."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core import clock, database, scheduler
from core.config import TIMEZONE
from core.errors import UserError
from core.timeinput import AmbiguousTime
from tasks import dev, registry
from tasks.dev import clockwords, panel, tools


def nz(*parts) -> datetime:
    return datetime(*parts, tzinfo=TIMEZONE)


NOW = nz(2026, 10, 9, 15, 0)  # a Friday afternoon


# ---------------------------------------------------------------------------
# What was typed after `dev clock`
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "words, expected",
    [
        (["5:59pm"], nz(2026, 10, 9, 17, 59)),  # later today
        (["20:00"], nz(2026, 10, 9, 20, 0)),
        (["5:59am"], nz(2026, 10, 10, 5, 59)),  # already past today: tomorrow's, by way of midnight
        (["6", "am"], nz(2026, 10, 10, 6, 0)),
        (["3pm"], nz(2026, 10, 10, 15, 0)),  # this very time is the next one, a day on
        (["midnight"], nz(2026, 10, 10, 0, 0)),
        (["+2h"], nz(2026, 10, 9, 17, 0)),
        (["+15m"], nz(2026, 10, 9, 15, 15)),
        (["+", "1h", "30m"], nz(2026, 10, 9, 16, 30)),
    ],
)
def test_a_time_or_a_duration_is_a_moment_ahead(words, expected):
    moment = clockwords.target(words, NOW)
    assert moment == expected
    assert moment > NOW, "the clock only ever moves forward"


def test_reset_is_not_a_moment():
    assert clockwords.target(["reset"], NOW) is None
    assert clockwords.target(["RESET"], NOW) is None


def test_a_time_that_could_be_morning_or_evening_is_not_guessed():
    with pytest.raises(AmbiguousTime, match="6am or 6pm"):
        clockwords.target(["6"], NOW)


@pytest.mark.parametrize("words", [[], ["soon"], ["+"], ["+banana"], ["-2h"], ["yesterday"]])
def test_anything_else_is_refused(words):
    with pytest.raises(UserError):
        clockwords.target(words, NOW)


def test_the_clock_in_words():
    assert clockwords.describe(NOW, timedelta(0)) == "Fri 9 Oct, 3:00 pm (the real time)"
    assert clockwords.describe(nz(2026, 10, 10, 6, 0), timedelta(hours=15)) == "Sat 10 Oct, 6:00 am (15h ahead)"
    almost = timedelta(hours=2) - timedelta(microseconds=45)
    assert clockwords.describe(nz(2026, 10, 9, 17, 0), almost) == "Fri 9 Oct, 5:00 pm (2h ahead)"


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def loaded():
    registry.load()


@pytest.mark.parametrize(
    "typed, args",
    [("dev clock", []), ("dev clock 5:59am", ["5:59am"]), ("dev clock +2h", ["+2h"]), ("dev clock reset", ["reset"])],
)
def test_dev_clock_is_a_typed_word(typed, args):
    match = registry._keyword_router.match(typed)
    assert match.entry[1].name == "dev clock"
    assert match.args == args


def test_reset_db_is_its_own_exact_word():
    assert registry._keyword_router.match("dev reset-db").entry[1].name == "dev reset-db"
    assert registry._keyword_router.match("dev reset").entry[1].name == "dev reset"
    assert registry._keyword_router.match("dev reset-db").entry[1].destructive
    assert registry._keyword_router.match("dev reset-dv") is None, "never matched by a typo"


def context(*args):
    said = []

    async def say(text):
        said.append(text)

    return SimpleNamespace(args=list(args), reply=say, confirm=say, said=said)


def test_on_the_live_database_the_clock_is_refused_with_an_explanation():
    ctx = context("+2h")
    with pytest.raises(UserError, match=r"only works on the dev database.*python main\.py --dev"):
        asyncio.run(dev.dev_clock(ctx))
    assert not clock.is_shifted()
    assert ctx.said == []


def test_on_the_live_database_the_clock_can_still_be_read():
    ctx = context()
    asyncio.run(dev.dev_clock(ctx))
    assert "(the real time)" in ctx.said[0]
    assert "dev database" in ctx.said[0]


def test_on_the_dev_database_the_clock_moves_and_the_scheduler_is_woken(dev_clock, monkeypatch, dev_off):
    monkeypatch.setattr(dev, "DEV_DATABASE", True)
    woken = []
    monkeypatch.setattr(scheduler, "wake", lambda: woken.append(True))

    ctx = context("+2h")
    asyncio.run(dev.dev_clock(ctx))
    assert abs(clock.offset() - timedelta(hours=2)) < timedelta(seconds=1)
    assert woken == [True]
    assert "(2h ahead)" in ctx.said[0]

    asyncio.run(dev.dev_clock(context("reset")))
    assert not clock.is_shifted()


def test_on_the_live_database_reset_db_is_refused_before_anything_is_asked():
    with pytest.raises(UserError, match="live database is never wiped"):
        asyncio.run(tools.reset_db(context()))


def test_the_live_database_cannot_be_wiped_even_if_asked_directly(db):
    path = database.DB_PATH
    assert path.exists()
    with pytest.raises(RuntimeError):
        database.wipe_dev()
    assert path.exists()


def test_only_a_file_named_as_the_dev_database_is_wiped(db, monkeypatch, tmp_path):
    # --dev, but the path is not the dev database's: still refused
    monkeypatch.setattr(database, "DEV_DATABASE", True)
    with pytest.raises(RuntimeError):
        database.wipe_dev()
    assert database.DB_PATH.exists()

    dev_db = tmp_path / "dev.db"
    dev_db.write_text("x", encoding="utf-8")
    (tmp_path / "dev.db-wal").write_text("x", encoding="utf-8")
    monkeypatch.setattr(database, "DB_PATH", dev_db)
    database.wipe_dev()
    assert not dev_db.exists() and not (tmp_path / "dev.db-wal").exists()


# ---------------------------------------------------------------------------
# The panel and the status
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "dev_mode, dev_database, expected",
    [
        (False, False, None),
        (True, False, "🛠️ Dev mode"),
        (False, True, "🧪 DEV DATABASE"),
        (True, True, "🛠️ Dev mode · 🧪 DEV DATABASE"),
    ],
)
def test_the_status_says_dev_mode_and_dev_database(dev_mode, dev_database, expected):
    assert panel.status_text(dev_mode, dev_database) == expected


def test_the_panel_shows_the_clock_and_marks_the_dev_database(dev_off, monkeypatch):
    from core import devmode

    devmode.enable()
    live = panel.render()
    assert "Clock: **" in live and "(the real time)** · fixed on the live database" in live
    assert "DEV DATABASE" not in live

    monkeypatch.setattr(panel, "DEV_DATABASE", True)
    marked = panel.render()
    assert "🧪 **DEV DATABASE**" in marked
    assert "fixed on the live database" not in marked
