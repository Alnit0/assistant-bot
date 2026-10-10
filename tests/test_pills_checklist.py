"""Pills: the daily checklist and logging a dose (tasks/pills/checklist.py, plain.log_doses).
Against a temporary database, with the messages kept in a list instead of Discord."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, database, day, hub, live, llm, occurrences, scheduler
from core.actions import Request, Shown
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from tasks.pills import checklist, plain, store, today
from tasks.pills import task as pills_task

HUB, INBOX = 400, 100
DAY = date(2026, 10, 12)


@pytest.fixture
def world(make_db, monkeypatch, owner):
    make_db({"pills": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=7000, now=day.at(DAY, time(9, 0)), gone=set())

    async def send(channel_id, card, silent=False):
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        if message_id in seen.gone:
            return False
        seen.edited.append((message_id, card))
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(clock, "now", lambda: seen.now)
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(llm, "_exchanges", {})
    live.reset()
    seen.request = lambda channel=INBOX: Request(owner, channel, "said")
    return seen


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


def add(world, *items):
    proposal = run(plain.add_card(world.request(), {"pills": list(items)}, frozenset()))
    run(plain.add_save(world.request(), proposal.data))


def log(world, *doses):
    return run(plain.log_doses(world.request(), {"doses": list(doses)}, frozenset()))


def sheet(world):
    """Today's checklist as it stands: the latest text of the message that is recorded as it."""
    record = next(m for m in run(database.run(store.db_messages, world.owner.id, DAY)) if m.kind == store.CHECKLIST)
    edits = [card.text for message_id, card in world.edited if message_id == record.message_id]
    return (edits or [next(m.card.text for m in world.sent if m.id == record.message_id)])[-1]


def dose_messages(world):
    return [m for m in run(database.run(store.db_messages, world.owner.id, DAY)) if m.kind == store.DOSE]


def press(world, message, action):
    removed = []

    async def remove():
        removed.append(message.message_id)

    pressed = SimpleNamespace(user=world.owner, arg=str(message.occurrence_id), channel_id=HUB, message_id=message.message_id, remove=remove)
    return run(action(pressed)), removed


THREE = ({"name": "Vitamin D"}, {"name": "Magnesium", "notes": "with food"}, {"name": "Evening pill", "times": ["8:00 pm"]})


# --- posting it --------------------------------------------------------------------------------------
def test_the_checklist_is_posted_silently_in_the_hub_with_a_message_for_each_dose_with_no_time(world):
    add(world, *THREE)
    assert world.sent == [], "nothing is posted by setting pills up"
    run(checklist.post(world.owner.id))
    first, *rest = world.sent
    assert (first.channel, first.silent) == (HUB, True) and first.card.rows == ()
    assert first.card.text.splitlines() == [
        "## 💊 Pills · ▱▱▱▱▱ 0 of 3", "", "💊 **Magnesium** · *with food*", "💊 **Vitamin D**", "💊 **Evening pill** · `8:00 pm`",
    ]
    assert [(m.card.text, m.silent, [button.label for button in m.card.rows[0]]) for m in rest] == [
        ("💊 **Magnesium** · *with food*", True, ["Taken", "Skip"]),
        ("💊 **Vitamin D**", True, ["Taken", "Skip"]),
    ], "no message for the timed dose, and no Snooze: there is no time pressure"


def test_asking_again_posts_a_fresh_copy_and_the_old_one_and_its_messages_go(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    old = [m.id for m in world.sent]
    run(checklist.post(world.owner.id, INBOX))
    assert world.deleted == old and len(world.sent) == 6 and all(m.channel == HUB for m in world.sent)
    records = run(database.run(store.db_messages, world.owner.id, DAY))
    assert [m.message_id for m in records] == [m.id for m in world.sent[3:]], "only ever one checklist for today"


def test_with_no_hub_set_it_is_posted_where_it_was_asked_for(world, monkeypatch):
    monkeypatch.setattr(hub, "channel_id", lambda: None)
    add(world, {"name": "Zinc"})
    assert run(checklist.post(world.owner.id)) is None and world.sent == [], "nowhere to post it by itself"
    run(checklist.post(world.owner.id, INBOX))
    assert world.sent[0].channel == INBOX


def test_the_word_and_the_question_post_today_and_say_where_it_is(world):
    add(world, {"name": "Zinc"})
    confirmed = []

    async def confirm(text):
        confirmed.append(text)

    ctx = SimpleNamespace(user=world.owner, channel_id=INBOX, confirm=confirm)
    (keyword,) = pills_task.keywords()
    assert run(keyword.handler(ctx)) == "posted today's checklist"
    assert world.sent[0].channel == HUB and confirmed == ["💊 Today's checklist is in <#400>."]
    shown = run(plain.show_today(world.request(HUB), {}, frozenset()))
    assert shown == Shown("posted today's checklist", ""), "asked in the hub: nothing more to say"
    assert run(plain.show_today(world.request(INBOX), {}, frozenset())).also == "💊 Today's checklist is in <#400>."


# --- the buttons under it ------------------------------------------------------------------------------
def test_taken_on_a_dose_message_removes_it_and_ticks_the_checklist(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    magnesium = dose_messages(world)[0]
    said, removed = press(world, magnesium, checklist.on_taken)
    assert said == "✅ **Magnesium** · taken 9:00 am" and removed == [magnesium.message_id]
    assert "✅ **Magnesium** · taken 9:00 am" in sheet(world) and "▰▰▱▱▱ 1 of 3" in sheet(world)
    assert [m.occurrence_id for m in dose_messages(world)] != [magnesium.occurrence_id] and len(dose_messages(world)) == 1
    taken = run(occurrences.get(magnesium.occurrence_id))
    assert (taken.state, taken.actual_at) == (DONE, world.now)
    assert run(occurrences.history(taken.id))[-1].source == occurrences.BUTTON
    assert llm.exchanges_for(HUB) == [("(pressed Taken on Magnesium)", "✅ **Magnesium** · taken 9:00 am")]


def test_skip_counts_towards_progress(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    said, _ = press(world, dose_messages(world)[1], checklist.on_skip)
    assert said == "⏭️ **Vitamin D** · skipped"
    assert "⏭️ **Vitamin D** · skipped" in sheet(world) and "1 of 3" in sheet(world)


def test_a_button_on_a_dose_already_dealt_with_only_removes_its_message(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    magnesium = dose_messages(world)[0]
    log(world, {"pill": "magnesium", "did": "taken"})
    said, removed = press(world, magnesium, checklist.on_taken)
    assert said == "already dealt with" and removed == [magnesium.message_id]
    assert len(run(occurrences.history(magnesium.occurrence_id))) == 2, "made, then taken once: not marked twice"


# --- saying it -----------------------------------------------------------------------------------------
def test_saying_i_took_it_ticks_it_off_removes_its_message_and_says_what_is_left(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    vitamin_d = dose_messages(world)[1]
    assert log(world, {"pill": "vitamin d", "did": "taken"}) == (
        "✅ **Vitamin D** · taken 9:00 am · still to take today: Magnesium, Evening pill `8:00 pm`"
    )
    assert "✅ **Vitamin D** · taken 9:00 am" in sheet(world)
    assert vitamin_d.message_id in world.deleted and len(dose_messages(world)) == 1
    assert run(occurrences.history(vitamin_d.occurrence_id))[-1].source == occurrences.MESSAGE


def test_it_works_before_the_checklist_is_posted_and_the_checklist_then_shows_it(world):
    add(world, {"name": "Zinc"})
    assert log(world, {"pill": "Zinc", "did": "taken"}) == "✅ **Zinc** · taken 9:00 am · nothing left to take today"
    assert world.sent == [] and world.edited == []
    run(checklist.post(world.owner.id))
    assert world.sent[0].card.text.splitlines()[-1] == "✅ **Zinc** · taken 9:00 am" and len(world.sent) == 1


def test_a_time_given_is_used_and_checked(world):
    add(world, {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180})
    assert log(world, {"pill": "pill a", "did": "taken", "at": "8:10 am"}).startswith("✅ **Pill A** (dose 1 of 3) · taken 8:10 am")
    # Not taken after all: it is 9:00 am, so dose 1 can't be before now and dose 2 follows it by the gap
    assert log(world, {"pill": "pill a", "did": "not_taken"}) == (
        "↩️ **Pill A** (dose 1 of 3) · no longer ticked off · still to take today: "
        "Pill A (dose 1 of 3) `8:00 am`, Pill A (dose 2 of 3) `12:00 pm`, Pill A (dose 3 of 3) `3:00 pm`"
    )
    assert log(world, {"pill": "pill a", "did": "taken", "at": "8:00"}).startswith("✅ **Pill A** (dose 1 of 3) · taken 8:00 am"), "8 can only be this morning: it is 9 am"
    assert log(world, {"pill": "pill a", "did": "taken", "at": "10:00 am"}) == "⚠️ Pill A (dose 2 of 3): 10:00 am hasn't happened yet: it's 9:00 am now."
    assert log(world, {"pill": "pill a", "did": "taken", "at": "7:00 am"}) == "⚠️ Pill A (dose 2 of 3): 7:00 am is before the previous one, at 8:00 am."


def test_a_time_that_could_be_either_is_the_latest_one_that_has_happened(world):
    world.now = day.at(DAY, time(21, 0))
    add(world, {"name": "Zinc"})
    assert log(world, {"pill": "zinc", "did": "taken", "at": "8:00"}).startswith("✅ **Zinc** · taken 8:00 pm")


def test_today_s_times_follow_what_was_taken(world):
    add(world, {"name": "Course A", "per_day": 3, "min_gap_minutes": 180})
    run(checklist.post(world.owner.id))
    assert len(dose_messages(world)) == 1, "only the first dose has no time"
    world.now = day.at(DAY, time(8, 12))
    assert log(world, {"pill": "course a", "did": "taken"}) == (
        "✅ **Course A** (dose 1 of 3) · taken 8:12 am · still to take today: Course A (dose 2 of 3) `11:12 am`, Course A (dose 3 of 3) `2:12 pm`"
    )
    assert "💊 **Course A** (dose 2 of 3) · `11:12 am`" in sheet(world) and dose_messages(world) == []


def test_several_at_once_skipping_and_what_cannot_be_done_are_each_said(world):
    add(world, *THREE, {"name": "Iron"})
    run(plain.pause_save(world.request(), {"pills": [{"pill": "iron"}]}))
    said = log(
        world,
        {"pill": "vitamin d", "did": "taken"}, {"pill": "magnesium", "did": "skipped"}, {"pill": "iron", "did": "taken"},
        {"pill": "copper", "did": "taken"}, {"pill": "@that", "did": "taken"},
    )
    assert said.splitlines() == [
        "✅ **Vitamin D** · taken 9:00 am",
        "⏭️ **Magnesium** · skipped",
        "⏸️ **Iron** is paused: there is nothing to tick off today.",
        "⚠️ I don't have a pill called “copper”. Yours: Evening pill, Iron, Magnesium, Vitamin D.",
        "⚠️ Which pill? Say its name. · still to take today: Evening pill `8:00 pm`",
    ]


def test_what_is_already_so_names_the_dose_and_shows_it(world):
    add(world, {"name": "Zinc"})
    log(world, {"pill": "zinc", "did": "taken"})
    assert log(world, {"pill": "zinc", "did": "taken"}) == "✅ **Zinc** · taken 9:00 am already"
    assert log(world, {"pill": "zinc", "did": "skipped"}) == "💊 **Zinc** has nothing left to take today."
    assert log(world, {"pill": "zinc", "did": "not_taken"}) == "↩️ **Zinc** · no longer ticked off · still to take today: Zinc"
    assert log(world, {"pill": "zinc", "did": "not_taken"}) == "💊 **Zinc** isn't ticked off today: there is nothing to change."
    states = [event.kind for event in run(occurrences.history(run(occurrences.for_day(world.owner.id, "pills", DAY))[0].id))]
    assert states == ["created", "done", "reopened"], "every change leaves an event, and nothing else does"


def test_a_change_that_did_not_save_is_never_said_to_have_happened(world, monkeypatch):
    add(world, {"name": "Zinc"})
    monkeypatch.setattr(checklist, "db_mark", lambda conn, occurrence_id, did, at, source: occurrences.db_get(conn, occurrence_id))
    with pytest.raises(Exception, match="That didn't save: Zinc is still pending"):
        log(world, {"pill": "zinc", "did": "taken"})


def test_the_names_of_my_pills_are_what_a_message_may_name(world):
    add(world, *THREE)
    run(plain.remove_save(world.request(), {"pills": [{"pill": "magnesium"}]}))
    assert run(plain.names(world.request())) == ["Evening pill", "Vitamin D"]


# --- changes during the day ---------------------------------------------------------------------------------
def test_a_pill_added_paused_or_removed_today_changes_the_checklist_and_its_messages_straight_away(world):
    add(world, {"name": "Vitamin D"})
    run(checklist.post(world.owner.id))
    add(world, {"name": "Zinc"})
    assert "💊 **Zinc**" in sheet(world) and "0 of 2" in sheet(world)
    assert [m.card.text for m in world.sent][-1] == "💊 **Zinc**", "its own message is posted under the checklist"
    zinc = dose_messages(world)[-1]
    run(plain.pause_save(world.request(), {"pills": [{"pill": "zinc"}]}))
    assert "### ⏸️ Paused\n⏸️ **Zinc** · paused" in sheet(world) and "0 of 1" in sheet(world)
    assert zinc.message_id in world.deleted and len(dose_messages(world)) == 1
    run(plain.remove_save(world.request(), {"pills": [{"pill": "vitamin d"}]}))
    assert "Nothing to take today." in sheet(world) and dose_messages(world) == []


def test_a_course_that_starts_tomorrow_is_not_on_today(world):
    add(world, {"name": "Vitamin D"}, {"name": "Course B", "start": "tomorrow", "days": 3})
    run(checklist.post(world.owner.id))
    assert "Course B" not in sheet(world) and "0 of 1" in sheet(world)


def test_a_checklist_that_has_gone_is_posted_again(world):
    add(world, {"name": "Zinc"})
    first = run(checklist.post(world.owner.id))
    world.gone.add(first)
    run(checklist.refresh(world.owner.id))
    records = run(database.run(store.db_messages, world.owner.id, DAY))
    assert [m.kind for m in records] == [store.CHECKLIST, store.DOSE] and records[0].message_id != first


# --- 6:00 am, a late start, a restart ------------------------------------------------------------------------
def job():
    return scheduler.Job(1, None, "pills", checklist.JOB, {}, day.at(DAY, time(6, 0)))


def test_at_six_it_is_posted_and_the_next_morning_is_booked(world):
    add(world, {"name": "Zinc"})
    world.now = day.at(DAY, time(6, 0))
    run(checklist.post_job(job()))
    assert [m.card.text.splitlines()[0] for m in world.sent] == ["## 💊 Pills · ▱▱▱▱▱ 0 of 1", "💊 **Zinc**"]
    (booked,) = run(scheduler.pending_jobs("pills", checklist.JOB))
    assert booked.due_at == day.at(DAY + timedelta(days=1), time(6, 0))


def test_nothing_is_posted_on_a_day_with_nothing_to_take(world):
    world.now = day.at(DAY, time(6, 0))
    run(checklist.post_job(job()))
    add(world, {"name": "Iron"})
    run(plain.pause_save(world.request(), {"pills": [{"pill": "iron"}]}))
    run(checklist.post_job(job()))
    assert world.sent == []


def test_starting_after_six_posts_it_once_and_a_restart_or_a_late_job_never_makes_a_second(world):
    add(world, *THREE)
    run(checklist.startup())
    assert len(world.sent) == 3 and len(run(scheduler.pending_jobs("pills", checklist.JOB))) == 1
    log(world, {"pill": "magnesium", "did": "taken"})
    run(checklist.startup())  # a restart in the middle of the day
    run(checklist.post_job(job()))  # and the 6:00 am job, run late
    assert len(world.sent) == 3, "the same messages, found again: no duplicates"
    assert "✅ **Magnesium** · taken 9:00 am" in sheet(world) and len(dose_messages(world)) == 1
    assert len(run(scheduler.pending_jobs("pills", checklist.JOB))) == 1


def test_starting_before_six_posts_nothing_yet(world):
    add(world, {"name": "Zinc"})
    world.now = day.at(DAY, time(5, 30))
    run(checklist.startup())
    assert world.sent == []
    (booked,) = run(scheduler.pending_jobs("pills", checklist.JOB))
    assert booked.due_at == day.at(DAY, time(6, 0))


# --- the end of the day -----------------------------------------------------------------------------------------
def test_at_midnight_what_was_untouched_is_missed_and_the_single_messages_go(world):
    add(world, *THREE)
    run(checklist.post(world.owner.id))
    log(world, {"pill": "vitamin d", "did": "taken"})
    left = dose_messages(world)
    record = run(database.run(store.db_messages, world.owner.id, DAY))[0]
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    states = {o.item_id: o.state for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert sorted(states.values()) == [DONE, MISSED, MISSED]
    assert [m.message_id for m in left] == world.deleted[-1:], "the message of the dose nobody touched is deleted"
    last = [card.text for message_id, card in world.edited if message_id == record.message_id][-1]
    assert "❌ **Magnesium** · missed" in last and "❌ **Evening pill** · missed" in last and "✅ **Vitamin D**" in last
    assert run(database.run(store.db_messages, world.owner.id, DAY)) == [], "yesterday's checklist stays as it is, and is no longer ours"
    assert run(occurrences.for_day(world.owner.id, "pills", DAY + timedelta(days=1))) == [], "the new day starts from the plan when it is asked for"


def test_a_dose_of_a_pill_removed_during_the_day_is_set_aside_not_missed(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    run(plain.remove_save(world.request(), {"pills": [{"pill": "iron"}]}))
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    found = {o.item_id: (o.state, o.reason) for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert found == {1: (MISSED, None), 2: (SKIPPED, "no longer in the plan")}


def test_the_task_says_which_of_its_messages_are_live_and_which_wait_to_be_pressed(world):
    from core.lifecycle import MessageClass

    add(world, {"name": "Zinc"})
    run(checklist.post(world.owner.id))
    listed, single = world.sent
    assert run(pills_task.message_class(listed.id)) == MessageClass.LIVE
    assert run(pills_task.message_class(single.id)) == MessageClass.ALERT
    assert run(pills_task.message_class(1)) is None
    assert PENDING == "pending" and today.TASK == "pills"
