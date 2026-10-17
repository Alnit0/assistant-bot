"""The gym's golden conversations, end to end through the conversation's own code on what the router and
extraction really answered (evals/fixtures/gym.json): a whole session described after the fact in messy words
(gy9), a partial one days later with a note about pain (gy16), yesterday's in a few words (gy15), and starting
a workout (gy1). Made-up plan (tests/gym_files.py)."""
import asyncio
import json
from datetime import time
from pathlib import Path

import pytest

from core import actions, config, database, llm
from core import day as days
from tasks import gym, nudges, todos
from tasks.gym import plain, session, store
from tests.test_conversation import open_cards, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "gym.json").read_text(encoding="utf-8"))
ROUTER = {each["golden"]: each["recorded"] for each in FIXTURES["router"]}
EXTRACTED = {each["golden"]: each["recorded"] for each in FIXTURES["extraction"]}
MESSAGE = {each["golden"]: each["message"] for each in FIXTURES["extraction"]}
GYM = 700


@pytest.fixture
def gym_bot(bot, make_db, monkeypatch, dev_clock):  # noqa: F811
    from tasks.nudges import store as nudges_store
    from tasks.todos import store as todos_store
    from tests import test_gym

    make_db({"gym": store.MIGRATIONS, "todos": todos_store.MIGRATIONS, "nudges": nudges_store.MIGRATIONS})
    for name in ("GYM_ENABLED", "TODOS_ENABLED", "NUDGES_ENABLED"):
        monkeypatch.setattr(config, name, True)
    monkeypatch.setitem(config.CHANNELS, "gym", GYM)
    monkeypatch.setattr(session, "changed", lambda user_id: None)
    actions.set_catalogue([*todos.task.entries(), *nudges.task.entries(), *gym.task.entries()])
    session.register()
    real = llm.call_tool
    monkeypatch.setattr(llm, "call_tool", test_gym.fake_claude)
    from core.actions import Request

    owner = bot.owner if hasattr(bot, "owner") else None
    user = owner or asyncio.run(_owner())
    proposal = asyncio.run(plain.import_card(Request(user, 100, "logbook", attachments=(test_gym.attached("logbook.csv", test_gym.gym_files.logbook_csv()),)), {}, frozenset()))
    asyncio.run(plain.import_save(Request(user, 100), proposal.data))
    monkeypatch.setattr(llm, "call_tool", real)
    bot.user = user
    return bot


async def _owner():
    from core.users import get_user_by_discord_id

    return await get_user_by_discord_id(int(config.OWNER_ID))


def replay(bot, golden: str):
    bot.claude(("route", ROUTER.get(golden, ROUTER["gy8"])), tuple(EXTRACTED[golden]))  # gy15, gy16: the router said gym for gy8 alike
    bot.say(MESSAGE[golden])
    return open_cards()[-1] if open_cards() else None


def shown(bot) -> str:
    return bot.sent[-1][1].text


def test_gy9_a_whole_session_described_in_messy_words_is_one_card(gym_bot):
    card = replay(gym_bot, "gy9")
    assert card.task == "gym" and card.action == "gym_log"
    said = shown(gym_bot)
    assert "**Upper 1** · today" in said
    assert "**Bench press** · 20 kg × 15, 40 kg × 9, 40 kg × 8" in said
    assert "**Incline press** · 14 kg each × 10, 14 kg each × 9" in said
    assert "**Lateral raise** · skipped" in said and "⚠️ note: “shoulder felt off”" in said
    assert "note: “last set was a grind”" in said


def test_gy16_a_partial_session_days_later_with_its_note_on_the_right_exercise(gym_bot):
    replay(gym_bot, "gy16")
    said = shown(gym_bot)
    assert "**Bench press** · 40 kg × 9, 40 kg × 9, 40 kg × 8" in said
    assert "⚠️ note: “knee was sore”" in said
    assert "**Upper 1** · Tue " in said, "last Tuesday, worked out by Python"


def test_gy15_yesterday_in_a_few_words_is_the_workout_its_exercises_make(gym_bot):
    replay(gym_bot, "gy15")
    said = shown(gym_bot)
    assert "**Lower 1** · yesterday ❓" in said, "worked out from its exercises, flagged as a guess"
    assert "**Romanian deadlift** · 70 kg × 8, 70 kg × 8" in said


def test_gy1_starting_a_workout_posts_the_next_one_in_gym(gym_bot):
    gym_bot.claude(("route", ROUTER["gy1"]), tuple(EXTRACTED["gy1"]))
    gym_bot.say(MESSAGE["gy1"])
    opened = asyncio.run(database.run(store.db_open_session, gym_bot.user.id))
    assert opened is not None and opened.name == "Lower 1"
