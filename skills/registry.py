import importlib
import logging
import pkgutil

import skills
from core import scheduler
from core.config import ENABLED_SKILLS
from core.context import Context
from core.database import log_received, log_result
from core.permissions import is_allowed
from skills.base import Command, Skill

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
_problems: list[str] = []


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

    log.info("Skills loaded: %s", summary())


def loaded_skills() -> list[Skill]:
    return list(_skills)


def all_commands() -> list[tuple[Skill, Command]]:
    """Every registered command with the skill it belongs to, in load order."""
    return list(_commands.values())


def problems() -> list[str]:
    """Anything that was skipped while loading, for the startup log."""
    return list(_problems)


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
