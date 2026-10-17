import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from core import cards, clock, config, database, design, hub, notify, planning, repeats, scheduler, timeinput, timetable
from core import day as days
from core.actions import INTEGER, ITEMS, LIST, TIME, Field, Proposal, Request
from core.attention import TIMED, Item
from core.cards import Card
from core.errors import UserError
from tasks.base import Task

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The bedtime nudge, behind BEDTIME_ENABLED: off until Alex sets a usual
# bedtime in words ("bedtime 11pm; midnight on Fridays and Saturdays"); then
# its two schedule rows (Wind down, Bedtime) are his like any other ("my
# schedule" shows and moves them).
#
#   wind down (30 minutes before, changeable)   one message: the bedtime, a small
#        line of what is still open tonight (diary not yet, a dose still due, a
#        reminder still to come) and tomorrow's first thing; an earlier bedtime
#        suggested when tomorrow starts early (8 hours, 45 minutes to get going,
#        never more than an hour earlier); the diary's ask folded in when the two
#        are within 30 minutes
#   bedtime                                     one gentle line, once
#   "goodnight", "heading to bed"               quiet for the night: the bot's own
#        nudges are skipped (pill reminders keep their own rules); one short line
#
# Both get through quiet hours (Alex set them), never ntfy; what a phone shows
# is "🌙 Wind down" or "🌙 Bedtime". Nothing about sleep is recorded: no streak,
# no follow-up.
# ---------------------------------------------------------------------------
TASK = "bedtime"
ICON = "🌙"
WIND, BED = "wind_down", "bed_line"
KIND = "bedtime.nudge"
WIND_DOWN = 30  # minutes before, by default
SLEEP = timedelta(hours=8)
GET_GOING = timedelta(minutes=45)
MOST_EARLIER = timedelta(hours=1)
FOLD = timedelta(minutes=30)  # the diary's ask within this of the wind-down is folded into it
NIGHT_ENDS = time(4, 0)  # a bedtime before this belongs to the evening before

ONLY_FOR = (
    "The user's usual bedtime and the evening's wind-down nudge: setting it (\"bedtime 11pm; midnight on Fridays and "
    "Saturdays\", \"wind down 45 minutes before\") and saying they are going to bed (\"goodnight\", \"heading to bed\", "
    "\"going to sleep\"). Not a reminder at a time (the reminders task) and not the diary."
)
EXAMPLES = ("bedtime 11pm; midnight on Fridays and Saturdays", "goodnight")


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bedtime_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            times TEXT NOT NULL,
            wind_down INTEGER NOT NULL DEFAULT 30,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE bedtime_quiet (user_id INTEGER NOT NULL REFERENCES users(id), night TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (user_id, night))")
    conn.execute("CREATE TABLE bedtime_sent (user_id INTEGER NOT NULL, night TEXT NOT NULL, kind TEXT NOT NULL, message_id INTEGER, PRIMARY KEY (user_id, night, kind))")


MIGRATIONS = [create_tables]


# --- pure ------------------------------------------------------------------------------------------------------------------
def night_of(moment: datetime) -> date:
    """The evening a moment belongs to: up to 4:00 am is still the night before."""
    local = days.local_time(moment)
    day = days.day_of(moment)
    return day - timedelta(days=1) if local < NIGHT_ENDS else day


def bedtime_on(times: dict[int, time], night: date) -> time | None:
    """The bedtime for an evening (its weekday's, Monday 0), or None."""
    return times.get(night.weekday())


def bed_moment(night: date, at: time) -> datetime:
    """When bed is, for an evening: a time before 4:00 am is the next morning's."""
    return days.at(night + timedelta(days=1) if at < NIGHT_ENDS else night, at)


def earlier(bed: datetime, first: datetime | None) -> datetime | None:
    """An earlier bedtime when tomorrow's first thing leaves under 8 hours (with 45 minutes to get going), never
    more than an hour earlier, on a quarter hour; None when the usual one is fine."""
    if first is None:
        return None
    up = first - GET_GOING
    if up - bed >= SLEEP:
        return None
    wanted = max(up - SLEEP, bed - MOST_EARLIER)
    wanted = wanted.replace(minute=(wanted.minute // 15) * 15, second=0, microsecond=0)
    return wanted if wanted < bed else None


def wind_down_text(bed: datetime, still_open: list[str], first: tuple[str, datetime] | None, suggested: datetime | None) -> list[str]:
    """The wind-down message's lines: the bedtime, what is still open, tomorrow's first thing, an earlier time."""
    lines = [f"{ICON} Wind down · bed at {timeinput.format_moment(bed)}"]
    if still_open:
        lines.append(design.small("still open tonight: " + " · ".join(still_open)))
    if first is not None:
        lines.append(design.small(f"tomorrow: {first[0]} {timeinput.format_moment(first[1])}"))
    if suggested is not None:
        lines.append(design.small(f"tomorrow starts early: bed at {timeinput.format_moment(suggested)} gives you 8 hours"))
    return lines


# --- the store -----------------------------------------------------------------------------------------------------------------
def db_settings(conn: sqlite3.Connection, user_id: int) -> tuple[dict[int, time], int] | None:
    row = conn.execute("SELECT times, wind_down FROM bedtime_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return {int(day): time.fromisoformat(at) for day, at in json.loads(row[0]).items()}, row[1]


def db_save(conn: sqlite3.Connection, user_id: int, times: dict[int, time], wind_down: int, now: datetime) -> None:
    stored = json.dumps({str(day): at.isoformat(timespec="minutes") for day, at in times.items()})
    conn.execute(
        "INSERT INTO bedtime_settings (user_id, times, wind_down, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET times = excluded.times, wind_down = excluded.wind_down, updated_at = excluded.updated_at",
        (user_id, stored, wind_down, now.isoformat()),
    )
    # Its schedule rows: the old ones removed, one a time and its days for each step
    for schedule in timetable.db_all(conn):
        if schedule.user_id == user_id and set(schedule.steps) & {scheduler.handler_name(TASK, WIND), scheduler.handler_name(TASK, BED)}:
            timetable.db_update(conn, schedule.id, now, state=timetable.REMOVED)
    groups: dict[time, list[int]] = {}
    for day, at in times.items():
        groups.setdefault(at, []).append(day)
    for at, weekdays in groups.items():
        bed = datetime.combine(date(2000, 1, 3), at)  # a Monday, only for the sum
        wind = bed - timedelta(minutes=wind_down)
        night_days = tuple(sorted(weekdays))
        bed_days = tuple(sorted((day + 1) % 7 for day in weekdays)) if at < NIGHT_ENDS else night_days
        wind_days = tuple(sorted((day + 1) % 7 for day in weekdays)) if wind.time() < NIGHT_ENDS else night_days
        timetable.db_add(conn, now, user_id=user_id, name="Wind down", at=wind.time(), steps=[scheduler.handler_name(TASK, WIND)], days=wind_days, notify=timetable.NOTIFY)
        timetable.db_add(conn, now, user_id=user_id, name="Bedtime", at=at, steps=[scheduler.handler_name(TASK, BED)], days=bed_days, notify=timetable.NOTIFY)


def db_quiet(conn: sqlite3.Connection, user_id: int, night: date) -> bool:
    return conn.execute("SELECT 1 FROM bedtime_quiet WHERE user_id = ? AND night = ?", (user_id, night.isoformat())).fetchone() is not None


def db_set_quiet(conn: sqlite3.Connection, user_id: int, night: date, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO bedtime_quiet (user_id, night, at) VALUES (?, ?, ?)", (user_id, night.isoformat(), now.isoformat()))


def db_claim(conn: sqlite3.Connection, user_id: int, night: date, kind: str) -> bool:
    return conn.execute("INSERT OR IGNORE INTO bedtime_sent (user_id, night, kind) VALUES (?, ?, ?)", (user_id, night.isoformat(), kind)).rowcount > 0


async def is_quiet(user_id: int, moment: datetime) -> bool:
    """Whether Alex said goodnight for this night: the bot's own nudges are skipped."""
    return await database.run(db_quiet, user_id, night_of(moment))


async def folds_diary(user_id: int, moment: datetime) -> bool:
    """Whether a wind-down comes within 30 minutes after this moment tonight (the diary's ask is folded into it)."""
    found = await database.run(db_settings, user_id) if config.BEDTIME_ENABLED else None
    if not found:
        return False
    times, wind_down = found
    at = bedtime_on(times, night_of(moment))
    if at is None:
        return False
    wind = bed_moment(night_of(moment), at) - timedelta(minutes=wind_down)
    return moment <= wind <= moment + FOLD


# --- what is open tonight, and tomorrow's first thing --------------------------------------------------------------------------
async def tonight(user_id: int, now: datetime) -> tuple[list[str], bool]:
    """What is still open tonight, in a few words each (no names), and whether the diary is still to write."""
    found = []
    diary_open = False
    if config.DIARY_ENABLED:
        from tasks.diary import plain as diary_plain, store as diary_store

        diary_open = await diary_store.entry(user_id, diary_plain.today()) is None
        if diary_open:
            found.append("📔 diary not yet")
    pieces = await planning.gather(user_id, days.day_of(now))
    doses = [each for each in pieces if each.task == "pills" and not each.done and each.at is not None]
    if doses:
        found.append(f"💊 {len(doses)} dose{'' if len(doses) == 1 else 's'} still due")
    reminders = [each for each in pieces if each.task == "nudges" and each.at is not None and each.at > now]
    if reminders:
        found.append(f"⏰ {len(reminders)} reminder{'' if len(reminders) == 1 else 's'} still to come")
    return found, diary_open


async def first_tomorrow(user_id: int, night: date) -> tuple[str, datetime] | None:
    """Tomorrow's first commitment: the first event (a planned gym session is one) or the first dose."""
    pieces = await planning.gather(user_id, night + timedelta(days=1))
    timed = sorted((each for each in pieces if each.task in ("calendar", "pills") and each.at is not None and not each.all_day), key=lambda each: each.at)
    if not timed:
        return None
    first = timed[0]
    what = f"{first.icon} {first.text}" if first.task == "calendar" else f"{first.icon} first dose"
    return what, first.at


# --- the two handlers ---------------------------------------------------------------------------------------------------------
async def _owner():
    from core.users import get_user_by_discord_id

    return await get_user_by_discord_id(int(config.OWNER_ID)) if config.OWNER_ID else None


async def wind_job(job) -> None:
    owner = await _owner()
    channel_id = hub.channel_id()
    if owner is None or channel_id is None:
        scheduler.note(job, "not sent: no owner or hub")
        return
    now = clock.now()
    night = night_of(now)
    found = await database.run(db_settings, owner.id)
    at = bedtime_on(found[0], night) if found else None
    if at is None:
        scheduler.note(job, "not sent: no bedtime tonight")
        return
    if await is_quiet(owner.id, now):
        scheduler.note(job, "not sent: goodnight was said")
        return
    if not await database.run(db_claim, owner.id, night, WIND):
        scheduler.note(job, "not sent: sent already tonight")
        return
    bed = bed_moment(night, at)
    still_open, diary_open = await tonight(owner.id, now)
    first = await first_tomorrow(owner.id, night)
    lines = wind_down_text(bed, still_open, first, earlier(bed, first[1] if first else None))
    rows = ()
    asked = False
    if diary_open and config.DIARY_ENABLED:
        from tasks.diary import plain as diary_plain, rules as diary_rules, store as diary_store

        ask = await database.run(diary_store.db_ask, owner.id, diary_plain.today())
        if ask is None and await database.run(diary_store.db_claim_ask, owner.id, diary_plain.today(), now):
            # The diary's ask in the same message: one, not two
            lines.append(diary_rules.ASK)
            rows = (diary_plain.ask_row(diary_plain.today()),)
            asked = True
    item = Item("wind down", TIMED, when=now, short=())
    message_id = await notify.post(KIND, channel_id, Card(f"{ICON} Wind down"), user_id=owner.id, item=item, key=f"wind{night.isoformat()}")
    if message_id is None:
        scheduler.note(job, "not sent: the hub can't be found")
        return
    await cards.edit(channel_id, message_id, Card("\n".join(lines), rows))
    if asked:
        from tasks.diary import plain as diary_plain, store as diary_store

        await database.run(diary_store.db_asked, owner.id, diary_plain.today(), channel_id, message_id)
        diary_plain.remember_ask(message_id, owner.id, diary_plain.today())
    from core import messages

    await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=owner.id)
    scheduler.note(job, "sent" + (", with the diary's ask" if asked else ""))


async def bed_job(job) -> None:
    owner = await _owner()
    channel_id = hub.channel_id()
    if owner is None or channel_id is None:
        scheduler.note(job, "not sent: no owner or hub")
        return
    now = clock.now()
    night = night_of(now)
    if await is_quiet(owner.id, now):
        scheduler.note(job, "not sent: goodnight was said")
        return
    if not await database.run(db_claim, owner.id, night, BED):
        scheduler.note(job, "not sent: sent already tonight")
        return
    item = Item("bedtime", TIMED, when=now, short=())
    message_id = await notify.post(KIND, channel_id, Card(f"{ICON} Bedtime"), user_id=owner.id, item=item, key=f"bed{night.isoformat()}")
    if message_id is not None:
        await cards.edit(channel_id, message_id, Card(f"{ICON} Bedtime · sleep well"))
        from core import messages

        await messages.record(message_id, channel_id, lifetime=messages.DAY, task=TASK, user_id=owner.id)
    scheduler.note(job, "sent" if message_id is not None else "not sent: the hub can't be found")


# --- plain words -----------------------------------------------------------------------------------------------------------------
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _read_times(items: list[dict], was: dict[int, time] | None) -> dict[int, time]:
    """Each said time on its days ("11pm"; "midnight on Fridays and Saturdays"): every day, then the named days."""
    times = dict(was or {})
    for item in sorted(items, key=lambda each: bool(each.get("days"))):
        try:
            at = timeinput.parse_time(str(item.get("time")))
        except timeinput.AmbiguousTime as which:
            at = which.options[-1] if which.options[-1].hour >= 18 or which.options[0].hour < NIGHT_ENDS.hour else which.options[0]
        except Exception:
            raise UserError(f"{ICON} “{item.get('time')}” is not a time I can read.")
        named = [WEEKDAYS.index(str(day).lower()[:3]) for day in item.get("days") or [] if str(day).lower()[:3] in WEEKDAYS]
        for day in named or range(7):
            times[day] = at
    return times


def _times_text(times: dict[int, time]) -> list[str]:
    groups: dict[time, list[int]] = {}
    for day, at in sorted(times.items()):
        groups.setdefault(at, []).append(day)
    if len(groups) == 1:
        (at, _), = groups.items()
        return [f"bed at **{timeinput.format_time(at)}** every night"]
    return [f"**{timeinput.format_time(at)}** · " + ", ".join(WEEKDAYS[day].capitalize() for day in found) for at, found in groups.items()]


async def set_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    found = await database.run(db_settings, request.user.id)
    was_times, was_wind = found if found else ({}, WIND_DOWN)
    items = list(data.get("bedtimes") or [])
    if not items and not data.get("wind_down") and not was_times:
        raise UserError(f"{ICON} What time is bed? Say it like “bedtime 11pm”.")
    times = _read_times(items, was_times) if items else was_times
    wind = int(data.get("wind_down") or was_wind)
    if not 5 <= wind <= 120:
        raise UserError(f"{ICON} Wind down how long before? 5 to 120 minutes.")
    lines = [*_times_text(times), design.small(f"a wind-down nudge {wind} minutes before; a gentle line at bedtime; “goodnight” makes it quiet for the night")]
    return Proposal(lines=tuple(lines), data={"times": {str(day): at.isoformat(timespec="minutes") for day, at in times.items()}, "wind_down": wind}, kind="change" if was_times else "new")


async def set_save(request: Request, data: dict) -> str:
    times = {int(day): time.fromisoformat(at) for day, at in data["times"].items()}
    await database.run(db_save, request.user.id, times, int(data["wind_down"]), clock.now())
    await scheduler.book()
    return f"{ICON} Saved · " + "; ".join(each.replace("**", "") for each in _times_text(times)) + f" · wind down {data['wind_down']} minutes before"


async def set_check(request: Request, data: dict) -> str:
    found = await database.run(db_settings, request.user.id)
    return "" if found and {str(day): at.isoformat(timespec="minutes") for day, at in found[0].items()} == data["times"] else "the bedtime is not there"


async def goodnight(request: Request, data: dict, guessed: frozenset) -> str:
    """ "goodnight": quiet for the night, one short line; nothing recorded about sleep."""
    await database.run(db_set_quiet, request.user.id, night_of(clock.now()), clock.now())
    return f"{ICON} Goodnight"


def actions() -> list:
    from core.actions import EACH_DAY, SET_UP, Action

    return [
        Action("bedtime_set", "Set the usual bedtime (\"bedtime 11pm; midnight on Fridays and Saturdays\" -> two items) or how long before to wind down (\"wind down 45 minutes before\" -> wind_down 45).",
               (Field("bedtimes", "Each bedtime said, with its days if named (none: every night).", ITEMS, item_fields=(Field("time", "The time.", TIME, required=True), Field("days", "The days named (\"Fridays\" -> fri).", LIST, choices=WEEKDAYS))),
                Field("wind_down", "Minutes before bed for the wind-down nudge, if said.", INTEGER)),
               prepare=set_card, apply=set_save, verify=set_check, purpose=SET_UP, say=("bedtime 11pm; midnight on Fridays and Saturdays",)),
        Action("bedtime_goodnight", "Going to bed now (\"goodnight\", \"heading to bed\", \"going to sleep\"). A log: no card.", (), needs_card=False, run=goodnight, purpose=EACH_DAY, say=("goodnight",)),
    ]


class BedtimeTask(Task):
    """The bedtime nudge: a wind-down message and a gentle line at bedtime, once set."""

    name = TASK
    title = "Bedtime"
    description = "Bedtime: set your usual bedtime in words; a wind-down nudge before it with what is still open and tomorrow's first thing; goodnight makes it quiet"
    icon = ICON
    only_for = ONLY_FOR
    examples = EXAMPLES
    identity = ()
    on_repeat = repeats.ALLOW_ANOTHER
    place = 95

    def switched_on(self) -> bool:
        return bool(config.BEDTIME_ENABLED)

    def actions(self) -> list:
        return actions()

    def migrations(self):
        return MIGRATIONS

    def job_handlers(self):
        return {WIND: wind_job, BED: bed_job}

    def job_labels(self):
        return {WIND: "wind down", BED: "bedtime"}


task = BedtimeTask()
