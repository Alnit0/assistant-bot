"""Alex's rule of 17 Oct, end to end on the router's and extraction's recorded answers (evals/fixtures/
crosstask.json, x45 and x46): a thing to do on a day with no time is a to-do for that day; with a time it is a
reminder. Applied in code after extraction (tasks/nudges/plain.py `to_do_instead`, core's `actions.HandOff`)."""
import json
from pathlib import Path

from tests.test_conversation import open_cards, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401
from tests.test_smartinbox import inbox, made_up_key, shown  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "crosstask.json").read_text(encoding="utf-8"))
ROUTER = {each["golden"]: each["recorded"] for each in FIXTURES["router"] if each.get("golden") in ("x45", "x46")}
EXTRACTED = {each["golden"]: each["recorded"] for each in FIXTURES["extraction"] if each.get("golden") in ("x45", "x46")}


def replay(bot, golden: str, message: str):
    bot.claude(("route", ROUTER[golden]), tuple(EXTRACTED[golden]))
    bot.say(message)
    return open_cards()[-1]


def test_x45_a_day_and_no_time_is_a_to_do_for_that_day(inbox):
    card = replay(inbox, "x45", "I need to call the bank on Friday")
    assert card.task == "todos" and card.action == "todo_add", "never a reminder that asks for a time"
    said = shown(inbox).text
    assert said.startswith("📝 To-dos · new") and "**Call the bank** · Fri" in said


def test_x46_a_day_and_a_time_is_a_reminder(inbox):
    card = replay(inbox, "x46", "call the bank Friday at 10")
    assert card.task == "nudges" and card.action == "nudge_add"
    said = shown(inbox).text
    assert said.startswith("⏰ Reminders · new") and "**Call the bank**" in said


def test_remind_me_on_a_day_with_no_time_stays_a_reminder_that_asks_when(inbox):
    inbox.claude(("route", ROUTER["x45"]), ("nudge_add", {"text": "call the bank", "day": "Friday", "guessed": [], "not_included": []}))
    inbox.say("remind me to call the bank on Friday")
    card = open_cards()[-1]
    assert card.task == "nudges", "asked to be reminded in so many words: its card asks the time"
