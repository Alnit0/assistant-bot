import logging

import discord
from discord import app_commands

from core import discord_utils, interactions
from core.config import now_nz
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import log_simple, report_interaction_error, safe_reply
from core.errors import UserError
from core.interactions import explain
from skills.base import ANY, Keyword

log = logging.getLogger("assistant")

# When this process started, for uptime displays
STARTED_AT = now_nz()


class LabError(UserError):
    """Something went wrong that the user can fix. The message is shown to them as is."""


# ---------------------------------------------------------------------------
# Who may use the lab
# ---------------------------------------------------------------------------
async def check_owner(interaction: discord.Interaction) -> bool:
    """The lab's permission check, for slash commands, buttons and forms."""
    return await interactions.check_allowed(interaction, "lab", "The lab isn't for you.")


# ---------------------------------------------------------------------------
# One use of a lab command, however it was started
#
# Every lab command is a single function taking a Run, so the typed word
# ("lab chart") and the slash command (/lab chart) do exactly the same thing.
# Output always goes to the channel; only the acknowledgement differs.
# ---------------------------------------------------------------------------
class Run:
    channel: discord.abc.Messageable  # where to post
    user_id: int | None  # our users.id, for records
    member: discord.abc.User  # the Discord user, for mentions and DMs
    client: discord.Client
    summary: str = "done"

    async def start(self) -> None:
        """Acknowledge the request before doing the work."""

    async def done(self, text: str) -> None:
        """Tell the user privately that it's finished, where that is possible."""

    def note(self, summary: str) -> None:
        """Say what the command did, for message_log and #bot-log."""
        self.summary = summary


class SlashRun(Run):
    """Started with /lab ...: acknowledged privately, logged by core/interactions.py."""

    def __init__(self, interaction: discord.Interaction):
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            raise LabError("I can't post in this channel.")
        self.interaction = interaction
        self.channel = channel
        self.user_id = interaction.extras.get("user_id")
        self.member = interaction.user
        self.client = interaction.client

    async def start(self) -> None:
        await self.interaction.response.defer(ephemeral=True)

    async def done(self, text: str) -> None:
        await safe_reply(self.interaction, text)

    def note(self, summary: str) -> None:
        super().note(summary)
        interactions.note(self.interaction, summary)


class TypedRun(Run):
    """Started by typing "lab ...": acknowledged with a confirmation that deletes itself."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.channel = ctx.channel
        self.user_id = ctx.user.id
        self.member = ctx.author
        self.client = discord_utils.client

    async def done(self, text: str) -> None:
        await self.ctx.confirm(text)


class Args:
    """Reads the words typed after a lab phrase, in order."""

    def __init__(self, words: list[str], usage: str):
        self.words = [word.lower() for word in words]
        self.usage = usage

    def error(self) -> LabError:
        return LabError(f"Usage: `{self.usage}`")

    def choice(self, choices: list[str], default: str | None = None) -> str:
        """The next word if it is one of the choices, else the default (required if None)."""
        if self.words and self.words[0] in choices:
            return self.words.pop(0)
        if default is None:
            raise self.error()
        return default

    def number(self, name: str, default: int, low: int, high: int) -> int:
        if not self.words or not self.words[0].lstrip("-").isdigit():
            return default
        value = int(self.words.pop(0))
        if not low <= value <= high:
            raise LabError(f"{name} must be between {low} and {high}. Usage: `{self.usage}`")
        return value

    def delay(self, maximum: int) -> int:
        """An optional wait in seconds: "delay 90" or just "90". 0 if not given."""
        said_delay = self.flag("delay")
        if said_delay and not (self.words and self.words[0].isdigit()):
            raise self.error()
        return self.number("delay", 0, 0, maximum)

    def flag(self, word: str) -> bool:
        if self.words and self.words[0] == word:
            self.words.pop(0)
            return True
        return False

    def finish(self) -> None:
        """Anything left over is something we didn't understand."""
        if self.words:
            raise self.error()


def lab_keyword(phrase: str, description: str, run_command, *, usage: str = "", parse=None, examples=()) -> Keyword:
    """Register the typed form of a lab command, e.g. "lab chart".

    `run_command(run, *values)` is the same function the slash command calls.
    `parse(args)` turns the typed words into its values; leave it out for
    commands with no arguments. Works in any channel, for whoever may use the lab.
    """
    full_usage = f"{phrase} {usage}".strip()

    async def handler(ctx: Context) -> str:
        args = Args(ctx.args, full_usage)
        values = parse(args) if parse is not None else ()
        args.finish()
        run = TypedRun(ctx)
        await run_command(run, *values)
        return run.summary

    return Keyword(
        phrase,
        description,
        handler,
        examples=list(examples) or [phrase],
        channels=ANY,
        permission="lab",
        takes_args=True,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Logging lab actions that aren't commands: button presses, forms, summaries
# ---------------------------------------------------------------------------
async def report_component_error(
    interaction: discord.Interaction, error: Exception, label: str
) -> None:
    """A button, select or form handler failed: log it everywhere and tell the user."""
    await report_interaction_error(
        interaction, error, f"Lab component failed: {label}", reply=explain(error)
    )


# Parts of the lab that want to hear what the rest of it is doing (the tour
# uses this to notice a test has been completed). Each is `async (label)`.
observers: list = []


async def announce(label: str) -> None:
    """Tell the observers something happened, without logging it."""
    for observer in observers:
        try:
            await observer(label)
        except Exception:
            log.exception("A lab observer failed on %r", label)


async def record(
    label: str,
    summary: str,
    *,
    channel_id: int | None = None,
    user_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """Log a lab action that isn't a command: a button press, a form, a summary."""
    log.info("Lab: %s", label)
    row_id = await log_received(label, "lab", message_id, channel_id, user_id=user_id)
    await log_result(row_id, reply=summary, status="ok")
    await log_simple(f"🧪 Lab: {label}", summary)
    await announce(label)


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
# The /lab command group (the fallback way in; the typed words are the main one)
# ---------------------------------------------------------------------------
async def lab_check(interaction: discord.Interaction) -> bool:
    """Runs before every /lab command: owner only, then log the input."""
    if not await check_owner(interaction):
        return False
    await interactions.begin(interaction, kind="lab", label="Lab", emoji="🧪")
    return True


class LabGroup(app_commands.Group):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await lab_check(interaction)


lab = LabGroup(name="lab", description="Test bench for Discord features (owner only)")
