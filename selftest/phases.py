import asyncio
import os
from datetime import timedelta

from core import clock, config, confirm, database, design, occurrences, scheduler, surface
from core import day as days
from selftest.harness import Harness

# ---------------------------------------------------------------------------
# The steps, by start of the bot. Each step says where it comes from: a step
# of docs/QA-TONIGHT.md ("T41"), a block and step of docs/QA-RUN.md ("38.2"),
# or the request for the self-test itself ("asked").
#
# The pills are made up, and the day is tomorrow by the dev clock:
#   Testa     8:00 am, 11:00 am, 2:00 pm · at least 3 hours apart · not after 4:00 pm
#   Testany   once a day, any time
#   Testiron  8:00 pm (asked on the card: morning or evening?)
# ---------------------------------------------------------------------------
TASK = "pills"
NEUTRAL = "💊 Routine due · "
CAUGHT_UP = "🔁 Caught up after a restart"
PENDING, DONE, MISSED, SKIPPED = occurrences.PENDING, occurrences.DONE, occurrences.MISSED, occurrences.SKIPPED


def add(*pills: dict, guessed=()) -> tuple[str, dict]:
    return "pill_add", {"pills": list(pills), "guessed": list(guessed), "not_included": []}


def log(*doses: dict) -> tuple[str, dict]:
    return "pill_log", {"doses": list(doses), "guessed": [], "not_included": []}


def scheduled(action: str, *schedules: dict) -> tuple[str, dict]:
    return action, {"schedules": list(schedules), "guessed": [], "not_included": []}


async def schedule_named(h: Harness, name: str):
    return next((each for each in await h.schedules() if each.name == name and each.state != "removed"), None)


def about(action: str, *pills: dict) -> tuple[str, dict]:
    return action, {"pills": list(pills), "guessed": [], "not_included": []}


async def held(h: Harness, kind: str | None = None, day_offset: int = 0) -> list:
    """The checklist's messages for a day, as the pills task keeps them."""
    from tasks.pills import store

    found = await database.run(store.db_messages, h.user.id, days.today() + timedelta(days=day_offset))
    return [each for each in found if kind is None or each.kind == kind]


async def sheet_id(h: Harness, day_offset: int = 0) -> int | None:
    found = await held(h, "checklist", day_offset)
    return found[-1].message_id if found else None


async def prompts(h: Harness) -> list:
    from tasks.pills import reminders

    return await database.run(reminders.db_prompts, h.user.id)


async def dose_id(h: Harness, pill: str, seq: int) -> str:
    found = await occurrences.for_day(h.user.id, TASK, days.today())
    ids = {name: each.id for name, each in (await h.pills()).items()}
    return next(str(each.id) for each in found if each.item_id == ids[pill] and each.seq == seq)


async def card(h: Harness, channel=None):
    """The open card in a channel: (what is kept about it, the message as Discord has it)."""
    channel = channel or h.inbox
    stored = await database.run(confirm.db_latest_open, h.user.id, channel.id)
    return stored, await h.get(channel, stored.message_id if stored else None)


async def remind_due(h: Harness):
    from tasks.pills import reminders

    jobs = await scheduler.pending_jobs(TASK, reminders.JOB)
    return jobs[0].due_at if jobs else None


async def no_marks(h: Harness, message_id: int, channel=None) -> None:
    """My message is left with no 👀 (the bot is not stuck) and no ⚠️ (it did not fail)."""
    mine = await h.get(channel or h.inbox, message_id)
    if mine is not None:
        h.check("👀" not in mine.reactions and "⚠️" not in mine.reactions, f"my message is left with {mine.reactions}")


async def save_new(h: Harness, key: str, said: str, canned, name: str, source: str) -> None:
    async with h.step(key, f"“{said}”, then Save", f"A card “💊 Pills · new” naming {name} with Save and Cancel; after Save the pill exists and the card is its confirmation", source):
        mine = await h.say(said, canned=canned)
        stored, shown = await card(h)
        h.check(shown is not None, "no card was posted")
        h.check("Pills" in shown.text and name.lower() in shown.text.lower(), f"the card reads: {shown.text[:200]}")
        h.check(any("Save" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        await no_marks(h, mine)
        await h.press(shown.id, "Save", h.inbox)
        h.check(name in await h.pills(), f"{name} is not among the pills: {list(await h.pills())}")
        after = await h.get(h.inbox, shown.id)
        h.check(after is not None and not after.buttons and name.lower() in after.text.lower(), f"after Save the message reads: {after.text[:160] if after else 'gone'} with {after.labels if after else []}")
        h.saw(after.text.splitlines()[0][:120])


# ---------------------------------------------------------------------------
# Start 1
# ---------------------------------------------------------------------------
async def p1(h: Harness) -> None:
    async with h.step("1.01", "The dev bot starts in the test channels and says nothing about it", "On the dev database, with no “Online and ready” in #selftest-inbox and no start card in #selftest-log: a start leaves no trace", "asked"):
        h.check(config.DEV_DATABASE and clock.shiftable(), "this is not the dev database")
        h.check(await h.find(h.inbox, "Online and ready") is None, "“Online and ready” was posted in #selftest-inbox")
        said = [each.all_text[:60] for each in await h.recent(h.botlog, 5)]
        h.check(not any("Bot started" in each or "Started with a problem" in each or "unexpected stop" in each for each in said), f"#selftest-log has: {said}")

    async with h.step("1.01a", "The dev bot's status line and nickname during a self-test", "The status line says how far the run is: 🧪, steps done (of all, once that is known), the minutes left, and ❌ with a count once a step has failed. The nickname ends “· testing”", "attention spec, part 2"):
        import re

        from core import identity

        line = await identity.current_line()
        h.check(re.fullmatch(r"🧪 \d+(/\d+)? · \d+m( · ❌\d+)?", line) is not None, f"the status line reads: {line!r}")
        if config.BOT_NAME:
            nick = h.inbox.guild.me.nick or ""
            h.check(nick.endswith(" · testing"), "the nickname does not end “· testing”")
        h.saw(line)

    async with h.step("1.01b", "The schedules the engine made at start", "Five rows, each once: Nightly backup, End of the day and Exchange rate (the bot's own, locked), Pills checklist at 6:00 am every day in the hub, silent, and the Needs-a-look check at 7:00 am; each with exactly one run booked, with a key", "scheduler stage 1"):
        made = {each.name: each for each in await h.schedules()}
        h.check(sorted(made) == ["End of the day", "Exchange rate", "Needs-a-look check", "Nightly backup", "Pills checklist"], f"the schedules are {sorted(made)}")
        sheet = made["Pills checklist"]
        h.check((f"{sheet.at:%H:%M}", sheet.days, sheet.notify, sheet.channel, sheet.locked, sheet.steps) == ("06:00", (0, 1, 2, 3, 4, 5, 6), "silent", "hub", False, ("pills.checklist",)), f"Pills checklist is {sheet}")
        h.check(made["Nightly backup"].locked and made["End of the day"].locked and made["Nightly backup"].user_id is None, "the bot's own are not locked, or have an owner")
        for task, kind in (("core", "nightly_backup"), ("core", "day_rollover"), ("pills", "checklist")):
            waiting = [each for each in await h.runs(task, kind) if each[0] == "pending"]
            h.check(len(waiting) == 1 and waiting[0][2] and waiting[0][2].startswith("s") and "@" in waiting[0][2], f"{task}/{kind} has {waiting} booked")
        h.memo["schedules"] = sorted(f"{each.id}:{each.name}" for each in made.values())
        h.saw(", ".join(f"{name} {each.at:%H:%M}" for name, each in sorted(made.items())))

    async with h.step("1.02", "The dev clock is moved to tomorrow, 5:50 am", "The clock reads 5:50 am tomorrow; the day rolled over with nothing posted in the hub", "asked"):
        await h.clock_to(5, 50, day_offset=1)
        h.check(f"{config.now_nz():%H:%M}" == "05:50", f"the clock reads {config.now_nz():%a %H:%M}")
        h.check(not [each for each in await h.recent(h.hub, 5)], "something was posted in the hub before any pill exists")
        h.saw(f"{config.now_nz():%a %d %b %H:%M}")

    async with h.step("1.02b", "Midnight and 3:00 am went by on the way", "The end of the day and the nightly backup each ran once from their schedules, for those local times, and each is booked again for the next day; “💾 Backup saved” is in #selftest-log (the copy is in the run's own folder)", "scheduler stage 1"):
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        for task, kind, at in (("core", "day_rollover", "00:00"), ("core", "nightly_backup", "03:00")):
            found = await h.runs(task, kind)
            done = [each for each in found if each[0] == "done" and each[1] == f"{day_stamp}T{at}"]
            h.check(len(done) == 1, f"{task}/{kind} for {day_stamp} {at}: {found}")
            h.check(len([each for each in found if each[0] == "pending"]) == 1, f"{task}/{kind} is not booked once for the next day: {found}")
        h.check(await h.find(h.botlog, "Backup saved") is not None, "no “Backup saved” in #selftest-log")
        from core import backup

        saved = sorted(path.name for path in backup.BACKUP_DIR.glob("*.db"))
        h.check(len(saved) == 1, f"the backups in the run's folder: {saved}")
        h.saw(f"backup {saved[0]}")

    await save_new(
        h, "1.03", "add Testa to my pills at 8am, 11am and 2pm, at least 3 hours apart, not after 4pm, with food",
        add({"name": "Testa", "per_day": 3, "times": ["8:00 am", "11:00 am", "2:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm", "notes": "with food"}),
        "Testa", "T49, golden 1",
    )
    await save_new(h, "1.04", "add Testany to my pills once a day", add({"name": "Testany", "per_day": 1}), "Testany", "T15")

    async with h.step("1.04b", "Straight after that Save: “no, I meant 9pm”", "A change card for Testany, the pill just saved: any time → 9:00 pm, with Save and Cancel and no ❓ (it is known, not guessed). Cancel leaves the pill as it was", "golden 2b (G3)"):
        mine = await h.say("no, I meant 9pm", canned=about("pill_edit", {"pill": "@that", "times": ["9:00 pm"]}))
        stored, shown = await card(h)
        h.check(shown is not None and stored is not None and stored.action == "pill_edit", f"no change card: {[each.text[:80] for each in await h.recent(h.inbox, 3) if each.id not in h.typed]}")
        h.check("Testany" in shown.text and "9:00 pm" in shown.text and "→" in shown.text, f"the card reads: {shown.text[:240]}")
        h.check("Testa**" not in shown.text and "❓" not in shown.text, f"it is about another pill, or marked as a guess: {shown.text[:240]}")
        h.check(any("Save" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        await no_marks(h, mine)
        await h.press(shown.id, "Cancel", h.inbox)
        plan = (await h.pills())["Testany"].plan
        h.check(not plan.schedule.times, f"Cancel changed the pill: {plan.schedule.times}")
        h.saw(next((line for line in shown.text.splitlines() if "→" in line), "")[:120])

    async with h.step("1.04c", "Days of the week: “add Testdays to my pills on weekdays only”", "A card “💊 Pills · new” naming Testdays, Mon to Fri, with Save. Cancel: nothing is saved", "asked 2026-10-13 (stage 3)"):
        await h.say("add Testdays to my pills on weekdays only", canned=add({"name": "Testdays", "weekdays": ["mon", "tue", "wed", "thu", "fri"]}))
        stored, shown = await card(h)
        h.check(shown is not None and "Testdays" in shown.text and "Mon to Fri" in shown.text, f"the card reads: {shown.text[:200] if shown else 'nothing'}")
        h.check(any("Save" in label for label in shown.labels), f"its buttons are {shown.labels}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check("Testdays" not in await h.pills(), "Cancel saved the pill")
        h.saw(next((line for line in shown.text.splitlines() if "Testdays" in line), "")[:120])

    async with h.step("1.05", "A question on the card: “add Testiron to my pills at 8”", "A card with “daily at ❔”, the question morning or evening, a button for 8:00 am and 8:00 pm, Cancel, and no Save", "T25 (37.1)"):
        await h.say("add Testiron to my pills at 8", canned=add({"name": "Testiron", "times": ["8:00"]}, guessed=["times[0]"]))
        stored, shown = await card(h)
        h.check(shown is not None, "no card was posted")
        h.check("❔" in shown.text and "8:00 am" in " ".join(shown.labels) and "8:00 pm" in " ".join(shown.labels), f"the card reads: {shown.text[:200]} with {shown.labels}")
        h.check(not any("Save" in label for label in shown.labels), f"it has Save before the question is answered: {shown.labels}")
        h.memo["question_card"] = shown.id
        h.saw(" / ".join(shown.labels))

    async with h.step("1.06", "The answer is pressed: 8:00 pm, then Save", "The same message is rewritten with 8:00 pm and Save; Save adds Testiron at 8:00 pm", "T26 (37.2)"):
        pressed = await h.press(h.memo["question_card"], "8:00 pm", h.inbox)
        shown = await h.get(h.inbox, h.memo["question_card"])
        h.check(shown is not None and "8:00 pm" in shown.text and any("Save" in label for label in shown.labels), f"after the answer: {shown.text[:200] if shown else 'gone'} with {shown.labels if shown else []}")
        h.check(pressed.edits >= 1, "the card was not edited in place")
        await h.press(shown.id, "Save", h.inbox)
        pill = (await h.pills()).get("Testiron")
        h.check(pill is not None and [f"{each:%H:%M}" for each in pill.plan.schedule.times] == ["20:00"], f"Testiron is {pill.plan if pill else 'missing'}")

    async with h.step("1.07", "A typed answer: “add Testmag to my pills, twice a day at 8am”, then “9pm”", "A card asking for the other dose's time with no Save; after “9pm” a card with 8:00 am and 9:00 pm and Save. Then Cancel removes it", "T27 (37.4)"):
        await h.say("add Testmag to my pills, twice a day at 8am", canned=add({"name": "Testmag", "per_day": 2, "times": ["8:00 am"]}))
        stored, shown = await card(h)
        h.check(shown is not None and not any("Save" in label for label in shown.labels) and "?" in shown.text, f"the first card: {shown.text[:200] if shown else 'none'} with {shown.labels if shown else []}")
        await h.say("9pm", canned=add({"name": "Testmag", "per_day": 2, "times": ["8:00 am", "9:00 pm"]}))
        stored, shown = await card(h)
        h.check(shown is not None and "8:00 am" in shown.text and "9:00 pm" in shown.text and any("Save" in label for label in shown.labels), f"the second card: {shown.text[:200] if shown else 'none'} with {shown.labels if shown else []}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check((await card(h))[0] is None and "Testmag" not in await h.pills(), "the card is still open, or Testmag was saved")

    async with h.step("1.07b", "The same request with an empty place where the second time would go", "What Claude understood is still used: a card for Testmag asking for the other dose's time, never “I didn't understand that”. Cancel removes it", "self-test of 2026-10-13, fix 2"):
        # Always the recorded answer: this is the malformed shape itself, which the real API only sometimes sends
        h._canned = None
        was, h.claude = h.claude, False
        try:
            await h.say("add Testmag to my pills, twice a day at 8am", canned=add({"name": "Testmag", "per_day": 2, "times": ["8:00 am", None]}))
        finally:
            h.claude = was
        stored, shown = await card(h)
        h.check(shown is not None and "Testmag" in shown.text and "?" in shown.text and not any("Save" in label for label in shown.labels), f"the card: {shown.text[:200] if shown else 'none'}; the newest line: {[each.text[:60] for each in await h.recent(h.inbox, 2)]}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check("Testmag" not in await h.pills(), "Testmag was saved")

    async with h.step("1.07c", "A change to a pill that is only on the open card, read as a change to a saved pill", "“add Testnew at 8am, 11:30am and 2pm, at least 3 hours apart”, not saved; then “make 11:30, 11am instead”, handed over as a change to a saved pill (as it was on live): the card is replaced with 8:00 am, 11:00 am and 2:00 pm, still a new pill with Save. Never a line saying there is no such pill. Cancel removes it", "the week's messages, 2026-10-11; golden 2c"):
        # Always the recorded answers: the misreading itself is what is being tested
        h._canned = None
        was, h.claude = h.claude, False
        try:
            await h.say("add Testnew to my pills at 8am, 11:30am and 2pm, at least 3 hours apart", canned=add({"name": "Testnew", "per_day": 3, "times": ["8:00 am", "11:30 am", "2:00 pm"], "min_gap_minutes": 180}))
            stored, first = await card(h)
            h.check(first is not None and "Testnew" in first.text and "`11:30 am`" in first.text, f"the first card: {first.text[:200] if first else 'none'}")
            await h.say("make 11:30, 11am instead", canned=("pill_edit", {"pills": [{"pill": "Testnew", "times": ["8:00 am", "11:00 am", "2:00 pm"]}], "guessed": [], "not_included": []}))
        finally:
            h.claude = was
        stored, shown = await card(h)
        h.check(shown is not None and "Pills · new" in shown.text and "`8:00 am`, `11:00 am`, `2:00 pm`" in shown.text and any("Save" in label for label in shown.labels), f"the card: {shown.text[:240] if shown else 'none'}; the newest lines: {[each.text[:80] for each in await h.recent(h.inbox, 2)]}")
        h.check(shown is not None and first is not None and shown.id != first.id and await h.get(h.inbox, first.id) is None, "the first card is still there: the new one did not replace it")
        h.check("Testnew" not in await h.pills(), "Testnew was saved before Save")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check("Testnew" not in await h.pills(), "Testnew was saved")
        h.saw(shown.text.splitlines()[1][:120] if shown else "no card")

    async with h.step("1.08", "Names: “add Testvit and Testvit forte”, “I took testvit”, “skip forte”", "The whole name wins: Testvit is taken, not Testvit forte. Part of a name finds the only fit: Testvit forte is skipped", "T22 (40.1, 40.2)"):
        await h.say("add Testvit and Testvit forte to my pills, once a day", canned=add({"name": "Testvit", "per_day": 1}, {"name": "Testvit forte", "per_day": 1}))
        stored, shown = await card(h)
        h.check(shown is not None, "no card for the two pills")
        await h.press(shown.id, "Save", h.inbox)
        await h.say("I took testvit", canned=log({"pill": "testvit", "did": "taken"}), route={"kind": "task", "tasks": [TASK], "confidence": "high", "reports_doing": True, "chat_part": ""})
        await h.say("skip forte", canned=log({"pill": "forte", "did": "skipped"}))
        states = await h.doses()
        h.check(states.get(("Testvit", 1)) == DONE and states.get(("Testvit forte", 1)) == SKIPPED, f"the doses are {states}")
        h.saw(str({name: state for (name, _), state in states.items() if name.startswith("Testvit")}))

    async with h.step("1.09", "A name that fits two: “pause testv”", "A card asking which one, a button for each of the two, no Save. Cancel removes it", "T23 (40.3)"):
        await h.say("pause testv", canned=about("pill_pause", {"pill": "testv"}))
        stored, shown = await card(h)
        h.check(shown is not None, "no card was posted")
        labels = " ".join(shown.labels)
        h.check("Testvit" in labels and "forte" in labels and not any("Save" in label for label in shown.labels), f"the card reads: {shown.text[:160]} with {shown.labels}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.saw(" / ".join(shown.labels))

    for key, handed, how in (("1.09b", "Testvit", "completed to a whole name"), ("1.09c", "@that", "handed over as “it”")):
        async with h.step(key, f"“pause testv” when Claude does not pass the name on as typed ({how})", "The code checks what was typed: “testv” fits two pills, so the card still asks which one, with a button each and no Save", "self-test of 2026-10-13, fix 1"):
            was, h.claude = h.claude, False  # always the recorded answer: it is Claude's mistake that is being tested
            try:
                await h.say("pause testv", canned=about("pill_pause", {"pill": handed}))
            finally:
                h.claude = was
            stored, shown = await card(h)
            h.check(shown is not None, f"no card was posted: {[each.text[:60] for each in await h.recent(h.inbox, 2)]}")
            labels = " ".join(shown.labels)
            h.check("Testvit" in labels and "forte" in labels and not any("Save" in label for label in shown.labels), f"the card reads: {shown.text[:160]} with {shown.labels}")
            h.check("testv" in shown.text, f"the question does not quote what was typed: {shown.text[:160]}")
            await h.press(shown.id, "Cancel", h.inbox)

    async with h.step("1.10", "“remove testvit and testvit forte”, then Remove", "A remove card with a red Remove; after it both are gone", "T25 (40.5)"):
        await h.say("remove testvit and testvit forte", canned=about("pill_remove", {"pill": "Testvit"}, {"pill": "Testvit forte"}))
        stored, shown = await card(h)
        h.check(shown is not None and any("Remove" in label for label in shown.labels), f"the card: {shown.text[:160] if shown else 'none'} with {shown.labels if shown else []}")
        await h.press(shown.id, "Remove", h.inbox)
        left = list(await h.pills())
        h.check(not any(name.startswith("Testvit") for name in left), f"still there: {left}")

    async with h.step("1.10b", "`my schedule`", "A list, with no request to Claude: “🗓️ My schedule”, Pills checklist every day at 6:00 am in #hub, silent, with its next run and its last; the Needs-a-look check at 7:00 am; the bot's own a small line each with its last run; a plain message with CARDS_V2 off", "scheduler stage 2 (schedule-list-v2)"):
        before = h._real_calls
        await h.say("my schedule")
        shown = await h.find(h.inbox, "My schedule")
        h.check(shown is not None and "**Pills checklist** · every day at `6:00 am`" in shown.text, f"the list: {shown.text[:300] if shown else 'nothing'}")
        h.check("#hub · silent · next: today 6:00 am" in shown.text and "The bot's own, not changed here:" in shown.text and "Nightly backup · 3:00 am · last:" in shown.text and "Needs-a-look check" in shown.text, f"its details: {shown.text[:500]}")
        h.check(not shown.v2 and not shown.buttons and h._real_calls == before, "it is drawn, has buttons, or asked Claude")
        h.memo["schedule_list"] = shown.id

    async with h.step("1.10c", "Add: “also post the pills checklist at 6 pm”, then Save", "A card “🗓️ Schedule · new”: Evening pills checklist, every day at 6:00 pm, #hub, silent, its next run, and “also every day at 6:00 am”. After Save the schedule exists, its run for 6:00 pm today is booked, and the list shown before is brought up to date in place", "scheduler stage 2"):
        mine = await h.say("also post the pills checklist at 6 pm", canned=("schedule_add", {"what": "pills checklist", "time": "6:00 pm", "guessed": [], "not_included": []}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and "Schedule" in shown.text and "**Evening pills checklist** · every day at `6:00 pm`" in shown.text, f"the card: {shown.text[:300] if shown else 'none'}")
        h.check("also every day at `6:00 am`" in shown.text and any("Save" in label for label in shown.labels), f"the card: {shown.text[:300]} with {shown.labels}")
        await no_marks(h, mine)
        await h.press(shown.id, "Save", h.inbox)
        made = await schedule_named(h, "Evening pills checklist")
        h.check(made is not None and f"{made.at:%H:%M}" == "18:00" and made.steps == ("pills.checklist",) and made.origin == "mine", f"the schedule is {made}")
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        h.check(any(each[0] == "pending" and each[1] == f"{day_stamp}T18:00" for each in await h.runs("pills", "checklist")), f"no run booked for 6:00 pm today: {await h.runs('pills', 'checklist')}")
        await h.settle(2)
        listed = await h.get(h.inbox, h.memo["schedule_list"])
        h.check(listed is not None and "Evening pills checklist" in listed.text, "the list shown before was not brought up to date")

    async with h.step("1.10d", "Move: “move the evening checklist to 6:30pm”, then Save", "A change card: **Evening pills checklist**, `time · 6:00 pm → 6:30 pm`, and “Next after this: … today 6:30 pm”. After Save the run booked for 6:00 pm is gone and one for 6:30 pm is booked", "scheduler stage 2 (schedule-change-v1)"):
        await h.say("move the evening checklist to 6:30pm", canned=scheduled("schedule_change", {"schedule": "evening checklist", "time": "6:30 pm"}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and "time · `6:00 pm` → `6:30 pm`" in shown.text and "**Evening pills checklist**" in shown.text, f"the card: {shown.text[:300] if shown else 'none'}")
        h.check("Next after this: Evening pills checklist today 6:30 pm" in shown.text, f"it does not say when it next runs: {shown.text[:300]}")
        await h.press(shown.id, "Save", h.inbox)
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        waiting = sorted(each[1] for each in await h.runs("pills", "checklist") if each[0] == "pending")
        h.check(waiting == [f"{day_stamp}T06:00", f"{day_stamp}T18:30"], f"the runs booked are {waiting}")

    async with h.step("1.11", "6:00 am: today's checklist", "One checklist in the hub, posted without a notification, naming Testa, Testany and Testiron; a Taken / Skip message under it for Testany (no time)", "asked; 36, T15"):
        await h.clock_to(6, 0, 5)
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1, f"{len(sheets)} checklists are kept for today")
        shown = await h.get(h.hub, sheets[0].message_id)
        h.check(shown is not None and all(name in shown.text for name in ("Testa", "Testany", "Testiron")), f"the checklist reads: {shown.text[:300] if shown else 'gone'}")
        h.check(shown.silent, "it was posted with a notification")
        singles = await held(h, "dose")
        under = [await h.get(h.hub, each.message_id) for each in singles]
        h.check(len(under) == 1 and under[0] is not None and "Testany" in under[0].text and any("Taken" in label for label in under[0].labels), f"the single-dose messages: {[(each.text[:60], each.labels) if each else None for each in under]}")
        h.check(not shown.v2, "the checklist is drawn the new way with CARDS_V2 off")
        h.memo["sheet_d1"] = shown.id
        h.saw(shown.text.splitlines()[0][:80])

    async with h.step("1.11d", "What live's status line would read now (6:00 am, nothing taken, Testa due at 8:00 am)", "The top attention item is the next dose with a time, in its short form: 💊, taken/all, and “8am”. No pill is named", "attention spec, part 2"):
        import re

        from core import attention

        items = await attention.gather(h.user.id, clock.now())
        line = attention.status_line(attention.top(items, clock.now()))
        h.check(re.fullmatch(r"💊 0/\d+ · 8am", line) is not None, f"it would read: {line!r} from {[(item.task, item.urgency, item.short) for item in items]}")
        h.check(not any(name in line for name in ("Testa", "Testany", "Testiron")), f"a pill is named: {line}")
        h.check(any(item.task == "morning" and item.icon == "🌅" for item in items), f"the next morning routine is not handed in: {[(item.task, item.short) for item in items]}")
        h.saw(line)

    async with h.step("1.11a", "With BRIEFING_ENABLED off, the morning is as it always was", "No briefing in the hub, and the 6:00 am schedule is the checklist alone, under its own name", "scheduler stage 3: off"):
        h.check(not config.BRIEFING_ENABLED, "BRIEFING_ENABLED is on in this start")
        h.check(await h.count(h.hub, "☀️ Today") == 0, "a briefing was posted")
        sheet = await schedule_named(h, "Pills checklist")
        h.check(sheet is not None and sheet.steps == ("pills.checklist",), f"the 6:00 am schedule is {sheet}")

    async with h.step("1.11b", "The run log for the 6:00 am checklist", "One run for today's 6:00 am, done, with its key and a line saying what it decided; tomorrow's 6:00 am booked once", "scheduler stage 1"):
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        found = await h.runs("pills", "checklist")
        today_ = [each for each in found if each[1] == f"{day_stamp}T06:00"]
        h.check(len(today_) == 1 and today_[0][0] == "done" and today_[0][3], f"today's run: {today_}")
        waiting = sorted(each[1] for each in found if each[0] == "pending")
        next_day = f"{(config.now_nz() + timedelta(days=1)):%Y-%m-%d}"
        h.check(waiting == [f"{day_stamp}T18:30", f"{next_day}T06:00"], f"booked: {waiting} (tomorrow's 6:00 am, and this evening's from the schedule added at 1.10c)")
        h.saw(f"{today_[0][2]} · {today_[0][3][:60]}")

    async with h.step("1.11c", "`dev jobs`", "What is booked next (the backup, the end of the day, the checklist) and how the last run of each ended, from the engine's run log", "scheduler stage 1"):
        await h.say("dev jobs")
        shown = await h.find(h.inbox, "Pending jobs")
        h.check(shown is not None and "Last run of each" in shown.text, f"`dev jobs` said: {shown.text[:200] if shown else 'nothing'}")
        h.check(all(name in shown.text for name in ("core/nightly_backup", "core/day_rollover", "pills/checklist")), f"it lists: {shown.text[:400]}")

    async with h.step("1.12", "`pills` typed in #selftest-inbox", "A fresh copy at the bottom of the hub; the old checklist and its messages are gone", "T15, R48"):
        old = h.memo["sheet_d1"]
        old_single = (await held(h, "dose"))[0].message_id
        await h.say("pills")
        new = await sheet_id(h)
        h.check(new is not None and new != old, "no fresh copy was posted")
        h.check(await h.get(h.hub, old) is None and await h.get(h.hub, old_single) is None, "the old checklist or its message is still in the hub")
        h.check(len(await held(h, "checklist")) == 1, "more than one checklist is kept for today")
        h.memo["sheet_d1"] = new

    async with h.step("1.13", "`took testany`: the typed shortcut", "At once “✅ **Testany** · taken …”, the checklist shows it, Testany's own message goes, and no request to Claude is made", "43.1"):
        before = h._real_calls
        single = (await held(h, "dose"))[0].message_id
        mine = await h.say("took testany")
        said = await h.find(h.inbox, "Testany", "taken")
        h.check(said is not None and "✅" in said.text, f"the newest lines: {[each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        h.check((await h.doses()).get(("Testany", 1)) == DONE, f"the doses are {await h.doses()}")
        h.check(await h.get(h.hub, single) is None, "Testany's Taken / Skip message is still there")
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and "✅" in sheet.text, f"the checklist reads: {sheet.text[:200] if sheet else 'gone'}")
        h.check(h._real_calls == before, "a request went to Claude")
        await no_marks(h, mine)
        h.saw(said.text[:80])

    async with h.step("1.14", "`took testany` again", "Not the shortcut any more (nothing is left today): it is read as plain words, and the answer says it is already taken. Nothing changes", "43.2"):
        mine = await h.say("took testany", canned=log({"pill": "Testany", "did": "taken"}), route={"kind": "task", "tasks": [TASK], "confidence": "high", "reports_doing": True, "chat_part": ""})
        latest = [each for each in await h.recent(h.inbox, 4) if each.id not in h.typed]
        h.check(latest and "Testany" in latest[0].text, f"the newest line: {latest[0].text[:120] if latest else 'none'}")
        h.check((await h.doses()).get(("Testany", 1)) == DONE, "the dose changed")
        await no_marks(h, mine)
        h.saw(latest[0].text[:100])

    async with h.step("1.15", "8:00 am: the reminder for Testa", "One new message in the hub that notifies. Its first line is “💊 Routine due · 8:00 am” and names no pill; it was posted as that line and written in after (an edit); under it Testa, dose 1 of 3, with Taken, Taken at…, Snooze 15m, Skip", "T41 (38.2), asked"):
        await h.clock_to(8, 0, 5)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None, "the prompt is not in the hub")
        first = shown.text.splitlines()[0]
        h.check(first.startswith(NEUTRAL + "8:00 am") and "Testa" not in first, f"its first line is “{first}”")
        h.check("Testa" in shown.text and "dose 1 of 3" in shown.text, f"it reads: {shown.text[:200]}")
        h.check(shown.edited, "it was not edited after being posted: the pill was in the notification")
        h.check(not shown.silent, "it was posted silently: it would not notify")
        h.check([label.split()[-1] if label else "" for label in shown.labels] and all(any(word in label for label in shown.labels) for word in ("Taken", "Taken at", "Snooze", "Skip")), f"its buttons are {shown.labels}")
        h.memo["prompt"] = shown.id
        h.saw(first)

    async with h.step("1.15b", "With the 8:00 am dose due and not taken, live's status line would say so", "The top attention item is the dose that is due: “💊 due 8am”", "attention spec, part 2"):
        from core import attention

        line = attention.status_line(attention.top(await attention.gather(h.user.id, clock.now()), clock.now()))
        h.check(line == "💊 due 8am", f"it would read: {line!r}")
        h.saw(line)

    async with h.step("1.16", "Taken is pressed on the reminder", "The reminder goes; dose 1 is taken; the checklist shows it", "38.4"):
        await h.press(h.memo["prompt"], "Taken")
        h.check(await h.get(h.hub, h.memo["prompt"]) is None and not await prompts(h), "the reminder is still up")
        h.check((await h.doses()).get(("Testa", 1)) == DONE, f"the doses are {await h.doses()}")
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and "8:00 am" in sheet.text, f"the checklist reads: {sheet.text[:240] if sheet else 'gone'}")

    async with h.step("1.17", "Too soon: `took testa` a minute after dose 1", "A card that says dose 1 was already logged and asks in so many words: “⚠️ You already logged dose 1 at … Add another dose?” with Log it and Cancel; nothing is ticked off. Cancel removes it", "43.3, T46; asked 2026-10-14"):
        await h.say("took testa")
        stored, shown = await card(h)
        h.check(shown is not None and "⚠️ You already logged dose 1 at " in shown.text and "Add another dose?" in shown.text, f"the card: {shown.text[:200] if shown else 'none'}")
        h.check("Log it anyway?" not in shown.text and "Log it as taken now?" not in shown.text, f"it still asks as if nothing had been logged: {shown.text[:200]}")
        h.check(any("Log it" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        h.check((await h.doses()).get(("Testa", 2)) == PENDING, "dose 2 was ticked off without asking")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check((await h.doses()).get(("Testa", 2)) == PENDING and (await card(h))[0] is None, "after Cancel the dose changed or the card is still open")
        warned = next((line for line in shown.text.splitlines() if "⚠️" in line), "")
        h.saw(warned[:120])
        h.check("0m" not in warned, f"it still counts in minutes under a minute: {warned.strip()[:100]}")
        if f"{config.now_nz():%H:%M}" == "08:00":  # dose 1 was taken at 8:00 and it is still 8:00
            h.check("just now" in warned, f"under a minute after dose 1 it does not say “just now”: {warned.strip()[:100]}")

    async with h.step("1.17b", "“that was dose 2”, about the dose just logged", "A correction of that log, with no card open: a change card “Testa · dose 1 → dose 2 · taken …” with what becomes of dose 1 under it, Save and Cancel. Nothing is logged a second time, and nothing changes until Save. Cancel", "golden 19; asked 2026-10-14"):
        before = await h.doses()
        mine = await h.say("that was dose 2", canned=log({"pill": "@that", "did": "taken", "dose": 2, "correction": True}))
        stored, shown = await card(h)
        h.check(shown is not None, f"no card: {[each.text[:80] for each in await h.recent(h.inbox, 3)]}")
        h.check("**Testa** · dose 1 → dose 2 · taken " in shown.text and "dose 1 · still to take" in shown.text, f"the card reads: {shown.text[:240]}")
        h.check("Log it as taken now?" not in shown.text and "Add another dose?" not in shown.text, f"it reads as a new dose: {shown.text[:240]}")
        h.check(any("Save" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        h.check(await h.doses() == before, f"something changed by asking: {await h.doses()}")
        h.saw(next((line for line in shown.text.splitlines() if "→" in line), "")[:120])
        await h.press(shown.id, "Cancel", h.inbox)
        h.check(await h.doses() == before and (await card(h))[0] is None, "after Cancel a dose changed or the card is still open")
        await no_marks(h, mine)

    async with h.step("1.18", "The next reminder, and Snooze 15m", "When dose 2 falls due a reminder is posted; Snooze rewrites the same message with “Snoozed until …”", "T42 (38.3)"):
        due = await remind_due(h)
        h.check(due is not None, "no reminder is booked")
        await h.clock_at(due)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        h.memo["prompt"] = up[0].message_id
        pressed = await h.press(up[0].message_id, "Snooze")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None and "Snoozed until" in shown.text, f"after Snooze: {shown.text[:200] if shown else 'gone'}")
        h.check(pressed.edits >= 1, "the message was not edited in place")
        h.saw(next((line for line in shown.text.splitlines() if "Snoozed" in line), ""))

    async with h.step("1.19", "15 minutes later the reminder is posted again", "A new message takes the place of the snoozed one (so the phone buzzes again); only ever one prompt", "T42 (38.3)"):
        await h.clock_by(minutes=15, seconds=10)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id and up[0].message_id != h.memo["prompt"], f"the prompt kept is {up[0].message_id if up else None}, before {h.memo['prompt']}")
        h.check(await h.get(h.hub, h.memo["prompt"]) is None, "the snoozed message is still there")
        h.check(await h.count(h.hub, NEUTRAL) == 1, f"{await h.count(h.hub, NEUTRAL)} reminders are in the hub")
        h.memo["prompt"] = up[0].message_id

    async with h.step("1.20", "Taken at… on the reminder, with a time typed", "A form opens; with the time sent, the reminder goes and dose 2 is taken at that time", "T43 (38.4)"):
        pressed = await h.press(h.memo["prompt"], "Taken at")
        h.check(pressed.form is not None, f"no form opened; it said {pressed.said}")
        at = config.now_nz() - timedelta(minutes=5)
        typed = f"{at:%I:%M%p}".lstrip("0").lower()
        sent = await h.submit(pressed, at=typed)
        h.check(await h.get(h.hub, h.memo["prompt"]) is None, f"the reminder is still up; the form said {sent.said}")
        h.check((await h.doses()).get(("Testa", 2)) == DONE, f"the doses are {await h.doses()}")
        h.memo["dose2_at"] = f"{at:%I:%M %p}".lstrip("0").lower()
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and h.memo["dose2_at"] in sheet.text.lower(), f"the checklist does not show {h.memo['dose2_at']}: {sheet.text[:260] if sheet else 'gone'}")
        h.saw(f"taken at {h.memo['dose2_at']}")

    async with h.step("1.21", "A correction in words: “actually dose 2 of testa was at …”", "One line with the old time → the new one, and no second dose logged", "asked; pills stage 4"):
        at = config.now_nz() - timedelta(minutes=9)
        new = f"{at:%I:%M %p}".lstrip("0").lower()
        mine = await h.say(f"actually dose 2 of testa was at {new.replace(' ', '')}", canned=log({"pill": "Testa", "did": "taken", "dose": 2, "at": new}), route={"kind": "task", "tasks": [TASK], "confidence": "high", "reports_doing": True, "chat_part": ""})
        said = await h.find(h.inbox, "Testa", "→")
        h.check(said is not None and new in said.text.lower(), f"the newest lines: {[each.text[:90] for each in await h.recent(h.inbox, 3)]}")
        states = await h.doses()
        h.check(states.get(("Testa", 2)) == DONE and states.get(("Testa", 3)) == PENDING, f"the doses are {states}")
        await no_marks(h, mine)
        h.saw(said.text[:110])

    async with h.step("1.22", "A question about my data: “what pills do I have left today?”", "The pills task answers (the checklist, or a line pointing at it); my message is left with no ⚠️", "fixture"):
        mine = await h.say("what pills do I have left today?", canned=("pill_today", {"guessed": [], "not_included": []}))
        await no_marks(h, mine)
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1 and await h.get(h.hub, sheets[0].message_id) is not None, "today's checklist is not in the hub afterwards")
        h.memo["sheet_d1"] = sheets[0].message_id

    async with h.step("1.23", "The clock is moved to 20 seconds before dose 3 falls due, and a card is left open: “add Otherpill once a day”", "A card with Save, not pressed (asked for now, so that it has not expired by the restart)", "T36 (36.1)"):
        due = await remind_due(h)
        h.check(due is not None, "no reminder is booked for dose 3")
        clock.advance_to(due - timedelta(seconds=25))
        h.memo["due3"] = due.isoformat()
        await h.say("add Otherpill to my pills once a day", canned=add({"name": "Otherpill", "per_day": 1}))
        stored, shown = await card(h)
        h.check(shown is not None and any("Save" in label for label in shown.labels), "no card with Save")
        h.memo["open_card"] = shown.id

    async with h.step("1.24", "The bot is cut off in the middle of answering a message, seconds before dose 3 falls due", "The process ends with my message still marked 👀 and its log row still “received”. Checked after the restart (2.01 to 2.05)", "asked; T38 (36.4)"):
        h.check(not await prompts(h), "dose 3's reminder is up already: the stop came too late")
        h.memo["caught_up_before"] = await h.count(h.botlog, CAUGHT_UP)
        h.cut_here = True
    if h.results[-1]["status"] == "pass":
        real = await h.inbox.send("what is the capital of France?")
        h.typed.add(real.id)
        h.memo["cut_message"] = real.id
        h.save()
        from selftest.discordside import Typed

        await h.main.on_message(Typed(real, h.owner))  # never returns: the process ends inside it
        await asyncio.sleep(10)
        os._exit(0)


# ---------------------------------------------------------------------------
# Start 2: after the cut-off
# ---------------------------------------------------------------------------
async def p2(h: Harness) -> None:
    async with h.step("2.01", "The catch-up after the restart is said once", "One new “🔁 Caught up after a restart” in #selftest-log. It says my message was cut off and that something ran late or was posted, and names no pill", "asked; T38 (36.4)"):
        cards_now = [each for each in await h.recent(h.botlog, 30) if CAUGHT_UP in each.all_text]
        h.check(len(cards_now) - h.memo.get("caught_up_before", 0) == 1, f"{len(cards_now) - h.memo.get('caught_up_before', 0)} new catch-up cards")
        said = cards_now[0].all_text
        h.check("cut off" in said, f"it does not mention the message that was cut off: {said[:300]}")
        h.check("Testa" not in said and "Testiron" not in said and "Testany" not in said, f"it names a pill: {said[:300]}")
        h.saw(" / ".join(line for line in said.splitlines()[1:4])[:260])
        h.check("pills remind" not in said and "pills/" not in said and "_" not in said, f"a job or an action is named the code's way: {said[:300]}")
        h.check("pill reminder" in said, f"the reminder that ran late is not called “pill reminder”: {said[:300]}")
        if "reminder" not in said.lower().replace("pills remind", ""):
            h.odd("The catch-up card does not say that a reminder was posted at start (the architecture notes say it is said once, with a count and no pill's name)")

    async with h.step("2.02", "The message that was cut off", "⚠️ in place of 👀 on it: it was never answered, so I say it again", "36 (restarts)"):
        mine = await h.get(h.inbox, h.memo.get("cut_message"))
        h.check(mine is not None, "the message has gone")
        h.check("⚠️" in mine.reactions and "👀" not in mine.reactions, f"its reactions are {mine.reactions}")

    async with h.step("2.03", "Dose 3's reminder fell due while the bot was off", "Exactly one reminder in the hub, posted once at start, with the neutral first line; not one for each minute missed", "asked; restarts"):
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None and shown.text.startswith(NEUTRAL) and "dose 3 of 3" in shown.text, f"the prompt reads: {shown.text[:200] if shown else 'gone'}")
        h.check(await h.count(h.hub, NEUTRAL) == 1, f"{await h.count(h.hub, NEUTRAL)} reminders are in the hub")
        h.memo["prompt"] = shown.id

    async with h.step("2.04", "The checklist after the restart", "The same message as before the stop, brought up to date in place: no second copy", "T37 (36.3)"):
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1 and sheets[0].message_id == h.memo.get("sheet_d1"), f"the checklist kept is {[each.message_id for each in sheets]}, before the stop {h.memo.get('sheet_d1')}")
        h.check(await h.get(h.hub, sheets[0].message_id) is not None, "it is not in the hub")

    async with h.step("2.04b", "The schedules after the restart", "The same three rows as before the stop (none made again), no run booked twice, and the 6:00 am checklist was not posted a second time", "scheduler stage 1"):
        made = sorted(f"{each.id}:{each.name}" for each in await h.schedules() if each.origin == "default")
        h.check(made == h.memo.get("schedules"), f"the schedules a task supplied are {made}, before the stop {h.memo.get('schedules')}")
        for task, kind in (("core", "nightly_backup"), ("core", "day_rollover"), ("pills", "checklist")):
            found = await h.runs(task, kind)
            keys = [each[2] for each in found]
            h.check(len(keys) == len(set(keys)), f"{task}/{kind} has a key twice: {keys}")
            # The checklist has two schedules by now: the 6:00 am one and the evening one added at 1.10c
            wanted = 2 if kind == "checklist" else 1
            h.check(len([each for each in found if each[0] == "pending"]) == wanted, f"{task}/{kind} is booked {len([each for each in found if each[0] == 'pending'])} times, not {wanted}")
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        h.check(len([each for each in await h.runs("pills", "checklist") if each[1] == f"{day_stamp}T06:00"]) == 1, "today's 6:00 am checklist has more than one run")

    async with h.step("2.05", "A card from before the restart: Save is pressed", "Otherpill is saved: the button still works and applies exactly what the card showed", "T37 (36.2)"):
        await h.press(h.memo["open_card"], "Save", h.inbox)
        h.check("Otherpill" in await h.pills(), f"the pills are {list(await h.pills())}")

    for number, minutes in ((1, 15), (2, 15), (3, 15)):
        async with h.step(f"2.0{5 + number}", f"Left alone, the reminder is posted again ({number} of 3)", f"A new message in place of the old, saying “reminder {number} of 3”; only ever one", "T44 (38.5)"):
            before = h.memo["prompt"]
            await h.clock_by(minutes=minutes, seconds=10)
            up = await prompts(h)
            h.check(len(up) == 1 and up[0].message_id and up[0].message_id != before, f"the prompt kept is {up[0].message_id if up else None}, before {before}")
            shown = await h.get(h.hub, up[0].message_id)
            h.check(shown is not None and f"reminder {number} of 3" in shown.text.lower(), f"it reads: {shown.text[:160] if shown else 'gone'}")
            h.check(await h.get(h.hub, before) is None and await h.count(h.hub, NEUTRAL) == 1, "the old copy is still in the hub")
            h.memo["prompt"] = up[0].message_id

    async with h.step("2.09", "After the third reminder the reminders stop, and the dose is still to take", "The reminder goes and no other is posted. The dose is not missed (it can still be taken today): the checklist still shows it to take, with no ❌", "T45 (38.6); asked 2026-10-14"):
        await h.clock_by(minutes=15, seconds=10)
        h.check(not [each for each in await prompts(h) if each.message_id] and await h.get(h.hub, h.memo["prompt"]) is None, "the reminder is still up")
        h.check(await h.count(h.hub, NEUTRAL) == 0, f"{await h.count(h.hub, NEUTRAL)} reminders are in the hub")
        h.check((await h.doses()).get(("Testa", 3)) == PENDING, f"the doses are {await h.doses()}")
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and "❌" not in sheet.text and "missed" not in sheet.text, f"the checklist reads: {sheet.text[:300] if sheet else 'gone'}")
        await h.clock_by(minutes=15, seconds=10)
        h.check(await h.count(h.hub, NEUTRAL) == 0, "a quarter of an hour on, a reminder was posted again")

    async with h.step("2.09b", "Half an hour before Testa's latest time: one last chance", "At 3:30 pm one more message, which notifies: “💊 Last chance today · take by 4:00 pm”, with no pill in that line; under it the pill, the dose and why. Taken, Taken at… and Skip, no Snooze. Only the one", "asked 2026-10-14"):
        await h.clock_to(15, 30, 5)
        up = [each for each in await prompts(h) if each.message_id]
        h.check(len(up) == 1, f"{len(up)} messages are up for a dose")
        shown = await h.get(h.hub, up[0].message_id) if up else None
        h.check(shown is not None and shown.text.startswith("💊 Last chance today · take by 4:00 pm"), f"it reads: {shown.text[:160] if shown else 'nothing'}")
        first = shown.text.splitlines()[0]
        h.check("Testa" not in first and "dose" not in first, f"its first line names the pill or the dose: {first}")
        h.check("Testa" in shown.text and "dose 3 of 3" in shown.text and "The last reminder for this dose" in shown.text, f"the rest reads: {shown.text[:300]}")
        h.check(not shown.silent, "it was posted silently: it would not notify")
        h.check(any("Taken" in label for label in shown.labels) and any("Skip" in label for label in shown.labels) and not any("Snooze" in label for label in shown.labels), f"its buttons are {shown.labels}")
        h.saw(first)
        await h.clock_by(minutes=15, seconds=5)
        h.check(len([each for each in await prompts(h) if each.message_id]) == 1 and await h.count(h.hub, "💊 Last chance today") == 1, "a quarter of an hour on there is not exactly one")
        h.memo["last_chance"] = up[0].message_id

    async with h.step("2.10", "Past Testa's latest time the dose is missed; logged as taken then: `took testa`", "At 4:00 pm dose 3 is missed. The typed shortcut, with no request to Claude, asks first: a card “Dose 3 was missed (due …). … Log it as taken now?” with Log it and Cancel; nothing is ticked off until Log it", "T45 (38.7); asked 2026-10-13"):
        if (config.now_nz().hour, config.now_nz().minute) < (16, 1):
            await h.clock_to(16, 1, 5)
        h.check(await h.get(h.hub, h.memo.get("last_chance")) is None, "the last-chance message is still up after 4:00 pm")
        before = h._real_calls
        mine = await h.say("took testa")
        stored, shown = await card(h)
        h.check(shown is not None, f"no card that asks: {[each.text[:80] for each in await h.recent(h.inbox, 3)]}")
        asked = next((line for line in shown.text.splitlines() if "⚠️" in line), "")
        h.check("Dose 3 was missed (due " in asked and asked.rstrip().endswith("Log it as taken now?"), f"the card asks: {asked.strip()[:140] or shown.text[:140]}")
        h.check(any("Log it" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        h.check((await h.doses()).get(("Testa", 3)) == MISSED, "the dose was ticked off before Log it")
        h.check(h._real_calls == before, "a request went to Claude")
        h.saw(asked.strip()[:120])
        await h.press(shown.id, "Log it", h.inbox)
        h.check((await h.doses()).get(("Testa", 3)) == DONE, f"after Log it the doses are {await h.doses()}")
        await no_marks(h, mine)

    async with h.step("2.10b", "8:00 pm: Discord takes Testiron's reminder and still answers that it failed", "The job does not fail and nothing is posted again at once. A minute later the hub is read first: the line that went through is found and the pill is written into it. One reminder in the hub, never two", "asked 2026-10-14"):
        door, lost = surface._door(), {}
        real = door.send_card

        async def goes_through_and_fails(channel_id, card, text, silent=False):
            message_id = await real(channel_id, card, text, silent=silent)
            if text.startswith(NEUTRAL) and not lost:
                lost["id"] = message_id
                raise surface.Failed("503 Service Unavailable (the self-test's own: the post went through)")
            return message_id

        door.send_card = goes_through_and_fails
        try:
            await h.clock_to(20, 0, 5)
            up = await prompts(h)
            h.check(bool(lost), "the reminder was never posted")
            h.check(len(up) == 1 and up[0].attempts == 1 and up[0].message_id is None, f"what is kept: {[(each.message_id, each.attempts) for each in up]}")
            h.check(("pills", "remind", "failed") not in await scheduler.troubled(), "the reminders' job is recorded as failed")
            h.check((await h.doses()).get(("Testiron", 1)) == PENDING, f"the doses are {await h.doses()}")
            bare = await h.get(h.hub, lost.get("id"))
            h.check(bare is not None and bare.text.strip() == NEUTRAL + "8:00 pm", f"in the hub: {bare.text[:120] if bare else 'nothing'}")
            await h.clock_by(minutes=1, seconds=2)
        finally:
            door.send_card = real
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id == lost.get("id") and up[0].attempts == 0, f"what is kept: {[(each.message_id, each.attempts) for each in up]}, the line that went through is {lost.get('id')}")
        h.check(await h.count(h.hub, NEUTRAL) == 1, f"{await h.count(h.hub, NEUTRAL)} reminders are in the hub")
        shown = await h.get(h.hub, lost.get("id"))
        h.check(shown is not None and "Testiron" in shown.text and any("Taken" in label for label in shown.labels), f"it reads: {shown.text[:160] if shown else 'gone'}")

    async with h.step("2.11", "Testiron's reminder, and Skip", "A reminder for Testiron; Skip takes it down and the dose is skipped", "38"):
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None and "Testiron" in shown.text, f"it reads: {shown.text[:160] if shown else 'gone'}")
        await h.press(shown.id, "Skip")
        h.check(not await prompts(h) and (await h.doses()).get(("Testiron", 1)) == SKIPPED, f"the doses are {await h.doses()}")

    async with h.step("2.11b", "The schedule I added ran at the time I moved it to", "One run of the checklist for 6:30 pm, done, and none for 6:00 pm; the hub still has one checklist for the day (it was brought up to date, not posted again)", "scheduler stage 2"):
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        found = await h.runs("pills", "checklist")
        h.check([each[0] for each in found if each[1] == f"{day_stamp}T18:30"] == ["done"], f"the runs for 6:30 pm: {[each for each in found if each[1] and each[1].startswith(day_stamp)]}")
        h.check(not [each for each in found if each[1] == f"{day_stamp}T18:00" and each[0] == "done"], "it also ran at 6:00 pm, the time it was moved from")
        h.check(len(await held(h, "checklist")) == 1, f"{len(await held(h, 'checklist'))} checklists are kept for today")

    async with h.step("2.12", "Midnight: the day is closed", "Nothing of yesterday is left open; Otherpill, never touched, is missed. Yesterday's checklist is written one last time and left in the hub (as the code does today; the clean-up spec changes this)", "pills 29; scheduler spec 18.2"):
        old = h.memo["sheet_d1"]
        await h.clock_to(0, 0, 30, day_offset=1)
        states = await h.doses(day_offset=-1)
        h.check(PENDING not in states.values(), f"yesterday still has open doses: {states}")
        h.check(states.get(("Otherpill", 1)) == MISSED, f"Otherpill is {states.get(('Otherpill', 1))}")
        left = await h.get(h.hub, old)
        h.check(left is not None and "Otherpill" in left.text, "yesterday's checklist has gone, or does not show Otherpill")
        h.saw("yesterday's checklist is still in the hub")
        h.odd("Yesterday's checklist stays in the hub after midnight and after the next morning's is posted. That is what the code does today; the clean-up spec replaces it")

    async with h.step("2.12b", "Just after midnight: “took otherpill last night at 11”", "Yesterday's missed dose is logged as taken at 11:00 pm, and the line says “yesterday”. (If the day had to be worked out from the time, it is asked first on a card: Log it)", "asked 2026-10-13 (stage 3)"):
        await h.say("took otherpill last night at 11", canned=log({"pill": "otherpill", "did": "taken", "at": "11:00", "day": "last_night"}))
        said = await h.find(h.inbox, "Otherpill", "yesterday")
        stored, asked = await card(h)
        if asked is not None and any("Log it" in label for label in asked.labels):
            h.odd("it was asked first on a card: the day was not handed over as said, and was worked out from the time")
            h.check("yesterday" in asked.text, f"the card reads: {asked.text[:200]}")
            await h.press(asked.id, "Log it", h.inbox)
            said = await h.get(h.inbox, asked.id)
        h.check(said is not None and "taken" in said.text and "11:00 pm" in said.text and "yesterday" in said.text, f"the line reads: {said.text[:200] if said else [each.text[:80] for each in await h.recent(h.inbox, 3)]}")
        states = await h.doses(day_offset=-1)
        h.check(states.get(("Otherpill", 1)) == DONE, f"yesterday's Otherpill is {states.get(('Otherpill', 1))}")
        h.check((await h.doses()).get(("Otherpill", 1)) == PENDING, f"today's Otherpill is {(await h.doses()).get(('Otherpill', 1))}")
        h.saw(said.text.splitlines()[0][:140])

    async with h.step("2.12c", "“what did I take yesterday?”", "A reply from the record: “Yesterday”, the date, the count, and a line a dose, with Otherpill taken at 11:00 pm", "asked 2026-10-13 (stage 4)"):
        await h.say("what did I take yesterday?", canned=("pill_history", {"period": "yesterday", "guessed": [], "not_included": []}))
        said = await h.find(h.inbox, "Yesterday", "taken")
        h.check(said is not None and "**Yesterday**" in said.text and " of " in said.text.splitlines()[0], f"the reply: {[each.text[:100] for each in await h.recent(h.inbox, 2) if each.id not in h.typed]}")
        h.check("Otherpill" in said.text and "11:00 pm" in said.text, f"it does not show last night's dose: {said.text[:300]}")
        h.saw(said.text.splitlines()[0][:140])

    async with h.step("2.12d", "“show my week”", "The week so far, a line a day up to today with a mark a dose, and the count for the week", "asked 2026-10-13 (stage 4)"):
        await h.say("show my week", canned=("pill_history", {"period": "week", "guessed": [], "not_included": []}))
        said = await h.find(h.inbox, "This week")
        h.check(said is not None and " taken" in said.text.splitlines()[0], f"the reply: {[each.text[:100] for each in await h.recent(h.inbox, 2) if each.id not in h.typed]}")
        h.check(len(said.text.splitlines()) >= 2 and any(mark in said.text for mark in ("✅", "❌")), f"no line for a day: {said.text[:300]}")
        h.saw(" / ".join(said.text.splitlines()[:3])[:200])

    async with h.step("2.13", "6:00 am the next day: a fresh checklist", "A new message for the new day with every dose still to take; one checklist for today", "asked; 23"):
        await h.clock_to(6, 0, 5)
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1 and sheets[0].message_id != h.memo["sheet_d1"], f"today's checklists: {[each.message_id for each in sheets]}")
        shown = await h.get(h.hub, sheets[0].message_id)
        h.check(shown is not None and all(name in shown.text for name in ("Testa", "Testany", "Testiron", "Otherpill")), f"it reads: {shown.text[:300] if shown else 'gone'}")
        states = await h.doses()
        h.check(states and set(states.values()) == {PENDING}, f"today's doses are {states}")
        h.memo["sheet_d2"] = shown.id

    async with h.step("2.14", "Left for the next start, in the old look: an open change card and a reminder", "A change card “dose · … → 2 tablets” with Save, and at 8:00 am a reminder for Testa", "asked: switching looks"):
        await h.clock_to(8, 0, 5)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        h.memo["plain_prompt"] = up[0].message_id
        await h.say("testa is 2 tablets now", canned=about("pill_edit", {"pill": "Testa", "dose": "2 tablets"}))
        stored, shown = await card(h)
        h.check(shown is not None and "2 tablets" in shown.text and "→" in shown.text and not shown.v2, f"the card: {shown.text[:200] if shown else 'none'}")
        h.memo["plain_card"] = shown.id
        h.memo["caught_up_before"] = await h.count(h.botlog, CAUGHT_UP)


# ---------------------------------------------------------------------------
# Start 3: the new look
# ---------------------------------------------------------------------------
def accent(status: str) -> int:
    return design.COLOURS[design.ACCENTS[status]]


async def p3(h: Harness) -> None:
    async with h.step("3.01", "A clean restart with CARDS_V2 on", "No new catch-up card about pills or a checklist (one naming only `tidy` is all right), and no second checklist", "T39 (36.5)"):
        new = [each for each in await h.recent(h.botlog, 30) if CAUGHT_UP in each.all_text][: max(0, await h.count(h.botlog, CAUGHT_UP) - h.memo.get("caught_up_before", 0))]
        h.check(not any("checklist" in each.all_text or "pill" in each.all_text.lower() for each in new), f"a catch-up card: {[each.all_text[:200] for each in new]}")
        h.check(len(await held(h, "checklist")) == 1, "more than one checklist is kept for today")
        h.check(config.CARDS_V2, "CARDS_V2 is not on")

    async with h.step("3.02", "An old-look reminder, Snooze pressed with the new look on", "Discord accepts the edit: the same message now says “Snoozed until …”", "asked: switching looks"):
        pressed = await h.press(h.memo["plain_prompt"], "Snooze")
        shown = await h.get(h.hub, h.memo["plain_prompt"])
        h.check(shown is not None and "Snoozed until" in shown.text, f"after Snooze: {shown.text[:200] if shown else 'gone'}; said {pressed.said}")
        h.saw(f"the message is {'Components V2' if shown.v2 else 'plain'} afterwards")

    async with h.step("3.03", "An old-look card, Save pressed with the new look on", "Discord accepts the edit: the card becomes its confirmation and Testa's dose is 2 tablets", "asked: switching looks"):
        pressed = await h.press(h.memo["plain_card"], "Save", h.inbox)
        shown = await h.get(h.inbox, h.memo["plain_card"])
        pill = (await h.pills()).get("Testa")
        h.check(pill is not None and "2 tablets" in str(pill.plan.dose), f"Testa's dose is {pill.plan.dose if pill else None}; the press said {pressed.said}")
        h.check(shown is not None and not shown.buttons, f"the card after Save: {shown.text[:160] if shown else 'gone'} with {shown.labels if shown else []}")
        h.saw(f"the message is {'Components V2' if shown.v2 else 'plain'} afterwards")
        if not shown.v2:
            h.odd("A card posted in the old look and saved with CARDS_V2 on stays a plain message: its confirmation is not drawn the new way. Harmless, but the two looks sit side by side after a switch")

    async with h.step("3.04", "The old-look checklist, rewritten with the new look on (`took testany`)", "The checklist kept for today shows Testany taken. Either the same message turned into the new look in place, or it was replaced by one message: never two", "asked: switching looks"):
        before = h.memo["sheet_d2"]
        await h.say("took testany")
        h.check((await h.doses()).get(("Testany", 1)) == DONE, f"the doses are {await h.doses()}")
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1, f"{len(sheets)} checklists are kept")
        shown = await h.get(h.hub, sheets[0].message_id)
        h.check(shown is not None and "Testany" in shown.text, "the checklist is not in the hub")
        same = sheets[0].message_id == before
        h.check(same or await h.get(h.hub, before) is None, "the old checklist was left beside the new one")
        h.memo["sheet_d2"] = shown.id
        h.saw(f"{'the same message, edited' if same else 'a new message in its place'}; it is {'Components V2' if shown.v2 else 'plain'}")

    async with h.step("3.05", "`pills` with the new look on", "One message: “💊 Today · Thu 15 Oct”, then one box: “### 💊 Pills” with dots and a count, a pill an item, Testany (taken) in the small line at the bottom, and no separate message for a dose with no time", "T51 (41.3)"):
        await h.say("pills")
        sheets = await held(h, "checklist")
        shown = await h.get(h.hub, sheets[-1].message_id) if sheets else None
        h.check(shown is not None and shown.v2, f"the fresh checklist is {'plain' if shown else 'missing'}")
        h.check("💊 Today · " in shown.text and "### 💊 Pills " in shown.text and "/" in shown.text, f"its heading: {shown.text.splitlines()[:2]}")
        allowed = {accent(status) for status in design.ACCENTS}
        h.check(shown.accents and set(shown.accents) <= allowed, f"its box colours are {[hex(each) if each else None for each in shown.accents]}")
        h.check(len(shown.accents) == 1 and "✅ Testany" in shown.text, f"one box, Testany in its small line: {shown.accents} {shown.text[-200:]}")
        h.check(not await held(h, "dose"), f"{len(await held(h, 'dose'))} separate dose messages are kept with the new look on")
        h.memo["sheet_d2"] = shown.id
        h.saw(shown.text.splitlines()[0] + " · boxes " + ", ".join(hex(each) for each in shown.accents if each))

    async with h.step("3.06", "Taken is pressed in Testa's box on the checklist", "The checklist stays and is rewritten in place: dose 1 has ✅; the reminder for it goes", "T53 (41.5)"):
        pressed = await h.press(h.memo["sheet_d2"], "Taken", arg=await dose_id(h, "Testa", 1))
        shown = await h.get(h.hub, h.memo["sheet_d2"])
        h.check((await h.doses()).get(("Testa", 1)) == DONE, f"the doses are {await h.doses()}; the press said {pressed.said}")
        h.check(shown is not None and shown.v2, "the checklist has gone, or is no longer drawn")
        h.check("✅" in next((part for part in shown.text.split("**Testa**")[1:]), "")[:160], f"Testa's box reads: {shown.text.split('**Testa**')[-1][:160]}")
        h.check(len(await held(h, "checklist")) == 1, "a second checklist was posted")
        h.check(not await prompts(h) and await h.get(h.hub, h.memo["plain_prompt"]) is None, "the reminder for dose 1 is still up")

    async with h.step("3.07", "Taken pressed again in Testa's box: too soon", "An amber box “⚠️ You already logged dose 1 at … Add another dose?” with Log it and Cancel; nothing ticked off. Cancel", "T54 (41.6); asked 2026-10-14"):
        pressed = await h.press(h.memo["sheet_d2"], "Taken", arg=await dose_id(h, "Testa", 2))
        asked = await h.find(h.hub, "Add another dose?") or await h.find(h.inbox, "Add another dose?")
        h.check(asked is not None, f"no card that asks; the press said {pressed.said}")
        h.check((await h.doses()).get(("Testa", 2)) == PENDING, "dose 2 was ticked off without asking")
        h.check(asked.v2 and asked.accents[:1] == [accent(design.RISKY)], f"it is {'drawn' if asked.v2 else 'plain'} with colours {[hex(each) if each else None for each in asked.accents]}")
        where = h.hub if await h.get(h.hub, asked.id) is not None else h.inbox
        await h.press(asked.id, "Cancel", where)
        h.check((await h.doses()).get(("Testa", 2)) == PENDING, "after Cancel the dose changed")
        sheet = await h.get(h.hub, h.memo["sheet_d2"])
        h.check(sheet is not None and "Today" in sheet.text, "the checklist was lost to the card that asked")

    async with h.step("3.08", "Skip is pressed in Otherpill's box", "Its box turns grey and says skipped, with no buttons for it", "T55 (41.7)"):
        which = await dose_id(h, "Otherpill", 1)
        await h.press(h.memo["sheet_d2"], "Skip", arg=which)
        shown = await h.get(h.hub, h.memo["sheet_d2"])
        h.check((await h.doses()).get(("Otherpill", 1)) == SKIPPED, f"the doses are {await h.doses()}")
        h.check(shown is not None and "skipped" in shown.text and not any(custom_id.endswith(f":{which}") for _, custom_id in shown.buttons), "the checklist does not show it skipped, or still offers its buttons")

    async with h.step("3.09", "A question card in the new look: “add Testb to my pills at 8”", "A blurple box ending with the question, a button an answer and Cancel, no Save. The answer rewrites it in place with Save. Cancel removes it", "T50 (41.2)"):
        await h.say("add Testb to my pills at 8", canned=add({"name": "Testb", "times": ["8:00"]}, guessed=["times[0]"]))
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2, f"the card is {'plain' if shown else 'missing'}")
        h.check(shown.accents[:1] == [accent(design.DECISION)], f"its colour is {[hex(each) if each else None for each in shown.accents]}")
        h.check("8:00 pm" in " ".join(shown.labels) and not any("Save" in label for label in shown.labels), f"its buttons are {shown.labels}")
        pressed = await h.press(shown.id, "8:00 pm", h.inbox)
        after = await h.get(h.inbox, shown.id)
        h.check(after is not None and after.v2 and any("Save" in label for label in after.labels) and pressed.edits >= 1, f"after the answer: {after.labels if after else 'gone'}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check("Testb" not in await h.pills() and (await card(h))[0] is None, "Testb was saved, or the card is still open")

    async with h.step("3.10", "A remove card in the new look: “remove otherpill”, then Remove", "A box with a red Remove; after it Otherpill is gone", "T57 (41.8)"):
        await h.say("remove otherpill", canned=about("pill_remove", {"pill": "Otherpill"}))
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2 and any("Remove" in label for label in shown.labels), f"the card: {shown.text[:160] if shown else 'none'} with {shown.labels if shown else []}")
        h.saw("box colour " + ", ".join(hex(each) for each in shown.accents if each))
        await h.press(shown.id, "Remove", h.inbox)
        h.check("Otherpill" not in await h.pills(), "Otherpill is still there")

    async with h.step("3.10b", "A pill with no time is added with the new look on: “add Testlate once a day”", "After Save the drawn checklist gains Testlate, any time, with its buttons, in place; no separate message for it", "T51 (41.3)"):
        await h.say("add Testlate to my pills once a day", canned=add({"name": "Testlate", "per_day": 1}))
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2, "no drawn card")
        await h.press(shown.id, "Save", h.inbox)
        await h.settle(2)
        sheet = await h.get(h.hub, h.memo["sheet_d2"])
        h.check(sheet is not None and "Testlate" in sheet.text and "any time" in sheet.text, f"the checklist: {sheet.text[-300:] if sheet else 'gone'}")
        h.check(len(sheet.accents) == 1 and sheet.accents[0] in (accent(design.DUE), accent(design.ANY_TIME)), f"one box, amber or blue: {[hex(each) if each else None for each in sheet.accents]}")
        h.check(not await held(h, "dose"), "a separate dose message was posted")

    async with h.step("3.11", "A reminder in the new look", "When dose 2 falls due: posted as the one neutral line and drawn after (an edit), an amber box naming Testa, four buttons. Left up for the next start", "T52 (41.4)"):
        due = await remind_due(h)
        h.check(due is not None, "no reminder is booked")
        await h.clock_at(due)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None and shown.text.startswith(NEUTRAL) and "Testa" not in shown.text.splitlines()[0], f"it reads: {shown.text[:160] if shown else 'gone'}")
        h.check(shown.v2 and shown.edited and accent(design.DUE) in shown.accents, f"it is {'drawn' if shown.v2 else 'plain'}, {'edited' if shown.edited else 'never edited'}, colours {[hex(each) if each else None for each in shown.accents]}")
        h.check("Testa" in shown.text and len(shown.buttons) == 4, f"its buttons are {shown.labels}")
        h.memo["v2_prompt"] = shown.id

    async with h.step("3.12", "Left for the next start, in the new look: an open change card", "A blurple change card “dose · 2 tablets → 3 tablets” with Save", "asked: switching back"):
        await h.say("testa is 3 tablets now", canned=about("pill_edit", {"pill": "Testa", "dose": "3 tablets"}))
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2 and "3 tablets" in shown.text and "→" in shown.text, f"the card: {shown.text[:200] if shown else 'none'}")
        h.memo["v2_card"] = shown.id

    async with h.step("3.13", "The reset card in the new look: `reset channel`, then Cancel", "A red box (Components V2) with the channel under the heading, the count, that it can't be undone, and a red Delete all inside it; Cancel removes it and deletes nothing", "39.4; self-test of 2026-10-13, fix 5"):
        count = len(await h.recent(h.inbox, 50))
        await h.say("reset channel")
        shown = await h.find(h.inbox, "can't be undone")
        h.check(shown is not None and any("Delete all" in label for label in shown.labels), f"no reset card: {[each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        h.saw(f"{'drawn' if shown.v2 else 'plain'}, colours {[hex(each) if each else None for each in shown.accents]}")
        h.check(shown.v2 and shown.accents[:1] == [accent(design.DESTRUCTIVE)], f"it is {'drawn' if shown.v2 else 'plain'} with colours {[hex(each) if each else None for each in shown.accents]}")
        h.check("## 🧹 Channel · reset" in shown.text and "messages**" in shown.text, f"it reads: {shown.text[:200]}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check(await h.get(h.inbox, shown.id) is None, "the card is still there after Cancel")
        h.check(len(await h.recent(h.inbox, 50)) >= count - 1, "messages were deleted")

    async with h.step("3.13b", "`my schedule` in the new look", "One drawn message: the page title, one amber box (the next to run is in it) with a rule between schedules, and no buttons", "scheduler stage 2 (schedule-list-v2)"):
        await h.say("my schedule")
        shown = await h.find(h.inbox, "My schedule")
        h.check(shown is not None and shown.v2 and not shown.buttons, f"the list is {'plain' if shown and not shown.v2 else 'missing' if shown is None else 'drawn with buttons'}")
        h.check("**Pills checklist**" in shown.text and "**Evening pills checklist**" in shown.text, f"it lists: {shown.text[:400]}")
        h.check(shown.accents == [accent(design.DUE)], f"its colours are {[hex(each) if each else None for each in shown.accents]}")
        h.memo["schedule_list"] = shown.id

    async with h.step("3.13b2", "The lists that were plain, in the new look: `my pills`, “show my week”, `bugs`", "Each is one drawn message (Components V2) with the same words: a page title, one box with a rule between items (a pill; a day of the week; “No open bugs.”), and no buttons", "stage 5 (2026-10-13)"):
        await h.say("my pills", canned=("pill_list", {"guessed": [], "not_included": []}))
        listed = await h.find(h.inbox, "💊 Pills", "in use")
        h.check(listed is not None and listed.v2 and not listed.buttons and "Testa" in listed.text and "Testany" in listed.text, f"my pills: {(listed.v2, listed.text[:200]) if listed else [each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        h.check(set(listed.accents) <= {accent(design.QUIET)}, f"its boxes' colours: {[hex(each) if each else None for each in listed.accents]}")
        await h.say("show my week", canned=("pill_history", {"period": "week", "guessed": [], "not_included": []}))
        week = await h.find(h.inbox, "This week")
        h.check(week is not None and week.v2 and not week.buttons and " taken" in week.text.splitlines()[0], f"the week: {(week.v2, week.text[:200]) if week else 'nothing'}")
        h.check(set(week.accents) <= {accent(status) for status in (design.DONE, design.MISSED, design.ANY_TIME, design.QUIET)}, f"its boxes' colours: {[hex(each) if each else None for each in week.accents]}")
        await h.say("bugs")
        bugs = await h.find(h.inbox, "Open bugs")
        h.check(bugs is not None and bugs.v2 and not bugs.buttons, f"bugs: {(bugs.v2, bugs.text[:120]) if bugs else [each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        h.saw(f"{listed.text.splitlines()[0]} / {week.text.splitlines()[0]} / {bugs.text.splitlines()[0]}"[:200])

    async with h.step("3.13c", "Days and notify: “make the evening checklist notify, and only on weekdays”, then Save", "A blurple change card with `days · every day → Mon to Fri` and `notify · silent → notifies`; after Save the schedule is so", "scheduler stage 2 (schedule-change-v1)"):
        await h.say("make the evening checklist notify, and only on weekdays", canned=scheduled("schedule_change", {"schedule": "evening checklist", "notify": "notify", "days": ["mon", "tue", "wed", "thu", "fri"], "days_change": "set"}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2 and shown.accents[:1] == [accent(design.DECISION)], f"the card is {'plain' if shown and not shown.v2 else 'missing' if shown is None else 'drawn'}")
        h.check("days · ~~every day~~ → **Mon to Fri**" in shown.text and "notify · ~~silent~~ → **notifies**" in shown.text, f"the card: {shown.text[:300]}")
        await h.press(shown.id, "Save", h.inbox)
        made = await schedule_named(h, "Evening pills checklist")
        h.check(made is not None and made.days == (0, 1, 2, 3, 4) and made.notify == "notify", f"the schedule is {made}")

    async with h.step("3.13d", "Pause and resume: “pause the evening checklist”, Save; then “turn the evening checklist back on”, Save", "`paused · no → until you turn it back on`, and nothing is booked for it while paused; then `paused · … → on` and its next run is booked again", "scheduler stage 2"):
        await h.say("pause the evening checklist", canned=scheduled("schedule_change", {"schedule": "evening checklist", "paused": "pause"}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and "paused · ~~no~~ → **until you turn it back on**" in shown.text and "not while it is paused" in shown.text, f"the card: {shown.text[:300] if shown else 'none'}")
        await h.press(shown.id, "Save", h.inbox)
        made = await schedule_named(h, "Evening pills checklist")
        waiting = [each for each in await h.runs("pills", "checklist") if each[0] == "pending" and each[2].startswith(f"s{made.id}@")]
        h.check(made.state == "paused" and not waiting, f"it is {made.state} with {waiting} booked")
        await h.settle(2)
        listed = await h.get(h.inbox, h.memo["schedule_list"])
        h.check(listed is not None and "Paused" in listed.text, "the list does not show it paused")
        await h.say("turn the evening checklist back on", canned=scheduled("schedule_change", {"schedule": "evening checklist", "paused": "resume"}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and "→ **on**" in shown.text, f"the card: {shown.text[:300] if shown else 'none'}")
        await h.press(shown.id, "Save", h.inbox)
        made = await schedule_named(h, "Evening pills checklist")
        waiting = [each for each in await h.runs("pills", "checklist") if each[0] == "pending" and each[2].startswith(f"s{made.id}@")]
        h.check(made.state == "on" and len(waiting) == 1, f"it is {made.state} with {waiting} booked")

    async with h.step("3.13e", "Remove: “remove the evening checklist”, then Remove", "A card `… → removed` with a red Remove; after it the schedule is gone from the list, nothing is booked for it, and the 6:00 am one is untouched", "scheduler stage 2"):
        await h.say("remove the evening checklist", canned=scheduled("schedule_remove", {"schedule": "evening checklist"}), task="schedule")
        stored, shown = await card(h)
        h.check(shown is not None and "→ **removed**" in shown.text and any("Remove" in label for label in shown.labels), f"the card: {shown.text[:300] if shown else 'none'} with {shown.labels if shown else []}")
        await h.press(shown.id, "Remove", h.inbox)
        h.check(await schedule_named(h, "Evening pills checklist") is None, "it is still there")
        left = await schedule_named(h, "Pills checklist")
        h.check(left is not None and f"{left.at:%H:%M}" == "06:00" and left.state == "on", f"Pills checklist is {left}")
        h.check(len([each for each in await h.runs("pills", "checklist") if each[0] == "pending"]) == 1, "the runs booked are not just the 6:00 am one")
        await h.settle(2)
        listed = await h.get(h.inbox, h.memo["schedule_list"])
        h.check(listed is not None and "Evening pills checklist" not in listed.text, "the list still shows it")

    from tasks.dev import mock

    refused, posted = [], []
    async with h.step("3.14", f"Every sketch in docs/mockups ({len(mock.names())}) posted with `dev mock`", "Discord accepts each one as a Components V2 message (the reminder's first line alone is plain text)", "T2 to T10, block 44"):
        for name in mock.names():
            before = {each.id for each in await h.recent(h.inbox, 6)}
            await h.say(f"dev mock {name}", wait=0.6)
            new = [each for each in await h.recent(h.inbox, 6) if each.id not in before and each.id not in h.typed]
            if not new or any(each.text.startswith("⚠️") for each in new):
                refused.append(f"{name}: {new[0].text[:120] if new else 'nothing posted'}")
            else:
                posted.append(name)
        h.check(not refused, "; ".join(refused))
        h.saw(f"{len(posted)} posted")

    async with h.step("3.15", "The checklist sketch's colours", "Its boxes carry the values of core/design.py for amber, blue, green, red and grey (how they look is yours to judge)", "T4 (39.1)"):
        await h.say("dev mock checklist-v2", wait=0.6)
        shown = await h.find(h.inbox, "Pill A", "Pill B")
        h.check(shown is not None and shown.v2, "the sketch was not posted")
        wanted = {design.COLOURS[name] for name in ("amber", "blue", "green", "red", "grey")}
        h.check(wanted <= set(shown.accents), f"its colours are {[hex(each) if each else None for each in shown.accents]}")


# ---------------------------------------------------------------------------
# Start 4: back to the old look
# ---------------------------------------------------------------------------
async def p4(h: Harness) -> None:
    async with h.step("4.01", "A new-look reminder, Snooze pressed with the new look off", "Discord accepts the edit, and the message stays Components V2 (one can never go back to plain text): it now says “Snoozed until …”", "asked: switching back; T58"):
        h.check(not config.CARDS_V2, "CARDS_V2 is still on")
        pressed = await h.press(h.memo["v2_prompt"], "Snooze")
        shown = await h.get(h.hub, h.memo["v2_prompt"])
        h.check(shown is not None and "Snoozed until" in shown.text, f"after Snooze: {shown.text[:200] if shown else 'gone'}; said {pressed.said}")
        h.check(shown.v2, "the message is no longer Components V2")

    async with h.step("4.02", "A new-look card, Save pressed with the new look off", "Discord accepts the edit: the card becomes its confirmation and Testa's dose is 3 tablets", "asked: switching back"):
        pressed = await h.press(h.memo["v2_card"], "Save", h.inbox)
        pill = (await h.pills()).get("Testa")
        h.check(pill is not None and "3 tablets" in str(pill.plan.dose), f"Testa's dose is {pill.plan.dose if pill else None}; the press said {pressed.said}")
        shown = await h.get(h.inbox, h.memo["v2_card"])
        h.check(shown is not None and not shown.buttons and "Testa" in shown.text, f"the card after Save: {shown.text[:160] if shown else 'gone'} with {shown.labels if shown else []}")

    async with h.step("4.03", "The new-look checklist after a start with the new look off", "The same message, still Components V2 (it can never go back to plain text), now holding the old look's words; and the Taken / Skip message for Testlate (no time) is back under it", "asked: switching back"):
        sheets = await held(h, "checklist")
        h.check(len(sheets) == 1 and sheets[0].message_id == h.memo["sheet_d2"], f"the checklist kept is {[each.message_id for each in sheets]}, before the stop {h.memo['sheet_d2']}")
        shown = await h.get(h.hub, h.memo["sheet_d2"])
        h.check(shown is not None and shown.v2 and "Testlate" in shown.text, f"the checklist: {shown.text[:200] if shown else 'gone'}")
        singles = [await h.get(h.hub, each.message_id) for each in await held(h, "dose")]
        h.check(len(singles) == 1 and singles[0] is not None and "Testlate" in singles[0].text and not singles[0].v2, f"the single-dose messages: {[(each.text[:50], each.v2) if each else None for each in singles]}")
        h.saw(shown.text.splitlines()[0][:80])

    async with h.step("4.03b", "`took testlate` with the new look off, on the checklist that was drawn", "Discord accepts the edit of the Components V2 message from the old look's code: it shows Testlate taken, and Testlate's own message goes", "asked: switching back"):
        single = (await held(h, "dose"))[0].message_id
        await h.say("took testlate")
        shown = await h.get(h.hub, h.memo["sheet_d2"])
        h.check((await h.doses()).get(("Testlate", 1)) == DONE, f"the doses are {await h.doses()}")
        h.check(shown is not None and shown.v2 and len(await held(h, "checklist")) == 1, "the checklist was replaced, or is no longer Components V2")
        h.check("Testlate" in shown.text and "✅" in shown.text.split("Testlate")[0].splitlines()[-1] + shown.text.split("Testlate")[1][:60], f"it reads: {shown.text[-240:]}")
        h.check(await h.get(h.hub, single) is None, "Testlate's own message is still there")

    async with h.step("4.04", "`pills` with the new look off", "A fresh checklist in the old look (a plain message), in place of the drawn one", "T58 (41.8)"):
        old = h.memo["sheet_d2"]
        await h.say("pills")
        sheets = await held(h, "checklist")
        shown = await h.get(h.hub, sheets[-1].message_id) if sheets else None
        h.check(shown is not None and shown.id != old and not shown.v2, f"the fresh checklist is {'drawn' if shown and shown.v2 else 'missing' if shown is None else 'the old message'}")
        h.check(await h.get(h.hub, old) is None and len(sheets) == 1, "the drawn checklist is still there")
        h.saw(shown.text.splitlines()[0][:80])

    async with h.step("4.05", "A new card with the new look off: “add Testlast once a day”, then Cancel", "A plain card with Save and Cancel; Cancel removes it", "T58 (41.8)"):
        await h.say("add Testlast to my pills once a day", canned=add({"name": "Testlast", "per_day": 1}))
        stored, shown = await card(h)
        h.check(shown is not None and not shown.v2 and any("Save" in label for label in shown.labels), f"the card is {'drawn' if shown and shown.v2 else 'missing' if shown is None else 'plain with ' + str(shown.labels)}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check("Testlast" not in await h.pills(), "Testlast was saved")

    async with h.step("4.05b", "The reset card with the new look off: `reset channel`, then Cancel", "A plain message with the same words and buttons; Cancel removes it", "T58; self-test of 2026-10-13, fix 5"):
        await h.say("reset channel")
        shown = await h.find(h.inbox, "can't be undone")
        h.check(shown is not None and not shown.v2 and any("Delete all" in label for label in shown.labels), f"the reset card is {'drawn' if shown and shown.v2 else 'missing' if shown is None else 'plain with ' + str(shown.labels)}")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check(await h.get(h.inbox, shown.id) is None, "the card is still there after Cancel")

    async with h.step("4.06", "`dev cost`", "Under Today a small line with what was spent against DAILY_SPEND_LIMIT_NZD, the limit of a tenth of a cent written as NZ$0.001, and which exchange rate is in use", "T35, T56 (42.1, 42.3)"):
        await h.say("dev cost")
        shown = await h.find(h.inbox, "limit")
        h.check(shown is not None, f"no line about the limit: {[each.text[:120] for each in await h.recent(h.inbox, 2)]}")
        line = next((line for line in shown.text.splitlines() if "limit" in line), "")
        h.saw(line[:120])
        h.check("NZ$0.001" in line, f"a limit under a cent is not shown to three places, in NZ$: {line.strip()[:90]}")
        h.check("US$1 = NZ$" in shown.text, "dev cost does not say which exchange rate is in use")

    spent = await h.spent()
    if spent > 0 and await h.can_ask_claude():
        async with h.step("4.07", "The spend line: two messages to Claude with the limit at US$0.001", "One “💰 Claude spend is over today's limit” in #selftest-log after the first, and no second one after the second", "T49, T50 (42.2, 42.3)"):
            await h.say("what pills do I have left today?", canned=("pill_today", {"guessed": [], "not_included": []}))
            first = await h.count(h.botlog, "over today's limit")
            await h.say("what pills do I have left today?", canned=("pill_today", {"guessed": [], "not_included": []}))
            second = await h.count(h.botlog, "over today's limit")
            h.check(first == 1 and second == 1, f"{first} card(s) after the first message, {second} after the second")
    else:
        h.skip("4.07", "The spend line in #bot-log when the limit is passed", "needs real requests to Claude with money left: run with --claude", "T49, T50 (42.2, 42.3)")

    async with h.step("4.07a", "The bot's own is not changed by words: “move the backup to 4am”", "One line saying the nightly backup is the bot's own and isn't changed here; no card, and it still runs at 3:00 am", "scheduler stage 2"):
        mine = await h.say("move the backup to 4am", canned=scheduled("schedule_change", {"schedule": "backup", "time": "4:00 am"}), task="schedule")
        said = await h.find(h.inbox, "the bot's own")
        h.check(said is not None and "Nightly backup" in said.text, f"it said: {[each.text[:100] for each in await h.recent(h.inbox, 2)]}")
        h.check((await card(h))[0] is None, "a card was opened")
        own = await schedule_named(h, "Nightly backup")
        h.check(own is not None and f"{own.at:%H:%M}" == "03:00", f"the backup is at {own.at if own else None}")

    async with h.step("4.07b", "`dev run backup`", "A handler run by hand, outside its schedule: “▶️ Ran: core.nightly_backup”, a second “Backup saved”, a run of its own in the log, and the night's backup still booked", "scheduler stage 1"):
        before = await h.count(h.botlog, "Backup saved")
        await h.say("dev run backup")
        said = await h.find(h.inbox, "Ran: core.nightly_backup")
        h.check(said is not None, f"`dev run backup` said: {[each.text[:80] for each in await h.recent(h.inbox, 2)]}")
        h.check(await h.count(h.botlog, "Backup saved") == before + 1, "no second “Backup saved” in #selftest-log")
        found = await h.runs("core", "nightly_backup")
        h.check(any(each[2] and each[2].startswith("manual:core.nightly_backup") and each[0] == "done" for each in found), f"no run of its own in the log: {found[-3:]}")
        h.check(len([each for each in found if each[0] == "pending"]) == 1, "the night's backup is no longer booked once")

    async with h.step("4.08", "`dev clock reset`", "The clock is the real time again, and the standing jobs are booked for the real day", "T57"):
        await h.say("dev clock reset")
        h.check(not clock.is_shifted(), "the clock is still moved")
        jobs = await scheduler.all_pending()
        late = [job for job in jobs if job.kind in ("day_rollover", "nightly_backup", "checklist") and job.due_at - clock.now() > timedelta(hours=25)]
        h.check(not late, f"jobs booked more than a day ahead: {[(job.task, job.kind, job.due_at.isoformat()) for job in late]}")
        booked = {job.kind for job in jobs if job.schedule_id is not None}
        h.check({"day_rollover", "nightly_backup", "checklist"} <= booked, f"after the clock went back only these are booked from a schedule: {sorted(booked)}")
        real_today = f"{config.real_now_nz():%Y-%m-%d}"
        sheet = next(job for job in jobs if job.kind == "checklist")
        h.check(sheet.local_at and sheet.local_at[:10] >= real_today and sheet.due_at > clock.now(), f"the checklist is booked for {sheet.local_at}")
        h.saw(f"checklist booked for {sheet.local_at}")


# ---------------------------------------------------------------------------
# Start 5: the briefing switched on (the clock is the real time again)
# ---------------------------------------------------------------------------
# What only the real briefing says (the sketches posted at 3.14 say "☀️ Today" too)
BRIEFING = "tick things off on their own message"


def pills_count(text: str) -> tuple[int, int] | None:
    """The pills box's count in the briefing, as its card title says it: "### 💊 Pills ●○○ 1/3" is (1, 3)."""
    import re

    found = re.search(r"### 💊 Pills [●○]+ (\d+)/(\d+)", text or "")
    return (int(found[1]), int(found[2])) if found else None


async def briefing_in_hub(h: Harness):
    """The briefing the bot keeps for the hub, as Discord has it."""
    from core import livelists

    placed = await database.run(livelists.db_get, h.user.id, "briefing:hub")
    return await h.get(h.hub, placed.message_id) if placed is not None else None


async def seed(h: Harness) -> None:
    """The pills the story has by now, for a run that begins here (the day
    stage was not run). Recorded answers only: nothing here is being tested
    for the first time, so no request is paid for."""
    h.recorded_only = True
    try:
        await save_new(
            h, "0.01", "add Testa to my pills at 8am, 11am and 2pm, at least 3 hours apart, not after 4pm, with food",
            add({"name": "Testa", "per_day": 3, "times": ["8:00 am", "11:00 am", "2:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm", "notes": "with food"}),
            "Testa", "set up for a run without the day stage",
        )
        await save_new(h, "0.02", "add Testany to my pills once a day", add({"name": "Testany", "per_day": 1}), "Testany", "set up")
        await save_new(h, "0.03", "add Testiron to my pills at 8pm", add({"name": "Testiron", "times": ["8:00 pm"]}), "Testiron", "set up")
        await save_new(h, "0.04", "add Testlate to my pills once a day", add({"name": "Testlate", "per_day": 1}), "Testlate", "set up")
    finally:
        h.recorded_only = False
    h.memo["began_here"] = True


async def p5(h: Harness) -> None:
    if "sheet_d2" not in h.memo:  # the day stage leaves it; without it this is where the run begins
        await seed(h)

    async with h.step("5.01", "A start with BRIEFING_ENABLED on", "The 6:00 am schedule is the same row, now called Morning routine, with two steps: the briefing, then the pills checklist; both are booked for the next 6:00 am", "scheduler stage 3"):
        h.check(config.BRIEFING_ENABLED, "BRIEFING_ENABLED is not on")
        routine = await schedule_named(h, "Morning routine")
        h.check(routine is not None and routine.steps == ("briefing.post", "pills.checklist") and f"{routine.at:%H:%M}" == "06:00", f"the schedules are {[(each.name, each.steps) for each in await h.schedules()]}")
        h.check(await schedule_named(h, "Pills checklist") is None, "there is still a schedule called Pills checklist beside it")
        for task, kind, step in (("briefing", "post", 1), ("pills", "checklist", 2)):
            waiting = [each for each in await h.runs(task, kind) if each[0] == "pending" and each[2].startswith(f"s{routine.id}@")]
            h.check(len(waiting) == 1 and waiting[0][2].endswith(f"#{step}"), f"{task}/{kind} booked: {waiting}")
        h.memo["routine"] = routine.id

    async with h.step("5.01b", "A fresh day, 9:00 am: the morning routine ran at 6:00 on the way", "One briefing in the hub and the checklist under it, both without a notification; the routine's two steps each ran once for 6:00 am, the briefing first; it has the line about yesterday", "scheduler stage 3"):
        await h.clock_to(9, 0, day_offset=3)
        fresh = await briefing_in_hub(h)
        h.check(fresh is not None and "☀️ Today" in fresh.text and await h.count(h.hub, BRIEFING) == 1, f"{await h.count(h.hub, BRIEFING)} briefings in the hub")
        sheet = await sheet_id(h)
        h.check(sheet is not None and sheet > fresh.id, f"the checklist ({sheet}) is not under the briefing ({fresh.id})")
        h.check(fresh.silent, "the briefing was posted with a notification")
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        # Only the runs that were done: one booked for this morning days ago, on the moved clock, and taken out since is still in the log
        done = [each[2].split("~")[0][-2:] for each in [*await h.runs("briefing", "post"), *await h.runs("pills", "checklist")] if each[1] == f"{day_stamp}T06:00" and each[0] == "done"]
        h.check(done == ["#1", "#2"], f"the routine's runs done for 6:00 am: {done}")
        if h.memo.get("began_here"):
            # The clock has just gone three days on from an empty story: nothing was to take the day
            # before, so there is no line (5.07 is where it is looked at: the day after a real one)
            h.check("Yesterday: " not in fresh.text, f"a line about a day nothing was recorded on: {fresh.text[:400]}")
        else:
            h.check("Yesterday: " in fresh.text, f"no line about yesterday: {fresh.text[:400]}")
        h.memo["briefing_hub"] = fresh.id
        h.saw(" / ".join(line for line in fresh.text.splitlines() if "Pills" in line or "Yesterday" in line)[:200])

    async with h.step("5.01c", "Weather in the briefing, from a recorded forecast", "With WEATHER_ENABLED on: two schedules of its own, Weather fetch at 5:50 am and Weather refresh at 8:50 am; the briefing has a Weather section with the low and high, the sky, the rain and the wind, read from what was fetched (the network is never asked: WEATHER_SOURCE is a recorded forecast)", "item 7"):
        h.check(config.WEATHER_ENABLED and bool(config.WEATHER_SOURCE), "WEATHER_ENABLED is not on, or there is no recorded forecast to read")
        fetch, refresh = await schedule_named(h, "Weather fetch"), await schedule_named(h, "Weather refresh")
        h.check(fetch is not None and refresh is not None and f"{fetch.at:%H:%M}" == "05:50" and f"{refresh.at:%H:%M}" == "08:50", f"the schedules are {[each.name for each in await h.schedules()]}")
        fresh = await briefing_in_hub(h)
        said = fresh.all_text if fresh is not None else ""
        h.saw(next((line for line in said.splitlines() if "Weather" in line), "no Weather line")[:120])
        h.check("### 🌤️ Weather\n14° to 20° · drizzle" in said and "61% rain after 1pm · wind 15 km/h N" in said, f"the briefing: {said[:400]}")
        ran = [each for each in await h.runs("weather", "fetch") if each[0] == "done"]
        h.check(len(ran) >= 1, f"the 5:50 am fetch did not run: {await h.runs('weather', 'fetch')}")

    async with h.step("5.02", "`brief me` in #selftest-inbox", "With no request to Claude, a copy there: “☀️ Today”, the date, a Pills box (### 💊 Pills, its dots and count) with the next dose; drawn, in the colour of its status, with no buttons", "scheduler stage 3 (briefing-v2)"):
        before = h._real_calls
        await h.say("brief me")
        shown = await h.find(h.inbox, BRIEFING)
        h.check(shown is not None and "☀️ Today" in shown.text and pills_count(shown.text) is not None, f"the briefing: {shown.text[:300] if shown else 'nothing'}")
        h.check(f"{config.now_nz():%A} {config.now_nz().day} {config.now_nz():%B}" in shown.text and "as of" not in shown.text, f"its date line: {shown.text.splitlines()[:2]}")
        h.check(shown.v2 and not shown.buttons and set(shown.accents) <= {accent(status) for status in design.ACCENTS}, f"drawn: {shown.v2}, buttons {shown.labels}, colours {[hex(each) if each else None for each in shown.accents]}")
        h.check(h._real_calls == before, "a request went to Claude")
        h.memo["briefing_inbox"] = shown.id
        h.saw(" / ".join(shown.text.splitlines()[2:4])[:160])

    async with h.step("5.03", "`brief me` in the hub", "Nothing new is posted: the briefing that is there is brought up to date in place, and a line says so", "scheduler stage 3"):
        await h.say("brief me", channel=h.hub)
        again = await briefing_in_hub(h)
        h.check(again is not None and again.id == h.memo["briefing_hub"] and await h.count(h.hub, BRIEFING) == 1, f"{await h.count(h.hub, BRIEFING)} briefings in the hub")
        h.check(await h.find(h.hub, "The briefing above is up to date") is not None, "no line saying it is up to date")

    async with h.step("5.03b", "“what's on today?” in plain words", "The router sends it to the briefing, which answers with its card there; my message is left with no ⚠️", "scheduler stage 3"):
        mine = await h.say("what's on today?", canned=("briefing_show", {"guessed": [], "not_included": []}), task="briefing")
        await no_marks(h, mine)
        shown = await h.find(h.inbox, BRIEFING)
        h.check(shown is not None and shown.id != h.memo["briefing_inbox"], f"no briefing was posted in answer: {[each.text[:80] for each in await h.recent(h.inbox, 3) if each.id not in h.typed]}")

    async with h.step("5.03c", "“what's left today?” in plain words", "With DAY_QUESTIONS on, the briefing task answers in one message from the day's own data: “☀️ **Left today**”, the day's dots and count as the checklist counts them, then a line a dose still to take. No card, and my message is left with no ⚠️", "asked 2026-10-14 (questions about my day); golden 21"):
        from tasks.pills import checklist
        from tasks.pills import today as pills_today

        h.check(config.DAY_QUESTIONS, "DAY_QUESTIONS is not on in this start")
        mine = await h.say("what's left today?", canned=("day_left", {"guessed": [], "not_included": []}), task="briefing")
        await no_marks(h, mine)
        _, listed, _ = await checklist.view(h.user.id)
        done, total = pills_today.progress(listed)
        said = await h.find(h.inbox, "Left today")
        h.check(said is not None and f"☀️ **Left today** · {design.progress(done, total)}" in said.text, f"the answer: {said.text[:200] if said else 'nothing'}")
        left = pills_today.left_lines(listed)
        h.check(said is not None and all(f"💊 {line}" in said.text for line in left[:3]) and not said.buttons, f"not a line a dose still to take ({left[:3]}): {said.text[:300] if said else 'nothing'}")
        h.saw(said.text.splitlines()[0] if said else "nothing")

    async with h.step("5.03d", "“how did I go yesterday?” in plain words", "The briefing task answers from the record of that day: “☀️ **Yesterday**”, its date, its dots and count, and the pills task's own line about the day before. With nothing recorded for yesterday (a run of this stage alone) it says so, and gives no number", "asked 2026-10-14 (questions about my day); golden 23"):
        from datetime import timedelta

        from core import day as days
        from core import occurrences

        mine = await h.say("how did I go yesterday?", canned=("day_past", {"period": "yesterday", "guessed": [], "not_included": []}), task="briefing")
        await no_marks(h, mine)
        recorded = await occurrences.for_day(h.user.id, "pills", days.today() - timedelta(days=1))
        said = await h.find(h.inbox, "esterday", "☀️")
        if recorded:
            h.check(said is not None and said.text.startswith("☀️ **Yesterday** · ") and "💊 Yesterday: " in said.text and " taken" in said.text, f"the answer: {said.text[:200] if said else 'nothing'}")
            h.check(said is not None and ("●" in said.text.splitlines()[0] or "○" in said.text.splitlines()[0]) and "%" not in said.text, f"its first line has no dots, or there is a percentage: {said.text[:120] if said else 'nothing'}")
        else:
            h.check(said is not None and said.text == "☀️ Nothing was on yesterday.", f"nothing is recorded for yesterday, and the answer is: {said.text[:200] if said else 'nothing'}")
        h.saw(" / ".join(said.text.splitlines()[:2]) if said else "nothing")

    async with h.step("5.03e", "“will it rain?” in plain words", "The weather task answers from the forecast it keeps (the recorded one), with no request to the network: the highest chance in the hours still to come and roughly when, and when it was updated", "asked 2026-10-14 (questions about my day); golden 24"):
        mine = await h.say("will it rain?", canned=("weather_ask", {"rain": True, "guessed": [], "not_included": []}), task="weather")
        await no_marks(h, mine)
        said = await h.find(h.inbox, "chance of rain")
        h.check(said is not None and said.text.startswith("🌤️ 61% chance of rain for the rest of today, most likely between 1pm and 5pm."), f"the answer: {said.text[:200] if said else [each.text[:80] for each in await h.recent(h.inbox, 3) if each.id not in h.typed]}")
        h.check(said is not None and "updated " in said.text, "it does not say when the forecast was updated")
        h.saw(said.text.splitlines()[0][:120] if said else "nothing")

    async with h.step("5.03f", "“what's the weather this afternoon?” in plain words", "The weather task answers for that part of the day: “**This afternoon**”, the chance of rain in those hours, and the day's wind small under it. No temperature is said: the recorded forecast has none by the hour", "asked 2026-10-14 (questions about my day); golden 25"):
        mine = await h.say("what's the weather this afternoon?", canned=("weather_ask", {"when": "afternoon", "guessed": [], "not_included": []}), task="weather")
        await no_marks(h, mine)
        said = await h.find(h.inbox, "**This afternoon**")
        h.check(said is not None and said.text.splitlines()[0] == "🌤️ **This afternoon**" and "61% chance of rain this afternoon" in said.text, f"the answer: {said.text[:200] if said else 'nothing'}")
        h.check(said is not None and "wind up to 15 km/h N today" in said.text and "°" not in said.text, f"the small line, or a temperature that is not in the forecast: {said.text[:300] if said else 'nothing'}")
        h.saw(" / ".join(said.text.splitlines()[:2]) if said else "nothing")

    async with h.step("5.04", "A dose is ticked off: `took testany`", "The briefing in the hub is edited in place: the Pills box's count goes up by one; no new briefing is posted, there or in #selftest-inbox", "scheduler stage 3"):
        before = await briefing_in_hub(h)
        count = pills_count(before.text)[0] if before is not None and pills_count(before.text) else None
        h.check(count is not None, f"no Pills count in the briefing: {before.text[:300] if before else 'gone'}")
        await h.say("took testany")
        await h.settle(3)
        after = await briefing_in_hub(h)
        h.check(after is not None and after.id == before.id, "the briefing in the hub was replaced, not edited")
        now = pills_count(after.text)[0] if after is not None and pills_count(after.text) else None
        h.check(now == count + 1, f"its count went from {count} to {now}")
        h.check(await h.count(h.hub, BRIEFING) == 1, f"{await h.count(h.hub, BRIEFING)} briefings in the hub")
        from core import livelists

        copy = await database.run(livelists.db_get, h.user.id, "briefing")
        latest = await h.get(h.inbox, copy.message_id) if copy is not None else None
        h.check(latest is not None and pills_count(latest.text) is not None and pills_count(latest.text)[0] == now, "the copy in #selftest-inbox was not brought up to date too")
        h.saw(f"{count} → {now} dealt with, in place")

    async with h.step("5.04b", "The day's progress at the top of the briefing", "With DAY_PROGRESS on: the day's total in the title as a dot a thing to do and the count (“☀️ Today ●○○○○○ 1/6”), no percentage, and under the date one small line a task (“💊 1/6”), with the numbers the checklist itself counts; it moved in place with the dose just ticked off", "asked 2026-10-14 (day progress)"):
        from tasks.pills import checklist
        from tasks.pills import today as pills_today

        h.check(config.DAY_PROGRESS, "DAY_PROGRESS is not on in this start")
        shown = await briefing_in_hub(h)
        lines = shown.all_text.splitlines() if shown is not None else []
        _, listed, _ = await checklist.view(h.user.id)
        done, total = pills_today.progress(listed)
        h.check(done >= 1 and total > done, f"the checklist counts {done} of {total}: the step needs a day part done")
        wanted = design.progress(done, total)
        h.check(bool(lines) and lines[0].endswith(f"☀️ Today {wanted}"), f"the title does not end {wanted!r}: {lines[:4]}")
        h.check(any(line.endswith(f"💊 {done}/{total}") and line.startswith(design.SMALL) for line in lines[1:4]), f"no small line for pills, {done}/{total}, under the title: {lines[:6]}")
        h.check("%" not in "\n".join(lines[:4]), f"a percentage at the top: {lines[:4]}")
        h.saw(" / ".join(lines[:3]))

    async with h.step("5.06", "`my schedule` with a routine in it", "Morning routine, every day at 6:00 am, with its steps numbered: 1. briefing, 2. pills checklist", "scheduler stage 3"):
        await h.say("my schedule")
        shown = await h.find(h.inbox, "My schedule")
        h.check(shown is not None and "**Morning routine** · every day at " in shown.text and "6:00 am" in shown.text, f"the list: {shown.text[:300] if shown else 'nothing'}")
        h.check("1. briefing" in shown.text and "2. pills checklist" in shown.text, f"its steps: {shown.text[:400]}")

    async with h.step("5.06b", "With WEEKLY_SUMMARY on: its schedule, and the summary when it runs", "A schedule “Weekly pills summary”, Sunday at 7:00 pm in the hub, silent. Run now, it posts the week in the hub: “Your week”, the count, a line a day", "asked 2026-10-13 (stage 4)"):
        from tasks.pills import history

        h.check(config.WEEKLY_SUMMARY, "WEEKLY_SUMMARY is not on in this start")
        weekly = await schedule_named(h, "Weekly pills summary")
        h.check(weekly is not None and (f"{weekly.at:%H:%M}", weekly.days, weekly.notify, weekly.channel) == ("19:00", (6,), "silent", "hub"), f"the schedule is {weekly}")
        await scheduler.run_now("pills", history.WEEK_JOB)
        await h.settle(2)
        posted = await h.find(h.hub, "Your week")
        h.check(posted is not None and " taken" in posted.text.splitlines()[0] and posted.silent, f"the hub has: {[each.text[:60] for each in await h.recent(h.hub, 4)]}")
        h.saw(posted.text.splitlines()[0][:140])

    async with h.step("5.07", "The next morning at 6:00: the routine again", "A new briefing, then the checklist under it; yesterday's briefing is gone; one briefing in the hub; the line about yesterday counts the dose ticked off at 5.04", "scheduler stage 3"):
        old = h.memo["briefing_hub"]
        await h.clock_to(6, 0, 5, day_offset=1)
        fresh = await briefing_in_hub(h)
        h.check(fresh is not None and fresh.id != old, "no new briefing was posted")
        h.check(await h.get(h.hub, old) is None and await h.count(h.hub, BRIEFING) == 1, f"yesterday's briefing is still there, or there are {await h.count(h.hub, BRIEFING)}")
        sheet = await sheet_id(h)
        h.check(sheet is not None and sheet > fresh.id, f"the checklist ({sheet}) is not under the briefing ({fresh.id})")
        h.check(fresh.silent, "the briefing was posted with a notification")
        h.check("Yesterday: " in fresh.text and "taken" in fresh.text.split("Yesterday: ")[1], f"no line about yesterday: {fresh.text[:400]}")
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        # Only the runs that were done: one booked for this morning days ago, on the moved clock, and taken out since is still in the log
        done = [each[2].split("~")[0][-2:] for each in [*await h.runs("briefing", "post"), *await h.runs("pills", "checklist")] if each[1] == f"{day_stamp}T06:00" and each[0] == "done"]
        h.check(done == ["#1", "#2"], f"the routine's runs done for 6:00 am: {done}")
        h.saw(next((line for line in fresh.text.splitlines() if "Yesterday" in line), "")[:120])

    async with h.step("5.07b", "With HUB_TIDY off, nothing has a lifetime and nothing was tidied", "No message has been recorded, and yesterday's checklist is still in the hub beside today's (as the code has always left it)", "scheduler stage 4: off"):
        from core import messages

        h.check(not config.HUB_TIDY, "HUB_TIDY is on in this start")
        recorded = await database.run(lambda conn: conn.execute("SELECT COUNT(*) FROM bot_messages").fetchone()[0])
        h.check(recorded == 0, f"{recorded} messages have a lifetime recorded")
        sheets = [each for each in await h.recent(h.hub, 50) if each.id not in h.typed and "💊 Today · " in each.text]
        h.check(len(sheets) >= 2, f"{len(sheets)} checklists are in the hub: yesterday's was removed with the tidy off")
        h.memo["old_sheet"] = sheets[-1].id
        h.memo["hub_before_tidy"] = [each.id for each in await h.recent(h.hub, 50)]
        h.check(messages.enabled() is False, "the tidy says it is on")

    async with h.step("5.08", "`dev clock reset`", "The clock is the real time again", "housekeeping"):
        await h.say("dev clock reset")
        h.check(not clock.is_shifted(), "the clock is still moved")


# ---------------------------------------------------------------------------
# Start 6: the tidy switched on as well
# ---------------------------------------------------------------------------
async def lifetimes(h: Harness) -> dict[int, tuple]:
    """What is recorded about each message: {id: (lifetime, slot, gone or not, why)}."""
    def read(conn):
        return {row[0]: row[1:] for row in conn.execute("SELECT message_id, lifetime, slot, gone_at IS NOT NULL, why FROM bot_messages")}

    return await database.run(read)


async def expire(h: Harness) -> None:
    """Two minutes go by, and the tidy's own job runs."""
    await h.clock_by(minutes=2, seconds=5)
    await h.settle(2)


async def p6(h: Harness) -> None:
    from core import messages

    async with h.step("6.01", "A start with HUB_TIDY on", "The morning routine has three steps: the tidy, the briefing, the pills checklist. Nothing that was in the hub before has a lifetime, and none of it is touched", "scheduler stage 4"):
        h.check(config.HUB_TIDY and messages.enabled(), "HUB_TIDY is not on")
        routine = await schedule_named(h, "Morning routine")
        h.check(routine is not None and routine.steps == ("core.hub_tidy", "briefing.post", "pills.checklist"), f"its steps are {routine.steps if routine else None}")
        await h.clock_to(9, 0, day_offset=6)
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        ran = [(each[0], each[2].split("~")[0][-2:], each[3]) for each in await h.runs("core", "hub_tidy") if each[1] == f"{day_stamp}T06:00" and each[0] == "done"]
        h.check(len(ran) == 1 and ran[0][1] == "#1", f"the tidy's run for 6:00 am: {ran}")
        still = [each for each in h.memo.get("hub_before_tidy", []) if await h.get(h.hub, each) is not None]
        h.check(len(still) >= max(1, len(h.memo.get("hub_before_tidy", [])) - 3), f"only {len(still)} of {len(h.memo.get('hub_before_tidy', []))} messages from before the tidy are still in the hub")
        h.check(await h.get(h.hub, h.memo.get("old_sheet")) is not None, "an old checklist with no lifetime recorded was removed")
        h.saw(f"the tidy's line: {ran[0][2]} · {len(still)} old messages left alone")

    async with h.step("6.02", "This morning's briefing and checklist have a slot each", "Both are recorded as “replaced” (briefing, pills.checklist): one of each at a time", "scheduler stage 4"):
        recorded = await lifetimes(h)
        slots = sorted(slot for lifetime, slot, gone, why in recorded.values() if lifetime == "replaced" and not gone)
        h.check(slots == ["briefing", "pills.checklist"], f"the slots recorded are {slots}")
        h.memo["sheet_tidy"] = await sheet_id(h)

    async with h.step("6.03", "I say something in the hub and get a reply: `took testany`", "The line is there; 2 minutes later my message and the reply are both gone, with nothing said about it; the checklist and the briefing stay", "scheduler stage 4"):
        mine = await h.say("took testany", channel=h.hub)
        reply = await h.find(h.hub, "Testany", "taken")
        h.check(reply is not None, f"no reply in the hub: {[each.text[:60] for each in await h.recent(h.hub, 3)]}")
        recorded = await lifetimes(h)
        h.check(recorded.get(mine, ("",))[0] == "expiry" and recorded.get(reply.id, ("",))[0] == "expiry", f"recorded: mine {recorded.get(mine)}, the reply {recorded.get(reply.id)}")
        log_before = len(await h.recent(h.botlog, 50))
        await expire(h)
        h.check(await h.get(h.hub, mine) is None and await h.get(h.hub, reply.id) is None, "my message or the reply is still in the hub after 2 minutes")
        h.check(await h.get(h.hub, h.memo["sheet_tidy"]) is not None and await briefing_in_hub(h) is not None, "the checklist or the briefing went with them")
        tidy_cards = [each for each in await h.recent(h.botlog, 50) if "Tidy" in each.all_text]
        h.check(not tidy_cards and len(await h.recent(h.botlog, 50)) <= log_before + 1, f"#selftest-log was told: {[each.all_text[:80] for each in tidy_cards]}")

    async with h.step("6.04", "A copy was saved first", "The exports folder (the run's own, never data/exports) has a tidy file for the hub, for that day, with my words and the reply in it", "scheduler stage 4"):
        path = messages.transcript_path(h.hub.name, clock.now())  # the file for the day it was removed on
        h.check(path.exists(), f"no {path.name} in {path.parent}")
        said = path.read_text(encoding="utf-8")
        h.check("took testany" in said and "Testany" in said and "taken" in said, f"the copy holds: {said[-300:]}")
        h.check(path.parent == h.out.parent / "exports", f"the copy is in {path.parent}, not the run's own folder")
        h.saw(path.name)

    async with h.step("6.05", "Something I say in the hub that leads to a card, then Cancel", "The card waits; on Cancel the card and my message both go at once", "scheduler stage 4"):
        mine = await h.say("add Testhub to my pills once a day", channel=h.hub, canned=add({"name": "Testhub", "per_day": 1}))
        stored, shown = await card(h, h.hub)
        h.check(shown is not None, "no card in the hub")
        await h.clock_by(minutes=3)
        h.check(await h.get(h.hub, mine) is not None and await h.get(h.hub, shown.id) is not None, "they went while the card was still open")
        await h.press(shown.id, "Cancel", h.hub)
        await h.clock_by(seconds=5)
        await h.settle(2)
        h.check(await h.get(h.hub, shown.id) is None and await h.get(h.hub, mine) is None, "the card or my message is still there after Cancel")

    async with h.step("6.06", "The same, then Save", "On Save my message goes at once and the card becomes its confirmation, which goes 2 minutes later; the pill is saved all the same", "scheduler stage 4"):
        mine = await h.say("add Testhub to my pills once a day", channel=h.hub, canned=add({"name": "Testhub", "per_day": 1}))
        stored, shown = await card(h, h.hub)
        h.check(shown is not None, "no card in the hub")
        await h.press(shown.id, "Save", h.hub)
        await h.clock_by(seconds=5)
        await h.settle(2)
        h.check(await h.get(h.hub, mine) is None, "my message is still there after Save")
        confirmation = await h.get(h.hub, shown.id)
        h.check(confirmation is not None and "Testhub" in confirmation.text, "the confirmation went at once")
        await expire(h)
        h.check(await h.get(h.hub, shown.id) is None and "Testhub" in await h.pills(), "the confirmation is still there, or the pill was not saved")

    async with h.step("6.07", "Pinned stays", "A reply I pin inside its 2 minutes is still there afterwards; what I typed goes", "scheduler stage 4"):
        mine = await h.say("took testhub", channel=h.hub)
        reply = await h.find(h.hub, "Testhub", "taken")
        h.check(reply is not None, "no reply in the hub")
        await (await h.hub.fetch_message(reply.id)).pin()
        await expire(h)
        h.check(await h.get(h.hub, reply.id) is not None, "the pinned reply was removed")
        h.check(await h.get(h.hub, mine) is None, "what I typed is still there")
        h.check((await lifetimes(h)).get(reply.id, ("",))[0] == "kept", f"it is recorded as {(await lifetimes(h)).get(reply.id)}")
        await (await h.hub.fetch_message(reply.id)).unpin()
        h.memo["pinned"] = reply.id

    async with h.step("6.08", "The same exchange in #selftest-inbox", "Nothing goes after 2 minutes: the hub's rule is the hub's. The line that reports the change is recorded to last the day", "scheduler stage 4"):
        mine = await h.say("took testlate")
        reply = await h.find(h.inbox, "Testlate", "taken")
        h.check(reply is not None, f"no reply: {[each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        await expire(h)
        h.check(await h.get(h.inbox, mine) is not None and await h.get(h.inbox, reply.id) is not None, "they were removed from #selftest-inbox")
        recorded = await lifetimes(h)
        h.check(mine not in recorded and recorded.get(reply.id, ("",))[0] == "day", f"recorded: mine {recorded.get(mine)}, the reply {recorded.get(reply.id)}")
        h.memo["inbox_line"] = reply.id

    async with h.step("6.09", "The next morning at 6:00", "The tidy runs first: yesterday's checklist and briefing are gone and today's are there, one of each; yesterday's line in #selftest-inbox is gone; the reply I had pinned (and unpinned since) is left, being kept; nothing in #selftest-log", "scheduler stage 4"):
        old_sheet, old_briefing = h.memo["sheet_tidy"], (await briefing_in_hub(h)).id
        log_before = [each.id for each in await h.recent(h.botlog, 50)]
        await h.clock_to(6, 0, 10, day_offset=1)
        await h.settle(3)
        h.check(await h.get(h.hub, old_sheet) is None and await h.get(h.hub, old_briefing) is None, "yesterday's checklist or briefing is still in the hub")
        fresh, sheet = await briefing_in_hub(h), await sheet_id(h)
        h.check(fresh is not None and sheet is not None and sheet > fresh.id and await h.count(h.hub, BRIEFING) == 1, "today's briefing and checklist are not there, one of each, the checklist last")
        h.check(await h.get(h.inbox, h.memo["inbox_line"]) is None, "yesterday's line that reported a change is still in #selftest-inbox")
        h.check(await h.get(h.hub, h.memo["pinned"]) is not None, "the reply that was kept for being pinned was removed after all")
        new = [each for each in await h.recent(h.botlog, 50) if each.id not in log_before and "Tidy" in each.all_text]
        h.check(not new, f"#selftest-log was told of the tidy: {[each.all_text[:100] for each in new]}")
        day_stamp = f"{config.now_nz():%Y-%m-%d}"
        ran = [each[3] for each in await h.runs("core", "hub_tidy") if each[1] == f"{day_stamp}T06:00" and each[0] == "done"]
        h.saw(f"the tidy's line: {ran[0] if ran else 'none'}")

    async with h.step("6.10", "`dev clock reset`", "The clock is the real time again", "housekeeping"):
        await h.say("dev clock reset")
        h.check(not clock.is_shifted(), "the clock is still moved")


PHASES = {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5, "p6": p6}
