"""The live state of timers and the Pomodoro, as Claude is told it, and the ids it acts by."""
from datetime import datetime, timedelta, timezone

import pytest

from skills.timers import status, store
from skills.timers.pomodoro import FOCUS, SHORT_BREAK, Plan, different_lengths, parse_session

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
HERE, THERE = 100, 200


def timer(timer_id=12, **changes) -> store.Timer:
    values = dict(
        user_id=1, discord_user_id=1, channel_id=HERE, label="tea", duration_s=300,
        ends_at=NOW + timedelta(seconds=80), message_id=500 + timer_id, id=timer_id,
    )
    return store.Timer(**{**values, **changes})


def session(**changes) -> store.Session:
    values = dict(
        user_id=1, discord_user_id=1, channel_id=HERE, label="writing", focus_s=3000, short_s=600,
        long_s=1800, rounds=4, auto_continue=False, phase=FOCUS, round=3,
        ends_at=NOW + timedelta(minutes=38), id=4,
    )
    return store.Session(**{**values, **changes})


# --- ids ---------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [("t12", 12), ("T12", 12), (" 12 ", 12), ("#12", 12), ("p4", None), ("tea", None), ("", None)])
def test_a_timer_id_is_read_back_from_what_claude_sends(text, expected):
    assert status.parse_ref(text, status.TIMER) == expected


def test_a_session_id_is_not_a_timer_id():
    assert status.parse_ref("p4", status.SESSION) == 4
    assert status.parse_ref("t4", status.SESSION) is None


# --- list_timers -------------------------------------------------------------
def test_each_timer_has_its_id_label_state_time_left_and_channel():
    paused = timer(3, status=store.PAUSED, ends_at=None, remaining_s=604, channel_id=THERE)
    text = status.timers_text([paused, timer()], [], None, NOW, here=HERE)
    assert text.splitlines() == [
        "Timers going now. Use the id with timer_control:",
        't3: "tea" · paused with 10m 4s left · <#200>',
        't12: "tea" · running, 1m 20s left · <#100> (this channel)',
    ]


def test_no_timers_says_so():
    assert status.timers_text([], [], None, NOW) == status.NO_TIMERS


def test_a_timer_that_ended_lately_is_told_apart_from_one_that_never_was():
    finished = timer(10, status=store.DISMISSED, ends_at=NOW - timedelta(minutes=4), duration_s=150)
    waiting = timer(9, status=store.FINISHED, ends_at=NOW - timedelta(hours=2), duration_s=60)
    cancelled = timer(8, status=store.CANCELLED)
    lines = status.timers_text([], [finished, waiting, cancelled], None, NOW).splitlines()
    assert lines == [
        status.NO_TIMERS,
        "Ended in the last day (nothing more can be done to these):",
        't10: "tea" · finished 4m ago · was 2m 30s',
        't9: "tea" · finished 2h ago, its alert not dismissed yet · was 1m',
        't8: "tea" · cancelled · was 5m',
    ]


def test_the_timer_the_user_replied_to_is_pointed_out():
    text = status.timers_text([timer(12), timer(13, label="eggs")], [], None, NOW, replied_to=512)
    first, second = text.splitlines()[1:]
    assert first.endswith("the user replied to this one") and "replied" not in second


def test_a_sped_up_clock_is_reported_in_the_timers_own_time():
    text = status.timers_text([timer(speed=60)], [], None, NOW)  # 80 real seconds to go, at 60x
    assert "running, 1h 20m left" in text
    assert "running, 1h left" in status.session_text(session(speed=60, ends_at=NOW + timedelta(minutes=1)), NOW)


def test_the_timer_list_mentions_a_session_without_describing_it():
    text = status.timers_text([], [], session(), NOW)
    assert text.splitlines()[-1] == 'Pomodoro: p4 "writing" is going; get_pomodoro_status has the details.'


# --- get_pomodoro_status -----------------------------------------------------
def test_a_running_session_gives_phase_round_time_left_and_lengths():
    assert status.session_text(session(), NOW, here=HERE) == (
        'p4: "writing" · Focus, round 3 of 4 · running, 38m left in this phase · '
        "lengths 50m/10m/30m (focus/break/long break) · each phase waits for Start · <#100> (this channel)"
    )


def test_a_session_waiting_for_start_says_nothing_is_counting_down():
    text = status.session_text(session(state=store.WAITING, phase=SHORT_BREAK, ends_at=None), NOW)
    assert "waiting for Start: Short break (10m) is next and nothing is counting down" in text


def test_a_paused_session_gives_what_is_left():
    text = status.session_text(session(state=store.PAUSED, ends_at=None, remaining_s=754, auto_continue=True), NOW)
    assert "paused with 12m 34s left in this phase" in text and "phases start by themselves" in text


def test_no_session_says_so():
    assert status.session_text(None, NOW) == status.NO_SESSION


# --- asking for a session while one is going ---------------------------------
GOING = Plan(50 * 60, 10 * 60, 30 * 60)


@pytest.mark.parametrize(
    "typed, asked",
    [
        ("25/5", "25/5"),
        ("50/10", None),  # the same: the long break wasn't mentioned, so it isn't compared
        ("50/10/30", None),
        ("50/10/20", "50/10/20"),
        ("", None),
        ("writing", None),
        ("auto 25/5 deep work", "25/5"),
    ],
)
def test_other_lengths_than_the_session_has_are_noticed(typed, asked):
    words = typed.split()
    parse_session(words)  # what the handler has already done: they are readable
    assert different_lengths(words, GOING) == asked


# --- what happened ------------------------------------------------------------
NZ = timezone(timedelta(hours=13))


def event(name, remaining=None, detail="", minutes=0, kind=store.TIMER, record_id=3, label="tea") -> store.Event:
    return store.Event(kind, record_id, label, name, remaining, detail, NOW + timedelta(minutes=minutes))


def test_events_are_listed_with_the_local_time_and_what_was_left():
    text = status.events_text(
        [
            event(store.RESUMED, 604),
            event(store.WAS_PAUSED, 561.2, minutes=1),
            event(store.EXTENDED, 1161, "+10m", minutes=2),
            event(store.WAS_FINISHED, 0, minutes=30),
            event(store.WAS_PAUSED, 1348, "Focus, round 1", minutes=31, kind=store.SESSION, record_id=5, label="Pomodoro"),
        ],
        NZ,
    )
    assert text.splitlines() == [
        "What happened, oldest first (times are local):",
        'Thu 01:00:00 · t3 "tea" · resumed · 10m 4s left',
        'Thu 01:01:00 · t3 "tea" · paused · 9m 21s left',
        'Thu 01:02:00 · t3 "tea" · extended (+10m) · 19m 21s left',
        'Thu 01:30:00 · t3 "tea" · finished',
        'Thu 01:31:00 · p5 "Pomodoro" · paused (Focus, round 1) · 22m 28s left',
    ]


def test_no_events_says_the_record_is_new():
    assert status.events_text([], NZ) == status.NO_EVENTS


# --- pause all / resume all: exactly what was done -----------------------------
def test_pause_all_names_each_one_with_the_time_left():
    text = status.bulk_text(
        True,
        [status.bulk_line("tea", 561), status.bulk_line("🍅 Pomodoro", 1348, "Focus, round 1")],
        ["eggs (**eggs** has already finished, so there is nothing to pause.)"],
    )
    assert text.splitlines() == [
        "⏸️ **Paused 2**",
        "• tea · 9m 21s left",
        "• 🍅 Pomodoro · Focus, round 1 · 22m 28s left",
        "Left alone: eggs (**eggs** has already finished, so there is nothing to pause.)",
    ]


def test_nothing_to_pause_or_resume_says_so():
    assert status.bulk_text(True, [], []) == "⏸️ Nothing was running, so nothing was paused."
    assert status.bulk_text(False, [], [], "The Pomodoro was left as it is.").splitlines() == [
        "▶️ Nothing was paused, so nothing was resumed.",
        "The Pomodoro was left as it is.",
    ]
