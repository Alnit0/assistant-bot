import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import design
from core.clearing import Found
from core.config import TIMEZONE
from core.timeinput import format_time

# ---------------------------------------------------------------------------
# Channel reset: which messages go and how, and every word said about it.
# Pure: no Discord, no database, no clock (the time comes in as `now`).
#
# Discord deletes messages up to 14 days old a hundred at a time and older
# ones only one by one. The age is by the real clock: it is Discord's rule
# about real messages, whatever the dev clock reads.
# ---------------------------------------------------------------------------
BATCH = 100
# A little inside Discord's 14 days, so a message can't grow too old between the plan and the request
BULK_AGE = timedelta(days=14) - timedelta(hours=1)
SECONDS_EACH = 1.2  # roughly what one single delete takes once the rate limit bites
NOTE_SECONDS = 10


@dataclass(frozen=True)
class Plan:
    """What a reset deletes, and how."""

    bulk: tuple[tuple[int, ...], ...]  # up to BATCH each, one request a tuple
    single: tuple[int, ...]  # too old for that: one request each
    kept: int  # pinned or 📌 messages left alone

    @property
    def ids(self) -> set[int]:
        return {message_id for batch in self.bulk for message_id in batch} | set(self.single)


def _is_old(message: Found, now: datetime) -> bool:
    return now - message.created_at > BULK_AGE


def plan(messages, keep_protected: bool, now: datetime, leave: frozenset[int] = frozenset()) -> Plan:
    """Every message goes, or every one that isn't pinned or marked 📌. `leave`
    is never touched or counted (the card that is asking)."""
    wanted = [message for message in messages if message.id not in leave and not (keep_protected and message.protected)]
    kept = sum(1 for message in messages if message.id not in leave and keep_protected and message.protected)
    young = [message.id for message in wanted if not _is_old(message, now)]
    old = [message.id for message in wanted if _is_old(message, now)]
    # A "batch" of one is no bulk request: it goes with the singles
    if len(young) == 1:
        old, young = [*young, *old], []
    batches = tuple(tuple(young[start : start + BATCH]) for start in range(0, len(young), BATCH))
    return Plan(batches, tuple(old), kept)


def counts(messages, now: datetime, leave: frozenset[int] = frozenset()) -> tuple[int, int, int]:
    """(all, pinned or 📌, over 14 days old) of the messages that would be looked at."""
    mine = [message for message in messages if message.id not in leave]
    return len(mine), sum(message.protected for message in mine), sum(_is_old(message, now) for message in mine)


def _messages(count: int) -> str:
    return f"{count} message{'' if count == 1 else 's'}"


def slow_text(old: int) -> str:
    """Said on the card when some messages can only go one at a time."""
    minutes = math.ceil(old * SECONDS_EACH / 60)
    return (
        f"⏳ {old} of them {'is' if old == 1 else 'are'} over 14 days old and can only be deleted one at a time: "
        f"that will be slow, about {minutes} minute{'' if minutes == 1 else 's'}"
    )


HEADING = "🧹 Channel · reset"
NOT_UNDONE = "⚠️ This can't be undone"


AGAIN = "♻️ Posted again afterwards:"


def card_text(mention: str, total: int, protected: int, old: int, again=()) -> str:
    """The card that asks: the counts, how slow it will be, what the tasks will
    post again once it is done (`again`, a line each), and that it can't be undone."""
    lines = [HEADING, f"{_messages(total)} in {mention}, {protected} of them pinned or 📌"]
    if old:
        lines.append(slow_text(old))
    if again:
        lines += [AGAIN, *(f"• {what}" for what in again)]
    lines.append(NOT_UNDONE)
    return "\n".join(lines)


def card_layout(mention: str, total: int, protected: int, old: int, again=(), row=()) -> tuple:
    """The same card in the one style of docs/DESIGN.md (drawn when CARDS_V2 is
    on): a red box, since it can't be undone, with the channel under the
    heading, the counts, what is posted again afterwards, the warning, and
    the buttons inside the box."""
    counts = f"**{_messages(total)}** · {protected} of them pinned or 📌"
    if old:
        counts += "\n" + design.small(slow_text(old))
    things = [counts]
    if again:
        things.append("\n".join(["♻️ **Posted again afterwards**", *(design.small(what) for what in again)]))
    return design.decision(HEADING, things, status=design.DESTRUCTIVE, context=mention, warnings=(f"**{NOT_UNDONE.removeprefix(design.WARNING).strip()}**",), row=row)


def cannot_text(mention: str, missing) -> str:
    """The card when the bot may not do it here: what it needs, instead of a failure."""
    needs = " and ".join(f"**{name}**" for name in missing)
    return f"{HEADING}\n⚠️ I can't reset {mention}: my role needs {needs} in this channel. Nothing was deleted."


def empty_text(mention: str) -> str:
    return f"🧹 {mention} is already empty: there is nothing to delete."


def working_text(count: int, single: int) -> str:
    slow = f" ({single} of them one at a time: this will be slow)" if single else ""
    return f"🧹 Deleting {_messages(count)}{slow}…"


def done_text(deleted: int, saved: bool = True) -> str:
    return f"🧹 Channel reset: {_messages(deleted)} deleted" + (" · a copy was saved" if saved else "")


NOT_SAVED = "⚠️ I couldn't save a copy of this channel first, so nothing was deleted. The reason is in #bot-log."


# ---------------------------------------------------------------------------
# The transcript taken before anything is deleted
# ---------------------------------------------------------------------------
def _when(moment: datetime) -> str:
    local = moment.astimezone(TIMEZONE)
    return f"{local:%Y-%m-%d} {format_time(local.time())}"


def file_name(channel: str, saved_at: datetime) -> str:
    """ "inbox-2026-10-11-1432.txt": the channel, the date and the time it was saved (NZ)."""
    safe = re.sub(r"[^a-z0-9_-]+", "-", channel.lower()).strip("-") or "channel"
    return f"{safe}-{saved_at.astimezone(TIMEZONE):%Y-%m-%d-%H%M%S}.txt"


def transcript(channel: str, messages, saved_at: datetime) -> str:
    """Everything in a channel, oldest first: who, when, what they said, whether
    it was pinned or marked, and a link to each attachment (the files
    themselves are not kept)."""
    ordered = sorted(messages, key=lambda message: (message.created_at, message.id))
    lines = [f"#{channel} · saved {_when(saved_at)} · {_messages(len(ordered))}", ""]
    for message in ordered:
        marked = f" ({message.why})" if message.why else ""
        said = message.content.splitlines() or [""]
        lines.append(f"[{_when(message.created_at)}] {message.author or 'unknown'}{marked}: {said[0]}".rstrip())
        lines += [f"    {more}" for more in said[1:]]
        lines += [f"    attachment: {link}" for link in message.attachments]
    return "\n".join(lines) + "\n"


def log_text(mention: str, deleted: int, kept: int, failed: int, saved_as: str = "") -> str:
    """The line for #bot-log."""
    parts = [f"{_messages(deleted)} deleted in {mention}"]
    parts.append(f"{kept} pinned or 📌 kept" if kept else "nothing kept")
    if failed:
        parts.append(f"{failed} could not be deleted")
    if saved_as:
        parts.append(f"copy saved as `{saved_as}`")
    return " · ".join(parts)
