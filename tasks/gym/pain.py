import sqlite3
from collections import Counter
from datetime import date

from core import database
from tasks.gym import rules

# ---------------------------------------------------------------------------
# The pain tracker: pain or discomfort mentioned in a gym note or in the diary,
# with its body part and exercise. Claude reads the words (a note's `pain` and
# `body_part`; the diary's own extraction); Python only counts. A history, the
# pattern on the exercise's card ("⚠️ shoulder flagged 3 times on lateral
# raises") with a swap from the list below, and "any pain?" in place. No
# medical advice: the pattern, and from 3 times a suggestion to have it looked
# at. Never on the lock screen, the status line or a ping.
# ---------------------------------------------------------------------------
LOOK_AT = 3  # times on one exercise: suggest checking with a professional
# A config list: a gentler swap to try for an exercise, by the words of its name (the first that fits)
SWAPS = (
    ("lateral raise", "cable lateral raise, lighter"), ("overhead press", "landmine press"), ("bench", "dumbbell bench press, neutral grip"),
    ("incline", "low-incline dumbbell press"), ("dip", "close-grip push-ups"), ("squat", "goblet squat or leg press"),
    ("romanian deadlift", "hip thrust"), ("deadlift", "trap-bar deadlift"), ("leg press", "leg extension"), ("pulldown", "neutral-grip pulldown"),
    ("row", "chest-supported row"), ("curl", "hammer curl"),
)
DIARY = "diary"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE gym_notes ADD COLUMN body_part TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE gym_pain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            day TEXT NOT NULL,
            body_part TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
        )
        """
    )


def swap_for(exercise: str) -> str:
    lowered = exercise.lower()
    return next((swap for words, swap in SWAPS if words in lowered), "")


def plural(name: str) -> str:
    lowered = name.lower()
    return lowered if lowered.endswith("s") else f"{lowered}s"


def pattern(exercise: str, flags: list[tuple[date, str]]) -> list[str]:
    """The card's lines for an exercise flagged twice or more: the count by body part, a swap, and from 3 times
    a suggestion to have it looked at. Pure."""
    if len(flags) < 2:
        return []
    parts = Counter(part or "pain" for _, part in flags)
    part, _ = parts.most_common(1)[0]
    lines = [f"⚠️ {part} flagged {len(flags)} times on {plural(exercise)}"]
    swap = swap_for(exercise)
    if swap:
        lines.append(f"maybe try {swap} instead")
    if len(flags) >= LOOK_AT:
        lines.append("if it keeps coming up, worth checking with a physio or doctor")
    return lines


# --- the store ---------------------------------------------------------------------------------------------------------------
def db_flags(conn: sqlite3.Connection, user_id: int, exercise: str) -> list[tuple[date, str]]:
    rows = conn.execute(
        "SELECT s.day, n.body_part FROM gym_notes n JOIN gym_sessions s ON s.id = n.session_id WHERE n.user_id = ? AND lower(n.exercise) = lower(?) AND n.pain = 1 ORDER BY s.day",
        (user_id, exercise),
    ).fetchall()
    return [(date.fromisoformat(row[0]), row[1] or "") for row in rows]


def db_history(conn: sqlite3.Connection, user_id: int) -> list[tuple[date, str, str]]:
    """Every mention: (day, body part, the exercise or "diary")."""
    gym = conn.execute(
        "SELECT s.day, n.body_part, n.exercise FROM gym_notes n JOIN gym_sessions s ON s.id = n.session_id WHERE n.user_id = ? AND n.pain = 1", (user_id,)
    ).fetchall()
    diary = conn.execute("SELECT day, body_part, source FROM gym_pain WHERE user_id = ?", (user_id,)).fetchall()
    return sorted((date.fromisoformat(row[0]), row[1] or "", row[2]) for row in [*gym, *diary])


def db_add_diary(conn: sqlite3.Connection, user_id: int, day: date, body_part: str) -> None:
    conn.execute("INSERT INTO gym_pain (user_id, day, body_part, source) VALUES (?, ?, ?, ?)", (user_id, day.isoformat(), body_part.strip().lower()[:40], DIARY))


async def flags(user_id: int, exercise: str) -> list[tuple[date, str]]:
    return await database.run(db_flags, user_id, exercise)


async def from_diary(user_id: int, day: date, body_part: str) -> None:
    """The diary's extraction said its words spoke of pain (the words themselves stay the diary's)."""
    await database.run(db_add_diary, user_id, day, body_part or "")


def history_text(found: list[tuple[date, str, str]], today: date) -> str:
    """ "any pain?", "pain history": counts by body part, where, and the latest. Pure."""
    if not found:
        return f"{rules.ICON} No pain noted."
    parts = Counter(part or "unsaid" for _, part, _ in found)
    lines = [f"{rules.ICON} **Pain noted** · {len(found)} time{'' if len(found) == 1 else 's'} · " + ", ".join(f"{part} {count}" for part, count in parts.most_common(4))]
    by_where = Counter(where for _, _, where in found)
    lines.append("on " + ", ".join(f"{where.lower()} {count}" for where, count in by_where.most_common(4)))
    last = found[-1]
    lines.append(f"last: {last[0].day} {last[0]:%b}" + (f" · {last[1]}" if last[1] else ""))
    if any(count >= LOOK_AT for count in by_where.values()):
        lines.append("if it keeps coming up, worth checking with a physio or doctor")
    return "\n".join(lines)
