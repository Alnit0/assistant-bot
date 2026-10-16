import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from core import attention, cards, clock, database, hub, hubcard, llm, messages, names, notify, recurrence, scheduler, summaries, timeinput
from core import day as days
from core.actions import BOOLEAN, INTEGER, LIST, MINUTES, TIME, Choice, Field, LiveReply, Proposal, Question, Request, State, flag, is_guessed, is_reference
from core.attention import TIMED, Item
from core.cards import Card
from core.errors import UserError
from tasks.nudges import rules, store
from tasks.nudges.rules import DAILY, DAYS, EVERY, ICON, ONCE, REPEATS, TASK, WEEKDAYS, Nudge

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Reminders I set myself, in plain words, and what happens when one goes off.
#
# Setting, changing and removing one is a card that only Save writes. When
# it is due is the engine's (core/scheduler.py): Save books the next
# occurrence as a job with a run key, and each one that goes off books the
# one after. Going off: the occurrence is claimed in `nudges_fired` first,
# so it is never posted twice; it is posted at the bottom of the hub through
# the one way out (core/notify.py, a kind that gets through quiet hours and
# never goes to ntfy), as the neutral line, then drawn with Done and Snooze.
# One that can't be posted is tried again after 1, 2 and 5 minutes, then
# every 5, as a pill reminder is. One missed while the bot was off goes off
# once when it is back, marked late.
# ---------------------------------------------------------------------------
FIRE, CARD = "fire", "card"
KIND = "nudges.reminder"
RETRY_MINUTES = (1, 2, 5)  # after the first, second and third try that failed; then every 5
MAX_TRIES = 30
LIST_KEY = "nudges"
REF = "n"

ONLY_FOR = (
    "Reminders the user sets for themselves at a time of day: \"remind me at 5pm to call Mum\", \"gym at 6\", "
    "\"dentist Friday 3pm\" (a thing with a time is a reminder, even an appointment), \"remind me to buy milk\" (asked "
    "to be reminded, no time yet: its card asks when), \"remind me in 20 minutes to check the oven\", \"every Monday at "
    "9am put the bins out\", moving one (\"move that to 6\"), removing one, ticking off one that went off (\"done\" "
    "straight after it), and seeing them. Also things that expire or must be renewed on a day, with nudges before it: \"Kiwa domain expires 3 March, yearly\", \"passport expires June 2031\", \"rego due 14 Nov, every year\", \"renewed the Kiwa domain\", \"what's expiring soon?\". A thing to do with no day it expires on (\"renew the passport\") is a to-do. Not pills or their reminders (that is the pills task), not a thing to do "
    "with no time that the user does not ask to be reminded of (the to-dos task), and not when the bot posts its own "
    "things (the schedule task)."
)
# With the calendar taking new events (CALENDAR_WRITE): an appointment said with a time is the
# calendar's, and a reminder is what the user asks to be reminded of
ONLY_FOR_WITH_CALENDAR = (
    "Reminders the user asks for, at a time of day: \"remind me at 5pm to call Mum\", \"remind me about the dentist "
    "Friday\", \"remind me to buy milk\" (asked to be reminded, no time yet: its card asks when), \"remind me in 20 "
    "minutes to check the oven\", \"every Monday at 9am put the bins out\" (a thing to do at a time, again and again), "
    "moving one (\"move that to 6\"), removing one, ticking off one that went off (\"done\" straight after it), and "
    "seeing them. Also things that expire or must be renewed on a day, with nudges before it: \"Kiwa domain expires 3 March, yearly\", \"passport expires June 2031\", \"rego due 14 Nov, every year\", \"renewed the Kiwa domain\", \"what's expiring soon?\". A thing to do with no day it expires on (\"renew the passport\") is a to-do. An appointment or a plan said with a day and a time and no \"remind me\" (\"dentist Friday 3pm\") "
    "is an event for the calendar task. Not pills or their reminders (that is the pills task), not a thing to do with "
    "no time that the user does not ask to be reminded of (the to-dos task), and not when the bot posts its own "
    "things (the schedule task)."
)
EXAMPLES = ("remind me at 5pm to call Mum", "every weekday at 8am remind me to stretch", "move that to 6")

_WHICH = (
    "Which reminder, exactly as the user said it (its words or part of them, from the state). \"that\" or \"it\" with "
    "nothing named: @that. Never complete or correct it."
)


def ref(nudge: Nudge) -> str:
    return f"{REF}{nudge.id}"


async def every(user_id: int) -> list[Nudge]:
    return await store.every(user_id)


def _day_words(found) -> tuple[int, ...]:
    return tuple(sorted({rules.DAY_WORDS.index(str(each).lower()[:3]) for each in found or [] if str(each).lower()[:3] in rules.DAY_WORDS}))


# ---------------------------------------------------------------------------
# Booking: the engine runs it
# ---------------------------------------------------------------------------
def _key(nudge_id: int, local: str, extra: str = "") -> str:
    return f"n{nudge_id}@{local}{extra}"


async def cancel(nudge_id: int) -> None:
    """Take out the next occurrence that is booked (a snooze that is waiting stays)."""
    for job in await scheduler.pending_jobs(TASK, FIRE):
        if job.payload.get("id") == nudge_id and not job.payload.get("snooze"):
            await scheduler.cancel_job(job.id)


async def book(nudge: Nudge, after: datetime | None = None) -> datetime | None:
    """Book its next occurrence after `after` (now), in place of any that was booked."""
    await cancel(nudge.id)
    due = rules.next_due(nudge, max(after or clock.now(), clock.now()))
    if due is not None:
        local = rules.local(due)
        await scheduler.add_job(TASK, FIRE, due, {"id": nudge.id, "local": local}, user_id=nudge.user_id, key=_key(nudge.id, local))
    return due


# ---------------------------------------------------------------------------
# The card in the hub, the list, and what extraction is told
# ---------------------------------------------------------------------------
async def hub_card(user_id: int) -> Card | None:
    """What is still to come today, or None: then there is no card."""
    now = clock.now()
    waiting = rules.coming(await every(user_id), now)
    if not waiting:
        return None
    return Card(rules.card_text(waiting), (), rules.card_layout(waiting, now))


def changed(user_id: int) -> None:
    hubcard.changed(TASK, user_id, lambda: hub_card(user_id))
    summaries.changed(TASK, user_id)
    attention.changed()


async def post_job(job) -> None:
    user_id = job.user_id or await database.run(scheduler._db_owner)
    if user_id is None:
        scheduler.note(job, "not posted: there is nobody to post for")
        return
    posted = await hubcard.post(TASK, user_id, lambda: hub_card(user_id))
    scheduler.note(job, "posted" if posted is not None else "not posted: nothing still to come today")


def listed(nudges: list[Nudge], today: date) -> str:
    if not nudges:
        return rules.NOTHING
    return "\n".join([f"{ICON} **Reminders** · {len(nudges)}", *(f"• {rules.line(each, today)}" for each in nudges)])


async def show(request: Request, data: dict, guessed: frozenset) -> LiveReply:
    return LiveReply(LIST_KEY, listed(await every(request.user.id), days.today()))


async def state(request: Request) -> State:
    today = days.today()
    lines = [f"{each.text} ({rules.repeat_text(each, today)} at {timeinput.format_time(each.at)})" for each in await every(request.user.id)]
    latest = await database.run(store.db_latest, request.user.id)
    if latest is not None:
        gone = await database.run(store.db_get, latest.nudge_id)
        if gone is not None:
            lines.append(f"(the last one that went off: {gone.text}, at {timeinput.format_moment(latest.due_at)})")
    from tasks.nudges import expiry

    lines += [f"expires: {each.name} ({expiry.short(each.due, today)}, {recurrence.cycle_text(each.cycle_months)})" for each in await expiry.every(request.user.id)]
    return State("The user's reminders now", tuple(lines), "none")


async def item_names(request: Request) -> list[str]:
    from tasks.nudges import expiry

    return [each.text for each in await every(request.user.id)] + [each.name for each in await expiry.every(request.user.id)]


# ---------------------------------------------------------------------------
# Reading what was said: Python works out every time and day
# ---------------------------------------------------------------------------
def _time_question(typed: str, raw: dict) -> Question:
    try:
        timeinput.parse_time(typed)
    except timeinput.AmbiguousTime as which:
        return Question(f"Is that {typed} in the morning or the evening?", tuple(Choice(timeinput.format_time(each), {**raw, "time": timeinput.format_time(each)}, ("time",)) for each in which.options))
    except Exception:
        pass
    return Question("At what time?")


def _read(item: dict, now: datetime, was: Nudge | None = None) -> tuple[dict, list[str], Question | None, set[str]]:
    """What a reminder will be, as a card's data, from what was said (and what it was);
    what could not be read; the question to ask, if any; what the code guessed."""
    today = days.day_of(now)
    words = str(item.get("text") or (was.text if was else "")).strip()
    words = words[:1].upper() + words[1:]
    warnings, guessed = [], set()
    repeat = str(item.get("repeat") or (was.repeat if was else ONCE))
    repeat = repeat if repeat in REPEATS else ONCE
    weekdays = _day_words(item.get("weekdays")) or (was.weekdays if was else ())
    every_days = int(item.get("every_days") or (was.every_days if was else 1) or 1)
    at = was.at if was else None
    first = was.first if was else None
    raw = {key: value for key, value in item.items() if key not in ("guessed", "not_included")}
    if item.get("in_minutes"):
        moment = now + timedelta(minutes=int(item["in_minutes"]))
        at, first, repeat = time(days.local_time(moment).hour, days.local_time(moment).minute), days.day_of(moment), ONCE
    elif item.get("time"):
        try:
            at = timeinput.parse_time(str(item["time"]))
        except Exception:
            return {}, warnings, _time_question(str(item["time"]), raw), guessed
    if at is None:
        return {}, warnings, _time_question("", raw), guessed
    if item.get("day"):
        try:
            first = timeinput.parse_date(str(item["day"]), today)
        except Exception:
            warnings.append(f"“{item['day']}” is not a day I can read")
    if repeat == ONCE and (first is None or (was is None and not item.get("day") and not item.get("in_minutes"))):
        # No day said: today if the time is still to come, else tomorrow, and marked as a guess
        first = today if days.at(today, at) > now else today + timedelta(days=1)
        if first != today:
            guessed.add("day")
    if repeat == DAYS and not weekdays:
        warnings.append("Which days of the week? Say them and I'll set them")
        repeat = DAILY
    if repeat == EVERY:
        first = first or today
        every_days = max(1, every_days)
    data = {
        "text": words, "at": f"{at:%H:%M}", "repeat": repeat, "first": first.isoformat() if first else None,
        "weekdays": list(weekdays), "every_days": every_days,
    }
    return data, warnings, None, guessed


def from_data(data: dict, user_id: int, nudge_id: int = 0) -> Nudge:
    hour, minute = (int(part) for part in data["at"].split(":"))
    return Nudge(nudge_id, user_id, data["text"], time(hour, minute), data["repeat"], date.fromisoformat(data["first"]) if data.get("first") else None, tuple(data.get("weekdays") or ()), int(data.get("every_days") or 1))


def _next_line(nudge: Nudge, now: datetime) -> str:
    due = rules.next_due(nudge, now)
    return f"-# next: {rules.repeat_text(replace(nudge, repeat=ONCE, first=days.day_of(due)), days.day_of(now))} at {timeinput.format_moment(due)}" if due else "-# that time has gone by"


# ---------------------------------------------------------------------------
# Add, change, remove: cards
# ---------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    now = clock.now()
    item = {**(request.previous or {}).get("said", {}), **{key: value for key, value in data.items() if value not in (None, "", [])}}
    if not str(item.get("text") or "").strip():
        raise UserError("What should I remind you of?")
    held, warnings, question, mine = _read(item, now)
    if question is not None:
        words = str(item.get("text")).strip()
        return Proposal(lines=(f"**{words[:1].upper() + words[1:]}** · at ❔",), data={"said": item}, kind="new", question=question)
    nudge = from_data(held, request.user.id)
    guess = "day" in mine or is_guessed(guessed, "time") or is_guessed(guessed, "day")
    lines = (flag(rules.line(nudge, days.day_of(now)), guess), _next_line(nudge, now))
    return Proposal(lines=lines, data={"said": item, "nudge": held}, warnings=tuple(warnings), kind="new", guessed=tuple(sorted(mine)))


async def add_save(request: Request, data: dict) -> str:
    nudge = from_data(data["nudge"], request.user.id)
    nudge_id = await request.db.run(store.db_add, nudge, clock.now())
    saved = replace(nudge, id=nudge_id)
    due = await book(saved)
    changed(request.user.id)
    return f"✅ Saved · {ICON} {rules.line(saved, days.today())}" + (f" · next {timeinput.format_moment(due)}" if due else "")


async def add_check(request: Request, data: dict) -> str:
    there = [each for each in await every(request.user.id) if each.text == data["nudge"]["text"]]
    if not there:
        return "the reminder is not there"
    booked = [job for job in await scheduler.pending_jobs(TASK, FIRE) if job.payload.get("id") in {each.id for each in there}]
    return "" if booked or rules.next_due(there[-1], clock.now()) is None else "its next time is not booked"


async def _which(request: Request, item: dict, nudges: list[Nudge]) -> Nudge:
    wanted = str(item.get("reminder") or "").strip()
    if wanted.lower().startswith(REF) and wanted[len(REF):].isdigit():
        found = [each for each in nudges if each.id == int(wanted[len(REF):])]
        if found:
            return found[0]
    if is_reference(wanted) or not wanted:
        # "that": the one that went off last, else the one set last
        latest = await database.run(store.db_latest, request.user.id)
        last = next((each for each in nudges if latest is not None and each.id == latest.nudge_id), None)
        if last is not None:
            return last
        if nudges:
            return max(nudges, key=lambda each: each.id)
        raise UserError("You have no reminders.")
    try:
        return names.find(nudges, wanted, lambda each: each.text)
    except names.Unknown:
        raise UserError(f"There is no reminder “{wanted}”.")
    except names.Ambiguous as which:
        raise UserError(f"“{wanted}” could be {' or '.join(f'**{each.text}**' for each in which.candidates[:4])}: say which.")


def _change_lines(before: Nudge, after: Nudge, today: date) -> list[str]:
    found = []
    if before.text != after.text:
        found.append(f"words · {before.text} → {after.text}")
    if before.at != after.at:
        found.append(f"time · {timeinput.format_time(before.at)} → {timeinput.format_time(after.at)}")
    if (before.repeat, before.first, before.weekdays, before.every_days) != (after.repeat, after.first, after.weekdays, after.every_days):
        found.append(f"when · {rules.repeat_text(before, today)} → {rules.repeat_text(after, today)}")
    return found


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    now = clock.now()
    previous = request.previous or {}
    item = {**previous.get("said", {}), **{key: value for key, value in data.items() if value not in (None, "", [])}}
    nudges = await every(request.user.id)
    was = await _which(request, item, nudges)
    item["reminder"] = ref(was)
    held, warnings, question, _ = _read(item, now, was)
    if question is not None:
        return Proposal(lines=(f"**{was.text}** · time · {timeinput.format_time(was.at)} → ❔",), data={"said": item}, kind="change", question=question)
    after = from_data(held, request.user.id, was.id)
    differs = _change_lines(was, after, days.day_of(now))
    if not differs:
        raise UserError(f"{rules.line(was, days.day_of(now))} is already like that.")
    # A time Claude marked as a guess ("move that to 6", read as the evening) is shown with ❓
    differs = [flag(each, is_guessed(guessed, "time")) if each.startswith("time · ") else each for each in differs]
    lines = (flag(f"**{was.text}**", is_guessed(guessed, "reminder")), *differs, _next_line(after, now))
    return Proposal(lines=lines, data={"said": item, "nudge": held, "id": was.id}, warnings=tuple(warnings), kind="change")


async def change_save(request: Request, data: dict) -> str:
    after = from_data(data["nudge"], request.user.id, data["id"])
    await request.db.run(store.db_change, after)
    due = await book(after)
    changed(request.user.id)
    return f"✅ Saved · {ICON} {rules.line(after, days.today())}" + (f" · next {timeinput.format_moment(due)}" if due else "")


async def change_check(request: Request, data: dict) -> str:
    there = await request.db.run(store.db_get, data["id"])
    return "" if there is not None and there == from_data(data["nudge"], request.user.id, data["id"]) else "the reminder is not as the card said"


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    nudge = await _which(request, data, await every(request.user.id))
    line = f"**{nudge.text}** → removed"
    return Proposal(lines=(flag(line, is_guessed(guessed, "reminder")), f"-# was {rules.when_text(nudge, days.today())}"), data={"id": nudge.id, "text": nudge.text}, kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    await request.db.run(store.db_remove, data["id"], clock.now())
    await cancel(data["id"])
    changed(request.user.id)
    return f"🗑️ Removed **{data['text']}**"


async def remove_check(request: Request, data: dict) -> str:
    return "the reminder is still there" if await request.db.run(store.db_get, data["id"]) is not None else ""


# ---------------------------------------------------------------------------
# Going off
# ---------------------------------------------------------------------------
def retry_after(tries: int) -> timedelta:
    return timedelta(minutes=RETRY_MINUTES[min(tries, len(RETRY_MINUTES)) - 1] if tries <= len(RETRY_MINUTES) else 5)


def item(nudge: Nudge, due: datetime) -> Item:
    """What the alert is about, for the one ranking: due now. Never the reminder's words."""
    return Item("a reminder is due", TIMED, when=due, can_act=True, short=(f"due {attention.short_time(due)}",))


async def fire_job(job) -> None:
    """Scheduler handler: one occurrence of a reminder goes off (or a snoozed one again)."""
    payload = job.payload
    nudge = await database.run(store.db_get, int(payload.get("id", 0)))
    if nudge is None:
        scheduler.note(job, "not posted: the reminder was removed")
        return
    local = str(payload["local"])
    late = job.is_late and not payload.get("snooze")
    fired_id = await database.run(store.db_went_off, nudge.user_id, nudge.id, local, job.due_at, late)
    if not payload.get("snooze") and not payload.get("try"):
        await book(nudge, after=job.due_at)  # the next one, whatever becomes of this one
    if fired_id is None:
        scheduler.note(job, "not posted: it went off already")
        return
    channel_id = hub.channel_id()
    try:
        if channel_id is None:
            raise UserError("the hub channel is not set")
        first = Card(rules.notice(job.due_at, late))
        message_id = await notify.post(KIND, channel_id, first, user_id=nudge.user_id, item=item(nudge, job.due_at), key=f"nudge{fired_id}")
        if message_id is None:
            raise UserError("the hub channel can't be found")
    except Exception as error:
        await database.run(store.db_unclaim, fired_id)
        tries = int(payload.get("try") or 0) + 1
        if tries <= MAX_TRIES:
            again = clock.now() + retry_after(tries)
            await scheduler.add_job(TASK, FIRE, again, {**payload, "try": tries}, user_id=nudge.user_id, key=_key(nudge.id, local, f"+r{tries}"))
        log.warning("Reminders: one could not be posted (try %s): %s", tries, error)
        scheduler.note(job, f"not posted (try {tries}): {error}; tried again later")
        return
    await database.run(store.db_posted, fired_id, channel_id, message_id)
    row = rules.fired_row(fired_id)
    await cards.edit(channel_id, message_id, Card(rules.fired_text(nudge, job.due_at, late), (row,), rules.fired_layout(nudge, job.due_at, late, row)))
    await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=nudge.user_id)
    # The bot's latest word in the hub is about this reminder: "done" straight after is its (core/llm.py)
    llm.task_answered(channel_id, TASK)
    changed(nudge.user_id)
    scheduler.note(job, "posted" + (", late" if late else ""))


# ---------------------------------------------------------------------------
# The buttons on a reminder that went off
# ---------------------------------------------------------------------------
async def _pressed(press: cards.Press) -> tuple:
    fired_id = int(press.arg.split(":")[0]) if press.arg.split(":")[0].isdigit() else 0
    fired = await press.db.run(store.db_fired_by_id, fired_id)
    nudge = await press.db.run(store.db_get, fired.nudge_id) if fired is not None else None
    return fired, nudge


async def on_done(press: cards.Press) -> str:
    fired, nudge = await _pressed(press)
    if fired is None or not fired.is_open:
        await press.remove()
        return "already dealt with"
    await press.db.run(store.db_done, fired.id, clock.now())
    await press.remove()  # dealt with: it leaves the hub
    changed(press.user.id)
    return f"✅ {nudge.text if nudge else 'Reminder'} · done"


async def on_snooze(press: cards.Press) -> str:
    fired, nudge = await _pressed(press)
    if fired is None or nudge is None or not fired.is_open:
        await press.remove()
        return "already dealt with"
    row = rules.snooze_row(fired.id)
    await press.update(Card(rules.fired_text(nudge, fired.due_at, fired.late), (row,), rules.fired_layout(nudge, fired.due_at, fired.late, row)))
    return "asked how long"


async def on_back(press: cards.Press) -> str:
    fired, nudge = await _pressed(press)
    if fired is None or nudge is None:
        return "gone"
    row = rules.fired_row(fired.id)
    await press.update(Card(rules.fired_text(nudge, fired.due_at, fired.late), (row,), rules.fired_layout(nudge, fired.due_at, fired.late, row)))
    return "back"


def snoozed_until(minutes: int, fired_due: datetime, now: datetime) -> datetime:
    """10 minutes and 1 hour from now; "Tomorrow" is tomorrow at the time it was due."""
    if minutes >= 24 * 60:
        return days.at(days.day_of(now) + timedelta(days=1), days.local_time(fired_due))
    return now + timedelta(minutes=minutes)


async def on_snooze_for(press: cards.Press) -> str:
    fired, nudge = await _pressed(press)
    if fired is None or nudge is None or not fired.is_open:
        await press.remove()
        return "already dealt with"
    minutes = int(press.arg.split(":")[1])
    until = snoozed_until(minutes, fired.due_at, clock.now())
    await press.db.run(store.db_snoozed, fired.id, until)
    await scheduler.add_job(TASK, FIRE, until, {"id": nudge.id, "local": fired.local, "snooze": True}, user_id=nudge.user_id, key=_key(nudge.id, fired.local, f"~{until:%Y%m%d%H%M}"))
    await press.remove()
    changed(press.user.id)
    return f"💤 {nudge.text} · again at {timeinput.format_moment(until)}"


async def done(request: Request, data: dict, guessed: frozenset) -> str:
    """ "done" in words for a reminder that went off, as its Done button: the one replied to,
    else the one named, else the latest still waiting. A log: no card."""
    waiting = await request.db.run(store.db_open, request.user.id)  # the latest first
    if not waiting:
        raise UserError("No reminder that went off is waiting: there is nothing to tick off.")
    nudges = {each.id: each for each in await every(request.user.id)}
    fired = next((each for each in waiting if request.replied_to is not None and each.message_id == request.replied_to), None)
    wanted = str(data.get("reminder") or "").strip()
    if fired is None and wanted and not is_reference(wanted):
        meant = await _which(request, {"reminder": wanted}, [nudges[each.nudge_id] for each in waiting if each.nudge_id in nudges])
        fired = next(each for each in waiting if each.nudge_id == meant.id)
    fired = fired or waiting[0]
    await request.db.run(store.db_done, fired.id, clock.now())
    channel_id = hub.channel_id()
    if fired.message_id and channel_id is not None:
        await cards.delete(channel_id, fired.message_id)  # dealt with: it leaves the hub, as with the button
    changed(request.user.id)
    nudge = nudges.get(fired.nudge_id)
    return f"✅ {nudge.text if nudge else 'Reminder'} · done"


def register() -> None:
    cards.register(TASK, rules.DONE, on_done)
    cards.register(TASK, rules.SNOOZE, on_snooze)
    cards.register(TASK, rules.SNOOZE_FOR, on_snooze_for)
    cards.register(TASK, rules.BACK, on_back)


# ---------------------------------------------------------------------------
# What extraction fills in
# ---------------------------------------------------------------------------
_FIELDS = (
    Field("text", "What to be reminded of, in the user's words, without the time (\"call Mum\").", required=True),
    Field("time", "The time of day, if the user gave one.", TIME),
    Field("in_minutes", "For \"in 20 minutes\", \"in an hour\": how many minutes from now. Leave out otherwise.", MINUTES),
    Field("day", "For a one-off: the day, exactly as the user said it (\"Friday\", \"tomorrow\"). Never work out a date."),
    Field(
        "repeat",
        "once (one day), daily (every day), weekdays (Monday to Friday), days (chosen days of the week: fill weekdays), "
        "every (every N days: fill every_days). Leave out for once.",
        choices=REPEATS,
    ),
    Field("weekdays", "For days: the days of the week named (\"every Monday\" -> mon).", LIST, choices=rules.DAY_WORDS),
    Field("every_days", "For every: N, as in every N days.", INTEGER),
)
_CHANGE = (Field("reminder", _WHICH, required=True), *(replace(each, required=False) for each in _FIELDS))
DESCRIPTIONS = {
    "nudge_add": "Set a reminder at a time (\"remind me at 5pm to call Mum\" -> text call Mum, time 5:00 pm; \"every Monday 9am bins out\" -> repeat days, weekdays mon, time 9:00 am). With no time said (\"remind me to buy milk\"), leave time out: the card asks.",
    "nudge_change": "Change a reminder: its time, its days or its words (\"move that to 6\" -> reminder @that, time 6:00). Give a time with no am or pm when the user said none.",
    "nudge_remove": "Remove a reminder (\"cancel the bins reminder\", \"stop reminding me to stretch\").",
    "nudge_show": "The user asks what reminders they have (\"my reminders\", \"what have I asked you to remind me of?\").",
    "nudge_done": "A reminder that went off is done (\"done\" straight after it, \"done the bins\", \"called the bank\"). A log: no card. With nothing named, leave reminder as @that.",
}


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action
    from tasks.nudges import expiry

    return [
        Action("nudge_add", DESCRIPTIONS["nudge_add"], _FIELDS, prepare=add_card, apply=add_save, verify=add_check, purpose=SET_UP, say=("remind me at 5pm to call Mum",)),
        Action("nudge_change", DESCRIPTIONS["nudge_change"], _CHANGE, prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("move that to 6",)),
        Action("nudge_remove", DESCRIPTIONS["nudge_remove"], (Field("reminder", _WHICH, required=True),), prepare=remove_card, apply=remove_save, verify=remove_check, purpose=SET_UP, say=("cancel the bins reminder",)),
        Action("nudge_show", DESCRIPTIONS["nudge_show"], needs_card=False, run=show, purpose=SEE, say=("my reminders",)),
        Action("nudge_done", DESCRIPTIONS["nudge_done"], (Field("reminder", _WHICH),), needs_card=False, run=done, purpose=EACH_DAY, say=("done the bins",)),
        *expiry.actions(),
    ]
