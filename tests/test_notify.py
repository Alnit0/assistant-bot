"""The notify service (core/notify.py): where each kind of alert goes, the push to ntfy behind NOTIFY_NTFY, quiet
hours behind QUIET_HOURS_ENABLED, and the briefing on the one ranking (tasks/briefing)."""
import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone

import pytest

from core import attention, cards, clock, config, database, day, design, devmode, notify, scheduler
from core.attention import PROBLEM, TIMED, USEFUL, Item
from core.cards import Card
from core.summaries import Section
from core.actions import Summary
from interfaces.discord import surface as discord_surface
from tasks import briefing
from tasks.briefing import rules
from tasks.pills import reminders
from tests.test_pills_reminders import EVENING, HUB, NOTICE, PILL_A, add, at, notices, press, run, world  # noqa: F401

TOPIC = "a-made-up-topic-for-tests"
LATE = {"name": "Late pill", "times": ["10:30 pm"]}
NZ = config.TIMEZONE


@pytest.fixture(autouse=True)
def as_with_nothing_set(monkeypatch):
    """The switches as they are with nothing in .env, whatever this PC's own .env says."""
    monkeypatch.setattr(config, "QUIET_HOURS_ENABLED", False)
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    monkeypatch.setattr(config, "NTFY_BOT_TOPIC", "")


@pytest.fixture
def phone(monkeypatch):
    """ntfy switched on for live, with a made-up topic, and every push caught."""
    pushed = []

    def deliver(request):
        pushed.append(request)

    monkeypatch.setattr(config, "NOTIFY_NTFY", True)
    monkeypatch.setattr(config, "NTFY_BOT_TOPIC", TOPIC)
    monkeypatch.setattr(config, "DEV_DATABASE", False)
    monkeypatch.setattr(notify, "_deliver", deliver)
    monkeypatch.setattr(cards, "link", lambda channel_id, message_id: f"https://discord.com/channels/7/{channel_id}/{message_id}")
    return pushed


def said(request) -> tuple[str, str, str, str]:
    """A caught push: its title, its body, where a tap goes, how loud."""
    import base64

    title = base64.b64decode(request.get_header("Title").removeprefix("=?UTF-8?B?").removesuffix("?=")).decode("utf-8")
    return title, request.data.decode("utf-8"), request.get_header("Click") or "", request.get_header("Priority")


def post(name="pills.reminder", line="💊 Routine due · 8:00 am", item=None, **more):
    async def go():
        sent = await notify.post(name, HUB, Card(line), user_id=1, item=item or Item("a dose is due", TIMED, when=clock.now()), **more)
        await notify.settle()
        return sent

    return asyncio.run(go())


# --- where each kind goes ---------------------------------------------------------------------------------------------
def test_every_kind_is_in_one_table_and_says_where_it_goes():
    assert notify.KINDS["pills.reminder"].where == notify.BOTH, "pill reminders are the first user: Discord and the phone"
    assert all(each.where in notify.WHERE and each.title for each in notify.KINDS.values())
    assert notify.kind("nobody.knows") == notify.UNLISTED and notify.UNLISTED.where == notify.DISCORD, "a kind that is not listed is Discord only"


def test_nothing_is_pushed_unless_switched_on_with_a_topic_and_never_by_the_dev_bot(monkeypatch, phone):
    assert config.flag(None, False) is False, "NOTIFY_NTFY and QUIET_HOURS_ENABLED are off unless .env says otherwise"
    assert notify.ready() and notify.pushes("pills.reminder") and not notify.pushes("nobody.knows")
    monkeypatch.setattr(config, "NTFY_BOT_TOPIC", "")
    assert not notify.ready(), "no topic: nothing can be pushed"
    monkeypatch.setattr(config, "NTFY_BOT_TOPIC", TOPIC)
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    assert not notify.ready(), "the switch is off"
    monkeypatch.setattr(config, "NOTIFY_NTFY", True)
    monkeypatch.setattr(config, "DEV_DATABASE", True)
    assert not notify.ready(), "the dev bot never reaches my phone: a self-test pushes nothing"


def test_off_an_alert_is_posted_in_discord_as_it_always_was(world):
    message_id = post()
    (sent,) = world.sent
    assert (sent.id, sent.channel, sent.card.text, sent.silent) == (message_id, HUB, "💊 Routine due · 8:00 am", False), "it notifies in Discord"


def test_both_notifies_in_discord_and_pushes_a_neutral_line_that_opens_the_message(world, phone):
    message_id = post()
    assert world.sent[-1].silent is False
    (request,) = phone
    assert request.full_url == f"https://ntfy.sh/{TOPIC}", "the bot's own topic"
    assert said(request) == ("Reminder", "💊 Routine due · 8:00 am", f"https://discord.com/channels/7/{HUB}/{message_id}", "4"), "tapping opens the Discord message"


def test_ntfy_only_posts_in_discord_without_a_sound_and_falls_back_to_discord_when_it_can_not_push(world, phone, monkeypatch):
    monkeypatch.setitem(notify.KINDS, "pills.reminder", notify.Kind("Reminder", notify.NTFY))
    post()
    assert world.sent[-1].silent is True and len(phone) == 1, "the phone is told by ntfy alone: the message is there for the tap"
    monkeypatch.setattr(config, "NOTIFY_NTFY", False)
    post()
    assert world.sent[-1].silent is False and len(phone) == 1, "with ntfy off the alert is never lost to a setting: Discord notifies"


def test_discord_only_never_pushes(world, phone, monkeypatch):
    monkeypatch.setitem(notify.KINDS, "pills.reminder", notify.Kind("Reminder", notify.DISCORD))
    post()
    assert world.sent[-1].silent is False and phone == []


def test_a_problem_is_louder_than_something_due(world, phone):
    post(item=Item("backup failed", PROBLEM), line="⚠️ Something needs a look")
    post(item=Item("something useful", USEFUL), line="☀️ Morning briefing")
    assert [said(each)[3] for each in phone] == ["5", "3"]


def test_a_line_that_names_one_of_my_things_is_never_pushed(world, phone, caplog):
    with caplog.at_level(logging.ERROR, logger="assistant"):
        post(line="💊 Pill A is due", private=("Pill A", "Evening pill"))
    assert said(phone[-1])[:2] == ("Reminder", notify.NOT_SAID), "the title goes by itself"
    assert "names one of the user's things" in caplog.text and "Pill A" not in caplog.text
    assert notify.neutral("💊 Routine due · 8:00 am", ("Pill A",)) and not notify.neutral("take pill a now", ("Pill A",))


def test_a_push_that_fails_is_logged_without_the_topic_and_raises_nothing(world, phone, monkeypatch, caplog):
    def broken(request):
        raise OSError(f"could not reach {request.full_url}")

    monkeypatch.setattr(notify, "_deliver", broken)
    with caplog.at_level(logging.DEBUG, logger="assistant"):
        assert post() is not None, "the Discord message is up all the same"
    assert "could not be pushed to ntfy (OSError)" in caplog.text and TOPIC not in caplog.text, "the topic is a secret: never in a log"


def test_the_link_is_the_one_discord_opens(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(discord_surface, "_channel", lambda channel_id: SimpleNamespace(guild=SimpleNamespace(id=7)) if channel_id == 400 else None)
    assert cards.link(400, 9001) == "https://discord.com/channels/7/400/9001"
    assert cards.link(123, 9001) == "" and cards.link(400, None) == "", "a channel that can't be found has no link"


# --- quiet hours ------------------------------------------------------------------------------------------------------
def moment(hour, minute=0, on=date(2026, 10, 14)):
    return datetime.combine(on, time(hour, minute), tzinfo=NZ).astimezone(timezone.utc)


def test_quiet_hours_run_over_midnight(monkeypatch):
    monkeypatch.setattr(config, "QUIET_HOURS", (time(22, 0), time(6, 0)))
    assert [notify.quiet(moment(*each)) for each in ((21, 59), (22, 0), (23, 30), (0, 0), (5, 59), (6, 0), (12, 0))] == [False, True, True, True, True, False, False]
    monkeypatch.setattr(config, "QUIET_HOURS", (time(1, 0), time(5, 0)))
    assert [notify.quiet(moment(*each)) for each in ((0, 59), (1, 0), (4, 59), (5, 0), (23, 0))] == [False, True, True, False, False]
    monkeypatch.setattr(config, "QUIET_HOURS", (time(6, 0), time(6, 0)))
    assert not notify.quiet(moment(6, 0)), "from and to the same: no quiet hours"


NOTE = "test.note"  # a kind that quiet hours hold, as every kind but a pill reminder is


@pytest.fixture
def night(monkeypatch):
    """Quiet hours in force, 10:00 pm to 6:00 am, and a kind of alert they hold."""
    monkeypatch.setattr(config, "QUIET_HOURS", (time(22, 0), time(6, 0)))
    monkeypatch.setattr(config, "QUIET_HOURS_ENABLED", True)
    monkeypatch.setitem(notify.KINDS, NOTE, notify.Kind("Note", notify.BOTH))


def test_in_quiet_hours_everything_is_held_but_a_kind_that_gets_through_and_only_with_the_switch_on(monkeypatch, night):
    late = moment(23, 0)
    assert notify.KINDS["pills.reminder"].through, "a pill reminder always gets through, with its sound"
    assert notify.holds(NOTE, late) and not notify.holds("pills.reminder", late)
    assert notify.holds("nobody.knows", late), "a kind that is not listed is held like any other"
    assert not notify.holds(NOTE, moment(12, 0)), "by day nothing is held"
    monkeypatch.setattr(devmode, "quiet_hours_ignored", lambda: True)
    assert not notify.holds(NOTE, late), "dev mode can say to ignore quiet hours"
    monkeypatch.setattr(devmode, "quiet_hours_ignored", lambda: False)
    monkeypatch.setattr(config, "QUIET_HOURS_ENABLED", False)
    assert not notify.holds(NOTE, late), "off, nothing is held: everything notifies as it always did"


def test_what_is_held_is_posted_without_a_sound_never_pushed_and_kept_for_the_morning(world, phone, night):
    clock.advance_to(day.at(world.day, time(22, 30)))
    post(NOTE, line="📅 Event · 10:30 pm", key="event-1")
    assert world.sent[-1].silent is True and phone == [], "nothing sounds and nothing is pushed"
    clock.advance_to(day.at(world.day, time(22, 45)))
    post(NOTE, line="📅 Event · 10:30 pm · again", key="event-1")
    post(NOTE, line="⚠️ Something needs a look", item=Item("backup failed", PROBLEM), key="backup")
    assert world.sent[-1].silent is True and phone == [], "something wrong is held too: level 1 respects quiet hours"
    post(line="💊 Routine due · 10:45 pm", key="dose-1")
    assert world.sent[-1].silent is False and len(phone) == 1, "a pill reminder gets through, with its sound and its push"
    morning = world.day + timedelta(days=1)
    first, second = run(notify.held_overnight(world.owner.id, morning))
    assert (first.kind, first.line, first.times) == (NOTE, "📅 Event · 10:30 pm", 2), "asked for again for the same thing, it is one line"
    assert second.line == "⚠️ Something needs a look"
    assert run(notify.held_overnight(world.owner.id, world.day)) == [], "the night before held nothing"
    assert run(notify.held_overnight(2, morning)) == [], "only mine"


def test_what_is_dealt_with_is_no_longer_listed(world, phone, night):
    told = []
    attention.on_change(lambda: told.append(1))
    clock.advance_to(day.at(world.day, time(23, 0)))
    post(NOTE, key="a")
    post(NOTE, key="b")
    morning = world.day + timedelta(days=1)
    assert run(notify.dealt_with(world.owner.id, NOTE, "a")) is True and told == [1], "whoever lists them is told to look again"
    assert [each.times for each in run(notify.held_overnight(world.owner.id, morning))] == [1]
    assert run(notify.dealt_with(world.owner.id, NOTE, "a")) is False and told == [1], "nothing was held under that: nothing to say"


def test_overnight_is_the_quiet_hours_that_ended_that_morning(monkeypatch):
    monkeypatch.setattr(config, "QUIET_HOURS", (time(22, 0), time(6, 0)))
    since, until = notify.window(date(2026, 10, 14))
    assert (since, until) == (moment(22, 0, date(2026, 10, 13)), moment(6, 0)), "from last night at 10:00 pm to 6:00 am"
    monkeypatch.setattr(config, "QUIET_HOURS", (time(1, 0), time(5, 0)))
    assert notify.window(date(2026, 10, 14)) == (moment(1, 0), moment(5, 0))


def test_what_was_held_is_forgotten_after_a_week(world, phone, night):
    clock.advance_to(day.at(world.day, time(23, 0)))
    post(NOTE, key="old")
    clock.advance_to(day.at(world.day + timedelta(days=8), time(23, 0)))
    post(NOTE, key="new")

    def keys(conn):
        return [row[0] for row in conn.execute("SELECT key FROM held_alerts")]

    assert run(database.run(keys)) == ["new"]


# --- pill reminders, the first user -----------------------------------------------------------------------------------
def test_a_pill_reminder_reaches_the_phone_as_the_neutral_line_and_never_names_the_pill(world, phone):
    add(world, PILL_A)
    at(world, 8, 0)
    run(notify.settle())
    assert notices(world) == ["💊 Routine due · 8:00 am"]
    (request,) = phone
    title, body, click, priority = said(request)
    assert (title, body, priority) == ("Reminder", "💊 Routine due · 8:00 am", "4") and "Pill A" not in title + body
    assert click.endswith(f"/{HUB}/{world.sent[-1].id}"), "the tap opens the reminder itself"


def test_a_pill_reminder_in_quiet_hours_gets_through_with_its_sound(world, phone, night):
    add(world, LATE)
    at(world, 22, 30)
    run(notify.settle())
    assert [each.silent for each in world.sent if each.card.text.startswith(NOTICE)] == [False], "it sounds in Discord"
    assert [said(each)[1] for each in phone] == ["💊 Routine due · 10:30 pm"], "and on the phone"
    assert run(notify.held_overnight(world.owner.id, world.day + timedelta(days=1))) == [], "nothing of it is held"


def test_the_briefing_lists_what_was_held_overnight_until_it_is_dealt_with(world, phone, night):
    add(world, PILL_A)
    clock.advance_to(day.at(world.day, time(22, 30)))
    post(NOTE, line="📅 Event · 10:30 pm", key="event-1")
    post(NOTE, line="📅 Event · 10:30 pm", key="event-1")
    clock.advance_to(day.at(world.day + timedelta(days=1), time(6, 0)))
    run(scheduler.run_all_due())  # the day turns over: the new day's doses are there
    lines = run(briefing.card_for(world.owner.id)).text.splitlines()
    assert rules.HELD in lines and "📅 Event · 10:30 pm · 2 times" in lines, "what was held back, in its neutral words"
    assert "-# quiet hours (10:00 pm to 6:00 am): posted without a sound" in lines
    assert lines.index(rules.HELD) < next(at for at, line in enumerate(lines) if "**Pills**" in line), "before the sections"
    run(notify.dealt_with(world.owner.id, NOTE, "event-1"))
    assert rules.HELD not in run(briefing.card_for(world.owner.id)).text, "dealt with: it is dropped, and the box with it"


def test_a_held_pill_reminder_is_dropped_when_its_dose_is_taken(world, phone, night, monkeypatch):
    # If pill reminders were ever set to be held, taking the dose is what deals with the line
    monkeypatch.setitem(notify.KINDS, "pills.reminder", notify.Kind("Reminder", notify.BOTH))
    add(world, LATE)
    at(world, 22, 30)
    morning = world.day + timedelta(days=1)
    assert [each.line for each in run(notify.held_overnight(world.owner.id, morning))] == ["💊 Routine due · 10:30 pm"]
    press(world, reminders.P_TAKEN)
    assert run(notify.held_overnight(world.owner.id, morning)) == []


def test_with_quiet_hours_off_a_late_reminder_notifies_as_it_always_did(world, phone):
    add(world, LATE)
    at(world, 22, 30)
    assert [each.silent for each in world.sent if each.card.text.startswith(NOTICE)] == [False]
    assert run(notify.held_overnight(world.owner.id, world.day + timedelta(days=1))) == []


# --- the briefing on the one ranking ----------------------------------------------------------------------------------
def _section(name):
    return Section(name, "📦", name.title(), Summary("ok", design.DONE))


def test_the_sections_come_in_the_ranking_s_order_and_the_rest_stay_as_they_were():
    sections = [_section("keep"), _section("pills"), _section("shopping"), _section("gym")]
    assert [each.task for each in rules.ordered(sections, ["system", "gym", "pills", "gym"])] == ["gym", "pills", "keep", "shopping"]
    assert [each.task for each in rules.ordered(sections, [])] == ["keep", "pills", "shopping", "gym"], "nothing ranked: the catalogue's order"


def test_what_needs_a_look_is_said_with_its_bug():
    assert rules.problem(Item("backup failed", PROBLEM, bug="B14", icon="⚠️")) == "⚠️ B14 · backup failed"
    assert rules.problem(Item("dev mode is on", PROBLEM, icon="🛠️")) == "🛠️ dev mode is on"
    assert rules.held("💊 Routine due · 11:00 pm") == "💊 Routine due · 11:00 pm" and rules.held("x", 3) == "x · 3 times"


def test_the_briefing_reads_as_before_with_nothing_wrong_and_nothing_held():
    on = date(2026, 10, 14)
    assert rules.text([_section("pills")], on, (), (), "10:00 pm to 6:00 am") == rules.text([_section("pills")], on)
    assert rules.NEEDS not in rules.text([_section("pills")], on) and rules.HELD not in rules.text([_section("pills")], on)


def test_the_briefing_puts_what_needs_me_on_top_from_the_same_ranking_as_the_status_line(world, monkeypatch):
    async def problems(user_id, now):
        return [Item("backup failed", PROBLEM, bug="B14")]

    monkeypatch.setattr(attention, "_providers", {})
    add(world, PILL_A)
    attention.provide("system", attention.PROBLEM_ICON, problems)
    shown = run(briefing.card_for(world.owner.id))
    lines = shown.text.splitlines()
    assert lines[3:5] == [rules.NEEDS, "⚠️ B14 · backup failed"], "under the heading and the date"
    now = clock.now()
    top = attention.top(run(attention.gather(world.owner.id, now)), now)
    assert attention.status_line(top) == "⚠️ B14 · backup failed", "the status line's top item is the briefing's first"
    assert shown.layout, "drawn in the new look too"


def test_a_problem_alone_is_worth_a_briefing_and_nothing_at_all_is_not(world, monkeypatch):
    monkeypatch.setattr(attention, "_providers", {})
    assert run(briefing.card_for(world.owner.id)) is None, "nothing to take, nothing wrong, nothing held: nothing to say"

    async def problems(user_id, now):
        return [Item("backup failed", PROBLEM)]

    attention.provide("system", attention.PROBLEM_ICON, problems)
    assert rules.NEEDS in run(briefing.card_for(world.owner.id)).text


def test_the_briefing_is_rewritten_when_what_needs_a_look_changes_and_not_when_nothing_did(world, monkeypatch):
    found = []

    async def problems(user_id, now):
        return list(found)

    monkeypatch.setattr(attention, "_providers", {})
    monkeypatch.setattr(briefing, "_said", {})
    add(world, PILL_A)
    attention.provide("system", attention.PROBLEM_ICON, problems)
    message_id = run(briefing.post_in_hub(world.owner.id, HUB))
    assert run(briefing.look_again()) is False, "nothing reads differently: no edit"
    found.append(Item("backup failed", PROBLEM))
    assert run(briefing.look_again()) is True
    assert [card.text for edited, card in world.edited if edited == message_id][-1].splitlines()[3] == rules.NEEDS
    assert run(briefing.look_again()) is False, "said once"
