import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import discord

from core import database, discord_utils
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import report_interaction_error, safe_reply
from core.errors import UserError
from core.permissions import is_allowed
from core.users import User, get_user_by_discord_id

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Cards: a message of the bot's with buttons, a dropdown or a form, for tasks
# that may not use discord.py themselves.
#
# A task describes a card with the plain records below (Card, Button, Select,
# Form) and says what each of its actions does:
#
#     cards.register("pills", "save", on_save)      # once, at import or in setup
#     await cards.post(ctx, Card("…", (Button("Save", "pills", "save", "d5"),)))
#
#     async def on_save(press: cards.Press) -> str:
#         ...                                        # press.arg == "d5"
#         await press.update(Card("✅ Saved"))
#         return "saved draft d5"                    # recorded in message_log
#
# Everything a press needs is in the component's id ("card.b:pills:save:d5"),
# so nothing is held in memory and a card posted before a restart still works.
# Keep the arg to an id of the task's own record; the state lives in its tables.
#
# This file does what every interaction must: answers within 3 seconds
# (deferring first), checks permission with is_allowed, logs the press in
# message_log, shows a UserError to the presser alone, and reports anything
# else in #bot-log.
# ---------------------------------------------------------------------------
PRIMARY, SECONDARY, SUCCESS, DANGER = "primary", "secondary", "success", "danger"
_STYLES = {
    PRIMARY: discord.ButtonStyle.primary,
    SECONDARY: discord.ButtonStyle.secondary,
    SUCCESS: discord.ButtonStyle.success,
    DANGER: discord.ButtonStyle.danger,
}

# Discord's limits
MAX_ROWS = 5
MAX_BUTTONS_IN_ROW = 5
MAX_OPTIONS = 25
MAX_ID = 100
MAX_LABEL = 80
MAX_OPTION_TEXT = 100
MAX_FORM_FIELDS = 5
MAX_FORM_TITLE = 45

_BUTTON, _SELECT, _FORM = "b", "s", "f"
_NAME = r"[a-z0-9_]+"
_ID = re.compile(rf"card\.(?P<kind>[bsf]):(?P<task>{_NAME}):(?P<action>{_NAME}):(?P<arg>.*)", re.DOTALL)

GONE = "⌛ That no longer works: what it belonged to has gone. Ask for it again."


# ---------------------------------------------------------------------------
# What a task writes (pure)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Button:
    label: str
    task: str
    action: str
    arg: str = ""  # which record this is about; comes back as press.arg
    emoji: str | None = None
    style: str = SECONDARY
    disabled: bool = False


@dataclass(frozen=True)
class Option:
    label: str
    value: str
    description: str = ""
    emoji: str | None = None


@dataclass(frozen=True)
class Select:
    """A dropdown: one control however many things there are to choose from.
    What was picked comes back as press.values."""

    task: str
    action: str
    options: tuple[Option, ...]
    placeholder: str = ""
    arg: str = ""
    max_values: int = 1


@dataclass(frozen=True)
class Field:
    name: str  # the key in press.fields
    label: str
    value: str = ""
    placeholder: str = ""
    required: bool = True


@dataclass(frozen=True)
class Form:
    """A small pop-up form. It can only be opened as the first answer to a
    press, so its action is registered with `opens_form=True`; what was typed
    comes back to `action` as press.fields."""

    title: str
    task: str
    action: str
    fields: tuple[Field, ...]
    arg: str = ""


@dataclass(frozen=True)
class Card:
    """A message: its text, and rows of buttons (a tuple of them) or one dropdown."""

    text: str
    rows: tuple[tuple[Button, ...] | Select, ...] = ()


def make_id(kind: str, task: str, action: str, arg: str = "") -> str:
    custom_id = f"card.{kind}:{task}:{action}:{arg}"
    if not re.fullmatch(_NAME, task) or not re.fullmatch(_NAME, action):
        raise ValueError(f"A card's task and action are lower-case names: {task!r}, {action!r}")
    if len(custom_id) > MAX_ID:
        raise ValueError(f"A card component's id is at most {MAX_ID} characters: {custom_id!r}")
    return custom_id


def parse_id(custom_id: str) -> tuple[str, str, str, str] | None:
    """(kind, task, action, arg) of one of our component ids, or None."""
    match = _ID.fullmatch(custom_id or "")
    return (match["kind"], match["task"], match["action"], match["arg"]) if match else None


def check(card: Card) -> None:
    """Refuse a card Discord would refuse, with a reason that names the problem.
    Raises ValueError: this is a mistake in the code, not the user's."""
    if len(card.rows) > MAX_ROWS:
        raise ValueError(f"A card has at most {MAX_ROWS} rows, not {len(card.rows)}")
    seen: set[str] = set()
    for row in card.rows:
        if isinstance(row, Select):
            if not 1 <= len(row.options) <= MAX_OPTIONS:
                raise ValueError(f"A dropdown has 1 to {MAX_OPTIONS} options, not {len(row.options)}")
            if not 1 <= row.max_values <= len(row.options):
                raise ValueError("A dropdown can't allow more picks than it has options")
            values = [option.value for option in row.options]
            if len(set(values)) != len(values):
                raise ValueError("A dropdown's options need different values")
            if any(len(text) > MAX_OPTION_TEXT for option in row.options for text in (option.label, option.value)):
                raise ValueError(f"A dropdown option's label and value are at most {MAX_OPTION_TEXT} characters")
            ids = [make_id(_SELECT, row.task, row.action, row.arg)]
        else:
            if not 1 <= len(row) <= MAX_BUTTONS_IN_ROW:
                raise ValueError(f"A row has 1 to {MAX_BUTTONS_IN_ROW} buttons, not {len(row)}")
            if any(len(button.label) > MAX_LABEL for button in row):
                raise ValueError(f"A button's label is at most {MAX_LABEL} characters")
            ids = [make_id(_BUTTON, button.task, button.action, button.arg) for button in row]
        for custom_id in ids:
            if custom_id in seen:
                raise ValueError(f"Two components on one card share the id {custom_id!r}")
            seen.add(custom_id)


def check_form(form: Form) -> None:
    if not 1 <= len(form.fields) <= MAX_FORM_FIELDS:
        raise ValueError(f"A form has 1 to {MAX_FORM_FIELDS} fields, not {len(form.fields)}")
    if len(form.title) > MAX_FORM_TITLE:
        raise ValueError(f"A form's title is at most {MAX_FORM_TITLE} characters")
    if len({entry.name for entry in form.fields}) != len(form.fields):
        raise ValueError("A form's fields need different names")
    make_id(_FORM, form.task, form.action, form.arg)


def truncate_label(text: str, limit: int = MAX_LABEL) -> str:
    """A label cut to fit, for names the user chose."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# What the task's action is handed
# ---------------------------------------------------------------------------
@dataclass
class Press:
    """One press of a button, pick from a dropdown, or submitted form."""

    user: User
    task: str
    action: str
    arg: str
    channel_id: int | None
    message_id: int | None
    values: tuple[str, ...] = ()  # what was picked in a dropdown
    fields: dict[str, str] | None = None  # what was typed in a form; None unless it is one
    _interaction: discord.Interaction | None = field(default=None, repr=False)
    shown: list[str] = field(default_factory=list)  # what the presser was shown, for the log

    # Database access, as on Context
    db = database

    def _answered(self) -> bool:
        return self._interaction.response.is_done()

    async def update(self, card: Card) -> None:
        """Rewrite the message the component is on, in place."""
        check(card)
        self.shown.append(card.text)
        if self._answered():
            await self._interaction.edit_original_response(content=card.text, view=view(card))
        else:
            await self._interaction.response.edit_message(content=card.text, view=view(card))

    async def say(self, text: str) -> None:
        """Tell the presser something only they see."""
        self.shown.append(text)
        await safe_reply(self._interaction, text)

    async def open_form(self, form: Form) -> None:
        """Pop a form up. Only possible as the first answer (register with opens_form)."""
        check_form(form)
        if self._answered():
            raise RuntimeError(f"{self.task}/{self.action} must be registered with opens_form=True to open a form")
        self.shown.append(f"form: {form.title}")
        await self._interaction.response.send_modal(_Modal(form))

    async def remove(self) -> None:
        """Delete the message the component is on."""
        self.shown.append("message removed")
        if not self._answered():
            await self._interaction.response.defer()
        await self._interaction.delete_original_response()


Handler = Callable[[Press], Awaitable[str | None]]


@dataclass(frozen=True)
class _Action:
    handler: Handler
    permission: str
    opens_form: bool


_actions: dict[tuple[str, str], _Action] = {}


def register(task: str, action: str, handler: Handler, *, permission: str = "", opens_form: bool = False) -> None:
    """Say what runs when a component with this task and action is used.

    `handler(press)` returns what to record in the log (None records what the
    presser was shown). `permission` is what is_allowed is asked, by default
    "card:<task>". Set `opens_form` if the handler may answer with a form.
    """
    make_id(_BUTTON, task, action)  # the names must be usable in an id
    _actions[(task, action)] = _Action(handler, permission or f"card:{task}", opens_form)


async def handle(
    interaction: discord.Interaction,
    task: str,
    action: str,
    arg: str,
    values: tuple[str, ...] = (),
    fields: dict[str, str] | None = None,
) -> None:
    """Run the action behind a press. Never raises."""
    try:
        registered = _actions.get((task, action))
        if registered is None:
            # Its task isn't loaded any more
            await safe_reply(interaction, GONE)
            return
        user = await get_user_by_discord_id(interaction.user.id)
        if not is_allowed(user, registered.permission):
            await safe_reply(interaction, "That isn't yours to press.")
            return
        # Answer straight away, unless the answer may be a form (which has to come first)
        if fields is not None or not registered.opens_form:
            await interaction.response.defer()

        message = getattr(interaction, "message", None)
        press = Press(
            user, task, action, arg, interaction.channel_id, getattr(message, "id", None), values, fields, interaction
        )
        detail = "".join(
            [f" {arg}" if arg else "", f" picked {list(values)}" if values else "", f" typed {fields}" if fields else ""]
        )
        row_id = await log_received(
            f"card: {task}/{action}{detail}", "card", press.message_id, press.channel_id, user_id=user.id
        )
        try:
            reply = await registered.handler(press)
        except UserError as error:
            # The presser can fix this one: tell them, and nobody else
            log.info("Card %s/%s not done: %s", task, action, error)
            await log_result(row_id, status="error", error=str(error))
            await safe_reply(interaction, f"⚠️ {error}")
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        await log_result(row_id, reply=reply or "\n".join(press.shown) or "done", status="ok")
    except Exception as error:
        await report_interaction_error(interaction, error, f"Card action failed: {task}/{action}")


# ---------------------------------------------------------------------------
# Discord's side: components that find their action from their id
# ---------------------------------------------------------------------------
class _CardButton(discord.ui.DynamicItem[discord.ui.Button], template=rf"card\.b:(?P<task>{_NAME}):(?P<action>{_NAME}):(?P<arg>.*)"):
    def __init__(self, button: Button):
        super().__init__(
            discord.ui.Button(
                label=button.label,
                emoji=button.emoji,
                style=_STYLES[button.style],
                disabled=button.disabled,
                custom_id=make_id(_BUTTON, button.task, button.action, button.arg),
            )
        )
        self.spec = button

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(Button(item.label or "", match["task"], match["action"], match["arg"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await handle(interaction, self.spec.task, self.spec.action, self.spec.arg)


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
                custom_id=make_id(_SELECT, select.task, select.action, select.arg),
            )
        )
        self.spec = select

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        # Only the id matters here: the options are the message's own
        return cls(Select(match["task"], match["action"], (Option("-", "-"),), arg=match["arg"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        picked = tuple((interaction.data or {}).get("values", ()))
        await handle(interaction, self.spec.task, self.spec.action, self.spec.arg, values=picked)


class _Modal(discord.ui.Modal):
    def __init__(self, form: Form):
        super().__init__(title=form.title, custom_id=make_id(_FORM, form.task, form.action, form.arg))
        self.form = form
        self.inputs: dict[str, discord.ui.TextInput] = {}
        for entry in form.fields:
            text_input = discord.ui.TextInput(
                label=entry.label,
                default=entry.value or None,
                placeholder=entry.placeholder or None,
                required=entry.required,
            )
            self.inputs[entry.name] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        typed = {name: (text_input.value or "").strip() for name, text_input in self.inputs.items()}
        await handle(interaction, self.form.task, self.form.action, self.form.arg, fields=typed)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_interaction_error(interaction, error, f"Card form failed: {self.form.task}/{self.form.action}")


def view(card: Card) -> discord.ui.View | None:
    """The card's components as discord.py wants them; None if it has none
    (which also takes the old ones off a message being edited)."""
    check(card)
    if not card.rows:
        return None
    built = discord.ui.View(timeout=None)
    for number, row in enumerate(card.rows):
        items = [_CardSelect(row)] if isinstance(row, Select) else [_CardButton(button) for button in row]
        for item in items:
            item.item.row = number
            built.add_item(item)
    return built


def setup(client: discord.Client) -> None:
    """Before connecting, so components on cards from before a restart still answer."""
    client.add_dynamic_items(_CardButton, _CardSelect)


# ---------------------------------------------------------------------------
# Posting, editing and removing a card
# ---------------------------------------------------------------------------
async def post(ctx: Context, card: Card) -> int | None:
    """Send a card as the reply to what the user sent. Returns the message's id."""
    built = view(card)
    message = await ctx.reply(card.text, view=built)
    return getattr(message, "id", None)


def _channel(channel_id: int | None):
    client = discord_utils.client
    return client.get_channel(channel_id) if client is not None and channel_id else None


async def send(channel_id: int, card: Card, *, silent: bool = False) -> int | None:
    """Post a card in a channel, with no message of the user's to answer.
    `silent` posts without a notification. Returns the message's id, or None
    if the channel can't be found."""
    channel = _channel(channel_id)
    if channel is None:
        log.warning("Could not post a card: channel %s not found", channel_id)
        return None
    built = view(card)
    if built is None:
        message = await channel.send(card.text, silent=silent)
    else:
        message = await channel.send(card.text, view=built, silent=silent)
    return message.id


async def edit(channel_id: int, message_id: int, card: Card) -> bool:
    """Rewrite a card in place. False if it has gone or can't be reached."""
    channel = _channel(channel_id)
    if channel is None:
        return False
    try:
        await channel.get_partial_message(message_id).edit(content=card.text, view=view(card))
    except discord.NotFound:
        return False
    except discord.HTTPException as error:
        log.warning("Could not edit card %s: %s", message_id, error)
        return False
    return True


async def delete(channel_id: int, message_id: int) -> bool:
    """Delete a card. Best effort: False if it had already gone or can't be reached.
    The caller asks core/lifecycle.py first if this is the bot tidying up by itself."""
    channel = _channel(channel_id)
    if channel is None:
        return False
    try:
        await channel.get_partial_message(message_id).delete()
    except discord.HTTPException:
        return False
    return True
