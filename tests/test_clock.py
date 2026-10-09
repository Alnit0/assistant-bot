"""The bot's clock (core/clock.py): the real time, moved ahead only on the dev database."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from core import clock, config
from core.errors import UserError

HOUR = timedelta(hours=1)


def close(a: datetime, b: datetime) -> bool:
    return abs((a - b).total_seconds()) < 1


def test_it_is_the_real_time_unless_moved():
    assert close(clock.now(), datetime.now(timezone.utc))
    assert not clock.is_shifted()
    assert clock.offset() == timedelta(0)


def test_it_cannot_be_moved_on_the_live_database():
    assert not clock.shiftable(), "the tests run without --dev, like the live bot"
    with pytest.raises(UserError, match="dev database"):
        clock.advance(HOUR)
    assert not clock.is_shifted()


def test_moved_ahead_it_goes_on_ticking_from_there(dev_clock):
    landed = clock.advance(2 * HOUR)
    assert close(landed, clock.real_now() + 2 * HOUR)
    assert close(clock.now(), clock.real_now() + 2 * HOUR)
    assert close(config.now_nz(), clock.now()), "now_nz follows the clock"
    assert close(config.real_now_nz(), clock.real_now()), "real_now_nz never does"


def test_moves_add_up(dev_clock):
    clock.advance(HOUR)
    clock.advance_to(clock.now() + 3 * HOUR)
    assert abs(clock.offset() - 4 * HOUR) < timedelta(seconds=1)


@pytest.mark.parametrize("by", [timedelta(0), -HOUR])
def test_it_only_moves_forward(dev_clock, by):
    clock.advance(HOUR)
    with pytest.raises(UserError, match="only moves forward"):
        clock.advance(by)
    with pytest.raises(UserError, match="only moves forward"):
        clock.advance_to(clock.now() - HOUR)
    assert clock.offset() == HOUR


def test_reset_is_the_one_way_back(dev_clock):
    clock.advance(5 * HOUR)
    clock.reset()
    assert not clock.is_shifted()
    assert close(clock.now(), clock.real_now())


def test_the_offset_survives_a_restart(tmp_path):
    store = tmp_path / "dev-clock.json"
    try:
        clock.configure(shiftable=True, store=store)
        clock.advance(90 * timedelta(minutes=1))
        assert json.loads(store.read_text(encoding="utf-8")) == {"offset_seconds": 5400.0}

        clock.configure(shiftable=True, store=store)  # the next start
        assert clock.offset() == timedelta(minutes=90)

        clock.reset()
        assert not store.exists(), "back at the real time there is nothing to keep"
    finally:
        clock.configure(shiftable=False)


def test_the_live_bot_never_picks_up_a_stored_offset(tmp_path):
    store = tmp_path / "dev-clock.json"
    store.write_text(json.dumps({"offset_seconds": 3600}), encoding="utf-8")
    clock.configure(shiftable=False, store=store)
    try:
        assert not clock.is_shifted()
    finally:
        clock.configure(shiftable=False)


@pytest.mark.parametrize("content", ["", "not json", "{}", '{"offset_seconds": "soon"}', '{"offset_seconds": -60}'])
def test_an_unreadable_or_backwards_offset_is_ignored(tmp_path, content):
    store = tmp_path / "dev-clock.json"
    store.write_text(content, encoding="utf-8")
    try:
        clock.configure(shiftable=True, store=store)
        assert not clock.is_shifted()
    finally:
        clock.configure(shiftable=False)


def test_time_jumped_over_is_counted(dev_clock):
    before = clock.now()
    clock.advance(2 * HOUR)
    after = clock.now()
    # All of the jump lies between a moment before it and one after
    assert clock.skipped_between(before - HOUR, after + HOUR) == pytest.approx(7200, abs=1)
    # Only the part of it after a moment inside the jump
    assert clock.skipped_between(before + HOUR, after) == pytest.approx(3600, abs=1)
    # None of it before the jump began, or after it landed
    assert clock.skipped_between(before - 2 * HOUR, before - HOUR) == 0
    assert clock.skipped_between(after + timedelta(seconds=5), after + HOUR) == 0
    clock.reset()
    assert clock.skipped_between(before - HOUR, after + HOUR) == 0
