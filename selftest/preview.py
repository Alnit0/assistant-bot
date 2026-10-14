"""The round 3 design as built, to look at on the phone: `python -m selftest.preview`.

Every message is drawn by the real code (tasks/briefing/rules.py,
tasks/pills/sheet.py, core/confirm.py, core/design.py) and the real
renderer (interfaces/discord/render.py), from made-up data: the pills are
"Pill A" to "Pill E", and nothing is read from a database. So what is
posted is what the hub shows with CARDS_V2 on.

They go in the design-options post of the dev bot's own forum, under one
message "Round 3 built", each under a line saying what it is. The buttons
on them do nothing.

`--check` builds them all and checks each fits one message, posting nothing.
Over HTTP only, as the dev bot: no bot is started, and live is not touched.
"""
import asyncio
import sys
from datetime import date, datetime, time, timedelta

from core import config, design
from core import day as days
from core.actions import Choice, Entry, Proposal, Question, Summary
from core.occurrences import DONE, MISSED, PENDING, Occurrence
from core.schedule import AFTER_PREVIOUS, ANY_TIME, PLANNED, Due, Schedule
from core.summaries import Section

TITLE = "Round 3 built"
PILLS = Entry("pills", "💊", "Pills", "x", ("y",), ())
MORNING = time(7, 30)  # the mock "now" of the first card: about when the preview is read


def _dose(pill, number: int, state: str, due: datetime | None, why: str = PLANNED, taken: datetime | None = None):
    from tasks.pills.today import Dose

    occurrence = Occurrence(pill.id * 10 + number, 1, "pills", pill.id, _day(), number, None, due, state, taken, False, None)
    return Dose(pill, occurrence, Due(due, why))


def _day() -> date:
    return days.today()


def _at(hour: int, minute: int = 0) -> datetime:
    return days.at(_day(), time(hour, minute))


def _pills():
    from tasks.pills.rules import Pill, Plan

    def pill(number: int, name: str, per_day: int = 1, notes: str = "", gap: int | None = None, latest: time | None = None) -> Pill:
        return Pill(number, 1, Plan(name, notes=notes, schedule=Schedule(per_day=per_day, gap_minutes=gap, latest=latest)))

    return (
        pill(1, "Pill A", 3, "with food", gap=180, latest=time(22, 0)),
        pill(2, "Pill B"),
        pill(3, "Pill C"),
        pill(4, "Pill D"),
    )


def checklist(state: str, now: datetime) -> tuple:
    """Today's checklist in one of four states: nothing done, part done, overdue, all done."""
    from tasks.pills import sheet

    a, b, c, d = _pills()
    if state == "nothing":
        listed = [
            _dose(a, 1, PENDING, _at(8)), _dose(a, 2, PENDING, _at(11)), _dose(a, 3, PENDING, _at(14)),
            _dose(b, 1, PENDING, None, ANY_TIME), _dose(c, 1, PENDING, _at(9)), _dose(d, 1, PENDING, _at(20)),
        ]
    elif state == "part":
        listed = [
            _dose(a, 1, DONE, _at(8), taken=_at(8, 4)), _dose(a, 2, PENDING, _at(11, 4), AFTER_PREVIOUS), _dose(a, 3, PENDING, _at(14, 4), AFTER_PREVIOUS),
            _dose(b, 1, PENDING, None, ANY_TIME), _dose(c, 1, DONE, _at(7, 42), taken=_at(7, 42)), _dose(d, 1, PENDING, _at(20)),
        ]
    elif state == "overdue":
        listed = [
            _dose(a, 1, DONE, _at(8), taken=_at(8, 4)), _dose(a, 2, PENDING, _at(11, 4), AFTER_PREVIOUS), _dose(a, 3, PENDING, _at(14, 4), AFTER_PREVIOUS),
            _dose(b, 1, PENDING, None, ANY_TIME), _dose(c, 1, MISSED, _at(9)), _dose(d, 1, PENDING, _at(20)),
        ]
    else:
        listed = [
            _dose(a, 1, DONE, _at(8), taken=_at(8, 4)), _dose(a, 2, DONE, _at(11, 4), taken=_at(11, 20)), _dose(a, 3, DONE, _at(14, 20), taken=_at(14, 31)),
            _dose(b, 1, DONE, None, ANY_TIME, taken=_at(12, 2)), _dose(c, 1, DONE, _at(9), taken=_at(9, 1)), _dose(d, 1, DONE, _at(20), taken=_at(20, 3)),
        ]
    return sheet.layout(listed, [a, b, c, d], _day(), now)


def briefing(problems: tuple[str, ...] = ()) -> tuple:
    """The 6 am briefing as it reads mid-morning, with or without something that needs a look."""
    from tasks.briefing import rules

    pills = Section("pills", "💊", "Pills", Summary("2 of 6 taken", design.DUE, ("**Next:** Pill A, dose 2 · `11:04 am`", "🔥 4 days in a row"), "1 to take any time", "Yesterday: 5 of 6 taken · 1 missed", done=2, total=6))
    weather = Section("weather", "🌤️", "Weather", Summary("14° to 20° · drizzle", design.QUIET, ("61% rain after 1:00 pm · wind 15 km/h N",), "updated 5:50 am"))
    so_far = rules.progress([pills, weather])
    spend = rules.spend_line("NZ$0.12", "NZ$0.30", "NZ$0.42")
    return rules.layout([pills, weather], _day(), problems=problems, spend=spend, so_far=so_far, notes=("3:02 am · restarted, nothing was missed",))


def change() -> tuple:
    """A change to two pills, one value a guess, as the confirm card draws it."""
    from core import confirm

    lines = ("**Pill A**", "time · `8:00 pm` → `9:00 pm` ❓", "-# ❓ a guess: you did not say morning or evening", "**Pill B**", "dose · 1 tablet → 2 tablets")
    return confirm.render(PILLS, Proposal(lines=lines, data={}, kind="change"), 1).layout


def questions() -> tuple[tuple, tuple]:
    """Two question cards, one after the other, as they stack in a channel."""
    from core import confirm

    first = Proposal(lines=("**Pill E** · daily at ❔ · *with food*",), data={}, question=Question("Is that 8 in the morning or the evening?", (Choice("8:00 am", {}), Choice("8:00 pm", {}))))
    entries = [Entry("pills", "💊", "Pills", "x", ("y",), ()), Entry("schedule", "🗓️", "Schedule", "x", ("y",), ())]
    return confirm.render(PILLS, first, 1).layout, confirm.render_tie(entries, 2, "move it to 9").layout


def messages() -> list[tuple[str, tuple]]:
    """(the line above it, the layout) for each message of the preview, in the order posted."""
    now = _at(MORNING.hour, MORNING.minute)
    asked, tie = questions()
    return [
        ("The briefing · 6 am, edited in place all day", briefing()),
        ("The briefing with something wrong · the Needs a look box, red, on top", briefing(("⚠️ B14 · backup failed at 3:00 am", "⚠️ B9 · memory 312 MB"))),
        ("Pills card · nothing done yet", checklist("nothing", now)),
        ("Pills card · part done", checklist("part", _at(10, 30))),
        ("Pills card · overdue (dose 2 due 11:04 am, it is 12:30 pm), and a missed pill", checklist("overdue", _at(12, 30))),
        ("Pills card · all done", checklist("done", _at(21, 0))),
        ("A change · old struck through → new bold", change()),
        ("A question card, and a second one under it · thin, so they stack", asked),
        ("", tie),
    ]


def opening() -> str:
    return "\n".join([
        f"## {TITLE}",
        "The round 3 type scale, **built**: each message below is drawn by the real code from made-up data (Pill A to Pill E), so it is what the hub shows once `CARDS_V2` is on. The buttons here do nothing.",
        "-# One box a topic, a rule between items, dots and the count in the card title, times in bold, a change struck through → bold, buttons only on what can be done now.",
        "**Please look on your phone** and reply here with anything to change (spacing, colours, what wraps).",
    ])


def checked() -> list[tuple[str, tuple]]:
    """Every message of the preview, each within one message, or a ValueError naming the one that is not."""
    found = messages()
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise ValueError(f"{label or 'the second question'}: {wrong}")
    return found


async def post() -> str:
    """Post the preview in the design-options post of the dev bot's forum. Returns its link."""
    import discord
    from dotenv import dotenv_values

    from interfaces.discord import render
    from selftest import options

    token, expected = config.test_bot_token(), config.test_bot_id()
    if token is None or expected is None:
        raise SystemExit("There is no dev bot (.env.dev needs its own token and BOT_USER_ID): nothing posted.")
    forum_id = (dotenv_values(config.BASE_DIR / ".env.dev").get("BUGS_CHANNEL_ID") or "").strip()
    if not forum_id.isdigit():
        raise SystemExit("BUGS_CHANNEL_ID is not set in .env.dev: the preview goes in the dev bot's forum. Nothing posted.")
    found = checked()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    try:
        if client.user.id != expected:
            raise SystemExit("Not the dev bot's account: nothing posted.")
        forum = await client.fetch_channel(int(forum_id))
        if not isinstance(forum, discord.ForumChannel):
            raise SystemExit("BUGS_CHANNEL_ID in .env.dev is not a forum: nothing posted.")
        quiet = discord.AllowedMentions.none()
        thread = await options._earlier_post(client, forum)
        if thread is None:
            made = await forum.create_thread(name=f"{options.TITLE} · {TITLE}", content=opening(), allowed_mentions=quiet)
            thread = made.thread
        else:
            await thread.send(opening(), allowed_mentions=quiet)
        for label, pieces in found:
            if label:
                await thread.send(f"### {label}", allowed_mentions=quiet)
            await thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(1)  # paced: well under Discord's rate limit
        return thread.jump_url
    finally:
        await client.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--check" in sys.argv[1:]:
        print(f"{len(checked())} messages built, each within one message.")
        return 0
    print("Posted:", asyncio.run(post()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
