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


async def get_stats() -> dict:
    """All-time totals from the database."""
    return await asyncio.to_thread(_get_stats)
