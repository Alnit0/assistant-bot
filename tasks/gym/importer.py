import logging
from dataclasses import dataclass, field, replace
from datetime import date

from core import costs, llm
from tasks.gym import rules
from core.grid import Table
from tasks.gym.rules import DoneSet, Exercise, Note, PlannedSet, Workout

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Importing a plan and its log from a logbook (a CSV, an XLSX with a tab a
# workout or one table, or pasted rows).
#
#   1. Claude is shown each table's headings and three sample rows and says
#      which heading is which field (`MAP`), and which it is unsure of
#   2. Claude is shown the distinct words the plan uses (brackets on exercise
#      names, purposes, exercise names, notes) and says what each means: a set
#      type, to failure or not, the kind of weight, a note's pain, per hand or
#      target weight (`MEANING`). It reads no number
#   3. Python reads every value, row by row (rules.py), and parts the plan
#      (each workout as last done, in the order first seen) from the log
#      (dated sessions; DNF or nothing done is planned, not done)
#
# Blank rows part workouts. Nothing is saved before the card's Save.
# ---------------------------------------------------------------------------
FIELDS = ("workout", "date", "week", "exercise", "set_type", "sets", "reps", "sets_and_reps", "reps_done", "weight", "result", "purpose", "notes", "none")
MAP_TOOL, MEANING_TOOL = "map_columns", "read_words"
PURPOSE_MAP, PURPOSE_MEANING = "gym-map", "gym-words"
MAX_WORDS = 120  # distinct words sent to be read, of each kind
MAP_TOKENS = 3000  # a workbook of a tab a workout is many headings: room for every one (17 Oct: 800 cut it off)

MAP_SYSTEM = (
    "You map the columns of a gym logbook or plan to fields. You are given each table's name, its headings and up "
    "to three sample rows. For every heading say which field it is: workout (the workout's or day's name: Upper 1, "
    "Push, Day A), date (the day a session was done), week, exercise, set_type (warm-up or working, when a column "
    "says), sets (how many sets the row is), reps (the target reps or range), sets_and_reps (\"3x8\" in one cell), "
    "reps_done (the reps achieved), weight, result (one set's weight and reps done in one cell, \"40x9\": several "
    "such columns are several sets), purpose (what the set is for: Warm-up, To failure, Form check), notes, or none. "
    "Mark sure false for any you are not sure of. Read no value: Python does."
)
MEANING_SYSTEM = (
    "You read the words of a gym logbook. For each bracket found on an exercise's name, say whether it is a set "
    "type (warm-up or working) or part of the name (\"high foot\" is part of the name). For each purpose, say which "
    "it is: to_failure, near_failure, technique (find groove, form check) or warm_up. For each exercise, its kind: "
    "barbell, dumbbell, machine, cable or bodyweight. For each note, whether it speaks of pain or discomfort (pain), "
    "whether it says the weight was per hand (dumbbells: per_hand), and any weight in kg it says to go to next "
    "(\"go up to 40-45kg next week\" -> target_low 40, target_high 45)."
)


@dataclass(frozen=True)
class Mapping:
    columns: dict[int, str]  # column index -> field
    unsure: tuple[int, ...] = ()


@dataclass
class Imported:
    plan: list[Workout] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)  # {"workout", "day", "sets": [DoneSet], "notes": [Note]}
    not_done: int = 0  # workouts planned but not done (DNF)
    unused: list[str] = field(default_factory=list)  # headings mapped to none
    unsure: list[str] = field(default_factory=list)  # "Objective → purpose"
    problems: list[str] = field(default_factory=list)

    @property
    def set_count(self) -> int:
        return sum(len([each for each in session["sets"] if each.done]) for session in self.sessions)


# --- the requests ------------------------------------------------------------------------------------------------------
def map_tool() -> dict:
    return {
        "name": MAP_TOOL, "description": "Say which field each heading of each table is.",
        "input_schema": {"type": "object", "properties": {"columns": {"type": "array", "items": {"type": "object", "properties": {
            "table": {"type": "string"}, "heading": {"type": "string"}, "field": {"type": "string", "enum": list(FIELDS)}, "sure": {"type": "boolean"},
        }, "required": ["table", "heading", "field", "sure"]}}}, "required": ["columns"]},
    }


def meaning_tool() -> dict:
    item = lambda extra: {"type": "array", "items": {"type": "object", "properties": {"index": {"type": "integer"}, **extra}, "required": ["index", *extra]}}
    return {
        "name": MEANING_TOOL, "description": "Say what each word of the logbook means.",
        "input_schema": {"type": "object", "properties": {
            "brackets": item({"meaning": {"type": "string", "enum": ["warm-up", "working", "name"]}}),
            "purposes": item({"category": {"type": "string", "enum": list(rules.PURPOSES)}}),
            "exercises": item({"kind": {"type": "string", "enum": list(rules.KINDS)}}),
            "notes": item({"pain": {"type": "boolean"}, "per_hand": {"type": "boolean"}, "target_low": {"type": "number"}, "target_high": {"type": "number"}}),
        }, "required": ["brackets", "purposes", "exercises", "notes"]},
    }


def map_turn(tables: list[Table]) -> str:
    said = []
    for table in tables:
        said.append(f"Table “{table.name}”\nHeadings: " + " | ".join(table.headings))
        for row in table.samples():
            said.append("Row: " + " | ".join(row))
    return "\n".join(said)


async def ask_mapping(tables: list[Table]) -> dict[str, Mapping]:
    called = await llm.call_tool([{"type": "text", "text": MAP_SYSTEM, "cache_control": llm.CACHED}], map_turn(tables), [map_tool()],
                                 choice={"type": "tool", "name": MAP_TOOL}, purpose=PURPOSE_MAP, task=rules.TASK, max_tokens=MAP_TOKENS)
    return mapping_from(called[1] if called else None, tables)


def mapping_from(raw, tables: list[Table]) -> dict[str, Mapping]:
    """What came back, checked: a heading of a table, a field of FIELDS; anything else is left out."""
    found: dict[str, Mapping] = {}
    for table in tables:
        columns, unsure = {}, []
        for each in (raw or {}).get("columns", []) if isinstance(raw, dict) else []:
            if not isinstance(each, dict) or each.get("table") not in (table.name, "") or each.get("field") not in FIELDS:
                continue
            heading = str(each.get("heading", "")).strip().lower()
            index = next((number for number, said in enumerate(table.headings) if said.strip().lower() == heading), None)
            if index is None or index in columns:
                continue
            columns[index] = each["field"]
            if each.get("sure") is False:
                unsure.append(index)
        found[table.name] = Mapping(columns, tuple(unsure))
    return found


@dataclass(frozen=True)
class Meanings:
    brackets: dict[str, str] = field(default_factory=dict)  # bracket (lower case) -> warm-up / working / name
    purposes: dict[str, str] = field(default_factory=dict)  # purpose (lower case) -> category
    kinds: dict[str, str] = field(default_factory=dict)  # exercise (lower case) -> kind
    notes: dict[str, dict] = field(default_factory=dict)  # note text -> {pain, per_hand, target_low, target_high}


def words_turn(brackets: list[str], purposes: list[str], exercises: list[str], notes: list[str]) -> str:
    def listed(title: str, values: list[str]) -> str:
        return f"{title}:\n" + "\n".join(f"{index}. {value}" for index, value in enumerate(values)) if values else f"{title}: none"

    return "\n\n".join([listed("Brackets", brackets), listed("Purposes", purposes), listed("Exercises", exercises), listed("Notes", notes)])


async def ask_meanings(brackets: list[str], purposes: list[str], exercises: list[str], notes: list[str]) -> Meanings:
    if not any((brackets, purposes, exercises, notes)):
        return Meanings()
    called = await llm.call_tool([{"type": "text", "text": MEANING_SYSTEM, "cache_control": llm.CACHED}], words_turn(brackets, purposes, exercises, notes), [meaning_tool()],
                                 choice={"type": "tool", "name": MEANING_TOOL}, purpose=PURPOSE_MEANING, task=rules.TASK, max_tokens=2000)
    return meanings_from(called[1] if called else None, brackets, purposes, exercises, notes)


def meanings_from(raw, brackets: list[str], purposes: list[str], exercises: list[str], notes: list[str]) -> Meanings:
    raw = raw if isinstance(raw, dict) else {}

    def pick(key: str, values: list[str], value_key: str, allowed) -> dict:
        found = {}
        for each in raw.get(key, []) or []:
            if isinstance(each, dict) and isinstance(each.get("index"), int) and 0 <= each["index"] < len(values) and each.get(value_key) in allowed:
                found[values[each["index"]].lower()] = each[value_key]
        return found

    read_notes = {}
    for each in raw.get("notes", []) or []:
        if isinstance(each, dict) and isinstance(each.get("index"), int) and 0 <= each["index"] < len(notes):
            read_notes[notes[each["index"]]] = {key: each.get(key) for key in ("pain", "per_hand", "target_low", "target_high")}
    return Meanings(pick("brackets", brackets, "meaning", ("warm-up", "working", "name")), pick("purposes", purposes, "category", rules.PURPOSES),
                    pick("exercises", exercises, "kind", rules.KINDS), read_notes)


# --- Python reads the values ----------------------------------------------------------------------------------------------
def _cell(row: tuple[str, ...], columns: dict[int, str], wanted: str) -> str:
    index = next((number for number, said in columns.items() if said == wanted), None)
    return row[index].strip() if index is not None and index < len(row) else ""


def words_of(tables: list[Table], mappings: dict[str, Mapping]) -> tuple[list[str], list[str], list[str], list[str]]:
    """The distinct brackets, purposes, exercise names and notes, for Claude to read (step 2)."""
    import re

    brackets, purposes, exercises, notes = [], [], [], []
    for table in tables:
        columns = mappings[table.name].columns
        for row in table.rows:
            cell = _cell(row, columns, "exercise")
            for found in re.finditer(r"\(([^)]*)\)", cell):
                said = found[1].strip()
                if said and said.lower() not in [each.lower() for each in brackets]:
                    brackets.append(said)
            name = re.sub(r"\s*\([^)]*\)\s*", " ", cell).strip()
            if name and rules.tidy(name).lower() not in [each.lower() for each in exercises]:
                exercises.append(rules.tidy(name))
            purpose = _cell(row, columns, "purpose")
            if purpose and purpose.lower() not in [each.lower() for each in purposes]:
                purposes.append(purpose)
            note = _cell(row, columns, "notes")
            if note and note not in notes:
                notes.append(note)
    return brackets[:MAX_WORDS], purposes[:MAX_WORDS], exercises[:MAX_WORDS], notes[:MAX_WORDS]


def _groups(table: Table, columns: dict[int, str]) -> list[list[tuple[str, ...]]]:
    """The rows in workouts: a blank row ends one, and so does a new date or workout."""
    groups: list[list[tuple[str, ...]]] = []
    current: list[tuple[str, ...]] = []
    key = None
    for row in table.rows:
        if not any(row):
            if current:
                groups.append(current)
            current, key = [], None
            continue
        this = (_cell(row, columns, "date"), _cell(row, columns, "workout") or table.name)
        if current and key is not None and this != key and (this[0] or this[1] != key[1]):
            groups.append(current)
            current = []
        current.append(row)
        key = this
    if current:
        groups.append(current)
    return groups


def read(tables: list[Table], mappings: dict[str, Mapping], meanings: Meanings) -> Imported:
    """The plan and the log from the tables, every value read by Python."""
    found = Imported()
    order: list[str] = []
    last_seen: dict[str, tuple[date | None, list[Exercise]]] = {}
    for table in tables:
        mapping = mappings[table.name]
        columns = mapping.columns
        found.unused += [table.headings[index] for index, said in columns.items() if said == "none" and table.headings[index]]
        found.unused += [heading for index, heading in enumerate(table.headings) if index not in columns and heading]
        found.unsure += [f"“{table.headings[index]}” → {columns[index].replace('_', ' ')}" for index in mapping.unsure]
        if "exercise" not in columns.values():
            found.problems.append(f"“{table.name}” has no column for the exercise")
            continue
        for group in _groups(table, columns):
            first = group[0]
            name = rules.tidy(_cell(first, columns, "workout") or table.name)
            if name.lower() not in [each.lower() for each in order]:
                order.append(name)
            said_date = _cell(first, columns, "date")
            day = rules.logbook_date(said_date)
            exercises, sets, notes = [], [], []
            position = 0
            for row in group:
                cell = _cell(row, columns, "exercise")
                if not cell:
                    continue
                exercise_name, from_bracket = rules.split_exercise(cell, meanings.brackets)
                set_type = from_bracket or (rules.WARM_UP if _cell(row, columns, "set_type").lower().startswith("warm") else rules.WORKING)
                purpose = _cell(row, columns, "purpose")
                category = meanings.purposes.get(purpose.lower(), "")
                if category == rules.WARMING and from_bracket is None:
                    set_type = rules.WARM_UP
                low, high = rules.reps_range(_cell(row, columns, "reps"))
                count = rules.reps(_cell(row, columns, "sets")) or 1
                combined = _cell(row, columns, "sets_and_reps")
                if combined and "x" in combined.lower():
                    left, _, right = combined.lower().partition("x")
                    count = rules.reps(left) or count
                    low, high = rules.reps_range(right)
                planned = PlannedSet(set_type, purpose, category, low, high)
                if not exercises or exercises[-1].name.lower() != exercise_name.lower():
                    exercises.append(Exercise(exercise_name, (), meanings.kinds.get(exercise_name.lower(), "")))
                exercises[-1] = replace(exercises[-1], sets=(*exercises[-1].sets, *([planned] * count)))
                note = _cell(row, columns, "notes")
                read_note = meanings.notes.get(note, {})
                per_hand = bool(read_note.get("per_hand"))
                results = [row[index] for index, said in sorted(columns.items()) if said == "result" and index < len(row)]
                if results:
                    for each in results:
                        weight_kg, reps_done, said_per_hand = rules.result(each)
                        sets.append(DoneSet(exercise_name, set_type, purpose, category, low, high, reps_done if day else None, weight_kg, per_hand or said_per_hand, position))
                        position += 1
                else:
                    weight_kg, said_per_hand = rules.weight(_cell(row, columns, "weight"))
                    reps_done = rules.reps(_cell(row, columns, "reps_done")) if day else None
                    for _ in range(count):
                        sets.append(DoneSet(exercise_name, set_type, purpose, category, low, high, reps_done, weight_kg, per_hand or said_per_hand, position))
                        position += 1
                if note:
                    notes.append(Note(exercise_name, note, bool(read_note.get("pain")), _number(read_note.get("target_low")), _number(read_note.get("target_high"))))
            if not exercises:
                continue
            last_seen[name.lower()] = (day, exercises) if name.lower() not in last_seen or (day or date.min) >= (last_seen[name.lower()][0] or date.min) else last_seen[name.lower()]
            if day is None or not any(each.done for each in sets):
                found.not_done += 1
                continue
            found.sessions.append({"workout": name, "day": day, "sets": sets, "notes": notes})
    found.plan = [Workout(name, tuple(last_seen[name.lower()][1])) for name in order if name.lower() in last_seen]
    found.unused = sorted(set(found.unused))
    found.sessions.sort(key=lambda each: each["day"])
    return found


def _number(value) -> float | None:
    """A weight Claude handed over; none, or 0 (what it gives for a note with no target: 18 Oct), is None."""
    try:
        found = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return found if found is not None and found > 0 else None


async def imported(tables: list[Table], overrides: dict[str, dict[str, str]] | None = None) -> Imported:
    """The whole import: the mapping (with any said on the card laid over it), the words, the values."""
    mappings = await ask_mapping(tables)
    for table_name, said in (overrides or {}).items():
        for table in tables:
            if table.name != table_name and table_name != "*":
                continue
            columns = dict(mappings[table.name].columns)
            unsure = list(mappings[table.name].unsure)
            for heading, field_name in said.items():
                index = next((number for number, each in enumerate(table.headings) if each.strip().lower() == heading.strip().lower()), None)
                if index is not None and field_name in FIELDS:
                    columns[index] = field_name
                    unsure = [each for each in unsure if each != index]
            mappings[table.name] = Mapping(columns, tuple(unsure))
    meanings = await ask_meanings(*words_of(tables, mappings))
    return read(tables, mappings, meanings)


# --- the card's words -------------------------------------------------------------------------------------------------------
def card_lines(found: Imported) -> list[str]:
    from core import design

    lines = []
    for workout in found.plan:
        sets = sum(len(each.sets) for each in workout.exercises)
        lines.append(f"**{workout.name}** · {len(workout.exercises)} exercises · {sets} sets")
        lines.append(design.small(" · ".join(each.name for each in workout.exercises[:6]) + (f" +{len(workout.exercises) - 6} more" if len(workout.exercises) > 6 else "")))
    if found.sessions:
        first, last = found.sessions[0]["day"], found.sessions[-1]["day"]
        lines.append(f"**Log** · {len(found.sessions)} sessions · {found.set_count} sets · {first.day} {first:%b %Y} to {last.day} {last:%b %Y}")
    else:
        lines.append("**Log** · no dated sessions")
    if found.not_done:
        lines.append(design.small(f"{found.not_done} workout{'' if found.not_done == 1 else 's'} planned and not done (DNF or nothing logged): not in the log"))
    pain = sum(1 for session in found.sessions for note in session["notes"] if note.pain)
    if pain:
        lines.append(design.small(f"⚠️ {pain} note{'' if pain == 1 else 's'} about pain: shown the next time that exercise comes up"))
    if found.unused:
        lines.append(design.small("not used: " + ", ".join(found.unused)))
    return lines
