"""What's new (core/whatsnew.py): a queue of lines that one morning's briefing shows once, in a box of its own."""
import asyncio
from datetime import date, time, timedelta

from core import clock, database, design, notify, whatsnew
from core import day as days
from tasks.briefing import rules

DAY = date(2030, 10, 16)  # a day to come: the dev clock only moves forward (it failed once 16 Oct 2026 was past 6 am)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_line_is_shown_on_its_day_only_and_once_however_often_it_is_added(db, owner):
    run(whatsnew.add("Round 3 of the design is live", DAY))
    run(whatsnew.add("Round 3 of the design is live", DAY))
    run(whatsnew.add("Two previews to look at in the design options post", DAY))
    assert run(whatsnew.for_day(owner.id, DAY)) == ["Round 3 of the design is live", "Two previews to look at in the design options post"]
    assert run(whatsnew.for_day(owner.id, DAY + timedelta(days=1))) == [], "gone the next day: after the next tidy"
    assert run(whatsnew.for_day(owner.id, DAY - timedelta(days=1))) == []


def test_it_is_never_taken_for_an_alert_held_back_overnight(db, owner):
    run(whatsnew.add("Round 3 of the design is live", DAY))
    assert run(notify.held_overnight(owner.id, DAY)) == [] and run(notify.notes_for(owner.id, DAY)) == []
    since, until = notify.window(DAY)
    assert whatsnew.moment(DAY) >= until, "after the night the briefing lists as held back, so older code never shows it either"


def test_more_than_a_box_holds_are_counted():
    found = [f"line {n}" for n in range(9)]
    assert whatsnew.lines(found) == [*found[: whatsnew.MAX], "…and 3 more"]


def test_the_briefing_has_a_what_s_new_box_under_needs_a_look_in_both_looks():
    news = ("Round 3 of the design is live", "3 new questions in docs/QUESTIONS.md")
    drawn = rules.layout([], DAY, problems=("⚠️ B14 · backup failed",), news=news)
    needs, new = drawn[1], drawn[2]
    assert needs.children[0].content == "### ⚠️ Needs a look" and new.children[0].content == "### 🆕 What's new"
    assert [child.content for child in new.children if isinstance(child, design.Text)][1:] == list(news) and new.status == design.QUIET
    assert rules.text([], DAY, news=news).splitlines()[3:6] == ["🆕 **What's new**", *news]
    assert "What's new" not in rules.text([], DAY), "nothing queued: no box"


def test_the_command_line_adds_to_the_database_it_is_pointed_at(db, owner, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["whatsnew", "add", "Round 3 of the design is live", "--on", DAY.isoformat()])
    assert whatsnew.main() == 0
    assert run(whatsnew.for_day(owner.id, DAY)) == ["Round 3 of the design is live"]
    monkeypatch.setattr(sys, "argv", ["whatsnew", "list", "--on", DAY.isoformat()])
    assert whatsnew.main() == 0 and "- Round 3 of the design is live" in capsys.readouterr().out


def test_the_briefing_reads_what_is_worth_knowing_and_what_is_new_together(db, owner, dev_clock):
    clock.advance_to(days.at(DAY, time(6, 0)))
    run(notify.worth_knowing("3:02 am · restarted, nothing was missed"))
    run(whatsnew.add("Round 3 of the design is live", DAY))
    kept, found = run(whatsnew.notes_and_news(owner.id, DAY))
    assert [each.line for each in kept] == [each.line for each in run(notify.notes_for(owner.id, DAY))] == ["3:02 am · restarted, nothing was missed"]
    assert found == ["Round 3 of the design is live"]
