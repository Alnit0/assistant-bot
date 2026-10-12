import asyncio
import os
from datetime import timedelta

from core import clock, config, confirm, database, design, occurrences, scheduler
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
    async with h.step("1.01", "The dev bot starts in the test channels", "“🟢 Bot started” in #selftest-log naming dev.db, and “👋 Online and ready” in #selftest-inbox", "asked"):
        started = await h.find(h.botlog, "Bot started")
        h.check(started is not None and "dev.db" in started.all_text, f"#selftest-log has: {[each.all_text[:60] for each in await h.recent(h.botlog, 5)]}")
        h.check(await h.find(h.inbox, "Online and ready") is not None, "no “Online and ready” in #selftest-inbox")
        h.check(config.DEV_DATABASE and clock.shiftable(), "this is not the dev database")

    async with h.step("1.02", "The dev clock is moved to tomorrow, 5:50 am", "The clock reads 5:50 am tomorrow; the day rolled over with nothing posted in the hub", "asked"):
        await h.clock_to(5, 50, day_offset=1)
        h.check(f"{config.now_nz():%H:%M}" == "05:50", f"the clock reads {config.now_nz():%a %H:%M}")
        h.check(not [each for each in await h.recent(h.hub, 5)], "something was posted in the hub before any pill exists")
        h.saw(f"{config.now_nz():%a %d %b %H:%M}")

    await save_new(
        h, "1.03", "add Testa to my pills at 8am, 11am and 2pm, at least 3 hours apart, not after 4pm, with food",
        add({"name": "Testa", "per_day": 3, "times": ["8:00 am", "11:00 am", "2:00 pm"], "min_gap_minutes": 180, "latest": "4:00 pm", "notes": "with food"}),
        "Testa", "T49, golden 1",
    )
    await save_new(h, "1.04", "add Testany to my pills once a day", add({"name": "Testany", "per_day": 1}), "Testany", "T15")

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

    async with h.step("1.10", "“remove testvit and testvit forte”, then Remove", "A remove card with a red Remove; after it both are gone", "T25 (40.5)"):
        await h.say("remove testvit and testvit forte", canned=about("pill_remove", {"pill": "Testvit"}, {"pill": "Testvit forte"}))
        stored, shown = await card(h)
        h.check(shown is not None and any("Remove" in label for label in shown.labels), f"the card: {shown.text[:160] if shown else 'none'} with {shown.labels if shown else []}")
        await h.press(shown.id, "Remove", h.inbox)
        left = list(await h.pills())
        h.check(not any(name.startswith("Testvit") for name in left), f"still there: {left}")

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

    async with h.step("1.16", "Taken is pressed on the reminder", "The reminder goes; dose 1 is taken; the checklist shows it", "38.4"):
        await h.press(h.memo["prompt"], "Taken")
        h.check(await h.get(h.hub, h.memo["prompt"]) is None and not await prompts(h), "the reminder is still up")
        h.check((await h.doses()).get(("Testa", 1)) == DONE, f"the doses are {await h.doses()}")
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and "8:00 am" in sheet.text, f"the checklist reads: {sheet.text[:240] if sheet else 'gone'}")

    async with h.step("1.17", "Too soon: `took testa` a minute after dose 1", "A card “⚠️ That's … after dose 1 … Log it anyway?” with Log it and Cancel; nothing is ticked off. Cancel removes it", "43.3, T46"):
        await h.say("took testa")
        stored, shown = await card(h)
        h.check(shown is not None and "Log it anyway?" in shown.text and "⚠️" in shown.text, f"the card: {shown.text[:200] if shown else 'none'}")
        h.check(any("Log it" in label for label in shown.labels) and any("Cancel" in label for label in shown.labels), f"its buttons are {shown.labels}")
        h.check((await h.doses()).get(("Testa", 2)) == PENDING, "dose 2 was ticked off without asking")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check((await h.doses()).get(("Testa", 2)) == PENDING and (await card(h))[0] is None, "after Cancel the dose changed or the card is still open")
        warned = next((line for line in shown.text.splitlines() if "⚠️" in line), "")
        h.saw(warned[:120])
        if "0m after" in warned:
            h.odd(f"The too-soon card says “{warned.strip()[:60]}…”: “0m after” reads oddly for a dose logged less than a minute before")

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
        if "pills remind" in said:
            h.odd("The catch-up card calls the reminder job by its internal name, “pills remind”. It names no pill, but it is not a phrase you would know")
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

    async with h.step("2.09", "After the third reminder the dose is missed", "The reminder goes, the dose is missed, and the checklist shows ❌", "T45 (38.6)"):
        await h.clock_by(minutes=15, seconds=10)
        h.check(not await prompts(h) and await h.get(h.hub, h.memo["prompt"]) is None, "the reminder is still up")
        h.check((await h.doses()).get(("Testa", 3)) == MISSED, f"the doses are {await h.doses()}")
        sheet = await h.get(h.hub, h.memo["sheet_d1"])
        h.check(sheet is not None and "❌" in sheet.text and "missed" in sheet.text, f"the checklist reads: {sheet.text[:300] if sheet else 'gone'}")

    async with h.step("2.10", "A late log: “took testa” after it was missed", "It is ticked off all the same: at once, or after a card that asks first", "T45 (38.7)"):
        mine = await h.say("took testa", canned=log({"pill": "Testa", "did": "taken"}), route={"kind": "task", "tasks": [TASK], "confidence": "high", "reports_doing": True, "chat_part": ""})
        if (await h.doses()).get(("Testa", 3)) != DONE:
            stored, shown = await card(h)
            h.check(shown is not None and any("Log it" in label for label in shown.labels), f"not ticked off and no card that asks: {[each.text[:80] for each in await h.recent(h.inbox, 3)]}")
            h.saw("asked first: " + next((line for line in shown.text.splitlines() if "⚠️" in line), shown.text.splitlines()[-1])[:120])
            await h.press(shown.id, "Log it", h.inbox)
        else:
            h.saw("ticked off at once")
            h.odd("“took testa” a minute after dose 3 was marked missed (an hour after it was due) ticks it off at once, with no card asking first. QA-TONIGHT step 45 expects exactly that; noted because CLAUDE.md says a late log asks first, which here means after the pill's latest time")
        h.check((await h.doses()).get(("Testa", 3)) == DONE, f"the doses are {await h.doses()}")
        await no_marks(h, mine)

    async with h.step("2.11", "8:00 pm: Testiron's reminder, and Skip", "A reminder for Testiron; Skip takes it down and the dose is skipped", "38"):
        await h.clock_to(20, 0, 5)
        up = await prompts(h)
        h.check(len(up) == 1 and up[0].message_id, f"{len(up)} prompts are kept")
        shown = await h.get(h.hub, up[0].message_id)
        h.check(shown is not None and "Testiron" in shown.text, f"it reads: {shown.text[:160] if shown else 'gone'}")
        await h.press(shown.id, "Skip")
        h.check(not await prompts(h) and (await h.doses()).get(("Testiron", 1)) == SKIPPED, f"the doses are {await h.doses()}")

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

    async with h.step("3.05", "`pills` with the new look on", "One message: “💊 Today · n of m taken”, the date, a box a pill with its status colour (green for Testany, taken; grey or amber for the rest), and no separate message for a dose with no time", "T51 (41.3)"):
        await h.say("pills")
        sheets = await held(h, "checklist")
        shown = await h.get(h.hub, sheets[-1].message_id) if sheets else None
        h.check(shown is not None and shown.v2, f"the fresh checklist is {'plain' if shown else 'missing'}")
        h.check("💊 Today · " in shown.text and "taken" in shown.text, f"its heading: {shown.text.splitlines()[0]}")
        allowed = {accent(status) for status in design.ACCENTS}
        h.check(shown.accents and set(shown.accents) <= allowed, f"its box colours are {[hex(each) if each else None for each in shown.accents]}")
        h.check(accent(design.DONE) in shown.accents, "no green box for Testany, which is taken")
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

    async with h.step("3.07", "Taken pressed again in Testa's box: too soon", "An amber box “⚠️ That's … after dose 1 … Log it anyway?” with Log it and Cancel; nothing ticked off. Cancel", "T54 (41.6)"):
        pressed = await h.press(h.memo["sheet_d2"], "Taken", arg=await dose_id(h, "Testa", 2))
        asked = await h.find(h.hub, "Log it anyway?") or await h.find(h.inbox, "Log it anyway?")
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

    async with h.step("3.10b", "A pill with no time is added with the new look on: “add Testlate once a day”", "After Save the drawn checklist gains a blue box for Testlate, any time, with its buttons, in place; no separate message for it", "T51 (41.3)"):
        await h.say("add Testlate to my pills once a day", canned=add({"name": "Testlate", "per_day": 1}))
        stored, shown = await card(h)
        h.check(shown is not None and shown.v2, "no drawn card")
        await h.press(shown.id, "Save", h.inbox)
        await h.settle(2)
        sheet = await h.get(h.hub, h.memo["sheet_d2"])
        h.check(sheet is not None and "Testlate" in sheet.text and "any time" in sheet.text, f"the checklist: {sheet.text[-300:] if sheet else 'gone'}")
        h.check(accent(design.ANY_TIME) in sheet.accents, f"no blue box: {[hex(each) if each else None for each in sheet.accents]}")
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

    async with h.step("3.13", "The reset card in the new look: `reset channel`, then Cancel", "A red box that says it can't be undone, with a red Delete all; Cancel removes it and deletes nothing", "39.4"):
        count = len(await h.recent(h.inbox, 50))
        await h.say("reset channel")
        shown = await h.find(h.inbox, "can't be undone")
        h.check(shown is not None and any("Delete all" in label for label in shown.labels), f"no reset card: {[each.text[:60] for each in await h.recent(h.inbox, 3)]}")
        h.saw(f"{'drawn' if shown.v2 else 'plain'}, colours {[hex(each) if each else None for each in shown.accents]}")
        if not shown.v2:
            h.odd("With CARDS_V2 on the reset card is still a plain message: it is not one of the five cards built in the new look (docs/DESIGN.md says so)")
        await h.press(shown.id, "Cancel", h.inbox)
        h.check(await h.get(h.inbox, shown.id) is None, "the card is still there after Cancel")
        h.check(len(await h.recent(h.inbox, 50)) >= count - 1, "messages were deleted")

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

    async with h.step("4.06", "`dev cost`", "Under Today a small line with what was spent against DAILY_SPEND_LIMIT", "T35, T56 (42.1, 42.3)"):
        await h.say("dev cost")
        shown = await h.find(h.inbox, "limit")
        h.check(shown is not None, f"no line about the limit: {[each.text[:120] for each in await h.recent(h.inbox, 2)]}")
        line = next((line for line in shown.text.splitlines() if "limit" in line), "")
        h.saw(line[:120])
        if "US$0.00 limit" in line or "of US$0.00" in line:
            h.odd(f"`dev cost` shows a limit under one cent as “US$0.00” ({line.strip()[:70]}). Only seen because the test sets DAILY_SPEND_LIMIT=0.0001")

    spent = await h.spent()
    if spent > 0 and await h.can_ask_claude():
        async with h.step("4.07", "The spend line: two messages to Claude with the limit at US$0.0001", "One “💰 Claude spend is over today's limit” in #selftest-log after the first, and no second one after the second", "T49, T50 (42.2, 42.3)"):
            await h.say("what pills do I have left today?", canned=("pill_today", {"guessed": [], "not_included": []}))
            first = await h.count(h.botlog, "over today's limit")
            await h.say("what pills do I have left today?", canned=("pill_today", {"guessed": [], "not_included": []}))
            second = await h.count(h.botlog, "over today's limit")
            h.check(first == 1 and second == 1, f"{first} card(s) after the first message, {second} after the second")
    else:
        h.skip("4.07", "The spend line in #bot-log when the limit is passed", "needs real requests to Claude with money left: run with --claude", "T49, T50 (42.2, 42.3)")

    async with h.step("4.08", "`dev clock reset`", "The clock is the real time again, and the standing jobs are booked for the real day", "T57"):
        await h.say("dev clock reset")
        h.check(not clock.is_shifted(), "the clock is still moved")
        jobs = await scheduler.all_pending()
        late = [job for job in jobs if job.kind in ("day_rollover", "post", "checklist") and job.due_at - clock.now() > timedelta(hours=25)]
        h.check(not late, f"jobs booked more than a day ahead: {[(job.task, job.kind, job.due_at.isoformat()) for job in late]}")


PHASES = {"p1": p1, "p2": p2, "p3": p3, "p4": p4}
