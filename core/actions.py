import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core import database, durations, repeats, trace
from core.errors import UserError
from core.users import User

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Actions: what a task can be asked to do in plain words, as the routing
# standard has it.
#
# Claude understands; Python does the work and the talking. A task declares:
#   - an Entry for the router's catalogue: its name, icon, what it is "only
#     for", and two or three things one might say to it. The router never
#     sees more than that
#   - its Actions: for each, the fields Claude is to fill in (a strict schema
#     is built from them), and what Python does with them
#
# An action is one of two kinds:
#   - needs_card (anything that changes setup): `prepare` turns the data into
#     a Proposal, the confirm card shows it, and only Save runs `apply`
#   - direct (logging, questions, quick actions): `run` does it and returns
#     what to say
# Either way every word the user reads comes from the task's own code. Claude
# never writes a confirmation.
#
# This file is the contract and the checking of what Claude returns. Pure: no
# Discord, no API calls. core/routing.py and core/extraction.py make the
# calls, core/confirm.py shows the cards, core/conversation.py ties them up.
# ---------------------------------------------------------------------------
STRING, INTEGER, LIST, BOOLEAN, ITEMS = "string", "integer", "list", "boolean", "items"
# Lengths of time and times of day are not handed over as the user's words:
# Claude does the reading and gives them in one form, the same for every task.
#   MINUTES  a length of time, as a whole number of minutes
#   TIME     a time of day in TIME_FORMAT
#   TIMES    several of them, as a list
# What arrives in another form all the same is not thrown away: validate()
# reads a length given in words (core/durations.py) and passes on anything it
# can't read as the text it was, for the task to show as unread on its card.
MINUTES, TIME, TIMES = "minutes", "time", "times"
# A number that need not be whole (a weight is 62.5). It comes as a number,
# never as my words; one that came as text ("62.5", "62,5") is read in code
NUMBER = "number"
TYPES = (STRING, INTEGER, NUMBER, LIST, BOOLEAN, ITEMS, MINUTES, TIME, TIMES)
IN_AN_ITEM = (STRING, INTEGER, NUMBER, BOOLEAN, MINUTES, TIME, TIMES, LIST)
NUMBER_FORMAT = " A number, with a decimal point if it has a part (62.5), and no unit."

MINUTES_FORMAT = (
    " As a whole number of minutes, worked out by you: \"3 hours\" is 180, \"an hour and a half\" is 90, "
    "\"2.5 hours\" is 150. Never text."
)
TIME_FORMAT = (
    " In this form only: `8:00 am`, `11:30 am`, `3:00 pm` (\"8pm\" and \"20:00\" are `8:00 pm`, \"noon\" is "
    "`12:00 pm`, \"half past eight in the evening\" is `8:30 pm`). If the user did not say morning or evening, "
    "it is not a 24-hour time and nothing else they said settles it (\"at 8\"), give it with no am or pm, "
    "`8:00`: never choose for them."
)

GUESSED = "guessed"  # the field of every action that lists what Claude guessed
# The field of every action that lists what was asked for and could not be put
# into it. Nothing is ever dropped without a word: the card or reply says so
NOT_INCLUDED = "not_included"
ADDED = (GUESSED, NOT_INCLUDED)  # in every action's schema; a task's field can't use these names
NONE = "none"  # the action that says "nothing here fits"
NOT_THIS = "not_this"  # in a follow-up: "this isn't about the open card"
RESERVED = (NONE, NOT_THIS)

MIN_EXAMPLES, MAX_EXAMPLES = 2, 8
GUESS_MARK = "❓"
WARNING_MARK = "⚠️"
# The kind of change a card says on its first line: the same three words for every task
KINDS = ("new", "change", "remove")
STATE_LINES = 20  # the most of a task's state that goes to extraction with one message


@dataclass(frozen=True)
class State:
    """What a task has now, for extraction to read with a message: a heading
    and a line for each thing. A task returns this from `live_state`, not one
    long string, so that only what the message could be about is sent."""

    heading: str  # "On the shopping list now"
    lines: tuple[str, ...] = ()
    empty: str = "nothing"


def _stems(text: str) -> set[str]:
    words = re.findall(r"[^\W_]+", str(text).lower())
    return {word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words if len(word) > 2}


def shown_state(state: "State | str", said: str, limit: int = STATE_LINES) -> tuple[str, int, int]:
    """A task's state as it is sent to extraction: (the text, lines sent, lines
    there are). A long state is cut to `limit` lines: first the ones that
    share a word with what was said (what the message could refer to), then
    the others in the task's own order, and it says how many were left out."""
    if isinstance(state, str):
        every = [line for line in state.splitlines() if line.strip()]
        heading, every, empty = (every[0].rstrip(":"), every[1:], "") if len(every) > limit else ("", every, "")
    else:
        heading, every, empty = state.heading, list(state.lines), state.empty
    total = len(every)
    if total <= limit:
        sent = every
    else:
        heard = _stems(said)
        about = [line for line in every if _stems(line) & heard]
        chosen = set(map(id, about[:limit]))
        for line in every:
            if len(chosen) >= limit:
                break
            chosen.add(id(line))
        sent = [line for line in every if id(line) in chosen]  # in the task's order
    if not sent:
        return (f"{heading}: {empty}" if heading and empty else heading), 0, total
    left = total - len(sent)
    more = f"\n(and {left} more not shown: what the message names is among the lines above if it is there at all)" if left else ""
    body = "\n".join(f"- {line}" for line in sent) if heading else "\n".join(sent)
    return (f"{heading}:\n{body}{more}" if heading else f"{body}{more}"), len(sent), total


@dataclass(frozen=True)
class Field:
    """One thing Claude fills in for an action."""

    name: str  # snake_case
    description: str  # what to put here, with an example
    type: str = STRING
    choices: tuple[str, ...] = ()  # the only values allowed (a STRING, or each item of a LIST)
    required: bool = False
    # For ITEMS: the fields of each item. One request can hold several things
    # ("add honey, jam and 5 eggs"), so anything that can be asked for in the
    # plural takes a list of items, never a single one
    item_fields: tuple["Field", ...] = ()


@dataclass(frozen=True)
class Choice:
    """One likely answer to a card's question: the button's label, and what the
    action's data is with that answer in it (as extraction would hand it
    over: the card is made again from it). `settles` names the fields the
    answer decides, so a guess about one of them is a guess no longer."""

    label: str
    data: dict
    settles: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    """What a card has to ask before it can be saved (docs/CONVERSATION.md,
    section 4): one question, with a button for each likely answer. An
    answer can always be typed instead, so there may be no buttons at all."""

    text: str
    choices: tuple[Choice, ...] = ()


MAX_CHOICES = 4  # with Cancel, one row of buttons


@dataclass(frozen=True)
class Proposal:
    """What a confirm card shows: every interpretation written out, guesses
    flagged, problems shown with the sensible fix already applied."""

    lines: tuple[str, ...]  # the card's body, one interpretation a line
    data: dict  # exactly what Save will apply (fixes included)
    warnings: tuple[str, ...] = ()  # shown with ⚠️
    kind: str = "new"  # the kind of change, for the first line: one of KINDS
    destructive: bool = False  # can't be undone: a card of its own kind
    # The card asks first because something is risky (a late log, too soon): its
    # warning says why. Only how it is drawn (docs/DESIGN.md: amber)
    risky: bool = False
    confirm_label: str = "Save"
    # False while something on the card has to be put right first (its reason
    # is one of the warnings): the card has Cancel only, and a reply fixes it
    can_save: bool = True
    # What the task's own code guessed in `data` (a time taken as the morning),
    # named as Claude names a guess ("pills[0].times"). Kept with the card beside
    # Claude's guesses, so a follow-up knows the value was never said
    guessed: tuple[str, ...] = ()
    # What has to be answered first: one question, the most important. The card
    # shows everything that was understood, then asks; there is no Save until
    # it is answered, by a button or by typing
    question: Question | None = None


@dataclass(frozen=True)
class Summary:
    """A task in a few lines, for whatever shows summaries (the briefing): what
    its `summary` returns for a user and a day, or None with nothing to say.
    The icon and the name come from the task's entry, never from here. A
    summary only reads, makes no request to Claude, and is written in the
    task's own words by the task's own code (core/summaries.py)."""

    glance: str = ""  # its state in a few words, beside its name: "2 of 6 taken"
    status: str = ""  # one of the design's statuses (core/design.py), never a colour
    lines: tuple[str, ...] = ()  # up to three lines
    hint: str = ""  # small text
    before: str = ""  # one line about the day before, or none
    # What of the day is done, out of what there is to do (doses, sets, to-dos): whoever shows
    # summaries adds these up into the day's progress without knowing the task. A task with
    # nothing countable (weather) leaves both out
    done: int | None = None
    total: int | None = None
    # What is still to do that day, a line each, in the task's own words ("Pill A (dose 2 of 3) `12:00 pm`"):
    # for "what's left today?". Not trimmed to three: whoever shows them counts what it leaves out
    left: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attachment:
    """A file sent with a message, for a task's plain-words code: its name, its
    size in bytes, its kind as the sender's app gave it ("text/csv", or ""),
    and `fetch`, awaited for the bytes. Nothing is downloaded until a task
    asks; the router is only told the name."""

    name: str
    size: int = 0
    content_type: str = ""
    fetch: Callable[[], Awaitable[bytes]] | None = field(default=None, compare=False, repr=False)

    @property
    def extension(self) -> str:
        """ "csv" for "Plan.CSV"; empty if the name has none."""
        return self.name.rsplit(".", 1)[1].lower() if "." in self.name.strip(".") else ""

    async def read(self) -> bytes:
        if self.fetch is None:
            raise UserError(f"I can't read {self.name}.")
        return await self.fetch()


@dataclass(frozen=True)
class Saved:
    """The card saved a moment ago, when that Save is the last thing a task
    did in the channel: its task, its action, and the data that was saved."""

    task: str
    action: str
    data: dict


@dataclass
class Request:
    """Who is asking and where, for an action's code. Not a discord object:
    the same for a message and for a press of Save."""

    user: User
    channel_id: int | None
    text: str = ""  # what the user said (empty when Save is pressed)
    # When the message corrects an open card of this same action: that card's
    # data, as it stood. `prepare` builds the new card from it and what the
    # message changes (see merge_items), so code, not Claude, carries the rest
    # of the card over and does any sums
    previous: dict | None = None
    # With `previous`: the fields the open card's question was asking about ("times"),
    # none when it asked nothing. A message that gives one of them is the answer to that
    # question: the task fills in what was missing, and does not take it as a replacement
    asked: tuple[str, ...] = ()
    # The message the user replied to, if they replied to one ("pause this")
    replied_to: int | None = None
    # The user's own message (None for a press of a button)
    message_id: int | None = None
    # The files sent with the message (none for a press of a button)
    attachments: tuple[Attachment, ...] = ()
    # The card saved straight before this message, if a Save was the last thing a task did
    # here: "no, I meant 9pm" with nothing named is about that, and it is no guess
    just_saved: Saved | None = None

    db = database


@dataclass(frozen=True)
class LiveReply:
    """What a direct action returns when its reply is a list shown on request:
    the message becomes the Live copy of that list, kept up to date in place
    when the data changes (core/livelists.py). `key` names the list."""

    key: str
    text: str
    # The same list as a card with a layout (core/design.py), for a task whose list is
    # drawn: posted in place of the text, which is still what is logged
    card: object | None = None


@dataclass(frozen=True)
class Shown:
    """What a direct action returns when it has put its own message in the
    channel (a timer's message with its buttons, a session card): nothing more
    is posted for it. `summary` is for the log; `also`, if there is any, is
    said as well (a guess to point out, something that could not be done).
    `placed(message_id)`, if given, is awaited with the message `also` was
    said in, so the task can record that line as its own (see `Answer`)."""

    summary: str
    also: str = ""
    placed: Callable[[int], Awaitable[None]] | None = None


@dataclass(frozen=True)
class Answer:
    """What a direct action returns when its reply is about things of the task's
    own (the timer that was paused): `placed(message_id)` is awaited once the
    reply is sent, so the task can record the message as theirs and a Discord
    reply to it means the same thing (`Task.owns_message`)."""

    text: str
    placed: Callable[[int], Awaitable[None]]


Prepare = Callable[[Request, dict, frozenset], Awaitable[Proposal]]
Apply = Callable[[Request, dict], Awaitable["str | Answer"]]
# `async (request, data) -> str`: read back from the database what `apply` was
# to change and say what does not match the card's data ("" if it all does).
# A confirmation is only ever sent after this has come back empty
Verify = Callable[[Request, dict], Awaitable[str]]
Run = Callable[[Request, dict, frozenset], Awaitable["str | LiveReply | Shown | Answer"]]
# `async (request, data, guessed) -> bool`: `guessed` is what Claude said it guessed, so a guess
# about which thing is meant can be shown on a card instead of acted on
CardIf = Callable[[Request, dict, frozenset], Awaitable[bool]]


# What a way in is for, as #commands groups them (tasks/builtin/commands.py)
SET_UP, EACH_DAY, SEE = "set up", "each day", "see"
PURPOSES = (SET_UP, EACH_DAY, SEE)


@dataclass(frozen=True)
class Action:
    name: str  # unique across every task: "pill_add"
    description: str  # for Claude: when this is the one, with an example
    fields: tuple[Field, ...] = ()
    needs_card: bool = True
    prepare: Prepare | None = None  # needs_card: the data as a Proposal
    apply: Apply | None = None  # needs_card: Save was pressed; returns what to say
    run: Run | None = None  # direct: do it; returns what to say
    # After `apply`: the change re-read from the database (see Verify). Every
    # action with an `apply` has one. A direct action re-reads inside `run`
    verify: Verify | None = None
    # For an action that only sometimes needs a card (cancelling one timer acts
    # at once, cancelling several asks first): `async (request, data) -> bool`.
    # Such an action has all three of `prepare`, `apply` and `run`
    card_if: CardIf | None = None
    # For an action that changes a thing already there (pill_edit): the name of the action that
    # sets such a thing up (pill_add), and `async (request, data, on_card) -> dict | None`, which
    # gives this message's data as data for THAT action when everything it names is still only
    # on an open card of it and not saved yet (None when it is about saved things after all).
    # "Make the second one 11am", said about a card not saved yet and read as a change to a
    # saved thing, then changes the card, where it would fail for want of anything saved
    unsaved: "tuple[str, Callable[[Request, dict, dict], Awaitable[dict | None]]] | None" = None
    # For people, never sent to Claude: which group of #commands this goes in (one of
    # PURPOSES) and what one might type for it. Names in `say` are placeholders
    # ("Pill A"), never a real one of the user's. An action with no `say` is not listed
    purpose: str = ""
    say: tuple[str, ...] = ()

    def field(self, name: str) -> Field | None:
        return next((entry for entry in self.fields if entry.name == name), None)


@dataclass(frozen=True)
class Entry:
    """A task as the router knows it, with the actions extraction may pick from."""

    name: str  # lower case: "pills"
    icon: str  # "💊"
    only_for: str  # what it is for and what it is not, in a sentence or two
    examples: tuple[str, ...]  # two or three things one might say to it
    actions: tuple[Action, ...]
    # `async (request) -> str`: what extraction should know about this task's
    # state right now (names and ids). Goes in the user turn, never the cached part
    live_state: Callable[[Request], Awaitable["State | str"]] | None = None
    # The action that shows what this task has (its list, its board). The task's
    # name said on its own ("pills", "my shopping list") runs it, with no request
    show: str = ""
    # `async (request, about) -> str | None`: the task's own line for "that is
    # already so", naming the thing and showing it. `about` is the name or id
    # extraction gave for it. Without one, or when it returns None, core's
    # plain line is said instead
    already: Callable[[Request, str], Awaitable[str | None]] | None = None
    # `async (request) -> list[str]`: the names of the things of the user's that
    # this task holds now (their pills, their running timers). A message that
    # names one is this task's to answer, whatever the router made of it
    names: Callable[[Request], Awaitable[list[str]]] | None = None
    # Adding something that is already there (core/repeats.py). `identity`: the
    # fields that make two items the same thing, e.g. ("name",); empty when no
    # two are ever the same. `on_repeat`: what asking to add one that is there
    # means, one of repeats.ON_REPEAT. Every entry declares `on_repeat`
    identity: tuple[str, ...] = ()
    on_repeat: str = ""
    # `async (message_id) -> bool`: whether a message is one this task posted (a dose's
    # Taken / Skip message, a timer's card, a checklist). A Discord reply to one goes to
    # this task's extraction first, without the router
    owns: Callable[[int], Awaitable[bool]] | None = None
    # `async (user_id, day) -> Summary | None`: this task in a few lines for that user
    # and day, or None with nothing to say. A task that has one appears wherever
    # summaries are shown (the briefing), with no change there
    summary: Callable[[int, date], Awaitable["Summary | None"]] | None = None
    # `async (user_id, day) -> (done, total) | None`: what was done of what there was to do on
    # that day, from the task's own record of it and not from how things are set up now; None
    # with nothing that day. For looking back over days ("how did the week go?")
    tally: Callable[[int, date], Awaitable["tuple[int, int] | None"]] | None = None
    # `async (user_id, now) -> list of attention.Item`: what of this task's may deserve a
    # look now (core/attention.py). The core ranks them with everyone else's, once; the
    # status line, the briefing and pings each show a slice of that one ranking
    attention: Callable[[int, datetime], Awaitable[list]] | None = None

    @property
    def title(self) -> str:
        return self.name.capitalize()

    def action(self, name: str) -> Action | None:
        return next((action for action in self.actions if action.name == name), None)


def flag(text: str, guessed: bool) -> str:
    """Text with ❓ after it if it was a guess, for a card or a reply.

    ❓ is for a genuine guess: a time that could be morning or evening, a
    field Claude wasn't sure of. A value simply left at its default (one of
    something, when no amount was said) is not a guess and is never flagged,
    so that ❓ still means something on a card with several lines."""
    return f"{text} {GUESS_MARK}" if guessed else text


# ---------------------------------------------------------------------------
# Changes to the items of a list: add, set, remove
#
# For any task that keeps a list of things with amounts. A request names the
# items it is about and, for each, what to do: add more of it (or add it
# new), set what it should be, or remove it. Claude says which; code does the
# sum and shows before -> after. The same three work on a saved list and on
# an open card that isn't saved yet.
# ---------------------------------------------------------------------------
ADD, SET, REMOVE = "add", "set", "remove"
CHANGE = "change"  # the name of the item field that says which

# ---------------------------------------------------------------------------
# References: "it", "that", "this one"
#
# Claude never works out what a pronoun points at. It puts REFERENCE where the
# name or id would go, and code resolves it: the message replied to, if the
# user replied to one; otherwise the last thing the user mentioned (a card
# keeps that under LAST in its data). Never something the bot said.
# ---------------------------------------------------------------------------
REFERENCE = "@that"
LAST = "_last"  # in a card's data: what the user mentioned last, for the next "it"


def is_reference(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in (REFERENCE, "@it", "@this", "@them", "@those")


_POINTING = re.compile(r"\b(?:it|that|this|them|those|these)\b", re.IGNORECASE)
_POINTING_AT_ONE = re.compile(r"\b(?:it|that|this)\b", re.IGNORECASE)
# Words a line of state and a message can share without the message naming the thing
_SMALL_WORDS = frozenset(
    "it that this them those these the a an to in on at of for and or with from left right now my is are be one more "
    "running paused active daily channel bag list timer pill item make give add put set stop start pause resume "
    "cancel remove delete change".split()
)


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[^\W\d_]{3,}", str(text).lower())
    return {word[:-1] if word.endswith("s") and len(word) > 3 else word for word in words} - _SMALL_WORDS


def _named_by(value: str, said: str, state: str) -> bool:
    """Whether the message names this thing: by its own words, or, for an id
    taken from the state ("t12"), by a word of that id's line ("tea")."""
    heard = _content_words(said)
    if re.search(rf"(?<!\w){re.escape(value.strip().lower())}(?!\w)", said.lower()):
        return True
    if _content_words(value) and _content_words(value) <= heard:
        return True
    for line in state.splitlines():
        if re.match(rf"\W*{re.escape(value.strip())}\s*:", line, re.IGNORECASE):
            return bool(_content_words(line) & heard)
    return False


def as_references(action: "Action", data: dict, said: str, state: str = "") -> tuple[dict, list[str]]:
    """What extraction returned, with any name Claude worked out from a pronoun
    put back as a reference: (the data, what was put back).

    Claude is told to return REFERENCE for "it" and sometimes names the thing
    itself. Whether it was right is not for it to say: when the message
    points ("it", "that") and does not name the thing, the name is replaced
    by REFERENCE and the code resolves it by its own rule. Applies to what
    names a thing: a required text field with no choices, and the first
    required field of each item in a list. A thing the message names keeps
    its name. Pure."""
    if not _POINTING.search(said):
        return data, []
    changed, back = dict(data), []
    for entry_field in action.fields:
        value = data.get(entry_field.name)
        if entry_field.type == STRING and entry_field.required and not entry_field.choices and isinstance(value, str):
            # One thing, pointed at as one: "cancel them" with "all" is no single thing to resolve
            one = _POINTING_AT_ONE.search(said) and len(value.split()) == 1
            if one and not is_reference(value) and not _named_by(value, said, state):
                changed[entry_field.name] = REFERENCE
                back.append(value)
        elif entry_field.type == ITEMS and isinstance(value, list):
            key = next((inner.name for inner in entry_field.item_fields if inner.required), None)
            unnamed = [
                item for item in value
                if key and isinstance(item.get(key), str) and not is_reference(item[key]) and not _named_by(item[key], said, state)
            ]
            # One thing pointed at: a message that points and names nothing else. With
            # several unnamed things it is not plain which the pronoun is, so none is touched
            if len(unnamed) == 1:
                changed[entry_field.name] = [{**item, key: REFERENCE} if item is unnamed[0] else item for item in value]
                back.append(unnamed[0][key])
    return changed, back


_GIVEN_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])m", re.IGNORECASE)
_HALF_MARKED = re.compile(r"(?<![a-z])\d{1,2}(?:[:.]\d{2})?\s*[ap]\.?m\b")
_PART_OF_DAY = re.compile(
    r"\b(?:morning|afternoon|evening|night|tonight|noon|midday|midnight|lunch|lunchtime|breakfast|dinner|supper|bedtime)\b"
)


def _half_is_said(given: str, said: str) -> bool:
    """Whether the message can settle which half of the day a time is in: it
    marks a time am or pm, names a part of the day, or has this very time on
    the 24-hour clock. A time that isn't in the fixed form is not judged."""
    match = _GIVEN_TIME.fullmatch(given.strip())
    if not match:
        return True
    heard = said.lower()
    if _HALF_MARKED.search(heard) or _PART_OF_DAY.search(heard):
        return True
    hour = int(match[1]) % 12 + (12 if match[3].lower() == "p" else 0)
    forms = {f"{hour:02d}:{match[2]}", f"{hour:02d}.{match[2]}", f"{hour:02d}{match[2]}"}
    if hour >= 13:
        forms |= {f"{hour}:{match[2]}", f"{hour}.{match[2]}"} | ({str(hour)} if match[2] == "00" else set())
    return any(re.search(rf"(?<![\d:.]){re.escape(form)}(?![\d:.]\d)", heard) for form in forms)


def unchosen(action: "Action", data: dict, said: str) -> tuple[dict, list[str]]:
    """What extraction returned, with any morning or evening Claude chose by
    itself taken back: (the data, the times it was taken from).

    A time comes in the fixed form, with no am or pm when the user gave none
    (TIME_FORMAT). When one comes with am or pm and nothing in the message
    could settle it ("at 8"), the choice was Claude's: the am or pm is taken
    off, and the code decides what to do with a time that could be either.
    Applies to every TIME and TIMES field, in a list of items too. Pure."""
    back: list[str] = []

    def checked(value):
        if isinstance(value, list):
            return [checked(each) for each in value]
        if isinstance(value, str) and not _half_is_said(value, said):
            back.append(value)
            match = _GIVEN_TIME.fullmatch(value.strip())
            return f"{int(match[1])}:{match[2]}"
        return value

    def within(fields_: tuple[Field, ...], held: dict) -> dict:
        changed = dict(held)
        for entry_field in fields_:
            value = held.get(entry_field.name)
            if entry_field.type in (TIME, TIMES) and value is not None:
                changed[entry_field.name] = checked(value)
            elif entry_field.type == ITEMS and isinstance(value, list):
                changed[entry_field.name] = [within(entry_field.item_fields, item) for item in value]
        return changed

    return within(action.fields, data), back


_SAID_TIME = re.compile(r"(?<![\w:.])(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\b", re.IGNORECASE)


def _said_times(said: str) -> list[int]:
    """The times of day a message states outright, with am or pm, as minutes of the day."""
    found = []
    for hour, minute, half in _SAID_TIME.findall(said):
        if 1 <= int(hour) <= 12 and int(minute or 0) < 60:
            found.append((int(hour) % 12 + (12 if half.lower() == "p" else 0)) * 60 + int(minute or 0))
    return found


def _given_minutes(value) -> int | None:
    match = _GIVEN_TIME.fullmatch(value.strip()) if isinstance(value, str) else None
    return (int(match[1]) % 12 + (12 if match[3].lower() == "p" else 0)) * 60 + int(match[2]) if match else None


def restated(action: "Action", data: dict, said: str) -> tuple[dict, list[str]]:
    """What extraction returned, with a time I stated put back where Claude
    handed over another: (the data, what was put right, as "8:00 pm → 9:00 pm").

    What I state wins. When the message gives exactly one time, with am or
    pm, that is nowhere in what was handed over, and exactly one time handed
    over is not in the message, that one was meant to be mine: mine takes its
    place. (Found 2026-10-13: to "9pm", typed in answer to a card whose button
    offered 8:00 pm, Claude handed over 8:00 pm.) With more than one of
    either nothing is touched: which goes where is not the code's to guess.
    Applies to every TIME and TIMES field, in a list of items too. Pure."""
    stated = _said_times(said)
    given: list[str] = []

    def collect(fields_: tuple[Field, ...], held: dict) -> None:
        for entry_field in fields_:
            value = held.get(entry_field.name)
            if entry_field.type in (TIME, TIMES) and value is not None:
                given.extend(value if isinstance(value, list) else [value])
            elif entry_field.type == ITEMS and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        collect(entry_field.item_fields, item)

    collect(action.fields, data)
    minutes = [_given_minutes(each) for each in given]
    missing = [each for each in dict.fromkeys(stated) if each not in minutes]
    odd = [value for value, at in zip(given, minutes) if at is not None and at not in stated]
    if len(missing) != 1 or len(odd) != 1:
        return data, []
    hour, minute = divmod(missing[0], 60)
    mine = f"{hour % 12 or 12}:{minute:02d} {'am' if hour < 12 else 'pm'}"

    def put(value):
        if isinstance(value, list):
            return [put(each) for each in value]
        return mine if value == odd[0] else value

    def within(fields_: tuple[Field, ...], held: dict) -> dict:
        changed = dict(held)
        for entry_field in fields_:
            value = held.get(entry_field.name)
            if entry_field.type in (TIME, TIMES) and value is not None:
                changed[entry_field.name] = put(value)
            elif entry_field.type == ITEMS and isinstance(value, list):
                changed[entry_field.name] = [within(entry_field.item_fields, item) if isinstance(item, dict) else item for item in value]
        return changed

    return within(action.fields, data), [f"{odd[0]} → {mine}"]


def point_at(changes: list[dict], key: str, last: str | None) -> list[dict]:
    """The changes with each reference ("it") given the name it stands for:
    `last`, the last thing the user mentioned. Raises UserError if there is
    nothing it could mean: that is said, never guessed."""
    if not any(is_reference(change.get(key)) for change in changes):
        return changes
    if not last:
        raise UserError("I can't tell what “it” is. Say its name.")
    return [{**change, key: last} if is_reference(change.get(key)) else change for change in changes]


# ---------------------------------------------------------------------------
# What the user stated is never a guess
# ---------------------------------------------------------------------------
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "a": 1, "an": 1, "once": 1, "twice": 2,
}


def _value_at(data: dict, guess: str):
    match = _GUESS_PATH.fullmatch(guess.strip())
    if not match or match[1] not in data:
        return None
    value = data[match[1]]
    if match[2] is None:
        return value
    if not isinstance(value, list) or int(match[2]) >= len(value):
        return None
    item = value[int(match[2])]
    return item.get(match[3]) if match[3] is not None and isinstance(item, dict) else None


def _is_stated(value, said: str) -> bool:
    """Whether a value is in the message in so many words: the same text, or the same number."""
    heard = said.lower()
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        numbers = {int(found) for found in re.findall(r"(?<![\w.])\d+(?![\w.]*\d)", heard)}
        numbers |= {number for word, number in _NUMBER_WORDS.items() if word not in ("a", "an") and re.search(rf"\b{word}\b", heard)}
        return value in numbers
    if isinstance(value, str):
        text = value.strip().lower()
        return len(text) > 0 and not is_reference(text) and re.search(rf"(?<!\w){re.escape(text)}(?!\w)", heard) is not None
    return False


def unstated(data: dict, guessed: frozenset, said: str) -> frozenset:
    """The guesses that really are guesses: a value the user stated outright (an
    amount, a time, a dose, a note) is used exactly and never flagged, whatever
    Claude listed. A guess about a whole item, or one whose value isn't in the
    message, stays."""
    return frozenset(guess for guess in guessed if not _is_stated(_value_at(data, guess), said))


def change_field() -> Field:
    """The `change` field of an item, the same for every list-like task."""
    return Field(
        CHANGE,
        "What to do with this item. add: the user wants it added, or more of it (\"add 3 milk\", \"another "
        "loaf\", \"milk too\"): any amount is how many MORE. set: the user says what it should be (\"make the "
        "eggs 7\", \"make it 2\", \"change milk to 3\", \"I only need 2\"): the amount is the new total. "
        "remove: take it off altogether (\"remove the jam\", \"no jam\", \"drop the eggs\"). Never work a "
        "total out yourself: give what the user said and which of the three it is. Leave out for add.",
        choices=(ADD, SET, REMOVE),
    )


def merge_items(
    pending: list[dict],
    changes: list[dict],
    *,
    key: str = "item",
    amount: str | None = "quantity",
    same=None,
    exists=None,
    said: str | None = None,
) -> tuple[list[dict], list[str]]:
    """An open card's items with a message's changes applied: (the items as
    they now stand, the names it was asked to remove that aren't anywhere).

    `pending` is what the card holds, `changes` what the message is about,
    each item with its `change` (add if left out). `key` names an item and
    `amount` is the field that counts it (None if the task has no amounts).
    `same(a, b)` says whether two names are the same item; `exists(name)`
    whether one is in the saved list, so that removing something that is only
    on the card takes it off the card, and removing something saved becomes a
    removal to confirm.

    Code does the sums: adding 3 to a card that adds 2 adds 5; setting
    replaces whatever was pending. The name is kept as typed last.

    `said` is the message the changes came from. Claude is asked for the
    changes only; as a safety net, a line of the card that comes back beside
    other changes, without the message naming it, is taken as the card
    restated and not as more of it (see `_restated`).
    """
    same = same or (lambda one, other: str(one).strip().lower() == str(other).strip().lower())
    merged = [dict(item) for item in pending]
    missing: list[str] = []
    for change in changes:
        was = next((item for item in merged if same(item[key], change[key])), None)
        if _restated(change, was, changes, key, amount, same, said):
            trace.note(f"restatement check: {change[key]} came back with the card and the message doesn't name it: not added again")
            # As it was: left alone. With another amount: that is what it should be, never added on top
            if amount is not None and amount in change:
                was[amount] = change[amount]
            was.update({field: value for field, value in change.items() if field not in (amount, CHANGE, key)})
            continue
        name, what = change[key], change.get(CHANGE, ADD)
        at = next((index for index, item in enumerate(merged) if same(item[key], name)), None)
        was = merged[at] if at is not None else None
        if was is not None and what != REMOVE and len(changes) > 1:
            trace.note(f"restatement check: {name} is on the card and came back, taken as a real change ({what})")
        trace.note(f"merge: {name} {what}" + (f" {change[amount]}" if amount is not None and amount in change else "") + (" (on the card)" if was is not None else " (new to the card)"))
        if what == REMOVE:
            if at is not None:
                merged.pop(at)
            if exists is not None and exists(name):
                merged.append({key: name, CHANGE: REMOVE})
            elif was is None or was.get(CHANGE) == REMOVE:
                missing.append(name)
            continue
        now = {field: value for field, value in change.items() if field != CHANGE}
        if what == SET or was is None or was.get(CHANGE) == REMOVE:
            # Set replaces whatever was pending; a first mention, or one after a removal, stands as it is
            now[CHANGE] = what
        else:
            # More of something the card already changes: the amounts add up, and it stays what it was
            now = {**{field: value for field, value in was.items() if field != CHANGE}, **now}
            if amount is not None:
                now[amount] = was.get(amount, 1) + change.get(amount, 1)
            now[CHANGE] = was.get(CHANGE, ADD)
        if at is not None:
            merged[at] = now
        else:
            merged.append(now)
    return merged, missing


def _restated(change: dict, was: dict | None, changes: list[dict], key: str, amount: str | None, same, said: str | None) -> bool:
    """Whether a change is only a line of the open card sent back, not something
    the message asked for. The safety net for when Claude repeats the card
    ("and jam" coming back as butter and jam): without it the butter would be
    added a second time.

    It is, when the item is on the card, something else came back with it (a
    message about this item alone is a real change, pronoun or not: "two
    more"), the message doesn't name it, and it is an add, or a set to what
    the card already has. Works for a card of one line as for many."""
    if was is None or len(changes) < 2:
        return False
    kind = change.get(CHANGE, ADD)
    if kind == REMOVE or was.get(CHANGE) == REMOVE:
        return False
    if said is not None and _named(change[key], said, same):
        return False
    unchanged = amount is None or change.get(amount, was.get(amount, 1)) == was.get(amount, 1)
    return kind == ADD or unchanged


def _named(name: str, said: str, same) -> bool:
    """Whether a message names an item: every word of the name is in it,
    by the task's own rule for the same name ("egg" names "eggs")."""
    heard = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", said.lower())
    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", str(name).lower())
    return bool(words) and all(any(same(word, other) for other in heard) for word in words)


def path(name: str, index: int | None = None, sub: str = "") -> str:
    """How a guess is named: "times", "times[0]", "items[2].quantity"."""
    return name + (f"[{index}]" if index is not None else "") + (f".{sub}" if sub else "")


def is_guessed(guessed: frozenset, name: str, index: int | None = None, sub: str = "") -> bool:
    """Whether this value was a guess: named itself, or as part of what holds it
    ("items[2]" covers "items[2].quantity")."""
    wanted = path(name, index, sub)
    return wanted in guessed or (bool(sub) and path(name, index) in guessed) or (index is not None and name in guessed)


# ---------------------------------------------------------------------------
# The catalogue: every entry of every loaded task, set by the registry
# ---------------------------------------------------------------------------
_entries: dict[str, Entry] = {}


def set_catalogue(entries: list[Entry]) -> None:
    _entries.clear()
    _entries.update({entry.name: entry for entry in entries})


def catalogue() -> list[Entry]:
    return list(_entries.values())


def entry(name: str) -> Entry | None:
    return _entries.get(name)


def problems(entries: list[Entry]) -> list[str]:
    """What is wrong with a set of entries, in words: the contract every task
    must meet before the bot starts routing to it. Empty if nothing is."""
    found: list[str] = []
    names: dict[str, str] = {}
    seen_entries: set[str] = set()
    for entry in entries:
        who = entry.name or "(unnamed)"
        if not entry.name or entry.name != entry.name.lower() or " " in entry.name:
            found.append(f"{who}: an entry's name is one lower-case word")
        if entry.name in seen_entries:
            found.append(f"{who}: two entries share this name")
        seen_entries.add(entry.name)
        if not entry.icon.strip():
            found.append(f"{who}: needs an icon")
        if not entry.only_for.strip():
            found.append(f"{who}: needs an \"only for\" line, so the router can tell it from other tasks")
        if not MIN_EXAMPLES <= len(entry.examples) <= MAX_EXAMPLES:
            found.append(f"{who}: needs {MIN_EXAMPLES} to {MAX_EXAMPLES} example phrases, not {len(entry.examples)}")
        if not entry.actions:
            found.append(f"{who}: has no actions")
        if entry.show and not any(action.name == entry.show and not action.needs_card and not action.fields for action in entry.actions):
            found.append(f"{who}: `show` must name one of its actions that acts at once and takes nothing ({entry.show})")
        taken = {inner.name for action in entry.actions for outer in action.fields for inner in (outer, *outer.item_fields)}
        found += repeats.problems(who, tuple(entry.identity), entry.on_repeat, taken)
        for action in entry.actions:
            where = f"{who}: action {action.name or '(unnamed)'}"
            if not action.name or action.name in RESERVED:
                found.append(f"{where} needs a name of its own")
            elif action.name in names:
                found.append(f"{where} is also an action of {names[action.name]}")
            else:
                names[action.name] = who
            if not action.description.strip():
                found.append(f"{where} has no description for Claude")
            if action.apply is not None and action.verify is None:
                found.append(f"{where} saves with `apply`, so it needs `verify` (the change read back before it is confirmed)")
            if action.card_if is not None:
                if action.prepare is None or action.apply is None or action.run is None:
                    found.append(f"{where} needs a card only sometimes (`card_if`), so it needs `prepare`, `apply` and `run`")
            elif action.needs_card and (action.prepare is None or action.apply is None):
                found.append(f"{where} needs a card, so it needs both `prepare` (the card) and `apply` (Save)")
            elif not action.needs_card and action.run is None:
                found.append(f"{where} acts straight away, so it needs `run` (which writes the reply)")
            field_names = [entry_field.name for entry_field in action.fields]
            if len(set(field_names)) != len(field_names):
                found.append(f"{where} has two fields with the same name")
            for entry_field in action.fields:
                if entry_field.type not in TYPES:
                    found.append(f"{where}: field {entry_field.name} has an unknown type {entry_field.type!r}")
                if entry_field.name in ADDED:
                    found.append(f"{where}: `{entry_field.name}` is added to every action; a field can't be called that")
                if entry_field.choices and entry_field.type not in (STRING, LIST):
                    found.append(f"{where}: field {entry_field.name} has choices, which only text can have")
                if not entry_field.description.strip():
                    found.append(f"{where}: field {entry_field.name} has no description for Claude")
                if entry_field.type == ITEMS:
                    if not entry_field.item_fields:
                        found.append(f"{where}: field {entry_field.name} is a list of items, so it needs `item_fields`")
                    for inner in entry_field.item_fields:
                        if inner.type not in IN_AN_ITEM:
                            found.append(f"{where}: an item's field {inner.name} must be text, a number, yes/no, a length of time, times of day or a list of words")
                        if not inner.description.strip():
                            found.append(f"{where}: an item's field {inner.name} has no description for Claude")
                elif entry_field.item_fields:
                    found.append(f"{where}: field {entry_field.name} has `item_fields` but is not a list of items")
    return found


# ---------------------------------------------------------------------------
# Schemas: what Claude is told an action takes
# ---------------------------------------------------------------------------
def _property(entry_field: Field) -> dict:
    if entry_field.type == ITEMS:
        return {
            "type": "array",
            "description": entry_field.description,
            "items": {
                "type": "object",
                "properties": {inner.name: _property(inner) for inner in entry_field.item_fields},
                "required": [inner.name for inner in entry_field.item_fields if inner.required],
                "additionalProperties": False,
            },
        }
    if entry_field.type == LIST:
        items: dict = {"type": "string"}
        if entry_field.choices:
            items["enum"] = list(entry_field.choices)
        return {"type": "array", "items": items, "description": entry_field.description}
    if entry_field.type == MINUTES:
        return {"type": "integer", "description": entry_field.description + MINUTES_FORMAT}
    if entry_field.type == NUMBER:
        return {"type": "number", "description": entry_field.description + NUMBER_FORMAT}
    if entry_field.type == TIME:
        return {"type": "string", "description": entry_field.description + TIME_FORMAT}
    if entry_field.type == TIMES:
        return {"type": "array", "items": {"type": "string"}, "description": entry_field.description + " Each one:" + TIME_FORMAT}
    prop: dict = {"type": entry_field.type, "description": entry_field.description}
    if entry_field.choices:
        prop["enum"] = list(entry_field.choices)
    return prop


def schema(action: Action) -> dict:
    """The strict JSON schema of an action: its fields, `guessed` (what Claude
    filled in without being told) and `not_included` (what was asked for and
    could not be put into the action)."""
    properties = {entry_field.name: _property(entry_field) for entry_field in action.fields}
    properties[GUESSED] = {
        "type": "array",
        "items": {"type": "string"},
        # Short on purpose: this is in every action's schema, and the rule is said once, in the
        # instructions (core/extraction.py, `rules`)
        "description": (
            "The fields you genuinely guessed, each named by its path (`times[0]`, `items[2].quantity`). "
            "A field left to its default is not a guess. Empty if none."
        ),
    }
    properties[NOT_INCLUDED] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Every part of what the user asked for that you could NOT put into this action, each a whole "
            "part copied word for word. Empty if all of it is covered."
        ),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [entry_field.name for entry_field in action.fields if entry_field.required] + [GUESSED, NOT_INCLUDED],
        "additionalProperties": False,
    }


def tool(action: Action, strict: bool = False) -> dict:
    """An action as the API takes it."""
    definition = {"name": action.name, "description": action.description, "input_schema": schema(action)}
    if strict:
        definition["strict"] = True
    return definition


# Why nothing was done, as one of a few kinds the code has a line for. The
# reason in words is for the log only: code never reads it
ALREADY_SO, CANNOT, UNCLEAR = "already_so", "cannot", "unclear"
DECLINES = (ALREADY_SO, CANNOT, UNCLEAR)
NONE_TOOL = {
    "name": NONE,
    "description": (
        "Nothing here fits what the user said, or it isn't clear enough to act on even with a best guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "why": {
                "type": "string",
                "enum": list(DECLINES),
                "description": (
                    f"`{ALREADY_SO}`: the request is clear, but what it asks for is already exactly the case and no "
                    f"action would change anything. `{CANNOT}`: the request is clear and is for this task, but none "
                    f"of its actions can do it. `{UNCLEAR}`: it makes no sense for this task, or you can't tell what "
                    "is wanted."
                ),
            },
            "about": {
                "type": "string",
                "description": (
                    f"With `{ALREADY_SO}` only: the id or name, from the state, of the one thing the request is "
                    "about, so that the user can be shown it. Leave out otherwise."
                ),
            },
            "reason": {"type": "string", "description": "Why, in a few words. For the log, not the user."},
        },
        "required": ["why", "reason"],
        "additionalProperties": False,
    },
}
NOT_THIS_TOOL = {
    "name": NOT_THIS,
    "description": (
        "The user's message is not about the open card or this task's list at all: it is a new request for "
        "something else."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Why, in a few words. For the log, not the user."}},
        "required": ["reason"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Checking what Claude returned. Always done, strict schema or not
# ---------------------------------------------------------------------------
class Invalid(ValueError):
    """What Claude returned doesn't fit the action's schema. The message says how."""


@dataclass(frozen=True)
class Checked:
    """What Claude returned, once it has been checked."""

    data: dict
    guessed: frozenset  # paths: "times", "times[0]", "items[2].quantity"
    not_included: tuple[str, ...] = ()  # what was asked for and is not in `data`, to be told to the user

    def __iter__(self):
        # (data, guessed), for code that only wants those two
        return iter((self.data, self.guessed))


_PYTHON_TYPES = {STRING: str, INTEGER: int, BOOLEAN: bool}
_GUESS_PATH = re.compile(r"(\w+)(?:\[(\d+)\])?(?:\.(\w+))?")


_BETWEEN_TIMES = re.compile(r"\s*(?:,|;|&|\band\b|\bthen\b)\s*")


def _structured(entry_field: Field, value, where: str):
    """A length of time or times of day, checked. A length that came as words
    is read here; what can't be read, and every time, is passed on as text
    for the task's own code, which shows what it couldn't read on its card.
    None if it was left empty."""
    if entry_field.type == MINUTES:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise Invalid(f"`{where}` must be a number of minutes")
        if isinstance(value, int):
            if value < 0:
                raise Invalid(f"`{where}` is less than nothing")
            return value
        text = value.strip()
        if not text:
            return None
        try:
            seconds = durations.parse_duration(text) if re.search(r"[a-z:]", text.lower()) else int(text) * 60
        except (durations.DurationError, ValueError):
            trace.note(f"`{where}` came as text that is not a length of time: {text!r}")
            return text
        trace.note(f"`{where}` came as text ({text!r}), read as {round(seconds / 60)} minutes")
        return round(seconds / 60)
    if entry_field.type == TIME:
        if not isinstance(value, str):
            raise Invalid(f"`{where}` must be a time of day")
        return value.strip() or None
    # TIMES: a list, or the times in one text ("8am, 8pm")
    if isinstance(value, str):
        value = _BETWEEN_TIMES.split(value)
    if not isinstance(value, list):
        raise Invalid(f"`{where}` must be a list of times of day")
    # A place left empty (a null for the time that wasn't said) is not a time: it is left out, and
    # the task's own rules ask for what is missing. Anything else that is no text is refused
    if not all(each is None or isinstance(each, str) for each in value):
        raise Invalid(f"`{where}` must be a list of times of day")
    return [each.strip() for each in value if each is not None and each.strip()] or None


_AS_A_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _number(value, where: str):
    """A number that need not be whole, checked: 62.5 stays 62.5 and 60.0 is
    60. One that came as text is read here ("62.5", "62,5"); None if that
    text was empty. Never a yes/no, never infinite."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not _AS_A_NUMBER.fullmatch(text):
            raise Invalid(f"`{where}` must be a number, and came as {text!r}")
        trace.note(f"`{where}` came as text ({text!r}), read as a number")
        value = float(text.replace(",", "."))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"`{where}` must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise Invalid(f"`{where}` is not a number that can be used")
    return int(value) if float(value).is_integer() else float(value)


def _scalar(entry_field: Field, value, where: str):
    """One text, number or yes/no value, checked. Returns it, or None if it is
    an optional text left empty."""
    if entry_field.type in (MINUTES, TIME, TIMES):
        value = _structured(entry_field, value, where)
        if value is None and entry_field.required:
            raise Invalid(f"`{where}` is empty")
        return value
    if entry_field.type == NUMBER:
        value = _number(value, where)
        if value is None and entry_field.required:
            raise Invalid(f"`{where}` is empty")
        return value
    expected = _PYTHON_TYPES[entry_field.type]
    # bool is an int in Python: an INTEGER must not be True
    if not isinstance(value, expected) or (entry_field.type == INTEGER and isinstance(value, bool)):
        raise Invalid(f"`{where}` must be {entry_field.type}")
    if entry_field.type != STRING:
        return value
    value = value.strip()
    if not value:
        if entry_field.required:
            raise Invalid(f"`{where}` is empty")
        return None
    if entry_field.choices and value not in entry_field.choices:
        raise Invalid(f"`{where}` is {value!r}, which is not one of {', '.join(entry_field.choices)}")
    return value


def _words(entry_field: Field, value, where: str) -> list[str] | None:
    """A list of words, checked against the field's choices. None if it is empty."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Invalid(f"`{where}` must be a list of strings")
    value = [item.strip() for item in value if item.strip()]
    wrong = [item for item in value if entry_field.choices and item not in entry_field.choices]
    if wrong:
        raise Invalid(f"`{where}` has {wrong[0]!r}, which is not one of {', '.join(entry_field.choices)}")
    if not value and entry_field.required:
        raise Invalid(f"`{where}` is empty")
    return value or None


def _item(entry_field: Field, raw, where: str) -> dict:
    """One item of a list of items, checked like a small action of its own."""
    if not isinstance(raw, dict):
        raise Invalid(f"`{where}` is not an object")
    known = {inner.name: inner for inner in entry_field.item_fields}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise Invalid(f"`{where}` has what is not a field of an item: {', '.join(unknown)}")
    item: dict = {}
    for name, inner in known.items():
        if name not in raw or raw[name] is None:
            if inner.required:
                raise Invalid(f"`{where}.{name}` is missing")
            continue
        check = _words if inner.type == LIST else _scalar
        value = check(inner, raw[name], f"{where}.{name}")
        if value is not None:
            item[name] = value
    return item


# Words that join or soften a request and ask for nothing themselves
_FILLER = frozenset(
    "and also plus too then please pls as well thanks thank you cheers ok okay oh so just now actually well hey hi hello "
    "btw the a an to my for of with on in it that this also, &".split()
)


def is_filler(part: str) -> bool:
    """Whether a leftover part of a message is only connecting or filler words
    ("and", "also", "please"): never worth telling the user it was not
    included. A leftover that is a real request or content has other words."""
    words = re.findall(r"[^\W_]+|&", part.lower())
    return all(word in _FILLER for word in words)


# Joining words that mean nothing left hanging at an end of a leftover
_DANGLING_END = frozenset("of and or the a an my at for with plus &".split())
_DANGLING_START = frozenset("and or of plus then also &".split())


def whole_part(part: str) -> str:
    """A leftover as whole words of a real part of the message. Claude sometimes
    cuts one mid-phrase ("dose 1 of", from "dose 1 of Pill A"): a joining
    word left hanging at either end is taken off ("dose 1")."""
    words = part.split()
    while words and words[-1].strip(",;:.").lower() in _DANGLING_END:
        words.pop()
    while words and words[0].strip(",;:.").lower() in _DANGLING_START:
        words.pop(0)
    return " ".join(words).strip(" ,;:")


def validate(action: Action, raw) -> Checked:
    """What Claude returned, checked: the data, what was guessed, and what was
    left out. Raises Invalid if it doesn't fit the action at all.

    Strict: every required field present, nothing that isn't a field, every
    value of its type and among its choices. Text is trimmed; an optional
    field left empty is left out, so code can tell "not said" from "said".

    In a list of items, one item that doesn't fit is not allowed to sink the
    rest, and is not dropped unseen either: it is left out of the data and
    named in `not_included`, which the user is shown.
    """
    if not isinstance(raw, dict):
        raise Invalid("the input is not an object")
    known = {entry_field.name: entry_field for entry_field in action.fields}
    unknown = sorted(set(raw) - set(known) - set(ADDED))
    if unknown:
        raise Invalid(f"not fields of {action.name}: {', '.join(unknown)}")

    data: dict = {}
    left_out: list[str] = []
    shifted: set[str] = set()
    for name, entry_field in known.items():
        if name not in raw or raw[name] is None:
            if entry_field.required:
                raise Invalid(f"`{name}` is missing")
            continue
        value = raw[name]
        if entry_field.type == ITEMS:
            if not isinstance(value, list):
                raise Invalid(f"`{name}` must be a list of items")
            items = []
            dropped: set[int] = set()
            for index, each in enumerate(value):
                try:
                    items.append(_item(entry_field, each, f"{name}[{index}]"))
                except Invalid as problem:
                    # In the user's terms: what the item was, not what was wrong with its form
                    trace.note(f"{problem}: the item is left out ({each!r})")
                    log.info("An item of %s.%s could not be used (%s): %r", action.name, name, problem, each)
                    dropped.add(index)
                    left_out.append(", ".join(str(part) for part in each.values()) if isinstance(each, dict) and each else str(each))
            if not items:
                if entry_field.required:
                    raise Invalid(f"`{name}` has no item that can be used" if value else f"`{name}` is empty")
                continue
            if dropped:
                # The places Claude named no longer line up: a guess about an item is forgotten
                # rather than pinned on the wrong one
                shifted.add(name)
            value = items
        elif entry_field.type == LIST:
            value = _words(entry_field, value, name)
            if value is None:
                continue
        else:
            value = _scalar(entry_field, value, name)
            if value is None:
                continue
        data[name] = value

    guessed = raw.get(GUESSED, [])
    if not isinstance(guessed, list) or not all(isinstance(item, str) for item in guessed):
        raise Invalid(f"`{GUESSED}` must be a list of field names")
    not_included = raw.get(NOT_INCLUDED, [])
    if not isinstance(not_included, list) or not all(isinstance(item, str) for item in not_included):
        raise Invalid(f"`{NOT_INCLUDED}` must be a list of the parts left out")
    left_out = [whole for part in not_included if (whole := whole_part(part)) and not is_filler(whole)] + left_out
    # A guess named by an item's field alone ("duration" for "timers[0].duration"),
    # seen from Claude on a list of one: it is put where it belongs, on each item that
    # has that field, so the guess is still flagged rather than forgotten
    lists = [entry_field for entry_field in action.fields if entry_field.type == ITEMS and entry_field.name in data]
    placed: list[str] = []
    for name in guessed:
        if name in known or "[" in name or "." in name or len(lists) != 1 or lists[0].name in shifted:
            placed.append(name)
        elif any(inner.name == name for inner in lists[0].item_fields):
            placed += [path(lists[0].name, index, name) for index, item in enumerate(data[lists[0].name]) if name in item]
        else:
            placed.append(name)
    guessed = placed
    kept = frozenset(
        name for name in guessed if _guess_is_about(name, data) and not ("[" in name and name.split("[")[0] in shifted)
    )
    return Checked(data, kept, tuple(left_out))


def _guess_is_about(guess: str, data: dict) -> bool:
    """Whether a guess names something that is in the data: a guess about a
    field that isn't there says nothing."""
    match = _GUESS_PATH.fullmatch(guess.strip())
    if not match or match[1] not in data:
        return False
    value = data[match[1]]
    if match[2] is None:
        return match[3] is None
    if not isinstance(value, list) or int(match[2]) >= len(value):
        return False
    return match[3] is None or (isinstance(value[int(match[2])], dict) and match[3] in value[int(match[2])])
