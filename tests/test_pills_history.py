"""Pills, looking back (tasks/pills/history.py): a day that is over, the week, the streak in the
briefing's pills section, and the weekly summary behind WEEKLY_SUMMARY."""
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import config, day, messages, scheduler
from core.actions import Request
from tasks.pills import checklist, history, plain, store
from tasks.pills import summary as pills_summary
from tests.test_pills_checklist import DAY, HUB, add, log, run, world  # noqa: F401

TUESDAY, WEDNESDAY, THURSDAY = (DAY + timedelta(days=offset) for offset in (1, 2, 3))
THREE = ({"name": "Zinc"}, {"name": "Iron"}, {"name": "Evening pill", "times": ["8:00 pm"]})


def lived(world, on, *taken, at=time(9, 0)):
    """A day goes by: it begins (the one before is closed), and these are ticked off."""
    world.now = day.at(on, at)
    if on > DAY:
        run(checklist.new_day(on - timedelta(days=1), on))
    else:
        run(checklist.view(world.owner.id))
    for name in taken:
        log(world, {"pill": name, "did": "taken"})


def test_yesterday_is_shown_as_it_was_recorded_a_line_a_dose(world):
    lived(world, TUESDAY)
    assert run(history.yesterday(world.owner.id)) == "💊 Nothing was to take yesterday (Mon 12 Oct)."
    add(world, *THREE)
    lived(world, WEDNESDAY - timedelta(days=1), "zinc")
    log(world, {"pill": "iron", "did": "skipped"})
    lived(world, WEDNESDAY)
    assert run(history.yesterday(world.owner.id)).splitlines() == [
        "💊 **Yesterday** · Tue 13 Oct · 1 of 3 taken · 1 missed · 1 skipped",
        "✅ **Zinc** · taken 9:00 am", "❌ **Evening pill** · missed", "⏭️ **Iron** · skipped",
    ]
    # What has become of a pill since changes nothing about the day that is over
    proposal = run(plain.remove_card(world.request(), {"pills": [{"pill": "zinc"}]}, frozenset()))
    run(plain.remove_save(world.request(), proposal.data))
    assert "✅ **Zinc** · taken 9:00 am" in run(history.yesterday(world.owner.id)), "a pill removed today was still taken yesterday"
    request = Request(world.owner, HUB, "what did I take yesterday?")
    shown = run(history.show(request, {"period": "yesterday"}, frozenset()))
    assert (shown.key, shown.text.splitlines()[0]) == ("pills.yesterday", "💊 **Yesterday** · Tue 13 Oct · 1 of 3 taken · 1 missed · 1 skipped") and shown.card.text == shown.text


def test_the_week_is_a_line_a_day_up_to_today_with_the_count_and_the_streak(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    lived(world, DAY, "zinc", "iron")
    lived(world, TUESDAY, "zinc", "iron")
    lived(world, WEDNESDAY, "zinc")  # Iron is missed when the day ends
    lived(world, THURSDAY, "zinc")
    said = run(history.week(world.owner.id)).splitlines()
    assert said[0] == "💊 **This week** · Mon 12 – Sun 18 Oct · 6 of 8 taken · 1 missed"
    assert said[1:5] == ["`Mon 12` ✅✅ 2 of 2", "`Tue 13` ✅✅ 2 of 2", "`Wed 14` ✅❌ 1 of 2", "`Thu 15` ✅▫️ 1 of 2 so far"]
    assert len(said) == 5, "days still to come are left out, and a streak of one day is not said"
    assert history.week_of(THURSDAY) == (DAY, DAY + timedelta(days=6)) and history.week_of(DAY + timedelta(days=6))[0] == DAY
    request = Request(world.owner, HUB, "show my week")
    assert run(history.show(request, {"period": "week"}, frozenset())).text.startswith("💊 **This week**")


def test_the_streak_is_days_in_a_row_one_for_all_pills_and_only_a_missed_dose_breaks_it(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    lived(world, DAY, "zinc", "iron")
    assert run(history.streak_days(world.owner.id, DAY)) == 1 and history.streak_line(1) == "", "one day is not yet a streak worth saying"
    lived(world, TUESDAY, "zinc")
    log(world, {"pill": "iron", "did": "skipped"})  # a skip never breaks it
    lived(world, WEDNESDAY, "zinc", "iron")
    assert run(history.streak_days(world.owner.id, WEDNESDAY)) == 3 and history.streak_line(3) == "🔥 Streak · 3 days"
    assert run(history.week(world.owner.id)).splitlines()[-1] == "🔥 Streak · 3 days"
    lived(world, THURSDAY)  # nothing taken on Thursday yet: the streak stands until the day is lost
    assert run(history.streak_days(world.owner.id, THURSDAY)) == 3
    lived(world, THURSDAY + timedelta(days=1), "zinc")  # Thursday ended with both missed
    assert run(history.streak_days(world.owner.id, THURSDAY + timedelta(days=1))) == 1


def test_the_briefing_s_pills_section_says_the_streak_from_two_days_up_and_only_reads(world):
    add(world, {"name": "Zinc"}, {"name": "Evening pill", "times": ["8:00 pm"]})
    lived(world, DAY, "zinc", "evening pill", at=time(21, 0))
    lived(world, TUESDAY, "zinc", "evening pill", at=time(21, 0))
    lived(world, WEDNESDAY)
    before = run(_counts())
    said = run(pills_summary.summary(world.owner.id, WEDNESDAY))
    assert said.lines == ("**Next:** Evening pill · `8:00 pm`", "🔥 Streak · 2 days") and len(said.lines) <= 3
    assert run(_counts()) == before, "nothing is written to say it"
    lived(world, THURSDAY)  # Wednesday was missed
    assert "Streak" not in " ".join(run(pills_summary.summary(world.owner.id, THURSDAY)).lines)


async def _counts():
    from core import database

    def read(conn):
        return conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0], conn.execute("SELECT COUNT(*) FROM occurrence_events").fetchone()[0]

    return await database.run(read)


# --- the weekly summary --------------------------------------------------------------------------------------------
def _job(notify="silent"):
    return scheduler.Job(id=9, user_id=None, task="pills", kind=history.WEEK_JOB, payload={}, due_at=day.at(DAY + timedelta(days=6), time(19, 0)), notify=notify)


@pytest.fixture
def sunday(world, monkeypatch):
    world.notes, world.reported, world.recorded = [], [], []
    monkeypatch.setattr(scheduler, "note", lambda job, text: world.notes.append(text))
    monkeypatch.setattr(scheduler, "report", lambda job, ended: world.reported.append(ended))

    async def record(message_id, channel_id, **kwargs):
        world.recorded.append((message_id, channel_id, kwargs.get("lifetime"), kwargs.get("slot")))

    monkeypatch.setattr(messages, "record", record)
    monkeypatch.setattr(config, "WEEKLY_SUMMARY", True)
    return world


def test_it_is_off_unless_switched_on_and_its_schedule_is_sunday_evening(world, monkeypatch):
    assert config.WEEKLY_SUMMARY is False and not history.enabled()
    monkeypatch.setattr(scheduler, "_standing", {})
    history.register()
    assert scheduler._standing == {}, "off: no schedule is made"
    monkeypatch.setattr(config, "WEEKLY_SUMMARY", True)
    history.register()
    default = scheduler._standing[("pills", "weekly")]
    assert (default.name, default.at, default.days, default.channel, default.notify, default.locked) == ("Weekly pills summary", time(19, 0), (6,), "hub", "silent", False)
    monkeypatch.setattr(config, "WEEKLY_SUMMARY", False)
    notes = []
    monkeypatch.setattr(scheduler, "note", lambda job, text: notes.append(text))
    before = len(world.sent)
    run(history.week_job(_job()))
    assert notes == ["off (WEEKLY_SUMMARY)"] and len(world.sent) == before, "a run booked before it was switched off posts nothing"


def test_on_sunday_evening_the_week_is_posted_in_the_hub_one_at_a_time(sunday):
    add(sunday, {"name": "Zinc"})
    for offset in range(6):
        lived(sunday, DAY + timedelta(days=offset), "zinc")
    lived(sunday, DAY + timedelta(days=6), "zinc", at=time(19, 0))
    before = len(sunday.sent)
    run(history.week_job(_job()))
    (posted,) = sunday.sent[before:]
    lines = posted.card.text.splitlines()
    assert posted.channel == HUB and posted.silent is True
    assert lines[0] == "💊 **Your week** · Mon 12 – Sun 18 Oct · 7 of 7 taken" and lines[-1] == "🔥 Streak · 7 days" and len(lines) == 9
    assert sunday.recorded == [(posted.id, HUB, messages.REPLACED, "pills.week")] and sunday.notes == ["posted for 1"] and sunday.reported == []
    run(history.week_job(_job("notify")))
    assert sunday.sent[-1].silent is False, "notifying is the schedule's to say"


def test_a_week_with_nothing_to_take_posts_nothing_and_no_hub_is_a_real_problem(sunday, monkeypatch):
    lived(sunday, DAY + timedelta(days=6), at=time(19, 0))
    before = len(sunday.sent)
    run(history.week_job(_job()))
    assert len(sunday.sent) == before and sunday.notes == ["nothing was to take this week"] and sunday.reported == []
    monkeypatch.setattr(history.hub, "channel_id", lambda: None)
    run(history.week_job(_job()))
    assert sunday.reported == [scheduler.SKIPPED] and sunday.notes[-1] == "not posted: the hub channel is not set"


def test_the_pills_task_gives_the_handler_and_its_name_in_words():
    from tasks.pills import task

    assert task.job_handlers()[history.WEEK_JOB] is history.week_job and task.job_labels()[history.WEEK_JOB] == "weekly pills summary"


# --- the same, drawn (stage 5: every remaining card in the new look) -----------------------------------------------
from core import cards, design  # noqa: E402


def _boxes(pieces):
    return [(piece.status, piece.children[0].content) for piece in pieces if isinstance(piece, design.Box)]


def test_a_day_is_drawn_as_a_box_a_dose_in_the_colour_of_what_became_of_it(world):
    add(world, *THREE)
    lived(world, TUESDAY, "zinc")
    log(world, {"pill": "iron", "did": "skipped"})
    lived(world, WEDNESDAY)
    shown = run(history.yesterday_card(world.owner.id))
    cards.check(shown)
    assert design.problem(shown.layout) == "" and shown.layout[0].content == "# 💊 Yesterday · 1 of 3 taken · 1 missed · 1 skipped\n-# Tue 13 Oct"
    assert _boxes(shown.layout) == [
        (design.DONE, "✅ **Zinc** · taken 9:00 am"), (design.MISSED, "❌ **Evening pill** · missed"), (design.QUIET, "⏭️ **Iron** · skipped"),
    ]
    assert shown.text.splitlines()[1:] == [text for _, text in _boxes(shown.layout)], "the same words, drawn or not"


def test_the_week_is_drawn_as_a_box_a_day_with_the_streak_under_it(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    lived(world, DAY, "zinc", "iron")
    lived(world, TUESDAY, "zinc", "iron")
    lived(world, WEDNESDAY, "zinc")
    lived(world, THURSDAY, "zinc")
    shown = run(history.week_card(world.owner.id))
    cards.check(shown)
    assert shown.layout[0].content == "# 💊 This week · 6 of 8 taken · 1 missed\n-# Mon 12 – Sun 18 Oct"
    assert _boxes(shown.layout) == [
        (design.DONE, "**Mon 12** · ✅✅ 2 of 2"), (design.DONE, "**Tue 13** · ✅✅ 2 of 2"),
        (design.MISSED, "**Wed 14** · ✅❌ 1 of 2"), (design.ANY_TIME, "**Thu 15** · ✅▫️ 1 of 2 so far"),
    ]
    lived(world, THURSDAY, "iron")
    lived(world, THURSDAY + timedelta(days=1), "zinc", "iron")
    again = run(history.week_card(world.owner.id))
    assert again.layout[-1].content == "-# 🔥 Streak · 2 days", "the streak is the small line under the days"
    empty = history.week_layout([], DAY)
    assert _boxes(empty) == [(design.QUIET, "Nothing was to take this week.")] and design.problem(empty) == ""


def test_a_long_day_still_fits_one_message(world):
    add(world, *({"name": f"Pill {n:02d}"} for n in range(20)))
    lived(world, DAY)
    lived(world, TUESDAY)
    shown = run(history.yesterday_card(world.owner.id))
    cards.check(shown)
    assert len(_boxes(shown.layout)) == 1 and _boxes(shown.layout)[0][0] == design.MISSED, "past twelve doses they share a box, in the colour of the worst of them"
