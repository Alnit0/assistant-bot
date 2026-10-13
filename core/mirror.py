import logging

from core import surface

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A channel that shows exactly a given list of messages, and nothing else of
# the bot's: #commands. The channel itself is the record of what is there, so
# nothing is stored: the bot's messages in it are read, and
#   they read the same            nothing is touched
#   some read differently         those are edited in place
#   more are wanted               the ones there are edited to the first of the
#                                 list, and only the extra are posted, at the end
#   fewer are wanted              the first are edited, and only the ones left
#                                 over, the newest, are deleted
# So the order is always right, and the lot is never deleted and posted again:
# doing that at every change drew a rate limit from Discord each time.
# Messages from anyone else are left alone.
# ---------------------------------------------------------------------------
SAME, EDIT, ADD, DELETE = "unchanged", "edited", "added", "deleted"
MISSING = "channel not found"
LOOK_BACK = 200


class Refused(Exception):
    """The channel could not be read or written (a missing permission, say)."""


def plan(have: list[str], want: list[str]) -> tuple[list[int], int, int]:
    """What to do to turn the messages there (`have`, oldest first) into `want`:
    (the positions to edit in place, how many of `want` to post at the end,
    how many of `have` to delete from the end). Nothing in all three: it
    reads the same. Pure."""
    different = [position for position, (old, new) in enumerate(zip(have, want)) if old.strip() != new.strip()]
    return different, max(0, len(want) - len(have)), max(0, len(have) - len(want))


def done_text(edited: int, added: int, deleted: int) -> str:
    """What was done, in words: "unchanged", "2 edited", "9 edited, 1 added"."""
    parts = [f"{count} {word}" for count, word in ((edited, EDIT), (added, ADD), (deleted, DELETE)) if count]
    return ", ".join(parts) or SAME


async def sync(channel_id: int | None, texts: list[str]) -> str:
    """Make the bot's messages in a channel read `texts`, in order, by editing
    the ones there in place; a message is posted or deleted only when the
    number of them changes. Returns what was done, in words ("unchanged",
    "2 edited", "9 edited, 1 added", or MISSING). Raises Refused if that
    isn't allowed."""
    if surface.place(channel_id) is None:
        return MISSING
    try:
        me = surface.me()
        mine = [message for message in await surface.history(channel_id, limit=LOOK_BACK, oldest_first=True) if message.author.id == me]
        positions, added, deleted = plan([message.content for message in mine], texts)
        for position in positions:
            await surface.edit(channel_id, mine[position].id, texts[position], suppress_embeds=True)
        for text in texts[len(mine):]:
            await surface.send(channel_id, text, silent=True, suppress_embeds=True)
        for message in mine[len(texts):]:
            try:
                await surface.delete(channel_id, message.id)
            except surface.Gone:
                pass
    except surface.Failed as error:
        raise Refused(str(error)) from error
    return done_text(len(positions), added, deleted)
