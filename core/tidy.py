import logging
from datetime import timedelta

import discord

from core import discord_utils, lifecycle, outgoing, scheduler
from core.lifecycle import MessageClass

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Lines that must not outstay their welcome. A housekeeping line (delete,
# archive, pin, unpin, channel reset) is to be gone about ten seconds after it
# is said, and "gone" has to survive a restart: Discord's own "delete this
# message later" lives in the bot's memory and is forgotten with it. So the
# deleting is a job in the scheduler, which is kept in the database: a line
# whose time came while the bot was off is deleted when it starts.
# ---------------------------------------------------------------------------
JOB_TASK, JOB_KIND = "core", "tidy"


async def later(channel_id: int | None, message_id: int | None, seconds: float | None) -> None:
    """Have a message of ours deleted `seconds` from now. Nothing is booked if
    `seconds` is None (clean-up is switched off) or the message isn't known."""
    if seconds is None or channel_id is None or message_id is None:
        return
    due_at = scheduler.utc_now() + timedelta(seconds=seconds)
    await scheduler.add_job(JOB_TASK, JOB_KIND, due_at, {"channel": channel_id, "message": message_id})


async def tidy_job(job: scheduler.Job) -> None:
    """Scheduler handler: delete the message. Best effort: it may be gone already."""
    if not lifecycle.deletes(MessageClass.TRANSIENT):
        return  # clean-up was switched off meanwhile: leave it
    client = discord_utils.client
    channel = client.get_channel(job.payload.get("channel")) if client is not None else None
    if channel is None:
        return
    try:
        await channel.get_partial_message(job.payload["message"]).delete()
    except discord.HTTPException as error:
        log.debug("A line to tidy away had already gone, or couldn't be deleted: %s", error)


async def pointer(channel_id: int | None, text: str) -> None:
    """A line that only says where to look ("Today's checklist is in #hub"). What
    it points at is the answer, so the line itself goes after about ten
    seconds, whatever KEEP_CONFIRMATIONS says, and by the stored job."""
    client = discord_utils.client
    channel = client.get_channel(channel_id) if client is not None and channel_id else None
    text = outgoing.clean(text)
    if channel is None or not text:
        return
    message = await channel.send(text)
    lifecycle.note_transient(getattr(message, "id", None))
    await later(channel_id, getattr(message, "id", None), lifecycle.tidy_after())


def setup() -> None:
    scheduler.register_handler(JOB_TASK, JOB_KIND, tidy_job)
