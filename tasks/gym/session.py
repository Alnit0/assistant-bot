import logging
import re
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta

from core import attention, cards, clock, config, database, design, summaries, timeinput
from core import day as days
from core.cards import Button, Card, Field, Form
from core.errors import UserError
from tasks.gym import rules, store
from tasks.gym.rules import ICON, TASK, DoneSet, Exercise, Note, PlannedSet, Workout

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The rotation and a session: which workout is next (a queue in plan order,
# no fixed days), the workout card in #gym, the Log form, Finish (personal
# bests, the queue moved on), Cancel, and undo. No discord.py.
#
#   starting a workout     the next in the queue, its card in #gym
#   do Lower 2 instead     that one now; the queue's head stays next
#   skip Upper 1           to the back of the queue
#   off-plan (a 30 min run) logged as off-plan; the queue as it was
#   Finish                 unlogged sets not done, the card becomes the summary
#                          with PBs, the workout to the back of the queue; Undo
#   Cancel                 as if never started: nothing logged, the queue as it
#                          was; Undo when something had been logged
#
# The workout is one card, edited in place: nothing else is posted under it, so
# it stays the last message in #gym and its buttons, all at its foot, never move
# between taps (Discord keeps a message's foot where it is when the message
# above it grows). What was logged is a table at the top; each exercise still to
# do has last time's numbers and notes small under its name; what the last press
# did is one small line over the buttons. One Log button an exercise, always
# there (✅ once logged, to put it right), then Undo, Finish and Cancel.
# ---------------------------------------------------------------------------
LOG, LOGGED, FINISH, UNDO, PICK, CANCEL = "log", "logged", "finish", "undo", "pick", "cancel"
FIRST_FORM_SETS = 4  # a form holds five boxes: the first form a box a set for four sets, and Notes
MORE_FORM_SETS = 5  # each form after it, for an exercise with more sets: five sets, no Notes
NO_PLAN_SETS = 4  # boxes for an exercise with no planned sets (one done instead)
NOTE_ON_CARD = 64  # characters of a note on the card: about a line on a phone
BUTTON_NAME = 22  # characters of an exercise's name on its button


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


# --- what last time was, and what to lift today -----------------------------------------------------------------------------
async def last_time(user_id: int, exercise: str, before_session: int | None = None) -> tuple[date | None, list[DoneSet], Note | None]:
    history = await database.run(store.db_exercise_history, user_id, [exercise], before_session)
    if not history:
        return None, [], None
    session, sets = history[-1]
    notes = [each for each in await database.run(store.db_notes, session.id) if each.exercise.lower() == exercise.lower()]
    return session.day, sets, (notes[-1] if notes else None)


async def planned_today(user_id: int, exercise: Exercise, before_session: int | None = None) -> list[tuple[rules.PlannedSet, float | None]]:
    """Each planned set with its suggested weight: double progression for the working sets, about half for warm-ups."""
    _, last, note = await last_time(user_id, exercise.name, before_session)
    suggestion = rules.suggest(exercise, last, note)
    return [(each, rules.warm_up_weight(suggestion.weight, exercise) if each.set_type == rules.WARM_UP else suggestion.weight) for each in exercise.sets]


def by_position(sets: list[DoneSet]) -> dict[int, DoneSet]:
    """Today's sets by the set of the exercise each one was (0 the first); in the order logged when that wasn't kept."""
    found = {each.position: each for each in sets}
    return found if len(found) == len(sets) else dict(enumerate(sets))


def in_order(sets: list[DoneSet]) -> dict[int, DoneSet]:
    """Another session's sets of one exercise, its first set 0: a logbook's numbers its sets across the session."""
    return dict(enumerate(sorted(sets, key=lambda each: (each.position, each.id))))


# --- the card -----------------------------------------------------------------------------------------------------------------
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


def notes_lines(name: str, sets: list[DoneSet], note: Note | None, named: bool = True, order=by_position) -> list[str]:
    """Small lines under the table: the exercise's note, then each set's own, shortened to fit a phone."""
    head = f"{name} · " if named else ""
    lines = []
    if note is not None:
        lines.append(design.small(rules.shortened(("⚠️ " if note.pain else "") + f"{head}“{note.text}”", NOTE_ON_CARD)))
    for index, each in sorted(order(sets).items()):
        if each.note:
            lines.append(design.small(rules.shortened(f"{head}set {index + 1}: {each.note}", NOTE_ON_CARD)))
    return lines


def plan_line(planned: list[tuple[rules.PlannedSet, float | None]]) -> str:
    """The planned sets in one line, alike ones together: "1 warm-up 8-10 at 40 kg · 2 working 4-6 at 82.5 kg"."""
    groups: list[list] = []
    for each, suggested in planned:
        key = (each.set_type, rules.range_text(each.low, each.high), suggested)
        if groups and groups[-1][0] == key:
            groups[-1][1] += 1
        else:
            groups.append([key, 1])
    return " · ".join(f"{count} {kind} {reps} at {rules.kg(weight) if weight else 'a weight of your choice'}" for (kind, reps, weight), count in groups)


async def to_do_text(session: store.Session, exercise: Exercise) -> str:
    """An exercise still to log: its name, the plan, and last time's numbers and notes small."""
    lines = [design.card_title(exercise.name)]
    planned = await planned_today(session.user_id, exercise, session.id)
    day, last, note = await last_time(session.user_id, exercise.name, session.id)
    if planned:
        lines.append(design.small(plan_line(planned)))
    if last:
        lines.append(design.small(rules.shortened(f"last {day:%a} {day.day} {day:%b}: " + " · ".join(rules.short_set(each) for each in in_order(last).values()), NOTE_ON_CARD)))
        why = rules.suggest(exercise, last, note).why
        if why:
            lines.append(design.small(f"why: {why}"))
        lines += notes_lines(exercise.name, last, note, named=False, order=in_order)
    else:
        lines.append(design.small("First time"))
    from tasks.gym import pain

    lines += [design.small(each) for each in pain.pattern(exercise.name, await pain.flags(session.user_id, exercise.name))]
    return "\n".join(lines)


def logged_names(logged: list[DoneSet], pending: str) -> set[str]:
    """The exercises logged in full: those with a set logged and no form still to come."""
    waiting = pending.partition(":")[2]
    return {each.exercise.lower() for each in logged if each.exercise.lower() != waiting}


def log_buttons(session: store.Session, exercises: list[Exercise], logged: list[DoneSet]) -> list[design.Row]:
    """A Log button an exercise, in the plan's order, always there: ✅ once it is logged."""
    done = logged_names(logged, session.pending)
    buttons = [Button(rules.shortened(each.name, BUTTON_NAME), TASK, LOG, f"{session.id}:{each.name.lower()}"[:90], emoji="✅" if each.name.lower() in done else "📝", style=cards.PRIMARY)
               for each in exercises]
    return [design.Row(tuple(buttons[at:at + design.MAX_BUTTONS_IN_ROW])) for at in range(0, len(buttons), design.MAX_BUTTONS_IN_ROW)]


def undo_button(undo_id: int | None) -> Button:
    """Undo, greyed out when there is nothing to take back: it is always in the same place."""
    return Button("Undo", TASK, UNDO, str(undo_id or 0), emoji="↩️", style=cards.PRIMARY, disabled=not undo_id)


def title_of(session: store.Session, icon: str = ICON) -> str:
    return f"{icon} {session.name}" + (f" · session {session.number}" if session.number else "")


async def notes_today(session: store.Session) -> dict[str, Note]:
    return {each.exercise.lower(): each for each in await database.run(store.db_notes, session.id)}


async def card(session: store.Session) -> Card:
    if session.status == store.CANCELLED:
        return cancelled_card(session)
    if session.status != store.OPEN:
        return await summary_card(session)
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    notes = await notes_today(session)
    done = logged_names(logged, session.pending)
    top = [design.page_title(title_of(session)), design.small(f"{session.day:%a} {session.day.day} {session.day:%b} · {len([each for each in exercises if each.name.lower() in done])} of {len(exercises)} logged")]
    rows = table_rows(exercises, logged)
    if rows:
        top.append(rules.code_block(rules.table(rows)))
        for exercise in exercises:
            top += notes_lines(exercise.name, mine(logged, exercise.name), notes.get(exercise.name.lower()))
    children = [design.Text("\n".join(top))]
    children += [design.Text(await to_do_text(session, each)) for each in exercises if each.name.lower() not in done]
    if session.said:
        children.append(design.Text(design.small(session.said)))
    under = design.Row((undo_button(session.undo_id), Button("Finish workout", TASK, FINISH, str(session.id), emoji="🏁", style=cards.SUCCESS), cards.cancel(TASK, CANCEL, str(session.id), label="Cancel workout")))
    pieces = (design.Box(design.PREPARED, (*children, *log_buttons(session, exercises, logged), under)),)
    if design.problem(pieces):
        # Too many for one message: the Log buttons give way to one dropdown, in the same place
        pieces = (design.Box(design.PREPARED, (*children, *_picker(session, exercises, logged), under)),)
    text = "\n".join([title_of(session), *(f"• {each.name}" for each in exercises)])
    return Card(text, (), design.fit(pieces))


def _picker(session: store.Session, exercises: list[Exercise], logged: list[DoneSet]) -> tuple:
    options = tuple(cards.Option(each.name[:100], each.name.lower()[:100], emoji="✅" if each.name.lower() in logged_names(logged, session.pending) else "📝") for each in exercises)
    if not options:
        return ()
    return (design.Row((cards.Select(TASK, PICK, options[:25], placeholder="📝 Log: pick an exercise", arg=str(session.id)),)),)


async def summary_card(session: store.Session) -> Card:
    """A finished workout: the summary in place of the card, with Undo."""
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    text = await summary_text(session, logged)
    lines = [design.page_title(title_of(session, "🏁")), *text.splitlines()[1:]]
    if session.said:
        lines.append(session.said)
    children = [design.Text("\n".join(lines))]
    if session.undo_id:
        children.append(design.Row((undo_button(session.undo_id),)))
    return Card("\n".join([title_of(session, "🏁"), *(f"• {each.name}" for each in exercises)]), (), design.fit((design.Box(design.PREPARED, tuple(children)),)))


def cancelled_card(session: store.Session) -> Card:
    lines = [design.page_title(f"{ICON} {session.name} · cancelled"), design.small(session.said or "nothing logged")]
    children = [design.Text("\n".join(lines))]
    if session.undo_id:
        children.append(design.Row((undo_button(session.undo_id),)))
    return Card(f"{ICON} {session.name} · cancelled", (), design.fit((design.Box(design.PREPARED, tuple(children)),)))


async def draw(session: store.Session) -> None:
    """The card brought up to date in place (posted again if it has gone)."""
    if session.channel_id and session.message_id and await cards.edit(session.channel_id, session.message_id, await card(session)):
        return
    channel_id = gym_channel()
    if channel_id is None:
        return
    message_id = await cards.send(channel_id, await card(session), silent=True)
    if message_id is not None:
        await database.run(store.db_placed, session.id, channel_id, message_id)


async def say_on_card(session: store.Session, said: str, undo_id: int | None) -> store.Session:
    """What the last press did, on the card's own line, with what its Undo takes back; the card drawn again."""
    await database.run(store.db_card_line, session.id, said, undo_id)
    now = await database.run(store.db_session, session.id)
    await draw(now)
    return now


# --- starting -------------------------------------------------------------------------------------------------------------------
async def start(user_id: int, workout: Workout | None = None, day: date | None = None) -> store.Session:
    """A session of `workout` (the next in the queue unless said), its card in #gym. One open session at a time:
    one left open is finished first, as it stands."""
    if gym_channel() is None:
        raise UserError(f"{ICON} There is no #gym channel set (GYM_CHANNEL_ID).")
    workout = workout or await next_workout(user_id)
    if workout is None:
        raise UserError(f"{ICON} You have no gym plan yet: send your logbook (a CSV or XLSX) to import it.")
    left = await database.run(store.db_open_session, user_id)
    if left is not None:
        await finish(left, quietly=True)
    session_id = await database.run(store.db_add_session, user_id, workout.id, workout.name, day or days.today(), store.OPEN, clock.now())
    session = await database.run(store.db_session, session_id)
    await draw(session)
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


# --- the Log form ---------------------------------------------------------------------------------------------------------------
def set_count(exercise: Exercise) -> int:
    return len(exercise.sets) or NO_PLAN_SETS


def form_part(exercise: Exercise, start: int) -> range:
    """The sets one form holds, from `start`: four and Notes in the first, five in each after it."""
    return range(start, min(set_count(exercise), start + (FIRST_FORM_SETS if start == 0 else MORE_FORM_SETS)))


def set_label(index: int, last: dict[int, DoneSet]) -> str:
    """ "Set 1 · last 60 x 8", within what a box's label holds; just "Set 1" with no last time, or no room."""
    label = f"Set {index + 1}"
    if index in last:
        with_last = f"{label} · last {rules.short_set(last[index], spaced=True) if last[index].done else 'not done'}"
        return with_last if len(with_last) <= cards.MAX_FORM_TITLE else label
    return label


async def form_for(session: store.Session, exercise: Exercise, start: int = 0) -> Form:
    """A box a set, every one empty (nothing to delete before typing), last time's numbers in its label; Notes
    for the exercise in the first form. An exercise with more sets than one form holds has its next form
    straight after, from the same button."""
    _, last, _ = await last_time(session.user_id, exercise.name, session.id)
    previous = in_order(last)
    part = form_part(exercise, start)
    fields = [Field(f"set{index}", set_label(index, previous), required=False) for index in part]
    if start == 0:
        fields.append(Field("note", "Notes", required=False, long=True))
    whole = part.start == 0 and part.stop == set_count(exercise)
    title = rules.shortened(exercise.name, cards.MAX_FORM_TITLE) if whole else rules.shortened(f"{exercise.name} · sets {part.start + 1} to {part.stop}", cards.MAX_FORM_TITLE)
    return Form(title, TASK, LOGGED, tuple(fields), arg=f"{session.id}:{start}:{exercise.name.lower()}"[:90])


def reps_alone(exercise: Exercise, last: list[DoneSet]) -> bool:
    """Whether reps typed alone are a set: for a bodyweight move, or one never logged with a weight."""
    if exercise.kind == rules.BODYWEIGHT:
        return True
    return exercise.kind == "" and not any(each.weight is not None for each in last)


def read_form(fields: dict[str, str], exercise: Exercise, alone: bool = False) -> tuple[list[DoneSet], list[int]]:
    """What was typed, a box a set: its numbers (Python reads them), anything after them its note. An empty box
    is a set not done. A box that can't be read is kept whole as that set's note, with no number made up, and
    its number (1 the first) is in the second list."""
    typed = {int(key[3:]): str(value or "") for key, value in fields.items() if re.fullmatch(r"set\d+", key)}
    if "sets" in fields:  # one long box, a line a set (a form opened before 30 Oct)
        typed = dict(enumerate(str(fields["sets"]).splitlines()))
    found, look = [], []
    for index, text in sorted(typed.items()):
        if not text.strip():
            continue
        each = exercise.sets[index] if index < len(exercise.sets) else PlannedSet()
        planned = DoneSet(exercise.name, each.set_type, each.purpose, each.category, each.low, each.high, position=index)
        said = rules.typed_set(text, alone)
        if said.readable:
            found.append(replace(planned, reps=said.reps, weight=said.weight, per_hand=said.per_hand, note=said.note))
        else:
            found.append(replace(planned, note=said.note))
            look.append(index + 1)
    return found, look


async def read_note(exercise: str, text: str) -> Note:
    """What a note means (pain, per hand, a target weight), read by Claude: one small request."""
    from tasks.gym import importer

    meant = (await importer.ask_meanings([], [], [], [text])).notes.get(text, {})
    return Note(exercise, text, bool(meant.get("pain")), importer._number(meant.get("target_low")), importer._number(meant.get("target_high")), str(meant.get("body_part") or "") if meant.get("pain") else "")


async def log_sets(session: store.Session, exercise: str, sets: list[DoneSet], note: Note | None, replace_logged: bool = True, part: range | None = None) -> int:
    """Sets (and a note) for one exercise of a session, in place of what was logged for it (with `part`, for
    those sets of it only); an undo's id."""
    before = [each for each in await database.run(store.db_sets, session.id) if each.exercise.lower() == exercise.lower() and (part is None or each.position in part)]
    if replace_logged and before:
        await database.run(store.db_delete_sets, [each.id for each in before])
    ids = await database.run(store.db_add_sets, session.user_id, session.id, sets)
    note_ids = [await database.run(store.db_add_note, session.user_id, session.id, note)] if note is not None else []
    payload = {"session": session.id, "sets": ids, "notes": note_ids, "restore": [vars(each) for each in before] if replace_logged else []}
    undo_id = await database.run(store.db_remember, session.user_id, "log", payload, clock.now())
    from tasks.gym import sheet

    await sheet.mirror(session, sets, note)
    return undo_id


def undo_row(undo_id: int) -> tuple:
    return (Button("Undo", TASK, UNDO, str(undo_id), emoji="↩️", style=cards.PRIMARY),)


def _form_arg(arg: str) -> tuple[str, int, str]:
    """(the session's id, the set the form starts at, the exercise) from a form's arg: "4:0:leg press"; a form
    opened before 30 Oct has no start ("4:leg press")."""
    session_id, _, rest = arg.partition(":")
    start, _, name = rest.partition(":")
    return (session_id, int(start), name) if start.isdigit() and name else (session_id, 0, rest)


def _exercise(exercises: list[Exercise], name: str) -> Exercise | None:
    """The exercise a button or form names: its id holds the name, cut short when the name is long."""
    return next((each for each in exercises if each.name.lower() == name), None) or next((each for each in exercises if name and each.name.lower().startswith(name)), None)


def _sets_said(numbers: list[int]) -> str:
    return f"set {numbers[0]}" if len(numbers) == 1 else "sets " + ", ".join(str(each) for each in numbers[:-1]) + f" and {numbers[-1]}"


async def on_log(press: cards.Press) -> str:
    session_id, _, name = press.arg.partition(":")
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None or session.status != store.OPEN:
        raise UserError("That workout is finished: say what you did in words to add to it.")
    exercise = _exercise(await exercises_of(session), name)
    if exercise is None:
        raise UserError("That exercise is not in this workout any more.")
    start, _, waiting = session.pending.partition(":")
    await press.open_form(await form_for(session, exercise, int(start) if waiting == exercise.name.lower() and start.isdigit() else 0))
    return "the log form opened"


async def on_pick(press: cards.Press) -> str:
    press.arg = f"{press.arg}:{(press.values or [''])[0]}"
    return await on_log(press)


async def on_logged(press: cards.Press) -> str:
    """A form sent: its sets logged, and what was done said on the card's own line. Nothing else is posted."""
    session_id, start, name = _form_arg(press.arg)
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None:
        raise UserError("That workout has gone.")
    exercise = _exercise(await exercises_of(session), name)
    if exercise is None:
        raise UserError("That exercise is not in this workout any more.")
    _, last, _ = await last_time(session.user_id, exercise.name, session.id)
    part = form_part(exercise, start)
    found, look = read_form(press.fields or {}, exercise, reps_alone(exercise, last))
    note_text = str((press.fields or {}).get("note") or "").strip()
    if not found and not note_text:
        await say_on_card(session, f"Nothing typed for {exercise.name}: nothing logged", session.undo_id)
        return "nothing typed"
    note = await read_note(exercise.name, note_text) if note_text else None
    undo_id = await log_sets(session, exercise.name, found, note, part=None if start == 0 else part)
    more = form_part(exercise, part.stop) if part.stop < set_count(exercise) else None
    await database.run(store.db_set_pending, session.id, f"{more.start}:{exercise.name.lower()}" if more else "")
    done = [each for each in found if each.done]
    if look:
        said = f"⚠️ {exercise.name}: {_sets_said(look)} could not be read, kept as {'its note' if len(look) == 1 else 'their notes'}: have a look"
    elif more:
        said = f"✅ {exercise.name} · sets {part.start + 1} to {part.stop} logged · tap it again for sets {more.start + 1} to {set_count(exercise)}"
    else:
        said = f"✅ {exercise.name} logged · {len(done)} set{'' if len(done) == 1 else 's'}" + (" · note kept" if note else "")
    await say_on_card(session, said, undo_id)
    changed(session.user_id)
    return f"logged {len(done)} sets" + (f", {_sets_said(look)} to look at" if look else "")


# --- Finish ---------------------------------------------------------------------------------------------------------------------
async def finish(session: store.Session, quietly: bool = False) -> tuple[str, int]:
    """End a session: what was planned and not logged is not done; personal bests; the workout to the back of the
    queue; the card becomes the summary, with Undo. The summary's words and an undo's id."""
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    done_names = {each.exercise.lower() for each in logged}
    missing = [DoneSet(each.name, planned.set_type, planned.purpose, planned.category, planned.low, planned.high, None, None, False, index)
               for each in exercises if each.name.lower() not in done_names for index, planned in enumerate(each.sets)]
    missing_ids = await database.run(store.db_add_sets, session.user_id, session.id, missing) if missing else []
    before = await database.run(store.db_bests, session.user_id)
    beaten = rules.beaten(before, logged)
    await database.run(store.db_put_bests, session.user_id, rules.bests(logged), session.id)
    await database.run(store.db_set_status, session.id, store.FINISHED, clock.now())
    await database.run(store.db_set_pending, session.id, "")
    queue_before = await database.run(store.db_queue, session.user_id)
    if session.workout_id is not None:
        plan = await store.plan(session.user_id)
        await database.run(store.db_set_queue, session.user_id, moved_to_back([each.id for each in queue_now(queue_before, plan)], session.workout_id), clock.now())
    undo_id = await database.run(store.db_remember, session.user_id, "finish", {"session": session.id, "missing": missing_ids, "queue": queue_before}, clock.now())
    names = {each.exercise.lower(): each.exercise for each in logged}
    finished = await say_on_card(session, "\n".join(rules.best_line(each, names) for each in beaten), undo_id)
    said = "\n".join([await summary_text(finished, await database.run(store.db_sets, session.id)), *(rules.best_line(each, names) for each in beaten)])
    changed(session.user_id)
    return said, undo_id


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
async def cancel(session: store.Session) -> tuple[str, int | None]:
    """Cancel is an undo of Start: everything back as it was before it. Nothing of the session is logged or
    counted (what was logged in it is taken off, kept to put back), it is never numbered or done, and the queue
    is not touched, so the same workout is still next. Undo when something had been logged."""
    sets = await database.run(store.db_sets, session.id)
    notes = await database.run(store.db_notes, session.id)
    await database.run(store.db_clear_session, session.id)
    await database.run(store.db_set_status, session.id, store.CANCELLED, clock.now())
    await database.run(store.db_set_pending, session.id, "")
    await database.run(store.db_rebuild_bests, session.user_id)
    undo_id = None
    if sets or notes:
        payload = {"session": session.id, "sets": [asdict(each) for each in sets], "notes": [asdict(each) for each in notes]}
        undo_id = await database.run(store.db_remember, session.user_id, "cancel", payload, clock.now())
    nxt = await next_workout(session.user_id)
    taken = sum(1 for each in sets if each.done)
    said = (f"{taken} set{'' if taken == 1 else 's'} taken off: nothing logged" if taken else "nothing logged") + (f" · {nxt.name} is still next" if nxt else "")
    await say_on_card(session, said, undo_id)
    changed(session.user_id)
    return f"{ICON} **{session.name}** cancelled · {said}", undo_id


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
    if kind == "log":
        await database.run(store.db_delete_sets, payload["sets"])
        await database.run(store.db_delete_notes, payload.get("notes", []))
        if payload.get("restore"):
            await database.run(store.db_add_sets, user_id, payload["session"], [DoneSet(**{key: value for key, value in each.items()}) for each in payload["restore"]])
        if session is not None:
            await database.run(store.db_set_pending, session.id, "")
        said = "↩️ Taken back: that log"
    elif kind == "finish":
        await database.run(store.db_delete_sets, payload["missing"])
        await database.run(store.db_set_status, payload["session"], store.OPEN, None)
        await database.run(store.db_set_queue, user_id, payload["queue"], clock.now())
        said = "↩️ The workout is open again"
    elif kind == "cancel":
        await database.run(store.db_set_status, payload["session"], store.OPEN, None)
        await database.run(store.db_add_sets, user_id, payload["session"], [DoneSet(**each) for each in payload["sets"]])
        for each in payload["notes"]:
            await database.run(store.db_add_note, user_id, payload["session"], Note(**each))
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
    if session is not None and await database.run(store.db_session, session.id) is not None:
        await say_on_card(session, said, None)
    changed(user_id)
    return said


async def on_undo(press: cards.Press) -> str:
    said = await undo(int(press.arg) if press.arg.isdigit() else 0, press.user.id)
    if press.message_id is None or await press.db.run(store.db_session_of_message, press.message_id) is None:
        await press.update(Card(said))  # an Undo on a message of its own (from before 30 Oct); the card says it on its own line
    return said


def register() -> None:
    cards.register(TASK, LOG, on_log, opens_form=True)
    cards.register(TASK, PICK, on_pick, opens_form=True)
    cards.register(TASK, LOGGED, on_logged)
    cards.register(TASK, FINISH, on_finish)
    cards.register(TASK, CANCEL, on_cancel)
    cards.register(TASK, UNDO, on_undo)
