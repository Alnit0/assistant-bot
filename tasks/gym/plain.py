import json
import logging
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta

from core import cards, clock, config, database, design, grid, names, scheduler, timeinput
from core import day as days
from core.actions import BOOLEAN, INTEGER, ITEMS, NUMBER, TIME, Choice, Field, Proposal, Question, Request, Shown, State, flag
from core.cards import Card
from core.errors import UserError
from tasks.gym import importer, rules, session, store
from tasks.gym.rules import ICON, TASK, DoneSet, Exercise, Note, PlannedSet, Workout

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The gym in plain words. Claude says which action and hands over values
# (an exercise as the plan names it when it is clear, reps, a weight, per
# hand, a day as said, whether a note speaks of pain); Python matches every
# name to the plan (core/names.py), works out every date and every sum, and
# writes every word. Changes to the plan, an import and a described session
# are cards; starting, skipping and questions are done at once.
# ---------------------------------------------------------------------------
ONLY_FOR = (
    "The user's gym training: importing their gym plan or logbook (a spreadsheet or pasted rows), starting a "
    "workout (\"starting a workout\", \"gym now\", \"what's my workout?\", \"do Lower 2 instead\", \"extra session\"), "
    "skipping one (\"skip Upper 1\"), something else done instead (\"did a 30 min run instead\"), swapping an "
    "exercise (\"swap bench for dumbbell press today\"), changing the plan (\"make RDLs 6-10\", \"add face pulls "
    "to Upper 1\"), logging sets or a whole session in words, during or after (\"bench 20 for 15, 40 for 9, 40 for "
    "8\", \"did Upper 1 this morning: …\"), finishing (\"finish the workout\"), questions about their lifts "
    "(\"what did I do on bench last time?\", \"my notes on RDLs\", \"best leg press\", \"how's my bench going?\", "
    "\"sessions this month\", \"how's my training going?\"), pain or discomfort noted in workouts or the diary (\"any pain?\", "
    "\"pain history\"), a weekly target (\"aim for 3 a week\"), planning a session at a time (\"gym "
    "tomorrow 6pm\") and the user's gym plans, a version for each logbook imported: listing them (\"show my gym "
    "plans\"), switching (\"switch to the October plan\", \"go back to the previous plan\") and deleting one. Not general fitness questions (chat), not body weight or food, and not a reminder."
)
EXAMPLES = ("starting a workout", "bench 20 for 15, 40 for 9, 40 for 8", "how's my bench going?")
_EXERCISE = "The exercise as the user's plan names it, from the state, when it is clear which (\"laterals\" -> Lateral raise, \"RDLs\" -> Romanian deadlift); else exactly as said."
_DAY = "The day, exactly as the user said it (\"today\", \"this morning\" -> today, \"yesterday\", \"last Tuesday\"). Never work out a date. Leave out for today."


async def state(request: Request) -> State:
    plan = await store.plan(request.user.id)
    queue = session.queue_now(await database.run(store.db_queue, request.user.id), plan)
    lines = [f"next in turn: {queue[0].name}"] if queue else ["no plan yet"]
    for workout in plan:
        lines.append(f"{workout.name}: " + ", ".join(each.name for each in workout.exercises))
    open_ = await database.run(store.db_open_session, request.user.id)
    if open_ is not None:
        lines.append(f"(a session of {open_.name} is open, started {open_.day:%a})")
    from tasks.gym import plans

    kept = await plans.every(request.user.id)
    if kept:
        lines.append("plans kept: " + "; ".join(each.name + (" (active)" if each.active else "") for each in kept))
    return State("The user's gym plan (workouts in rotation order, each with its exercises)", tuple(lines), "no plan yet")


async def item_names(request: Request) -> list[str]:
    return [each.name for each in await store.plan(request.user.id)]


# --- import ----------------------------------------------------------------------------------------------------------------
async def tables_of(request: Request, data: dict) -> list[grid.Table]:
    """The tables sent: the files with the message, else pasted rows, else the open card's."""
    found = []
    for attachment in request.attachments:
        lower = attachment.name.lower()
        if lower.endswith((".csv", ".xlsx")) and attachment.fetch is not None:
            found += grid.from_file(attachment.name, await attachment.fetch())
    if not found and grid.looks_like_rows(request.text):
        found = grid.from_text("pasted rows", request.text)
    if not found and data.get("tables"):
        found = [grid.Table(each["name"], tuple(each["headings"]), tuple(tuple(row) for row in each["rows"])) for each in data["tables"]]
    return found


def _kept(found: importer.Imported) -> dict:
    from tasks.gym import plans

    return {
        "name": plans.plan_name(days.today(), found.split, found.weeks), "split": found.split, "weeks": found.weeks,
        "plan": [{"name": workout.name, "exercises": [{"name": each.name, "kind": each.kind, "sets": [asdict(one) for one in each.sets]} for each in workout.exercises]} for workout in found.plan],
        "sessions": [{"workout": each["workout"], "day": each["day"].isoformat(), "sets": [asdict(one) for one in each["sets"]], "notes": [asdict(one) for one in each["notes"]]} for each in found.sessions],
    }


async def import_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    previous = request.previous or {}
    tables = await tables_of(request, {**previous, **data})
    if not tables:
        raise UserError(f"{ICON} Send your logbook as a CSV or an XLSX, or paste its rows, to import your plan.")
    overrides = dict(previous.get("overrides") or {})
    for each in data.get("columns") or []:
        if each.get("heading") and each.get("field") in importer.FIELDS:
            overrides.setdefault("*", {})[str(each["heading"])] = each["field"]
    found = await importer.imported(tables, overrides)
    lines = importer.card_lines(found)
    keep = {"tables": [{"name": each.name, "headings": list(each.headings), "rows": [list(row) for row in each.rows]} for each in tables], "overrides": overrides, **_kept(found)}
    if found.problems or not found.plan:
        return Proposal(lines=tuple(lines), data=keep, warnings=tuple(found.problems or ["No workouts could be read"]), kind="new", can_save=False)
    question = None
    if found.unsure:
        heading = found.unsure[0].split("”")[0].lstrip("“")
        choices = tuple(Choice(label, {**keep, "columns": [{"heading": heading, "field": field_name}]}, ("columns",))
                        for label, field_name in (("Weight", "weight"), ("Purpose", "purpose"), ("Notes", "notes"), ("Not used", "none")))
        question = Question(f"I read {found.unsure[0]}: is that right? Pick what “{heading}” is.", choices)
    there = await store.plan(request.user.id)
    kind = "change" if there else "new"
    if there:
        lines.insert(0, design.small("your active plan now · the one before is kept, to switch back to, and your log stays as it is"))
    lines.insert(0, f"**{keep['name']}**")
    return Proposal(lines=tuple(lines), data=keep, kind=kind, question=question)


def _workouts_from(data: dict) -> list[Workout]:
    return [Workout(each["name"], tuple(Exercise(one["name"], tuple(PlannedSet(**set_) for set_ in one["sets"]), one.get("kind", "")) for one in each["exercises"])) for each in data["plan"]]


async def import_save(request: Request, data: dict) -> str:
    from tasks.gym import plans

    workouts = _workouts_from(data)
    now = clock.now()
    name = data.get("name") or plans.plan_name(days.today(), data.get("split", ""), data.get("weeks"))
    ids = await database.run(store.db_replace_plan, request.user.id, workouts, now, name, data.get("split", ""), data.get("weeks"))
    by_name = {workout.name.lower(): workout_id for workout, workout_id in zip(workouts, ids)}

    def keep_log(conn):
        last = None
        kept = {(row[0], row[1].lower()) for row in conn.execute("SELECT day, name FROM gym_sessions WHERE user_id = ?", (request.user.id,))}
        for each in data["sessions"]:
            workout_id = by_name.get(each["workout"].lower())
            if (each["day"], each["workout"].lower()) in kept:
                continue  # logged already (the same logbook sent again): the log has it once
            session_id = store.db_add_session(conn, request.user.id, workout_id, each["workout"], date.fromisoformat(each["day"]), store.FINISHED, now, "import")
            store.db_add_sets(conn, request.user.id, session_id, [DoneSet(**one) for one in each["sets"]])
            for note in each["notes"]:
                store.db_add_note(conn, request.user.id, session_id, Note(**note))
            last = workout_id
        store.db_rebuild_bests(conn, request.user.id)
        if last in ids:
            # The rotation goes on from the workout after the last one logged
            at = ids.index(last) + 1
            store.db_set_queue(conn, request.user.id, ids[at:] + ids[:at], now)

    await database.run(keep_log)
    await plans.write_copies(request.user.id)
    session.changed(request.user.id)
    nxt = await session.next_workout(request.user.id)
    exercises = sum(len(each.exercises) for each in workouts)
    small = f"{len(data['sessions'])} sessions in the log" + (f" · next: **{nxt.name}**" if nxt else "")
    return f"{plans.active_line(name)}\n{plans.summary_line(exercises, len(workouts), data.get('weeks'))}\n{design.small(small)}"


async def import_check(request: Request, data: dict) -> str:
    there = await store.plan(request.user.id)
    return "" if [each.name for each in there] == [each["name"] for each in data["plan"]] else "the plan is not as the card said"


# --- starting, skipping, off-plan ---------------------------------------------------------------------------------------------
async def _plan_or_say(request: Request) -> list[Workout]:
    plan = await store.plan(request.user.id)
    if not plan:
        raise UserError(f"{ICON} You have no gym plan yet: send your logbook (a CSV or XLSX), or paste its rows, to import it.")
    return plan


async def start(request: Request, data: dict, guessed: frozenset):
    """ "starting a workout", "gym now", "do Lower 2 instead", "extra session": the card in #gym."""
    plan = await _plan_or_say(request)
    workout = session.find_workout(plan, str(data["workout"])) if data.get("workout") else None
    started = await session.start(request.user.id, workout)
    line = f"{ICON} **{started.name}**" + (f" · session {started.number}" if started.number else "")
    if request.channel_id != session.gym_channel():
        line += " · its card is in #gym"
        return line
    return Shown(line)


async def skip(request: Request, data: dict, guessed: frozenset) -> str:
    plan = await _plan_or_say(request)
    workout = session.find_workout(plan, str(data["workout"])) if data.get("workout") else await session.next_workout(request.user.id)
    queue_before = await database.run(store.db_queue, request.user.id)
    order = await session.skip(request.user.id, workout)
    await database.run(store.db_remember, request.user.id, "queue", {"session": 0, "queue": queue_before}, clock.now())
    return f"{ICON} **{workout.name}** to the back · next: **{order[0].name}**"


async def off_plan(request: Request, data: dict, guessed: frozenset) -> str:
    what = " ".join(str(data.get("activity") or "").split())
    if not what:
        raise UserError(f"{ICON} What did you do instead?")
    day = _day(data.get("day"))
    session_id = await session.off_plan(request.user.id, what, day)
    await database.run(store.db_remember, request.user.id, "session", {"session": session_id, "queue": None}, clock.now())
    nxt = await session.next_workout(request.user.id)
    return f"{ICON} Off-plan · **{what[:1].upper() + what[1:]}** · {_day_text(day)}" + (f" · next is still **{nxt.name}**" if nxt else "")


def _day(said) -> date:
    today = days.today()
    if not said or str(said).strip().lower() in ("today", "this morning", "tonight", "this evening"):
        return today
    try:
        return timeinput.parse_past_date(str(said), today)
    except Exception:
        raise UserError(f"{ICON} “{said}” is not a day I can read.")


def _day_text(day: date) -> str:
    today = days.today()
    return "today" if day == today else "yesterday" if day == today - timedelta(days=1) else f"{day:%a} {day.day} {day:%b}"


async def finish(request: Request, data: dict, guessed: frozenset) -> str:
    open_ = await database.run(store.db_open_session, request.user.id)
    if open_ is None:
        raise UserError(f"{ICON} No workout is open.")
    said, _ = await session.finish(open_)
    return said


async def undo(request: Request, data: dict, guessed: frozenset) -> str:
    last = await database.run(store.db_last_undo, request.user.id)
    if last is None:
        raise UserError(f"{ICON} There is nothing to undo.")
    return await session.undo(last, request.user.id)


# --- swaps and plan changes -----------------------------------------------------------------------------------------------------
async def swap(request: Request, data: dict, guessed: frozenset):
    """ "swap bench for dumbbell press today": today's session (the open one, else the next started); from now on
    it is a change to the plan, on a card (`change_card`)."""
    plan = await _plan_or_say(request)
    old, new = str(data.get("exercise") or "").strip(), " ".join(str(data.get("instead") or "").split())
    if not old or not new:
        raise UserError(f"{ICON} Swap which exercise for which?")
    open_ = await database.run(store.db_open_session, request.user.id) or await session.start(request.user.id)
    exercises = await session.exercises_of(open_)
    found = session.find_exercise(exercises, old)
    if found is None:
        raise UserError(f"{ICON} “{old}” is not in today's {open_.name}.")
    swaps = await database.run(store.db_swaps, open_.id)
    original = next((key for key, value in swaps.items() if value.lower() == found.name.lower()), found.name.lower())
    swaps[original] = rules.tidy(new)
    await database.run(store.db_set_swaps, open_.id, swaps)
    await session.draw(await database.run(store.db_session, open_.id))
    return f"{ICON} Today: **{found.name}** → **{rules.tidy(new)}** · the plan as it was"


CHANGES = ("reps", "add", "remove", "rename", "step")


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """A change to the plan: a rep range, an exercise added or removed, renamed (swap from now on), its weight step."""
    plan = await _plan_or_say(request)
    what = str(data.get("change") or "")
    if what not in CHANGES:
        raise UserError(f"{ICON} What should change in the plan?")
    workouts = [session.find_workout(plan, str(data["workout"]))] if data.get("workout") else plan
    said = str(data.get("exercise") or "").strip()
    if what == "add":
        if len(workouts) != 1:
            raise UserError(f"{ICON} Add it to which workout?")
        workout = workouts[0]
        low, high = rules.reps_range(data.get("reps") or "8-12")
        count = max(1, min(10, int(data.get("sets") or 3)))
        made = Exercise(rules.tidy(said), tuple(PlannedSet(rules.WORKING, "", "", low, high) for _ in range(count)))
        return Proposal(lines=(f"**{workout.name}** · ➕ **{made.name}** · {count} × {rules.range_text(low, high)}",),
                        data={"change": "add", "workout_id": workout.id, "position": len(workout.exercises), "exercise": made.name, "sets": count, "low": low, "high": high}, kind="change")
    pairs = [(workout, found) for workout in workouts if (found := session.find_exercise(list(workout.exercises), said)) is not None]
    if not pairs:
        raise UserError(f"{ICON} “{said}” is not in your plan.")
    lines, changes = [], []
    for workout, exercise in pairs:
        if what == "remove":
            lines.append(f"**{workout.name}** · ➖ **{exercise.name}**")
            changes.append({"id": exercise.id})
        elif what == "reps":
            low, high = rules.reps_range(data.get("reps"))
            if low is None:
                raise UserError(f"{ICON} What rep range? Say it like 6-10.")
            sets = [replace(each, low=low, high=high) if each.set_type == rules.WORKING else each for each in exercise.sets]
            olds = sorted({rules.range_text(each.low, each.high) for each in exercise.sets if each.set_type == rules.WORKING})
            lines.append(f"**{workout.name}** · **{exercise.name}** · " + design.change(", ".join(olds), rules.range_text(low, high)))
            changes.append({"id": exercise.id, "name": exercise.name, "kind": exercise.kind, "step": exercise.step, "sets": [asdict(each) for each in sets]})
        elif what == "rename":
            new = rules.tidy(str(data.get("instead") or ""))
            if not new:
                raise UserError(f"{ICON} Swap it for which exercise?")
            lines.append(f"**{workout.name}** · " + design.change(exercise.name, new) + design.small(" from now on"))
            changes.append({"id": exercise.id, "name": new, "kind": "", "step": exercise.step, "sets": [asdict(each) for each in exercise.sets]})
        elif what == "step":
            step = float(data.get("step") or 0)
            if not 0 < step <= 50:
                raise UserError(f"{ICON} What step, in kg?")
            lines.append(f"**{exercise.name}** · step " + design.change(f"{rules.step_of(exercise):g} kg", f"{step:g} kg"))
            changes.append({"id": exercise.id, "name": exercise.name, "kind": exercise.kind, "step": step, "sets": [asdict(each) for each in exercise.sets]})
    return Proposal(lines=tuple(lines), data={"change": what, "changes": changes}, kind="remove" if what == "remove" else "change", confirm_label="Remove" if what == "remove" else "Save")


async def change_save(request: Request, data: dict) -> str:
    now = clock.now()
    if data["change"] == "add":
        made = Exercise(data["exercise"], tuple(PlannedSet(rules.WORKING, "", "", data["low"], data["high"]) for _ in range(int(data["sets"]))))
        await database.run(store.db_add_exercise, request.user.id, data["workout_id"], data["position"], made)
        said = f"{ICON} Added **{made.name}**"
    elif data["change"] == "remove":
        for each in data["changes"]:
            await database.run(store.db_remove_exercise, each["id"], now)
        said = f"{ICON} Removed from the plan (its history is kept)"
    else:
        for each in data["changes"]:
            await database.run(store.db_set_exercise, each["id"], each["name"], each["kind"], each["step"], [PlannedSet(**one) for one in each["sets"]])
        said = f"{ICON} Plan changed"
    session.changed(request.user.id)
    return said


async def change_check(request: Request, data: dict) -> str:
    plan = await store.plan(request.user.id)
    there = {each.id: each for workout in plan for each in workout.exercises}
    if data["change"] == "add":
        return "" if any(each.name == data["exercise"] for each in there.values()) else "it is not in the plan"
    if data["change"] == "remove":
        return "" if all(each["id"] not in there for each in data["changes"]) else "it is still in the plan"
    return "" if all(each["id"] in there and there[each["id"]].name == each["name"] for each in data["changes"]) else "the plan is not as the card said"


# --- a session described in words ---------------------------------------------------------------------------------------------
def _sets_of(items: list[dict], exercises: list[Exercise]) -> tuple[dict[str, list[DoneSet]], list[str], list[Note], list[str]]:
    """What was described, exercise by exercise, matched to the plan: {name: sets}, skipped, notes, not in the plan."""
    by_name: dict[str, list[DoneSet]] = {}
    skipped, notes, extra = [], [], []
    for item in items:
        said = str(item.get("exercise") or "").strip()
        if not said:
            continue
        found = session.find_exercise(exercises, said)
        name = found.name if found is not None else rules.tidy(said)
        if found is None and name not in extra:
            extra.append(name)
        if item.get("note"):
            notes.append(Note(name, str(item["note"]).strip(), bool(item.get("pain")), body_part=str(item.get("body_part") or "") if item.get("pain") else ""))
        if item.get("skipped"):
            skipped.append(name)
            continue
        if item.get("reps") is None:
            continue
        planned = list(found.sets) if found is not None else []
        mine = by_name.setdefault(name, [])
        index = len(mine)
        set_type = item.get("set_type") if item.get("set_type") in rules.SET_TYPES else (planned[index].set_type if index < len(planned) else rules.WORKING)
        plan_set = planned[index] if index < len(planned) else PlannedSet(set_type)
        weight_kg = float(item["weight"]) if item.get("weight") not in (None, "") else None
        mine.append(DoneSet(name, set_type, plan_set.purpose, plan_set.category, plan_set.low, plan_set.high, int(item["reps"]), weight_kg, bool(item.get("per_hand")), index))
    return by_name, skipped, notes, extra


def closest(plan: list[Workout], said_names: list[str]) -> Workout | None:
    """The workout whose exercises match most of what was described (half or more), else None: off-plan."""
    best, score = None, 0.0
    for workout in plan:
        matched = sum(1 for name in said_names if session.find_exercise(list(workout.exercises), name) is not None)
        share = matched / max(1, len(said_names))
        if share > score:
            best, score = workout, share
    return best if score >= 0.5 else None


def _apply_corrections(previous: dict, corrections: list[dict]) -> dict:
    """ "the second bench set was 9 not 8": that set of that exercise, on the open card's data."""
    kept = json.loads(json.dumps(previous))
    for each in corrections:
        name = str(each.get("exercise") or "").lower()
        number = int(each.get("set") or 0)
        for exercise, sets in kept.get("sets", {}).items():
            if exercise.lower().startswith(name[:5]) and 0 < number <= len(sets):
                if each.get("reps") is not None:
                    sets[number - 1]["reps"] = int(each["reps"])
                if each.get("weight") not in (None, ""):
                    sets[number - 1]["weight"] = float(each["weight"])
    return kept


async def describe_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """A whole session, or part of one, described in words (or read from a photo by the smart inbox): one card,
    each exercise with its sets as understood, what was skipped, the notes on the right exercise."""
    plan = await _plan_or_say(request)
    previous = request.previous or {}
    if previous and data.get("corrections") and not data.get("sets"):
        kept = _apply_corrections(previous, data["corrections"])
        return await _describe_proposal(request, plan, kept)
    workout = session.find_workout(plan, str(data["workout"])) if data.get("workout") else None
    items = list(data.get("sets") or [])
    candidate = workout or closest(plan, [str(each.get("exercise") or "") for each in items if each.get("exercise")])
    exercises = list(candidate.exercises) if candidate else []
    by_name, skipped, notes, extra = _sets_of(items, exercises)
    if previous.get("sets"):
        merged = {**previous["sets"], **{name: [asdict(each) for each in sets] for name, sets in by_name.items()}}
    else:
        merged = {name: [asdict(each) for each in sets] for name, sets in by_name.items()}
    kept = {
        "workout_id": candidate.id if candidate else None, "workout": candidate.name if candidate else "Off-plan session",
        "day": (_day(data.get("day")) if data.get("day") else date.fromisoformat(previous["day"]) if previous.get("day") else days.today()).isoformat(),
        "sets": merged, "skipped": sorted({*(previous.get("skipped") or []), *skipped}),
        "notes": [*(previous.get("notes") or []), *(asdict(each) for each in notes)], "extra": sorted({*(previous.get("extra") or []), *extra}),
        "guessed_workout": workout is None and candidate is not None,
    }
    return await _describe_proposal(request, plan, kept)


async def _describe_proposal(request: Request, plan: list[Workout], kept: dict) -> Proposal:
    day = date.fromisoformat(kept["day"])
    there = await database.run(store.db_session_on, request.user.id, kept["workout_id"], day) if kept["workout_id"] else None
    head = flag(f"**{kept['workout']}** · {_day_text(day)}", kept.get("guessed_workout", False))
    lines = [head + (design.small(" · added to the session logged by buttons") if there is not None else "")]
    for name, sets in kept["sets"].items():
        lines.append(f"**{name}** · " + rules.sets_text([DoneSet(**each) for each in sets]))
        for note in kept["notes"]:
            if note["exercise"] == name:
                lines.append(design.small(("⚠️ " if note["pain"] else "") + f"note: “{note['text']}”"))
    for name in kept["skipped"]:
        lines.append(f"**{name}** · skipped")
        for note in kept["notes"]:
            if note["exercise"] == name:
                lines.append(design.small(("⚠️ " if note["pain"] else "") + f"note: “{note['text']}”"))
    warnings = [f"“{name}” is not in {kept['workout']}: logged as an extra" for name in kept["extra"]] if kept["workout_id"] else []
    if not kept["sets"] and not kept["skipped"]:
        raise UserError(f"{ICON} I couldn't find a set in that: say it like “bench 40 for 9 and 8”.")
    return Proposal(lines=tuple(lines), data=kept, warnings=tuple(warnings), kind="new")


async def describe_save(request: Request, data: dict) -> str:
    day = date.fromisoformat(data["day"])
    there = await database.run(store.db_session_on, request.user.id, data["workout_id"], day) if data["workout_id"] else None
    queue_before = await database.run(store.db_queue, request.user.id)
    made = there is None
    if made:
        status = store.FINISHED if data["workout_id"] else store.OFF_PLAN
        session_id = await database.run(store.db_add_session, request.user.id, data["workout_id"], data["workout"], day, status, clock.now(), "words")
        if data["workout_id"] is not None:
            plan = await store.plan(request.user.id)
            await database.run(store.db_set_queue, request.user.id, session.moved_to_back([each.id for each in session.queue_now(queue_before, plan)], data["workout_id"]), clock.now())
    else:
        session_id = there.id
    current = await database.run(store.db_session, session_id)
    before = await database.run(store.db_bests, request.user.id)
    for name, sets in data["sets"].items():
        notes = [Note(**each) for each in data["notes"] if each["exercise"] == name]
        await session.log_sets(current, name, [DoneSet(**each) for each in sets], notes[-1] if notes else None)
    for name in data["skipped"]:
        notes = [Note(**each) for each in data["notes"] if each["exercise"] == name]
        if notes:
            await database.run(store.db_add_note, request.user.id, session_id, notes[-1])
    logged = await database.run(store.db_sets, session_id)
    beaten = rules.beaten(before, logged)
    await database.run(store.db_put_bests, request.user.id, rules.bests(logged), session_id)
    if made:
        await database.run(store.db_remember, request.user.id, "session", {"session": session_id, "queue": queue_before}, clock.now())
    if current.channel_id:
        await session.draw(current)
    session.changed(request.user.id)
    names_seen = {each.exercise.lower(): each.exercise for each in logged}
    said = f"{ICON} Saved · **{data['workout']}** · {_day_text(day)} · {sum(len(each) for each in data['sets'].values())} sets"
    return "\n".join([said, *(rules.best_line(each, names_seen) for each in beaten)])


async def describe_check(request: Request, data: dict) -> str:
    day = date.fromisoformat(data["day"])
    sessions = [each for each in await database.run(store.db_sessions, request.user.id, day) if each.day == day and each.name == data["workout"]]
    if not sessions:
        return "the session is not there"
    logged = {each.exercise for each in await database.run(store.db_sets, sessions[-1].id)}
    return "" if set(data["sets"]) <= logged else "a set is not there"


# --- questions ------------------------------------------------------------------------------------------------------------------
QUESTIONS = ("last", "notes", "best", "trend", "sessions", "training", "pain")


async def _named(request: Request, said: str) -> list[str]:
    """Every name the exercise has had in the log that the words fit."""
    plan = await store.plan(request.user.id)
    exercises = [each for workout in plan for each in workout.exercises]
    found = session.find_exercise(exercises, said)
    return [found.name] if found is not None else [rules.tidy(said)]


async def ask(request: Request, data: dict, guessed: frozenset) -> str:
    what = str(data.get("question") or "last")
    today = days.today()
    if what == "training":
        from tasks.gym import insights

        return await insights.answer(request.user.id, today)
    if what == "pain":
        from tasks.gym import pain

        return pain.history_text(await database.run(pain.db_history, request.user.id), today)
    if what == "sessions":
        span = str(data.get("span") or "month")
        since = today - timedelta(days=today.weekday()) if span == "week" else today.replace(day=1)
        found = await database.run(store.db_sessions, request.user.id, since)
        listed = ", ".join(f"{each.name} {each.day.day} {each.day:%b}" for each in found[-8:])
        return f"{ICON} **{len(found)} session{'' if len(found) == 1 else 's'}** this {span}" + (f" · {listed}" if listed else "")
    said = str(data.get("exercise") or "").strip()
    if not said:
        raise UserError(f"{ICON} Which exercise?")
    names_ = await _named(request, said)
    if what == "notes":
        notes = await database.run(store.db_exercise_notes, request.user.id, names_)
        if not notes:
            return f"{ICON} No notes on **{names_[0]}**."
        return "\n".join([f"{ICON} **{names_[0]}** · notes", *(f"{'⚠️ ' if note.pain else ''}{day.day} {day:%b}: “{note.text}”" for day, note in notes[-6:])])
    history = await database.run(store.db_exercise_history, request.user.id, names_)
    if not history:
        return f"{ICON} Nothing logged for **{names_[0]}** yet."
    if what == "best":
        best = rules.top_set([each for _, sets in history for each in sets])
        return f"{ICON} **{names_[0]}** · best: {rules.set_line(best)}" if best else f"{ICON} No working set of **{names_[0]}** yet."
    if what == "trend":
        recent = [(found.day, sets) for found, sets in history[-6:]]
        return f"{ICON} **{names_[0]}** · last {len(recent)} sessions: {rules.trend(recent)}"
    found, sets = history[-1]
    return f"{ICON} **{names_[0]}** · {found.day:%a} {found.day.day} {found.day:%b} · {rules.sets_text(sets)}"


async def show_plan(request: Request, data: dict, guessed: frozenset) -> str:
    plan = await _plan_or_say(request)
    queue = session.queue_now(await database.run(store.db_queue, request.user.id), plan)
    lines = [f"{ICON} **Your plan** · next: **{queue[0].name}**" if queue else f"{ICON} **Your plan**"]
    for workout in queue:
        lines.append(f"**{workout.name}** · " + ", ".join(each.name for each in workout.exercises))
    return "\n".join(lines)


# --- a target, and a session at a time --------------------------------------------------------------------------------------------
async def target_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    count = int(data.get("per_week") or 0)
    was = await database.run(store.db_target, request.user.id)
    if not 0 <= count <= 14:
        raise UserError(f"{ICON} How many sessions a week?")
    said = f"{count} a week" if count else "no target"
    return Proposal(lines=(f"**Weekly target** · " + (design.change(f"{was} a week", said) if was else said), design.small("shown in the week's summary only: never a ping")),
                    data={"per_week": count or None}, kind="change" if was else "new")


async def target_save(request: Request, data: dict) -> str:
    await database.run(store.db_set_target, request.user.id, data["per_week"], clock.now())
    return f"{ICON} Target · {data['per_week']} a week" if data["per_week"] else f"{ICON} No weekly target"


async def target_check(request: Request, data: dict) -> str:
    return "" if await database.run(store.db_target, request.user.id) == data["per_week"] else "the target is not there"


POST_JOB = "post"


async def at_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "gym tomorrow 6pm": a Bot calendar event, and the card posted in #gym at that time."""
    await _plan_or_say(request)
    if not data.get("time"):
        raise UserError(f"{ICON} At what time?")
    day = timeinput.parse_date(str(data.get("day") or "today"), days.today())
    try:
        at = timeinput.parse_time(str(data["time"]))
    except timeinput.AmbiguousTime as which:
        at = which.options[-1]  # a gym session said with no am or pm: the evening's, and said so
    start = days.at(day, at)
    workout = await session.next_workout(request.user.id)
    on_calendar = _writer() is not None
    lines = (f"**{workout.name if workout else 'Gym'}** · {day:%a} {day.day} {day:%b} · {design.time(timeinput.format_moment(start))}",
             design.small("on the Bot calendar, and its card posted in #gym then" if on_calendar else "its card posted in #gym then"))
    return Proposal(lines=lines, data={"start": start.isoformat(), "workout": workout.name if workout else "Gym", "calendar": on_calendar}, kind="new")


def _writer():
    try:
        from tasks.calendar import plain as calendar_plain, source

        if not calendar_plain.writing():
            return None
        found = source.bot()
        return found if found is not None and found.can_write else None
    except Exception:
        return None


async def at_save(request: Request, data: dict) -> str:
    start = datetime.fromisoformat(data["start"])
    if data.get("calendar") and _writer() is not None:
        made = await _writer().add(f"{ICON} Gym · {data['workout']}", start, start + timedelta(hours=1))
        from tasks.calendar import plain as calendar_plain, store as calendar_store

        await database.run(calendar_store.db_put, request.user.id, made)
        calendar_plain._changed(request.user.id)
    await scheduler.add_job(TASK, POST_JOB, start, {"user": request.user.id}, user_id=request.user.id, key=f"gym@{start.isoformat()}")
    return f"{ICON} Booked · **{data['workout']}** · {timeinput.format_moment(start)}" + (" · on the Bot calendar" if data.get("calendar") else "")


async def at_check(request: Request, data: dict) -> str:
    return "" if any(job.due_at.isoformat() == data["start"] for job in await scheduler.pending_jobs(TASK, POST_JOB)) else "the booking is not there"


async def post_job(job) -> None:
    """Scheduler handler: a session asked for at a time ("gym tomorrow 6pm"): the next workout's card in #gym."""
    user_id = job.payload.get("user") or job.user_id
    try:
        started = await session.start(int(user_id))
        scheduler.note(job, f"posted the next workout (session {started.number or ''})".strip())
    except UserError as error:
        scheduler.note(job, f"not posted: {error}")


# --- what extraction fills in ---------------------------------------------------------------------------------------------------
_PLAN_FIELDS = (
    Field("plan", "The words that name the plan, as the user said them (\"October\", \"upper lower\", \"2026-10-19\"). Leave out with previous, and when no plan is named (\"the gym plan\", \"my plan\")."),
    Field("previous", "True for the plan before the active one (\"the previous plan\", \"the old one\").", BOOLEAN),
)


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action
    from tasks.gym import plans

    set_item = (
        Field("exercise", _EXERCISE, required=True),
        Field("set_type", "warm-up or working, when said or clear from the order (a lighter first set is a warm-up).", choices=rules.SET_TYPES),
        Field("reps", "The reps done.", INTEGER),
        Field("weight", "The weight in kg, as a number (\"14s\" -> 14).", NUMBER),
        Field("per_hand", "True for dumbbells or a weight said per hand (\"14s\", \"14 each\").", BOOLEAN),
        Field("skipped", "True when the exercise was skipped (\"skipped laterals\").", BOOLEAN),
        Field("note", "What the user said about this exercise, word for word (\"shoulder felt off\", \"last set was a grind\"), on the exercise it was said with (\"bench 40 for 9, knee was sore\" is bench's note), on one item only. Leave out when nothing."),
        Field("pain", "True when the note speaks of pain or discomfort (sore, hurt, felt off, a joint).", BOOLEAN),
        Field("body_part", "With pain: where, in a word or two (\"shoulder\", \"left knee\")."),
    )
    return [
        Action("gym_import", "Import the gym plan or logbook from a spreadsheet sent with the message or rows pasted in it (\"here's my gym logbook\"). On the open import card, say what a column is (\"the Load column is the weight\" -> columns).",
               (Field("columns", "A column said to be a field, only when the user says.", ITEMS, item_fields=(Field("heading", "The column's heading.", required=True), Field("field", "Which field.", choices=importer.FIELDS, required=True))),),
               prepare=import_card, apply=import_save, verify=import_check, purpose=SET_UP, say=("here's my gym logbook",)),
        Action("gym_start", "Start a workout: the next in turn (\"starting a workout\", \"gym now\", \"what's my workout?\", \"extra session\"), or a named one instead (\"do Lower 2 instead\" -> workout Lower 2).",
               (Field("workout", "A workout named, as the user said it. Leave out for the next in turn."),), needs_card=False, run=start, purpose=EACH_DAY, say=("starting a workout",)),
        Action("gym_skip", "Skip a workout: it goes to the back of the queue (\"skip Upper 1\"; \"skip today's\" -> nothing named).",
               (Field("workout", "The workout named, as said."),), needs_card=False, run=skip, purpose=EACH_DAY, say=("skip Upper 1",)),
        Action("gym_off_plan", "Something else done instead of a workout (\"did a 30 min run instead\" -> activity 30 min run).",
               (Field("activity", "What was done, in the user's words.", required=True), Field("day", _DAY)), needs_card=False, run=off_plan, purpose=EACH_DAY, say=("did a 30 min run instead",)),
        Action("gym_swap", "Swap an exercise for another today only (\"swap bench for dumbbell press today\"). From now on is gym_change with change rename.",
               (Field("exercise", _EXERCISE, required=True), Field("instead", "The exercise done instead, as said.", required=True)), needs_card=False, run=swap, purpose=EACH_DAY, say=("swap bench for dumbbell press today",)),
        Action("gym_change", "Change the plan: a rep range (\"make RDLs 6-10\" -> change reps, reps 6-10), add an exercise (\"add face pulls to Upper 1, 3 sets of 12-15\" -> change add), remove one, swap one from now on (change rename, instead), or its weight step (\"bench steps are 2.5\" -> change step, step 2.5).",
               (Field("change", "reps, add, remove, rename or step.", choices=CHANGES, required=True), Field("exercise", _EXERCISE, required=True), Field("workout", "The workout, if named."),
                Field("reps", "The rep range as said (\"6-10\")."), Field("sets", "How many sets, for an add.", INTEGER), Field("instead", "For rename: the new exercise."), Field("step", "For step: kg.", NUMBER)),
               prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("make RDLs 6-10",)),
        Action("gym_log", "Sets done, or a whole session described, during or after, even days later (\"bench 20 for 15, 40 for 9, 40 for 8\"; \"did Upper 1 this morning: bench warm-up 20 for 15, then 40 for 9 and 8; skipped laterals, shoulder felt off\"). A set an item; a skipped exercise an item with skipped. On the open card, a correction (\"the second bench set was 9 not 8\") is corrections.",
               (Field("workout", "The workout named, if said."), Field("day", _DAY), Field("sets", "Each set done, in order, or a skipped exercise.", ITEMS, item_fields=set_item),
                Field("corrections", "On the open card only: a set put right.", ITEMS, item_fields=(Field("exercise", _EXERCISE, required=True), Field("set", "Which set of it, counting from 1.", INTEGER, required=True), Field("reps", "The reps it should be.", INTEGER), Field("weight", "The weight it should be, in kg.", NUMBER)))),
               prepare=describe_card, apply=describe_save, verify=describe_check, purpose=EACH_DAY, say=("bench 20 for 15, 40 for 9, 40 for 8",)),
        Action("gym_finish", "Finish the workout that is open (\"finish the workout\", \"done at the gym\").", (), needs_card=False, run=finish, purpose=EACH_DAY, say=("finish the workout",)),
        Action("gym_ask", "A question about the user's lifts: last time (\"what did I do on bench last time?\" -> last), notes (\"my notes on RDLs\"), best (\"best leg press\"), trend (\"how's my bench going?\"), sessions (\"sessions this month\" -> span month), training (\"how's my training going?\"), pain (\"any pain?\", \"pain history\").",
               (Field("question", "last, notes, best, trend or sessions.", choices=QUESTIONS, required=True), Field("exercise", _EXERCISE), Field("span", "week or month, for sessions.", choices=("week", "month"))),
               needs_card=False, run=ask, purpose=SEE, say=("how's my bench going?",)),
        Action("gym_plan_show", "Show the active plan's workouts and exercises (\"my gym plan\", \"what's in my plan?\"). Not the list of plans kept (gym_plans).", (), needs_card=False, run=show_plan, purpose=SEE, say=("my gym plan",)),
        Action("gym_target", "A weekly target of sessions (\"aim for 3 a week\" -> per_week 3; \"no gym target\" -> 0).", (Field("per_week", "Sessions a week; 0 for none.", INTEGER, required=True),),
               prepare=target_card, apply=target_save, verify=target_check, purpose=SET_UP, say=("aim for 3 a week",)),
        Action("gym_at", "A session planned at a time (\"gym tomorrow 6pm\" -> day tomorrow, time 6:00 pm).", (Field("day", "The day as said."), Field("time", "The time.", TIME, required=True)),
               prepare=at_card, apply=at_save, verify=at_check, purpose=SET_UP, say=("gym tomorrow 6pm",)),
        Action("gym_undo", "Undo the last gym change (\"undo that\" straight after one).", (), needs_card=False, run=undo, purpose=EACH_DAY, say=("undo that",)),
        Action("gym_plans", "List every gym plan the user has, the active one included: a version for each logbook imported (\"show my gym plans\", \"what plans do I have\", \"list my plans\").", (), needs_card=False, run=plans.list_said, purpose=SEE, say=("show my gym plans",)),
        Action("gym_plan_switch", "Make another of the user's gym plans the active one (\"switch to the October plan\" -> plan October; \"use the upper lower one\" -> plan upper lower; \"switch to the previous plan\", \"go back to the previous plan\" -> previous).",
               _PLAN_FIELDS, prepare=plans.switch_card, apply=plans.switch_save, verify=plans.switch_check, purpose=SET_UP, say=("switch to the October plan",)),
        Action("gym_plan_delete", "Delete one of the user's gym plans, the active one included (\"delete the gym plan\", \"delete my plan\" -> nothing named: the active one; \"delete the October plan\" -> plan October). A card asks first; the log is never deleted.",
               _PLAN_FIELDS, prepare=plans.delete_card, apply=plans.delete_save, verify=plans.delete_check, purpose=SET_UP, say=("delete the October plan",)),
    ]
