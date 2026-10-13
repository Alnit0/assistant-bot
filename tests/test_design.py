"""Cards as Components V2 (core/design.py, docs/DESIGN.md), behind CARDS_V2: off is today's look, unchanged."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import discord
import pytest

from core import actions, cards, clock, config, confirm, database, day, design, occurrences
from core.actions import Choice, Entry, Proposal, Question
from core.cards import Button, Card
from interfaces.discord import render
from interfaces.discord import surface as discord_surface
from tasks.dev import mock
from tasks.pills import checklist, plain, reminders, sheet, store
from tests.test_pills_reminders import EVENING, HUB, PILL_A, Press, add, at, log, miss, prompts, run, states, world  # noqa: F401

ENTRY = Entry("pills", "💊", "Pills", "x", ("y",), ())
SAVE = Button("Save", "confirm", "save", "1", emoji="✅", style=cards.SUCCESS)


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setattr(config, "CARDS_V2", True)


def kinds(pieces):
    """A layout as Discord would get it: the type of each component, a box with what is in it."""
    return [(each["type"], [inner["type"] for inner in each.get("components", [])]) if each["type"] == 17 else each["type"] for each in render.layout_view(pieces).to_components()]


# --- one place for every value ------------------------------------------------------------------------------
def test_every_status_has_a_colour_and_the_colours_are_the_ones_the_design_names():
    assert set(design.ACCENTS.values()) <= set(design.COLOURS)
    named = {status: design.ACCENTS[status] for status in (design.DUE, design.ANY_TIME, design.DONE, design.MISSED, design.QUIET, design.DECISION, design.RISKY, design.DESTRUCTIVE)}
    assert named == {"due": "amber", "any_time": "blue", "done": "green", "missed": "red", "quiet": "grey", "decision": "blurple", "risky": "amber", "destructive": "red"}
    assert design.colour(design.DUE) == design.COLOURS["amber"]


def test_a_colour_changed_in_the_one_file_changes_every_card_and_every_sketch(monkeypatch):
    monkeypatch.setitem(design.COLOURS, "amber", 0x123456)
    box = design.item(design.DUE, "**Pill A**")
    assert render.layout_view((box,)).to_components()[0]["accent_color"] == 0x123456
    assert mock.ACCENTS["blue"] == design.COLOURS["blue"] and mock.ACCENTS["gray"] == design.COLOURS["grey"]
    assert not hasattr(cards, "COLOURS") and "0x" not in open(sheet.__file__, encoding="utf-8").read(), "no colour of a task's own"


def test_the_separators_take_their_spacing_from_the_same_place(monkeypatch):
    monkeypatch.setattr(design, "SECTION_LARGE", True)
    pieces = design.standing("💊 Today", "Monday 12 October", [design.item(design.DONE, "**A**")], [design.item(design.QUIET, "⏸️ **Paused**")])
    sent = render.layout_view(pieces).to_components()
    assert [each["type"] for each in sent] == [10, 17, 14, 17] and sent[2]["spacing"] == 2 and sent[2]["divider"] is True
    assert render.layout_view((design.Separator(line=False, large=False), design.Text("x"))).to_components()[0] == {"type": 14, "divider": False, "spacing": 1}


# --- the shapes ------------------------------------------------------------------------------------------------
def test_a_box_is_name_then_what_there_is_to_say_and_its_buttons_and_an_empty_line_is_left_out():
    box = design.item(design.DUE, "**Pill A** · ●○○", "-# with food", "", "✅ 9:00 am", row=(SAVE,))
    assert box.children[0].content == "**Pill A** · ●○○\n-# with food\n✅ 9:00 am" and box.children[1].buttons == (SAVE,)
    assert design.item(design.DONE, "**Pill C**").children == (design.Text("**Pill C**"),), "nothing to do: no buttons"
    assert design.count((box,)) == 4 and design.count((design.item(design.DONE, "x"),)) == design.BOX_COST


def test_a_decision_card_is_one_box_heading_things_warning_question_and_buttons_with_the_hint_under_it():
    pieces = design.decision("💊 Pills · change", ["**A**\none", "**B**\ntwo"], warnings=["careful"], question="Which?", row=(SAVE,), hint="-# or tell me")
    box, hint = pieces
    assert box.status == design.DECISION and hint == design.Text("-# or tell me")
    assert [type(child).__name__ for child in box.children] == ["Text", "Separator", "Text", "Separator", "Text", "Separator", "Text", "Row"]
    assert box.children[0].content == "## 💊 Pills · change" and box.children[6].content == "⚠️ careful\n**Which?**"


def test_a_layout_discord_would_refuse_is_refused_with_the_reason():
    many = tuple(design.item(design.DUE, f"**{n}**", row=(Button("Taken", "pills", "t", str(n), style=cards.SUCCESS),)) for n in range(11))
    with pytest.raises(ValueError, match="44 components, and one message takes 40"):
        cards.check(Card("x", (), many))
    with pytest.raises(ValueError, match="grey is for Cancel only"):
        cards.check(Card("x", (), (design.Row((Button("Maybe", "a", "b", style=cards.SECONDARY),)),)))
    with pytest.raises(ValueError, match="share the id"):
        cards.check(Card("x", (), (design.Row((SAVE, SAVE)),)))
    assert design.problem((design.Text("x" * 4001),)).startswith("4001 characters")
    assert design.problem((design.Box("purple", (design.Text("x"),)),)) == "“purple” is not a status"


def test_the_words_of_a_drawn_card_can_be_read_back():
    drawn = SimpleNamespace(content="", components=[
        SimpleNamespace(content="💊 Routine due · 11:12 am"),
        SimpleNamespace(children=[SimpleNamespace(content="**Pill A**"), SimpleNamespace(children=[SimpleNamespace(label="Taken")])]),
    ])
    assert design.words(drawn) == "💊 Routine due · 11:12 am\n**Pill A**"
    assert design.words(SimpleNamespace(content=" plain ", components=[])) == "plain" and design.words(SimpleNamespace()) == ""


# --- off is today's look ---------------------------------------------------------------------------------------
class Channel:
    def __init__(self, refuse_text=False):
        self.sent, self.edits, self.refuse_text = [], [], refuse_text

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return SimpleNamespace(id=1)

    def get_partial_message(self, message_id):
        channel = self

        class Message:
            async def edit(self, **kwargs):
                if channel.refuse_text and kwargs.get("content") is not None:
                    raise discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request"), "Invalid Form Body")
                channel.edits.append(kwargs)

        return Message()


CARD = Card("💊 Pills · change\n**Pill A**", ((SAVE,),), design.decision("💊 Pills · change", ["**Pill A**"], row=(SAVE,)))


def test_off_a_card_with_a_layout_is_sent_and_rewritten_exactly_as_before(monkeypatch):
    channel = Channel()
    monkeypatch.setattr(discord_surface, "_channel", lambda channel_id: channel)
    assert config.CARDS_V2 is False and not cards.designed(CARD)
    asyncio.run(cards.send(5, CARD))
    (args, kwargs), = channel.sent
    assert args == ("💊 Pills · change\n**Pill A**",) and isinstance(kwargs["view"], discord.ui.View) and not isinstance(kwargs["view"], discord.ui.LayoutView)
    assert asyncio.run(cards.edit(5, 1, CARD))
    assert channel.edits[0]["content"] == CARD.text and not isinstance(channel.edits[0]["view"], discord.ui.LayoutView)


def test_on_it_is_sent_as_components_v2_with_no_text_beside_it_and_a_card_with_no_layout_is_still_plain(monkeypatch, v2):
    channel = Channel()
    monkeypatch.setattr(discord_surface, "_channel", lambda channel_id: channel)
    asyncio.run(cards.send(5, CARD, silent=True))
    (args, kwargs), = channel.sent
    assert args == () and kwargs["silent"] is True and isinstance(kwargs["view"], discord.ui.LayoutView)
    sent = kwargs["view"].to_components()
    assert sent[0]["type"] == 17 and sent[0]["accent_color"] == design.COLOURS["blurple"]
    assert asyncio.run(cards.edit(5, 1, CARD)) and channel.edits[0]["content"] is None and isinstance(channel.edits[0]["view"], discord.ui.LayoutView)
    asyncio.run(cards.send(5, Card("💊 Routine due · 11:12 am")))
    assert channel.sent[1] == (("💊 Routine due · 11:12 am",), {"silent": False}), "what notifies is still one plain line"


def test_a_message_that_is_components_v2_already_is_rewritten_as_a_layout_of_the_plain_card(monkeypatch):
    # CARDS_V2 was on, the message was drawn, and it is off again (or the card has no layout): a
    # Components V2 message can never go back to text, so the same words and buttons go in as a layout
    channel = Channel(refuse_text=True)
    monkeypatch.setattr(discord_surface, "_channel", lambda channel_id: channel)
    assert asyncio.run(cards.edit(5, 1, Card("✅ Saved.", ((SAVE,),))))
    (kwargs,) = channel.edits
    assert kwargs["content"] is None and [each["type"] for each in kwargs["view"].to_components()] == [10, 1]
    assert kwargs["view"].to_components()[0]["content"] == "✅ Saved."


def test_a_press_rewrites_a_drawn_message_as_a_layout_and_a_plain_one_as_text(v2):
    class Response:
        def __init__(self):
            self.edited = None

        def is_done(self):
            return False

        async def edit_message(self, **kwargs):
            self.edited = kwargs

    def pressed(drawn):
        interaction = SimpleNamespace(response=Response(), message=SimpleNamespace(flags=SimpleNamespace(components_v2=drawn)))
        press = cards.Press(None, "confirm", "save", "1", 5, 1, _interaction=interaction)
        asyncio.run(press.update(Card("✅ Saved.")))
        return interaction.response.edited

    assert pressed(False) == {"content": "✅ Saved.", "view": None}
    after = pressed(True)
    assert after["content"] is None and after["view"].to_components() == [{"type": 10, "content": "✅ Saved."}]


# --- the confirm card, the question card and the card that asks first ------------------------------------------
def test_the_confirm_card_keeps_its_plain_form_and_has_the_same_words_as_a_blurple_box():
    proposal = Proposal(lines=("**Pill A** · daily at `9:00 pm` ❓", "notes · with food → none", "**Pill B** · daily, any time"), data={}, warnings=("Not included: “and the other one”",), kind="change")
    card = confirm.render(ENTRY, proposal, 7)
    assert card.text.splitlines() == ["💊 Pills · change", *proposal.lines, "⚠️ Not included: “and the other one”", confirm.FOOTER]
    box, hint = card.layout
    assert box.status == design.DECISION and hint.content == confirm.FOOTER
    said = [child.content for child in box.children if isinstance(child, design.Text)]
    assert said == ["## 💊 Pills · change", "**Pill A** · daily at `9:00 pm` ❓\nnotes · with food → none", "**Pill B** · daily, any time", "⚠️ Not included: “and the other one”"]
    assert box.children[-1].buttons == card.rows[0] and [button.label for button in card.rows[0]] == ["Save", "Cancel"]
    assert kinds(card.layout) == [(17, [10, 14, 10, 14, 10, 14, 10, 1]), 10]


def test_a_card_that_asks_has_the_question_in_bold_an_answer_a_button_and_no_save():
    question = Question("What time is the other dose?", (Choice("8:00 am", {}), Choice("8:00 pm", {})))
    card = confirm.render(ENTRY, Proposal(lines=("**Magnesium** · 2× daily",), data={}, question=question), 7)
    box, hint = card.layout
    assert box.status == design.DECISION and hint.content == confirm.ASKING
    assert box.children[-2].content == "**What time is the other dose?**"
    assert [button.label for button in box.children[-1].buttons] == ["8:00 am", "8:00 pm", "Cancel"]
    assert "What time is the other dose?" in card.text and "Save" not in [button.label for button in card.rows[0]]


def test_a_card_that_asks_first_because_something_is_risky_is_amber_and_one_that_cannot_be_undone_is_red():
    risky = confirm.render(ENTRY, Proposal(lines=("**Pill A** (dose 2 of 3) · taken 10:12 am",), data={}, warnings=("That's 2h after dose 1. Log it anyway?",), kind="change", confirm_label="Log it", risky=True), 7)
    assert risky.layout[0].status == design.RISKY and design.ACCENTS[design.RISKY] == "amber"
    assert risky.layout[0].children[-2].content == "⚠️ That's 2h after dose 1. Log it anyway?", "the warning is a line, and says why"
    gone = confirm.render(ENTRY, Proposal(lines=("**Iron** → deleted",), data={}, kind="remove", destructive=True, confirm_label="Delete for good"), 7)
    assert gone.layout[0].status == design.DESTRUCTIVE and gone.rows[0][0].style == cards.DANGER
    removed = confirm.render(ENTRY, Proposal(lines=("**Iron** → removed",), data={}, kind="remove", confirm_label="Remove"), 7)
    assert removed.layout[0].status == design.DECISION, "a removal that keeps its history is a decision with a red button"


def test_a_card_of_many_things_is_one_block_rather_than_too_many_components():
    lines = tuple(f"**Pill {n}** · daily" for n in range(30))
    card = confirm.render(ENTRY, Proposal(lines=lines, data={}), 7)
    assert design.problem(card.layout) == "" and "**Pill 29** · daily" in card.layout[0].children[2].content


def test_the_too_soon_card_from_pills_is_the_risky_one(world):
    add(world, PILL_A)
    at(world, 8, 0)
    log(world, {"pill": "pill a", "did": "taken"})
    at(world, 9, 0)
    proposal = run(plain.log_card(world.request(), {"doses": [{"pill": "pill a", "did": "taken"}]}, frozenset()))
    assert proposal.risky and proposal.confirm_label == "Log it"
    assert confirm.render(ENTRY, proposal, 1).layout[0].status == design.RISKY


# --- the reminder ----------------------------------------------------------------------------------------------
def test_a_reminder_is_first_posted_as_the_one_neutral_line_and_the_pill_is_drawn_into_it_after(world, v2):
    add(world, PILL_A)
    at(world, 8, 0)
    first = world.sent[-1].card
    assert first.text == "💊 Routine due · 8:00 am" and first.layout == () and first.rows == (), "what notifies has no pill, no box and no button"
    message_id, drawn = world.edited[-1]
    assert message_id == world.sent[-1].id
    line, box = drawn.layout
    assert line == design.Text("💊 Routine due · 8:00 am"), "the same line stays on top, outside the box"
    assert box.status == design.DUE and box.children[0].content.splitlines() == ["**Pill A** · dose 1 of 3", "Due `8:00 am`", "-# with food", "-# ⚠️ Take by 10:00 am so the doses after it still fit"]
    assert [button.label for button in box.children[1].buttons] == ["Taken", "Taken at…", "Snooze 15m", "Skip"]
    assert kinds(drawn.layout) == [10, (17, [10, 1])]


def test_a_snoozed_reminder_is_grey_and_one_asked_again_is_still_amber(world, v2):
    add(world, PILL_A)
    at(world, 8, 0)
    at(world, 8, 15)
    again = world.edited[-1][1]
    assert again.layout[0].content == "💊 Routine due · 8:00 am · reminder 1 of 3" and again.layout[1].status == design.DUE
    pressed, _ = Press(world, prompts(world)[0][0], run(database.run(reminders.db_prompts, world.owner.id))[0].occurrence_id), None
    run(cards._actions[("pills", reminders.P_SNOOZE)].handler(pressed))
    assert pressed.shown[-1].layout[1].status == design.QUIET and "-# 💤 Snoozed until 8:30 am" in pressed.shown[-1].layout[1].children[0].content


# --- today's checklist -----------------------------------------------------------------------------------------
def sheet_of(world):
    pills, listed, today_ = run(checklist.view(world.owner.id))
    return sheet.layout(listed, pills, today_, clock.now())


def boxes(pieces):
    return [(piece.status, piece.children[0].content.splitlines(), [button.label for child in piece.children if isinstance(child, design.Row) for button in child.buttons]) for piece in pieces if isinstance(piece, design.Box)]


def test_the_checklist_is_a_heading_a_box_a_pill_in_the_colour_of_what_is_still_to_do_and_paused_apart(world, v2):
    add(world, PILL_A, EVENING, {"name": "Any", "notes": "with water"}, {"name": "Done"}, {"name": "Off"})
    run(plain.pause_save(world.request(), run(plain.pause_card(world.request(), {"pills": [{"pill": "off"}]}, frozenset())).data))
    at(world, 8, 0)
    log(world, {"pill": "pill a", "did": "taken"}, {"pill": "done", "did": "taken"})
    pieces = sheet_of(world)
    assert pieces[0].content == f"# 💊 Today · 2 of 6 taken\n-# {world.day:%A} {world.day.day} {world.day:%B}"
    found = {lines[0].split("**")[1]: (status, lines, buttons) for status, lines, buttons in boxes(pieces)}
    assert found["Pill A"] == (design.DUE, ["**Pill A** · ●○○", "-# with food", "✅ dose 1 · 8:00 am", "**Next:** dose 2 · `11:30 am`"], ["Taken", "Taken at…", "Skip"])
    assert found["Evening pill"] == (design.DUE, ["**Evening pill** · ○", "Due `8:00 pm`"], ["Taken", "Taken at…", "Skip"])
    assert found["Any"] == (design.ANY_TIME, ["**Any** · ○ · any time", "-# with water"], ["Taken", "Taken at…", "Skip"])
    assert found["Done"] == (design.DONE, ["**Done** · ●", "✅ 8:00 am"], [])
    assert isinstance(pieces[-2], design.Separator) and pieces[-2].large is design.SECTION_LARGE
    assert boxes(pieces[-1:]) == [(design.QUIET, ["⏸️ **Paused**", "-# Off"], [])]
    assert design.problem(pieces) == ""


def test_a_pill_is_red_only_when_a_dose_was_missed_and_nothing_is_left_to_take_today(world, v2):
    add(world, PILL_A)
    at(world, 8, 0)
    log(world, {"pill": "pill a", "did": "taken"})
    at(world, 12, 30)
    miss(world, "Pill A", 2)  # dose 2 is missed; dose 3 is still to come
    assert states(world)[("Pill A", 2)] == occurrences.MISSED and states(world)[("Pill A", 3)] == occurrences.PENDING
    status, lines, buttons = boxes(sheet_of(world))[0]
    assert status == design.DUE and "❌ dose 2 · missed · was due 11:30 am" in lines and lines[0] == "**Pill A** · ●✕○" and buttons
    log(world, {"pill": "pill a", "did": "skipped"})
    status, lines, buttons = boxes(sheet_of(world))[0]
    assert status == design.MISSED and buttons == [] and lines[0] == "**Pill A** · ●✕⏭"


def test_a_skip_by_the_bot_says_why_in_small_text_and_a_pill_all_skipped_is_grey(world, v2):
    add(world, EVENING)
    at(world, 20, 0)
    log(world, {"pill": "evening pill", "did": "skipped"})
    assert boxes(sheet_of(world)) == [(design.QUIET, ["**Evening pill** · ⏭", "⏭️ skipped"], [])]
    doses = run(checklist.view(world.owner.id))[1]
    auto = [dose.__class__(dose.pill, dose.occurrence.__class__(**{**dose.occurrence.__dict__, "automatic": True, "reason": "not enough time before 4:00 pm"}), dose.due) for dose in doses]
    assert sheet.box(auto, clock.now()).children[0].content.splitlines()[1] == "-# ⏭️ skipped by the bot: not enough time before 4:00 pm"


def test_with_nothing_to_take_it_says_so(world, v2):
    pieces = sheet_of(world)
    assert [piece.content for piece in pieces] == [f"# 💊 Today\n-# {world.day:%A} {world.day.day} {world.day:%B}", sheet.NOTHING]


def test_too_many_pills_for_one_message_drop_buttons_first_then_fold_what_is_done_and_never_lose_one(world, v2):
    add(world, *({"name": f"Pill {n:02}", "times": [f"{8 + n % 10}:00 am" if n % 10 < 4 else f"{n % 10 - 3}:00 pm"]} for n in range(8)))
    at(world, 6, 0)
    pieces = sheet_of(world)
    assert design.problem(pieces) == "" and design.count(pieces) <= design.MAX_COMPONENTS
    with_buttons = [lines[0] for _, lines, buttons in boxes(pieces) if buttons]
    assert with_buttons == ["**Pill 00** · ○"], "eight boxes with buttons are 48 components: only the next one due keeps its buttons"
    assert len(boxes(pieces)) == 8, "and every pill is still there"
    # Twenty pills, most of them taken: what is done is folded into one box of lines
    add(world, *({"name": f"Extra {n:02}", "times": ["9:00 pm"]} for n in range(14)))
    log(world, *({"pill": f"extra {n:02}", "did": "taken"} for n in range(14)))
    pieces = sheet_of(world)
    assert design.problem(pieces) == ""
    folded = pieces[-1].children[0].content.splitlines()
    assert folded[0] == "**Dealt with**" and len(folded) == 15 and all("Extra" in line for line in folded[1:])
    # Forty still to take: a line each, and how many more are not shown is said
    add(world, *({"name": f"More {n:02}", "times": ["10:00 pm"]} for n in range(40)))
    pieces = sheet_of(world)
    assert design.problem(pieces) == ""
    lines = pieces[1].children[0].content.splitlines()
    assert lines[0] == "**Still to take**" and (len(lines) - 1 == 48 or lines[-1].startswith("-# and ")), "none dropped unsaid"


def test_off_the_checklist_is_the_plain_message_with_a_message_for_each_dose_with_no_time(world):
    add(world, {"name": "Any"}, EVENING)
    run(checklist.post(world.owner.id))
    posted = [each.card for each in world.sent]
    assert posted[-2].text.startswith("## 💊 Pills · ") and posted[-1].text == "💊 **Any**" and [b.label for b in posted[-1].rows[0]] == ["Taken", "Skip"]
    assert not cards.designed(posted[-2])


def test_on_the_checklist_carries_its_own_buttons_and_no_dose_gets_a_message_of_its_own(world, v2):
    add(world, {"name": "Any"}, EVENING)
    before = len(world.sent)
    run(checklist.post(world.owner.id))
    posted = world.sent[before:]
    assert len(posted) == 1 and posted[0].silent and cards.designed(posted[0].card)
    assert posted[0].card.text.startswith("## 💊 Pills · "), "the plain form is still there, for the log"
    assert [buttons for _, _, buttons in boxes(posted[0].card.layout)] == [["Taken", "Taken at…", "Skip"]] * 2


def press_sheet(world, action, name, number=1, fields=None):
    doses = run(checklist.view(world.owner.id))[1]
    dose = next(each for each in doses if each.pill.plan.name == name and each.number == number)
    pressed = Press(world, 777, dose.occurrence.id, fields)
    return pressed, run(cards._actions[("pills", action)].handler(pressed))


def test_taken_on_the_checklist_ticks_it_off_and_rewrites_the_checklist_which_is_never_removed(world, v2):
    sheet.register()
    add(world, EVENING)
    run(checklist.post(world.owner.id))
    sheet_id = world.sent[-1].id
    at(world, 20, 5)
    edits = len(world.edited)
    pressed, said = press_sheet(world, sheet.S_TAKEN, "Evening pill")
    assert said == "✅ **Evening pill** · taken 8:05 pm" and not pressed.removed and sheet_id not in world.deleted
    assert states(world)[("Evening pill", 1)] == occurrences.DONE
    rewritten = [card for message_id, card in world.edited[edits:] if message_id == sheet_id]
    assert rewritten and boxes(rewritten[-1].layout) == [(design.DONE, ["**Evening pill** · ●", "✅ 8:05 pm"], [])]
    assert prompts(world) == [], "and the reminder that was up for it goes"
    # Pressed again from a stale copy: nothing is logged twice
    assert press_sheet(world, sheet.S_TAKEN, "Evening pill")[1] == "already dealt with"


def test_taken_too_soon_from_the_checklist_asks_first_on_the_amber_card_and_logs_nothing(world, v2):
    sheet.register()
    add(world, PILL_A)
    at(world, 8, 0)
    press_sheet(world, sheet.S_TAKEN, "Pill A", 1)
    at(world, 9, 0)
    sent = len(world.sent)
    pressed, said = press_sheet(world, sheet.S_TAKEN, "Pill A", 2)
    assert said.startswith("asked first: That's 1h after dose 1") and states(world)[("Pill A", 2)] == occurrences.PENDING
    asked = world.sent[sent].card
    assert asked.layout[0].status == design.RISKY and [button.label for button in asked.rows[0]] == ["Log it", "Cancel"]


def test_skip_and_taken_at_on_the_checklist(world, v2):
    sheet.register()
    add(world, EVENING, {"name": "Any"})
    at(world, 20, 30)
    assert press_sheet(world, sheet.S_SKIP, "Any")[1] == "⏭️ **Any** · skipped"
    pressed, said = press_sheet(world, sheet.S_AT, "Evening pill")
    assert said == "asked for the time" and pressed.form.title == sheet.FORM_TITLE and pressed.form.action == sheet.S_AT
    pressed, said = press_sheet(world, sheet.S_AT, "Evening pill", fields={"at": "8:10 pm"})
    assert said == "✅ **Evening pill** · taken 8:10 pm" and not pressed.removed
