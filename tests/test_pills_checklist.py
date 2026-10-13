"""Pills: the daily checklist and logging a dose (tasks/pills/checklist.py, plain.log_doses).
Against a temporary database, with the messages kept in a list instead of Discord."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, database, day, hub, live, llm, occurrences, scheduler, tidy
from core.actions import Request, Shown
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from core.errors import UserError
from tasks.pills import checklist, plain, rules, store, today
from tasks.pills import sheet as sheet_module
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
    # When the checklist is posted is its schedule's: 6:00 am, as a fresh database gets it
    monkeypatch.setattr(scheduler, "_standing", {("pills", checklist.JOB): checklist.DEFAULT})
    seen.bot_log = []

    async def log_simple(title, description=None):
        seen.bot_log.append((title, description))

    monkeypatch.setattr(checklist.discord_utils, "log_simple", log_simple)
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


def test_the_word_and_the_question_post_today_and_point_to_it_in_a_line_that_goes(world, monkeypatch):
    add(world, {"name": "Zinc"})
    pointed, shown = [], []

    async def pointer(channel_id, text):
        pointed.append((channel_id, text))

    monkeypatch.setattr(tidy, "pointer", pointer)  # the line that deletes itself after about ten seconds
    ctx = SimpleNamespace(user=world.owner, channel_id=INBOX, shown=shown.append)
    keyword = pills_task.keywords()[0]
    assert run(keyword.handler(ctx)) == "posted today's checklist"
    assert world.sent[0].channel == HUB and pointed == [(INBOX, "💊 Today's checklist is in <#400>.")]
    assert shown == ["pointed to the hub"], "so no Done line is added on top of the pointer"
    assert run(plain.show_today(world.request(HUB), {}, frozenset())) == Shown("posted today's checklist", "")
    assert len(pointed) == 1, "asked in the hub: nothing more to say"
    assert run(plain.show_today(world.request(INBOX), {}, frozenset())) == Shown("posted today's checklist", "")
    assert pointed[1:] == [(INBOX, "💊 Today's checklist is in <#400>.")], "never a lasting reply: the pointer only"


def test_what_a_reset_would_post_again_is_the_checklist_and_names_no_pill(world):
    add(world, {"name": "Zinc"})
    assert run(checklist.reposted(HUB, {1, 2, 3})) == [], "no checklist posted yet"
    run(checklist.post(world.owner.id))
    mine = {each.id for each in world.sent}
    assert run(checklist.reposted(HUB, mine)) == ["Today's pills checklist"]
    assert run(checklist.reposted(HUB, {1, 2, 3})) == [] and run(checklist.reposted(INBOX, mine)) == [], "kept, or another channel"


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
    # Not taken after all: each dose is shown at its planned time again, whatever time it is now
    assert log(world, {"pill": "pill a", "did": "not_taken"}) == (
        "↩️ **Pill A** (dose 1 of 3) · no longer ticked off · still to take today: "
        "Pill A (dose 1 of 3) `8:00 am`, Pill A (dose 2 of 3) `11:30 am`, Pill A (dose 3 of 3) `3:00 pm`"
    )
    assert log(world, {"pill": "pill a", "did": "taken", "at": "8:00"}).startswith("✅ **Pill A** (dose 1 of 3) · taken 8:00 am"), "8 can only be this morning: it is 9 am"
    assert log(world, {"pill": "pill a", "did": "taken", "at": "10:00 am"}) == "⚠️ Pill A (dose 1 of 3): 10:00 am hasn't happened yet: it's 9:00 am now."
    world.now = day.at(DAY, time(12, 0))  # no longer "just logged": a later time is the next dose
    assert log(world, {"pill": "pill a", "did": "taken", "at": "11:40 am"}).startswith("✅ **Pill A** (dose 2 of 3) · taken 11:40 am")
    world.now = day.at(DAY, time(13, 0))
    assert log(world, {"pill": "pill a", "did": "taken", "at": "1:00 pm"}).startswith("✅ **Pill A** (dose 3 of 3) · taken 1:00 pm"), "asking about a dose taken too soon comes with reminders"


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
        "💊 **Magnesium** has nothing left to take today. · still to take today: Evening pill `8:00 pm`",
    ], "\"it\" is the pill logged last, here Magnesium, which I skipped"


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
    world.now = day.at(DAY, time(6, 0, 1))
    run(scheduler.book())  # the engine's next look: the handler books nothing itself any more
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
    fresh = run(occurrences.for_day(world.owner.id, "pills", DAY + timedelta(days=1)))
    assert len(fresh) == 3 and {each.state for each in fresh} == {PENDING}, "the new day's rows are made from the plan as the old day ends (asked for 2026-10-13: what only reads finds them)"
    assert run(database.run(store.db_messages, world.owner.id, DAY + timedelta(days=1))) == [], "and nothing is posted for it: that is the 6:00 am checklist's"


def test_a_dose_of_a_pill_removed_during_the_day_is_set_aside_not_missed(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    run(plain.remove_save(world.request(), {"pills": [{"pill": "iron"}]}))
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    found = {o.item_id: (o.state, o.reason, o.cause) for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert found == {1: (MISSED, None, None), 2: (SKIPPED, "no longer in the plan", "not_in_plan")}


def test_the_task_says_which_of_its_messages_are_live_and_which_wait_to_be_pressed(world):
    from core.lifecycle import MessageClass

    add(world, {"name": "Zinc"})
    run(checklist.post(world.owner.id))
    listed, single = world.sent
    assert run(pills_task.message_class(listed.id)) == MessageClass.LIVE
    assert run(pills_task.message_class(single.id)) == MessageClass.ALERT
    assert run(pills_task.message_class(1)) is None
    assert PENDING == "pending" and today.TASK == "pills"


# --- going live, 2026-10-11: a pill with a latest time, logged late and then corrected -------------------
MAIN = {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm"}
AUTO = "*skipped automatically: not enough time before 4:00 pm*"


def pill_a(world):
    return {o.seq: (o.state, o.automatic, o.reason) for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}


def late_night(world):
    """10:57 pm, nothing taken all day; then "Taken my Pill A", asked about, and logged."""
    world.now = day.at(DAY, time(22, 57))
    add(world, MAIN)
    request, said = world.request(), {"doses": [{"pill": "Pill A", "did": "taken"}]}
    assert run(plain.log_asks(request, said)) is True
    asked = run(plain.log_card(request, said, frozenset()))
    return request, asked


def test_past_its_latest_time_with_nothing_taken_the_day_is_missed_and_no_time_is_shown(world):
    world.now = day.at(DAY, time(22, 57))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    assert pill_a(world) == {1: (MISSED, True, None), 2: (MISSED, True, None), 3: (MISSED, True, None)}
    assert sheet(world).count("❌") == 3 and "`" not in sheet(world), "no time is shown for what can't be taken any more"


def test_logging_after_the_latest_time_asks_first_on_a_card(world):
    request, asked = late_night(world)
    assert asked.lines == ("**Pill A** (dose 1 of 3) · taken 10:57 pm",) and asked.kind == "change"
    assert asked.warnings == ("Dose 1 was missed (due 8:00 am). That's after the latest time, 4:00 pm. Log it as taken now?",) and asked.confirm_label == "Log it"
    assert pill_a(world)[1][0] == MISSED, "nothing is logged by asking"
    world.now = day.at(DAY, time(22, 58))  # Log it is pressed a minute later: the card's time is what is saved
    assert run(plain.log_save(request, asked.data)) == "✅ **Pill A** (dose 1 of 3) · taken 10:57 pm · nothing left to take today"
    assert run(plain.log_check(request, asked.data)) == ""


def test_the_doses_that_can_no_longer_fit_are_skipped_by_the_bot_and_never_given_a_time_past_the_day(world):
    # It used to say "still to take today: dose 2 1:57 am, dose 3 4:57 am"
    request, asked = late_night(world)
    said = run(plain.log_save(request, asked.data))
    assert "am" not in said.split("·", 2)[2] and said.endswith("nothing left to take today")
    reason = "not enough time before 4:00 pm"
    assert pill_a(world) == {1: (DONE, False, None), 2: (SKIPPED, True, reason), 3: (SKIPPED, True, reason)}
    run(checklist.post(world.owner.id))
    assert sheet(world).splitlines() == [
        "## 💊 Pills · ▰▰▰▰▰ 3 of 3",
        "",
        "✅ **Pill A** (dose 1 of 3) · taken 10:57 pm",
        f"⏭️ **Pill A** (dose 2 of 3) · {AUTO}",
        f"⏭️ **Pill A** (dose 3 of 3) · {AUTO}",
    ]


@pytest.mark.parametrize("named", ["@that", "Pill A", "pl1"])
def test_a_time_given_straight_after_is_a_correction_of_the_dose_just_logged_old_to_new(world, named):
    # "I took it at 9am" got "Which pill?", and "I took Pill A at 9am" was read as a second dose and refused
    request, asked = late_night(world)
    run(plain.log_save(request, asked.data))
    world.now = day.at(DAY, time(22, 58))
    again = {"doses": [{"pill": named, "did": "taken", "at": "9:00 am"}]}
    assert run(plain.log_asks(request, again)) is False, "9 am is not after the latest time: nothing to ask"
    assert log(world, *again["doses"]) == "✏️ **Pill A** (dose 1 of 3) · taken 10:57 pm → 9:00 am · nothing left to take today"
    states = pill_a(world)
    assert states[1] == (DONE, False, None) and run(occurrences.for_day(world.owner.id, "pills", DAY))[0].actual_at == day.at(DAY, time(9, 0))
    assert states[2] == (MISSED, True, None), "taken at 9, dose 2 was due at noon and had its time"
    assert states[3] == (SKIPPED, True, "not enough time before 4:00 pm")
    kinds = [event.kind for event in run(occurrences.history(run(occurrences.for_day(world.owner.id, "pills", DAY))[0].id))]
    assert kinds[-1] == "corrected", "the correction is on the dose's record"
    assert log(world, *again["doses"]) == "✅ **Pill A** (dose 1 of 3) · taken 9:00 am already"


def test_a_time_earlier_than_the_dose_last_taken_corrects_it_however_long_ago_it_was_logged(world):
    world.now = day.at(DAY, time(9, 30))
    add(world, MAIN)
    log(world, {"pill": "pill a", "did": "taken"})
    world.now = day.at(DAY, time(11, 0))
    assert log(world, {"pill": "pill a", "did": "taken", "at": "8:15 am"}).startswith("✏️ **Pill A** (dose 1 of 3) · taken 9:30 am → 8:15 am")
    assert log(world, {"pill": "pill a", "did": "taken", "at": "12:00 pm"}) == "⚠️ Pill A (dose 1 of 3): 12:00 pm hasn't happened yet: it's 11:00 am now."


def test_it_with_nothing_logged_yet_is_asked_about_or_shown_as_a_guess(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    assert log(world, {"pill": "@that", "did": "taken", "at": "8:00 am"}) == "⚠️ Which pill? Say its name.", "two it could be"
    assert log(world, {"did": "taken"}) == "⚠️ Which pill? Say its name.", "no pill handed over at all is no different"


def test_with_nothing_to_go_by_the_card_asks_which_pill_with_a_button_each_never_a_message(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"}, {"name": "Evening pill", "times": ["8:00 pm"]})
    said = {"doses": [{"pill": "@that", "did": "taken"}]}
    assert run(plain.log_asks(world.request(), said, frozenset())) is True, "it goes on a card"
    card = run(plain.log_card(world.request(), said, frozenset()))
    assert card.lines == () and card.question.text == "Which pill?"
    assert [(choice.label, choice.data) for choice in card.question.choices] == [
        ("Iron", {"doses": [{"pill": "pl2", "did": "taken"}]}), ("Zinc", {"doses": [{"pill": "pl1", "did": "taken"}]}),
        ("Evening pill", {"doses": [{"pill": "pl3", "did": "taken"}]}),
    ]
    assert state_of(world, "Zinc") == PENDING, "nothing is logged by asking"
    # The answer names the pill: nothing is left to ask, so it is logged at once
    answered = card.question.choices[1].data
    assert run(plain.log_asks(world.request(), answered, frozenset())) is False
    assert run(plain.log_doses(world.request(), answered, frozenset())).startswith("✅ **Zinc** · taken 9:00 am")
    # "I didn't take it" offers only what is ticked off
    undo = run(plain.log_card(world.request(), {"doses": [{"pill": "@that", "did": "not_taken"}]}, frozenset()))
    assert undo.lines == ("**Zinc** · no longer ticked off",) or [choice.label for choice in undo.question.choices] == ["Zinc"]


def test_a_dose_logged_under_a_name_that_fits_two_pills_asks_which_one_on_the_card(world):
    add(world, {"name": "Vitamin D"}, {"name": "Vitamin C"})
    said = {"doses": [{"pill": "vitamin", "did": "taken", "at": "8:00 am"}]}
    assert run(plain.log_asks(world.request(), said, frozenset())) is True
    card = run(plain.log_card(world.request(), said, frozenset()))
    assert card.question.text == "Which one: Vitamin C or Vitamin D?"
    assert [(choice.label, choice.data["doses"][0]) for choice in card.question.choices] == [
        ("Vitamin C", {"pill": "pl2", "did": "taken", "at": "8:00 am"}), ("Vitamin D", {"pill": "pl1", "did": "taken", "at": "8:00 am"}),
    ], "the time said goes with the answer"


def test_an_unnamed_pill_with_no_anchor_is_shown_on_a_card_with_the_pill_the_code_picked(world):
    # "took the usual one" comes from Claude as "it" with nothing guessed: the code decides
    add(world, {"name": "Zinc"})
    sheet_id = run(checklist.post(world.owner.id))
    usual = {"doses": [{"pill": "@that", "did": "taken"}]}
    assert run(plain.log_asks(world.request(), usual, frozenset())) is True, "the only pill with a dose left: picked, never logged unseen"
    card = run(plain.log_card(world.request(), usual, frozenset()))
    assert card.lines == ("**Zinc** · taken 9:00 am ❓",) and card.confirm_label == "Save" and state_of(world, "Zinc") == PENDING
    run(plain.log_save(world.request(), card.data))
    assert state_of(world, "Zinc") == DONE
    # Straight after, "it" has an anchor: the pill just logged. No card
    undo = {"doses": [{"pill": "@that", "did": "not_taken"}]}
    assert run(plain.log_asks(world.request(), undo, frozenset())) is False
    # Six minutes on the anchor has gone: the pill logged last is picked, and shown first
    world.now += timedelta(minutes=6)
    assert run(plain.log_asks(world.request(), undo, frozenset())) is True
    assert run(plain.log_card(world.request(), undo, frozenset())).lines == ("**Zinc** · no longer ticked off ❓",)
    # A reply is an anchor however long ago, and a name needs none
    assert run(plain.log_asks(replying(world, sheet_id), undo, frozenset())) is False
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "zinc", "did": "not_taken"}]}, frozenset())) is False


def test_a_dose_is_skipped_by_the_bot_the_moment_it_can_no_longer_fit_and_comes_back_if_a_correction_makes_room(world):
    world.now = day.at(DAY, time(12, 30))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    # Dose 1 logged for 12:20 pm: dose 2 at 3:20 pm still fits before 4:00 pm, dose 3 at 6:20 pm does not
    said = log(world, {"pill": "pill a", "did": "taken", "at": "12:20 pm"})
    assert said == "✅ **Pill A** (dose 1 of 3) · taken 12:20 pm · still to take today: Pill A (dose 2 of 3) `3:20 pm`"
    assert pill_a(world)[3] == (SKIPPED, True, "not enough time before 4:00 pm") and f"⏭️ **Pill A** (dose 3 of 3) · {AUTO}" in sheet(world)
    # It was really at 9: dose 2 is due at noon and dose 3 fits again
    said = log(world, {"pill": "@that", "did": "taken", "at": "9:00 am"})
    assert said == (
        "✏️ **Pill A** (dose 1 of 3) · taken 12:20 pm → 9:00 am · still to take today: "
        "Pill A (dose 2 of 3) `12:00 pm`, Pill A (dose 3 of 3) `3:00 pm`"
    )
    assert pill_a(world)[3] == (PENDING, False, None), "the bot's own skip is taken back"


# --- streaks: only a missed dose breaks one, and the cause never changes which those are ------------------------
def broken(world, on=DAY):
    """The doses of a day that would break a streak: the missed ones, and nothing else."""
    return sorted((o.item_id, o.seq) for o in run(occurrences.for_day(world.owner.id, "pills", on)) if o.state == MISSED)


def causes(world, on=DAY):
    return {o.seq: o.cause for o in run(occurrences.for_day(world.owner.id, "pills", on))}


def test_a_dose_the_bot_skips_for_want_of_room_breaks_no_streak_and_is_known_by_its_cause(world):
    request, asked = late_night(world)
    assert broken(world) == [(1, 1), (1, 2), (1, 3)], "10:57 pm with nothing taken: all three missed"
    run(plain.log_save(request, asked.data))
    assert broken(world) == [] and causes(world) == {1: None, 2: "no_room", 3: "no_room"}
    # Midnight closes the day: skipped stays skipped, so the streak stands
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    assert broken(world) == [] and causes(world) == {1: None, 2: "no_room", 3: "no_room"}


def test_a_dose_that_had_its_time_and_was_not_taken_breaks_the_streak_whatever_is_skipped_beside_it(world):
    world.now = day.at(DAY, time(9, 0))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    log(world, {"pill": "pill a", "did": "taken", "at": "9:00 am"})
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    # Dose 2 had its time (noon) and passed: missed. Dose 3 could then never fit: set aside
    assert broken(world) == [(1, 2)] and causes(world) == {1: None, 2: None, 3: "no_room"}


def test_skipping_by_hand_a_removed_pill_and_a_pause_break_no_streak(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"}, {"name": "Calcium"})
    run(checklist.post(world.owner.id))
    log(world, {"pill": "zinc", "did": "skipped"})
    run(plain.remove_save(world.request(), {"pills": [{"pill": "iron"}]}))
    world.now = day.at(DAY + timedelta(days=1), time(0, 0))
    run(checklist.new_day(DAY, DAY + timedelta(days=1)))
    found = {o.item_id: (o.state, o.automatic, o.cause) for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert found == {1: (SKIPPED, False, None), 2: (SKIPPED, True, "not_in_plan"), 3: (MISSED, True, None)}
    assert broken(world) == [(3, 1)], "only the one nobody touched"


def test_a_correction_that_makes_room_takes_the_skip_and_its_cause_back(world):
    world.now = day.at(DAY, time(12, 30))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    log(world, {"pill": "pill a", "did": "taken", "at": "12:20 pm"})
    assert causes(world)[3] == "no_room"
    log(world, {"pill": "@that", "did": "taken", "at": "9:00 am"})
    assert causes(world)[3] is None and broken(world) == []


def test_doses_set_aside_before_the_log_kept_a_cause_are_given_theirs_once(world):
    world.now = day.at(DAY, time(12, 30))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    log(world, {"pill": "pill a", "did": "taken", "at": "12:20 pm"})

    def as_it_was(conn):
        conn.execute("UPDATE occurrences SET cause = NULL")
        store.dose_causes(conn)

    run(database.run(as_it_was))
    assert causes(world)[3] == "no_room"
    log(world, {"pill": "@that", "did": "taken", "at": "9:00 am"})
    assert pill_a(world)[3] == (PENDING, False, None), "an old skip of the bot's is still its to take back"


def test_with_a_dose_overdue_the_one_after_it_keeps_its_time_until_it_cannot_fit(world):
    # Dose 3 was shown at 2:03 am: three hours from "now", because dose 2 was overdue
    world.now = day.at(DAY, time(9, 0))
    add(world, MAIN)
    run(checklist.post(world.owner.id))
    log(world, {"pill": "pill a", "did": "taken"})
    world.now = day.at(DAY, time(12, 40))
    run(checklist.refresh(world.owner.id))
    assert "💊 **Pill A** (dose 2 of 3) · `12:00 pm`" in sheet(world) and "💊 **Pill A** (dose 3 of 3) · `3:00 pm`" in sheet(world)
    world.now = day.at(DAY, time(13, 1))  # dose 2 not taken by 1:00 pm: dose 3 can no longer fit
    run(checklist.refresh(world.owner.id))
    assert "💊 **Pill A** (dose 2 of 3) · `12:00 pm`" in sheet(world) and f"⏭️ **Pill A** (dose 3 of 3) · {AUTO}" in sheet(world)
    world.now = day.at(DAY, time(16, 1))  # and dose 2 had its time
    run(checklist.limit_job(job()))
    assert "❌ **Pill A** (dose 2 of 3) · missed" in sheet(world) and f"⏭️ **Pill A** (dose 3 of 3) · {AUTO}" in sheet(world)


def test_with_no_latest_time_the_limit_is_midnight_and_nothing_is_ever_due_tomorrow(world):
    world.now = day.at(DAY, time(21, 30))
    add(world, {"name": "Course A", "per_day": 3, "min_gap_minutes": 180})
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "course a", "did": "taken"}]})) is False, "no latest time: nothing to ask"
    assert log(world, {"pill": "course a", "did": "taken"}) == "✅ **Course A** (dose 1 of 3) · taken 9:30 pm · nothing left to take today"
    found = {o.seq: (o.state, o.reason) for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert found[2] == (SKIPPED, "not enough time before midnight") and found[3] == (SKIPPED, "not enough time before midnight")


# --- a dose named by its number is that dose, exactly (QA 2026-10-12) -----------------------------------------
def numbered(dose, at=None, did="taken", pill="Pill A"):
    return {"pill": pill, "did": did, "dose": dose, **({"at": at} if at else {})}


def two_taken(world):
    """Dose 1 logged at 12:32 am and dose 2 at 9:00 am, as it was; it is now 9:30 am."""
    world.now = day.at(DAY, time(0, 32))
    add(world, MAIN)
    log(world, {"pill": "pill a", "did": "taken"})
    world.now = day.at(DAY, time(9, 30))
    assert log(world, {"pill": "pill a", "did": "taken", "at": "9:00 am"}).startswith("✅ **Pill A** (dose 2 of 3) · taken 9:00 am")


def test_a_time_for_dose_1_corrects_dose_1_whatever_was_logged_since(world):
    # "I took dose 1 of Pill A at 9am" gave "Pill A (dose 2 of 3) · taken 9:00 am already": the number was ignored
    two_taken(world)
    said = log(world, numbered(1, "5:30 am"))
    assert said.startswith("✏️ **Pill A** (dose 1 of 3) · taken 12:32 am → 5:30 am"), "dose 1, old → new"
    taken = {o.seq: o.actual_at for o in run(occurrences.for_day(world.owner.id, "pills", DAY))}
    assert taken[1] == day.at(DAY, time(5, 30)) and taken[2] == day.at(DAY, time(9, 0)), "and dose 2 is as it was"
    assert log(world, numbered(1, "5:30 am")) == "✅ **Pill A** (dose 1 of 3) · taken 5:30 am already"
    assert log(world, numbered(1)) == "✅ **Pill A** (dose 1 of 3) · taken 5:30 am already", "no time: nothing to put right"


@pytest.mark.parametrize(
    "at, asked",
    [
        ("9:00 am", "That's the same time as dose 2, taken 9:00 am. Log it anyway?"),
        ("9:15 am", "That's after dose 2, taken 9:00 am. Log it anyway?"),
        ("8:00 am", "That's less than 3h before dose 2, taken 9:00 am. Log it anyway?"),
    ],
)
def test_a_time_that_breaks_the_order_or_the_gap_is_asked_about_on_a_card(world, at, asked):
    two_taken(world)
    request, said = world.request(), {"doses": [numbered(1, at)]}
    assert run(plain.log_asks(request, said)) is True
    card = run(plain.log_card(request, said, frozenset()))
    assert card.lines == (f"**Pill A** (dose 1 of 3) · taken 12:32 am → {at}",) and card.warnings == (asked,)
    assert run(occurrences.for_day(world.owner.id, "pills", DAY))[0].actual_at == day.at(DAY, time(0, 32)), "nothing is changed by asking"
    assert run(plain.log_save(request, card.data)).startswith(f"✏️ **Pill A** (dose 1 of 3) · taken 12:32 am → {at}")
    assert run(plain.log_check(request, card.data)) == ""


def test_dose_2_by_its_number_is_logged_then_corrected_and_what_is_not_there_is_said(world):
    world.now = day.at(DAY, time(9, 5))
    add(world, MAIN)
    log(world, {"pill": "pill a", "did": "taken", "at": "9:00 am"})
    world.now = day.at(DAY, time(12, 30))
    assert run(plain.log_asks(world.request(), {"doses": [numbered(2, "12:15 pm")]})) is False, "in order and 3h on: nothing to ask"
    assert run(plain.log_asks(world.request(), {"doses": [numbered(2, "12:15 pm", pill="@that")]})) is True, "hours after the last log, “it” is only a pick"
    assert log(world, numbered(2, "12:15 pm")).startswith("✅ **Pill A** (dose 2 of 3) · taken 12:15 pm")
    assert log(world, numbered(2, "12:20 pm")).startswith("✏️ **Pill A** (dose 2 of 3) · taken 12:15 pm → 12:20 pm")
    early = run(plain.log_card(world.request(), {"doses": [numbered(2, "8:00 am")]}, frozenset()))
    assert early.warnings == ("That's before dose 1, taken 9:00 am. Log it anyway?",)
    assert log(world, numbered(4, "12:25 pm")) == "⚠️ **Pill A** is 3 doses a day: there is no dose 4."
    assert log(world, numbered(3, did="not_taken")) == "💊 **Pill A** (dose 3 of 3) isn't ticked off today: there is nothing to change."
    assert log(world, numbered(1, did="not_taken")).startswith("↩️ **Pill A** (dose 1 of 3) · no longer ticked off"), "dose 1, though dose 2 was taken later"


def test_a_later_dose_logged_before_an_earlier_one_is_asked_about(world):
    world.now = day.at(DAY, time(12, 30))
    add(world, MAIN)
    card = run(plain.log_card(world.request(), {"doses": [numbered(2, "12:15 pm")]}, frozenset()))
    assert card.lines == ("**Pill A** (dose 2 of 3) · taken 12:15 pm",) and card.warnings == ("Dose 1 isn't ticked off. Log it anyway?",)
    assert run(plain.log_save(world.request(), card.data)).startswith("✅ **Pill A** (dose 2 of 3) · taken 12:15 pm")
    assert pill_a(world)[1][0] != DONE


def test_the_log_action_takes_a_dose_number_and_shows_how(world):
    from core import actions

    log_action = next(action for action in plain.ACTIONS if action.name == "pill_log")
    item = actions.schema(log_action)["properties"]["doses"]["items"]
    assert item["properties"]["dose"]["type"] == "integer" and "dose" not in item["required"], "only when I say which"
    assert "dose 1, at 9:00 am" in log_action.description and "dose 2, at 12:15 pm" in log_action.description


# --- the morning's post, as it went wrong live on 2026-10-12 --------------------------------------------------
# The bot was started at about 1:30 am and the checklist was asked for by hand at 1:29 am. At 6:00 am the job ran
# on time, found "today's checklist is there already", brought it up to date in place and posted nothing, saying
# nothing anywhere.
NOT_POSTED = "💊 Pills checklist not posted"


def six(number=61, late=None):
    due = day.at(DAY, time(6, 0))
    return scheduler.Job(number, None, "pills", checklist.JOB, {}, due)


def test_started_at_half_past_one_on_a_fresh_day_the_checklist_posts_at_six(world, caplog):
    add(world, MAIN)
    world.now = day.at(DAY, time(1, 30))
    run(checklist.startup())
    assert world.sent == [], "before 6:00 am nothing is posted"
    (booked,) = run(scheduler.pending_jobs("pills", checklist.JOB))
    assert booked.due_at == day.at(DAY, time(6, 0)), "today's 6:00 am, not tomorrow's"
    world.now = day.at(DAY, time(6, 0))
    with caplog.at_level("INFO", logger="assistant"):
        run(checklist.post_job(six(booked.id)))
    assert [sent.card.text.splitlines()[0] for sent in world.sent] == ["## 💊 Pills · ▱▱▱▱▱ 0 of 3"] and world.sent[0].channel == HUB
    assert f"Pills checklist, job {booked.id} (2026-10-12 6:00 am), user {world.owner.id}: posted: 3 doses" in caplog.text
    assert world.bot_log == [], "posted: nothing to report"


def test_with_yesterday_s_checklist_still_there_today_s_posts_at_six(world):
    add(world, MAIN)
    world.now = day.at(DAY - timedelta(days=1), time(22, 0))
    run(checklist.post(world.owner.id))
    world.now = day.at(DAY, time(1, 30))
    run(checklist.startup())
    world.now = day.at(DAY, time(6, 0))
    run(checklist.post_job(six()))
    assert len(world.sent) == 2 and world.sent[-1].card.text.count("💊 **Pill A**") == 3, "a fresh one for today"
    held = run(database.run(store.db_messages, world.owner.id, DAY))
    assert [message.message_id for message in held] == [world.sent[-1].id]
    assert world.sent[0].id not in world.deleted, "yesterday's is closed and left where it is"


def test_a_checklist_asked_for_in_the_night_does_not_stand_in_for_the_morning_s(world, caplog):
    add(world, MAIN)
    world.now = day.at(DAY, time(1, 29))
    night = run(checklist.post(world.owner.id))  # `pills`, typed at 1:29 am
    world.now = day.at(DAY, time(6, 0))
    with caplog.at_level("INFO", logger="assistant"):
        run(checklist.post_job(six()))
    assert len(world.sent) == 2 and night in world.deleted, "a fresh copy at the bottom of the hub; the night's copy goes"
    assert "posted: 3 doses, in place of the copy from 1:29 am" in caplog.text
    # The job run twice, or a restart later in the morning: this morning's is there, so it is only brought up to date
    world.now = day.at(DAY, time(7, 0))
    with caplog.at_level("INFO", logger="assistant"):
        run(checklist.post_job(six(62)))
    run(checklist.startup())
    assert len(world.sent) == 2
    why = "it was already posted at 6:00 am; brought up to date in place"
    assert f"not posted: {why}" in caplog.text
    assert world.bot_log == [], "the checklist is simply there: nothing to say in #bot-log"


def test_a_morning_with_no_post_says_why_in_the_log_and_only_a_real_problem_in_bot_log(world, monkeypatch, caplog):
    world.now = day.at(DAY, time(6, 0))
    with caplog.at_level("INFO", logger="assistant"):
        run(checklist.post_job(six()))
    assert "not posted: nobody has a pill" in caplog.text and world.bot_log == [], "no pills at all: the log only"
    add(world, {"name": "Iron"})
    run(plain.pause_save(world.request(), {"pills": [{"pill": "iron"}]}))
    with caplog.at_level("INFO", logger="assistant"):
        run(checklist.post_job(six()))
    assert "not posted: there is nothing to take today" in caplog.text and world.bot_log == [], "nothing to take is no problem"
    run(plain.resume_save(world.request(), {"pills": [{"pill": "iron"}]}))
    monkeypatch.setattr(hub, "channel_id", lambda: None)
    run(checklist.post_job(six()))
    assert world.bot_log == [(NOT_POSTED, "Job 61: the hub channel is not set or can't be found.")] and world.sent == []


def test_only_a_hub_that_cannot_be_found_makes_the_morning_job_a_skipped_one(world, monkeypatch):
    reported = []
    monkeypatch.setattr(scheduler, "report", lambda job, ended: reported.append((job.id, ended)))
    world.now = day.at(DAY, time(6, 0))
    run(checklist.post_job(six(70)))  # nothing to take today
    add(world, MAIN)
    run(checklist.post_job(six(71)))  # posted
    world.now = day.at(DAY, time(7, 0))
    run(checklist.post_job(six(72)))  # this morning's is there already
    assert reported == [], "a morning with nothing to do is not a problem"

    async def nowhere(channel_id, card, silent=False):
        return None

    monkeypatch.setattr(cards, "send", nowhere)  # the hub can't be found
    world.now = day.at(DAY + timedelta(days=1), time(6, 0))
    run(checklist.post_job(scheduler.Job(73, None, "pills", checklist.JOB, {}, world.now)))
    assert reported == [(73, scheduler.SKIPPED)]
    assert world.bot_log[-1] == (NOT_POSTED, "Job 73: the hub channel is not set or can't be found.")


# --- a pill that was guessed is shown first, never logged straight away (task-check C6) ------------------
def test_a_guessed_pill_is_put_on_a_card_with_a_question_mark_and_nothing_is_logged(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    said = {"doses": [{"pill": "zinc", "did": "taken"}]}
    guessed = frozenset({"doses[0].pill"})
    assert run(plain.log_asks(world.request(), said, guessed)) is True, "a guess is never saved unseen"
    proposal = run(plain.log_card(world.request(), said, guessed))
    assert proposal.lines == ("**Zinc** · taken 9:00 am ❓",) and proposal.kind == "change"
    assert proposal.confirm_label == "Save" and proposal.warnings == (), "Save and Cancel: nothing is being asked but whether the guess is right"
    assert state_of(world, "Zinc") == PENDING
    assert run(plain.log_save(world.request(), proposal.data)).startswith("✅ **Zinc** · taken 9:00 am")
    assert state_of(world, "Zinc") == DONE and run(plain.log_check(world.request(), proposal.data)) == ""


def test_an_exact_name_part_of_one_that_fits_one_pill_and_it_all_log_at_once(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    nothing = frozenset()
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "Zinc", "did": "taken"}]}, nothing)) is False
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "zin", "did": "taken"}]}, nothing)) is False, "only one pill it could be"
    assert log(world, {"pill": "zinc", "did": "taken"}).startswith("✅ **Zinc** · taken")
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "@that", "did": "not_taken"}]}, nothing)) is False, "the code resolves “it”: no guess"
    # A guess about something else (the time) is not a guess about which pill
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "iron", "did": "taken"}]}, frozenset({"doses[0].at"}))) is False


def test_with_two_pills_only_the_guessed_one_is_marked(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    said = {"doses": [{"pill": "zinc", "did": "taken"}, {"pill": "iron", "did": "taken"}]}
    proposal = run(plain.log_card(world.request(), said, frozenset({"doses[1].pill"})))
    assert proposal.lines == ("**Zinc** · taken 9:00 am", "**Iron** · taken 9:00 am ❓")


# --- a Discord reply to a dose's message or the checklist is what "it" means (task-check C5) ---------------
def replying(world, message_id, said="took it"):
    return Request(world.owner, HUB, said, replied_to=message_id)


def dose_message(world, name):
    held = run(database.run(store.db_messages, world.owner.id, DAY))
    _, listed, _ = run(checklist.view(world.owner.id))
    wanted = next(dose for dose in listed if dose.pill.plan.name == name)
    return next(message.message_id for message in held if message.occurrence_id == wanted.occurrence.id)


def test_a_reply_to_a_doses_message_means_that_pill_not_the_one_logged_last(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    log(world, {"pill": "zinc", "did": "taken"})  # the pill logged last is Zinc
    iron = dose_message(world, "Iron")
    said = run(plain.log_doses(replying(world, iron), {"doses": [{"pill": "@that", "did": "taken"}]}, frozenset()))
    assert said.startswith("✅ **Iron** · taken 9:00 am"), "where I point beats what is newest"
    assert state_of(world, "Iron") == DONE


def test_without_a_reply_it_is_still_the_pill_logged_last(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    log(world, {"pill": "zinc", "did": "taken"})
    said = log(world, {"pill": "@that", "did": "not_taken"})
    assert said.startswith("↩️ **Zinc** · no longer ticked off") and state_of(world, "Iron") == PENDING


def test_a_pill_i_name_wins_over_the_message_i_replied_to(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    iron = dose_message(world, "Iron")
    said = run(plain.log_doses(replying(world, iron, "took zinc"), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset()))
    assert said.startswith("✅ **Zinc** · taken") and state_of(world, "Iron") == PENDING, "what I state wins"


def test_a_reply_to_the_checklist_means_its_pill_when_there_is_one(world):
    add(world, {"name": "Pill A", "times": ["8:00 am"]})
    sheet_id = run(checklist.post(world.owner.id))
    said = run(plain.log_doses(replying(world, sheet_id), {"doses": [{"pill": "@that", "did": "taken"}]}, frozenset()))
    assert "**Pill A**" in said and "taken 9:00 am" in said, "nothing was logged before: the checklist says which pill"


def test_a_reply_to_a_checklist_of_several_pills_or_to_any_other_message_falls_back(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    sheet_id = run(checklist.post(world.owner.id))
    asked = {"doses": [{"pill": "@that", "did": "taken"}]}
    assert run(plain.log_doses(replying(world, sheet_id), asked, frozenset())) == "⚠️ Which pill? Say its name.", "it can't tell which, and nothing was logged yet"
    assert run(plain.log_doses(replying(world, 123456), asked, frozenset())) == "⚠️ Which pill? Say its name."


def state_of(world, name):
    """The state of a pill's (first) dose today, as the database has it."""
    _, listed, _ = run(checklist.view(world.owner.id))
    return next(dose.occurrence.state for dose in listed if dose.pill.plan.name == name)


# --- every line about a pill or a dose is that pill's: a reply to it means that pill and that dose -------
def said_as(world, answer, message_id):
    """An action's answer, posted as the conversation posts it: the task is told which message it was."""
    run(answer.placed(message_id))
    return answer.text


def test_a_reply_to_the_line_that_said_a_dose_was_taken_means_that_pill_and_that_dose(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    zinc_line = 9001
    said = said_as(world, run(plain.log_answer(world.request(), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset())), zinc_line)
    assert said.startswith("✅ **Zinc** · taken 9:00 am")
    said_as(world, run(plain.log_answer(world.request(), {"doses": [{"pill": "iron", "did": "taken"}]}, frozenset())), 9002)  # Iron is now the pill logged last
    it = lambda did, **more: {"doses": [{"pill": "@that", "did": did, **more}]}  # noqa: E731
    reply = replying(world, zinc_line)
    assert run(plain.log_asks(reply, it("taken", at="8:30 am"), frozenset())) is False, "the line is the anchor: no card"
    assert run(plain.log_doses(reply, it("taken", at="8:30 am"), frozenset())).startswith("✏️ **Zinc** · taken 9:00 am → 8:30 am"), "that dose, corrected"
    assert run(plain.log_doses(reply, it("taken"), frozenset())).startswith("✅ **Zinc** · taken 8:30 am") and state_of(world, "Iron") == DONE
    assert run(plain.log_doses(reply, it("not_taken"), frozenset())).startswith("↩️ **Zinc** · no longer ticked off")
    assert state_of(world, "Zinc") == PENDING and state_of(world, "Iron") == DONE
    from tasks.pills import task

    assert run(task.owns_message(zinc_line)) is True and run(task.owns_message(424242)) is False


def test_a_line_about_two_pills_points_at_neither_and_is_no_anchor(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    both = {"doses": [{"pill": "zinc", "did": "taken"}, {"pill": "iron", "did": "taken"}]}
    said_as(world, run(plain.log_answer(world.request(), both, frozenset())), 9001)
    undo = {"doses": [{"pill": "@that", "did": "not_taken"}]}
    assert run(plain.log_asks(world.request(), undo, frozenset())) is True, "straight after, but the line named two: the pick is shown first"
    assert run(plain.log_card(world.request(), undo, frozenset())).lines == ("**Iron** · no longer ticked off ❓",)
    assert run(plain.log_asks(replying(world, 9001), undo, frozenset())) is True, "a reply to it says no more"


def test_a_saved_card_and_an_already_line_are_the_pills_too(world):
    add(world, {"name": "Zinc"}, {"name": "Iron"})
    run(checklist.post(world.owner.id))
    # The card that asks first, once saved, is the line of the dose it logged
    card = run(plain.log_card(world.request(), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset({"doses[0].pill"})))
    said_as(world, run(plain.log_saved(world.request(), card.data)), 9001)
    assert [pill_id for pill_id, _ in run(database.run(store.db_line, 9001))] == [1] and run(database.run(store.db_line, 9001))[0][1] is not None
    # "✅ Zinc · taken … already" is about Zinc though nothing was done
    again = run(plain.log_answer(world.request(), {"doses": [{"pill": "zinc", "did": "taken"}]}, frozenset()))
    assert said_as(world, again, 9002).endswith("already") and run(database.run(store.db_line, 9002)) == [(1, None)]
    # A plan card's Save says a line about the pill it changed
    edit = next(action for action in plain.ACTIONS if action.name == "pill_add")
    proposal = run(plain.add_card(world.request(), {"pills": [{"name": "Magnesium"}]}, frozenset()))
    saved = run(edit.apply(world.request(), proposal.data))
    assert said_as(world, saved, 9003).startswith("✅ Saved") and run(database.run(store.db_line, 9003)) == [(3, None)]
    took = run(plain.log_doses(replying(world, 9003), {"doses": [{"pill": "@that", "did": "taken"}]}, frozenset()))
    assert took.startswith("✅ **Magnesium** · taken"), "“took it” as a reply to the line that saved it"


# --- days of the week (2026-10-13): a pill taken on certain days only ---------------------------------------------------
TUESDAY = DAY + timedelta(days=1)


def _card(world, action, *items):
    return run(action(world.request(), {"pills": list(items)}, frozenset()))


def test_a_pill_on_certain_days_says_so_on_its_card_and_is_saved_with_them(world):
    proposal = _card(world, plain.add_card, {"name": "Gym vitamin", "times": ["8:00 am"], "weekdays": ["mon", "wed", "fri"]})
    assert proposal.lines == ("**Gym vitamin** · Mon, Wed, Fri at `8:00 am`",)
    assert run(plain.add_save(world.request(), proposal.data)) == "✅ Saved · 💊 **Gym vitamin** · Mon, Wed, Fri at `8:00 am`"
    (pill,) = run(store.pills(world.owner.id))
    assert pill.plan.schedule.days == (0, 2, 4) and pill.plan.schedule.is_on(DAY) and not pill.plan.schedule.is_on(TUESDAY)
    assert _card(world, plain.add_card, {"name": "Work pill", "weekdays": ["mon", "tue", "wed", "thu", "fri"]}).lines == ("**Work pill** · Mon to Fri, any time",)
    assert _card(world, plain.add_card, {"name": "Twice", "per_day": 2, "weekdays": ["sat", "sun"]}).lines == ("**Twice** · 2× a day, Sat, Sun, any time",)
    every = _card(world, plain.add_card, {"name": "All week", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]})
    assert every.lines == ("**All week** · daily, any time",), "every day of the week is simply daily"


def test_it_is_on_the_checklist_on_its_days_and_listed_with_its_days_on_the_others(world):
    add(world, {"name": "Gym vitamin", "weekdays": ["mon", "wed", "fri"]}, {"name": "Zinc"})
    run(checklist.post(world.owner.id))
    assert "Gym vitamin" in sheet(world) and "Not today" not in sheet(world), "Monday is one of its days"
    world.now = day.at(TUESDAY, time(9, 0))
    run(checklist.new_day(DAY, TUESDAY))
    pills, listed, _ = run(checklist.view(world.owner.id))
    assert [dose.pill.plan.name for dose in listed] == ["Zinc"], "no dose is expected on a day that is not one of its days"
    text = today.checklist(listed, pills, TUESDAY)
    assert text.endswith("### 🗓️ Not today\n🗓️ **Gym vitamin** · Mon, Wed, Fri") and "of 1" in text.splitlines()[0] or "1" in text.splitlines()[0]
    assert log(world, {"pill": "gym vitamin", "did": "taken"}) == "🗓️ **Gym vitamin** is taken Mon, Wed, Fri: there is nothing to tick off today."
    drawn = sheet_module.layout(listed, pills, TUESDAY, world.now)
    said = " ".join(str(piece) for piece in drawn)
    assert "Not today" in said and "Gym vitamin · Mon, Wed, Fri" in said, "the drawn checklist shows it too"


def test_the_days_are_changed_and_taken_away_on_a_change_card(world):
    add(world, {"name": "Gym vitamin", "times": ["8:00 am"], "weekdays": ["mon", "wed", "fri"]})
    proposal = _card(world, plain.edit_card, {"pill": "gym vitamin", "weekdays": ["sat", "sun"]})
    assert proposal.lines[1] == "schedule · Mon, Wed, Fri at `8:00 am` → Sat, Sun at `8:00 am`"
    run(plain.edit_save(world.request(), proposal.data))
    assert run(store.pills(world.owner.id))[0].plan.schedule.days == (5, 6)
    proposal = _card(world, plain.edit_card, {"pill": "gym vitamin", "clear": ["weekdays"]})
    assert proposal.lines[1] == "schedule · Sat, Sun at `8:00 am` → daily at `8:00 am`"
    run(plain.edit_save(world.request(), proposal.data))
    assert run(store.pills(world.owner.id))[0].plan.schedule.days == ()
    proposal = _card(world, plain.edit_card, {"pill": "gym vitamin", "notes": "with food"})
    run(plain.edit_save(world.request(), proposal.data))
    assert run(store.pills(world.owner.id))[0].plan.schedule.days == (), "a change that says nothing about days keeps them as they are"


def test_days_come_as_a_list_of_days_and_nothing_else_is_read(world):
    assert rules._weekdays("mon, wed, fri") == (0, 2, 4) and rules._weekdays("sun mon") == (0, 6)
    assert rules._weekdays("monday, TUESDAY") == (0, 1), "a day's full name is its first three letters"
    for wrong in ("weekdays", "every other day", ""):
        with pytest.raises(UserError):
            rules._weekdays(wrong)
    add_action = next(action for action in plain.ACTIONS if action.name == "pill_add")
    from core import actions as core_actions

    item = core_actions.schema(add_action)["properties"]["pills"]["items"]["properties"]
    assert item["weekdays"]["items"]["enum"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "which days a phrase means is Claude's to say, as a list"


def test_a_pill_from_before_days_of_the_week_is_taken_every_day(world):
    add(world, {"name": "Zinc"})
    (pill,) = run(store.pills(world.owner.id))
    assert pill.plan.schedule.days == () and all(pill.plan.schedule.is_on(DAY + timedelta(days=offset)) for offset in range(7))
    assert rules.is_taken_on(pill, TUESDAY) and not rules.is_off_day(pill, TUESDAY)


# --- a dose of the day before, logged after midnight -----------------------------------------------------------------
def _after_midnight(world, hour=0, minute=30):
    """Monday evening's checklist is up; then the day ends and it is Tuesday, early."""
    world.now = day.at(DAY, time(21, 0))
    run(checklist.post(world.owner.id))
    world.now = day.at(TUESDAY, time(hour, minute))
    run(checklist.new_day(DAY, TUESDAY))


def _states(world, on):
    pills = {pill.id: pill.plan.name for pill in run(store.pills(world.owner.id))}
    return {pills[each.item_id]: (each.state, each.actual_at) for each in run(occurrences.for_day(world.owner.id, "pills", on))}


def test_took_it_last_night_at_11_is_yesterday_s_dose_and_is_done_at_once(world):
    add(world, {"name": "Zinc"}, {"name": "Evening pill", "times": ["8:00 pm"]})
    _after_midnight(world)
    data = {"doses": [{"pill": "zinc", "did": "taken", "at": "11:00", "day": "last_night"}]}
    assert run(plain.log_asks(world.request(), data)) is False, "said in so many words, with a time that reads one way: nothing to ask"
    said = log(world, *data["doses"])
    assert said.startswith("✅ **Zinc** · taken 11:00 pm · yesterday")
    assert _states(world, DAY)["Zinc"] == (DONE, day.at(DAY, time(23, 0))), "last night at 11 is the evening"
    assert _states(world, TUESDAY)["Zinc"][0] == PENDING, "and today's dose is still to take"
    assert "yesterday already" in log(world, *data["doses"]), "said again, nothing is logged twice"


def test_a_time_that_has_not_come_yet_after_midnight_is_asked_about_as_yesterday_s(world):
    add(world, {"name": "Evening pill", "times": ["8:00 pm"]})
    _after_midnight(world)
    data = {"doses": [{"pill": "evening pill", "did": "taken", "at": "9:00 pm"}]}
    assert run(plain.log_asks(world.request(), data)) is True, "nobody said yesterday: it is asked first"
    proposal = run(plain.log_card(world.request(), data, frozenset()))
    assert proposal.lines == ("**Evening pill** · taken 9:00 pm · yesterday",) and proposal.confirm_label == "Log it"
    assert proposal.warnings[0].startswith("It is past midnight and 9:00 pm has not come yet today, so this is yesterday's dose.")
    assert _states(world, DAY)["Evening pill"][0] == MISSED, "nothing is changed until Log it"
    assert run(plain.log_save(world.request(), proposal.data)).startswith("✅ **Evening pill** · taken 9:00 pm · yesterday")
    assert _states(world, DAY)["Evening pill"] == (DONE, day.at(DAY, time(21, 0))) and run(plain.log_check(world.request(), proposal.data)) == ""


def test_later_in_the_day_a_time_still_to_come_is_simply_refused(world):
    add(world, {"name": "Evening pill", "times": ["8:00 pm"]})
    _after_midnight(world, 5, 0)
    assert log(world, {"pill": "evening pill", "did": "taken", "at": "9:00 pm"}) == "⚠️ Evening pill: 9:00 pm hasn't happened yet: it's 5:00 am now."
    said = log(world, {"pill": "evening pill", "did": "taken", "at": "9:00 pm", "day": "yesterday"})
    assert said.startswith("✅ **Evening pill** · taken 9:00 pm · yesterday"), "said to be yesterday, it is, at any hour"


def test_yesterday_with_a_time_that_reads_two_ways_or_none_asks_first(world):
    add(world, {"name": "Zinc"}, {"name": "Evening pill", "times": ["8:00 pm"]})
    _after_midnight(world, 9, 0)
    either = {"doses": [{"pill": "zinc", "did": "taken", "at": "8:00", "day": "yesterday"}]}
    assert run(plain.log_asks(world.request(), either)) is True
    proposal = run(plain.log_card(world.request(), either, frozenset()))
    assert proposal.lines == ("**Zinc** · taken 8:00 pm · yesterday",) and proposal.warnings[0].startswith("“8:00” could be morning or evening: taken as 8:00 pm.")
    none = {"doses": [{"pill": "evening pill", "did": "taken", "day": "yesterday"}]}
    proposal = run(plain.log_card(world.request(), none, frozenset()))
    assert proposal.lines == ("**Evening pill** · taken 8:00 pm · yesterday",) and proposal.warnings[0].startswith("No time was given: its planned time is used (8:00 pm).")
    none = {"doses": [{"pill": "zinc", "did": "taken", "day": "yesterday"}]}
    assert run(plain.log_card(world.request(), none, frozenset())).warnings[0].startswith("No time was given: the end of the day is used (11:59 pm).")


def test_what_cannot_be_yesterday_s_is_said(world):
    add(world, {"name": "Zinc"})
    _after_midnight(world)
    add(world, {"name": "New today"})
    assert log(world, {"pill": "new today", "did": "taken", "day": "yesterday"}) == "💊 **New today** had nothing to take yesterday."
    assert log(world, {"pill": "zinc", "did": "skipped", "day": "yesterday"}) == "⚠️ For yesterday I can only log a dose as taken."
    assert log(world, {"pill": "zinc", "did": "taken", "dose": 2, "at": "9:00 pm", "day": "yesterday"}) == "💊 **Zinc** had 1 dose yesterday, not a dose 2."
