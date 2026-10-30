import math
import re
from dataclasses import dataclass, field, replace
from datetime import date

# ---------------------------------------------------------------------------
# The gym's rules and words. Pure: no database, no Discord, no Claude.
#
# Python reads every value (reps, a range, a weight, a date, "40 x 9") and does
# every sum (the suggested weight, personal bests, a trend). What a note or a
# set's purpose means (pain, per hand, a target weight, to failure) is
# Claude's to say (importer.py, plain.py), never read here from the words.
# ---------------------------------------------------------------------------
TASK = "gym"
ICON = "🏋️"
TITLE = "Gym"
WARM_UP, WORKING = "warm-up", "working"
SET_TYPES = (WARM_UP, WORKING)
# What a set is for, as Claude sorts the plan's own words (Warm-up, Near failure, To failure, Find groove…)
TO_FAILURE, NEAR_FAILURE, TECHNIQUE, WARMING = "to_failure", "near_failure", "technique", "warm_up"
PURPOSES = (TO_FAILURE, NEAR_FAILURE, TECHNIQUE, WARMING)
BARBELL, DUMBBELL, MACHINE, CABLE, BODYWEIGHT = "barbell", "dumbbell", "machine", "cable", "bodyweight"
KINDS = (BARBELL, DUMBBELL, MACHINE, CABLE, BODYWEIGHT)
STEP = {BARBELL: 2.5, DUMBBELL: 2.5, MACHINE: 5.0, CABLE: 5.0, BODYWEIGHT: 2.5}
BIG_JUMP = 5  # reps over the top of the range that call for a bigger jump
MAX_REPS, MAX_WEIGHT = 200, 1000.0


@dataclass(frozen=True)
class PlannedSet:
    set_type: str = WORKING
    purpose: str = ""  # the plan's own words ("To failure")
    category: str = ""  # one of PURPOSES, as Claude sorted the purpose
    low: int | None = None  # target reps, a range (5-8) or one number (low == high)
    high: int | None = None


@dataclass(frozen=True)
class Exercise:
    name: str
    sets: tuple[PlannedSet, ...] = ()
    kind: str = ""  # one of KINDS, as Claude said; "" not known
    step: float | None = None  # its own step, when said ("bench steps are 2.5")
    id: int = 0


@dataclass(frozen=True)
class Workout:
    name: str
    exercises: tuple[Exercise, ...] = ()
    id: int = 0


@dataclass(frozen=True)
class DoneSet:
    """A set as it was done (or not): reps None is planned but not done."""

    exercise: str
    set_type: str = WORKING
    purpose: str = ""
    category: str = ""
    low: int | None = None
    high: int | None = None
    reps: int | None = None
    weight: float | None = None  # kg; per hand when per_hand
    per_hand: bool = False
    position: int = 0
    id: int = 0
    note: str = ""  # that set's own note, typed after its numbers ("60 x 8 felt heavy"), or a box that couldn't be read
    look: bool = False  # a box of it could not be read: kept as its note, and its card says to look at it

    @property
    def done(self) -> bool:
        return self.reps is not None


@dataclass(frozen=True)
class Note:
    exercise: str
    text: str
    pain: bool = False  # Claude: it speaks of pain or discomfort
    target_low: float | None = None  # Claude: a weight it says to go to ("go up to 40-45kg next week")
    target_high: float | None = None
    body_part: str = ""  # Claude: where the pain is, when it speaks of pain ("shoulder")


# --- reading values --------------------------------------------------------------------------------------------
_SPACES = re.compile(r"\s+")
_BRACKETED = re.compile(r"\s*\(([^)]*)\)\s*")


def tidy(name: str) -> str:
    """A name with its spacing put right: one space between words, none inside brackets' edges, a capital first."""
    said = _SPACES.sub(" ", str(name or "")).strip()
    said = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", said))
    said = re.sub(r"\s*-\s*", " - ", said) if " - " in said or re.search(r"\s-\S|\S-\s", said) else said
    return said[:1].upper() + said[1:]


def split_exercise(cell: str, set_types: dict[str, str] | None = None) -> tuple[str, str | None]:
    """ "Bench press (warm-up)" -> ("Bench press", the set type the bracket means, when Claude said so). A bracket
    that is not a set type ("(high foot)") is part of the name. `set_types` is Claude's reading of each bracket."""
    set_types = set_types or {}
    name, kind = str(cell or ""), None
    for found in _BRACKETED.finditer(name):
        meant = set_types.get(found[1].strip().lower())
        if meant in SET_TYPES:
            kind = meant
            name = name.replace(found[0], " ")
    return tidy(name), kind


_RANGE = re.compile(r"^\s*(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\s*$")
_ONE = re.compile(r"^\s*(\d{1,3})\s*$")


def reps_range(cell) -> tuple[int | None, int | None]:
    """ "5-8" -> (5, 8); "12" -> (12, 12); anything else (None, None)."""
    text = str(cell or "")
    if found := _RANGE.match(text):
        low, high = sorted((int(found[1]), int(found[2])))
        return low, high
    if found := _ONE.match(text):
        return int(found[1]), int(found[1])
    return None, None


def reps(cell) -> int | None:
    found = _ONE.match(str(cell or ""))
    return int(found[1]) if found and int(found[1]) <= MAX_REPS else None


_WEIGHT = re.compile(r"^\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(kg|kgs|s)?\s*$", re.IGNORECASE)


def weight(cell) -> tuple[float | None, bool]:
    """ "40kg" -> (40.0, False); "14s" (dumbbells, as said) -> (14.0, True); "" -> (None, False)."""
    found = _WEIGHT.match(str(cell or ""))
    if not found:
        return None, False
    value = float(found[1].replace(",", "."))
    return (value if value <= MAX_WEIGHT else None), (found[2] or "").lower() == "s"


_RESULT = re.compile(r"^\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(kg|s)?\s*(?:x|×|\*|for)\s*(\d{1,3})\s*$", re.IGNORECASE)
_RESULT_REPS_FIRST = re.compile(r"^\s*(\d{1,3})\s*(?:@|at)\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(kg|s)?\s*$", re.IGNORECASE)


def result(cell) -> tuple[float | None, int | None, bool]:
    """A set as typed in the form or a cell: "40 x 9", "40kg × 9", "14s for 10", "9 @ 40", or reps alone "9"
    (no weight said): (weight, reps, per hand)."""
    text = str(cell or "").strip()
    if found := _RESULT.match(text):
        return float(found[1].replace(",", ".")), int(found[3]), (found[2] or "").lower() == "s"
    if found := _RESULT_REPS_FIRST.match(text):
        return float(found[2].replace(",", ".")), int(found[1]), (found[3] or "").lower() == "s"
    return None, reps(text), False


# One box of the Log form, a set: "60 x 8", "60kg × 8", "60*8 felt heavy", "14s for 10", "8" (reps alone, for a
# bodyweight move). Only numbers and their units are read; whatever follows them is that set's own note
_BOX = re.compile(r"^\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(kgs?|s)?\s*(?:x|×|\*|for)\s*(\d{1,3})(?:\s*reps?)?\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
_BOX_REPS = re.compile(r"^\s*(\d{1,3})(?:\s*reps?)?(?![\d.,]|\s*(?:kgs?|s|x|×|\*|for|@)\b|\s*[x×*@])\s*(.*)$", re.IGNORECASE | re.DOTALL)
_NOTE_EDGE = " ,;:-–.·"


@dataclass(frozen=True)
class Typed:
    """What one set's box said: its numbers, and the rest as its note. `readable` False keeps the whole text as
    the note and reads no number from it."""

    weight: float | None = None
    reps: int | None = None
    per_hand: bool = False
    note: str = ""
    readable: bool = True


def typed_set(text: str, reps_alone: bool) -> Typed:
    """One set's box, read: weight × reps (x, X, ×, * or "for", "kg" or not), or reps alone when `reps_alone`
    (a bodyweight move), and anything after the numbers as the set's note. Nothing is ever made up: what can't
    be read is not readable, its words kept whole."""
    said = " ".join(str(text or "").split())
    found = _BOX.match(said)
    if found:
        weight_kg, reps_done = float(found[1].replace(",", ".")), int(found[3])
        if weight_kg <= MAX_WEIGHT and 0 < reps_done <= MAX_REPS:
            return Typed(weight_kg, reps_done, (found[2] or "").lower() == "s", found[4].strip(_NOTE_EDGE + " "))
        return Typed(note=said, readable=False)
    found = _BOX_REPS.match(said) if reps_alone else None
    if found and 0 < int(found[1]) <= MAX_REPS:
        return Typed(None, int(found[1]), False, found[2].strip(_NOTE_EDGE + " "))
    return Typed(note=said, readable=False)


_REPS_BOX = re.compile(r"^\s*(\d{1,3})\s*(?:reps?)?\s*$", re.IGNORECASE)


def typed_weight(text: str) -> tuple[float | None, bool, bool]:
    """The set pop-up's Weight box: (kg, per hand, readable). "60", "60kg", "22.5", "14s" (per hand); an empty
    box is no weight (a bodyweight move), and readable. Nothing is made up from what can't be read."""
    said = " ".join(str(text or "").split())
    if not said:
        return None, False, True
    found = _WEIGHT.match(said)
    if not found or float(found[1].replace(",", ".")) > MAX_WEIGHT:
        return None, False, False
    return float(found[1].replace(",", ".")), (found[2] or "").lower() == "s", True


def typed_reps(text: str) -> tuple[int | None, bool]:
    """The set pop-up's Reps box: (reps, readable). "8", "8 reps"; an empty box is no reps, and readable."""
    said = " ".join(str(text or "").split())
    if not said:
        return None, True
    found = _REPS_BOX.match(said)
    if not found or not 0 < int(found[1]) <= MAX_REPS:
        return None, False
    return int(found[1]), True


def set_cell(each: "DoneSet | None") -> str:
    """One set on an exercise's card: "60 x 8", "8" (reps alone), "60 x ?" (a box to look at), "-" not done."""
    if each is None:
        return "-"
    if not each.done:
        return f"{each.weight:g} x ?" if each.weight is not None else "?" if each.look else "-"
    return short_set(each, spaced=True) + (" each" if each.per_hand and each.weight is not None else "")


def sets_table(cells: list[str]) -> list[str]:
    """An exercise's sets for a code block, a row a set: its number, then weight x reps, or a dash not done."""
    width = len(str(len(cells)))
    return [f"{str(number).rjust(width)}  {cell}"[:TABLE_WIDTH] for number, cell in enumerate(cells, start=1)]


def short_set(each: DoneSet, spaced: bool = False) -> str:
    """A set in a few characters, for a table cell or a label: "60x8" ("60 x 8" spaced), reps alone with no
    weight ("8"), "-" not done."""
    if not each.done:
        return "-"
    if each.weight is None:
        return str(each.reps)
    return f"{each.weight:g} x {each.reps}" if spaced else f"{each.weight:g}x{each.reps}"


def shortened(text: str, limit: int) -> str:
    """Within `limit` characters, an ellipsis where it was cut."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


TABLE_WIDTH = 32  # characters a row: what a phone shows of a code block without scrolling
_NAME_AT_LEAST = 10  # characters of an exercise's name kept before sets go on to a line of their own


def table(rows: list[tuple[str, list[str]]], width: int = TABLE_WIDTH) -> list[str]:
    """The sets as a table for a code block: a row an exercise, a column a set ("S1", "S2"…), each row within
    `width` characters. A long name is shortened with an ellipsis; sets that still don't fit go on to a line of
    their own under it, in the same columns."""
    if not rows:
        return []
    count = max(len(cells) for _, cells in rows)
    columns = [max([len(f"S{index + 1}")] + [len(cells[index]) for _, cells in rows if index < len(cells)]) for index in range(count)]
    longest = max(len(name) for name, _ in rows)
    fitting = count
    while fitting > 1 and _NAME_AT_LEAST + sum(each + 1 for each in columns[:fitting]) > width:
        fitting -= 1
    groups = [range(start, min(count, start + fitting)) for start in range(0, count, fitting)]
    # A line's first column is as wide as the widest that comes in that place on any line, so they line up
    slots = [max(columns[index] for index in range(slot, count, fitting)) for slot in range(fitting)]
    while fitting > 1 and _NAME_AT_LEAST + sum(each + 1 for each in slots) > width:
        fitting -= 1
        groups = [range(start, min(count, start + fitting)) for start in range(0, count, fitting)]
        slots = [max(columns[index] for index in range(slot, count, fitting)) for slot in range(fitting)]
    name_width = max(_NAME_AT_LEAST, min(longest, width - sum(each + 1 for each in slots)))

    def line(first: str, cells: list[str], group) -> str:
        return (first.ljust(name_width) + "".join(" " + (cells[index] if index < len(cells) else "").ljust(slots[slot]) for slot, index in enumerate(group))).rstrip()

    lines = [line("", [f"S{index + 1}" for index in range(count)], groups[0])]
    for name, cells in rows:
        for number, group in enumerate(groups):
            if number and all(index >= len(cells) for index in group):
                continue
            lines.append(line(shortened(name, name_width) if number == 0 else "", cells, group))
    return lines


def code_block(lines: list[str]) -> str:
    return "```\n" + "\n".join(lines) + "\n```" if lines else ""


_SLASHED = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")


def logbook_date(cell) -> date | None:
    """d/m/yyyy, as Alex's logbook writes it; "DNF" or anything else None (planned, not done)."""
    found = _SLASHED.match(str(cell or ""))
    if not found:
        return None
    day, month, year = int(found[1]), int(found[2]), int(found[3])
    year += 2000 if year < 100 else 0
    try:
        return date(year, month, day)
    except ValueError:
        return None


def kg(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:g} kg"


def range_text(low: int | None, high: int | None) -> str:
    if low is None:
        return "any reps"
    return f"{low}" if high in (None, low) else f"{low}-{high}"


# --- the suggested weight: double progression ---------------------------------------------------------------------
def step_of(exercise: Exercise) -> float:
    return exercise.step or STEP.get(exercise.kind, 2.5)


def round_down(value: float, step: float) -> float:
    return round(math.floor(value / step + 1e-9) * step, 2)


def estimated(weight_kg: float, reps_done: int, reps_wanted: int) -> float:
    """The weight for `reps_wanted` from a set of `reps_done` at `weight_kg` (Epley's estimate)."""
    one_rep = weight_kg * (1 + reps_done / 30)
    return one_rep / (1 + reps_wanted / 30)


@dataclass(frozen=True)
class Suggestion:
    weight: float | None
    why: str


def suggest(exercise: Exercise, last: list[DoneSet], note: Note | None = None) -> Suggestion:
    """Next time's working weight from last time's sets: up when the last to-failure set (else the last working
    one) reached the top of its range, a bigger jump when it beat the top by 5 or more (enough to land back in
    the range), a note's own target first, and the same when it fell short."""
    working = [each for each in last if each.done and each.set_type == WORKING and each.weight is not None]
    if note is not None and note.target_low is not None and note.target_low > 0:
        aim = note.target_low if note.target_high is None else note.target_low
        return Suggestion(aim, f"your note: {kg(note.target_low)}" + (f" to {kg(note.target_high)}" if note.target_high else ""))
    if not working:
        return Suggestion(None, "no working set logged yet")
    failure = [each for each in working if each.category == TO_FAILURE]
    key = (failure or working)[-1]
    step = step_of(exercise)
    if key.high is None:
        return Suggestion(key.weight, f"last {kg(key.weight)} × {key.reps}")
    if key.reps >= key.high + BIG_JUMP:
        aim = max(key.weight + step, round_down(estimated(key.weight, key.reps, key.high), step))
        return Suggestion(aim, f"last {kg(key.weight)} × {key.reps}, {key.reps - key.high} over {range_text(key.low, key.high)}: up to land in range")
    if key.reps >= key.high:
        return Suggestion(round(key.weight + step, 2), f"last {kg(key.weight)} × {key.reps}, top of {range_text(key.low, key.high)}: +{step:g}")
    return Suggestion(key.weight, f"last {kg(key.weight)} × {key.reps}, in {range_text(key.low, key.high)}: same weight")


def warm_up_weight(working: float | None, exercise: Exercise) -> float | None:
    """About half the working weight, on the exercise's step."""
    if working is None:
        return None
    return max(step_of(exercise), round_down(working / 2, step_of(exercise)))


# --- personal bests ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Best:
    exercise: str
    kind: str  # "weight" (heaviest for a target range) or "reps" (most reps at a weight)
    key: str  # the range ("5-8") or the weight ("40")
    value: float


def bests(sets: list[DoneSet]) -> dict[tuple[str, str, str], float]:
    """Every best in these sets: the heaviest weight for each target range, the most reps at each weight
    (working sets only)."""
    found: dict[tuple[str, str, str], float] = {}
    for each in sets:
        if not each.done or each.weight is None or each.set_type != WORKING:
            continue
        name = each.exercise.lower()
        if each.low is not None:
            key = (name, "weight", range_text(each.low, each.high))
            found[key] = max(found.get(key, 0.0), each.weight)
        key = (name, "reps", f"{each.weight:g}")
        found[key] = max(found.get(key, 0.0), float(each.reps))
    return found


def beaten(before: dict[tuple[str, str, str], float], today: list[DoneSet]) -> list[Best]:
    """Today's bests that beat what was there (a first time is no best)."""
    now = bests(today)
    return [Best(name, kind, key, value) for (name, kind, key), value in now.items() if (name, kind, key) in before and value > before[(name, kind, key)]]


def best_line(best: Best, names: dict[str, str]) -> str:
    shown = names.get(best.exercise, best.exercise.capitalize())
    if best.kind == "weight":
        return f"🏆 **{shown}** · heaviest for {best.key}: {kg(best.value)}"
    return f"🏆 **{shown}** · most at {best.key} kg: {int(best.value)} reps"


# --- the trend ---------------------------------------------------------------------------------------------------------
def top_set(sets: list[DoneSet]) -> DoneSet | None:
    working = [each for each in sets if each.done and each.weight is not None and each.set_type == WORKING]
    return max(working, key=lambda each: (each.weight, each.reps)) if working else None


def trend(sessions: list[tuple[date, list[DoneSet]]]) -> str:
    """ "40 kg × 9 → 42.5 × 8 → 42.5 × 10 ▲": the top working set of each session, oldest first."""
    tops = [(day, top_set(sets)) for day, sets in sessions]
    tops = [(day, each) for day, each in tops if each is not None]
    if not tops:
        return ""
    said = " → ".join(f"{each.weight:g} × {each.reps}" for _, each in tops)
    if len(tops) >= 2:
        first, last = tops[0][1], tops[-1][1]
        mark = "▲" if (last.weight, last.reps) > (first.weight, first.reps) else "▼" if (last.weight, last.reps) < (first.weight, first.reps) else "="
        said += f" {mark}"
    return said


def set_line(each: DoneSet) -> str:
    """ "40 kg × 9", "14 kg each × 10", "not done"."""
    if not each.done:
        return "not done"
    weight_said = "bodyweight" if each.weight is None else f"{each.weight:g} kg" + (" each" if each.per_hand else "")
    return f"{weight_said} × {each.reps}"


def sets_text(sets: list[DoneSet]) -> str:
    return ", ".join(set_line(each) for each in sets) or "nothing logged"
