"""The gym's add-ons: the weight tracker (tasks/gym/weight.py, GYM_WEIGHT: a smoothed trend, the week's change,
a target, one line only on a day with a weigh-in, private), training insights (tasks/gym/insights.py: sets per
muscle group, push against pull, stalls, a lighter week) and the pain tracker (tasks/gym/pain.py: the pattern
on an exercise's card with a swap, the history, the diary's mentions). Made-up data only."""
import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, database, design, live, llm
from core import day as days
from core.actions import Request
from tasks.gym import insights, pain, rules, session, store, weight
from tasks.gym.rules import DoneSet, Note
from tests import test_gym

run = test_gym.run


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"gym": store.MIGRATIONS})
    monkeypatch.setattr(config, "GYM_ENABLED", True)
    monkeypatch.setattr(config, "GYM_WEIGHT", True)
    seen = SimpleNamespace(owner=owner, sent=[])

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.sent.append(card)
        return len(seen.sent)

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(weight, "_changed", lambda user_id: None)
    weight.register()
    seen.today = date(2026, 10, 20) if days.today() < date(2026, 10, 20) else days.today() + timedelta(days=1)
    clock.advance_to(days.at(seen.today, time(7, 30)))
    seen.request = lambda text="said": Request(owner, 100, text)
    return seen


def weigh(world, kg, days_ago=0, hour=7):
    at = days.at(world.today - timedelta(days=days_ago), time(hour, 0))
    run(database.run(weight.db_add, world.owner.id, at, kg))


# --- the weight tracker ----------------------------------------------------------------------------------------------------
def test_the_trend_is_smoothed_so_a_day_s_swing_does_not_dominate():
    found = [weight.WeighIn(index, datetime(2026, 10, 1 + index, 7), kg) for index, kg in enumerate([82.0, 82.0, 84.0, 82.0])]
    smoothed = [value for _, value in weight.trend(found)]
    assert smoothed == [82.0, 82.0, 82.2, 82.18], "a 2 kg jump moves the trend 0.2"


def test_a_weigh_in_in_words_is_kept_with_undo_and_the_line_has_the_trend_and_the_week(world):
    for ago, kg in ((8, 83.0), (6, 82.8), (3, 82.6)):
        weigh(world, kg, ago)
    said = run(weight.log(world.request("weighed 82.4 this morning"), {"kg": 82.4}, frozenset()))
    assert said.summary.startswith("⚖️ 82.4 kg kept · trend ") and "this week" in said.summary
    (row,) = world.sent[-1].rows
    assert row[0].label == "Undo"
    with pytest.raises(Exception, match="doesn't look like a weight"):
        run(weight.log(world.request("weighed 8240"), {"kg": 8240}, frozenset()))


def test_a_target_and_the_briefing_s_line_only_on_a_day_with_a_weigh_in(world):
    weigh(world, 83.0, 7)
    assert run(weight.summary(world.owner.id, world.today)) is None, "no weigh-in today: no line, no prompt"
    weigh(world, 82.0, 0)
    target = run(weight.target_card(world.request("aim for 80"), {"kg": 80}, frozenset()))
    run(weight.target_save(world.request(), target.data))
    assert run(weight.target_check(world.request(), target.data)) == ""
    line = run(weight.summary(world.owner.id, world.today)).overview
    assert line.startswith("trend 82.9 · −0.1 this week · ") and line.endswith("to go")
    week = run(weight.week(world.owner.id, world.today - timedelta(days=world.today.weekday()), world.today))
    assert week.small.endswith("weigh-in") or week.small.endswith("weigh-ins")


def test_the_weight_entry_is_private_and_never_on_the_status_line(world):
    from tasks import gym

    entries = gym.task.entries()
    assert [each.name for each in entries] == ["gym", "weight"]
    assert entries[1].private and entries[1].attention is None, "never an attention item: never on the status line or a ping"
    assert not actions.problems(entries)


# --- training insights -------------------------------------------------------------------------------------------------------
def _session(day, *sets):
    return (day, [DoneSet(name, rules.WORKING, "", rules.TO_FAILURE, 5, 8, reps, kg) for name, kg, reps in sets])


def test_sets_per_group_push_against_pull_and_stalls():
    monday = date(2026, 10, 19)
    sessions = [
        _session(monday, ("Bench press", 40, 8), ("Bench press", 40, 7), ("Overhead press", 30, 6), ("Lat pulldown", 55, 10)),
        _session(monday + timedelta(days=2), ("Squat", 80, 6), ("Romanian deadlift", 70, 8)),
    ]
    sets = insights.weekly_sets(sessions, monday)
    assert sets["chest"] == 2 and sets["shoulders"] == 1 and sets["back"] == 1 and sets["biceps"] == 1 and sets["hamstrings"] == 1
    assert insights.balance(sessions, monday + timedelta(days=3)) == (3, 1)
    assert insights.imbalance(3, 1) == "pushing 3 sets against pulling 1 over 4 weeks" and insights.imbalance(3, 3) == ""
    history = {
        "Bench press": [_session(monday - timedelta(days=7 * n), ("Bench press", 40, 8)) for n in range(4, 0, -1)],
        "Squat": [_session(monday - timedelta(days=7 * n), ("Squat", 80 + 2.5 * (4 - n), 6)) for n in range(4, 0, -1)],
        "Row": [_session(monday - timedelta(days=7 * n), ("Row", 50, 8)) for n in range(4, 0, -1)],
    }
    assert insights.stalls(history) == ["Bench press", "Row"], "no gain in weight or reps for 3 sessions; squat went up"
    assert insights.summary_line(3, 1, ["Bench press", "Row"]) == "pushing 3 sets against pulling 1 over 4 weeks · stalled: Bench press, Row · a lighter week could help"


def test_an_exercise_the_table_doesn_t_know_is_asked_of_claude_once(world, monkeypatch):
    asked = []

    async def call_tool(system, user, tools, **more):
        asked.append(user)
        return insights.TOOL, {"exercises": [{"index": 0, "groups": ["back", "biceps"]}]}

    monkeypatch.setattr(llm, "call_tool", call_tool)
    learned = run(insights.learn(["Bench press", "Made-up landmine thing"]))
    assert learned["made-up landmine thing"] == ("back", "biceps") and asked == ["0. made-up landmine thing"]
    run(insights.learn(["Made-up landmine thing"]))
    assert len(asked) == 1, "kept: never asked again"


def test_how_s_my_training_going_answers_from_the_log(world, monkeypatch):
    monkeypatch.setattr(llm, "call_tool", test_gym.fake_claude)
    monkeypatch.setitem(config.CHANNELS, "gym", 700)
    test_gym.imported(SimpleNamespace(**{**vars(world), "request": lambda text="said", previous=None, attachments=(): Request(world.owner, 100, text, previous=previous, attachments=attachments)}))
    said = run(insights.answer(world.owner.id, world.today))
    assert said.startswith("🏋️ **Training** · ") and "push " in said and "over 4 weeks" in said


# --- the pain tracker -----------------------------------------------------------------------------------------------------
def test_the_pattern_on_an_exercise_s_card_with_a_swap_and_a_professional_from_3_times():
    flags = [(date(2026, 10, day), "shoulder") for day in (1, 8, 15)]
    assert pain.pattern("Lateral raise", flags[:1]) == [], "once is no pattern"
    assert pain.pattern("Lateral raise", flags[:2]) == ["⚠️ shoulder flagged 2 times on lateral raises", "maybe try cable lateral raise, lighter instead"]
    assert pain.pattern("Lateral raise", flags)[-1] == "if it keeps coming up, worth checking with a physio or doctor"
    assert pain.swap_for("Made-up thing") == ""


def test_pain_from_gym_notes_and_the_diary_is_one_history(world):
    for day in (1, 2, 3):
        session_id = run(database.run(store.db_add_session, world.owner.id, None, "Upper 1", world.today - timedelta(days=day), store.FINISHED, clock.now()))
        run(database.run(store.db_add_note, world.owner.id, session_id, Note("Lateral raise", "shoulder felt off", True, body_part="Shoulder")))
    run(pain.from_diary(world.owner.id, world.today, "knee"))
    assert len(run(pain.flags(world.owner.id, "Lateral raise"))) == 3
    said = pain.history_text(run(database.run(pain.db_history, world.owner.id)), world.today)
    assert said.startswith("🏋️ **Pain noted** · 4 times · shoulder 3, knee 1")
    assert "lateral raise 3" in said and "diary 1" in said and said.endswith("worth checking with a physio or doctor")
    assert "felt off" not in said, "the pattern, never the words"


def test_the_card_shows_the_pattern_the_next_time(world, monkeypatch):
    monkeypatch.setattr(llm, "call_tool", test_gym.fake_claude)
    monkeypatch.setitem(config.CHANNELS, "gym", 700)
    monkeypatch.setattr(cards, "edit", lambda channel_id, message_id, card: asyncio.sleep(0, True))
    monkeypatch.setattr(session, "changed", lambda user_id: None)
    session.register()
    test_gym.imported(SimpleNamespace(**{**vars(world), "request": lambda text="said", previous=None, attachments=(): Request(world.owner, 100, text, previous=previous, attachments=attachments)}))
    for day in (2, 3):
        session_id = run(database.run(store.db_add_session, world.owner.id, None, "Lower 1", world.today - timedelta(days=day), store.FINISHED, clock.now()))
        run(database.run(store.db_add_note, world.owner.id, session_id, Note("Romanian deadlift", "knee again", True, body_part="knee")))
    run(session.start(world.owner.id))
    shown = "\n".join(design.texts(world.sent[-1].layout))
    assert "⚠️ knee flagged" in shown and "romanian deadlifts" in shown and "maybe try hip thrust instead" in shown
