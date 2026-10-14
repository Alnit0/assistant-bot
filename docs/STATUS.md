# Status

Where the work stands, in one page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.
No history is kept here: what changed is `docs/CHANGELOG.md`, and this
file as it stood until midday on 2026-10-14 (every batch, every answer,
all of "Decided overnight") is `docs/archive/STATUS-2026-10-14.md`.

**Updated:** 2026-10-14

## Priorities (Alex, 2026-10-14)

The hub is a daily overview I check, plus a place to talk to the bot
and do more. I am not relying on the bot for reminders yet. So, most
important first, when work is chosen, ordered or cut short:

1. **What the hub shows and how it reads**: the briefing, the design,
   progress.
2. **How well it understands what I say.**
3. Everything else.

Notifications and ntfy are low priority.

## Decided (the batch of 2026-10-14, afternoon)

Choices the batch's prompt did not settle. Each is yours to overturn.
(The night before's 32 are in the archive.)

**Item 1, the day's progress, and the design messages that came in
while it was being built**

1. **Behind a switch, `DAY_PROGRESS`**, off unless set, as every new
   feature is. It goes on for live with the restart at the end of
   the batch.
2. **A dose taken or skipped counts as done**, as the checklist's own
   count has it, so a day can end with every dot solid. A missed
   dose is not done.
3. **The total is built in the briefing's title** ("☀️ Today ●●●●●○○
   5/7", your example), with the date and then the small line a task
   under it. As a line of normal text it is one value in
   `core/design.py` (`DAY_TOTAL_IN_TITLE`). Question 45.
4. **More than ten things**: ten dots to the nearest, but all solid
   only when everything is done and all hollow only when nothing is.
5. **"Everywhere" was taken at its word**: the block bar is also gone
   from the lab's countdown. **Not changed**: the old-look
   checklist's "▰▰▱▱▱ 2 of 5", which is a different bar and goes with
   the old look (question 46); and per-item dots ("Pill A ●●○") are
   what the drawn checklist already has, so nothing was added there.
6. **The four block-bar sketches are deleted from the repo; the
   messages already posted for them in the forum are left**, above
   round 3. Say if you want them deleted there too.
7. **Round 3 is one folder**: the two dot sketches (R3-A in the title,
   R3-B in normal text) and the five of the type scale. Posted in
   the design-options post, in that order.
8. **Questions 16 to 20 are gone as answered** (progress marks, the
   total, the block bar, the custom-emoji bar): dots. 45 to 48 are
   new.
9. **The type scale is a draft and nothing of it is built.** Five
   things the sketches had to decide are listed in `docs/DESIGN.md`
   (the day's total moves under a title that holds the date; a
   one-card message has both a page and a card title; what notifies
   has no page title; the briefing's pills box lists each pill; a
   relative time in a sketch is a real timestamp).

**Item 2, questions about my day**

10. **Behind one switch, `DAY_QUESTIONS`**, off unless set; on for live
    with the restart at the end of the batch.
11. **The day's questions belong to the briefing task**, which answers
    them from what each task hands in and still knows no task. "What's
    on today?" is the briefing itself, as it was.
12. **Yesterday and the week are read from each task's record of the
    day** (a new `tally` in the contract), not from today's summary:
    a summary is built from how the pills are set up now, which could
    give a wrong number for a day that has passed.
13. **"This week?" is Monday to today**, a line a day with dots and a
    count. The pills' own week ("show my week", a mark a dose) is
    unchanged and still the pills task's.
14. **Straight after you log a pill, "what's left today?" showed the
    checklist.** Overturned the same afternoon: a question never
    sticks to the task that just answered (golden 27, 27a).
15. **Weather answers only from the forecast it keeps**, and nothing is
    fetched to answer. "Tomorrow" says only today's forecast is kept.
    "This afternoon" is 12 to 6, "this evening" and "tonight" 6 to
    midnight, "this morning" 6 to 12; "will it rain?" with no part
    named is the hours still to come today.
16. **How warm a part of the day is needs the temperature by the hour,
    which the fetch now asks for.** Until the first fetch after the
    restart, an answer about the afternoon has no temperature rather
    than a made-up one.
17. **Weather is now a line in the router's catalogue** (last night it
    was kept out so no prompt changed): about US$0.0002 more on each
    routed message. A question costs about half a US cent.
18. **The golden conversations are 21 to 25** (with 23a, "and this
    week?"), recorded from the real API: 33 requests, 33 right,
    NZ$0.18.

**Item 3, the understanding check-up** (what was found is in
`docs/BACKLOG.md`, "Understanding check-up, 2026-10-14")

19. **"My messages to live from the past week" was read as the message
    log of live's database, 7 to 14 October**: 484 rows, of which
    about 30 are plain words since the router went in on the 10th.
    The hundred before that went through the old way of asking
    Claude, which is gone: they were read, and are summed up, not
    replayed.
20. **One misread was still open, and is fixed in code and in the
    prompt**: a change to a pill that is only on the card. The others
    had been fixed since they happened; each now has a golden
    conversation (2c, 18c and 26 are new).
21. **No golden conversation for the two timer misreads**: timers are
    frozen and may be scrapped, and a golden conversation that must
    fail would stand in the list for nothing. Question 50.
22. **A contradiction in what you said is still put right with a ⚠️
    line, not asked about.** The standard can be read either way:
    question 49.
23. **In the fixtures and tests the pill is "Pill A"**: what the real
    API returned is kept as it was but for the name.
24. **`python -m evals.live --part 1/2`** is new: half of a fixture
    file a run, so no run came near NZ$0.40 (the dearest was
    NZ$0.23).
25. **One pills fixture now accepts either of two actions** ("add
    iron…" when iron is there): its own note already said both end
    in the same card. With that the pills fixtures are 62 of 62.

**The end of the batch**

26. **`DAY_PROGRESS` and `DAY_QUESTIONS` are on for live** (two lines
    added to `.env`). To turn either off: set it to false, restart.
27. **Live was restarted twice, not once** (3:03 pm and 3:07 pm). The
    first start showed a fault from this morning's #commands change:
    the first time its text really changed, the edit in place raised
    (a partial message can't be told to hide link previews) and
    #commands was left as it was. Fixed, with test fakes that now take
    only what discord.py takes, and live restarted on the fix:
    "#commands: 1 edited", no error.
28. **#commands does not list the weather questions until the next
    restart.** A task that is only talked to had no page there; the fix
    is committed, and I did not restart live a third time for it.
29. **How warm an afternoon is will be said from the 5:50 pm refresh
    on**: the forecast kept before the restart has no temperature by
    the hour.
30. **The test suite took 1 min 57 s.** Brought to 36 seconds the same
    afternoon, with the same tests (`docs/DECISIONS.md`, "The test
    suite").

**The small fixes after the batch**

31. **What counts as a question is the task's own reading of it**: an
    action that only shows or says something. No list of question
    words. "And this week?" after the answer about yesterday now
    goes by the router too (golden 23a says so).
32. **An open card still holds the conversation**: a question typed
    while a card is open is read against that card first, as before.
    Say if a question should pass a card by as well.
33. **No self-test step for it**: a step's one recorded answer is
    given to every task that reads the message, so the step could not
    tell the old behaviour from the new. Golden 27 and 27a are
    recorded from the real API.
34. **The `end-of-task` skill was reordered** to match the new rule:
    docs, then the full test run, then the commit.

## Where things stand

- **Branch `feature/pills`**: everything is committed and pushed;
  nothing is merged into `main`.
- **Live** was last restarted at 3:07 pm on 2026-10-14 and runs the
  day in dots at the top of the briefing, the questions about the
  day and the weather, and the fix for a change to a pill that is only
  on the card. Not yet live, until the next restart: a question never
  sticking to the last task, and the weather questions in #commands.
  No error since the start; nothing needs a look.
- **The morning routine ran as booked on its first morning** (live's
  run log, 2026-10-14): the exchange rate, the weather fetch, the tidy,
  the briefing, the checklist, and a needs-a-look check with nothing
  to say.
- **Tests**: offline 2861 passed, 1 skipped, in about 40 seconds (it
  was 1 min 56 s); the same tests pass the slow way, with real threads
  and connections (`TESTS_AS_ON_LIVE=1`). The last full self-test
  (3:42 pm, the dev bot with live up, recorded answers): 122 of 123,
  none failed, one skipped for needing real requests. The golden
  conversations asked of the real API: 57 of 59, the two misses old
  known ones that the code puts right; 27 and 27a recorded since, 5 of
  5.
- **Spend on the day's batch**: NZ$1.10 (US$0.62), all of it live
  evals; the dearest run NZ$0.23. The self-test's month (NZ$3.50) is
  spent: recorded answers until November.
- **Bugs**: 2 open on live (`bugs`).

## Switched on (live's `.env`)

- **On**: `BRIEFING_ENABLED`, `DAY_PROGRESS`, `DAY_QUESTIONS`,
  `WEATHER_ENABLED`, `HUB_TIDY`, `REMINDERS_ENABLED`,
  `QUIET_HOURS_ENABLED` (10:00 pm to 7:00 am), `NIGHTLY_SELFTEST`.
- **Off**: `CARDS_V2` (the hub is in the old look), `WEEKLY_SUMMARY`,
  `DMS_ENABLED`, `NOTIFY_NTFY` (nothing goes to ntfy).
- **Each day**: midnight the end of the day; 3:00 am the backup and the
  nightly self-test; 5:30 am the exchange rate; 5:50 am the weather
  fetch; 6:00 am the morning routine (tidy, briefing, checklist);
  7:00 am the needs-a-look check; 8:50 am the weather refresh, then
  every three hours to 8:00 pm.

## Waiting on you

1. **The short list at the top of `docs/QA-RUN.md`**: eleven looks only
   you can take, most useful first. The first two are today's: the hub
   with the day in dots, and design rounds 2 and 3 in the
   design-options post.
2. **The design picks**, questions 12 to 15, 21, 22 and 45 to 48 of
   `docs/QUESTIONS.md`: they are what the new look in the hub waits
   for. Round 3's type scale is a draft until you say what to change.
3. **The other questions**: `docs/QUESTIONS.md` has 45, each with a
   suggested answer ("yes to all suggestions except 4 and 7").
4. **Gym and the calendar** wait on their answers there (23 to 28, 29
   to 32).
5. **The merge** into `main`, then live's own folder (33, 34).

## Next

In the order of the priorities; the full list is `docs/BACKLOG.md`.

1. **The hub's look**: build the type scale of round 3 once you have
   said what to change (one box a topic, the card title with dots,
   times in bold), then the phone check, then `CARDS_V2` on for live
   and #commands' words for it.
2. **What the briefing shows**: whatever your look at the hub turns
   up; the answers about your day, once you have read a few.
3. **Understanding**: the two golden conversations that failed once
   near midnight (question 39); a correction straight after Save for
   schedules (question 8); task ties asked too often (G4).
4. **Then**: the merge and live's own folder; gym once its answers are
   in; the calendar after its four; a flavour status line (backlog).

## Standing

- Nothing is added unasked. New tasks are allowed (gym is next), spec
  and sketches first. Timers are frozen and may be scrapped.
- Open questions are `docs/QUESTIONS.md` and nowhere else.
