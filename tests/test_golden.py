"""The golden conversations: the acceptance test for how the bot talks (the conversation
standard, section 6). Each is run end to end, offline: Claude's part is replayed from what
the real API last returned for it (evals/fixtures/golden.json), and everything else is the
bot's own code against a temporary database.

A conversation the bot can't yet hold is marked `gap` with what is missing. It must fail
until that is built (strict), so the list of gaps here is always the true one. Every change
must keep the others passing.
"""
import json
from datetime import time, timedelta
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
def bot(world, monkeypatch, dev_clock):  # noqa: F811
    """The world of the conversation tests with the real pills and timers beside the demo lists,
    at noon tomorrow: never by the real time of day, which near midnight turns a minute or two
    into a new day (question 39: two of these failed once in a run at about 12:08 am)."""
    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(12, 0)))
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


def answer(bot, label):
    """Press one of the answers under the latest card's question: the card as it then reads (it is rewritten in place)."""
    stored = open_cards()[-1]
    index = next(at for at, choice in enumerate(stored.question["choices"]) if choice["label"] == label)
    pressed = bot.Press(f"{stored.id}:{index}")
    run(confirm.on_answer(pressed))
    shown = pressed.cards[-1]
    bot.sent.append((bot.sent[-1][0], shown))
    return shown.text.splitlines(), [button.label for row in shown.rows for button in row]


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


def test_1c_a_time_that_could_be_morning_or_evening_is_asked_on_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    lines, buttons = card(bot)
    assert buttons == ["8:00 am", "8:00 pm", "Cancel"], "a button per likely answer, and no Save until it is answered"
    assert "morning or the evening" in "\n".join(lines)
    assert lines[:3] == ["💊 Pills · new", "**iron** · daily at ❔", "Is that 8:00 in the morning or the evening?"]
    assert pills(bot) == []


def test_1d_a_missing_second_time_is_asked_on_the_card_with_the_rest_filled_in(bot):
    bot.claude(ROUTED["1d"], EXTRACTED["1d"])
    bot.say(SAID["1d"])
    assert open_cards() and open_cards()[-1].status == "open", "a card, with what was understood"
    lines, buttons = card(bot)
    assert "**magnesium**" in lines[1] and "Save" not in buttons
    assert lines[1:4] == ["**magnesium** · 2× daily, any time", "❔ times · 8:00 am is 1 time for 2 doses a day", "What time is the other dose?"]
    assert buttons == ["8:00 pm", "Cancel"], "the one likely answer; any other is typed"
    assert answer(bot, "8:00 pm")[0][1] == "**magnesium** · daily at `8:00 am`, `8:00 pm`" and card(bot)[1] == ["Save", "Cancel"]
    assert press(bot).startswith("✅ Saved") and [pill.plan.schedule.per_day for pill in pills(bot)] == [2]


def test_1d_a_typed_answer_that_gives_only_the_new_time_is_the_other_dose_s_time(bot):
    # The self-test of 2026-10-13, with real requests: "9pm" came back as times [9:00 pm] alone, the
    # first time was replaced by it, and the card asked for "the other dose" again
    from tasks.pills import plain as pills_plain

    bot.claude(ROUTED["1d"], EXTRACTED["1d"])
    bot.say(SAID["1d"])
    assert confirm.asked_about(open_cards()[-1]) == ("times",), "the card knows which field its question is about"
    bot.claude(("pill_add", {"pills": [{"name": "magnesium", "times": ["9:00 pm"], "per_day": 2}], "guessed": [], "not_included": []}))
    bot.say("9pm")
    lines, buttons = card(bot)
    assert lines[1] == "**magnesium** · daily at `8:00 am`, `9:00 pm`" and buttons == ["Save", "Cancel"], "the answer filled in what was missing"
    # Handed over whole, it is the same card
    held = [{"name": "magnesium", "times": ["8:00 am"], "per_day": 2}]
    both = pills_plain.overlay(held, [{"name": "magnesium", "times": ["8:00 am", "9:00 pm"], "per_day": 2}], "name", ("times",))[0]
    assert both[0]["times"] == ["8:00 am", "9:00 pm"]
    # With no question about times on the card, a time said is the new time: a correction, as before
    assert pills_plain.overlay(held, [{"name": "magnesium", "times": ["9:00 pm"]}], "name")[0][0]["times"] == ["9:00 pm"]
    assert pills_plain.overlay(held, [{"name": "magnesium", "times": ["9:00 pm"]}], "name", ("pill",))[0][0]["times"] == ["9:00 pm"]
    # Every dose already has its time: nothing is missing, so it is a replacement
    full = [{"name": "magnesium", "times": ["8:00 am", "8:00 pm"], "per_day": 2}]
    assert pills_plain.overlay(full, [{"name": "magnesium", "times": ["9:00 pm"]}], "name", ("times",))[0][0]["times"] == ["9:00 pm"]


# --- 2: correcting ------------------------------------------------------------------------------------
def test_2_a_correction_in_chat_replaces_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    first = bot.sent[-1][0]
    bot.claude(EXTRACTED["2"])
    bot.say(SAID["2"])
    assert bot.deleted == [first] and card(bot)[0][1].lower() == "**iron** · daily at `8:00 am`", "replaced, and no longer a guess"


def test_2a_after_answering_a_question_a_correction_still_replaces_the_card(bot):
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    assert "8:00 pm" in card(bot)[1]
    asked = bot.sent[-1][0]
    lines, buttons = answer(bot, "8:00 pm")
    assert lines[:2] == ["💊 Pills · new", "**iron** · daily at `8:00 pm`"] and buttons == ["Save", "Cancel"], "answered in place: the same card, now with Save"
    assert bot.deleted == [] and pills(bot) == [], "and nothing is saved by answering"
    bot.claude(EXTRACTED["2"])
    bot.say(SAID["2"])
    assert bot.deleted == [asked] and card(bot)[0][1].lower() == "**iron** · daily at `8:00 am`", "the correction replaces the card, as before"
    assert press(bot) == "✅ Saved · 💊 **iron** · daily at `8:00 am`"


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
    assert not any("❓" in line for line in lines), "what was just saved is known, not guessed (G3)"


def test_2b_the_correction_is_about_the_card_just_saved_not_whichever_pill_changed_last(bot):
    # Two pills; the first is saved last of all, then corrected. "It" is the saved card's pill
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Iron", "times": "8pm"}], "guessed": [], "not_included": []}))
    bot.say("add iron to my pills at 8pm")
    press(bot)
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc", "times": "7am"}], "guessed": [], "not_included": []}))
    bot.say("add zinc to my pills at 7am")
    press(bot)
    bot.claude(route("pills"), ("pill_edit", {"pills": [{"pill": "iron", "notes": "with food"}], "guessed": [], "not_included": []}))
    bot.say("iron is with food")
    assert press(bot).startswith("✅ Updated")
    bot.claude(("pill_edit", {"pills": [{"pill": "@that", "times": ["9:00 pm"]}], "guessed": [], "not_included": []}))
    bot.say("no, I meant 9pm", straight_after=True)
    lines, buttons = card(bot)
    assert lines[1] == "**Iron**" and "`8:00 pm` → daily at `9:00 pm`" in lines[2] and not any("❓" in line for line in lines)


def test_2b_once_something_else_was_done_the_saved_card_is_forgotten_and_it_is_a_guess_again(bot):
    from core import llm
    from tests.test_pills_reminders import INBOX  # noqa: F401

    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Iron", "times": "8pm"}], "guessed": [], "not_included": []}))
    ctx, _ = bot.say("add iron to my pills at 8pm")
    press(bot)
    assert llm.just_saved(ctx.channel_id) is not None, "straight after the Save, the card is known"
    llm.task_answered(ctx.channel_id, "pills")  # anything else the task did since (a dose logged, a list shown)
    assert llm.just_saved(ctx.channel_id) is None, "then the Save is no longer the last thing, and the card is not what “it” means"
    llm.task_answered(ctx.channel_id, "pills", saved=7)
    assert llm.just_saved(ctx.channel_id, llm.clock.now() + llm.ANSWER_STICKS + llm.timedelta(seconds=1)) is None, "nor after a few minutes"


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
    assert {"1", "1a", "1b", "1c", "1d", "2", "2a", "2b", "3", "4", "5", "6", "7", "8", "9", "10", "10a", "11", "12", "13", "14", "15", "16", "17", "18", "18a", "18b", "19", "19a", "20", "21", "22", "23", "23a", "24", "25", "2c", "18c", "26", "27", "27a", "28", "28a"} == tested


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
    assert lines[:3] == ["💊 Pills · change", "**Pill A** (dose 1 of 3) · taken 10:57 pm", "⚠️ Dose 1 was missed (due 8:00 am). That's after the latest time, 4:00 pm. Log it as taken now?"]
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


def test_a_reply_to_the_line_that_said_zinc_was_taken_goes_to_pills_first_and_corrects_that_dose(bot, dev_clock):
    iron_message, before = _two_pills_and_zinc_logged(bot)
    zinc_line = next(message_id for message_id, shown in bot.sent if shown.text.startswith("✅ **Zinc** · taken"))
    bot.claude(route("pills"), ("pill_log", {"doses": [{"pill": "iron", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("took my iron")
    dev_clock.advance(timedelta(minutes=10))
    before = len(bot.requests)
    bot.claude(("pill_log", {"doses": [{"pill": "@that", "did": "not_taken"}], "guessed": [], "not_included": []}))
    bot.say("actually I didn't", reply_to=zinc_line)
    assert any(shown.text.startswith("↩️ **Zinc** · no longer ticked off") for _, shown in bot.sent), "Zinc, though Iron was logged last and long ago"
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests[before:]] == [("pills", True)], "no router: the line is pills'"
    assert not any("Pills · change" in shown.text for _, shown in bot.sent), "and no card: the reply is the anchor"


# --- questions on the card (G1): the buttons, the words, and what is kept -------------------------------
def test_a_card_that_asks_has_a_blurple_button_an_answer_cancel_and_no_save(bot):
    from core import cards

    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    shown = bot.sent[-1][1]
    assert shown.text.splitlines()[-2:] == ["Is that 8:00 in the morning or the evening?", "-# or type your answer"]
    (row,) = shown.rows
    assert [(button.label, button.style) for button in row] == [("8:00 am", cards.PRIMARY), ("8:00 pm", cards.PRIMARY), ("Cancel", cards.SECONDARY)]
    cards.check(shown)
    stored = open_cards()[-1]
    assert stored.question["text"].startswith("Is that 8:00") and [choice["label"] for choice in stored.question["choices"]] == ["8:00 am", "8:00 pm"]
    # Save can't be reached on it, even by a stale press
    with pytest.raises(Exception, match="Answer the question"):
        run(confirm.on_save(bot.Press(stored.id)))
    assert pills(bot) == []


def test_an_answer_that_leaves_nothing_to_look_over_is_done_at_once_and_the_card_says_so(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc"}, {"name": "Iron"}], "guessed": [], "not_included": []}))
    bot.say("add zinc and iron to my pills")
    press(bot)
    run(checklist.post(bot.owner.id))
    bot.claude(route("pills"), ("pill_log", {"doses": [{"pill": "@that", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("took it")
    lines, buttons = card(bot)
    assert lines[:2] == ["💊 Pills · change", "Which pill?"] and buttons == ["Iron", "Zinc", "Cancel"], "asked on a card, with a button a pill"
    stored = open_cards()[-1]
    pressed = bot.Press(f"{stored.id}:1")
    run(confirm.on_answer(pressed))
    assert pressed.cards[-1].text.startswith("✅ **Zinc** · taken ") and not pressed.cards[-1].rows, "logged, and said on the card"
    assert not [each for each in open_cards() if each.status == "open"]


def test_a_typed_answer_to_which_pill_logs_it_and_the_card_that_asked_goes(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc"}, {"name": "Iron"}], "guessed": [], "not_included": []}))
    bot.say("add zinc and iron to my pills")
    press(bot)
    run(checklist.post(bot.owner.id))
    bot.claude(route("pills"), ("pill_log", {"doses": [{"pill": "@that", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("took it")
    asked = bot.sent[-1][0]
    bot.claude(("pill_log", {"doses": [{"pill": "zinc", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("zinc")
    assert bot.sent[-1][1].text.startswith("✅ **Zinc** · taken "), "typed instead of pressed: the same"
    assert asked in bot.deleted and not [each for each in open_cards() if each.status == "open"]


# --- part of a pill's name is a hint for the router, which still decides -----------------------------------------
def test_part_of_a_pills_name_is_handed_to_the_router_as_a_hint_and_the_router_decides(bot):
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Testvit"}, {"name": "Testvit forte"}], "guessed": [], "not_included": []}))
    bot.say("add testvit and testvit forte to my pills")
    press(bot)
    # The router is told, and here it chooses pills: the code then asks which of the two is meant
    bot.claude(route("pills"), ("pill_pause", {"pills": [{"pill": "Testvit"}], "guessed": [], "not_included": []}))
    bot.say("pause testv")
    asked = next(request for request in reversed(bot.requests) if request.purpose == "router")
    assert "A hint, not a decision: “testv” could be the start of the name of one of the user's own things in pills." in asked.user
    hint = next(line for line in asked.user.splitlines() if line.startswith("A hint"))
    assert "Testvit" not in hint, "the hint holds the word typed and the task, never a name of mine"
    lines, buttons = card(bot)
    assert "Which one is “testv”?" in lines and buttons == ["Testvit", "Testvit forte", "Cancel"]
    # It is only a hint: when the router chooses another task, that task gets the message
    run(confirm.on_cancel(bot.Press(open_cards()[-1].id)))  # the card that asked is put away first
    sent = len(bot.sent)
    bot.claude(route("timers"), ("none", {"why": "unclear", "reason": "no timer is called that"}))
    bot.say("pause testv")
    asked = next(request for request in reversed(bot.requests) if request.purpose == "router")
    assert "A hint, not a decision" in asked.user and bot.requests[-1].task == "timers", "the router chose timers, and timers was asked"
    assert len(bot.sent) == sent + 1 and "Which one" not in bot.sent[-1][1].text, "no pills card: the hint decided nothing"
    # A message that names nothing of mine carries no hint
    bot.claude(route("timers"), ("none", {"why": "unclear", "reason": "no timer is running"}))
    bot.say("pause everything")
    assert "hint" not in next(request for request in reversed(bot.requests) if request.purpose == "router").user


# --- 19 and 20: live, 2026-10-14. One dose taken at 9:20 am ended up as two logs ------------------------------
# Dose 1 had been marked missed at 9:00 am, so "Took it at 9:20" went in as dose 2. "That was dose 1" was then read
# as a new dose: its card asked only "Log it as taken now?", and Save added a second log, at 9:27 am
LOGGED_AT_9_20 = ("pill_log", {"doses": [{"pill": "pl1", "did": "taken", "at": "9:20"}], "guessed": [], "not_included": []})
MOVED = "**Pill A** · dose 2 → dose 1 · taken 9:20 am"


def _doses(bot):
    return {dose.number: (dose.occurrence.state, timeinput.format_moment(dose.occurrence.actual_at) if dose.occurrence.actual_at else None) for dose in run(checklist.view(bot.owner.id))[1]}


def _one_dose_at_9_20(bot, dev_clock, dose_1_missed):
    from datetime import time

    from core import occurrences

    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(9, 23)))
    bot.claude(route("pills"), ("pill_add", {"pills": [MAIN], "guessed": [], "not_included": []}))
    bot.say("add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm")
    press(bot)
    if dose_1_missed:
        # As a row from before the fix can be: missed with the doses after it still to come
        first = next(dose for dose in run(checklist.view(bot.owner.id))[1] if dose.number == 1)
        run(database.run(occurrences.db_miss, first.occurrence.id, None, "ignored"))
    bot.claude(route("pills"), LOGGED_AT_9_20)
    bot.say("Took Pill A at 9:20")
    dev_clock.advance(timedelta(minutes=4))
    return len(bot.requests)


def _that_was_dose_1(bot, dev_clock, golden):
    before = _one_dose_at_9_20(bot, dev_clock, dose_1_missed=True)
    assert bot.sent[-1][1].text.startswith("✅ **Pill A** (dose 2 of 3) · taken 9:20 am") and _doses(bot)[2] == ("done", "9:20 am")
    bot.claude(EXTRACTED[golden])  # one request, for pills: it answered a moment ago
    bot.say(SAID[golden], straight_after=True)
    lines, buttons = card(bot)
    assert lines[:3] == ["💊 Pills · change", MOVED, "-# dose 2 · still to take · `12:20 pm`"], "a change card, old → new, with the time it has"
    assert buttons == ["Save", "Cancel"] and not any("Log it as taken now" in line for line in lines)
    assert _doses(bot) == {1: ("missed", None), 2: ("done", "9:20 am"), 3: ("pending", None)}, "nothing changes by asking"
    assert press(bot) == f"✏️ {MOVED} · still to take today: Pill A (dose 2 of 3) `12:20 pm`, Pill A (dose 3 of 3) `3:20 pm`"
    assert _doses(bot) == {1: ("done", "9:20 am"), 2: ("pending", None), 3: ("pending", None)}, "one dose, moved: never a second log"
    assert [(asked.task, "not_this" in asked.tools) for asked in bot.requests[before:]] == [("pills", True)]
    _no_chat(bot)


def test_19_that_was_dose_1_moves_the_log_just_made_and_never_adds_another(bot, dev_clock):
    _that_was_dose_1(bot, dev_clock, "19")


def test_19a_no_that_was_my_first_dose_does_the_same(bot, dev_clock):
    _that_was_dose_1(bot, dev_clock, "19a")


def test_19_the_correction_is_checked_against_what_was_logged_with_no_card_open(bot, dev_clock):
    from tests.test_conversation import traces

    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=True)  # logged at once: no card is open
    bot.claude(EXTRACTED["19"])
    bot.say(SAID["19"], straight_after=True)
    checks = traces()[-1]["checks"]
    assert "open card: none, so the sticky and correction checks were skipped" in checks, "as that morning: no card was open"
    assert any(note.startswith("correction check: against what was logged, not only an open card: the log of dose 2 is moved to dose 1") for note in checks)


def test_19_more_than_five_minutes_later_it_is_still_a_move_and_the_pill_it_picked_is_shown(bot, dev_clock):
    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=True)
    dev_clock.advance(timedelta(minutes=30))
    bot.claude(ROUTED["19"], EXTRACTED["19"])
    bot.say(SAID["19"], straight_after=True)
    assert f"{MOVED} ❓" in card(bot)[0] and card(bot)[1] == ["Save", "Cancel"]
    assert press(bot).startswith(f"✏️ {MOVED}")
    assert _doses(bot)[1] == ("done", "9:20 am") and _doses(bot)[2] == ("pending", None)


def test_19_read_as_a_new_dose_as_it_was_that_morning_the_card_says_one_was_already_logged(bot, dev_clock):
    # Trace #562, as Claude answered then: taken, dose 1, no time, and nothing saying it corrects the log
    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=True)
    bot.claude(("pill_log", {"doses": [{"pill": "@that", "did": "taken", "dose": 1}], "guessed": [], "not_included": []}))
    bot.say("That was dose 1", straight_after=True)
    lines, buttons = card(bot)
    assert lines[1] == "**Pill A** (dose 1 of 3) · taken 9:27 am"
    assert "⚠️ You already logged dose 2 at 9:20 am. Dose 1 was missed (due 8:00 am). That's after dose 2, taken 9:20 am. Add another dose?" in lines
    assert buttons == ["Log it", "Cancel"] and not any(line.endswith("Log it as taken now?") for line in lines)
    assert _doses(bot)[1] == ("missed", None), "nothing is logged by asking"


def test_20_a_card_that_would_add_a_dose_says_one_was_logged_a_moment_ago(bot, dev_clock):
    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=False)
    assert bot.sent[-1][1].text.startswith("✅ **Pill A** (dose 1 of 3) · taken 9:20 am"), "nothing was missed: the one dose is dose 1"
    bot.claude(EXTRACTED["20"])
    bot.say(SAID["20"], straight_after=True)
    lines, buttons = card(bot)
    assert lines[:2] == ["💊 Pills · change", "**Pill A** (dose 2 of 3) · taken 9:27 am"]
    assert "⚠️ You already logged dose 1 at 9:20 am. That's 7m later. The gap is at least 3h. Add another dose?" in lines
    assert buttons == ["Log it", "Cancel"]
    assert _doses(bot) == {1: ("done", "9:20 am"), 2: ("pending", None), 3: ("pending", None)}, "nothing is added by asking"
    assert press(bot).startswith("✅ **Pill A** (dose 2 of 3) · taken 9:27 am"), "and Log it does add it: it was asked in so many words"


def test_20_more_than_an_hour_after_the_last_log_the_card_reads_as_it_did(bot, dev_clock):
    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=False)
    dev_clock.advance(timedelta(minutes=70))
    bot.claude(ROUTED["20"], EXTRACTED["20"])
    bot.say(SAID["20"])
    assert "⚠️ That's 1h 17m after dose 1, taken 9:20 am. The gap is at least 3h. Log it anyway?" in card(bot)[0]


def test_19_the_morning_after_only_today_s_logs_are_moved_unasked_and_the_card_asks_which_day(bot, dev_clock):
    from datetime import time

    _one_dose_at_9_20(bot, dev_clock, dose_1_missed=True)
    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(7, 0)))
    bot.claude(ROUTED["19"], EXTRACTED["19"])
    bot.say(SAID["19"])
    lines, buttons = card(bot)
    assert any("Pill A has no dose ticked off today. Which day was it?" in line for line in lines), lines
    assert buttons == ["Yesterday", "Cancel"], "it says so and asks: nothing is moved, and nothing is logged"
    assert all(state == "pending" for state, _ in _doses(bot).values())
    lines, buttons = answer(bot, "Yesterday")
    assert f"{MOVED} · yesterday ❓" in lines or f"{MOVED} · yesterday" in lines
    assert "-# dose 2 · not taken yesterday" in lines and buttons == ["Save", "Cancel"]
    assert press(bot).startswith(f"✏️ {MOVED} · yesterday")
    assert all(state == "pending" for state, _ in _doses(bot).values()), "today is as it was"


# --- 21 to 25: questions about my day, answered from data and never guessed (asked 2026-10-14) ---------------
@pytest.fixture
def my_day(bot, monkeypatch, make_db, dev_clock):
    """The bot with the briefing and the weather answering questions (DAY_QUESTIONS), a forecast kept at 9:00 am
    from the recorded one, and the clock on a day of its own."""
    from datetime import time

    from core import config
    from tasks import briefing, weather
    from tasks.weather import store as weather_store

    make_db({"weather": weather_store.MIGRATIONS})
    for name, value in (("BRIEFING_ENABLED", True), ("WEATHER_ENABLED", True), ("DAY_QUESTIONS", True), ("DAY_PROGRESS", True)):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(config, "WEATHER_SOURCE", str(Path(__file__).parent / "fixtures" / "weather_drizzle.json"))
    actions.set_catalogue([*demo.ENTRIES, *pills_task.entries(), *timers_task.entries(), *briefing.task.entries(), *weather.task.entries()])
    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(9, 0)))
    assert run(weather.update(bot.owner.id)) == ""
    return bot


def _said(bot):
    """What the bot said last: a task's answer is posted as a message of its own."""
    return bot.sent[-1][1].text


def _answered_by(bot, task):
    """The message took one router request and one extraction for that task, and plain chat was never asked."""
    assert [(asked.purpose, asked.task) for asked in bot.requests[-2:]] == [("router", ""), ("extraction", task)], [(asked.purpose, asked.task) for asked in bot.requests]
    assert bot.chats == [], "plain chat cannot see my data: it was never asked"


def test_21_what_s_left_today_is_answered_from_the_day_s_own_data(my_day):
    bot = my_day
    _with_zinc(bot)
    run(checklist.post(bot.owner.id, 100))
    cards_before = len(open_cards())
    bot.claude(ROUTED["21"], EXTRACTED["21"])
    ctx, _ = bot.say(SAID["21"])
    assert _said(bot) == "☀️ **Left today** · ○ 0/1\n💊 Zinc", _said(bot)
    _answered_by(bot, "briefing")
    assert len(open_cards()) == cards_before, "a question is answered, not asked about on a card"


def test_21_with_everything_done_it_says_nothing_is_left_and_no_number_is_made_up(my_day):
    bot = my_day
    bot.claude(ROUTED["21"], EXTRACTED["21"])
    ctx, _ = bot.say(SAID["21"])
    assert _said(bot) == "☀️ Nothing on today.", "no pills, nothing to count"
    from tasks.pills import plain

    _with_zinc(bot)
    run(checklist.post(bot.owner.id, 100))
    run(plain.log_doses(Request(bot.owner, 100, ""), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset()))
    bot.claude(ROUTED["21"], EXTRACTED["21"])
    ctx, _ = bot.say(SAID["21"])
    assert _said(bot) == "☀️ **Nothing left today** · ● 1/1"


def test_22_what_s_on_today_is_the_briefing_itself(my_day):
    bot = my_day
    _with_zinc(bot)
    run(checklist.post(bot.owner.id, 100))
    bot.claude(ROUTED["22"], EXTRACTED["22"])
    ctx, _ = bot.say(SAID["22"])
    shown = bot.sent[-1][1].text.splitlines()
    assert shown[0] == "## ☀️ Today ○ 0/1" and "-# 💊 0/1" in shown and "💊 **Pills** · 0 of 1 taken" in shown, shown
    assert "🌤️ **Weather** · 14° to 20° · drizzle" in shown and ctx.replies == [], "the card, and not a word about it"
    _answered_by(bot, "briefing")


def _a_day_with_zinc_taken_then_the_next_morning(bot, dev_clock):
    from datetime import time

    from tasks.pills import plain

    _with_zinc(bot)
    run(checklist.post(bot.owner.id, 100))
    run(plain.log_doses(Request(bot.owner, 100, ""), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset()))
    first = day.today()
    dev_clock.advance_to(day.at(first + timedelta(days=1), time(9, 0)))
    run(checklist.new_day(first, first + timedelta(days=1)))
    return first


def test_23_how_did_i_go_yesterday_is_the_record_of_that_day(my_day, dev_clock):
    bot = my_day
    first = _a_day_with_zinc_taken_then_the_next_morning(bot, dev_clock)
    bot.claude(ROUTED["23"], EXTRACTED["23"])
    ctx, _ = bot.say(SAID["23"])
    assert _said(bot) == f"☀️ **Yesterday** · {first:%a} {first.day} {first:%b} · ● 1/1\n💊 Yesterday: 1 of 1 taken", _said(bot)
    _answered_by(bot, "briefing")


def test_23_with_nothing_recorded_yesterday_it_says_so(my_day):
    bot = my_day
    bot.claude(ROUTED["23"], EXTRACTED["23"])
    ctx, _ = bot.say(SAID["23"])
    assert _said(bot) == "☀️ Nothing was on yesterday."


def test_23a_and_this_week_is_asked_of_the_router_and_is_the_week_so_far(my_day, dev_clock):
    bot = my_day
    first = _a_day_with_zinc_taken_then_the_next_morning(bot, dev_clock)
    today = day.today()
    bot.claude(ROUTED["23"], EXTRACTED["23"])
    bot.say(SAID["23"])
    before = len(bot.requests)
    # The briefing, having just answered, reads it first; a question never sticks, so the router is asked
    # all the same, and when it sends it back to the briefing that reading is used: not asked twice
    bot.claude(EXTRACTED["23a"], ROUTED["23a"])
    ctx, _ = bot.say(SAID["23a"], straight_after=True)
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "briefing"), ("router", "")]
    said = _said(bot).splitlines()
    assert said[0].startswith("☀️ **This week** · ") and said[-1] == f"`{today:%a} {today.day}` ○ 0/1 · today", said
    if today.weekday() != 0:
        assert said[0].endswith("●○ 1/2") and said[1] == "-# 💊 1/2" and f"`{first:%a} {first.day}` ● 1/1" in said
    assert bot.chats == []


def test_24_will_it_rain_is_answered_by_the_weather_task_from_the_forecast_it_keeps(my_day, monkeypatch):
    from tasks.weather import source

    async def never():
        raise AssertionError("a question never asks the network")

    bot = my_day
    monkeypatch.setattr(source, "fetch", never)
    bot.claude(ROUTED["24"], EXTRACTED["24"])
    ctx, _ = bot.say(SAID["24"])
    assert _said(bot) == "🌤️ 61% chance of rain for the rest of today, most likely between 1pm and 5pm.\n-# updated 9:00 am", _said(bot)
    _answered_by(bot, "weather")


def test_25_the_weather_this_afternoon_is_that_part_of_the_kept_forecast(my_day, dev_clock):
    from datetime import time

    bot = my_day
    bot.claude(ROUTED["25"], EXTRACTED["25"])
    ctx, _ = bot.say(SAID["25"])
    assert _said(bot) == "🌤️ **This afternoon**\n61% chance of rain this afternoon, most likely between 1pm and 5pm.\n-# wind up to 15 km/h N today · updated 9:00 am", _said(bot)
    _answered_by(bot, "weather")
    dev_clock.advance_to(day.at(day.today(), time(19, 0)))
    bot.claude(ROUTED["25"], EXTRACTED["25"])
    ctx, _ = bot.say(SAID["25"])
    assert _said(bot).splitlines()[0] == "🌤️ This afternoon is over.", "a part that is over says so"


def test_25_with_no_forecast_kept_it_says_so_and_gives_no_number(my_day):
    bot = my_day
    conn = database.connect()
    try:
        conn.execute("DELETE FROM weather_forecasts")
        conn.commit()
    finally:
        conn.close()
    bot.claude(ROUTED["25"], EXTRACTED["25"])
    ctx, _ = bot.say(SAID["25"])
    assert _said(bot) == "🌤️ I have no forecast for today yet." and not any(character.isdigit() for character in _said(bot))


# --- the week of 2026-10-07 to 14, read back from live's own log: the misreads that had no golden conversation --
# As Claude really answered on 2026-10-11 (the pill's name replaced): the new pill, then the change to it read
# as a change to a saved pill, to which the bot said "There are no pills yet."
ADDED_THAT_NIGHT = ("pill_add", {"pills": [{"name": "Pill A", "notes": "with no food within 30 minutes", "times": ["8:00 am", "11:30 am", "2:00 pm"], "per_day": 3, "min_gap_minutes": 180}], "guessed": [], "not_included": []})
READ_AS_AN_EDIT = ("pill_edit", {"pills": [{"pill": "Pill A", "times": ["8:00 am", "11:00 am", "2:00 pm"]}], "guessed": [], "not_included": []})
SAID_THAT_NIGHT = "add pill A, 3 times a day, 8am, 11:30am, 2pm, 3 hours apart and with no food within 30 minutes"


def _a_new_pill_on_an_open_card(bot):
    saved = len(pills(bot))
    bot.claude(route("pills"), ADDED_THAT_NIGHT)
    bot.say(SAID_THAT_NIGHT)
    lines, buttons = card(bot)
    assert lines[1] == "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `2:30 pm`" and buttons == ["Save", "Cancel"] and len(pills(bot)) == saved, "nothing is saved before Save"
    assert "⚠️ 11:30 am to 2:00 pm is under 3h: the third dose moves to 2:30 pm" in lines


def _the_card_now_has_11_am(bot, third="2:30 pm"):
    lines, buttons = card(bot)
    assert lines[0] == "💊 Pills · new" and lines[1] == f"**Pill A** · 3× daily · `8:00 am`, `11:00 am`, `{third}`", lines
    assert "At least 3h apart · *with no food within 30 minutes*" in lines and not any("⚠️" in line for line in lines), "everything else on the card is kept, and the times now fit"
    assert buttons == ["Save", "Cancel"] and [each.status for each in open_cards()] == ["replaced", "open"], "one card is open: the old one was replaced"
    assert not any("no pills yet" in shown.text for _, shown in bot.sent)
    assert press(bot).startswith(f"✅ Saved · 💊 **Pill A** · 3× daily · `8:00 am`, `11:00 am`, `{third}`")
    assert [pill.plan.name for pill in pills(bot)] == ["Pill A"]


def test_2c_a_change_to_a_pill_that_is_only_on_the_open_card_changes_the_card(bot):
    _a_new_pill_on_an_open_card(bot)
    bot.claude(EXTRACTED["2c"])  # a follow-up to the card: one request, and no router
    bot.say(SAID["2c"])
    _the_card_now_has_11_am(bot)  # only the time I named moves: the third dose stays where the card had it


def test_2c_read_as_a_change_to_a_saved_pill_as_it_was_that_night_it_still_changes_the_card(bot):
    _a_new_pill_on_an_open_card(bot)
    bot.claude(READ_AS_AN_EDIT)
    bot.say(SAID["2c"])
    _the_card_now_has_11_am(bot, third="2:00 pm")  # that night it gave all three times as first said


def test_2c_it_as_the_pill_on_the_card_is_that_pill_when_there_is_only_one(bot):
    _a_new_pill_on_an_open_card(bot)
    bot.claude(("pill_edit", {"pills": [{"pill": "@that", "times": ["8:00 am", "11:00 am", "2:00 pm"]}], "guessed": [], "not_included": []}))
    bot.say("make its second dose 11am")
    _the_card_now_has_11_am(bot, third="2:00 pm")


def test_a_change_to_a_pill_that_is_saved_stays_a_change_to_it_though_a_new_card_is_open(bot):
    from tasks.pills import plain

    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Zinc"}], "guessed": [], "not_included": []}))
    bot.say("add zinc to my pills")
    press(bot)
    _a_new_pill_on_an_open_card(bot)
    request = Request(bot.owner, 100, "")
    on_card = ADDED_THAT_NIGHT[1]
    assert run(plain.edit_on_card(request, {"pills": [{"pill": "zinc", "times": ["9:00 pm"]}]}, on_card)) is None, "a saved pill: an edit as ever"
    assert run(plain.edit_on_card(request, {"pills": [{"pill": "pl1", "times": ["9:00 pm"]}]}, on_card)) is None, "by its id too"
    assert run(plain.edit_on_card(request, {"pills": [{"pill": "Iron", "times": ["9:00 pm"]}]}, on_card)) is None, "not on the card: nothing is guessed"
    assert run(plain.edit_on_card(request, {"pills": [{"pill": "Pill A", "name": "Pill B"}]}, on_card)) is None, "a new name is a change only a saved pill takes"
    assert run(plain.edit_on_card(request, {"pills": [{"pill": "pill a", "dose": "2 tablets"}]}, on_card)) == {"pills": [{"dose": "2 tablets", "name": "Pill A"}]}
    bot.claude(("pill_edit", {"pills": [{"pill": "zinc", "times": ["9:00 pm"]}], "guessed": [], "not_included": []}))
    bot.say("move zinc to 9pm")
    lines, _ = card(bot)
    assert lines[0] == "💊 Pills · change" and "**Zinc**" in lines[1], lines


def test_18c_a_time_with_the_pill_named_straight_after_a_late_log_corrects_it_and_adds_no_dose(bot, dev_clock):
    # Live, 2026-10-11: "I took <the pill> at 9am" a minute after a late log came back as
    # "9:00 am is before the previous one, at 10:57 pm": read as a second dose, not as a correction
    test_a_late_log_is_asked_about_then_a_time_said_straight_after_corrects_it.__wrapped__(bot, dev_clock, "I took Pill A at 9am") if hasattr(
        test_a_late_log_is_asked_about_then_a_time_said_straight_after_corrects_it, "__wrapped__"
    ) else test_a_late_log_is_asked_about_then_a_time_said_straight_after_corrects_it(bot, dev_clock, "I took Pill A at 9am")
    (dose, *_rest) = [each for each in run(checklist.view(bot.owner.id))[1] if each.occurrence.state == "done"]
    assert not _rest and dose.number == 1, "one dose taken, dose 1: nothing was added"


def test_26_the_first_dose_reported_after_its_reminders_ran_out_is_dose_1(bot, dev_clock):
    # Live, 2026-10-14: dose 1 (due 8:00 am) had been closed as missed when its reminders ran out at 9:00 am,
    # so "Took <the pill> at 9:20" was logged as dose 2
    from datetime import time

    dev_clock.advance_to(day.at(day.today() + timedelta(days=1), time(7, 0)))
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Pill A", "times": ["8:00 am", "11:00 am", "2:00 pm"], "per_day": 3, "min_gap_minutes": 180}], "guessed": [], "not_included": []}))
    bot.say("add pill A to my pills at 8am, 11am and 2pm, at least 3 hours apart")
    press(bot)
    dev_clock.advance_to(day.at(day.today(), time(9, 23)))
    bot.claude(ROUTED["26"], EXTRACTED["26"])
    bot.say(SAID["26"])
    assert bot.sent[-1][1].text == "✅ **Pill A** (dose 1 of 3) · taken 9:20 am · still to take today: Pill A (dose 2 of 3) `12:20 pm`, Pill A (dose 3 of 3) `3:20 pm`", bot.sent[-1][1].text
    states = sorted((each.number, each.occurrence.state) for each in run(checklist.view(bot.owner.id))[1])
    assert states == [(1, "done"), (2, "pending"), (3, "pending")], "one log, of dose 1"


# --- 27: a question never sticks to the task that just answered (asked 2026-10-14) ----------------------------
def _zinc_just_logged_in_words(bot):
    """Zinc and iron on today's checklist, and "took my zinc" said a moment ago: pills is the task that just answered."""
    _with_zinc(bot)
    bot.claude(route("pills"), ("pill_add", {"pills": [{"name": "Iron"}], "guessed": [], "not_included": []}))
    bot.say("add iron to my pills")
    press(bot)
    run(checklist.post(bot.owner.id, 100))
    bot.claude(route("pills"), ("pill_log", {"doses": [{"pill": "zinc", "did": "taken"}], "guessed": [], "not_included": []}))
    bot.say("took my zinc")
    assert bot.sent[-1][1].text.startswith("✅ **Zinc** · taken "), bot.sent[-1][1].text
    return len(bot.requests), sum(1 for _, shown in bot.sent if shown.text.startswith("## 💊 Pills"))


def test_27_a_question_about_my_day_straight_after_a_log_gets_the_day_s_own_answer(my_day):
    bot = my_day
    before, checklists = _zinc_just_logged_in_words(bot)
    # Pills had just answered, so it reads the message first, and reads it as a question of its own (what is
    # left to take). A question never sticks: the router is asked, and it is the day's
    bot.claude(EXTRACTED["27"], ROUTED["27"], EXTRACTED["21"])
    bot.say(SAID["27"], straight_after=True)
    assert _said(bot) == "☀️ **Left today** · ●○ 1/2\n💊 Iron", _said(bot)
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", ""), ("extraction", "briefing")]
    assert sum(1 for _, shown in bot.sent if shown.text.startswith("## 💊 Pills")) == checklists, "the checklist is not posted again in answer"
    assert bot.chats == []


def test_27a_the_weather_straight_after_a_log_is_the_weather_s(my_day):
    bot = my_day
    before, _ = _zinc_just_logged_in_words(bot)
    bot.claude(EXTRACTED["27a"], ROUTED["27a"], EXTRACTED["24"])
    bot.say(SAID["27a"], straight_after=True)
    assert _said(bot).startswith("🌤️ 61% chance of rain for the rest of today"), _said(bot)
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", ""), ("extraction", "weather")]


def test_27_a_question_for_the_very_task_that_just_answered_goes_by_the_router_and_is_read_once(my_day):
    bot = my_day
    before, _ = _zinc_just_logged_in_words(bot)
    listing = ("pill_list", {"guessed": [], "not_included": []})
    bot.claude(listing, route("pills"))  # pills reads it, the router agrees it is pills': that reading is used
    bot.say("what do I take?", straight_after=True)
    assert bot.sent[-1][1].text.startswith("## 💊 Pills") and "**Iron**" in bot.sent[-1][1].text
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", "")], "not read a second time"


def test_27_a_report_or_a_correction_straight_after_still_sticks(my_day, dev_clock):
    # What sticks is what follows up on the thing just done: golden 18 is unchanged
    bot = my_day
    before, _ = _zinc_just_logged_in_words(bot)
    bot.claude(("pill_log", {"doses": [{"pill": "@that", "did": "not_taken"}], "guessed": [], "not_included": []}))
    bot.say("actually I didn't", straight_after=True)
    assert any(shown.text.startswith("↩️ **Zinc** · no longer ticked off") for _, shown in bot.sent), [shown.text[:60] for _, shown in bot.sent[-3:]]
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills")], "no router: it is about what was just logged"


# --- 28: an open card takes only what could answer or change it (asked 2026-10-14) ----------------------------
def _iron_asked_about_on_a_card(bot):
    """Zinc saved and on today's checklist, then a card for iron that asks whether 8 is morning or evening."""
    _with_zinc(bot)
    run(checklist.post(bot.owner.id, 100))
    bot.claude(ROUTED["1c"], EXTRACTED["1c"])
    bot.say(SAID["1c"])
    assert card(bot)[1] == ["8:00 am", "8:00 pm", "Cancel"]
    return len(bot.requests), open_cards()[-1].id


def _the_card_is_still_open_and_answerable(bot, held):
    assert [each.id for each in open_cards() if each.status == "open"] == [held], "the card stays open, as it was"
    lines, buttons = answer(bot, "8:00 pm")
    assert lines[1] == "**iron** · daily at `8:00 pm`" and buttons == ["Save", "Cancel"]
    assert press(bot).startswith("✅ Saved · 💊 **iron**") and sorted(pill.plan.name.lower() for pill in pills(bot)) == ["iron", "zinc"]


def test_28_a_question_about_my_day_while_a_card_is_open_gets_the_day_s_answer_and_the_card_stays(my_day):
    bot = my_day
    before, held = _iron_asked_about_on_a_card(bot)
    # Pills reads it against its card first, and reads it as a question of its own: that neither answers nor
    # changes the card, so the router is asked, as for any message, and it is the day's
    bot.claude(EXTRACTED["28"], ROUTED["28"], EXTRACTED["21"])
    bot.say(SAID["28"])
    assert _said(bot) == "☀️ **Left today** · ○ 0/1\n💊 Zinc", _said(bot)
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", ""), ("extraction", "briefing")]
    assert not any(shown.text.startswith("## 💊 Pills") for _, shown in bot.sent[-1:]) and bot.chats == []
    _the_card_is_still_open_and_answerable(bot, held)


def test_28a_the_weather_while_a_card_is_open_is_the_weather_s_and_the_card_stays(my_day):
    bot = my_day
    before, held = _iron_asked_about_on_a_card(bot)
    bot.claude(EXTRACTED["28a"], ROUTED["28a"], EXTRACTED["24"])
    bot.say(SAID["28a"])
    assert _said(bot).startswith("🌤️ 61% chance of rain for the rest of today"), _said(bot)
    # Pills read it once, against its card: not a second time as a follow-up to the card it had just posted
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", ""), ("extraction", "weather")]
    _the_card_is_still_open_and_answerable(bot, held)


def test_28_a_question_the_router_gives_back_to_the_card_s_task_is_read_once_and_leaves_the_card(my_day):
    bot = my_day
    before, held = _iron_asked_about_on_a_card(bot)
    bot.claude(("pill_list", {"guessed": [], "not_included": []}), route("pills"))
    bot.say("what do I take?")
    assert bot.sent[-1][1].text.startswith("## 💊 Pills") and "**Zinc**" in bot.sent[-1][1].text
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills"), ("router", "")], "not read a second time"
    _the_card_is_still_open_and_answerable(bot, held)


def test_28_what_answers_or_changes_the_card_is_still_read_against_it(my_day):
    # Golden 2 is unchanged: a correction typed while the card is open replaces it, with no router
    bot = my_day
    before, held = _iron_asked_about_on_a_card(bot)
    bot.claude(EXTRACTED["2"])
    bot.say(SAID["2"])
    assert card(bot)[0][1].lower() == "**iron** · daily at `8:00 am`"
    assert [(asked.purpose, asked.task) for asked in bot.requests[before:]] == [("extraction", "pills")]


def test_the_golden_conversations_never_go_by_the_real_time_of_day(bot):
    from core import clock

    # Near midnight a minute or two would be a new day: they run at noon, whenever the suite runs (question 39)
    assert day.local_time(clock.now()) == time(12, 0)
