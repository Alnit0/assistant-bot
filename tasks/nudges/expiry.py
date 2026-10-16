import json
import logging
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from core import cards, clock, config, database, design, hub, messages, names, notify, recurrence, scheduler, timeinput, timetable
from core import day as days
from core.actions import INTEGER, LIST, Field, Proposal, Request, Shown
from core.attention import PROBLEM, TIMED, Item
from core.cards import Button, Card
from core.errors import UserError
from tasks.nudges.rules import ICON, SNOOZES, TASK

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Expiries and renewals, part of reminders: "Kiwa domain expires 3 March,
# yearly", "passport expires June 2031", "rego due 14 Nov, every year". A day,
# a cycle (yearly, monthly, every N months, or none: the repeat engine's
# months, core/recurrence.py) and the days before to be told (30, 7 and 1 by
# default; "remind me 60 days before" changes them).
#
#   until the last day before: one quiet line in the briefing's overview
#   1 day before (or the day): posted like a reminder, with Done and Snooze;
#                              held by quiet hours, never ntfy; what a phone
#                              shows is neutral ("🔁 Renewal due · 3 Mar")
#   "renewed the Kiwa domain", or Done: one cycle on, the new date said, Undo;
#                              with no cycle it is done and leaves the list
#   gone by and not renewed:   one line in Needs a look, never a ping
#   "what's expiring soon?":   the next 90 days, soonest first
#
# A new one is a card first. Which one is meant is found by code
# (core/names.py) from the words as said.
# ---------------------------------------------------------------------------
RENEW_ICON = "🔁"
KIND = "nudges.renewal"
BEFORE = (30, 7, 1)  # days before the day, by default
SOON_DAYS = 90  # "what's expiring soon?"
CHECK_JOB, AGAIN_JOB = "renewals", "renewal_again"
CHECK_AT = time(9, 0)
CHECK_DEFAULT = timetable.Default("Renewals check", CHECK_AT, locked=True)
RENEWED, UNDO, R_SNOOZE, R_SNOOZE_FOR, R_BACK = "renewed", "renew_undo", "renew_snooze", "renew_snooze_for", "renew_back"


@dataclass(frozen=True)
class Expiry:
    id: int
    user_id: int
    name: str
    due: date
    anchor: int  # the date of the month it was set on: kept through short months
    cycle_months: int | None = None  # None: once
    before: tuple[int, ...] = BEFORE
    done_at: str | None = None

    @property
    def open(self) -> bool:
        return self.done_at is None


# --- pure ----------------------------------------------------------------------------------------------------------
def short(day: date, today: date) -> str:
    """"3 Mar", with the year when it is not this year or next ("Jun 2031")."""
    return f"{day.day} {day:%b}" + (f" {day.year}" if day.year > today.year + 1 or day.year < today.year else "")


def days_left(expiry: Expiry, today: date) -> int:
    return (expiry.due - today).days


def is_quiet(expiry: Expiry, today: date) -> bool:
    """In the overview line: from the first nudge to the last day before the post."""
    left = days_left(expiry, today)
    return expiry.open and 1 < left <= max(expiry.before or BEFORE)


def is_posting(expiry: Expiry, today: date) -> bool:
    """The one nudge that is posted: the last (1 day before by default), or the day itself if the last is 0."""
    left = days_left(expiry, today)
    return expiry.open and 0 <= left <= min(expiry.before or BEFORE)


def is_expired(expiry: Expiry, today: date) -> bool:
    return expiry.open and expiry.due < today


def rolled(expiry: Expiry) -> Expiry:
    """Renewed: one cycle on, on its own date of the month; with no cycle, done."""
    if expiry.cycle_months is None:
        return replace(expiry, done_at="renewed")
    return replace(expiry, due=recurrence.add_months(expiry.due, expiry.cycle_months, expiry.anchor))


def in_words(left: int) -> str:
    if left == 0:
        return "today"
    if left == 1:
        return "tomorrow"
    return f"in {left} days" if left > 0 else f"{-left} days ago"


def before_text(before: tuple[int, ...]) -> str:
    return ", ".join(f"{each} day{'' if each == 1 else 's'}" for each in sorted(before, reverse=True)) + " before"


def neutral(due: date, today: date) -> str:
    """What a phone shows: never the item's name."""
    return f"{RENEW_ICON} Renewal due · {short(due, today)}"


_MONTH_YEAR = re.compile(r"^\s*([a-z]{3,9})\.?\s+(\d{4})\s*$", re.IGNORECASE)


def read_date(said: str, today: date) -> tuple[date, bool]:
    """The day as said ("3 March", "14 Nov", "June 2031"), the next one to come; and whether only a month was said
    (then the 1st of it, so nothing is missed)."""
    found = _MONTH_YEAR.match(str(said or ""))
    if found:
        month = next((number for number in range(1, 13) if date(2000, number, 1).strftime("%B").lower().startswith(found[1].lower()[:3])), None)
        if month is not None:
            return date(int(found[2]), month, 1), True
    try:
        return timeinput.parse_date(str(said), today), False
    except Exception:
        raise UserError(f"{RENEW_ICON} “{said}” is not a date I can read. Try `3 March`, `14 Nov` or `June 2031`.")


# --- the store -----------------------------------------------------------------------------------------------------
_COLUMNS = "id, user_id, name, due, anchor, cycle_months, before, done_at"


def _expiry(row: tuple) -> Expiry:
    return Expiry(row[0], row[1], row[2], date.fromisoformat(row[3]), row[4], row[5], tuple(json.loads(row[6] or "[]")) or BEFORE, row[7])


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Expiry]:
    return [_expiry(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_expiries WHERE user_id = ? AND done_at IS NULL ORDER BY due, id", (user_id,))]


def db_every_user(conn: sqlite3.Connection) -> list[Expiry]:
    return [_expiry(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_expiries WHERE done_at IS NULL ORDER BY due, id")]


def db_get(conn: sqlite3.Connection, expiry_id: int) -> Expiry | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM nudges_expiries WHERE id = ?", (expiry_id,)).fetchone()
    return _expiry(row) if row else None


def db_add(conn: sqlite3.Connection, expiry: Expiry, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO nudges_expiries (user_id, name, due, anchor, cycle_months, before, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (expiry.user_id, expiry.name, expiry.due.isoformat(), expiry.anchor, expiry.cycle_months, json.dumps(list(expiry.before)), now.isoformat()),
    )
    return cursor.lastrowid


def db_set(conn: sqlite3.Connection, expiry: Expiry) -> None:
    conn.execute("UPDATE nudges_expiries SET due = ?, cycle_months = ?, before = ?, done_at = ? WHERE id = ?",
                 (expiry.due.isoformat(), expiry.cycle_months, json.dumps(list(expiry.before)), expiry.done_at, expiry.id))


def db_renewed(conn: sqlite3.Connection, before: Expiry, after: Expiry, now: datetime) -> int:
    """A renewal, kept for undo: what it was."""
    db_set(conn, after)
    cursor = conn.execute("INSERT INTO nudges_renewals (user_id, expiry_id, was_due, was_done, at) VALUES (?, ?, ?, ?, ?)",
                          (before.user_id, before.id, before.due.isoformat(), before.done_at, now.isoformat()))
    return cursor.lastrowid


def db_undo(conn: sqlite3.Connection, renewal_id: int) -> Expiry | None:
    """The renewal taken back: the day and the done it had. None if undone already."""
    row = conn.execute("SELECT expiry_id, was_due, was_done FROM nudges_renewals WHERE id = ? AND undone = 0", (renewal_id,)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE nudges_expiries SET due = ?, done_at = ? WHERE id = ?", (row[1], row[2], row[0]))
    conn.execute("UPDATE nudges_renewals SET undone = 1 WHERE id = ?", (renewal_id,))
    return db_get(conn, row[0])


def db_last_renewal(conn: sqlite3.Connection, user_id: int) -> int | None:
    row = conn.execute("SELECT id FROM nudges_renewals WHERE user_id = ? AND undone = 0 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return row[0] if row else None


def db_claim_post(conn: sqlite3.Connection, expiry_id: int, due: date) -> bool:
    """The 1-day nudge for this due day, once: True only the first time."""
    cursor = conn.execute("INSERT OR IGNORE INTO nudges_renewal_posts (expiry_id, due) VALUES (?, ?)", (expiry_id, due.isoformat()))
    return cursor.rowcount == 1


def db_posted(conn: sqlite3.Connection, expiry_id: int, due: date, channel_id: int, message_id: int) -> None:
    conn.execute("UPDATE nudges_renewal_posts SET channel_id = ?, message_id = ? WHERE expiry_id = ? AND due = ?", (channel_id, message_id, expiry_id, due.isoformat()))


def db_unclaim(conn: sqlite3.Connection, expiry_id: int, due: date) -> None:
    conn.execute("DELETE FROM nudges_renewal_posts WHERE expiry_id = ? AND due = ?", (expiry_id, due.isoformat()))


def db_post_of(conn: sqlite3.Connection, message_id: int) -> tuple[int, str] | None:
    row = conn.execute("SELECT expiry_id, due FROM nudges_renewal_posts WHERE message_id = ?", (message_id,)).fetchone()
    return (row[0], row[1]) if row else None


async def every(user_id: int) -> list[Expiry]:
    return await database.run(db_all, user_id)


def changed(user_id: int) -> None:
    from core import attention, summaries

    summaries.changed(TASK, user_id)
    attention.changed()


# --- finding one by its words -------------------------------------------------------------------------------------------
async def which(request: Request, words) -> Expiry:
    said = str(words or "").strip()
    found = await every(request.user.id)
    if not found:
        raise UserError(f"{RENEW_ICON} You have no expiries or renewals.")
    if not said:
        raise UserError(f"{RENEW_ICON} Which one?")
    try:
        return names.find(found, said, lambda each: each.name)
    except names.Unknown:
        raise UserError(f"{RENEW_ICON} Nothing like “{said}” is among your expiries.")
    except names.Ambiguous as many:
        raise UserError(f"{RENEW_ICON} “{said}” could be {' or '.join(f'**{each.name}**' for each in many.candidates[:4])}: say which.")


def _before_of(data: dict, was: tuple[int, ...] = BEFORE) -> tuple[int, ...]:
    said = [int(each) for each in data.get("before") or [] if str(each).lstrip("-").isdigit() and 0 <= int(each) <= 366]
    return tuple(sorted(set(said), reverse=True)) or was


# --- a new one: a card first ----------------------------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise UserError(f"{RENEW_ICON} What expires? Say it with its name, like “passport expires June 2031”.")
    if not data.get("date"):
        raise UserError(f"{RENEW_ICON} When does **{name}** expire?")
    today = days.today()
    due, month_only = read_date(str(data["date"]), today)
    months = recurrence.cycle_months(data.get("cycle"), data.get("every_months"))
    before = _before_of(data)
    name = name[:1].upper() + name[1:]
    warnings = []
    if month_only:
        warnings.append(f"Only the month was said: it is the 1st of {due:%B}")
    if due < today:
        warnings.append("That day has gone by")
    return Proposal(
        lines=(f"**{name}** · {due:%a} {due.day} {due:%b} {due.year}", f"{recurrence.cycle_text(months).capitalize()} · told {before_text(before)}", design.small("in your reminders")),
        data={"name": name, "due": due.isoformat(), "cycle_months": months, "before": list(before)}, warnings=tuple(warnings), kind="new",
    )


async def add_save(request: Request, data: dict) -> str:
    due = date.fromisoformat(data["due"])
    made = Expiry(0, request.user.id, data["name"], due, due.day, data.get("cycle_months"), tuple(data.get("before") or BEFORE))
    await database.run(db_add, made, clock.now())
    changed(request.user.id)
    return f"{RENEW_ICON} Saved · **{made.name}** · {short(due, days.today())} · {recurrence.cycle_text(made.cycle_months)}"


async def add_check(request: Request, data: dict) -> str:
    there = [each for each in await every(request.user.id) if each.name == data["name"] and each.due.isoformat() == data["due"]]
    return "" if there else "it is not among your expiries"


# --- a change: when to be told, the day or the cycle -----------------------------------------------------------------------
async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "remind me 60 days before the passport", "the rego is due 20 Nov now", "the domain is monthly"."""
    found = await which(request, data.get("expiry"))
    today = days.today()
    after = found
    if data.get("before"):
        after = replace(after, before=_before_of(data, found.before))
    if data.get("date"):
        due, _ = read_date(str(data["date"]), today)
        after = replace(after, due=due, anchor=due.day)
    if data.get("cycle"):
        after = replace(after, cycle_months=recurrence.cycle_months(data.get("cycle"), data.get("every_months")))
    if after == found:
        raise UserError(f"{RENEW_ICON} **{found.name}** is like that already.")
    lines = [f"**{found.name}**"]
    if after.due != found.due:
        lines.append(design.change(short(found.due, today), short(after.due, today)))
    if after.cycle_months != found.cycle_months:
        lines.append(design.change(recurrence.cycle_text(found.cycle_months), recurrence.cycle_text(after.cycle_months)))
    if after.before != found.before:
        lines.append(design.change(before_text(found.before), before_text(after.before)))
    return Proposal(lines=tuple(lines), data={"id": found.id, "due": after.due.isoformat(), "anchor": after.anchor, "cycle_months": after.cycle_months, "before": list(after.before)}, kind="change")


async def change_save(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    after = replace(found, due=date.fromisoformat(data["due"]), anchor=int(data["anchor"]), cycle_months=data.get("cycle_months"), before=tuple(data["before"]))
    await database.run(db_set, after)
    changed(request.user.id)
    return f"{RENEW_ICON} Changed · **{after.name}** · {short(after.due, days.today())} · told {before_text(after.before)}"


async def change_check(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    return "" if found is not None and found.due.isoformat() == data["due"] and list(found.before) == list(data["before"]) else "the change is not there"


# --- renewed ----------------------------------------------------------------------------------------------------------------
def _undo_row(renewal_id: int) -> tuple[Button, ...]:
    return (Button("Undo", TASK, UNDO, str(renewal_id), emoji="↩️", style=cards.PRIMARY),)


def renewed_line(before: Expiry, after: Expiry, today: date) -> str:
    if not after.open:
        return f"✅ **{before.name}** · renewed: done, off the list"
    return f"✅ **{before.name}** · renewed: next {short(after.due, today)} {after.due.year}"


async def renew(user_id: int, expiry: Expiry) -> tuple[str, int]:
    after = rolled(expiry)
    renewal_id = await database.run(db_renewed, expiry, after, clock.now())
    await _done_post(expiry)
    changed(user_id)
    return renewed_line(expiry, after, days.today()), renewal_id


async def renewed_said(request: Request, data: dict, guessed: frozenset) -> Shown:
    """ "renewed the Kiwa domain": one cycle on, the new date said, with Undo. A log: no card."""
    found = await which(request, data.get("expiry"))
    line, renewal_id = await renew(request.user.id, found)
    message_id = await cards.send(request.channel_id, Card(line, (_undo_row(renewal_id),)))
    return Shown(line if message_id is not None else "not shown")


async def undo_said(request: Request, data: dict, guessed: frozenset) -> str:
    renewal_id = await database.run(db_last_renewal, request.user.id)
    back = await database.run(db_undo, renewal_id) if renewal_id else None
    if back is None:
        raise UserError(f"{RENEW_ICON} There is no renewal to undo.")
    changed(request.user.id)
    return f"↩️ **{back.name}** · back to {short(back.due, days.today())}"


async def on_undo(press: cards.Press) -> str:
    back = await press.db.run(db_undo, int(press.arg)) if press.arg.isdigit() else None
    line = f"↩️ **{back.name}** · back to {short(back.due, days.today())}" if back else "↩️ Nothing to undo"
    if back is not None:
        changed(press.user.id)
    await press.update(Card(line))
    return line


# --- what's expiring soon ----------------------------------------------------------------------------------------------------
def soon(found: list[Expiry], today: date) -> list[Expiry]:
    return sorted((each for each in found if each.open and days_left(each, today) <= SOON_DAYS), key=lambda each: (each.due, each.name))


def soon_text(found: list[Expiry], today: date) -> str:
    if not found:
        return f"{RENEW_ICON} Nothing expires in the next {SOON_DAYS} days."
    return "\n".join([f"## {RENEW_ICON} Expiring soon · {len(found)}", *(f"**{each.name}** · {short(each.due, today)} · {in_words(days_left(each, today))}" for each in found)])


def soon_layout(found: list[Expiry], today: date) -> tuple:
    """Round 5: one box, soonest first, the edge the most urgent (gone by red, this week amber)."""
    entries = []
    for each in found:
        left = days_left(each, today)
        status = design.MISSED if left < 0 else design.DUE if left <= 7 else design.QUIET
        entries.append(design.Entry(f"{design.name(each.name)}\n{design.time(short(each.due, today))} · {in_words(left)} · {recurrence.cycle_text(each.cycle_months)}", status))
    box = design.topic(design.card_title(f"{RENEW_ICON} Expiring soon"), entries, status=design.QUIET)
    return design.fit((box,))


async def soon_said(request: Request, data: dict, guessed: frozenset) -> Shown:
    today = days.today()
    found = soon(await every(request.user.id), today)
    text = soon_text(found, today)
    message_id = await cards.send(request.channel_id, Card(text, (), soon_layout(found, today)) if found else Card(text))
    return Shown(text if message_id is not None else "not shown")


# --- the briefing, Needs a look ---------------------------------------------------------------------------------------------
def overview(found: list[Expiry], today: date) -> str:
    """The quiet line in the briefing's overview: each one between its first nudge and the day before."""
    quiet = [each for each in found if is_quiet(each, today)]
    return " · ".join(f"{RENEW_ICON} {each.name} {in_words(days_left(each, today))}" for each in quiet)


def expired_items(found: list[Expiry], today: date) -> list[Item]:
    """Gone by and not renewed: one line each in Needs a look, never a ping, never the name on the status line."""
    return [
        Item(f"{each.name} · expired {short(each.due, today)}", PROBLEM, short=("renewal overdue",), ping=False, once=f"expiry:{each.id}:{each.due.isoformat()}")
        for each in found if is_expired(each, today)
    ]


# --- the 1-day nudge: posted like a reminder ----------------------------------------------------------------------------------
def post_row(expiry_id: int) -> tuple[Button, ...]:
    return (
        Button("Done", TASK, RENEWED, str(expiry_id), emoji="✅", style=cards.SUCCESS),
        Button("Snooze", TASK, R_SNOOZE, str(expiry_id), emoji="💤", style=cards.PRIMARY),
    )


def snooze_row(expiry_id: int) -> tuple[Button, ...]:
    return (*(Button(label, TASK, R_SNOOZE_FOR, f"{expiry_id}:{minutes}", style=cards.PRIMARY) for label, minutes in SNOOZES), cards.cancel(TASK, R_BACK, str(expiry_id)))


def post_card(expiry: Expiry, today: date, row: tuple) -> Card:
    left = days_left(expiry, today)
    text = "\n".join([neutral(expiry.due, today), f"**{expiry.name}** · {in_words(left)}"])
    box = design.Box(design.DUE, (design.Text("\n".join([design.card_title(f"{RENEW_ICON} {expiry.name}"), f"due {design.time(short(expiry.due, today))} · {in_words(left)}", design.small("Done when it is renewed")])), design.Row(tuple(row))))
    return Card(text, (row,), design.fit(design.notifying(neutral(expiry.due, today), box)))


async def post_nudge(expiry: Expiry, again: bool = False) -> str:
    """Post the 1-day nudge in the hub, once a due day (a snooze posts it again)."""
    today = days.today()
    if not again and not await database.run(db_claim_post, expiry.id, expiry.due):
        return "posted already"
    channel_id = hub.channel_id()
    item = Item("a renewal is due", TIMED, when=clock.now(), can_act=True, short=("renewal due",))
    message_id = await notify.post(KIND, channel_id, Card(neutral(expiry.due, today)), user_id=expiry.user_id, item=item, key=f"renewal{expiry.id}@{expiry.due.isoformat()}") if channel_id else None
    if message_id is None:
        if not again:
            await database.run(db_unclaim, expiry.id, expiry.due)
        return "not posted: the hub can't be found"
    await database.run(db_posted, expiry.id, expiry.due, channel_id, message_id)
    await cards.edit(channel_id, message_id, post_card(expiry, today, post_row(expiry.id)))
    await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=expiry.user_id)
    return "posted"


async def _done_post(expiry: Expiry) -> None:
    """Renewed: its nudge, if one is up, leaves the hub."""
    def read(conn):
        row = conn.execute("SELECT channel_id, message_id FROM nudges_renewal_posts WHERE expiry_id = ? AND due = ? AND done = 0", (expiry.id, expiry.due.isoformat())).fetchone()
        conn.execute("UPDATE nudges_renewal_posts SET done = 1 WHERE expiry_id = ? AND due = ?", (expiry.id, expiry.due.isoformat()))
        return row

    found = await database.run(read)
    if found and found[0] and found[1]:
        await cards.delete(found[0], found[1])


async def check_job(job) -> None:
    """Scheduler handler, each morning: every renewal at its last nudge is posted, once a due day."""
    said = []
    for each in await database.run(db_every_user):
        if is_posting(each, days.today()):
            said.append(await post_nudge(each))
    posted = said.count("posted")
    scheduler.note(job, f"{posted} renewal nudge{'' if posted == 1 else 's'} posted" if posted else "nothing due tomorrow")


async def again_job(job) -> None:
    """Scheduler handler: a snoozed renewal nudge, posted again (if it is still not renewed)."""
    found = await database.run(db_get, int(job.payload.get("id", 0)))
    if found is None or not found.open or found.due.isoformat() != job.payload.get("due"):
        scheduler.note(job, "not posted: renewed or changed since")
        return
    scheduler.note(job, await post_nudge(found, again=True))


async def _pressed(press: cards.Press) -> Expiry | None:
    number = press.arg.split(":")[0]
    return await press.db.run(db_get, int(number)) if number.isdigit() else None


async def on_renewed(press: cards.Press) -> str:
    found = await _pressed(press)
    if found is None or not found.open:
        await press.remove()
        return "already dealt with"
    line, renewal_id = await renew(press.user.id, found)
    channel_id = hub.channel_id()
    if channel_id is not None:
        await cards.send(channel_id, Card(line, (_undo_row(renewal_id),)))
    return line


async def on_snooze(press: cards.Press) -> str:
    found = await _pressed(press)
    if found is None or not found.open:
        await press.remove()
        return "already dealt with"
    await press.update(post_card(found, days.today(), snooze_row(found.id)))
    return "asked how long"


async def on_back(press: cards.Press) -> str:
    found = await _pressed(press)
    if found is None:
        return "gone"
    await press.update(post_card(found, days.today(), post_row(found.id)))
    return "back"


async def on_snooze_for(press: cards.Press) -> str:
    from tasks.nudges import plain

    found = await _pressed(press)
    if found is None or not found.open:
        await press.remove()
        return "already dealt with"
    minutes = int(press.arg.split(":")[1])
    until = plain.snoozed_until(minutes, days.at(days.today(), CHECK_AT), clock.now())
    await scheduler.add_job(TASK, AGAIN_JOB, until, {"id": found.id, "due": found.due.isoformat()}, user_id=found.user_id, key=f"r{found.id}@{found.due.isoformat()}~{until:%Y%m%d%H%M}")
    await press.remove()
    return f"💤 again at {timeinput.format_moment(until)}"


def register() -> None:
    cards.register(TASK, RENEWED, on_renewed)
    cards.register(TASK, UNDO, on_undo)
    cards.register(TASK, R_SNOOZE, on_snooze)
    cards.register(TASK, R_SNOOZE_FOR, on_snooze_for)
    cards.register(TASK, R_BACK, on_back)


# --- what extraction is told and offered -------------------------------------------------------------------------------------
_WHICH = Field("expiry", "The words naming it, exactly as the user said them (\"the Kiwa domain\" -> Kiwa domain). Never complete or correct them.", required=True)
_CYCLE = Field("cycle", "yearly, monthly, months (every N months: fill every_months), or none (once: \"passport expires June 2031\"). Leave out when not said.", choices=recurrence.CYCLES)
_EVERY = Field("every_months", "For months: N, as in every N months (\"every 6 months\" -> 6).", INTEGER)
_BEFORE = Field("before", "How many days before to be told, only when the user says (\"remind me 60 days before\" -> [60]; \"a week and a day before\" -> [7, 1]).", LIST)
_DATE = Field("date", "The day it expires or is due, exactly as the user said it (\"3 March\", \"14 Nov\", \"June 2031\"). Never work out a date.")


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    return [
        Action(
            "expiry_add",
            "Something that expires or must be renewed on a day: a domain, a passport, a car's registration, a licence, a "
            "subscription (\"Kiwa domain expires 3 March, yearly\" -> name Kiwa domain, date 3 March, cycle yearly; \"passport "
            "expires June 2031\" -> cycle none; \"rego due 14 Nov, every year\" -> name rego, cycle yearly). A thing to do at a "
            "time is a reminder; an appointment is the calendar.",
            (Field("name", "What expires, in the user's words (\"Kiwa domain\", \"passport\", \"rego\").", required=True), _DATE, _CYCLE, _EVERY, _BEFORE),
            prepare=add_card, apply=add_save, verify=add_check, purpose=SET_UP, say=("Kiwa domain expires 3 March, yearly",),
        ),
        Action(
            "expiry_change",
            "Change an expiry: the days before to be told (\"remind me 60 days before the passport\" -> expiry passport, before [60]), "
            "its day or its cycle.",
            (_WHICH, replace(_DATE, required=False), _CYCLE, _EVERY, _BEFORE),
            prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("remind me 60 days before the passport",),
        ),
        Action(
            "expiry_renewed",
            "An expiry was renewed (\"renewed the Kiwa domain\", \"I've paid the rego\"): it rolls on a cycle. A log: no card.",
            (_WHICH,), needs_card=False, run=renewed_said, purpose=EACH_DAY, say=("renewed the Kiwa domain",),
        ),
        Action(
            "expiry_soon",
            "What expires or is due for renewal soon (\"what's expiring soon?\", \"any renewals coming up?\").",
            (), needs_card=False, run=soon_said, purpose=SEE, say=("what's expiring soon?",),
        ),
        Action(
            "expiry_undo",
            "Undo the last renewal (\"undo that\" straight after it).",
            (), needs_card=False, run=undo_said, purpose=EACH_DAY, say=("undo that",),
        ),
    ]
