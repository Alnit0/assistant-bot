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


# --- the day's progress (DAY_PROGRESS) -------------------------------------------------------------------------
def test_progress_is_a_dot_a_thing_and_the_exact_count_and_never_a_percentage():
    assert design.progress(5, 7) == "●●●●●○○ 5/7" and design.progress(0, 3) == "○○○ 0/3" and design.progress(3, 3) == "●●● 3/3"
    assert design.dots(2, 3) == "●●○" and design.progress(10, 10) == "●●●●●●●●●● 10/10" and design.dots(0, 0) == ""
    assert "%" not in design.progress(1, 2) and "█" not in design.progress(1, 2)


def test_more_than_ten_things_are_ten_dots_scaled_with_the_exact_count_after():
    assert design.progress(6, 12) == "●●●●●○○○○○ 6/12" and design.progress(7, 21) == "●●●○○○○○○○ 7/21"
    assert design.progress(19, 20) == "●●●●●●●●●○ 19/20", "nearly there is never shown as done"
    assert design.progress(1, 40) == "●○○○○○○○○○ 1/40", "something done is never shown as nothing"
    assert design.progress(40, 40) == "●●●●●●●●●● 40/40" and design.progress(0, 40) == "○○○○○○○○○○ 0/40"
    assert all(len(design.dots(done, 25)) == design.MAX_DOTS for done in range(26))


def test_the_day_s_progress_adds_up_what_each_task_says_and_knows_no_task():
    pills = summaries.Section("pills", "💊", "Pills", Summary("2 of 3 taken", design.DUE, done=2, total=3))
    gym = summaries.Section("gym", "🏋️", "Gym", Summary("to do", design.DUE, done=0, total=1))
    weather = summaries.Section("weather", "🌤️", "Weather", Summary("14° to 20°", design.QUIET))
    unread = summaries.Section("todo", "📝", "Todo", problem="couldn't be read")
    assert rules.progress([pills]) == ("●●○ 2/3", "-# 💊 2/3")
    assert rules.progress([pills, weather, gym, unread]) == ("●●○○ 2/4", "-# 💊 2/3 · 🏋️ 0/1"), "one small line, a task that counts each, in the order given"
    assert rules.progress([weather, unread]) == () and rules.progress([]) == (), "nothing countable: nothing shown"


def test_the_day_s_total_is_in_the_title_with_the_small_line_a_task_under_the_date_in_both_looks():
    on = date(2026, 10, 14)
    so_far = ("●●●●●○○ 5/7", "-# 💊 5/7")
    assert design.DAY_TOTAL_IN_TITLE, "as built; the other way is one value in core/design.py"
    assert rules.text(SECTIONS, on, so_far=so_far).splitlines()[:4] == ["## ☀️ Today ●●●●●○○ 5/7", "-# Wednesday 14 October", "-# 💊 5/7", ""]
    drawn = rules.layout(SECTIONS, on, so_far=so_far)
    assert design.texts(drawn)[0] == "# ☀️ Today ●●●●●○○ 5/7\n-# Wednesday 14 October\n-# 💊 5/7" and design.problem(drawn) == ""
    assert rules.text(SECTIONS, on) == rules.text(SECTIONS, on, so_far=()), "with none it reads as it did"
    assert design.texts(rules.layout(SECTIONS, on))[0] == "# ☀️ Today\n-# Wednesday 14 October"


def test_the_day_s_total_as_a_line_of_ordinary_text_is_one_value_away(monkeypatch):
    monkeypatch.setattr(design, "DAY_TOTAL_IN_TITLE", False)
    on = date(2026, 10, 14)
    so_far = ("●●●●●○○ 5/7", "-# 💊 5/7")
    assert rules.text(SECTIONS, on, so_far=so_far).splitlines()[:5] == ["## ☀️ Today", "-# Wednesday 14 October", "●●●●●○○ 5/7", "-# 💊 5/7", ""]
    assert design.texts(rules.layout(SECTIONS, on, so_far=so_far))[0] == "# ☀️ Today\n-# Wednesday 14 October\n●●●●●○○ 5/7\n-# 💊 5/7"


def test_pills_says_what_is_dealt_with_out_of_all_as_its_checklist_counts_it(world):
    add(world, PILL_A, {"name": "Any"}, {"name": "Other"})
    said = run(pills_summary.summary(world.owner.id, world.day))
    assert (said.done, said.total) == (0, 5)
    log(world, {"pill": "any", "did": "taken"})
    log(world, {"pill": "other", "did": "skipped"})
    said = run(pills_summary.summary(world.owner.id, world.day))
    assert (said.done, said.total) == (2, 5), "taken and skipped are dealt with, as on the checklist's own bar"


def test_switched_on_the_briefing_in_the_hub_has_the_dots_and_they_move_in_place_as_doses_are_ticked_off(on, monkeypatch):
    add(on, {"name": "Any"}, {"name": "Other"})
    assert "○" not in run(briefing.card_for(on.owner.id)).text, "off unless switched on: the briefing reads as it did"
    monkeypatch.setattr(config, "DAY_PROGRESS", True)
    briefing.task.setup(None)
    message_id = run(briefing.post_in_hub(on.owner.id, HUB))
    assert on.sent[-1].card.text.splitlines()[:3] == ["## ☀️ Today ○○ 0/2", f"-# {rules.date_line(on.day)}", "-# 💊 0/2"]
    log(on, {"pill": "any", "did": "taken"})
    shown = run(briefing.card_for(on.owner.id))
    assert shown.text.splitlines()[0] == "## ☀️ Today ●○ 1/2" and shown.text.splitlines()[2] == "-# 💊 1/2"
    assert design.texts(shown.layout)[0].startswith("# ☀️ Today ●○ 1/2\n")
    edits = [card.text for edited, card in on.edited if edited == message_id]
    assert edits and "☀️ Today ●○ 1/2" in edits[-1], "the one in the hub is edited in place: nothing new is posted"


# --- questions about the day (DAY_QUESTIONS) ---------------------------------------------------------------------
def test_what_is_left_is_the_day_s_dots_and_each_thing_still_to_do_in_its_task_s_words():
    pills = summaries.Section("pills", "💊", "Pills", Summary("1 of 3 taken", design.DUE, done=1, total=3, left=("Pill A (dose 2 of 3) `12:00 pm`", "Zinc")))
    gym = summaries.Section("gym", "🏋️", "Gym", Summary("to do", design.DUE, done=0, total=1, left=("Push day",)))
    weather = summaries.Section("weather", "🌤️", "Weather", Summary("14° to 20°", design.QUIET))
    assert rules.left([pills, weather, gym]).splitlines() == ["☀️ **Left today** · ●○○○ 1/4", "💊 Pill A (dose 2 of 3) `12:00 pm`", "💊 Zinc", "🏋️ Push day"]
    done = summaries.Section("pills", "💊", "Pills", Summary("3 of 3 taken", design.DONE, done=3, total=3))
    assert rules.left([done, weather]) == "☀️ **Nothing left today** · ●●● 3/3"
    assert rules.left([weather]) == rules.NOTHING and rules.left([]) == rules.NOTHING, "nothing to count: nothing is on"
    many = summaries.Section("pills", "💊", "Pills", Summary("", design.DUE, done=0, total=12, left=tuple(f"Pill {n}" for n in range(12))))
    assert rules.left([many]).splitlines()[-1] == "…and 4 more" and len(rules.left([many]).splitlines()) == 1 + rules.MAX_LEFT + 1


def test_yesterday_is_the_record_s_count_and_each_task_s_own_line_about_the_day_before():
    tallies = [summaries.Tally("pills", "💊", 2, 3)]
    pills = summaries.Section("pills", "💊", "Pills", Summary("0 of 3 taken", design.DUE, before="Yesterday: 2 of 3 taken · 1 missed"))
    assert rules.yesterday(date(2026, 10, 13), tallies, [pills]).splitlines() == ["☀️ **Yesterday** · Tue 13 Oct · ●●○ 2/3", "💊 Yesterday: 2 of 3 taken · 1 missed"]
    assert rules.yesterday(date(2026, 10, 13), tallies, []).splitlines() == ["☀️ **Yesterday** · Tue 13 Oct · ●●○ 2/3", "💊 2/3"], "no line of its own: its count"
    assert rules.yesterday(date(2026, 10, 13), [], []) == "☀️ Nothing was on yesterday."


def test_the_week_is_monday_to_today_a_line_a_day_from_each_task_s_record():
    monday, today = date(2026, 10, 12), date(2026, 10, 14)
    found = [
        (monday, [summaries.Tally("pills", "💊", 3, 3)]),
        (date(2026, 10, 13), [summaries.Tally("pills", "💊", 2, 3), summaries.Tally("gym", "🏋️", 1, 1)]),
        (today, [summaries.Tally("pills", "💊", 1, 3)]),
    ]
    assert rules.week(found, today).splitlines() == [
        "☀️ **This week** · Mon 12 – Wed 14 Oct · ●●●●●●●○○○ 7/10", "-# 💊 6/9 · 🏋️ 1/1", "`Mon 12` ●●● 3/3", "`Tue 13` ●●●○ 3/4", "`Wed 14` ●○○ 1/3 · today",
    ]
    assert rules.week([(monday, []), (today, [summaries.Tally("pills", "💊", 0, 2)])], today).splitlines()[2:] == ["`Wed 14` ○○ 0/2 · today"], "a day with nothing in it has no line"
    assert rules.week([(monday, [])], monday) == "☀️ Nothing was on this week."
    assert "%" not in rules.week(found, today)


def test_a_day_s_tally_is_read_from_the_record_and_a_task_that_fails_is_left_out_never_made_up(monkeypatch):
    async def pills(user_id, on):
        return (2, 3)

    async def nothing(user_id, on):
        return None

    async def broken(user_id, on):
        raise RuntimeError("boom")

    monkeypatch.setattr(actions, "_entries", {})
    entries = [Entry("pills", "💊", "x", ("a", "b"), (), tally=pills, on_repeat="allow_another"), Entry("gym", "🏋️", "x", ("a", "b"), (), tally=nothing, on_repeat="allow_another"),
               Entry("todo", "📝", "x", ("a", "b"), (), tally=broken, on_repeat="allow_another"), _entry("timers")]
    actions.set_catalogue(entries)
    assert asyncio.run(summaries.tallies(1, date(2026, 10, 13))) == [summaries.Tally("pills", "💊", 2, 3)]


def test_switched_off_the_briefing_has_only_brief_me_and_on_it_answers_the_day_s_questions(on, monkeypatch):
    (entry,) = briefing.task.entries()
    assert [action.name for action in entry.actions] == ["briefing_show"] and entry.only_for == briefing.ONLY_FOR
    monkeypatch.setattr(config, "DAY_QUESTIONS", True)
    (entry,) = briefing.task.entries()
    assert [action.name for action in entry.actions] == ["briefing_show", "day_left", "day_past"] and actions.problems([entry]) == []
    assert entry.only_for == briefing.ONLY_FOR_THE_DAY and "what's left today?" in entry.examples and not any(action.needs_card for action in entry.actions[1:])
    monkeypatch.setattr(config, "BRIEFING_ENABLED", False)
    assert briefing.task.entries() == []


def test_what_s_left_and_how_yesterday_and_the_week_went_are_answered_from_pills_own_data(on, monkeypatch):
    monkeypatch.setattr(config, "DAY_QUESTIONS", True)
    add(on, PILL_A, {"name": "Any"})
    request = Request(on.owner, INBOX, "asked")
    assert run(briefing.left_today(request, {}, frozenset())).splitlines() == [
        "☀️ **Left today** · ○○○○ 0/4", "💊 Any", "💊 Pill A (dose 1 of 3) `8:00 am`", "💊 Pill A (dose 2 of 3) `11:30 am`", "💊 Pill A (dose 3 of 3) `3:00 pm`",
    ]
    log(on, {"pill": "any", "did": "taken"})
    assert run(briefing.left_today(request, {}, frozenset())).splitlines()[0] == "☀️ **Left today** · ●○○○ 1/4"
    assert run(briefing.looking_back(request, {"period": "yesterday"}, frozenset())) == "☀️ Nothing was on yesterday."
    first = on.day
    tomorrow = first + timedelta(days=1)
    clock.advance_to(day.at(tomorrow, time(6, 0, 30)))
    run(scheduler.run_all_due())
    said = run(briefing.looking_back(request, {"period": "yesterday"}, frozenset())).splitlines()
    assert said == [f"☀️ **Yesterday** · {rules.short_date(first)} · ●○○○ 1/4", "💊 Yesterday: 1 of 4 taken · 3 missed"], "from the record of that day"
    week = run(briefing.looking_back(request, {"period": "week"}, frozenset())).splitlines()
    assert week[0].startswith("☀️ **This week** · ") and week[1].startswith("-# 💊 ") and week[-1] == f"`{tomorrow:%a} {tomorrow.day}` ○○○○ 0/4 · today"
    if tomorrow.weekday() != 0:
        assert f"`{first:%a} {first.day}` ●○○○ 1/4" in week and week[0].endswith("●○○○○○○○ 1/8") and week[1] == "-# 💊 1/8"


def test_pills_tally_is_the_day_as_it_was_recorded_whatever_became_of_the_pill_since(world):
    from tasks.pills import history, plain

    add(world, {"name": "Any"}, {"name": "Other"})
    log(world, {"pill": "any", "did": "taken"})
    assert run(history.tally(world.owner.id, world.day)) == (1, 2)
    run(plain.remove_save(world.request(), run(plain.remove_card(world.request(), {"pills": [{"pill": "other"}]}, frozenset())).data))
    assert run(history.tally(world.owner.id, world.day - timedelta(days=30))) is None
    assert run(pills_summary.summary(world.owner.id, world.day)).left == ()
