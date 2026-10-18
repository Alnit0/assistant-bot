"""Two previews of 17 Oct, posted in the Design forum as the dev bot, made-up data only:

    python -m selftest.tonight --plan [--check]                Design · Plan my day and birthdays
    python -m selftest.tonight --round-6 day.json [--check]    Design · Round 6 timeline

Every card is drawn by the bot's own code (core/planning.py, core/confirm.py, tasks/nudges/birthdays.py,
core/weekview.py, tasks/diary, core/timeline.py) from made-up items. Round 5 in the round 6 post is a real run
of the dev bot (`python -m selftest.day`, its file named); round 6 is core/timeline.py, a preview only.
"""
import asyncio
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from core import config, design, planning, timeline, weekview
from core import day as days
from core.planning import Piece

PLAN_TITLE = "Design · Plan my day and birthdays"
ROUND_6_TITLE = "Design · Round 6 timeline"
DAY = date(2026, 10, 19)  # a Monday, made up


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return days.at(day, time(hour, minute))


def _in_round(number: int, build):
    before = config.DESIGN_ROUND
    config.DESIGN_ROUND = number
    try:
        return build()
    finally:
        config.DESIGN_ROUND = before


# ---------------------------------------------------------------------------
# Plan my day, birthdays, the diary's ask, the week view
# ---------------------------------------------------------------------------
def _day_pieces(day: date = DAY) -> list[Piece]:
    return [
        Piece("pills", "p1.1", "💊", "Pill A", at(8, 0, day), fold="dose"),
        Piece("pills", "p1.2", "💊", "Pill A", at(13, 0, day), fold="dose"),
        Piece("pills", "p2.1", "💊", "Pill B", at(8, 0, day), fold="dose"),
        Piece("calendar", "e1", "📅", "Made-up standup", at(9, 0, day), at(9, 15, day)),
        Piece("calendar", "e2", "📅", "Made-up lunch", at(12, 30, day), at(13, 30, day)),
        Piece("nudges", "n1", "⏰", "Made-up call", at(17, 0, day)),
        Piece("habits", "h1", "🔁", "Evening", at(20, 0, day), at(20, 30, day), note="8:00 pm to 11:00 pm", fold="routine"),
        Piece("nudges", "e1", "🪪", "Made-up passport due", all_day=True),  # birthdays are never a calendar item (19 Oct)
        Piece("todos", "t1", "📝", "Write the essay", flexible=True, rank=planning.OVERDUE),
        Piece("todos", "t2", "📝", "Weekly shop", flexible=True, rank=planning.TODAY),
        Piece("todos", "t3", "📝", "Laundry", flexible=True),
        Piece("todos", "t4", "📝", "Email Sam", flexible=True),
    ]


def _plan_card(plan: planning.Plan, *, also: str = "", warnings=(), extra=()) -> tuple:
    from core import confirm
    from core.actions import Choice, Entry, Proposal

    entry = Entry("plan", planning.ICON, "x", ("y",), (), label="Plan my day")
    lines = (*planning.lines(plan, DAY), *extra)
    proposal = Proposal(lines=lines, data={}, warnings=tuple(warnings), kind="new", can_save=bool(plan.slots), also=(Choice(also, {}),) if also and plan.slots else ())
    return confirm.render(entry, proposal, 1).layout


def plan_cards() -> list[tuple[str, tuple]]:
    from core import cards, today as today_card
    from core.cards import Button, Card
    from core.today import Line
    from tasks.diary import mood, plain as diary_plain, rules as diary_rules
    from tasks.nudges import birthdays
    from tasks.nudges.birthdays import Birthday

    lengths = {"t1": 90, "t2": 60, "t3": 60, "t4": 15}
    start, end = planning.window(DAY, at(7, 50))
    first = planning.place(DAY, _day_pieces(), lengths, start, end)
    out = planning.place(DAY, _day_pieces(), lengths, start, end, out=[(at(14), at(16))], parts={"t3": "evening"})
    full = planning.place(DAY, [Piece("calendar", "e9", "📅", "Made-up conference", at(6), at(23)), *_day_pieces()[8:]], lengths, start, end)
    blocks = len(out.slots)
    today_lines = [
        Line("🔁", "**Evening** · 8:00 pm to 11:00 pm · 0/3", at(20), at(23)),
        *(Line(slot.piece.icon, f"**{slot.piece.text}** · planned", slot.start, slot.end) for slot in out.slots),
        Line("⏰", "**Made-up call**", at(17), note=True),
        Line("📅", "**Made-up standup**", at(9), at(9, 15), event=True),
    ]
    today_lines.sort(key=lambda each: each.at)
    mum = Birthday(1, 1, "Mum", 3, 12, 1966)
    sam = Birthday(2, 1, "Sam", 6, 3, 1995)
    friend = Birthday(3, 1, "Made-up Friend", 2, 29, 1992)
    own = Birthday(4, 1, "", 2, 22, mine=True)
    tom = Birthday(5, 1, "Tom", 3, 2, relation="brother")
    ahead = date(2027, 2, 20)
    box_lines = [design.small(birthdays.box_line(each, ahead)) for each in birthdays.coming([mum, friend, own, tom], ahead)]
    listed = [mum, sam, friend, own, tom]
    list_lines = []
    for each in sorted(listed, key=lambda each: birthdays.days_left(each, ahead)):
        list_lines += [birthdays.list_line(each, ahead), *([design.small("🎁 a scarf"), design.small("🎁 the climbing book")] if each is mum else [])]
    this = [weekview.of(day, _day_pieces(day) if day.weekday() in (0, 2) else _day_pieces(day)[:3]) for day in weekview.week_of(DAY)]
    following = [weekview.of(day, _day_pieces(day)[:3] + ([_day_pieces(day)[5]] if day.weekday() == 3 else [])) for day in weekview.week_of(DAY + timedelta(days=7))]
    ask_row = diary_plain.ask_row(DAY)
    found = [
        ("“plan my day” at 7:50 am: the to-dos placed around what is fixed (overdue first), 15 minutes between things, the free time small, one summary line. Save (green), Put it on my calendar (blurple), Cancel (grey)",
         _plan_card(first, also="Put it on my calendar")),
        ("…then “I'm out 2 to 4” and “move laundry to the evening”: the card made again, nothing saved yet",
         _plan_card(out, also="Put it on my calendar")),
        ("Put it on my calendar: the card says it first; its Save keeps the plan and adds the blocks to the Bot calendar",
         _plan_card(out, also="Without the calendar", extra=(design.small(f"Save adds {blocks} blocks to the Bot calendar too"),))),
        ("A day with no free time: nothing placed, said, and only Cancel",
         _plan_card(full, warnings=("No free time between 8:00 am and 10:00 pm: nothing could be placed",))),
        ("After Save: the planned times on the Today card",
         _in_round(5, lambda: today_card.layout(today_lines, at(7, 55)))),
        ("“Mum's birthday 12 March 1966”: a card first, the age she is turning, and the Bot calendar's yearly all-day event",
         _birthday_card(mum)),
        ("29 February: on the 28th in a year without one (said on the card)",
         _birthday_card(friend, ("29 February: on the 28th in a year without one",))),
        ("“my birthday is 22 February”: your own, never a person called My",
         _birthday_card(own)),
        ("From 14 days before, low in the briefing below The day: a small grey box, a line each counting down, soonest first. No post, no ping, no button",
         (design.topic(design.card_title("🗓️ The day"), lines=["💊 **Pills** · 6 doses · first 7:00 am", "⏰ **Reminders** · 2 today · first 10:30 am"], status=design.QUIET),
          design.topic(design.card_title("🎂 Upcoming birthdays"), lines=box_lines, status=design.QUIET))),
        ("#calendar, pinned: everyone in order of who is next, the days to go, the age turning, gift notes small; edited in place",
         design.fit((design.topic(design.card_title(birthdays.LIST_TITLE), lines=list_lines, status=design.QUIET),))),
        ("“upcoming birthdays”: the next 90 days, soonest first",
         design.fit((design.topic(design.card_title("🎂 Birthdays coming up"), [design.Entry(birthdays.when_line(each, date(2027, 2, 20)), design.QUIET) for each in (mum, sam)], status=design.QUIET),))),
        ("#calendar, pinned: this week, a box a day, today highlighted, past days faint, doses and routines counted",
         weekview.this_week(this, DAY + timedelta(days=2))),
        ("#calendar, below it: next week, a line a day", weekview.next_week(following, DAY + timedelta(days=2))),
        ("The diary at 9 pm: 📔 How was today?, with ✍️ Write (a form with one long box) and the three moods. A reply to it is the entry",
         (design.Box(design.DECISION, (design.Text(diary_rules.ASK + "\n" + design.small("Say “plan tomorrow” to plan it")), design.Row(ask_row))),)),
        ("A mood with no words: one small offer, on that line only, never again",
         (design.Box(design.QUIET, (design.Text("📔 Saved · 😊 Good · streak 5\n-# a few words too?"), design.Row((diary_plain.write_button(DAY, diary_plain.ADD_LABEL), Button("Undo", "diary", "undo", "x", emoji="↩️", style=cards.PRIMARY))))),)),
        ("The diary's one line, in the briefing's The day only: the streak, and whether today is written (not yet from 6 pm). Never a past mood, never the Today card",
         (design.topic(design.card_title("🗓️ The day"), lines=["💊 **Pills** · 6 doses · first 7:00 am", "📔 **Diary** · streak 5 · not yet"], status=design.QUIET),)),
    ]
    return _checked(found)


def _birthday_card(birthday, warnings=()) -> tuple:
    from core import confirm
    from core.actions import Entry, Proposal
    from tasks.nudges import birthdays

    entry = Entry("birthdays", birthdays.ICON, "x", ("y",), (), label="Birthdays")
    lines = (birthdays.when_line(birthday, DAY), f"Shown {birthdays.told_text(birthday)}", birthdays.calendar_line(True))
    return confirm.render(entry, Proposal(lines=lines, data={}, warnings=tuple(warnings)), 1).layout


def plan_opening() -> str:
    return "\n".join([
        f"## {PLAN_TITLE}",
        "**Plan my day** (say plan my day, plan tomorrow, replan, what should I do now?): your open to-dos placed in the free time between 7:00 am and 10:00 pm around everything fixed (events, doses, reminders, routines), overdue first, 15 minutes between things, never more than 6 hours of them and always one free block left. Change it in words before saving: I'm out 2 to 4, move laundry to the evening, drop the shopping, make the essay 2 hours, I start at 8 tomorrow. Save puts the times on the Today card; Put it on my calendar adds blocks to the Bot calendar (a card first). It never pings.",
        "**Birthdays** (in reminders): Mum's birthday 12 March, Sam 3 June 1995, gift idea for Mum: a scarf. Never posted or pinged (19 Oct): from 14 days before a small grey Upcoming birthdays box low in the briefing; one pinned list in #calendar; the day itself is the Bot calendar's yearly all-day event, never a calendar item in the hub; upcoming birthdays, when is Mum's birthday. No name or gift note is ever in a log.",
        "**Also tonight:** the week in #calendar, and the diary's Write and its one line.",
        "-# Made-up items only. The buttons here do nothing.",
    ])


def _checked(found: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:60]}: {wrong}")
    return found


# ---------------------------------------------------------------------------
# Round 6: the timeline hub, at 7 am, 12 pm and 8 pm, a busy day too
# ---------------------------------------------------------------------------
def _round_6_day(now: datetime, busy: bool = False) -> tuple[timeline.Header, list[timeline.Item], list[str]]:
    """The made-up day of `python -m selftest.day` (four pills, two routines, reminders, events, to-dos), as
    round 6 would show it at `now`; busy adds a work day 8 to 5 and more."""
    T = timeline
    h = now.astimezone(config.TIMEZONE).hour + now.astimezone(config.TIMEZONE).minute / 60
    taken_a1 = at(9, 15)
    items = [
        T.Item(T.DOSE, "💊", "Pill B", at(7), done=h >= 7.1, done_at=at(7, 5), button="Taken" if 7 <= h < 7.1 else ""),
        T.Item(T.DOSE, "💊", "Pill A (dose 1 of 3)", at(8), done=h >= 9.25, done_at=taken_a1, button="Taken" if 8 <= h < 9.25 else ""),
        T.Item(T.DOSE, "💊", "Pill A (dose 2 of 3)", at(12, 15) if h >= 9.25 else at(11), planned=at(11) if h >= 9.25 else None,
               why="dose 1 was taken at 9:15 am: 3 hours apart" if h >= 9.25 else "", later=h < 12.25, done=h >= 12.4, done_at=at(12, 20),
               button="Taken" if 12.25 <= h < 12.4 else ""),
        T.Item(T.DOSE, "💊", "Pill A (dose 3 of 3)", at(15, 15) if h >= 9.25 else at(14), planned=at(14) if h >= 9.25 else None,
               why="dose 2 moved: 3 hours apart" if h >= 9.25 else "", later=h < 15.25, done=h >= 15.3, done_at=at(15, 20)),
        T.Item(T.DOSE, "💊", "Pill C", at(21), later=h < 21, button="Taken" if h >= 21 else ""),
        T.Item(T.ROUTINE, "🔁", "Morning", at(6, 30), at(9), ("Skincare ✓ · Stretch · Glass of water",), done=h >= 8.75, done_at=at(8, 45), button="Done: pick one" if 6.5 <= h < 8.75 else ""),
        T.Item(T.ROUTINE, "🔁", "Evening", at(20), at(23), ("Brush teeth · Floss · Read",), button="Done: pick one" if h >= 20 else ""),
        T.Item(T.EVENT, "📅", "Standup", at(9), at(9, 15)),
        T.Item(T.EVENT, "📅", "Lunch", at(12, 30), at(13, 30)),
        T.Item(T.EVENT, "📅", "Gym", at(18), at(19)),
        T.Item(T.REMINDER, "⏰", "Call the bank", at(10, 30), done=h >= 11.6, done_at=at(11, 35), button="Done" if 10.5 <= h < 11.6 else ""),
        T.Item(T.REMINDER, "⏰", "Put the bins out", at(17), done=h >= 17.1, done_at=at(17, 5), button="Done" if 17 <= h < 17.1 else ""),
        T.Item(T.TODO, "📝", "Write the essay · planned", at(13, 45), at(15, 15), ("1h 30m",), button="Done" if h >= 13.75 else ""),
    ]
    if h >= 18:
        items.append(T.Item(T.DIARY, "📔", "Diary", at(18), details=("streak 4 · not yet",), button="Write"))
    untimed = ["**Buy stamps**", "**Call the plumber**", "**Need milk**", "**Renew the passport** · from Thu 15 Oct"]
    if busy:
        items += [
            T.Item(T.EVENT, "💼", "Work", at(8), at(17)),
            T.Item(T.EVENT, "📅", "Made-up client call", at(14), at(14, 30)),
            T.Item(T.REMINDER, "⏰", "Pay the power bill", at(16)),
            T.Item(T.DUE, "🔁", "Car registration due", all_day=True),
            T.Item(T.TODO, "📝", "Weekly shop · planned", at(19, 15), at(20, 15), ("1h",)),
        ]
        items = [each for each in items if each.title != "Write the essay · planned"]
        untimed += ["**Laundry**", "**Book the dentist**"]
    done = sum(1 for each in items if each.kind in (T.DOSE, T.ROUTINE, T.REMINDER, T.TODO) and each.done)
    total = sum(1 for each in items if each.kind in (T.DOSE, T.ROUTINE, T.REMINDER, T.TODO))
    return T.Header(DAY, done, total, "14° to 20° · drizzle"), items, untimed


def round_6_moment(hour: int, busy: bool = False) -> list[tuple]:
    now = at(hour)
    head, items, untimed = _round_6_day(now, busy)
    return _in_round(6, lambda: timeline.hub(head, items, now, at(22), untimed))


def _lines_of(pieces) -> int:
    from selftest import preview

    lines, _ = preview._count(pieces)
    return lines + 2 * len(design.menus(pieces)) + len(design.buttons(pieces))


PHONE_LINES = 20


def screens(messages: list[tuple]) -> float:
    return round(sum(_lines_of(each) + 1 for each in messages) / PHONE_LINES, 1)


def raw_screens(snapshot: dict) -> float:
    from selftest import day

    lines = 0
    for each in snapshot["messages"]:
        lines += len([line for line in day.lines_of(each["raw"]) if line.strip()]) + 1
    return round(lines / PHONE_LINES, 1)


def tidy_frame() -> tuple:
    lines = [
        design.card_title("🧹 Conversation tidy (round 6, a preview)"),
        "9:02 am · you: “what's on today?” · the bot's answer 9:02 am",
        design.small("9:12 am: both gone, 10 minutes after the exchange finished; a reply to either goes with them"),
        "6:00 am · What's new: “try ✍️ Write at 9 pm”",
        design.small("gone by noon"),
        "🔁 Caught up after a restart: one line, only when something was missed",
        design.small("gone by noon; a restart that missed nothing says nothing"),
    ]
    return (design.Box(design.QUIET, (design.Text("\n".join(lines)),)),)


def round_6_opening(day_file: str) -> str:
    return "\n".join([
        f"## {ROUND_6_TITLE}",
        "Your round 6, as asked tonight: the briefing becomes a header (the date with the day's dots, one small line with the weather and what's next, one faint line of what is done with names and times, Needs a look only for a real problem), and **under it one card per item in time order**: doses, routines, events, timed reminders, to-dos with a planned time, the diary from 6 pm, what is due today, and free time of 90 minutes or more outside events with how many to-dos would fit. A card has its emoji, title and time, a line or two, and its own button only when it can be acted on now. Finished items join the done line; to-dos with no time are one card at the end.",
        "**Below, at 7 am, 12 pm and 8 pm:** round 5 (the real hub, from a run of the dev bot with tonight's code, at its nearest moments: 7:30 am, 12:00 pm, 9:00 pm) and round 6 (drawn by `core/timeline.py` from the same made-up day), each with how many phone screens it takes. Then a busy day (a work day 8 to 5, 18 items) in round 6, the one-moving-pills-card variant, and the conversation tidy.",
        "**What round 6 is so far:** the layout, built and tested, behind DESIGN_ROUND=6 for previews. Live stays on round 5, and the hub's own messages are not switched to it until you pick it: then each card becomes a message in a fixed slot, rewritten in place.",
        f"-# Made-up data only. Round 5's day: {Path(day_file).name}. The buttons here do nothing.",
    ])


async def post_round_6(day_file: str) -> str:
    import discord
    from discord.http import Route

    from interfaces.discord import render
    from selftest import day as day_replay
    from selftest import preview

    snapshots = json.loads(Path(day_file).read_text(encoding="utf-8"))["snapshots"]
    nearest = {7: "7:30 am", 12: "12:00 pm", 20: "9:00 pm"}
    by_label = {each["label"]: each for each in snapshots}

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await preview._with_tags(await preview._design_forum(client))
        tags = [each for each in forum.available_tags if each.name == preview.tag_named(preview.PREVIEW)]
        made = await forum.create_thread(name=ROUND_6_TITLE, content=round_6_opening(day_file)[:2000], applied_tags=tags, allowed_mentions=quiet)
        thread = made.thread

        async def drawn(pieces):
            await thread.send(view=render.layout_view(pieces), allowed_mentions=quiet)
            await asyncio.sleep(0.7)

        for hour, label in nearest.items():
            five = by_label.get(label)
            six = round_6_moment(hour)
            shown = f"{hour % 12 or 12}:00 {'am' if hour < 12 else 'pm'}"
            await thread.send(f"## {shown}\n-# round 5: {raw_screens(five) if five else '?'} phone screens · round 6: {screens(six)} phone screens", allowed_mentions=quiet)
            await thread.send(f"### Round 5 · the real hub at {label}", allowed_mentions=quiet)
            for each in (five or {}).get("messages", []):
                if each.get("typed"):
                    continue
                await client.http.request(Route("POST", "/channels/{channel_id}/messages", channel_id=thread.id), json=day_replay.copy_payload(each["raw"]))
                await asyncio.sleep(0.6)
            await thread.send(f"### Round 6 · {shown}", allowed_mentions=quiet)
            for pieces in six:
                await drawn(pieces)
        await thread.send("## A busy day, round 6 (a work day 8 to 5, 18 items)", allowed_mentions=quiet)
        for hour in (7, 12, 20):
            busy = round_6_moment(hour, busy=True)
            await thread.send(f"### {hour % 12 or 12}:00 {'am' if hour < 12 else 'pm'} · {screens(busy)} phone screens", allowed_mentions=quiet)
            for pieces in busy:
                await drawn(pieces)
        await thread.send("## The pills, two ways at 12 pm\n-# A card a dose (round 6 as asked), the later doses moved with why; or one card that moves to the next dose's place, for comparison", allowed_mentions=quiet)
        head, items, _ = _round_6_day(at(12))
        doses = [each for each in items if each.kind == timeline.DOSE]
        await thread.send("### A card a dose", allowed_mentions=quiet)
        for each in doses:
            if not each.done:
                await drawn(timeline.card(each, at(12)))
        await thread.send("### One moving card (the variant)", allowed_mentions=quiet)
        await drawn(timeline.one_pills_card(doses, at(12)))
        await thread.send("## The conversation tidy (preview)", allowed_mentions=quiet)
        await drawn(tidy_frame())
        return thread.jump_url

    return await preview._as_dev_bot(work)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--plan" in args:
        found = plan_cards()
        if "--check" in args:
            print(f"{len(found)} messages built, each within one message.")
            return 0
        from selftest import preview

        print("Posted:", asyncio.run(preview.post_preview(PLAN_TITLE, plan_opening(), found)))
        return 0
    if "--round-6" in args:
        named = args[args.index("--round-6") + 1] if args.index("--round-6") + 1 < len(args) else ""
        for hour in (7, 12, 20):
            for busy in (False, True):
                found = round_6_moment(hour, busy)
                for pieces in found:
                    wrong = design.problem(pieces)
                    if wrong:
                        raise SystemExit(f"{hour} {busy}: {wrong}")
                print(f"{hour}:00{' busy' if busy else ''}: {len(found)} messages, {screens(found)} phone screens")
        if "--check" in args or not named:
            return 0
        print("Posted:", asyncio.run(post_round_6(named)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
