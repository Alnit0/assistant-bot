import logging
from dataclasses import replace
from datetime import date, datetime, timedelta

from core import attention, cards, clock, config, database, design, summaries, timeinput
from core import day as days
from core.cards import Button, Card, Field, Form
from core.errors import UserError
from tasks.gym import rules, store
from tasks.gym.rules import ICON, TASK, DoneSet, Exercise, Note, Workout

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The rotation and a session: which workout is next (a queue in plan order,
# no fixed days), the workout card in #gym, the Log form, Finish (personal
# bests, the queue moved on), and undo. No discord.py.
#
#   starting a workout     the next in the queue, its card in #gym
#   do Lower 2 instead     that one now; the queue's head stays next
#   skip Upper 1           to the back of the queue
#   off-plan (a 30 min run) logged as off-plan; the queue as it was
#   Finish                 unlogged sets not done, a summary with PBs, the
#                          workout to the back of the queue; Undo
#
# The card: each exercise with its sets (type, purpose, target, suggested
# weight and why), last time's result and note small, ⚠️ when that note
# spoke of pain; Log on each exercise not logged yet, Finish last.
# ---------------------------------------------------------------------------
LOG, LOGGED, FINISH, UNDO, PICK = "log", "logged", "finish", "undo", "pick"
MAX_FORM_SETS = 4  # a form holds five boxes: a set each and the note; more sets go in one long box


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


async def exercise_box(session: store.Session, exercise: Exercise, logged: list[DoneSet], open_: bool) -> design.Box:
    lines = [design.card_title(exercise.name)]
    planned = await planned_today(session.user_id, exercise, session.id)
    day, last, note = await last_time(session.user_id, exercise.name, session.id)
    mine = [each for each in logged if each.exercise.lower() == exercise.name.lower()]
    for each, suggested in planned:
        purpose = f" · {each.purpose}" if each.purpose else ""
        lines.append(f"{each.set_type}{purpose} · {rules.range_text(each.low, each.high)} · {design.time(rules.kg(suggested)) if suggested else 'weight of your choice'}")
    if last:
        lines.append(design.small(f"last: {rules.sets_text(last)} · {day.day} {day:%b}"))
        why = rules.suggest(exercise, last, note).why
        if why:
            lines.append(design.small(f"why: {why}"))
    if note is not None:
        lines.append(design.small(("⚠️ " if note.pain else "") + f"last note: “{note.text}”"))
    from tasks.gym import pain

    lines += [design.small(each) for each in pain.pattern(exercise.name, await pain.flags(session.user_id, exercise.name))]
    status = design.QUIET
    row = ()
    if mine:
        lines.append(f"✅ {rules.sets_text(mine)}")
        status = design.DONE
    elif open_:
        status = design.DUE
        row = (Button(f"Log {exercise.name}"[:80], TASK, LOG, f"{session.id}:{exercise.name.lower()}"[:90], emoji="📝", style=cards.PRIMARY),)
    children = [design.Text("\n".join(lines))]
    if row:
        children.append(design.Row(row))
    return design.Box(status, tuple(children))


async def card(session: store.Session) -> Card:
    exercises = await exercises_of(session)
    logged = await database.run(store.db_sets, session.id)
    open_ = session.status == store.OPEN
    title = f"{ICON} {session.name}" + (f" · session {session.number}" if session.number else "")
    top = [design.page_title(title), design.small(f"{session.day:%a} {session.day.day} {session.day:%b}" + ("" if open_ else " · finished"))]
    boxes = [await exercise_box(session, each, logged, open_) for each in exercises]
    under = []
    if open_:
        under = [design.Row((Button("Finish workout", TASK, FINISH, str(session.id), emoji="🏁", style=cards.SUCCESS),))]
    pieces = design.page(top, boxes)
    if under:
        pieces = (*pieces, *under)
    if design.problem(pieces):
        # Too many for one message: the Log buttons give way to one dropdown
        pieces = (*design.page(top, [replace(each, children=tuple(child for child in each.children if not isinstance(child, design.Row))) for each in boxes]), *_picker(session, exercises, logged), *under)
    text = "\n".join([title, *(f"• {each.name}" for each in exercises)])
    return Card(text, (), design.fit(pieces))


def _picker(session: store.Session, exercises: list[Exercise], logged: list[DoneSet]) -> tuple:
    done = {each.exercise.lower() for each in logged}
    options = tuple(cards.Option(each.name[:100], each.name.lower()[:100]) for each in exercises if each.name.lower() not in done)
    if not options:
        return ()
    return (design.Row((cards.Select(TASK, PICK, options[:25], placeholder="📝 Log: pick an exercise", arg=str(session.id)),)),)


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
async def form_for(session: store.Session, exercise: Exercise) -> Form:
    planned = await planned_today(session.user_id, exercise, session.id)
    title = f"Log {exercise.name}"[:45]
    if len(planned) <= MAX_FORM_SETS and planned:
        fields = tuple(
            Field(f"set{index}", f"Set {index + 1} · {each.set_type} · {rules.range_text(each.low, each.high)} reps"[:45],
                  value=f"{suggested:g} kg × " if suggested is not None else "", placeholder="40 x 9", required=False)
            for index, (each, suggested) in enumerate(planned)
        )
    else:
        lines = "\n".join(f"{suggested:g} kg × " if suggested is not None else "" for _, suggested in planned) or "kg × "
        fields = (Field("sets", "One line a set: weight × reps", value=lines, placeholder="40 x 9", long=True, required=False),)
    return Form(title, TASK, LOGGED, (*fields, Field("note", "A note (optional)", required=False, long=True)), arg=f"{session.id}:{exercise.name.lower()}"[:90])


def read_form(fields: dict[str, str], exercise: Exercise, planned) -> tuple[list[DoneSet], list[str]]:
    """What was typed: a set a line (weight × reps, or reps alone at the suggested weight); what couldn't be read."""
    typed = [fields[key] for key in sorted(fields) if key.startswith("set") and key != "sets"]
    if "sets" in fields:
        typed = [line for line in str(fields["sets"]).splitlines()]
    found, unread = [], []
    for index, text in enumerate(typed):
        text = text.strip()
        if not text or text.lower().rstrip(" ×x").strip().endswith("kg") or text.endswith(("×", "x")):
            continue  # left as it was pre-filled: not done
        weight_kg, reps_done, per_hand = rules.result(text)
        each, suggested = planned[index] if index < len(planned) else (rules.PlannedSet(), None)
        if reps_done is None:
            unread.append(text)
            continue
        found.append(DoneSet(exercise.name, each.set_type, each.purpose, each.category, each.low, each.high, reps_done,
                             weight_kg if weight_kg is not None else suggested, per_hand, index))
    return found, unread


async def read_note(exercise: str, text: str) -> Note:
    """What a note means (pain, per hand, a target weight), read by Claude: one small request."""
    from tasks.gym import importer

    meant = (await importer.ask_meanings([], [], [], [text])).notes.get(text, {})
    return Note(exercise, text, bool(meant.get("pain")), importer._number(meant.get("target_low")), importer._number(meant.get("target_high")), str(meant.get("body_part") or "") if meant.get("pain") else "")


async def log_sets(session: store.Session, exercise: str, sets: list[DoneSet], note: Note | None, replace_logged: bool = True) -> int:
    """Sets (and a note) for one exercise of a session, in place of what was logged for it; an undo's id."""
    before = [each for each in await database.run(store.db_sets, session.id) if each.exercise.lower() == exercise.lower()]
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


async def on_log(press: cards.Press) -> str:
    session_id, _, name = press.arg.partition(":")
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None or session.status != store.OPEN:
        raise UserError("That workout is finished: say what you did in words to add to it.")
    exercise = next((each for each in await exercises_of(session) if each.name.lower() == name), None)
    if exercise is None:
        raise UserError("That exercise is not in this workout any more.")
    await press.open_form(await form_for(session, exercise))
    return "the log form opened"


async def on_pick(press: cards.Press) -> str:
    press.arg = f"{press.arg}:{(press.values or [''])[0]}"
    return await on_log(press)


async def on_logged(press: cards.Press) -> str:
    session_id, _, name = press.arg.partition(":")
    session = await press.db.run(store.db_session, int(session_id)) if session_id.isdigit() else None
    if session is None:
        raise UserError("That workout has gone.")
    exercise = next((each for each in await exercises_of(session) if each.name.lower() == name), None)
    if exercise is None:
        raise UserError("That exercise is not in this workout any more.")
    planned = await planned_today(session.user_id, exercise, session.id)
    found, unread = read_form(press.fields or {}, exercise, planned)
    if unread:
        raise UserError("I couldn't read " + ", ".join(f"“{each}”" for each in unread) + ": a set is weight × reps, like 40 x 9.")
    note_text = str((press.fields or {}).get("note") or "").strip()
    note = await read_note(exercise.name, note_text) if note_text else None
    if not found and note is None:
        raise UserError("Nothing was typed: nothing is logged.")
    undo_id = await log_sets(session, exercise.name, found, note)
    await draw(await press.db.run(store.db_session, session.id))
    line = f"✅ **{exercise.name}** · {rules.sets_text(found)}" + (" · note kept" if note else "")
    if session.channel_id:
        await cards.send(session.channel_id, Card(line, (undo_row(undo_id),)))
    changed(session.user_id)
    return f"logged {len(found)} sets"


# --- Finish ---------------------------------------------------------------------------------------------------------------------
async def finish(session: store.Session, quietly: bool = False) -> tuple[str, int]:
    """End a session: what was planned and not logged is not done; personal bests; the workout to the back of the
    queue; a short summary in #gym. The summary's words and an undo's id."""
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
    queue_before = await database.run(store.db_queue, session.user_id)
    if session.workout_id is not None:
        plan = await store.plan(session.user_id)
        await database.run(store.db_set_queue, session.user_id, moved_to_back([each.id for each in queue_now(queue_before, plan)], session.workout_id), clock.now())
    undo_id = await database.run(store.db_remember, session.user_id, "finish", {"session": session.id, "missing": missing_ids, "queue": queue_before}, clock.now())
    finished = await database.run(store.db_session, session.id)
    await draw(finished)
    said = await summary_text(finished, logged, beaten, len(missing))
    if not quietly and finished.channel_id:
        await cards.send(finished.channel_id, Card(said, (undo_row(undo_id),)))
    changed(session.user_id)
    return said, undo_id


async def summary_text(session: store.Session, logged: list[DoneSet], beaten: list[rules.Best], missing: int) -> str:
    names = {each.exercise.lower(): each.exercise for each in logged}
    done = [each for each in logged if each.done]
    lines = [f"🏁 **{session.name}**" + (f" · session {session.number}" if session.number else "") + f" · {len(done)} sets" + (f" · {missing} not done" if missing else "")]
    for name in dict.fromkeys(each.exercise for each in done):
        today = [each for each in done if each.exercise == name]
        _, last, _ = await last_time(session.user_id, name, session.id)
        mark = ""
        if last:
            a, b = rules.top_set(today), rules.top_set(last)
            if a and b:
                mark = " ▲" if (a.weight, a.reps) > (b.weight, b.reps) else " ▼" if (a.weight, a.reps) < (b.weight, b.reps) else ""
        lines.append(f"**{name}** · {rules.sets_text(today)}" + (f" · last {rules.sets_text(last)}{mark}" if last else ""))
    lines += [rules.best_line(each, names) for each in beaten]
    return "\n".join(lines)


async def on_finish(press: cards.Press) -> str:
    session = await press.db.run(store.db_session, int(press.arg)) if press.arg.isdigit() else None
    if session is None or session.status != store.OPEN:
        return "already finished"
    await finish(session)
    return "workout finished"


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
        said = "↩️ Taken back: that log"
    elif kind == "finish":
        await database.run(store.db_delete_sets, payload["missing"])
        await database.run(store.db_set_status, payload["session"], store.OPEN, None)
        await database.run(store.db_set_queue, user_id, payload["queue"], clock.now())
        said = "↩️ The workout is open again"
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
    if session is not None:
        refreshed = await database.run(store.db_session, session.id)
        if refreshed is not None:
            await draw(refreshed)
    changed(user_id)
    return said


async def on_undo(press: cards.Press) -> str:
    said = await undo(int(press.arg) if press.arg.isdigit() else 0, press.user.id)
    await press.update(Card(said))
    return said


def register() -> None:
    cards.register(TASK, LOG, on_log, opens_form=True)
    cards.register(TASK, PICK, on_pick, opens_form=True)
    cards.register(TASK, LOGGED, on_logged)
    cards.register(TASK, FINISH, on_finish)
    cards.register(TASK, UNDO, on_undo)
