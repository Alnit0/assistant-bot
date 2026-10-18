import calendar
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from core import cards, clock, database, design, names, scheduler, timeinput, timetable
from core import day as days
from core.actions import INTEGER, Field, Proposal, Request, Shown, State
from core.cards import Card
from core.errors import UserError
from tasks.nudges.rules import TASK

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Birthdays, part of reminders, behind BIRTHDAYS_ENABLED (with NUDGES_ENABLED):
# "Mum's birthday 12 March", "Sam 3 June 1995" (with a year, the age they are
# turning is shown), "my birthday is 20 October" (Alex's own: "Your
# birthday"), "gift idea for Mum: a scarf". A card first, as every change to
# one of my things is.
#
# Alex, 19 Oct: "they only really need to be a calendar notification and
# somewhere else they need to be listed; a heads-up 14 days in advance, up
# until the birthday, but subtle." So the bot never posts or pings for one:
#
#   the day itself:  a yearly all-day event on the Bot calendar (its own
#                    notification is set there, docs/GOOGLE-SETUP.md), kept
#                    in step when one is changed or removed
#   14 days before:  a small grey box low in the briefing, 🎂 Upcoming
#                    birthdays, a line each counting down, soonest first
#   the list:        one pinned 🎂 Birthdays message in #calendar, edited in
#                    place on every change and once a day
#
# Nothing on the status line or a lock screen. 29 February is the 28th in a
# year without one. Birthdays are a task of their own to the router
# ("birthdays", private): a name or a gift note is never in a log, the trace
# or #bot-log, only a note in its place.
# ---------------------------------------------------------------------------
NAME = "birthdays"  # the entry the router knows; the buttons and jobs are the reminders task's
ICON = "🎂"
GIFT = "🎁"
HEADS_UP = 14  # days before: from then to the day, in the briefing's Upcoming birthdays box
SOON_DAYS = 90  # "upcoming birthdays"
BOX = "Upcoming birthdays"  # the briefing's box (its icon is the entry's)
LIST_TITLE = f"{ICON} Birthdays"  # the pinned list in #calendar
CHECK_JOB, AGAIN_JOB = "birthdays", "birthday_again"  # AGAIN_JOB: a snooze booked before 19 Oct, now a note
CHECK_AT = time(0, 2)
CHECK_DEFAULT = timetable.Default("Birthdays list", CHECK_AT, locked=True)
EVERY = 60.0  # seconds: the pinned list is edited at most once a minute
# The buttons of a post from before 19 Oct: a press takes it away
DONE, SNOOZE, SNOOZE_FOR, BACK = "bday_done", "bday_snooze", "bday_snooze_for", "bday_back"

ONLY_FOR = (
    "People's birthdays (the user's own too, \"my birthday is 20 October\") and gift ideas for them: adding one "
    "(\"Mum's birthday 12 March\", \"Sam 3 June 1995\"), a gift idea (\"gift idea for Mum: a scarf\"), when to be told "
    "(\"tell me 5 days before Mum's birthday\"), changing or removing one, when someone's birthday is (\"when is Mum's birthday?\") and the birthdays coming up (\"upcoming "
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
    heads_up: int = HEADS_UP
    calendar_ref: str | None = None
    mine: bool = False  # Alex's own: shown as "Your birthday", its name kept empty
    relation: str | None = None  # "brother", when said: shown "Tom (brother)"


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


def countdown(left: int) -> str:
    """ "today", "tomorrow", "10 days": the days to go, in the briefing's box and the list."""
    return "today" if left == 0 else "tomorrow" if left == 1 else f"{left} days"


def tidy(said: str) -> tuple[str, bool]:
    """The name extraction handed over, made a name, and whether it is the user's own (Alex, 19 Oct: "my birthday
    is 20 October" was saved as a person called My). Mechanical, after extraction: the spaces, a trailing 's, a
    leading "my", a capital; what is left of "my", "me", "myself" or "I" is the user's own. Extraction is told the
    same (`_WHO`): this is its safety net, never the way a message is understood."""
    words = " ".join(str(said or "").replace("’", "'").split())
    if words.lower().endswith("'s"):
        words = words[:-2]
    elif words.endswith("'"):
        words = words[:-1]
    words = words.strip()
    if words.lower().startswith("my "):
        words = words[3:].strip()
    if words.lower() in ("", "my", "me", "myself", "i", "mine"):
        return "", True
    return " ".join(each[:1].upper() + each[1:] for each in words.split()), False


def label(birthday: Birthday) -> str:
    """ "Your birthday", "Tom (brother)", "Mum": how one is named wherever it is shown."""
    if birthday.mine:
        return "Your birthday"
    return birthday.name + (f" ({birthday.relation})" if birthday.relation else "")


def whose(birthday: Birthday) -> str:
    """ "Your birthday", "Mum's birthday": the Bot calendar's event, the plan."""
    return "Your birthday" if birthday.mine else f"{possessive(birthday.name)} birthday"


def date_text(birthday: Birthday) -> str:
    """ "12 March", "3 June 1995", "29 February"."""
    return f"{birthday.day} {date(2000, birthday.month, 1):%B}" + (f" {birthday.year}" if birthday.year else "")


def told_text(birthday: Birthday) -> str:
    """ "in the briefing from 14 days before"."""
    return f"in the briefing from {birthday.heads_up} days before"


def coming(found: list[Birthday], today: date) -> list[Birthday]:
    """Those in their heads-up, from its first day to the day itself, soonest first."""
    return sorted((each for each in found if days_left(each, today) <= each.heads_up), key=lambda each: (days_left(each, today), label(each)))


def box_line(birthday: Birthday, today: date) -> str:
    """ "Sam · Thu 29 Oct · 10 days"; on the day "Sam · today"."""
    left = days_left(birthday, today)
    if left == 0:
        return f"{label(birthday)} · today"
    day = next_on(birthday, today)
    return f"{label(birthday)} · {day:%a} {day.day} {day:%b} · {countdown(left)}"


def list_line(birthday: Birthday, today: date) -> str:
    """ "**Sam** · Thu 29 Oct · 10 days · turns 31": the pinned list's line."""
    day = next_on(birthday, today)
    age = turning(birthday, today)
    return f"**{label(birthday)}** · {day:%a} {day.day} {day:%b} · {countdown(days_left(birthday, today))}" + (f" · turns {age}" if age else "")


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


MARK = "birthday"  # the value of the Bot calendar's marker (tasks/calendar/google.py HIDDEN) on a birthday's event


def event_body(birthday: Birthday, today: date) -> dict:
    """The yearly all-day event, marked as the bot's birthday so it is never shown as a calendar item."""
    from tasks.calendar import google

    first = next_on(birthday, today)
    return {
        "summary": f"{ICON} {whose(birthday)}",
        "start": {"date": first.isoformat()}, "end": {"date": (first + timedelta(days=1)).isoformat()},
        "recurrence": [rule(birthday)],
        "extendedProperties": {"private": {google.HIDDEN: MARK}},
    }


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def when_line(birthday: Birthday, today: date) -> str:
    """ "**Mum** · Thu 12 Mar · in 146 days · turns 60"."""
    day = next_on(birthday, today)
    age = turning(birthday, today)
    return f"**{label(birthday)}** · {day:%a} {day.day} {day:%b} · {in_words(days_left(birthday, today))}" + (f" · turns {age}" if age else "")


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


def add_mine_and_list(conn: sqlite3.Connection) -> None:
    """19 Oct: the user's own birthday (`mine`), a relation ("brother"), a Bot calendar event to bring up to
    date (`resync`: every one, so each gets the bot's marker), and the pinned list's message in #calendar. Each
    kept name is tidied as a new one is (`tidy`): one saved as "My" or "Mum's" is the user's own, or "Mum"."""
    conn.execute("ALTER TABLE nudges_birthdays ADD COLUMN mine INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE nudges_birthdays ADD COLUMN relation TEXT")
    conn.execute("ALTER TABLE nudges_birthdays ADD COLUMN resync INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE nudges_birthday_list (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        )
        """
    )
    for row_id, name in conn.execute("SELECT id, name FROM nudges_birthdays").fetchall():
        tidied, mine = tidy(name)
        if mine:
            conn.execute("UPDATE nudges_birthdays SET name = '', mine = 1, resync = 1 WHERE id = ?", (row_id,))
        elif tidied != name:
            conn.execute("UPDATE nudges_birthdays SET name = ?, resync = 1 WHERE id = ?", (tidied, row_id))
    conn.execute("UPDATE nudges_birthdays SET resync = 1 WHERE calendar_ref IS NOT NULL")  # the marker


_COLUMNS = "id, user_id, name, month, day, year, heads_up, calendar_ref, mine, relation"


def _birthday(row: tuple) -> Birthday:
    return Birthday(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], bool(row[8]), row[9])


def db_all(conn: sqlite3.Connection, user_id: int) -> list[Birthday]:
    return [_birthday(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE user_id = ? AND removed_at IS NULL ORDER BY month, day, id", (user_id,))]


def db_every_user(conn: sqlite3.Connection) -> list[Birthday]:
    return [_birthday(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE removed_at IS NULL ORDER BY id")]


def db_get(conn: sqlite3.Connection, birthday_id: int) -> Birthday | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE id = ? AND removed_at IS NULL", (birthday_id,)).fetchone()
    return _birthday(row) if row else None


def db_add(conn: sqlite3.Connection, birthday: Birthday, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO nudges_birthdays (user_id, name, month, day, year, heads_up, calendar_ref, mine, relation, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (birthday.user_id, birthday.name, birthday.month, birthday.day, birthday.year, birthday.heads_up, birthday.calendar_ref, int(birthday.mine), birthday.relation, now.isoformat()),
    )
    return cursor.lastrowid


def db_set(conn: sqlite3.Connection, birthday: Birthday) -> None:
    conn.execute(
        "UPDATE nudges_birthdays SET name = ?, month = ?, day = ?, year = ?, heads_up = ?, calendar_ref = ?, mine = ?, relation = ? WHERE id = ?",
        (birthday.name, birthday.month, birthday.day, birthday.year, birthday.heads_up, birthday.calendar_ref, int(birthday.mine), birthday.relation, birthday.id),
    )


def db_to_resync(conn: sqlite3.Connection) -> list[Birthday]:
    return [_birthday(row) for row in conn.execute(f"SELECT {_COLUMNS} FROM nudges_birthdays WHERE resync = 1 AND removed_at IS NULL ORDER BY id")]


def db_resynced(conn: sqlite3.Connection, birthday_id: int, calendar_ref: str | None) -> None:
    conn.execute("UPDATE nudges_birthdays SET resync = 0, calendar_ref = ? WHERE id = ?", (calendar_ref, birthday_id))


def db_list_where(conn: sqlite3.Connection, user_id: int) -> tuple[int, int] | None:
    row = conn.execute("SELECT channel_id, message_id FROM nudges_birthday_list WHERE user_id = ?", (user_id,)).fetchone()
    return (row[0], row[1]) if row else None


def db_list_put(conn: sqlite3.Connection, user_id: int, channel_id: int, message_id: int) -> None:
    conn.execute(
        "INSERT INTO nudges_birthday_list (user_id, channel_id, message_id) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET channel_id = excluded.channel_id, message_id = excluded.message_id",
        (user_id, channel_id, message_id),
    )


def db_list_users(conn: sqlite3.Connection) -> list[int]:
    found = conn.execute("SELECT DISTINCT user_id FROM nudges_birthdays WHERE removed_at IS NULL UNION SELECT user_id FROM nudges_birthday_list").fetchall()
    return sorted(row[0] for row in found)


def db_is_list(conn: sqlite3.Connection, message_id: int) -> bool:
    return conn.execute("SELECT 1 FROM nudges_birthday_list WHERE message_id = ?", (message_id,)).fetchone() is not None


def db_remove(conn: sqlite3.Connection, birthday_id: int, now: datetime) -> None:
    conn.execute("UPDATE nudges_birthdays SET removed_at = ? WHERE id = ?", (now.isoformat(), birthday_id))


def db_gifts(conn: sqlite3.Connection, birthday_id: int) -> list[Gift]:
    return [Gift(row[0], row[1], row[2]) for row in conn.execute("SELECT id, birthday_id, note FROM nudges_birthday_gifts WHERE birthday_id = ? AND removed_at IS NULL ORDER BY id", (birthday_id,))]


def db_add_gift(conn: sqlite3.Connection, user_id: int, birthday_id: int, note: str, now: datetime) -> int:
    cursor = conn.execute("INSERT INTO nudges_birthday_gifts (user_id, birthday_id, note, created_at) VALUES (?, ?, ?, ?)", (user_id, birthday_id, note, now.isoformat()))
    return cursor.lastrowid


def db_post_of(conn: sqlite3.Connection, message_id: int) -> tuple[int, str, int] | None:
    row = conn.execute("SELECT birthday_id, on_day, stage FROM nudges_birthday_posts WHERE message_id = ?", (message_id,)).fetchone()
    return (row[0], row[1], row[2]) if row else None


async def every(user_id: int) -> list[Birthday]:
    return await database.run(db_all, user_id)


def changed(user_id: int) -> None:
    """A birthday added, changed or removed (or a gift note): the briefing, and the pinned list soon, at most
    once a minute (the changes coalesced)."""
    from core import live, summaries

    summaries.changed(TASK, user_id)

    async def refresh() -> None:
        await redraw_list(user_id)

    live.schedule((NAME, user_id), refresh, every=EVERY)


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


async def resync() -> int:
    """The events of birthdays marked by the 19 Oct migration, brought up to date on the Bot calendar (renamed,
    and given the bot's marker), when it can be written to: until then they wait. How many were."""
    if writer() is None:
        return 0
    found = await database.run(db_to_resync)
    for each in found:
        try:
            ref = await _calendar_change(each) if each.calendar_ref else each.calendar_ref
        except Exception:
            log.warning("Birthdays: an event could not be brought up to date on the Bot calendar")
            continue
        await database.run(db_resynced, each.id, ref)
    return len(found)


def calendar_line(on_calendar: bool) -> str:
    return design.small(f"{ICON} and a yearly all-day event on the Bot calendar" if on_calendar else "in your reminders")


# --- finding one by its words --------------------------------------------------------------------------------------
async def which(request: Request, words) -> Birthday:
    said, mine = tidy(words)
    found = await every(request.user.id)
    if not found:
        raise UserError(f"{ICON} You have no birthdays.")
    if mine:
        own = next((each for each in found if each.mine), None)
        if own is None:
            raise UserError(f"{ICON} I don't have your birthday. Say it like “my birthday is 20 October”.")
        return own
    found = [each for each in found if not each.mine]
    if not found:
        raise UserError(f"{ICON} There is no birthday for “{said}”.")
    try:
        return names.find(found, said, lambda each: each.name)
    except names.Unknown:
        raise UserError(f"{ICON} There is no birthday for “{said}”.")
    except names.Ambiguous as many:
        raise UserError(f"{ICON} “{said}” could be {' or '.join(f'**{each.name}**' for each in many.candidates[:4])}: say which.")


def _same(found: list[Birthday], name: str, mine: bool = False) -> Birthday | None:
    if mine:
        return next((each for each in found if each.mine), None)
    return next((each for each in found if not each.mine and names.tidy(each.name) == names.tidy(name)), None)


def _relation(data: dict) -> str | None:
    said = " ".join(str(data.get("relation") or "").split()).lower()
    return said[:40] or None


# --- add, change, remove: cards ---------------------------------------------------------------------------------------
async def add_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    if not str(data.get("person") or "").strip():
        raise UserError(f"{ICON} Whose birthday? Say it with the name, like “Mum's birthday 12 March”.")
    name, mine = tidy(data.get("person"))
    relation = None if mine else _relation(data)
    made = Birthday(0, request.user.id, name, 1, 1, mine=mine, relation=relation)
    if not data.get("date"):
        raise UserError(f"{ICON} When is {'your birthday' if mine else whose(made)}?")
    month, day, year = read(str(data["date"]))
    made = replace(made, month=month, day=day, year=year)
    today = days.today()
    there = _same(await every(request.user.id), name, mine)
    on_calendar = writer() is not None
    if there is not None:
        if (there.month, there.day, there.year) == (month, day, year):
            raise UserError(f"{ICON} {when_line(there, today)} is there already.")
        return Proposal(
            lines=(f"**{label(there)}**", design.change(date_text(there), date_text(made)), calendar_line(on_calendar and bool(there.calendar_ref))),
            data={"id": there.id, "name": there.name, "mine": there.mine, "month": month, "day": day, "year": year}, kind="change",
        )
    warnings = ["29 February: on the 28th in a year without one"] if (month, day) == (2, 29) else []
    return Proposal(
        lines=(when_line(made, today), f"Shown {told_text(made)}", calendar_line(on_calendar)),
        data={"name": name, "mine": mine, "relation": relation, "month": month, "day": day, "year": year}, warnings=tuple(warnings), kind="new",
    )


def _said_name(data: dict) -> str:
    return "Your birthday" if data.get("mine") else data["name"]


async def add_save(request: Request, data: dict) -> str:
    if data.get("id"):
        return await _change_save(request, data)
    made = Birthday(0, request.user.id, data["name"], int(data["month"]), int(data["day"]), data.get("year"), mine=bool(data.get("mine")), relation=data.get("relation"))
    made = replace(made, calendar_ref=await _calendar_add(made))
    await database.run(db_add, made, clock.now())
    changed(request.user.id)
    return f"{ICON} Saved · {when_line(made, days.today())}" + (" · on the Bot calendar" if made.calendar_ref else "")


async def add_check(request: Request, data: dict) -> str:
    there = _same(await every(request.user.id), data["name"], bool(data.get("mine")))
    if there is None or (there.month, there.day) != (int(data["month"]), int(data["day"])):
        return "the birthday is not there"
    return ""


async def add_undo(request: Request, data: dict) -> str:
    there = _same(await every(request.user.id), data["name"], bool(data.get("mine")))
    if there is None or data.get("id"):
        return f"↩️ {ICON} **{_said_name(data)}** · was not there"
    await _calendar_remove(there)
    await database.run(db_remove, there.id, clock.now())
    changed(request.user.id)
    return f"↩️ {ICON} Taken off · **{label(there)}**"


async def change_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """ "tell me 5 days before Mum's birthday", "Mum's birthday is the 13th of March actually"."""
    found = await which(request, data.get("person"))
    after = found
    if data.get("date"):
        month, day, year = read(str(data["date"]))
        after = replace(after, month=month, day=day, year=year or found.year)
    if data.get("heads_up") and str(data["heads_up"]).isdigit():
        after = replace(after, heads_up=max(1, min(60, int(data["heads_up"]))))
    if after == found:
        raise UserError(f"{ICON} {whose(found)} is like that already.")
    lines = [f"**{label(found)}**"]
    if (after.month, after.day, after.year) != (found.month, found.day, found.year):
        lines.append(design.change(date_text(found), date_text(after)))
    if after.heads_up != found.heads_up:
        lines.append(design.change(told_text(found), told_text(after)))
    if found.calendar_ref and (after.month, after.day) != (found.month, found.day):
        lines.append(design.small("the Bot calendar's event moves with it"))
    return Proposal(
        lines=tuple(lines),
        data={"id": found.id, "name": found.name, "mine": found.mine, "month": after.month, "day": after.day, "year": after.year, "heads_up": after.heads_up},
        kind="change",
    )


async def _change_save(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    if found is None:
        raise UserError(f"{ICON} That birthday has gone.")
    after = replace(found, month=int(data["month"]), day=int(data["day"]), year=data.get("year"), heads_up=int(data.get("heads_up") or found.heads_up))
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
    return "" if "heads_up" not in data or found.heads_up == int(data["heads_up"]) else "the change is not there"


async def remove_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await which(request, data.get("person"))
    lines = (f"**{label(found)}** → removed", design.small(f"was {date_text(found)}" + (" · its Bot calendar event goes too" if found.calendar_ref else "")))
    return Proposal(lines=lines, data={"id": found.id, "name": found.name, "mine": found.mine}, kind="remove", confirm_label="Remove")


async def remove_save(request: Request, data: dict) -> str:
    found = await database.run(db_get, int(data["id"]))
    if found is not None:
        await _calendar_remove(found)
        await database.run(db_remove, found.id, clock.now())
    changed(request.user.id)
    return "🗑️ Removed your birthday" if data.get("mine") else f"🗑️ Removed **{data['name']}**'s birthday"


async def remove_check(request: Request, data: dict) -> str:
    return "the birthday is still there" if await database.run(db_get, int(data["id"])) is not None else ""


# --- gift notes ---------------------------------------------------------------------------------------------------------
async def gift_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await which(request, data.get("person"))
    note = " ".join(str(data.get("note") or "").split())
    if not note:
        raise UserError(f"{ICON} What is the gift idea for **{found.name}**?")
    kept = await database.run(db_gifts, found.id)
    lines = [f"**{label(found)}** · {GIFT} {note}"]
    if kept:
        lines.append(design.small("with " + ", ".join(each.note for each in kept)))
    return Proposal(lines=tuple(lines), data={"id": found.id, "name": found.name, "mine": found.mine, "note": note}, kind="new")


async def gift_save(request: Request, data: dict) -> str:
    await database.run(db_add_gift, request.user.id, int(data["id"]), data["note"], clock.now())
    changed(request.user.id)
    return f"{GIFT} Saved · gift idea for " + ("your birthday" if data.get("mine") else f"**{data['name']}**")


async def gift_check(request: Request, data: dict) -> str:
    return "" if any(each.note == data["note"] for each in await database.run(db_gifts, int(data["id"]))) else "the gift idea is not there"


async def gift_undo(request: Request, data: dict) -> str:
    def take_back(conn):
        row = conn.execute("SELECT id FROM nudges_birthday_gifts WHERE birthday_id = ? AND note = ? AND removed_at IS NULL ORDER BY id DESC LIMIT 1", (int(data["id"]), data["note"])).fetchone()
        if row is not None:
            conn.execute("UPDATE nudges_birthday_gifts SET removed_at = ? WHERE id = ?", (clock.now().isoformat(), row[0]))
        return row is not None

    gone = await database.run(take_back)
    if gone:
        changed(request.user.id)
    return f"↩️ {GIFT} Taken off · gift idea for " + ("your birthday" if data.get("mine") else f"**{data['name']}**") if gone else f"↩️ {GIFT} was not there"


# --- when, and what is coming up ------------------------------------------------------------------------------------------
async def _with_gifts(birthday: Birthday) -> list[str]:
    return [design.small(f"{GIFT} {each.note}") for each in await database.run(db_gifts, birthday.id)]


async def when_said(request: Request, data: dict, guessed: frozenset) -> str:
    """ "when is Mum's birthday?": answered where it was asked, with her gift notes."""
    found = await which(request, data.get("person"))
    return "\n".join([f"{ICON} {when_line(found, days.today())}", *await _with_gifts(found)])


def soon(found: list[Birthday], today: date) -> list[Birthday]:
    return sorted((each for each in found if days_left(each, today) <= SOON_DAYS), key=lambda each: (days_left(each, today), label(each)))


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


# --- the briefing, the week, the plan --------------------------------------------------------------------------------------
async def summary(user_id: int, day: date):
    """The briefing's 🎂 Upcoming birthdays box, only with one in its heads-up: low in the briefing, below the
    day's things, a grey edge, a small line each ("Sam · Thu 29 Oct · 10 days"), soonest first. Never a button,
    never red or amber, nothing for the status line."""
    from core.actions import Summary

    found = coming(await every(user_id), day)
    if not found:
        return None
    return Summary(status=design.QUIET, lines=tuple(design.small(box_line(each, day)) for each in found), heading=BOX, low=True)


async def week(user_id: int, monday: date, upto: date):
    """The weekly summary's line: the birthdays in the 14 days after it ("Sam Thu 29 Oct · Mum Sat 7 Nov")."""
    from core import weekly

    after = upto + timedelta(days=1)
    found = sorted((each for each in await every(user_id) if days_left(each, after) < HEADS_UP), key=lambda each: days_left(each, after))
    if not found:
        return None
    said = " · ".join(f"{label(each)} {next_on(each, after):%a} {next_on(each, after).day} {next_on(each, after):%b}" for each in found)
    return weekly.Week(said, small=f"in the next {HEADS_UP} days")


async def state(request: Request) -> State:
    today = days.today()
    return State("The user's birthdays now", tuple(f"{'the user (their own)' if each.mine else label(each)} ({date_text(each)}, {in_words(days_left(each, today))})" for each in await every(request.user.id)), "none")


# --- the pinned list in #calendar -------------------------------------------------------------------------------------------
async def list_card(user_id: int, today: date) -> Card:
    """🎂 Birthdays: everyone in order of who is next, the date, the days to go, the age turning when a year is
    known, and the gift notes small under each."""
    found = sorted(await every(user_id), key=lambda each: (days_left(each, today), label(each)))
    lines = []
    for each in found:
        lines.append(list_line(each, today))
        lines += [design.small(f"{GIFT} {gift.note}") for gift in await database.run(db_gifts, each.id)]
    if not lines:
        lines = [design.small("none yet · say “Mum's birthday 12 March”")]
    text = "\n".join([f"## {LIST_TITLE}", *lines])
    box = design.topic(design.card_title(LIST_TITLE), lines=lines, status=design.QUIET)
    return Card(text, (), design.fit((box,)))


async def redraw_list(user_id: int) -> str:
    """The pinned list up to date: edited in place, or posted silently and pinned if it has gone. Never a ping."""
    from core import config, pins

    channel_id = config.CALENDAR_CHANNEL_ID
    if channel_id is None:
        return "no #calendar set"
    card = await list_card(user_id, days.today())
    where = await database.run(db_list_where, user_id)
    if where is not None and where[0] == channel_id and await cards.edit(channel_id, where[1], card):
        return "list edited"
    if where is None and not await every(user_id):
        return "no birthdays to list"
    message_id = await cards.send(channel_id, card, silent=True)
    if message_id is None:
        return "#calendar can't be found"
    await database.run(db_list_put, user_id, channel_id, message_id)
    try:
        await pins.set_pinned(channel_id, message_id, True, "The birthdays list")
    except UserError as error:
        log.warning("Birthdays: the list could not be pinned: %s", error)
    return "list posted"


async def check_job(job) -> None:
    """Scheduler handler, just after midnight: the list's countdown moves on, and an event renamed since is
    brought up to date. Never a name in its note."""
    renamed = await resync()
    said = [await redraw_list(each) for each in await database.run(db_list_users)]
    scheduler.note(job, "; ".join([*(said or ["no birthdays to list"]), *([f"{renamed} calendar event{'' if renamed == 1 else 's'} renamed"] if renamed else [])]))


async def again_job(job) -> None:
    """Scheduler handler: a snooze booked before 19 Oct. Birthdays are no longer posted."""
    scheduler.note(job, "not posted: birthdays are no longer posted (the Bot calendar has the day)")


async def startup(user_id: int) -> None:
    """At a start, saying nothing: events renamed by the migration, and the list brought up to date."""
    await resync()
    await redraw_list(user_id)


async def on_old_post(press: cards.Press) -> str:
    """A button on a post from before 19 Oct: the post is taken away."""
    await press.remove()
    return "old birthday post taken away"


def register() -> None:
    for each in (DONE, SNOOZE, SNOOZE_FOR, BACK):
        cards.register(TASK, each, on_old_post)


# --- what extraction is told and offered -----------------------------------------------------------------------------------
_WHO = Field(
    "person",
    "Whose birthday: the name alone, without my or the 's (\"Mum's birthday\" -> Mum; \"my mum's birthday\" -> Mum; \"my "
    "brother Tom's birthday\" -> Tom). The user's own birthday (\"my birthday\", \"I was born on\", \"it's my birthday on\") "
    "-> me. Never complete or correct a name.",
    required=True,
)
_DATE = Field("date", "The day of the birthday, exactly as the user said it, with the year if one was said (\"12 March\", \"3 June 1995\"). Never work out a date.")


def actions() -> list:
    from core.actions import EACH_DAY, SEE, SET_UP, Action

    return [
        Action(
            "birthday_add",
            "Someone's birthday (\"Mum's birthday 12 March\" -> person Mum, date 12 March; \"Sam 3 June 1995\" -> person Sam, "
            "date 3 June 1995; \"my birthday is 20 October\" -> person me, date 20 October).",
            # Not required here: a required name is read as "it" when the message points ("it's my birthday on
            # 20 October", core/actions.py as_references), and a new birthday never points at one kept
            (replace(_WHO, required=False), replace(_DATE, required=True), Field("relation", "How the person is related to the user, only when said with a name (\"my brother Tom\" -> brother). Never for Mum or Dad said alone.")),
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
            "Change a birthday: its day, or how long before it is shown in the briefing (\"tell me 5 days before Mum's "
            "birthday\" -> heads_up 5; \"start telling me a month before\" -> heads_up 30).",
            (
                _WHO, _DATE,
                Field("heads_up", "Days before the birthday it starts showing in the briefing, only when said.", INTEGER),
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
