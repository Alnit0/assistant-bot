import logging

import discord
from discord import app_commands

from core.database import log_received, log_result
from core.discord_utils import interaction_gone, log_error, log_simple, safe_reply
from core.errors import UserError
from core.permissions import is_allowed
from core.users import get_user_by_discord_id

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Shared plumbing for slash commands and context menus: who may use them, and
# logging each use to message_log and #bot-log. A skill calls check_allowed and
# begin from its command check; main.py calls finish or fail when the command
# ends. Slash commands are the fallback way in: most things are keywords.
# ---------------------------------------------------------------------------


async def check_allowed(interaction: discord.Interaction, permission: str, refusal: str) -> bool:
    """Permission check for slash commands, menus, buttons and forms."""
    user = await get_user_by_discord_id(interaction.user.id)
    if not is_allowed(user, permission):
        await safe_reply(interaction, refusal)
        return False
    # Remember who it was, for the log
    interaction.extras["user_id"] = user.id
    return True


def describe(interaction: discord.Interaction) -> str:
    """The command as it was used, e.g. "/lab chart renderer=matplotlib days=7"."""
    command = interaction.command
    if isinstance(command, app_commands.ContextMenu):
        target = (interaction.data or {}).get("target_id", "?")
        return f"menu: {command.name} (message {target})"
    name = command.qualified_name if command else "unknown"
    options = "".join(f" {key}={value}" for key, value in interaction.namespace)
    return f"/{name}{options}"


async def begin(interaction: discord.Interaction, *, kind: str, label: str, emoji: str) -> None:
    """Log a slash command or menu action before it runs.

    `kind` goes in message_log; `label` and `emoji` title the #bot-log cards,
    e.g. "🧪 Lab: /lab time" and "Lab failed: /lab time".
    """
    text = describe(interaction)
    log.info("%s: %s", label, text)
    interaction.extras["log_text"] = text
    interaction.extras["log_label"] = label
    interaction.extras["log_emoji"] = emoji
    interaction.extras["log_row_id"] = await log_received(
        text, kind, channel_id=interaction.channel_id, user_id=interaction.extras.get("user_id")
    )


def note(interaction: discord.Interaction, summary: str) -> None:
    """Say what the command did, for the log entry written when it finishes."""
    interaction.extras["log_summary"] = summary


async def finish(interaction: discord.Interaction, command=None) -> None:
    """Record that a logged command finished. Does nothing if begin was never called."""
    row_id = interaction.extras.pop("log_row_id", None)
    if row_id is None:
        return
    summary = interaction.extras.get("log_summary", "done")
    await log_result(row_id, reply=summary, status="ok")
    extras = interaction.extras
    await log_simple(f"{extras['log_emoji']} {extras['log_label']}: {extras['log_text']}", summary)


def explain(error: Exception) -> str:
    """Turn an error into something worth showing the user."""
    error = getattr(error, "original", error)
    if isinstance(error, UserError):
        return f"⚠️ {error}"
    if isinstance(error, discord.Forbidden):
        return (
            "⚠️ Discord refused that: the bot is missing a permission here "
            f"({error.text or 'no detail given'}). See the list in docs/DEVELOPMENT.md."
        )
    if isinstance(error, discord.HTTPException):
        return f"⚠️ Discord returned an error ({error.status}): {error.text or 'no detail given'}"
    return "⚠️ That didn't work. Check #bot-log."


async def fail(interaction: discord.Interaction, error: Exception) -> bool:
    """Record that a logged command failed and tell the user.

    Returns False if begin was never called for this interaction, so the
    caller knows nobody has explained the failure yet.
    """
    row_id = interaction.extras.pop("log_row_id", None)
    if row_id is None:
        return False
    original = getattr(error, "original", error)

    if interaction_gone(error):
        # Nothing to tell the user and nothing broken: close the log row and move on
        await log_result(
            row_id,
            status="error",
            error=f"interaction expired or was already answered: {original}",
        )
        return True

    message = explain(error)
    extras = interaction.extras
    await log_result(row_id, status="error", error=repr(original))
    await log_error(f"{extras['log_label']} failed: {extras['log_text']}", f"{message}\n{original!r}")
    await safe_reply(interaction, message)
    return True
