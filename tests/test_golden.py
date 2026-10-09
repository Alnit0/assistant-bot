"""The golden conversations: the acceptance test for how the bot talks (the conversation
standard, section 6). Each is run end to end, offline: Claude's part is replayed from what
the real API last returned for it (evals/fixtures/golden.json), and everything else is the
bot's own code against a temporary database.

A conversation the bot can't yet hold is marked `gap` with what is missing. It must fail
until that is built (strict), so the list of gaps here is always the true one. Every change
must keep the others passing.
"""
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import actions, confirm, day, timeinput
from core.actions import Request
from tasks.lab import demo
from tasks.pills import store as pills_store
from tasks.pills import task as pills_task
from tasks.timers import plain as timers_plain
from tasks.timers import store as timers_store
from tasks.timers import task as timers_task
from tests.test_conversation import card_lines, open_cards, pack, route, run, shop_add_all, world  # noqa: F401

FIXTURES = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "golden.json").read_text(encoding="utf-8"))
ROUTED = {entry["golden"]: ("route", entry["recorded"]) for entry in FIXTURES["router"]}
EXTRACTED = {entry["golden"]: tuple(entry["recorded"]) for entry in FIXTURES["extraction"]}
SAID = {entry["golden"]: entry["message"] for entry in [*FIXTURES["extraction"], *FIXTURES["router"]]}


def gap(reason: str):
    """A golden conversation the bot can't hold yet: it has to fail until that is built."""
    return pytest.mark.xfail(strict=True, reason=f"gap: {reason}")


@pytest.fixture
def bot(world, monkeypatch):  # noqa: F811
    """The world of the conversation tests with the real pills and timers beside the demo lists."""
    actions.set_catalogue([*demo.ENTRIES, *pills_task.entries(), *timers_task.entries()])
    channel = SimpleNamespace(sent=[])

    async def send(text, **options):
        channel.sent.append(text)
        world.next_id += 1
        world.bot_messages.append(world.next_id)
        return SimpleNamespace(id=world.next_id)

    channel.send = send
    monkeypatch.setattr(timers_plain, "channel_for", lambda channel_id: channel)
    world.timer_messages = channel.sent
    return world


def card(bot):
    """The latest card: its text lines without the footer, and the labels of its buttons."""
    shown = bot.sent[-1][1]
    return shown.text.splitlines(), [button.label for row in shown.rows for button in row]


def press(bot):
    pressed = bot.Press(open_cards()[-1].id)
    run(confirm.on_save(pressed))
    return pressed.cards[-1].text


def pills(bot):
    return run(pills_store.pills(bot.owner.id))


def timers(bot):
    return run(timers_store.active_timers(user_id=bot.owner.id))


# --- 1: specific in, exact out ------------------------------------------------------------------
def test_1_every_detail_i_state_is_on_the_card_exactly_with_no_question_mark(bot):
    bot.claude(ROUTED["1"], EXTRACTED["1"])
    bot.say(SAID["1"])
    lines, buttons = card(bot)
    assert lines[:2] == ["💊 Pills · new", "**vitamin D** (1 tablet) · daily at `8:00 am` · *with food*"]
    assert "❓" not in bot.sent[-1][1].text and buttons == ["Save", "Cancel"]
    assert pills(bot) == [], "nothing is saved before Save"


def test_1a_a_course_with_every_detail_and_no_question_mark(bot):
    bot.claude(ROUTED["1a"], EXTRACTED["1a"])
    bot.say(SAID["1a"])
    today = day.today()
    dates = timeinput.format_dates(today + timedelta(days=1), today + timedelta(days=7))
    assert card(bot)[0][1] == f"**Course A** · 3× daily, ≥3h apart · *with food* · {dates} · first dose when ready"
    assert "❓" not in bot.sent[-1][1].text


def test_1b_a_brief_request_gets_a_card_with_the_defaults(bot):
    bot.claude(ROUTED["1b"], EXTRACTED["1b"])
    bot.say(SAID["1b"])
    assert card(bot)[0][:2] == ["💊 Pills · new", "**Vitamin D** · daily, untimed"]


@gap("questions on the card are not built: the time is guessed as the morning and marked ❓")
def test_1c_a_time_that_could_be_morning_or_evening_is_asked_on_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    lines, buttons = card(bot)
    assert buttons == ["8:00 am", "8:00 pm", "Cancel"], "a button per likely answer, and no Save until it is answered"
    assert "morning or the evening" in "\n".join(lines)


@gap("questions on the card are not built: one time for two doses is refused in a message, with no card")
def test_1d_a_missing_second_time_is_asked_on_the_card_with_the_rest_filled_in(bot):
    bot.claude(ROUTED["1d"], EXTRACTED["1d"])
    bot.say(SAID["1d"])
    assert open_cards() and open_cards()[-1].status == "open", "a card, with what was understood"
    lines, buttons = card(bot)
    assert "**magnesium**" in lines[1] and "Save" not in buttons


# --- 2: correcting ------------------------------------------------------------------------------------
def test_2_a_correction_in_chat_replaces_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    first = bot.sent[-1][0]
    bot.claude(EXTRACTED["2"])
    bot.say(SAID["2"])
    assert bot.deleted == [first] and card(bot)[0][1] == "**iron** · daily at `8:00 am`", "replaced, and no longer a guess"


@gap("questions on the card are not built, so there is no 8:00 pm button to tap before correcting")
def test_2a_after_answering_a_question_a_correction_still_replaces_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    assert "8:00 pm" in card(bot)[1]


def test_2b_straight_after_save_a_correction_is_a_change_card_for_what_was_just_saved(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Iron", "times": "8pm"}], "guessed": [], "not_included": []}))
    bot.say("add iron to my pills at 8pm")
    assert press(bot) == "✅ Saved · 💊 **Iron** · daily at `8:00 pm`"
    bot.claude(ROUTED["2b"], EXTRACTED["2b"])
    bot.say(SAID["2b"])
    lines, buttons = card(bot)
    assert lines[:3] == ["💊 Pills · change", "**Iron**", "schedule · daily at `8:00 pm` → daily at `9:00 pm`"]
    assert buttons == ["Save", "Cancel"]


# --- 3, 4: timers ----------------------------------------------------------------------------------------
def test_3_a_timer_starts_with_no_card(bot):
    bot.claude(ROUTED["3"], EXTRACTED["3"])
    bot.say(SAID["3"])
    (tea,) = timers(bot)
    assert (tea.label, tea.duration_s) == ("tea", 300) and open_cards() == [] and len(bot.timer_messages) == 1


def test_4_it_is_the_timer_just_started(bot):
    bot.claude(ROUTED["3"], EXTRACTED["3"])
    bot.say(SAID["3"])
    bot.claude(ROUTED["4"], EXTRACTED["4"])
    bot.say(SAID["4"])
    (tea,) = timers(bot)
    assert tea.duration_s + 120 == pytest.approx(tea.left(timers_plain.utc_now()), abs=5), "two more minutes on the tea timer"
    assert "tea" in bot.sent[-1][1].text and open_cards() == []


# --- 5, 6 ---------------------------------------------------------------------------------------------------
def test_5_a_general_question_gets_a_plain_answer_and_no_card(bot):
    bot.claude(ROUTED["5"])
    ctx, _ = bot.say(SAID["5"])
    assert ctx.replies == ["Paris."] and open_cards() == [] and bot.sent == []


def test_6_several_things_are_one_card(bot):
    bot.claude(ROUTED["6"], EXTRACTED["6"])
    bot.say(SAID["6"])
    assert card_lines(bot) == ["🛒 Shopping · new", "honey · × 1", "jam · × 1", "eggs · × 5"]


# --- 7, 8, 9: where I point beats what is newest ---------------------------------------------------------------
def test_7_a_reply_to_an_older_card_changes_that_card_not_the_newest(bot):
    bot.claude(route("shopping"), shop_add_all("milk"))
    bot.say("add milk to the shopping list")
    older = bot.sent[-1][0]
    bot.claude(route("packing"), pack("socks"))
    bot.say("add socks to the packing list")  # names its list, so it is a card of its own
    newest = bot.sent[-1][0]
    assert [stored.status for stored in open_cards()] == ["open", "open"] and older != newest, "two cards open"
    bot.claude(EXTRACTED["7"])
    bot.say(SAID["7"], reply_to=older)
    assert older in bot.deleted and newest not in bot.deleted
    assert card_lines(bot) == ["🛒 Shopping · new", "milk · × 2"]


def test_8_a_reply_to_the_older_timer_pauses_that_one_not_the_newest(bot):
    # The typed word "pause" as a reply is a shortcut and never reaches Claude; in plain
    # words ("pause this") the code takes the timer replied to whatever Claude returned
    for label in ("tea", "dinner"):
        run(timers_plain.start(Request(bot.owner, 100, "start"), {"timers": [{"duration": "5m", "label": label}]}, frozenset()))
    tea, dinner = timers(bot)
    replied = Request(bot.owner, 100, "pause", replied_to=tea.message_id)
    run(timers_plain.change(replied, {"which": f"t{dinner.id}", "action": "pause"}, frozenset()))
    assert [(timer.label, timer.status) for timer in timers(bot)] == [("tea", timers_store.PAUSED), ("dinner", timers_store.RUNNING)]


def test_9_dev_why_as_a_reply_to_a_bot_message_is_the_trace_for_that_message(bot):
    from core import database, trace

    bot.claude(ROUTED["6"], EXTRACTED["6"])
    bot.say(SAID["6"])
    bot.claude(ROUTED["14"])
    bot.say(SAID["14"])
    rows = run(database.run(trace.db_recent, bot.owner.id, 5, ("chat",)))
    first = rows[0]
    from datetime import datetime

    just_after = datetime.fromisoformat(first["received_at"]) + timedelta(microseconds=1)
    anchor = run(database.run(trace.db_anchor, bot.owner.id, ("chat",), 987654, just_after))
    shown = run(database.run(trace.db_recent, bot.owner.id, 1, ("chat",), "dev why", anchor))
    assert [row["content"] for row in shown] == [SAID["6"]], "the message of mine that the bot's card answered, not the newest"


# --- 10: a list on screen is context, and what I state beats it ---------------------------------------------------
def test_10_straight_after_a_list_a_bare_request_is_for_that_list(bot):
    bot.claude(ROUTED["10"], ("demo_pack_list", {"guessed": [], "not_included": []}))
    bot.say(SAID["10"])
    bot.claude(EXTRACTED["10"])
    bot.say("add milk")
    assert card_lines(bot)[:2] == ["🧳 Packing · new", "milk · checked bag"] and len(bot.requests) == 3, "no router: the list says which task"


def test_10a_a_destination_i_state_beats_the_list_on_screen(bot):
    bot.claude(ROUTED["10"], ("demo_pack_list", {"guessed": [], "not_included": []}))
    bot.say(SAID["10"])
    bot.claude(ROUTED["10a"], EXTRACTED["10a"])
    bot.say(SAID["10a"])
    assert card_lines(bot) == ["🛒 Shopping · new", "milk · × 1"]


# --- 11, 12: it, and a correction that undoes only the mistake ------------------------------------------------------
def test_11_it_is_the_item_mentioned_last(bot):
    bot.claude(route("shopping"), shop_add_all("milk", "bread rolls"))
    bot.say("add milk and bread rolls")
    bot.claude(EXTRACTED["11"])
    bot.say(SAID["11"])
    assert card_lines(bot) == ["🛒 Shopping · new", "milk · × 1", "bread rolls · × 2"]


def test_12_no_undoes_the_change_it_corrects_and_only_that(bot):
    bot.claude(route("shopping"), shop_add_all("milk", "bread rolls"))
    bot.say("add milk and bread rolls")
    bot.claude(EXTRACTED["11"])
    bot.say(SAID["11"])
    bot.claude(EXTRACTED["12"])
    bot.say(SAID["12"])
    assert card_lines(bot) == ["🛒 Shopping · new", "milk · × 2", "bread rolls · × 1"]


# --- 13, 14 --------------------------------------------------------------------------------------------------------
def test_13_deleted_is_only_said_when_it_really_is(bot, monkeypatch):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc"}], "guessed": [], "not_included": []}))
    bot.say("add zinc to my pills")
    press(bot)
    bot.claude(ROUTED["13"], EXTRACTED["13"])
    bot.say(SAID["13"])
    assert card(bot)[1] == ["Delete for good", "Cancel"]

    kept = pills_store.db_delete
    monkeypatch.setattr(pills_store, "db_delete", lambda conn, pill_id: None)  # the delete goes nowhere
    monkeypatch.setattr(confirm, "log_error", _quiet)
    pressed = bot.Press(open_cards()[-1].id)
    run(confirm.on_save(pressed))
    assert pressed.cards[-1].text.startswith("⚠️ That didn't save: pl1 is still there") and len(pills(bot)) == 1

    monkeypatch.setattr(pills_store, "db_delete", kept)
    bot.claude(ROUTED["13"], EXTRACTED["13"])
    bot.say(SAID["13"])
    assert press(bot) == "🗑️ Deleted **Zinc** and its history." and pills(bot) == []


async def _quiet(*args, **options):
    return None


def test_14_a_message_with_nothing_to_do_gets_no_reply(bot):
    bot.claude(ROUTED["14"])
    ctx, _ = bot.say(SAID["14"])
    assert bot.sent == [] and ctx.replies == [] and open_cards() == []
    assert bot.reactions == [(SAID["14"], "✅")], "a tick, so I know it was received"


# --- the list itself ---------------------------------------------------------------------------------------------------
def test_every_golden_conversation_in_the_fixture_file_has_a_test_here():
    ids = {entry["golden"] for entry in [*FIXTURES["router"], *FIXTURES["extraction"]]}
    tested = {name.split("_")[1] for name in globals() if name.startswith("test_") and name.split("_")[1][0].isdigit()}
    assert ids <= tested, f"no test for: {sorted(ids - tested)}"
    assert {"1", "1a", "1b", "1c", "1d", "2", "2a", "2b", "3", "4", "5", "6", "7", "8", "9", "10", "10a", "11", "12", "13", "14"} == tested
