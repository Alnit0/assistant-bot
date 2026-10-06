import discord

from core import pins
from core.config import REACTION_DEBOUNCE_SECONDS
from core.protection import PROTECT_EMOJI
from core.users import User
from skills.base import Reaction, Skill

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


class KeepSkill(Skill):
    """Keeping messages: pinned, and safe from clean-ups, archive and delete."""

    name = "keep"
    description = "Keep a message: pinned, left alone by clean-ups, and asked about before archiving or deleting"

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


skill = KeepSkill()
