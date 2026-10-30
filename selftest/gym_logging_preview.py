"""Design · Gym logging, posted in the Design forum as the dev bot, made-up data only:

    python -m selftest.gym_logging_preview [--check]

Logging at the gym on a phone (30 Oct): every card drawn by the gym's own code against a temporary database
holding the made-up logbook of tests/gym_files.py, imported on what the real API answered for it
(evals/fixtures/gym_import.json, offline). The workout card at the start, the pop-up (drawn as its boxes: a
pop-up can't be posted), the card after two logs, the two pop-ups of a five-set exercise, the summary table and
a cancelled workout. No request to Claude.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

TITLE = "Design · Gym logging"


def form_box(form) -> tuple:
    """A pop-up drawn as a box: each box's name, and the empty box under it."""
    boxes = "\n".join(f"**{each.label}**\n> ​" for each in form.fields)
    from core import design

    return (design.Box(design.DECISION, (design.Text(f"### 📝 {form.title}\n{boxes}"),)),)


def build() -> list[tuple[str, tuple]]:
    from core import backup, cards, config, database, llm, migrations, users
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
    drawn: list = []

    async def send(channel_id, card, silent=False):
        drawn.append(card)
        return 1

    async def edit(channel_id, message_id, card):
        drawn.append(card)
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

    found = []

    def press(arg, fields=None):
        from types import SimpleNamespace

        return SimpleNamespace(arg=arg, fields=fields, values=(), db=database, user=owner, channel_id=1, message_id=1)

    async def story():
        proposal = await plain.import_card(Request(owner, 1, "here's my gym logbook", attachments=(Attachment("logbook.csv", len(data), "text/csv", fetch),)), {}, frozenset())
        await plain.import_save(Request(owner, 1), proposal.data)
        plan = await store.plan(owner.id)
        lower = next(each for each in plan if each.name == "Lower 1")
        await database.run(store.db_add_exercise, owner.id, lower.id, len(lower.exercises), rules.Exercise("Test row", tuple(rules.PlannedSet(rules.WORKING, "", "", 8, 12) for _ in range(5)), rules.MACHINE))
        started = await session.start(owner.id)
        await database.run(store.db_placed, started.id, 1, 1)
        found.append(("“starting a workout”: the workout as one card in #gym. Each exercise still to do has last time's date, sets and notes small under it (or First time); its Log button, and Undo, Finish and Cancel, all at the foot of the card", drawn[-1].layout))
        exercises = await session.exercises_of(started)
        squat = next(each for each in exercises if each.name == "Squat")
        form = await session.form_for(started, squat)
        found.append(("📝 Squat opens the pop-up (Discord's own; drawn here as its boxes): a box a set, every one empty, last time's numbers in each box's name, and Notes. Type “82.5 x 6”, and anything after the numbers is that set's note", form_box(form)))
        await session.on_logged(press(form.arg, {"set0": "40 x 10", "set1": "82.5 x 6 felt heavy", "note": ""}))
        deadlift = next(each for each in exercises if each.name == "Romanian deadlift")
        await session.on_logged(press((await session.form_for(started, deadlift)).arg, {"set0": "72.5 x 9", "note": ""}))
        found.append(("After two logs: the same card, edited in place, nothing posted under it, so its buttons stay where your thumb is. What was logged is a table at the top, a note small under it; what the last form did is the small line over the buttons, with Undo; a logged exercise keeps its button, ✅", drawn[-1].layout))
        row = next(each for each in await session.exercises_of(started) if each.name == "Test row")
        first = await session.form_for(started, row)
        found.append(("An exercise of five sets (made up, Test row): a pop-up holds five boxes, so the first has sets 1 to 4 and Notes…", form_box(first)))
        await session.on_logged(press(first.arg, {"set0": "40 x 12", "set1": "40 x 12", "set2": "40 x 11", "set3": "40 x 10", "note": ""}))
        second = await session.form_for(started, row, 4)
        found.append(("…and one more tap on the same button, which hasn't moved, opens the rest. Discord can't open a pop-up straight from another one's Submit", (*form_box(second), *drawn[-1].layout)))
        await session.on_logged(press(second.arg, {"set4": "40 x 9"}))
        current = await database.run(store.db_session, started.id)
        await session.finish(current)
        found.append(("🏁 Finish workout: the card becomes the summary. Every exercise a row, every set a column, a dash for a set not done, each row within 32 characters; the bests under it; Undo", drawn[-1].layout))
        again = await session.start(owner.id)
        await database.run(store.db_placed, again.id, 1, 1)
        upper = await session.exercises_of(again)
        await session.on_logged(press((await session.form_for(again, upper[0])).arg, {"set0": "20 x 15", "note": ""}))
        await session.cancel(await database.run(store.db_session, again.id))
        found.append(("↩️ Cancel workout (or say “cancel workout”): as if it was never started. What was logged is taken off, nothing counts as done, and the same workout is still next. Undo when something had been logged", drawn[-1].layout))

    asyncio.run(story())
    from core import design

    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:50]}: {wrong}")
    return found


def opening() -> str:
    return "\n".join([
        f"## {TITLE}",
        "Logging at the gym, for your phone: one box a set, Cancel as an undo, one tap every time, a clean table, and last time's numbers shown but never in the way.",
        "**Try it on the dev bot:** start a workout, log two exercises, a five-set one, then Finish, and Cancel another. The buttons should never move between taps.",
        "-# Drawn by the bot's own code from a made-up logbook. The pop-ups can't be posted, so they are drawn as their boxes. The buttons here do nothing.",
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
