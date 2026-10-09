"""Cards (core/cards.py): buttons, dropdowns and forms for tasks that may not use discord.py."""
import asyncio
from types import SimpleNamespace

import pytest

from core import cards, database
from core.cards import Button, Card, Field, Form, Option, Select
from core.errors import UserError


# ---------------------------------------------------------------------------
# Ids: everything a press needs is in them
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, task, action, arg",
    [("b", "pills", "save", "12"), ("s", "pills", "pick", ""), ("f", "pills", "taken_at", "7:2:0830"), ("b", "a_b", "c9", "x:y:z")],
)
def test_an_id_carries_its_task_action_and_argument(kind, task, action, arg):
    custom_id = cards.make_id(kind, task, action, arg)
    assert cards.parse_id(custom_id) == (kind, task, action, arg)


@pytest.mark.parametrize("custom_id", ["", "dev:panel:extend", "card.b:pills", "card.x:pills:save:1", "card.b:Pills:save:1"])
def test_other_ids_are_not_ours(custom_id):
    assert cards.parse_id(custom_id) is None


def test_an_id_that_discord_would_refuse_is_refused_here():
    with pytest.raises(ValueError, match="at most 100"):
        cards.make_id("b", "pills", "save", "x" * 100)
    with pytest.raises(ValueError, match="lower-case names"):
        cards.make_id("b", "Pills", "save")
    with pytest.raises(ValueError, match="lower-case names"):
        cards.make_id("b", "pills", "save:now")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def button(action="go", arg="", label="Go"):
    return Button(label, "test", action, arg)


def options(count):
    return tuple(Option(f"Option {number}", str(number)) for number in range(count))


def test_a_card_within_discords_limits_passes():
    cards.check(Card("text"))
    cards.check(Card("text", ((button(arg="1"), button(arg="2")), Select("test", "pick", options(25)))))


@pytest.mark.parametrize(
    "card, reason",
    [
        (Card("t", tuple((button(arg=str(n)),) for n in range(6))), "at most 5 rows"),
        (Card("t", (tuple(button(arg=str(n)) for n in range(6)),)), "1 to 5 buttons"),
        (Card("t", ((),)), "1 to 5 buttons"),
        (Card("t", ((button(label="x" * 81),),)), "label is at most 80"),
        (Card("t", ((button(), button()),)), "share the id"),
        (Card("t", (Select("test", "pick", ()),)), "1 to 25 options"),
        (Card("t", (Select("test", "pick", options(26)),)), "1 to 25 options"),
        (Card("t", (Select("test", "pick", (Option("a", "1"), Option("b", "1"))),)), "different values"),
        (Card("t", (Select("test", "pick", options(2), max_values=3),)), "more picks"),
    ],
)
def test_a_card_discord_would_refuse_is_refused_with_the_reason(card, reason):
    with pytest.raises(ValueError, match=reason):
        cards.check(card)


def test_forms_have_one_to_five_differently_named_fields():
    cards.check_form(Form("When?", "test", "at", (Field("time", "Time"),)))
    with pytest.raises(ValueError, match="1 to 5 fields"):
        cards.check_form(Form("When?", "test", "at", ()))
    with pytest.raises(ValueError, match="different names"):
        cards.check_form(Form("When?", "test", "at", (Field("time", "A"), Field("time", "B"))))
    with pytest.raises(ValueError, match="title"):
        cards.check_form(Form("x" * 46, "test", "at", (Field("time", "Time"),)))


def test_a_long_name_is_cut_to_fit_a_label():
    assert cards.truncate_label("Vitamin D") == "Vitamin D"
    cut = cards.truncate_label("x" * 200)
    assert len(cut) == 80 and cut.endswith("…")


# ---------------------------------------------------------------------------
# What discord.py is given
# ---------------------------------------------------------------------------
def test_a_card_becomes_components_with_our_ids_that_never_time_out():
    async def build():
        card = Card(
            "text",
            (
                (Button("Save", "pills", "save", "5", emoji="✅", style=cards.SUCCESS), Button("Edit", "pills", "edit", "5")),
                Select("pills", "pick", (Option("Iron", "3", "paused"),), placeholder="Choose…"),
            ),
        )
        built = cards.view(card)
        return built.timeout, [(item.item.custom_id, item.item.row, type(item.item).__name__) for item in built.children]

    timeout, items = asyncio.run(build())
    assert timeout is None, "so the buttons work for as long as the message exists"
    assert items == [
        ("card.b:pills:save:5", 0, "Button"),
        ("card.b:pills:edit:5", 0, "Button"),
        ("card.s:pills:pick:", 1, "Select"),
    ]


def test_a_card_with_no_components_has_no_view():
    assert cards.view(Card("✅ Saved")) is None, "which also takes the buttons off a message being edited"


def test_buttons_and_dropdowns_are_told_apart_by_their_ids():
    # discord.py matches a pressed component against every registered pattern, whatever its type
    import re

    button_pattern = cards._CardButton.__discord_ui_compiled_template__
    select_pattern = cards._CardSelect.__discord_ui_compiled_template__
    assert button_pattern.fullmatch("card.b:pills:save:5") and not select_pattern.fullmatch("card.b:pills:save:5")
    assert select_pattern.fullmatch("card.s:pills:pick:") and not button_pattern.fullmatch("card.s:pills:pick:")
    assert isinstance(button_pattern, re.Pattern)


# ---------------------------------------------------------------------------
# A press
# ---------------------------------------------------------------------------
class Interaction:
    """Stands in for discord.Interaction: records how it was answered."""

    def __init__(self, user_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.channel_id = 100
        self.message = SimpleNamespace(id=555)
        self.data = {}
        self.calls = []
        outer = self

        class Response:
            done = False

            def is_done(self):
                return self.done

            async def defer(self):
                self.done = True
                outer.calls.append("defer")

            async def edit_message(self, **kwargs):
                self.done = True
                outer.calls.append(("edit_message", kwargs["content"]))

            async def send_message(self, text, ephemeral=False):
                self.done = True
                outer.calls.append(("send_message", text, ephemeral))

            async def send_modal(self, modal):
                self.done = True
                outer.calls.append(("send_modal", modal.title, [entry.label for entry in modal.form.fields]))

        class Followup:
            async def send(self, text, ephemeral=False):
                outer.calls.append(("followup", text, ephemeral))

        self.response, self.followup = Response(), Followup()

    async def edit_original_response(self, **kwargs):
        self.calls.append(("edit_original", kwargs["content"], kwargs["view"]))

    async def delete_original_response(self):
        self.calls.append("delete_original")


@pytest.fixture
def actions(db, monkeypatch):
    monkeypatch.setattr(cards, "_actions", {})
    errors = []

    async def report(interaction, error, title, reply=""):
        errors.append((title, repr(error)))

    monkeypatch.setattr(cards, "report_interaction_error", report)
    return errors


def logged():
    conn = database.connect()
    try:
        return conn.execute("SELECT kind, content, reply, status, error FROM message_log ORDER BY id").fetchall()
    finally:
        conn.close()


def test_a_press_is_answered_first_then_logged_then_handled(actions):
    seen = []

    async def on_save(press):
        seen.append((press.user.id, press.task, press.action, press.arg, press.message_id, list(press.shown)))
        await press.update(Card("✅ Saved"))
        return "saved draft 5"

    cards.register("pills", "save", on_save)
    interaction = Interaction()
    asyncio.run(cards.handle(interaction, "pills", "save", "5"))

    assert seen == [(1, "pills", "save", "5", 555, [])]
    assert interaction.calls == ["defer", ("edit_original", "✅ Saved", None)], "deferred before anything else"
    assert logged() == [("card", "card: pills/save 5", "saved draft 5", "ok", None)]


def test_what_was_picked_in_a_dropdown_reaches_the_handler(actions):
    seen = []

    async def on_pick(press):
        seen.append(press.values)

    cards.register("pills", "pick", on_pick)
    asyncio.run(cards.handle(Interaction(), "pills", "pick", "", values=("3",)))
    assert seen == [("3",)]
    assert logged()[0][1:3] == ("card: pills/pick picked ['3']", "done")


def test_a_problem_the_presser_can_fix_is_told_to_them_alone(actions):
    async def on_save(press):
        raise UserError("That pill isn't there any more.")

    cards.register("pills", "save", on_save)
    interaction = Interaction()
    asyncio.run(cards.handle(interaction, "pills", "save", "5"))
    assert interaction.calls == ["defer", ("followup", "⚠️ That pill isn't there any more.", True)]
    assert logged()[0][3:] == ("error", "That pill isn't there any more.")
    assert actions == [], "not an error for #bot-log"


def test_any_other_failure_is_reported(actions):
    async def on_save(press):
        raise RuntimeError("boom")

    cards.register("pills", "save", on_save)
    asyncio.run(cards.handle(Interaction(), "pills", "save", "5"))
    assert actions == [("Card action failed: pills/save", "RuntimeError('boom')")]


def test_someone_else_cannot_press(actions):
    ran = []

    async def on_save(press):
        ran.append(press)

    cards.register("pills", "save", on_save)
    interaction = Interaction(user_id=22)
    asyncio.run(cards.handle(interaction, "pills", "save", "5"))
    assert ran == []
    assert interaction.calls == [("send_message", "That isn't yours to press.", True)]
    assert logged() == []


def test_a_component_whose_task_has_gone_says_so(actions):
    interaction = Interaction()
    asyncio.run(cards.handle(interaction, "gone", "save", "5"))
    assert interaction.calls == [("send_message", cards.GONE, True)]


def test_a_form_is_the_first_answer_and_its_submission_comes_back_with_what_was_typed(actions):
    seen = []

    async def on_at(press):
        if press.fields is None:
            await press.open_form(Form("Taken at…", "pills", "at", (Field("time", "What time?", placeholder="8:30am"),), arg=press.arg))
            return "form opened"
        seen.append(press.fields)
        await press.update(Card("✅ taken 8:30 am"))

    cards.register("pills", "at", on_at, opens_form=True)

    opened = Interaction()
    asyncio.run(cards.handle(opened, "pills", "at", "7"))
    assert opened.calls == [("send_modal", "Taken at…", ["What time?"])], "nothing may be answered before a form"

    submitted = Interaction()
    asyncio.run(cards.handle(submitted, "pills", "at", "7", fields={"time": "8:30am"}))
    assert seen == [{"time": "8:30am"}]
    assert submitted.calls[0] == "defer"
    assert [row[1] for row in logged()] == ["card: pills/at 7", "card: pills/at 7 typed {'time': '8:30am'}"]


def test_a_form_cannot_be_opened_by_an_action_that_did_not_say_it_might(actions):
    async def on_at(press):
        await press.open_form(Form("Taken at…", "pills", "at", (Field("time", "What time?"),)))

    cards.register("pills", "at", on_at)
    asyncio.run(cards.handle(Interaction(), "pills", "at", "7"))
    assert "opens_form=True" in actions[0][1]


def test_an_opens_form_action_that_opens_none_is_still_answered(actions):
    async def on_at(press):
        return "decided not to"

    cards.register("pills", "at", on_at, opens_form=True)
    interaction = Interaction()
    asyncio.run(cards.handle(interaction, "pills", "at", "7"))
    assert interaction.calls == ["defer"]


def test_posting_a_card_is_the_reply_to_what_the_user_sent():
    sent = []

    async def reply(text, view=None):
        sent.append((text, view))
        return SimpleNamespace(id=777)

    async def scenario():
        ctx = SimpleNamespace(reply=reply)
        with_buttons = await cards.post(ctx, Card("Remove?", ((Button("Remove", "pills", "remove_yes", "3"),),)))
        plain = await cards.post(ctx, Card("Nothing here"))
        return with_buttons, plain

    assert asyncio.run(scenario()) == (777, 777)
    assert sent[0][0] == "Remove?" and sent[0][1] is not None
    assert sent[1] == ("Nothing here", None)


def test_without_a_client_nothing_is_sent_edited_or_deleted(monkeypatch):
    from core import discord_utils

    monkeypatch.setattr(discord_utils, "client", None)

    async def scenario():
        return await cards.send(400, Card("x")), await cards.edit(400, 1, Card("x")), await cards.delete(400, 1)

    assert asyncio.run(scenario()) == (None, False, False)
