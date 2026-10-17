import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core import cards, clock, config, database, design, timeinput
from core import day as days
from core.actions import NUMBER, TIME, Field, Proposal, Request, Shown
from core.cards import Button, Card
from core.errors import UserError

# ---------------------------------------------------------------------------
# The weight tracker, part of the gym, behind GYM_WEIGHT (with GYM_ENABLED): a
# private entry of its own to the router ("weight"), so a weight is never in a
# log, the trace or #bot-log, only a note in its place.
#
#   "82.4", "weighed 82.4 this morning"   kept at once, with its time, and Undo
#   the trend                             exponentially smoothed (each weigh-in
#                                         moves it a tenth of the way), so a day's
#                                         swing doesn't dominate; the week's change
#   "aim for 80"                          a target, on a card
#   the briefing                          one small line, only on a day with a weigh-in
#   the week's summary                    one line
#
# Never on the lock screen or the status line: no attention items, no alerts.
# ---------------------------------------------------------------------------
NAME = "weight"
ICON = "⚖️"
SMOOTHING = 0.1  # how far each weigh-in moves the trend
UNDO = "weight_undo"
MIN_KG, MAX_KG = 20.0, 400.0

ONLY_FOR = (
    "The user's body weight: a weigh-in (\"82.4\", \"weighed 82.4 this morning\", \"82.4kg\"), the trend (\"what's my "
    "weight trend?\"), and a target (\"aim for 80\"). A bare number on its own is a weigh-in only when the user is "
    "talking about their weight or nothing else fits. Not a weight lifted at the gym (the gym task)."
)
EXAMPLES = ("weighed 82.4 this morning", "what's my weight trend?", "aim for 80")


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE gym_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            at TEXT NOT NULL,
            kg REAL NOT NULL,
            removed_at TEXT
        )
        """
    )
    conn.execute("ALTER TABLE gym_state ADD COLUMN weight_target REAL")


@dataclass(frozen=True)
class WeighIn:
    id: int
    at: datetime
    kg: float


# --- pure --------------------------------------------------------------------------------------------------------------
def trend(found: list[WeighIn]) -> list[tuple[datetime, float]]:
    """The smoothed weight after each weigh-in, oldest first."""
    said, value = [], None
    for each in sorted(found, key=lambda one: one.at):
        value = each.kg if value is None else value + SMOOTHING * (each.kg - value)
        said.append((each.at, round(value, 2)))
    return said


def trend_on(found: list[WeighIn], moment: datetime) -> float | None:
    before = [value for at, value in trend(found) if at <= moment]
    return before[-1] if before else None


def week_change(found: list[WeighIn], now: datetime) -> float | None:
    """The trend now against a week ago (None without one then)."""
    current, before = trend_on(found, now), trend_on(found, now - timedelta(days=7))
    return round(current - before, 1) if current is not None and before is not None else None


def signed(value: float) -> str:
    return f"{'−' if value < 0 else '+'}{abs(value):g}"


def line(found: list[WeighIn], now: datetime, target: float | None = None) -> str:
    """ "⚖️ trend 82.1 · −0.4 this week · 2.1 to go"."""
    current = trend_on(found, now)
    if current is None:
        return ""
    said = [f"{ICON} trend {current:.1f}"]
    change = week_change(found, now)
    if change is not None:
        said.append(f"{signed(change)} this week")
    if target:
        said.append("at your target" if abs(current - target) < 0.1 else f"{abs(current - target):.1f} to go")
    return " · ".join(said)


# --- the store -----------------------------------------------------------------------------------------------------------
def db_all(conn: sqlite3.Connection, user_id: int) -> list[WeighIn]:
    return [WeighIn(row[0], datetime.fromisoformat(row[1]), row[2]) for row in conn.execute("SELECT id, at, kg FROM gym_weights WHERE user_id = ? AND removed_at IS NULL ORDER BY at", (user_id,))]


def db_add(conn: sqlite3.Connection, user_id: int, at: datetime, kg: float) -> int:
    return conn.execute("INSERT INTO gym_weights (user_id, at, kg) VALUES (?, ?, ?)", (user_id, at.isoformat(), kg)).lastrowid


def db_remove(conn: sqlite3.Connection, weigh_id: int, now: datetime) -> bool:
    return conn.execute("UPDATE gym_weights SET removed_at = ? WHERE id = ? AND removed_at IS NULL", (now.isoformat(), weigh_id)).rowcount > 0


def db_target(conn: sqlite3.Connection, user_id: int) -> float | None:
    row = conn.execute("SELECT weight_target FROM gym_state WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def db_set_target(conn: sqlite3.Connection, user_id: int, kg: float | None, now: datetime) -> None:
    conn.execute(
        "INSERT INTO gym_state (user_id, weight_target, updated_at) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET weight_target = excluded.weight_target, updated_at = excluded.updated_at",
        (user_id, kg, now.isoformat()),
    )


async def every(user_id: int) -> list[WeighIn]:
    return await database.run(db_all, user_id)


# --- plain words -----------------------------------------------------------------------------------------------------------
def _kg(said) -> float:
    try:
        value = float(str(said).replace(",", "."))
    except (TypeError, ValueError):
        raise UserError(f"{ICON} What did you weigh, in kg?")
    if not MIN_KG <= value <= MAX_KG:
        raise UserError(f"{ICON} {value:g} kg doesn't look like a weight: say it again?")
    return round(value, 2)


async def log(request: Request, data: dict, guessed: frozenset) -> Shown:
    """ "weighed 82.4 this morning": kept at once, at the time said (or now), with Undo. A log: no card."""
    kg = _kg(data.get("kg"))
    now = clock.now()
    at = now
    if data.get("time"):
        try:
            moment = days.at(days.today(), timeinput.parse_time(str(data["time"])))
            at = moment if moment <= now else at
        except Exception:
            pass
    weigh_id = await database.run(db_add, request.user.id, at, kg)
    found = await every(request.user.id)
    said = f"{ICON} {kg:g} kg kept · " + line(found, now, await database.run(db_target, request.user.id)).removeprefix(f"{ICON} ")
    message_id = await cards.send(request.channel_id, Card(said, ((Button("Undo", "gym", UNDO, str(weigh_id), emoji="↩️", style=cards.PRIMARY),),)))
    _changed(request.user.id)
    return Shown(said if message_id is not None else "not shown")


async def on_undo(press: cards.Press) -> str:
    gone = await press.db.run(db_remove, int(press.arg), clock.now()) if press.arg.isdigit() else False
    await press.update(Card("↩️ Taken back" if gone else "↩️ Nothing to undo"))
    _changed(press.user.id)
    return "weigh-in taken back" if gone else "nothing to undo"


async def ask(request: Request, data: dict, guessed: frozenset) -> str:
    found = await every(request.user.id)
    if not found:
        return f"{ICON} No weigh-ins yet: say “weighed 82.4” to keep one."
    now = clock.now()
    said = [line(found, now, await database.run(db_target, request.user.id))]
    recent = found[-5:]
    said.append(design.small("last: " + ", ".join(f"{each.kg:g} {each.at.astimezone(config.TIMEZONE):%a}" for each in recent)))
    return "\n".join(said)


async def target_card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    kg = _kg(data.get("kg")) if data.get("kg") not in (None, "", 0) else None
    was = await database.run(db_target, request.user.id)
    shown = f"{kg:g} kg" if kg else "no target"
    return Proposal(lines=(f"**Weight target** · " + (design.change(f"{was:g} kg", shown) if was else shown),), data={"kg": kg}, kind="change" if was else "new")


async def target_save(request: Request, data: dict) -> str:
    await database.run(db_set_target, request.user.id, data["kg"], clock.now())
    _changed(request.user.id)
    return f"{ICON} Target · {data['kg']:g} kg" if data["kg"] else f"{ICON} No weight target"


async def target_check(request: Request, data: dict) -> str:
    return "" if await database.run(db_target, request.user.id) == data["kg"] else "the target is not there"


def _changed(user_id: int) -> None:
    from core import summaries

    summaries.changed(NAME, user_id)


# --- the briefing and the week ---------------------------------------------------------------------------------------------
async def summary(user_id: int, day: date):
    """One small line, only on a day with a weigh-in."""
    from core.actions import Summary

    found = await every(user_id)
    if not any(days.day_of(each.at) == day for each in found):
        return None
    said = line(found, days.end_of(day) if day != days.today() else clock.now(), await database.run(db_target, user_id))
    return Summary("", design.QUIET, overview=said.removeprefix(f"{ICON} ")) if said else None


async def week(user_id: int, monday: date, upto: date):
    from core.weekly import Week

    found = await every(user_id)
    inside = [each for each in found if monday <= days.day_of(each.at) <= upto]
    if not inside:
        return None
    said = line(found, days.end_of(upto), await database.run(db_target, user_id)).removeprefix(f"{ICON} ")
    return Week(said, None, None, f"{len(inside)} weigh-in{'' if len(inside) == 1 else 's'}", design.QUIET)


def entry():
    from core import repeats
    from core.actions import EACH_DAY, SEE, SET_UP, Action, Entry

    actions = (
        Action("weight_log", "A weigh-in (\"82.4\", \"weighed 82.4 this morning\" -> kg 82.4). A log: no card.",
               (Field("kg", "The weight in kg, as a number.", NUMBER, required=True), Field("time", "The time, if one was said.", TIME)),
               needs_card=False, run=log, purpose=EACH_DAY, say=("weighed 82.4 this morning",)),
        Action("weight_trend", "The weight trend (\"what's my weight trend?\", \"how's my weight going?\").", (), needs_card=False, run=ask, purpose=SEE, say=("what's my weight trend?",)),
        Action("weight_target", "A weight target (\"aim for 80\" -> kg 80; \"no weight target\" -> kg 0).", (Field("kg", "The target in kg; 0 for none.", NUMBER, required=True),),
               prepare=target_card, apply=target_save, verify=target_check, purpose=SET_UP, say=("aim for 80",)),
    )
    return Entry(NAME, ICON, ONLY_FOR, EXAMPLES, actions, identity=(), on_repeat=repeats.ALLOW_ANOTHER, label="Weight", private=True, place=41,
                 summary=summary, week=week)


def register() -> None:
    cards.register("gym", UNDO, on_undo)
