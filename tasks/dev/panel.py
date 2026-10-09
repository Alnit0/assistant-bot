import asyncio
import logging
import re

import discord

from core import channels, clock, devmode, lifecycle
from core.config import DB_PATH, DEV_DATABASE
from core.database import log_received, log_result
from core.discord_utils import log_error, log_simple, report_interaction_error, safe_reply
from core.lifecycle import MessageClass
from core.permissions import is_allowed
from core.clock import real_now
from core.users import get_user_by_discord_id
from tasks.dev import clockwords

log = logging.getLogger("assistant")

# This task uses discord.py directly for the panel, its pin and buttons, and
# the bot's status, like the lab, archive and timers tasks.

TASK = "dev"
PERMISSION = "dev"
TITLE = "🛠️ **Dev mode**"
STATUS = "🛠️ Dev mode"
# Shown on the panel and in the status for as long as the bot runs with --dev
DEV_DATABASE_LABEL = "DEV DATABASE"
EXTEND_SECONDS = 60 * 60

_client: discord.Client | None = None
# Where the panel is. In memory, like dev mode itself
_channel_id: int | None = None
_message_id: int | None = None
_expiry: asyncio.Task | None = None


def bind(client: discord.Client) -> None:
    global _client
    _client = client


# ---------------------------------------------------------------------------
# What the panel says
# ---------------------------------------------------------------------------
def _seconds(value: float) -> str:
    return f"{value:g}s"


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def _quiet(ignored: bool) -> str:
    return "ignored" if ignored else "respected"


def render() -> str:
    """Each setting against its normal value, and when dev mode ends."""
    now, normal = devmode.settings, devmode.NORMAL
    ends = int(devmode.expires_at.timestamp())
    database = [f"🧪 **{DEV_DATABASE_LABEL}** · `{DB_PATH.name}`"] if DEV_DATABASE else []
    return "\n".join(
        [
            f"{TITLE} · expires <t:{ends}:R> (<t:{ends}:t>)",
            *database,
            f"Reaction debounce: **{_seconds(now.debounce_s)}** (normal: {_seconds(normal.debounce_s)})",
            f"Speed: **{now.speed:g}x** (normal: {normal.speed:g}x)",
            f"Verbose log: **{_on_off(now.verbose)}** (normal: {_on_off(normal.verbose)})",
            f"Quiet hours: **{_quiet(now.ignore_quiet_hours)}** (normal: {_quiet(normal.ignore_quiet_hours)})",
            f"Clean-up: **{_on_off(now.cleanup)}** (normal: {_on_off(normal.cleanup)})",
            f"Clock: **{clockwords.describe(clock.now(), clock.offset())}**"
            + ("" if DEV_DATABASE else " · fixed on the live database"),
            "-# `dev off` to finish · `help dev` lists the words",
        ]
    )


# ---------------------------------------------------------------------------
# Buttons. Their ids are fixed, so one on a panel from before a restart still
# reaches us (and tidies that panel away).
# ---------------------------------------------------------------------------
BUTTONS = {
    "extend": ("+1 hour", "⏳", discord.ButtonStyle.primary),
    "reset": ("Reset", "🔁", discord.ButtonStyle.secondary),
    "disable": ("Disable", "⏹️", discord.ButtonStyle.danger),
}


class PanelButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"dev:panel:(?P<action>extend|reset|disable)",
):
    def __init__(self, action: str):
        label, emoji, style = BUTTONS[action]
        super().__init__(
            discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"dev:panel:{action}")
        )
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str], /):
        return cls(match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            user = await get_user_by_discord_id(interaction.user.id)
            if not is_allowed(user, PERMISSION):
                await safe_reply(interaction, "The dev panel isn't yours to press.")
                return
            # Answer straight away; the work below edits and deletes messages itself
            await interaction.response.defer()
            row_id = await log_received(
                f"dev panel button: {self.action}", TASK, interaction.message.id,
                interaction.channel_id, user_id=user.id,
            )
            if not devmode.enabled or interaction.message.id != _message_id:
                # A panel left over from before a restart
                await _delete(interaction.channel, interaction.message.id)
                outcome = "old panel removed (dev mode is off)"
            elif self.action == "extend":
                devmode.extend(EXTEND_SECONDS)
                await changed()
                outcome = "one more hour"
            elif self.action == "reset":
                devmode.reset()
                await changed()
                outcome = "reset to the dev defaults"
            else:
                outcome = await stop("Disable button")
            await log_result(row_id, reply=outcome, status="ok")
        except Exception as error:
            await report_interaction_error(interaction, error, f"Dev panel button failed: {self.action}")


def _view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in BUTTONS:
        view.add_item(PanelButton(action))
    return view


# ---------------------------------------------------------------------------
# Posting, updating and removing the panel
# ---------------------------------------------------------------------------
def _channel(channel_id: int | None):
    return _client.get_channel(channel_id) if _client and channel_id else None


async def _delete(channel, message_id: int | None) -> None:
    """Unpin and delete a panel. Best effort: it may already be gone.

    The panel is Live with no lasting value, so it goes; while clean-up is off
    it is only unpinned."""
    if channel is None or message_id is None:
        return
    message = channel.get_partial_message(message_id)
    steps = (message.unpin, message.delete) if lifecycle.deletes(MessageClass.LIVE) else (message.unpin,)
    for step in steps:
        try:
            await step()
        except discord.HTTPException:
            pass


async def _post(channel_id: int) -> None:
    """Post the panel in a channel and pin it. main.py deletes the pin notice."""
    global _channel_id, _message_id
    channel = _channel(channel_id)
    if channel is None:
        _channel_id = _message_id = None
        return
    message = await channel.send(render(), view=_view(), silent=True)
    _channel_id, _message_id = channel_id, message.id
    try:
        await message.pin(reason="Dev mode panel")
    except discord.HTTPException as error:
        log.warning("Could not pin the dev panel: %s", error)
        await log_error(
            "Dev panel not pinned",
            f"I posted the panel in {getattr(channel, 'mention', channel_id)} but couldn't pin it. "
            "The bot's role needs Pin Messages (or Manage Messages) there.",
        )


def status_text(dev_mode: bool, dev_database: bool) -> str | None:
    """What the bot's status reads: dev mode, the dev database, both or nothing."""
    parts = ([STATUS] if dev_mode else []) + ([f"🧪 {DEV_DATABASE_LABEL}"] if dev_database else [])
    return " · ".join(parts) or None


async def _set_status(on: bool) -> None:
    if _client is None:
        return
    text = status_text(on, DEV_DATABASE)
    try:
        await _client.change_presence(activity=discord.CustomActivity(name=text) if text else None)
    except Exception as error:
        log.warning("Could not change the bot's status: %s", error)


async def show_status() -> None:
    """Set the status to match how things are now (at startup)."""
    await _set_status(devmode.enabled)


async def _expire_later(seconds: float) -> None:
    await asyncio.sleep(seconds)
    await stop("expired")


def _arm_expiry() -> None:
    """(Re)start the countdown to the moment dev mode ends."""
    global _expiry
    if _expiry is not None and _expiry is not asyncio.current_task():
        _expiry.cancel()
    _expiry = None
    if devmode.enabled and devmode.expires_at is not None:
        wait = max(0.0, (devmode.expires_at - real_now()).total_seconds())
        _expiry = asyncio.create_task(_expire_later(wait), name="dev mode expiry")


async def started(channel_id: int) -> None:
    """Dev mode has just been switched on: show the panel here and set the status."""
    await _post(channel_id)
    await _set_status(True)
    _arm_expiry()
    await log_simple("🛠️ Dev mode on", f"In <#{channel_id}>, until <t:{int(devmode.expires_at.timestamp())}:t>.")


async def changed() -> None:
    """A setting changed: edit the panel in place and restart the countdown."""
    _arm_expiry()
    channel = _channel(_channel_id)
    if channel is None or _message_id is None:
        return
    try:
        await channel.get_partial_message(_message_id).edit(content=render(), view=_view())
    except discord.NotFound:
        await _post(_channel_id)  # someone deleted it: put it back
    except discord.HTTPException as error:
        log.warning("Could not update the dev panel: %s", error)


def is_panel(message_id: int) -> bool:
    """Whether a message is the current dev panel."""
    return devmode.enabled and message_id == _message_id


async def reshow(channel_id: int) -> None:
    """Bring the panel to the bottom of this channel (moving it from another if need be)."""
    await _delete(_channel(_channel_id), _message_id)
    await _post(channel_id)


async def stop(reason: str) -> str:
    """Switch dev mode off: remove the panel, restore normal settings, say so in #bot-log."""
    global _channel_id, _message_id
    if not devmode.enabled:
        return "dev mode was already off"
    devmode.disable()
    _arm_expiry()
    await _delete(_channel(_channel_id), _message_id)
    _channel_id = _message_id = None
    await _set_status(False)
    await log_simple("🛠️ Dev mode off", f"Reason: {reason}. Normal settings are back.")
    return f"dev mode off ({reason})"


async def clear_stale() -> None:
    """At startup dev mode is off, so any panel still pinned is from before the restart."""
    if _client is None:
        return
    removed = 0
    # Only channels that have pins: a forum (the #bugs channel) has none to read
    for channel in channels.named(_client):
        try:
            async for message in channel.pins():
                if message.author.id == _client.user.id and message.content.startswith(TITLE):
                    await _delete(channel, message.id)
                    removed += 1
        except discord.HTTPException as error:
            log.info("Could not look for an old dev panel in %s: %s", channel.id, error)
    if removed:
        await log_simple("🛠️ Dev mode off", "Reason: restart. The old panel was removed.")
