---
name: end-of-task
description: The closing checklist for every task that changed code or docs in this repository - run the tests, update CHANGELOG, TESTING and BACKLOG, and give the suggested commit command. Use at the end of every task, before the final summary.
---

# End of task

Do these in order, then write the summary.

## 1. Tests

Run `python -m pytest -q` (from the project root, with the `.venv`
Python). Report passed, failed and skipped counts, and any failure. Never
suggest a commit over a failing run without saying so.

If you started a bot process while testing, stop it and confirm nothing is
left: `python -m core.instance_lock` (it asks the lock, and doesn't count
the `.venv` launcher as a second bot). A bot it reports that you didn't
start is the user's own: leave it running and say so.

## 2. Docs

- **`docs/TESTING.md`** and **`docs/QA-RUN.md`**: follow the `qa` skill if
  the change added or affected tests.
- **`docs/BACKLOG.md`**: add anything found and left unfixed (create the
  file if it doesn't exist); remove items this task fixed.
- **`docs/CHANGELOG.md`**: one entry per task under a `## YYYY-MM-DD`
  heading, newest first (add to the top of today's heading, or start a new
  one), as one to three bullets on what changed for the user. Docs-only
  tidy-ups get one line.
- **`docs/ARCHITECTURE.md`**: update it if a file was added, moved, renamed
  or changed responsibility.
- **`docs/DECISIONS.md`**: add an entry if an architectural choice was made.
- UK spelling in all of them.

## 3. Summary and commit command

Summarise what changed, the pytest result, and anything the user must do
(a new `.env` setting, manual tests to run).

Then run `git status --short` and show its output in a code block, so the
user can check what the commit will include. Point out anything in it that
this task didn't touch.

Finish with the suggested commit as ONE ready-to-paste PowerShell command
in a code block:

- Title: short, present tense, under 50 characters
- Body: 2 to 4 bullet points on what changed and why, each on its own line
- Title and body as two `-m` arguments, each in single quotes; escape any
  apostrophe by doubling it (`''`)
- Start with `git add -A;` when there are new files
- Then `git push` on its own line

Example:

    git add -A; git commit -m 'Add dev mode and test tracker' -m '- Add dev mode with a pinned panel and inspection tools
    - Split archive logic into testable modules
    - Add docs/TESTING.md with Auto and Manual tests'
    git push

Do not commit unless asked.
