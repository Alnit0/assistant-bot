"""Button colours: one rule for every button the bot shows (the conversation standard, section 4).
green = the positive main action · red = destructive · blurple = every other choice · grey = Cancel
only, written with ↩️. Also: a housekeeping line is deleted by a stored job, restart or not."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import discord
import pytest

from core import cards, confirm, confirmations, devmode, discord_utils, scheduler, tidy
from core.actions import Proposal
from core.cards import DANGER, PRIMARY, SECONDARY, SUCCESS, Button, Card
from tasks.archive import messages as archive_messages
from tasks.bugs import posts as bug_posts
from tasks.builtin import views as builtin_views
from tasks.dev import panel as dev_panel
from tasks.timers import sessions, timers
from tests import demo

STYLE = {
    discord.ButtonStyle.primary: PRIMARY, discord.ButtonStyle.secondary: SECONDARY,
    discord.ButtonStyle.success: SUCCESS, discord.ButtonStyle.danger: DANGER,
}


def run(coroutine):
    return asyncio.run(coroutine)


# --- the rule ---------------------------------------------------------------------------------------
def test_a_button_is_blurple_unless_it_says_otherwise_and_cancel_is_the_one_grey_button():
    assert Button("Skip", "pills", "skip").style == PRIMARY
    made = cards.cancel("pills", "cancel", "7")
    assert (made.label, made.style, made.emoji, made.arg) == ("Cancel", SECONDARY, "↩️", "7")
    assert cards.cancel("confirm", "cancel", "7", "Neither").label == "Neither"


@pytest.mark.parametrize(
    "label, style, emoji, wrong",
    [
        ("Save", SUCCESS, "✅", ""),
        ("Delete all", DANGER, "🗑️", ""),
        ("Skip", PRIMARY, "⏭️", ""),
        ("Cancel", SECONDARY, "↩️", ""),
        ("Neither", SECONDARY, "↩️", ""),
        ("Skip", SECONDARY, "⏭️", "grey is for Cancel only"),
        ("Dismiss", SECONDARY, None, "grey is for Cancel only"),
        ("Cancel", SECONDARY, "✖️", "grey is for Cancel only"),
        ("Cancel", PRIMARY, "↩️", "must be the grey ↩️ button"),
        ("cancel", DANGER, None, "must be the grey ↩️ button"),
    ],
)
def test_what_follows_the_rule_and_what_does_not(label, style, emoji, wrong):
    found = cards.colour_problem(label, style, emoji)
    assert (wrong in found and bool(found)) if wrong else found == ""


def test_a_card_that_breaks_the_rule_is_refused_before_it_is_sent():
    with pytest.raises(ValueError, match="“Skip” is grey: grey is for Cancel only"):
        cards.check(Card("x", ((Button("Taken", "pills", "taken", style=SUCCESS), Button("Skip", "pills", "skip", style=SECONDARY)),)))
    with pytest.raises(ValueError, match="“Cancel” must be the grey ↩️ button"):
        cards.check(Card("x", ((Button("Cancel", "pills", "cancel"),),)))
    cards.check(Card("x", ((Button("Taken", "pills", "taken", style=SUCCESS), Button("Skip", "pills", "skip"), cards.cancel("pills", "cancel")),)))


# --- every button there is: the cards --------------------------------------------------------------
def colours(card: Card):
    return [(button.label, button.style, button.emoji) for row in card.rows for button in row]


def test_the_confirm_card_save_is_green_what_takes_away_is_red_and_cancel_is_grey():
    saved = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}), 1)
    assert colours(saved) == [("Save", SUCCESS, "✅"), ("Cancel", SECONDARY, "↩️")]
    removed = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, kind="remove", confirm_label="Remove"), 1)
    assert colours(removed) == [("Remove", DANGER, "🗑️"), ("Cancel", SECONDARY, "↩️")], "a removal is red even when its history is kept"
    for_good = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, kind="remove", destructive=True, confirm_label="Delete for good"), 1)
    assert colours(for_good)[0] == ("Delete for good", DANGER, "🗑️")
    bulk = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, kind="remove", destructive=True, confirm_label="Cancel 3 timers"), 1)
    assert colours(bulk)[0] == ("Cancel 3 timers", DANGER, "🗑️"), "a bulk cancel is red; only the way out is grey"
    held = confirm.render(demo.SHOPPING, Proposal(lines=("x",), data={}, can_save=False), 1)
    assert colours(held) == [("Cancel", SECONDARY, "↩️")]


def test_the_question_on_a_tie_tasks_are_blurple_and_neither_is_the_grey_way_out():
    asked = confirm.render_tie([demo.SHOPPING, demo.PACKING], 1, "add socks")
    assert colours(asked) == [("Shopping", PRIMARY, "🛒"), ("Packing", PRIMARY, "🧳"), ("Neither", SECONDARY, "↩️")]


def test_the_pills_dose_message_taken_is_green_and_skip_is_blurple():
    from datetime import date

    from core.occurrences import Occurrence
    from core.schedule import ANY_TIME, Due, Schedule
    from tasks.pills import checklist
    from tasks.pills.rules import Pill, Plan
    from tasks.pills.today import Dose

    dose = Dose(Pill(1, 1, Plan("Zinc", schedule=Schedule())), Occurrence(5, 1, "pills", 1, date(2026, 10, 12), 1, None, None, "pending", None, False, None), Due(None, ANY_TIME))
    assert colours(checklist.dose_card(dose)) == [("Taken", SUCCESS, "✅"), ("Skip", PRIMARY, "⏭️")]


# --- every button there is: the ones made with discord.py ---------------------------------------------
def problems(named):
    """What is wrong with (label, discord style, emoji) buttons, by the same rule."""
    return [found for label, style, emoji in named if (found := cards.colour_problem(label, STYLE[style], emoji and str(emoji)))]


def of_view(view):
    return [(child.label, child.style, child.emoji and child.emoji.name) for child in view.children]


def test_timers_sessions_and_the_dev_panel_have_no_grey_button():
    for table in (timers.BUTTONS, sessions.BUTTONS, dev_panel.BUTTONS):
        assert problems((label, style, emoji) for label, emoji, style in table.values()) == []
    assert {name: STYLE[style] for name, (_, _, style) in sessions.BUTTONS.items()} == {
        "ok": PRIMARY, "pause": PRIMARY, "resume": SUCCESS, "start": SUCCESS, "skip": PRIMARY, "stop": DANGER,
    }
    assert {name: STYLE[style] for name, (_, _, style) in timers.BUTTONS.items()} == {"plus5": PRIMARY, "restart": PRIMARY, "dismiss": PRIMARY}


def test_the_views_follow_the_rule_and_cancel_is_grey_with_its_arrow(owner):
    async def every_view():
        async def nothing():
            return ""

        return {
            "confirm": of_view(confirmations._Prompt(owner, "Sure?", nothing)),
            "choose": of_view(confirmations._Choice(owner, "Which?", [("A", nothing), ("B", nothing)])),
            "bug open": of_view(bug_posts.CloseButtons()),
            "bug closed": of_view(bug_posts.ReopenButton()),
            "buttons": of_view(builtin_views.TestButtons(owner)) if _takes_owner(builtin_views.TestButtons) else of_view(builtin_views.TestButtons()),
            "restore": [(b.item.label, b.item.style, b.item.emoji and b.item.emoji.name) for b in [archive_messages.RestoreButton(1)]],
        }

    found = run(every_view())
    for name, buttons in found.items():
        assert problems(buttons) == [], name
    assert [(label, STYLE[style], emoji) for label, style, emoji in found["confirm"]] == [("Confirm", DANGER, None), ("Cancel", SECONDARY, "↩️")]
    assert found["choose"][-1][0] == "None of these" and STYLE[found["choose"][-1][1]] == SECONDARY and found["choose"][-1][2] == "↩️"
    assert [STYLE[style] for _, style, _ in found["choose"][:-1]] == [PRIMARY, PRIMARY], "answers to a question are blurple"
    assert [(label, STYLE[style]) for label, style, _ in found["bug open"]] == [("Fixed", SUCCESS), ("Won't fix", PRIMARY)]
    assert STYLE[found["restore"][0][1]] == PRIMARY


def _takes_owner(view_class) -> bool:
    import inspect

    return len(inspect.signature(view_class.__init__).parameters) > 1


# --- a housekeeping line is deleted by a stored job ---------------------------------------------------
class Deleting:
    def __init__(self):
        self.deleted = []

    def get_channel(self, channel_id):
        client = self

        def partial(message_id):
            async def delete():
                client.deleted.append((channel_id, message_id))

            return SimpleNamespace(delete=delete)

        return SimpleNamespace(get_partial_message=partial)


def test_a_line_is_booked_and_deleted_when_its_time_comes_even_after_a_restart(db, monkeypatch):
    client = Deleting()
    monkeypatch.setattr(discord_utils, "client", client)
    monkeypatch.setattr(scheduler, "_handlers", {})
    tidy.setup()
    run(tidy.later(100, 555, 10))
    (job,) = run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND))
    assert job.payload == {"channel": 100, "message": 555}
    assert run(scheduler.run_all_due()) == 0 and client.deleted == [], "not yet"
    # The bot was off when its time came: nothing in memory remembers the line, the stored job does
    later = scheduler.utc_now() + timedelta(minutes=37)
    assert run(scheduler.run_due(later)) == 1 and client.deleted == [(100, 555)]
    assert run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND)) == []


def test_nothing_is_booked_while_clean_up_is_off_and_a_job_then_leaves_the_line(db, monkeypatch):
    client = Deleting()
    monkeypatch.setattr(discord_utils, "client", client)
    run(tidy.later(100, 555, None))
    run(tidy.later(100, None, 10))
    assert run(scheduler.pending_jobs(tidy.JOB_TASK, tidy.JOB_KIND)) == []
    monkeypatch.setattr(devmode, "cleanup_enabled", lambda: False)
    run(tidy.tidy_job(scheduler.Job(1, None, tidy.JOB_TASK, tidy.JOB_KIND, {"channel": 100, "message": 555}, scheduler.utc_now())))
    assert client.deleted == []
