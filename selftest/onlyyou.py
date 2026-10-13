# ---------------------------------------------------------------------------
# What the self-test cannot check, by step of docs/QA-TONIGHT.md and block of
# docs/QA-RUN.md: looks, colours as they appear, the lock screen, wording as a
# person reads it, and anything that needs a hand on the phone.
# ---------------------------------------------------------------------------
ONLY_YOU = (
    ("QA-TONIGHT 2, 3 (39.2, 33.1)", "What the lock screen shows for a reminder as first posted and once written in. The test checks the message was posted as the neutral line and edited after; what the phone shows for it only you can see"),
    ("QA-TONIGHT 4, 5 (39.1, 39.6)", "The checklist sketch's colours in each theme you use, and whether amber, blue, green, red and grey can be told apart. The test checks each box's accent value against `core/design.py`, not how it looks"),
    ("QA-TONIGHT 6 to 10 (39.3 to 39.5, 33, 35)", "How each sketch reads: layout, spacing, whether the wording is right. The test checks Discord accepts every sketch and that it posts as Components V2"),
    ("QA-TONIGHT 41, 52 (38.2, 41.4)", "The lock screen for a real reminder, old look and new"),
    ("QA-TONIGHT 42 (38.3)", "That the phone buzzes again when a reminder is posted again. The test checks it is a new message and the old one is gone"),
    ("QA-TONIGHT 49 to 55 (block 41)", "How the new look reads on the phone: the boxes, the hint under a card, the buttons inside a pill's box. The test checks what each message holds and that presses edit it in place"),
    ("QA-TONIGHT 11 to 14 (blocks 27, 30, 31)", "Timers: not in the self-test. They post with discord.py directly and are a proof of concept"),
    ("QA-TONIGHT 24 (40.4)", "A picture sent with words: the test cannot attach a file as you"),
    ("QA-TONIGHT 32 to 34 (32.1, 32.2, 34.3)", "Bugs: 🐞 as a reaction of yours, and Won't fix in the #bugs forum. A bot cannot react as you, and the forum is live's"),
    ("QA-TONIGHT 29 (37.6)", "“took it” six minutes after anything else: the wait is real time, not the dev clock's"),
    ("QA-TONIGHT 59", "Live after its restart: the test starts the service and checks the lock and the start card; that it behaves is yours"),
    ("Block 44", "The four new sketches (briefing, schedule list, schedule change, tidy): whether they are what you want. The test only checks Discord accepts them"),
    ("Wording everywhere", "Every line the bot says is checked for the words that matter (a name, a time, a mark), not for whether it reads well"),
    ("Real presses", "Every press in this run was simulated: the handler behind the button was called and it edited the real message. That Discord delivers a real tap to that handler is checked by discord.py's own routing and by you pressing one"),
)

# What the specs and the standard say that no step here exercises
NOT_TESTED = (
    "The nightly self-test (`NIGHTLY_SELFTEST`): the dev bot cannot start a self-test of itself; its parts are tested offline (`tests/test_nightly.py`)",
    "Messages sent while the bot was off (“I was offline when you sent this”): a bot cannot write as you while another is stopped; block 50 of `docs/QA-RUN.md`",
    "Pills: a course with a start and an end, pausing until a date and coming back by itself, a pill whose doses can't fit, more than a handful of pills on one checklist, a dose skipped by the bot for want of time",
    "Pills: “no, …” undoing a change, a correction straight after Save becoming a change card, a reply to a line meaning that dose (the test replies to nothing)",
    "Reminders: nothing sent after a pill's latest time when the bot starts late; reminders on with no hub channel; a channel reset while a reminder is up",
    "Restarts: a Save cut off half way through the save itself, and a channel reset cut off (the test cuts off a typed message only)",
    "The standard: no reply to a remark, chat never acknowledging, task ties, several things in one message for two tasks. The golden conversations cover these offline (`tests/test_golden.py`), with recorded answers",
    "Reactions (📌, 📦, 🗑️, 🐞), reply words (`pin`, `archive`, `bug`), slash commands and context menus: a bot cannot make them as you",
    "Timers, bugs, archive, keep and lab: they post with discord.py directly or need your reactions",
    "Notifications themselves: whether the phone buzzed, and what it showed",
    "The nightly backup (its job is cancelled for the run, so the test's database is never backed up over the dev database's own backups), quiet hours, the daily spend card on the real day boundary",
    "The scheduler, clean-up and briefing specs, and gym: nothing of them is built",
    "Live: only that the service came back and holds the lock",
)


def lines() -> list[str]:
    out = ["## Only you can check", "", "| Where | What |", "|---|---|"]
    out += [f"| {where} | {what} |" for where, what in ONLY_YOU]
    return out + [""]
