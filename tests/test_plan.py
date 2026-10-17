"""Plan my day (tasks/plan), behind PLAN_MY_DAY: the card from every task's day (to-dos placed around a
reminder and an event), Claude's estimates and lengths said, changes in words on the open card, Save with the
times on the Today card, Put it on my calendar (a card first, then blocks on the Bot calendar, replaced when the
day is planned again and never planned around), replan from now, tomorrow, a day with no free time, and the
contract (help, #commands, the router's catalogue). Made-up names only."""
import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, clock, config, confirm, database, planning, summaries
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks.calendar import store as calendar_store
from tasks.calendar import task as calendar_task
from tasks.calendar.rules import Event
from tasks.nudges import store as nudges_store
from tasks.nudges import task as nudges_task
from tasks.nudges.rules import Nudge
from tasks.plan import plain, store
from tasks.plan import task as plan_task
from tasks.todos import store as todos_store
from tasks.todos import task as todos_task

INBOX = 100


def run(coroutine):
    return asyncio.run(coroutine)


class FakeBot:
    """The Bot calendar, made up: what was added and deleted."""

    origin = "bot"
    can_write = True

    def __init__(self):
        self.added, self.deleted, self.next = [], [], 0

    async def add(self, title, start, end):
        self.next += 1
        made = Event(f"bot:b{self.next}@{start.isoformat()}", title, start, end, origin="bot", ref=f"b{self.next}")
        self.added.append(made)
        return made

    async def delete(self, ref):
        self.deleted.append(ref)


@pytest.fixture
def world(make_db, dev_clock, monkeypatch, owner):
    """A Monday at 8 am: three to-dos, a reminder at 12:30 pm; plan, to-dos and reminders in the catalogue."""
    make_db({"todos": todos_store.MIGRATIONS, "nudges": nudges_store.MIGRATIONS, "plan": store.MIGRATIONS, "calendar": calendar_store.MIGRATIONS})
    monkeypatch.setattr(config, "PLAN_MY_DAY", True)
    seen = SimpleNamespace(owner=owner, told=[], bot=FakeBot())
    monday = days.today() + timedelta(days=(0 - days.today().weekday()) % 7 or 7)
    seen.day = monday
    clock.advance_to(days.at(monday, time(8, 0)))
    actions.set_catalogue([*todos_task.entries(), *nudges_task.entries(), *calendar_task.entries(), *plan_task.entries()])
    monkeypatch.setattr(summaries, "changed", lambda task, user_id: seen.told.append(task))
    monkeypatch.setattr(plain, "calendar_writer", lambda: seen.bot)
    from tasks.calendar import plain as calendar_plain

    monkeypatch.setattr(calendar_plain, "_changed", lambda user_id: None)
    now = clock.now()
    seen.todos = {}
    for text, day in (("Write the essay", monday - timedelta(days=1)), ("Weekly shop", monday), ("Email Sam", None)):
        seen.todos[text] = f"t{run(database.run(todos_store.db_add, owner.id, text, day, monday - timedelta(days=2), now))}"
    run(database.run(nudges_store.db_add, Nudge(0, owner.id, "Made-up call", time(12, 30), "once", monday), now))
    seen.request = lambda text="said", previous=None: Request(owner, INBOX, text, previous=previous)
    return seen


def estimates(world, **minutes):
    return [{"todo": world.todos[text], "length": str(value)} for text, value in minutes.items()]


def card(world, data, previous=None, text="plan my day"):
    return run(plain.plan_card(world.request(text, previous), data, frozenset()))


def first(world):
    return card(world, {"estimates": estimates(world, **{"Write the essay": 90, "Weekly shop": 60, "Email Sam": 15})})


def at(world, hour, minute=0, day=None):
    return days.at(day or world.day, time(hour, minute))


# --- the card ------------------------------------------------------------------------------------------------------------
def test_plan_my_day_is_a_card_in_time_order_with_the_reminder_fixed(world):
    proposal = first(world)
    assert proposal.kind == "new" and proposal.can_save
    assert proposal.lines[0].startswith("**Today · ") and "3 things planned" in proposal.lines[0]
    slots = [(each["text"], datetime.fromisoformat(each["start"]), each["minutes"]) for each in proposal.data["slots"]]
    assert slots == [("Write the essay", at(world, 8), 90), ("Weekly shop", at(world, 9, 45), 60), ("Email Sam", at(world, 11, 0), 15)]
    assert any(each == "12:30 pm · ⏰ Made-up call · fixed" or each.endswith("Made-up call · fixed") for each in proposal.lines)
    assert "**8:00 am · 📝 Write the essay** · 1h 30m" in proposal.lines
    assert any(each.startswith("-# free ") for each in proposal.lines)
    assert [choice.label for choice in proposal.also] == [plain.CALENDAR_LABEL]
    assert run(store.day(world.owner.id, world.day)) == [], "nothing is saved until Save"


def test_save_keeps_the_times_and_the_today_card_shows_them(world):
    proposal = first(world)
    said = run(plain.plan_save(world.request(), proposal.data))
    assert said.startswith("🗓️ Saved · today's plan · 3 things · first 8:00 am") and plan_task.name in world.told
    assert run(plain.plan_check(world.request(), proposal.data)) == ""
    lines = run(plain.today_lines(world.owner.id, clock.now()))
    assert [(line.text, line.at) for line in lines] == [
        ("**Write the essay** · planned", at(world, 8)), ("**Weekly shop** · planned", at(world, 9, 45)), ("**Email Sam** · planned", at(world, 11)),
    ]
    run(database.run(todos_store.db_done, int(world.todos["Email Sam"][1:]), clock.now(), world.day))
    assert [line.done for line in run(plain.today_lines(world.owner.id, clock.now()))] == [False, False, True], "a to-do done is done on the Today card"
    lengths = run(database.run(store.db_lengths, world.owner.id))
    assert lengths[world.todos["Write the essay"]] == (90, False), "Claude's estimate is kept for the next plan"


def test_changes_in_words_before_saving(world):
    proposal = first(world)
    out = card(world, {"out": [{"from": "8:00", "to": "10"}]}, previous=proposal.data, text="I'm out 8 to 10")
    starts = {each["text"]: datetime.fromisoformat(each["start"]) for each in out.data["slots"]}
    assert all(start >= at(world, 10, 15) for start in starts.values()), "nothing in the time out, and 15 minutes after"
    assert any("out until 10:00 am · fixed" in each for each in out.lines)
    moved = card(world, {"moves": [{"todo": "laundry"}, {"todo": world.todos["Weekly shop"], "part": "evening"}]}, previous=out.data, text="move the shop to the evening")
    assert datetime.fromisoformat(next(each for each in moved.data["slots"] if each["text"] == "Weekly shop")["start"]) >= at(world, 17)
    assert "“laundry” is not among your to-dos" in moved.warnings, "a to-do that isn't there is said, never guessed"
    dropped = card(world, {"drop": ["Email Sam"]}, previous=moved.data, text="drop the email")
    assert "Email Sam" not in {each["text"] for each in dropped.data["slots"]}
    longer = card(world, {"lengths": [{"todo": "essay", "minutes": 120}]}, previous=dropped.data, text="make the essay 2 hours")
    essay = next(each for each in longer.data["slots"] if each["text"] == "Write the essay")
    assert essay["minutes"] == 120 and longer.data["lengths"][world.todos["Write the essay"]] == [120, True]
    later = card(world, {"starts": "9:00", "day": "tomorrow"}, previous=longer.data, text="I start at 9 tomorrow")
    assert later.data["day"] == (world.day + timedelta(days=1)).isoformat()
    assert min(datetime.fromisoformat(each["start"]) for each in later.data["slots"]) >= at(world, 9, day=world.day + timedelta(days=1))


def test_put_it_on_my_calendar_is_a_card_first_then_blocks_replaced_when_planned_again(world):
    proposal = first(world)
    (choice,) = proposal.also
    asked = card(world, choice.data)
    assert asked.data["calendar"] is True and [each.label for each in asked.also] == [plain.NO_CALENDAR_LABEL]
    assert "-# Save adds 3 blocks to the Bot calendar too" in asked.lines and not world.bot.added, "nothing is added by the press"
    said = run(plain.plan_save(world.request(), asked.data))
    assert said.endswith("· on the Bot calendar") and [each.title for each in world.bot.added] == ["Write the essay", "Weekly shop", "Email Sam"]
    assert run(plain.plan_check(world.request(), asked.data)) == ""
    assert run(plain.today_lines(world.owner.id, clock.now())) == [], "the calendar's own lines show them: not twice"
    # The blocks are the plan's own: planning again neither plans around them nor keeps the old ones
    again = card(world, {**choice.data})
    assert len(again.data["slots"]) == 3 and again.data["slots"][0]["start"] == proposal.data["slots"][0]["start"]
    run(plain.plan_save(world.request(), again.data))
    assert sorted(world.bot.deleted) == ["b1", "b2", "b3"] and len(world.bot.added) == 6


def test_replan_from_now_keeps_what_is_done_and_places_the_rest_after_now(world):
    run(plain.plan_save(world.request(), first(world).data))
    run(database.run(todos_store.db_done, int(world.todos["Write the essay"][1:]), clock.now(), world.day))
    clock.advance_to(at(world, 13, 2))
    replanned = card(world, {"from_now": True}, text="replan")
    assert [each["text"] for each in replanned.data["slots"]] == ["Weekly shop", "Email Sam"]
    assert min(datetime.fromisoformat(each["start"]) for each in replanned.data["slots"]) >= at(world, 13, 5)
    assert "-# ✅ done: Write the essay" in replanned.lines


def test_a_day_with_no_free_time_has_nothing_to_save(world):
    run(database.run(calendar_store.db_put, world.owner.id, Event("link:x@1", "Made-up conference", at(world, 6), at(world, 23), origin="link", ref="x")))
    proposal = first(world)
    assert not proposal.can_save and not proposal.data["slots"] and not proposal.also
    assert any(each.startswith("No free time between 8:00 am and 10:00 pm") for each in proposal.warnings)


def test_after_the_day_s_end_it_says_to_plan_tomorrow(world):
    clock.advance_to(at(world, 22, 30))
    with pytest.raises(UserError, match="plan tomorrow"):
        first(world)
    tomorrow = card(world, {"day": "tomorrow", "estimates": estimates(world, **{"Email Sam": 15})}, text="plan tomorrow")
    assert tomorrow.lines[0].startswith("**Tomorrow · ") and tomorrow.data["slots"][0]["start"] == at(world, 7, day=world.day + timedelta(days=1)).isoformat()


# --- the core's confirm card: Save, Put it on my calendar, Cancel ----------------------------------------------------------
def test_the_card_has_save_green_the_calendar_blurple_and_cancel_grey(world):
    from core import cards

    entry = actions.entry(plan_task.name)
    shown = confirm.render(entry, first(world), 7)
    (row,) = shown.rows
    assert [(button.label, button.style) for button in row] == [("Save", cards.SUCCESS), (plain.CALENDAR_LABEL, cards.PRIMARY), ("Cancel", cards.SECONDARY)]
    assert actions.ALSO in confirm.kept(first(world)) and actions.ALSO not in confirm.applied(confirm.kept(first(world)))
    cards.check(shown)


def test_the_plan_task_is_in_the_catalogue_with_a_say_for_commands_and_states_ids(world):
    entry = actions.entry(plan_task.name)
    assert not actions.problems(actions.catalogue()), actions.problems(actions.catalogue())
    (action,) = entry.actions
    assert action.say == ("plan my day", "plan tomorrow", "replan") and action.purpose == actions.EACH_DAY
    state = run(plain.state(world.request()))
    assert f"{world.todos['Write the essay']}: Write the essay (overdue)" in state.lines
    assert f"{world.todos['Email Sam']}: Email Sam (any day)" in state.lines
