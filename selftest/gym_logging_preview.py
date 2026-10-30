"""Design · Gym logging, a new message in its post in the Design forum, as the dev bot, made-up data only:

    python -m selftest.gym_logging_preview [--check]

Logging a set at a time (30 Oct, reworked after Alex's look; ticked set buttons and notes on sets only after his
try): the workout's header and three exercise cards,
drawn by the gym's own code against a temporary database holding the made-up logbook of tests/gym_files.py,
imported on what the real API answered for it (evals/fixtures/gym_import.json, offline): one exercise untouched,
one with one set logged, one complete. The set's pop-up can't be posted, so it is said in words. No request to
Claude.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

TITLE = "Design · Gym logging"


def build() -> list[tuple[str, tuple]]:
    from types import SimpleNamespace

    from core import backup, cards, config, database, design, llm, migrations, users
    from core.actions import Attachment, Request
    from tasks.gym import plain, rules, session, store
    from tests import gym_files

    folder = Path(tempfile.mkdtemp(prefix="gym-logging-preview-"))
    database.DB_PATH = folder / "preview.db"
    backup.BACKUP_DIR = folder / "backups"
    migrations.migrate({"gym": store.MIGRATIONS})
    users.ensure_owner()
    owner = asyncio.run(users.get_user(1))
    config.GYM_ENABLED = True
    config.CHANNELS["gym"] = 1
    config.CARDS_V2 = True
    messages: dict[int, object] = {}

    async def send(channel_id, card, silent=False):
        message_id = len(messages) + 1
        messages[message_id] = card
        return message_id

    async def edit(channel_id, message_id, card):
        messages[message_id] = card
        return True

    cards.send, cards.edit = send, edit
    session.changed = lambda user_id: None
    recorded = [tuple(each) for each in json.loads((config.BASE_DIR / "evals" / "fixtures" / "gym_import.json").read_text(encoding="utf-8"))["csv"]]

    async def replay(system, user, tools, **more):
        return recorded.pop(0)

    llm.call_tool = replay
    data = gym_files.logbook_csv()

    async def fetch():
        return data

    def press(arg, fields=None):
        return SimpleNamespace(arg=arg, fields=fields, values=(), db=database, user=owner, channel_id=1, message_id=1)

    found = []

    async def story():
        proposal = await plain.import_card(Request(owner, 1, "here's my gym logbook", attachments=(Attachment("logbook.csv", len(data), "text/csv", fetch),)), {}, frozenset())
        await plain.import_save(Request(owner, 1), proposal.data)
        plan = await store.plan(owner.id)
        lower = next(each for each in plan if each.name == "Lower 1")
        # Three exercises: Squat, a made-up Test row of four sets, Romanian deadlift
        leg_press = next(each for each in lower.exercises if each.name.startswith("Leg press"))
        from core import clock

        await database.run(store.db_remove_exercise, leg_press.id, clock.now())
        await database.run(store.db_add_exercise, owner.id, lower.id, 1, rules.Exercise("Test row", tuple(rules.PlannedSet(rules.WORKING, "", "", 8, 12) for _ in range(4)), rules.MACHINE))
        started = await session.start(owner.id)
        for position, (weight, reps) in enumerate((("40", "10"), ("82.5", "6"))):
            await session.on_logged(press(f"{started.id}:0:{position}", {"weight": weight, "reps": reps, "note": "felt heavy" if position else ""}))
        await session.on_logged(press(f"{started.id}:1:0", {"weight": "40", "reps": "12", "note": ""}))
        now = await database.run(store.db_session, started.id)
        squat, row, deadlift = (messages[each] for each in now.cards["exercises"])
        found.append(("The header: the workout, how many exercises are done, and Undo, Finish and Cancel. It is edited in place as you go", messages[now.message_id].layout))
        found.append(("Squat, complete: every set logged, so its edge turns green. A logged set's button is ticked, ✅ 2, since its numbers are in the table, and one tap opens it again to put it right. A set's note is small under the table", squat.layout))
        found.append(("Test row (made up), one set logged: the table has a row a planned set from the start, so the card never grows as you log. Purple until every set is in", row.layout))
        found.append(("Romanian deadlift, untouched: last time's sets on the small line, then a dash a set, and a button a set, five to a row; no Note button, a note goes in a set's pop-up", deadlift.layout))

    asyncio.run(story())
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:50]}: {wrong}")
    return found


def opening() -> str:
    return "\n".join([
        "## Updated: ticked set buttons, notes on sets",
        "Each exercise is its own card under the workout's header, with a button a set. Finish set 1, tap **1**, log it; rest; finish set 2, tap **2**, log it. Only that exercise's card and the header change, in place, and nothing else is posted while the workout is open.",
        "**The set's pop-up** (Discord's own, so it can't be posted here): its title is the exercise and the set, “Squat · set 2”. Three boxes, every one empty, no placeholder: **Weight (kg)** and **Reps**, one line each, and **Note**, a box of several lines. Notes go only here: the card has no Note button now. Last session's numbers for that same set are in the labels, “Weight (kg) · last 80” and “Reps · last 6”; with no last session they are just the names. Leave Weight empty for a bodyweight move. When you put a set right, the labels also say what it is now, “Weight (kg) · now 82.5 · last 80”.",
        "A note said in words, “note on squat: last set felt heavy”, goes on that exercise's set logged most recently, after a confirm card.",
        "**Finish** takes the buttons off and posts the summary, every exercise and every set, under the cards. **Cancel** deletes the header and cards and leaves one line with Undo; the same workout is still next.",
        "**Try it on the dev bot:** start a workout in its #inbox (its #gym), log two sets of one exercise, put one right, add a note in a set's pop-up, then Finish or Cancel.",
        "-# Drawn by the bot's own code from a made-up logbook. The buttons here do nothing.",
    ])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    found = build()
    if "--check" in sys.argv:
        print(f"{len(found)} messages built, each within one message.")
        return 0
    from selftest import preview

    print("Posted:", asyncio.run(preview.reply_preview(TITLE, opening(), found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
