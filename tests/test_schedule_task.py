"""My schedule in plain words (tasks/schedule): the list, and changing, adding and removing by a card."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, backup, clock, database, day, design, names, scheduler, timetable
from core.actions import Request
from core.errors import UserError
from tasks import registry
from tasks.pills import checklist
from tasks.schedule import plain, rules
from tasks.schedule import task as schedule_task

INBOX = 100


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def world(db, dev_clock, monkeypatch, owner):
    """The schedules a fresh database gets (the backup, the bot's own; the pills
    checklist, mine), at noon tomorrow, a Wednesday or whatever it is."""
    async def ran(job):
        pass

    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_labels", {})
    scheduler.register_handler("pills", checklist.JOB, ran, "pills checklist")
    scheduler.register_handler(backup.JOB_TASK, backup.JOB_KIND, ran, "nightly backup")
    monkeypatch.setattr(scheduler, "_standing", {("pills", checklist.JOB): checklist.DEFAULT, (backup.JOB_TASK, backup.JOB_KIND): backup.DEFAULT})
    seen = SimpleNamespace(owner=owner, changed=[])
    monkeypatch.setattr(plain, "list_changed", lambda user_id: seen.changed.append(user_id))
    seen.today = day.today() + timedelta(days=1)
    clock.advance_to(day.at(seen.today, time(12, 0)))
    run(scheduler.book())
    seen.request = lambda text="said", previous=None: Request(owner, INBOX, text, previous=previous)
    return seen


def schedules():
    return {each.name: each for each in run(plain.every())}


def change(world, said, *items, previous=None, guessed=frozenset()):
    return run(plain.change_card(world.request(said, previous), {"schedules": list(items)}, guessed))


def booked(kind=checklist.JOB):
    return [job.local_at for job in run(scheduler.pending_jobs("pills", kind))]


# --- the list ---------------------------------------------------------------------------------------------------
def test_the_list_shows_each_schedule_when_it_runs_where_and_its_next_run(world):
    shown = run(plain.list_card())
    tomorrow = world.today + timedelta(days=1)
    assert shown.text.splitlines()[:5] == [
        "## 🗓️ My schedule", "-# 1 on · times are New Zealand time", "", "**Pills checklist** · every day at `6:00 am`",
        "-# #hub · silent · next: tomorrow 6:00 am",
    ]
    assert "-# The bot's own, not changed here: nightly backup 3:00 am" in shown.text and "-# Pill times belong to each pill: say “pills”" in shown.text
    assert design.problem(shown.layout) == "" and design.buttons(shown.layout) == [], "drawn within the limits, and no buttons: every change is by words"
    assert shown.layout[1].status == design.DUE, "the next to run is amber"
    assert design.texts(shown.layout)[1].startswith("**Pills checklist** · every day at `6:00 am`") and tomorrow > world.today


def test_paused_ones_are_together_and_a_routine_lists_its_steps(world):
    sheet = schedules()["Pills checklist"]
    run(database.run(lambda conn: timetable.db_update(conn, sheet.id, clock.now(), state=timetable.PAUSED, paused_until=world.today + timedelta(days=5))))
    shown = run(plain.list_card())
    assert "⏸️ **Paused**" in shown.text and "Pills checklist · every day at `6:00 am` · until" in shown.text and "0 on · 1 paused" in shown.text
    assert shown.layout[-2].status == design.QUIET
    listed = rules.Listed(sheet, ("tidy", "briefing", "pills checklist"))
    assert rules._steps(listed) == ["1. tidy", "2. briefing", "3. pills checklist"] and rules._steps(rules.Listed(sheet, ("pills checklist",))) == []


def test_the_typed_word_and_the_contract():
    registry.load()
    kind, task, item = registry.find("my schedule")
    assert (kind, task.name, item.exact) == ("keyword", "schedule", True) and registry.find("schedule")[1].name == "schedule"
    (entry,) = schedule_task.entries()
    assert [action.name for action in entry.actions] == ["schedule_show", "schedule_change", "schedule_add", "schedule_remove"]
    assert entry.show == "schedule_show" and actions.problems([entry]) == []
    change_fields = {field.name: field for field in entry.action("schedule_change").field("schedules").item_fields}
    assert change_fields["time"].type == actions.TIME and change_fields["days"].choices == rules.DAY_WORDS
    assert change_fields["days_change"].choices == ("add", "set", "remove") and change_fields["notify"].choices == ("silent", "notify")
    assert "pills task" in entry.only_for, "a pill's own times are not this task's"


# --- change -----------------------------------------------------------------------------------------------------
def test_moving_one_is_a_card_with_old_to_new_and_when_it_next_runs_and_only_save_writes_it(world):
    asked = change(world, "move the pills checklist to 7", {"schedule": "pills checklist", "time": "7:00 am"})
    assert asked.lines == ("**Pills checklist**", "time · `6:00 am` → `7:00 am`", "-# Next after this: Pills checklist tomorrow 7:00 am")
    assert asked.kind == "change" and asked.question is None and schedules()["Pills checklist"].at == time(6, 0), "nothing is written by asking"
    said = run(plain.change_save(world.request(), asked.data))
    assert said == "✅ Saved · 🗓️ **Pills checklist** · time · `6:00 am` → `7:00 am`"
    assert run(plain.change_check(world.request(), asked.data)) == "" and schedules()["Pills checklist"].at == time(7, 0)
    tomorrow = world.today + timedelta(days=1)
    assert booked() == [f"{tomorrow.isoformat()}T07:00"], "the run that was booked follows the schedule at once"
    assert world.changed == [world.owner.id], "the list last shown is brought up to date"


def test_days_are_set_added_and_taken_away_and_never_left_empty(world):
    weekdays = change(world, "checklist on weekdays only", {"schedule": "checklist", "days": ["mon", "tue", "wed", "thu", "fri"], "days_change": "set"})
    assert weekdays.lines[1] == "days · every day → Mon to Fri"
    run(plain.change_save(world.request(), weekdays.data))
    also = change(world, "also Saturdays", {"schedule": "checklist", "days": ["sat"], "days_change": "add"})
    assert also.lines[1] == "days · Mon to Fri → Mon to Sat"
    fewer = change(world, "not on Mondays", {"schedule": "checklist", "days": ["mon"], "days_change": "remove"})
    assert fewer.lines[1] == "days · Mon to Fri → Tue to Fri"
    none = change(world, "not on weekdays", {"schedule": "checklist", "days": ["mon", "tue", "wed", "thu", "fri"], "days_change": "remove", "notify": "notify"})
    assert none.lines[1] == "notify · silent → notifies" and none.warnings == ("Pills checklist: That leaves no day at all: remove it or pause it instead",)


def test_pause_until_a_day_resume_silent_and_channel(world):
    paused = change(world, "pause the checklist until Friday", {"schedule": "checklist", "paused": "pause", "until": (world.today + timedelta(days=3)).strftime("%A")})
    until = world.today + timedelta(days=3)
    assert paused.lines[1] == f"paused · no → until {until:%a} {until.day} {until:%b}"
    assert paused.lines[2] == f"-# Next after this: Pills checklist {until:%a} {until.day} {until:%b} 6:00 am"
    run(plain.change_save(world.request(), paused.data))
    assert booked() == [f"{until.isoformat()}T06:00"], "nothing is booked before the day it is on again"
    back = change(world, "turn it back on", {"schedule": "@that", "paused": "resume"})
    assert back.lines[:2] == ("**Pills checklist** ❓", f"paused · until {until:%a} {until.day} {until:%b} → on"), "“it” was the code's pick: marked"
    for_good = change(world, "pause the checklist", {"schedule": "checklist", "paused": "pause", "channel": "inbox", "notify": "notify"})
    assert "notify · silent → notifies" in for_good.lines and "channel · #hub → #inbox" in for_good.lines
    assert for_good.lines[-1] == "-# Next after this: Pills checklist: not while it is paused"
    with pytest.raises(UserError, match="Nothing to change|already like that"):
        change(world, "make the checklist silent", {"schedule": "checklist", "notify": "silent"})


def test_what_can_t_be_read_is_said_and_the_rest_is_kept(world):
    asked = change(world, "checklist at 7 in #nowhere until blursday", {"schedule": "checklist", "time": "7:00 am", "channel": "nowhere", "until": "blursday"})
    assert asked.lines[1] == "time · `6:00 am` → `7:00 am`" and len(asked.warnings) == 2
    assert asked.warnings[0] == "Pills checklist: I don't know a channel called #nowhere" and "blursday" in asked.warnings[1]


def test_the_bot_s_own_are_refused_in_a_line_and_an_unknown_name_says_which_there_are(world):
    with pytest.raises(UserError, match="Nightly backup is the bot's own: it isn't changed here"):
        change(world, "move the backup to 4", {"schedule": "backup", "time": "4:00 am"})
    with pytest.raises(UserError, match="I don't have a schedule called “briefing”. Yours: Nightly backup, Pills checklist."):
        change(world, "move the briefing to 7", {"schedule": "briefing", "time": "7:00 am"})
    assert schedules()["Nightly backup"].at == time(3, 0)


def test_a_name_that_fits_two_is_asked_on_the_card_and_the_answer_is_not_asked_again(world):
    run(plain.add_save(world.request(), run(plain.add_card(world.request("also the checklist at 6pm"), {"what": "pills checklist", "time": "6:00 pm"}, frozenset())).data))
    asked = change(world, "move the checklist to 7", {"schedule": "checklist", "time": "7:00 am"})
    assert asked.question.text == "Which one is “checklist”?" and [choice.label for choice in asked.question.choices] == ["Pills checklist", "Evening pills checklist"]
    assert asked.lines == () and asked.data == {"schedules": []}
    answered = run(plain.change_card(world.request(""), asked.question.choices[1].data, frozenset()))
    assert answered.question is None and answered.lines[:2] == ("**Evening pills checklist**", "time · `6:00 pm` → `7:00 am`")
    # Another word of what was typed says which: no question, though "checklist" fits both
    evening = change(world, "move the evening checklist to 6:30pm", {"schedule": "evening checklist", "time": "6:30 pm"})
    assert evening.question is None and evening.lines[:2] == ("**Evening pills checklist**", "time · `6:00 pm` → `6:30 pm`")
    named = change(world, "move the evening checklist to 6:30pm", {"schedule": "Evening pills checklist", "time": "6:30 pm"})
    assert named.question is None and named.lines[0] == "**Evening pills checklist**"
    # Claude completing the name does not get past what was typed
    completed = change(world, "pause the checkl", {"schedule": "Pills checklist", "paused": "pause"})
    assert completed.question is not None and completed.question.text == "Which one is “checkl”?"
    # "it" with two it could be is a question too
    assert change(world, "pause it", {"schedule": "@that", "paused": "pause"}).question.text == "Which schedule?"


def test_a_correction_to_the_open_card_keeps_what_it_held(world):
    first = change(world, "move the checklist to 7 and make it notify", {"schedule": "checklist", "time": "7:00 am", "notify": "notify"})
    second = change(world, "no, 7:30", {"schedule": "@that", "time": "7:30 am"}, previous=first.data)
    assert second.lines[1:3] == ("time · `6:00 am` → `7:30 am`", "notify · silent → notifies")


def test_moved_after_it_ran_today_the_card_says_tomorrow(world):
    tomorrow = world.today + timedelta(days=1)
    clock.advance_to(day.at(tomorrow, time(6, 0, 5)))
    run(scheduler.run_all_due())
    asked = change(world, "move the checklist to 9", {"schedule": "checklist", "time": "9:00 am"})
    assert asked.lines[-1] == "-# Next after this: Pills checklist tomorrow 9:00 am", "it has run today: once a day"
    clock.advance_to(day.at(tomorrow + timedelta(days=1), time(5, 0)))
    before = change(world, "move the checklist to 9", {"schedule": "checklist", "time": "9:00 am"})
    assert before.lines[-1] == "-# Next after this: Pills checklist today 9:00 am"


# --- add and remove ---------------------------------------------------------------------------------------------
def test_adding_another_time_for_something_that_can_be_scheduled(world):
    asked = run(plain.add_card(world.request("also post the pills checklist at 6 pm on weekdays"), {"what": "pills checklist", "time": "6:00 pm", "days": ["mon", "tue", "wed", "thu", "fri"]}, frozenset()))
    assert asked.lines[0] == "**Evening pills checklist** · Mon to Fri at `6:00 pm`" and asked.lines[1].startswith("-# #hub · silent · next: ")
    assert asked.lines[2] == "-# also every day at `6:00 am`" and asked.kind == "new"
    assert run(plain.add_save(world.request(), asked.data)) == "✅ Saved · 🗓️ **Evening pills checklist** · Mon to Fri at `6:00 pm`"
    assert run(plain.add_check(world.request(), asked.data)) == ""
    made = schedules()["Evening pills checklist"]
    assert (made.origin, made.user_id, made.steps, made.days) == ("mine", world.owner.id, ("pills.checklist",), (0, 1, 2, 3, 4))
    assert len(booked()) == 2, "each schedule has its own next run booked"
    with pytest.raises(UserError, match="already runs Mon to Fri at `6:00 pm`: nothing to add"):
        run(plain.add_card(world.request(), {"what": "checklist", "time": "6:00 pm"}, frozenset()))


def test_with_no_time_the_card_asks_and_what_can_t_be_scheduled_is_said(world):
    asked = run(plain.add_card(world.request("also post the checklist in the evening"), {"what": "checklist"}, frozenset()))
    assert asked.lines == ("**Pills checklist** · every day at ❔",) and asked.question.text == "At what time?"
    assert [choice.label for choice in asked.question.choices] == ["6:00 am", "6:00 pm"]
    answered = run(plain.add_card(world.request(""), asked.question.choices[1].data, frozenset()))
    assert answered.question is None and answered.lines[0] == "**Evening pills checklist** · every day at `6:00 pm`"
    with pytest.raises(UserError, match="I can't schedule “the weather”. What I can: pills checklist."):
        run(plain.add_card(world.request(), {"what": "the weather", "time": "7:00 am"}, frozenset()))
    with pytest.raises(UserError, match="I can't schedule “backup”"):
        run(plain.add_card(world.request(), {"what": "backup", "time": "4:00 am"}, frozenset()))


def test_removing_one_keeps_its_row_stops_its_runs_and_adding_it_back_is_the_same_row(world):
    asked = run(plain.remove_card(world.request("stop posting the checklist"), {"schedules": [{"schedule": "checklist"}]}, frozenset()))
    assert asked.lines == ("**Pills checklist** · every day at `6:00 am` → removed", "-# It stops running. What it did is kept, and it can be added back")
    assert asked.kind == "remove" and asked.confirm_label == "Remove" and not asked.destructive
    sheet_id = schedules()["Pills checklist"].id
    assert run(plain.remove_save(world.request(), asked.data)) == "🗑️ Removed **Pills checklist** · still scheduled: nothing"
    assert run(plain.remove_check(world.request(), asked.data)) == "" and "Pills checklist" not in schedules() and booked() == []
    run(scheduler.book())  # the next start: the default is not made a second time
    assert "Pills checklist" not in schedules() and booked() == []
    back = run(plain.add_card(world.request("post the checklist at 7am"), {"what": "checklist", "time": "7:00 am"}, frozenset()))
    run(plain.add_save(world.request(), back.data))
    assert schedules()["Pills checklist"].id == sheet_id and schedules()["Pills checklist"].at == time(7, 0) and len(booked()) == 1
    with pytest.raises(UserError, match="isn't removed here"):
        run(plain.remove_card(world.request(), {"schedules": [{"schedule": "backup"}]}, frozenset()))


def test_the_state_claude_is_given_and_the_names_for_the_router(world):
    said = run(plain.state(world.request()))
    assert said == (
        "The user's schedules now (use the name): Nightly backup (every day at 3:00 am, the bot's own); "
        "Pills checklist (every day at 6:00 am, silent, #hub). Can be scheduled: pills checklist."
    )
    assert "cannot" not in said and "can't" not in said, "nothing in it invites Claude to decline: the code says what is the bot's own"
    (entry,) = schedule_task.entries()
    assert "Never decline because of whose it is" in entry.action("schedule_change").description
    assert run(plain.item_names(world.request())) == ["Pills checklist"]
    assert isinstance(names.unclear(list(schedules().values()), "move the checklist", lambda each: each.name), type(None))


def test_what_an_added_schedule_is_called():
    assert rules.name_for("pills checklist", time(18, 0), set()) == "Pills checklist"
    assert rules.name_for("pills checklist", time(18, 0), {"pills checklist"}) == "Evening pills checklist"
    assert rules.name_for("pills checklist", time(7, 0), {"pills checklist"}) == "Morning pills checklist"
    assert rules.name_for("pills checklist", time(19, 0), {"pills checklist", "evening pills checklist"}) == "Evening pills checklist 2"
    assert [rules.part_of_day(time(hour, 0)) for hour in (0, 11, 12, 16, 17, 20, 21, 23)] == ["Morning", "Morning", "Afternoon", "Afternoon", "Evening", "Evening", "Night", "Night"]


def test_the_words_for_days_and_dates():
    today = date(2026, 10, 14)  # a Wednesday
    assert rules.read_days(["Mon", "wednesday", "SUN"]) == (0, 2, 6) and rules.changed_days((0, 1), (1, 2), "add") == (0, 1, 2)
    assert rules.day_text(today, today) == "today" and rules.day_text(date(2026, 10, 15), today) == "tomorrow" and rules.day_text(date(2026, 10, 19), today) == "Mon 19 Oct"
    assert rules.read_until("Monday", today) == date(2026, 10, 19)
    with pytest.raises(UserError, match="not a day of the week"):
        rules.read_days(["someday"])
    with pytest.raises(UserError, match="later day"):
        rules.read_until("today", today)
