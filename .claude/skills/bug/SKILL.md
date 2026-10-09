---
name: bug
description: Fix a reported bug. Use when the user gives a bug id (e.g. "B4", "/bug B4") or pastes an exchange with the bot that went wrong - read what was captured, write a failing test that reproduces it, fix it, update TESTING.md and BACKLOG.md, and record "fix ready, needs retest" in the bug's notes.
---

# Fix a bug

Bugs are reported in Discord (🐞 or `bug`) and kept in the database with
what was captured: the message, the five before it, the turn's tool calls,
timings and log errors, the commit, and the notes written in the bug's post
in #bugs. `tasks/bugs/cli.py` reads them without starting the bot, and is
safe to run while the bot or the service is running.

## 1. Read it

- **A bug id:** `.\.venv\Scripts\python.exe -m tasks.bugs.cli show B4`
  (`list` shows the open ones). An id starting with D (`D4`) is a bug of
  the dev database: add `--dev` to every command for it (`show D4 --dev`,
  `note D4 "…" --dev`). Read all of it: the notes often say what
  was expected, what happened instead and whether it has happened before.
- **A pasted exchange:** work from the paste. There is no record to read
  or to add a note to; say so in the summary.
- Compare the report's commit with `git log --oneline -1`. If the code has
  moved on, check the fault is still there before fixing it.
- If what was captured isn't enough to tell what went wrong, say what is
  missing and ask. Don't guess at a fix.

## 2. Reproduce it with a failing test

- Find the decision that went wrong (`docs/ARCHITECTURE.md` is the map).
  Logic lives in modules with no Discord calls, so the test calls that.
- Write the test in the matching `tests/test_*.py`, named for the
  behaviour that should hold, with the bug id in a comment.
- Run it and see it fail for the reported reason:
  `.\.venv\Scripts\python.exe -m pytest tests/test_<area>.py -q`. A test
  that passes before the fix reproduces nothing: fix the test first.
- If the fault is in Discord-facing code that can't be unit tested, move
  the decision into a pure function and test that. If that isn't
  possible, say so and add a 👤 Manual row instead.

## 3. Fix it

- The smallest change that makes the test pass and follows `CLAUDE.md`.
- Run the whole suite: `.\.venv\Scripts\python.exe -m pytest -q`.
- Never start `main.py` to check: the user's copy or the service may be
  running.

## 4. Record it

- `docs/TESTING.md`: a 🤖 row for the new test (✅ Pass, today's date, the
  test file, the bug id in Notes), and reset the feature's 👤 rows that
  the fix affects to ⬜ Untested. Recount the summary. Mirror manual
  changes in `docs/QA-RUN.md` (see the `qa` skill).
- `docs/BACKLOG.md`: add the bug under "Fixed in code, waiting for a
  manual retest" (the bug id, what changed, which rows to retest), and
  remove any item this fixes.
- The bug's notes, so `bugs` shows it as ready:
  `.\.venv\Scripts\python.exe -m tasks.bugs.cli note B4 "fix ready, needs retest: <what changed, and how to retest it>"`

**Never mark a bug fixed.** There is no command for it on purpose: the
user retests in Discord and presses **Fixed** or **Won't fix** on the
bug's post.

## 5. Finish

Follow the `end-of-task` skill. In the summary, say which bug, what the
cause was, the test that now covers it, and exactly what to retest in
Discord before pressing Fixed (the fix is not live until the bot is
restarted).
