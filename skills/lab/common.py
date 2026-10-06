import logging

import discord
from discord import app_commands

from core.config import now_nz
from core.database import log_received, log_result
from core.discord_utils import log_error, log_simple
from core.permissions import is_allowed
from core.users import get_user_by_discord_id

log = logging.getLogger("assistant")

# When this process started, for uptime displays
STARTED_AT = now_nz()


class LabError(Exception):
    """Something went wrong that the user can fix. The message is shown to them as is."""


# ---------------------------------------------------------------------------
# Who may use the lab
# ---------------------------------------------------------------------------
async def check_owner(interaction: discord.Interaction) -> bool:
    """The lab's permission check, for slash commands, menus, buttons and forms."""
    user = await get_user_by_discord_id(interaction.user.id)
    if not is_allowed(user, "lab"):
        await interaction.response.send_message("The lab isn't for you.", ephemeral=True)
        return False
    # Remember who it was, for the log
    interaction.extras["user_id"] = user.id
    return True


# ---------------------------------------------------------------------------
# Logging lab actions to message_log and #bot-log
# ---------------------------------------------------------------------------
def describe(interaction: discord.Interaction) -> str:
    """The command as it was used, e.g. "/lab chart renderer=matplotlib days=7"."""
    command = interaction.command
    if isinstance(command, app_commands.ContextMenu):
        target = (interaction.data or {}).get("target_id", "?")
        return f"menu: {command.name} (message {target})"
    name = command.qualified_name if command else "unknown"
    options = "".join(f" {key}={value}" for key, value in interaction.namespace)
    return f"/{name}{options}"


async def begin(interaction: discord.Interaction) -> None:
    """Log a slash command or menu action before it runs."""
    text = describe(interaction)
    log.info("Lab: %s", text)
    interaction.extras["lab_text"] = text
    interaction.extras["lab_row_id"] = await log_received(
        text, "lab", channel_id=interaction.channel_id, user_id=interaction.extras.get("user_id")
    )


def note(interaction: discord.Interaction, summary: str) -> None:
    """Say what the command did, for the log entry written when it finishes."""
    interaction.extras["lab_summary"] = summary


async def finish(interaction: discord.Interaction, command=None) -> None:
    """Record that a lab command finished. Does nothing for other skills' commands."""
    row_id = interaction.extras.pop("lab_row_id", None)
    if row_id is None:
        return
    summary = interaction.extras.get("lab_summary", "done")
    await log_result(row_id, reply=summary, status="ok")
    await log_simple(f"🧪 Lab: {interaction.extras['lab_text']}", summary)


def explain(error: Exception) -> str:
    """Turn an error into something worth showing the user."""
    error = getattr(error, "original", error)
    if isinstance(error, LabError):
        return f"⚠️ {error}"
    if isinstance(error, discord.Forbidden):
        return (
            "⚠️ Discord refused that: the bot is missing a permission here "
            f"({error.text or 'no detail given'}). See the list in docs/DEVELOPMENT.md."
        )
    if isinstance(error, discord.HTTPException):
        return f"⚠️ Discord returned an error ({error.status}): {error.text or 'no detail given'}"
    return "⚠️ That lab command failed. Check #bot-log."


async def say(interaction: discord.Interaction, text: str) -> None:
    """Reply privately, whether or not the interaction has been answered already."""
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


async def fail(interaction: discord.Interaction, error: Exception) -> None:
    """Record that a lab command failed and tell the user. Ignores other skills' commands."""
    row_id = interaction.extras.pop("lab_row_id", None)
    if row_id is None:
        return
    original = getattr(error, "original", error)
    message = explain(error)
    await log_result(row_id, status="error", error=repr(original))
    await log_error(
        f"Lab failed: {interaction.extras['lab_text']}", f"{message}\n{original!r}"
    )
    try:
        await say(interaction, message)
    except discord.HTTPException:
        log.warning("Could not tell the user about a failed lab command")


async def report_component_error(
    interaction: discord.Interaction, error: Exception, label: str
) -> None:
    """A button, select or form handler failed: log it everywhere and tell the user."""
    log.error("Lab component failed: %s", label, exc_info=error)
    await log_error(f"Lab component failed: {label}", repr(error))
    try:
        await say(interaction, explain(error))
    except discord.HTTPException:
        log.warning("Could not tell the user about a failed lab component")


async def record(
    label: str,
    summary: str,
    *,
    channel_id: int | None = None,
    user_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """Log a lab action that isn't a slash command: a button press, a form, a summary."""
    log.info("Lab: %s", label)
    row_id = await log_received(label, "lab", message_id, channel_id, user_id=user_id)
    await log_result(row_id, reply=summary, status="ok")
    await log_simple(f"🧪 Lab: {label}", summary)


async def record_press(interaction: discord.Interaction, label: str, summary: str) -> None:
    """Log a button, select or form interaction."""
    await record(
        label,
        summary,
        channel_id=interaction.channel_id,
        user_id=interaction.extras.get("user_id"),
        message_id=interaction.message.id if interaction.message else None,
    )


# ---------------------------------------------------------------------------
# The /lab command group
# ---------------------------------------------------------------------------
async def lab_check(interaction: discord.Interaction) -> bool:
    """Runs before every lab command: owner only, then log the input."""
    if not await check_owner(interaction):
        return False
    await begin(interaction)
    return True


class LabGroup(app_commands.Group):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await lab_check(interaction)


lab = LabGroup(name="lab", description="Test bench for Discord features (owner only)")


def target_channel(interaction: discord.Interaction):
    """The channel the command was used in, as something we can post to."""
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        raise LabError("I can't post in this channel.")
    return channel
