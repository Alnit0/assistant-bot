"""The summary in the task contract (core/summaries.py), the pills summary, and the briefing (tasks/briefing)."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, clock, config, database, day, design, hub, livelists, scheduler, summaries, tidy
from core.actions import Entry, LiveReply, Request, Shown, Summary
from tasks import briefing
from tasks.briefing import rules
from tasks.pills import checklist, reminders
from tasks.pills import summary as pills_summary
from tasks.pills import task as pills_task
from tests.test_pills_reminders import EVENING, HUB, INBOX, PILL_A, add, at, log, press, run, world  # noqa: F401


def _entry(name, summary=None, icon="📦"):
    return Entry(name, icon, f"Only for {name}.", ("a", "b"), (), summary=summary, on_repeat="allow_another")


# --- the contract and the gathering ------------------------------------------------------------------------------
def test_a_task_with_a_summary_is_gathered_and_one_with_nothing_to_say_is_left_out(monkeypatch):
    async def pills(user_id, on):
        return Summary("2 of 6 taken", design.DUE, ("**Next:** Pill A · `8:00 am`",), "1 to take any time", "Yesterday: 5 of 6 taken")

    async def nothing(user_id, on):
        return None

    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue([_entry("pills", pills, "💊"), _entry("gym", nothing, "🏋️"), _entry("timers")])
    (found,) = asyncio.run(summaries.gather(1, date(2026, 10, 14)))
    assert (found.task, found.icon, found.title, found.problem) == ("pills", "💊", "Pills", ""), "the icon and the name are the entry's"
    assert found.summary.glance == "2 of 6 taken" and found.summary.status == design.DUE


def test_one_that_fails_or_takes_too_long_says_so_and_never_stops_the_others(monkeypatch):
    said = []

    async def broken(user_id, on):
        raise RuntimeError("boom")

    async def slow(user_id, on):
        await asyncio.sleep(5)

    async def fine(user_id, on):
        return Summary("all done", design.DONE)

    async def log_error(title, details):
        said.append(title)

    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(summaries, "log_error", log_error)
    monkeypatch.setattr(summaries, "TIME_LIMIT", 0.05)
    actions.set_catalogue([_entry("broken", broken), _entry("slow", slow), _entry("fine", fine)])
    found = asyncio.run(summaries.gather(1, date(2026, 10, 14)))
    assert [(each.task, each.problem) for each in found] == [("broken", "couldn't be read"), ("slow", "couldn't be read"), ("fine", "")]
    assert said == ["Summary could not be read: broken", "Summary could not be read: slow"], "the reason goes to #bot-log"


def test_a_summary_is_kept_short_and_what_is_left_out_is_counted():
    long = Summary("x" * 300, design.DUE, ("one", "", "two", "three", "four", "five"), "hint", "before")
    short = summaries.trimmed(long)
    assert short.lines == ("one", "two", "…and 3 more") and len(short.glance) == summaries.MAX_LINE and short.glance.endswith("…")
    assert summaries.trimmed(Summary("ok", design.DONE, ("a", "b", "c"))).lines == ("a", "b", "c")


def test_whoever_shows_summaries_is_told_when_one_may_have_changed(monkeypatch):
    told = []
    monkeypatch.setattr(summaries, "_listeners", [])

    def listener(task, user_id):
        told.append((task, user_id))

    def broken(task, user_id):
        raise RuntimeError("no")

    summaries.on_change(broken)
    summaries.on_change(listener)
    summaries.on_change(listener)  # registered again: still told once
    summaries.changed("pills", 7)
    assert told == [("pills", 7)], "one listener failing never stops the task's own work or the others"


def test_the_contract_carries_the_summary_only_for_a_task_that_has_one():
    (pills_entry,) = pills_task.entries()
    assert pills_entry.summary is not None
    from tasks.schedule import task as schedule_task

    assert schedule_task.entries()[0].summary is None, "a task that has none is simply not in the briefing"


# --- the pills summary -------------------------------------------------------------------------------------------
def test_pills_in_a_few_lines_from_what_the_checklist_works_out(world):
    assert run(pills_summary.summary(world.owner.id, world.day)) is None, "nothing to take today: nothing to say"
    add(world, PILL_A, EVENING, {"name": "Any"})
    said = run(pills_summary.summary(world.owner.id, world.day))
    assert (said.glance, said.status, said.lines, said.hint, said.before) == ("0 of 5 taken", design.DUE, ("**Next:** Pill A, dose 1 · `8:00 am`",), "1 to take any time", "")
    at(world, 8, 0)
    press(world, reminders.P_TAKEN)
    log(world, {"pill": "any", "did": "taken"})
    said = run(pills_summary.summary(world.owner.id, world.day))
    assert said.glance == "2 of 5 taken" and said.lines == ("**Next:** Pill A, dose 2 · `11:30 am`",) and said.hint == ""


def test_its_colour_is_that_of_what_is_still_to_do(world):
    add(world, {"name": "Any"})
    assert run(pills_summary.summary(world.owner.id, world.day)).status == design.ANY_TIME, "only doses with no time are left"
    log(world, {"pill": "any", "did": "taken"})
    done = run(pills_summary.summary(world.owner.id, world.day))
    assert (done.status, done.glance, done.lines) == (design.DONE, "1 of 1 taken", ())


def test_yesterday_is_one_line_from_the_occurrence_log(world):
    add(world, EVENING, {"name": "Any"}, {"name": "Other"})
    log(world, {"pill": "any", "did": "taken"})
    log(world, {"pill": "other", "did": "skipped"})
    tomorrow = world.day + timedelta(days=1)
    clock.advance_to(day.at(tomorrow, time(6, 0, 30)))
    run(scheduler.run_all_due())
    said = run(pills_summary.summary(world.owner.id, tomorrow))
    assert said.before == "Yesterday: 1 of 3 taken · 1 missed · 1 skipped" and said.glance == "0 of 3 taken"
    assert pills_summary.yesterday([]) == "", "nothing to take yesterday: no line"


# --- the briefing ------------------------------------------------------------------------------------------------
SECTIONS = [
    summaries.Section("pills", "💊", "Pills", Summary("2 of 6 taken", design.DUE, ("**Next:** Pill A, dose 2 · `12:00 pm`",), "1 to take any time", "Yesterday: 5 of 6 taken · 1 missed")),
    summaries.Section("gym", "🏋️", "Gym", problem="couldn't be read"),
]


def test_the_briefing_is_a_heading_the_date_and_a_box_a_task_with_no_buttons():
    on = date(2026, 10, 14)
    assert rules.text(SECTIONS, on).splitlines() == [
        "## ☀️ Today", "-# Wednesday 14 October", "", "💊 **Pills** · 2 of 6 taken", "**Next:** Pill A, dose 2 · `12:00 pm`", "-# 1 to take any time",
        "-# Yesterday: 5 of 6 taken · 1 missed", "", "🏋️ **Gym**", "-# ⚠️ couldn't be read", "", f"-# {rules.FOOT}",
    ]
    drawn = rules.layout(SECTIONS, on)
    assert design.problem(drawn) == "" and design.buttons(drawn) == [], "things are ticked off on the task's own message"
    assert [piece.status for piece in drawn[1:3]] == [design.DUE, design.QUIET], "a box in the colour of its status; one that couldn't be read is grey"
    assert design.texts(drawn)[0] == "# ☀️ Today\n-# Wednesday 14 October" and "as of" not in rules.text(SECTIONS, on), "it always shows now: nothing says when it was written"
    assert rules.notice("6:00 am") == "☀️ Morning briefing · 6:00 am"


@pytest.fixture
def on(world, monkeypatch):
    """The briefing switched on, in the world of the pills tests (a hub, cards that record)."""
    monkeypatch.setattr(config, "BRIEFING_ENABLED", True)
    monkeypatch.setattr(summaries, "_listeners", [])
    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue([*pills_task.entries(), *briefing.task.entries()])
    world.pointed = []

    async def pointer(channel_id, text):
        world.pointed.append((channel_id, text))

    monkeypatch.setattr(tidy, "pointer", pointer)
    return world


def test_switched_off_it_offers_nothing_posts_nothing_and_joins_no_routine(world, monkeypatch):
    monkeypatch.setattr(config, "BRIEFING_ENABLED", False)
    task = briefing.task
    assert task.actions() == [] and task.keywords() == [] and task.job_handlers() == {} and task.job_labels() == {} and task.entries() == []
    task.setup(None)
    assert scheduler.routine_steps(hub.MORNING) == (hub.MORNING,) and summaries._listeners == [] or briefing.summary_changed not in summaries._listeners


def test_switched_on_it_is_a_task_with_brief_me_and_joins_the_morning_routine_before_the_checklist(on):
    task = briefing.task
    (entry,) = task.entries()
    assert [action.name for action in entry.actions] == ["briefing_show"] and entry.show == "briefing_show" and actions.problems([entry]) == []
    assert [keyword.words for keyword in task.keywords()] == [["briefing", "brief me"]] and task.job_labels() == {"post": "briefing"}
    task.setup(None)
    assert scheduler.routine_steps(hub.MORNING) == ("briefing.post", "pills.checklist"), "the briefing first, so the checklist is the newest message"
    assert briefing.summary_changed in summaries._listeners


def test_the_morning_s_briefing_is_posted_once_silently_and_the_next_one_takes_its_place(on):
    add(on, PILL_A)
    first = run(briefing.post_in_hub(on.owner.id, HUB))
    posted = on.sent[-1]
    assert posted.id == first and posted.silent and posted.channel == HUB and posted.card.text.splitlines()[0] == "## ☀️ Today"
    assert "💊 **Pills** · 0 of 3 taken" in posted.card.text and posted.card.layout, "it carries its layout for the new look"
    second = run(briefing.post_in_hub(on.owner.id, HUB))
    assert second != first and on.deleted[-1] == first, "the new one is up, then the old goes: one at a time"
    assert run(database.run(livelists.db_get, on.owner.id, briefing.IN_THE_HUB)).message_id == second


def test_one_that_notifies_is_posted_as_the_neutral_line_and_written_in_after(on):
    add(on, PILL_A)
    at(on, 6, 0)
    message_id = run(briefing.post_in_hub(on.owner.id, HUB, notify=True))
    sent = next(each for each in on.sent if each.id == message_id)
    assert sent.card.text == "☀️ Morning briefing · 6:00 am" and not sent.silent, "what the phone shows names nothing of mine"
    assert on.edited[-1][0] == message_id and "Pill A" in on.edited[-1][1].text


def test_with_nothing_to_say_nothing_is_posted_and_brief_me_says_so(on):
    assert run(briefing.post_in_hub(on.owner.id, HUB)) is None and [each for each in on.sent if "Today" in each.card.text] == []
    assert run(briefing.show(Request(on.owner, INBOX, "brief me"), {}, frozenset())) == "☀️ Nothing on today."
    job = scheduler.Job(5, on.owner.id, "briefing", "post", {}, clock.now())
    run(briefing.post_job(job))
    assert scheduler._notes.pop(5) == "not posted: nothing to say today" and 5 not in scheduler._reported, "a morning with nothing in it is not a problem"


def test_when_a_section_changes_the_briefing_is_edited_in_place_and_nothing_new_is_posted(on):
    briefing.task.setup(None)
    add(on, {"name": "Any"})
    message_id = run(briefing.post_in_hub(on.owner.id, HUB))
    sent = len(on.sent)
    log(on, {"pill": "any", "did": "taken"})  # the checklist is brought up to date, and says its summary changed
    edits = [card.text for edited, card in on.edited if edited == message_id]
    assert edits and "💊 **Pills** · 1 of 1 taken" in edits[-1], "the briefing shows now"
    assert not [each for each in on.sent[sent:] if "☀️" in each.card.text], "no second briefing"


def test_brief_me_in_the_hub_brings_the_one_there_up_to_date_and_elsewhere_gives_a_copy(on):
    add(on, {"name": "Any"})
    asked = Request(on.owner, HUB, "brief me")
    first = run(briefing.show(asked, {}, frozenset()))
    assert isinstance(first, Shown) and first.summary == "the briefing was posted in the hub", "none there yet: one is posted"
    posted = len([each for each in on.sent if "☀️ Today" in each.card.text])
    again = run(briefing.show(asked, {}, frozenset()))
    assert again.summary == "the briefing in the hub was brought up to date in place" and on.pointed == [(HUB, "☀️ The briefing above is up to date.")]
    assert len([each for each in on.sent if "☀️ Today" in each.card.text]) == posted, "no new post in the hub"
    elsewhere = run(briefing.show(Request(on.owner, INBOX, "brief me"), {}, frozenset()))
    assert isinstance(elsewhere, LiveReply) and elsewhere.key == briefing.ELSEWHERE and elsewhere.card.layout and elsewhere.text.startswith("## ☀️ Today")


def test_the_morning_job_posts_for_the_schedule_s_user_and_says_what_it_decided(on):
    add(on, {"name": "Any"})
    job = scheduler.Job(9, on.owner.id, "briefing", "post", {}, clock.now())
    run(briefing.post_job(job))
    assert scheduler._notes.pop(9) == "posted" and [each for each in on.sent if "☀️ Today" in each.card.text]
    # No request to Claude is made anywhere in it: the world's Claude is not scripted, and would have refused


def test_the_checklist_says_its_summary_changed_whenever_it_is_brought_up_to_date(world, monkeypatch):
    told = []
    monkeypatch.setattr(summaries, "_listeners", [lambda task, user_id: told.append((task, user_id))])
    add(world, {"name": "Any"})
    run(checklist.refresh(world.owner.id))
    assert ("pills", world.owner.id) in told


# --- the summary only reads; the end of the day makes the rows ---------------------------------------------------------
def _counts():
    conn = database.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0], conn.execute("SELECT COUNT(*) FROM occurrence_events").fetchone()[0], conn.execute("SELECT GROUP_CONCAT(state) FROM occurrences").fetchone()[0]
    finally:
        conn.close()


def test_the_pills_summary_writes_nothing_not_a_row_and_not_a_state(world):
    add(world, PILL_A, {"name": "Any"})
    tomorrow = world.day + timedelta(days=1)
    before = _counts()
    assert run(pills_summary.summary(world.owner.id, tomorrow)) is None, "no rows for that day yet: nothing to say, and none is made"
    assert _counts() == before
    # Late in the day: doses that can no longer be taken read as they would on the checklist, and nothing is written
    clock.advance_to(day.at(world.day, time(23, 30)))
    said = run(pills_summary.summary(world.owner.id, world.day))
    assert _counts() == before, "what has passed is worked out, not written"
    assert said is not None and said.lines == () and said.status != design.DUE, f"no timed dose is still shown as to take: {said}"


def test_the_end_of_the_day_makes_the_new_day_s_rows_so_the_summary_finds_them(world):
    add(world, PILL_A, {"name": "Any"})
    tomorrow = world.day + timedelta(days=1)
    clock.advance_to(day.at(tomorrow, time(0, 0, 30)))
    run(checklist.new_day(world.day, tomorrow))
    said = run(pills_summary.summary(world.owner.id, tomorrow))
    assert said is not None and said.glance.startswith("0 of ") and "**Next:** Pill A, dose 1" in said.lines[0]
    before = _counts()
    run(checklist.new_day(world.day, tomorrow))
    assert _counts() == before, "asked twice, no second row"
