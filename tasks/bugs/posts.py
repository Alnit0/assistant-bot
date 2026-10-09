import logging

import discord

from core import discord_utils
from core.config import CHANNELS, DISCORD_LIMIT
from core.database import log_received, log_result
from core.discord_utils import log_error, log_simple, report_interaction_error, safe_reply, split_message, truncate
from core.errors import UserError
from core.permissions import is_allowed
from core.users import get_user_by_discord_id
from tasks.bugs import rules, store

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The Discord work for bugs, and the only place in this task that uses
# discord.py: reading the reported message, the forum post with its tags and
# buttons, and the line left in the channel. What they say is decided in
# rules.py.
# ---------------------------------------------------------------------------
PERMISSION = "bugs:close"
QUIET = discord.AllowedMentions.none()  # quoting a message must never ping anyone


async def _channel(channel_id: int):
    client = discord_utils.client
    if client is None:
        raise UserError("I'm not connected to Discord.")
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            # A thread that has gone quiet isn't remembered: ask for it
            channel = await client.fetch_channel(channel_id)
        except discord.HTTPException as error:
            raise UserError("I can't see the channel that message is in.") from error
    return channel


def forum() -> discord.ForumChannel:
    """The #bugs forum. Raises UserError, with what to put right, if it can't be used."""
    channel_id = CHANNELS.get("bugs")
    if channel_id is None:
        raise UserError("BUGS_CHANNEL_ID isn't set in .env, so there is nowhere to log bugs.")
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client else None
    if channel is None:
        raise UserError("I can't see the #bugs channel. Check BUGS_CHANNEL_ID.")
    if not isinstance(channel, discord.ForumChannel):
        raise UserError("BUGS_CHANNEL_ID must be a forum channel.")
    return channel


# --- reading what is reported -------------------------------------------------
async def preceding(message: discord.Message, count: int = rules.PRECEDING) -> list[rules.Snapshot]:
    """The messages just before this one in its channel, oldest first."""
    try:
        before = [item async for item in message.channel.history(limit=count, before=message)]
    except discord.HTTPException as error:
        log.info("Could not read the messages before a reported one: %s", error)
        return []
    return [rules.snapshot(item) for item in reversed(before)]


async def fetch_message(channel_id: int, message_id: int) -> discord.Message:
    channel = await _channel(channel_id)
    try:
        return await channel.fetch_message(message_id)
    except discord.HTTPException as error:
        raise UserError("I can't find the message you reacted to.") from error


async def send(channel_id: int, text: str) -> None:
    """Leave a lasting line in a channel (Kept): where the bug was logged."""
    channel = await _channel(channel_id)
    await channel.send(text, allowed_mentions=QUIET)


# --- the forum post -----------------------------------------------------------
def _tags(channel: discord.ForumChannel, names: list[str]) -> list[discord.ForumTag]:
    wanted = {name.lower() for name in names}
    return [tag for tag in channel.available_tags if tag.name.lower() in wanted][:5]


async def ensure_tags() -> None:
    """Make sure the forum has our tags. Never raises: a problem is reported in #bot-log."""
    try:
        channel = forum()
    except UserError as error:
        if CHANNELS.get("bugs") is not None:
            await log_error("Bugs: the forum can't be used", str(error))
        return
    missing = rules.missing_tags([tag.name for tag in channel.available_tags])
    if not missing:
        return
    # All of them in one request, so a refusal is one warning and not one a tag.
    # Asked again at every start for as long as any is missing
    wanted = list(channel.available_tags) + [discord.ForumTag(name=name) for name in missing]
    try:
        await channel.edit(available_tags=wanted)
    except discord.HTTPException as error:
        forbidden = isinstance(error, discord.Forbidden)
        log.warning("Could not create the forum tags %s: %s", ", ".join(missing), error)
        await log_error("Bugs: the forum's tags are missing", rules.tags_problem(missing, forbidden, str(error)))
        return
    log.info("Created the forum tags: %s", ", ".join(missing))


async def create_post(number: int, report: rules.Report) -> tuple[int, str]:
    """Open the bug's forum post. Returns (thread id, link to it)."""
    channel = forum()
    first, *rest = rules.post_sections(number, report)
    try:
        created = await channel.create_thread(
            name=rules.title(number, report.target.content),
            content=truncate(first, DISCORD_LIMIT),
            applied_tags=_tags(channel, [rules.TAGS[rules.OPEN]]),
            view=CloseButtons(),
            allowed_mentions=QUIET,
        )
        for section in rest:
            for chunk in split_message(section):
                await created.thread.send(chunk, allowed_mentions=QUIET)
    except discord.Forbidden as error:
        raise UserError(
            "Discord refused the post in #bugs: the bot needs Create Posts and Send Messages in Threads there."
        ) from error
    except discord.HTTPException as error:
        raise UserError(f"Discord refused the post in #bugs ({error.status}): {error.text}") from error
    return created.thread.id, created.thread.jump_url


# --- closing ------------------------------------------------------------------
async def _close(interaction: discord.Interaction, status: str) -> None:
    user = await get_user_by_discord_id(interaction.user.id)
    if not is_allowed(user, PERMISSION):
        await safe_reply(interaction, "Closing bugs isn't for you.")
        return
    # Answer first; the database and the tag change follow
    await interaction.response.defer()
    item = await store.by_thread(interaction.channel_id)
    if item is None:
        await safe_reply(interaction, "I have no bug on record for this post.")
        return
    row_id = await log_received(
        f"close {rules.bug_id(item.id)} as {status}", "bugs", interaction.message.id, interaction.channel_id,
        user_id=user.id,
    )
    already = item.status == status
    if not already:
        await store.set_status(item.id, status)
    text = rules.closed_text(item.id, status, already)
    # Said before archiving: a message sent to an archived post would reopen it
    await interaction.followup.send(text)
    thread = interaction.channel
    try:
        names = rules.tags_after([tag.name for tag in thread.applied_tags], status)
        await thread.edit(applied_tags=_tags(thread.parent, names), archived=True)
    except discord.HTTPException as error:
        log.warning("Could not tag and archive the post of %s: %s", rules.bug_id(item.id), error)
        await log_error(
            f"Bugs: {rules.bug_id(item.id)} is closed, but its post isn't",
            f"The bot needs Manage Threads in #bugs to set the tag and archive the post. ({error})",
        )
    await log_result(row_id, reply=text, status="ok")
    await log_simple(f"{rules.BUG_EMOJI} Bug closed", text)


class CloseButtons(discord.ui.View):
    """Fixed and Won't fix, under the first message of every bug's post. The ids
    are fixed and the bug is found from the post, so they work after a restart."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fixed", emoji="✅", style=discord.ButtonStyle.success, custom_id="bugs:fixed")
    async def fixed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close(interaction, rules.FIXED)

    @discord.ui.button(label="Won't fix", style=discord.ButtonStyle.secondary, custom_id="bugs:wontfix")
    async def wontfix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close(interaction, rules.WONTFIX)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_interaction_error(interaction, error, "Closing a bug failed")
