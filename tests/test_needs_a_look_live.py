"""Needs a look as it should read now (16 Oct): the nightly's count reset by a ship, a failure gone once dealt with,
pings that go with what they point at, real problems red and what is only worth knowing small, every change
redrawing the briefing at most every 30 seconds, and B bugs filed in live's folder only. Made-up data only."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core import alerts, attention, config, health, live, livelists, messages
from core.attention import PROBLEM, Item
from core.errors import UserError
from tasks import briefing
from tasks.briefing import rules as briefing_rules
from tests.test_alerts import BACKUP, box, said  # noqa: F401
from tests.test_pills_reminders import run, world  # noqa: F401


def night(when, failed):
    return {"date": when, "ran": "nightly, full", "failed": str(len(failed.split())), "failed_steps": failed, "note": ""}


SHIPPED = datetime(2026, 10, 16, 13, 58, tzinfo=config.TIMEZONE)


# --- the nightly: a ship resets the count; a failure dealt with leaves --------------------------------------------------
def test_two_failing_nights_before_a_ship_are_not_two_in_a_row_after_it():
    rows = [night("2026-10-15 03:00", "5.01c"), night("2026-10-16 03:30", "1.01b")]
    assert health.two_nights(rows) is not None, "with no ship between, two in a row"
    assert health.two_nights(rows, SHIPPED) is None, "the ship carried the fix: the count starts again"
    after = rows + [night("2026-10-17 03:30", "2.04"), night("2026-10-18 03:30", "2.04")]
    item = health.two_nights(after, SHIPPED)
    assert item is not None and item.once == "selftest:nights-from-2026-10-17", "two failing nights since the last fix"
    assert health.nights_failed(rows + [night("2026-10-17 03:30", "2.04")], SHIPPED) == ["2026-10-17"], "the first after it is night 1"


def test_a_nightly_failure_leaves_once_its_bug_is_closed_or_a_ship_came_after_it():
    failed = night("2026-10-16 03:30", "1.01b 5.01")
    assert health.selftest_problem(failed, {"1.01b": 3}, None, lambda number: True).bug == "D3"
    assert health.selftest_problem(failed, {"1.01b": 3}, None, lambda number: False) is None, "its bug closed: dealt with"
    assert health.selftest_problem(failed, {}, None) is not None, "no bug and no ship since: still shown"
    assert health.selftest_problem(failed, {}, SHIPPED) is None, "no bug, but a ship since: dealt with"


def test_the_last_ship_is_read_from_live_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert health.last_ship() is None
    (tmp_path / "live-versions.txt").write_text("aaa 2026-10-16 11:22 before moving to bbb\nbbb 2026-10-16 13:58 before moving to ccc\n", encoding="utf-8")
    assert health.last_ship() == SHIPPED


# --- pings are transient ----------------------------------------------------------------------------------------------
def test_a_ping_goes_at_the_next_morning_s_tidy_if_nothing_takes_it_down_first(box, monkeypatch):
    recorded = []

    async def record(message_id, channel_id, **kwargs):
        recorded.append((message_id, kwargs.get("lifetime")))

    monkeypatch.setattr(messages, "record", record)
    box.items.append(BACKUP)
    run(alerts.look())
    assert recorded == [(box.sent[0].id, messages.DAY)]
    box.items.clear()
    run(alerts.look())
    assert box.deleted == [box.sent[0].id], "what it points at is dealt with: it goes at once"


# --- severity: only real problems are red ---------------------------------------------------------------------------------
def test_what_is_only_worth_knowing_is_small_and_last_and_alone_is_one_small_line_in_the_overview():
    from core import design

    day = datetime(2026, 10, 16).date()
    shipped = Item("fix shipped, closing Mon", PROBLEM, bug="B5", quiet=True)
    info = (briefing_rules.info(shipped),)
    assert info == ("B5 · fix shipped, closing Mon",) and "⚠️" not in info[0]
    alone = briefing_rules.text([], day, (), info=info)
    assert briefing_rules.NEEDS not in alone and design.small("B5 · fix shipped, closing Mon") in alone, "no box, one small line"
    together = briefing_rules.text([], day, ("⚠️ N3 · nightly check failed, 20 steps",), info=info)
    lines = together.splitlines()
    at = lines.index(briefing_rules.NEEDS)
    assert lines[at + 1:at + 3] == ["⚠️ N3 · nightly check failed, 20 steps", design.small("B5 · fix shipped, closing Mon")], "the real one first, red; the other last and small"


def test_resolved_items_leave_the_briefing_at_once(box):
    box.items.append(BACKUP)
    assert briefing_rules.NEEDS in run(briefing.card_for(box.owner.id)).text
    box.items.clear()
    shown = run(briefing.card_for(box.owner.id))
    assert shown is None or briefing_rules.NEEDS not in shown.text


def test_an_informational_item_alone_makes_no_needs_a_look_box(box):
    box.items.append(Item("fix shipped, closing Mon", PROBLEM, bug="B5", quiet=True, ping=False))
    shown = run(briefing.card_for(box.owner.id))
    assert briefing_rules.NEEDS not in shown.text and "B5 · fix shipped, closing Mon" in shown.text


# --- every change redraws, at most once every 30 seconds -----------------------------------------------------------------
def test_each_kind_of_change_tells_the_briefing_to_look_again(monkeypatch):
    import inspect

    from core import nightly
    from tasks.bugs import filing, listing, plain

    told = []
    monkeypatch.setattr(attention, "changed", lambda: told.append(True))
    async def bug_changed():
        listing.changed(1)

    run(bug_changed())
    assert told, "a bug opened, closed, reopened or marked fix shipped: listing.changed tells the attention model"
    for path, words in ((filing.file_report, "listing.changed"), (plain._set, "listing.changed"), (plain.reopen_said, "listing.changed"),
                        (plain.shipped_round, "listing.changed"), (nightly._watch, "attention.changed")):
        assert words in inspect.getsource(path), path.__name__
    assert "summary_changed" in inspect.getsource(briefing.task.startup.__func__), "a restart redraws it"


def test_the_briefing_is_edited_at_most_once_every_30_seconds(monkeypatch):
    calls = []
    monkeypatch.setattr(livelists, "changed", lambda user_id, key, render, slow=False: calls.append((key, slow)))
    briefing.summary_changed("bugs", 1)
    assert calls and all(slow for _, slow in calls)
    assert live.SLOW_INTERVAL == 30.0
    assert live.wait_needed(100.0, 110.0, live.SLOW_INTERVAL) == 20.0


# --- B bugs: live's folder only ------------------------------------------------------------------------------------------
def test_a_b_bug_is_never_filed_outside_live_s_folder(monkeypatch):
    from tasks.bugs import posts, rules

    monkeypatch.setattr(rules, "DEV", False)
    monkeypatch.setattr(config, "LIVE_FOLDER", False)
    with pytest.raises(UserError, match="B bugs are filed on live only"):
        run(posts.create_post(1, SimpleNamespace()))
