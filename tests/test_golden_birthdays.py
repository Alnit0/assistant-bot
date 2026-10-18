"""Birthdays, end to end on the router's and extraction's recorded answers (evals/fixtures/birthdays.json, bd6
and bd8 to bd14): the user's own birthday in each phrasing is "Your birthday", never a person called My or Me (a
live bug of 19 Oct); "my mum's" is Mum; "my brother Tom's" is Tom (brother); the heads-up changed in words. The
names are tidied in code after extraction (tasks/nudges/birthdays.py `tidy`). Made-up names only."""
import json
from pathlib import Path

import pytest

from core import actions, config, confirm
from tests.test_conversation import open_cards, run, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401
from tests.test_smartinbox import inbox, made_up_key  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "birthdays.json").read_text(encoding="utf-8"))
ROUTER = {each["golden"]: each["recorded"] for each in FIXTURES["router"] if each.get("recorded")}
EXTRACTED = {each["golden"]: (each["message"], tuple(each["recorded"])) for each in FIXTURES["extraction"] if each.get("recorded")}


@pytest.fixture
def birthday_bot(inbox, monkeypatch):  # noqa: F811
    from tasks import nudges
    from tasks.nudges import birthdays

    monkeypatch.setattr(config, "BIRTHDAYS_ENABLED", True)
    monkeypatch.setattr(birthdays, "changed", lambda user_id: None)
    monkeypatch.setattr(actions, "_entries", dict(actions._entries))
    actions.set_catalogue([*actions.catalogue(), birthdays_entry := nudges.birthdays_entry()])
    assert birthdays_entry.name == "birthdays"
    return inbox


def replay(bot, golden: str, routed: str = "bd8"):
    message, extracted = EXTRACTED[golden]
    bot.claude(("route", ROUTER[routed]), extracted)
    bot.say(message)
    return bot.sent[-1][1].text


def save(bot) -> str:
    run(confirm.on_save(press := bot.Press(open_cards()[-1].id)))
    return press.cards[-1].text


def kept(bot):
    from tasks.nudges import birthdays

    return run(birthdays.every(bot.owner.id))


@pytest.mark.parametrize("golden", ["bd8", "bd9", "bd10"])
def test_the_user_s_own_birthday_in_each_phrasing_is_your_birthday(birthday_bot, golden):
    said = replay(birthday_bot, golden)
    assert said.startswith("🎂 Birthdays · new") and "**Your birthday** · " in said
    assert "My" not in said.replace("Your", "") and "**Me**" not in said
    assert save(birthday_bot).startswith("🎂 Saved · **Your birthday** · ")
    (own,) = kept(birthday_bot)
    assert own.mine and own.name == ""


def test_my_mum_s_birthday_is_mum(birthday_bot):
    said = replay(birthday_bot, "bd11")
    assert "**Mum** · Thu 12 Mar" in said or "**Mum** · " in said
    save(birthday_bot)
    assert [each.name for each in kept(birthday_bot)] == ["Mum"]


def test_my_brother_tom_s_birthday_is_tom_with_the_relation(birthday_bot):
    said = replay(birthday_bot, "bd12")
    assert "**Tom (brother)** · " in said
    save(birthday_bot)
    (tom,) = kept(birthday_bot)
    assert (tom.name, tom.relation) == ("Tom", "brother")


def test_sam_s_birthday_is_sam(birthday_bot):
    assert "**Sam** · " in replay(birthday_bot, "bd13")


def test_when_is_my_birthday_answers_with_your_birthday(birthday_bot):
    replay(birthday_bot, "bd8")
    save(birthday_bot)
    said = replay(birthday_bot, "bd14")
    assert said.startswith("🎂 **Your birthday** · ")


def test_tell_me_5_days_before_is_the_heads_up(birthday_bot):
    from tests.test_birthdays import FakeBot  # noqa: F401

    message, extracted = EXTRACTED["bd1"]
    birthday_bot.claude(("route", ROUTER["bd1"]), extracted)
    birthday_bot.say(message)
    save(birthday_bot)
    said = replay(birthday_bot, "bd6", routed="bd6")
    assert "**in the briefing from 5 days before**" in said
