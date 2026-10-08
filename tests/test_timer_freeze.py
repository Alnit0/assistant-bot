"""Pausing must freeze a clock and resuming must carry on from where it froze, at any
dev speed. Run against a real (temporary) database with the time under the test's control."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import devmode
from core.context import Context
from core.errors import UserError
from skills import registry
from skills.timers import board, control, sessions, status, store, timers

T0 = datetime(2026, 10, 7, 9, 53, 12, tzinfo=timezone.utc)
CHANNEL = 100


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Channel:
    id = CHANNEL

    def __init__(self):
        self.sent = []

    async def send(self, text, **options):
        self.sent.append(text)
        return SimpleNamespace(id=7000 + len(self.sent))


@pytest.fixture
def world(make_db, dev_off, owner, monkeypatch):
    make_db({"timers": store.MIGRATIONS})
    clock = Clock()
    for module in (timers, sessions, control):
        monkeypatch.setattr(module, "utc_now", clock)
    channel = Channel()

    def typed(*words) -> Context:
        message = SimpleNamespace(id=99, reference=None, author=SimpleNamespace(id=1))
        return Context(owner, CHANNEL, 99, " ".join(words), channel, args=list(words), _message=message)

    return SimpleNamespace(clock=clock, typed=typed, channel=channel, owner=owner)


def run(coroutine):
    return asyncio.run(coroutine)


def start_timer(world, *words) -> store.Timer:
    run(timers.start(world.typed(*words)))
    return run(store.active_timers(user_id=world.owner.id))[-1]


def saved(timer: store.Timer) -> store.Timer:
    return run(store.get_timer(timer.id))


def left(timer: store.Timer, clock: Clock) -> float:
    """Time left as the read tool reports it, in the timer's own seconds."""
    timer = saved(timer)
    if timer.status == store.PAUSED:
        return timer.remaining_s
    return (timer.ends_at - clock.now).total_seconds() * timer.speed


# --- at normal speed ---------------------------------------------------------
def test_a_paused_timer_freezes_and_resume_carries_on_from_there(world):
    dinner = start_timer(world, "5m", "dinner")
    world.clock.wait(129.9)  # 22:53:12 -> 22:55:21, as in the session that was reported
    assert run(timers.pause(saved(dinner))) == "⏸️ Paused: dinner (2m 50s left)"

    world.clock.wait(127)  # two minutes later it must say the same
    frozen = saved(dinner)
    assert frozen.status == store.PAUSED and frozen.ends_at is None and frozen.job_id is None
    assert frozen.remaining_s == pytest.approx(170.1)
    assert "paused with 2m 50s left" in status.timers_text([frozen], [], None, world.clock.now)

    run(timers.resume(frozen))
    running = saved(dinner)
    assert running.status == store.RUNNING and running.remaining_s is None
    assert (running.ends_at - world.clock.now).total_seconds() == pytest.approx(170.1)
    world.clock.wait(60)
    assert left(dinner, world.clock) == pytest.approx(110.1)


def test_pausing_twice_and_extending_while_paused_adds_up(world):
    tea = start_timer(world, "10m", "tea")
    world.clock.wait(100)
    run(timers.pause(saved(tea)))
    world.clock.wait(500)
    run(timers.extend(saved(tea), 60))
    assert saved(tea).remaining_s == pytest.approx(560)
    run(timers.resume(saved(tea)))
    world.clock.wait(60)
    run(timers.pause(saved(tea)))
    world.clock.wait(3600)
    assert left(tea, world.clock) == pytest.approx(500)


# --- with dev speed ----------------------------------------------------------
def test_at_dev_speed_a_pause_still_freezes_the_stated_time(world):
    devmode.enable()
    devmode.set_speed(60)
    eggs = start_timer(world, "5m", "eggs")
    world.clock.wait(2)  # two real seconds are two of the timer's minutes
    assert run(timers.pause(saved(eggs))) == "⏸️ Paused: eggs (3m left)"
    world.clock.wait(30)
    assert left(eggs, world.clock) == pytest.approx(180)
    run(timers.resume(saved(eggs)))
    assert (saved(eggs).ends_at - world.clock.now).total_seconds() == pytest.approx(3)


def test_a_timer_started_at_normal_speed_gains_nothing_when_dev_speed_is_switched_on(world):
    dinner = start_timer(world, "5m", "dinner")
    world.clock.wait(60)
    devmode.enable()
    devmode.set_speed(60)  # "for timers started from now": this one keeps its own clock
    assert left(dinner, world.clock) == pytest.approx(240)
    assert run(timers.pause(saved(dinner))) == "⏸️ Paused: dinner (4m left)"
    assert saved(dinner).remaining_s == pytest.approx(240)


def test_a_sped_up_timer_loses_nothing_when_dev_mode_goes_off(world):
    devmode.enable()
    devmode.set_speed(60)
    eggs = start_timer(world, "5m", "eggs")
    world.clock.wait(2)
    devmode.disable()
    assert left(eggs, world.clock) == pytest.approx(180)
    assert run(timers.pause(saved(eggs))) == "⏸️ Paused: eggs (3m left)"
    run(timers.resume(saved(eggs)))  # resumed at the speed in force now: normal
    assert (saved(eggs).ends_at - world.clock.now).total_seconds() == pytest.approx(180)


def test_extending_a_running_timer_uses_its_own_speed(world):
    devmode.enable()
    devmode.set_speed(60)
    eggs = start_timer(world, "5m", "eggs")
    devmode.disable()
    run(timers.extend(saved(eggs), 60))
    assert left(eggs, world.clock) == pytest.approx(360)


# --- a timer whose time is already up ----------------------------------------
def test_a_timer_that_has_run_out_is_finished_not_paused(world):
    tea = start_timer(world, "10s", "tea")
    world.clock.wait(12)  # its time is up, though the scheduler hasn't got to it yet
    with pytest.raises(UserError, match="already finished"):
        run(timers.pause(saved(tea)))
    over = saved(tea)
    assert over.status == store.FINISHED and over.remaining_s is None, "never paused with 0s left"


# --- the Pomodoro ------------------------------------------------------------
def start_session(world, *words) -> store.Session:
    run(sessions.start(world.typed(*words)))
    return run(store.active_sessions(user_id=world.owner.id))[0]


def test_a_paused_session_freezes_and_resume_carries_on_from_there(world):
    session = start_session(world, "25/5")
    world.clock.wait(152)
    run(sessions.pause(run(store.get_session(session.id))))
    world.clock.wait(600)
    frozen = run(store.get_session(session.id))
    assert frozen.state == store.PAUSED and frozen.remaining_s == pytest.approx(1348)
    assert "paused with 22m 28s left" in status.session_text(frozen, world.clock.now)
    run(sessions.resume(frozen))
    running = run(store.get_session(session.id))
    assert (running.ends_at - world.clock.now).total_seconds() == pytest.approx(1348)


def test_a_session_started_at_normal_speed_gains_nothing_under_dev_speed(world):
    session = start_session(world, "25/5")
    world.clock.wait(300)
    devmode.enable()
    devmode.set_speed(60)
    run(sessions.pause(run(store.get_session(session.id))))
    assert run(store.get_session(session.id)).remaining_s == pytest.approx(1200)


# --- what the control tool reports is what was saved ---------------------------
@pytest.fixture
def tool(world):
    registry.load()
    specs = {spec.name: spec for spec in registry.tools_for(world.owner, CHANNEL)}

    def call(name, **value):
        return run(registry.run_tool(world.typed("chat"), specs[name], value))

    return call


def test_the_control_tool_reports_the_state_that_was_saved(world, tool):
    tea = start_timer(world, "10m", "tea")
    world.clock.wait(39)
    paused = tool("timer_control", ids=f"t{tea.id}", action="pause", duration="", propose=False)
    assert paused.status == "ok"
    assert paused.text == f'⏸️ Paused: tea (9m 21s left)\nNow saved as: t{tea.id}: "tea" · paused with 9m 21s left'
    world.clock.wait(95)
    resumed = tool("timer_control", ids=f"t{tea.id}", action="resume", duration="", propose=False)
    assert resumed.text.endswith(f't{tea.id}: "tea" · running, 9m 21s left')
    assert saved(tea).status == store.RUNNING


def test_a_resume_that_was_not_saved_is_a_failure_not_a_success(world, tool, monkeypatch):
    tea = start_timer(world, "10m", "tea")
    run(timers.pause(saved(tea)))

    async def lost(timer):  # the write goes missing
        return None

    monkeypatch.setattr(store, "save_timer", lost)
    outcome = tool("timer_control", ids=f"t{tea.id}", action="resume", duration="", propose=False)
    assert outcome.status == "error" and "still paused" in outcome.text


# --- what happened is kept -----------------------------------------------------
def happened(world, timer=None) -> list[tuple[str, float | None, str]]:
    found = run(store.events(world.owner.id, *((store.TIMER, timer.id) if timer else ())))
    return [(event.event, None if event.remaining_s is None else round(event.remaining_s), event.detail) for event in found]


def test_every_change_to_a_timer_is_recorded_with_what_was_left(world):
    tea = start_timer(world, "10m", "tea")
    world.clock.wait(39)
    run(timers.pause(saved(tea)))
    world.clock.wait(95)
    run(timers.resume(saved(tea)))
    run(timers.extend(saved(tea), 300))
    world.clock.wait(60)
    run(timers.cancel(saved(tea)))
    assert happened(world, tea) == [
        ("started", 600, ""),
        ("paused", 561, ""),
        ("resumed", 561, ""),
        ("extended", 861, "+5m"),
        ("cancelled", 801, ""),
    ]


def test_finishing_and_dismissing_are_recorded(world):
    tea = start_timer(world, "10s", "tea")
    world.clock.wait(12)
    with pytest.raises(UserError):
        run(timers.pause(saved(tea)))
    run(timers.dismiss(saved(tea)))
    assert [name for name, *_ in happened(world, tea)] == ["started", "finished", "dismissed"]


def test_a_sessions_changes_are_recorded_with_the_phase(world):
    session = start_session(world, "25/5")
    world.clock.wait(152)
    run(sessions.pause(run(store.get_session(session.id))))
    run(sessions.resume(run(store.get_session(session.id))))
    run(sessions.skip(run(store.get_session(session.id))))
    run(sessions.stop(run(store.get_session(session.id))))
    found = run(store.events(world.owner.id, store.SESSION, session.id))
    assert [(event.event, event.detail) for event in found] == [
        ("started", "Focus, round 1"),
        ("paused", "Focus, round 1"),
        ("resumed", "Focus, round 1"),
        ("skipped", "Focus, round 1"),
        ("phase started", "Short break, round 1"),
        ("stopped", ""),
    ]
    assert round(found[1].remaining_s) == 1348


def test_claude_can_ask_what_happened(world, tool):
    tea = start_timer(world, "10m", "tea")
    world.clock.wait(39)
    run(timers.pause(saved(tea)))
    everything = tool("timer_history", id="").text.splitlines()
    assert everything[0] == "What happened, oldest first (times are local):"
    assert everything[1].endswith(f't{tea.id} "tea" · started · 10m left')
    assert everything[2].endswith(f't{tea.id} "tea" · paused · 9m 21s left')
    assert everything[-1] == status.ONLY_READ
    assert tool("timer_history", id=f"t{tea.id}").text.splitlines()[1:3] == everything[1:3]
    assert tool("timer_history", id="p9").text.splitlines()[0] == status.NO_EVENTS
    assert tool("timer_history", id="tea").status == "error"


# --- pause all / resume all ------------------------------------------------------
def test_pause_all_pauses_every_timer_and_the_pomodoro_and_says_which(world):
    tea = start_timer(world, "10m", "tea")
    dinner = start_timer(world, "5m", "dinner")
    eggs = start_timer(world, "10s", "eggs")
    session = start_session(world, "25/5")
    world.clock.wait(39)  # eggs has run out by now

    text = run(control.pause_all(world.typed()))
    assert text.splitlines() == [
        "⏸️ **Paused 3**",
        "• tea · 9m 21s left",
        "• dinner · 4m 21s left",
        "• 🍅 Pomodoro · Focus, round 1 · 24m 21s left",
        "Left alone: eggs (**eggs** has already finished, so there is nothing to pause.)",
    ]
    assert world.channel.sent[-1] == text, "said in the channel, word for word what was saved"
    assert [saved(timer).status for timer in (tea, dinner, eggs)] == [store.PAUSED, store.PAUSED, store.FINISHED]
    assert run(store.get_session(session.id)).state == store.PAUSED

    world.clock.wait(600)
    assert left(tea, world.clock) == pytest.approx(561) and left(dinner, world.clock) == pytest.approx(261)

    again = run(control.resume_all(world.typed()))
    assert again.splitlines() == [
        "▶️ **Resumed 3**",
        "• tea · 9m 21s left",
        "• dinner · 4m 21s left",
        "• 🍅 Pomodoro · Focus, round 1 · 24m 21s left",
    ]
    assert [saved(timer).status for timer in (tea, dinner)] == [store.RUNNING, store.RUNNING]
    assert run(store.get_session(session.id)).state == store.RUNNING


def test_the_pomodoro_can_be_left_out(world):
    start_timer(world, "10m", "tea")
    session = start_session(world, "25/5")
    text = run(control.pause_all(world.typed("timers", "except", "pomodoro")))
    assert text.splitlines() == ["⏸️ **Paused 1**", "• tea · 10m left", "The Pomodoro was left as it is."]
    assert run(store.get_session(session.id)).state == store.RUNNING


def test_pause_all_with_nothing_running_changes_nothing(world):
    tea = start_timer(world, "10m", "tea")
    run(timers.pause(saved(tea)))
    assert run(control.pause_all(world.typed())) == "⏸️ Nothing was running, so nothing was paused."
    assert saved(tea).remaining_s == pytest.approx(600), "an already paused timer is left exactly as it was"


@pytest.mark.parametrize(
    "words, ours, leaves_out",
    [
        ("", True, False),
        ("timers", True, False),  # "pause all timers" still means the Pomodoro too
        ("my timers", True, False),
        ("except pomodoro", True, True),
        ("timers only", True, True),
        ("but not the pomo", True, True),
        ("the lights", False, False),
        ("day long", False, False),
    ],
)
def test_what_may_follow_pause_all(words, ours, leaves_out):
    args = words.split()
    assert control.scope_is_ours(args) == ours
    if ours:
        assert control.leaves_out_pomodoro(args) == leaves_out


def test_pause_all_and_resume_all_are_typed_words_and_tools(world, tool):
    for typed, name in (("pause all timers", "pause all"), ("Resume all", "resume all"), ("unpause all", "resume all")):
        match = registry._keyword_router.match(typed)
        assert match.entry[1].name == name and match.entry[1].accepts(match.args)
        assert not match.entry[1].exact, "nothing is lost by pausing: it runs when asked"
    start_timer(world, "10m", "tea")
    outcome = tool("pause_all", scope="", propose=False)
    assert outcome.status == "ok" and outcome.text.splitlines() == ["⏸️ **Paused 1**", "• tea · 10m left"]


# --- the "Your timers" list is live ----------------------------------------------
def test_the_list_shows_a_paused_timer_as_paused_not_counting_down(world):
    tea = start_timer(world, "10m", "tea")
    dinner = start_timer(world, "5m", "dinner")
    world.clock.wait(39)
    run(timers.pause(saved(tea)))
    text = board.render_list([saved(tea), saved(dinner)], [])
    stamp = int(saved(dinner).ends_at.timestamp())
    assert text.splitlines() == [
        "📋 **Your timers**",
        "⏸️ tea · paused, 9m 21s left · <#100>",
        f"⏱️ dinner · ends <t:{stamp}:R> · <#100>",
        "-# Live: this updates whenever a timer changes",
    ]
    assert board.render_list([], []) == "📋 No active timers."


def test_there_is_one_list_per_channel_and_it_is_the_newest(world):
    from skills.timers import list_timers, skill

    start_timer(world, "10m", "tea")
    run(list_timers(world.typed()))
    first = run(store.lists(world.owner.id))
    run(list_timers(world.typed()))
    second = run(store.lists(world.owner.id))
    assert len(first) == len(second) == 1 and first[0][0] == second[0][0] == CHANNEL
    assert first[0][1] != second[0][1], "the new one replaces the old one"
    assert run(skill.message_class(second[0][1])).value == "Live"
    assert run(skill.message_class(first[0][1])) is None


def test_a_list_with_nothing_on_it_is_not_kept_live(world):
    from skills.timers import list_timers

    assert run(list_timers(world.typed())) == "no active timers"
    assert world.channel.sent[-1] == "📋 No active timers." and run(store.lists(world.owner.id)) == []


# --- several timers in one call: by ids, all of them, or all with a label ---------
def control_call(tool, **value):
    return tool("timer_control", **{"duration": "", "label": "", "propose": False, **value})


def statuses(world) -> dict[str, str]:
    def read(conn):
        return dict(conn.execute("SELECT label, status FROM timers_timers ORDER BY id").fetchall())

    from core import database

    return run(database.run(read))


def test_cancel_all_cancels_every_timer_in_one_call(world, tool):
    # 23:46:42 on 2026-10-07: "cancel all timers" took one call each, hit the cap of 5 and left D and E going
    for label in ("tea", "dinner", "C", "D", "E", "F", "G"):
        start_timer(world, "30m", label)
    outcome = control_call(tool, ids="all", action="cancel")
    assert outcome.status == "ok" and outcome.text.splitlines()[0] == "🚫 **Cancelled 7**"
    assert set(statuses(world).values()) == {store.CANCELLED}
    assert outcome.told == (outcome.text.split("\nNow saved as: ")[0],), "what the user is shown"


def test_all_timers_called_tea_acts_on_every_match_and_nothing_else(world, tool):
    # 23:46:24 on 2026-10-07: "stop all timers called tea" -> "I don't have a timer called tea running"
    for label in ("Tea", "tea 2", "dinner", "team"):
        start_timer(world, "30m", label)
    outcome = control_call(tool, ids="all", action="stop", label="tea")
    assert outcome.status == "ok", outcome.text
    assert outcome.text.splitlines()[:3] == ["🚫 **Cancelled 2**", "• Tea", "• tea 2"]
    assert statuses(world) == {
        "Tea": store.CANCELLED, "tea 2": store.CANCELLED, "dinner": store.RUNNING, "team": store.RUNNING,
    }


def test_stop_is_cancel(world, tool):
    tea = start_timer(world, "10m", "tea")
    outcome = control_call(tool, ids=f"t{tea.id}", action="stop")
    assert outcome.text.splitlines()[0] == "🚫 Cancelled: tea" and saved(tea).status == store.CANCELLED


def test_several_ids_in_one_call(world, tool):
    tea, dinner, eggs = (start_timer(world, "10m", label) for label in ("tea", "dinner", "eggs"))
    world.clock.wait(60)
    outcome = control_call(tool, ids=f"t{tea.id} t{eggs.id}", action="pause")
    assert outcome.text.splitlines()[:3] == ["⏸️ **Paused 2**", "• tea · 9m left", "• eggs · 9m left"]
    assert (saved(tea).status, saved(dinner).status, saved(eggs).status) == (store.PAUSED, store.RUNNING, store.PAUSED)


def test_pause_all_is_about_the_running_ones_and_resume_all_the_paused(world, tool):
    tea, dinner = start_timer(world, "10m", "tea"), start_timer(world, "10m", "dinner")
    run(timers.pause(saved(tea)))
    assert control_call(tool, ids="all", action="pause").text.splitlines()[0] == "⏸️ Paused: dinner (10m left)"
    again = control_call(tool, ids="all", action="pause")
    assert again.status == "error" and "None of them is running" in again.text
    resumed = control_call(tool, ids="all", action="resume")
    assert resumed.text.splitlines()[0] == "▶️ **Resumed 2**"
    assert (saved(tea).status, saved(dinner).status) == (store.RUNNING, store.RUNNING)


def test_one_that_cannot_be_changed_is_named_and_the_rest_still_are(world, tool):
    tea, dinner = start_timer(world, "10m", "tea"), start_timer(world, "10m", "dinner")
    run(timers.pause(saved(tea)))
    outcome = control_call(tool, ids=f"t{tea.id} t{dinner.id}", action="pause")
    lines = outcome.text.splitlines()
    assert outcome.status == "ok" and lines[0] == "⏸️ **Paused 1**" and lines[1].startswith("• dinner")
    assert lines[2].startswith("Left alone: tea (") and "isn't running" in lines[2]


def test_a_label_nothing_has_or_an_id_that_is_not_there_is_explained(world, tool):
    start_timer(world, "10m", "tea")
    nobody = control_call(tool, ids="all", action="cancel", label="coffee")
    assert nobody.status == "error" and 'No timer going is called "coffee"' in nobody.text and '"tea"' in nobody.text
    missing = control_call(tool, ids="t1 t99", action="cancel")
    assert missing.status == "error" and "`t99`" in missing.text
    assert statuses(world) == {"tea": store.RUNNING}, "nothing is done when part of the request is wrong"


def test_the_pomodoro_can_be_named_as_the_current_one(world, tool):
    run(sessions.start(world.typed()))
    paused = tool("pomodoro_control", id="current", action="pause", duration="", propose=False)
    assert paused.status == "ok", paused.text
    assert run(store.active_sessions(user_id=world.owner.id))[0].state == store.PAUSED
    assert paused.told and paused.told[0].startswith("⏸️")


def test_the_live_state_is_complete_and_current(world):
    for label in ("tea", "tea", "Tea 2", "dinner"):
        start_timer(world, "10m", label)
    tea = run(store.active_timers(user_id=world.owner.id))[0]
    world.clock.wait(60)
    run(timers.pause(saved(tea)))
    world.clock.wait(60)
    lines = run(control.live_state(world.typed("stop all timers called tea"))).splitlines()
    assert lines[1:5] == [
        't1: "tea" · paused with 9m left · <#100> (this channel)',
        't2: "tea" · running, 8m left · <#100> (this channel)',
        't3: "Tea 2" · running, 8m left · <#100> (this channel)',
        't4: "dinner" · running, 8m left · <#100> (this channel)',
    ]
    run(timers.cancel(saved(tea)))
    after = run(control.live_state(world.typed("and now?")))
    assert 't1: "tea" · cancelled' in after and 't1: "tea" · paused' not in after
