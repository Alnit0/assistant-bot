from dataclasses import replace
from datetime import time

from core import clock, config, database, livelists, names, scheduler, timeinput, timetable
from core.actions import SET, Choice, LiveReply, Proposal, Question, Request, flag, is_guessed, is_reference
from core.cards import Card
from core.errors import UserError
from core.timetable import NOTIFY, ON, PAUSED, REMOVED, SILENT, Schedule
from tasks.schedule import rules
from tasks.schedule.rules import ICON, PAUSE, RESUME, TASK, Listed

# ---------------------------------------------------------------------------
# My schedule in plain words: the list, and changing, adding and removing a
# schedule, each on a card that only Save writes. The rows and the engine are
# the core's (core/timetable.py, core/scheduler.py); this is only the
# conversation. Takes a Request, never a Context, and calls no Discord.
#
# What Claude hands over is structured: a time in the one form, days as a
# list of weekdays with add / set / remove, silent or notify as one of two,
# pause or resume, a date as I said it. Which schedule a name means is
# core/names.py: more than one fit is asked about on the card.
# ---------------------------------------------------------------------------
KEY = "schedule"
LIST = "schedules"
REF = "s"  # a schedule as the card's own data names it: "s3"


def ref(schedule: Schedule) -> str:
    return f"{REF}{schedule.id}"


async def every() -> list[Schedule]:
    """Every schedule that is not removed, in the order of the time of day."""
    return await database.run(timetable.db_all)


def step_words(schedule: Schedule) -> tuple[str, ...]:
    return tuple(scheduler.label(*scheduler.handler_parts(step)) for step in schedule.steps)


async def listed() -> list[Listed]:
    found = []
    for schedule in await every():
        found.append(Listed(schedule, step_words(schedule), await scheduler.coming(schedule), await scheduler.last_of(schedule.id)))
    return found


async def list_card() -> Card:
    today = rules.local_today(clock.now())
    found = await listed()
    return Card(rules.list_text(found, today), (), rules.list_layout(found, today))


def list_changed(user_id: int) -> None:
    """A schedule changed: the list last shown on request is brought up to date in place."""
    livelists.changed(user_id, KEY, list_card)


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    shown = await list_card()
    return LiveReply(KEY, shown.text, shown)


async def state(request: Request) -> str:
    """What extraction is told: the schedules there are, and what can be added."""
    # One of the bot's own is listed like any other: whether it may be changed is the code's
    # to say, with its own line, never a reason for Claude to decline
    lines = [
        f"{each.name} ({rules.when(each).replace('`', '')}"
        + (", the bot's own" if each.locked else f", {rules.notify_text(each.notify)}, #{each.channel}" + (", paused" if each.state == PAUSED else "")) + ")"
        for each in await every()
    ]
    can = ", ".join(sorted(label for label, _ in addable()))
    return "The user's schedules now (use the name): " + ("; ".join(lines) or "none") + (f". Can be scheduled: {can}." if can else "")


async def item_names(request: Request) -> list[str]:
    return [each.name for each in await every() if not each.locked]


# ---------------------------------------------------------------------------
# Which schedule is meant
# ---------------------------------------------------------------------------
def find(schedules: list[Schedule], wanted: str, said: str = "") -> Schedule:
    """The schedule a name (or the card's own "s3") means. More than one fit
    raises names.Ambiguous: asked about, never guessed. What was typed is
    checked too, as for a pill."""
    wanted = wanted.strip()
    if wanted.lower().startswith(REF) and wanted[len(REF):].isdigit():
        by_id = [each for each in schedules if each.id == int(wanted[len(REF):])]
        if by_id:
            return by_id[0]
    try:
        found = names.find(schedules, wanted, lambda each: each.name)
    except names.Unnamed:
        raise UserError("Which schedule?")
    except names.Unknown:
        yours = ", ".join(each.name for each in schedules) or "none yet"
        raise UserError(f"I don't have a schedule called “{wanted}”. Yours: {yours}.")
    typed = names.unclear(schedules, said, lambda each: each.name, found) if said else None
    if typed is not None:
        raise typed
    return found


def _resolve(schedules: list[Schedule], items: list[dict], said: str) -> tuple[list[tuple[dict, Schedule, bool]], list[str], list[tuple[dict, list[Schedule]]]]:
    """Each item with the schedule it means and whether that was a pick of the
    code's own ("it", with only one it could be); what couldn't be found, in
    words; and each item whose name fits more than one, to be asked about."""
    found, problems, unclear = [], [], []
    mine = [each for each in schedules if not each.locked]
    for item in items:
        wanted = str(item.get("schedule", ""))
        try:
            if is_reference(wanted) or not wanted.strip():
                # "it" is the code's to work out: the only one there is, or a question
                if len(mine) != 1:
                    unclear.append(({**item, "schedule": "it"}, mine))
                    continue
                found.append((item, mine[0], True))
                continue
            found.append((item, find(schedules, wanted, said), False))
        except names.Ambiguous as which:
            unclear.append(({**item, "schedule": which.said}, which.candidates))
        except UserError as error:
            problems.append(str(error))
    return found, problems, unclear


def _which_one(known: list[dict], unclear: list[tuple[dict, list[Schedule]]]) -> Question | None:
    if not unclear:
        return None
    raw, candidates = unclear[0]
    rest = [dict(item) for item, _ in unclear[1:]]
    if not candidates:
        return None
    asked = "Which schedule?" if raw.get("schedule") == "it" else f"Which one is “{raw.get('schedule')}”?"
    return Question(asked, tuple(Choice(each.name, {LIST: [*known, {**raw, "schedule": ref(each)}, *rest]}, ("schedule",)) for each in candidates[:4]))


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------
def _stored(schedule: Schedule) -> dict:
    """A schedule's settings as a card's data keeps them."""
    return {
        "time": f"{schedule.at:%H:%M}", "days": list(schedule.days), "notify": schedule.notify, "channel": schedule.channel,
        "state": schedule.state, "paused_until": schedule.paused_until.isoformat() if schedule.paused_until else None,
    }


def _from_stored(schedule: Schedule, held: dict) -> Schedule:
    from datetime import date

    hour, _, minute = held["time"].partition(":")
    return replace(
        schedule, at=time(int(hour), int(minute)), days=tuple(held["days"]), notify=held["notify"], channel=held["channel"],
        state=held["state"], paused_until=date.fromisoformat(held["paused_until"]) if held.get("paused_until") else None,
    )


def changed(schedule: Schedule, item: dict, today) -> tuple[Schedule, list[str]]:
    """The schedule as the item asks for it, and what couldn't be read (in words)."""
    after, problems = schedule, []

    def attempt(read):
        nonlocal after
        try:
            after = read()
        except UserError as error:
            problems.append(str(error))

    if item.get("time"):
        attempt(lambda: replace(after, at=rules.read_time(str(item["time"]))))
    if item.get("days"):
        attempt(lambda: replace(after, days=rules.changed_days(after.days, rules.read_days(item["days"]), item.get("days_change") or SET)))
        if not after.days:
            problems.append("That leaves no day at all: remove it or pause it instead")
            after = replace(after, days=schedule.days)
    if item.get("notify") in (SILENT, NOTIFY):
        after = replace(after, notify=item["notify"])
    if item.get("channel"):
        channel = str(item["channel"]).strip().lstrip("#").lower()
        if channel in config.CHANNELS:
            after = replace(after, channel=channel)
        else:
            problems.append(f"I don't know a channel called #{channel}")
    paused, until = item.get("paused"), str(item.get("until") or "").strip()
    if paused == RESUME:
        after = replace(after, state=ON, paused_until=None)
    elif paused == PAUSE or until:
        if until:
            attempt(lambda: replace(after, state=PAUSED, paused_until=rules.read_until(until, today)))
        else:
            after = replace(after, state=PAUSED, paused_until=None)
    return after, problems


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    schedules = await every()
    today = rules.local_today(clock.now())
    by_id = {each.id: each for each in schedules}
    # A card being corrected: what it already holds stays, and the message changes it
    held: dict[int, dict] = {}
    for item in (request.previous or {}).get(LIST, []):
        schedule = by_id.get(int(str(item["schedule"])[len(REF):])) if str(item.get("schedule", "")).startswith(REF) else None
        if schedule is not None:
            held[schedule.id] = item
    found, warnings, unclear = _resolve(schedules, data[LIST], request.text)
    marked: set[int] = set()
    for index, (item, schedule, picked) in enumerate(found):
        if schedule.locked:
            warnings.append(f"{schedule.name} is the bot's own: it isn't changed here")
            continue
        before = _from_stored(schedule, held[schedule.id]) if schedule.id in held else schedule
        after, problems = changed(before, item, today)
        warnings += [f"{schedule.name}: {problem}" for problem in problems]
        held[schedule.id] = {"schedule": ref(schedule), **_stored(after)}
        if picked or is_guessed(guessed, LIST, index):
            marked.add(schedule.id)
    lines, kept, coming = [], [], []
    for schedule_id, item in held.items():
        schedule = by_id[schedule_id]
        after = _from_stored(schedule, item)
        differs = rules.change_lines(schedule, after, today)
        if not differs:
            warnings.append(f"{schedule.name} is already like that: nothing changes")
            continue
        lines += [flag(f"**{schedule.name}**", schedule_id in marked), *differs]
        kept.append(item)
        coming.append(rules.next_line(schedule.name, await scheduler.coming(after), today))
    question = _which_one([dict(item) for item, _, _ in found], unclear)
    if not kept and question is None:
        raise UserError("; ".join(warnings) or "Nothing to change.")
    if coming:
        lines.append(f"-# Next after this: {' · '.join(coming)}")
    return Proposal(lines=tuple(lines), data={LIST: kept}, warnings=tuple(warnings), kind="change", question=question)


async def change_save(request: Request, data: dict) -> str:
    schedules = {each.id: each for each in await every()}
    today = rules.local_today(clock.now())
    said = []

    def write(conn):
        for item in data[LIST]:
            schedule = schedules.get(int(item["schedule"][len(REF):]))
            if schedule is None or schedule.locked:
                continue
            after = _from_stored(schedule, item)
            timetable.db_update(
                conn, schedule.id, clock.now(), at=after.at, days=after.days, notify=after.notify, channel=after.channel,
                state=after.state, paused_until=after.paused_until,
            )
            said.append(f"**{schedule.name}** · " + " · ".join(rules.change_lines(schedule, after, today)))

    await request.db.run(write)
    await scheduler.book()  # the runs that are booked follow the schedule at once
    list_changed(request.user.id)
    return f"✅ Saved · {ICON} " + "\n".join(said)


async def change_check(request: Request, data: dict) -> str:
    """Read the rows back: each is as the card said."""
    schedules = {each.id: each for each in await every()}
    wrong = []
    for item in data[LIST]:
        schedule = schedules.get(int(item["schedule"][len(REF):]))
        if schedule is None:
            wrong.append("a schedule on the card is no longer there")
        elif _stored(schedule) != {key: item[key] for key in _stored(schedule)}:
            wrong.append(f"{schedule.name} is not as the card said")
    return "; ".join(wrong)


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------
def addable() -> list[tuple[str, tuple[str, str]]]:
    """What can be given a schedule: (its name in words, its handler), for
    every handler a task supplied a default for that is not the bot's own."""
    return [
        (scheduler.label(task, kind), (task, kind))
        for (task, kind), default in scheduler.defaults().items() if not default.locked
    ]


def _handler(what: str, said: str) -> tuple[str, tuple[str, str]]:
    things = addable()
    try:
        found = names.find(things, what, lambda each: each[0])
    except names.Ambiguous:
        raise
    except UserError:
        can = ", ".join(label for label, _ in things) or "nothing yet"
        raise UserError(f"I can't schedule “{what.strip()}”. What I can: {can}.")
    return found


async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    previous = request.previous or {}
    what = str(data.get("what") or previous.get("what") or "")
    label, (task, kind) = _handler(what, request.text)
    handler = scheduler.handler_name(task, kind)
    default = scheduler.defaults()[(task, kind)]
    today = rules.local_today(clock.now())
    title = label[:1].upper() + label[1:]
    days = rules.read_days(data["days"]) if data.get("days") else tuple(previous.get("days") or default.days)
    notify = data.get("notify") or previous.get("notify") or default.notify
    channel = str(data.get("channel") or previous.get("channel") or default.channel).lstrip("#").lower()
    if channel not in config.CHANNELS:
        raise UserError(f"I don't know a channel called #{channel}.")
    said_time = data.get("time") or previous.get("time")
    raw = {"what": what, "days": [rules.DAY_WORDS[day] for day in days], "notify": notify, "channel": channel}
    if not said_time:
        # Asked on the card, with the likely answers as buttons; any other time is typed
        likely = dict.fromkeys([timeinput.format_time(default.at), timeinput.format_time(time((default.at.hour + 12) % 24, default.at.minute))])
        question = Question("At what time?", tuple(Choice(each, {**raw, "time": each}, ("time",)) for each in likely))
        return Proposal(lines=(f"**{title}** · {timetable.days_text(days)} at ❔",), data={**raw, "time": ""}, kind="new", question=question)
    at = rules.read_time(str(said_time))
    existing = await request.db.run(timetable.db_all, True)
    same = [each for each in existing if each.steps == (handler,) and each.at == at and each.state != REMOVED]
    if same:
        raise UserError(f"{ICON} **{same[0].name}** already runs {rules.when(same[0])}: nothing to add.")
    removed = next((each for each in existing if each.steps == (handler,) and each.state == REMOVED), None)
    taken = {each.name.lower() for each in existing if each.state != REMOVED and (removed is None or each.id != removed.id)}
    name = rules.name_for(label, at, taken)
    made = Schedule(0, request.user.id, name, at, timetable.ZONE, days, notify, channel, ON, None, default.missed, timetable.MINE, None, False, (handler,))
    others = [each for each in existing if each.steps == (handler,) and each.state != REMOVED]
    lines = [
        flag(f"**{name}** · {rules.when(made)}", is_guessed(guessed, "time")),
        f"-# #{channel} · {rules.notify_text(notify)} · next: {rules.moment_text((timetable.next_occurrence(made, clock.now())).local, today)}",
    ]
    if others:
        lines.append("-# also " + ", ".join(rules.when(each) for each in others))
    held = {**raw, "time": f"{at:%H:%M}", "handler": handler, "name": name, "days_kept": list(days), "restore": removed.id if removed else None}
    return Proposal(lines=tuple(lines), data=held, kind="new")


async def add_save(request: Request, data: dict) -> str:
    hour, _, minute = data["time"].partition(":")
    at, days = time(int(hour), int(minute)), tuple(data["days_kept"])
    task, kind = scheduler.handler_parts(data["handler"])
    default = scheduler.defaults().get((task, kind))

    def write(conn):
        if data.get("restore"):
            # One I removed, added back: the same row, so its history is still its own
            timetable.db_update(conn, data["restore"], clock.now(), at=at, days=days, notify=data["notify"], channel=data["channel"], state=ON, paused_until=None, name=data["name"])
            return data["restore"]
        return timetable.db_add(
            conn, clock.now(), user_id=request.user.id, name=data["name"], at=at, steps=(data["handler"],), days=days, notify=data["notify"],
            channel=data["channel"], missed=default.missed if default else timetable.RUN_LATE,
        )

    schedule_id = await request.db.run(write)
    await scheduler.book()
    list_changed(request.user.id)
    made = await request.db.run(timetable.db_get, schedule_id)
    return f"✅ Saved · {ICON} **{made.name}** · {rules.when(made)}"


async def add_check(request: Request, data: dict) -> str:
    hour, _, minute = data["time"].partition(":")
    there = [each for each in await every() if each.steps == (data["handler"],) and each.at == time(int(hour), int(minute)) and each.state == ON]
    return "" if there else f"{data['name']} is not among the schedules"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------
async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    schedules = await every()
    found, warnings, unclear = _resolve(schedules, data[LIST], request.text)
    lines, kept = [], []
    for index, (item, schedule, picked) in enumerate(found):
        if schedule.locked:
            warnings.append(f"{schedule.name} is the bot's own: it isn't removed here")
            continue
        lines.append(flag(f"**{schedule.name}** · {rules.when(schedule)} → removed", picked or is_guessed(guessed, LIST, index)))
        kept.append({"schedule": ref(schedule)})
    question = _which_one([dict(item) for item, _, _ in found], unclear)
    if not kept and question is None:
        raise UserError("; ".join(warnings) or "Nothing to remove.")
    if kept:
        lines.append("-# It stops running. What it did is kept, and it can be added back")
    return Proposal(lines=tuple(lines), data={LIST: kept}, warnings=tuple(warnings), kind="remove", confirm_label="Remove", question=question)


async def remove_save(request: Request, data: dict) -> str:
    schedules = {each.id: each for each in await every()}
    gone = []

    def write(conn):
        for item in data[LIST]:
            schedule = schedules.get(int(item["schedule"][len(REF):]))
            if schedule is not None and not schedule.locked:
                timetable.db_update(conn, schedule.id, clock.now(), state=REMOVED, paused_until=None)
                gone.append(schedule.name)

    await request.db.run(write)
    await scheduler.book()
    list_changed(request.user.id)
    left = ", ".join(each.name for each in await every() if not each.locked) or "nothing"
    return f"🗑️ Removed {', '.join(f'**{name}**' for name in gone)} · still scheduled: {left}"


async def remove_check(request: Request, data: dict) -> str:
    still = {ref(each) for each in await every()}
    left = [item["schedule"] for item in data[LIST] if item["schedule"] in still]
    return f"{len(left)} of them still there" if left else ""

