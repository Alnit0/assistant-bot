"""The golden conversations: the acceptance test for how the bot talks (the conversation
standard, section 6). Each is run end to end, offline: Claude's part is replayed from what
the real API last returned for it (evals/fixtures/golden.json), and everything else is the
bot's own code against a temporary database.

A conversation the bot can't yet hold is marked `gap` with what is missing. It must fail
until that is built (strict), so the list of gaps here is always the true one. Every change
must keep the others passing.
"""
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import actions, confirm, database, day, timeinput
from tasks.pills import checklist
from core.actions import Request
from tests import demo
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
    # The name is kept as typed; a re-recording may come back with either capital, so that alone isn't judged
    assert lines[0] == "💊 Pills · new" and lines[1].lower() == "**vitamin d** (1 tablet) · daily at `8:00 am` · *with food*"
    assert "❓" not in bot.sent[-1][1].text and buttons == ["Save", "Cancel"]
    assert pills(bot) == [], "nothing is saved before Save"


def test_1a_a_course_with_every_detail_and_no_question_mark(bot):
    bot.claude(ROUTED["1a"], EXTRACTED["1a"])
    bot.say(SAID["1a"])
    today = day.today()
    dates = timeinput.format_dates(today + timedelta(days=1), today + timedelta(days=7))
    # The name is kept as typed; a re-recording may come back with either capital, so that alone isn't judged
    assert card(bot)[0][1].lower() == f"**course a** · 3× daily, at least 3h apart, first dose when ready · *with food* · {dates}".lower()
    assert "❓" not in bot.sent[-1][1].text


def test_1b_a_brief_request_gets_a_card_with_the_defaults(bot):
    bot.claude(ROUTED["1b"], EXTRACTED["1b"])
    bot.say(SAID["1b"])
    lines = card(bot)[0]
    assert lines[0] == "💊 Pills · new" and lines[1].lower() == "**vitamin d** · daily, any time"


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
    assert bot.deleted == [first] and card(bot)[0][1].lower() == "**iron** · daily at `8:00 am`", "replaced, and no longer a guess"


@gap("questions on the card are not built, so there is no 8:00 pm button to tap before correcting")
def test_2a_after_answering_a_question_a_correction_still_replaces_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    assert "8:00 pm" in card(bot)[1]


def test_2b_straight_after_save_a_correction_is_a_change_card_for_what_was_just_saved(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Iron", "times": "8pm"}], "guessed": [], "not_included": []}))
    bot.say("add iron to my pills at 8pm")
    assert press(bot) == "✅ Saved · 💊 **Iron** · daily at `8:00 pm`"
    # Straight after the Save: pills answered a moment ago, so this goes to pills with no router
    bot.claude(EXTRACTED["2b"])
    bot.say(SAID["2b"], straight_after=True)
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
    # Straight after the timer started: timers answered a moment ago, so no router
    bot.claude(EXTRACTED["4"])
    bot.say(SAID["4"], straight_after=True)
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
    assert bot.reactions == [], "and no reaction is left on it: the 👀 coming off says it was read"


def test_15_a_remark_gets_no_reply(bot):
    bot.claude(ROUTED["15"])
    ctx, handled = bot.say(SAID["15"])
    assert bot.sent == [] and ctx.replies == [] and bot.reactions == []
    assert handled.done, "and it is not handed on to anything that would answer it"


def test_16_a_lists_name_on_its_own_is_the_list_itself(bot):
    run(demo._save("shopping", 1, [{"item": "milk", "quantity": 2}]))
    bot.claude()  # no request may be made
    ctx, _ = bot.say("shopping list")
    assert bot.sent[-1][1].text == "## 🛒 Shopping list\n- **milk** × 2" and bot.requests == [] and bot.chats == []
    assert ctx.replies == [], "the list, and not a word about it or an offer after it"
    bot.say("my pills")
    assert bot.sent[-1][1].text.startswith("## 💊 Pills") and bot.requests == []


# --- the list itself ---------------------------------------------------------------------------------------------------
def test_every_golden_conversation_in_the_fixture_file_has_a_test_here():
    ids = {entry["golden"] for entry in [*FIXTURES["router"], *FIXTURES["extraction"]]}
    tested = {name.split("_")[1] for name in globals() if name.startswith("test_") and name.split("_")[1][0].isdigit()}
    assert ids <= tested, f"no test for: {sorted(ids - tested)}"
    assert {"1", "1a", "1b", "1c", "1d", "2", "2a", "2b", "3", "4", "5", "6", "7", "8", "9", "10", "10a", "11", "12", "13", "14", "15", "16", "17", "18", "18a", "18b"} == tested


# --- QA 2026-10-10: "already so" ends in the task's own line, whichever way it was found --------------------
ZINC_AS_IT_IS = "💊 **Zinc** is already in your pills with these settings\n💊 **Zinc** · daily, any time"


def _with_zinc(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc"}], "guessed": [], "not_included": []}))
    bot.say("add zinc to my pills")
    press(bot)


def test_adding_what_is_there_with_the_same_details_names_it_and_shows_it(bot):
    _with_zinc(bot)
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "zinc", "per_day": 1}], "guessed": [], "not_included": []}))
    bot.say("add zinc to my pills, once a day")
    assert bot.sent[-1][1].text == ZINC_AS_IT_IS and bot.sent[-1][1].rows == (), "a line, not a card"


def test_a_change_that_changes_nothing_says_the_same_line(bot):
    _with_zinc(bot)
    bot.claude(route("pills"), ("pill_edit", {"pills": [{"pill": "zinc", "per_day": 1}], "guessed": [], "not_included": []}))
    bot.say("make zinc once a day")
    assert bot.sent[-1][1].text == ZINC_AS_IT_IS and bot.sent[-1][1].rows == ()


def test_a_decline_because_it_is_already_so_says_the_same_line_not_the_plain_one(bot):
    _with_zinc(bot)
    declined = {"why": "already_so", "about": "Zinc", "reason": "Zinc already exists with identical specifications"}
    bot.claude(route("pills"), ("none", declined))
    bot.say("add zinc to my pills, once a day")
    assert bot.sent[-1][1].text == ZINC_AS_IT_IS


def test_only_when_the_task_cannot_name_the_thing_is_the_plain_line_said(bot):
    _with_zinc(bot)
    bot.claude(route("pills"), ("none", {"why": "already_so", "reason": "nothing to change"}))
    bot.say("leave my pills as they are")
    assert bot.sent[-1][1].text == "✅ That's already how it is: there is nothing to change."


# --- 17: saying a pill was taken ticks it off today's checklist -----------------------------------------------
def _zinc_on_the_checklist(bot):
    _with_zinc(bot)
    return run(checklist.post(bot.owner.id, 100))


def _ticked_off(bot, sheet):
    said = bot.sent[-1][1].text
    assert said.startswith("✅ **Zinc** · taken ") and said.endswith(" · nothing left to take today"), said
    last = [text for message_id, text in bot.edited if message_id == sheet][-1]
    assert "✅ **Zinc** · taken " in last and "▰▰▰▰▰ 1 of 1" in last, "the checklist itself, edited in place"
    assert sheet + 1 in bot.deleted, "its own Taken / Skip message goes"
    (dose,) = run(checklist.view(bot.owner.id))[1]
    assert dose.occurrence.state == "done"


def test_17_saying_i_have_taken_it_ticks_it_off_on_todays_checklist(bot):
    sheet = _zinc_on_the_checklist(bot)
    bot.claude(ROUTED["17"], EXTRACTED["17"])
    bot.say(SAID["17"])
    _ticked_off(bot, sheet)


def test_17_a_message_that_names_one_of_my_pills_is_never_dropped_as_a_remark(bot):
    # QA 2026-10-10: this very sentence was routed as a remark and got no reply. With logging
    # built, silence would look like success: a message that names a pill goes to pills
    sheet = _zinc_on_the_checklist(bot)
    bot.claude(("route", {"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}), EXTRACTED["17"])
    bot.say(SAID["17"])
    _ticked_off(bot, sheet)


def test_a_remark_that_names_nothing_of_mine_still_gets_no_reply(bot):
    _zinc_on_the_checklist(bot)
    before = len(bot.sent)
    bot.claude(("route", {"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}))
    bot.say("shopping is boring")
    assert len(bot.sent) == before


def test_a_message_that_names_a_pill_and_asks_nothing_clear_is_answered_not_dropped(bot):
    _zinc_on_the_checklist(bot)
    bot.claude(
        ("route", {"kind": "nothing", "tasks": [], "confidence": "high", "chat_part": ""}),
        ("none", {"why": "unclear", "reason": "a remark about zinc"}),
    )
    bot.say("zinc is a funny word")
    assert bot.sent[-1][1].text == "🤔 I didn't understand that.", "said, so that silence never passes for done"


# --- going live, 2026-10-11: the exact sequence, replayed with the clock at 10:57 pm -------------------------
PILLS = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "pills.json").read_text(encoding="utf-8"))
LOGGED = {entry["message"]: tuple(entry["recorded"]) for entry in PILLS["extraction"] if entry.get("note", "").startswith("going live")}
NUMBERED = {entry["message"]: tuple(entry["recorded"]) for entry in PILLS["extraction"] if entry.get("note", "").startswith("dose number")}
GENERAL = json.loads((Path(__file__).parent.parent / "evals" / "fixtures" / "general.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("corrected", ["I took it at 9am", "I took Pill A at 9am"])
def test_a_late_log_is_asked_about_then_a_time_said_straight_after_corrects_it(bot, dev_clock, corrected):
    from datetime import time

    tonight = day.at(day.today() + timedelta(days=1), time(22, 57))
    dev_clock.advance_to(tonight)
    main = {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm"}
    bot.claude(route("pills"), ("pill_add", {"pills": [main], "guessed": [], "not_included": []}))
    bot.say("add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm")
    press(bot)

    bot.claude(route("pills"), LOGGED["Taken my Pill A"])
    bot.say("Taken my Pill A")
    lines, buttons = card(bot)
    assert lines[:3] == ["💊 Pills · change", "**Pill A** (dose 1 of 3) · taken 10:57 pm", "⚠️ That's after the latest time, 4:00 pm. Log it anyway?"]
    assert buttons == ["Log it", "Cancel"], "asked first, on a card"
    assert press(bot) == "✅ **Pill A** (dose 1 of 3) · taken 10:57 pm · nothing left to take today", "and no dose is promised for 1:57 am"

    bot.claude(route("pills"), LOGGED[corrected])
    bot.say(corrected)
    assert bot.sent[-1][1].text == "✏️ **Pill A** (dose 1 of 3) · taken 10:57 pm → 9:00 am · nothing left to take today"
    assert bot.sent[-1][1].rows == (), "a correction of today's dose is done at once: old → new, no card"


# --- 18: a follow-up sticks to the task that just answered, and chat never acknowledges ----------------------
# QA 2026-10-12, on --dev: "Taken my pill A", then "I took it at 9pm" went to plain chat, which said "Got it. So
# you took it about 2 hours and 49 minutes ago." Nothing was corrected, and it read as if it had been
MAIN = {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm"}
CORRECTED = "✏️ **Pill A** (dose 1 of 3) · taken 11:49 pm → 9:00 pm · nothing left to take today"
PICKED_18 = "**Pill A** (dose 1 of 3) · taken 11:49 pm → 9:00 pm ❓"
NOT_UNDERSTOOD = "🤔 I didn't understand that."
CANT_LOG = "I can't log that yet."


def _taken_at_11_49(bot, dev_clock):
    from datetime import time

    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(23, 49)))
    bot.claude(route("pills"), ("pill_add", {"pills": [MAIN], "guessed": [], "not_included": []}))
    bot.say("add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm")
    press(bot)
    bot.claude(route("pills"), LOGGED["Taken my Pill A"])
    bot.say("Taken my pill A")
    assert press(bot) == "✅ **Pill A** (dose 1 of 3) · taken 11:49 pm · nothing left to take today"
    return len(bot.requests)


def _no_chat(bot):
    assert bot.chats == [], "plain chat was never asked"
    assert not any("Got it" in shown.text or "So you took" in shown.text for _, shown in bot.sent)


def test_18_i_took_it_at_9pm_straight_after_a_log_goes_to_that_task_and_corrects_the_dose(bot, dev_clock):
    _corrects_the_dose_just_logged(bot, dev_clock, "18")


def test_18a_i_had_it_at_9pm_does_the_same(bot, dev_clock):
    _corrects_the_dose_just_logged(bot, dev_clock, "18a")


def test_18b_it_was_9pm_actually_does_the_same(bot, dev_clock):
    _corrects_the_dose_just_logged(bot, dev_clock, "18b")


def _corrects_the_dose_just_logged(bot, dev_clock, golden):
    before = _taken_at_11_49(bot, dev_clock)
    bot.claude(EXTRACTED[golden])  # one request, for pills: the router is not asked
    bot.say(SAID[golden], straight_after=True)
    assert bot.sent[-1][1].text == CORRECTED
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests[before:]] == [("pills", True)]
    _no_chat(bot)


def test_18_more_than_five_minutes_later_the_router_is_asked_and_it_is_still_a_correction(bot, dev_clock):
    _taken_at_11_49(bot, dev_clock)
    dev_clock.advance(timedelta(minutes=6))
    bot.claude(ROUTED["18"], EXTRACTED["18"])
    bot.say(SAID["18"], straight_after=True)  # as it comes: by now nothing sticks
    # Still a correction (9 pm is before the dose last taken), but nothing anchors "it" any more:
    # the pill the code picked is shown first, with ❓, and Save does it
    assert PICKED_18 in bot.sent[-1][1].text.splitlines() and card(bot)[1] == ["Save", "Cancel"]
    assert press(bot) == CORRECTED
    _no_chat(bot)


def test_a_short_message_for_something_else_straight_after_is_read_afresh(bot, dev_clock):
    before = _taken_at_11_49(bot, dev_clock)
    bot.claude(("not_this", {"reason": "a general question"}), ROUTED["5"])
    asked, _ = bot.say("what's the capital of France?", straight_after=True)
    assert asked.replies == ["Paris."] and len(bot.requests) == before + 2, "pills said it wasn't theirs; then the router"
    # And after chat has answered, nothing sticks to pills any more
    bot.claude(ROUTED["5"])
    again, _ = bot.say("and of Spain?", straight_after=True)
    assert again.replies == ["Paris."] and len(bot.requests) == before + 3, "the router alone: no request to pills first"


@pytest.mark.parametrize("kind", ["chat", "nothing"])
def test_a_report_of_something_done_that_no_task_owns_is_neither_chat_nor_silence(bot, kind):
    bot.claude(("route", {"kind": kind, "tasks": [], "confidence": "high", "reports_doing": True, "chat_part": ""}))
    bot.say("I went for a run at 7 this morning")
    assert bot.sent[-1][1].text == CANT_LOG
    _no_chat(bot)


def test_the_run_as_the_router_really_answered_it_is_told_it_cannot_be_logged(bot):
    run_ = next(entry for entry in GENERAL["router"] if entry["message"] == "I went for a run at 7 this morning")
    bot.claude(("route", run_["recorded"]))
    bot.say(run_["message"])
    assert [shown.text for _, shown in bot.sent] == [CANT_LOG]
    _no_chat(bot)


def test_dose_1_at_9am_as_claude_really_read_it_is_about_dose_1_with_nothing_left_out(bot, dev_clock):
    # QA 2026-10-12: it answered about dose 2 and said "⚠️ Not included: dose 1 of"
    from datetime import time

    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(0, 32)))
    bot.claude(route("pills"), ("pill_add", {"pills": [MAIN], "guessed": [], "not_included": []}))
    bot.say("add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm")
    press(bot)
    bot.claude(route("pills"), LOGGED["Taken my Pill A"])
    bot.say("Taken my pill A")
    dev_clock.advance_to(day.at(day.today(), time(9, 30)))
    bot.claude(route("pills"), LOGGED["I took Pill A at 9am"])
    bot.say("I took Pill A at 9am")
    assert bot.sent[-1][1].text.startswith("✅ **Pill A** (dose 2 of 3) · taken 9:00 am")
    bot.claude(route("pills"), NUMBERED["I took dose 1 of Pill A at 9am"])
    bot.say("I took dose 1 of Pill A at 9am")
    card = bot.sent[-1][1].text
    assert "**Pill A** (dose 1 of 3) · taken 12:32 am → 9:00 am" in card and "Not included" not in card
    assert "That's the same time as dose 2, taken 9:00 am. Log it anyway?" in card
    assert press(bot).startswith("✏️ **Pill A** (dose 1 of 3) · taken 12:32 am → 9:00 am")


def test_an_acknowledgement_from_chat_is_never_sent_and_the_message_is_routed_again(bot, dev_clock):
    from core import llm

    _taken_at_11_49(bot, dev_clock)
    dev_clock.advance(timedelta(minutes=6))
    bot.chat_answers.append("Got it. So you took it about 2 hours and 49 minutes ago.")
    chat = ("route", {"kind": "chat", "tasks": [], "confidence": "high", "reports_doing": False, "chat_part": ""})
    bot.claude(chat, ROUTED["18"], EXTRACTED["18"])  # the router's slip, chat's slip, then the second look
    bot.say(SAID["18"], straight_after=True)
    assert PICKED_18 in bot.sent[-1][1].text.splitlines(), "six minutes on: the pill it picked is shown first"
    assert press(bot) == CORRECTED
    assert not any("Got it" in shown.text for _, shown in bot.sent), "what chat wrote was never shown"
    assert llm.history_for(100) == [], "nor kept as something chat said"


def test_an_acknowledgement_from_chat_with_no_task_to_own_it_gets_the_neutral_line(bot):
    bot.chat_answers.append("Noted! Well done on the run.")
    chat = ("route", {"kind": "chat", "tasks": [], "confidence": "high", "reports_doing": False, "chat_part": ""})
    bot.claude(chat, chat)
    bot.say("I went for a run at 7 this morning")
    assert [shown.text for _, shown in bot.sent] == [CANT_LOG]


# --- a Discord reply to a message a task posted goes to that task first (asked for 2026-10-12) ----------------
ADDED = lambda name: ("pill_add", {"pills": [{"name": name}], "guessed": [], "not_included": []})  # noqa: E731
TOOK_IT = ("pill_log", {"doses": [{"pill": "@that", "did": "taken"}], "guessed": [], "not_included": []})


def _two_pills_and_zinc_logged(bot):
    """Zinc and Iron on today's checklist, each with its own Taken / Skip message, and Zinc
    logged last. Returns Iron's message and how many requests were made so far."""
    from tasks.pills import checklist as pills_checklist

    for name in ("Zinc", "Iron"):
        bot.claude(route("pills"), ADDED(name))
        bot.say(f"add {name} to my pills, once a day")
        press(bot)
    run(pills_checklist.post(bot.owner.id))
    bot.claude(route("pills"), ("pill_log", {"doses": [{"pill": "zinc", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("took my zinc")
    _, listed, today_ = run(pills_checklist.view(bot.owner.id))
    iron = next(dose for dose in listed if dose.pill.plan.name == "Iron")
    held = run(database.run(pills_store.db_messages, bot.owner.id, today_))
    return next(message.message_id for message in held if message.occurrence_id == iron.occurrence.id), len(bot.requests)


def test_a_reply_to_a_doses_message_goes_to_pills_first_and_means_that_pill(bot):
    iron_message, before = _two_pills_and_zinc_logged(bot)
    bot.claude(TOOK_IT)  # one request, for pills: the router is not asked
    bot.say("took it", reply_to=iron_message)
    assert bot.sent[-1][1].text.startswith("✅ **Iron** · taken"), "the pill whose message I replied to, not the one logged last"
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests[before:]] == [("pills", True)]
    _no_chat(bot)


def test_a_reply_that_is_not_about_the_tasks_message_is_handed_back_to_the_router(bot):
    iron_message, before = _two_pills_and_zinc_logged(bot)
    bot.claude(("not_this", {"reason": "a general question"}), ROUTED["5"])
    asked, _ = bot.say("what's the capital of France?", reply_to=iron_message)
    assert asked.replies == ["Paris."] and len(bot.requests) == before + 2, "pills said it wasn't its own; then the router"


def test_a_reply_to_a_timers_card_goes_to_timers_first_however_old_the_card(bot):
    for label in ("tea", "dinner"):
        run(timers_plain.start(Request(bot.owner, 100, "start"), {"timers": [{"duration": "5m", "label": label}]}, frozenset()))
    tea, dinner = timers(bot)
    bot.claude(("timer_change", {"which": "@that", "action": "extend", "duration": "2m", "guessed": [], "not_included": []}))
    bot.say("give it 2 more", reply_to=tea.message_id)
    tea, dinner = timers(bot)
    assert tea.left(timers_plain.utc_now()) == pytest.approx(420, abs=5) and dinner.left(timers_plain.utc_now()) == pytest.approx(300, abs=5)
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests] == [("timers", True)], "no router: the card says whose it is"


def test_give_it_2_more_as_a_reply_to_the_line_that_said_dinner_was_paused_is_dinners(bot):
    # QA 2026-10-12 (#545), this exact sequence: several timers going; `pause` as a reply to
    # dinner's card; then "Give it 2 more" as a reply to "⏸️ Paused: dinner". That line was no
    # task's own, so the router was asked and the timer was the newest one by luck
    from tasks import timers as timers_words
    from tests.test_conversation import traces

    for label in ("tea", "dinner", "eggs"):
        run(timers_plain.start(Request(bot.owner, 100, "start"), {"timers": [{"duration": "5m", "label": label}]}, frozenset()))
    tea, dinner, eggs = timers(bot)

    async def confirm(text):
        bot.next_id += 1
        bot.bot_messages.append(bot.next_id)
        return SimpleNamespace(id=bot.next_id)

    typed = SimpleNamespace(channel_id=100, reply_target_id=dinner.message_id, confirm=confirm)
    run(timers_words.pause_reply(typed, SimpleNamespace(id=dinner.message_id)))
    paused_line = bot.next_id
    # Something else is done since, so dinner is not the timer spoken of last
    bot.claude(route("timers"), ("timer_change", {"which": f"t{eggs.id}", "action": "extend", "duration": "1m", "guessed": [], "not_included": []}))
    bot.say("give eggs 1 more")
    before = len(bot.requests)

    bot.claude(("timer_change", {"which": "@that", "action": "extend", "duration": "2m", "guessed": ["duration"], "not_included": []}))
    bot.say("Give it 2 more", reply_to=paused_line)
    assert bot.sent[-1][1].text == "➕ Added 2m to dinner\n❓ I guessed how much time to add."
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests[before:]] == [("timers", True)], "no router"
    tea, dinner, eggs = timers(bot)
    # (the clock here is the real one, and the test takes a few seconds)
    assert dinner.remaining_s == pytest.approx(420, abs=30) and tea.left(timers_plain.utc_now()) == pytest.approx(300, abs=30)
    assert eggs.left(timers_plain.utc_now()) == pytest.approx(360, abs=30), "eggs was spoken of last, and is left alone"
    assert "reply to timers' message: it goes to timers first, and the router is not asked" in traces()[-1]["why"]
    # The line that said so is dinner's too: a reply to it means dinner again
    bot.claude(("timer_change", {"which": "@that", "action": "resume", "guessed": [], "not_included": []}))
    bot.say("carry on", reply_to=bot.sent[-1][0])
    assert bot.sent[-1][1].text.startswith("▶️ Resumed: dinner")


def test_with_several_timers_going_and_none_named_it_asks_which_and_changes_nothing(bot, dev_clock):
    for label in ("tea", "dinner"):
        run(timers_plain.start(Request(bot.owner, 100, "start"), {"timers": [{"duration": "30m", "label": label}]}, frozenset()))
    dev_clock.advance(timedelta(minutes=10))  # nothing was said about either of them lately
    bot.claude(route("timers"), ("timer_change", {"which": f"t{timers(bot)[1].id}", "action": "extend", "duration": "2m", "guessed": ["which"], "not_included": []}))
    bot.say("give it 2 more")
    asked = bot.sent[-1][1].text.splitlines()
    assert asked[0] == "⚠️ Which timer? Say its name." and len(asked) == 3
    assert asked[1].startswith("⏱️ **tea** · ") and asked[2].startswith("⏱️ **dinner** · ") and asked[2].endswith(" left")
    assert [timer.left(timers_plain.utc_now()) for timer in timers(bot)] == [pytest.approx(1200, abs=30)] * 2, "neither was touched"


def test_a_reply_to_a_message_no_task_posted_is_routed_as_before(bot):
    bot.claude(ROUTED["5"])
    asked, _ = bot.say("what's the capital of France?", reply_to=987654)
    assert asked.replies == ["Paris."] and [each.purpose for each in bot.requests] == ["router"], "the router alone"


def test_each_task_says_which_messages_are_its_own(bot):
    run(timers_plain.start(Request(bot.owner, 100, "start"), {"timers": [{"duration": "5m", "label": "tea"}]}, frozenset()))
    (tea,) = timers(bot)
    run(timers_plain.change(Request(bot.owner, 100, "cancel"), {"which": f"t{tea.id}", "action": "cancel"}, frozenset()))
    (timers_entry,) = timers_task.entries()
    (pills_entry,) = pills_task.entries()
    assert run(timers_entry.owns(tea.message_id)) is True, "a timer's card is the timer's even once it has ended"
    assert run(timers_entry.owns(987654)) is False and run(pills_entry.owns(tea.message_id)) is False


# --- an unnamed pill is only logged straight away with an anchor ------------------------------------------
USUAL = next(tuple(entry["recorded"]) for entry in PILLS["extraction"] if entry["message"] == "took the usual one")


def test_took_the_usual_one_as_claude_really_read_it_is_shown_on_a_card_with_the_pill_it_picked(bot, dev_clock):
    iron_message, before = _two_pills_and_zinc_logged(bot)
    dev_clock.advance(timedelta(minutes=10))  # nothing was said about a pill lately
    bot.claude(route("pills"), USUAL)
    bot.say("took the usual one")
    lines, buttons = card(bot)
    assert lines[0] == "💊 Pills · change" and lines[1].startswith("**Iron** · taken ") and lines[1].endswith(" ❓"), "the one pill with a dose left, as a guess"
    assert buttons == ["Save", "Cancel"]


def test_it_straight_after_a_log_is_that_pill_and_is_done_at_once(bot):
    iron_message, before = _two_pills_and_zinc_logged(bot)
    bot.claude(("pill_log", {"doses": [{"pill": "@that", "did": "not_taken"}], "guessed": [], "not_included": []}))
    bot.say("no I didn't take it", straight_after=True)
    assert any(shown.text.startswith("↩️ **Zinc** · no longer ticked off") for _, shown in bot.sent), "the pill the last pills message was about: no card"
    assert not any("Pills · change" in shown.text for _, shown in bot.sent)
