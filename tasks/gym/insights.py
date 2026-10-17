import sqlite3
from collections import Counter
from datetime import date, timedelta

from core import database, llm
from tasks.gym import rules, store

# ---------------------------------------------------------------------------
# Training insights, from the log (imported history included). Pure but for
# reading the log and, for an exercise the table below doesn't know, one small
# request to Claude for its muscle groups (kept, so it is asked once).
#
#   weekly working sets per muscle group
#   imbalance   pushing against pulling over 4 weeks, one half again the other
#   stall       an exercise's top set no heavier and no more reps for 3 sessions
#   lighter     two stalls or more: a lighter week is suggested
# ---------------------------------------------------------------------------
PUSH, PULL, LEGS, CORE = "push", "pull", "legs", "core"
# A config table: what an exercise works, by the words of its name (the first that fits). Claude for the rest
GROUPS = (
    ("bench", ("chest", "triceps")), ("incline", ("chest", "shoulders")), ("chest press", ("chest",)), ("fly", ("chest",)),
    ("dip", ("chest", "triceps")), ("push", ("chest", "triceps")), ("overhead press", ("shoulders", "triceps")),
    ("shoulder press", ("shoulders",)), ("lateral raise", ("shoulders",)), ("tricep", ("triceps",)),
    ("pulldown", ("back", "biceps")), ("pull-up", ("back", "biceps")), ("pull up", ("back", "biceps")), ("chin", ("back", "biceps")),
    ("row", ("back",)), ("face pull", ("rear shoulders",)), ("curl", ("biceps",)),
    ("squat", ("quads", "glutes")), ("leg press", ("quads", "glutes")), ("lunge", ("quads", "glutes")), ("leg extension", ("quads",)),
    ("romanian deadlift", ("hamstrings", "glutes")), ("deadlift", ("hamstrings", "back")), ("leg curl", ("hamstrings",)),
    ("calf", ("calves",)), ("hip thrust", ("glutes",)), ("plank", ("core",)), ("crunch", ("core",)),
)
SIDE = {"chest": PUSH, "shoulders": PUSH, "triceps": PUSH, "back": PULL, "biceps": PULL, "rear shoulders": PULL,
        "quads": LEGS, "glutes": LEGS, "hamstrings": LEGS, "calves": LEGS, "core": CORE}
KNOWN = tuple(SIDE)
STALL_SESSIONS = 3
IMBALANCE = 1.5
TOOL, PURPOSE = "muscle_groups", "gym-muscles"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE gym_muscles (name TEXT PRIMARY KEY, groups TEXT NOT NULL)")


def groups_of(name: str, learned: dict[str, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    lowered = name.lower()
    if learned and lowered in learned:
        return learned[lowered]
    return next((found for words, found in GROUPS if words in lowered), ())


async def learn(names: list[str]) -> dict[str, tuple[str, ...]]:
    """The muscle groups of exercises the table doesn't know, asked once and kept."""
    kept = await database.run(lambda conn: {row[0]: tuple(row[1].split(",")) for row in conn.execute("SELECT name, groups FROM gym_muscles")})
    unknown = sorted({each.lower() for each in names if not groups_of(each) and each.lower() not in kept})
    if not unknown:
        return kept
    tool = {"name": TOOL, "description": "Say which muscle groups each exercise works.", "input_schema": {"type": "object", "properties": {"exercises": {"type": "array", "items": {
        "type": "object", "properties": {"index": {"type": "integer"}, "groups": {"type": "array", "items": {"type": "string", "enum": list(KNOWN)}}}, "required": ["index", "groups"]}}}, "required": ["exercises"]}}
    called = await llm.call_tool([{"type": "text", "text": "Say which muscle groups each gym exercise mainly works, one to three of the list.", "cache_control": llm.CACHED}],
                                 "\n".join(f"{index}. {name}" for index, name in enumerate(unknown)), [tool], choice={"type": "tool", "name": TOOL}, purpose=PURPOSE, task=rules.TASK, max_tokens=800)
    raw = called[1] if called else {}
    found = {}
    for each in (raw or {}).get("exercises", []) if isinstance(raw, dict) else []:
        if isinstance(each, dict) and isinstance(each.get("index"), int) and 0 <= each["index"] < len(unknown):
            groups = tuple(group for group in each.get("groups") or [] if group in KNOWN)
            if groups:
                found[unknown[each["index"]]] = groups

    def keep(conn):
        conn.executemany("INSERT OR REPLACE INTO gym_muscles (name, groups) VALUES (?, ?)", [(name, ",".join(groups)) for name, groups in found.items()])

    await database.run(keep)
    return {**kept, **found}


# --- pure: the numbers ----------------------------------------------------------------------------------------------------
def weekly_sets(sessions: list[tuple[date, list[rules.DoneSet]]], monday: date, learned=None) -> Counter:
    """Working sets done each muscle group that week."""
    found: Counter = Counter()
    for day, sets in sessions:
        if monday <= day < monday + timedelta(days=7):
            for each in sets:
                if each.done and each.set_type == rules.WORKING:
                    for group in groups_of(each.exercise, learned):
                        found[group] += 1
    return found


def balance(sessions, today: date, learned=None) -> tuple[int, int]:
    """(pushing, pulling) working sets over the last 4 weeks."""
    since = today - timedelta(days=28)
    push = pull = 0
    for day, sets in sessions:
        if since < day <= today:
            for each in sets:
                if each.done and each.set_type == rules.WORKING:
                    sides = {SIDE.get(group) for group in groups_of(each.exercise, learned)}
                    push += PUSH in sides
                    pull += PULL in sides
    return push, pull


def imbalance(push: int, pull: int) -> str:
    if push and pull and push >= pull * IMBALANCE:
        return f"pushing {push} sets against pulling {pull} over 4 weeks"
    if push and pull and pull >= push * IMBALANCE:
        return f"pulling {pull} sets against pushing {push} over 4 weeks"
    return ""


def stalls(history: dict[str, list[tuple[date, list[rules.DoneSet]]]]) -> list[str]:
    """Exercises whose top set has not gone up (weight, then reps) for the last 3 sessions."""
    found = []
    for name, sessions in history.items():
        tops = [rules.top_set(sets) for _, sets in sessions]
        tops = [(each.weight, each.reps) for each in tops if each is not None]
        if len(tops) >= STALL_SESSIONS + 1 and max(tops[-STALL_SESSIONS:]) <= tops[-STALL_SESSIONS - 1]:
            found.append(name)
    return found


def summary_line(push: int, pull: int, stalled: list[str]) -> str:
    """The week's one line: an imbalance, stalls, and a lighter week after 2 or more."""
    said = [each for each in (imbalance(push, pull),) if each]
    if stalled:
        said.append(f"stalled: {', '.join(stalled[:3])}" + (f" +{len(stalled) - 3}" if len(stalled) > 3 else ""))
    if len(stalled) >= 2:
        said.append("a lighter week could help")
    return " · ".join(said)


# --- reading the log --------------------------------------------------------------------------------------------------------
async def read(user_id: int) -> tuple[list[tuple[date, list[rules.DoneSet]]], dict[str, list]]:
    sessions = await database.run(store.db_sessions, user_id)
    every = []
    by_exercise: dict[str, list] = {}
    for session in sessions:
        sets = await database.run(store.db_sets, session.id)
        every.append((session.day, sets))
        for name in dict.fromkeys(each.exercise for each in sets if each.done):
            by_exercise.setdefault(name, []).append((session.day, [each for each in sets if each.exercise == name]))
    return every, by_exercise


async def week_line(user_id: int, today: date) -> str:
    every, by_exercise = await read(user_id)
    if not every:
        return ""
    learned = await learn(list(by_exercise))
    push, pull = balance(every, today, learned)
    return summary_line(push, pull, stalls(by_exercise))


async def answer(user_id: int, today: date) -> str:
    """ "how's my training going?": this week's sets by group, the balance, stalls."""
    every, by_exercise = await read(user_id)
    if not every:
        return f"{rules.ICON} Nothing logged yet."
    learned = await learn(list(by_exercise))
    monday = today - timedelta(days=today.weekday())
    sets = weekly_sets(every, monday, learned) or weekly_sets(every, monday - timedelta(days=7), learned)
    push, pull = balance(every, today, learned)
    stalled = stalls(by_exercise)
    lines = [f"{rules.ICON} **Training** · " + (", ".join(f"{group} {count}" for group, count in sets.most_common(6)) + " working sets this week" if sets else "no working sets this week")]
    lines.append(f"push {push} · pull {pull} over 4 weeks" + (f" · {imbalance(push, pull)}" if imbalance(push, pull) else " · balanced"))
    if stalled:
        lines.append(f"stalled 3 sessions: {', '.join(stalled)}" + (" · a lighter week could help" if len(stalled) >= 2 else ""))
    return "\n".join(lines)
