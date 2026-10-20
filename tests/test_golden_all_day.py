"""All-day events in the conversation, as live had it (21 Oct): the message is an all-day card, and "All day"
typed under a card's "At what time?" answers it, with no router. On what the real API answered
(evals/fixtures/calendar_write.json, w25 to w27); the Bot calendar in memory, made-up events."""
from core import confirm
from tests.test_calendar_all_day import EXTRACTED, LIVE, NO_TIME, ROUTER, TITLE, TWO_DAYS
from tests.test_calendar_google import BOT_ID, made_up_key  # noqa: F401
from tests.test_conversation import open_cards, run, world  # noqa: F401
from tests.test_golden import bot  # noqa: F401
from tests.test_smartinbox import inbox  # noqa: F401

def test_the_live_message_is_an_all_day_card_and_save_adds_it(inbox):  # noqa: F811
    inbox.claude(("route", ROUTER["w25"]), tuple(EXTRACTED[("w25", LIVE)]))
    inbox.say(LIVE)
    card = open_cards()[-1]
    assert card.task == "calendar" and card.action == "calendar_add" and TWO_DAYS in inbox.sent[-1][1].text
    pressed = inbox.Press(card.id, card.message_id)
    run(confirm.on_save(pressed))
    assert pressed.cards[-1].text.startswith(f"📅 Added · **{TITLE}**")
    (made,) = inbox.google.calendars[BOT_ID].values()
    assert made["start"] == {"date": "2026-11-21"} and made["end"] == {"date": "2026-11-23"}
    assert not any("Not included" in str(getattr(each[1], "text", each[1])) for each in inbox.sent)


def test_all_day_typed_under_the_question_answers_it_without_the_router(inbox):  # noqa: F811
    asked = {"title": TITLE, "day": "21 November", "last_day": "22 November", "guessed": [], "not_included": []}
    inbox.claude(("route", ROUTER["w25"]), ("calendar_add", asked))
    inbox.say(NO_TIME)
    card = open_cards()[-1]
    assert "At what time?" in inbox.sent[-1][1].text
    before = len(inbox.requests)
    inbox.claude(tuple(EXTRACTED[("w27", "All day")]))
    inbox.say("All day")
    assert [each.purpose for each in inbox.requests[before:]] == ["extraction"], "read against the card: no router"
    remade = open_cards()[-1]
    assert remade.action == "calendar_add" and TWO_DAYS in inbox.sent[-1][1].text and "Not included" not in inbox.sent[-1][1].text
    pressed = inbox.Press(remade.id, remade.message_id)
    run(confirm.on_save(pressed))
    (made,) = inbox.google.calendars[BOT_ID].values()
    assert made["start"] == {"date": "2026-11-21"} and made["end"] == {"date": "2026-11-23"} and card.id


def test_move_then_delete_the_hen_do_in_words_each_a_card(inbox):  # noqa: F811
    from tests.test_calendar_all_day import FIXTURES

    routed = {each["golden"]: each["recorded"] for each in FIXTURES["router"] if each.get("golden") in ("w28", "w29")}
    extracted = {each["message"]: each["recorded"] for each in FIXTURES["extraction"] if each.get("golden") in ("w28", "w29")}
    inbox.claude(("route", ROUTER["w25"]), ("calendar_add", {"title": "hen do", "day": "21 November", "last_day": "22 November", "all_day": True, "guessed": [], "not_included": []}))
    inbox.say("add an all day event 21 and 22 November, hen do")
    run(confirm.on_save(inbox.Press(open_cards()[-1].id, open_cards()[-1].message_id)))
    (ref,) = inbox.google.calendars[BOT_ID]
    inbox.claude(("route", routed["w28"]), tuple(extracted["move the hen do to 28 November"]))
    inbox.say("move the hen do to 28 November")
    card = open_cards()[-1]
    assert card.action == "calendar_move" and "Sat 28 Nov to Sun 29 Nov" in inbox.sent[-1][1].text and "another calendar" not in inbox.sent[-1][1].text
    run(confirm.on_save(inbox.Press(card.id, card.message_id)))
    assert inbox.google.calendars[BOT_ID][ref]["start"] == {"date": "2026-11-28"}
    inbox.claude(("route", routed["w29"]), tuple(extracted["delete the hen do"]))
    inbox.say("delete the hen do")
    card = open_cards()[-1]
    assert card.action == "calendar_delete"
    run(confirm.on_save(inbox.Press(card.id, card.message_id)))
    assert inbox.google.calendars[BOT_ID] == {}
