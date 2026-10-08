from datetime import datetime, timezone

import pytest

from tasks.timers import board, store
from tasks.timers.pomodoro import FOCUS, SHORT_BREAK, starts_by_itself
from tasks.timers.timers import render_timer

ENDS = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
STAMP = int(ENDS.timestamp())


def timer(**changes) -> store.Timer:
    values = dict(user_id=1, discord_user_id=1, channel_id=100, label="Tea", duration_s=300, ends_at=ENDS)
    return store.Timer(**{**values, **changes})


def session(**changes) -> store.Session:
    values = dict(
        user_id=1, discord_user_id=1, channel_id=100, label="Writing", focus_s=1500, short_s=300,
        long_s=900, rounds=4, auto_continue=False, phase=FOCUS, ends_at=ENDS,
    )
    return store.Session(**{**values, **changes})


# --- a timer's own message ---------------------------------------------------
def test_a_running_timer_shows_a_live_end_time_and_what_to_reply():
    text = render_timer(timer())
    assert text.splitlines()[0] == f"⏱️ **Tea** · 5m · ends <t:{STAMP}:R> (<t:{STAMP}:t>)"
    assert "`cancel`, `pause` or `+10m`" in text


def test_a_paused_timer_shows_what_is_left_and_offers_resume():
    text = render_timer(timer(status=store.PAUSED, ends_at=None, remaining_s=90))
    assert text.splitlines()[0] == "⏸️ **Tea** · paused with 1m 30s left"
    assert "`resume`" in text


@pytest.mark.parametrize(
    "status, expected",
    [
        (store.CANCELLED, "🚫 **Tea** · 5m · cancelled"),
        (store.FINISHED, "✅ **Tea** · 5m · finished"),
        (store.DISMISSED, "✅ **Tea** · 5m · finished"),
    ],
)
def test_an_ended_timer_is_one_plain_line(status, expected):
    assert render_timer(timer(status=status)) == expected


def test_only_running_and_paused_timers_are_active():
    assert timer().active and timer(status=store.PAUSED).active
    for status in (store.FINISHED, store.CANCELLED, store.DISMISSED):
        assert not timer(status=status).active


# --- the board ---------------------------------------------------------------
def test_an_empty_board_says_so():
    assert board.render_board([], []) == "📋 **Active timers**\nNo active timers"


def test_the_board_lists_sessions_before_timers():
    text = board.render_board([timer()], [session()])
    assert text.splitlines() == [
        "📋 **Active timers**",
        f"🍅 Writing · Focus · round 1 of 4 · ends <t:{STAMP}:R>",
        f"⏱️ Tea · ends <t:{STAMP}:R>",
    ]


def test_board_lines_for_paused_things():
    assert board.timer_line(timer(status=store.PAUSED, remaining_s=45)) == "⏸️ Tea · paused, 45s left"
    paused = session(state=store.PAUSED, remaining_s=600, phase=SHORT_BREAK, round=2)
    assert board.session_line(paused) == "⏸️ Writing · Short break · round 2 of 4 · paused, 10m left"


def test_a_session_waiting_for_start_names_the_phase_and_its_length():
    waiting = session(state=store.WAITING, ends_at=None, phase=SHORT_BREAK)
    assert board.session_line(waiting) == "🍅 Writing · Short break (5m) is next · waiting for Start"


def test_stamps_are_discord_timestamps():
    assert board.stamp(ENDS) == f"<t:{STAMP}:R>"
    assert board.stamp(ENDS, "t") == f"<t:{STAMP}:t>"


# --- whether the next Pomodoro phase starts by itself -------------------------
@pytest.mark.parametrize(
    "auto_continue, is_late, expected",
    [
        (True, False, True),
        (False, False, False),  # the default: wait for Start
        (True, True, False),  # after downtime it always waits
        (False, True, False),
    ],
)
def test_next_phase_only_starts_itself_in_auto_mode_and_on_time(auto_continue, is_late, expected):
    assert starts_by_itself(auto_continue, is_late) is expected
