import logging
import re
from dataclasses import asdict, replace
from datetime import date

from core import attention, cards, clock, config, database, design, summaries
from core import day as days
from core.cards import Button, Card, Field, Form
from core.errors import UserError
from tasks.gym import rules, store
from tasks.gym.rules import ICON, TASK, DoneSet, Exercise, Note, PlannedSet, Workout

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The rotation and a session: which workout is next (a queue in plan order,
# no fixed days), the workout's messages in #gym, a set logged as it is done,
# Finish (personal bests, the queue moved on), Cancel, and undo. No discord.py.
#
#   starting a workout     the next in the queue: a header, then a card an exercise
#   do Lower 2 instead     that one now; the queue's head stays next
#   skip Upper 1           to the back of the queue
#   off-plan (a 30 min run) logged as off-plan; the queue as it was
#   Finish                 the buttons go, unlogged sets not done, PBs, the workout
#                          to the back of the queue, the summary posted under; Undo
#   Cancel                 as if never started: nothing logged, the queue as it
#                          was, the messages gone, one line with Undo
#
# A workout is a header (its name, how many exercises are done, Undo, Finish
# and Cancel) and a card an exercise, each its own message, edited in place:
# nothing else is posted while it is open. An exercise's card reads from
# reference to today: its name, the plan, last time's sets, then today's sets
# as a table with a row a planned set from the start (so the card never grows
# as sets are logged), and a button a set ("1", "2"…, "✅ 60 x 8" once logged,
# to put it right) and Note. A set's button opens a pop-up for that one set:
# Weight (kg), Reps and Note, every box empty, last time's numbers in the labels.
# ---------------------------------------------------------------------------
LOG, LOGGED, NOTE, NOTED, FINISH, UNDO, UNDO_LAST, CANCEL = "log", "logged", "note", "noted", "finish", "undo", "undo_last", "cancel"
NO_PLAN_SETS = 3  # rows and buttons for an exercise with no planned sets (one done instead)
MOST_SETS = 20  # buttons a card holds: four rows of five, and Note
NOTE_ON_CARD = 64  # characters of a note on the card: about a line on a phone
LAST_ON_CARD = 120  # characters of last time's sets: two lines on a phone at most
LABEL = 45  # characters of a pop-up box's label (Discord's limit)


def gym_channel() -> int | None:
    return config.CHANNELS.get("gym")


def changed(user_id: int) -> None:
    summaries.changed(TASK, user_id)
    attention.changed()


# --- the queue -------------------------------------------------------------------------------------------------------------
def queue_now(queue: list[int], plan: list[Workout]) -> list[Workout]:
    """The queue as workouts, those gone from the plan left out and any new ones at the back."""
    by_id = {each.id: each for each in plan}
    found = [by_id[each] for each in queue if each in by_id]
    return found + [each for each in plan if each not in found]


def moved_to_back(queue: list[int], workout_id: int) -> list[int]:
    return [each for each in queue if each != workout_id] + [workout_id]


async def next_workout(user_id: int) -> Workout | None:
    plan = await store.plan(user_id)
    queue = queue_now(await database.run(store.db_queue, user_id), plan)
    return queue[0] if queue else None


def find_workout(plan: list[Workout], said: str) -> Workout:
    from core import names

    try:
        return names.find(plan, said, lambda each: each.name)
    except names.Unknown:
        raise UserError(f"{ICON} There is no workout “{said}” in your plan.")
    except names.Ambiguous as many:
        raise UserError(f"{ICON} “{said}” could be {' or '.join(f'**{each.name}**' for each in many.candidates[:4])}: say which.")


def find_exercise(exercises: list[Exercise], said: str) -> Exercise | None:
    """Which of the plan's exercises the words mean: the whole name, then part of one (core/names.py), then the
    same with each word's plural taken off ("laterals" is Lateral raise). A nickname ("RDLs") is Claude's to
    hand over as the plan names it."""
    from core import names

    for wanted in (said, " ".join(word[:-1] if len(word) > 3 and word.lower().endswith("s") else word for word in str(said).split())):
        try:
            return names.find(exercises, wanted, lambda each: each.name)
        except (names.Unknown, names.Ambiguous, names.Unnamed):
            continue
    return None


# --- what last time was -----------------------------------------------------------------------------------------------------
async def last_time(user_id: int, exercise: str, before_session: int | None = None) -> tuple[date | None, list[DoneSet], Note | None]:
    history = await database.run(store.db_exercise_history, user_id, [exercise], before_session)
    if not history:
        return None, [], None
    session, sets = history[-1]
    notes = [each for each in await database.run(store.db_notes, session.id) if each.exercise.lower() == exercise.lower()]
    return session.day, sets, (notes[-1] if notes else None)


def by_position(sets: list[DoneSet]) -> dict[int, DoneSet]:
    """Today's sets by the set of the exercise each one was (0 the first); in the order logged when that wasn't kept."""
    found = {each.position: each for each in sets}
    return found if len(found) == len(sets) else dict(enumerate(sets))


def in_order(sets: list[DoneSet]) -> dict[int, DoneSet]:
    """Another session's sets of one exercise, its first set 0: a logbook's numbers its sets across the session."""
    return dict(enumerate(sorted(sets, key=lambda each: (each.position, each.id))))


# --- an exercise and its sets -----------------------------------------------------------------------------------------------
async def exercises_of(session: store.Session) -> list[Exercise]:
    """The session's exercises: its workout's, with today's swaps; an off-plan session's as logged."""
    plan = await store.plan(session.user_id)
    workout = next((each for each in plan if each.id == session.workout_id), None)
    swaps = await database.run(store.db_swaps, session.id)
    found = list(workout.exercises) if workout else []
    found = [replace(each, name=swaps.get(each.name.lower(), each.name)) for each in found]
    logged = await database.run(store.db_sets, session.id)
    for each in logged:
        if each.exercise.lower() not in [one.name.lower() for one in found]:
            found.append(Exercise(each.exercise, ()))
    return found


def mine(sets: list[DoneSet], name: str) -> list[DoneSet]:
    return [each for each in sets if each.exercise.lower() == name.lower()]


def set_count(exercise: Exercise, sets: list[DoneSet] = ()) -> int:
    """The rows (and set buttons) an exercise's card has: a planned set each, from the start; more only when more
    were logged (in words)."""
    return min(MOST_SETS, max([len(exercise.sets) or NO_PLAN_SETS, *(each + 1 for each in by_position(list(sets)))]))


def logged_well(each: DoneSet | None) -> bool:
    return each is not None and each.done and not each.look


def complete(exercise: Exercise, sets: list[DoneSet]) -> bool:
    """Every planned set logged and read (any set at all, for one with none planned)."""
    found = by_position(sets)
    if not exercise.sets:
        return any(logged_well(each) for each in found.values())
    return all(logged_well(found.get(index)) for index in range(len(exercise.sets)))


def plan_text(exercise: Exercise) -> str:
    """The plan in a few words: "3 sets · 8-10 reps"; "1 warm-up 8-10 · 2 working 4-6 reps" when they differ."""
    groups: list[list] = []
    for each in exercise.sets:
        key = (each.set_type, rules.range_text(each.low, each.high))
        if groups and groups[-1][0] == key:
            groups[-1][1] += 1
        else:
            groups.append([key, 1])
    if not groups:
        return "No sets planned"
    if len({reps for (_, reps), _ in groups}) == 1 and len({kind for (kind, _), _ in groups}) == 1:
        (_, reps), count = groups[0][0], len(exercise.sets)
        return f"{count} set{'' if count == 1 else 's'}" + (f" · {reps} reps" if reps else "")
    return " · ".join(f"{count} {kind}" + (f" {reps}" if reps else "") for (kind, reps), count in groups) + " reps"


def last_text(day: date | None, last: list[DoneSet]) -> str:
    """Last session's sets of this exercise, with its day: "Last · Mon 26 Oct · 60 x 8, 60 x 8"; "First time"."""
    if day is None or not last:
        return "First time"
    return rules.shortened(f"Last · {day:%a} {day.day} {day:%b} · " + ", ".join(rules.set_cell(each) for each in in_order(last).values()), LAST_ON_CARD)


def notes_lines(name: str, sets: list[DoneSet], note: Note | None, named: bool = True, order=by_position) -> list[str]:
    """Small lines under a table: each set's own note (a set to look at first said so), then the exercise's."""
    head = f"{name} · " if named else ""
    lines = []
    for index, each in sorted(order(sets).items()):
        if each.look:
            lines.append(design.small(rules.shortened(f"⚠️ {head}set {index + 1} needs a look" + (f": “{each.note}”" if each.note else ": no reps"), NOTE_ON_CARD)))
        elif each.note:
            lines.append(design.small(rules.shortened(f"{head}set {index + 1}: {each.note}", NOTE_ON_CARD)))
    if note is not None:
        lines.append(design.small(rules.shortened(("⚠️ " if note.pain else "") + f"{head}“{note.text}”", NOTE_ON_CARD)))
    return lines


def set_buttons(session: store.Session, index: int, exercise: Exercise, sets: list[DoneSet]) -> list[design.Row]:
    """A button a set, "1", "2"…, then Note; a logged set's button shows it ("✅ 60 x 8") and opens it again to
    put it right. Five to a row."""
    found = by_position(sets)
    buttons = []
    for position in range(set_count(exercise, sets)):
        each = found.get(position)
        if each is None or (not each.done and not each.look and each.weight is None):
            buttons.append(Button(str(position + 1), TASK, LOG, f"{session.id}:{index}:{position}", style=cards.PRIMARY))
        else:
            buttons.append(Button(rules.set_cell(each), TASK, LOG, f"{session.id}:{index}:{position}", emoji="✅" if logged_well(each) else "⚠️", style=cards.PRIMARY))
    buttons.append(Button("Note", TASK, NOTE, f"{session.id}:{index}", style=cards.PRIMARY))
    return [design.Row(tuple(buttons[at:at + design.MAX_BUTTONS_IN_ROW])) for at in range(0, len(buttons), design.MAX_BUTTONS_IN_ROW)]


async def exercise_card(session: store.Session, index: int, exercise: Exercise, sets: list[DoneSet], note: Note | None) -> Card:
    """One exercise's card: name, plan, last time, then today's sets as a table (a row a set from the start), its
    notes small under it, and its buttons while the workout is open. Purple, green once every set is logged."""
    day, last, last_note = await last_time(session.user_id, exercise.name, session.id)
    found = by_position(sets)
    cells = [rules.set_cell(found.get(position)) for position in range(set_count(exercise, sets))]
    from tasks.gym import pain

    lines = [design.card_title(exercise.name), design.small(plan_text(exercise)), design.small(last_text(day, last))]
    if last and last_note is not None and last_note.pain:
        lines.append(design.small(rules.shortened(f"⚠️ Last time: “{last_note.text}”", NOTE_ON_CARD)))  # pain comes up again
    lines += [design.small(each) for each in pain.pattern(exercise.name, await pain.flags(session.user_id, exercise.name))]
    lines.append(rules.code_block(rules.sets_table(cells)))
    lines += notes_lines(exercise.name, sets, note, named=False)
    children = [design.Text("\n".join(lines))]
    if session.status == store.OPEN:
        children += set_buttons(session, index, exercise, sets)
    status = design.DONE if complete(exercise, sets) else design.PREPARED
    text = "\n".join([f"{exercise.name}", *rules.sets_table(cells)])
    return Card(text, (), design.fit((design.Box(status, tuple(children)),)))


# --- the header -----------------------------------------------------------------------------------------------------------------
def title_of(session: store.Session, icon: str = ICON) -> str:
    return f"{icon} {session.name}" + (f" · session {session.number}" if session.number else "")


def undo_button(undo_id: int | None, action: str = UNDO, arg: str | None = None) -> Button:
    """Undo, greyed out when there is nothing to take back: it is always in the same place."""
    return Button("Undo", TASK, action, arg if arg is not None else str(undo_id or 0), emoji="↩️", style=cards.PRIMARY, disabled=not undo_id)


async def notes_today(session: store.Session) -> dict[str, Note]:
    return {each.exercise.lower(): each for each in await database.run(store.db_notes, session.id)}


async def header_card(session: store.Session) -> Card:
    """The workout's name, how many exercises are done, and Undo, Finish and Cancel while it is open."""
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    done = sum(1 for each in exercises if complete(each, mine(logged, each.name)))
    progress = f"{done} of {len(exercises)} exercise{'' if len(exercises) == 1 else 's'} done"
    lines = [design.page_title(title_of(session)), design.small(f"{session.day:%a} {session.day.day} {session.day:%b} · " + (progress if session.status == store.OPEN else f"finished · {progress}"))]
    children = [design.Text("\n".join(lines))]
    if session.status == store.OPEN:
        last = await database.run(store.db_last_session_undo, session.id)
        children.append(design.Row((undo_button(last, UNDO_LAST, str(session.id)), Button("Finish", TASK, FINISH, str(session.id), emoji="🏁", style=cards.SUCCESS),
                                    cards.cancel(TASK, CANCEL, str(session.id)))))
    status = design.PREPARED if session.status == store.OPEN else design.DONE
    return Card(f"{title_of(session)} · {progress}", (), design.fit((design.Box(status, tuple(children)),)))


# --- drawing: every message edited in place ---------------------------------------------------------------------------------------
async def _put(session: store.Session, message_id: int | None, card: Card) -> int | None:
    """A message brought up to date in place; posted (again) if it has gone. Its id."""
    if session.channel_id and message_id and await cards.edit(session.channel_id, message_id, card):
        return message_id
    channel_id = session.channel_id or gym_channel()
    if channel_id is None:
        return None
    return await cards.send(channel_id, card, silent=True)


async def draw_header(session: store.Session) -> None:
    placed = await _put(session, session.message_id, await header_card(session))
    if placed is not None and placed != session.message_id:
        await database.run(store.db_placed, session.id, session.channel_id or gym_channel(), placed)


async def draw_exercise(session: store.Session, index: int, exercises: list[Exercise] | None = None) -> None:
    exercises = exercises if exercises is not None else await exercises_of(session)
    if not 0 <= index < len(exercises):
        return
    exercise = exercises[index]
    logged = await database.run(store.db_sets, session.id)
    note = (await notes_today(session)).get(exercise.name.lower())
    ids = list(session.cards.get("exercises", []))
    placed = await _put(session, ids[index] if index < len(ids) else None, await exercise_card(session, index, exercise, mine(logged, exercise.name), note))
    if placed is not None and (index >= len(ids) or ids[index] != placed):
        now = await database.run(store.db_session, session.id)
        ids = list(now.cards.get("exercises", []))
        ids += [None] * (index + 1 - len(ids))
        ids[index] = placed
        await database.run(store.db_set_cards, session.id, {**now.cards, "exercises": ids})


async def draw(session: store.Session) -> None:
    """The header and every exercise's card brought up to date in place; on a start, posted in order."""
    session = await database.run(store.db_session, session.id) or session
    if gym_channel() is None and not session.channel_id:
        return
    await draw_header(session)
    exercises = await exercises_of(session)
    for index in range(len(exercises)):
        await draw_exercise(await database.run(store.db_session, session.id), index, exercises)


async def draw_one(session: store.Session, name: str) -> None:
    """One exercise's card and the header, after a change to that exercise."""
    session = await database.run(store.db_session, session.id) or session
    exercises = await exercises_of(session)
    index = next((at for at, each in enumerate(exercises) if each.name.lower() == name.lower()), None)
    if index is None or index >= len(session.cards.get("exercises", [])):
        await draw(session)
        return
    await draw_exercise(session, index, exercises)
    await draw_header(session)


async def _remove(session: store.Session) -> None:
    """The header and every exercise's card deleted (a cancelled workout's; they come back with its Undo)."""
    for message_id in [session.message_id, *session.cards.get("exercises", [])]:
        if session.channel_id and message_id:
            await cards.delete(session.channel_id, message_id)
    await database.run(store.db_placed, session.id, session.channel_id, None)
    await database.run(store.db_set_cards, session.id, {key: value for key, value in session.cards.items() if key != "exercises"})


async def _drop(session: store.Session, key: str) -> None:
    """A message of the workout's own deleted (its summary, its cancelled line), once an undo has taken it back."""
    now = await database.run(store.db_session, session.id)
    if now is None or not now.cards.get(key):
        return
    if now.channel_id:
        await cards.delete(now.channel_id, now.cards[key])
    await database.run(store.db_set_cards, now.id, {name: value for name, value in now.cards.items() if name != key})


async def _post(session: store.Session, key: str, card: Card) -> None:
    channel_id = session.channel_id or gym_channel()
    message_id = await cards.send(channel_id, card, silent=True) if channel_id else None
    if message_id is not None:
        now = await database.run(store.db_session, session.id)
        await database.run(store.db_set_cards, session.id, {**now.cards, key: message_id})


# --- starting -------------------------------------------------------------------------------------------------------------------
async def start(user_id: int, workout: Workout | None = None, day: date | None = None) -> store.Session:
    """A session of `workout` (the next in the queue unless said): its header and a card an exercise in #gym.
    One open session at a time: one left open is finished first, as it stands."""
    if gym_channel() is None:
        raise UserError(f"{ICON} There is no #gym channel set (GYM_CHANNEL_ID).")
    workout = workout or await next_workout(user_id)
    if workout is None:
        raise UserError(f"{ICON} You have no gym plan yet: send your logbook (a CSV or XLSX) to import it.")
    left = await database.run(store.db_open_session, user_id)
    if left is not None:
        await finish(left, quietly=True)
    session_id = await database.run(store.db_add_session, user_id, workout.id, workout.name, day or days.today(), store.OPEN, clock.now())
    await draw(await database.run(store.db_session, session_id))
    changed(user_id)
    return await database.run(store.db_session, session_id)


async def skip(user_id: int, workout: Workout) -> list[Workout]:
    """To the back of the queue; the new order."""
    plan = await store.plan(user_id)
    queue = moved_to_back([each.id for each in queue_now(await database.run(store.db_queue, user_id), plan)], workout.id)
    await database.run(store.db_set_queue, user_id, queue, clock.now())
    changed(user_id)
    return queue_now(queue, plan)


async def off_plan(user_id: int, what: str, day: date) -> int:
    """Something else done (a 30 min run): logged as off-plan; the queue as it was."""
    session_id = await database.run(store.db_add_session, user_id, None, what[:1].upper() + what[1:], day, store.OFF_PLAN, clock.now(), "live", what)
    changed(user_id)
    return session_id


# --- a set's pop-up ---------------------------------------------------------------------------------------------------------------
def box_label(name: str, now: str | None, last: str | None) -> str:
    """ "Weight (kg) · last 60"; "· now 62.5" first when the set is being put right; within what a label holds."""
    for label in (f"{name}" + (f" · now {now}" if now else "") + (f" · last {last}" if last else ""), f"{name}" + (f" · last {last}" if last else ""), name):
        if len(label) <= LABEL:
            return label
    return name[:LABEL]


def _weight_said(each: DoneSet | None) -> str | None:
    return None if each is None or each.weight is None else f"{each.weight:g}" + (" each" if each.per_hand else "")


async def set_form(session: store.Session, index: int, exercise: Exercise, position: int) -> Form:
    """One set's pop-up: Weight (kg), Reps and Note, every box empty (nothing to delete before typing), last
    session's numbers for this same set in the labels, and today's when it is being put right."""
    _, last, _ = await last_time(session.user_id, exercise.name, session.id)
    previous = in_order(last).get(position)
    previous = previous if previous is not None and previous.done else None
    now = by_position(mine(await database.run(store.db_sets, session.id), exercise.name)).get(position)
    fields = (
        Field("weight", box_label("Weight (kg)", _weight_said(now), _weight_said(previous)), required=False),
        Field("reps", box_label("Reps", str(now.reps) if now is not None and now.reps is not None else None, str(previous.reps) if previous is not None else None), required=False),
        Field("note", "Note", required=False),
    )
    tail = f" · set {position + 1}"
    return Form(rules.shortened(exercise.name, cards.MAX_FORM_TITLE - len(tail)) + tail, TASK, LOGGED, fields, arg=f"{session.id}:{index}:{position}")


def read_set(fields: dict[str, str], planned: DoneSet) -> DoneSet | None:
    """What was typed in a set's pop-up, read by Python: the weight (empty for a bodyweight move) and the reps. A
    box that can't be read is kept as the set's note, nothing made up from it, and the set marked to look at, as
    it is with no reps. None when every box is empty."""
    weight_text, reps_text, note_text = (" ".join(str((fields or {}).get(key) or "").split()) for key in ("weight", "reps", "note"))
    if not (weight_text or reps_text or note_text):
        return None
    weight_kg, per_hand, weight_ok = rules.typed_weight(weight_text)
    reps_done, reps_ok = rules.typed_reps(reps_text)
    unread = [text for text, ok in ((weight_text, weight_ok), (reps_text, reps_ok)) if not ok]
    return replace(planned, weight=weight_kg, per_hand=per_hand, reps=reps_done, note=" · ".join([*unread, *([note_text] if note_text else [])]), look=bool(unread) or reps_done is None)


def planned_set(exercise: Exercise, position: int) -> DoneSet:
    each = exercise.sets[position] if position < len(exercise.sets) else PlannedSet()
    return DoneSet(exercise.name, each.set_type, each.purpose, each.category, each.low, each.high, position=position)


def reps_alone(exercise: Exercise, last: list[DoneSet]) -> bool:
    """Whether reps typed alone are a set: for a bodyweight move, or one never logged with a weight."""
    if exercise.kind == rules.BODYWEIGHT:
        return True
    return exercise.kind == "" and not any(each.weight is not None for each in last)


def read_form(fields: dict[str, str], exercise: Exercise, alone: bool = False) -> tuple[list[DoneSet], list[int]]:
    """A pop-up opened before the card an exercise (a box a set, "60 x 8", or one long box a line a set): its
    numbers read by Python, anything after them the set's note. An empty box is a set not done; one that can't
    be read is kept whole as its note, with no number made up, and its number (1 the first) is in the second list."""
    typed = {int(key[3:]): str(value or "") for key, value in fields.items() if re.fullmatch(r"set\d+", key)}
    if "sets" in fields:
        typed = dict(enumerate(str(fields["sets"]).splitlines()))
    found, look = [], []
    for index, text in sorted(typed.items()):
        if not text.strip():
            continue
        planned = planned_set(exercise, index)
        said = rules.typed_set(text, alone)
        if said.readable:
            found.append(replace(planned, reps=said.reps, weight=said.weight, per_hand=said.per_hand, note=said.note))
        else:
            found.append(replace(planned, note=said.note, look=True))
            look.append(index + 1)
    return found, look


async def read_note(exercise: str, text: str) -> Note:
    """What a note means (pain, per hand, a target weight), read by Claude: one small request."""
    from tasks.gym import importer

    meant = (await importer.ask_meanings([], [], [], [text])).notes.get(text, {})
    return Note(exercise, text, bool(meant.get("pain")), importer._number(meant.get("target_low")), importer._number(meant.get("target_high")), str(meant.get("body_part") or "") if meant.get("pain") else "")


async def log_sets(session: store.Session, exercise: str, sets: list[DoneSet], note: Note | None, replace_logged: bool = True, part=None) -> int:
    """Sets (and a note) for one exercise of a session, each its own row with when it was logged, in place of
    what was logged for it (with `part`, for those sets of it only); an undo's id."""
    before = [each for each in await database.run(store.db_sets, session.id) if each.exercise.lower() == exercise.lower() and (part is None or each.position in part)]
    if replace_logged and before:
        await database.run(store.db_delete_sets, [each.id for each in before])
    ids = await database.run(store.db_add_sets, session.user_id, session.id, sets, clock.now())
    note_ids = [await database.run(store.db_add_note, session.user_id, session.id, note)] if note is not None else []
    payload = {"session": session.id, "exercise": exercise, "sets": ids, "notes": note_ids, "restore": [asdict(each) for each in before] if replace_logged else []}
    undo_id = await database.run(store.db_remember, session.user_id, "log", payload, clock.now())
    if sets or note is not None:
        from tasks.gym import sheet

        await sheet.mirror(session, sets, note)
    return undo_id


def _exercise(exercises: list[Exercise], name: str) -> Exercise | None:
    """The exercise an old button or form names: its id holds the name, cut short when the name is long."""
    return next((each for each in exercises if each.name.lower() == name), None) or next((each for each in exercises if name and each.name.lower().startswith(name)), None)


async def _open_session(press: cards.Press, session_id: str) -> store.Session:
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None or session.status != store.OPEN:
        raise UserError("That workout is finished: say what you did in words to add to it.")
    return session


def _where(arg: str) -> tuple[str, str, str]:
    """(the session, the exercise, the set) from a button's or pop-up's arg: "4:1:0"."""
    parts = arg.split(":", 2)
    return (parts + ["", "", ""])[0], (parts + ["", ""])[1], (parts + ["", "", ""])[2]


async def on_log(press: cards.Press) -> str:
    """A set's button: its pop-up. (A Log button from before the card an exercise names the exercise: its first
    set not logged.)"""
    session_id, which, position = _where(press.arg)
    session = await _open_session(press, session_id)
    exercises = await exercises_of(session)
    if which.isdigit() and position.isdigit() and int(which) < len(exercises):
        index, exercise, at = int(which), exercises[int(which)], int(position)
    else:
        exercise = _exercise(exercises, press.arg.partition(":")[2])
        if exercise is None:
            raise UserError("That exercise is not in this workout any more.")
        index = exercises.index(exercise)
        found = by_position(mine(await database.run(store.db_sets, session.id), exercise.name))
        at = next((each for each in range(set_count(exercise)) if not logged_well(found.get(each))), 0)
    await press.open_form(await set_form(session, index, exercise, at))
    return f"set {at + 1} pop-up opened"


async def on_logged(press: cards.Press) -> str:
    """A set's pop-up sent: that set logged (or put right), and only its exercise's card and the header redrawn.
    Nothing else is posted."""
    fields = press.fields or {}
    if not {"weight", "reps"} & set(fields):
        return await _on_old_form(press)
    session_id, which, position = _where(press.arg)
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None:
        raise UserError("That workout has gone.")
    exercises = await exercises_of(session)
    if not (which.isdigit() and position.isdigit() and int(which) < len(exercises)):
        raise UserError("That exercise is not in this workout any more.")
    exercise, at = exercises[int(which)], int(position)
    typed = read_set(fields, planned_set(exercise, at))
    there = by_position(mine(await database.run(store.db_sets, session.id), exercise.name)).get(at)
    if typed is None and there is None:
        return "nothing typed"
    await log_sets(session, exercise.name, [typed] if typed is not None else [], None, part={at})
    await draw_one(session, exercise.name)
    changed(session.user_id)
    if typed is None:
        return f"set {at + 1} cleared"
    return f"set {at + 1} kept to look at" if typed.look else f"set {at + 1} logged: {rules.set_cell(typed)}"


async def _on_old_form(press: cards.Press) -> str:
    """A pop-up opened before the card an exercise and sent after (a box a set): read as it was then."""
    session_id, _, rest = press.arg.partition(":")
    start, _, name = rest.partition(":")
    name = name if start.isdigit() and name else rest
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None:
        raise UserError("That workout has gone.")
    exercise = _exercise(await exercises_of(session), name)
    if exercise is None:
        raise UserError("That exercise is not in this workout any more.")
    _, last, _ = await last_time(session.user_id, exercise.name, session.id)
    found, look = read_form(press.fields or {}, exercise, reps_alone(exercise, last))
    note_text = str((press.fields or {}).get("note") or "").strip()
    if not found and not note_text:
        return "nothing typed"
    note = await read_note(exercise.name, note_text) if note_text else None
    await log_sets(session, exercise.name, found, note, part={each.position for each in found})
    await draw_one(session, exercise.name)
    changed(session.user_id)
    return f"logged {sum(1 for each in found if each.done)} sets" + (f", {len(look)} to look at" if look else "")


# --- an exercise's note ------------------------------------------------------------------------------------------------------------
async def on_note(press: cards.Press) -> str:
    session_id, which, _ = _where(press.arg)
    session = await _open_session(press, session_id)
    exercises = await exercises_of(session)
    if not which.isdigit() or int(which) >= len(exercises):
        raise UserError("That exercise is not in this workout any more.")
    exercise = exercises[int(which)]
    now = (await notes_today(session)).get(exercise.name.lower())
    label = box_label("Note", rules.shortened(now.text, 24) if now else None, None)
    tail = " · note"
    await press.open_form(Form(rules.shortened(exercise.name, cards.MAX_FORM_TITLE - len(tail)) + tail, TASK, NOTED, (Field("note", label, required=False, long=True),), arg=f"{session.id}:{which}"))
    return "note pop-up opened"


async def set_note(session: store.Session, exercise: str, text: str) -> int | None:
    """The exercise's note today, in place of the one there was (read by Claude for pain); empty takes it off. An
    undo's id, None when nothing changed."""
    before = await database.run(store.db_exercise_note_rows, session.id, exercise)
    if not text and not before:
        return None
    await database.run(store.db_delete_notes, [note_id for note_id, _ in before])
    ids = [await database.run(store.db_add_note, session.user_id, session.id, await read_note(exercise, text))] if text else []
    payload = {"session": session.id, "exercise": exercise, "notes": ids, "restore": [asdict(note) for _, note in before]}
    return await database.run(store.db_remember, session.user_id, "note", payload, clock.now())


async def on_noted(press: cards.Press) -> str:
    session_id, which, _ = _where(press.arg)
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None:
        raise UserError("That workout has gone.")
    exercises = await exercises_of(session)
    if not which.isdigit() or int(which) >= len(exercises):
        raise UserError("That exercise is not in this workout any more.")
    exercise = exercises[int(which)]
    text = " ".join(str((press.fields or {}).get("note") or "").split())
    if await set_note(session, exercise.name, text) is None:
        return "nothing typed"
    await draw_one(session, exercise.name)
    changed(session.user_id)
    return "note kept" if text else "note taken off"


# --- Finish ---------------------------------------------------------------------------------------------------------------------
async def finish(session: store.Session, quietly: bool = False) -> tuple[str, int]:
    """End a session: every planned set not logged is not done; personal bests; the workout to the back of the
    queue; the buttons taken off the header and every card, and the summary posted under them, with Undo. The
    summary's words and an undo's id."""
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    missing = [planned_set(each, index) for each in exercises for index in range(len(each.sets)) if index not in by_position(mine(logged, each.name))]
    missing_ids = await database.run(store.db_add_sets, session.user_id, session.id, missing) if missing else []
    before = await database.run(store.db_bests, session.user_id)
    beaten = rules.beaten(before, logged)
    await database.run(store.db_put_bests, session.user_id, rules.bests(logged), session.id)
    await database.run(store.db_set_status, session.id, store.FINISHED, clock.now())
    queue_before = await database.run(store.db_queue, session.user_id)
    if session.workout_id is not None:
        plan = await store.plan(session.user_id)
        await database.run(store.db_set_queue, session.user_id, moved_to_back([each.id for each in queue_now(queue_before, plan)], session.workout_id), clock.now())
    undo_id = await database.run(store.db_remember, session.user_id, "finish", {"session": session.id, "missing": missing_ids, "queue": queue_before}, clock.now())
    finished = await database.run(store.db_session, session.id)
    await draw(finished)
    names = {each.exercise.lower(): each.exercise for each in logged}
    best_lines = [rules.best_line(each, names) for each in beaten]
    summary = await summary_text(finished, await database.run(store.db_sets, session.id))
    await _post(finished, "summary", summary_card(summary, best_lines, undo_id))
    changed(session.user_id)
    return "\n".join([summary, *best_lines]), undo_id


def summary_card(summary: str, best_lines: list[str], undo_id: int | None) -> Card:
    """The summary posted under a finished workout's cards: every exercise and every set, its PBs, and Undo."""
    lines = summary.splitlines()
    shown = [design.page_title(lines[0].replace("**", "")), *lines[1:], *best_lines]
    children = [design.Text("\n".join(shown))]
    if undo_id:
        children.append(design.Row((undo_button(undo_id),)))
    return Card("\n".join([lines[0], *best_lines]), (), design.fit((design.Box(design.DONE, tuple(children)),)))


def table_rows(exercises: list[Exercise], logged: list[DoneSet], every: bool = False) -> list[tuple[str, list[str]]]:
    """A row an exercise logged (`every`: every exercise, the summary), a cell a set: "60x8", "-" not done."""
    rows = []
    for exercise in exercises:
        sets = by_position(mine(logged, exercise.name))
        if not sets and not every:
            continue
        count = max([len(exercise.sets), *(each + 1 for each in sets)] or [0]) or 1
        rows.append((exercise.name, [rules.short_set(sets[index]) if index in sets else "-" for index in range(count)]))
    return rows


async def summary_text(session: store.Session, logged: list[DoneSet]) -> str:
    """The summary: a line of counts, then every exercise as a table (a dash a set not done), its notes under it."""
    exercises = await exercises_of(session)
    done = [each for each in logged if each.done]
    missing = sum(1 for each in logged if not each.done and not each.note)
    lines = [f"🏁 **{session.name}**" + (f" · session {session.number}" if session.number else ""),
             design.small(f"{session.day:%a} {session.day.day} {session.day:%b} · {len(done)} set{'' if len(done) == 1 else 's'}" + (f" · {missing} not done" if missing else "")),
             rules.code_block(rules.table(table_rows(exercises, logged, every=True)))]
    notes = await notes_today(session)
    for exercise in exercises:
        lines += notes_lines(exercise.name, mine(logged, exercise.name), notes.get(exercise.name.lower()))
    return "\n".join(line for line in lines if line)


async def on_finish(press: cards.Press) -> str:
    session = await press.db.run(store.db_session, int(press.arg)) if press.arg.isdigit() else None
    if session is None or session.status != store.OPEN:
        return "already finished"
    await finish(session)
    return "workout finished"


# --- Cancel ---------------------------------------------------------------------------------------------------------------------
async def cancel(session: store.Session) -> tuple[str, int]:
    """Cancel is an undo of Start: everything back as it was before it. Nothing of the session is logged or
    counted (what was logged in it is taken off, kept to put back), it is never numbered or done, and the queue
    is not touched, so the same workout is still next. Its header and cards are deleted and one line says so,
    with Undo."""
    sets = await database.run(store.db_sets, session.id)
    notes = await database.run(store.db_notes, session.id)
    await database.run(store.db_clear_session, session.id)
    await database.run(store.db_set_status, session.id, store.CANCELLED, clock.now())
    await database.run(store.db_rebuild_bests, session.user_id)
    payload = {"session": session.id, "sets": [asdict(each) for each in sets], "notes": [asdict(each) for each in notes]}
    undo_id = await database.run(store.db_remember, session.user_id, "cancel", payload, clock.now())
    nxt = await next_workout(session.user_id)
    taken = sum(1 for each in sets if each.done)
    said = (f"{taken} set{'' if taken == 1 else 's'} taken off, nothing logged" if taken else "nothing logged") + (f" · {nxt.name} is still next" if nxt else "")
    line = f"{ICON} **{session.name}** cancelled · {said}"
    await _remove(session)
    await _post(await database.run(store.db_session, session.id), "cancelled", Card(line, ((undo_button(undo_id),),)))
    changed(session.user_id)
    return line, undo_id


async def on_cancel(press: cards.Press) -> str:
    session = await press.db.run(store.db_session, int(press.arg)) if press.arg.isdigit() else None
    if session is None or session.status != store.OPEN:
        return "not open"
    await cancel(session)
    return "workout cancelled"


# --- undo -----------------------------------------------------------------------------------------------------------------------
async def undo(undo_id: int, user_id: int) -> str:
    found = await database.run(store.db_undo_of, undo_id)
    if found is None or found[0] != user_id:
        return "↩️ Nothing to undo"
    _, kind, payload = found
    session = await database.run(store.db_session, payload["session"])
    redraw = "all"
    if kind == "log":
        await database.run(store.db_delete_sets, payload["sets"])
        await database.run(store.db_delete_notes, payload.get("notes", []))
        if payload.get("restore"):
            await database.run(store.db_add_sets, user_id, payload["session"], [DoneSet(**each) for each in payload["restore"]])
        redraw = payload.get("exercise") or "all"
        said = "↩️ Taken back: that log"
    elif kind == "note":
        await database.run(store.db_delete_notes, payload["notes"])
        for each in payload["restore"]:
            await database.run(store.db_add_note, user_id, payload["session"], Note(**each))
        redraw = payload["exercise"]
        said = "↩️ Taken back: that note"
    elif kind == "finish":
        await database.run(store.db_delete_sets, payload["missing"])
        await database.run(store.db_set_status, payload["session"], store.OPEN, None)
        await database.run(store.db_set_queue, user_id, payload["queue"], clock.now())
        if session is not None:
            await _drop(session, "summary")
        said = "↩️ The workout is open again"
    elif kind == "cancel":
        await database.run(store.db_set_status, payload["session"], store.OPEN, None)
        await database.run(store.db_add_sets, user_id, payload["session"], [DoneSet(**each) for each in payload["sets"]])
        for each in payload["notes"]:
            await database.run(store.db_add_note, user_id, payload["session"], Note(**each))
        if session is not None:
            await _drop(session, "cancelled")
        said = "↩️ The workout is back, as it was"
    elif kind == "session":
        await database.run(store.db_delete_session, payload["session"])
        if payload.get("queue") is not None:
            await database.run(store.db_set_queue, user_id, payload["queue"], clock.now())
        session = None
        said = "↩️ Taken back: that session"
    elif kind == "queue":
        await database.run(store.db_set_queue, user_id, payload["queue"], clock.now())
        said = "↩️ The queue is as it was"
    else:
        return "↩️ Nothing to undo"
    await database.run(store.db_undone, undo_id)
    await database.run(store.db_rebuild_bests, user_id)
    now = await database.run(store.db_session, session.id) if session is not None else None
    if now is not None and now.status in (store.OPEN, store.FINISHED) and (now.message_id or now.status == store.OPEN):
        await (draw(now) if redraw == "all" else draw_one(now, redraw))
    changed(user_id)
    return said


async def on_undo(press: cards.Press) -> str:
    # Asked first: an Undo on the workout's own summary or cancelled line deletes that message
    own = press.message_id is not None and await press.db.run(store.db_session_of_message, press.message_id) is not None
    said = await undo(int(press.arg) if press.arg.isdigit() else 0, press.user.id)
    if not own:
        await press.update(Card(said))  # an Undo on a message of its own (from before 30 Oct)
    return said


async def on_undo_last(press: cards.Press) -> str:
    """The header's Undo: the latest set or note logged in this workout taken back, one a press."""
    undo_id = await press.db.run(store.db_last_session_undo, int(press.arg)) if press.arg.isdigit() else None
    if undo_id is None:
        return "nothing to undo"
    return await undo(undo_id, press.user.id)


def register() -> None:
    cards.register(TASK, LOG, on_log, opens_form=True)
    cards.register(TASK, LOGGED, on_logged)
    cards.register(TASK, NOTE, on_note, opens_form=True)
    cards.register(TASK, NOTED, on_noted)
    cards.register(TASK, FINISH, on_finish)
    cards.register(TASK, CANCEL, on_cancel)
    cards.register(TASK, UNDO, on_undo)
    cards.register(TASK, UNDO_LAST, on_undo_last)
