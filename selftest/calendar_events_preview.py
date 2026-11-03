"""Design · Calendar events, a post of its own in the Design forum, as the dev bot, made-up events only:

    python -m selftest.calendar_events_preview [--check]

The confirm card for a weekly event with where it is, for an event over several days, and the question when a
message could be a calendar event or a personal routine (3 Nov): each drawn by the calendar's own code, in the
round live uses (DESIGN_ROUND=8, CARDS_V2 on), against a temporary database and a made-up Bot calendar that
nothing is written to. No request to Claude; Google and live are not touched.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

TITLE = "Design · Calendar events"
WEEKLY = ("create an event called pilates every Tuesday at 4 pm for one hour at the community hall",
          {"title": "pilates", "repeat": "days", "weekdays": ["tue"], "time": "4 pm", "length": 60, "location": "community hall"})
WEEKEND = ("camping trip from Friday to Sunday at Lake Test, notes: bring the tent",
           {"title": "camping trip", "day": "Friday", "last_day": "Sunday", "location": "Lake Test", "description": "bring the tent"})
EITHER = "yoga every Thursday at 6pm"


def build() -> list[tuple[str, tuple]]:
    from core import actions, backup, config, confirm, database, design, migrations, users
    from core.actions import Request
    from tasks.calendar import plain, store
    from tasks.calendar import task as calendar_task
    from tasks.habits import store as habits_store
    from tasks.habits import task as habits_task

    folder = Path(tempfile.mkdtemp(prefix="calendar-events-preview-"))
    database.DB_PATH = folder / "preview.db"
    backup.BACKUP_DIR = folder / "backups"
    migrations.migrate({"calendar": store.MIGRATIONS, "habits": habits_store.MIGRATIONS})
    users.ensure_owner()
    owner = asyncio.run(users.get_user(1))
    config.CARDS_V2, config.DESIGN_ROUND = True, 8
    config.CALENDAR_ENABLED, config.CALENDAR_WRITE, config.HABITS_ENABLED = True, True, True
    config.CALENDAR_BOT_ID, config.CALENDAR_ICS_URL, config.CALENDAR_READ = "made-up-preview@group.calendar.example", "", "google:CALENDAR_BOT_ID"
    actions.set_catalogue([*calendar_task.entries(), *habits_task.entries()])
    entry = actions.entry("calendar")
    found: list[tuple[str, tuple]] = []

    async def story():
        said, data = WEEKLY
        proposal = await plain.add_card(Request(owner, 1, said), data, frozenset())
        found.append((
            f"“{said}”: a weekly event, never refused or sent to routines. Every field it will save is on a small line of its own, "
            "and only those with a value: when it starts, its time, its length, where it is and how often (no end: it repeats until stopped). "
            "Then its next three dates. Save makes a real repeating event on the Bot calendar",
            confirm.render(entry, proposal, 1).layout,
        ))
        said, data = WEEKEND
        proposal = await plain.add_card(Request(owner, 1, said), data, frozenset())
        found.append((
            f"“{said}”: one event over the three days, all day as no time was said (“Friday 6pm to Sunday 2pm” would be timed). "
            "The location and the description are written to the event in Google Calendar. In answers and the week view each of its days says “day 1 of 3” and so on",
            confirm.render(entry, proposal, 2).layout,
        ))
        question = confirm.render_tie([actions.entry("calendar"), actions.entry("habits")], 3, EITHER)
        found.append((
            f"“{EITHER}”: a day and a time and nothing else could be a calendar event or a personal routine, so the bot asks, with two buttons. "
            "Naming an event, the calendar, a booking or a length (“for an hour”), or an end (“until Christmas”), makes it an event; "
            "something to tick off (“stretch every morning”) is a routine",
            question.layout,
        ))

    asyncio.run(story())
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:50]}: {wrong}")
    return found


def opening() -> str:
    return "\n".join([
        "## Calendar events",
        "Two weeks in, adding events was too narrow: no place or notes, several days misread, and a weekly event refused or sent to routines.",
        "**Where and notes:** “at the community hall”, “notes: bring the forms” go on the event in Google Calendar, and “what's on Tuesday?” says where.",
        "**Several days:** “from Friday to Sunday”, “12 to 14 November”, “3 days from Thursday” are one event, all day unless times are said; each day shows “day 1 of 3” and so on.",
        "**Weekly:** every Tuesday, every Monday and Thursday, every second Wednesday, until a day or a number of times, or no end. "
        "“cancel the gym next Tuesday” is that one only, “stop the weekly gym” ends it from today with the past kept, and “move Tuesday's gym to 5 pm” moves that one; each on a card that says which, with Undo after Save.",
        "**Event or routine:** an event, the calendar, a booking or a length is the calendar; something to tick off is a routine; one that could be either is asked, as below.",
        "-# Drawn by the bot's own code from made-up events, in the round live uses. The buttons here do nothing.",
    ])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    found = build()
    if "--check" in sys.argv:
        print(f"{len(found)} messages built, each within one message.")
        return 0
    from selftest import preview

    print("Posted:", asyncio.run(preview.post_preview(TITLE, opening(), found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
