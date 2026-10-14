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


def opening(title: str = TITLE) -> str:
    return "\n".join([
        f"## {title}",
        "The round 3 type scale, **built**: each message below is drawn by the real code from made-up data (Pill A to Pill E), so it is what the hub shows once `CARDS_V2` is on. The buttons here do nothing.",
        "-# One box a topic, a rule between items, dots and the count in the card title, times in bold, a change struck through → bold, buttons only on what can be done now.",
        "**Please look on your phone** and reply here with anything to change (spacing, colours, what wraps).",
    ])


def checked(found: list[tuple[str, tuple]] | None = None) -> list[tuple[str, tuple]]:
    """Every message of a preview, each within one message, or a ValueError naming the one that is not."""
    found = messages() if found is None else found
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise ValueError(f"{label or 'the message after the one before'}: {wrong}")
    return found


async def _the_post(client):
    """The design-options post of the dev bot's forum, or None; and the forum. Over HTTP only."""
    import discord
    from dotenv import dotenv_values

    from selftest import options

    if client.user.id != config.test_bot_id():
        raise SystemExit("Not the dev bot's account: nothing done.")
    forum_id = (dotenv_values(config.BASE_DIR / ".env.dev").get("BUGS_CHANNEL_ID") or "").strip()
    if not forum_id.isdigit():
        raise SystemExit("BUGS_CHANNEL_ID is not set in .env.dev: the preview goes in the dev bot's forum. Nothing done.")
    forum = await client.fetch_channel(int(forum_id))
    if not isinstance(forum, discord.ForumChannel):
        raise SystemExit("BUGS_CHANNEL_ID in .env.dev is not a forum: nothing done.")
    return await options._earlier_post(client, forum), forum


async def _as_dev_bot(work):
    """Log in as the dev bot over HTTP (no bot is started), do `work(client)`, log out."""
    import discord

    token = config.test_bot_token()
    if token is None or config.test_bot_id() is None:
        raise SystemExit("There is no dev bot (.env.dev needs its own token and BOT_USER_ID): nothing done.")
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    try:
        return await work(client)
    finally:
        await client.close()


async def post(title: str = TITLE, intro: str = "", found: list[tuple[str, tuple]] | None = None) -> str:
    """Post a preview in the design-options post: its opening message (`## title`), then
    each message under the line saying what it is. Returns the post's link."""
    import discord

    from interfaces.discord import render
    from selftest import options

    found = checked(found)
    intro = intro or opening(title)

    async def work(client):
        quiet = discord.AllowedMentions.none()
        thread, forum = await _the_post(client)
        if thread is None:
            made = await forum.create_thread(name=f"{options.TITLE} · {title}", content=intro, allowed_mentions=quiet)
            thread = made.thread
        else:
            await thread.send(intro, allowed_mentions=quiet)
        for label, pieces in found:
            if label:
                await thread.send(f"### {label}", allowed_mentions=quiet)
            await thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(1)  # paced: well under Discord's rate limit
        return thread.jump_url

    return await _as_dev_bot(work)


ROUND_MARK = "## Round "  # how a round's opening message begins (`opening`)


def since_last_round(history: list) -> list:
    """What people (not bots) said in the post after the latest round's opening message,
    oldest first. `history` is the post's messages, oldest first, shaped like Discord's."""
    start = max((at for at, each in enumerate(history) if getattr(each.author, "bot", False) and (each.content or "").startswith(ROUND_MARK)), default=-1)
    return [each for each in history[start + 1:] if not getattr(each.author, "bot", False) and (each.content or "").strip()]


async def replies() -> list[tuple[str, str]]:
    """Alex's replies in the design-options post since the latest round was posted, as
    (when, what he wrote), word for word: for docs/DESIGN-LOG.md. Read only."""
    from core import config as settings

    async def work(client):
        thread, _ = await _the_post(client)
        if thread is None:
            return []
        history = [each async for each in thread.history(limit=500, oldest_first=True)]
        return [(f"{each.created_at.astimezone(settings.TIMEZONE):%Y-%m-%d %H:%M}", each.content) for each in since_last_round(history)]

    return await _as_dev_bot(work)


# ---------------------------------------------------------------------------
# The three new hub tasks (to-dos, reminders, personal routines), each card in
# its main states, from made-up data: `python -m selftest.preview --hub-tasks`
# ---------------------------------------------------------------------------
HUB_TASKS_TITLE = "New hub tasks preview"


def _todo(number: int, text: str, day=None, done_at=None, added=None):
    from tasks.todos.rules import Todo

    today = _day()
    return Todo(number, 1, text, day, added or today - timedelta(days=3), done_at, days.day_of(done_at) if done_at else None)


def todos_cards() -> list[tuple[str, tuple]]:
    from tasks.todos import rules as todo

    today = _day()
    few = [_todo(1, "Call the dentist", today), _todo(2, "Buy stamps"), _todo(3, "Book the WOF", today + timedelta(days=2))]
    overdue = [_todo(4, "Pay the power bill", today - timedelta(days=2)), _todo(5, "Reply to Sam", today - timedelta(days=1)), *few, _todo(6, "Water the plants", today, _at(8, 10))]
    done = [_todo(7, "Call the dentist", today, _at(9, 5)), _todo(8, "Buy stamps", None, _at(12, 40))]
    return [
        ("To-dos · a few for today (one more for later)", todo.layout(todo.on(few, today), today)),
        ("To-dos · two overdue first, amber, with the day they were for", todo.layout(todo.on(overdue, today), today)),
        ("To-dos · all done: green, in one small line", todo.layout(todo.on(done, today), today)),
    ]


def reminders_cards() -> list[tuple[str, tuple]]:
    from tasks.nudges import rules as nudge
    from tasks.nudges.rules import Nudge

    today = _day()
    now = _at(MORNING.hour, MORNING.minute)
    set_up = [
        Nudge(1, 1, "Call Mum", time(17, 0), nudge.ONCE, today),
        Nudge(2, 1, "Stretch", time(11, 0), nudge.WEEKDAYS),
        Nudge(3, 1, "Put the bins out", time(19, 30), nudge.DAYS, weekdays=(today.weekday(),)),
    ]
    went_off = set_up[0]
    return [
        ("Reminders · what is still to come today (no buttons: nothing to do yet)", nudge.card_layout(nudge.coming(set_up, now), now)),
        ("A reminder going off, at the bottom of the hub: the neutral line, then Done and Snooze", nudge.fired_layout(went_off, _at(17, 0), False, nudge.fired_row(1))),
        ("…after Snooze: 10 minutes, 1 hour, tomorrow at the same time", nudge.fired_layout(went_off, _at(17, 0), False, nudge.snooze_row(1))),
        ("…one that went off while the bot was off: marked late", nudge.fired_layout(went_off, _at(17, 0), True, nudge.fired_row(1))),
    ]


def routines_cards() -> list[tuple[str, tuple]]:
    from tasks.habits import rules as habit
    from tasks.habits.rules import Habit, Step

    today = _day()
    morning = Habit(1, 1, "Morning", (), (Step(1, "Stretch"), Step(2, "Water"), Step(3, "Journal")))
    evening = Habit(2, 1, "Evening", (), (Step(4, "Tidy the desk"), Step(5, "Read")))
    both = [morning, evening]
    return [
        ("Personal routines · nothing done yet", habit.layout(habit.due(both, set(), today))),
        ("Personal routines · part done: each routine's own dots, its next step as a button", habit.layout(habit.due(both, {1, 4, 5}, today))),
        ("Personal routines · all done", habit.layout(habit.due(both, {1, 2, 3, 4, 5}, today))),
    ]


def hub_tasks() -> list[tuple[str, tuple]]:
    """Every message of the hub tasks preview, in the hub's order of cards."""
    return [*reminders_cards(), *routines_cards(), *todos_cards()]


def hub_tasks_opening() -> str:
    return "\n".join([
        f"## {HUB_TASKS_TITLE}",
        "Three new tasks, **built and switched off in live**: reminders you set yourself, personal routines, and to-dos. Each card below is drawn by the real code from made-up data, in the round 3 design. The buttons here do nothing.",
        "-# In the hub they come under the pills card, in this order: reminders, personal routines, (gym), to-dos. A card with nothing for today is not shown at all, so there is no empty card to see.",
        "**Please look on your phone**, read the questions in docs/QUESTIONS.md, and say which to switch on.",
    ])


# ---------------------------------------------------------------------------
# Round 4: the relevance rule and one Taken button, next to round 3, from
# made-up data (Pill A to Pill F): `python -m selftest.preview --round-4`
# ---------------------------------------------------------------------------
ROUND_4_TITLE = "Round 4 preview"


def _six():
    from tasks.pills.rules import PAUSED as PILL_PAUSED
    from tasks.pills.rules import Pill, Plan

    def pill(number: int, name: str, per_day: int = 1, notes: str = "", status: str = "active") -> Pill:
        return Pill(number, 1, Plan(name, notes=notes, schedule=Schedule(per_day=per_day)), status=status)

    return (
        pill(1, "Pill A"), pill(2, "Pill B"), pill(3, "Pill C"), pill(4, "Pill D", status=PILL_PAUSED),
        pill(5, "Pill E", notes="with food"), pill(6, "Pill F", per_day=2),
    )


def _round_4_day(state: str) -> tuple[list, list, datetime]:
    """(today's doses, the pills, now) for one of the three states."""
    a, b, c, d, e, f = _six()
    pills = [a, b, c, d, e, f]
    if state == "morning":
        listed = [
            _dose(a, 1, PENDING, _at(8)), _dose(b, 1, PENDING, _at(8)), _dose(c, 1, PENDING, _at(9)),
            _dose(e, 1, PENDING, _at(11, 30)), _dose(f, 1, PENDING, _at(15)), _dose(f, 2, PENDING, _at(20)),
        ]
        return listed, pills, _at(8, 5)
    if state == "midday":
        listed = [
            _dose(a, 1, DONE, _at(8), taken=_at(8, 4)), _dose(b, 1, DONE, _at(8), taken=_at(8, 6)), _dose(c, 1, MISSED, _at(9)),
            _dose(e, 1, PENDING, _at(11, 30)), _dose(f, 1, PENDING, _at(15)), _dose(f, 2, PENDING, _at(20)),
        ]
        return listed, pills, _at(12, 30)
    listed = [
        _dose(a, 1, DONE, _at(8), taken=_at(8, 4)), _dose(b, 1, DONE, _at(8), taken=_at(8, 6)), _dose(c, 1, DONE, _at(9), taken=_at(9, 2)),
        _dose(e, 1, DONE, _at(11, 30), taken=_at(11, 40)), _dose(f, 1, DONE, _at(15), taken=_at(15, 1)), _dose(f, 2, DONE, _at(20), taken=_at(20, 3)),
    ]
    return listed, pills, _at(20, 5)


def _in_round(number: int, build):
    """`build()` drawn in one round of the design, the setting put back after."""
    before = config.DESIGN_ROUND
    config.DESIGN_ROUND = number
    try:
        return build()
    finally:
        config.DESIGN_ROUND = before


def _count(pieces) -> tuple[int, int]:
    """How long a card is to read: (its lines of text, its buttons)."""
    lines = [line for text in design.texts(pieces) for line in text.splitlines() if line.strip()]
    return len(lines), len(design.buttons(pieces))


def _side_by_side(label: str, build) -> list[tuple[str, tuple]]:
    three, four = _in_round(3, build), _in_round(4, build)
    (l3, b3), (l4, b4) = _count(three), _count(four)
    return [
        (f"{label} · round 3, as live has it", three),
        (f"{label} · round 4", four),
        ("", (design.Text(design.small(f"round 4: {l4} lines and {b4} button{'' if b4 == 1 else 's'}, where round 3 has {l3} lines and {b3} buttons")),)),
    ]


def round_4() -> list[tuple[str, tuple]]:
    """Every message of the round 4 preview, in the order posted."""
    from tasks.pills import sheet

    found = []
    for state, label in (("morning", "Pills · morning, nothing taken yet"), ("midday", "Pills · midday: 2 taken, 1 missed, 1 paused, 1 due and 2 later"), ("done", "Pills · all done")):
        listed, pills, now = _round_4_day(state)
        found += _side_by_side(label, lambda listed=listed, pills=pills, now=now: sheet.layout(listed, pills, _day(), now))
    # The two ways one Taken button can work: the card is the same, what a tap does differs
    listed, pills, now = _round_4_day("midday")
    card = _in_round(4, lambda: sheet.layout(listed, pills, _day(), now))
    found.append(("Variant 1 · Taken opens a pop-up", card))
    found.append(("", (design.Text("\n".join([
        "**What the pop-up shows** (a Discord form, as on a phone):",
        "> **When did you take it?**",
        "> Taken at: `12:30 pm` (filled in with now: send it as it is, or change it)",
        "> [Cancel]  [Submit]",
        design.small("A changed time is read as one said in words: 9, 9:15, 9am. One in the future, too soon after the one before, or out of order is asked about first, as now."),
    ])),)))
    found.append(("Variant 2 · Taken logs at once", card))
    found.append(("", (design.Text("✅ **Pill E** · taken 12:30 pm · reply to this with a time to put it right"), design.Text(design.small("the line a tap leaves, under the card; a reply such as “11:45” corrects it, as “I took it at 11:45” would")))))
    # The to-dos card
    from tasks.todos import rules as todo

    today = _day()
    made = lambda number, text, day=None, done=None: todo.Todo(number, 1, text, day, today - timedelta(days=3), done, today if done else None)  # noqa: E731
    todos = todo.on([
        made(1, "Pay the power bill", today - timedelta(days=1)),
        *(made(2 + n, text, today) for n, text in enumerate(("Call the dentist", "Buy stamps", "Book the WOF", "Reply to Sam", "Water the plants", "Return the library books"))),
        made(9, "Take the bins out", today, _at(7, 30)), made(10, "Order more coffee", None, _at(9, 10)),
    ], today)
    found += _side_by_side("To-dos · 2 done, 1 overdue, 6 for today", lambda: todo.layout(todos, today))
    return found


def round_4_opening() -> str:
    return "\n".join([
        f"## {ROUND_4_TITLE}",
        "From your feedback and your friend's: less that is no longer relevant, paused and missed out of the way, one Taken button. Each card is drawn by the real code from made-up data (Pill A to Pill F), round 3 (as live has it) next to round 4. The buttons here do nothing.",
        "-# The rule on every card: what can be done now in full with its button; the next thing in full, no button; the rest of the day one small line of times; done and missed a small line each with a count; paused not shown (say “show paused”).",
        "**Question 67: Variant 1 or Variant 2?** Reply here. Live stays on round 3 until you say “ship round 4”.",
    ])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--check" in args and "--hub-tasks" not in args and "--round-4" not in args:
        print(f"{len(checked())} messages built, each within one message.")
        return 0
    if "--round-4" in args:
        found = checked(round_4())
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post(ROUND_4_TITLE, round_4_opening(), found)))
        return 0
    if "--hub-tasks" in args:
        found = checked(hub_tasks())
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post(HUB_TASKS_TITLE, hub_tasks_opening(), found)))
        return 0
    if "--replies" in args:
        found = asyncio.run(replies())
        for when, said in found:
            print(f"--- {when}\n{said}")
        print(f"{len(found)} replies since the latest round.")
        return 0
    title = f"Round {args[args.index('--round') + 1]}" if "--round" in args else TITLE
    print("Posted:", asyncio.run(post(title)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
