import asyncio
import logging
from datetime import datetime, timedelta
from typing import Literal

import discord
from discord import app_commands

from core.config import now_nz
from core.discord_utils import log_simple
from skills.lab import data, state
from skills.lab.common import (
    STARTED_AT,
    LabError,
    Run,
    SlashRun,
    announce,
    lab,
    lab_keyword,
    record,
)

log = logging.getLogger("assistant")

STATE_KEY = "status_message"

_client: discord.Client | None = None
_task: asyncio.Task | None = None
# Pinned message ids per channel, as last seen, to work out what a pin change was
_pins: dict[int, set[int]] = {}


# ---------------------------------------------------------------------------
# The status message
# ---------------------------------------------------------------------------
def format_uptime(uptime: timedelta) -> str:
    total_minutes = int(uptime.total_seconds() // 60)
    if total_minutes == 0:
        return "under a minute"
    days, minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def build_status(now: datetime, uptime: timedelta, messages_today: int) -> str:
    return (
        "📊 **Hive status**\n"
        f"🕒 {now:%A %d %B, %I:%M %p}\n"
        f"⏱️ Uptime: {format_uptime(uptime)}\n"
        f"💬 Messages today: {messages_today}\n"
        f"-# Updated <t:{int(now.timestamp())}:R>, every minute. `/lab pin action:stop` ends it."
    )


async def render_status() -> str:
    now = now_nz()
    return build_status(now, now - STARTED_AT, await data.messages_today())


async def _run(channel_id: int, message_id: int) -> None:
    channel = _client.get_channel(channel_id)
    if channel is None:
        log.warning("Status message channel not found; stopping updates")
        await state.clear(STATE_KEY)
        return
    message = channel.get_partial_message(message_id)

    while True:
        # Wake just after the next minute begins
        now = now_nz()
        await asyncio.sleep(60 - now.second - now.microsecond / 1_000_000 + 0.5)
        try:
            await message.edit(content=await render_status())
            await announce("status: updated")
        except discord.NotFound:
            await state.clear(STATE_KEY)
            await record(
                "pin: status message gone",
                "The status message was deleted, so updates have stopped.",
                channel_id=channel_id,
                message_id=message_id,
            )
            return
        except discord.HTTPException as error:
            # A blip: try again next minute
            log.warning("Status update failed: %s", error)


def _start(channel_id: int, message_id: int) -> None:
    global _task
    _task = asyncio.create_task(_run(channel_id, message_id), name="lab status message")


async def stop_status(final_text: str) -> bool:
    """Stop updating, unpin and mark the message. Returns False if nothing was running."""
    global _task
    saved = await state.get(STATE_KEY)
    if _task is not None:
        _task.cancel()
        _task = None
    if saved is None:
        return False

    channel = _client.get_channel(saved["channel_id"])
    if channel is not None:
        message = channel.get_partial_message(saved["message_id"])
        try:
            await message.edit(content=final_text)
            await message.unpin(reason="Lab status message stopped")
        except discord.HTTPException as error:
            # Already deleted, or no permission: nothing more we can tidy up
            log.info("Could not tidy up the old status message: %s", error)
    await state.clear(STATE_KEY)
    return True


async def resume(client: discord.Client) -> None:
    """At startup: carry on updating a status message from before the restart."""
    global _client
    _client = client
    saved = await state.get(STATE_KEY)
    if saved is not None:
        _start(saved["channel_id"], saved["message_id"])
        log.info("Resumed the lab status message")


async def run_pin(run: Run, action: str) -> None:
    await run.start()
    stamp = int(now_nz().timestamp())

    if action == "stop":
        stopped = await stop_status(f"⏹️ **Hive status** stopped <t:{stamp}:R>.")
        run.note("stopped the status message" if stopped else "nothing was running")
        await run.done("Stopped and unpinned." if stopped else "No status message is running.")
        return

    channel = run.channel
    await stop_status(f"⏹️ **Hive status** replaced by a newer one <t:{stamp}:R>.")
    await _remember_pins(channel)

    message = await channel.send(await render_status())
    try:
        await message.pin(reason="Lab status message")
    except discord.Forbidden:
        await message.edit(content="⚠️ I couldn't pin this status message, so I've stopped.")
        raise LabError(
            "I couldn't pin the message. The bot's role needs Pin Messages "
            "(or Manage Messages) in this channel."
        )

    await state.put(
        STATE_KEY,
        {"channel_id": channel.id, "message_id": message.id},
        run.user_id,
    )
    _start(channel.id, message.id)
    run.note(f"pinned a status message in #{getattr(channel, 'name', channel.id)}")
    await run.done("Status message pinned. It updates every minute.")


@lab.command(name="pin", description="A pinned status message that updates itself every minute")
@app_commands.describe(action="Start the status message, or stop and unpin it")
async def pin(interaction: discord.Interaction, action: Literal["start", "stop"] = "start"):
    await run_pin(SlashRun(interaction), action)


KEYWORDS = [
    lab_keyword(
        "lab pin",
        "a pinned status message that updates itself every minute",
        run_pin,
        usage="[start|stop]",
        parse=lambda args: (args.choice(["start", "stop"], default="start"),),
        examples=["lab pin", "lab pin stop"],
    ),
]


# ---------------------------------------------------------------------------
# Pin changes, anywhere in the server
# ---------------------------------------------------------------------------
async def _current_pins(channel) -> dict[int, str]:
    """Pinned message ids in the channel, with a link to each."""
    return {message.id: message.jump_url async for message in channel.pins(limit=50)}


async def _remember_pins(channel) -> None:
    """Note what is pinned now, so the next change can be described."""
    if channel.id in _pins:
        return
    try:
        _pins[channel.id] = set(await _current_pins(channel))
    except discord.HTTPException:
        pass


def describe_pin_change(
    channel_mention: str,
    current: dict[int, str] | None,
    previous: set[int] | None,
    last_pin: datetime | None,
) -> str:
    lines = [f"Channel: {channel_mention}"]
    if current is None:
        lines.append("I couldn't read the pins here (missing Read Message History?).")
    else:
        lines.append(f"Pinned messages now: {len(current)}")
        if previous is None:
            lines.append("First change seen here since the bot started, so I can't say what changed.")
        else:
            for message_id in current.keys() - previous:
                lines.append(f"📌 Pinned: {current[message_id]}")
            for message_id in previous - current.keys():
                lines.append(f"Unpinned: message `{message_id}`")
    if last_pin is not None:
        lines.append(f"Most recent pin: <t:{int(last_pin.timestamp())}:R>")
    return "\n".join(lines)


async def on_pins_update(channel, last_pin: datetime | None) -> None:
    try:
        current = await _current_pins(channel)
    except discord.HTTPException:
        current = None
    previous = _pins.get(channel.id)
    if current is not None:
        _pins[channel.id] = set(current)
    await log_simple(
        "📌 Pins changed", describe_pin_change(channel.mention, current, previous, last_pin)
    )
