"""What's new: a few lines for one morning's briefing, then gone.

A queue of plain lines about what changed (what a batch built overnight,
what is waiting to be looked at), each for one day. The briefing of that
day shows them in a "What's new" box; the next day's briefing does not, so
they are gone after the next tidy. Nothing pings and nothing is posted.

Kept in `held_alerts` as their own kind (core/notify.py), dated the
morning they are for, so a restart loses nothing and no migration is needed.

Added from code (`await whatsnew.add(line)`) or, by a batch, from the
command line before live is restarted:

    python -m core.whatsnew add "Round 3 of the design is live" [--on 2026-10-15]
    python -m core.whatsnew list [--on 2026-10-15]

The command line writes to the database of the settings it runs with
(`.env`: live's), and only adds or lists: it changes nothing else.
"""
import sqlite3
import sys
from datetime import date, datetime, time, timedelta

from core import clock, config, database, notify
from core import day as days

KIND = notify.NEWS
# The moment a day's lines are kept under: after 7 am, outside the night that the briefing lists
# as held back (notify.window), so code from before this file never shows them as alerts
AT = time(7, 30)
MAX = 6  # lines a box; more are counted


def moment(day: date) -> datetime:
    return days.at(day, AT)


def db_add(conn: sqlite3.Connection, user_id: int, line: str, day: date, now: datetime) -> None:
    """One line for that day's briefing. The same line twice for a day is kept once."""
    conn.execute(
        """
        INSERT INTO held_alerts (user_id, kind, key, line, level, channel_id, message_id, held_at, times)
        VALUES (?, ?, ?, ?, 0, NULL, NULL, ?, 1)
        ON CONFLICT(user_id, kind, key) DO NOTHING
        """,
        (user_id, KIND, f"{day.isoformat()}:{line.strip()}"[:500], line.strip(), moment(day).isoformat()),
    )


def db_for(conn: sqlite3.Connection, user_id: int, day: date) -> list[str]:
    rows = conn.execute(
        "SELECT line FROM held_alerts WHERE user_id = ? AND kind = ? AND held_at >= ? AND held_at < ? ORDER BY id",
        (user_id, KIND, days.start_of(day).isoformat(), days.start_of(day + timedelta(days=1)).isoformat()),
    ).fetchall()
    return [line for (line,) in rows]


async def add(line: str, day: date | None = None) -> None:
    """Put a line in the What's new box of a day's briefing (today's unless said)."""
    on = day or days.today()

    def keep(conn: sqlite3.Connection) -> None:
        user_id = notify.db_owner(conn)
        if user_id is not None:
            db_add(conn, user_id, line, on, clock.now())

    await database.run(keep)


async def notes_and_news(user_id: int, day: date) -> tuple[list, list[str]]:
    """What is worth knowing for a day's briefing (core/notify.py, `notes_for`) and its
    What's new lines, read together. Read only."""
    since, _ = notify.window(day)
    until = days.at(day + timedelta(days=1), config.QUIET_HOURS[1])
    return await database.run(lambda conn: (notify.db_notes(conn, user_id, since, until), db_for(conn, user_id, day)))


async def for_day(user_id: int, day: date) -> list[str]:
    """The lines for a day's briefing, in the order they were added. Read only."""
    return await database.run(db_for, user_id, day)


def lines(found: list[str]) -> list[str]:
    """At most MAX, and how many more."""
    return found[:MAX] + ([f"…and {len(found) - MAX} more"] if len(found) > MAX else [])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    on = date.fromisoformat(args[args.index("--on") + 1]) if "--on" in args else days.today()
    if args[:1] == ["add"] and len(args) >= 2:
        conn = database.connect()
        try:
            user_id = notify.db_owner(conn)
            if user_id is None:
                print("There is no owner in this database: nothing added.")
                return 1
            db_add(conn, user_id, args[1], on, clock.now())
            conn.commit()
            print(f"Added for {on}: {args[1]}")
        finally:
            conn.close()
        return 0
    if args[:1] == ["list"]:
        conn = database.connect()
        try:
            user_id = notify.db_owner(conn)
            for line in db_for(conn, user_id, on) if user_id is not None else []:
                print("-", line)
        finally:
            conn.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
