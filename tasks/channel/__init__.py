import asyncio
import logging
from pathlib import Path

from core import cards, clearing, clock, confirm, livelists, llm
from core.actions import Action, Request, Shown
from core.cards import Button, Card
from core.config import DATA_DIR, real_now_nz
from core.context import Context
from core.discord_utils import log_error, log_simple
from tasks.base import ANY, Keyword, Task
from tasks.channel import rules

# ---------------------------------------------------------------------------
# Channel reset: empty the channel you are in. Always asked first, on a card
# with the counts and that it can't be undone; one button deletes everything,
# another leaves what is pinned or marked 📌. Afterwards every task posts
# again whatever of its own was live there (Task.channel_cleared), so the
# day's checklist, running timers and the dev panel are back, and their
# records point at the new messages.
#
# Before anything is deleted the whole channel is written to a text file in
# data/exports/ (who, when, what, pinned or marked, links to attachments). If
# that can't be done, nothing is deleted.
#
# No discord.py here: reading and deleting is core/clearing.py, the buttons
# are core/cards.py. The channel's id travels in the buttons, so the card
# still works after a restart, and the channel is read again when one is
# pressed: what is deleted is what is there then.
# ---------------------------------------------------------------------------
TASK = "channel"
ICON = "🧹"
ALL, UNPINNED, CANCEL = "all", "unpinned", "cancel"
ONLY_FOR = (
    "Emptying the Discord channel the user is in: deleting every message in it at once (\"reset this "
    "channel\", \"clean up this channel\"). Not clearing or emptying a list, not deleting or archiving one "
    "message, and not resetting the chat's memory, a timer or a pill."
)
EXAMPLES = ("reset this channel", "clean up this channel")
EXPORT_DIR = DATA_DIR / "exports"  # in data/: never in git

log = logging.getLogger("assistant")


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text(text, encoding="utf-8")
    return target


async def save_copy(found: clearing.Scan) -> Path:
    """Write the channel as it stands to a text file, and say where. Raises
    OSError if it can't be written."""
    saved_at = real_now_nz()  # when it really was: a record, whatever the dev clock reads
    text = rules.transcript(found.name, found.messages, saved_at)
    return await asyncio.to_thread(_write, EXPORT_DIR, rules.file_name(found.name, saved_at), text)


def _cancel(channel_id: int) -> Button:
    return Button("Cancel", TASK, CANCEL, str(channel_id), emoji="✖️")


def asking_card(found: clearing.Scan, leave: frozenset[int] = frozenset()) -> Card | None:
    """The card for a channel as it stands. None if there is nothing in it to delete."""
    if found.missing:
        return Card(rules.cannot_text(found.mention, found.missing), ((_cancel(found.channel_id),),))
    total, protected, old = rules.counts(found.messages, clock.real_now(), leave)
    if not total:
        return None
    which = str(found.channel_id)
    return Card(
        rules.card_text(found.mention, total, protected, old),
        (
            (
                Button("Delete all", TASK, ALL, which, emoji="🗑️", style=cards.DANGER),
                Button("Delete all unpinned", TASK, UNPINNED, which, emoji="📌"),
                _cancel(found.channel_id),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------
async def reset_word(ctx: Context) -> str:
    """`reset channel`: the card for this channel."""
    # The word itself is tidied away once this has worked: it isn't one of the messages counted
    leave = frozenset({ctx.message_id} if ctx.message_id else ())
    found = await clearing.scan(ctx.channel_id)
    card = asking_card(found, leave)
    if card is None:
        await ctx.confirm(rules.empty_text(found.mention))
        return "nothing to delete"
    await cards.post(ctx, card)
    return f"asked before resetting {found.mention}"


async def reset_asked(request: Request, data: dict, guessed: frozenset) -> Shown | str:
    """ "reset this channel" in plain words: the same card."""
    found = await clearing.scan(request.channel_id)
    card = asking_card(found)
    if card is None:
        return rules.empty_text(found.mention)
    await cards.send(request.channel_id, card)
    return Shown(f"asked before resetting {found.mention}")


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------
async def _reset(press: cards.Press, keep_protected: bool) -> str:
    channel_id = int(press.arg)
    found = await clearing.scan(channel_id)
    if found.missing:
        # The permission went between the card and the press: said on the card, nothing deleted
        await press.update(Card(rules.cannot_text(found.mention, found.missing), ((_cancel(channel_id),),)))
        return "missing " + ", ".join(found.missing)
    # The card is left out of the plan and the count: it shows the work, and goes last
    card_id = frozenset({press.message_id} if press.message_id else ())
    todo = rules.plan(found.messages, keep_protected, clock.real_now(), card_id)
    await press.update(Card(rules.working_text(len(todo.ids), len(todo.single))))
    # A copy first, of everything that is there (the card apart): no copy, no deleting
    everything = clearing.Scan(found.channel_id, found.mention, tuple(m for m in found.messages if m.id not in card_id), name=found.name)
    try:
        saved = await save_copy(everything)
    except OSError as error:
        log.exception("Could not save a transcript of channel %s", channel_id)
        await log_error("Channel reset stopped: no copy could be saved", repr(error))
        await press.update(Card(f"{rules.HEADING}\n{rules.NOT_SAVED}", ((_cancel(channel_id),),)))
        return "not saved, nothing deleted"
    gone = await clearing.delete(channel_id, [list(batch) for batch in todo.bulk], list(todo.single))
    if press.message_id is not None:
        await cards.delete(channel_id, press.message_id)
        gone.add(press.message_id)
    deleted = len(gone & todo.ids)

    # Whatever pointed at a message that is gone is put right: open cards and
    # lists are forgotten, and each task posts its own live messages again
    await confirm.forget(gone)
    await livelists.forget(gone)
    done = rules.done_text(deleted, saved=True)
    await clearing.note(channel_id, done, rules.NOTE_SECONDS)
    from tasks import registry  # the registry loads this task: imported when used

    await registry.channel_cleared(channel_id, gone)
    await log_simple("🧹 Channel reset", rules.log_text(found.mention, deleted, todo.kept, len(todo.ids - gone), saved.name))
    llm.remember(channel_id, f"(pressed {'Delete all unpinned' if keep_protected else 'Delete all'})", done)
    return done


async def on_all(press: cards.Press) -> str:
    return await _reset(press, keep_protected=False)


async def on_unpinned(press: cards.Press) -> str:
    return await _reset(press, keep_protected=True)


async def on_cancel(press: cards.Press) -> str:
    await press.remove()
    return "cancelled"


class ChannelTask(Task):
    """Channel reset: empty the channel you are in, after asking."""

    name = TASK
    description = "Channel: empty the channel you are in, after asking, and put its live cards back"
    icon = ICON
    only_for = ONLY_FOR
    examples = EXAMPLES

    def actions(self) -> list:
        return [
            Action(
                "channel_reset",
                "The user asks to empty the channel they are in: delete every message in it (\"reset this channel\", "
                "\"clean up this channel\", \"clear this channel\"). They are always asked first, on a card.",
                needs_card=False,
                run=reset_asked,
            )
        ]

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["reset channel"],
                "empty the channel you are in: asks first, then deletes everything, or everything that isn't pinned or 📌; can't be undone",
                reset_word,
                examples=["reset channel"],
                channels=ANY,
                exact=True,
            ),
        ]

    def setup(self, client) -> None:
        cards.register(TASK, ALL, on_all)
        cards.register(TASK, UNPINNED, on_unpinned)
        cards.register(TASK, CANCEL, on_cancel)


task = ChannelTask()
