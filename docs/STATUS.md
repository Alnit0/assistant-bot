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

## Decided overnight

Nothing since the night of 2026-10-14. That night's 32 choices are in
the archive, each yours to overturn; the ones that ask something of you
are in `docs/QUESTIONS.md`.

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
2. **The design picks**, questions 12 to 22 of `docs/QUESTIONS.md`:
   they are what the new look in the hub waits for.
3. **The other questions**: `docs/QUESTIONS.md` has 44, each with a
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
