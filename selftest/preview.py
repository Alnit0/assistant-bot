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
from core.cards import Card
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
    """How long a card is to read: (its lines of text, its buttons and dropdowns)."""
    lines = [line for text in design.texts(pieces) for line in text.splitlines() if line.strip()]
    return len(lines), len(design.buttons(pieces)) + len(design.menus(pieces))


def _side_by_side(label: str, build) -> list[tuple[str, tuple]]:
    three, four = _in_round(3, build), _in_round(4, build)
    (l3, b3), (l4, b4) = _count(three), _count(four)
    return [
        (f"{label} · round 3, as live has it", three),
        (f"{label} · round 4", four),
        ("", (design.Text(design.small(f"round 4: {l4} lines and {b4} control{'' if b4 == 1 else 's'}, where round 3 has {l3} lines and {b3} (a control is a button or a dropdown)")),)),
    ]


def round_4() -> list[tuple[str, tuple]]:
    """Every message of the round 4 preview, in the order posted."""
    from tasks.pills import sheet

    found = []
    for state, label in (("morning", "Pills · morning, nothing taken yet"), ("midday", "Pills · midday: 2 taken, 1 missed, 1 paused, 1 due and 2 later"), ("done", "Pills · all done")):
        listed, pills, now = _round_4_day(state)
        found += _side_by_side(label, lambda listed=listed, pills=pills, now=now: sheet.layout(listed, pills, _day(), now))
    # One Taken, at once (question 67): the line a tap leaves, which a reply with a time corrects
    found.append(("", (design.Text("✅ **Pill E** · taken 12:30 pm · reply to this with a time to put it right"), design.Text(design.small("the line a tap on Taken leaves under the card; a reply such as “11:45” corrects it, as “I took it at 11:45” would")))))
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
        "Your answers of 15 Oct are in: one Taken that logs at once (reply with a time to correct it), and to-dos as the first three with one Done dropdown.",
    ])


# ---------------------------------------------------------------------------
# The Design forum (Alex, 15 Oct): one post a round, so rounds can be put
# side by side and the feedback on each stays in its own post. A post is
# named "Round N" and carries one tag: Live (what the hub shows), Preview
# (built, not shipped) or Retired. The forum's id is DESIGN_FORUM_ID in
# .env.dev (the dev bot's, never one of live's channels); `--forum` makes
# it if it is not there, with its tags.
#   python -m selftest.preview --forum                  the forum and its tags
#   python -m selftest.preview --post-round 4 --tag preview
#   python -m selftest.preview --ship 4                 4 Live, the Live before it Retired
#   python -m selftest.preview --replies-round 4        what was said in Round 4's post
# ---------------------------------------------------------------------------
DESIGN_FORUM = "Design"
DESIGN_FORUM_TOPIC = "One post a round of the hub's design: Live is what the hub shows, Preview is built and not shipped, Retired is gone by. Feedback on a round goes in its own post."
LIVE, PREVIEW, RETIRED = "Live", "Preview", "Retired"
TAGS = ((LIVE, "🟢"), (PREVIEW, "🟡"), (RETIRED, "⚪"))
ABOUT = {
    1: "The look before round 3: a box an item, its state at a glance.",
    3: "The type scale: a page title, a box a topic with a rule between items, dots with a count, names and times in bold, small details.",
    4: "The relevance rule: what can be done now in full with its button, the next thing in full, the rest of the day one small line; one Taken that logs at once (reply with a time to correct it); Skip in words; to-dos the first three and one Done dropdown.",
}


def round_title(number: int) -> str:
    return f"Round {number}"


def tag_named(word: str) -> str:
    """A tag's name from how it is typed (live, preview, retired)."""
    found = next((name for name, _ in TAGS if name.lower() == word.strip().lower()), None)
    if found is None:
        raise SystemExit(f"No tag {word!r}: one of {', '.join(name for name, _ in TAGS)}. Nothing done.")
    return found


def missing_tags(have: list[str]) -> list[tuple[str, str]]:
    """The tags of TAGS the forum does not have yet, by name (any case)."""
    there = {name.lower() for name in have}
    return [(name, emoji) for name, emoji in TAGS if name.lower() not in there]


def tag_of(tag_ids, by_id: dict[int, str]) -> str:
    """A post's tag of TAGS, from the ids Discord holds for it (over HTTP alone the names
    are not filled in: there is no cache of the forum), or Preview with none."""
    names = [by_id.get(int(each), "") for each in tag_ids or ()]
    return next((name for name in names if name in dict(TAGS)), PREVIEW)


def shipped(tags: dict[int, str], number: int) -> dict[int, str]:
    """Each round's tag once `number` ships: it is Live, the round that was Live is
    Retired, and the rest keep theirs."""
    return {each: LIVE if each == number else RETIRED if tag == LIVE else tag for each, tag in {**tags, number: tags.get(number, PREVIEW)}.items()}


def round_cards(number: int) -> list[tuple[str, tuple]]:
    """Every message of a round's post: the main cards drawn in that round, then the to-dos card."""
    from tasks.todos import rules as todo

    def build():
        found = list(messages())
        today = _day()
        made = lambda each, text, day=None, done=None: todo.Todo(each, 1, text, day, today - timedelta(days=3), done, today if done else None)  # noqa: E731
        todos = todo.on([
            made(1, "Pay the power bill", today - timedelta(days=1)),
            *(made(2 + each, text, today) for each, text in enumerate(("Call the dentist", "Buy stamps", "Book the WOF", "Reply to Sam"))),
            made(9, "Take the bins out", today, _at(7, 30)),
        ], today)
        found.append(("To-dos · 1 done, 1 overdue, 4 for today", todo.layout(todos, today)))
        if number >= 4:
            found.append(("Taken, at once · the line it leaves", (design.Text("✅ **Pill E** · taken 12:30 pm · reply to this with a time to put it right"), design.Text(design.small("a reply such as “11:45” corrects it, as “I took it at 11:45” would")))))
        return found

    return checked(_in_round(number, build))


def round_opening(number: int, tag: str) -> str:
    return "\n".join([
        f"## {round_title(number)} · {tag}",
        ABOUT.get(number, ""),
        "-# Every card is drawn by the real code from made-up data (Pill A to Pill F). The buttons here do nothing.",
        f"Feedback on round {number} goes in this post; each round has its own.",
    ])


def _forum_id() -> int | None:
    from dotenv import dotenv_values

    value = (dotenv_values(config.BASE_DIR / ".env.dev").get("DESIGN_FORUM_ID") or "").strip()
    return int(value) if value.isdigit() else None


async def _design_forum(client):
    """The Design forum named by DESIGN_FORUM_ID in .env.dev. Over HTTP only."""
    import discord

    if client.user.id != config.test_bot_id():
        raise SystemExit("Not the dev bot's account: nothing done.")
    forum_id = _forum_id()
    if forum_id is None:
        raise SystemExit("DESIGN_FORUM_ID is not set in .env.dev: run `python -m selftest.preview --forum` first. Nothing done.")
    forum = await client.fetch_channel(forum_id)
    if not isinstance(forum, discord.ForumChannel):
        raise SystemExit("DESIGN_FORUM_ID in .env.dev is not a forum: nothing done.")
    return forum


async def _with_tags(forum):
    """The forum, with every tag of TAGS on it (the ones it has are kept)."""
    import discord

    wanted = missing_tags([tag.name for tag in forum.available_tags])
    if wanted:
        forum = await forum.edit(available_tags=[*forum.available_tags, *(discord.ForumTag(name=name, emoji=emoji) for name, emoji in wanted)])
    return forum


async def _round_posts(client, forum) -> dict[int, object]:
    """Each round's post in the forum, by its number (open or archived)."""
    found = await client.http.get_active_threads(forum.guild.id)
    threads = [await client.fetch_channel(int(each["id"])) for each in found.get("threads", []) if str(each.get("parent_id")) == str(forum.id)]
    threads += [thread async for thread in forum.archived_threads(limit=100)]
    posts = {}
    for thread in threads:
        # "Round 4 · …" or "Design · Round 5": the part that names the round, wherever it is
        for name in thread.name.split(" · "):
            if name.startswith("Round ") and name[6:].isdigit():
                posts.setdefault(int(name[6:]), thread)
                break
    return posts


async def make_forum() -> str:
    """The Design forum: found by DESIGN_FORUM_ID, or made (as the dev bot, which may) and its id
    to be put in .env.dev; its tags added if they are missing. Returns what was done."""
    import discord

    from dotenv import dotenv_values

    async def work(client):
        if client.user.id != config.test_bot_id():
            raise SystemExit("Not the dev bot's account: nothing done.")
        forum_id = _forum_id()
        if forum_id is not None:
            forum = await _with_tags(await _design_forum(client))
            return f"The forum is there; tags: {', '.join(tag.name for tag in forum.available_tags)}"
        near = await client.fetch_channel(int((dotenv_values(config.BASE_DIR / ".env.dev").get("BUGS_CHANNEL_ID") or "0").strip()))
        guild = await client.fetch_guild(near.guild.id)
        tags = [discord.ForumTag(name=name, emoji=emoji) for name, emoji in TAGS]
        forum = await guild.create_forum(DESIGN_FORUM, topic=DESIGN_FORUM_TOPIC, available_tags=tags, reason="Design previews, one post a round")
        return f"Made the forum {forum.name}: put DESIGN_FORUM_ID={forum.id} in .env.dev"

    return await _as_dev_bot(work)


async def post_round(number: int, tag: str) -> str:
    """A new post for one round, tagged; refused when the round has one already."""
    import discord

    from interfaces.discord import render

    found = round_cards(number)
    tag = tag_named(tag)

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await _with_tags(await _design_forum(client))
        if number in await _round_posts(client, forum):
            raise SystemExit(f"Round {number} has a post already: nothing posted.")
        applied = [each for each in forum.available_tags if each.name == tag]
        made = await forum.create_thread(name=round_title(number), content=round_opening(number, tag), applied_tags=applied, allowed_mentions=quiet)
        for label, pieces in found:
            if label:
                await made.thread.send(f"### {label}", allowed_mentions=quiet)
            await made.thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(1)  # paced: well under Discord's rate limit
        return made.thread.jump_url

    return await _as_dev_bot(work)


async def ship(number: int) -> str:
    """Round `number` is Live and the one that was is Retired: the tags of the posts, nothing else."""

    async def work(client):
        forum = await _with_tags(await _design_forum(client))
        by_name = {each.name: each for each in forum.available_tags}
        posts = await _round_posts(client, forum)
        if number not in posts:
            raise SystemExit(f"Round {number} has no post: nothing changed.")
        by_id = {tag.id: tag.name for tag in forum.available_tags}
        now = {each: tag_of(getattr(thread, "_applied_tags", ()), by_id) for each, thread in posts.items()}
        after = shipped(now, number)
        changed = []
        for each, tag in after.items():
            if now.get(each) != tag:
                await posts[each].edit(applied_tags=[by_name[tag]])
                changed.append(f"Round {each}: {now.get(each)} → {tag}")
        return "; ".join(changed) or "nothing to change"

    return await _as_dev_bot(work)


async def round_replies(number: int) -> list[tuple[str, str]]:
    """What people (not bots) said in a round's post, oldest first, word for word. Read only."""

    async def work(client):
        forum = await _design_forum(client)
        thread = (await _round_posts(client, forum)).get(number)
        if thread is None:
            return []
        history = [each async for each in thread.history(limit=500, oldest_first=True)]
        return [(f"{each.created_at.astimezone(config.TIMEZONE):%Y-%m-%d %H:%M}", each.content) for each in history if not each.author.bot and (each.content or "").strip()]

    return await _as_dev_bot(work)


# ---------------------------------------------------------------------------
# Personal routines: Layout A and Layout B, and the Today card, from made-up
# routines (`python -m selftest.preview --routines`), as a post of its own in
# the Design forum, tagged Preview. A short routine (3 items: Brush teeth,
# Floss, a Skincare group of 4 steps) and a long one (12 items, 2 of them
# groups), each card by the list rule (the first three open items in full,
# "+N more", one Done dropdown).
# ---------------------------------------------------------------------------
ROUTINES_TITLE = "Routines layout preview"


def _routines():
    from core import recurrence
    from tasks.habits.rules import AT, GROUP, WINDOW, GuideStep, Habit, Item

    def group(number, name, *steps):
        return Item(number, name, GROUP, tuple(GuideStep(step) for step in steps))

    short = Habit(1, 1, "Morning", recurrence.EVERY_DAY, (
        Item(11, "Brush teeth"), Item(12, "Floss"), group(13, "Skincare", "Cleanser", "Toner", "Serum", "Moisturiser"),
    ), AT, at=time(7, 0))
    long = Habit(2, 1, "Evening", recurrence.EVERY_DAY, (
        Item(21, "Tidy the kitchen"), Item(22, "Lay out clothes"), Item(23, "Pack my bag"), Item(24, "Shower"),
        group(25, "Skincare", "Cleanser", "Toner", "Serum", "Moisturiser"), Item(26, "Brush teeth"), Item(27, "Floss"),
        group(28, "Stretch", "Hamstrings", "Hips", "Shoulders"), Item(29, "Journal"), Item(30, "Read"), Item(31, "Phone on charge"), Item(32, "Lights out"),
    ), WINDOW, start=time(20, 0), end=time(23, 0))
    return short, long


def _routine_days(ticked: set[int]):
    from tasks.habits import rules

    return rules.due(list(_routines()), ticked, _day())


def _today_lines(found, notes_and_todos=True, all_done=False):
    from core.today import Line
    from tasks.habits import rules

    lines = [Line(rules.ICON, f"**{each.habit.name}** · {rules.when_text(each.habit)} · {each.done}/{each.total}", each.starts(), each.ends(), each.finished) for each in found]
    if notes_and_todos:
        lines += [
            Line("⏰", "**Call the bank**", _at(11), note=True), Line("⏰", "**Bins out**", _at(19, 30), note=True),
            Line("📝", "**Pay the power bill** · from yesterday", done=all_done), Line("📝", "**Call the dentist**", done=all_done),
            Line("📝", "**Buy stamps**", done=all_done), Line("📝", "**Book the WOF**", done=all_done),
        ]
    return sorted(lines, key=lambda each: (each.at is None, each.at.timestamp() if each.at else 0))


def routines_layout() -> list[tuple[str, tuple]]:
    """Every message of the routines preview, in the order posted."""
    from core import today
    from tasks.habits import rules

    morning_early = _routine_days({11})  # 7:10 am: Brush teeth done
    evening = _routine_days({11, 12, 13, 21, 22, 23, 24})  # 8:30 pm: Morning done, Evening 4 of 12
    all_done = _routine_days({11, 12, 13, *range(21, 33)})
    found = [
        ("Layout A · one Personal routines card · 7:10 am, Brush teeth done", rules.all_layout(morning_early, _at(7, 10))),
        ("Layout A · 8:30 pm, Morning done, Evening 4 of 12", rules.all_layout(evening, _at(20, 30))),
        ("Layout B · the Today card as the overview · 7:10 am", today.layout(_today_lines(morning_early), _at(7, 10))),
        ("Layout B · Morning's own card, from 7:00 am until it is done", rules.routine_card(morning_early[0], _at(7, 10))),
        ("Layout B · the Today card · 8:30 pm", today.layout(_today_lines(evening), _at(20, 30))),
        ("Layout B · Evening's own card, from 8:00 pm (Morning's is tidied away, done)", rules.routine_card(evening[1], _at(20, 30))),
        ("The Today card · 11:30 pm, Evening not done by the end of its window", today.layout(_today_lines(evening), _at(23, 30))),
        ("The Today card · everything done: one small line", today.layout(_today_lines(all_done, all_done=True), _at(23, 30))),
    ]
    return checked(found)


def routines_opening() -> str:
    return "\n".join([
        f"## {ROUTINES_TITLE}",
        "Personal routines reworked, two ways to show them. Made-up routines: **Morning** at 7:00 am (Brush teeth, Floss, a Skincare group of 4 steps) and **Evening** 8:00 pm to 11:00 pm (12 items, 2 of them groups).",
        "**Layout A**: one Personal routines card holding every routine, a rule between them, the Done dropdowns at the bottom.",
        "**Layout B**: the Today card as the overview, and one card a routine with its Done dropdown right under it, from its time or window until it is done.",
        "-# Each routine follows round 4: the first three open items in full, “+N more”, one Done dropdown (a group's tick is the whole group). The buttons here do nothing. Nothing here is switched on.",
        "**A or B?** And your message was cut off at “Also show the Today card with a…”: what was the rest?",
    ])


async def post_preview(title: str, intro: str, found: list[tuple[str, tuple]], tag: str = PREVIEW) -> str:
    """A post of its own in the Design forum, tagged (Preview unless said)."""
    import discord

    from interfaces.discord import render

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await _with_tags(await _design_forum(client))
        applied = [each for each in forum.available_tags if each.name == tag_named(tag)]
        made = await forum.create_thread(name=title, content=intro, applied_tags=applied, allowed_mentions=quiet)
        for label, pieces in found:
            if label:
                await made.thread.send(f"### {label}", allowed_mentions=quiet)
            if isinstance(pieces, Card) and pieces.embeds:
                # Round 7's messages of embeds (the briefing, the morning news), drawn as live draws them
                await made.thread.send(render.heading(pieces), embeds=render.embeds(pieces), allowed_mentions=quiet)
            elif isinstance(pieces, Card):
                await made.thread.send(pieces.text, allowed_mentions=quiet)
            else:
                await made.thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(1)  # paced: well under Discord's rate limit
        return made.thread.jump_url

    return await _as_dev_bot(work)


PHONE_LINES = 20  # about how many lines of a card one phone screen shows, with a dropdown as two


def phone_note(pieces) -> str:
    """How long a card is on a phone, said under it: its lines and controls, and a screen's worth."""
    lines, controls = _count(pieces)
    tall = lines + 2 * len(design.menus(pieces)) + len(design.buttons(pieces))
    if tall <= PHONE_LINES // 2:
        share = "under half a screen"
    elif tall <= PHONE_LINES * 3 // 4:
        share = "about half a screen"
    elif tall <= PHONE_LINES + 3:
        share = "about a screen"
    else:
        share = f"about {tall / PHONE_LINES:.1f} screens"
    return design.small(f"on a phone: {lines} line{'' if lines == 1 else 's'} and {controls} control{'' if controls == 1 else 's'}, {share}")


def routines_compare() -> list[tuple[str, tuple]]:
    """The reply to the Routines layout preview: A and B side by side at the same moments
    (a mix of to-dos, two routines and two reminders as notes), each labelled and with
    how long it is on a phone under it."""
    from core import today
    from tasks.habits import rules

    morning = _routine_days({11})
    evening = _routine_days({11, 12, 13, 21, 22, 23, 24})
    done = _routine_days({11, 12, 13, *range(21, 33)})
    found = []

    def add(label, pieces):
        found.append((label, pieces))
        found.append(("", (design.Text(phone_note(pieces)),)))

    add("A · 7:10 am · one Personal routines card", rules.all_layout(morning, _at(7, 10)))
    add("B · 7:10 am · the Today card", today.layout(_today_lines(morning), _at(7, 10)))
    add("B · 7:10 am · Morning's own card", rules.routine_card(morning[0], _at(7, 10)))
    add("A · 8:30 pm, part done · one Personal routines card", rules.all_layout(evening, _at(20, 30)))
    add("B · 8:30 pm, part done · the Today card", today.layout(_today_lines(evening), _at(20, 30)))
    add("B · 8:30 pm, part done · Evening's own card (Morning's is gone, done)", rules.routine_card(evening[1], _at(20, 30)))
    add("A · all done · one Personal routines card", rules.all_layout(done, _at(23, 30)))
    add("B · all done · the Today card (the routines' own cards are gone)", today.layout(_today_lines(done, all_done=True), _at(23, 30)))
    return checked(found)


def routines_compare_opening() -> str:
    return "\n".join([
        "## A and B, side by side",
        "The same day in both layouts: two routines (Morning, Evening), four to-dos and two reminders as notes, at 7:10 am, at 8:30 pm part done, and all done. Each card is labelled **A** or **B**, with how long it is on a phone under it.",
        "-# Layout B is what is live now; A is one setting away (ROUTINES_LAYOUT=a). The buttons here do nothing.",
    ])


async def reply_preview(title: str, intro: str, found: list[tuple[str, tuple]]) -> str:
    """More messages in a post of the Design forum that is there already, found by its title."""
    import discord

    from interfaces.discord import render

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await _design_forum(client)
        active = await client.http.get_active_threads(forum.guild.id)
        threads = [await client.fetch_channel(int(each["id"])) for each in active.get("threads", []) if str(each.get("parent_id")) == str(forum.id) and each.get("name") == title]
        threads += [thread async for thread in forum.archived_threads(limit=100) if thread.name == title]
        if not threads:
            raise SystemExit(f"No post called {title!r} in the Design forum: nothing posted.")
        thread = threads[0]
        await thread.send(intro, allowed_mentions=quiet)
        for label, pieces in found:
            if label:
                await thread.send(f"### {label}", allowed_mentions=quiet)
            if isinstance(pieces, Card) and pieces.embeds:
                await thread.send(render.heading(pieces), embeds=render.embeds(pieces), allowed_mentions=quiet)
            elif isinstance(pieces, Card):
                await thread.send(pieces.text, allowed_mentions=quiet)
            else:
                await thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(1)  # paced: well under Discord's rate limit
        return thread.jump_url

    return await _as_dev_bot(work)


# ---------------------------------------------------------------------------
# The week of everything (WEEKLY_ALL, off): the Sunday summary as one card, a
# busy week and a quiet one, each task's line drawn by its own code from
# made-up data (`python -m selftest.preview --weekly`), a post of its own.
# ---------------------------------------------------------------------------
WEEKLY_TITLE = "Design · Weekly summary"


def _week_sections(busy: bool) -> list:
    from core import weekly
    from tasks.calendar import rules as calendar
    from tasks.habits import rules as habits
    from tasks.pills import history
    from tasks.todos.rules import Todo
    from tasks.todos import rules as todos

    sunday = _day()
    monday = sunday - timedelta(days=sunday.weekday())
    sunday = monday + timedelta(days=6)
    found = []

    def add(name, icon, title, week):
        if week is not None:
            found.append(weekly.Section(name, icon, title, week))

    def done(text, on):
        return Todo(0, 1, text, None, monday - timedelta(days=3), days.at(on, time(12)), on)

    if busy:
        add("pills", "💊", "Pills", history.week_line(36, 42, 3, 2, 4, 3))
        add("todos", "📝", "To-dos", todos.week_line(
            [done("Buy stamps", monday), done("Call the plumber", monday + timedelta(days=2)), done("Pay the power bill", monday + timedelta(days=3)),
             done("Water the plants", monday + timedelta(days=5)), done("Book a haircut", sunday),
             Todo(6, 1, "Renew the passport", monday - timedelta(days=4), monday - timedelta(days=9)), Todo(7, 1, "Sort the garage", None, monday + timedelta(days=1)),
             Todo(8, 1, "Return the library books", sunday - timedelta(days=1), monday)], monday, sunday))
        add("habits", "🔁", "Personal routines", habits.week_line([("Morning", [True, True, True, False, True, True, True]), ("Evening", [True, False, True, True, False, True, True])]))
        nxt = monday + timedelta(days=7)
        add("calendar", "🗓️", "Calendar", calendar.week_line([
            (nxt, [days.at(nxt, time(9)), days.at(nxt, time(18))]), (nxt + timedelta(days=1), [None]), (nxt + timedelta(days=2), [days.at(nxt + timedelta(days=2), time(12, 30))]),
            (nxt + timedelta(days=4), [days.at(nxt + timedelta(days=4), time(9)), days.at(nxt + timedelta(days=4), time(15)), days.at(nxt + timedelta(days=4), time(19))]),
        ]))
    else:
        add("pills", "💊", "Pills", history.week_line(7, 7, 0, 0, 0, 7))
        add("todos", "📝", "To-dos", todos.week_line([done("Buy stamps", monday + timedelta(days=2))], monday, sunday))
        add("habits", "🔁", "Personal routines", habits.week_line([("Morning", [True] * 7)]))
        add("calendar", "🗓️", "Calendar", calendar.week_line([(monday + timedelta(days=7 + ahead), []) for ahead in range(7)]))
    return found, monday, sunday


def weekly_cards() -> list[tuple[str, tuple]]:
    from core import weekly

    found = []
    for label, busy in (("A busy week", True), ("A quiet week (the calendar has nothing next week, so it is left out)", False)):
        sections, monday, sunday = _week_sections(busy)
        found.append((label, weekly.layout(sections, monday, sunday)))
        found.append(("", (design.Text(design.small(f"what a phone shows: {weekly.text(sections, monday, sunday).splitlines()[0]}")),)))
    return checked(found)


def weekly_opening() -> str:
    return "\n".join([
        f"## {WEEKLY_TITLE}",
        "The Sunday 7:00 pm summary for everything, not only pills: one card, a box a task with one line for the week and the detail small. A task with nothing to say that week is left out.",
        "**Pills**: taken of all, late (half an hour or more after its time), missed, skipped; the streak small. **To-dos**: done this week, still open, the oldest small. **Personal routines**: the days each was done, as dots. **Calendar**: next week's events counted by day, the first one's time small, never a name.",
        "-# Made-up data, a busy week and a quiet one. Behind WEEKLY_ALL (off): nothing changes on live until you say so. The buttons here do nothing.",
    ])


# ---------------------------------------------------------------------------
# Gym onboarding, sketches only (`python -m selftest.preview --gym`): three ways
# a plan could come in, each with how a session is logged and how the plan is
# changed later, drawn by the real card code from a made-up plan (Push, Pull,
# Legs). Nothing of gym is built: the buttons go nowhere. The options in words
# are docs/drafts/gym-onboarding.md.
# ---------------------------------------------------------------------------
GYM_TITLE = "Design · Gym onboarding sketches"
GYM = Entry("gym", "🏋️", "Gym", "x", ("y",), ())
_GYM_IDS: list[int] = []


def _gym_card(lines, kind="new", question=None, warnings=()):
    from core import confirm

    _GYM_IDS.append(len(_GYM_IDS) + 1)  # a card id each: several cards share one reply
    return confirm.render(GYM, Proposal(lines=tuple(lines), data={}, kind=kind, question=question, warnings=tuple(warnings)), _GYM_IDS[-1]).layout


def _plan_lines(note="", rest=True):
    rest_said = " · rest 2 min" if rest else ""
    return [
        "**Push** · 4 exercises",
        f"Bench press · 3 × 8–12 · 60 kg{rest_said}",
        f"Overhead press · 3 × 8–10 · 40 kg{rest_said}",
        "Dips · 3 × 10 · bodyweight",
        "Triceps pushdown · 3 × 12 · 20 kg",
        "**Pull** · 4 exercises · **Legs** · 4 exercises",
        *([note] if note else []),
    ]


def _workout(now_line: str, which: str) -> tuple:
    """Today's workout, asked for with `gym`, by the relevance rule: the exercise you're on in full with its
    buttons, the next one in full, the rest one small line, what is done one small line."""
    from core.cards import Button, PRIMARY, SUCCESS

    row = (Button("Done as planned", "gym", "done", which, emoji="✅", style=SUCCESS), Button("Different…", "gym", "other", which, emoji="✏️", style=PRIMARY))
    entries = [
        design.Entry(f"**Bench press** · 3 × 8–12 · **60 kg**\n{design.small('last time 60 kg × 10, 9, 8 · Mon 12 Oct')}", design.DUE, row),
        design.Entry(f"**Overhead press** · 3 × 8–10 · **40 kg**\n{design.small('next · last time 40 kg × 10, 9, 9')}", design.QUIET),
    ]
    box = design.topic(design.card_title("🏋️ Push", 0, 4), entries, lines=[design.small(now_line)], tail="later · Dips, Triceps pushdown")
    return design.fit((box,))


def _logged() -> tuple:
    return (design.Text("✅ **Bench press** · 60 kg × 10, 10, 9 · last time 10, 9, 8 ▲ · 3 to go: Overhead press next"),)


def _one_message(*cards) -> tuple:
    """Several sketches in one reply, a small label above each."""
    out: list = []
    for label, pieces in cards:
        out.append(design.Text(design.small(label)))
        out += list(pieces)
    return tuple(out)


def gym_cards() -> list[tuple[str, tuple]]:
    from core.actions import Choice

    a = _one_message(
        ("1 · you attach the sheet (a .csv), or paste its rows: the card shows what was read", _gym_card(_plan_lines("-# Columns not used: Tempo · Load ❓ → weight"))),
        ("2 · `gym` on a training day: today's workout in the hub", _workout("Push is next in turn · Pull was Wed 14 Oct", "a")),
        ("3 · “bench 60 for 10, 10, 9”, or Done as planned", _logged()),
        ("4 · later: attach the new sheet, and only what changed is shown", _gym_card(["**Push**", "Bench press · weight · 60 kg → 62.5 kg", "➕ Face pulls · 3 × 15 · 10 kg"], kind="change")),
    )
    b = _one_message(
        ("1 · “set up my gym plan”: a short guided setup, one question at a time", _gym_card(["**Your plan** · workouts in turn"], question=Question("How many workouts do you rotate through?", (Choice("2", {}), Choice("3", {}), Choice("4", {}), Choice("5", {}))))),
        ("2 · you type the names (“push, pull, legs”), then a workout's exercises, a line each", _gym_card(["**Push** · step 2 of 4", "Bench press · 3 × 8–12 · 60 kg", "Overhead press · 3 × 8–10 · 40 kg", "Dips · 3 × 10 · bodyweight", "Triceps pushdown · 3 × 12 · 20 kg"], question=Question("Anything else in Push? Say it, or press Next.", (Choice("Next", {}),)))),
        ("3 · logging is the same as A", _workout("Push is next in turn", "b")),
        ("4 · later, in words: “add face pulls to pull, 3 x 15 at 10”", _gym_card(["**Pull**", "➕ Face pulls · 3 × 15 · 10 kg"], kind="change")),
    )
    c = _one_message(
        ("1 · one message: “my gym plan: push: bench 3x8-12 60, ohp 3x8-10 40, dips 3x10, pushdowns 3x12 20. pull: … legs: …”", _gym_card(_plan_lines("-# ❓ dips: no weight said, so bodyweight", rest=False))),
        ("2 · logging is the same as A", _workout("Push is next in turn", "c")),
        ("3 · later, in words: “bench is 62.5 now”", _gym_card(["**Push**", "Bench press · weight · 60 kg → 62.5 kg"], kind="change")),
    )
    return checked([("A · Attach your spreadsheet", a), ("B · A short guided setup", b), ("C · Say it in words", c)])


def gym_opening() -> str:
    return "\n".join([
        f"## {GYM_TITLE}",
        "Three ways your gym plan could get into the bot, and how you'd use it day to day. Each reply below is one option: setting up, today's workout, logging a whole exercise at once (question 28), and changing the plan later.",
        "**A** · attach your spreadsheet (or paste its rows): the bot reads it and shows a card to confirm. **B** · a short guided setup, one question at a time. **C** · describe the plan in one message.",
        "-# Sketches drawn by the bot's own card code from a made-up plan (Push, Pull, Legs). Nothing of gym is built; the buttons do nothing. The options in full, with what could go wrong, are in docs/drafts/gym-onboarding.md; questions 76 to 79.",
    ])


# ---------------------------------------------------------------------------
# The diary (DIARY_ENABLED, off): `python -m selftest.preview --diary`, a post
# of its own. Made-up entries only, drawn by the diary's own words and buttons.
# ---------------------------------------------------------------------------
DIARY_TITLE = "Design · Diary"


def diary_cards() -> list[tuple[str, tuple]]:
    from core import today as today_card
    from core.today import Line
    from tasks.diary import mood, rules
    from tasks.diary.rules import Entry

    day = _day()
    happy = Entry(1, 1, day, "Made-up: finished the essay at last, then a long walk.", "three", "good", notes=1)
    plain_entry = Entry(2, 1, day, "Made-up: a long day of meetings.", notes=1)

    def line_card(text, row=()):
        return (design.Text(text), *((design.Row(tuple(row)),) if row else ()))

    week = [Entry(10 + at, 1, day - timedelta(days=at), "Made-up words.", "three", key, notes=1) for at, key in ((1, "good"), (2, "ok"), (3, "good"), (5, "bad"))]
    today_lines = [Line("🔁", "**Evening**", _at(20), _at(23)), Line("📔", "**Diary** · not yet"), Line("⏰", "**Put the bins out**", _at(21), note=True)]
    found = [
        ("“today was good, finally finished the essay”: the mood from the words, on the line (no words of the entry on it)", line_card(rules.saved_line(happy, 4))),
        ("“a long day of meetings”: no mood clear from it, so the line asks, a blurple button a mood", line_card(f"{rules.saved_line(plain_entry, 4)}\n-# how was it?", mood.buttons("diary", "mood", day.isoformat()))),
        ("9:00 pm, nothing written today: one gentle ask at the bottom of the hub, once a day, never again that day", line_card(rules.ASK, mood.buttons("diary", "mood", day.isoformat()))),
        ("The Today card: one line, written or not yet (with its mood once written)", today_card.layout(today_lines, _at(19))),
        ("The briefing (round 5): one line in the overview box, the streak and yesterday's mood", (design.topic(design.card_title("🗓️ The day"), lines=["💊 **Pills** · 6 doses · first 7:00 am", "📔 **Diary** · streak 4 · yesterday 😊"], status=design.QUIET),)),
        ("“show this week's diary”: a line a day with its mood, never the words", line_card(rules.span_answer(week, rules.week_of(day), day, "This week"))),
        ("“what did I write yesterday?”: that day, the words only because they were asked for", line_card(rules.day_answer(week[0], week[0].day, day, words=True))),
        ("“how was my mood this month?”", line_card(rules.mood_answer(week, rules.month_of(day), f"{day:%B}"))),
    ]
    return checked(found)


def diary_opening() -> str:
    return "\n".join([
        f"## {DIARY_TITLE}",
        "Your own words about your day, sent in #inbox or a DM. Several messages on one day add to one entry; the day ends at 4:00 am, so just after midnight still counts for the evening before.",
        "**Mood:** Good, OK or Bad, from the words when they make it clear, otherwise three buttons; changed in words or by button, with Undo. One small mood scale, so it can change later (the number of levels, a score, or off) and old entries still read.",
        "**Evening:** if nothing is written by 9:00 pm, one gentle ask in the hub. **Streak:** days in a row with an entry, in the briefing and the week of everything. Nothing is ever said about missing a day.",
        "**Private:** the words stay in the database; no line, notification, log or status line shows them.",
        "-# Made-up entries only. Behind DIARY_ENABLED (off). The buttons here do nothing. Questions 80 to 85.",
    ])


# ---------------------------------------------------------------------------
# The morning news (READING_ENABLED, off; 21 Oct): `python -m selftest.preview --news`, a post of its own.
# Round 7's second message drawn by the real code (tasks/briefing/embeds.py, tasks/reading/news.py) from
# made-up headlines only: an ordinary weekday, a Monday, a quiet day with no wildcard, a day with a topic empty.
# ---------------------------------------------------------------------------
NEWS_TITLE = "Design · Morning news"
NEWS_ENTRY = Entry("reading", "📰", "Morning news", "x", ("y",), ())
_MADE_UP = {
    "world_politics": ["Made-up: a northern republic calls a snap election after its coalition splits", "Made-up: two neighbours sign a border pact after a decade of talks"],
    "nz_politics": ["Made-up: parliament passes the water reform bill on a split vote", "Made-up: a minister steps down over a report on school funding"],
    "world": ["Made-up: an earthquake shakes an island chain, thousands without power", "Made-up: a river delta braces for its worst floods in fifty years"],
    "tech": ["Made-up: a chip maker unveils a processor it says is twice as fast", "Made-up: a phone maker recalls a battery pack over overheating"],
    "ai": ["Made-up: a lab releases an open reasoning model anyone can run", "Made-up: a regulator drafts the first rules for chatbots in schools"],
    "nz_money": ["Made-up: the Reserve Bank holds the OCR, signals cuts next year", "Made-up: house prices slip for a sixth month as listings climb"],
    "webdev": ["Made-up: a widely used package registry patches a serious security hole"],
}
_TLDR = {
    "world_politics": "The coalition split over the budget, so voters go to the polls in six weeks. Worth a read for what it means for the region's trade talks.",
    "nz_politics": "The bill moves water services to four regional bodies from next July. It matters for rates bills and who answers for outages.",
    "world": "A strong quake cut power across the islands overnight. No deaths reported so far; aid flights are being readied from Auckland.",
    "tech": "The new processor is due in laptops next spring. The speed claim is the company's own, so the independent tests are the thing to watch.",
    "ai": "The model's weights are free to download and it runs on one good graphics card. It could change what small teams can build cheaply.",
    "nz_money": "The OCR stays at 3.5 percent, with cuts pencilled in for next year. Fixed mortgage rates may ease before then, banks say.",
    "webdev": "A flaw let attackers publish fake versions of popular packages. Update your lockfiles today if you install from it.",
}


def _news(day, picks) -> list:
    from tasks.reading.news import Story

    return [Story(f"https://example.com/made-up/{topic}/{number}", _MADE_UP[topic][number], f"Made-up {topic}", topic, _TLDR[topic] if number == 0 else _TLDR[topic].split(".")[0] + ".") for topic, number in picks]


def _message_two(day, stories, todos=True):
    from core.actions import PREPARED, TODO, TRACKING, DayItem
    from tasks.briefing import embeds
    from tasks.reading import news

    items = [DayItem(TODO, "Buy stamps"), DayItem(TODO, "Call the plumber", state="taken")] if todos else []
    items += [DayItem(TRACKING, "Diary · Streak: 4 days", icon="📓")]
    items.append(DayItem(PREPARED, "", icon="📰", title="Morning news", fields=news.fields(stories, "📰 Morning news")))
    return embeds.everything_else(items)


def news_cards() -> list:
    from core import confirm
    from core.actions import Proposal
    from tasks.reading import news

    day = _day()
    weekday = _news(day, [("world_politics", 0), ("nz_politics", 0), ("world", 0), ("tech", 0), ("ai", 0), ("nz_money", 0), ("nz_politics", 1), ("webdev", 0)])
    monday = _news(day, [("world_politics", 1), ("nz_politics", 1), ("world", 1), ("tech", 1), ("ai", 1), ("nz_money", 1), ("world", 0), ("world_politics", 0)])
    quiet = _news(day, [("world_politics", 0), ("nz_politics", 0), ("world", 0), ("tech", 0), ("ai", 0), ("nz_money", 0), ("world", 1)])
    empty = _news(day, [("world_politics", 0), ("nz_politics", 0), ("world", 0), ("tech", 0), ("nz_money", 0), ("nz_politics", 1)])
    housing = next(each for each in weekday if each.topic == "nz_money")
    steer = news.changes(news.Prefs(), news.steered(news.Prefs(), less="ai", like=housing))
    another = news.another_line(_news(day, [("tech", 1)])[0])
    return [
        ("An ordinary weekday: one a topic, then two extras (here NZ politics, and the web development wildcard on a day with a security hole). In round 7's second message, after the to-dos and the diary", _message_two(day, weekday)),
        ("A Monday: since Saturday 5:30 am, so the weekend's biggest stories; no wildcard", _message_two(day, monday, todos=False)),
        ("A quiet day: seven, one a topic and one extra, no wildcard. The news alone is enough for the second message to be sent", _message_two(day, quiet, todos=False)),
        ("A day with a topic empty (AI had nothing new): six and an extra, never padded", _message_two(day, empty, todos=False)),
        ("“another one”: the next best story not shown, as a reply", Card(another)),
        ("“less AI”, then “more like the housing one”: a card first, Save keeps it for every later pick", confirm.render(NEWS_ENTRY, Proposal(lines=tuple(steer), data={}, kind="change"), 1).layout),
    ]


def news_reply_intro() -> str:
    return "\n".join([
        "## The hierarchy version (21 Oct)",
        "From your look on your phone: “It's too cluttered in its ordered list layout, it needs more hierarchy”. The numbered list is gone: "
        "**a field a topic**, full width, in a fixed order (NZ politics, Housing and money, World news, World politics, Tech, AI, Web dev), "
        "named in plain words; each story its headline in bold as the link, then its TL;DR small under it; a topic with two has both, "
        "the bigger first. A topic with nothing that day has no field.",
        "**In words, without numbers:** “more like the housing one”, “more like the one about the water reform”, “less AI”, “another one”. "
        "“more like 3” now asks which, by topic.",
        "📱 Please look again on your phone. The same four days as above, made-up headlines only.",
    ])


def news_opening() -> str:
    return "\n".join([
        f"## {NEWS_TITLE}",
        "The daily read and the news headlines are now **one morning news**: 7 or 8 stories a day, one for each of **world politics**, **NZ politics**, **world news**, **tech**, **AI** and **NZ housing and money** (house prices, interest rates, the OCR, the economy), then one or two extras for the day's biggest news. **Web development** is a wildcard: only on a day with something notable.",
        "**Each story:** the headline in bold is the link, the topic in italics, then a TL;DR of about 30 words: what happened, and why you might read it. Paywalled articles are never picked; at most one story about US politics alone a day.",
        "**Where:** round 7's second message, one purple embed after the to-dos and the diary; 👍 on it says it was a good set, which the next picks lean on. Before round 7 it is not in the hub: say “the news”.",
        "**In words:** another one, more like 3, less AI, more NZ politics, skip housing tomorrow, more US politics, what do you know about my news, add or remove a source.",
        "📱 **Please look at this on your phone:** the embed is built for a phone's width. A screenshot of it there, or a word on what is too long or too dense, is the feedback this round needs.",
        "-# Made-up headlines and links only. Behind READING_ENABLED. The buttons here do nothing.",
    ])


# ---------------------------------------------------------------------------
# The smart inbox (SMART_INBOX): `python -m selftest.preview --inbox`, a post of
# its own. Made-up items only, drawn by core/smartinbox.py's own card; each
# item's lines are the words its task's own code wrote for them in the tests.
# ---------------------------------------------------------------------------
INBOX_TITLE = "Design · Smart inbox"


def inbox_cards() -> list[tuple[str, tuple]]:
    from core import smartinbox
    from core.cards import Button

    before = config.DESIGN_ROUND
    config.DESIGN_ROUND = 5
    try:
        entries = [Entry("nudges", "⏰", "x", ("y",), (), label="Reminders"), Entry("todos", "📝", "x", ("y",), (), label="To-dos"),
                   Entry("calendar", "🗓️", "x", ("y",), (), label="Calendar")]
        rego_asks = {"task": "nudges", "lines": ["**Renew rego** · at ❔", "❓ At what time?"], "ready": False}
        rego = {"task": "nudges", "lines": ["**Renew rego** · Fri 6 Nov at **9:00 am**", "-# next: Fri 6 Nov at 9:00 am"], "ready": True}
        mum = {"task": "nudges", "lines": ["**Call Mum** · Sun 8 Nov at **2:00 pm**", "-# next: Sun 8 Nov at 2:00 pm"], "ready": True}
        milk = {"task": "todos", "lines": ["**Need milk** · any day"], "ready": True}
        dentist = {"task": "calendar", "lines": ["**Dentist**", "Thu 5 Nov · `3:00 pm` to `4:00 pm` · 1 hour", "-# on the Bot calendar"], "ready": True}
        booked = {"task": "calendar", "lines": ["**Made-up Dental Clinic**", "Thu 5 Nov · `3:00 pm` to `3:45 pm` · 45 minutes", "-# on the Bot calendar"], "ready": True}
        renewal = {"task": "nudges", "lines": ["**Car registration** · Sat 14 Nov 2026", "Yearly · told 30 days, 7 days, 1 day before", "-# in your reminders"], "ready": True}
        saved = "\n".join([
            "✅ Saved · 4 of 4", "✅ Saved · ⏰ **Renew rego** · Fri 6 Nov at **9:00 am** · next 9:00 am",
            "✅ Saved · ⏰ **Call Mum** · Sun 8 Nov at **2:00 pm** · next 2:00 pm", "✅ Added · 📝 **Need milk**",
            "🗓️ Added · **Dentist** · Thu 5 Nov · `3:00 pm` to `4:00 pm` · 1 hour",
        ])
        undo = design.Row((Button("Undo", smartinbox.CARDS, "undo", "1", emoji="↩️", style="primary"),))

        def drawn(items):
            return smartinbox.render(items, entries, 1).layout

        found = [
            ("“renew rego by Friday, call Mum Sunday 2pm, need milk, dentist Thursday 3pm”: one card, each thing where it will go with its day and time. The reminder with no time asks on the card, and Save leaves it out until it is answered", drawn([rego_asks, mum, milk, dentist])),
            ("“make the rego one a reminder at 9am Friday”: that line is read again (no other), the card redrawn in place of the old one, and Save is for all four", drawn([rego, mum, milk, dentist])),
            ("Save all: each thing saved by its own task, in its own words, then Undo for a while", (design.Text(saved), undo)),
            ("A screenshot of a booking confirmation, sent in #inbox: an event, with its day, time and length from the picture", drawn([booked])),
            ("A renewal letter as a PDF: an expiry with its date, yearly, and the nudges before it", drawn([renewal])),
            ("A CSV that is plainly a gym plan: its rows kept for the gym task to come (nothing of gym is built yet)", drawn([{"task": "gym_plan", "lines": ["🏋️ Gym · **gym plan** · 5 rows kept for the gym task to come"], "ready": True}])),
            ("A photo with nothing to keep: what it saw, in one line", (design.Text(f"{smartinbox.NOTHING_FOUND}: an image with a blue circle and a red square"),)),
        ]
    finally:
        config.DESIGN_ROUND = before
    return checked(found)


def inbox_opening() -> str:
    return "\n".join([
        f"## {INBOX_TITLE}",
        "Send whatever you have: several things in one message, or a photo, screenshot, PDF or CSV in #inbox or a DM. The bot splits it into things, gives each to the task that takes it (to-dos, reminders, expiries, calendar events, routine steps, a pill taken, the diary) and shows **one card** with every item, where it goes and its day and time.",
        "**Save all** (green) saves each with its own task; **Cancel** (grey) saves nothing; say what to change (“make the rego one a reminder at 9am Friday”) and only that line is read again. **Undo** after Save takes each back. Something it can't place, or a time a task needs, is asked on the card and left out of Save until answered.",
        "**Files:** read once and not kept, except a gym plan's rows (for the gym task to come). What a file holds never goes in a log, and the card's first line never names anything, so a lock screen shows nothing private. A medicine label is only ever a suggested pill to add, never saved without Save.",
        "**One thing** in a message works exactly as before; a question is never sorted.",
        "-# Made-up items only. Behind SMART_INBOX. The buttons here do nothing.",
    ])


# ---------------------------------------------------------------------------
# The brainstorm (docs/BRAINSTORM.md): `python -m selftest.preview --brainstorm`,
# a post of its own. The top 10, each a reply with a two-line sketch of how it
# would look in the hub. Nothing of these is built; made-up names only.
# ---------------------------------------------------------------------------
BRAINSTORM_TITLE = "Design · Brainstorm"
BRAINSTORM_TOP = (
    ("32 · Hours by message", "“2h on the Made-up Co site” after you finish:", "⏱️ **Made-up Co** · 2h logged · 9h this week\n-# Sunday: the week's hours by client"),
    ("1 · Plan my day", "“plan my day”:", "☀️ **Your day** · 8:00 Pill B · 9:00 standup · free 9:15 to 12:30 · 12:30 lunch\n-# then 3 more, and 2 to-dos with no time"),
    ("2 · Free time finder", "“when am I free for 2 hours this week?”:", "🗓️ **Free for 2 hours** · Tue 6:00 pm · Thu 7:30 pm · Sat all afternoon\n-# from every calendar, after work"),
    ("25 · Bin day", "Said once, “bins Tuesday, recycling every other week”:", "⏰ **Bins out tonight** · rubbish and recycling\n-# Monday 8:00 pm, the evening before"),
    ("38 · Birthdays", "Said once, “Sam's birthday 3 May”:", "🎂 **Sam's birthday** · Sat 3 May, in a week\n-# your gift note: a book on climbing"),
    ("26 · The usual", "“need the usual and eggs”:", "📝 To-dos · **Milk**, **Bread**, **Coffee**, **Eggs** · any day\n-# the usual: milk, bread, coffee (change it in words)"),
    ("9 · Draft the email", "“draft an email to the landlord about the leak”:", "✉️ **Draft** · Hi, the kitchen tap has been leaking since Monday…\n-# copy it, or say what to change"),
    ("13 · Pill refill countdown", "Said once, “I have 60 of Pill A”:", "💊 **Pill A** · order more by Wed 12 Nov\n-# 14 days left at 3 a day: one line in the briefing a week ahead"),
    ("23 · Flat expenses", "“I paid the power 180, split three ways”:", "🏠 **Power** · $180 · Made-up A and Made-up B owe you $60 each\n-# “who owes me?” any time"),
    ("19 · Subscriptions from a bank CSV", "A bank CSV sent in #inbox:", "💳 **7 subscriptions** · $94 a month · next: Made-up Music Fri 21 Nov\n-# each one an expiry, if you say so"),
)


def brainstorm_cards() -> list[tuple[str, tuple]]:
    found = [(f"{name} · {how}", (design.Text(sketch),)) for name, how, sketch in BRAINSTORM_TOP]
    found.append(("", (design.Text("**Which of these should I build first?** Reply with the numbers, most wanted first (for example “32, 23, 13”)."),)))
    return checked(found)


def brainstorm_opening() -> str:
    return "\n".join([
        f"## {BRAINSTORM_TITLE}",
        "48 ideas for taking admin off your plate, in docs/BRAINSTORM.md, grouped (daily planning, admin and paperwork, health, money, home and flat, work and freelance, people and social, learning, fun), each with how you'd use it, its value to you, the effort and what it needs from you.",
        "**Below: the top 10 by value for effort**, each with a two-line sketch of how it would look in the hub. Nothing of these is built.",
        "-# From Claude's own knowledge of assistants and life-admin apps (no web search). Made-up names only. No ideas inbox and no uni deadlines, as asked.",
    ])


def _number_after(args: list[str], flag: str) -> int:
    value = args[args.index(flag) + 1] if args.index(flag) + 1 < len(args) else ""
    if not value.isdigit() or int(value) not in design.ROUNDS:
        raise SystemExit(f"{flag} takes a round that was built: one of {', '.join(map(str, design.ROUNDS))}. Nothing done.")
    return int(value)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--diary" in args:
        found = diary_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(DIARY_TITLE, diary_opening(), found)))
        return 0
    if "--brainstorm" in args:
        found = brainstorm_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(BRAINSTORM_TITLE, brainstorm_opening(), found)))
        return 0
    if "--inbox" in args:
        found = inbox_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(INBOX_TITLE, inbox_opening(), found)))
        return 0
    if "--news-reply" in args:
        found = news_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(reply_preview(NEWS_TITLE, news_reply_intro(), found)))
        return 0
    if "--news" in args:
        found = news_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(NEWS_TITLE, news_opening(), found)))
        return 0
    if "--gym" in args:
        found = gym_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(GYM_TITLE, gym_opening(), found)))
        return 0
    if "--weekly" in args:
        found = weekly_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(WEEKLY_TITLE, weekly_opening(), found)))
        return 0
    if "--routines-compare" in args:
        found = routines_compare()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(reply_preview(ROUTINES_TITLE, routines_compare_opening(), found)))
        return 0
    if "--routines" in args:
        found = routines_layout()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_preview(ROUTINES_TITLE, routines_opening(), found)))
        return 0
    if "--forum" in args:
        print(asyncio.run(make_forum()))
        return 0
    if "--post-round" in args:
        number = _number_after(args, "--post-round")
        tag = args[args.index("--tag") + 1] if "--tag" in args and args.index("--tag") + 1 < len(args) else PREVIEW
        if "--check" in args:
            print(f"{len(round_cards(number))} messages built for round {number}, each within one message.")
            return 0
        print("Posted:", asyncio.run(post_round(number, tag)))
        return 0
    if "--ship" in args:
        print(asyncio.run(ship(_number_after(args, "--ship"))))
        return 0
    if "--replies-round" in args:
        found = asyncio.run(round_replies(_number_after(args, "--replies-round")))
        for when, said in found:
            print(f"--- {when}\n{said}")
        print(f"{len(found)} replies in that round's post.")
        return 0
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
