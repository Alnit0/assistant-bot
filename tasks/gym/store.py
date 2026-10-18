import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from core import database
from tasks.gym.rules import DoneSet, Exercise, Note, PlannedSet, Workout

# ---------------------------------------------------------------------------
# The gym in the database. The plan (workouts in rotation order, exercises in
# order, each planned set), the rotation's queue, sessions (from the import or
# as they happen) and their sets and notes, personal bests, and what can be
# undone. Every row has a user_id; history keeps exercise names as they were,
# so a new plan never rewrites what a past session shows.
# ---------------------------------------------------------------------------


def create_tables(conn: sqlite3.Connection) -> None:
    # One statement at a time: a script would commit by itself, inside the migration's own transaction
    for statement in _TABLES.split(";"):
        if statement.strip():
            conn.execute(statement)


_TABLES = (
        """
        CREATE TABLE gym_workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            position INTEGER NOT NULL,
            removed_at TEXT
        );
        CREATE TABLE gym_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            workout_id INTEGER NOT NULL REFERENCES gym_workouts(id),
            position INTEGER NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            step REAL,
            sets TEXT NOT NULL DEFAULT '[]',
            removed_at TEXT
        );
        CREATE TABLE gym_state (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            queue TEXT NOT NULL DEFAULT '[]',
            target_per_week INTEGER,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE gym_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            workout_id INTEGER,
            name TEXT NOT NULL,
            day TEXT NOT NULL,
            number INTEGER,
            status TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'live',
            off_plan TEXT,
            swaps TEXT NOT NULL DEFAULT '{}',
            channel_id INTEGER,
            message_id INTEGER,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE TABLE gym_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            session_id INTEGER NOT NULL REFERENCES gym_sessions(id),
            exercise TEXT NOT NULL,
            position INTEGER NOT NULL,
            set_type TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            low INTEGER,
            high INTEGER,
            reps INTEGER,
            weight REAL,
            per_hand INTEGER NOT NULL DEFAULT 0,
            mirrored INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX gym_sets_session ON gym_sets (session_id);
        CREATE TABLE gym_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            session_id INTEGER NOT NULL REFERENCES gym_sessions(id),
            exercise TEXT NOT NULL,
            text TEXT NOT NULL,
            pain INTEGER NOT NULL DEFAULT 0,
            target_low REAL,
            target_high REAL
        );
        CREATE TABLE gym_bests (
            user_id INTEGER NOT NULL REFERENCES users(id),
            exercise TEXT NOT NULL,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            value REAL NOT NULL,
            session_id INTEGER,
            PRIMARY KEY (user_id, exercise, kind, key)
        );
        CREATE TABLE gym_undo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            at TEXT NOT NULL,
            undone INTEGER NOT NULL DEFAULT 0
        );
        """
)


def add_weights(conn: sqlite3.Connection) -> None:
    from tasks.gym import weight

    weight.create_tables(conn)


def add_muscles(conn: sqlite3.Connection) -> None:
    from tasks.gym import insights

    insights.create_tables(conn)


def add_pain(conn: sqlite3.Connection) -> None:
    from tasks.gym import pain

    pain.create_tables(conn)


def add_plans(conn: sqlite3.Connection) -> None:
    """19 Oct: a plan a version (tasks/gym/plans.py)."""
    from tasks.gym import plans

    plans.add_tables(conn)


MIGRATIONS = [create_tables, add_weights, add_muscles, add_pain, add_plans]  # appended, never in between


def _sets_json(sets) -> str:
    return json.dumps([{"set_type": each.set_type, "purpose": each.purpose, "category": each.category, "low": each.low, "high": each.high} for each in sets])


def _sets_of(text: str) -> tuple[PlannedSet, ...]:
    return tuple(PlannedSet(**each) for each in json.loads(text or "[]"))


# --- the plan --------------------------------------------------------------------------------------------------------
def db_plan(conn: sqlite3.Connection, user_id: int) -> list[Workout]:
    """The active plan's workouts (tasks/gym/plans.py): none with no plan active."""
    workouts = conn.execute(
        "SELECT id, name FROM gym_workouts WHERE user_id = ? AND removed_at IS NULL AND plan_id = "
        "(SELECT id FROM gym_plans WHERE user_id = ? AND active = 1 AND removed_at IS NULL) ORDER BY position, id",
        (user_id, user_id),
    ).fetchall()
    found = []
    for workout_id, name in workouts:
        rows = conn.execute("SELECT id, name, kind, step, sets FROM gym_exercises WHERE workout_id = ? AND removed_at IS NULL ORDER BY position, id", (workout_id,)).fetchall()
        found.append(Workout(name, tuple(Exercise(row[1], _sets_of(row[4]), row[2], row[3], row[0]) for row in rows), workout_id))
    return found


def db_replace_plan(conn: sqlite3.Connection, user_id: int, workouts: list[Workout], now: datetime, name: str = "", split: str = "", weeks: int | None = None) -> list[int]:
    """A new plan, active, in place of the one that was (kept, inactive, to switch back to: tasks/gym/plans.py);
    the queue starts at its first workout."""
    from tasks.gym import plans

    from core import day as days

    plan_id = plans.db_add(conn, user_id, name or plans.plan_name(days.day_of(now), split, weeks), split, weeks, now)
    ids = []
    for position, workout in enumerate(workouts):
        workout_id = conn.execute("INSERT INTO gym_workouts (user_id, name, position, plan_id) VALUES (?, ?, ?, ?)", (user_id, workout.name, position, plan_id)).lastrowid
        ids.append(workout_id)
        for order, exercise in enumerate(workout.exercises):
            conn.execute(
                "INSERT INTO gym_exercises (user_id, workout_id, position, name, kind, step, sets) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, workout_id, order, exercise.name, exercise.kind, exercise.step, _sets_json(exercise.sets)),
            )
    db_set_queue(conn, user_id, ids, now)
    return ids


def db_set_exercise(conn: sqlite3.Connection, exercise_id: int, name: str, kind: str, step: float | None, sets) -> None:
    conn.execute("UPDATE gym_exercises SET name = ?, kind = ?, step = ?, sets = ? WHERE id = ?", (name, kind, step, _sets_json(sets), exercise_id))


def db_add_exercise(conn: sqlite3.Connection, user_id: int, workout_id: int, position: int, exercise: Exercise) -> int:
    conn.execute("UPDATE gym_exercises SET position = position + 1 WHERE workout_id = ? AND position >= ? AND removed_at IS NULL", (workout_id, position))
    return conn.execute(
        "INSERT INTO gym_exercises (user_id, workout_id, position, name, kind, step, sets) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, workout_id, position, exercise.name, exercise.kind, exercise.step, _sets_json(exercise.sets)),
    ).lastrowid


def db_remove_exercise(conn: sqlite3.Connection, exercise_id: int, now: datetime) -> None:
    conn.execute("UPDATE gym_exercises SET removed_at = ? WHERE id = ?", (now.isoformat(), exercise_id))


def db_unremove_exercise(conn: sqlite3.Connection, exercise_id: int) -> None:
    conn.execute("UPDATE gym_exercises SET removed_at = NULL WHERE id = ?", (exercise_id,))


# --- the queue and the target ----------------------------------------------------------------------------------------
def db_queue(conn: sqlite3.Connection, user_id: int) -> list[int]:
    row = conn.execute("SELECT queue FROM gym_state WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else []


def db_set_queue(conn: sqlite3.Connection, user_id: int, queue: list[int], now: datetime) -> None:
    conn.execute(
        "INSERT INTO gym_state (user_id, queue, updated_at) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET queue = excluded.queue, updated_at = excluded.updated_at",
        (user_id, json.dumps(queue), now.isoformat()),
    )


def db_target(conn: sqlite3.Connection, user_id: int) -> int | None:
    row = conn.execute("SELECT target_per_week FROM gym_state WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def db_set_target(conn: sqlite3.Connection, user_id: int, target: int | None, now: datetime) -> None:
    conn.execute(
        "INSERT INTO gym_state (user_id, target_per_week, updated_at) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET target_per_week = excluded.target_per_week, updated_at = excluded.updated_at",
        (user_id, target, now.isoformat()),
    )


# --- sessions, sets, notes ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Session:
    id: int
    user_id: int
    workout_id: int | None
    name: str
    day: date
    number: int | None
    status: str  # open, finished, off_plan, not_done
    source: str
    off_plan: str | None
    channel_id: int | None
    message_id: int | None


OPEN, FINISHED, OFF_PLAN, NOT_DONE = "open", "finished", "off_plan", "not_done"
_SESSION = "id, user_id, workout_id, name, day, number, status, source, off_plan, channel_id, message_id"


def _session(row) -> Session:
    return Session(row[0], row[1], row[2], row[3], date.fromisoformat(row[4]), row[5], row[6], row[7], row[8], row[9], row[10])


def db_add_session(conn: sqlite3.Connection, user_id: int, workout_id: int | None, name: str, day: date, status: str, now: datetime, source: str = "live", off_plan: str | None = None) -> int:
    number = None
    if workout_id is not None or status != OFF_PLAN:
        number = 1 + conn.execute("SELECT COUNT(*) FROM gym_sessions WHERE user_id = ? AND lower(name) = lower(?) AND status IN (?, ?, ?)", (user_id, name, FINISHED, OPEN, OFF_PLAN)).fetchone()[0]
    return conn.execute(
        "INSERT INTO gym_sessions (user_id, workout_id, name, day, number, status, source, off_plan, started_at, finished_at, plan_id) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, (SELECT id FROM gym_plans WHERE user_id = ? AND active = 1 AND removed_at IS NULL))",
        (user_id, workout_id, name, day.isoformat(), number, status, source, off_plan, now.isoformat(), None if status == OPEN else now.isoformat(), user_id),
    ).lastrowid


def db_session(conn: sqlite3.Connection, session_id: int) -> Session | None:
    row = conn.execute(f"SELECT {_SESSION} FROM gym_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session(row) if row else None


def db_open_session(conn: sqlite3.Connection, user_id: int) -> Session | None:
    row = conn.execute(f"SELECT {_SESSION} FROM gym_sessions WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT 1", (user_id, OPEN)).fetchone()
    return _session(row) if row else None


def db_session_on(conn: sqlite3.Connection, user_id: int, workout_id: int | None, day: date) -> Session | None:
    """A session of that workout on that day (for words that describe one logged by buttons too)."""
    row = conn.execute(f"SELECT {_SESSION} FROM gym_sessions WHERE user_id = ? AND workout_id IS ? AND day = ? AND status IN (?, ?) ORDER BY id DESC LIMIT 1",
                       (user_id, workout_id, day.isoformat(), OPEN, FINISHED)).fetchone()
    return _session(row) if row else None


def db_sessions(conn: sqlite3.Connection, user_id: int, since: date | None = None) -> list[Session]:
    rows = conn.execute(f"SELECT {_SESSION} FROM gym_sessions WHERE user_id = ? AND day >= ? AND status IN (?, ?, ?) ORDER BY day, id",
                        (user_id, (since or date(1900, 1, 1)).isoformat(), FINISHED, OPEN, OFF_PLAN)).fetchall()
    return [_session(row) for row in rows]


def db_set_status(conn: sqlite3.Connection, session_id: int, status: str, now: datetime | None) -> None:
    conn.execute("UPDATE gym_sessions SET status = ?, finished_at = ? WHERE id = ?", (status, now.isoformat() if now else None, session_id))


def db_placed(conn: sqlite3.Connection, session_id: int, channel_id: int, message_id: int) -> None:
    conn.execute("UPDATE gym_sessions SET channel_id = ?, message_id = ? WHERE id = ?", (channel_id, message_id, session_id))


def db_session_of_message(conn: sqlite3.Connection, message_id: int) -> Session | None:
    row = conn.execute(f"SELECT {_SESSION} FROM gym_sessions WHERE message_id = ?", (message_id,)).fetchone()
    return _session(row) if row else None


def db_swaps(conn: sqlite3.Connection, session_id: int) -> dict[str, str]:
    """Today's swaps in a session: {exercise in the plan (lower case): the one done instead}."""
    row = conn.execute("SELECT swaps FROM gym_sessions WHERE id = ?", (session_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def db_set_swaps(conn: sqlite3.Connection, session_id: int, swaps: dict[str, str]) -> None:
    conn.execute("UPDATE gym_sessions SET swaps = ? WHERE id = ?", (json.dumps(swaps), session_id))


def db_delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM gym_sets WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM gym_notes WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM gym_sessions WHERE id = ?", (session_id,))


_SET = "id, exercise, set_type, purpose, category, low, high, reps, weight, per_hand, position"


def _done(row) -> DoneSet:
    return DoneSet(row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], bool(row[9]), row[10], row[0])


def db_add_sets(conn: sqlite3.Connection, user_id: int, session_id: int, sets: list[DoneSet]) -> list[int]:
    return [
        conn.execute(
            "INSERT INTO gym_sets (user_id, session_id, exercise, position, set_type, purpose, category, low, high, reps, weight, per_hand) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, session_id, each.exercise, each.position, each.set_type, each.purpose, each.category, each.low, each.high, each.reps, each.weight, int(each.per_hand)),
        ).lastrowid
        for each in sets
    ]


def db_sets(conn: sqlite3.Connection, session_id: int) -> list[DoneSet]:
    return [_done(row) for row in conn.execute(f"SELECT {_SET} FROM gym_sets WHERE session_id = ? ORDER BY position, id", (session_id,))]


def db_delete_sets(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.executemany("DELETE FROM gym_sets WHERE id = ?", [(each,) for each in ids])


def db_exercise_history(conn: sqlite3.Connection, user_id: int, names: list[str], before_session: int | None = None) -> list[tuple[Session, list[DoneSet]]]:
    """Every session with a set of one of these names (as written then), oldest first, with those sets."""
    lowered = [each.lower() for each in names]
    marks = ",".join("?" * len(lowered))
    rows = conn.execute(
        f"SELECT DISTINCT session_id FROM gym_sets WHERE user_id = ? AND lower(exercise) IN ({marks}) AND reps IS NOT NULL", (user_id, *lowered)
    ).fetchall()
    found = []
    for (session_id,) in rows:
        if before_session is not None and session_id == before_session:
            continue
        session = db_session(conn, session_id)
        if session is None:
            continue
        sets = [each for each in db_sets(conn, session_id) if each.exercise.lower() in lowered]
        found.append((session, sets))
    return sorted(found, key=lambda pair: (pair[0].day, pair[0].id))


def db_all_sets(conn: sqlite3.Connection, user_id: int, before_session: int | None = None) -> list[DoneSet]:
    rows = conn.execute(f"SELECT {_SET} FROM gym_sets WHERE user_id = ? AND reps IS NOT NULL AND session_id IS NOT ?", (user_id, before_session)).fetchall()
    return [_done(row) for row in rows]


def db_add_note(conn: sqlite3.Connection, user_id: int, session_id: int, note: Note) -> int:
    return conn.execute(
        "INSERT INTO gym_notes (user_id, session_id, exercise, text, pain, target_low, target_high, body_part) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, session_id, note.exercise, note.text, int(note.pain), note.target_low, note.target_high, (note.body_part or "").strip().lower()[:40]),
    ).lastrowid


def db_notes(conn: sqlite3.Connection, session_id: int) -> list[Note]:
    return [Note(row[0], row[1], bool(row[2]), row[3], row[4], row[5]) for row in conn.execute("SELECT exercise, text, pain, target_low, target_high, body_part FROM gym_notes WHERE session_id = ? ORDER BY id", (session_id,))]


def db_exercise_notes(conn: sqlite3.Connection, user_id: int, names: list[str]) -> list[tuple[date, Note]]:
    lowered = [each.lower() for each in names]
    marks = ",".join("?" * len(lowered))
    rows = conn.execute(
        f"SELECT s.day, n.exercise, n.text, n.pain, n.target_low, n.target_high, n.body_part FROM gym_notes n JOIN gym_sessions s ON s.id = n.session_id "
        f"WHERE n.user_id = ? AND lower(n.exercise) IN ({marks}) ORDER BY s.day, n.id", (user_id, *lowered),
    ).fetchall()
    return [(date.fromisoformat(row[0]), Note(row[1], row[2], bool(row[3]), row[4], row[5], row[6] or "")) for row in rows]


def db_delete_notes(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.executemany("DELETE FROM gym_notes WHERE id = ?", [(each,) for each in ids])


# --- personal bests ------------------------------------------------------------------------------------------------------
def db_bests(conn: sqlite3.Connection, user_id: int) -> dict[tuple[str, str, str], float]:
    return {(row[0], row[1], row[2]): row[3] for row in conn.execute("SELECT exercise, kind, key, value FROM gym_bests WHERE user_id = ?", (user_id,))}


def db_put_bests(conn: sqlite3.Connection, user_id: int, found: dict[tuple[str, str, str], float], session_id: int | None) -> None:
    conn.executemany(
        "INSERT INTO gym_bests (user_id, exercise, kind, key, value, session_id) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, exercise, kind, key) DO UPDATE SET value = MAX(value, excluded.value), session_id = CASE WHEN excluded.value > value THEN excluded.session_id ELSE session_id END",
        [(user_id, name, kind, key, value, session_id) for (name, kind, key), value in found.items()],
    )


def db_rebuild_bests(conn: sqlite3.Connection, user_id: int) -> None:
    """Every best worked out again from every set (after an undo)."""
    from tasks.gym import rules

    conn.execute("DELETE FROM gym_bests WHERE user_id = ?", (user_id,))
    db_put_bests(conn, user_id, rules.bests(db_all_sets(conn, user_id)), None)


# --- undo -------------------------------------------------------------------------------------------------------------------
def db_remember(conn: sqlite3.Connection, user_id: int, kind: str, payload: dict, now: datetime) -> int:
    return conn.execute("INSERT INTO gym_undo (user_id, kind, payload, at) VALUES (?, ?, ?, ?)", (user_id, kind, json.dumps(payload), now.isoformat())).lastrowid


def db_undo_of(conn: sqlite3.Connection, undo_id: int) -> tuple[int, str, dict] | None:
    row = conn.execute("SELECT user_id, kind, payload FROM gym_undo WHERE id = ? AND undone = 0", (undo_id,)).fetchone()
    return (row[0], row[1], json.loads(row[2])) if row else None


def db_last_undo(conn: sqlite3.Connection, user_id: int) -> int | None:
    row = conn.execute("SELECT id FROM gym_undo WHERE user_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return row[0] if row else None


def db_undone(conn: sqlite3.Connection, undo_id: int) -> None:
    conn.execute("UPDATE gym_undo SET undone = 1 WHERE id = ?", (undo_id,))


async def plan(user_id: int) -> list[Workout]:
    return await database.run(db_plan, user_id)
