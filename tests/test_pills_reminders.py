"""Pills reminders (tasks/pills/reminders.py): a prompt at each timed dose's time, its buttons,
the reminders after it, missed, the latest time, the lock-screen line, and a restart. All on the
dev clock, moved forward as `dev clock` moves it, with the real scheduler running the real jobs;
only Discord is a list of messages. REMINDERS_ENABLED is off unless a test switches it on."""
import asyncio
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from core import actions, cards, clock, config, confirm, database, day, discord_utils, hub, live, llm, occurrences, restart, scheduler
from core.actions import Request
from core.errors import UserError
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from tasks.pills import checklist, plain, reminders, store
from tasks.pills import task as pills_task

HUB, INBOX = 400, 100
PILL_A = {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "11:30 am", "3:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm", "notes": "with food"}
EVENING = {"name": "Evening pill", "times": ["8:00 pm"]}
NOTICE = "💊 Routine due · "


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"pills": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], bot_log=[], next_id=9000)

    async def send(channel_id, card, silent=False):
        cards.check(card)
        seen.next_id += 1
        seen.sent.append(SimpleNamespace(id=seen.next_id, channel=channel_id, card=card, silent=silent))
        return seen.next_id

    async def edit(channel_id, message_id, card):
        cards.check(card)
        seen.edited.append((message_id, card))
        return True

    async def delete(channel_id, message_id):
        seen.deleted.append(message_id)
        return True

    async def log_simple(title, description=None):
        seen.bot_log.append((title, description))

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(discord_utils, "log_simple", log_simple)
    monkeypatch.setattr(llm, "_exchanges", {})
    monkeypatch.setattr(llm, "_answered", {})
    monkeypatch.setattr(scheduler, "_handlers", {})
    monkeypatch.setattr(scheduler, "_standing", {(day.JOB_TASK, day.JOB_KIND): day.DEFAULT})
    monkeypatch.setattr(day, "_listeners", {})
    monkeypatch.setattr(restart, "_lines", [])
    monkeypatch.setattr(restart, "_catching_up", False)
    monkeypatch.setattr(config, "REMINDERS_ENABLED", True)
    monkeypatch.setattr(reminders, "_said_no_hub", False)
    monkeypatch.setattr(actions, "_entries", {})
    actions.set_catalogue(pills_task.entries())
    _set_up()
    # The 6:00 am post is the checklist tests' business: here a checklist is there only when a test asks for one
    scheduler._standing.pop(("pills", checklist.JOB), None)
    live.reset()
    seen.request = lambda replied_to=None: Request(owner, INBOX, "said", replied_to=replied_to)
    # Tomorrow, early: the clock only moves forward
    seen.day = day.today() + timedelta(days=1)
    clock.advance_to(day.at(seen.day, time(0, 30)))
    run(scheduler.run_all_due())
    run(day.schedule_next())
    return seen


def _set_up():
    """What the registry does before the bot connects."""
    scheduler.register_handler(day.JOB_TASK, day.JOB_KIND, day.rollover_job)
    for kind, handler in pills_task.job_handlers().items():
        scheduler.register_handler("pills", kind, handler)
    day.on_new_day("pills", pills_task.new_day)
    checklist.register()
    reminders.register()
    confirm.setup()


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


def at(world, hour, minute=0):
    """Move the clock to a time today and let everything that came due run, in order."""
    clock.advance_to(day.at(world.day, time(hour, minute)))
    return run(scheduler.run_all_due())


def add(world, *items):
    proposal = run(plain.add_card(world.request(), {"pills": list(items)}, frozenset()))
    run(plain.add_save(world.request(), proposal.data))


def log(world, *doses, replied_to=None):
    return run(plain.log_doses(world.request(replied_to), {"doses": list(doses)}, frozenset()))


def prompts(world):
    """The prompts that are up now: (message id, its text as it reads, its button labels)."""
    kept = run(database.run(reminders.db_prompts, world.owner.id))
    found = []
    for prompt in kept:
        if prompt.message_id is None:
            continue
        edits = [card for message_id, card in world.edited if message_id == prompt.message_id]
        shown = (edits or [next(m.card for m in world.sent if m.id == prompt.message_id)])[-1]
        found.append((prompt.message_id, shown.text.splitlines(), [button.label for row in shown.rows for button in row]))
    return found


def notices(world):
    """Every message posted to notify, as it was when the phone showed it: its text at the moment it was sent."""
    return [m.card.text for m in world.sent if m.card.text.startswith(NOTICE)]


def states(world):
    found = run(occurrences.for_day(world.owner.id, "pills", world.day))
    names = {pill.id: pill.plan.name for pill in run(store.pills(world.owner.id))}
    return {(names[o.item_id], o.seq): o.state for o in found}


def remind_job():
    """When the reminders' one job is booked for, to the minute (a dose's time follows the second the one before was taken)."""
    return [reminders.minute(job.due_at) for job in run(scheduler.pending_jobs("pills", reminders.JOB))]


class Press:
    def __init__(self, world, prompt_id, occurrence_id, fields=None):
        self.user, self.arg, self.message_id, self.channel_id, self.fields = world.owner, str(occurrence_id), prompt_id, HUB, fields
        self.shown, self.removed, self.form, self.world = [], False, None, world

    async def update(self, card):
        self.shown.append(card)
        self.world.edited.append((self.message_id, card))

    async def remove(self):
        self.removed = True
        self.world.deleted.append(self.message_id)

    async def open_form(self, form):
        cards.check_form(form)
        self.form = form


def press(world, action, fields=None, which=0):
    kept = run(database.run(reminders.db_prompts, world.owner.id))[which]
    pressed = Press(world, kept.message_id, kept.occurrence_id, fields)
    said = run(cards._actions[("pills", action)].handler(pressed))
    return pressed, said


# --- off by default ----------------------------------------------------------------------------------------
def test_off_no_reminder_is_ever_sent_and_nothing_is_booked(world, monkeypatch):
    monkeypatch.setattr(config, "REMINDERS_ENABLED", False)
    assert reminders.enabled() is False
    add(world, PILL_A, EVENING)
    run(reminders.startup())
    for hour in (8, 9, 12, 16, 21, 23):
        at(world, hour, 5)
    assert notices(world) == [] and run(database.run(reminders.db_prompts)) == [] and remind_job() == []
    run(checklist.view(world.owner.id))
    assert states(world)[("Pill A", 1)] == MISSED, "the day's limit still closes it, as before reminders"


def test_the_setting_is_off_unless_it_is_set():
    assert config.flag(None, False) is False and config.flag("", False) is False and config.flag("true", False) is True
    assert "REMINDERS_ENABLED=false" in (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")


def test_switched_off_with_a_prompt_up_the_prompt_goes_and_nothing_more_comes(world, monkeypatch):
    add(world, EVENING)
    at(world, 20, 0)
    ((prompt_id, _, _),) = prompts(world)
    monkeypatch.setattr(config, "REMINDERS_ENABLED", False)
    run(reminders.startup())
    assert prompts(world) == [] and prompt_id in world.deleted and remind_job() == []
    at(world, 20, 40)
    assert len(notices(world)) == 1 and states(world)[("Evening pill", 1)] == PENDING


# --- the prompt ----------------------------------------------------------------------------------------------
def test_at_its_time_a_dose_gets_one_prompt_and_what_the_phone_shows_names_no_pill(world):
    add(world, EVENING)
    assert remind_job() == [day.at(world.day, time(20, 0))], "one job, for the next dose with a time"
    at(world, 19, 59)
    assert notices(world) == []
    at(world, 20, 0)
    # What notifies is the message as it was sent: one neutral line. The pill is written in after (an edit notifies nobody)
    assert notices(world) == ["💊 Routine due · 8:00 pm"]
    sent = world.sent[-1]
    assert sent.channel == HUB and not sent.silent and not sent.card.rows and "Evening" not in sent.card.text
    ((prompt_id, lines, buttons),) = prompts(world)
    assert prompt_id == sent.id and lines == ["💊 Routine due · 8:00 pm", "**Evening pill**", "Due `8:00 pm`"]
    assert buttons == ["Taken", "Taken at…", "Snooze 15m", "Skip"]


def test_every_line_that_notifies_is_the_neutral_one_whatever_the_pill_dose_or_reminder(world):
    add(world, PILL_A, EVENING, {"name": "Secret thing", "times": ["9:00 am"], "notes": "private note"})
    for hour, minute in ((8, 0), (8, 15), (8, 30), (8, 45), (9, 0), (9, 30), (11, 30), (15, 0), (20, 0), (20, 30)):
        at(world, hour, minute)
    assert len(notices(world)) >= 8
    for line in notices(world):
        assert "\n" not in line and line.startswith(NOTICE), line
        assert not any(word in line for word in ("Pill A", "Evening", "Secret", "dose", "food", "note")), line
    assert all(m.card.text.startswith(NOTICE) for m in world.sent), "nothing else was posted to notify"


def test_the_prompt_says_which_dose_when_it_is_due_and_why_and_the_note(world):
    add(world, PILL_A)
    at(world, 8, 0)
    ((_, lines, _),) = prompts(world)
    assert lines == [
        "💊 Routine due · 8:00 am", "**Pill A** · dose 1 of 3", "Due `8:00 am`", "-# with food",
        "-# ⚠️ Take by 10:00 am so the doses after it still fit",
    ], "two more doses, three hours apart, before 4:00 pm: this one by 10:00 am, which is within two hours"
    assert lines[1:4] == ["**Pill A** · dose 1 of 3", "Due `8:00 am`", "-# with food"]
    at(world, 8, 14)
    log(world, {"pill": "pill a", "did": "taken", "at": "8:12 am"})
    assert prompts(world) == [], "said in words: the prompt goes, as if Taken had been pressed"
    at(world, 11, 30)
    ((_, lines, _),) = prompts(world)
    assert lines[:3] == ["💊 Routine due · 11:30 am", "**Pill A** · dose 2 of 3", "Due `11:30 am`"], "its planned time: 3h after 8:12 is earlier"


def test_a_dose_moved_by_the_gap_says_so_and_take_by_shows_only_when_it_is_close(world):
    add(world, PILL_A)
    at(world, 9, 0)
    log(world, {"pill": "pill a", "did": "taken", "at": "9:00 am"})
    assert remind_job() == [day.at(world.day, time(12, 0))], "dose 2 moved to noon: the job moved with it"
    at(world, 11, 30)
    assert prompts(world) == [], "not at its planned time: the gap has not passed"
    at(world, 12, 0)
    ((_, lines, _),) = prompts(world)
    assert lines == [
        "💊 Routine due · 12:00 pm", "**Pill A** · dose 2 of 3", "Due `12:00 pm` · 3h after dose 1 at 9:00 am", "-# with food",
        "-# ⚠️ Take by 1:00 pm so dose 3 still fits",
    ]


# --- the buttons ---------------------------------------------------------------------------------------------
def test_taken_ticks_it_off_now_removes_the_prompt_and_moves_the_doses_after_it(world):
    add(world, PILL_A)
    at(world, 9, 0)
    pressed, said = press(world, reminders.P_TAKEN)
    assert pressed.removed and said == "✅ **Pill A** (dose 1 of 3) · taken 9:00 am"
    assert states(world)[("Pill A", 1)] == DONE and prompts(world) == []
    assert remind_job() == [day.at(world.day, time(12, 0))]


def test_skip_skips_it_and_removes_the_prompt(world):
    add(world, EVENING)
    at(world, 20, 0)
    pressed, said = press(world, reminders.P_SKIP)
    assert pressed.removed and states(world)[("Evening pill", 1)] == SKIPPED and prompts(world) == [] and remind_job() == []
    at(world, 20, 30)
    assert len(notices(world)) == 1, "nothing more about a dose that was dealt with"


def test_taken_at_opens_a_one_box_form_and_the_time_typed_is_checked_as_a_time_said_is(world):
    add(world, PILL_A)
    at(world, 9, 0)
    pressed, _ = press(world, reminders.P_AT)
    assert pressed.form.title == "When did you take it?" and [field.name for field in pressed.form.fields] == ["at"]
    assert states(world)[("Pill A", 1)] == PENDING
    with pytest.raises(UserError):
        press(world, reminders.P_AT, {"at": "11pm"})  # in the future
    pressed, said = press(world, reminders.P_AT, {"at": "8:15"})
    assert said == "✅ **Pill A** (dose 1 of 3) · taken 8:15 am" and pressed.removed and prompts(world) == []
    taken = next(o for o in run(occurrences.for_day(world.owner.id, "pills", world.day)) if o.seq == 1)
    assert taken.actual_at == day.at(world.day, time(8, 15))
    assert run(occurrences.history(taken.id))[-1].source == occurrences.FORM


def test_a_time_in_the_form_that_needs_asking_gets_the_same_log_it_anyway_card_as_saying_it(world):
    add(world, PILL_A)
    at(world, 8, 0)
    press(world, reminders.P_TAKEN)
    at(world, 11, 30)
    pressed, said = press(world, reminders.P_AT, {"at": "10:00 am"})
    assert not pressed.removed and states(world)[("Pill A", 2)] == PENDING and len(prompts(world)) == 1, "nothing is logged by asking, and the reminder stays"
    asked = world.sent[-1]
    assert asked.channel == HUB and asked.card.text.splitlines()[:3] == [
        "💊 Pills · change", "**Pill A** (dose 2 of 3) · taken 10:00 am",
        "⚠️ That's 2h after dose 1, taken 8:00 am. The gap is at least 3h. Log it anyway?",
    ]
    assert [button.label for button in asked.card.rows[0]] == ["Log it", "Cancel"]
    # Word for word the card that saying it gives
    typed = run(plain.log_card(world.request(), {"doses": [{"pill": "pill a", "did": "taken", "at": "10:00 am"}]}, frozenset()))
    stored = run(database.run(confirm.db_by_message, asked.id))
    assert (typed.lines, typed.warnings, typed.confirm_label) == (("**Pill A** (dose 2 of 3) · taken 10:00 am",), ("That's 2h after dose 1, taken 8:00 am. The gap is at least 3h. Log it anyway?",), "Log it")
    assert stored.data == typed.data and stored.action == "pill_log"
    # Log it logs it at that time, and the reminder goes
    answered = Press(world, asked.id, stored.id)
    run(cards._actions[(confirm.CARDS, "save")].handler(answered))
    assert answered.shown[-1].text.startswith("✅ **Pill A** (dose 2 of 3) · taken 10:00 am")
    assert states(world)[("Pill A", 2)] == DONE and prompts(world) == []


def test_cancel_on_that_card_logs_nothing_and_leaves_the_reminder_up(world):
    add(world, PILL_A)
    at(world, 8, 0)
    press(world, reminders.P_TAKEN)
    at(world, 11, 30)
    press(world, reminders.P_AT, {"at": "10:00 am"})
    asked = world.sent[-1]
    stored = run(database.run(confirm.db_by_message, asked.id))
    cancelled = Press(world, asked.id, stored.id)
    run(cards._actions[(confirm.CARDS, "cancel")].handler(cancelled))
    assert cancelled.removed and states(world)[("Pill A", 2)] == PENDING and len(prompts(world)) == 1
    at(world, 11, 45)
    assert notices(world)[-1] == "💊 Routine due · 11:30 am · reminder 1 of 3", "and it goes on reminding"


def test_snooze_keeps_the_prompt_says_until_when_and_a_fresh_copy_comes_when_it_ends(world):
    add(world, EVENING)
    at(world, 20, 5)
    ((first, _, _),) = prompts(world)
    pressed, _ = press(world, reminders.P_SNOOZE)
    assert not pressed.removed and pressed.shown[-1].text.splitlines()[-1] == "-# 💤 Snoozed until 8:20 pm"
    assert [button.label for button in pressed.shown[-1].rows[0]] == ["Taken", "Taken at…", "Snooze 15m", "Skip"]
    at(world, 20, 19)
    assert len(notices(world)) == 1, "nothing while it is snoozed"
    at(world, 20, 20)
    ((second, lines, _),) = prompts(world)
    assert second != first and first in world.deleted, "a fresh copy, so the phone buzzes: the old one goes"
    assert notices(world)[-1] == "💊 Routine due · 8:00 pm" and lines == ["💊 Routine due · 8:00 pm", "**Evening pill**", "Due `8:00 pm`"], "a snooze is not one of the reminders"


# --- left alone ----------------------------------------------------------------------------------------------
def test_ignored_it_is_posted_again_every_15_minutes_three_times_then_missed(world):
    add(world, EVENING)
    seen = []
    for minute in (0, 15, 30, 45):
        at(world, 20, minute)
        ((prompt_id, lines, _),) = prompts(world)
        seen.append(prompt_id)
        assert len(run(database.run(reminders.db_prompts))) == 1, "only ever one prompt for a dose"
    assert notices(world) == [
        "💊 Routine due · 8:00 pm", "💊 Routine due · 8:00 pm · reminder 1 of 3",
        "💊 Routine due · 8:00 pm · reminder 2 of 3", "💊 Routine due · 8:00 pm · reminder 3 of 3",
    ]
    assert len(set(seen)) == 4 and set(seen[:3]) <= set(world.deleted), "each a new message in place of the one before"
    assert lines[-1] == "-# ⏰ Reminder 3 of 3 · first asked 8:00 pm · the last reminder"
    assert states(world)[("Evening pill", 1)] == PENDING
    at(world, 21, 0)
    assert prompts(world) == [] and seen[3] in world.deleted and states(world)[("Evening pill", 1)] == MISSED
    missed = run(occurrences.for_day(world.owner.id, "pills", world.day))[0]
    assert (missed.automatic, missed.cause) == (True, "ignored")
    at(world, 21, 30)
    run(checklist.view(world.owner.id))
    assert states(world)[("Evening pill", 1)] == MISSED and len(notices(world)) == 4, "final: it is not opened again, and nothing more is sent"
    assert remind_job() == []


def test_the_reminder_line_counts_down(world):
    add(world, EVENING)
    at(world, 20, 0)
    at(world, 20, 15)
    assert prompts(world)[0][1][-1] == "-# ⏰ Reminder 1 of 3 · first asked 8:00 pm · 2 more, the next at 8:30 pm"
    at(world, 20, 30)
    assert prompts(world)[0][1][-1] == "-# ⏰ Reminder 2 of 3 · first asked 8:00 pm · one more at 8:45 pm"


def test_a_dose_missed_after_its_reminders_can_still_be_ticked_off_and_is_asked_about_first(world):
    add(world, EVENING)
    for minute in (0, 15, 30, 45):
        at(world, 20, minute)
    at(world, 21, 0)
    said = {"doses": [{"pill": "evening pill", "did": "taken"}]}
    assert run(plain.log_asks(world.request(), said)), "a missed dose is never logged as taken unseen"
    asked = run(plain.log_card(world.request(), said, frozenset()))
    assert asked.lines == ("**Evening pill** · taken 9:00 pm",) and asked.risky and asked.confirm_label == "Log it"
    assert asked.warnings == ("Dose 1 was missed (due 8:00 pm). Log it as taken now?",)
    assert states(world)[("Evening pill", 1)] == MISSED, "nothing is logged by asking"
    assert run(plain.log_save(world.request(), asked.data)).startswith("✅ **Evening pill** · taken 9:00 pm")
    assert states(world)[("Evening pill", 1)] == DONE


def test_logging_a_missed_dose_shows_what_it_does_to_the_next_dose_s_time(world):
    add(world, PILL_A)  # 8:00 am, 11:30 am, 3:00 pm, at least 3 hours apart, not after 4:00 pm
    for minute in (0, 15, 30, 45):
        at(world, 8, minute)
    at(world, 9, 0)
    assert states(world)[("Pill A", 1)] == MISSED
    at(world, 9, 40)
    # Named by its number: with a dose still waiting, "took pill a" alone means that next dose, as before
    asked = run(plain.log_card(world.request(), {"doses": [{"pill": "pill a", "did": "taken", "dose": 1}]}, frozenset()))
    assert asked.lines == ("**Pill A** (dose 1 of 3) · taken 9:40 am", "-# next: dose 2 · `11:30 am` → `12:40 pm`"), "three hours after 9:40"
    assert asked.warnings == ("Dose 1 was missed (due 8:00 am). Log it as taken now?",)
    assert states(world)[("Pill A", 1)] == MISSED and states(world)[("Pill A", 2)] == PENDING
    # Taken early enough that the next dose keeps its time: nothing is said about it
    world2 = run(plain.log_card(world.request(), {"doses": [{"pill": "pill a", "did": "taken", "dose": 1, "at": "8:10 am"}]}, frozenset()))
    assert world2.lines == ("**Pill A** (dose 1 of 3) · taken 8:10 am",) and "was missed" in world2.warnings[0]
    # A dose that is simply waiting is not asked about, and "Log it anyway?" keeps its words for the rest
    run(plain.log_save(world.request(), asked.data))
    at(world, 12, 45)
    assert not run(plain.log_asks(world.request(), {"doses": [{"pill": "pill a", "did": "taken"}]})), "dose 2, waiting and past its gap"
    soon = run(plain.log_card(world.request(), {"doses": [{"pill": "pill a", "did": "taken", "at": "10:00 am"}]}, frozenset()))
    assert soon.warnings[0].endswith("Log it anyway?") and "missed" not in soon.warnings[0]


# --- the latest time, and the day ---------------------------------------------------------------------------
def test_nothing_is_sent_after_the_latest_time_and_a_prompt_still_up_then_goes(world):
    add(world, PILL_A)
    at(world, 8, 0)
    press(world, reminders.P_TAKEN)
    at(world, 11, 30)
    press(world, reminders.P_TAKEN)
    at(world, 15, 0)
    at(world, 15, 15)
    at(world, 15, 30)
    at(world, 15, 45)
    count = len(notices(world))
    assert notices(world)[-1] == "💊 Routine due · 3:00 pm · reminder 3 of 3"
    at(world, 16, 2)
    assert prompts(world) == [] and len(notices(world)) == count
    assert states(world)[("Pill A", 3)] == MISSED
    at(world, 18, 0)
    assert len(notices(world)) == count and remind_job() == []


def test_a_dose_that_can_no_longer_fit_gets_no_prompt(world):
    add(world, PILL_A)
    at(world, 8, 0)
    press(world, reminders.P_TAKEN)
    at(world, 13, 15)
    log(world, {"pill": "pill a", "dose": 2, "did": "taken", "at": "1:15 pm"})
    assert states(world)[("Pill A", 3)] == SKIPPED and prompts(world) == [] and remind_job() == []
    at(world, 15, 0)
    assert all("3:00 pm" not in line for line in notices(world))


def test_a_dose_with_no_time_gets_no_prompt_and_keeps_its_own_message(world):
    add(world, {"name": "Vitamin D"})
    run(checklist.post(world.owner.id))
    at(world, 12, 0)
    assert notices(world) == [] and remind_job() == []
    assert [m.kind for m in run(database.run(store.db_messages, world.owner.id, world.day))] == [store.CHECKLIST, store.DOSE]


def test_at_midnight_a_prompt_left_up_goes_and_tomorrow_s_first_is_booked(world):
    add(world, {"name": "Late pill", "times": ["11:50 pm"]})
    at(world, 23, 50)
    ((prompt_id, _, _),) = prompts(world)
    clock.advance_to(day.at(world.day + timedelta(days=1), time(0, 1)))
    run(scheduler.run_all_due())
    assert prompt_id in world.deleted and run(database.run(reminders.db_prompts)) == []
    assert remind_job() == [day.at(world.day + timedelta(days=1), time(23, 50))]


# --- the worked example --------------------------------------------------------------------------------------
def test_pill_a_through_a_day_taken_late(world):
    add(world, PILL_A)
    at(world, 8, 0)
    at(world, 8, 15)
    at(world, 8, 30)  # two reminders in, taken at 8:40
    at(world, 8, 40)
    press(world, reminders.P_TAKEN)
    assert remind_job() == [day.at(world.day, time(11, 40))], "dose 2: three hours after 8:40, later than its planned 11:30"
    at(world, 11, 40)
    assert prompts(world)[0][1][2] == "Due `11:40 am` · 3h after dose 1 at 8:40 am"
    press(world, reminders.P_AT, {"at": "11:40 am"})  # the form's time
    at(world, 15, 0)
    assert prompts(world)[0][1][:3] == ["💊 Routine due · 3:00 pm", "**Pill A** · dose 3 of 3", "Due `3:00 pm`"]
    press(world, reminders.P_TAKEN)
    assert [state for state in states(world).values()] == [DONE, DONE, DONE] and remind_job() == []
    assert notices(world) == [
        "💊 Routine due · 8:00 am", "💊 Routine due · 8:00 am · reminder 1 of 3", "💊 Routine due · 8:00 am · reminder 2 of 3",
        "💊 Routine due · 11:40 am", "💊 Routine due · 3:00 pm",
    ]


# --- a reply, a reset, a restart ---------------------------------------------------------------------------
def test_a_reply_to_a_prompt_means_that_dose_and_the_prompt_is_the_task_s_own_message(world):
    add(world, PILL_A, EVENING)
    at(world, 8, 5)
    ((prompt_id, _, _),) = prompts(world)
    assert run(pills_task.owns_message(prompt_id)) is True and run(pills_task.message_class(prompt_id)).name == "ALERT"
    said = log(world, {"pill": "@that", "did": "taken", "at": "8:02 am"}, replied_to=prompt_id)
    assert said.startswith("✅ **Pill A** (dose 1 of 3) · taken 8:02 am") and prompts(world) == []


def test_a_prompt_that_went_with_a_channel_reset_is_posted_again_and_the_card_says_so_without_a_name(world):
    add(world, EVENING)
    at(world, 20, 0)
    at(world, 20, 15)
    ((prompt_id, _, _),) = prompts(world)
    assert run(pills_task.reposted(HUB, {prompt_id})) == ["A pill reminder"]
    run(pills_task.channel_cleared(HUB, {prompt_id}))
    ((again, lines, _),) = prompts(world)
    assert again != prompt_id and lines[0] == "💊 Routine due · 8:00 pm · reminder 1 of 3", "the same reminder, not the next one"


def stop_and_start(world, monkeypatch):
    """The bot stops and starts again: memory is gone, the database stays, start-up runs in its order."""
    for held in (cards._actions, scheduler._handlers, day._listeners):
        held.clear()
    live.reset()
    restart._lines.clear()
    monkeypatch.setattr(restart, "_catching_up", True)
    _set_up()

    async def ready():
        await checklist.startup()
        await reminders.startup()
        await day.schedule_next()
        return await restart.catch_up()

    return run(ready())


def test_off_for_an_hour_over_a_dose_s_time_it_gets_one_prompt_at_start_not_one_a_reminder(world, monkeypatch):
    add(world, EVENING)
    at(world, 19, 0)
    clock.advance_to(day.at(world.day, time(20, 50)))  # the bot was off from 7 until now: nothing ran
    lines = stop_and_start(world, monkeypatch)
    assert notices(world) == ["💊 Routine due · 8:00 pm"], "one prompt, the first: it was never asked"
    assert len(prompts(world)) == 1 and states(world)[("Evening pill", 1)] == PENDING
    assert "1 pill reminder posted at start: it came due while the bot was off" in lines and not any("Evening" in line for line in lines)
    assert remind_job() == [day.at(world.day, time(21, 5))]


def test_a_restart_with_a_prompt_up_posts_no_second_one_and_its_buttons_still_work(world, monkeypatch):
    add(world, EVENING)
    at(world, 20, 0)
    clock.advance_to(day.at(world.day, time(20, 5)))
    assert stop_and_start(world, monkeypatch) == []
    assert len(notices(world)) == 1 and len(prompts(world)) == 1
    pressed, said = press(world, reminders.P_TAKEN)
    assert pressed.removed and states(world)[("Evening pill", 1)] == DONE


def test_off_while_reminders_were_due_the_next_one_in_its_turn_is_posted_once(world, monkeypatch):
    add(world, EVENING)
    at(world, 20, 0)
    clock.advance_to(day.at(world.day, time(20, 50)))  # off through the reminders of 8:15, 8:30 and 8:45
    stop_and_start(world, monkeypatch)
    assert notices(world) == ["💊 Routine due · 8:00 pm", "💊 Routine due · 8:00 pm · reminder 1 of 3"], "one, not three"
    assert len(prompts(world)) == 1


def test_off_past_the_latest_time_nothing_is_sent_at_start(world, monkeypatch):
    add(world, PILL_A)
    at(world, 7, 0)
    clock.advance_to(day.at(world.day, time(16, 30)))
    stop_and_start(world, monkeypatch)
    assert notices(world) == [] and prompts(world) == [] and states(world)[("Pill A", 1)] == MISSED


def test_a_job_run_twice_or_asked_again_and_again_never_makes_a_second_prompt(world):
    add(world, EVENING)
    at(world, 20, 0)
    for _ in range(3):
        run(reminders.run())
        run(reminders.remind_job(scheduler.Job(99, None, "pills", reminders.JOB, {}, clock.now())))
    assert len(notices(world)) == 1 and len(run(scheduler.pending_jobs("pills", reminders.JOB))) == 1


# --- no hub ---------------------------------------------------------------------------------------------------
def test_on_with_no_hub_to_post_in_it_is_said_once_in_bot_log_and_again_only_after_the_hub_came_back(world, monkeypatch):
    add(world, EVENING, {"name": "Later", "times": ["9:00 pm"]})
    monkeypatch.setattr(hub, "channel_id", lambda: None)
    at(world, 20, 0)
    at(world, 20, 15)
    at(world, 21, 0)
    run(reminders.run())
    assert notices(world) == [] and world.bot_log == [reminders.NO_HUB], "once, however many doses came due"
    assert states(world)[("Evening pill", 1)] == PENDING, "never missed for want of somewhere to ask"
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    run(reminders.run())
    assert len(notices(world)) == 2 and world.bot_log == [reminders.NO_HUB], "found again: both are asked, and nothing more is said"
    monkeypatch.setattr(hub, "channel_id", lambda: None)
    run(reminders.channel_cleared(HUB, {prompts(world)[0][0]}))
    assert world.bot_log == [reminders.NO_HUB, reminders.NO_HUB], "gone again later: said again, once"


def test_at_start_with_reminders_on_and_no_hub_it_is_said_at_once_and_never_when_they_are_off(world, monkeypatch):
    monkeypatch.setattr(hub, "channel_id", lambda: None)
    run(reminders.startup())
    run(reminders.startup())
    assert world.bot_log == [reminders.NO_HUB]
    world.bot_log.clear()
    monkeypatch.setattr(reminders, "_said_no_hub", False)
    monkeypatch.setattr(config, "REMINDERS_ENABLED", False)
    run(reminders.startup())
    assert world.bot_log == [], "off: nothing is sent, so nothing is wrong"


# --- too soon -------------------------------------------------------------------------------------------------
def test_a_dose_said_to_be_taken_before_the_gap_has_passed_is_asked_about_on_a_card(world):
    add(world, PILL_A)
    at(world, 8, 12)
    log(world, {"pill": "pill a", "did": "taken"})
    at(world, 10, 12)
    said = {"doses": [{"pill": "pill a", "did": "taken"}]}
    assert run(plain.log_asks(world.request(), said, frozenset())) is True
    card = run(plain.log_card(world.request(), said, frozenset()))
    assert card.lines == ("**Pill A** (dose 2 of 3) · taken 10:12 am",)
    assert card.warnings == ("That's 2h after dose 1, taken 8:12 am. The gap is at least 3h. Log it anyway?",) and card.confirm_label == "Log it"
    assert states(world)[("Pill A", 2)] == PENDING
    assert run(plain.log_save(world.request(), card.data)).startswith("✅ **Pill A** (dose 2 of 3) · taken 10:12 am")
    at(world, 11, 13)
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "pill a", "did": "taken", "dose": 3}]}, frozenset())) is True
    add(world, {"name": "No gap", "per_day": 2, "times": ["8:00 am", "8:00 pm"]})
    log(world, {"pill": "no gap", "did": "taken"})
    assert run(plain.log_asks(world.request(), {"doses": [{"pill": "no gap", "did": "taken"}]}, frozenset())) is False, "no gap: nothing is too soon"


# --- the decision, a piece at a time -------------------------------------------------------------------------
def test_what_to_do_about_a_dose_is_worked_out_from_what_is_kept_and_the_clock(world):
    add(world, EVENING)
    _, listed, _ = run(checklist.view(world.owner.id))
    (dose,) = listed
    due = day.at(world.day, time(20, 0))
    minutes = lambda count: timedelta(minutes=count)  # noqa: E731
    assert reminders.decide(dose, None, due - minutes(1)) == (reminders.WAIT, due, 0)
    assert reminders.decide(dose, None, due) == (reminders.POST, due + minutes(15), 0)
    up = reminders.Prompt(dose.occurrence.id, 1, world.day, HUB, 7, due, due, 0)
    assert reminders.decide(dose, up, due + minutes(14)) == (reminders.WAIT, due + minutes(15), 0)
    assert reminders.decide(dose, up, due + minutes(15)) == (reminders.POST, due + minutes(30), 1)
    assert reminders.decide(dose, up, due + minutes(200)) == (reminders.POST, due + minutes(215), 1), "however late: the next in its turn"
    last = reminders.Prompt(dose.occurrence.id, 1, world.day, HUB, 7, due, due + minutes(45), 3)
    assert reminders.decide(dose, last, due + minutes(59)) == (reminders.WAIT, due + minutes(60), 3)
    assert reminders.decide(dose, last, due + minutes(60)) == (reminders.MISS, None, 3)
    snoozed = reminders.Prompt(dose.occurrence.id, 1, world.day, HUB, 7, due, due, 1, due + minutes(20))
    assert reminders.decide(dose, snoozed, due + minutes(19)) == (reminders.WAIT, due + minutes(20), 1)
    assert reminders.decide(dose, snoozed, due + minutes(20)) == (reminders.POST, due + minutes(35), 1), "a fresh copy, the same reminder"
    gone = reminders.Prompt(dose.occurrence.id, 1, world.day, HUB, None, due, due, 2)
    assert reminders.decide(dose, gone, due + minutes(1)) == (reminders.POST, due + minutes(16), 2)
