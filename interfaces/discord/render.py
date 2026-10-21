import logging
import re

import discord

from core import cards, design, outgoing
from core.cards import Button, Card, Form, Option, Select
from core.discord_utils import report_interaction_error, safe_reply

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A card, drawn for Discord. The card itself is plain records (core/cards.py,
# core/design.py); here they become buttons, dropdowns, forms and Components
# V2 layouts, each component finding its action from its id, so that a card
# posted before a restart still answers.
#
# And a press, as the core is handed it: `Answer` wraps a discord.Interaction
# so that core/cards.py can answer one without knowing what it is.
# ---------------------------------------------------------------------------
_STYLES = {
    cards.PRIMARY: discord.ButtonStyle.primary,
    cards.SECONDARY: discord.ButtonStyle.secondary,
    cards.SUCCESS: discord.ButtonStyle.success,
    cards.DANGER: discord.ButtonStyle.danger,
}
_NAME = cards._NAME
_BUTTON, _SELECT, _FORM = cards._BUTTON, cards._SELECT, cards._FORM


class _CardButton(discord.ui.DynamicItem[discord.ui.Button], template=rf"card\.b:(?P<task>{_NAME}):(?P<action>{_NAME}):(?P<arg>.*)"):
    def __init__(self, button: Button):
        super().__init__(
            discord.ui.Button(
                label=button.label,
                emoji=button.emoji,
                style=_STYLES[button.style],
                disabled=button.disabled,
                custom_id=cards.make_id(_BUTTON, button.task, button.action, button.arg),
            )
        )
        self.spec = button

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(Button(item.label or "", match["task"], match["action"], match["arg"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await cards.handle(interaction, self.spec.task, self.spec.action, self.spec.arg)


class _CardSelect(discord.ui.DynamicItem[discord.ui.Select], template=rf"card\.s:(?P<task>{_NAME}):(?P<action>{_NAME}):(?P<arg>.*)"):
    def __init__(self, select: Select):
        super().__init__(
            discord.ui.Select(
                placeholder=select.placeholder or None,
                max_values=select.max_values,
                options=[
                    discord.SelectOption(
                        label=option.label, value=option.value, description=option.description or None, emoji=option.emoji
                    )
                    for option in select.options
                ],
                custom_id=cards.make_id(_SELECT, select.task, select.action, select.arg),
            )
        )
        self.spec = select

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        # Only the id matters here: the options are the message's own
        return cls(Select(match["task"], match["action"], (Option("-", "-"),), arg=match["arg"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        picked = tuple((interaction.data or {}).get("values", ()))
        await cards.handle(interaction, self.spec.task, self.spec.action, self.spec.arg, values=picked)


class _Modal(discord.ui.Modal):
    def __init__(self, form: Form):
        super().__init__(title=form.title, custom_id=cards.make_id(_FORM, form.task, form.action, form.arg))
        self.form = form
        self.inputs: dict[str, discord.ui.TextInput] = {}
        for entry in form.fields:
            text_input = discord.ui.TextInput(
                label=entry.label,
                default=entry.value or None,
                placeholder=entry.placeholder or None,
                required=entry.required,
                style=discord.TextStyle.paragraph if entry.long else discord.TextStyle.short,
                max_length=cards.MAX_LONG if entry.long else None,
            )
            self.inputs[entry.name] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        typed = {name: (text_input.value or "").strip() for name, text_input in self.inputs.items()}
        await cards.handle(interaction, self.form.task, self.form.action, self.form.arg, fields=typed)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_interaction_error(interaction, error, f"Card form failed: {self.form.task}/{self.form.action}")


def view(card: Card) -> discord.ui.View | None:
    """The card's components as discord.py wants them; None if it has none
    (which also takes the old ones off a message being edited)."""
    cards.check(card)
    if not card.rows:
        return None
    built = discord.ui.View(timeout=None)
    for number, row in enumerate(card.rows):
        items = [_CardSelect(row)] if isinstance(row, Select) else [_CardButton(button) for button in row]
        for item in items:
            item.item.row = number
            built.add_item(item)
    return built


def layout_view(pieces: tuple) -> discord.ui.LayoutView:
    """A layout (core/design.py records) as a Components V2 message. Every
    colour and spacing comes from core/design.py."""
    cards.check_layout(pieces)

    def built(piece):
        if isinstance(piece, design.Text):
            return discord.ui.TextDisplay(outgoing.clean(piece.content) or piece.content)
        if isinstance(piece, design.Separator):
            spacing = discord.SeparatorSpacing.large if piece.large else discord.SeparatorSpacing.small
            return discord.ui.Separator(visible=piece.line, spacing=spacing)
        if isinstance(piece, design.Row):
            return discord.ui.ActionRow(*(_CardButton(button) for button in piece.buttons))
        if isinstance(piece, Select):
            return discord.ui.ActionRow(_CardSelect(piece))
        return discord.ui.Container(*(built(child) for child in piece.children), accent_colour=discord.Colour(design.embed_colour(piece.status)))

    drawn = discord.ui.LayoutView(timeout=None)
    for piece in pieces:
        drawn.add_item(built(piece))
    return drawn


def embeds(card: Card) -> list[discord.Embed]:
    """A card's embeds (round 7's briefing, a news card) as Discord's, each with its border colour
    (core/design.py), and its author line and its title's link where it has them."""
    drawn = []
    for each in card.embeds:
        embed = discord.Embed(
            title=(outgoing.clean(each.title) or each.title) if each.title else None,
            description=(outgoing.clean(each.description) or each.description) if each.description else None,
            colour=discord.Colour(design.embed_colour(each.status)) if each.status else None,
            url=each.url or None,
        )
        if each.author:
            embed.set_author(name=outgoing.clean(each.author) or each.author)
        drawn.append(embed)
    return drawn


def heading(card: Card) -> str | None:
    """The line above a card's embeds, or None for none."""
    return (outgoing.clean(card.heading) or card.heading) if card.heading else None


def reply_view(card: Card):
    """What a reply is sent with: the layout when the card is drawn as one, else its rows."""
    return layout_view(card.layout) if cards.designed(card) else view(card)


def drawn(card: Card, was_designed: bool = False) -> dict:
    """What a message is rewritten with: the card's layout when CARDS_V2 is on
    and it has one; else its text and rows. A message that is Components V2
    already can never go back to plain text, so a plain card rewrites it as a
    layout of that same text and those same rows."""
    if card.embeds:
        return {"content": heading(card), "embeds": embeds(card), "view": view(card)}
    if cards.designed(card):
        return {"content": None, "view": layout_view(card.layout)}
    if was_designed:
        return {"content": None, "view": layout_view(design.plain(card.text, card.rows))}
    return {"content": card.text, "view": view(card)}


def setup(client: discord.Client) -> None:
    """Before connecting, so components on cards from before a restart still answer."""
    client.add_dynamic_items(_CardButton, _CardSelect)


class Answer:
    """A press, as core/cards.py answers it."""

    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction

    @property
    def user_id(self) -> int:
        return self.interaction.user.id

    @property
    def channel_id(self) -> int | None:
        return self.interaction.channel_id

    @property
    def message_id(self) -> int | None:
        return getattr(getattr(self.interaction, "message", None), "id", None)

    def done(self) -> bool:
        return self.interaction.response.is_done()

    async def defer(self) -> None:
        await self.interaction.response.defer()

    async def say(self, text: str) -> None:
        await safe_reply(self.interaction, text)

    async def update(self, card: Card) -> None:
        flags = getattr(getattr(self.interaction, "message", None), "flags", None)
        rewritten = drawn(card, was_designed=bool(getattr(flags, "components_v2", False)))
        if self.done():
            await self.interaction.edit_original_response(**rewritten)
        else:
            await self.interaction.response.edit_message(**rewritten)

    async def open_form(self, form: Form) -> None:
        await self.interaction.response.send_modal(_Modal(form))

    async def remove(self) -> None:
        if not self.done():
            await self.interaction.response.defer()
        await self.interaction.delete_original_response()

    async def fail(self, error: Exception, title: str) -> None:
        await report_interaction_error(self.interaction, error, title)
