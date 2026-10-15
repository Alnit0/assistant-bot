import logging
import re

from core import actions, mirror
from core.config import COMMANDS_CHANNEL_ID
from core.discord_utils import log_error, log_simple, split_message
from tasks import registry

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# #commands: what the bot can do, for a person to read. Written from the task
# registry and nothing else, so it can't fall out of date: one message a task
# (icon and name, what it is for, then its ways in grouped by purpose), one
# for housekeeping, and the tasks for testing (dev, lab) last. Checked every
# time the bot starts, and only touched when it would read differently
# (core/mirror.py).
#
# What a line shows comes from the registrations themselves: a typed word's
# description, a plain-words action's `say` (placeholder names only: no pill
# of mine is ever named here), a task's `buttons()`.
# ---------------------------------------------------------------------------
WORDS, REPLIES, REACTIONS, BUTTONS = "words", "reply words", "reactions", "buttons"
# The order the groups come in, and their headings
GROUPS = (*actions.PURPOSES, WORDS, REPLIES, REACTIONS, BUTTONS)
DEFAULT_ICON = "🔹"
SPLIT_AT = 1900  # under Discord's 2000, with room for the line that says whose the rest is
HOUSEKEEPING_TITLE = "## 🧹 Housekeeping"
HOUSEKEEPING_ABOUT = (
    "Tidying messages away: archive, delete, pin and unpin, and emptying a channel. What the bot says about "
    "these goes after about ten seconds; #bot-log is the record."
)

_ASIDE = re.compile(r"\s*\([^()]*\)")
_NOT_FOR = re.compile(r"^(?:Not|Only|Never)\b")
_YOU = (("the user's", "your"), ("the user is", "you are"), ("the user has", "you have"), ("the user does", "you do"))
_THEY_DO = re.compile(r"\bthe user (\w+?)s\b")  # "the user takes" -> "you take"


def about(task) -> str:
    """What a task is for, for a person: its "only for" line without the asides
    in brackets (the router's examples, which may name things) and without
    what it is not for; "the user" becomes "you". A task with no such line
    (it takes no plain words) is described by its description."""
    if not task.only_for.strip():
        return task.description.strip()
    text = _ASIDE.sub("", task.only_for)
    for theirs, yours in _YOU:
        text = text.replace(theirs, yours)
    text = _THEY_DO.sub(r"you \1", text).replace("the user", "you")
    kept = [sentence for sentence in re.split(r"(?<=[.!?])\s+", text.strip()) if sentence and not _NOT_FOR.match(sentence)]
    return " ".join(kept) or task.description.strip()


def _typed(item) -> str:
    text = f"`{item.name}{' ' + item.usage if item.usage else ''}`"
    if item.aliases:
        text += f" (or {', '.join(f'`{alias}`' for alias in item.aliases)})"
    return f"• {text} · {item.description}"


def _said(action) -> str:
    return "• " + " · ".join(f"“{phrase}”" for phrase in action.say)


def _grouped(keywords=(), said=(), replies=(), reactions=(), buttons=()) -> dict[str, list[str]]:
    """Every line, under the group it belongs to."""
    groups: dict[str, list[str]] = {name: [] for name in GROUPS}
    for keyword in keywords:
        groups[keyword.purpose if keyword.purpose in actions.PURPOSES else WORDS].append(_typed(keyword))
    for action in said:
        groups[action.purpose if action.purpose in actions.PURPOSES else WORDS].append(_said(action))
    groups[REPLIES] += [_typed(reply) for reply in replies]
    groups[REACTIONS] += [f"• {reaction.emoji} · {reaction.description}" for reaction in reactions]
    groups[BUTTONS] += [f"• **{button.label}** · {button.description}" for button in buttons]
    return groups


def _page(title: str, described: str, groups: dict[str, list[str]]) -> str:
    lines = [title, described]
    for name in GROUPS:
        if groups[name]:
            lines += [f"**{name.capitalize()}**", *groups[name]]
    return "\n".join(line for line in lines if line)


def _is_housekeeping(entry) -> bool:
    """A task all of whose ways in are housekeeping (archive, keep, channel) has
    no message of its own: everything of it is listed with the housekeeping."""
    registered = [*entry.keywords, *entry.reply_actions, *entry.reactions]
    return bool(registered) and all(item.housekeeping for item in registered)


def build(entries) -> list[str]:
    """The messages of #commands, in order, from what each task registered
    (`registry.catalogue()`). Pure. One longer than Discord allows is split
    at a line break."""
    everyday, testing = [], []
    tidy = {"keywords": [], "said": [], "replies": [], "reactions": [], "buttons": []}
    for entry in entries:
        task = entry.task
        said = [action for action in task.actions() if action.say]
        folded = _is_housekeeping(entry)
        mine = {
            "keywords": [item for item in entry.keywords if not item.housekeeping and not folded],
            "said": [] if folded else said,
            "replies": [item for item in entry.reply_actions if not item.housekeeping and not folded],
            "reactions": [item for item in entry.reactions if not item.housekeeping and not folded],
            "buttons": [button for button in task.buttons() if not button.housekeeping and not folded],
        }
        tidy["keywords"] += [item for item in entry.keywords if item not in mine["keywords"]]
        tidy["said"] += said if folded else []
        tidy["replies"] += [item for item in entry.reply_actions if item not in mine["replies"]]
        tidy["reactions"] += [item for item in entry.reactions if item not in mine["reactions"]]
        tidy["buttons"] += [button for button in task.buttons() if button not in mine["buttons"]]
        if any(mine.values()):
            page = _page(f"## {task.icon or DEFAULT_ICON} {task.label}", about(task), _grouped(**mine))
            (testing if task.testing else everyday).append(page)
    pages = list(everyday)
    if any(tidy.values()):
        pages.append(_page(HOUSEKEEPING_TITLE, HOUSEKEEPING_ABOUT, _grouped(**tidy)))
    pages += testing
    return [chunk for page in pages for chunk in _split(page)]


def _split(page: str) -> list[str]:
    """A page as messages Discord will take: one too long is cut at a line break,
    and what follows says whose it is."""
    first, *rest = split_message(page, SPLIT_AT)
    title = page.splitlines()[0].lstrip("# ")
    return [first, *(f"-# {title} · continued\n{chunk}" for chunk in rest)]


def pages() -> list[str]:
    """#commands as the loaded tasks make it. A task that is only ever talked to
    (weather: no typed word, no reply word, no reaction) is listed too, for
    what one can say to it."""
    listed = registry.catalogue()
    have = {entry.task.name for entry in listed}
    spoken = [
        registry.TaskCapabilities(task, [], [], [])
        for task in registry.loaded_tasks()
        if task.name not in have and any(action.say for action in task.actions())
    ]
    return build([*listed, *spoken])


async def update() -> str:
    """Bring #commands up to date, if it is set in .env. Returns what was done.
    Never raises: a channel the bot may not write in is reported in #bot-log."""
    if COMMANDS_CHANNEL_ID is None:
        return "COMMANDS_CHANNEL_ID is not set"
    try:
        done = await mirror.sync(COMMANDS_CHANNEL_ID, pages())
    except mirror.Refused as error:
        log.warning("Could not update #commands: %s", error)
        await log_error(
            "#commands not updated",
            f"{error}. In <#{COMMANDS_CHANNEL_ID}> my role needs View Channel, Send Messages, Read Message History "
            "and Manage Messages.",
        )
        return "refused by Discord"
    log.info("#commands: %s", done)
    if done == mirror.MISSING:
        await log_error("#commands not updated", f"I can't see the channel COMMANDS_CHANNEL_ID names ({COMMANDS_CHANNEL_ID}).")
    elif done != mirror.SAME:
        await log_simple("📖 #commands updated", f"<#{COMMANDS_CHANNEL_ID}>: {done}.")
    return done
