import asyncio
import sqlite3

from core.config import DB_PATH, now_nz

# ---------------------------------------------------------------------------
# Database (raw input log)
#
# The schema lives in core/migrations.py. The functions starting with an
# underscore block while they talk to SQLite; the async wrappers run them in a
# worker thread so the event loop is never held up.
# ---------------------------------------------------------------------------
LOG_COLUMNS = {
    "reply",
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "duration_s",
    "status",
    "error",
    "timing",
}


def connect() -> sqlite3.Connection:
    """Open a new connection. One per call, so it is safe to use from worker threads."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _log_received(
    content: str,
    kind: str,
    discord_message_id: int | None,
    channel_id: int | None,
    user_id: int | None,
) -> int:
    conn = connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO message_log
                (received_at, kind, content, discord_message_id, channel_id, user_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'received')
            """,
            (now_nz().isoformat(), kind, content, discord_message_id, channel_id, user_id),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _log_result(row_id: int, fields: dict) -> None:
    columns = [name for name in fields if name in LOG_COLUMNS]
    if not columns:
        return
    assignments = ", ".join(f"{name} = ?" for name in columns)
    values = [fields[name] for name in columns] + [row_id]
    conn = connect()
    try:
        conn.execute(f"UPDATE message_log SET {assignments} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def _get_stats() -> dict:
    conn = connect()
    try:
        chats, input_tokens, output_tokens, cost = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(input_tokens), 0),
                   COALESCE(SUM(output_tokens), 0),
                   COALESCE(SUM(cost_usd), 0)
            FROM message_log
            WHERE kind = 'chat' AND status = 'ok'
            """
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM message_log").fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM message_log WHERE status = 'error'"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "total": total,
        "chats": chats,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "errors": errors,
    }


def _run(func, args: tuple):
    conn = connect()
    try:
        result = func(conn, *args)
        conn.commit()
        return result
    finally:
        conn.close()


async def run(func, *args):
    """Run func(conn, *args) in a worker thread with its own connection, then commit.

    For tasks' own tables: func does the blocking SQLite work and returns the result.
    """
    return await asyncio.to_thread(_run, func, args)


async def log_received(
    content: str,
    kind: str,
    discord_message_id: int | None = None,
    channel_id: int | None = None,
    user_id: int | None = None,
) -> int:
    """Record raw input before processing. Returns the new row's id."""
    return await asyncio.to_thread(
        _log_received, content, kind, discord_message_id, channel_id, user_id
    )


async def log_result(row_id: int, **fields) -> None:
    """Fill in the outcome of a logged input (reply, tokens, status and so on)."""
    await asyncio.to_thread(_log_result, row_id, fields)


# What the user sent as a message of their own (not a tool call or a reaction,
# which are logged against someone else's message or as a second row)
OWN_MESSAGE_KINDS = ("chat", "command", "reply_action", "expected", "confirmation")


def _recent_log(conn: sqlite3.Connection, channel_id: int, user_id: int, limit: int) -> list[tuple[int, str, str]]:
    marks = ", ".join("?" for _ in OWN_MESSAGE_KINDS)
    return conn.execute(
        f"""
        SELECT discord_message_id, content, received_at FROM message_log
        WHERE channel_id = ? AND user_id = ? AND discord_message_id IS NOT NULL AND kind IN ({marks})
        ORDER BY id DESC LIMIT ?
        """,
        (channel_id, user_id, *OWN_MESSAGE_KINDS, limit),
    ).fetchall()


async def recent_log(channel_id: int, user_id: int, limit: int) -> list[tuple[int, str, str]]:
    """The user's latest logged messages in a channel, newest first, as
    (Discord message id, content, when received as ISO text)."""
    return await run(_recent_log, channel_id, user_id, limit)


async def get_stats() -> dict:
    """All-time totals from the database."""
    return await asyncio.to_thread(_get_stats)
