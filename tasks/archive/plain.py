import discord

from core import discord_utils, pins
from core.actions import INTEGER, LIST, Action, Entry, Field, Proposal, Request, State, flag, is_guessed
from core.errors import UserError
from core.protection import PROTECT_EMOJI, protection
from tasks.archive import messages

# ---------------------------------------------------------------------------
# Tidying messages in plain words (core/actions.py): archive, pin, unpin,
# delete. "Archive that", "pin the one about the invoice", "delete my last
# two messages".
#
# Which message is meant: Claude says how it was pointed at, and the code
# finds it. "That" or "the last two" is the newest in the channel (`newest`);
# "my last message" is the newest the user wrote (`mine`); one described by
# its words is picked from the channel's last few messages, which are sent
# with the request, each with a short id (`named`). Counting positions is the
# code's job, never Claude's. Then:
#
#   pin, unpin     at once; the reply quotes the message with a link
#   archive        at once (the copy has a Restore button); a protected
#                  message asks first, with a card
#   delete         always a card: it can't be undone
#
# What is done to a message chosen without a reply is always shown quoted,
# so a wrong pick is seen straight away.
# ---------------------------------------------------------------------------
NAME = "messages"
ICON = "🗂️"
ONLY_FOR = (
    "Tidying the messages in this channel themselves: archiving one to the archive channel, pinning or "
    "unpinning one, or deleting one. Not for what a message is about: removing an item from a list, a "
    "pill or a timer belongs to that task, and so does anything to be remembered or done."
)
EXAMPLES = ("archive that", "pin the message about the invoice", "delete my last message")
HINT = "Try “archive that”, or reply to the message with `archive`, `pin` or `delete`."

RECENT = 10  # how many of the channel's last messages Claude is shown
NEWEST, MINE, NAMED = "newest", "mine", "named"  # how a message was pointed at
PREFIX = "m"
QUOTE = 120


# ---------------------------------------------------------------------------
# The channel's last messages, and which of them an id means
# ---------------------------------------------------------------------------
async def recent(request: Request) -> list:
    """The last messages in the channel before the user's own, newest first."""
    client = discord_utils.client
    channel = client.get_channel(request.channel_id) if client and request.channel_id else None
    if channel is None:
        return []
    before = discord.Object(id=request.message_id) if request.message_id is not None else None
    try:
        return [message async for message in channel.history(limit=RECENT, before=before)]
    except discord.HTTPException:
        return []


def short(text: str, limit: int = QUOTE) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def said(message) -> str:
    """What a message says, in a line: its text, or what it holds if it has none."""
    text = short(getattr(message, "content", "") or "")
    if text:
        return text
    if getattr(message, "embeds", None):
        return "(a card)"
    return "(files)" if getattr(message, "attachments", None) else "(no text)"


def state_lines(found: list, replied_to: int | None = None) -> list[str]:
    """A line a message with its id, in the order they were sent: the newest
    (m1) is the last line and says so, as it would be read in the channel.
    `found` is newest first. Pure."""
    lines = []
    for number, message in enumerate(found, 1):
        author = getattr(message.author, "display_name", "someone")
        who = f"{author} (the bot)" if getattr(message.author, "bot", False) else f"{author} (the user)"
        text = f"{PREFIX}{number}: {who}: {said(message)}"
        if protection(message):
            text += f" · {protection(message)}"
        if replied_to is not None and message.id == replied_to:
            text += " · the user replied to this one"
        lines.append(text)
    return lines[::-1]


async def state(request: Request) -> State:
    return State(
        "The last messages in this channel, in the order they were sent: the last line is the newest (use these ids)",
        tuple(state_lines(await recent(request), request.replied_to)),
        empty="none before this one",
    )


def pick(found: list, refs: list[str]) -> tuple[list, list[str]]:
    """The messages the ids mean, in the order given and each once, and the ids
    that mean none. Pure."""
    chosen, bad, seen = [], [], set()
    for ref in refs:
        text = ref.strip().lower()
        number = int(text[len(PREFIX):]) if text.startswith(PREFIX) and text[len(PREFIX):].isdigit() else 0
        if not 1 <= number <= len(found):
            bad.append(ref)
        elif number not in seen:
            seen.add(number)
            chosen.append(found[number - 1])
    return chosen, bad


async def chosen(request: Request, data: dict) -> list:
    """The messages a request is about. A reply always means the message replied to."""
    found = await recent(request)
    if request.replied_to is not None:
        target = next((message for message in found if message.id == request.replied_to), None)
        if target is None:
            client = discord_utils.client
            channel = client.get_channel(request.channel_id) if client else None
            try:
                target = await channel.fetch_message(request.replied_to) if channel else None
            except discord.HTTPException:
                target = None
        if target is None:
            raise UserError("I can't find the message you replied to.")
        return [target]
    how, count = data.get("which", NAMED), max(1, int(data.get("count") or 1))
    if how == NEWEST:
        picked = found[:count]
    elif how == MINE:
        picked = [message for message in found if not getattr(message.author, "bot", False)][:count]
    else:
        picked, _ = pick(found, data.get("ids") or [])
    if not picked:
        raise UserError("I couldn't tell which message you meant. Reply to it, or say a few of its words.")
    return picked


def unsure(request: Request, guessed: frozenset) -> bool:
    """Whether the message acted on was a guess. Never on a reply: that says which."""
    return request.replied_to is None and (is_guessed(guessed, "which") or is_guessed(guessed, "ids"))


def quote(message, guessed: bool = False) -> str:
    link = f" · [jump]({message.jump_url})" if getattr(message, "jump_url", None) else ""
    return flag(f"> {said(message)}{link}", guessed)


# ---------------------------------------------------------------------------
# Pin and unpin: at once
# ---------------------------------------------------------------------------
async def pin(request: Request, data: dict, guessed: frozenset) -> str:
    pinning = data["action"] == "pin"
    done = []
    for message in await chosen(request, data):
        await pins.set_pinned(message.channel.id, message.id, pinning, "Pinned by asking" if pinning else "Unpinned by asking")
        done.append(quote(message, unsure(request, guessed)))
    return "\n".join([f"{PROTECT_EMOJI} {'Pinned' if pinning else 'Unpinned'}", *done])


# ---------------------------------------------------------------------------
# Archive: at once, unless a message is protected
# ---------------------------------------------------------------------------
async def archive_asks(request: Request, data: dict) -> bool:
    try:
        return any(protection(message) for message in await chosen(request, data))
    except UserError:
        return False  # `archive` says what is wrong in its own words


async def archive(request: Request, data: dict, guessed: frozenset) -> str:
    lines = []
    for message in await chosen(request, data):
        text = quote(message, unsure(request, guessed))  # read before it goes
        _, link = await messages.archive_message(message, request.user.id)
        lines += [f"{messages.ARCHIVE_EMOJI} Archived: {link}", text]
    return "\n".join(lines)


def _card(found: list, kind: str, label: str, destructive: bool, guessed: bool, last: str) -> Proposal:
    lines = [quote(message, guessed) for message in found]
    warnings = [f"“{short(said(message), 40)}” is {protection(message)}" for message in found if protection(message)]
    return Proposal(
        lines=tuple(lines),
        data={"channel": found[0].channel.id, "messages": [str(message.id) for message in found]},
        warnings=(*warnings, last),
        kind=kind,
        destructive=destructive,
        confirm_label=label,
    )


async def archive_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await chosen(request, data)
    for message in found:
        messages.check_archivable(message)
    return _card(found, "archive", "Archive anyway", False, unsure(request, guessed), "Archiving moves it to the archive channel, with a Restore button")


async def _fetch(data: dict) -> list:
    client = discord_utils.client
    channel = client.get_channel(data["channel"]) if client else None
    if channel is None:
        raise UserError("I can't see the channel those messages are in.")
    found = []
    for message_id in data["messages"]:
        try:
            found.append(await channel.fetch_message(int(message_id)))
        except discord.HTTPException:
            continue
    if not found:
        raise UserError("Those messages have already gone.")
    return found


async def archive_saved(request: Request, data: dict) -> str:
    links = [(await messages.archive_message(message, request.user.id))[1] for message in await _fetch(data)]
    return f"{messages.ARCHIVE_EMOJI} Archived: " + " · ".join(links)


# ---------------------------------------------------------------------------
# Delete: always asks
# ---------------------------------------------------------------------------
async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await chosen(request, data)
    for message in found:
        messages.check_deletable(message)
    count = len(found)
    return _card(
        found, "delete", "Delete for good" if count == 1 else f"Delete {count} for good", True,
        unsure(request, guessed), "Deleting can't be undone",
    )


async def delete_saved(request: Request, data: dict) -> str:
    found = await _fetch(data)
    for message in found:
        await messages.delete_message(message)
    return f"{messages.DELETE_EMOJI} Deleted" + (f" {len(found)} messages" if len(found) > 1 else "")


# ---------------------------------------------------------------------------
# The actions
# ---------------------------------------------------------------------------
_WHICH = (
    Field(
        "which",
        "How the user pointed at the message. newest: the last thing in the channel, whoever wrote it "
        "(\"that\", \"this\", \"it\", \"the last message\", \"the last two messages\"). mine: the last "
        "thing the USER wrote (\"my last message\", \"what I just said\"). named: a message described by "
        "its words or its subject (\"the one about the invoice\", \"the dentist note\"): then give `ids`. "
        "Never count positions yourself: the code finds the newest ones.",
        choices=(NEWEST, MINE, NAMED),
        required=True,
    ),
    Field("count", "With newest or mine: how many, if more than one (\"the last two\" -> 2). Leave out for one.", INTEGER),
    Field(
        "ids",
        "With named only: the id of each message meant, from the list given with the message, e.g. [\"m3\"]. "
        "If you cannot tell which is meant, give the likeliest and list `ids` as guessed.",
        LIST,
    ),
)

ACTIONS = (
    Action(
        "message_archive",
        "Move one or more messages to the archive channel (\"archive that\", \"file that away\", \"archive "
        "the last two messages\").",
        _WHICH,
        prepare=archive_card,
        apply=archive_saved,
        run=archive,
        card_if=archive_asks,
    ),
    Action(
        "message_pin",
        "Pin a message so it is kept, or unpin one (\"pin that\", \"keep the message about the invoice\", "
        "\"unpin it\").",
        (*_WHICH, Field("action", "pin or unpin.", choices=("pin", "unpin"), required=True)),
        needs_card=False,
        run=pin,
    ),
    Action(
        "message_delete",
        "Delete one or more messages for good (\"delete that\", \"delete my last message\"). Only for "
        "messages: never for an item, a pill, a timer or anything a message is about.",
        _WHICH,
        prepare=delete_card,
        apply=delete_saved,
    ),
)

ENTRY = Entry(NAME, ICON, ONLY_FOR, EXAMPLES, ACTIONS, HINT, state)
