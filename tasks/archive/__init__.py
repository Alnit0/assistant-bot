import discord

from core.config import REACTION_DEBOUNCE_SECONDS
from tasks.archive import messages, store
from tasks.base import Reaction, ReplyAction, Task

WAIT = f"{REACTION_DEBOUNCE_SECONDS:g} seconds"


class ArchiveTask(Task):
    """Tidying messages away: archive them to the archive channel, or delete them."""

    name = "archive"
    description = "Move messages to the archive channel (with a Restore button), or delete them"

    def reply_actions(self) -> list[ReplyAction]:
        return [
            ReplyAction(
                ["archive", "box", "file away"],
                "move that message to the archive channel (author, files and time kept; "
                "the copy has a Restore button)",
                messages.archive_reply,
                examples=["archive", "archive this"],
                validate=messages.check_archivable,
                undo=messages.undo_archive,
            ),
            ReplyAction(
                ["delete", "remove"],
                "delete that message for good",
                messages.delete_reply,
                examples=["delete"],
                # Destructive, so no typo correction: it must be spelled exactly
                exact=True,
                validate=messages.check_deletable,
            ),
        ]

    def reactions(self) -> list[Reaction]:
        # Destructive: once done, the message is gone, so these can only be cancelled
        # by removing the reaction within the quiet period. A message that can't be
        # archived or deleted is refused at once (validate), with no wait
        return [
            Reaction(
                messages.ARCHIVE_EMOJI,
                f"archive the message after {WAIT} (remove the reaction before then to cancel)",
                messages.on_archive_reaction,
                examples=[f"react {messages.ARCHIVE_EMOJI} to a message"],
                destructive=True,
                validate=messages.check_archivable,
            ),
            Reaction(
                messages.DELETE_EMOJI,
                f"delete the message after {WAIT} (remove the reaction before then to cancel)",
                messages.on_delete_reaction,
                examples=[f"react {messages.DELETE_EMOJI} to a message"],
                destructive=True,
                validate=messages.check_deletable,
            ),
        ]

    def app_commands(self) -> list:
        return [messages.archive_menu]

    def migrations(self) -> list:
        return list(store.MIGRATIONS)

    def setup(self, client: discord.Client) -> None:
        # Before connecting, so Restore buttons on old archived copies still work
        client.add_dynamic_items(messages.RestoreButton)

    async def startup(self, client: discord.Client) -> None:
        messages.bind(client)


task = ArchiveTask()
