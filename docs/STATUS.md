# Status

Where the work stands, in one page. Read it at the start of every
session; the end-of-task checklist updates it at the end of every task.
No history is kept here: what changed is `docs/CHANGELOG.md`, and this
file as it stood until midday on 2026-10-14 (every batch, every answer,
all of "Decided overnight") is `docs/archive/STATUS-2026-10-14.md`.

**Updated:** 2026-10-15

## Round 3 is live (2026-10-15, 8:59 am)

**The hub is in the round 3 design.** `CARDS_V2=true` and `DESIGN_ROUND=3`
were added to live's `.env` and live was restarted once at 8:59 am (the
next pill reminder was 11:07). It came up as its own account; the
briefing and the pills checklist were redrawn in place, read back from
Discord as Components V2. Before it: the full tests (2889 passed), the
commit, and a self-test as the dev bot with recorded answers, 122 of 123 steps
passed, none failed, one skipped as usual (NZ$0.00), which marked D6 and D3 fixed by itself. The preview is the
"Round 3 built" message in the design options post: **please look on your
phone** and reply there. To go back: `DESIGN_ROUND=1` (the look before it)
or `CARDS_V2=false` (the plain look), and a restart.

## Built on 2026-10-15, switched off in live

**Three new hub tasks**, each behind its own switch, off by default and
off in live (`.env` was not touched for them):

| Task | Switch | Words to see it |
|---|---|---|
| To-dos | `TODOS_ENABLED` | `my to-dos` |
| Reminders you set yourself | `NUDGES_ENABLED` | `my reminders` |
| Personal routines | `HABITS_ENABLED` | `my routines` |

`REMINDERS_ENABLED` is still the pills' reminders, untouched. Each task
has its card in the hub under the pills card (reminders, personal
routines, then to-dos), a section in the briefing and its items in the
one ranking (the status line and Needs a look work with no special
case). The real router and extraction were asked 36 natural phrasings,
35 right and the one miss a safe reading ("move that to 6" read as 6 pm,
marked as a guess); the answers are recorded for the tests to replay.
Spend: US$0.14 (NZ$0.25). **To look at**: the "New hub tasks preview" in
the design-options post, and questions 51 to 66 in `docs/QUESTIONS.md`.

**Also**: a task whose switch is off is not loaded (out of help,
#commands and the router); a **What's new** box for one morning's
briefing (`core/whatsnew.py`), not loaded in live until its next restart,
so it is not in tomorrow's 6 am briefing unless live is restarted
before then; `/catchup` for Claude Code; the design loop
(`docs/DESIGN-LOG.md`, `python -m selftest.preview --round N` and
`--replies`).

**Not done**: the prompt about `docs/NOW.md` and a SessionStart hook,
which `/catchup` follows, never reached this session: `/catchup` reads
`docs/NOW.md` when there is one and `docs/STATUS.md` until then. No
self-test steps for the three tasks yet (the month's self-test spend is
gone; `docs/BACKLOG.md`).

## Decided (2026-10-15, the new hub tasks)

17. **Built tonight against the rule "spec first, nothing built until it
    is approved"**: you asked for the build with your defaults, so the
    specs (`docs/specs/todos.md`, `reminders.md`, `routines.md`) were
    written first and the build follows them, everything open to change
    (questions 51 to 66).
18. **The folders are `todos`, `nudges` and `habits`**: `nudges` because
    `REMINDERS_ENABLED` and `tasks/pills/reminders.py` are the pills';
    `habits` because "routine" in code is the scheduler's. What you read
    is "To-dos", "Reminders", "Personal routines" (a new `title` a task
    can give).
19. **A task's card comes after the pills checklist**: steps of the
    morning routine can now run after its own handler (`scheduler.AFTER`),
    each task joining at its place in the order. Gym's place (+30) is
    kept for it.
20. **A card that has nothing for today is not posted, and one that gets
    something mid-day is posted then**, at the bottom of the hub, until
    the next morning puts it in order (question 65).
21. **Ticking a to-do or a step off is a log, done at once**, as a pill
    taken is; adding, changing and removing are cards that only Save
    writes.
22. **A name that fits two to-dos, reminders or steps is said back in a
    line ("“call” could be Call Ryan or Call Mum: say which"), not
    guessed**. A card's question would be better and is in the backlog.
23. **Reminders are booked one occurrence at a time** as engine jobs with
    a run key; each claimed in `nudges_fired` before it is posted, which
    is what makes "never twice" hold across a retry and a restart.
24. **"Late" means the bot was off**: time the dev clock jumps over is
    not counted, as for every job.
25. **The reminders card has no buttons**: nothing on it can be done
    before its time; what goes off carries Done and Snooze.
26. **Personal routines tick by a button for each routine's next step**
    (question 63), and a routine is at most twelve steps.
27. **What's new lines are kept under 7:30 am of their day**, outside the
    night the briefing lists as held back, so live's code from before
    them never shows them as alerts.
28. **Help leaving out a task whose switch is off is done by not loading
    it at all**, which also keeps it out of #commands, the router, its
    jobs and its cards.

## Overnight, 2026-10-15: the reboot

**Windows Update restarted the EliteDesk twice** (00:23 and 00:26). The
night's batch stopped part-way, with the round 3 design built but not
committed. Live came back by itself at 00:26, as its own account, on
the working copy (those uncommitted changes, with `CARDS_V2` still off,
so the old look). The 6 am routine ran in full and the briefing posted.
The 3 am self-test ran on the same working copy, whose phase 5 still
looked for the old briefing's words: five steps failed and it opened
D6 and re-opened D3. Not a fault of the bot. Fixed in the self-test's
checks the same morning. That live can load unreviewed work on a
reboot is now in `docs/BACKLOG.md` (Next, 5).

## Decided (2026-10-15, round 3 of the design)

Choices the prompts did not settle. Each is yours to overturn.

1. **A box is a Components V2 container, not an embed**, as the cards
   already were. So Discord's limits are those of Components V2 (40
   components and 4,000 characters a message), not 10 embeds and 6,000.
2. **The most urgent state, for a box's edge**: destructive, risky,
   due, any time, missed, decision, done, quiet. A miss makes a box red
   only when nothing in it is left to do, as the rule for a pill was.
3. **The day's total stays in the briefing's title** (R3-A, as built),
   with the date small under it: question 45 is still yours.
4. **The briefing's pills box is a summary** (the next dose, the
   streak, the line about yesterday), not each pill: the pills card
   right under it lists each one.
5. **The weather is the first task box in the briefing**: a box that
   counts nothing sets the scene, then the counted tasks in the
   ranking's order. No task is named in code for it.
6. **A time still to come has "in 2 hours" after it; one gone by has
   not.** An overdue dose reads "dose 2 · due **11:04 am**".
7. **A pill with only a miss left stays an item** ("missed · was due
   **9:00 am**", no buttons), after any time; it is not folded into
   the small line, which holds what is done, paused or not today.
8. **Every dose still to take keeps its buttons**, coming up included:
   taking one early is allowed, and asks first when too soon. When a
   card would not fit, the buttons go first and the next dose due
   keeps its own.
9. **Lists** (my pills, the week, a day looked back on, open bugs, my
   schedule) **are one box with a rule between items**, the edge the
   most urgent state in it. Statuses per item are no longer colours;
   each item keeps its mark (✅ ❌ ⏭️).
10. **A change is drawn only for the one format, `field · old → new`.**
    "**Iron** → removed" has no field and is left as it is.
11. **Times a task writes in code** (in summary lines shared with the
    old look) **are drawn bold**, so the old look is untouched.
12. **The hub's order was already briefing, then the pills card**, as
    the 6 am routine posts them, with what comes later under them. With
    no gym or to-dos card yet, nothing was changed for the order.
13. **The status line is unchanged.**
14. **The look before round 3 is "round 1"** (rounds 2 and 3 were
    sketches until now) and stays one setting away: `DESIGN_ROUND=1`.
    Proved by running the old tests against it: all passed but two that
    looked at a function that moved.
15. **The preview's made-up morning is 7:30 am**, when you are likely to
    look: its "in 2 hours" are real Discord timestamps, so they read
    right then and drift after.
16. **The self-test's phase 3 and 5 checks** now read the round 3
    wording (one box a topic, `### 💊 Pills ●○○ 1/6`, `~~old~~ →
    **new**`).

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
32. **An open card takes only what could answer or change it** (your
    answer, the same afternoon): a question typed while a card is
    open goes to the router, and the card stays open and answerable
    (golden 28, 28a, recorded from the real API, 4 of 4, NZ$0.03).
    A new request for the card's own task ("took my zinc" with a
    pills card open) is still done by that task without the router,
    as before: it already leaves the card as it is. After the
    answer, a typed answer to the card goes by the router, which is
    shown the card; a reply to the card or its buttons go straight
    to it.
33. **No self-test step for it**: a step's one recorded answer is
    given to every task that reads the message, so the step could not
    tell the old behaviour from the new. Golden 27 and 27a are
    recorded from the real API.
34. **The `end-of-task` skill was reordered** to match the new rule:
    docs, then the full test run, then the commit.

## Where things stand

- **Branch `feature/pills`**: everything is committed and pushed;
  nothing is merged into `main`.
- **Live** was last restarted at 8:59 am on 2026-10-15, on the round 3
  commit, with `CARDS_V2` on: the hub is in the round 3 look. Before
  that, Windows Update had restarted the PC twice (00:23 and 00:26) and
  live came back by itself on the working copy. Nothing needs a look.
- **The morning routine ran as booked on its first morning** (live's
  run log, 2026-10-14): the exchange rate, the weather fetch, the tidy,
  the briefing, the checklist, and a needs-a-look check with nothing
  to say.
- **Tests**: offline 2889 passed, 1 skipped, in about 40 seconds. The
  last full self-test (2026-10-15, 8:44 am, the dev bot with live up,
  recorded answers): 122 of 123, none failed, one skipped for needing
  real requests; it marked D6 and D3 fixed. The golden
  conversations asked of the real API: 57 of 59, the two misses old
  known ones that the code puts right; 27, 27a, 28 and 28a recorded
  since, 9 of 9.
- **Spend on the day's batch**: NZ$1.10 (US$0.62), all of it live
  evals; the dearest run NZ$0.23. The self-test's month (NZ$3.50) is
  spent: recorded answers until November.
- **Bugs**: 2 open on live (`bugs`), both from before 12 Oct. The
  self-test's D6 and D3 (3 am, its own checks behind the new look) are
  marked fixed by its 8:44 am run.

## Switched on (live's `.env`)

- **On**: `CARDS_V2` with `DESIGN_ROUND=3` (since 2026-10-15, 8:59 am), `BRIEFING_ENABLED`, `DAY_PROGRESS`, `DAY_QUESTIONS`,
  `WEATHER_ENABLED`, `HUB_TIDY`, `REMINDERS_ENABLED`,
  `QUIET_HOURS_ENABLED` (10:00 pm to 7:00 am), `NIGHTLY_SELFTEST`.
- **Off**: `WEEKLY_SUMMARY`,
  `DMS_ENABLED`, `NOTIFY_NTFY` (nothing goes to ntfy).
- **Each day**: midnight the end of the day; 3:00 am the backup and the
  nightly self-test; 5:30 am the exchange rate; 5:50 am the weather
  fetch; 6:00 am the morning routine (tidy, briefing, checklist);
  7:00 am the needs-a-look check; 8:50 am the weather refresh, then
  every three hours to 8:00 pm.

## Waiting on you

1. **The round 3 look, on your phone**: the hub itself, and "Round 3
   built" in the design-options post. Reply there with what to change;
   it goes into `docs/DESIGN-LOG.md` word for word as round 4.
2. **The new hub tasks**: the "New hub tasks preview" in the same post,
   questions 51 to 66, and which to switch on first.
3. **The other questions**: `docs/QUESTIONS.md` has 61, each with a
   suggested answer ("yes to all suggestions except 4 and 7").
4. **Gym and the calendar** wait on their answers there (23 to 28, 29
   to 32).
5. **The merge** into `main`, then live's own folder (33, 34).

## Next

In the order of the priorities; the full list is `docs/BACKLOG.md`.

1. **The hub's look**: round 4 from your feedback on round 3 (the design
   loop, `docs/DESIGN-LOG.md`), and #commands' words for the buttons.
2. **The new hub tasks**: switched on in the order you choose, with
   self-test steps for each, after your answers to 51 to 66.
3. **What the briefing shows**: whatever your look at the hub turns
   up; the answers about your day, once you have read a few.
4. **Understanding**: the two golden conversations that failed once
   near midnight (question 39); a correction straight after Save for
   schedules (question 8); task ties asked too often (G4).
5. **Then**: the merge and live's own folder (so a reboot never loads unreviewed work); gym once its answers are
   in; the calendar after its four; a flavour status line (backlog).

## Standing

- Nothing is added unasked. New tasks are allowed (gym is next), spec
  and sketches first. Timers are frozen and may be scrapped.
- Open questions are `docs/QUESTIONS.md` and nowhere else.
