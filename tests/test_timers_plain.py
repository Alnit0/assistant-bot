"""Timers and the Pomodoro in plain words (tasks/timers/plain.py): what each action does
with what extraction filled in, and every word it says. Against a temporary database."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import actions, conversation
from core.actions import Request, Shown
from core.errors import UserError
from core.extraction import Extracted
from tasks import registry
from tasks.timers import control, plain, sessions, status, store, timers

T0 = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)
CHANNEL = 100


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
    now = [T0]
    for module in (timers, sessions, control, plain, store):
        monkeypatch.setattr(module, "utc_now", lambda: now[0])
    channel = Channel()
    monkeypatch.setattr(plain, "channel_for", lambda channel_id: channel)
    deleted = []

    async def delete(channel_id, message_id, message_class=None):
        deleted.append(message_id)

    monkeypatch.setattr(plain, "delete_message", delete)

    def wait(seconds):
        now[0] += timedelta(seconds=seconds)

    return SimpleNamespace(channel=channel, owner=owner, request=Request(owner, CHANNEL, "said"), wait=wait, deleted=deleted)


def run(coroutine):
    return asyncio.run(coroutine)


def going(world):
    return run(store.active_timers(user_id=world.owner.id))


def start(world, *things, guessed=()):
    data = {"timers": [{"duration": thing} if isinstance(thing, str) else {"duration": thing[0], "label": thing[1]} for thing in things]}
    return run(plain.start(world.request, data, frozenset(guessed)))


def change(world, which, action, guessed=(), **more):
    return run(plain.change(world.request, {"which": which, "action": action, **more}, frozenset(guessed)))


def ref(timer):
    return status.ref(status.TIMER, timer.id)


# --- the contract ---------------------------------------------------------------------
def test_the_timers_task_meets_the_contract_and_is_one_entry():
    registry.load()
    entry = actions.entry("timers")
    assert entry is not None and (entry.icon, entry.title) == ("⏱️", "Timers")
    assert "Not pills" in entry.only_for and len(entry.examples) == 3
    assert [action.name for action in entry.actions] == [
        "timer_start", "timer_change", "timer_all", "timer_list", "timer_history",
        "pomo_start", "pomo_change", "pomo_status", "pomo_stats",
    ]
    assert actions.problems([entry]) == []
    assert registry.problems() == []


def test_only_cancelling_several_asks_first():
    change_action = next(action for action in plain.ACTIONS if action.name == "timer_change")
    assert change_action.card_if is plain.cancels_several and change_action.run is plain.change
    assert all(action.card_if is None and not action.needs_card for action in plain.ACTIONS if action.name != "timer_change")


def test_an_action_that_sometimes_needs_a_card_needs_all_three_halves():
    whole = next(action for action in plain.ACTIONS if action.name == "timer_change")
    broken = actions.Action("x_change", "Change x.", card_if=plain.cancels_several, run=plain.change)
    entry = actions.Entry("things", "📦", "Only for things.", ("a", "b"), (broken,))
    assert actions.problems([entry]) == ["things: action x_change needs a card only sometimes (`card_if`), so it needs `prepare`, `apply` and `run`"]
    assert actions.problems([actions.Entry("things", "📦", "Only for things.", ("a", "b"), (whole,))]) == []


# --- starting ----------------------------------------------------------------------------
def test_a_timer_starts_with_its_own_message_and_nothing_more_is_said(world):
    result = start(world, ("5m", "tea"))
    (timer,) = going(world)
    assert (timer.label, timer.duration_s, timer.channel_id, timer.message_id) == ("tea", 300, CHANNEL, 7001)
    assert "tea" in world.channel.sent[0] and len(world.channel.sent) == 1
    assert result == Shown("started 1 timer(s): tea 5m", "")


def test_several_timers_in_one_message_all_start(world):
    result = start(world, *[("1m", name) for name in "abcdef"])
    assert [timer.label for timer in going(world)] == list("abcdef")
    assert result.summary == "started 6 timer(s): a 1m, b 1m, c 1m, d 1m, e 1m, f 1m" and result.also == ""


def test_a_guessed_length_is_pointed_out_with_a_question_mark(world):
    result = start(world, ("5m", "tea"), "10m", guessed=["timers[0].duration"])
    assert result.also == "❓ I guessed the length: **tea** · 5m. Tell me if it should be something else."


def test_a_length_that_is_too_long_is_refused_in_the_tasks_words(world):
    with pytest.raises(UserError, match=r"No timer started: 72h \(The longest timer is 24 hours\.\)"):
        start(world, "72h")
    assert going(world) == []


def test_what_could_not_start_is_said_and_the_rest_still_start(world):
    result = start(world, ("5m", "tea"), ("72h", "roast"))
    assert [timer.label for timer in going(world)] == ["tea"]
    assert result.also == "⚠️ Not started: roast (The longest timer is 24 hours.)"


def test_past_the_limit_the_extra_ones_are_named(world, monkeypatch):
    monkeypatch.setattr(timers, "MAX_ACTIVE", 2)
    result = start(world, ("1m", "a"), ("1m", "b"), ("1m", "c"))
    assert [timer.label for timer in going(world)] == ["a", "b"]
    assert result.also == "⚠️ Not started: c (You already have 2 timers running. Cancel one first.)"


# --- changing one ---------------------------------------------------------------------------
def test_one_timer_is_paused_resumed_extended_and_cancelled_at_once(world):
    start(world, ("5m", "tea"))
    (tea,) = going(world)
    world.wait(60)
    assert "tea" in change(world, ref(tea), "pause") and going(world)[0].status == store.PAUSED
    assert going(world)[0].remaining_s == pytest.approx(240)
    change(world, ref(tea), "resume")
    assert going(world)[0].status == store.RUNNING
    change(world, ref(tea), "extend", duration="5m")
    assert going(world)[0].left(T0 + timedelta(seconds=60)) == pytest.approx(540)
    said = change(world, ref(tea), "cancel")
    assert going(world) == [] and "tea" in said


def test_a_guess_at_which_timer_is_flagged_after_what_was_done(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, _ = going(world)
    said = change(world, ref(tea), "pause", guessed=["which"])
    assert said.splitlines()[-1] == "❓ I wasn't sure which timer you meant. Tell me if it was another one."
    assert [timer.status for timer in going(world)] == [store.PAUSED, store.RUNNING]


def test_a_timer_that_is_not_there_is_said_in_words_the_user_can_act_on(world):
    with pytest.raises(UserError, match="No timers are running or paused"):
        change(world, "all", "pause")
    with pytest.raises(UserError, match="There is no timer `t99`"):
        change(world, "t99", "pause")


def test_several_can_be_paused_at_once_without_a_card(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, dinner = going(world)
    data = {"which": f"{ref(tea)} {ref(dinner)}", "action": "pause"}
    assert run(plain.cancels_several(world.request, data)) is False, "a pause is not a stop"
    said = run(plain.change(world.request, data, frozenset()))
    assert said.splitlines() == ["⏸️ **Paused 2**", "• tea · 5m left", "• dinner · 9m left"]


# --- a bulk stop asks first ---------------------------------------------------------------------
def test_cancelling_one_acts_at_once_and_cancelling_several_asks(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, dinner = going(world)
    assert run(plain.cancels_several(world.request, {"which": ref(tea), "action": "cancel"})) is False
    assert run(plain.cancels_several(world.request, {"which": "all", "action": "cancel"})) is True
    assert run(plain.cancels_several(world.request, {"which": f"{ref(tea)} {ref(dinner)}", "action": "cancel"})) is True
    assert run(plain.cancels_several(world.request, {"which": "t99", "action": "cancel"})) is False, "the reply says it isn't there"


def test_the_card_names_each_timer_and_confirm_cancels_exactly_those(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, dinner = going(world)
    proposal = run(plain.cancel_card(world.request, {"which": "all", "action": "cancel"}, frozenset()))
    assert proposal.lines == ("**tea** · running, 5m left", "**dinner** · running, 9m left")
    assert (proposal.kind, proposal.destructive, proposal.confirm_label) == ("cancel", True, "Cancel 2 timers")
    assert proposal.warnings == ("This cancels 2 timers and can't be undone",)
    assert proposal.data == {"ids": [tea.id, dinner.id]}
    assert len(going(world)) == 2, "nothing until it is confirmed"

    start(world, ("1m", "eggs"))  # started after the card: not on it, so not cancelled
    said = run(plain.cancel_saved(world.request, proposal.data))
    assert said.splitlines() == ["🚫 **Cancelled 2**", "• tea", "• dinner"]
    assert [timer.label for timer in going(world)] == ["eggs"]


def test_a_timer_that_ended_before_confirm_is_counted_not_failed(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, dinner = going(world)
    run(timers.cancel(tea))
    said = run(plain.cancel_saved(world.request, {"ids": [tea.id, dinner.id]}))
    assert said.splitlines() == ["🚫 **Cancelled 1**", "• dinner", "Left alone: 1 had already ended"]
    with pytest.raises(UserError, match="None of those timers is still going"):
        run(plain.cancel_saved(world.request, {"ids": [tea.id, dinner.id]}))


def test_the_conversation_asks_with_a_card_only_when_the_action_says_so(world, monkeypatch):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, _ = going(world)
    shown, said = [], []

    async def show(request, entry, action_name, proposal, guessed, replaces=None, **options):
        shown.append((action_name, proposal))

    async def send(channel_id, card):
        said.append(card.text)
        return 1

    monkeypatch.setattr(conversation.confirm, "show", show)
    monkeypatch.setattr(conversation.cards, "send", send)
    registry.load()
    entry = actions.entry("timers")
    action = entry.action("timer_change")

    turn = conversation.Turn()
    run(conversation.act(world.request, Extracted(entry, action, {"which": "all", "action": "cancel"}, frozenset()), turn))
    assert [name for name, _ in shown] == ["timer_change"] and said == [] and len(going(world)) == 2
    assert turn.said == ["card: timers · cancel: **tea** · running, 5m left / **dinner** · running, 9m left / ⚠️ This cancels 2 timers and can't be undone"]

    turn = conversation.Turn()
    run(conversation.act(world.request, Extracted(entry, action, {"which": ref(tea), "action": "cancel"}, frozenset()), turn))
    assert len(shown) == 1 and len(said) == 1 and "tea" in said[0], "one timer: done at once, and said"
    assert [timer.label for timer in going(world)] == ["dinner"]


def test_a_timer_that_starts_itself_is_logged_and_only_its_extras_are_said(world, monkeypatch):
    said = []

    async def send(channel_id, card):
        said.append(card.text)
        return 1

    monkeypatch.setattr(conversation.cards, "send", send)
    registry.load()
    entry = actions.entry("timers")
    turn = conversation.Turn()
    found = Extracted(entry, entry.action("timer_start"), {"timers": [{"duration": "5m", "label": "tea"}]}, frozenset({"timers[0].duration"}))
    run(conversation.act(world.request, found, turn))
    assert len(world.channel.sent) == 1, "the timer's own message"
    assert said == ["❓ I guessed the length: **tea** · 5m. Tell me if it should be something else."]
    assert turn.said[0] == "started 1 timer(s): tea 5m"


# --- everything at once -----------------------------------------------------------------------------
def test_pause_everything_takes_the_pomodoro_too_unless_told_to_leave_it(world):
    start(world, ("5m", "tea"))
    run(plain.pomo_start(world.request, {"label": "writing"}, frozenset()))
    said = run(plain.change_all(world.request, {"action": "pause", "leave_pomodoro": True}, frozenset()))
    assert said.splitlines()[:2] == ["⏸️ **Paused 1**", "• tea · 5m left"] and "The Pomodoro was left as it is." in said
    said = run(plain.change_all(world.request, {"action": "resume"}, frozenset()))
    assert said.splitlines()[0] == "▶️ **Resumed 1**"
    said = run(plain.change_all(world.request, {"action": "pause"}, frozenset()))
    assert said.splitlines()[0] == "⏸️ **Paused 2**" and "🍅 writing" in said


# --- showing and asking ----------------------------------------------------------------------------------
def test_the_list_is_the_live_one_and_a_new_copy_takes_the_old_ones_place(world):
    start(world, ("5m", "tea"))
    first = run(plain.show_list(world.request, {}, frozenset()))
    assert first == Shown("listed 1 timer(s), 0 pomodoro") and "tea" in world.channel.sent[-1]
    assert dict(run(store.lists(world.owner.id)))[CHANNEL] == 7002
    run(plain.show_list(world.request, {}, frozenset()))
    assert world.deleted == [7002] and dict(run(store.lists(world.owner.id)))[CHANNEL] == 7003


def test_with_nothing_going_the_list_says_so_and_is_not_kept(world):
    assert run(plain.show_list(world.request, {}, frozenset())) == Shown("no active timers")
    assert run(store.lists(world.owner.id)) == []


def test_what_happened_is_told_in_twelve_hour_times_with_no_ids(world):
    start(world, ("5m", "dinner"))
    (dinner,) = going(world)
    world.wait(60)
    change(world, ref(dinner), "pause")
    text = run(plain.history(world.request, {"which": ref(dinner)}, frozenset()))
    assert text.splitlines() == [
        "⏱️ **What happened** (oldest first)",
        "• Sat 10:00 pm · **dinner** · started · 5m left",
        "• Sat 10:01 pm · **dinner** · paused · 4m left",
    ]
    assert run(plain.history(world.request, {}, frozenset())) == text, "all of them, when none is named"
    with pytest.raises(UserError, match="couldn't tell which timer"):
        run(plain.history(world.request, {"which": "dinner"}, frozenset()))


def test_with_no_history_it_says_so(world):
    assert run(plain.history(world.request, {}, frozenset())) == "⏱️ Nothing has happened to a timer lately."


# --- the Pomodoro ---------------------------------------------------------------------------------------------
def test_a_pomodoro_starts_with_its_card_and_the_lengths_asked_for(world):
    result = run(plain.pomo_start(world.request, {"lengths": "50/10", "label": "writing"}, frozenset()))
    (session,) = run(store.active_sessions(user_id=world.owner.id))
    assert (session.label, session.focus_s, session.short_s) == ("writing", 3000, 600)
    assert result.summary.startswith(f"started pomodoro {session.id}: writing, 50m/10m") and result.also == ""
    assert len(world.channel.sent) == 1


def test_asking_for_a_pomodoro_while_one_is_going_shows_it_again(world):
    run(plain.pomo_start(world.request, {}, frozenset()))
    again = run(plain.pomo_start(world.request, {}, frozenset()))
    assert again.summary.endswith("already going; card shown again") and again.also == "-# Already going: here it is again."
    assert world.deleted == [7001] and len(run(store.active_sessions(user_id=world.owner.id))) == 1
    other = run(plain.pomo_start(world.request, {"lengths": "50/10"}, frozenset()))
    assert other.also == "-# Already going: here it is again. It runs at 25m/5m/15m; stop it first to start one at 50/10."


def test_lengths_that_cannot_be_read_are_refused(world):
    with pytest.raises(UserError, match="Say the lengths as focus and break"):
        run(plain.pomo_start(world.request, {"lengths": "0/10"}, frozenset()))


def test_the_session_is_changed_and_asked_about_in_plain_words(world):
    assert run(plain.pomo_status(world.request, {}, frozenset())) == "🍅 No Pomodoro session is going."
    with pytest.raises(UserError, match="No Pomodoro session is going"):
        run(plain.pomo_change(world.request, {"action": "pause"}, frozenset()))
    run(plain.pomo_start(world.request, {"label": "writing"}, frozenset()))
    world.wait(300)
    assert run(plain.pomo_status(world.request, {}, frozenset())) == "🍅 **writing** · Focus, round 1 of 4 · 20m left"
    run(plain.pomo_change(world.request, {"action": "pause"}, frozenset()))
    assert run(plain.pomo_status(world.request, {}, frozenset())) == "🍅 **writing** · Focus, round 1 of 4 · paused with 20m left"
    run(plain.pomo_change(world.request, {"action": "resume"}, frozenset()))
    run(plain.pomo_change(world.request, {"action": "extend", "duration": "10m"}, frozenset()))
    assert run(plain.pomo_status(world.request, {}, frozenset())).endswith("30m left")
    run(plain.pomo_change(world.request, {"action": "stop"}, frozenset()))
    assert run(store.active_sessions(user_id=world.owner.id)) == []


def test_focus_stats_are_the_same_as_the_typed_word_shows(world):
    assert run(plain.pomo_stats(world.request, {}, frozenset())).splitlines() == [
        "🍅 **Focus stats**", "**Today:** nothing yet", "**This week:** nothing yet",
    ]


# --- what extraction is told ----------------------------------------------------------------------------------------
def test_the_state_has_a_line_for_each_timer_with_its_id_and_the_session(world):
    start(world, ("5m", "tea"), ("9m", "dinner"))
    tea, dinner = going(world)
    run(timers.pause(dinner))
    run(plain.pomo_start(world.request, {"label": "writing"}, frozenset()))
    state = run(plain.state(Request(world.owner, CHANNEL, "pause this", replied_to=tea.message_id)))
    assert state.heading == "Timers and the Pomodoro session now (use these ids)"
    assert state.lines[0] == f'{ref(tea)}: "tea" · running, 5m left · in this channel · the user replied to this one'
    assert state.lines[1] == f'{ref(dinner)}: "dinner" · paused with 9m left · in this channel'
    assert state.lines[2].startswith('Pomodoro session p1: "writing" · Focus, round 1 of 4 · running, 25m left')
    assert not any("timer_control" in line or "pomodoro_control" in line for line in state.lines), "no tool of the old way is named"


def test_a_timer_that_ended_is_still_named_so_it_can_be_told_from_one_that_never_was(world):
    start(world, ("5m", "tea"))
    (tea,) = going(world)
    run(timers.cancel(tea))
    state = run(plain.state(world.request))
    assert state.lines == (f'{ref(tea)}: "tea" · cancelled (over: nothing more can be done to it)',)
    assert actions.shown_state(run(plain.state(Request(world.owner, CHANNEL, "x"))), "x")[0].startswith("Timers and the Pomodoro session now (use these ids):\n- ")


def test_with_nothing_going_the_state_says_so(world):
    assert actions.shown_state(run(plain.state(world.request)), "set a timer")[0] == (
        "Timers and the Pomodoro session now (use these ids): no timers and no Pomodoro session"
    )
