"""The gym (tasks/gym), behind GYM_ENABLED: the values read (names, reps, ranges, weights, results, dates), the
suggested weight's edge cases, bests and the trend; importing a logbook (CSV with a DNF workout, rep ranges,
a dumbbell note, uneven spacing, blank rows; XLSX a tab a workout; a wide layout; pasted rows), the plan apart
from the log; the rotation (start, instead, skip, off-plan, extra), the workout card in #gym, the Log form,
Finish with a PB and Undo; a session described in words (messy, partial, after the fact, merged with what
buttons logged, a correction); swaps and plan changes; questions; the briefing's line, the week's target and the
week view. Made-up data only (tests/gym_files.py)."""
import asyncio
import re
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, database, design, llm, live
from core import day as days
from core.actions import Attachment, Request
from core.errors import UserError
from tasks.gym import importer, plain, rules, session, sheet, store
from tasks.gym.rules import DoneSet, Exercise, Note, PlannedSet
from tests import gym_files

GYM, INBOX = 700, 100


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


# --- a stand-in for Claude: what it would say about these made-up files ---------------------------------------------------
FIELD_OF = {"date": "date", "week": "week", "day": "workout", "workout": "workout", "exercise": "exercise", "sets": "sets", "reps": "reps",
            "reps achieved": "reps_done", "weight": "weight", "objective": "purpose", "notes": "notes", "plan": "sets_and_reps",
            "set 1": "result", "set 2": "result", "set 3": "result"}


def _listed(user: str, title: str) -> list[str]:
    part = user.split(f"{title}:", 1)[1].split("\n\n", 1)[0]
    return [line.split(". ", 1)[1] for line in part.strip().splitlines() if ". " in line]


def answer(system, user, tools, *, choice=None, purpose="", task="", max_tokens=600):
    name = tools[0]["name"]
    if name == importer.MAP_TOOL:
        columns = []
        for block in user.split("Table “")[1:]:
            table = block.split("”", 1)[0]
            headings = block.split("Headings: ", 1)[1].split("\n", 1)[0].split(" | ")
            columns += [{"table": table, "heading": each, "field": FIELD_OF.get(each.strip().lower(), "none"), "sure": True} for each in headings]
        return name, {"columns": columns}
    if name == importer.MEANING_TOOL:
        brackets = [{"index": index, "meaning": each.lower() if each.lower() in ("warm-up", "working") else "name"} for index, each in enumerate(_listed(user, "Brackets"))]
        category = {"warm-up": "warm_up", "to failure": "to_failure", "near failure": "near_failure"}
        purposes = [{"index": index, "category": category.get(each.lower(), "technique")} for index, each in enumerate(_listed(user, "Purposes"))]
        kinds = [{"index": index, "kind": "dumbbell" if "incline" in each.lower() else "machine" if any(word in each.lower() for word in ("press (high", "leg press", "pulldown", "row", "curl")) else "barbell"} for index, each in enumerate(_listed(user, "Exercises"))]
        notes = []
        for index, each in enumerate(_listed(user, "Notes")):
            found = re.search(r"(\d+)-(\d+)kg", each)
            notes.append({"index": index, "pain": any(word in each.lower() for word in ("knee", "shoulder", "hurt")), "per_hand": "dumbbell" in each.lower(),
                          **({"target_low": float(found[1]), "target_high": float(found[2])} if found else {})})
        return name, {"brackets": brackets, "purposes": purposes, "exercises": kinds, "notes": notes}
    raise AssertionError(f"an unscripted request: {name}")


async def fake_claude(system, user, tools, **more):
    return answer(system, user, tools, **more)


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"gym": store.MIGRATIONS})
    monkeypatch.setattr(config, "GYM_ENABLED", True)
    monkeypatch.setitem(config.CHANNELS, "gym", GYM)
    monkeypatch.setattr(llm, "call_tool", fake_claude)
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], next_id=500)

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        seen.edited.append((message_id, card))
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(session, "changed", lambda user_id: None)
    session.register()
    live.reset()
    seen.today = date(2026, 10, 20) if days.today() < date(2026, 10, 20) else days.today() + timedelta(days=1)
    clock.advance_to(days.at(seen.today, time(7, 0)))
    seen.request = lambda text="said", previous=None, attachments=(): Request(owner, INBOX, text, previous=previous, attachments=attachments)
    return seen


def attached(name: str, data: bytes) -> Attachment:
    async def fetch():
        return data

    return Attachment(name, len(data), "", fetch)


def imported(world, data: bytes = None, name="logbook.csv"):
    proposal = run(plain.import_card(world.request("here's my gym logbook", attachments=(attached(name, data or gym_files.logbook_csv()),)), {}, frozenset()))
    assert proposal.can_save, proposal.warnings
    run(plain.import_save(world.request(), proposal.data))
    assert run(plain.import_check(world.request(), proposal.data)) == ""
    return proposal


# --- the values, read by Python -------------------------------------------------------------------------------------------
def test_names_reps_weights_results_and_dates_are_read_by_python():
    assert rules.tidy("Bench   press ( working )") == "Bench press (working)"
    assert rules.tidy("Lat pulldown -wide grip") == "Lat pulldown - wide grip"
    assert rules.split_exercise("Bench   press (warm-up)", {"warm-up": "warm-up"}) == ("Bench press", "warm-up")
    assert rules.split_exercise("Leg press (high foot) (working)", {"high foot": "name", "working": "working"}) == ("Leg press (high foot)", "working")
    assert rules.reps_range("5-8") == (5, 8) and rules.reps_range("12") == (12, 12) and rules.reps_range("AMRAP") == (None, None)
    assert rules.weight("40kg") == (40.0, False) and rules.weight("14s") == (14.0, True) and rules.weight("heavy") == (None, False)
    assert rules.result("40 x 9") == (40.0, 9, False) and rules.result("14s for 10") == (14.0, 10, True) and rules.result("9 @ 42.5") == (42.5, 9, False)
    assert rules.result("12") == (None, 12, False)
    assert rules.logbook_date("6/10/2026") == date(2026, 10, 6) and rules.logbook_date("DNF") is None


def _set(reps, weight, low=5, high=8, category=rules.TO_FAILURE, set_type=rules.WORKING):
    return DoneSet("Bench press", set_type, "", category, low, high, reps, weight)


def test_the_suggested_weight_double_progression_and_its_edge_cases():
    bench = Exercise("Bench press", (), rules.BARBELL)
    machine = Exercise("Leg press", (), rules.MACHINE)
    up = rules.suggest(bench, [_set(8, 40)])
    assert (up.weight, up.why) == (42.5, "last 40 kg × 8, top of 5-8: +2.5")
    assert rules.suggest(bench, [_set(6, 40)]).weight == 40, "in the range: the same"
    assert rules.suggest(bench, [_set(4, 40)]).weight == 40, "under it: the same"
    assert rules.suggest(machine, [_set(15, 120, 10, 15)]).weight == 125, "a machine's step is 5"
    jump = rules.suggest(machine, [_set(21, 120, 10, 15)])
    assert jump.weight > 125 and "over" in jump.why, "beat the top by 5 or more: a bigger jump, landing back in range"
    assert rules.estimated(120, 21, 15) > 120
    noted = rules.suggest(bench, [_set(6, 40)], Note("Bench press", "go up to 45kg", target_low=45.0))
    assert noted.weight == 45.0 and noted.why.startswith("your note")
    assert rules.suggest(bench, [_set(8, 40)], Note("Bench press", "too easy", target_low=0.0)).weight == 42.5, "a target of 0 is none"
    # The last to-failure set decides, not a near-failure one after it
    assert rules.suggest(bench, [_set(8, 40), _set(5, 40, category=rules.NEAR_FAILURE)]).weight == 42.5
    assert rules.suggest(Exercise("Bench press", (), rules.BARBELL, step=1.25), [_set(8, 40)]).weight == 41.25, "a step of its own"
    assert rules.warm_up_weight(42.5, bench) == 20.0 and rules.suggest(bench, []).weight is None


def test_bests_and_the_trend():
    before = rules.bests([_set(8, 40)])
    today = [_set(8, 42.5), _set(9, 40)]
    beaten = rules.beaten(before, today)
    assert {(each.kind, each.key, each.value) for each in beaten} == {("weight", "5-8", 42.5), ("reps", "40", 9.0)}
    assert rules.trend([(date(2026, 10, 1), [_set(8, 40)]), (date(2026, 10, 8), [_set(7, 42.5)])]) == "40 × 8 → 42.5 × 7 ▲"


# --- importing -------------------------------------------------------------------------------------------------------------
def test_a_logbook_is_a_plan_and_a_log_apart_with_a_dnf_workout_not_done(world):
    proposal = imported(world)
    plan = run(store.plan(world.owner.id))
    assert [each.name for each in plan] == ["Upper 1", "Lower 1", "Upper 2", "Lower 2"], "the rotation in the order first seen"
    upper = plan[0]
    assert [each.name for each in upper.exercises] == ["Bench press", "Incline press", "Lat pulldown - wide grip", "Lateral raise"], "spacing tidied, a variant kept in the name"
    assert [(each.set_type, each.low, each.high) for each in upper.exercises[0].sets] == [("warm-up", 12, 15), ("working", 5, 8), ("working", 5, 8)]
    assert plan[1].exercises[1].name == "Leg press (high foot)", "a bracket that is not a set type is part of the name"
    assert plan[3].exercises[0].name == "Deadlift", "a workout planned and not done is still in the plan"
    assert any("1 workout planned and not done" in line for line in proposal.lines)
    assert any("4 sessions" in line for line in proposal.lines)
    sessions = run(database.run(store.db_sessions, world.owner.id))
    assert [each.name for each in sessions] == ["Upper 1", "Lower 1", "Upper 2", "Upper 1"]
    incline = [each for each in run(database.run(store.db_sets, sessions[0].id)) if each.exercise == "Incline press"]
    assert incline[0].per_hand, "a note about dumbbells: per hand"
    laterals = [each for each in run(database.run(store.db_sets, sessions[-1].id)) if each.exercise == "Lateral raise"]
    assert laterals and not laterals[0].done, "empty results: planned, not done"
    assert run(session.next_workout(world.owner.id)).name == "Lower 1", "the rotation goes on after the last one logged"


def test_a_workbook_with_a_tab_a_workout_and_a_wide_layout_and_pasted_rows(world):
    proposal = run(plain.import_card(world.request(attachments=(attached("logbook.xlsx", gym_files.logbook_xlsx()),)), {}, frozenset()))
    assert [line.split(" · ")[0] for line in proposal.lines if line.startswith("**") and not line.startswith("**Log")] == ["**Upper 1**", "**Lower 1**", "**Upper 2**", "**Lower 2**"]
    wide = run(plain.import_card(world.request(attachments=(attached("wide.csv", gym_files.wide_csv()),)), {}, frozenset()))
    assert wide.lines[0] == "**Push** · 2 exercises · 6 sets" and any("2 sessions" in line for line in wide.lines)
    pasted = "\n".join(line for line in gym_files.wide_csv().decode().splitlines())
    from_words = run(plain.import_card(world.request(pasted), {}, frozenset()))
    assert from_words.lines[0] == wide.lines[0]


def test_an_unsure_column_is_asked_about_on_the_card(world, monkeypatch):
    async def unsure(system, user, tools, **more):
        name, raw = answer(system, user, tools, **more)
        if name == importer.MAP_TOOL:
            raw = {"columns": [{**each, "sure": each["heading"] != "Objective"} for each in raw["columns"]]}
        return name, raw

    monkeypatch.setattr(llm, "call_tool", unsure)
    proposal = run(plain.import_card(world.request(attachments=(attached("logbook.csv", gym_files.logbook_csv()),)), {}, frozenset()))
    assert proposal.question is not None and "“Objective” → purpose" in proposal.question.text
    assert [choice.label for choice in proposal.question.choices] == ["Weight", "Purpose", "Notes", "Not used"]


# --- the rotation, the card, the form, Finish ---------------------------------------------------------------------------------
def test_starting_posts_the_next_workout_in_gym_with_suggestions_last_time_and_a_pain_flag(world):
    imported(world)
    started = run(session.start(world.owner.id))
    assert started.name == "Lower 1" and started.number == 2
    posted = world.sent[-1]
    assert posted.channel == GYM
    shown = "\n".join(design.texts(posted.card.layout))
    assert "## 🏋️ Lower 1 · session 2" in shown
    assert "last: 120 kg × 21" in shown and "over 10-15: up to land in range" in shown, "a bigger jump for 21 reps on 10-15"
    assert "⚠️ last note: “knee felt a bit off”" in shown, "a note about pain comes up again"
    assert [button.label for button in design.buttons(posted.card.layout)][-1] == "Finish workout"


def test_do_another_instead_keeps_the_queue_skip_sends_to_the_back_off_plan_leaves_it(world):
    imported(world)
    plan = run(store.plan(world.owner.id))
    started = run(session.start(world.owner.id, plan[2]))
    run(session.finish(started))
    assert run(session.next_workout(world.owner.id)).name == "Lower 1", "the head of the queue kept its place"
    order = run(session.skip(world.owner.id, plan[1]))
    assert [each.name for each in order][0] == "Lower 2" and order[-1].name == "Lower 1"
    run(session.off_plan(world.owner.id, "30 min run", world.today))
    assert run(session.next_workout(world.owner.id)).name == "Lower 2", "an off-plan session leaves the queue as it was"


def test_the_log_form_has_a_line_a_set_with_the_suggestion_and_logs_what_is_typed(world):
    imported(world)
    started = run(session.start(world.owner.id))
    squat = next(each for each in run(session.exercises_of(started)) if each.name == "Squat")
    form = run(session.form_for(started, squat))
    assert [field.label for field in form.fields] == ["Set 1 · warm-up · 8-10 reps", "Set 2 · working · 4-6 reps", "A note (optional)"]
    assert form.fields[1].value == "82.5 kg × " and form.fields[0].value == "40 kg × ", "the working set's suggestion, the warm-up about half"
    cards.check_form(form)
    press = SimpleNamespace(arg=form.arg, fields={"set0": "40 x 10", "set1": "82.5 x 6", "note": ""}, db=database, user=world.owner, channel_id=GYM, message_id=1, update=None)
    assert run(session.on_logged(press)) == "logged 2 sets"
    logged = run(database.run(store.db_sets, started.id))
    assert [(each.exercise, each.weight, each.reps) for each in logged] == [("Squat", 40.0, 10), ("Squat", 82.5, 6)]
    assert world.sent[-1].card.text == "✅ **Squat** · 40 kg × 10, 82.5 kg × 6"
    with pytest.raises(UserError, match="couldn't read"):
        run(session.on_logged(SimpleNamespace(**{**vars(press), "fields": {"set0": "lots", "set1": "", "note": ""}})))


def test_more_sets_than_a_form_holds_are_one_long_box():
    exercise = Exercise("Bench press", tuple(PlannedSet(rules.WORKING, "", "", 5, 8) for _ in range(6)))
    found, unread = session.read_form({"sets": "40 x 8\n40 x 7\n\n40 kg × \n9"}, exercise, [(each, 40.0) for each in exercise.sets])
    assert [(each.weight, each.reps) for each in found] == [(40.0, 8), (40.0, 7), (40.0, 9)] and not unread


def test_finish_marks_what_is_not_logged_calls_out_a_best_and_undo_puts_it_back(world):
    imported(world)
    started = run(session.start(world.owner.id))
    sets = [DoneSet("Squat", rules.WORKING, "To failure", rules.TO_FAILURE, 4, 6, 6, 85.0)]
    run(session.log_sets(started, "Squat", sets, None))
    said, undo_id = run(session.finish(started))
    assert said.splitlines()[0].startswith("🏁 **Lower 1** · session 2 · 1 sets") and "not done" in said.splitlines()[0]
    assert "🏆 **Squat** · heaviest for 4-6: 85 kg" in said
    assert run(session.next_workout(world.owner.id)).name == "Upper 2", "the queue moved on"
    assert run(session.undo(undo_id, world.owner.id)) == "↩️ The workout is open again"
    assert run(session.next_workout(world.owner.id)).name == "Lower 1"
    assert run(database.run(store.db_session, started.id)).status == store.OPEN


# --- a session described in words ------------------------------------------------------------------------------------------
UPPER_1_DESCRIBED = [
    {"exercise": "Bench press", "set_type": "warm-up", "reps": 15, "weight": 20},
    {"exercise": "Bench press", "reps": 9, "weight": 40},
    {"exercise": "Bench press", "reps": 8, "weight": 40},
    {"exercise": "incline", "reps": 10, "weight": 14, "per_hand": True},
    {"exercise": "incline", "reps": 9, "weight": 14, "per_hand": True},
    {"exercise": "laterals", "skipped": True, "note": "shoulder felt off", "pain": True},
    {"exercise": "pulldown", "reps": 12, "weight": 57},
    {"exercise": "pulldown", "reps": 10, "weight": 57, "note": "last set was a grind"},
]


def test_a_whole_session_described_after_the_fact_is_one_card_matched_to_the_plan(world):
    imported(world)
    proposal = run(plain.describe_card(world.request("did Upper 1 yesterday …"), {"day": "yesterday", "sets": UPPER_1_DESCRIBED}, frozenset()))
    lines = proposal.lines
    assert lines[0].startswith("**Upper 1** · yesterday ❓"), "the workout worked out from the exercises: a guess, said"
    assert "**Bench press** · 20 kg × 15, 40 kg × 9, 40 kg × 8" in lines
    assert "**Incline press** · 14 kg each × 10, 14 kg each × 9" in lines, "a partial name matched; per hand"
    assert "**Lat pulldown - wide grip** · 57 kg × 12, 57 kg × 10" in lines
    assert "-# note: “last set was a grind”" in lines
    assert "**Lateral raise** · skipped" in lines and "-# ⚠️ note: “shoulder felt off”" in lines, "a note word for word, with its pain flag"
    fixed = run(plain.describe_card(world.request("the second bench set was 9 not 8", previous=proposal.data), {"corrections": [{"exercise": "bench", "set": 3, "reps": 9}]}, frozenset()))
    assert "**Bench press** · 20 kg × 15, 40 kg × 9, 40 kg × 9" in fixed.lines
    said = run(plain.describe_save(world.request(), fixed.data))
    assert said.startswith("🏋️ Saved · **Upper 1** · yesterday · 7 sets")
    assert run(plain.describe_check(world.request(), fixed.data)) == ""
    assert run(session.next_workout(world.owner.id)).name == "Lower 1", "Upper 1 went to the back: Lower 1 is still next"
    notes = run(database.run(store.db_exercise_notes, world.owner.id, ["Lateral raise"]))
    assert notes[-1][1].pain and notes[-1][1].text == "shoulder felt off"


def test_words_and_buttons_mixed_are_one_session(world):
    imported(world)
    started = run(session.start(world.owner.id))
    run(session.log_sets(started, "Squat", [DoneSet("Squat", rules.WORKING, "", "", 4, 6, 6, 80.0)], None))
    described = [{"exercise": "Romanian deadlift", "reps": 8, "weight": 72.5}, {"exercise": "leg press", "reps": 15, "weight": 130}]
    proposal = run(plain.describe_card(world.request("rdls 72.5 for 8, leg press 130 for 15"), {"sets": described}, frozenset()))
    assert "added to the session logged by buttons" in proposal.lines[0]
    run(plain.describe_save(world.request(), proposal.data))
    logged = {each.exercise for each in run(database.run(store.db_sets, started.id))}
    assert logged == {"Squat", "Romanian deadlift", "Leg press (high foot)"}
    assert run(database.run(store.db_session, started.id)).status == store.OPEN, "still open: Finish ends it"


def test_a_session_nothing_like_the_plan_is_off_plan(world):
    imported(world)
    proposal = run(plain.describe_card(world.request(), {"sets": [{"exercise": "rowing machine", "reps": 1, "weight": None}, {"exercise": "kettlebell swing", "reps": 20, "weight": 16}]}, frozenset()))
    assert proposal.lines[0].startswith("**Off-plan session**")
    run(plain.describe_save(world.request(), proposal.data))
    assert run(session.next_workout(world.owner.id)).name == "Lower 1", "the queue as it was"


# --- swaps, changes, questions, the target -----------------------------------------------------------------------------------
def test_a_swap_today_and_a_change_to_the_plan(world):
    imported(world)
    said = run(plain.swap(world.request(), {"exercise": "leg press", "instead": "hack squat"}, frozenset()))
    assert said == "🏋️ Today: **Leg press (high foot)** → **Hack squat** · the plan as it was"
    assert "Hack squat" in [each.name for each in run(session.exercises_of(run(database.run(store.db_open_session, world.owner.id))))]
    assert "Leg press (high foot)" in [each.name for each in run(store.plan(world.owner.id))[1].exercises]
    change = run(plain.change_card(world.request(), {"change": "reps", "exercise": "Romanian deadlift", "reps": "8-12"}, frozenset()))
    assert change.lines == ("**Lower 1** · **Romanian deadlift** · ~~6-10~~ → **8-12**",)
    run(plain.change_save(world.request(), change.data))
    assert run(plain.change_check(world.request(), change.data)) == ""
    added = run(plain.change_card(world.request(), {"change": "add", "workout": "Upper 1", "exercise": "face pulls", "reps": "12-15", "sets": 3}, frozenset()))
    run(plain.change_save(world.request(), added.data))
    assert run(store.plan(world.owner.id))[0].exercises[-1].name == "Face pulls"


def test_questions_are_answered_from_the_log(world):
    imported(world)
    ask = lambda **data: run(plain.ask(world.request(), data, frozenset()))
    assert ask(question="last", exercise="bench") == "🏋️ **Bench press** · Tue 13 Oct · 20 kg × 15, 40 kg × 9, 40 kg × 8"
    assert ask(question="notes", exercise="Romanian deadlift").endswith("⚠️ 8 Oct: “knee felt a bit off”")
    assert ask(question="best", exercise="leg press") == "🏋️ **Leg press (high foot)** · best: 120 kg × 21"
    assert ask(question="trend", exercise="bench") == "🏋️ **Bench press** · last 2 sessions: 40 × 8 → 40 × 9 ▲"
    assert ask(question="sessions", span="month").startswith("🏋️ **4 sessions** this month")


def test_the_briefing_line_the_weekly_target_and_the_week_view(world):
    from tasks import gym

    imported(world)
    line = run(gym.summary(world.owner.id, world.today)).overview
    assert line.startswith("next: Lower 1 · last session ") and "days ago" in line
    assert run(gym.week(world.owner.id, world.today - timedelta(days=world.today.weekday()), world.today)) is None, "no target: no line"
    target = run(plain.target_card(world.request(), {"per_week": 3}, frozenset()))
    run(plain.target_save(world.request(), target.data))
    started = run(session.start(world.owner.id))
    run(session.finish(started))
    monday = world.today - timedelta(days=world.today.weekday())
    assert run(gym.week(world.owner.id, monday, world.today)).line == "1 of 3 sessions"
    (piece,) = run(gym.plan_pieces(world.owner.id, world.today))
    assert piece.text == "Lower 1" and piece.all_day


def test_the_sheet_row_is_alex_s_layout(world):
    imported(world)
    started = run(session.start(world.owner.id))
    row = sheet.row(started, DoneSet("Squat", rules.WORKING, "To failure", rules.TO_FAILURE, 4, 6, 6, 82.5), "felt good")
    assert row == [f"{started.day.day}/{started.day.month}/{started.day.year}", "", "Lower 1", "Squat (working)", "1", "4-6", "6", "82.5kg", "To failure", "felt good"]
    assert not sheet.on(), "off until a sheet is shared"


def test_the_gym_task_is_in_the_catalogue_with_its_words_for_commands(world):
    from tasks import gym

    entries = gym.task.entries()
    assert not actions.problems(entries)
    assert all(action.say for action in entries[0].actions)
    assert gym.task.switched_on()
