"""#gym listens like #inbox (Alex, 19 Oct): a task's own channel (`Entry.home`) is read, the router is told a
message there is most likely the gym's ("bench 40 for 10" needs no word gym), anything else is answered as
anywhere, and a CSV or XLSX sent there is the gym's import at once, with no router. On what the router really
answered (evals/fixtures/gym.json, gh1 to gh6). Made-up plan (tests/gym_files.py)."""
import asyncio

import pytest

from core import actions, config, conversation, llm, routing
from tests.test_conversation import open_cards, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401
from tests.test_golden_gym import EXTRACTED, GYM, ROUTER, gym_bot  # noqa: F401


def say_in_gym(bot, text, attachments=()):
    ctx = bot.message(text, channel_id=GYM)
    ctx.attachments = tuple(attachments)
    return ctx, asyncio.run(conversation.handle(ctx, "the shortcuts"))


def test_the_bot_listens_in_gym_only_while_the_gym_is_loaded(gym_bot, monkeypatch):
    assert conversation.listens_in(GYM) and actions.home_of(GYM).name == "gym"
    monkeypatch.setattr(actions, "_entries", {name: each for name, each in actions._entries.items() if name != "gym"})
    assert not conversation.listens_in(GYM), "with the gym off, #gym is not read"


def test_the_router_is_told_a_message_in_gym_is_most_likely_the_gym_s():
    turn = routing.user_turn("bench 40 for 10", home=("gym", "gym"))
    assert "Sent in #gym, the gym task's own channel" in turn and turn.endswith("The message to route:\nbench 40 for 10")
    assert "Sent in" not in routing.user_turn("bench 40 for 10")


def test_bench_40_for_10_in_gym_goes_to_the_gym_without_the_word(gym_bot):
    gym_bot.claude(("route", ROUTER["gh1"]), ("gym_log", {"sets": [{"exercise": "Bench press", "weight": 40, "reps": 10, "set_type": "working"}], "guessed": [], "not_included": []}))
    say_in_gym(gym_bot, "bench 40 for 10")
    router = next(each for each in gym_bot.requests if each.purpose == "router")
    assert "Sent in #gym" in router.user
    card = open_cards()[-1]
    assert card.task == "gym" and card.action == "gym_log" and card.channel_id == GYM
    assert "**Bench press** · 40 kg × 10" in gym_bot.sent[-1][1].text


def test_starting_a_workout_in_gym(gym_bot):
    gym_bot.claude(("route", ROUTER["gh2"]), tuple(EXTRACTED["gy1"]))
    say_in_gym(gym_bot, "starting a workout")
    assert [each.purpose for each in gym_bot.requests][-2:] == ["router", "extraction"]
    assert any("gym" == each.task for each in gym_bot.requests if each.purpose == "extraction")


def test_anything_else_in_gym_is_answered_as_anywhere(gym_bot):
    assert ROUTER["gh4"]["kind"] == "chat", "the router's real answer: chat"
    gym_bot.claude(("route", ROUTER["gh4"]))
    gym_bot.chat_answers.append("Paris.")
    say_in_gym(gym_bot, "what's the capital of France?")
    assert gym_bot.chats, "answered by chat"
    assert not any(each.task == "gym" for each in open_cards())
    assert ROUTER["gh5"]["tasks"] == ["nudges"] and ROUTER["gh6"]["tasks"] == ["todos"], "another task's request stays that task's"


@pytest.mark.parametrize("name", ["new logbook.xlsx", "new logbook.csv"])
def test_a_spreadsheet_sent_in_gym_is_imported_at_once_with_no_router(gym_bot, monkeypatch, name):
    from tests import gym_files, test_gym

    monkeypatch.setattr(llm, "call_tool", test_gym.fake_claude)  # the import's own column mapping, made up
    before = len(gym_bot.requests)
    data = gym_files.logbook_xlsx() if name.endswith("xlsx") else gym_files.logbook_csv()
    say_in_gym(gym_bot, "", (test_gym.attached(name, data),))
    assert len(gym_bot.requests) == before, "the router is not asked"
    card = open_cards()[-1]
    assert card.task == "gym" and card.action == "gym_import" and card.channel_id == GYM
    assert config.CHANNELS["gym"] == GYM
