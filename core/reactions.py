import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import clock

# ---------------------------------------------------------------------------
# Reactions: deciding what to do once things have gone quiet.
#
# A reaction action is identified by (message id, emoji, user id). After the
# quiet period we look at where each one the user touched ENDED UP, and compare
# that with what is currently applied:
#   there now, not applied  -> apply it
#   gone now, applied       -> undo it
#   anything else           -> nothing (added then removed in time cancels out)
# ---------------------------------------------------------------------------
Key = tuple[int, str, int]

DONE_EMOJI = "✅"  # added to a message once a reaction action has been applied
FAILED_EMOJI = "⚠️"
# A reaction still waiting out the quiet period is kept in the database, so one made just before a
# stop is dealt with after it. One older than the quiet period and this at the start is too old to act on
STALE_AFTER = timedelta(minutes=10)


def emoji_key(emoji) -> str:
    """An emoji as we compare it. Discord sometimes drops the invisible "emoji style" character."""
    return str(emoji).replace("️", "")


@dataclass(frozen=True)
class Change:
    """One reaction being added or removed, as Discord reported it."""

    message_id: int
    channel_id: int
    emoji: str  # as emoji_key gives it
    discord_user_id: int


@dataclass(frozen=True)
class Waiting:
    """A reaction change kept while it waits out the quiet period (reaction_waiting). It carries
    what a handler reads of Discord's event (message_id, channel_id, emoji, user_id: Discord's id
    of who reacted), so one made before a restart is dealt with after it as it would have been."""

    row_id: int
    message_id: int
    channel_id: int
    emoji: str
    user_id: int
    added: bool
    at: datetime


def resumable(waiting: list["Waiting"], now: datetime, quiet_seconds: float) -> tuple[list["Waiting"], list["Waiting"]]:
    """At the start: (what still waits, in order, to go through the quiet period again; what is
    too old, older than the quiet period and STALE_AFTER, to act on: dropped and said in the log)."""
    cut = now - timedelta(seconds=quiet_seconds) - STALE_AFTER
    ordered = sorted(waiting, key=lambda each: (each.at, each.row_id))
    return [each for each in ordered if each.at >= cut], [each for each in ordered if each.at < cut]


def key_for(
    change: Change,
    works_here: Callable[[str, int], bool],
    user_id_for: Callable[[str, int], int | None],
) -> Key | None:
    """The reaction action a change is about, or None if it is to be ignored.

    `works_here(emoji, channel_id)` says whether that emoji is registered and
    works in that channel. `user_id_for(emoji, discord_user_id)` gives our id
    for the person if they are allowed to use it, else None: reactions from
    anyone else are ignored without comment.
    """
    if not works_here(change.emoji, change.channel_id):
        return None
    user_id = user_id_for(change.emoji, change.discord_user_id)
    if user_id is None:
        return None
    return (change.message_id, change.emoji, user_id)


def should_validate(added: bool, has_validator: bool, works_here: bool, allowed: bool) -> bool:
    """Whether a reaction change is checked on the spot, before the quiet period.

    Only a reaction being added, that has a check, where it works, by someone
    allowed to use it. Everything else goes on as before: a removal has nothing
    to refuse, and reactions from anyone else are ignored without comment.
    """
    return added and has_validator and works_here and allowed


def final_states(events: list[tuple[Key, bool]]) -> dict[Key, bool]:
    """Where each reaction ended up: True if it is there after the last change to it.

    `events` is (key, added) in the order things happened.
    """
    final: dict[Key, bool] = {}
    for key, added in events:
        final[key] = added
    return final


def plan_changes(final: dict[Key, bool], applied: set[Key]) -> tuple[list[Key], list[Key]]:
    """What to do about each reaction that was touched: (to apply, to undo)."""
    to_apply = [key for key, present in final.items() if present and key not in applied]
    to_undo = [key for key, present in final.items() if not present and key in applied]
    return to_apply, to_undo


# ---------------------------------------------------------------------------
# What is applied (blocking; called through database.run)
# ---------------------------------------------------------------------------
def db_applied(conn: sqlite3.Connection, message_ids: list[int]) -> set[Key]:
    if not message_ids:
        return set()
    marks = ", ".join("?" for _ in message_ids)
    rows = conn.execute(
        f"SELECT message_id, emoji, user_id FROM reaction_state WHERE message_id IN ({marks})", message_ids
    ).fetchall()
    return {tuple(row) for row in rows}


def db_mark_applied(conn: sqlite3.Connection, key: Key, channel_id: int) -> None:
    message_id, emoji, user_id = key
    conn.execute(
        "INSERT OR REPLACE INTO reaction_state (message_id, channel_id, emoji, user_id, applied_at) VALUES (?, ?, ?, ?, ?)",
        (message_id, channel_id, emoji, user_id, clock.real_now().isoformat()),  # a record of what really happened
    )


def db_forget(conn: sqlite3.Connection, key: Key) -> int:
    """Forget an applied action. Returns how many are still applied on that message."""
    message_id, emoji, user_id = key
    conn.execute(
        "DELETE FROM reaction_state WHERE message_id = ? AND emoji = ? AND user_id = ?",
        (message_id, emoji, user_id),
    )
    return conn.execute(
        "SELECT COUNT(*) FROM reaction_state WHERE message_id = ?", (message_id,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# What is waiting out the quiet period (blocking; called through database.run)
# ---------------------------------------------------------------------------
def db_wait(conn: sqlite3.Connection, change: Change, user_id: int | None, added: bool, at: datetime) -> int:
    """Keep a change while it waits. Returns its row, to be let go once it is dealt with."""
    cursor = conn.execute(
        "INSERT INTO reaction_waiting (message_id, channel_id, emoji, discord_user_id, user_id, added, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (change.message_id, change.channel_id, change.emoji, change.discord_user_id, user_id, int(added), at.isoformat()),
    )
    return cursor.lastrowid


def db_waiting(conn: sqlite3.Connection) -> list[Waiting]:
    rows = conn.execute("SELECT id, message_id, channel_id, emoji, discord_user_id, added, at FROM reaction_waiting ORDER BY id").fetchall()
    return [Waiting(row[0], row[1], row[2], row[3], row[4], bool(row[5]), datetime.fromisoformat(row[6])) for row in rows]


def db_done_waiting(conn: sqlite3.Connection, row_ids: list[int]) -> None:
    for row_id in row_ids:
        conn.execute("DELETE FROM reaction_waiting WHERE id = ?", (row_id,))

