import importlib
import logging
import pkgutil

import discord

import skills
from core import scheduler
from core.config import ENABLED_SKILLS
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import log_error, log_simple
from core.permissions import is_allowed
from core.users import get_user_by_discord_id
from skills.base import Command, Reaction, Skill

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Registry
#
# Every package in skills/ is a skill: its __init__.py exposes a `skill` object
# (a Skill subclass instance). A skill that can't be loaded is skipped and
# reported, never allowed to stop the bot.
# ---------------------------------------------------------------------------
_skills: list[Skill] = []
_commands: dict[str, tuple[Skill, Command]] = {}
_reactions: dict[str, tuple[Skill, Reaction]] = {}
_events: dict[str, list[tuple[Skill, object]]] = {}
_app_commands: list = []
_problems: list[str] = []


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


def load() -> None:
    """Import the enabled skills and register what they provide.

    Blocking: runs once at startup, before the event loop.
    """
    _skills.clear()
    _commands.clear()
    _reactions.clear()
    _events.clear()
    _app_commands.clear()
    _problems.clear()

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
            commands = skill.commands()
            jobs = skill.jobs()
            reactions = skill.reactions()
            events = skill.events()
            slash_commands = skill.app_commands()
            skill.migrations()
        except Exception as error:
            log.exception("Could not load skill %s", name)
            _problems.append(f"{name}: {error!r}")
            continue

        _skills.append(skill)
        for command in commands:
            key = command.name.lower()
            if key in _commands:
                _problem(f"{name}: command `{key}` already belongs to {_commands[key][0].name}")
                continue
            _commands[key] = (skill, command)
        for job in jobs:
            scheduler.add_daily_job(job.name, job.at, job.func)
        for reaction in reactions:
            key = _emoji_key(reaction.emoji)
            if key in _reactions:
                _problem(f"{name}: reaction {reaction.emoji} already belongs to {_reactions[key][0].name}")
                continue
            _reactions[key] = (skill, reaction)
        for event, handler in events.items():
            _events.setdefault(event, []).append((skill, handler))
        _app_commands.extend(slash_commands)

    log.info("Skills loaded: %s", summary())


def loaded_skills() -> list[Skill]:
    return list(_skills)


def all_commands() -> list[tuple[Skill, Command]]:
    """Every registered command with the skill it belongs to, in load order."""
    return list(_commands.values())


def problems() -> list[str]:
    """Anything that was skipped while loading, for the startup log."""
    return list(_problems)


def app_commands() -> list:
    """Every loaded skill's slash command groups and context menus."""
    return list(_app_commands)


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


async def dispatch_reaction(payload: discord.RawReactionActionEvent) -> bool:
    """Run the reaction handler for this emoji. Returns False if nobody handles it."""
    entry = _reactions.get(_emoji_key(payload.emoji))
    if entry is None:
        return False
    skill, reaction = entry

    # Reactions from anyone who isn't allowed are ignored without comment
    user = await get_user_by_discord_id(payload.user_id)
    if not is_allowed(user, f"reaction:{reaction.emoji}"):
        return False

    text = f"reaction: {reaction.emoji}"
    row_id = await log_received(
        text, "reaction", payload.message_id, payload.channel_id, user_id=user.id
    )
    try:
        reply = await reaction.handler(payload, user)
    except Exception as error:
        log.exception("Reaction failed: %s (%s)", reaction.emoji, skill.name)
        await log_result(row_id, status="error", error=repr(error))
        await log_error(f"Reaction failed: {reaction.emoji}", repr(error), text)
        return True

    reply = reply or "done"
    await log_result(row_id, reply=reply, status="ok")
    await log_simple(f"{reaction.emoji} Reaction: {skill.name}", reply)
    return True


def skill_migrations() -> dict[str, list]:
    """Each loaded skill's migrations, for core.migrations.migrate."""
    return {skill.name: skill.migrations() for skill in _skills if skill.migrations()}


def summary() -> str:
    """One line for the startup log, e.g. "builtin (5 commands)"."""
    parts = []
    for skill in _skills:
        count = sum(1 for owner, _ in _commands.values() if owner is skill)
        parts.append(f"{skill.name} ({count} command{'' if count == 1 else 's'})")
    return ", ".join(parts) or "none"


async def dispatch(ctx: Context) -> bool:
    """Run the command this input names. Returns False if it isn't a command."""
    entry = _commands.get(ctx.text.strip().lower())
    if entry is None:
        return False
    _, command = entry

    row_id = await log_received(
        ctx.text, "command", ctx.message_id, ctx.channel_id, user_id=ctx.user.id
    )

    if not is_allowed(ctx.user, f"command:{command.name}"):
        reply = "You're not allowed to do that."
        await ctx.reply(reply)
        await log_result(row_id, reply=reply, status="denied")
        return True

    try:
        reply = await command.handler(ctx)
    except Exception as error:
        log.exception("Command failed: %s", command.name)
        await log_result(row_id, status="error", error=repr(error))
        await ctx.reply("⚠️ Command failed. Check #bot-log.")
        await ctx.log_error(f"Command failed: {command.name}", repr(error), ctx.text)
        return True

    if reply is None:
        reply = "\n".join(ctx.replies)
    await log_result(row_id, reply=reply, status="ok")
    await ctx.log(f"⌨️ Command: {command.name}", reply)
    return True
