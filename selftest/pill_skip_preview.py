"""Design · Pill Skip, a post of its own in the Design forum, as the dev bot, made-up pills only:

    python -m selftest.pill_skip_preview [--check]

The pill reminder with Taken and Skip and no Snooze (3 Nov), the same card once Skip is pressed (in
place, with Undo), and the "skip all" confirm card with what its Save leaves: each drawn by the pills
task's own code, in the round live uses (DESIGN_ROUND=8, CARDS_V2 on), against a temporary database
holding Pill A (three doses) and Pill B (two). No request to Claude; live is not touched.
"""
import asyncio
import sys
import tempfile
from datetime import time
from pathlib import Path

TITLE = "Design · Pill Skip"
PILL_A = {"name": "Pill A", "per_day": 3, "times": ["8:00 am", "1:00 pm", "6:00 pm"], "notes": "with food"}
PILL_B = {"name": "Pill B", "times": ["1:00 pm", "9:00 pm"]}


def build() -> list[tuple[str, tuple]]:
    from types import SimpleNamespace

    from core import actions, backup, cards, clock, config, confirm, database, design, migrations, occurrences, users
    from core import day as days
    from core.actions import Request
    from tasks.pills import checklist, plain, reminders, skipping, store
    from tasks.pills import task as pills_task

    folder = Path(tempfile.mkdtemp(prefix="pill-skip-preview-"))
    database.DB_PATH = folder / "preview.db"
    backup.BACKUP_DIR = folder / "backups"
    migrations.migrate({"pills": store.MIGRATIONS})
    users.ensure_owner()
    owner = asyncio.run(users.get_user(1))
    config.CARDS_V2, config.DESIGN_ROUND, config.REMINDERS_ENABLED, config.HUB_TIDY = True, 8, False, False
    actions.set_catalogue(pills_task.entries())
    messages: dict[int, object] = {}

    async def send(channel_id, card, silent=False):
        message_id = len(messages) + 1
        messages[message_id] = card
        return message_id

    async def edit(channel_id, message_id, card, fall_back=True):
        messages[message_id] = card
        return True

    async def nothing(*args, **kwargs):
        return None

    cards.send, cards.edit = send, edit
    checklist.refresh = nothing
    found: list[tuple[str, tuple]] = []

    async def story():
        request = Request(owner, 1, "add")
        for each in (PILL_A, PILL_B):
            proposal = await plain.add_card(request, {"pills": [each]}, frozenset())
            await plain.add_save(request, proposal.data)
        _, listed, today_ = await checklist.view(owner.id)
        dose = next(each for each in listed if each.pill.plan.name == "Pill A" and each.number == 1)
        due = days.at(today_, time(8, 0))
        prompt = reminders.Prompt(dose.occurrence.id, owner.id, today_, 1, 1, due, due)
        reminder = reminders.card(dose, listed, prompt, due)
        found.append((
            "A reminder, as the hub shows it: the neutral line on top is all the lock screen shows (no pill), then the dose. "
            "Two buttons now, **Taken** and **Skip**: no Snooze, since the reminder already comes again 15, 30 and 45 minutes later. 👍 on it is still Taken",
            reminder.layout,
        ))
        await checklist.mark(dose, checklist.SKIP, clock.now(), occurrences.BUTTON)
        _, listed, _ = await checklist.view(owner.id)
        skipped = next(each for each in listed if each.occurrence.id == dose.occurrence.id)
        found.append((
            "The same message once **Skip** is pressed, edited in place: grey, dose 1 skipped, no more reminders for it today. "
            "Nothing new is posted under it. **Undo** makes it the reminder again, as it was, and its reminders carry on; the card leaves the hub after half an hour",
            reminders.skipped_card(skipped, listed, reminders.undo_arg(prompt)).layout,
        ))
        await checklist.mark(skipped, checklist.NOT_TAKEN, clock.now(), occurrences.BUTTON)
        _, listed, _ = await checklist.view(owner.id)
        first = next(each for each in listed if each.pill.plan.name == "Pill A" and each.number == 1)
        await checklist.mark(first, checklist.TAKEN, days.at(today_, time(8, 5)), occurrences.BUTTON)
        said = Request(owner, 1, "skip all")
        proposal = await skipping.card(said, {}, frozenset())
        shown = confirm.render(actions.entry("pills"), proposal, 1)
        found.append((
            "“skip all my pills” after dose 1 of Pill A was taken: one card listing every dose still to take today, by its time, "
            "with Save and Cancel. Which doses “all” covers is worked out by the bot from the plan, never by Claude; "
            "“skip all of Pill A” is the same card with Pill A's only. Nothing is skipped until Save",
            shown.layout,
        ))
        answer = await skipping.save(said, proposal.data)
        await answer.placed(99)
        saved = messages[99]
        found.append((
            "What Save leaves in its place: each dose skipped, what is left, and **Undo**, which brings them all back to take, with their reminders. "
            "With nothing left to skip it is one line instead: “💊 Nothing is left to take today: there is nothing to skip.”",
            design.plain(saved.text, saved.rows),
        ))

    asyncio.run(story())
    for label, pieces in found:
        wrong = design.problem(pieces)
        if wrong:
            raise SystemExit(f"{label[:50]}: {wrong}")
    return found


def opening() -> str:
    return "\n".join([
        "## Pill Skip",
        "Two weeks in, Snooze was never pressed: a reminder already comes again at the dose's time and 15, 30 and 45 minutes later. What was missing was Skip.",
        "**Every pill reminder has two buttons, Taken and Skip.** Skip skips that one dose and stops its reminders, and the card says so in place with Undo. "
        "The reminders that come again and the one “last chance” message are as before.",
        "**“skip all” means all:** “skip all of Pill A” or “skip all Pill A today” is every dose of that pill still to take today; “skip all my pills” or “skip all” is every pill's. "
        "Doses already taken are left alone. One confirm card lists them, Save skips them, Undo brings them back.",
        "Still the same: 👍 on a reminder is Taken, and “skip Pill A” or “skip the 1 pm one” skips one dose.",
        "**Try it on the dev bot:** add a made-up pill at three times, wait for its reminder, press Skip, then Undo; then say “skip all of” it, Save, and Undo.",
        "-# Drawn by the bot's own code from made-up pills, in the round live uses. The buttons here do nothing.",
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
