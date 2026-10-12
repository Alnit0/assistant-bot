"""A restart, intentional or a crash (core/restart.py): what survives, what the bot catches up
on when it starts, that it says so once in #bot-log, never posts a duplicate and never says a
thing was done that wasn't. A restart here is: everything held only in memory is thrown away,
the database stays, and the start-up runs again at whatever time it now is. Timers are left out."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clearing, clock, confirm, database, day, discord_utils, hub, live, llm, occurrences, restart, scheduler
from core.actions import Request
from core.clearing import Found, Scan
from core.config import real_now_nz
from core.occurrences import DONE, MISSED, PENDING
from tasks import channel as channel_task
from tasks import registry
from tasks.pills import checklist, plain, store
from tasks.pills import task as pills_task

DAY = date(2026, 10, 12)
EVE = DAY - timedelta(days=1)
INBOX, HUB = 100, 400
THREE = ({"name": "Vitamin D"}, {"name": "Magnesium", "notes": "with food"}, {"name": "Evening pill", "times": ["8:00 pm"]})
NOT_POSTED = "💊 Pills checklist not posted"


@pytest.fixture
def world(make_db, monkeypatch, owner, tmp_path):
    # The schedules the bot has when it runs: the end of the day, and (registered by the pills task) the 6:00 am post
    monkeypatch.setattr(scheduler, "_standing", {(day.JOB_TASK, day.JOB_KIND): day.DEFAULT})
    make_db({"pills": store.MIGRATIONS})
    seen = SimpleNamespace(
        owner=owner, sent=[], edited=[], deleted=[], bot_log=[], marked=[], next_id=7000, now=day.at(DAY, time(9, 0)),
        messages=[], cleared=[],
    )

    async def send(channel_id, card, silent=False):
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        seen.edited.append((message_id, card))
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        seen.messages = [each for each in seen.messages if each.id != message_id]
        return True

    async def log_simple(title, description=None):
        seen.bot_log.append((title, description))

    async def mark(channel_id, message_id):
        seen.marked.append((channel_id, message_id))
        return True

    async def scan(channel_id):
        return Scan(channel_id, f"<#{channel_id}>", tuple(seen.messages), (), name="inbox")

    async def delete_many(channel_id, bulk, single):
        ids = {each for batch in bulk for each in batch} | set(single)
        seen.messages = [each for each in seen.messages if each.id not in ids]
        seen.deleted += sorted(ids)
        return ids

    async def note(channel_id, text, seconds):
        pass

    async def cleared(channel_id, gone):
        seen.cleared.append((channel_id, set(gone)))

    async def reposted(channel_id, gone):
        return []

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(clock, "now", lambda: seen.now)
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(discord_utils, "log_simple", log_simple)
    monkeypatch.setattr(channel_task, "log_simple", log_simple)
    monkeypatch.setattr(channel_task, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(restart, "mark", mark)
    monkeypatch.setattr(clearing, "scan", scan)
    monkeypatch.setattr(clearing, "delete", delete_many)
    monkeypatch.setattr(clearing, "note", note)
    monkeypatch.setattr(registry, "channel_cleared", cleared)
    monkeypatch.setattr(registry, "reposted", reposted)
    # What a process holds in memory, fresh for the test and put back after it
    monkeypatch.setattr(llm, "_exchanges", {})
    monkeypatch.setattr(llm, "_answered", {})
    monkeypatch.setattr(actions, "_entries", {})
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(day, "_listeners", {})
    monkeypatch.setattr(restart, "_recoveries", {})
    monkeypatch.setattr(restart, "_lines", [])
    monkeypatch.setattr(restart, "_catching_up", True)
    monkeypatch.setattr(restart, "STARTED", real_now_nz())
    live.reset()
    seen.request = lambda channel=INBOX: Request(owner, channel, "said")
    _set_up()
    return seen


def _set_up():
    """What main.py and the registry do before the bot connects: every handler found again by name."""
    actions.set_catalogue(pills_task.entries())
    confirm.setup()
    checklist.register()
    channel_task.task.setup(None)
    for kind, handler in pills_task.job_handlers().items():
        scheduler.register_handler("pills", kind, handler)
    scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job)
    day.on_new_day("pills", pills_task.new_day)


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


def start(world):
    """The bot starts: what main.py's on_ready does, in its order."""

    async def ready():
        await checklist.startup()
        await day.schedule_next()
        return await restart.catch_up()

    return run(ready())


def stop_and_start(world, monkeypatch, at=None):
    """The bot stops (a restart or a crash) and starts again at `at`: nothing held in memory
    is left, and the database is as it was. Returns the lines of what it caught up on."""
    if at is not None:
        world.now = at
    for held in (llm._exchanges, llm._answered, actions._entries, cards._actions, scheduler._handlers, day._listeners, restart._recoveries):
        held.clear()
    live.reset()
    restart._lines.clear()
    monkeypatch.setattr(restart, "_catching_up", True)
    monkeypatch.setattr(restart, "STARTED", real_now_nz() + timedelta(seconds=1))  # everything logged so far was before it
    _set_up()
    return start(world)


def add(world, *items):
    proposal = run(plain.add_card(world.request(), {"pills": list(items)}, frozenset()))
    run(plain.add_save(world.request(), proposal.data))


def log(world, *doses):
    return run(plain.log_doses(world.request(), {"doses": list(doses)}, frozenset()))


def checklists(world, since=0):
    return [m for m in world.sent[since:] if m.card.text.startswith("## 💊 Pills")]


def sheet(world, on=DAY):
    record = next(m for m in run(database.run(store.db_messages, world.owner.id, on)) if m.kind == store.CHECKLIST)
    edits = [card.text for message_id, card in world.edited if message_id == record.message_id]
    return (edits or [next(m.card.text for m in world.sent if m.id == record.message_id)])[-1]


def states(world, on=DAY):
    found = run(occurrences.for_day(world.owner.id, "pills", on))
    pills = {pill.id: pill.plan.name for pill in run(store.pills(world.owner.id))}
    return {pills[o.item_id]: o.state for o in found}


def caught(world):
    """What the start said in #bot-log about catching up: every message of that kind."""
    return [description for title, description in world.bot_log if title == restart.TITLE]


class Press:
    """Stands in for cards.Press."""

    def __init__(self, user, arg, message_id=None, channel_id=INBOX):
        self.user, self.arg, self.message_id, self.channel_id, self.row_id = user, str(arg), message_id, channel_id, None
        self.shown, self.removed = [], False

    async def update(self, card):
        self.shown.append(card)

    async def remove(self):
        self.removed = True


def pressed(world, task, action, arg, message_id=None, channel_id=INBOX):
    """Press a button as Discord would after a restart: found again by its id alone."""
    press = Press(world.owner, arg, message_id, channel_id)
    run(cards._actions[(task, action)].handler(press))
    return press


def cut_off(world, content, kind="chat", message_id=None, channel_id=INBOX):
    """An input the bot logged and never finished: the row is left as it was received."""
    return run(database.log_received(content, kind, message_id, channel_id, user_id=world.owner.id))


def status_of(row_id):
    return run(database.run(lambda conn: conn.execute("SELECT status, error FROM message_log WHERE id = ?", (row_id,)).fetchone()))


# --- with nothing missed, nothing is said -------------------------------------------------------------
def test_a_restart_with_nothing_missed_says_nothing_about_catching_up_and_posts_nothing(world, monkeypatch):
    add(world, *THREE)
    assert start(world) == [], "the first start of the day: the checklist is start-up's own work, on time"
    posted = len(world.sent)
    assert len(checklists(world)) == 1
    assert stop_and_start(world, monkeypatch, day.at(DAY, time(9, 30))) == []
    assert len(world.sent) == posted, "the same checklist and dose messages, found again"
    assert caught(world) == []


# --- the 6:00 am checklist, with the bot off at 6 -----------------------------------------------------
def off_overnight(world, monkeypatch, back=time(8, 2)):
    """Yesterday evening: three pills, the checklist up, one taken. The bot is then off until `back` today."""
    world.now = day.at(EVE, time(21, 0))
    add(world, *THREE)
    start(world)
    log(world, {"pill": "vitamin d", "did": "taken"})
    world.bot_log.clear()
    before = len(world.sent)
    lines = stop_and_start(world, monkeypatch, day.at(DAY, back))
    return before, lines


def test_off_at_six_the_checklist_is_posted_once_at_start_and_said_once(world, monkeypatch):
    before, lines = off_overnight(world, monkeypatch)
    assert len(checklists(world, before)) == 1, "today's checklist, once"
    assert sheet(world).splitlines()[0] == "## 💊 Pills · ▱▱▱▱▱ 0 of 3"
    assert "Today's pills checklist was posted at 8:02 am: the bot was off at 6:00 am" in lines
    assert "2 pill doses left open on an earlier day were closed late" in lines
    assert "Ran late, as the bot was off when they were due: day rollover (8h late), pills checklist (2h late)" in lines
    # Said once, in one message, and nothing says it was not posted
    assert len(caught(world)) == 1 and all(f"• {line}" in caught(world)[0] for line in lines)
    assert [title for title, _ in world.bot_log] == [restart.TITLE]
    # The next 6:00 am is booked, once
    (booked,) = run(scheduler.pending_jobs("pills", checklist.JOB))
    assert booked.due_at == day.at(DAY + timedelta(days=1), time(6, 0))


def test_a_second_restart_the_same_morning_posts_no_duplicate_and_claims_nothing(world, monkeypatch):
    before, _ = off_overnight(world, monkeypatch)
    posted = len(world.sent)
    world.bot_log.clear()
    assert stop_and_start(world, monkeypatch, day.at(DAY, time(8, 10))) == []
    assert len(world.sent) == posted and len(checklists(world, before)) == 1
    assert caught(world) == [], "nothing was missed this time: no second message about catching up"
    assert world.bot_log == [], "the checklist is simply there: nothing is said at all"


def test_off_over_six_with_the_job_gone_start_up_posts_it_itself(world, monkeypatch):
    # No 6:00 am job is waiting (the database is new, or the job was lost): start-up still posts, once
    world.now = day.at(DAY, time(8, 2))
    add(world, *THREE)
    assert start(world) == []
    assert len(checklists(world)) == 1 and caught(world) == []


def test_started_before_six_nothing_is_posted_until_the_job_runs_on_time(world, monkeypatch):
    world.now = day.at(EVE, time(21, 0))
    add(world, *THREE)
    start(world)
    before = len(world.sent)
    lines = stop_and_start(world, monkeypatch, day.at(DAY, time(5, 30)))
    assert checklists(world, before) == [], "5:30 am: not yet"
    assert lines == ["Ran late, as the bot was off when they were due: day rollover (5h late)", "3 pill doses left open on an earlier day were closed late"]
    world.now = day.at(DAY, time(6, 0))
    run(scheduler.run_all_due())
    assert len(checklists(world, before)) == 1 and len(caught(world)) == 1, "on time: posted, and nothing more is said about catching up"


# --- pill doses and logs -----------------------------------------------------------------------------
def test_what_was_logged_before_a_restart_is_still_logged_and_nothing_is_made_twice(world, monkeypatch):
    add(world, *THREE)
    start(world)
    answer = run(plain.log_answer(world.request(), {"doses": [{"pill": "vitamin d", "did": "taken"}]}, frozenset()))
    run(answer.placed(9001))  # the line it said, as the conversation hands its id back
    before = run(occurrences.for_day(world.owner.id, "pills", DAY))
    posted = len(world.sent)
    stop_and_start(world, monkeypatch, day.at(DAY, time(11, 0)))
    after = run(occurrences.for_day(world.owner.id, "pills", DAY))
    assert [(o.id, o.state, o.actual_at) for o in after] == [(o.id, o.state, o.actual_at) for o in before], "the same rows: none made again, none reset"
    assert states(world) == {"Vitamin D": DONE, "Magnesium": PENDING, "Evening pill": PENDING}
    assert len(world.sent) == posted and "✅ **Vitamin D** · taken 9:00 am" in sheet(world), "the same checklist, brought up to date in place"
    assert run(pills_task.owns_message(9001)) is True, "a reply to the line said before the restart still means that dose"
    # "it" straight after no longer has the log to go by (that was in memory): but a correction by name still finds the dose
    assert log(world, {"pill": "vitamin d", "did": "taken", "at": "8:30 am"}).startswith("✏️ **Vitamin D** · taken 9:00 am → 8:30 am")


def test_the_taken_button_on_a_dose_message_from_before_the_restart_still_works(world, monkeypatch):
    add(world, *THREE)
    start(world)
    magnesium = next(m for m in run(database.run(store.db_messages, world.owner.id, DAY)) if m.kind == store.DOSE and "Magnesium" in next(s.card.text for s in world.sent if s.id == m.message_id))
    stop_and_start(world, monkeypatch, day.at(DAY, time(11, 0)))
    press = pressed(world, "pills", checklist.TAKEN, magnesium.occurrence_id, magnesium.message_id, HUB)
    assert states(world)["Magnesium"] == DONE and press.removed, "ticked off, and its message goes"
    assert "✅ **Magnesium** · taken 11:00 am" in sheet(world)


def test_off_over_midnight_yesterday_is_closed_as_it_stood_and_today_starts_from_the_plan(world, monkeypatch):
    off_overnight(world, monkeypatch)
    assert states(world, EVE) == {"Vitamin D": DONE, "Magnesium": MISSED, "Evening pill": MISSED}, "what was taken stays taken"
    assert states(world) == {"Vitamin D": PENDING, "Magnesium": PENDING, "Evening pill": PENDING}
    assert run(database.run(store.db_messages, world.owner.id, EVE)) == [], "yesterday's checklist is left as it ended, and is no longer ours"


def test_a_taken_press_cut_off_is_reported_and_the_checklist_is_right_either_way(world, monkeypatch):
    add(world, *THREE)
    start(world)
    row = cut_off(world, "card: pills/taken 2", "card", message_id=7003, channel_id=HUB)
    lines = stop_and_start(world, monkeypatch, day.at(DAY, time(9, 5)))
    assert lines == ["A press of a button of pills's was cut off by the stop. Nothing was done about it: press it again if it didn't take"]
    assert status_of(row) == ("interrupted", "the bot stopped before this was finished")
    assert world.marked == [], "a press is no message of mine: nothing is marked"
    assert states(world)["Magnesium"] == PENDING and "💊 **Magnesium**" in sheet(world), "never shown as taken when it wasn't"


# --- buttons on cards posted before the restart -----------------------------------------------------
def add_card(world, name="Zinc"):
    """A confirm card for a new pill, as the conversation posts it."""
    request = world.request()
    proposal = run(plain.add_card(request, {"pills": [{"name": name}]}, frozenset()))
    return run(confirm.show(request, actions.entry("pills"), "pill_add", proposal, frozenset()))


def names(world):
    return [pill.plan.name for pill in run(store.pills(world.owner.id))]


def test_a_confirm_card_from_before_the_restart_still_saves_exactly_what_it_showed(world, monkeypatch):
    card = add_card(world)
    stop_and_start(world, monkeypatch, day.at(DAY, time(9, 10)))
    press = pressed(world, confirm.CARDS, "save", card.id, card.message_id)
    assert names(world) == ["Zinc"] and press.shown[-1].text.startswith("✅"), "the card is kept in the database, not in memory"
    assert run(database.run(confirm.db_get, card.id)).status == confirm.SAVED


def test_a_card_that_expired_while_the_bot_was_off_goes_at_start_and_can_no_longer_save(world, monkeypatch):
    card = add_card(world)
    lines = stop_and_start(world, monkeypatch, day.at(DAY, time(10, 0)))
    assert card.message_id in world.deleted and run(database.run(confirm.db_get, card.id)).status == confirm.EXPIRED
    assert lines == ["Ran late, as the bot was off when they were due: a card's expiry (30m late)"]
    press = pressed(world, confirm.CARDS, "save", card.id, card.message_id)
    assert press.shown[-1].text == confirm.LAPSED and names(world) == []


def test_cancel_on_a_card_from_before_the_restart_still_cancels(world, monkeypatch):
    card = add_card(world)
    stop_and_start(world, monkeypatch, day.at(DAY, time(9, 10)))
    assert pressed(world, confirm.CARDS, "cancel", card.id, card.message_id).removed
    assert run(database.run(confirm.db_get, card.id)).status == confirm.CANCELLED and names(world) == []


# --- an action cut off half way ---------------------------------------------------------------------
def test_a_message_cut_off_gets_the_warning_mark_and_is_said_once(world, monkeypatch):
    row = cut_off(world, "took my zinc", message_id=555)
    lines = stop_and_start(world, monkeypatch)
    assert lines == ["“took my zinc” was cut off by the stop and never answered: marked ⚠️, say it again"]
    assert world.marked == [(INBOX, 555)] and status_of(row) == ("interrupted", "the bot stopped before this was finished")
    assert caught(world) == ["• “took my zinc” was cut off by the stop and never answered: marked ⚠️, say it again"]
    # Starting again finds nothing: it is only ever said once
    assert stop_and_start(world, monkeypatch) == [] and world.marked == [(INBOX, 555)] and len(caught(world)) == 1


def test_an_input_being_handled_as_the_bot_starts_is_not_taken_for_one_cut_off(world, monkeypatch):
    stop_and_start(world, monkeypatch)
    monkeypatch.setattr(restart, "STARTED", real_now_nz() - timedelta(seconds=1))
    row = cut_off(world, "what's the capital of France?", message_id=556)  # logged after this start began
    monkeypatch.setattr(restart, "_catching_up", True)
    assert run(restart.catch_up()) == [] and world.marked == [] and status_of(row)[0] == "received"


def test_a_long_message_is_cut_short_in_the_line_and_other_inputs_are_named_by_kind(world, monkeypatch):
    cut_off(world, "x" * 200, message_id=1)
    cut_off(world, "reaction 📦 on 123", kind="reaction", message_id=2)
    first, second = stop_and_start(world, monkeypatch)
    assert first.startswith("“" + "x" * 59 + "…”") and world.marked == [(INBOX, 1)]
    assert second == "“reaction 📦 on 123” (reaction) was cut off by the stop and never finished"


def press_cut_off(world, card):
    return cut_off(world, f"card: {confirm.CARDS}/save {card.id}", "card", message_id=card.message_id)


def test_save_cut_off_after_the_change_took_is_read_back_and_the_card_says_saved_without_saving_twice(world, monkeypatch):
    card = add_card(world)
    run(plain.add_save(world.request(), card.data))  # Save had written the pill when the bot stopped
    press_cut_off(world, card)
    lines = stop_and_start(world, monkeypatch, day.at(DAY, time(9, 1)))
    assert lines == ["Save of a pills card was cut off by the stop after it took: read back, and its card now says so"]
    assert names(world) == ["Zinc"], "once"
    assert run(database.run(confirm.db_get, card.id)).status == confirm.SAVED
    # The bot stopped inside the save, before its words were kept: the change is there, so it says so plainly
    assert world.edited[-1][0] == card.message_id and world.edited[-1][1].text == "✅ Saved.\n-# checked after a restart" and not world.edited[-1][1].rows
    assert run(scheduler.pending_jobs(confirm.JOB_TASK, confirm.JOB_KIND)) == [], "it will not expire later and say nothing was saved"


def test_save_cut_off_before_the_change_took_leaves_the_card_open_and_claims_nothing(world, monkeypatch):
    card = add_card(world)
    press_cut_off(world, card)
    edits = len(world.edited)
    (line,) = stop_and_start(world, monkeypatch, day.at(DAY, time(9, 1)))
    assert line.startswith("Save of a pills card was cut off by the stop before it took (") and line.endswith("its card is still open, press Save again")
    assert names(world) == [] and len(world.edited) == edits and card.message_id not in world.deleted
    assert run(database.run(confirm.db_get, card.id)).status == confirm.OPEN
    pressed(world, confirm.CARDS, "save", card.id, card.message_id)
    assert names(world) == ["Zinc"], "pressed again, it saves"


def test_save_cut_off_after_the_card_was_closed_only_puts_the_words_on_it(world, monkeypatch):
    card = add_card(world)
    said = run(plain.add_save(world.request(), card.data))
    run(database.run(confirm.db_confirmed, card.id, said))
    run(database.run(confirm.db_close, card.id, confirm.SAVED))  # closed, and the bot stopped before the card was rewritten
    press_cut_off(world, card)
    stop_and_start(world, monkeypatch, day.at(DAY, time(9, 1)))
    assert said.startswith("✅ ") and "Zinc" in said
    assert world.edited[-1] == (card.message_id, cards.Card(f"{said}\n-# checked after a restart")) and names(world) == ["Zinc"]


def test_save_keeps_its_words_the_moment_the_change_is_applied(world, monkeypatch):
    # The usual place to be cut off is while Discord is being told: by then the words are in the database
    card = add_card(world)

    class Dies(Press):
        async def update(self, shown):
            raise ConnectionError("the bot stopped here")

    with pytest.raises(ConnectionError):
        run(cards._actions[(confirm.CARDS, "save")].handler(Dies(world.owner, card.id, card.message_id)))
    kept = run(database.run(confirm.db_get, card.id))
    assert kept.status == confirm.SAVED and kept.confirmation.startswith("✅ ") and "Zinc" in kept.confirmation
    press_cut_off(world, card)
    stop_and_start(world, monkeypatch, day.at(DAY, time(9, 1)))
    assert world.edited[-1] == (card.message_id, cards.Card(f"{kept.confirmation}\n-# checked after a restart"))
    assert names(world) == ["Zinc"], "once"


def test_a_job_cut_off_by_the_stop_runs_again(world, monkeypatch):
    add(world, *THREE)
    world.now = day.at(DAY, time(6, 0))
    run(checklist.book_next())
    run(database.run(lambda conn: conn.execute("UPDATE scheduled_jobs SET due_at = ?, status = 'running' WHERE kind = ?", (scheduler.to_db(world.now), checklist.JOB))))
    lines = stop_and_start(world, monkeypatch, day.at(DAY, time(6, 0, 30)))
    assert lines == ["1 job cut off by the stop ran again"], "30 seconds on is not late"
    assert len(checklists(world)) == 1


def test_a_recovery_that_fails_is_reported_and_never_stops_the_start(world, monkeypatch):
    async def broken(cut, arg):
        raise RuntimeError("no")

    row = cut_off(world, "card: pills/taken 2", "card", message_id=1)
    cut_off(world, "hello", message_id=2)

    def set_up_with_a_broken_one():
        _real()
        restart.on_cut_off("pills", "taken", broken)

    _real = globals()["_set_up"]
    monkeypatch.setitem(globals(), "_set_up", set_up_with_a_broken_one)
    first, second = stop_and_start(world, monkeypatch)
    assert first == f"Log row {row} was cut off by the stop and could not be checked: RuntimeError('no')"
    assert second.startswith("“hello” was cut off"), "the rest is still put right"


# --- the reset card ---------------------------------------------------------------------------------
ASKED = 6


def message(message_id, **said):
    return Found(message_id, clock.real_now(), False, "", **said)


def reset_card(world):
    world.messages = [message(1), message(2), message(3), message(4), message(ASKED, author="Alnit0", content="reset this channel")]
    run(channel_task.reset_asked(Request(world.owner, INBOX, "reset this channel", message_id=ASKED), {}, frozenset()))
    card = world.sent[-1]
    world.messages.append(message(card.id))
    return card


def test_the_reset_card_from_before_a_restart_still_resets_the_channel_as_it_now_stands(world, monkeypatch):
    card = reset_card(world)
    stop_and_start(world, monkeypatch)
    world.messages.append(message(9))  # said since the card was posted
    press = pressed(world, "channel", channel_task.ALL, f"{INBOX}:{ASKED}", card.id)
    assert press.shown[0].text == "🧹 Deleting 5 messages…", "counted when pressed: nothing about the channel was kept in memory"
    assert world.messages == [] and world.cleared == [(INBOX, {1, 2, 3, 4, 9, ASKED, card.id})]


def test_cancel_on_the_reset_card_from_before_a_restart_removes_it_and_my_message(world, monkeypatch):
    card = reset_card(world)
    stop_and_start(world, monkeypatch)
    assert pressed(world, "channel", channel_task.CANCEL, f"{INBOX}:{ASKED}", card.id).removed and ASKED in world.deleted
    assert [each.id for each in world.messages] == [1, 2, 3, 4, card.id]


def test_a_reset_cut_off_half_way_deletes_nothing_more_and_its_card_asks_again(world, monkeypatch):
    card = reset_card(world)
    cut_off(world, f"card: channel/all {INBOX}:{ASKED}", "card", message_id=card.id)
    world.messages = [each for each in world.messages if each.id not in (1, 2)]  # two had gone when the bot stopped
    deleted = list(world.deleted)
    lines = stop_and_start(world, monkeypatch)
    assert lines == ["The reset of <#100> was cut off by the stop: 2 messages still there. Nothing more is deleted until a button is pressed: its card asks again"]
    assert world.deleted == deleted, "nothing more goes by itself"
    edited_id, shown = world.edited[-1]
    assert edited_id == card.id and shown.text.splitlines()[:2] == ["🧹 Channel · reset", "2 messages in <#100>, 0 of them pinned or 📌"]
    assert [button.label for button in shown.rows[0]] == ["Delete all", "Cancel"]
    assert world.cleared == [], "and nothing is said to have been reset"


def test_a_reset_cut_off_at_its_very_end_only_loses_its_own_two_messages(world, monkeypatch):
    card = reset_card(world)
    cut_off(world, f"card: channel/all {INBOX}:{ASKED}", "card", message_id=card.id)
    world.messages = [each for each in world.messages if each.id in (ASKED, card.id)]
    lines = stop_and_start(world, monkeypatch)
    assert lines == ["The reset of <#100> was cut off by the stop at its very end: nothing was left to delete, and its card is gone"]
    assert world.messages == [] and set(world.deleted[-2:]) == {ASKED, card.id}


# --- what is only in memory ---------------------------------------------------------------------------
def test_what_a_restart_does_lose_is_only_what_was_said_lately(world, monkeypatch):
    llm.remember(INBOX, "took my zinc", "✅ Zinc · taken")
    llm.task_answered(INBOX, "pills")
    assert llm.exchanges_for(INBOX) and llm.answering_task(INBOX) == "pills"
    stop_and_start(world, monkeypatch)
    assert llm.exchanges_for(INBOX) == [] and llm.answering_task(INBOX) == "", "the five-minute follow-up starts again: the next message goes to the router"


# --- the pieces ---------------------------------------------------------------------------------------
def test_a_press_is_read_from_its_log_line():
    cut = restart.CutOff(1, "card", "card: confirm/save 12", INBOX, 9, 1)
    assert cut.press == ("confirm", "save", "12")
    assert restart.CutOff(1, "card", "card: channel/all 100:6 picked ['x']", INBOX, 9, 1).press == ("channel", "all", "100:6")
    assert restart.CutOff(1, "card", "card: pills/taken", INBOX, 9, 1).press == ("pills", "taken", "")
    assert restart.CutOff(1, "chat", "card: confirm/save 12", INBOX, 9, 1).press is None, "only a press is a press"


def test_the_line_for_jobs_run_late_groups_them_and_names_each_in_words(monkeypatch):
    def job(kind, late, task="core"):
        return scheduler.Job(1, None, task, kind, {}, day.at(DAY, time(6, 0)), late)

    monkeypatch.setattr(scheduler, "_labels", {("core", "tidy"): "tidying a line away", ("pills", "checklist"): "pills checklist", ("pills", "remind"): "pill reminder"})
    assert restart.late_line([job("tidy", 100), job("tidy", 7300), job("checklist", 7300, "pills"), job("remind", 70, "pills")]) == (
        "Ran late, as the bot was off when they were due: tidying a line away ×2, pills checklist (2h late), pill reminder (1m late)"
    )


def test_the_catch_up_lines_are_checked_like_everything_the_bot_says(monkeypatch):
    from core import outgoing

    monkeypatch.setattr(scheduler, "_labels", {("pills", "remind"): "pill reminder", ("core", "day_rollover"): "end of the day", ("core", "tidy"): "tidying a line away"})
    monkeypatch.setattr(outgoing, "_names", {"pill_add"})
    lines = restart.checked([
        "Ran late, as the bot was off when they were due: pills remind (1m late)",
        "pills/remind ran again, and so did day_rollover",
        "Save of pill_add was cut off",
        "pill_add",
        "a tidy line that names no job is left as it is",
    ])
    assert lines == [
        "Ran late, as the bot was off when they were due: pill reminder (1m late)",
        "pill reminder ran again, and so did end of the day",
        "Save of was cut off",
        "a tidy line that names no job is left as it is",
    ], "a job is put in words, an action's name is taken out, and a line with nothing left is dropped"


def test_every_job_the_core_and_pills_register_has_a_name_in_words():
    from core import backup, confirm, tidy
    from tasks import registry
    from tasks.pills import task as pills_task

    assert backup.JOB_LABEL == "nightly backup" and day.JOB_LABEL == "end of the day"
    assert set(pills_task.job_labels()) == set(pills_task.job_handlers()), "a label for every kind of job"
    assert pills_task.job_labels()["remind"] == "pill reminder"
    registry.load()
    confirm.setup()
    tidy.setup()
    for (task, kind), said in scheduler._labels.items():
        assert "_" not in said and "/" not in said and said != kind, (task, kind, said)
    assert scheduler.label("pills", "remind") == "pill reminder" and scheduler.label("core", "confirm_expire") == "a card's expiry"
    assert scheduler.label("lab", "made_up") == "lab made up", "one nobody named is made readable"
    # Every task that has jobs names each of them: nothing I read is ever "timers timer due"
    for task in registry.loaded_tasks():
        assert set(task.job_labels()) == set(task.job_handlers()), task.name
    assert scheduler.label("timers", "timer_due") == "timer ending" and scheduler.label("timers", "pomo_phase_due") == "Pomodoro phase"
    assert scheduler.in_words("Ran late: timers timer due (2m late), pomo_phase_due") == "Ran late: timer ending (2m late), Pomodoro phase"


def test_a_line_from_a_task_is_only_kept_while_the_bot_is_starting(world):
    assert restart.caught_up("posted late") is True
    run(restart.catch_up())
    assert caught(world) == ["• posted late"]
    assert restart.caught_up("done on time, later") is False and restart._lines == []
