import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from core import clock, config, database, design
from core import day as days
from core.actions import Choice, Proposal, Question, Request
from core.errors import UserError
from tasks.gym import rules

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The gym's plans, one version per upload (Alex, 19 Oct). Each spreadsheet
# imported is a plan of its own, named "2026-10-19 — Upper/Lower 4-week": the
# day it came, its split (Claude reads it from the workouts' names, with the
# words of the logbook: tasks/gym/importer.py) and its weeks of data (Python
# counts them). One is active: the rotation, the workout card and the
# suggestions are its. Switching (“switch to the October plan”, “go back to
# the previous plan”) and deleting are cards, as every change is; the log is
# never touched by either: each session keeps the plan that was active then.
#
# The database is where a plan is kept (gym_plans, its workouts gym_workouts
# with their plan_id). As Alex asked, each is also written as JSON to
# data/gym/plans/<day>.json (name, uploaded, active, exercises), rewritten
# whenever which is active changes and deleted with the plan: a copy to read,
# never read back.
# ---------------------------------------------------------------------------
ICON = rules.ICON


@dataclass(frozen=True)
class Plan:
    id: int
    user_id: int
    name: str
    uploaded: datetime
    active: bool
    split: str = ""
    weeks: int | None = None
    file: str = ""


# --- pure ------------------------------------------------------------------------------------------------------------
def plan_name(day: date, split: str, weeks: int | None) -> str:
    """ "2026-10-19 — Upper/Lower 4-week"; with no weeks of data, "2026-10-19 — Upper/Lower"."""
    split = " ".join(str(split or "").split()) or "Gym plan"
    return f"{day.isoformat()} — {split}" + (f" {weeks}-week" if weeks else "")


def weeks_of(week_cells: list[str], days_done: list[date]) -> int | None:
    """How many weeks of data: the largest week number the logbook says, else the dated sessions' span in weeks
    (rounded up); None with neither."""
    numbers = [int(found) for each in week_cells for found in re.findall(r"\d+", str(each))[:1]]
    if numbers:
        return max(numbers)
    if not days_done:
        return None
    span = (max(days_done) - min(days_done)).days + 1
    return max(1, -(-span // 7))


def split_of(names: list[str]) -> str:
    """For a plan kept before 19 Oct, with no Claude to read it: the workouts' names without a trailing number or
    letter, each once, in order ("Upper 1", "Lower 1", "Upper 2" -> "Upper/Lower"). Mechanical."""
    bases: list[str] = []
    for each in names:
        base = re.sub(r"(\s*\d+|\s+[A-Za-z])$", "", each.strip()) or each.strip()
        if base and base.lower() not in [one.lower() for one in bases]:
            bases.append(base)
    if len(bases) == 1:
        return f"{bases[0]} {len(names)}-day"
    return "/".join(bases)


def _tokens(text: str) -> set[str]:
    return {each for each in re.split(r"[^0-9a-z]+", text.lower()) if each}


def plan_tokens(plan: Plan) -> set[str]:
    """What a plan can be called by: the words and numbers of its name, and its upload's month, in full and short."""
    when = days.day_of(plan.uploaded)
    return _tokens(plan.name) | {f"{when:%B}".lower(), f"{when:%b}".lower()}


def matches(plans: list[Plan], words: str) -> list[Plan]:
    """The plans the words fit best (“the October plan”, “the upper lower one”, “2026-10-19”): most of the words'
    tokens among a plan's own; none when no token fits any. Most recent first among equals."""
    wanted = _tokens(words)
    scored = [(len(wanted & plan_tokens(each)), each) for each in plans]
    best = max((score for score, _ in scored), default=0)
    if best == 0:
        return []
    return sorted((each for score, each in scored if score == best), key=lambda each: each.uploaded, reverse=True)


def previous_of(plans: list[Plan]) -> Plan | None:
    """The plan before the active one: the most recent other uploaded before it, else the most recent other."""
    active = next((each for each in plans if each.active), None)
    others = sorted((each for each in plans if not each.active), key=lambda each: each.uploaded, reverse=True)
    if active is not None:
        before = [each for each in others if each.uploaded < active.uploaded]
        if before:
            return before[0]
    return others[0] if others else None


def summary_line(exercises: int, workouts: int, weeks: int | None) -> str:
    """ "24 exercises across 4 days, 4 weeks." """
    said = f"{exercises} exercise{'' if exercises == 1 else 's'} across {workouts} day{'' if workouts == 1 else 's'}"
    return said + (f", {weeks} week{'' if weeks == 1 else 's'}." if weeks else ".")


def active_line(name: str) -> str:
    return f"✅ {name} is now your active plan."


# --- the store ---------------------------------------------------------------------------------------------------------
def add_tables(conn: sqlite3.Connection) -> None:
    """19 Oct: a plan a version (gym_plans); each workout of a plan, and each session the plan active then. The
    plan kept so far becomes the first, named from its workouts and log."""
    conn.execute(
        """
        CREATE TABLE gym_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            split TEXT NOT NULL DEFAULT '',
            weeks INTEGER,
            uploaded_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            file TEXT NOT NULL DEFAULT '',
            removed_at TEXT
        )
        """
    )
    conn.execute("ALTER TABLE gym_workouts ADD COLUMN plan_id INTEGER REFERENCES gym_plans(id)")
    conn.execute("ALTER TABLE gym_sessions ADD COLUMN plan_id INTEGER REFERENCES gym_plans(id)")
    now = clock.now()
    for (user_id,) in conn.execute("SELECT DISTINCT user_id FROM gym_workouts WHERE removed_at IS NULL").fetchall():
        names = [row[0] for row in conn.execute("SELECT name FROM gym_workouts WHERE user_id = ? AND removed_at IS NULL ORDER BY position, id", (user_id,))]
        done = [date.fromisoformat(row[0]) for row in conn.execute("SELECT day FROM gym_sessions WHERE user_id = ? AND source = 'import'", (user_id,))]
        split, weeks = split_of(names), weeks_of([], done)
        plan_id = conn.execute(
            "INSERT INTO gym_plans (user_id, name, split, weeks, uploaded_at, active) VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, plan_name(days.day_of(now), split, weeks), split, weeks, now.isoformat()),
        ).lastrowid
        conn.execute("UPDATE gym_workouts SET plan_id = ? WHERE user_id = ? AND removed_at IS NULL", (plan_id, user_id))
        conn.execute("UPDATE gym_sessions SET plan_id = ? WHERE user_id = ?", (plan_id, user_id))


_COLUMNS = "id, user_id, name, uploaded_at, active, split, weeks, file"


def _plan(row) -> Plan:
    return Plan(row[0], row[1], row[2], datetime.fromisoformat(row[3]), bool(row[4]), row[5], row[6], row[7])


def db_plans(conn: sqlite3.Connection, user_id: int) -> list[Plan]:
    """Every plan kept, most recent first."""
    return [_plan(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM gym_plans WHERE user_id = ? AND removed_at IS NULL ORDER BY uploaded_at DESC, id DESC", (user_id,))]


def db_get(conn: sqlite3.Connection, plan_id: int) -> Plan | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM gym_plans WHERE id = ? AND removed_at IS NULL", (plan_id,)).fetchone()
    return _plan(row) if row else None


def db_active_id(conn: sqlite3.Connection, user_id: int) -> int | None:
    row = conn.execute("SELECT id FROM gym_plans WHERE user_id = ? AND active = 1 AND removed_at IS NULL", (user_id,)).fetchone()
    return row[0] if row else None


def _file_for(conn: sqlite3.Connection, user_id: int, day: date) -> str:
    """ "2026-10-19.json"; a second on the same day "2026-10-19-2.json"."""
    taken = {row[0] for row in conn.execute("SELECT file FROM gym_plans WHERE user_id = ?", (user_id,))}
    name, number = f"{day.isoformat()}.json", 2
    while name in taken:
        name, number = f"{day.isoformat()}-{number}.json", number + 1
    return name


def db_add(conn: sqlite3.Connection, user_id: int, name: str, split: str, weeks: int | None, now: datetime) -> int:
    """A new plan, active; whichever was active before is not."""
    conn.execute("UPDATE gym_plans SET active = 0 WHERE user_id = ?", (user_id,))
    return conn.execute(
        "INSERT INTO gym_plans (user_id, name, split, weeks, uploaded_at, active, file) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (user_id, name, split, weeks, now.isoformat(), _file_for(conn, user_id, days.day_of(now))),
    ).lastrowid


def db_workout_ids(conn: sqlite3.Connection, plan_id: int) -> list[int]:
    return [row[0] for row in conn.execute("SELECT id FROM gym_workouts WHERE plan_id = ? AND removed_at IS NULL ORDER BY position, id", (plan_id,))]


def db_activate(conn: sqlite3.Connection, user_id: int, plan_id: int | None, now: datetime) -> None:
    """That plan active and the rest not; the rotation starts at its first workout. None: no plan is active."""
    from tasks.gym import store

    conn.execute("UPDATE gym_plans SET active = 0 WHERE user_id = ?", (user_id,))
    if plan_id is not None:
        conn.execute("UPDATE gym_plans SET active = 1 WHERE id = ? AND user_id = ?", (plan_id, user_id))
    store.db_set_queue(conn, user_id, db_workout_ids(conn, plan_id) if plan_id is not None else [], now)


def db_remove(conn: sqlite3.Connection, user_id: int, plan_id: int, now: datetime) -> int | None:
    """The plan gone (its workouts too; the log keeps every session). If it was active, the most recent left is
    active now, or none. Returns the one active after."""
    was_active = db_active_id(conn, user_id) == plan_id
    conn.execute("UPDATE gym_plans SET removed_at = ?, active = 0 WHERE id = ?", (now.isoformat(), plan_id))
    conn.execute("UPDATE gym_workouts SET removed_at = ? WHERE plan_id = ? AND removed_at IS NULL", (now.isoformat(), plan_id))
    if not was_active:
        return db_active_id(conn, user_id)
    left = db_plans(conn, user_id)
    db_activate(conn, user_id, left[0].id if left else None, now)
    return left[0].id if left else None


def db_counts(conn: sqlite3.Connection, plan_id: int) -> tuple[int, int]:
    """(exercises, workouts) of a plan."""
    workouts = db_workout_ids(conn, plan_id)
    if not workouts:
        return 0, 0
    marks = ", ".join("?" for _ in workouts)
    exercises = conn.execute(f"SELECT COUNT(*) FROM gym_exercises WHERE workout_id IN ({marks}) AND removed_at IS NULL", workouts).fetchone()[0]
    return exercises, len(workouts)


async def every(user_id: int) -> list[Plan]:
    return await database.run(db_plans, user_id)


# --- the JSON copies in data/gym/plans ---------------------------------------------------------------------------------
def folder():
    """data/gym/plans (the dev bot's data/dev-gym/plans): read when used, so a test's data folder is the one."""
    return config.DATA_DIR / ("dev-gym" if config.DEV_DATABASE else "gym") / "plans"


def db_copy(conn: sqlite3.Connection, plan: Plan) -> dict:
    """What a plan's file holds: its name, when it came, whether it is active, and its exercises as parsed."""
    from tasks.gym import store

    exercises = []
    for workout_id in db_workout_ids(conn, plan.id):
        workout = conn.execute("SELECT name FROM gym_workouts WHERE id = ?", (workout_id,)).fetchone()[0]
        for row in conn.execute("SELECT name, kind, step, sets FROM gym_exercises WHERE workout_id = ? AND removed_at IS NULL ORDER BY position, id", (workout_id,)):
            exercises.append({"workout": workout, "name": row[0], "kind": row[1], "step": row[2], "sets": json.loads(store._sets_json(store._sets_of(row[3])))})
    return {"name": plan.name, "uploaded": plan.uploaded.isoformat(), "active": plan.active, "exercises": exercises}


async def write_copies(user_id: int, gone: tuple[str, ...] = ()) -> None:
    """Every plan's file as the plans now stand, and the files of those deleted taken away. Never raises: a copy
    that can't be written is logged, and the plan in the database is what counts."""
    import asyncio

    try:
        plans = await every(user_id)
        copies = {each.file: await database.run(db_copy, each) for each in plans if each.file}

        def write() -> None:
            where = folder()
            where.mkdir(parents=True, exist_ok=True)
            for name, content in copies.items():
                (where / name).write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            for name in gone:
                if name and name not in copies:
                    (where / name).unlink(missing_ok=True)

        await asyncio.to_thread(write)
    except Exception:
        log.exception("Gym: the plans' copies in data/gym/plans could not be written")


# --- list, switch, delete ----------------------------------------------------------------------------------------------------
def _uploaded(plan: Plan) -> str:
    when = days.day_of(plan.uploaded)
    return f"{when:%a} {when.day} {when:%b} {when.year}"


async def list_said(request: Request, data: dict, guessed: frozenset) -> str:
    """ "show my gym plans": every plan, most recent first, with when it came and whether it is active."""
    found = await every(request.user.id)
    if not found:
        return f"{ICON} You have no gym plans yet: send your logbook (a CSV or XLSX) in #gym to import one."
    lines = [f"{ICON} **Your gym plans** · {len(found)}"]
    lines += [f"**{each.name}** · uploaded {_uploaded(each)}" + (" · ✅ active" if each.active else "") for each in found]
    return "\n".join(lines)


async def _which(request: Request, data: dict) -> tuple[Plan | None, list[Plan], list[Plan]]:
    """The plan meant, or the plans it could be: (one, candidates, every)."""
    found = await every(request.user.id)
    if not found:
        raise UserError(f"{ICON} You have no gym plans yet.")
    if data.get("previous"):
        before = previous_of(found)
        if before is None:
            raise UserError(f"{ICON} There is no plan before this one.")
        return before, [before], found
    said = str(data.get("plan") or "").strip()
    if not said:
        raise UserError(f"{ICON} Which plan? " + " · ".join(f"**{each.name}**" for each in found[:4]))
    fits = matches(found, said)
    if not fits:
        raise UserError(f"{ICON} No plan fits “{said}”. Your plans: " + " · ".join(f"**{each.name}**" for each in found[:4]))
    return (fits[0] if len(fits) == 1 else None), fits, found


def _ask(fits: list[Plan], data: dict, verb: str) -> Question:
    return Question(f"Which plan to {verb}?", tuple(Choice(each.name[:80], {**data, "plan": each.name, "previous": False}, ("plan",)) for each in fits[:4]))


async def switch_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "switch to the October plan", "go back to the previous plan", "use the upper lower one"."""
    one, fits, found = await _which(request, data)
    if one is None:
        return Proposal(lines=(f"{len(fits)} plans fit “{data.get('plan')}”",), data=dict(data), kind="change", question=_ask(fits, data, "switch to"))
    if one.active:
        raise UserError(f"{ICON} **{one.name}** is your active plan already.")
    active = next((each for each in found if each.active), None)
    lines = [f"**{one.name}** → active"]
    if active is not None:
        lines.append(design.small(f"in place of {active.name}"))
    lines.append(design.small("the rotation starts at its first workout · your log stays as it is"))
    return Proposal(lines=tuple(lines), data={"id": one.id, "name": one.name}, kind="change")


async def switch_save(request: Request, data: dict) -> str:
    from tasks.gym import session

    plan = await database.run(db_get, int(data["id"]))
    if plan is None:
        raise UserError(f"{ICON} That plan has gone.")
    await database.run(db_activate, request.user.id, plan.id, clock.now())
    exercises, workouts = await database.run(db_counts, plan.id)
    await write_copies(request.user.id)
    session.changed(request.user.id)
    return f"{active_line(plan.name)}\n{summary_line(exercises, workouts, plan.weeks)}"


async def switch_check(request: Request, data: dict) -> str:
    return "" if await database.run(db_active_id, request.user.id) == int(data["id"]) else "the plan is not active"


async def delete_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "delete the October plan": which one, then a card to delete it."""
    one, fits, found = await _which(request, data)
    if one is None:
        return Proposal(lines=(f"{len(fits)} plans fit “{data.get('plan')}”",), data=dict(data), kind="remove", question=_ask(fits, data, "delete"))
    lines = [f"**{one.name}** → deleted", design.small("your log stays as it is")]
    if one.active:
        left = [each for each in found if each.id != one.id]
        lines.append(design.small(f"{left[0].name} becomes active" if left else "no plan will be active"))
    return Proposal(lines=tuple(lines), data={"id": one.id, "name": one.name, "file": one.file}, kind="remove", confirm_label="Delete")


async def delete_save(request: Request, data: dict) -> str:
    from tasks.gym import session

    active_after = await database.run(db_remove, request.user.id, int(data["id"]), clock.now())
    await write_copies(request.user.id, gone=(str(data.get("file") or ""),))
    session.changed(request.user.id)
    said = f"🗑️ Deleted **{data['name']}**"
    if active_after is not None:
        plan = await database.run(db_get, active_after)
        said += f" · active: **{plan.name}**" if plan is not None else ""
    else:
        said += " · no plan is active now"
    return said


async def delete_check(request: Request, data: dict) -> str:
    return "the plan is still there" if await database.run(db_get, int(data["id"])) is not None else ""
