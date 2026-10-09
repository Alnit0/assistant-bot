import json
import sqlite3
from contextvars import ContextVar
from datetime import datetime

# ---------------------------------------------------------------------------
# What happened to one message, step by step, for `dev why` and bug reports.
#
# While a message is being handled, any code may leave a note here
# (`trace.note("…")`): a check that fired, one that was skipped, why a route
# was taken. core/conversation.py starts the trace, adds what the router and
# extraction returned and the card before and after, and keeps it with the
# message (`message_log.trace`, JSON). `block` puts a logged message and its
# trace into a few plain lines that can be copied whole.
#
# Pure apart from the two functions that take a connection. Imports nothing
# from core, so anything may leave a note.
# ---------------------------------------------------------------------------
_notes: ContextVar[list | None] = ContextVar("trace_notes", default=None)

MAX_NOTES = 40
MAX_BLOCK = 1800  # a block fits one Discord message, code fence included


def start() -> list:
    """Begin collecting notes for the message now being handled."""
    notes: list[str] = []
    _notes.set(notes)
    return notes


def stop() -> None:
    _notes.set(None)


def note(text: str) -> None:
    """Leave a note about the message being handled. Does nothing when no
    message is (a test, a job, a button with no trace)."""
    notes = _notes.get()
    if notes is not None and len(notes) < MAX_NOTES:
        notes.append(text)


# ---------------------------------------------------------------------------
# Database (blocking; called through database.run)
# ---------------------------------------------------------------------------
_COLUMNS = (
    "id, received_at, kind, content, route, tasks, reply, status, error, duration_s, cost_usd, claude_calls, "
    "extracted, trace, discord_message_id, channel_id"
)


def _row(conn: sqlite3.Connection, found: tuple) -> dict:
    row = dict(zip([name.strip() for name in _COLUMNS.split(",")], found))
    row["calls"] = conn.execute(
        "SELECT purpose, task, cost_usd, seconds, input_tokens, output_tokens FROM llm_calls WHERE message_log_id = ? ORDER BY id",
        (row["id"],),
    ).fetchall()
    # On the old way, each tool Claude ran is a row of its own against the same message
    row["parts"] = (
        conn.execute(
            "SELECT kind, content, status, reply FROM message_log WHERE discord_message_id = ? AND kind IN ('tool', 'undo') AND id != ? ORDER BY id",
            (row["discord_message_id"], row["id"]),
        ).fetchall()
        if row["discord_message_id"] and row["kind"] != "card"
        else []
    )
    return row


def db_recent(conn: sqlite3.Connection, user_id: int, limit: int, kinds: tuple[str, ...], skip_prefix: str = "") -> list[dict]:
    """The user's last messages with everything logged about them, oldest
    first. `skip_prefix` leaves out the words that ask for this very list."""
    marks = ", ".join("?" for _ in kinds)
    found = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM message_log
        WHERE user_id = ? AND kind IN ({marks}) AND (? = '' OR lower(content) NOT LIKE ?)
        ORDER BY id DESC LIMIT ?
        """,
        (user_id, *kinds, skip_prefix, skip_prefix.lower() + "%", limit),
    ).fetchall()
    return [_row(conn, row) for row in reversed(found)]


def db_get(conn: sqlite3.Connection, row_id: int) -> dict | None:
    found = conn.execute(f"SELECT {_COLUMNS} FROM message_log WHERE id = ?", (row_id,)).fetchone()
    return _row(conn, found) if found else None


# ---------------------------------------------------------------------------
# In words (pure)
# ---------------------------------------------------------------------------
def _loaded(text):
    try:
        return json.loads(text) if text else None
    except (TypeError, ValueError):
        return None


def _short(value, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = " ⏎ ".join(line for line in text.splitlines() if line.strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clock(received_at: str) -> str:
    try:
        return datetime.fromisoformat(received_at).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(received_at)


def _money(cost) -> str:
    return f"US${cost:.4f}" if cost is not None else "unknown"


def _extraction_line(found: dict) -> str:
    line = f"{found.get('task', '?')} · {found.get('action', '?')}"
    if "data" in found:
        line += f" {_short(found['data'])}"
    if found.get("guessed"):
        line += f" · guessed: {', '.join(found['guessed'])}"
    if found.get("not_included"):
        line += f" · not included: {'; '.join(found['not_included'])}"
    if found.get("reason"):
        line += f" · {_short(found['reason'], 160)}"
    return line


def lines(row: dict) -> list[str]:
    """One logged message as plain lines: what was said, how it was routed and
    why, what the router and extraction returned, what the code applied, the
    card before and after, what was shown, and what it cost."""
    kept = _loaded(row.get("trace")) or {}
    extracted = _loaded(row.get("extracted")) or []
    out = [f"#{row['id']} · {_clock(row['received_at'])} · {row['kind']} · {row['status']}", f"said: {_short(row['content'])}"]

    route = row.get("route") or "none"
    why = kept.get("why") or []
    out.append(f"route: {route}" + (f" ({'; '.join(why)})" if why else ""))
    if row.get("tasks"):
        out.append(f"tasks: {row['tasks']}")

    router = kept.get("router")
    if router:
        said = "chat" if router.get("chat") else ", ".join(router.get("tasks") or []) or "nothing"
        extras = [name for name in ("tie",) if router.get(name)]
        if router.get("chat_part"):
            extras.append(f"chat part: {_short(router['chat_part'], 120)}")
        if router.get("problem"):
            extras.append(f"problem: {_short(router['problem'], 120)}")
        out.append(f"router: {said}" + (f" · {' · '.join(extras)}" if extras else ""))
    elif route in ("router", "chat"):
        out.append("router: not recorded")
    else:
        out.append("router: not asked")

    if extracted:
        out += [f"extraction: {_extraction_line(found)}" for found in extracted]
    else:
        out.append("extraction: none")

    for kind, content, status, reply in row.get("parts") or []:
        out.append(f"{kind}: {_short(content, 160)} · {status}" + (f" · {_short(reply, 160)}" if reply else ""))
    for task, state in (kept.get("state") or {}).items():
        out.append(f"state sent ({task}): {state.get('sent', 0)} of {state.get('total', 0)} line(s)")
    checks = kept.get("checks") or []
    out += [f"python: {check}" for check in checks] or ["python: no checks recorded"]

    card = kept.get("card")
    if card:
        out.append("card before: " + (" / ".join(card.get("before") or []) or "none"))
        out.append("card after:  " + (" / ".join(card.get("after") or []) or "none"))
    if row.get("reply"):
        out.append(f"shown: {_short(row['reply'], 400)}")
    if row.get("error"):
        out.append(f"error: {_short(row['error'], 300)}")

    calls = row.get("calls") or []
    spent = " + ".join(
        f"{purpose}{f'/{task}' if task else ''} {_money(cost)} {seconds or 0:.1f}s" for purpose, task, cost, seconds, *_ in calls
    )
    total = row.get("cost_usd")
    took = f" · {row['duration_s']:.1f}s in all" if row.get("duration_s") is not None else ""
    out.append(f"cost: {_money(total if total is not None else 0.0)} · {len(calls)} request(s){took}" + (f" · {spent}" if spent else ""))
    return out


def block(row: dict) -> str:
    """The lines as one copyable code block that fits a Discord message."""
    text = "\n".join(line.replace("```", "'''") for line in lines(row))
    if len(text) > MAX_BLOCK:
        text = text[: MAX_BLOCK - 1] + "…"
    return f"```\n{text}\n```"
