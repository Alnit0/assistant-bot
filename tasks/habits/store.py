import json
import sqlite3
from datetime import date, datetime, time

from core import database, recurrence
from tasks.habits.rules import ANY_TIME, NUDGE_NONE, STEP, GuideStep, Habit, Item

# ---------------------------------------------------------------------------
# Personal routines in the database: a routine (its repeat, when and nudge),
# its items in order (a step, or a group with its guide steps as JSON, each
# with a repeat of its own if it has one), and each item ticked on a day (one
# row an item a day, so a day starts with nothing ticked). Every row has a
# user_id; a removed routine or item keeps its row. The table of items is
# still called habits_steps, and a tick's column step_id: a migration never
# renames.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE habits_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            weekdays TEXT NOT NULL DEFAULT '[]',
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE habits_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            habit_id INTEGER NOT NULL REFERENCES habits_items(id),
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            removed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE habits_ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            step_id INTEGER NOT NULL REFERENCES habits_steps(id),
            day TEXT NOT NULL,
            done_at TEXT NOT NULL,
            UNIQUE (step_id, day)
        )
        """
    )


def add_when_and_groups(conn: sqlite3.Connection) -> None:
    """The rework (15 Oct): a routine's repeat, when and nudge; an item is a step or
    a group with its guide steps, and may have a repeat of its own. A routine's
    days become its repeat (chosen days, or every day)."""
    conn.execute("ALTER TABLE habits_items ADD COLUMN repeat TEXT")
    conn.execute("ALTER TABLE habits_items ADD COLUMN when_kind TEXT NOT NULL DEFAULT 'any_time'")
    conn.execute("ALTER TABLE habits_items ADD COLUMN at_time TEXT")
    conn.execute("ALTER TABLE habits_items ADD COLUMN start_time TEXT")
    conn.execute("ALTER TABLE habits_items ADD COLUMN end_time TEXT")
    conn.execute("ALTER TABLE habits_items ADD COLUMN nudge TEXT NOT NULL DEFAULT 'none'")
    conn.execute("ALTER TABLE habits_steps ADD COLUMN kind TEXT NOT NULL DEFAULT 'step'")
    conn.execute("ALTER TABLE habits_steps ADD COLUMN guide TEXT NOT NULL DEFAULT '[]'")
    conn.execute("ALTER TABLE habits_steps ADD COLUMN repeat TEXT")
    for habit_id, weekdays in conn.execute("SELECT id, weekdays FROM habits_items").fetchall():
        chosen = tuple(json.loads(weekdays or "[]"))
        repeat = recurrence.Repeat(recurrence.DAYS, weekdays=chosen) if chosen and len(chosen) < 7 else recurrence.EVERY_DAY
        conn.execute("UPDATE habits_items SET repeat = ? WHERE id = ?", (json.dumps(recurrence.to_dict(repeat)), habit_id))


MIGRATIONS = [create_tables, add_when_and_groups]


# --- what a row holds ------------------------------------------------------------------------------------------
def _time(text: str | None) -> time | None:
    return time.fromisoformat(text) if text else None


def _repeat(text: str | None) -> recurrence.Repeat | None:
    return recurrence.from_dict(json.loads(text)) if text else None


def _guide(text: str | None) -> tuple[GuideStep, ...]:
    return tuple(GuideStep(each["text"], recurrence.from_dict(each["repeat"]) if each.get("repeat") else None) for each in json.loads(text or "[]"))


def guide_json(guide) -> str:
    return json.dumps([{"text": each.text, **({"repeat": recurrence.to_dict(each.repeat)} if each.repeat is not None else {})} for each in guide])


def repeat_json(repeat: recurrence.Repeat | None) -> str | None:
    return json.dumps(recurrence.to_dict(repeat)) if repeat is not None else None


def _items(conn: sqlite3.Connection, habit_id: int) -> tuple[Item, ...]:
    rows = conn.execute("SELECT id, text, kind, guide, repeat FROM habits_steps WHERE habit_id = ? AND removed_at IS NULL ORDER BY position, id", (habit_id,)).fetchall()
    return tuple(Item(item_id, text, kind or STEP, _guide(guide), _repeat(repeat)) for item_id, text, kind, guide, repeat in rows)


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Habit]:
    found = []
    rows = conn.execute(
        "SELECT id, name, repeat, when_kind, at_time, start_time, end_time, nudge FROM habits_items WHERE user_id = ? AND removed_at IS NULL ORDER BY id", (user_id,)
    ).fetchall()
    for habit_id, name, repeat, when, at, start, end, nudge in rows:
        found.append(Habit(habit_id, user_id, name, _repeat(repeat) or recurrence.EVERY_DAY, _items(conn, habit_id), when or ANY_TIME, _time(at), _time(start), _time(end), nudge or NUDGE_NONE))
    return found


def db_ticked(conn: sqlite3.Connection, user_id: int, day: date) -> set[int]:
    return {row[0] for row in conn.execute("SELECT step_id FROM habits_ticks WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))}


def _fields(habit: Habit) -> tuple:
    return (
        habit.name, repeat_json(habit.repeat), habit.when,
        habit.at.isoformat("minutes") if habit.at else None, habit.start.isoformat("minutes") if habit.start else None, habit.end.isoformat("minutes") if habit.end else None,
        habit.nudge,
    )


def db_add(conn: sqlite3.Connection, user_id: int, habit: Habit, now: datetime) -> int:
    """A new routine, as `habit` says (its id is not used), with its items."""
    habit_id = conn.execute(
        "INSERT INTO habits_items (user_id, name, repeat, when_kind, at_time, start_time, end_time, nudge, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, *_fields(habit), now.isoformat()),
    ).lastrowid
    db_set_items(conn, user_id, habit_id, habit.items, now)
    return habit_id


def db_change(conn: sqlite3.Connection, habit: Habit, now: datetime) -> None:
    """The routine is as `habit` says: its name, repeat, when, nudge and items."""
    conn.execute("UPDATE habits_items SET name = ?, repeat = ?, when_kind = ?, at_time = ?, start_time = ?, end_time = ?, nudge = ? WHERE id = ?", (*_fields(habit), habit.id))
    db_set_items(conn, habit.user_id, habit.id, habit.items, now)


def db_set_items(conn: sqlite3.Connection, user_id: int, habit_id: int, items, now: datetime) -> None:
    """The routine's items are these, in this order. An item with an id it had keeps
    its row (and what is ticked today); one with the same words as one there is that
    one; one new is added; one gone is marked removed."""
    rows = conn.execute("SELECT id, text FROM habits_steps WHERE habit_id = ? AND removed_at IS NULL", (habit_id,)).fetchall()
    by_id = {item_id: text for item_id, text in rows}
    by_text = {text.lower(): item_id for item_id, text in rows}
    kept = set()
    for position, item in enumerate(items):
        item_id = item.id if item.id in by_id and item.id not in kept else by_text.get(item.text.lower())
        values = (position, item.text, item.kind, guide_json(item.guide), repeat_json(item.repeat))
        if item_id is None or item_id in kept:
            conn.execute("INSERT INTO habits_steps (user_id, habit_id, position, text, kind, guide, repeat) VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, habit_id, *values))
        else:
            kept.add(item_id)
            conn.execute("UPDATE habits_steps SET position = ?, text = ?, kind = ?, guide = ?, repeat = ? WHERE id = ?", (*values, item_id))
    for item_id in set(by_id) - kept:
        conn.execute("UPDATE habits_steps SET removed_at = ? WHERE id = ?", (now.isoformat(), item_id))


def db_remove(conn: sqlite3.Connection, habit_id: int, now: datetime) -> None:
    conn.execute("UPDATE habits_items SET removed_at = ? WHERE id = ?", (now.isoformat(), habit_id))


def db_tick(conn: sqlite3.Connection, user_id: int, item_id: int, day: date, now: datetime) -> bool:
    """Tick an item (a group: the whole group) for a day. False if it was ticked already."""
    return conn.execute("INSERT OR IGNORE INTO habits_ticks (user_id, step_id, day, done_at) VALUES (?, ?, ?, ?)", (user_id, item_id, day.isoformat(), now.isoformat())).rowcount == 1


def db_untick(conn: sqlite3.Connection, item_id: int, day: date) -> bool:
    return conn.execute("DELETE FROM habits_ticks WHERE step_id = ? AND day = ?", (item_id, day.isoformat())).rowcount == 1


def db_step(conn: sqlite3.Connection, item_id: int) -> tuple[int, int, str] | None:
    """(the item's user, its routine, its words), or None."""
    return conn.execute("SELECT user_id, habit_id, text FROM habits_steps WHERE id = ? AND removed_at IS NULL", (item_id,)).fetchone()


async def every(user_id: int) -> list[Habit]:
    return await database.run(db_all, user_id)


async def ticked(user_id: int, day: date) -> set[int]:
    return await database.run(db_ticked, user_id, day)
