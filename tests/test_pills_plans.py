"""Pills: the records, the previews, the list and what the buttons do
(tasks/pills/store.py and plans.py), against a temporary database."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, database, day, occurrences, scheduler
from core.errors import UserError
from tasks.pills import plans, rules, store
from tasks.pills.rules import ACTIVE, FIXED, INTERVAL, PAUSED, REMOVED, Plan, Request

HUB = 400


@pytest.fixture
def world(make_db, monkeypatch, owner):
    """A database with the pills tables, and stand-ins for the channel."""
    make_db({"pills": store.MIGRATIONS})
    monkeypatch.setattr(scheduler, "_handlers", dict(scheduler._handlers))
    scheduler.register_handler(plans.TASK, plans.JOB_DRAFT, plans.draft_expired)
    channel = SimpleNamespace(sent=[], deleted=[], edited=[], next_id=1000)

    async def delete(channel_id, message_id):
        channel.deleted.append(message_id)
        return True

    async def edit(channel_id, message_id, card):
        channel.edited.append((message_id, card.text))
        return True

    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "edit", edit)

    def ctx():
        said = []

        async def reply(text, view=None):
            channel.next_id += 1
            channel.sent.append((channel.next_id, text, view))
            return SimpleNamespace(id=channel.next_id)

        async def confirm(text):
            said.append(text)

        return SimpleNamespace(user=owner, channel_id=HUB, db=database, reply=reply, confirm=confirm, said=said)

    class Press:
        """Stands in for cards.Press: what a button's handler is given."""

        db = database

        def __init__(self, arg="", values=()):
            self.user, self.arg, self.values = owner, str(arg), tuple(values)
            self.cards, self.told = [], []

        async def update(self, card):
            cards.check(card)
            self.cards.append(card)

        async def say(self, text):
            self.told.append(text)

    return SimpleNamespace(ctx=ctx, Press=Press, channel=channel, owner=owner)


def run(coroutine):
    return asyncio.run(coroutine)


def labels(card):
    return [[button.label for button in row] if isinstance(row, tuple) else "dropdown" for row in card.rows]


def saved_pills():
    return run(store.pills(1))


def add(world, **said):
    """Ask for a pill and press Save on its preview."""
    run(plans.add_tool(world.ctx(), said))
    draft = run(store.drafts(1))[-1]
    press = world.Press(draft.id)
    run(plans.on_save(press))
    return saved_pills()[-1], press


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
def test_a_plan_is_saved_and_read_back_whole(world):
    plan = Plan(
        "Course A", dose="1 tablet", notes="with food", kind=INTERVAL, times=(time(8, 0),), per_day=3,
        gap_minutes=180, start=date(2026, 10, 10), end=date(2026, 10, 16),
    )
    saved = run(database.run(store.db_add, 1, plan))
    assert saved.plan == plan and saved.status == ACTIVE and saved.user_id == 1 and saved.ref == f"pl{saved.id}"
    assert run(store.pill(saved.id)) == saved


def test_every_change_to_a_pill_is_recorded_with_the_plan_before_and_after(world):
    def scenario(conn):
        pill = store.db_add(conn, 1, Plan("Evening pill", kind=FIXED, times=(time(20, 0),)))
        store.db_edit(conn, pill.id, Plan("Evening pill", kind=FIXED, times=(time(21, 0),)))
        store.db_set_status(conn, pill.id, PAUSED, date(2026, 10, 20))
        store.db_set_status(conn, pill.id, ACTIVE)
        store.db_set_status(conn, pill.id, REMOVED)
        return pill.id, store.db_changes(conn, pill.id)

    pill_id, changes = run(database.run(scenario))
    assert [kind for _, kind, _, _ in changes] == ["created", "edited", "paused", "resumed", "removed"]
    assert changes[0][2] is None and '"times": "[\\"20:00\\"]"' in changes[0][3]
    assert '20:00' in changes[1][2] and '21:00' in changes[1][3], "the edit keeps old and new"
    assert run(store.pill(pill_id)).status == REMOVED
    assert saved_pills() == [], "a removed pill is in no list, though its record stays"


def test_a_pause_keeps_its_end_date_and_resuming_clears_it(world):
    pill = run(database.run(store.db_add, 1, Plan("Iron")))
    paused = run(store.set_status(pill.id, PAUSED, date(2026, 10, 20)))
    assert (paused.status, paused.paused_until) == (PAUSED, date(2026, 10, 20))
    resumed = run(store.set_status(pill.id, ACTIVE))
    assert (resumed.status, resumed.paused_until) == (ACTIVE, None)


def test_a_draft_keeps_the_request_in_the_users_words(world):
    request = Request(name="Evening pill", times="8", notes="with food")
    draft = run(store.add_draft(1, None, request))
    assert draft.request == request and draft.ref == f"d{draft.id}" and draft.pill_id is None
    updated = run(store.update_draft(draft.id, message_id=55, channel_id=HUB, request=Request(name="Evening pill", times="20:00")))
    assert (updated.message_id, updated.channel_id, updated.request.times) == (55, HUB, "20:00")
    assert store.draft_id("d12") == 12 and store.draft_id("12") == 12 and store.draft_id("pl3") is None
    with pytest.raises(ValueError):
        run(store.update_draft(draft.id, user_id=2))
    assert run(store.discard_draft(draft.id)) and run(store.draft(draft.id)) is None


# ---------------------------------------------------------------------------
# Adding: nothing is saved until Save
# ---------------------------------------------------------------------------
def test_asking_for_a_pill_shows_a_preview_and_saves_nothing(world):
    result = run(plans.add_tool(world.ctx(), {"name": "Vitamin D"}))

    message_id, text, view = world.channel.sent[-1]
    assert text == "💊 **Vitamin D** · daily, untimed"
    assert view is not None
    assert saved_pills() == [], "must never be added before Save"
    draft = run(store.drafts(1))[0]
    assert (draft.message_id, draft.channel_id) == (message_id, HUB)
    assert "NOT saved" in result and draft.ref in result


def test_the_preview_has_save_and_edit(world):
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "20:00"}))
    draft = run(store.drafts(1))[0]
    card, plan = plans.preview_card(draft, None, date(2026, 10, 9))
    assert card.text == "💊 **Evening pill** · daily at `8:00 pm`"
    assert labels(card) == [["Save", "Edit"]]
    assert [button.arg for button in card.rows[0]] == [str(draft.id)] * 2
    assert plan.times == (time(20, 0),)


def test_save_adds_the_pill_and_the_preview_becomes_one_line(world):
    pill, press = add(world, name="Course A", per_day="3", min_gap="3h", notes="with food", start="tomorrow", days="7")
    assert pill.plan.kind == INTERVAL and pill.plan.end - pill.plan.start == timedelta(days=6)
    assert press.cards[-1].text.startswith("✅ Saved · 🗓️ **Course A** · 3× daily, ≥3h apart · *with food*")
    assert press.cards[-1].rows == (), "the buttons go once it is saved"
    assert run(store.drafts(1)) == []
    assert run(scheduler.pending_jobs(plans.TASK, plans.JOB_DRAFT)) == [], "nothing left to lapse"


def test_a_recurring_pill_is_saved_with_no_dates(world):
    pill, press = add(world, name="Vitamin D")
    assert (pill.plan.start, pill.plan.end) == (None, None)
    assert press.cards[-1].text == "✅ Saved · 💊 **Vitamin D** · daily, untimed"


def test_an_unclear_time_is_asked_with_a_button_for_each_reading(world):
    result = run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "8"}))
    assert "Do not answer for them" in result
    draft = run(store.drafts(1))[0]
    card, plan = plans.preview_card(draft, None, date(2026, 10, 9))
    assert plan is None
    assert card.text == "💊 **Evening pill** · at 8: **8am or 8pm?**"
    assert labels(card) == [["8:00 am", "8:00 pm"]]
    assert [button.arg for button in card.rows[0]] == [f"{draft.id}:0:0800", f"{draft.id}:0:2000"]

    # Save can't be pressed, and even if it were asked for nothing would be saved
    with pytest.raises(UserError):
        run(plans.on_save(world.Press(draft.id)))
    assert saved_pills() == []

    press = world.Press(f"{draft.id}:0:2000")
    run(plans.on_time(press))
    assert press.cards[-1].text == "💊 **Evening pill** · daily at `8:00 pm`"
    assert labels(press.cards[-1]) == [["Save", "Edit"]]
    assert saved_pills() == [], "answering the question is not saving"
    assert run(store.draft(draft.id)).request.times == "20:00"


def test_an_answer_to_a_question_that_has_moved_on_is_refused(world):
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "8"}))
    draft = run(store.drafts(1))[0]
    with pytest.raises(UserError, match="question has changed"):
        run(plans.on_time(world.Press(f"{draft.id}:0:0900")))  # 9 was never offered
    with pytest.raises(UserError, match="question has changed"):
        run(plans.on_time(world.Press(f"{draft.id}:1:2000")))  # nor was a second time


def test_what_cannot_be_a_plan_is_refused_before_anything_is_shown(world):
    with pytest.raises(UserError, match="How many times a day"):
        run(plans.add_tool(world.ctx(), {"name": "Course A", "min_gap": "3h"}))
    with pytest.raises(UserError, match="What is the pill called"):
        run(plans.add_tool(world.ctx(), {"times": "8pm"}))
    assert world.channel.sent == [] and run(store.drafts(1)) == []


def test_a_name_already_in_use_is_refused(world):
    add(world, name="Vitamin D")
    with pytest.raises(UserError, match="already a pill called"):
        run(plans.add_tool(world.ctx(), {"name": "vitamin d", "times": "8am"}))


def test_changing_an_open_preview_replaces_it(world):
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "8pm", "notes": "with food"}))
    first = run(store.drafts(1))[0]
    run(plans.add_tool(world.ctx(), {"draft": first.ref, "times": "9pm"}))

    drafts = run(store.drafts(1))
    assert len(drafts) == 1 and drafts[0].id == first.id, "the same draft, changed"
    assert drafts[0].request == Request(name="Evening pill", times="9pm", notes="with food")
    assert world.channel.deleted == [first.message_id], "the old preview is taken away"
    assert world.channel.sent[-1][1] == "💊 **Evening pill** · daily at `9:00 pm` · *with food*"
    assert len(run(scheduler.pending_jobs(plans.TASK, plans.JOB_DRAFT))) == 1, "one lapse booked, not two"


def test_asking_again_by_name_changes_the_open_preview_too(world):
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "8pm"}))
    run(plans.add_tool(world.ctx(), {"name": "evening pill", "times": "9pm"}))
    drafts = run(store.drafts(1))
    assert len(drafts) == 1 and drafts[0].request.times == "9pm"


def test_edit_on_a_preview_says_how_and_keeps_the_buttons(world):
    run(plans.add_tool(world.ctx(), {"name": "Vitamin D"}))
    draft = run(store.drafts(1))[0]
    press = world.Press(draft.id)
    run(plans.on_edit(press))
    assert press.cards[-1].text == f"💊 **Vitamin D** · daily, untimed\n{plans.EDIT_HINT}"
    assert labels(press.cards[-1]) == [["Save", "Edit"]]
    assert saved_pills() == []


def test_a_preview_nobody_saves_lapses(world, dev_clock):
    run(plans.add_tool(world.ctx(), {"name": "Vitamin D"}))
    draft = run(store.drafts(1))[0]

    async def later():
        dev_clock.advance(timedelta(minutes=plans.DRAFT_MINUTES + 1))
        return await scheduler.run_all_due()

    assert run(later()) == 1
    assert run(store.drafts(1)) == []
    assert world.channel.deleted == [draft.message_id], "an unanswered question goes"

    press = world.Press(draft.id)
    assert run(plans.on_save(press)) == "preview had lapsed"
    assert press.cards[-1].text == plans.LAPSED
    assert saved_pills() == []


def test_with_clean_up_off_a_lapsed_preview_stays_and_says_so(world, dev_clock, dev_off):
    from core import devmode

    devmode.enable()
    devmode.set_cleanup(False)
    run(plans.add_tool(world.ctx(), {"name": "Vitamin D"}))
    draft = run(store.drafts(1))[0]

    async def later():
        dev_clock.advance(timedelta(minutes=plans.DRAFT_MINUTES + 1))
        await scheduler.run_all_due()

    run(later())
    assert world.channel.deleted == []
    assert world.channel.edited == [(draft.message_id, plans.LAPSED)]


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
def test_an_edit_shows_old_and_new_and_changes_nothing_until_save(world):
    pill, _ = add(world, name="Evening pill", times="20:00")
    result = run(plans.edit_tool(world.ctx(), {"pill": "evening", "times": "9pm"}))

    text = world.channel.sent[-1][1]
    assert "Now: 💊 **Evening pill** · daily at `8:00 pm`" in text
    assert "New: 💊 **Evening pill** · daily at `9:00 pm`" in text
    assert "NOT saved" in result
    assert run(store.pill(pill.id)).plan.times == (time(20, 0),), "the plan is never changed silently"

    draft = run(store.drafts(1))[0]
    press = world.Press(draft.id)
    run(plans.on_save(press))
    assert run(store.pill(pill.id)).plan.times == (time(21, 0),)
    assert press.cards[-1].text == "✅ Updated · 💊 **Evening pill** · daily at `9:00 pm`"


def test_an_edit_that_changes_nothing_says_so_and_shows_no_preview(world):
    add(world, name="Evening pill", times="20:00")
    shown = len(world.channel.sent)
    result = run(plans.edit_tool(world.ctx(), {"pill": "Evening pill", "times": "8pm"}))
    assert result.startswith("Nothing to change")
    assert len(world.channel.sent) == shown and run(store.drafts(1)) == []


def test_an_edit_with_an_unclear_time_asks_first(world):
    pill, _ = add(world, name="Evening pill", times="20:00")
    run(plans.edit_tool(world.ctx(), {"pill": pill.ref, "times": "9"}))
    assert world.channel.sent[-1][1] == "💊 **Evening pill** · at 9: **9am or 9pm?**"
    draft = run(store.drafts(1))[0]
    press = world.Press(f"{draft.id}:0:2100")
    run(plans.on_time(press))
    assert "New: 💊 **Evening pill** · daily at `9:00 pm`" in press.cards[-1].text


def test_a_second_edit_of_the_same_pill_changes_the_open_preview(world):
    pill, _ = add(world, name="Evening pill", times="20:00")
    run(plans.edit_tool(world.ctx(), {"pill": pill.ref, "times": "9pm"}))
    run(plans.edit_tool(world.ctx(), {"pill": pill.ref, "notes": "with food"}))
    drafts = run(store.drafts(1))
    assert len(drafts) == 1
    assert "New: 💊 **Evening pill** · daily at `9:00 pm` · *with food*" in world.channel.sent[-1][1]


def test_saving_an_edit_of_a_pill_removed_meanwhile_changes_nothing(world):
    pill, _ = add(world, name="Evening pill", times="20:00")
    run(plans.edit_tool(world.ctx(), {"pill": pill.ref, "times": "9pm"}))
    draft = run(store.drafts(1))[0]
    run(store.set_status(pill.id, REMOVED))
    press = world.Press(draft.id)
    run(plans.on_save(press))
    assert "removed since" in press.cards[-1].text
    assert run(store.pill(pill.id)).plan.times == (time(20, 0),)


def test_a_pill_that_cannot_be_told_apart_is_asked_about(world):
    add(world, name="Vitamin D")
    add(world, name="Vitamin C")
    with pytest.raises(UserError, match="Which one"):
        run(plans.edit_tool(world.ctx(), {"pill": "vitamin", "dose": "2 tablets"}))


# ---------------------------------------------------------------------------
# Pausing and resuming
# ---------------------------------------------------------------------------
def test_pause_acts_at_once_with_or_without_an_end_date(world):
    pill, _ = add(world, name="Iron")
    today = day.today()
    ctx = world.ctx()
    run(plans.pause_tool(ctx, {"pill": "iron", "action": "pause", "until": "in 5 days"}))
    paused = run(store.pill(pill.id))
    assert (paused.status, paused.paused_until) == (PAUSED, today + timedelta(days=5))
    assert ctx.said[-1].startswith("⏸️ **Iron** paused until ")

    run(plans.pause_tool(ctx, {"pill": "iron", "action": "resume"}))
    assert run(store.pill(pill.id)).status == ACTIVE and ctx.said[-1] == "▶️ **Iron** resumed."

    run(plans.pause_tool(ctx, {"pill": "iron", "action": "resume"}))
    assert ctx.said[-1] == "▶️ **Iron** isn't paused.", "asking for what is already so is not a mistake"

    run(plans.pause_tool(ctx, {"pill": "iron", "action": "pause", "until": ""}))
    assert run(store.pill(pill.id)).paused_until is None
    assert ctx.said[-1] == "⏸️ **Iron** paused. Say when to resume it."


def test_a_pause_cannot_end_today_or_before(world):
    add(world, name="Iron")
    with pytest.raises(UserError, match="later day than today"):
        run(plans.pause_tool(world.ctx(), {"pill": "iron", "action": "pause", "until": "today"}))
    assert saved_pills()[0].status == ACTIVE


# ---------------------------------------------------------------------------
# The list and its buttons
# ---------------------------------------------------------------------------
def test_the_list_has_one_dropdown_however_many_pills(world):
    for name in ("Vitamin D", "Iron", "Zinc"):
        add(world, name=name)
    result = run(plans.show_list(world.ctx()))
    assert result == "listed 3 pill(s): Iron, Vitamin D, Zinc"
    text = world.channel.sent[-1][1]
    assert text.splitlines()[0] == "## 💊 Pills" and "💊 **Iron** · daily, untimed" in text

    card = plans.list_card(saved_pills(), day.today())
    assert labels(card) == ["dropdown"]
    assert [(option.label, option.description) for option in card.rows[0].options] == [
        ("Iron", "active"), ("Vitamin D", "active"), ("Zinc", "active"),
    ]


def test_an_empty_list_has_no_dropdown(world):
    run(plans.show_list(world.ctx()))
    assert world.channel.sent[-1][1].endswith(rules.EMPTY_LIST)
    assert world.channel.sent[-1][2] is None


def test_picking_a_pill_shows_it_with_edit_pause_remove(world):
    pill, _ = add(world, name="Iron")
    press = world.Press(values=[str(pill.id)])
    run(plans.on_pick(press))
    assert press.cards[-1].text == "💊 **Iron** · daily, untimed"
    assert labels(press.cards[-1]) == [["Edit", "Pause", "Remove", "Back"]]

    run(plans.on_pill_pause(press := world.Press(pill.id)))
    assert run(store.pill(pill.id)).status == PAUSED
    assert press.cards[-1].text == "⏸️ **Iron** · daily, untimed · paused"
    assert labels(press.cards[-1]) == [["Edit", "Resume", "Remove", "Back"]]

    run(plans.on_pill_resume(press := world.Press(pill.id)))
    assert run(store.pill(pill.id)).status == ACTIVE
    assert labels(press.cards[-1]) == [["Edit", "Pause", "Remove", "Back"]]

    run(plans.on_list(press := world.Press()))
    assert press.cards[-1].text.startswith("## 💊 Pills")

    run(plans.on_pill_edit(press := world.Press(pill.id)))
    assert "Tell me what to change about **Iron**" in press.told[-1] and press.cards == []


def test_an_ended_course_cannot_be_paused(world):
    pill = run(database.run(store.db_add, 1, Plan("Old course", start=date(2026, 1, 1), end=date(2026, 1, 7))))
    assert labels(plans.pill_card(pill, date(2026, 10, 9))) == [["Edit", "Remove", "Back"]]
    with pytest.raises(UserError, match="has ended"):
        run(plans.pause_tool(world.ctx(), {"pill": "old course", "action": "pause"}))


# ---------------------------------------------------------------------------
# Removing, and deleting for good
# ---------------------------------------------------------------------------
def test_remove_asks_first_then_hides_the_pill_and_keeps_its_history(world):
    pill, _ = add(world, name="Iron")
    occurrence = run(occurrences.ensure(1, plans.TASK, pill.id, date(2026, 10, 9)))

    result = run(plans.remove_tool(world.ctx(), {"pill": "iron", "history": "keep"}))
    assert "Not done yet" in result
    assert world.channel.sent[-1][1].startswith("Remove **Iron**?") and "Its history is kept" in world.channel.sent[-1][1]
    assert saved_pills() != [], "nothing happens before Confirm"

    card = plans.remove_card(pill, for_good=False)
    assert labels(card) == [["Remove", "Cancel"]] and card.rows[0][0].action == "remove_yes"

    run(plans.on_remove_yes(press := world.Press(pill.id)))
    assert press.cards[-1].text == "🗑️ Removed **Iron**. Its history is kept."
    assert saved_pills() == [] and "Iron" not in rules.list_text(saved_pills(), date(2026, 10, 9))
    assert run(store.pill(pill.id)).status == REMOVED
    assert run(occurrences.get(occurrence.id)) is not None, "its doses stay, for the record"


def test_the_list_button_asks_before_removing_too(world):
    pill, _ = add(world, name="Iron")
    run(plans.on_pill_remove(press := world.Press(pill.id)))
    assert press.cards[-1].text.startswith("Remove **Iron**?")
    assert saved_pills() != []


def test_cancel_leaves_the_pill_alone(world):
    pill, _ = add(world, name="Iron")
    run(plans.on_cancel(press := world.Press(pill.id)))
    assert press.cards[-1].text == "👌 Left **Iron** as it is."
    assert saved_pills()[0].status == ACTIVE


def test_delete_for_good_is_its_own_question_and_takes_the_history(world):
    pill, _ = add(world, name="Iron")
    occurrence = run(occurrences.ensure(1, plans.TASK, pill.id, date(2026, 10, 9)))
    other = run(occurrences.ensure(1, plans.TASK, pill.id + 1, date(2026, 10, 9)))

    run(plans.remove_tool(world.ctx(), {"pill": "iron", "history": "delete"}))
    assert "for good" in world.channel.sent[-1][1] and "can't be undone" in world.channel.sent[-1][1]
    card = plans.remove_card(pill, for_good=True)
    assert labels(card) == [["Delete for good", "Cancel"]] and card.rows[0][0].action == "delete_yes"
    assert run(store.pill(pill.id)) is not None

    result = run(plans.on_delete_yes(press := world.Press(pill.id)))
    assert press.cards[-1].text == "🗑️ Deleted **Iron** and its history."
    assert "1 recorded dose" in result
    assert run(store.pill(pill.id)) is None
    assert run(occurrences.get(occurrence.id)) is None
    assert run(occurrences.get(other.id)) is not None, "another pill's doses are untouched"
    assert run(database.run(store.db_changes, pill.id)) == []


def test_a_button_for_a_pill_that_has_gone_says_so(world):
    pill, _ = add(world, name="Iron")
    run(store.set_status(pill.id, REMOVED))
    for handler in (plans.on_pill_pause, plans.on_remove_yes, plans.on_delete_yes, plans.on_pill_edit):
        with pytest.raises(UserError, match="isn't there any more"):
            run(handler(world.Press(pill.id)))
    with pytest.raises(UserError):
        run(plans.on_pick(world.Press(values=["999"])))


def test_someone_elses_pill_or_preview_is_not_reachable(world, stranger):
    pill, _ = add(world, name="Iron")
    run(plans.add_tool(world.ctx(), {"name": "Zinc"}))
    draft = run(store.drafts(1))[0]

    theirs = world.Press(pill.id)
    theirs.user = stranger
    with pytest.raises(UserError):
        run(plans.on_remove_yes(theirs))
    theirs = world.Press(draft.id)
    theirs.user = stranger
    assert run(plans.on_save(theirs)) == "preview had lapsed"
    assert [p.plan.name for p in saved_pills()] == ["Iron"]


# ---------------------------------------------------------------------------
# For Claude, and for the registry
# ---------------------------------------------------------------------------
def test_the_live_state_lists_pills_and_open_previews(world):
    add(world, name="Iron")
    run(plans.add_tool(world.ctx(), {"name": "Zinc", "times": "8"}))
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "20:00"}))
    text = run(plans.live_state(world.ctx()))
    assert "- pl1: 💊 Iron · daily, untimed [active]" in text
    assert "Zinc: waiting for the user to say whether 8 is morning or evening" in text
    assert "new pill 💊 Evening pill · daily at 8:00 pm" in text


def test_an_open_preview_is_a_live_message(world):
    from core.lifecycle import MessageClass

    run(plans.add_tool(world.ctx(), {"name": "Vitamin D"}))
    draft = run(store.drafts(1))[0]
    assert run(plans.message_class(draft.message_id)) is MessageClass.LIVE
    assert run(plans.message_class(123456)) is None
    run(plans.on_save(world.Press(draft.id)))
    assert run(plans.message_class(draft.message_id)) is None, "saved: one line, kept like any other"


def test_every_button_on_every_card_has_an_action(world):
    plans.register_actions()
    pill, _ = add(world, name="Iron")
    run(plans.add_tool(world.ctx(), {"name": "Zinc", "times": "8"}))
    question = run(store.drafts(1))[0]
    run(plans.add_tool(world.ctx(), {"name": "Evening pill", "times": "20:00"}))
    preview = run(store.drafts(1))[1]
    today = day.today()
    all_cards = [
        plans.preview_card(question, None, today)[0],
        plans.preview_card(preview, None, today)[0],
        plans.list_card(saved_pills(), today),
        plans.pill_card(pill, today),
        plans.remove_card(pill, False),
        plans.remove_card(pill, True),
    ]
    for card in all_cards:
        cards.check(card)
        for row in card.rows:
            for component in (row if isinstance(row, tuple) else (row,)):
                assert (component.task, component.action) in cards._actions, component


def test_the_task_registers_its_word_tools_and_job():
    from tasks import registry

    registry.load()
    assert registry.find("pills")[0] == "task"
    assert registry._keyword_router.match("pill").entry[1].name == "pills"
    task = next(task for task in registry.loaded_tasks() if task.name == "pills")
    assert [tool.name for tool in task.tools()] == ["pill_add", "pill_edit", "pill_pause", "pill_remove"]
    assert ("pills", "draft_expire") in scheduler._handlers
    assert registry._keyword_router.match("pills").entry[1].channels == ["inbox", "hub"]


# ---------------------------------------------------------------------------
# All the way through: a tool call from Claude, down the registry's own path
# ---------------------------------------------------------------------------
EMPTY = {name: "" for name in ("name", "dose", "notes", "times", "per_day", "min_gap", "start", "end", "days", "draft")}


def test_claudes_call_shows_the_preview_and_ends_the_turn_without_another_word(world, monkeypatch):
    from core import live, llm
    from core.context import Context
    from tasks import registry, toolcalls

    registry.load()
    monkeypatch.setattr(llm, "_histories", {})
    sent = []

    class Channel:
        id = 100

        async def send(self, text, **options):
            sent.append((text, options.get("view")))
            return SimpleNamespace(id=7000 + len(sent))

    async def scenario():
        ctx = Context(world.owner, 100, 99, "add evening pill at 20:00", Channel(), _message=None)
        turn = await toolcalls.prepare(ctx)
        added = await toolcalls.execute(turn, "pill_add", {**EMPTY, "name": "Evening pill", "times": "20:00", "propose": False})
        after_add = toolcalls.closing(turn)
        pill = (await database.run(store.db_add, 1, Plan("Iron"))).ref
        paused = await toolcalls.execute(turn, "pill_pause", {"pill": pill, "action": "pause", "until": "", "propose": False})
        after_pause = toolcalls.closing(turn)
        wrong = await toolcalls.execute(turn, "pill_edit", {**{k: v for k, v in EMPTY.items() if k != "draft"}, "pill": "zinc", "propose": False})
        after_wrong = toolcalls.closing(turn)
        await live.settle()  # the log cards that follow in the background
        return added, after_add, paused, after_pause, wrong, after_wrong

    added, after_add, paused, after_pause, wrong, after_wrong = run(scenario())

    # The preview is the answer: Claude is not asked for a closing line, and remembers it is unsaved
    assert added[1] is False and "NOT saved" in added[0]
    assert sent[0][0] == "💊 **Evening pill** · daily at `8:00 pm`" and sent[0][1] is not None
    assert after_add is not None and after_add.say == "" and "NOT saved" in after_add.remember
    assert [p.plan.name for p in saved_pills()] == ["Iron"], "the previewed pill is still not there"

    # A pause posts nothing itself: what it confirmed is the reply
    assert paused == ("⏸️ **Iron** paused. Say when to resume it.", False)
    assert after_pause.say == "⏸️ **Iron** paused. Say when to resume it."
    assert len(sent) == 1

    # A problem goes back to Claude to put into words
    assert wrong[1] is True and "don't have a pill called “zinc”" in wrong[0]
    assert after_wrong is None
