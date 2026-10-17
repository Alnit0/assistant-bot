"""Design · Gym, posted in the Design forum as the dev bot, made-up data only:

    python -m selftest.gym_preview [--check]

Every card is drawn by the gym's own code against a temporary database holding the made-up logbook of
tests/gym_files.py, imported on what the real API answered for it (evals/fixtures/gym_import.json, offline):
the import card, a workout card, the Log form (drawn as its boxes: a form can't be posted), a set logged, the
summary with a personal best, and a session described in words.
"""
import asyncio
import json
import sys
import tempfile
from datetime import date, time, timedelta
from pathlib import Path

TITLE = "Design · Gym"


def build() -> list[tuple[str, tuple]]:
    from core import backup, cards, clock, config, confirm, database, design, llm, migrations, users
    from core import day as days
    from core.actions import Attachment, Entry, Request
    from tasks.gym import plain, rules, session, store
    from tests import gym_files

    folder = Path(tempfile.mkdtemp(prefix="gym-preview-"))
    database.DB_PATH = folder / "preview.db"
    backup.BACKUP_DIR = folder / "backups"
    migrations.migrate({"gym": store.MIGRATIONS})
    users.ensure_owner()
    owner = asyncio.run(users.get_user(1))
    config.GYM_ENABLED = True
    config.CHANNELS["gym"] = 1
    config.DESIGN_ROUND = 5
    config.CARDS_V2 = True
    sent: list = []

    async def send(channel_id, card, silent=False):
        sent.append(card)
        return len(sent)

    async def edit(channel_id, message_id, card):
        sent.append(card)
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

    entry = Entry("gym", rules.ICON, "x", ("y",), (), label="Gym")
    request = Request(owner, 1, "here's my gym logbook", attachments=(Attachment("logbook.csv", len(data), "text/csv", fetch),))
    found = []

    async def story():
        proposal = await plain.import_card(request, {}, frozenset())
        found.append(("Your logbook sent in #inbox (a CSV, an XLSX with a tab a workout, or rows pasted): the plan and the log apart, on one card. A DNF workout is planned and not done; a note about pain is shown the next time", confirm.render(entry, proposal, 1).layout))
        await plain.import_save(Request(owner, 1), proposal.data)
        started = await session.start(owner.id)
        found.append(("“starting a workout”: the next in the queue, its card in #gym. Each set with its suggested weight and why, last time and its note small, ⚠️ when that note was about pain; a Log button on each exercise, Finish last", sent[-1].layout))
        squat = next(each for each in await session.exercises_of(started) if each.name == "Squat")
        form = await session.form_for(started, squat)
        boxes = "\n".join(f"**{each.label}**\n> {each.value or ' '}" for each in form.fields)
        found.append(("📝 Log on Squat opens a form (Discord's own pop-up): a box a set with the suggested weight filled in, you type the reps (and change the weight), and a note", (design.Box(design.DECISION, (design.Text(f"### 📝 {form.title}\n{boxes}"),)),)))
        await session.log_sets(started, "Squat", [rules.DoneSet("Squat", rules.WARM_UP, "Warm-up", rules.WARMING, 8, 10, 10, 40.0), rules.DoneSet("Squat", rules.WORKING, "To failure", rules.TO_FAILURE, 4, 6, 6, 85.0, position=1)], None)
        found.append(("After the form: one line under the card, with Undo, and the card drawn again with the exercise done", (design.Text("✅ **Squat** · 40 kg × 10, 85 kg × 6"), design.Row(session.undo_row(1)))))
        said, _ = await session.finish(started)
        found.append(("🏁 Finish workout: what was not logged is not done, a summary with today against last time and the bests beaten, and the next workout comes round. Undo after it", (design.Box(design.DONE, (design.Text(said), design.Row(session.undo_row(2)))),)))
        described = [
            {"exercise": "Bench press", "set_type": "warm-up", "reps": 15, "weight": 20}, {"exercise": "Bench press", "reps": 9, "weight": 40}, {"exercise": "Bench press", "reps": 8, "weight": 40},
            {"exercise": "Incline press", "reps": 10, "weight": 14, "per_hand": True}, {"exercise": "Lateral raise", "skipped": True, "note": "shoulder felt off", "pain": True},
            {"exercise": "Lat pulldown - wide grip", "reps": 12, "weight": 57}, {"exercise": "Lat pulldown - wide grip", "reps": 10, "weight": 57, "note": "last set was a grind"},
        ]
        card = await plain.describe_card(Request(owner, 1, "did Upper 1 this morning …"), {"workout": "Upper 1", "sets": described}, frozenset())
        found.append(("A session described in words, during or after (“did Upper 1 this morning; bench warm-up 20 for 15, then 40 for 9 and 8; incline 14s for 10; skipped laterals, shoulder felt off; pulldown 57 for 12 and 10, last set was a grind”): one card, the notes word for word on the right exercise. Save, Cancel, or fix it in words (“the second bench set was 9 not 8”). A photo of a whiteboard goes the same way", confirm.render(entry, card, 2).layout))
        found.append(("“how's my bench going?”, answered in place", (design.Text(await plain.ask(Request(owner, 1), {"question": "trend", "exercise": "bench"}, frozenset())),)))
        found.append(("The briefing's The day, one line; nothing pings", (design.topic(design.card_title("🗓️ The day"), lines=["💊 **Pills** · 6 doses · first 7:00 am", "🏋️ **Gym** · next: Upper 2 · last session today · 1 this week"], status=design.QUIET),)))

    asyncio.run(story())
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:50]}: {wrong}")
    return found


def opening() -> str:
    return "\n".join([
        f"## {TITLE}",
        "Your goals, in your words: help upkeep data entry, data retrieval, create consistency, lower administration, see progress, easy access to notes, make life easier. Flexible, never naggy.",
        "**Import:** send your logbook (CSV or XLSX, or paste its rows). Claude reads the headings and a few rows to map the columns; Python reads every value. The plan (workouts in rotation order) and the log (dated sessions) come apart, on one card.",
        "**The rotation:** no fixed days. Say starting a workout, gym now or what's my workout: the next one's card in #gym. Do Lower 2 instead, skip Upper 1, did a 30 min run instead, swap bench for dumbbell press today, make RDLs 6-10.",
        "**Logging:** a Log button on each exercise (a form, the suggested weight filled in), or say it in words, during or after, even days later. Finish gives a summary with your bests and moves the queue on. Undo for each.",
        "**Suggested weight:** double progression from your last to-failure set, said in a few words on the card. **Questions:** what did I do on bench last time, my notes on RDLs, best leg press, how's my bench going, sessions this month. **Gym tomorrow 6pm** books it on the Bot calendar.",
        "-# Made-up logbook only. The buttons here do nothing.",
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
