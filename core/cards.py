import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core import config, database, design, dms, messages, outgoing, surface
from core.context import Context
from core.database import log_received, log_result
from core.errors import UserError
from core.permissions import is_allowed
from core.users import User, get_user_by_discord_id

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Cards: a message of the bot's with buttons, a dropdown or a form, as plain
# data. Nothing here is Discord's: how a card is drawn, and how a press is
# answered, is the interface's business behind the door (core/surface.py;
# for Discord, interfaces/discord/render.py).
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
# This file does what every press must: answers within 3 seconds (deferring
# first), checks permission with is_allowed, logs the press in message_log,
# shows a UserError to the presser alone, and reports anything else in
# #bot-log.
# ---------------------------------------------------------------------------
PRIMARY, SECONDARY, SUCCESS, DANGER = "primary", "secondary", "success", "danger"

# The limits a card is checked against (Discord's: the strictest interface there is)
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
    # The colour says what kind of button it is, the same on every card (see COLOURS)
    style: str = PRIMARY
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
    """A message: its text, and rows of buttons (a tuple of them) or one dropdown.

    `layout` is the same card as Components V2 (core/design.py records, in
    the one style of docs/DESIGN.md). It is drawn only when CARDS_V2 is on;
    off, or for a card with no layout, the message is `text` and `rows`, as
    it always was. `text` is always there: it is what is logged and checked."""

    text: str
    rows: tuple[tuple[Button, ...] | Select, ...] = ()
    layout: tuple = ()


def designed(card: Card) -> bool:
    """Whether this card is drawn as Components V2."""
    return bool(card.layout) and config.CARDS_V2


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


# ---------------------------------------------------------------------------
# Button colours: one rule for every card (docs/CONVERSATION.md, section 4)
#   green   SUCCESS    the positive main action: Save, Taken
#   red     DANGER     destructive: Delete for good, Remove, Delete all, a bulk cancel
#   blurple PRIMARY    every other choice: Skip, Snooze, an answer to a question, a task
#   grey    SECONDARY  Cancel, and nothing else: grey is hard to read in dark mode
# Cancel is written with ↩️ (✖️ all but disappears on grey), and made with cancel().
# ---------------------------------------------------------------------------
CANCEL_EMOJI = "↩️"
CANCEL_LABEL = "Cancel"


def cancel(task: str, action: str, arg: str = "", label: str = CANCEL_LABEL) -> Button:
    """The one grey button: the way out of a card that changes nothing. `label`
    is for a card where "Cancel" would read oddly ("Neither", "None of these")."""
    return Button(label, task, action, arg, emoji=CANCEL_EMOJI, style=SECONDARY)


def colour_problem(label: str, style: str, emoji: str | None) -> str:
    """What is wrong with a button's colour, or "" if it follows the rule. Takes
    plain values, so buttons made with discord.py can be checked the same way."""
    is_cancel = emoji == CANCEL_EMOJI and style == SECONDARY
    if style == SECONDARY and not is_cancel:
        return f"“{label}” is grey: grey is for Cancel only (make it with cards.cancel), and any other choice is blurple"
    if label.strip().lower() == CANCEL_LABEL.lower() and not is_cancel:
        return f"“{label}” must be the grey {CANCEL_EMOJI} button (make it with cards.cancel)"
    return ""


def check(card: Card) -> None:
    """Refuse a card Discord would refuse, or one that breaks the rule for button
    colours, with a reason that names the problem. Raises ValueError: this is
    a mistake in the code, not the user's."""
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
            for button in row:
                wrong = colour_problem(button.label, button.style, button.emoji)
                if wrong:
                    raise ValueError(wrong)
            ids = [make_id(_BUTTON, button.task, button.action, button.arg) for button in row]
        for custom_id in ids:
            if custom_id in seen:
                raise ValueError(f"Two components on one card share the id {custom_id!r}")
            seen.add(custom_id)
    if card.layout:
        check_layout(card.layout)


def fitted(card: Card) -> Card:
    """The card with a layout Discord will take: one too big for a message is
    made to fit (`design.fit`) rather than refused, and the log says so. A
    card is never left unposted for its size."""
    if not card.layout or not design.problem(card.layout):
        return card
    log.warning("A card's layout was made to fit: %s", design.problem(card.layout))
    return Card(card.text, card.rows, design.fit(card.layout))


def check_layout(pieces: tuple) -> None:
    """Refuse a layout Discord would refuse, or one that breaks the rule for
    button colours. Raises ValueError, as `check` does."""
    wrong = design.problem(pieces)
    if wrong:
        raise ValueError(f"A card's layout has {wrong}")
    seen: set[str] = set()
    for button in design.buttons(pieces):
        wrong = colour_problem(button.label, button.style, button.emoji)
        if wrong:
            raise ValueError(wrong)
        if len(button.label) > MAX_LABEL:
            raise ValueError(f"A button's label is at most {MAX_LABEL} characters")
        custom_id = make_id(_BUTTON, button.task, button.action, button.arg)
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
    # The interface's own event for this press. Never looked into here: it is answered through the door
    _interaction: object | None = field(default=None, repr=False)
    shown: list[str] = field(default_factory=list)  # what the presser was shown, for the log
    row_id: int | None = None  # this press's row in message_log, for a handler with a cost to record on it

    # Database access, as on Context
    db = database

    @property
    def _answer(self):
        return surface.answer(self._interaction)

    async def update(self, card: Card) -> None:
        """Rewrite the message the component is on, in place."""
        card = fitted(card)
        check(card)
        card = dms.guarded(self.channel_id, card)
        self.shown.append(card.text)
        await self._answer.update(card)

    async def say(self, text: str) -> None:
        """Tell the presser something only they see."""
        self.shown.append(text)
        await self._answer.say(text)

    async def open_form(self, form: Form) -> None:
        """Pop a form up. Only possible as the first answer (register with opens_form)."""
        check_form(form)
        answer = self._answer
        if answer.done():
            raise RuntimeError(f"{self.task}/{self.action} must be registered with opens_form=True to open a form")
        self.shown.append(f"form: {form.title}")
        await answer.open_form(form)

    async def remove(self) -> None:
        """Delete the message the component is on."""
        self.shown.append("message removed")
        await self._answer.remove()


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
    source,
    task: str,
    action: str,
    arg: str,
    values: tuple[str, ...] = (),
    fields: dict[str, str] | None = None,
) -> None:
    """Run the action behind a press. `source` is the interface's own event
    for it, answered through the door. Never raises."""
    answer = surface.answer(source)
    try:
        registered = _actions.get((task, action))
        if registered is None:
            # Its task isn't loaded any more
            await answer.say(GONE)
            return
        user = await get_user_by_discord_id(answer.user_id)
        if not is_allowed(user, registered.permission):
            await answer.say("That isn't yours to press.")
            return
        # Answer straight away, unless the answer may be a form (which has to come first)
        if fields is not None or not registered.opens_form:
            await answer.defer()

        press = Press(user, task, action, arg, answer.channel_id, answer.message_id, values, fields, source)
        detail = "".join(
            [f" {arg}" if arg else "", f" picked {list(values)}" if values else "", f" typed {fields}" if fields else ""]
        )
        row_id = await log_received(
            f"card: {task}/{action}{detail}", "card", press.message_id, press.channel_id, user_id=user.id
        )
        press.row_id = row_id
        started = time.perf_counter()
        try:
            reply = await registered.handler(press)
        except UserError as error:
            # The presser can fix this one: tell them, and nobody else
            log.info("Card %s/%s not done: %s", task, action, error)
            await log_result(row_id, status="error", error=str(error))
            await answer.say(f"⚠️ {error}")
            return
        if not answer.done():
            await answer.defer()
        await log_result(
            row_id, reply=reply or "\n".join(press.shown) or "done", status="ok", duration_s=time.perf_counter() - started
        )
    except Exception as error:
        await answer.fail(error, f"Card action failed: {task}/{action}")


# ---------------------------------------------------------------------------
# Posting, editing and removing a card
# ---------------------------------------------------------------------------
async def post(ctx: Context, card: Card) -> int | None:
    """Send a card as the reply to what the user sent. Returns the message's id."""
    card = fitted(card)
    check(card)
    message = await ctx.reply(card.text, view=surface.drawn(card))  # checked there (core/outgoing.py)
    return getattr(message, "id", None)


def link(channel_id: int | None, message_id: int | None) -> str:
    """Where a message is, as the link the interface opens (in the app, on a
    phone). "" if the place can't be found or is not in a server."""
    return surface.link(channel_id, message_id)


async def send(channel_id: int, card: Card, *, silent: bool = False) -> int | None:
    """Post a card in a channel, with no message of the user's to answer.
    `silent` posts without a notification. Returns the message's id, or None
    if the channel can't be found. With the tidy on, one posted in the hub
    lasts the day unless its task says otherwise (`messages.record`)."""
    if surface.place(channel_id) is None:
        log.warning("Could not post a card: channel %s not found", channel_id)
        return None
    # In a direct message: silently, and never with one of my things named in its first line
    silent = silent or dms.is_dm(channel_id)
    card = dms.guarded(channel_id, fitted(card))
    check(card)
    text = outgoing.clean(card.text)
    if not text:
        log.error("A card with nothing left to say was not sent")
        return None
    message_id = await surface.send_card(channel_id, card, text, silent=silent)
    await messages.record(message_id, channel_id)
    return message_id


async def edit(channel_id: int, message_id: int, card: Card) -> bool:
    """Rewrite a card in place. False if it has gone or can't be reached."""
    if surface.place(channel_id) is None:
        return False
    card = fitted(card)
    check(card)
    card = dms.guarded(channel_id, card)
    plain = Card(outgoing.clean(card.text) or card.text, card.rows)
    try:
        await surface.edit_card(channel_id, message_id, card, plain)
    except surface.Gone:
        return False
    except surface.Failed as error:
        log.warning("Could not edit card %s: %s", message_id, error)
        return False
    return True


async def delete(channel_id: int, message_id: int) -> bool:
    """Delete a card. Best effort: False if it had already gone or can't be reached.
    The caller asks core/lifecycle.py first if this is the bot tidying up by itself."""
    if surface.place(channel_id) is None:
        return False
    try:
        await surface.delete(channel_id, message_id)
    except surface.Failed:
        return False
    return True
