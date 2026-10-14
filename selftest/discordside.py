from dataclasses import dataclass, field

import discord

# ---------------------------------------------------------------------------
# The self-test's stand-ins for what only a person can send, and its reading
# of what Discord then holds.
#
# A typed message: the bot posts the words itself, so there is a real message
# with a real id to react to, reply to and delete, and that message is handed
# to the bot's own `on_message` with the owner as its author (`Typed`).
#
# A press: there is no way to press a button from a bot, so the handler behind
# it is called with an interaction that answers by doing the real thing to the
# real message (`Pressed`): an edit is a real edit, a delete a real delete.
# What only the presser would have seen (an ephemeral line, a form) is kept
# here to be checked.
# ---------------------------------------------------------------------------


class Typed:
    """A real message of the bot's, seen as if the owner had typed it."""

    def __init__(self, real: discord.Message, author):
        self._real, self.author = real, author

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Response:
    def __init__(self, press: "Pressed"):
        self._press, self._done = press, False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, **_) -> None:
        self._done = True

    async def edit_message(self, **drawn) -> None:
        self._done = True
        await self._press.message.edit(**drawn)
        self._press.edits += 1

    async def send_message(self, text=None, **_) -> None:
        self._done = True
        self._press.said.append(text or "")

    async def send_modal(self, modal) -> None:
        self._done = True
        self._press.form = modal


class _Followup:
    def __init__(self, press: "Pressed"):
        self._press = press

    async def send(self, text=None, **_) -> None:
        self._press.said.append(text or "")


class Pressed:
    """An interaction that was never sent by Discord: what the bot does with
    it happens to the real message."""

    type = discord.InteractionType.component

    def __init__(self, user, message: discord.Message, custom_id: str):
        self.user, self.message, self.channel_id = user, message, message.channel.id
        self.channel, self.guild = message.channel, getattr(message, "guild", None)
        self.data = {"custom_id": custom_id}
        self.said: list[str] = []  # what only the presser was shown
        self.form = None  # the form that was opened, if one was
        self.edits, self.deleted = 0, False
        self.response, self.followup = _Response(self), _Followup(self)
        self.command = None

    async def edit_original_response(self, **drawn) -> None:
        await self.message.edit(**drawn)
        self.edits += 1

    async def delete_original_response(self) -> None:
        await self.message.delete()
        self.deleted = True


@dataclass
class Seen:
    """One message as Discord holds it now."""

    id: int
    text: str  # its content, or every text of a Components V2 message, a line each
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (label, custom id)
    v2: bool = False
    accents: list[int | None] = field(default_factory=list)  # each box's accent colour
    reactions: list[str] = field(default_factory=list)  # the bot's own reactions
    embeds: list[tuple[str, str]] = field(default_factory=list)  # (title, description and fields)
    edited: bool = False
    from_bot: bool = True
    silent: bool = False
    reference: int | None = None
    menus: list[tuple[str, str, list[tuple[str, str]]]] = field(default_factory=list)  # (placeholder, custom id, [(label, value)])

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.buttons]

    def button(self, label: str) -> str | None:
        """The custom id of the button whose label has `label` in it."""
        return next((custom_id for said, custom_id in self.buttons if label.lower() in said.lower()), None)

    @property
    def all_text(self) -> str:
        return "\n".join([self.text, *(f"{title}\n{body}" for title, body in self.embeds)])


def _walk(components, texts: list[str], buttons: list, accents: list, menus: list | None = None) -> None:
    for each in components or []:
        kind = type(each).__name__
        if kind == "Container":
            colour = getattr(each, "accent_colour", None)
            accents.append(getattr(colour, "value", colour))
        if kind == "TextDisplay":
            texts.append(str(getattr(each, "content", "")))
        if getattr(each, "custom_id", None) and hasattr(each, "label"):
            emoji = getattr(each, "emoji", None)
            label = " ".join(part for part in (str(emoji) if emoji else "", each.label or "") if part)
            buttons.append((label, each.custom_id))
        elif getattr(each, "custom_id", None) and getattr(each, "options", None) and menus is not None:
            menus.append((each.placeholder or "", each.custom_id, [(option.label, option.value) for option in each.options]))
        for name in ("children", "components", "accessory"):
            inner = getattr(each, name, None)
            if inner is not None:
                _walk(inner if isinstance(inner, (list, tuple)) else [inner], texts, buttons, accents, menus)


def seen(message: discord.Message, bot_id: int) -> Seen:
    texts, buttons, accents, menus = [], [], [], []
    _walk(message.components, texts, buttons, accents, menus)
    embeds = []
    for embed in message.embeds:
        body = "\n".join([embed.description or "", *(f"{each.name}: {each.value}" for each in embed.fields)])
        embeds.append((embed.title or "", body))
    reference = message.reference.message_id if message.reference else None
    return Seen(
        id=message.id,
        text="\n".join(part for part in [message.content, *texts] if part),
        buttons=buttons,
        v2=bool(getattr(message.flags, "components_v2", False)),
        accents=accents,
        reactions=[str(reaction.emoji) for reaction in message.reactions if reaction.me],
        embeds=embeds,
        edited=message.edited_at is not None,
        from_bot=message.author.id == bot_id,
        silent=bool(getattr(message.flags, "suppress_notifications", False) or getattr(message.flags, "silent", False)),
        reference=reference,
        menus=menus,
    )
