import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from core.config import OWNER_ID, TIMEZONE_NAME
from core.database import connect

ROLE_OWNER = "owner"
ROLE_USER = "user"


@dataclass(frozen=True)
class User:
    id: int
    discord_id: int
    display_name: str
    timezone: str
    role: str
    created_at: str


def ensure_owner() -> None:
    """Make sure the owner from OWNER_ID exists with the owner role.

    Blocking: runs at startup, before the event loop. OWNER_ID in .env is the
    source of truth, so anyone else still marked as owner is demoted.
    """
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO users (discord_id, display_name, timezone, role, created_at)
            VALUES (?, 'Owner', ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET role = excluded.role
            """,
            (OWNER_ID, TIMEZONE_NAME, ROLE_OWNER, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "UPDATE users SET role = ? WHERE role = ? AND discord_id != ?",
            (ROLE_USER, ROLE_OWNER, OWNER_ID),
        )
        conn.commit()
    finally:
        conn.close()


def _get_user_by_discord_id(discord_id: int) -> User | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, discord_id, display_name, timezone, role, created_at
            FROM users
            WHERE discord_id = ?
            """,
            (discord_id,),
        ).fetchone()
    finally:
        conn.close()
    return User(*row) if row else None


async def get_user_by_discord_id(discord_id: int) -> User | None:
    """Look up a user by their Discord id, or None if we don't know them."""
    return await asyncio.to_thread(_get_user_by_discord_id, discord_id)
