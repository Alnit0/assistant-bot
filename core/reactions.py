import sqlite3
from datetime import datetime, timezone

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


def emoji_key(emoji) -> str:
    """An emoji as we compare it. Discord sometimes drops the invisible "emoji style" character."""
    return str(emoji).replace("️", "")


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
        (message_id, channel_id, emoji, user_id, datetime.now(timezone.utc).isoformat()),
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
