---
name: task-check
description: Audit one task against the conversation standard (docs/CONVERSATION.md), the task contract, the core-or-task rule and the ban on reading wording in Python. Reports pass or fail for every item with file and line, and writes a QA block where every step says what to press. Use after building or changing a task, or when the user asks to check one (e.g. "task-check pills"). It reports; it fixes nothing.
---

# Task check

Audit **one task**. Fix nothing: the user chooses what to fix.

## Read first

- `docs/CONVERSATION.md`, whole.
- The Scaling notes in `docs/ARCHITECTURE.md`.
- The task: every file in `tasks/<name>/`, its spec in `docs/specs/` if
  it has one, its tests, and its fixtures in `evals/fixtures/`.
- The core it leans on, where a rule is met there and not in the task
  (the table "Where the standard lives in the code" in `CLAUDE.md`).

## How to judge

- **Evidence or it isn't a pass.** Each item gets `file:line` of the
  code that meets or breaks it, and the test that proves it if there is
  one. No line to point at means "not shown", which is reported as a
  fail of the check, not assumed.
- **Pass, fail, gap or n/a.** *Gap* is for something the standard asks
  that is on the gap list in `docs/BACKLOG.md` (G1, G3, G4, G7, G14):
  name the gap. *n/a* says why in a few words.
- What core does for every task (the 👀, the outgoing check) is checked
  once and marked "core"; look only at whether the task bypasses it
  (its own `channel.send`, its own buttons).
- Run the task's tests and the golden conversations that involve it
  (`python -m pytest -q tests/test_<name>*.py tests/test_golden.py`),
  and its replayed fixtures (`tests/test_routing.py`). Don't run a live
  eval.

## What to check

**A. The standard, item by item** (`docs/CONVERSATION.md`)

1. Each of the ten principles of section 2, in order.
2. Each context rule of section 3.
3. Each card rule of section 4, for every card the task shows: first
   line, interpretations written out, ❓ and ⚠️, old → new, questions
   on the card, Save / Cancel and "can't be undone", only what applies
   is offered, a correction replaces the card, "No, …", just after
   Save, expiry.
4. **Button colours**, for every button the task has, wherever it is
   made (`core/cards.py` records and discord.py views): green the
   positive main action, red destructive, blurple every other choice,
   grey Cancel only (`cards.colour_problem`).
5. Each always / never line of section 5. Search the task's strings for
   24-hour times, action names, "reply ok", offers ("want me to",
   "would you like"), and questions sent as their own message.
6. **Housekeeping leaves no trace**: for anything the task does that
   deletes, archives, pins, unpins or resets, one line that goes
   (`housekeeping=True`, `core/tidy.py`), the word deleted, #bot-log
   the record. And pointer lines go by themselves (`tidy.pointer`).
7. The golden conversations of section 6 that involve the task: which
   pass, which are gaps. Propose new ones for what the task adds.

**B. The task contract** (`core/actions.py`, `actions.problems`)

- "Only for" line: says what it is for and what it is not; no phrase
  another task's line also claims (read them all).
- Examples: two or three, real phrases, none a trap for another task.
- `identity` and `on_repeat` declared, and the code does what they say:
  adding what is there goes through `core/repeats.py`, and "already so"
  has one line however it was found (`Task.already_so`).
- Schemas: every field described; a length is `MINUTES`, a time `TIME`
  or `TIMES`, anything that could be plural is `ITEMS`, a change is
  add / set / remove, a reference is `@that`. No field asks Claude for
  a sum, a date worked out, or which thing a pronoun means.
- Templates: every word shown is written by the task's code, every
  action that saves has `prepare`, `apply` and `verify`, and a direct
  action re-reads what it changed before saying so.
- Ways in: each keyword, reply action and reaction has a description,
  examples, channels and permission; a typed word carries the task's
  name; destructive words are `exact`; `purpose`, `say` and `buttons()`
  are filled in for #commands, with placeholder names only.
- Fixtures: each action has extraction fixtures and the task has router
  fixtures, traps included; say which are not recorded.

**C. Core or task** (Scaling notes)

- Anything in the task that is how the bot behaves or talks, or
  plumbing, or a general tool a second task would need: name it with
  file and line and say where it belongs.
- discord.py in a task that may not use it; a Context in `plain.py`;
  the clock, the day or a time format taken from anywhere but core.

**D. Word lists and phrase patterns in Python**

- Search the task for regular expressions, word sets, `in (` / `in {`
  checks on text, `.startswith` / `.endswith` on what the user said,
  and string comparisons with words.
- For each: what it reads, why it is there, and whether it is a safety
  net (it checks what Claude returned, or reads a typed word) or the
  way something is understood (a fail: the fix is a field in the
  schema). Compare with the table in `docs/BACKLOG.md`; report any that
  is not listed there.

## The report

For the user, in the reply (not a file):

1. One line: the task, how many items passed, failed, are gaps.
2. A table for each of A to D: item, result, evidence (`file:line`),
   and for a fail what would change, in which layer (task, core,
   prompt, fixture) and how big (small, medium, large).
3. The failures again as a list, most important first by the
   standard's own priority order.

Don't fix anything, and don't soften a fail because it is known.

## The QA block

Add a block to `docs/QA-RUN.md` for the task (follow the `qa` skill for
the tracker rows in `docs/TESTING.md`):

- It starts with `dev clock reset` on its own line under the heading.
- It says which database (`--dev` for anything with test data) and what
  must be set up first.
- One step for each golden conversation of the task and each card,
  reply and button it has; a retest step for each fail once it is
  fixed.
- **Every step says what to press**, or "press nothing", and what to
  expect in the bot's own words.
- A step that needs special setup stays in as optional and says to
  report it as a skip.
