import discord

from core.config import REACTION_DEBOUNCE_SECONDS
from skills.archive import messages
from skills.base import Reaction, ReplyAction, Skill


class ArchiveSkill(Skill):
    """Tidying messages away: archive them to the archive channel, or delete them."""

    name = "archive"
    description = "Move messages to the archive channel, or delete them"

    def reply_actions(self) -> list[ReplyAction]:
        return [
            ReplyAction(
                ["archive", "box", "file away"],
                "move that message to the archive channel (author, files and time kept)",
                messages.archive_reply,
                examples=["archive"],
            ),
            ReplyAction(
                ["delete", "remove"],
                "delete that message for good",
                messages.delete_reply,
                examples=["delete"],
                # Destructive, so no typo correction: it must be spelled exactly
                exact=True,
            ),
        ]

    def reactions(self) -> list[Reaction]:
        return [
            Reaction(
                messages.ARCHIVE_EMOJI,
                f"archive the message after {REACTION_DEBOUNCE_SECONDS} seconds "
                "(remove the reaction before then to cancel)",
                messages.on_archive_reaction,
            ),
        ]

    def app_commands(self) -> list:
        return [messages.archive_menu]

    async def startup(self, client: discord.Client) -> None:
        messages.bind(client)


skill = ArchiveSkill()
