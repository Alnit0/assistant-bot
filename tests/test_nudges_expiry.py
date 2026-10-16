"""Expiries and renewals, part of reminders (tasks/nudges/expiry.py): a card first, nudges 30, 7 and 1 day before
(quiet until the last, which is posted with Done and Snooze), renewed in words or by Done with undo, what is
expiring soon, and one gone by in Needs a look. Made-up names only."""
import asyncio
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from core import cards, clock, config, database, hub, live, notify, recurrence, scheduler
from core import day as days
from core.actions import Request
from core.errors import UserError
from tasks.nudges import expiry, store

HUB = 400


def run(coroutine):
    async def settled():
        result = await coroutine
        await live.settle()
        return result

    return asyncio.run(settled())


@pytest.fixture
def world(make_db, monkeypatch, owner, dev_clock):
    make_db({"nudges": store.MIGRATIONS})
    seen = SimpleNamespace(owner=owner, sent=[], edited=[], deleted=[], next_id=8000, jobs=[])

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

    async def add_job(task, kind, due, payload, user_id=None, key=""):
        seen.jobs.append((kind, due, payload, key))

    monkeypatch.setattr(cards, "send", send)
    monkeypatch.setattr(cards, "edit", edit)
    monkeypatch.setattr(cards, "delete", delete)
    monkeypatch.setattr(cards, "_actions", {})
    monkeypatch.setattr(hub, "channel_id", lambda: HUB)
    monkeypatch.setattr(scheduler, "add_job", add_job)
    monkeypatch.setattr(expiry, "changed", lambda user_id: None)
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    expiry.register()
    live.reset()
    seen.today = days.today() + timedelta(days=1)  # the dev clock only moves forward
    clock.advance_to(days.at(seen.today, time(10, 0)))
    seen.request = lambda text="said": Request(owner, HUB, text)
    return seen


def add(world, data, text="said"):
    proposal = run(expiry.add_card(world.request(text), data, frozenset()))
    run(expiry.add_save(world.request(text), proposal.data))
    assert run(expiry.add_check(world.request(text), proposal.data)) == ""
    return proposal


def kept(world):
    return run(expiry.every(world.owner.id))


def made_up(world, name, left, months=12, before=expiry.BEFORE):
    """One kept straight in the store, `left` days from today."""
    due = world.today + timedelta(days=left)
    run(database.run(expiry.db_add, expiry.Expiry(0, world.owner.id, name, due, due.day, months, before), clock.now()))
    return next(each for each in kept(world) if each.name == name)


# --- the dates: the repeat engine's months ------------------------------------------------------------------------------
def test_a_month_on_keeps_its_date_or_the_month_s_last_day():
    assert recurrence.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert recurrence.add_months(date(2026, 2, 28), 1, anchor=31) == date(2026, 3, 31), "back to the 31st after a short month"
    assert recurrence.add_months(date(2027, 2, 28), 12, anchor=29) == date(2028, 2, 29), "29 Feb yearly: 29 Feb again in a leap year"
    assert recurrence.add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert recurrence.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28) and recurrence.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert [recurrence.cycle_months(word, 6) for word in recurrence.CYCLES] == [12, 1, 6, None]
    assert [recurrence.cycle_text(each) for each in (12, 1, 6, 24, None)] == ["yearly", "monthly", "every 6 months", "every 2 years", "once"]


def test_renewed_rolls_on_one_cycle_from_its_own_date():
    leap = expiry.Expiry(1, 1, "Made-up licence", date(2028, 2, 29), 29, 12)
    once = expiry.rolled(leap)
    assert once.due == date(2029, 2, 28) and expiry.rolled(expiry.rolled(once)).due == date(2031, 2, 28)
    assert expiry.rolled(expiry.rolled(expiry.rolled(once))).due == date(2032, 2, 29), "a leap year again"
    month_end = expiry.Expiry(2, 1, "Made-up plan", date(2027, 1, 31), 31, 1)
    assert [expiry.rolled(month_end).due, expiry.rolled(expiry.rolled(month_end)).due] == [date(2027, 2, 28), date(2027, 3, 31)]
    assert expiry.rolled(expiry.Expiry(3, 1, "Made-up card", date(2031, 6, 1), 1, None)).done_at == "renewed", "no cycle: done"


def test_a_date_as_said_and_a_month_alone_is_its_first():
    today = date(2026, 10, 16)
    assert expiry.read_date("June 2031", today) == (date(2031, 6, 1), True)
    assert expiry.read_date("3 March", today) == (date(2027, 3, 3), False), "the next one to come"
    assert expiry.read_date("14 Nov", today) == (date(2026, 11, 14), False)
    with pytest.raises(UserError, match="not a date I can read"):
        expiry.read_date("sometime soon", today)


# --- a new one, a card first --------------------------------------------------------------------------------------------
def test_a_new_expiry_is_a_card_with_its_name_date_cycle_and_nudges(world):
    proposal = add(world, {"name": "Kiwa domain", "date": "3 March", "cycle": "yearly"}, "Kiwa domain expires 3 March, yearly")
    assert proposal.lines[0].startswith("**Kiwa domain** · ") and "3 Mar" in proposal.lines[0]
    assert proposal.lines[1] == "Yearly · told 30 days, 7 days, 1 day before" and proposal.kind == "new"
    passport = run(expiry.add_card(world.request(), {"name": "passport", "date": "June 2031", "cycle": "none"}, frozenset()))
    assert passport.lines[0] == "**Passport** · Sun 1 Jun 2031" and passport.lines[1].startswith("Once") and "Only the month was said" in passport.warnings[0]
    sixty = run(expiry.add_card(world.request(), {"name": "rego", "date": "14 Nov", "cycle": "yearly", "before": [60]}, frozenset()))
    assert sixty.lines[1] == "Yearly · told 60 days before"


def test_remind_me_60_days_before_changes_its_nudges_on_a_card(world):
    made_up(world, "Made-up passport", 400, months=None)
    proposal = run(expiry.change_card(world.request(), {"expiry": "passport", "before": [60]}, frozenset()))
    assert proposal.lines[1] == "~~30 days, 7 days, 1 day before~~ → **60 days before**"
    run(expiry.change_save(world.request(), proposal.data))
    assert kept(world)[0].before == (60,)


# --- told: quiet, then posted the day before -----------------------------------------------------------------------------
def test_quiet_in_the_overview_until_the_last_nudge(world):
    made_up(world, "Made-up domain", 7)
    made_up(world, "Made-up rego", 45)
    assert expiry.overview(kept(world), world.today) == "🔁 Made-up domain in 7 days", "the rego is not yet 30 days off"
    assert expiry.overview(kept(world), world.today + timedelta(days=6)) == "", "the day before: posted, not quiet"


def test_the_day_before_it_is_posted_once_neutral_first_with_done_and_snooze(world):
    found = made_up(world, "Made-up domain", 1)
    job = SimpleNamespace(payload={}, id=1, task="nudges", kind=expiry.CHECK_JOB, user_id=None)
    notes = []
    original = scheduler.note
    scheduler.note = lambda job, text: notes.append(text)
    try:
        run(expiry.check_job(job))
        run(expiry.check_job(job))
    finally:
        scheduler.note = original
    assert notes == ["1 renewal nudge posted", "nothing due tomorrow"], "once a due day"
    (first,) = world.sent
    assert first.card.text == f"🔁 Renewal due · {expiry.short(found.due, world.today)}", "what a phone shows names nothing"
    assert "Made-up domain" not in first.card.text and notify.KINDS[expiry.KIND].where == notify.DISCORD and not notify.KINDS[expiry.KIND].through
    _, drawn = world.edited[0]
    assert "**Made-up domain** · tomorrow" in drawn.text and [each.label for each in drawn.rows[0]] == ["Done", "Snooze"]


def test_snooze_posts_it_again_later_unless_renewed_by_then(world):
    found = made_up(world, "Made-up domain", 1)
    press = SimpleNamespace(arg=f"{found.id}:60", user=world.owner, db=database, removed=[])

    async def remove():
        press.removed.append(True)

    press.remove = remove
    assert run(expiry.on_snooze_for(press)).startswith("💤 again at ") and press.removed
    (kind, due, payload, key) = world.jobs[0]
    assert kind == expiry.AGAIN_JOB and payload == {"id": found.id, "due": found.due.isoformat()}


# --- renewed ---------------------------------------------------------------------------------------------------------------
def test_renewed_in_words_rolls_it_on_says_the_date_and_undo_puts_it_back(world):
    found = made_up(world, "Kiwa domain", 1)
    shown = run(expiry.renewed_said(world.request("renewed the Kiwa domain"), {"expiry": "Kiwa domain"}, frozenset()))
    after = kept(world)[0]
    assert after.due == recurrence.add_months(found.due, 12, found.anchor)
    assert shown.summary == f"✅ **Kiwa domain** · renewed: next {expiry.short(after.due, world.today)} {after.due.year}"
    assert [each.label for each in world.sent[-1].card.rows[0]] == ["Undo"]
    assert run(expiry.undo_said(world.request("undo that"), {}, frozenset())).startswith("↩️ **Kiwa domain** · back to ")
    assert kept(world)[0].due == found.due


def test_done_on_the_post_renews_and_one_with_no_cycle_leaves_the_list(world):
    found = made_up(world, "Made-up passport", 1, months=None)
    press = SimpleNamespace(arg=str(found.id), user=world.owner, db=database)
    assert run(expiry.on_renewed(press)) == "✅ **Made-up passport** · renewed: done, off the list"
    assert kept(world) == []


# --- expiring soon, and gone by --------------------------------------------------------------------------------------------
def test_what_is_expiring_soon_lists_the_next_90_days_soonest_first(world):
    made_up(world, "Made-up rego", 29)
    made_up(world, "Made-up domain", 3)
    made_up(world, "Made-up passport", 300, months=None)
    shown = run(expiry.soon_said(world.request("what's expiring soon?"), {}, frozenset()))
    lines = shown.summary.splitlines()
    assert lines[0] == "## 🔁 Expiring soon · 2" and lines[1].startswith("**Made-up domain**") and lines[2].startswith("**Made-up rego**")
    assert world.sent[-1].card.layout, "drawn in round 5 style: one box"


def test_gone_by_and_not_renewed_is_one_line_in_needs_a_look_that_never_pings(world):
    made_up(world, "Made-up domain", -2)
    (item,) = expiry.expired_items(kept(world), world.today)
    assert not item.ping and item.short == ("renewal overdue",) and "Made-up domain" not in " ".join(item.short)
    assert item.what.startswith("Made-up domain · expired ")


def test_which_is_by_code_and_a_name_that_fits_two_is_asked(world):
    made_up(world, "Made-up domain one", 10)
    made_up(world, "Made-up domain two", 20)
    with pytest.raises(UserError, match="could be"):
        run(expiry.which(world.request(), "domain"))
    assert run(expiry.which(world.request(), "domain two")).name == "Made-up domain two"


def test_the_briefing_s_overview_line_carries_a_renewal_even_with_no_reminder_today(world):
    import tasks.nudges as nudges_task

    made_up(world, "Made-up domain", 7)
    said = run(nudges_task.summary(world.owner.id, world.today))
    assert said is not None and said.overview == "🔁 Made-up domain in 7 days"
