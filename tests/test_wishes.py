"""The wishlist (core/wishes.py): what live could not do, kept quietly, never in the message's own words; one Alex
adds himself; the count in the week's summary. Made-up data only."""
from datetime import timedelta
from types import SimpleNamespace

from core import database, weekly, wishes
from core import day as days
from tests.test_conversation import route, run, world  # noqa: F401


def kept():
    return run(database.run(wishes.db_since, 1, days.today() - timedelta(days=7)))


def test_a_message_not_understood_or_declined_is_kept_with_no_word_of_it_and_the_reply_is_as_before(world):
    world.claude(route("shopping"), ("none", {"why": "unclear", "reason": "made up"}))
    world.say("frobnicate the zinc thing")
    assert world.sent[-1][1].text == "🤔 I didn't understand that.", "nothing said differently"
    world.claude(route("shopping"), ("none", {"why": "cannot", "reason": "made up"}))
    world.say("order the zinc for me")
    found = kept()
    assert [(task, why) for _, task, why, _ in found] == [("shopping", wishes.NOT_UNDERSTOOD), ("shopping", wishes.DECLINED)]
    assert all("zinc" not in summary.lower() and "frobnicate" not in summary.lower() for *_, summary in found), "never the message's words"
    assert found[0][3] == "Shopping · not understood"


def test_already_so_is_no_wish(world):
    world.claude(route("shopping"), ("none", {"why": "already_so", "reason": "made up"}))
    world.say("add milk")
    assert kept() == []


def test_a_report_no_task_keeps_is_a_wish(world):
    world.claude(("route", {"kind": "nothing", "tasks": [], "confidence": "high", "reports_doing": True, "chat_part": ""}))
    world.say("I walked the dog at 6")
    assert [(task, why) for _, task, why, _ in kept()] == [("", wishes.NO_TASK)]


def test_one_alex_adds_himself_is_kept_in_his_words(make_db, owner):
    from tasks import builtin

    make_db()
    replied, confirmed = [], []

    async def confirm(text):
        confirmed.append(text)

    async def reply(text, **_):
        replied.append(text)

    ctx = SimpleNamespace(user=owner, args=[":", "plan", "my", "day"], confirm=confirm, reply=reply)
    run(builtin.wish(ctx))
    assert confirmed == ["✨ On your wishlist"]
    assert [(why, summary) for _, _, why, summary in kept()] == [(wishes.ASKED, "plan my day")]
    ctx.args = []
    run(builtin.wish(ctx))
    assert replied and len(kept()) == 1


def test_the_week_s_summary_has_the_count_in_one_small_line(make_db, owner):
    make_db()
    assert run(wishes.week_line(owner.id, days.today() - timedelta(days=days.today().weekday()))) == ""
    run(wishes.note(owner.id, "todos", "To-dos", wishes.DECLINED))
    run(wishes.note(owner.id, "", "", wishes.NO_TASK))
    line = run(wishes.week_line(owner.id, days.today() - timedelta(days=days.today().weekday())))
    assert line == "2 wishes on your wishlist this week: what I couldn't do yet"
    monday = days.today() - timedelta(days=days.today().weekday())
    assert weekly.text([], monday, weekly.sunday_of(monday), line).splitlines()[-1] == f"-# {line}"


def test_the_suggest_skill_and_the_brainstorm_are_there():
    from pathlib import Path

    root = Path(__file__).parent.parent
    skill = (root / ".claude" / "skills" / "suggest" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: suggest" in skill and "wishes" in skill
    brainstorm = (root / "docs" / "BRAINSTORM.md").read_text(encoding="utf-8")
    assert "## The top 10" in brainstorm and sum(1 for line in brainstorm.splitlines() if line[:3].strip().rstrip(".").isdigit()) >= 40
