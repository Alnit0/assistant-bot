import importlib
import logging
import pkgutil
from dataclasses import dataclass

import discord

import skills
from core import scheduler
from core.config import CHANNELS, ENABLED_SKILLS, REACTION_DEBOUNCE_SECONDS
from core.context import Context
from core.database import log_received, log_result
from core.debounce import Debouncer
from core.discord_utils import log_error, log_simple
from core.errors import UserError
from core.permissions import is_allowed
from core.router import Router
from core.users import User, get_user_by_discord_id
from skills.base import ANY, Keyword, Reaction, ReplyAction, Skill

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Registry
#
# Every package in skills/ is a skill: its __init__.py exposes a `skill` object
# (a Skill subclass instance). A skill that can't be loaded is skipped and
# reported, never allowed to stop the bot.
#
# The registry is also the one place that knows everything the bot can do:
# dispatch, `help` and Claude's capability list are all read from it.
# ---------------------------------------------------------------------------
_skills: list[Skill] = []
_keywords: list[tuple[Skill, Keyword]] = []
_reply_actions: list[tuple[Skill, ReplyAction]] = []
_reactions: dict[str, tuple[Skill, Reaction]] = {}
_events: dict[str, list[tuple[Skill, object]]] = {}
_app_commands: list = []
_problems: list[str] = []
_undocumented: list[str] = []

_keyword_router = Router()
_reply_router = Router()


def _emoji_key(emoji) -> str:
    # Discord sometimes drops the invisible "emoji style" character, so ignore it
    return str(emoji).replace("️", "")


def discover() -> list[str]:
    """Names of the skill packages in skills/, with builtin first."""
    names = [
        module.name
        for module in pkgutil.iter_modules(skills.__path__)
        if module.ispkg and not module.name.startswith("_")
    ]
    return sorted(names, key=lambda name: (name != "builtin", name))


def _problem(message: str) -> None:
    log.error("Skill problem: %s", message)
    _problems.append(message)


def _channel_names(item) -> list[str]:
    return [item.channels] if isinstance(item.channels, str) else list(item.channels)


def _check_registration(skill: Skill, kind: str, item) -> None:
    """Report a registration that doesn't describe itself or names an unknown channel."""
    if not (item.description or "").strip():
        _undocumented.append(f"{skill.name}: {kind} {item.name}")
    for name in _channel_names(item):
        if name != ANY and name not in CHANNELS:
            _problem(f"{skill.name}: {kind} {item.name} names channel '{name}', which isn't set in .env")


def _register_words(router: Router, skill: Skill, kind: str, item) -> None:
    entry = (skill, item)
    for word in item.words:
        owner = router.owner(word)
        if owner is not None:
            _problem(f"{skill.name}: {kind} `{word}` already belongs to {owner[0].name}")
            continue
        router.add(word, entry, takes_args=item.takes_args, exact=item.exact)


def load() -> None:
    """Import the enabled skills and register what they provide.

    Blocking: runs once at startup, before the event loop.
    """
    global _keyword_router, _reply_router
    _skills.clear()
    _keywords.clear()
    _reply_actions.clear()
    _reactions.clear()
    _events.clear()
    _app_commands.clear()
    _problems.clear()
    _undocumented.clear()
    _keyword_router = Router()
    _reply_router = Router()

    available = discover()
    if ENABLED_SKILLS is None:
        wanted = available
    else:
        wanted = [name for name in available if name in ENABLED_SKILLS]
        for name in ENABLED_SKILLS:
            if name not in available:
                _problem(f"{name}: listed in ENABLED_SKILLS but there is no skills/{name}/")

    for name in wanted:
        try:
            module = importlib.import_module(f"skills.{name}")
            skill = getattr(module, "skill", None)
            if not isinstance(skill, Skill):
                raise TypeError(f"skills/{name}/__init__.py must define `skill`, a Skill instance")
            if skill.name != name:
                raise ValueError(f"skill.name is {skill.name!r} but the folder is {name!r}")
            keywords = skill.keywords()
            reply_actions = skill.reply_actions()
            reactions = skill.reactions()
            jobs = skill.jobs()
            events = skill.events()
            slash_commands = skill.app_commands()
            skill.migrations()
        except Exception as error:
            log.exception("Could not load skill %s", name)
            _problems.append(f"{name}: {error!r}")
            continue

        _skills.append(skill)
        for keyword in keywords:
            _check_registration(skill, "keyword", keyword)
            _register_words(_keyword_router, skill, "keyword", keyword)
            _keywords.append((skill, keyword))
        for action in reply_actions:
            _check_registration(skill, "reply action", action)
            _register_words(_reply_router, skill, "reply action", action)
            _reply_actions.append((skill, action))
        for reaction in reactions:
            _check_registration(skill, "reaction", reaction)
            key = _emoji_key(reaction.emoji)
            if key in _reactions:
                _problem(f"{name}: reaction {reaction.emoji} already belongs to {_reactions[key][0].name}")
                continue
            _reactions[key] = (skill, reaction)
        for job in jobs:
            scheduler.add_daily_job(job.name, job.at, job.func)
        for event, handler in events.items():
            _events.setdefault(event, []).append((skill, handler))
        _app_commands.extend(slash_commands)

    log.info("Skills loaded: %s", summary())
    if _undocumented:
        log.warning("Registrations with no description: %s", "; ".join(_undocumented))


def loaded_skills() -> list[Skill]:
    return list(_skills)


def problems() -> list[str]:
    """Anything that was skipped while loading, for the startup log."""
    return list(_problems)


def missing_descriptions() -> list[str]:
    """Registrations that don't describe themselves, for the startup warning."""
    return list(_undocumented)


def app_commands() -> list:
    """Every loaded skill's slash command groups and context menus."""
    return list(_app_commands)


def skill_migrations() -> dict[str, list]:
    """Each loaded skill's migrations, for core.migrations.migrate."""
    return {skill.name: skill.migrations() for skill in _skills if skill.migrations()}


def summary() -> str:
    """One line for the startup log, e.g. "builtin (5 words), archive (2 reply actions, 1 reaction)"."""

    def count(number: int, noun: str) -> str:
        return f"{number} {noun}{'' if number == 1 else 's'}"

    parts = []
    for skill in _skills:
        words = sum(1 for owner, _ in _keywords if owner is skill)
        replies = sum(1 for owner, _ in _reply_actions if owner is skill)
        reactions = sum(1 for owner, _ in _reactions.values() if owner is skill)
        counts = [count(words, "word")] if words or not (replies or reactions) else []
        if replies:
            counts.append(count(replies, "reply action"))
        if reactions:
            counts.append(count(reactions, "reaction"))
        parts.append(f"{skill.name} ({', '.join(counts)})")
    return ", ".join(parts) or "none"


# ---------------------------------------------------------------------------
# Lifecycle and events
# ---------------------------------------------------------------------------
def setup(client: discord.Client) -> None:
    """Let each skill register persistent views before the bot connects. Never fatal."""
    for skill in _skills:
        try:
            skill.setup(client)
        except Exception as error:
            log.exception("Skill setup failed: %s", skill.name)
            _problems.append(f"{skill.name}: setup failed: {error!r}")


async def startup(client: discord.Client) -> None:
    """Give each skill its turn once the bot is connected. A failure is reported, not fatal."""
    for skill in _skills:
        try:
            await skill.startup(client)
        except Exception as error:
            log.exception("Skill startup failed: %s", skill.name)
            _problems.append(f"{skill.name}: startup failed: {error!r}")


async def emit(event: str, *args) -> None:
    """Pass a Discord event on to every skill that asked for it."""
    for skill, handler in _events.get(event, []):
        try:
            await handler(*args)
        except Exception as error:
            log.exception("Skill %s failed handling %s", skill.name, event)
            await log_error(f"Skill event failed: {skill.name} / {event}", repr(error))


# ---------------------------------------------------------------------------
# Where and for whom a registration works
# ---------------------------------------------------------------------------
def works_in(item, channel_id: int) -> bool:
    names = _channel_names(item)
    return ANY in names or any(CHANNELS.get(name) == channel_id for name in names)


def where(item) -> str:
    """Where a registration works, in words: "anywhere" or "#inbox, #gym"."""
    names = _channel_names(item)
    return "anywhere" if ANY in names else ", ".join(f"#{name}" for name in names)


# ---------------------------------------------------------------------------
# Dispatch: typed words and reply actions
# ---------------------------------------------------------------------------
async def _tell(ctx: Context, text: str) -> None:
    """Reply from an error path, where a second failure must not hide the first."""
    try:
        await ctx.reply(text)
    except discord.HTTPException as error:
        log.warning("Could not reply in channel %s: %s", ctx.channel_id, error)


async def _run(ctx: Context, *, kind: str, name: str, title: str, permission: str, call, after=None) -> None:
    """Log the input, check permission, run the handler, record what happened."""
    row_id = await log_received(ctx.text, kind, ctx.message_id, ctx.channel_id, user_id=ctx.user.id)

    if not is_allowed(ctx.user, permission):
        reply = "You're not allowed to do that."
        await _tell(ctx, reply)
        await log_result(row_id, reply=reply, status="denied")
        return

    try:
        reply = await call()
    except UserError as error:
        # The user can fix this one: say what's wrong, no traceback
        message = f"⚠️ {error}"
        log.info("%s not done: %s", name, error)
        await log_result(row_id, reply=message, status="error", error=str(error))
        await _tell(ctx, message)
        await ctx.log_error(f"Command failed: {name}", str(error), ctx.text)
        return
    except Exception as error:
        log.exception("Command failed: %s", name)
        await log_result(row_id, status="error", error=repr(error))
        await _tell(ctx, "⚠️ Command failed. Check #bot-log.")
        await ctx.log_error(f"Command failed: {name}", repr(error), ctx.text)
        return

    if reply is None:
        reply = "\n".join(ctx.replies) or "done"
    await log_result(row_id, reply=reply, status="ok")
    await ctx.log(title, reply)
    if after is not None:
        await after()


async def dispatch_keyword(ctx: Context) -> bool:
    """Run the keyword this input is. Returns False if it isn't one (here)."""
    match = _keyword_router.match(ctx.text)
    if match is None:
        return False
    _, keyword = match.entry
    if not works_in(keyword, ctx.channel_id):
        return False
    if keyword.accepts is not None and not keyword.accepts(match.args):
        return False
    ctx.args = match.args

    async def call():
        if match.corrected:
            await ctx.note(f"-# Read as: {match.phrase}")
        return await keyword.handler(ctx)

    await _run(
        ctx,
        kind="command",
        name=keyword.name,
        title=f"⌨️ Command: {keyword.name}",
        permission=keyword.permission,
        call=call,
    )
    return True


async def dispatch_reply_action(ctx: Context) -> bool:
    """Run the reply action this input is. Returns False if it isn't a reply, or not an action."""
    if not ctx.is_reply:
        return False
    match = _reply_router.match(ctx.text)
    if match is None:
        return False
    _, action = match.entry
    if not works_in(action, ctx.channel_id):
        return False
    ctx.args = match.args

    async def call():
        target = await ctx.fetch_reply_target()
        if target is None:
            raise UserError("I can't find the message you replied to.")
        if match.corrected:
            await ctx.note(f"-# Read as: {match.phrase}")
        return await action.handler(ctx, target)

    await _run(
        ctx,
        kind="reply_action",
        name=action.name,
        title=f"↩️ Reply action: {action.name}",
        permission=action.permission,
        call=call,
        after=ctx.delete_trigger if action.remove_trigger else None,
    )
    return True


# ---------------------------------------------------------------------------
# Dispatch: reactions, after a quiet period
# ---------------------------------------------------------------------------
async def _reactions_quiet(events: list[tuple[discord.RawReactionActionEvent, bool]]) -> None:
    """Things have gone quiet: act on the reactions that are still there."""
    balance: dict[tuple[int, str, int], int] = {}
    latest: dict[tuple[int, str, int], discord.RawReactionActionEvent] = {}
    for payload, added in events:
        key = (payload.message_id, _emoji_key(payload.emoji), payload.user_id)
        balance[key] = balance.get(key, 0) + (1 if added else -1)
        if added:
            latest[key] = payload
    for key, total in balance.items():
        # Added and then removed again cancels out: that is the undo
        if total > 0:
            await dispatch_reaction(latest[key])


# One timer for all reactions: any change to a registered emoji restarts it
_reaction_debouncer = Debouncer(REACTION_DEBOUNCE_SECONDS, _reactions_quiet, name="reactions")


def reaction_changed(payload: discord.RawReactionActionEvent, added: bool) -> None:
    """Note a reaction being added or removed. Handlers run once things go quiet."""
    if _emoji_key(payload.emoji) in _reactions:
        _reaction_debouncer.trigger((payload, added))


async def dispatch_reaction(payload: discord.RawReactionActionEvent) -> bool:
    """Run the reaction handler for this emoji. Returns False if nobody handles it."""
    entry = _reactions.get(_emoji_key(payload.emoji))
    if entry is None:
        return False
    skill, reaction = entry
    if not works_in(reaction, payload.channel_id):
        return False

    # Reactions from anyone who isn't allowed are ignored without comment
    user = await get_user_by_discord_id(payload.user_id)
    if not is_allowed(user, reaction.permission):
        return False

    text = f"reaction: {reaction.emoji}"
    row_id = await log_received(
        text, "reaction", payload.message_id, payload.channel_id, user_id=user.id
    )
    try:
        reply = await reaction.handler(payload, user)
    except UserError as error:
        log.info("Reaction %s not done: %s", reaction.emoji, error)
        await log_result(row_id, status="error", error=str(error))
        await log_error(f"Reaction failed: {reaction.emoji}", str(error), text)
        return True
    except Exception as error:
        log.exception("Reaction failed: %s (%s)", reaction.emoji, skill.name)
        await log_result(row_id, status="error", error=repr(error))
        await log_error(f"Reaction failed: {reaction.emoji}", repr(error), text)
        return True

    reply = reply or "done"
    await log_result(row_id, reply=reply, status="ok")
    await log_simple(f"{reaction.emoji} Reaction: {skill.name}", reply)
    return True


# ---------------------------------------------------------------------------
# What the bot can do: read by `help` and by Claude's system prompt
# ---------------------------------------------------------------------------
@dataclass
class SkillCapabilities:
    skill: Skill
    keywords: list[Keyword]
    reply_actions: list[ReplyAction]
    reactions: list[Reaction]


def catalogue(
    user: User | None = None, channel_id: int | None = None, skill_name: str | None = None
) -> list[SkillCapabilities]:
    """What each loaded skill offers, in load order.

    With a user, only what they are allowed to use. With a channel, only what
    works there. Skills with nothing left to show are left out.
    """

    def visible(item) -> bool:
        if channel_id is not None and not works_in(item, channel_id):
            return False
        return user is None or is_allowed(user, item.permission)

    result = []
    for skill in _skills:
        if skill_name is not None and skill.name != skill_name:
            continue
        entry = SkillCapabilities(
            skill,
            [item for owner, item in _keywords if owner is skill and visible(item)],
            [item for owner, item in _reply_actions if owner is skill and visible(item)],
            [item for owner, item in _reactions.values() if owner is skill and visible(item)],
        )
        if entry.keywords or entry.reply_actions or entry.reactions:
            result.append(entry)
    return result


def find(term: str) -> tuple[str, Skill, object] | None:
    """Look something up for `help <term>`: a skill, a word, a reply action or an emoji.

    Returns (kind, skill, item) with kind "skill", "keyword", "reply action" or
    "reaction"; item is None for a skill. Aliases and small typos are accepted.
    """
    wanted = term.strip().lower()
    for skill in _skills:
        if skill.name == wanted:
            return ("skill", skill, None)
    for kind, router in (("keyword", _keyword_router), ("reply action", _reply_router)):
        match = router.match(term)
        if match is not None and not match.args:
            skill, item = match.entry
            return (kind, skill, item)
    entry = _reactions.get(_emoji_key(term.strip()))
    if entry is not None:
        return ("reaction", entry[0], entry[1])
    return None


def describe_words(item) -> str:
    """A keyword or reply action as the user types it: "stats (also: stat)"."""
    text = item.name + (f" {item.usage}" if item.usage else "")
    if item.aliases:
        text += f" (also: {', '.join(item.aliases)})"
    return text


def capabilities_text(user: User | None, channel_id: int | None) -> str:
    """The same list `help` shows, as plain text for Claude's system prompt."""
    words, replies, reactions = [], [], []
    for entry in catalogue(user, channel_id):
        words += [f"- {describe_words(item)}: {item.description}" for item in entry.keywords]
        replies += [f"- {describe_words(item)}: {item.description}" for item in entry.reply_actions]
        reactions += [f"- {item.emoji}: {item.description}" for item in entry.reactions]

    sections = []
    if words:
        sections.append("Words to send as a message on their own:\n" + "\n".join(words))
    if replies:
        sections.append("Words to send as a reply to a message, to act on that message:\n" + "\n".join(replies))
    if reactions:
        sections.append("Reactions to add to a message:\n" + "\n".join(reactions))
    return "\n\n".join(sections)
