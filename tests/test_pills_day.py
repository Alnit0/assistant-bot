"""Pills: whole days on a clock that is moved, as `dev clock` moves it. The real scheduler runs the
real jobs (the day rollover, the 6:00 am post); only Discord is replaced by a list of messages.

Nothing here patches the time: the one clock (core/clock.py) is moved forward, so anything that
read the date or the time from anywhere else would show up as a wrong day."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, database, day, hub, live, llm, occurrences, scheduler
from core.actions import Request
from core.occurrences import DONE, MISSED, PENDING
from tasks.pills import checklist, plain, store

HUB, INBOX = 400, 100


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"pills": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=9000)

    async def send(channel_id, card, silent=False):
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        seen.edited.append((message_id, card.text))
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(llm, "_exchanges", {})
    # The jobs and listeners the bot has when it runs: the day rollover and the pills task's own
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_standing", {"core/day_rollover": day.schedule_next})
    monkeypatch.setattr(day, "_listeners", {})
    scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job)
    scheduler.register_handler("pills", checklist.JOB, checklist.post_job)
    day.on_new_day("pills", checklist.new_day)
    checklist.register()
    live.reset()
    seen.request = lambda: Request(owner, INBOX, "said")
    return seen


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


def move_to(target_day, at):
    """Move the clock to a time on a day and let everything that came due run, in order."""
    clock.advance_to(day.at(target_day, at))
    return run(scheduler.run_all_due())


def add(world, *items):
    proposal = run(plain.add_card(world.request(), {"pills": list(items)}, frozenset()))
    run(plain.add_save(world.request(), proposal.data))


def log(world, *doses):
    return run(plain.log_doses(world.request(), {"doses": list(doses)}, frozenset()))


def states(world, on):
    return {(o.item_id, o.seq): o.state for o in run(occurrences.for_day(world.owner.id, "pills", on))}


def records(world, on):
    return run(database.run(store.db_messages, world.owner.id, on))


def text_of(world, message_id):
    """A message as it stands now: its last edit, or what was posted."""
    edits = [text for edited, text in world.edited if edited == message_id]
    return (edits or [next(m.card.text for m in world.sent if m.id == message_id)])[-1]


def jobs():
    return {(job.task, job.kind): job.due_at for job in run(scheduler.all_pending())}


PILLS = (
    {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm"},
    {"name": "Pill B"},
    {"name": "Pill C"},
)


def test_two_days_on_a_moved_clock(world):
    saturday = day.today() + timedelta(days=1)
    sunday, monday = saturday + timedelta(days=1), saturday + timedelta(days=2)

    # --- Saturday afternoon: the bot starts, three pills are added, `pills` posts the checklist ---
    move_to(saturday, time(16, 50))
    run(day.schedule_next())
    run(checklist.startup())
    assert jobs() == {("core", "day_rollover"): day.end_of(saturday), ("pills", "checklist"): day.at(sunday, time(6, 0))}
    add(world, *PILLS)
    first = run(checklist.post(world.owner.id, INBOX))
    assert [m.silent for m in world.sent] == [True, True, True], "the checklist and a Taken / Skip message for B and for C"
    assert text_of(world, first).splitlines()[0] == "## 💊 Pills · ▱▱▱▱▱ 0 of 5"
    assert [(m.day, m.kind) for m in records(world, saturday)] == [(saturday, "checklist"), (saturday, "dose"), (saturday, "dose")]
    saturday_singles = [m.message_id for m in records(world, saturday) if m.kind == "dose"]

    # --- across midnight: Saturday is over ---
    assert move_to(sunday, time(0, 5)) == 1, "the rollover, and nothing else yet"
    assert set(states(world, saturday).values()) == {MISSED} and len(states(world, saturday)) == 5
    last = text_of(world, first)
    assert last.count("❌") == 5 and "❌ **Pill B** · missed" in last and "❌ **Pill A** (dose 3 of 3) · missed" in last
    assert world.deleted == saturday_singles, "the Taken / Skip messages nobody pressed are gone"
    assert records(world, saturday) == [] and records(world, sunday) == [], "Saturday's is finished with; Sunday's isn't posted yet"
    assert len(world.sent) == 3
    assert jobs()[("core", "day_rollover")] == day.end_of(sunday)

    # --- across 6:00 am: Sunday's checklist ---
    assert move_to(sunday, time(6, 23)) == 1, "the 6:00 am post"
    assert len(world.sent) == 6 and all(m.silent and m.channel == HUB for m in world.sent[3:])
    second = world.sent[3].id
    assert text_of(world, second).splitlines() == [
        "## 💊 Pills · ▱▱▱▱▱ 0 of 5",
        "",
        "💊 **Pill B**",
        "💊 **Pill C**",
        "💊 **Pill A** (dose 1 of 3) · `8:00 am`",
        "💊 **Pill A** (dose 2 of 3) · `11:30 am`",
        "💊 **Pill A** (dose 3 of 3) · `3:00 pm`",
    ]
    assert set(states(world, sunday).values()) == {PENDING}, "a new day starts fresh from the plan"
    assert jobs()[("pills", "checklist")] == day.at(monday, time(6, 0))
    assert "❌" in text_of(world, first) and len([t for m, t in world.edited if m == first]) == 1, "yesterday's is left as it ended"

    # --- Sunday: doses are logged, by saying so and by a button ---
    move_to(sunday, time(9, 0))
    assert log(world, {"pill": "pill a", "did": "taken", "at": "8:10 am"}) == (
        "✅ **Pill A** (dose 1 of 3) · taken 8:10 am · still to take today: "
        "Pill B, Pill C, Pill A (dose 2 of 3) `11:30 am`, Pill A (dose 3 of 3) `3:00 pm`"
    )
    assert log(world, {"pill": "pill b", "did": "taken"}).startswith("✅ **Pill B** · taken 9:00 am")
    single_c = next(m for m in records(world, sunday) if m.kind == "dose")
    removed = []

    async def remove():
        removed.append(single_c.message_id)

    pressed = SimpleNamespace(user=world.owner, arg=str(single_c.occurrence_id), channel_id=HUB, message_id=single_c.message_id, remove=remove)
    assert run(checklist.on_skip(pressed)) == "⏭️ **Pill C** · skipped" and removed == [single_c.message_id]
    now = text_of(world, second)
    assert "## 💊 Pills · ▰▰▰▱▱ 3 of 5" in now
    assert "✅ **Pill A** (dose 1 of 3) · taken 8:10 am" in now and "✅ **Pill B** · taken 9:00 am" in now and "⏭️ **Pill C** · skipped" in now
    assert [m.kind for m in records(world, sunday)] == ["checklist"], "no single message left: B was said, C was pressed"
    move_to(sunday, time(12, 40))
    assert log(world, {"pill": "pill a", "did": "taken"}).startswith("✅ **Pill A** (dose 2 of 3) · taken 12:40 pm · still to take today: Pill A (dose 3 of 3) `3:40 pm`")

    # --- across the next midnight: what was taken stays, what wasn't is missed ---
    assert move_to(monday, time(0, 1)) == 1
    found = states(world, sunday)
    assert sorted(found.values()) == [DONE, DONE, DONE, MISSED, "skipped"]
    assert found[(1, 3)] == MISSED, "the third dose of Pill A, which nobody took"
    ended = text_of(world, second)
    assert "▰▰▰▰▱ 4 of 5" in ended and "❌ **Pill A** (dose 3 of 3) · missed" in ended and ended.count("✅") == 3
    assert records(world, sunday) == [] and records(world, monday) == []
    assert jobs() == {("core", "day_rollover"): day.end_of(monday), ("pills", "checklist"): day.at(monday, time(6, 0))}
    assert len(world.sent) == 6, "nothing was posted twice anywhere along the way"


def test_jobs_booked_while_the_clock_was_ahead_come_back_with_it(world):
    # QA 2026-10-10: the bot was started with the clock still a day ahead from an earlier run, so
    # the rollover and the 6:00 am post were booked a day late. `dev clock reset` went back to the
    # real time and left them there: midnight and 6:00 am then came and went with nothing done
    today_ = day.today()
    tomorrow = today_ + timedelta(days=1)
    clock.advance(timedelta(hours=24))
    run(day.schedule_next())
    run(checklist.startup())
    assert jobs() == {("core", "day_rollover"): day.end_of(tomorrow), ("pills", "checklist"): scheduler.next_run(time(6, 0), clock.now())}

    clock.reset()
    run(scheduler.rebook_standing())  # what `dev clock reset` and `dev reset-db` now do
    assert jobs() == {("core", "day_rollover"): day.end_of(today_), ("pills", "checklist"): scheduler.next_run(time(6, 0), clock.now())}
    assert jobs()[("pills", "checklist")] <= day.at(tomorrow, time(6, 0))

    add(world, {"name": "Pill B"})
    first = run(checklist.post(world.owner.id, INBOX))
    move_to(tomorrow, time(0, 22))
    assert states(world, today_) == {(1, 1): MISSED} and "❌ **Pill B** · missed" in text_of(world, first)
    move_to(tomorrow, time(6, 23))
    assert [m.kind for m in records(world, tomorrow)] == ["checklist", "dose"], "the new day's checklist was posted"


def test_a_job_that_is_overdue_is_never_moved_later(world):
    booked = clock.now() - timedelta(hours=2)
    run(scheduler.add_job("core", "day_rollover", booked))
    run(scheduler.ensure("core", "day_rollover", clock.now() + timedelta(hours=5)))
    assert jobs() == {("core", "day_rollover"): booked}, "it still has to run"
    run(scheduler.ensure("pills", "checklist", clock.now() + timedelta(hours=5)))
    run(scheduler.ensure("pills", "checklist", clock.now() + timedelta(hours=5)))
    assert len(run(scheduler.pending_jobs("pills", "checklist"))) == 1, "asked twice: still one"


def test_a_day_that_is_over_is_closed_even_if_the_rollover_never_ran(world):
    # Whatever looks at today next closes yesterday: nothing depends on a job having run
    today_ = day.today()
    tomorrow = today_ + timedelta(days=1)
    add(world, {"name": "Pill B"}, {"name": "Pill C"})
    first = run(checklist.post(world.owner.id, INBOX))
    log(world, {"pill": "pill b", "did": "taken"})
    clock.advance_to(day.at(tomorrow, time(0, 22)))  # no job is run
    second = run(checklist.post(world.owner.id, INBOX))  # `pills`, typed on the new day
    assert states(world, today_) == {(1, 1): DONE, (2, 1): MISSED}
    assert "❌ **Pill C** · missed" in text_of(world, first) and "✅ **Pill B**" in text_of(world, first)
    assert records(world, today_) == [] and [m.message_id for m in records(world, tomorrow)][0] == second
    assert text_of(world, second).splitlines()[0] == "## 💊 Pills · ▱▱▱▱▱ 0 of 2", "the new day, from the plan"
    assert log(world, {"pill": "pill c", "did": "taken"}).startswith("✅ **Pill C** · taken 12:22 am")
    assert states(world, tomorrow)[(2, 1)] == DONE and states(world, today_)[(2, 1)] == MISSED, "logged on the day it is, not yesterday"
