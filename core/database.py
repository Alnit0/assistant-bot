import sqlite3

from core.config import DB_PATH, now_nz

# ---------------------------------------------------------------------------
# Database (raw input log)
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


def init_db() -> None:
    """Create the database table if it doesn't exist yet."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                discord_message_id INTEGER,
                channel_id INTEGER,
                reply TEXT,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                duration_s REAL,
                status TEXT NOT NULL,
                error TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def log_received(
    content: str,
    kind: str,
    discord_message_id: int | None = None,
    channel_id: int | None = None,
) -> int:
    """Record raw input before processing. Returns the new row's id."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            """
            INSERT INTO message_log
                (received_at, kind, content, discord_message_id, channel_id, status)
            VALUES (?, ?, ?, ?, ?, 'received')
            """,
            (now_nz().isoformat(), kind, content, discord_message_id, channel_id),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def log_result(row_id: int, **fields) -> None:
    """Fill in the outcome of a logged input (reply, tokens, status and so on)."""
    columns = [name for name in fields if name in LOG_COLUMNS]
    if not columns:
        return
    assignments = ", ".join(f"{name} = ?" for name in columns)
    values = [fields[name] for name in columns] + [row_id]
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(f"UPDATE message_log SET {assignments} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def get_stats() -> dict:
    """All-time totals from the database."""
    conn = sqlite3.connect(DB_PATH)
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
