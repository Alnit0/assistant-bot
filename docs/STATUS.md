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
14. **Straight after you log a pill, "what's left today?" still shows
    the checklist**: for five minutes a short message goes to the task
    that just answered. Left as the standard has it.
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

## Where things stand

- **Branch `feature/pills`**: everything is committed and pushed;
  nothing is merged into `main`.
- **Live** was last restarted at 11:58 am on 2026-10-14 and runs all of
  it, the morning's work included (one dose is one log, the last-chance
  nudge, retries, #commands edited in place).
- **The first morning of the routine ran as booked** (live's run log,
  2026-10-14): 5:30 am the exchange rate; 5:50 am the weather fetch;
  6:00 am the tidy (nothing to remove), the briefing (posted) and the
  checklist (posted, 3 doses); 7:00 am the needs-a-look check (nothing
  needed a look, nothing said); 8:50 and 11:50 am the weather refresh.
  The 3:00 am backup and the nightly self-test ran too.
- **Tests**: offline 2770 passed, 1 skipped. The last full self-test
  (11:42 am, the dev bot with live up): 116 of 117, one skipped for
  needing real requests. The self-test's month (NZ$3.50) is spent:
  recorded answers until November.
- **Bugs**: 2 open on live (`bugs`). Nothing needs a look.

## Switched on (live's `.env`)

- **On**: `BRIEFING_ENABLED`, `WEATHER_ENABLED`, `HUB_TIDY`,
  `REMINDERS_ENABLED`, `QUIET_HOURS_ENABLED` (10:00 pm to 7:00 am),
  `NIGHTLY_SELFTEST`.
- **Off**: `CARDS_V2` (the hub is in the old look), `WEEKLY_SUMMARY`,
  `DMS_ENABLED`, `NOTIFY_NTFY` (nothing goes to ntfy).
- **Each day**: midnight the end of the day; 3:00 am the backup and the
  nightly self-test; 5:30 am the exchange rate; 5:50 am the weather
  fetch; 6:00 am the morning routine (tidy, briefing, checklist);
  7:00 am the needs-a-look check; 8:50 am the weather refresh, then
  every three hours to 8:00 pm.

## Waiting on you

1. **The short list at the top of `docs/QA-RUN.md`**: ten looks only
   you can take, most useful first (this morning's hub, the design
   sketches, the colours, the status line, the lock screen).
2. **The design picks**, questions 12 to 15, 21, 22 and 45 to 48 of
   `docs/QUESTIONS.md`, with rounds 2 and 3 in the design-options post:
   they are what the new look in the hub waits for.
3. **The other questions**: `docs/QUESTIONS.md` has 43, each with a
   suggested answer ("yes to all suggestions except 4 and 7").
4. **Gym and the calendar** wait on their answers there (23 to 28, 29
   to 32).
5. **The merge** into `main`, then live's own folder (33, 34).

## Next

In the order of the priorities; the full list is `docs/BACKLOG.md`.

1. **The hub's look**: build what you pick in design round 2 (titles
   and rules, the progress marks, a total for the day), then the phone
   check, then `CARDS_V2` on for live and #commands' words for it.
2. **What the briefing shows**: whatever the look at this morning's
   hub turns up.
3. **Understanding**: the two golden conversations that failed once
   near midnight (question 39); a correction straight after Save for
   schedules (question 8); task ties asked too often (G4).
4. **Then**: the merge and live's own folder; gym once its answers are
   in; the calendar after its four.

## Standing

- Nothing is added unasked. New tasks are allowed (gym is next), spec
  and sketches first. Timers are frozen and may be scrapped.
- Open questions are `docs/QUESTIONS.md` and nowhere else.
