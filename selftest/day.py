"""A day in the hub: `python -m selftest.day [--post [file]] [--check file]`.

The dev bot is run through one made-up day on the dev clock, 6 am to
midnight, with every switch live has on, and the hub is read back at set
moments: every message in order, as Alex would see it, and the status line
live would show. For design rounds: run it, read the transcript, post it.

- No language is paid for: the made-up things are typed in words with the
  answer Claude would give recorded beside them (as the self-test does).
- Made-up data only: pills "Pill A" to "Pill D", events "Test ...", and a
  calendar file written for the day (never a link).
- As the dev bot only, in the self-test's own channels, on an empty dev
  database (the dev bot's own is set aside and put back, as a self-test run
  does). Live is never touched.

With nothing said it runs the day and keeps the snapshots in
`data/selftest/day-<stamp>.json`, printing a transcript. `--post` posts the
latest (or the file named) in the Design forum as one post; `--check` prints
a file's transcript and the rule checks without running anything.
"""
import asyncio
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from core import clock, config, database
from core import day as days

TITLE = "Design · A day in the hub"
NAME = "day"
# Live's switches as of 16 Oct (live's .env) with calendar writing too, and made-up sources in place of real
# ones: the weather, the calendar's link, the Bot calendar (a file in place of Google), the daily read's feeds
BOT_CALENDAR = "made-up-bot@group.calendar.example"
SETTINGS = {
    "CARDS_V2": "true", "DESIGN_ROUND": "5", "REMINDERS_ENABLED": "true", "BRIEFING_ENABLED": "true", "HUB_TIDY": "true",
    "DAY_PROGRESS": "true", "DAY_QUESTIONS": "true", "WEEKLY_SUMMARY": "true", "QUIET_HOURS_ENABLED": "true",
    "TODOS_ENABLED": "true", "NUDGES_ENABLED": "true", "HABITS_ENABLED": "true", "TODAY_CARD": "true",
    "WEATHER_ENABLED": "true", "WEATHER_SOURCE": str(config.BASE_DIR / "tests" / "fixtures" / "weather_drizzle.json"),
    "CALENDAR_ENABLED": "true", "WEEKLY_ALL": "true", "DIARY_ENABLED": "true", "READING_ENABLED": "true",
    "CALENDAR_WRITE": "true", "CALENDAR_BOT_ID": BOT_CALENDAR, "CALENDAR_READ": "ics,google:CALENDAR_BOT_ID",
}
TLDR_FIRST = "Builds a small agent from one tool to five, showing the prompt at each step.\nThe failures are left in, which is the useful part."
TLDR_SECOND = "How one team records model answers once and replays them in tests.\nCovers what to record and when to record again."


def day_of_run(today: date) -> date:
    """The day the replay is about: the next Sunday (from tomorrow), so the week's summary runs at 7 pm."""
    ahead = (6 - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def reading_source(day: date) -> dict:
    """Made-up feeds and pages for the daily read, dated the day before the replay's day."""
    stamp = f"{day - timedelta(days=1):%Y-%m-%d}T20:00:00+00:00"
    words = " ".join(["Made-up words about building with models, explained step by step."] * 70)

    def page(title):
        return f"<html><body><article><h1>{title}</h1><p>{words}</p></article></body></html>"

    items = [("https://example.com/made-up/agents", "Made-up: giving an agent the right tools"), ("https://example.com/made-up/testing", "Made-up: testing code that calls a model")]
    feed = "<rss version='2.0'><channel><title>Made-up</title>" + "".join(f"<item><title>{title}</title><link>{link}</link><pubDate>{stamp}</pubDate></item>" for link, title in items) + "</channel></rss>"
    return {"sources": [{"name": "Made-up AI blog", "url": "https://example.com/made-up/feed", "theme": "ai"}],
            "pages": {"https://example.com/made-up/feed": feed, **{link: page(title) for link, title in items}}}
# The moments the hub is read, and the story's own line for what happened since the one before
MOMENTS = (
    ((6, 0), "The night: yesterday closed; the daily read picked at 5:30; the 6 am tidy, then the briefing and the morning cards, the read's card last"),
    ((7, 30), "Quiet hours ended at 7; the morning routine's window opened at 6:30 and its card came up; Pill B's 7:00 reminder, Taken by its button at 7:05; Skincare ticked in the routine's dropdown at 7:20"),
    ((9, 45), "Pill A's 8:00 reminder went off and was left; 👎 on the daily read at 7:40, then Another one; Stretch and Glass of water ticked at 8:45, so the routine's card went; “took pill a” at 9:05, an hour late; Buy stamps done at 9:10; the 9:00 standup; “dentist at 4pm for an hour” added to the Bot calendar at 9:30"),
    ((12, 0), "The 10:30 reminder snoozed for an hour, then Done at 11:35; “skip pill d” at 11:00; Pill A's second dose moved to 12:05, three hours after the first"),
    ((15, 0), "Pill A's second dose taken by its reminder at 12:10; the 12:30 lunch; “move the dentist to 4:30pm” at 1:00; “paid the power bill” at 2:00; the 3:00 event was cancelled; the third dose is due at 3:10"),
    ((18, 30), "Pill A's third dose was never taken: missed at 5:00, its latest time; Call the plumber done at 4:00; the dentist at 4:30; the 5:00 reminder done at 5:05; the gym at 6"),
    ((21, 0), "The week's summary of everything at 7 pm (a Sunday); the evening routine's window opened at 8; the diary's evening ask and Pill C's reminder at 9:00"),
    ((23, 45), "Pill C taken at 9:05; a diary entry at 9:15 with its mood; Brush teeth and Floss ticked at 9:30, Read left; quiet hours from 10; the evening window closed at 11"),
)


def label(hour: int, minute: int) -> str:
    from core.timeinput import format_time

    return format_time(time(hour, minute))


# ---------------------------------------------------------------------------
# The made-up calendar, written for the day it is about
# ---------------------------------------------------------------------------
def ics(day: date) -> str:
    """An all-day event, three timed ones and one cancelled, on `day` (Auckland time)."""
    stamp = f"{day:%Y%m%d}"
    following = f"{day + timedelta(days=1):%Y%m%d}"

    def event(uid: str, summary: str, start: str, end: str, status: str = "") -> list[str]:
        return ["BEGIN:VEVENT", f"UID:{uid}@example.test", f"SUMMARY:{summary}", start, end, *([f"STATUS:{status}"] if status else []), "END:VEVENT"]

    def timed(at: str, until: str) -> tuple[str, str]:
        return f"DTSTART;TZID=Pacific/Auckland:{stamp}T{at}00", f"DTEND;TZID=Pacific/Auckland:{stamp}T{until}00"

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//assistant-bot//a day in the hub//EN", "CALSCALE:GREGORIAN", "X-WR-TIMEZONE:Pacific/Auckland"]
    lines += event("day-allday", "Test conference", f"DTSTART;VALUE=DATE:{stamp}", f"DTEND;VALUE=DATE:{following}")
    lines += event("day-standup", "Test standup", *timed("0900", "0915"))
    lines += event("day-lunch", "Test lunch", *timed("1230", "1330"))
    lines += event("day-dentist", "Test dentist", *timed("1500", "1600"), status="CANCELLED")
    lines += event("day-gym", "Test gym", *timed("1800", "1900"))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Reading a message as Discord holds it (its raw JSON), and posting a copy
# ---------------------------------------------------------------------------
TEXT, CONTAINER, SECTION, ROW, BUTTON, SEPARATOR = 10, 17, 9, 1, 2, 14
SELECTS = (3, 5, 6, 7, 8)
COMPONENTS_V2 = 1 << 15


def _walk(components, lines: list[str]) -> None:
    for each in components or []:
        kind = each.get("type")
        if kind == TEXT:
            lines.append(each.get("content", ""))
        elif kind == BUTTON:
            emoji = (each.get("emoji") or {}).get("name") or ""
            lines.append(f"[{' '.join(part for part in (emoji, each.get('label') or '') if part)}]")
        elif kind in SELECTS:
            lines.append(f"[▾ {each.get('placeholder') or 'pick'}: {', '.join(option.get('label', '') for option in each.get('options') or [])}]")
        elif kind == SEPARATOR:
            lines.append("———")
        if kind == CONTAINER:
            lines.append("┌ box")
        _walk(each.get("components"), lines)
        if each.get("accessory"):
            _walk([each["accessory"]], lines)
        if kind == CONTAINER:
            lines.append("└")


def lines_of(raw: dict) -> list[str]:
    """A message as plain lines: its words, each box, button and dropdown."""
    lines = [raw["content"]] if raw.get("content") else []
    for embed in raw.get("embeds") or []:
        lines += [part for part in (embed.get("title"), embed.get("description")) if part]
        lines += [f"{field.get('name')}: {field.get('value')}" for field in embed.get("fields") or []]
    _walk(raw.get("components"), lines)
    return lines


def _without_ids(components):
    found = []
    for each in components or []:
        each = {name: value for name, value in each.items() if name != "id"}
        for name in ("components",):
            if name in each:
                each[name] = _without_ids(each[name])
        if "accessory" in each:
            each["accessory"] = _without_ids([each["accessory"]])[0]
        found.append(each)
    return found


def copy_payload(raw: dict) -> dict:
    """What posts a copy of a message: the same boxes and buttons, or the same words and embeds."""
    quiet = {"parse": []}
    if int(raw.get("flags") or 0) & COMPONENTS_V2:
        return {"components": _without_ids(raw.get("components")), "flags": COMPONENTS_V2, "allowed_mentions": quiet}
    return {"content": raw.get("content") or "", "embeds": raw.get("embeds") or [], "components": _without_ids(raw.get("components")), "allowed_mentions": quiet}


def heading(raw: dict) -> str:
    """The first line worth naming a message by."""
    for line in lines_of(raw):
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("┌", "└", "———", "[")):
            return line[:80]
    return "(no words)"


# ---------------------------------------------------------------------------
# What changed between two snapshots, and the design rules checked on one
# ---------------------------------------------------------------------------
def changes(before: dict | None, after: dict) -> str:
    """One short line: what came, what went, what was rewritten."""
    if before is None:
        return f"{len(after['messages'])} messages"
    old = {each["id"]: each for each in before["messages"]}
    new = {each["id"]: each for each in after["messages"]}
    came = [each for key, each in new.items() if key not in old]
    went = [each for key, each in old.items() if key not in new]
    rewritten = [each for key, each in new.items() if key in old and lines_of(old[key]["raw"]) != lines_of(each["raw"])]
    parts = []
    if came:
        parts.append("new: " + "; ".join(heading(each["raw"]) for each in came))
    if went:
        parts.append("gone: " + "; ".join(heading(each["raw"]) for each in went))
    if rewritten:
        parts.append("rewritten: " + "; ".join(heading(each["raw"]) for each in rewritten))
    if before.get("status") != after.get("status"):
        parts.append(f"status line {before.get('status') or 'blank'} → {after.get('status') or 'blank'}")
    return " · ".join(parts) or "nothing changed"


# Where a message belongs in the hub, top to bottom: the briefing, the task cards in their fixed order, then the moment
PLACES = ("briefing:hub", "pills", "today", "nudges", "habits", "gym", "todos", "reading")


def place(message: dict) -> int:
    """0 the briefing, 1 to 6 a task card in its order, 9 anything else (the moment).
    A hub card's key is "<task>:hub", or "<task>.<slot>:hub" for one of several."""
    key = message.get("key") or ""
    if key == "briefing:hub":
        return 0
    if message.get("kind") == "checklist":
        return 1
    task = key.split(":")[0].split(".")[0] if key.endswith(":hub") else ""
    return PLACES.index(task) if task in PLACES[2:] else 9


def rule_problems(snapshot: dict) -> list[str]:
    """What breaks the hub's rules in one snapshot: the order (briefing, task cards,
    then the moment), a card twice, and anything left from another day. A moment's
    message (a reminder, the Sunday summary) stays where it was posted: a card that
    comes up after it goes under it (question 91), so only the cards' order is checked."""
    problems = []
    places = [place(each) for each in snapshot["messages"] if not each.get("typed") and place(each) != 9]
    for at in range(1, len(places)):
        if places[at] < places[at - 1]:
            problems.append(f"out of order: “{heading(snapshot['messages'][at]['raw'])}” is under something that comes after it")
            break
    keys = [each["key"] for each in snapshot["messages"] if each.get("key")]
    for key in sorted({key for key in keys if keys.count(key) > 1}):
        problems.append(f"{key} is in the hub {keys.count(key)} times")
    for each in snapshot["messages"]:
        if each.get("day") and each["day"] != snapshot["day"]:
            problems.append(f"left from {each['day']}: “{heading(each['raw'])}”")
    return problems


def transcript(snapshots: list[dict]) -> str:
    out, before = [], None
    for snap in snapshots:
        out.append(f"=== {snap['label']} · status line: {snap.get('status') or '(blank)'}")
        out.append(f"--- since: {snap.get('since', '')}")
        out.append(f"--- seen: {changes(before, snap)}")
        for problem in rule_problems(snap):
            out.append(f"!!! {problem}")
        for each in snap["messages"]:
            who = "YOU" if each.get("typed") else (each.get("key") or each.get("kind") or each.get("lifetime") or "?")
            out.append(f"  <{who}>")
            out += [f"    {line}" for line in lines_of(each["raw"])]
        before = snap
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The story, run inside a start of the dev bot (selftest/phase.py)
# ---------------------------------------------------------------------------
def _pill(name: str, **plan) -> dict:
    return {"name": name, **plan}


async def _at(h, the_day: date, hour: int, minute: int) -> None:
    """The clock to a time of the day, stopping at each job on the way so that each runs at its
    own time (a reminder at 8:00 goes off at 8:00, not when the clock lands at 8:45)."""
    from core import scheduler

    target = days.at(the_day, time(hour, minute))
    while clock.now() < target:
        due = [job.due_at for job in await scheduler.all_pending() if clock.now() < job.due_at <= target]
        clock.advance_to(min(min(due) + timedelta(seconds=5), target) if due else target)
        await h.run_due()
    await h.run_due()
    await h.settle(2)


async def snapshot(h, the_day: date, moment: tuple[int, int], since: str) -> None:
    """The hub as it stands, oldest first, with what each message is, and the status line live would show."""
    from core import attention, livelists, messages
    from tasks.pills import store as pills_store

    await h.settle(3)
    raw = list(reversed(await h.client.http.logs_from(h.hub.id, 100)))
    sheets = {each.message_id: each.kind for each in await database.run(pills_store.db_messages, h.user.id, the_day)}
    sheets.update({each.message_id: each.kind for each in await database.run(pills_store.db_messages, h.user.id, the_day - timedelta(days=1))})
    found = []
    for each in raw:
        message_id = int(each["id"])
        placed = await livelists.by_message(message_id)
        row = await database.run(messages.db_get, message_id)
        found.append({
            "id": message_id, "typed": message_id in h.typed, "key": placed.key if placed else "", "kind": sheets.get(message_id, ""),
            "lifetime": row.lifetime if row else "", "slot": row.slot if row else "", "day": row.day if row else "",
            "raw": {name: each.get(name) for name in ("content", "embeds", "components", "flags")},
        })
    now = clock.now()
    items = await attention.gather(h.user.id, now)
    status = attention.status_line(attention.top(items, now))
    h.memo.setdefault("snapshots", []).append({"label": label(*moment), "day": the_day.isoformat(), "status": status, "since": since, "messages": found})
    h.save()


async def story(h) -> None:
    from selftest.phases import card, log, slot_card, todo, todos_card
    from tasks.habits import store as habits_store

    h.recorded_only = True
    the_day = day_of_run(days.today())
    # The day before at 4 pm, straight there: the setting up is the afternoon before, as it would be
    clock.advance_to(max(clock.now(), days.at(the_day - timedelta(days=1), time(16, 0))))
    await h.run_due()
    # The daily read's pick at 5:30 is a job's request, with no message: its recorded answer
    h.background["reading"] = ("pick", {"choice": 1, "tldr": TLDR_FIRST})

    async def save(key: str, said: str, canned, task: str) -> None:
        async for attempt in h.step(key, f"“{said}”, then Save", "a card, and after Save it is kept", "a day in the hub (set up)"):
            async with attempt:
                await h.say(said, canned=canned, task=task)
                _, shown = await card(h)
                h.check(shown is not None and any("Save" in label for label in shown.labels), f"the card: {shown.text[:200] if shown else 'none'}")
                await h.press(shown.id, "Save", h.inbox)
        _, left = await card(h)
        if left is not None and any("Cancel" in label for label in left.labels):
            await h.press(left.id, "Cancel", h.inbox)  # a card left open would take the next words

    # --- the day before, in #inbox: what the day will hold -------------------------------------------
    # The words say every time in full: a time the words leave open is asked about on the card
    pills = (
        ("Pill A", "3 times a day at 8am, 12pm and 3pm, at least 3 hours apart, not after 5pm", {"per_day": 3, "times": ["8:00 am", "12:00 pm", "3:00 pm"], "min_gap_minutes": 180, "latest": "5:00 pm"}),
        ("Pill B", "once a day at 7am", {"per_day": 1, "times": ["7:00 am"]}),
        ("Pill C", "once a day at 9pm", {"per_day": 1, "times": ["9:00 pm"]}),
        ("Pill D", "once a day", {"per_day": 1}),
    )
    for at, (name, words, plan) in enumerate(pills, 1):
        await save(f"d.0{at}", f"add {name.lower()} to my pills {words}", ("pill_add", {"pills": [_pill(name, **plan)], "guessed": [], "not_included": []}), "pills")
    await save("d.05", "add renew the passport today, pay the power bill today, buy stamps and water the plants",
               todo("todo_add", todos=[{"text": "renew the passport", "day": "today"}, {"text": "pay the power bill", "day": "today"}, {"text": "buy stamps"}, {"text": "water the plants"}]), "todos")
    await save("d.06", "add call the plumber tomorrow and book a haircut tomorrow",
               todo("todo_add", todos=[{"text": "call the plumber", "day": "tomorrow"}, {"text": "book a haircut", "day": "tomorrow"}]), "todos")
    await save("d.07", "remind me tomorrow at 10:30 am to call the bank", todo("nudge_add", text="call the bank", time="10:30 am", day="tomorrow"), "nudges")
    await save("d.08", "remind me tomorrow at 5pm to put the bins out", todo("nudge_add", text="put the bins out", time="5:00 pm", day="tomorrow"), "nudges")
    await save("d.09", "make a morning routine 6:30 am to 9 am: stretch, glass of water, skincare: cleanse, tone, moisturise",
               todo("habit_add", routine="morning", items=[{"text": "stretch"}, {"text": "glass of water"}, {"text": "skincare", "steps": ["cleanse", "tone", "moisturise"]}], **{"from": "6:30 am", "until": "9:00 am"}), "habits")
    await save("d.10", "make an evening routine 8pm to 11pm: brush teeth, floss, read for 10 minutes",
               todo("habit_add", routine="evening", items=[{"text": "brush teeth"}, {"text": "floss"}, {"text": "read for 10 minutes"}], **{"from": "8:00 pm", "until": "11:00 pm"}), "habits")
    routines = {each.name: each.id for each in await habits_store.every(h.user.id)}

    async def step(key: str, title: str, work) -> None:
        async for attempt in h.step(key, title, "done as said", "a day in the hub"):
            async with attempt:
                await work()

    async def snap(at: int) -> None:
        moment, since = MOMENTS[at]
        await _at(h, the_day, *moment)
        async for attempt in h.step(f"d.s{at + 1}", f"Snapshot at {label(*moment)}", "the hub read back", "a day in the hub"):
            async with attempt:
                await snapshot(h, the_day, moment, since)
                h.saw(f"{len(h.memo['snapshots'][-1]['messages'])} messages; status {h.memo['snapshots'][-1]['status'] or 'blank'}")

    async def reminder_taken() -> None:
        went = await h.find(h.hub, "💊 Dose due")
        h.check(went is not None, "no pill reminder in the hub")
        await h.press(went.id, "Taken")

    async def nudge(button: str) -> object:
        went = await h.find(h.hub, "Reminder ·")
        h.check(went is not None, "no reminder in the hub")
        return await h.press(went.id, button)

    async def thumbs_down_then_another() -> None:
        shown = await h.find(h.hub, "Daily read")
        h.check(shown is not None, "no daily read card in the hub")
        await h.press(shown.id, "", arg=f"{the_day.isoformat()}:down")
        h.background["reading"] = ("pick", {"choice": 1, "tldr": TLDR_SECOND})
        await h.press(shown.id, "Another one", arg=the_day.isoformat())

    async def pick(slot: str, option: str) -> None:
        shown = await slot_card(h, slot) if slot != "todos" else await todos_card(h)
        h.check(shown is not None, f"no {slot} card in the hub")
        await h.pick(shown.id, option)

    # --- the day ----------------------------------------------------------------------------------------
    await snap(0)
    await _at(h, the_day, 7, 5)
    await step("d.11", "Pill B: Taken on its reminder", reminder_taken)
    await _at(h, the_day, 7, 20)
    await step("d.12", "Morning routine: Skincare in its dropdown", lambda: pick(f"habits.r{routines['Morning']}", "Skincare"))
    await snap(1)
    await _at(h, the_day, 8, 45)
    await _at(h, the_day, 7, 40)
    await step("d.25", "The daily read: 👎, then Another one", thumbs_down_then_another)
    await _at(h, the_day, 8, 45)
    await step("d.13", "“did stretch and glass of water”", lambda: h.say("did stretch and glass of water", channel=h.hub, canned=todo("habit_tick", items=["stretch", "glass of water"]), task="habits"))
    await _at(h, the_day, 9, 5)
    await step("d.14", "Pill A's first dose, late: “took pill a” in the hub", lambda: h.say("took pill a", channel=h.hub, canned=log({"pill": "Pill A", "did": "taken"})))
    await _at(h, the_day, 9, 10)
    await step("d.15", "To-dos: Buy stamps in the Done dropdown", lambda: pick("todos", "Buy stamps"))
    await _at(h, the_day, 9, 30)
    await save("d.26", "dentist at 4pm for an hour", todo("calendar_add", title="dentist", time="4:00 pm", length=60), "calendar")
    await snap(2)
    await _at(h, the_day, 10, 32)

    async def snooze() -> None:
        pressed = await nudge("Snooze")
        await h.settle()
        await h.press(pressed.message.id, "1 hour")

    await step("d.16", "The 10:30 reminder: Snooze, 1 hour", snooze)
    await _at(h, the_day, 11, 0)
    await step("d.17", "“skip pill d”", lambda: h.say("skip pill d", channel=h.hub, canned=log({"pill": "Pill D", "did": "skipped"})))
    await _at(h, the_day, 11, 35)
    await step("d.18", "The snoozed reminder again: Done", lambda: nudge("Done"))
    await snap(3)
    await _at(h, the_day, 12, 10)
    await step("d.19", "Pill A's noon dose: Taken on its reminder", reminder_taken)
    await _at(h, the_day, 13, 0)
    await save("d.27", "move the dentist to 4:30pm", todo("calendar_move", search="dentist", time="4:30 pm"), "calendar")
    await _at(h, the_day, 14, 0)
    await step("d.20", "“paid the power bill”", lambda: h.say("paid the power bill", channel=h.hub, canned=todo("todo_done", todos=[{"todo": "power bill"}]), task="todos"))
    await snap(4)
    await _at(h, the_day, 16, 0)
    await step("d.21", "To-dos: Call the plumber in the Done dropdown", lambda: pick("todos", "Call the plumber"))
    await _at(h, the_day, 17, 5)
    await step("d.22", "The 5:00 reminder: Done", lambda: nudge("Done"))
    await snap(5)
    await snap(6)
    await _at(h, the_day, 21, 5)
    await step("d.23", "Pill C: Taken on its reminder", reminder_taken)
    await _at(h, the_day, 21, 15)
    await step("d.28", "A diary entry: “made-up: a good day, finished the essay”", lambda: h.say("made-up: a good day, finished the essay", canned=todo("diary_write", mood="good"), task="diary"))
    await _at(h, the_day, 21, 30)
    await step("d.24", "“did brush teeth and floss”", lambda: h.say("did brush teeth and floss", channel=h.hub, canned=todo("habit_tick", items=["brush teeth", "floss"]), task="habits"))
    await snap(7)

    async for attempt in h.step("d.99", "The doses at the end of the day", "Pill A 1 and 2 taken, 3 missed; Pill B and C taken; Pill D skipped", "a day in the hub"):
        async with attempt:
            found = await h.doses()
            h.saw(", ".join(f"{name} {seq}: {state}" for (name, seq), state in sorted(found.items())))


PHASES = {NAME: story}


# ---------------------------------------------------------------------------
# The launcher: one start of the dev bot, the dev database set aside and put back
# ---------------------------------------------------------------------------
NOT_FROM, NOT_UNTIL = time(3, 15), time(4, 30)  # the nightly self-test's window


def may_run(now: datetime) -> str:
    """'' when a run may start now (local time), or why not."""
    if NOT_FROM <= now.time() < NOT_UNTIL:
        return "not between 3:15 and 4:30 am: the nightly self-test runs then"
    return ""


def run_day(anyway: bool = False, round_: int | None = None) -> Path | None:
    from selftest import __main__ as launcher
    from selftest import stages
    from core import instance_lock

    if not launcher.separate():
        print("There is no dev bot (.env.dev needs its own token): a day in the hub runs only as the dev bot.")
        return None
    if instance_lock.holder(instance_lock.TEST_LOCK) is not None:
        print("The dev bot is already running: stop it first.")
        return None
    why = may_run(datetime.now())
    if why:
        print(f"Not started: {why}.")
        return None
    low, line = stages.memory_line(stages.free_memory())
    print(f"--- {line}", flush=True)
    if low and not anyway:
        print("--- not started: too little free memory.")
        return None
    for each in launcher.recover():
        print(f"--- an earlier run had left the dev database aside: put back ({each['date']})", flush=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = launcher.WORK / f"run-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    feed = folder / "day.ics"
    the_day = day_of_run(config.now_nz().date())
    feed.write_text(ics(the_day), encoding="utf-8")
    reading = folder / "reading.json"
    reading.write_text(json.dumps(reading_source(the_day)), encoding="utf-8")
    made_up = {"CALENDAR_ICS_URL": str(feed), "READING_SOURCE": str(reading), "GOOGLE_CALENDAR_FAKE": str(folder / "google-calendar.json")}
    channels = asyncio.run(launcher.prepare_channels())
    saved = launcher.set_aside(stamp)
    try:
        found = launcher.run_phase(NAME, {**SETTINGS, **made_up, **({"DESIGN_ROUND": str(round_)} if round_ else {})}, channels, False, 0.0, {}, stamp)
    finally:
        launcher.put_back(saved, stamp)
        try:
            print(f"--- the dev bot's name: {asyncio.run(launcher.plain_name(channels['inbox']))}", flush=True)
        except Exception as error:
            print(f"--- the dev bot's name could not be put back ({type(error).__name__})", flush=True)
    bad = [each for each in found["results"] if each["status"] in ("fail", "error")]
    for each in bad:
        print(f"[{each['status']}] {each['key']} {each['title']} :: {each['saw'][:300]}")
    out = launcher.WORK / f"day-{stamp}{f'-r{round_}' if round_ else ''}.json"
    out.write_text(json.dumps({"stamp": stamp, "exit": found.get("exit"), "results": found["results"], "snapshots": found.get("memo", {}).get("snapshots", [])}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"--- {len(found['results'])} steps, {len(bad)} failed, exit {found.get('exit')}. Kept: {out}")
    return out


def latest() -> Path | None:
    from selftest import __main__ as launcher

    found = sorted(launcher.WORK.glob("day-*.json"))
    return found[-1] if found else None


def opening(snapshots: list[dict]) -> str:
    return "\n".join([
        f"## {TITLE}",
        "One made-up day, a Sunday, 6 am to midnight, run by the dev bot on its own clock with every switch live has on (round 5), and adding to the Bot calendar. "
        f"The hub is read back {len(snapshots)} times: each reply below is one moment, with the status line live would show, "
        "what happened since the moment before, and then every message in the hub, top to bottom, as you would see it.",
        "-# Made-up data only: Pill A to Pill D (6 doses: one late, one missed, one skipped), six to-dos (two overdue), "
        "two reminders (one snoozed), a morning and an evening routine (one with a group), a calendar with an all-day event, "
        "three timed and one cancelled, an event added to the Bot calendar and moved, the daily read (👎 then another one), "
        "a diary entry, and the week's summary at 7 pm, all set up at 4 pm the day before. "
        "The buttons here do nothing. Run again with `python -m selftest.day`.",
    ])


EVERYTHING = "Round 5 with everything on"


async def _thread_named(client, forum, name: str):
    """The forum's post with that name (open or archived), or None."""
    found = await client.http.get_active_threads(forum.guild.id)
    for each in found.get("threads", []):
        if str(each.get("parent_id")) == str(forum.id) and each.get("name") == name:
            return await client.fetch_channel(int(each["id"]))
    async for thread in forum.archived_threads(limit=100):
        if thread.name == name:
            return thread
    return None


async def post(snapshots: list[dict], heading: str = "") -> str:
    """One post in the Design forum: the opening, then a reply a moment (its line and the hub's
    messages, copied as they were). Over HTTP only, as the dev bot."""
    import discord
    from discord.http import Route

    from selftest import preview

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await preview._design_forum(client)
        thread = await _thread_named(client, forum, TITLE) if heading else None
        if thread is not None:
            if getattr(thread, "archived", False):
                await thread.edit(archived=False)
            await thread.send(f"# {heading}\n" + opening(snapshots).split("\n", 1)[1], allowed_mentions=quiet)
        else:
            thread = (await forum.create_thread(name=TITLE, content=opening(snapshots), allowed_mentions=quiet)).thread
        before = None
        for snap in snapshots:
            head = [f"## {snap['label']}", f"**Status line:** {snap.get('status') or '(blank)'}", f"**Since the last:** {snap.get('since', '')}"]
            head.append(f"-# What the hub shows changed: {changes(before, snap)}"[:900])
            await thread.send("\n".join(head)[:2000], allowed_mentions=quiet)
            for each in snap["messages"]:
                if each.get("typed"):
                    await thread.send(f"-# 🗨️ you, in the hub: {(each['raw'].get('content') or '')[:300]}", allowed_mentions=quiet)
                else:
                    await client.http.request(Route("POST", "/channels/{channel_id}/messages", channel_id=thread.id), json=copy_payload(each["raw"]))
                await asyncio.sleep(0.7)  # paced: well under Discord's rate limit
            before = snap
        return thread.jump_url

    return await preview._as_dev_bot(work)


ROUND_5_TITLE = "Design · Round 5"
ROUND_5_FEEDBACK = "there's a little bit of overlap with pills and calendar"
# Each change, with whether it was asked for or is a suggested answer to a question, for a yes or no each
ROUND_5_CHANGES = (
    ("R5.1", "asked", "The briefing is the morning overview: Needs a look and Weather keep their boxes; every task with a card of its own is one line in one small overview box, with no progress (its card has it)"),
    ("R5.2", "asked", "The briefing's page title is the date with the day's dots (“☀️ Thursday 15 October ●●● 3/3”): “Today” only ever means the Today card"),
    ("R5.3", "asked", "A task card whose items are all done leaves the hub, and comes back if something new is added (the pills checklist too, unless a dose was missed)"),
    ("R5.4", "asked", "No footer on the briefing: the how-to is in help (`help briefing`)"),
    ("Q68", "suggested", "A card that comes up mid-day (a routine's window) has the cards that belong under it posted again under it, so the order holds"),
    ("Q69", "suggested", "The Today card has no count of its own: the briefing's title has the day's"),
    ("Q70", "suggested", "The briefing keeps a line a task and no detail (R5.1), and the to-dos are on their own card, not on the Today card too"),
    ("Q71", "already so", "A routine whose window closed undone keeps its card, amber, until it is done or the morning tidy"),
    ("Q72", "suggested", "The overview's lines are in one fixed order every day (the order the tasks are loaded in), not by the ranking"),
    ("Q73", "suggested", "A plain “I can't find that” in the hub goes 2 minutes after, like any answer; only a failure of the bot's own keeps its ⚠️"),
    ("Q74", "replaced", "Replaced by R5.3: a card all done leaves the hub, the reminders card and the to-dos card alike"),
    ("Q75", "suggested", "A missed dose holds the status line until the evening (as “all taken” does), then the line looks ahead"),
)


def round_5_opening() -> str:
    lines = [
        f"## {ROUND_5_TITLE}",
        f"Your feedback on the live hub, word for word: “{ROUND_5_FEEDBACK}”. Round 5 is built behind DESIGN_ROUND=5 and is not on live.",
        "**Reply with a yes or no for each** (for example “yes to all but Q73”):",
        *(f"- **{key}** ({kind}): {words}" for key, kind, words in ROUND_5_CHANGES),
        "-# Below: the same made-up day run by the dev bot twice, round 4 (live now) and round 5, side by side at each of the eight moments. Made-up data only.",
    ]
    return "\n".join(lines)


async def post_compare(before: list[dict], after: list[dict], title: str, intro: str, names: tuple[str, str] = ("Round 4", "Round 5")) -> str:
    """One post: the opening, then at each moment a line of what changed in each run, then each run's hub, copied."""
    import discord
    from discord.http import Route

    from selftest import preview

    async def work(client):
        quiet = discord.AllowedMentions.none()
        forum = await preview._design_forum(client)
        tags = [each for each in (await preview._with_tags(forum)).available_tags if each.name == preview.tag_named(preview.PREVIEW)]
        made = await forum.create_thread(name=title, content=intro[:2000], applied_tags=tags, allowed_mentions=quiet)
        thread = made.thread
        last = (None, None)
        for one, two in zip(before, after):
            head = [f"## {one['label']}", f"**Since the last:** {one.get('since', '')}",
                    f"-# {names[0]}: status line {one.get('status') or '(blank)'} · {changes(last[0], one)}"[:700],
                    f"-# {names[1]}: status line {two.get('status') or '(blank)'} · {changes(last[1], two)}"[:700]]
            await thread.send("\n".join(head)[:2000], allowed_mentions=quiet)
            for name, snap in zip(names, (one, two)):
                await thread.send(f"### {name} · {one['label']}", allowed_mentions=quiet)
                for each in snap["messages"]:
                    if each.get("typed"):
                        await thread.send(f"-# 🗨️ you, in the hub: {(each['raw'].get('content') or '')[:300]}", allowed_mentions=quiet)
                    else:
                        await client.http.request(Route("POST", "/channels/{channel_id}/messages", channel_id=thread.id), json=copy_payload(each["raw"]))
                    await asyncio.sleep(0.6)  # paced: well under Discord's rate limit
            last = (one, two)
        return thread.jump_url

    return await preview._as_dev_bot(work)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--compare" in args:
        first, second = (Path(each) for each in args[args.index("--compare") + 1:args.index("--compare") + 3])
        before, after = (json.loads(path.read_text(encoding="utf-8"))["snapshots"] for path in (first, second))
        print("Posted:", asyncio.run(post_compare(before, after, ROUND_5_TITLE, round_5_opening())))
        return 0
    if "--check" in args or "--post" in args:
        flag = "--check" if "--check" in args else "--post"
        named = args[args.index(flag) + 1] if args.index(flag) + 1 < len(args) else ""
        path = Path(named) if named else latest()
        if path is None or not path.exists():
            print("No day has been run yet: `python -m selftest.day`.")
            return 2
        snapshots = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
        if flag == "--check":
            print(transcript(snapshots))
            return 0
        print("Posted:", asyncio.run(post(snapshots, EVERYTHING if "--reply" in args else "")))
        return 0
    wanted = args[args.index("--round") + 1] if "--round" in args and args.index("--round") + 1 < len(args) else ""
    out = run_day(anyway="--anyway" in args, round_=int(wanted) if wanted.isdigit() else None)
    if out is None:
        return 3
    print(transcript(json.loads(out.read_text(encoding="utf-8"))["snapshots"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
