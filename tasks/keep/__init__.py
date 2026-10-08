import discord

from core import pins
from core.config import REACTION_DEBOUNCE_SECONDS
from core.context import Context
from core.protection import PROTECT_EMOJI
from core.users import User
from tasks.base import Reaction, ReplyAction, Task

KEEP_EMOJI = PROTECT_EMOJI
WAIT = f"{REACTION_DEBOUNCE_SECONDS:g} seconds"

# A kept message is one carrying the owner's 📌. The 📌 itself is what protects it
# (core/protection.py: left alone by clean-ups, and archive and delete ask
# first); keeping adds a native Discord pin on top, and unkeeping takes it off.


async def keep(payload: discord.RawReactionActionEvent, user: User) -> str:
    await pins.set_pinned(payload.channel_id, payload.message_id, True, "Kept with 📌")
    return f"kept and pinned a message in <#{payload.channel_id}>"


async def unkeep(payload: discord.RawReactionActionEvent, user: User) -> str:
    await pins.set_pinned(payload.channel_id, payload.message_id, False, "📌 removed")
    return f"unkept and unpinned a message in <#{payload.channel_id}>"


# The same by reply: "pin" pins the message straight away, and a pinned message
# is protected just as a 📌-marked one is. No 📌 is involved, so there is nothing
# to wait for and nothing recorded as a reaction.
async def pin_reply(ctx: Context, target: discord.Message) -> str:
    await pins.set_pinned(target.channel.id, target.id, True, "Pinned by reply")
    await ctx.confirm(f"{KEEP_EMOJI} Pinned")
    return f"pinned a message in <#{target.channel.id}>"


async def unpin_reply(ctx: Context, target: discord.Message) -> str:
    await pins.set_pinned(target.channel.id, target.id, False, "Unpinned by reply")
    await ctx.confirm(f"{KEEP_EMOJI} Unpinned")
    return f"unpinned a message in <#{target.channel.id}>"


# Taking them back (the Undo button on a confirmation of Claude's)
async def undo_pin(ctx: Context, target: discord.Message) -> str:
    await pins.set_pinned(target.channel.id, target.id, False, "Pin undone")
    return f"{KEEP_EMOJI} Unpinned again"


async def undo_unpin(ctx: Context, target: discord.Message) -> str:
    await pins.set_pinned(target.channel.id, target.id, True, "Unpin undone")
    return f"{KEEP_EMOJI} Pinned again"


class KeepTask(Task):
    """Keeping messages: pinned, and safe from clean-ups, archive and delete."""

    name = "keep"
    description = "Keep a message: pinned, left alone by clean-ups, and asked about before archiving or deleting"

    def reply_actions(self) -> list[ReplyAction]:
        return [
            ReplyAction(
                ["pin", "keep", "save"],
                "pin that message at once: clean-ups leave it alone, and archiving or deleting it asks first",
                pin_reply,
                examples=["pin", "pin this", "keep"],
                undo=undo_pin,
            ),
            ReplyAction(
                ["unpin", "unkeep"],
                "unpin that message, so it is no longer protected",
                unpin_reply,
                examples=["unpin"],
                undo=undo_unpin,
            ),
        ]

    def reactions(self) -> list[Reaction]:
        return [
            Reaction(
                KEEP_EMOJI,
                f"keep the message: after {WAIT} it is pinned, clean-ups leave it alone, and archiving "
                "or deleting it asks first. Remove the reaction to unkeep and unpin it",
                keep,
                examples=[f"react {KEEP_EMOJI} to a message"],
                undo=unkeep,
            ),
        ]


task = KeepTask()
