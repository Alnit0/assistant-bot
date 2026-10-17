import calendar
import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from core import cards, clock, database, design, hub, messages, names, notify, scheduler, timeinput, timetable
from core import day as days
from core.actions import INTEGER, LIST, Field, Proposal, Request, Shown, State
from core.attention import TIMED, Item
from core.cards import Button, Card
from core.errors import UserError
from tasks.nudges.rules import SNOOZES, TASK

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Birthdays, part of reminders, behind BIRTHDAYS_ENABLED (with NUDGES_ENABLED):
# "Mum's birthday 12 March", "Sam 3 June 1995" (with a year, the age they are
# turning is shown), "gift idea for Mum: a scarf". A card first, as every
# change to one of my things is.
#
#   14 days before:   one quiet line in the briefing's overview
#   3 days before:    posted like a reminder, with the gift notes, Done and Snooze
#   on the day:       posted like a reminder
#   (the days are changed in words: "tell me 5 days before Mum's birthday")
#
# Each is also a yearly all-day event on the Bot calendar when it can be
# written to (the card says so), kept in step when it is changed or removed.
# 29 February is the 28th in a year without one. Posts go through the notify
# service (`nudges.birthday`: Discord only, held by quiet hours, never ntfy),
# and what a phone shows names nobody ("🎂 Birthday in 3 days"). Birthdays are
# a task of their own to the router ("birthdays", private): a name or a gift
# note is never in a log, the trace or #bot-log, only a note in its place.
# ---------------------------------------------------------------------------
NAME = "birthdays"  # the entry the router knows; the buttons and jobs are the reminders task's
ICON = "🎂"
GIFT = "🎁"
KIND = "nudges.birthday"
HEADS_UP = 14  # days before: the quiet line in the briefing
BEFORE = (3, 0)  # days before: posted (the day itself is always one)
SOON_DAYS = 90  # "upcoming birthdays"
CHECK_JOB, AGAIN_JOB = "birthdays", "birthday_again"
CHECK_AT = time(9, 0)
CHECK_DEFAULT = timetable.Default("Birthdays check", CHECK_AT, locked=True)
DONE, SNOOZE, SNOOZE_FOR, BACK = "bday_done", "bday_snooze", "bday_snooze_for", "bday_back"

ONLY_FOR = (
    "People's birthdays and gift ideas for them: adding one (\"Mum's birthday 12 March\", \"Sam 3 June 1995\"), a gift "
    "idea (\"gift idea for Mum: a scarf\"), when to be told (\"tell me 5 days before Mum's birthday\"), changing or "
    "removing one, when someone's birthday is (\"when is Mum's birthday?\") and the birthdays coming up (\"upcoming "
    "birthdays\"). Not a reminder at a time (the reminders task) and not an event (the calendar task)."
)
EXAMPLES = ("Mum's birthday 12 March", "gift idea for Mum: a scarf", "when is Mum's birthday?")


@dataclass(frozen=True)
class Birthday:
    id: int
    user_id: int
    name: str
    month: int
    day: int
    year: int | None = None  # the year they were born, if said
    before: tuple[int, ...] = BEFORE
    heads_up: int = HEADS_UP
    calendar_ref: str | None = None


@dataclass(frozen=True)
class Gift:
    id: int
    birthday_id: int
    note: str


# --- pure ----------------------------------------------------------------------------------------------------------
def on(birthday: Birthday, year: int) -> date:
    """Its day in a year: 29 February is the 28th in a year without one."""
    if birthday.month == 2 and birthday.day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, birthday.month, birthday.day)


def next_on(birthday: Birthday, today: date) -> date:
    """The next one to come, today included."""
    this_year = on(birthday, today.year)
    return this_year if this_year >= today else on(birthday, today.year + 1)


def days_left(birthday: Birthday, today: date) -> int:
    return (next_on(birthday, today) - today).days


def turning(birthday: Birthday, today: date) -> int | None:
    """The age they are turning at the next one, with a year; None without."""
    return next_on(birthday, today).year - birthday.year if birthday.year else None


def in_words(left: int) -> str:
    return "today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days"


def neutral(left: int) -> str:
    """What a phone shows: never the name."""
    return f"{ICON} Birthday {in_words(left)}"


def date_text(birthday: Birthday) -> str:
    """ "12 March", "3 June 1995", "29 February"."""
    return f"{birthday.day} {date(2000, birthday.month, 1):%B}" + (f" {birthday.year}" if birthday.year else "")


def told_text(birthday: Birthday) -> str:
    """ "a line 14 days before; posted 3 days before and on the day"."""
    posted = [f"{each} day{'' if each == 1 else 's'} before" for each in sorted(birthday.before, reverse=True) if each > 0]
    return f"a line {birthday.heads_up} days before; posted " + " and ".join([*posted, "on the day"])


def stage(birthday: Birthday, today: date) -> int | None:
    """Which post is due today: the nearest of its days before that has been reached (one missed while the bot
    was off is posted late, once); None when none is."""
    left = days_left(birthday, today)
    reached = [each for each in (*birthday.before, 0) if each >= left]
    return min(reached) if reached else None


def is_quiet(birthday: Birthday, today: date) -> bool:
    """In the overview line: from the heads-up to the day before the first post."""
    left = days_left(birthday, today)
    return max((*birthday.before, 0)) < left <= birthday.heads_up


def read(said: str) -> tuple[int, int, int | None]:
    """A birthday as said ("12 March", "3 June 1995", "29 Feb", "March 12"): its month, day and year (None if no
    year was said). Read twice against years apart, so a year is only taken when it was said."""
    text = str(said or "").strip()
    try:
        first, second = timeinput.parse_date(text, date(2000, 1, 1)), timeinput.parse_date(text, date(2004, 1, 1))
        third = timeinput.parse_date(text, date(2004, 1, 20))  # another day of the month, in a leap year
    except Exception:
        raise UserError(f"{ICON} “{said}” is not a day I can read. Try `12 March` or `3 June 1995`.")
    if len({(each.month, each.day) for each in (first, second, third)}) > 1:
        raise UserError(f"{ICON} Say the day of the birthday itself, like `12 March`.")
    return first.month, first.day, first.year if first.year == second.year else None


def rule(birthday: Birthday) -> str:
    """The Bot calendar's repeat: every year; 29 February is the last day of February each year."""
    if birthday.month == 2 and birthday.day == 29:
        return "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"
    return "RRULE:FREQ=YEARLY"


def event_body(birthday: Birthday, today: date) -> dict:
    first = next_on(birthday, today)
    return {
        "summary": f"{ICON} {birthday.name}'s birthday",
        "start": {"date": first.isoformat()}, "end": {"date": (first + timedelta(days=1)).isoformat()},
        "recurrence": [rule(birthday)],
    }


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def when_line(birthday: Birthday, today: date) -> str:
    """ "**Mum** · Thu 12 Mar · in 146 days · turns 60"."""
    day = next_on(birthday, today)
    age = turning(birthday, today)
    return f"**{birthday.name}** · {day:%a} {day.day} {day:%b} · {in_words(days_left(birthday, today))}" + (f" · turns {age}" if age else "")


# --- the store -----------------------------------------------------------------------------------------------------
def add_tables(conn: sqlite3.Connection) -> None:
    """Birthdays: the day (and the year, if said), when to be told, the Bot calendar's event; gift notes; and
    each post, once a birthday, a day before and a stage."""
    conn.execute(
        """
        CREATE TABLE nudges_birthdays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            month INTEGER NOT NULL,
            day INTEGER NOT NULL,
            year INTEGER,
            before TEXT NOT NULL DEFAULT '[3, 0]',
            heads_up INTEGER NOT NULL DEFAULT 14,
            calendar_ref TEXT,
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nudges_birthday_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            birthday_id INTEGER NOT NULL REFERENCES nudges_birthdays(id),
            note TEXT NOT NULL,
            removed_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE nudges_birthday_posts (
            birthday_id INTEGER NOT NULL REFERENCES nudges_birthdays(id),
            on_day TEXT NOT NULL,
            stage INTEGER NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            done INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (birthday_id, on_day, stage)
        )
        """
    )


_COLUMNS = "id, user_id, name, month, day, year, before, heads_up, calendar_ref"


def _birthday(row: tuple) -> Birthday:
    return Birthday(row[0], row[1], row[2], row[3], row[4], row[5], tuple(json.loads(row[6] or "[]")) or BEFORE, row[7], row[8])


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Birthday]:
    return [_birthday(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE user_id = ? AND removed_at IS NULL ORDER BY month, day, id", (user_id,))]


def db_every_user(conn: sqlite3.Connection) -> list[Birthday]:
    return [_birthday(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE removed_at IS NULL ORDER BY id")]


def db_get(conn: sqlite3.Connection, birthday_id: int) -> Birthday | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE id = ? AND removed_at IS NULL", (birthday_id,)).fetchone()
    return _birthday(row) if row else None


def db_add(conn: sqlite3.Connection, birthday: Birthday, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO nudges_birthdays (user_id, name, month, day, year, before, heads_up, calendar_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (birthday.user_id, birthday.name, birthday.month, birthday.day, birthday.year, json.dumps(list(birthday.before)), birthday.heads_up, birthday.calendar_ref, now.isoformat()),
    )
    return cursor.lastrowid


def db_set(conn: sqlite3.Connection, birthday: Birthday) -> None:
    conn.execute(
        "UPDATE nudges_birthdays SET name = ?, month = ?, day = ?, year = ?, before = ?, heads_up = ?, calendar_ref = ? WHERE id = ?",
        (birthday.name, birthday.month, birthday.day, birthday.year, json.dumps(list(birthday.before)), birthday.heads_up, birthday.calendar_ref, birthday.id),
    )


def db_remove(conn: sqlite3.Connection, birthday_id: int, now: datetime) -> None:
    conn.execute("UPDATE nudges_birthdays SET removed_at = ? WHERE id = ?", (now.isoformat(), birthday_id))


def db_gifts(conn: sqlite3.Connection, birthday_id: int) -> list[Gift]:
    return [Gift(row[0], row[1], row[2]) for row in conn.execute("SELECT id, birthday_id, note FROM nudges_birthday_gifts WHERE birthday_id = ? AND removed_at IS NULL ORDER BY id", (birthday_id,))]


def db_add_gift(conn: sqlite3.Connection, user_id: int, birthday_id: int, note: str, now: datetime) -> int:
    cursor = conn.execute("INSERT INTO nudges_birthday_gifts (user_id, birthday_id, note, created_at) VALUES (?, ?, ?, ?)", (user_id, birthday_id, note, now.isoformat()))
    return cursor.lastrowid


def db_claim_post(conn: sqlite3.Connection, birthday_id: int, on_day: date, at_stage: int) -> bool:
    cursor = conn.execute("INSERT OR IGNORE INTO nudges_birthday_posts (birthday_id, on_day, stage) VALUES (?, ?, ?)", (birthday_id, on_day.isoformat(), at_stage))
    return cursor.rowcount == 1


def db_unclaim(conn: sqlite3.Connection, birthday_id: int, on_day: date, at_stage: int) -> None:
    conn.execute("DELETE FROM nudges_birthday_posts WHERE birthday_id = ? AND on_day = ? AND stage = ? AND message_id IS NULL", (birthday_id, on_day.isoformat(), at_stage))


def db_posted(conn: sqlite3.Connection, birthday_id: int, on_day: date, at_stage: int, channel_id: int, message_id: int) -> None:
    conn.execute("UPDATE nudges_birthday_posts SET channel_id = ?, message_id = ? WHERE birthday_id = ? AND on_day = ? AND stage = ?", (channel_id, message_id, birthday_id, on_day.isoformat(), at_stage))


def db_post_of(conn: sqlite3.Connection, message_id: int) -> tuple[int, str, int] | None:
    row = conn.execute("SELECT birthday_id, on_day, stage FROM nudges_birthday_posts WHERE message_id = ?", (message_id,)).fetchone()
    return (row[0], row[1], row[2]) if row else None


def db_done(conn: sqlite3.Connection, birthday_id: int, on_day: str, at_stage: int) -> None:
    conn.execute("UPDATE nudges_birthday_posts SET done = 1 WHERE birthday_id = ? AND on_day = ? AND stage = ?", (birthday_id, on_day, at_stage))


async def every(user_id: int) -> list[Birthday]:
    return await database.run(db_all, user_id)


def changed(user_id: int) -> None:
    from core import attention, summaries

    summaries.changed(TASK, user_id)
    attention.changed()


# --- the Bot calendar ------------------------------------------------------------------------------------------------
def writer():
    """The Bot calendar, when it can be written to; None otherwise."""
    from tasks.calendar import plain as calendar_plain, source

    if not calendar_plain.writing():
        return None
    found = source.bot()
    return found if found is not None and found.can_write else None


async def _calendar_refresh(user_id: int) -> None:
    try:
        from tasks.calendar import plain as calendar_plain

        calendar_plain._changed(user_id)
    except Exception:
        log.warning("Birthdays: the calendar could not be told of a change")


async def _calendar_add(birthday: Birthday) -> str | None:
    bot = writer()
    if bot is None:
        return None
    made = await bot.insert(event_body(birthday, days.today()))
    await _calendar_refresh(birthday.user_id)
    return str(made.get("id") or "") or None


async def _calendar_change(birthday: Birthday) -> str | None:
    """Kept in step: the series patched (or made, if it has gone)."""
    bot = writer()
    if bot is None:
        return birthday.calendar_ref
    if birthday.calendar_ref and await bot.raw(birthday.calendar_ref) is not None:
        await bot.patch(birthday.calendar_ref, event_body(birthday, days.today()))
        await _calendar_refresh(birthday.user_id)
        return birthday.calendar_ref
    return await _calendar_add(birthday)


async def _calendar_remove(birthday: Birthday) -> None:
    bot = writer()
    if bot is None or not birthday.calendar_ref:
        return
    try:
        await bot.delete(birthday.calendar_ref)
    except Exception:
        log.warning("Birthdays: an event could not be taken off the Bot calendar")
    await _calendar_refresh(birthday.user_id)


def calendar_line(on_calendar: bool) -> str:
    return design.small(f"{ICON} and a yearly all-day event on the Bot calendar" if on_calendar else "in your reminders")


# --- finding one by its words --------------------------------------------------------------------------------------
async def which(request: Request, words) -> Birthday:
    said = str(words or "").strip()
    found = await every(request.user.id)
    if not found:
        raise UserError(f"{ICON} You have no birthdays.")
    if not said:
        raise UserError(f"{ICON} Whose birthday?")
    try:
        return names.find(found, said, lambda each: each.name)
    except names.Unknown:
        raise UserError(f"{ICON} There is no birthday for “{said}”.")
    except names.Ambiguous as many:
        raise UserError(f"{ICON} “{said}” could be {' or '.join(f'**{each.name}**' for each in many.candidates[:4])}: say which.")


def _same(found: list[Birthday], name: str) -> Birthday | None:
    return next((each for each in found if names.tidy(each.name) == names.tidy(name)), None)


def _before_of(data: dict, was: tuple[int, ...]) -> tuple[int, ...]:
    said = [int(each) for each in data.get("before") or [] if str(each).isdigit() and 0 < int(each) <= 60]
    return tuple(sorted(set(said), reverse=True)) + (0,) if said else was


# --- add, change, remove: cards ---------------------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    name = " ".join(str(data.get("person") or "").split())
    if not name:
        raise UserError(f"{ICON} Whose birthday? Say it with the name, like “Mum's birthday 12 March”.")
    if not data.get("date"):
        raise UserError(f"{ICON} When is **{name}**'s birthday?")
    month, day, year = read(str(data["date"]))
    name = name[:1].upper() + name[1:]
    today = days.today()
    made = Birthday(0, request.user.id, name, month, day, year)
    there = _same(await every(request.user.id), name)
    on_calendar = writer() is not None
    if there is not None:
        if (there.month, there.day, there.year) == (month, day, year):
            raise UserError(f"{ICON} {when_line(there, today)} is there already.")
        return Proposal(
            lines=(f"**{there.name}**", design.change(date_text(there), date_text(made)), calendar_line(on_calendar and bool(there.calendar_ref))),
            data={"id": there.id, "name": there.name, "month": month, "day": day, "year": year}, kind="change",
        )
    warnings = ["29 February: told on the 28th in a year without one"] if (month, day) == (2, 29) else []
    return Proposal(
        lines=(when_line(made, today), f"Told: {told_text(made)}", calendar_line(on_calendar)),
        data={"name": name, "month": month, "day": day, "year": year}, warnings=tuple(warnings), kind="new",
    )


async def add_save(request: Request, data: dict) -> str:
    if data.get("id"):
        return await _change_save(request, data)
    made = Birthday(0, request.user.id, data["name"], int(data["month"]), int(data["day"]), data.get("year"))
    made = replace(made, calendar_ref=await _calendar_add(made))
    await database.run(db_add, made, clock.now())
    changed(request.user.id)
    return f"{ICON} Saved · {when_line(made, days.today())}" + (" · on the Bot calendar" if made.calendar_ref else "")


async def add_check(request: Request, data: dict) -> str:
    there = _same(await every(request.user.id), data["name"])
    if there is None or (there.month, there.day) != (int(data["month"]), int(data["day"])):
        return "the birthday is not there"
    return ""


async def add_undo(request: Request, data: dict) -> str:
    there = _same(await every(request.user.id), data["name"])
    if there is None or data.get("id"):
        return f"↩️ {ICON} **{data['name']}** · was not there"
    await _calendar_remove(there)
    await database.run(db_remove, there.id, clock.now())
    changed(request.user.id)
    return f"↩️ {ICON} Taken off · **{there.name}**"


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "tell me 5 days before Mum's birthday", "Mum's birthday is the 13th of March actually"."""
    found = await which(request, data.get("person"))
    after = found
    if data.get("date"):
        month, day, year = read(str(data["date"]))
        after = replace(after, month=month, day=day, year=year or found.year)
    if data.get("before"):
        after = replace(after, before=_before_of(data, found.before))
    if data.get("heads_up") and str(data["heads_up"]).isdigit():
        after = replace(after, heads_up=max(1, min(60, int(data["heads_up"]))))
    if after == found:
        raise UserError(f"{ICON} **{found.name}**'s birthday is like that already.")
    lines = [f"**{found.name}**"]
    if (after.month, after.day, after.year) != (found.month, found.day, found.year):
        lines.append(design.change(date_text(found), date_text(after)))
    if (after.before, after.heads_up) != (found.before, found.heads_up):
        lines.append(design.change(told_text(found), told_text(after)))
    if found.calendar_ref and (after.month, after.day) != (found.month, found.day):
        lines.append(design.small("the Bot calendar's event moves with it"))
    return Proposal(
        lines=tuple(lines),
        data={"id": found.id, "name": found.name, "month": after.month, "day": after.day, "year": after.year, "before": list(after.before), "heads_up": after.heads_up},
        kind="change",
    )


async def _change_save(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    if found is None:
        raise UserError(f"{ICON} That birthday has gone.")
    after = replace(found, month=int(data["month"]), day=int(data["day"]), year=data.get("year"), before=tuple(data.get("before") or found.before), heads_up=int(data.get("heads_up") or found.heads_up))
    if (after.month, after.day) != (found.month, found.day):
        after = replace(after, calendar_ref=await _calendar_change(after))
    await database.run(db_set, after)
    changed(request.user.id)
    return f"{ICON} Changed · {when_line(after, days.today())}"


async def change_save(request: Request, data: dict) -> str:
    return await _change_save(request, data)


async def change_check(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    if found is None or (found.month, found.day) != (int(data["month"]), int(data["day"])):
        return "the change is not there"
    return "" if "before" not in data or list(found.before) == list(data["before"]) else "the change is not there"


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await which(request, data.get("person"))
    lines = (f"**{found.name}** → removed", design.small(f"was {date_text(found)}" + (" · its Bot calendar event goes too" if found.calendar_ref else "")))
    return Proposal(lines=lines, data={"id": found.id, "name": found.name}, kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    if found is not None:
        await _calendar_remove(found)
        await database.run(db_remove, found.id, clock.now())
    changed(request.user.id)
    return f"🗑️ Removed **{data['name']}**'s birthday"


async def remove_check(request: Request, data: dict) -> str:
    return "the birthday is still there" if await database.run(db_get, int(data["id"])) is not None else ""


# --- gift notes ---------------------------------------------------------------------------------------------------------
async def gift_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await which(request, data.get("person"))
    note = " ".join(str(data.get("note") or "").split())
    if not note:
        raise UserError(f"{ICON} What is the gift idea for **{found.name}**?")
    kept = await database.run(db_gifts, found.id)
    lines = [f"**{found.name}** · {GIFT} {note}"]
    if kept:
        lines.append(design.small("with " + ", ".join(each.note for each in kept)))
    return Proposal(lines=tuple(lines), data={"id": found.id, "name": found.name, "note": note}, kind="new")


async def gift_save(request: Request, data: dict) -> str:
    await database.run(db_add_gift, request.user.id, int(data["id"]), data["note"], clock.now())
    return f"{GIFT} Saved · gift idea for **{data['name']}**"


async def gift_check(request: Request, data: dict) -> str:
    return "" if any(each.note == data["note"] for each in await database.run(db_gifts, int(data["id"]))) else "the gift idea is not there"


async def gift_undo(request: Request, data: dict) -> str:
    def take_back(conn):
        row = conn.execute("SELECT id FROM nudges_birthday_gifts WHERE birthday_id = ? AND note = ? AND removed_at IS NULL ORDER BY id DESC LIMIT 1", (int(data["id"]), data["note"])).fetchone()
        if row is not None:
            conn.execute("UPDATE nudges_birthday_gifts SET removed_at = ? WHERE id = ?", (clock.now().isoformat(), row[0]))
        return row is not None

    gone = await database.run(take_back)
    return f"↩️ {GIFT} Taken off · gift idea for **{data['name']}**" if gone else f"↩️ {GIFT} was not there"


# --- when, and what is coming up ------------------------------------------------------------------------------------------
async def _with_gifts(birthday: Birthday) -> list[str]:
    return [design.small(f"{GIFT} {each.note}") for each in await database.run(db_gifts, birthday.id)]


async def when_said(request: Request, data: dict, guessed: frozenset) -> str:
    """ "when is Mum's birthday?": answered where it was asked, with her gift notes."""
    found = await which(request, data.get("person"))
    return "\n".join([f"{ICON} {when_line(found, days.today())}", *await _with_gifts(found)])


def soon(found: list[Birthday], today: date) -> list[Birthday]:
    return sorted((each for each in found if days_left(each, today) <= SOON_DAYS), key=lambda each: (days_left(each, today), each.name))


async def soon_said(request: Request, data: dict, guessed: frozenset) -> Shown:
    today = days.today()
    found = soon(await every(request.user.id), today)
    if not found:
        text = f"{ICON} No birthdays in the next {SOON_DAYS} days."
        message_id = await cards.send(request.channel_id, Card(text))
        return Shown(text if message_id is not None else "not shown")
    text = "\n".join([f"## {ICON} Birthdays coming up · {len(found)}", *(when_line(each, today) for each in found)])
    entries = [design.Entry(when_line(each, today), design.DUE if days_left(each, today) <= 3 else design.QUIET) for each in found]
    layout = design.fit((design.topic(design.card_title(f"{ICON} Birthdays coming up"), entries, status=design.QUIET),))
    message_id = await cards.send(request.channel_id, Card(text, (), layout))
    return Shown(text if message_id is not None else "not shown")


# --- the briefing, the plan ----------------------------------------------------------------------------------------------
def overview(found: list[Birthday], today: date) -> str:
    """The quiet line in the briefing's overview: each from its heads-up to the day before its first post."""
    return " · ".join(f"{ICON} {each.name} {in_words(days_left(each, today))}" for each in sorted(found, key=lambda each: days_left(each, today)) if is_quiet(each, today))


async def plan_pieces(user_id: int, day: date) -> list:
    """For a plan (core/planning.py): a birthday on that day, all day (not when the Bot calendar has it)."""
    from core import planning

    return [planning.Piece(NAME, f"b{each.id}", ICON, f"{possessive(each.name)} birthday", all_day=True) for each in await every(user_id) if next_on(each, day) == day and not each.calendar_ref]


async def state(request: Request) -> State:
    today = days.today()
    return State("The user's birthdays now", tuple(f"{each.name} ({date_text(each)}, {in_words(days_left(each, today))})" for each in await every(request.user.id)), "none")


# --- the posts: 3 days before (with the gift notes) and on the day ---------------------------------------------------------
def post_row(birthday_id: int, on_day: date, at_stage: int) -> tuple[Button, ...]:
    arg = f"{birthday_id}:{on_day.isoformat()}:{at_stage}"
    return (Button("Done", TASK, DONE, arg, emoji="✅", style=cards.SUCCESS), Button("Snooze", TASK, SNOOZE, arg, emoji="💤", style=cards.PRIMARY))


def snooze_row(birthday_id: int, on_day: date, at_stage: int) -> tuple[Button, ...]:
    arg = f"{birthday_id}:{on_day.isoformat()}:{at_stage}"
    return (*(Button(label, TASK, SNOOZE_FOR, f"{arg}:{minutes}", style=cards.PRIMARY) for label, minutes in SNOOZES), cards.cancel(TASK, BACK, arg))


def post_card(birthday: Birthday, gifts: list[Gift], today: date, row: tuple) -> Card:
    left = days_left(birthday, today)
    day = next_on(birthday, today)
    age = turning(birthday, today)
    said = f"{design.time(f'{day:%a} {day.day} {day:%b}')} · {in_words(left)}" + (f" · turns {age}" if age else "")
    notes = [f"{GIFT} {each.note}" for each in gifts] if left > 0 else []
    text = "\n".join([neutral(left), f"**{possessive(birthday.name)} birthday** · {in_words(left)}" + (f" · turns {age}" if age else ""), *notes])
    body = [design.card_title(f"{ICON} {possessive(birthday.name)} birthday"), said, *(design.small(each) for each in notes)]
    box = design.Box(design.DUE, (design.Text("\n".join(body)), design.Row(tuple(row))))
    return Card(text, (row,), design.fit(design.notifying(neutral(left), box)))


async def post(birthday: Birthday, at_stage: int, again: bool = False) -> str:
    """Post a birthday's reminder in the hub, once a birthday and stage (a snooze posts it again)."""
    today = days.today()
    on_day = next_on(birthday, today)
    if not again and not await database.run(db_claim_post, birthday.id, on_day, at_stage):
        return "posted already"
    channel_id = hub.channel_id()
    left = days_left(birthday, today)
    item = Item("a birthday is coming up", TIMED, when=clock.now(), can_act=True, short=("birthday",))
    message_id = await notify.post(KIND, channel_id, Card(neutral(left)), user_id=birthday.user_id, item=item, key=f"birthday{birthday.id}@{on_day.isoformat()}:{at_stage}", private=(birthday.name,)) if channel_id else None
    if message_id is None:
        if not again:
            await database.run(db_unclaim, birthday.id, on_day, at_stage)
        return "not posted: the hub can't be found"
    await database.run(db_posted, birthday.id, on_day, at_stage, channel_id, message_id)
    gifts = await database.run(db_gifts, birthday.id)
    await cards.edit(channel_id, message_id, post_card(birthday, gifts, today, post_row(birthday.id, on_day, at_stage)))
    await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=birthday.user_id)
    return "posted"


async def check_job(job) -> None:
    """Scheduler handler, each morning: each birthday whose post is due is posted, once a stage. Never a name in its note."""
    said = []
    today = days.today()
    for each in await database.run(db_every_user):
        at_stage = stage(each, today)
        if at_stage is not None:
            said.append(await post(each, at_stage))
    posted = said.count("posted")
    scheduler.note(job, f"{posted} birthday post{'' if posted == 1 else 's'}" if posted else "no birthday post today")


async def again_job(job) -> None:
    """Scheduler handler: a snoozed birthday post, posted again (if it is still that birthday)."""
    found = await database.run(db_get, int(job.payload.get("id", 0)))
    if found is None or next_on(found, days.today()).isoformat() != job.payload.get("on"):
        scheduler.note(job, "not posted: removed or changed since")
        return
    scheduler.note(job, await post(found, int(job.payload.get("stage", 0)), again=True))


def _arg(press: cards.Press) -> tuple[int, str, int]:
    parts = press.arg.split(":")
    return (int(parts[0]) if parts[0].isdigit() else 0), (parts[1] if len(parts) > 1 else ""), (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0)


async def on_done(press: cards.Press) -> str:
    birthday_id, on_day, at_stage = _arg(press)
    await press.db.run(db_done, birthday_id, on_day, at_stage)
    await press.remove()  # dealt with: it leaves the hub
    return "birthday post done"


async def on_snooze(press: cards.Press) -> str:
    birthday_id, on_day, at_stage = _arg(press)
    found = await press.db.run(db_get, birthday_id)
    if found is None:
        await press.remove()
        return "gone"
    await press.update(post_card(found, await press.db.run(db_gifts, found.id), days.today(), snooze_row(birthday_id, date.fromisoformat(on_day), at_stage)))
    return "asked how long"


async def on_back(press: cards.Press) -> str:
    birthday_id, on_day, at_stage = _arg(press)
    found = await press.db.run(db_get, birthday_id)
    if found is None:
        return "gone"
    await press.update(post_card(found, await press.db.run(db_gifts, found.id), days.today(), post_row(birthday_id, date.fromisoformat(on_day), at_stage)))
    return "back"


async def on_snooze_for(press: cards.Press) -> str:
    from tasks.nudges import plain

    birthday_id, on_day, at_stage = _arg(press)
    found = await press.db.run(db_get, birthday_id)
    if found is None:
        await press.remove()
        return "gone"
    minutes = int(press.arg.split(":")[3])
    until = plain.snoozed_until(minutes, days.at(days.today(), CHECK_AT), clock.now())
    await scheduler.add_job(TASK, AGAIN_JOB, until, {"id": found.id, "on": on_day, "stage": at_stage}, user_id=found.user_id, key=f"b{found.id}@{on_day}:{at_stage}~{until:%Y%m%d%H%M}")
    await press.db.run(db_done, birthday_id, on_day, at_stage)
    await press.remove()
    return f"💤 again at {timeinput.format_moment(until)}"


def register() -> None:
    cards.register(TASK, DONE, on_done)
    cards.register(TASK, SNOOZE, on_snooze)
    cards.register(TASK, SNOOZE_FOR, on_snooze_for)
    cards.register(TASK, BACK, on_back)


# --- what extraction is told and offered -----------------------------------------------------------------------------------
_WHO = Field("person", "Whose birthday, exactly as the user said it (\"Mum's birthday\" -> Mum). Never complete or correct it.", required=True)
_DATE = Field("date", "The day of the birthday, exactly as the user said it, with the year if one was said (\"12 March\", \"3 June 1995\"). Never work out a date.")


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    return [
        Action(
            "birthday_add",
            "Someone's birthday (\"Mum's birthday 12 March\" -> person Mum, date 12 March; \"Sam 3 June 1995\" -> person Sam, "
            "date 3 June 1995).",
            (_WHO, replace(_DATE, required=True)),
            prepare=add_card, apply=add_save, verify=add_check, undo=add_undo, purpose=SET_UP, say=("Mum's birthday 12 March",),
        ),
        Action(
            "birthday_gift",
            "A gift idea for someone with a birthday (\"gift idea for Mum: a scarf\" -> person Mum, note a scarf).",
            (_WHO, Field("note", "The gift idea, in the user's words.", required=True)),
            prepare=gift_card, apply=gift_save, verify=gift_check, undo=gift_undo, purpose=EACH_DAY, say=("gift idea for Mum: a scarf",),
        ),
        Action(
            "birthday_change",
            "Change a birthday: its day, or when to be told (\"tell me 5 days before Mum's birthday\" -> before [5]; \"start "
            "telling me a month before\" -> heads_up 30).",
            (
                _WHO, _DATE,
                Field("before", "Days before the birthday to be told with a post, only when the user says (\"5 days before\" -> [5]).", LIST),
                Field("heads_up", "Days before for the first quiet line in the briefing, only when said.", INTEGER),
            ),
            prepare=change_card, apply=change_save, verify=change_check, purpose=SET_UP, say=("tell me 5 days before Mum's birthday",),
        ),
        Action(
            "birthday_remove",
            "Remove someone's birthday (\"forget Sam's birthday\").",
            (_WHO,), prepare=remove_card, apply=remove_save, verify=remove_check, purpose=SET_UP, say=("remove Sam's birthday",),
        ),
        Action("birthday_when", "When someone's birthday is (\"when is Mum's birthday?\").", (_WHO,), needs_card=False, run=when_said, purpose=SEE, say=("when is Mum's birthday?",)),
        Action("birthday_soon", "The birthdays coming up (\"upcoming birthdays\", \"any birthdays soon?\").", (), needs_card=False, run=soon_said, purpose=SEE, say=("upcoming birthdays",)),
    ]
