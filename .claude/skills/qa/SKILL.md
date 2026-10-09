---
name: qa
description: Keep the test tracker and the manual QA run sheet right. Use when the user reports manual test results (e.g. "A1 pass, A2 fail: reason"), when a change adds or affects tests in docs/TESTING.md, or when docs/QA-RUN.md needs updating or regenerating.
---

# QA: test tracker and run sheet

- `docs/TESTING.md`: every test, grouped by feature (A, B, …), each with an
  ID, a type, a status, a date and notes, and a summary table at the top.
- `docs/QA-RUN.md`: one ordered pass through the 👤 Manual tests, in blocks
  that share setup.

🤖 Auto rows are logic covered by pytest (Notes names the test file).
👤 Manual rows are only for Discord-facing behaviour.

## When code changes

- A new feature adds rows: 🤖 for its logic (✅ Pass with today's date once
  `python -m pytest -q` passes), 👤 as ⬜ Untested.
- A change to an existing feature resets that feature's 👤 rows to
  ⬜ Untested and sets its 🤖 rows from the pytest run.
- Recount the summary table (per group and the total) and set "Last
  updated".
- Mirror manual changes in `docs/QA-RUN.md`: put each new test in the block
  whose setup it shares, keep the expected result identical to TESTING.md,
  renumber the block's steps and fix any "step N" references, and update
  the block table (tests, minutes) and the total in the first line.
- A test that can't be run in a normal pass (needs special setup) stays in
  the sheet as an optional step that says to report it as a skip.

## When the user reports results

For input like `A1 pass, A2 fail: reply came twice, K3 skip: no second
account`:

1. Update each row in `docs/TESTING.md`: status (✅ Pass, ❌ Fail,
   ⏭️ Skipped), today's date, and the reason in Notes.
2. Recount the summary table and set "Last updated".
3. Copy every failure into `docs/BACKLOG.md` (create it if it doesn't
   exist): the test ID, what was expected, what happened, the date.
4. Reply with the new totals and the list of failures. Don't start fixing
   them unless asked.

## Running things

- Never start `main.py` while the user's own copy or the service is
  running, and never leave a bot process behind. Check with
  `python -m core.instance_lock`, which asks the lock and says how many
  bots are running (a raw process list shows one bot as two `python.exe`
  lines: the `.venv` launcher and its child).
- Manual tests are the user's to run; don't mark one passed from reading
  the code.
