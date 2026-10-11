---
name: new-task
description: Design and build a new task (feature) for the bot - interview the user, settle the task contract, write the spec to docs/specs/ and wait for approval, then build it with fixtures and run task-check. Use when the user asks for a new task, or for a new way of talking to an existing one (a new action, list or card). For a single word, reply action, reaction or job on an existing task, read "Extending a task" below.
---

# New task

A task is built in this order, and nothing is built before the spec is
approved. Read first, every time:

1. `docs/STATUS.md`: the scope freeze. If it forbids new tasks, say so
   and stop unless the user has just asked for this one as an exception.
2. `docs/CONVERSATION.md`: the standard every task follows.
3. The **Scaling notes** in `docs/ARCHITECTURE.md`: core or task, and
   what Claude does and what Python does.
4. "How to add a task" and "Routing and confirm cards" in
   `docs/DEVELOPMENT.md`; `tasks/timers/` (acts at once) and
   `tasks/pills/` (cards) are the worked examples.

## 1. Interview

Ask, a few questions at a time, in the user's words. Don't propose a
design yet, and don't ask what the standard already answers (how cards
look, how corrections work).

**What it is**

- What do I tell it?
- What does it tell me?
- Where does that come from (what I said, a schedule, something it
  works out, somewhere outside)?
- When (straight away, at a time, when something happens)?

**One real use, start to finish**

- The moment: where am I, what has just happened?
- What I'd say, in my own words. Collect at least six real phrases,
  brief ones and specific ones.
- What happens then, exactly as I'd see it.
- Afterwards: what do I ask or change later? What if I got it wrong?
- Boundaries: what is it **not** for? What sounds like it and belongs
  to another task, or to none?

## 2. Settle the contract

Write each of these down and read them back before the spec.

- **Name and icon.**
- **The "only for" line**: what it is for and what it is not, in a
  sentence or two. It is all the router knows of the task.
- **Examples**: two or three phrases, the user's own.
- **Actions**, each with:
  - what one would say for it, and its fields. A field Claude fills in
    is structured: whole minutes (`actions.MINUTES`), a time in the one
    form (`TIME`, `TIMES`), a list of items (`ITEMS`) for anything that
    could ever be plural, add / set / remove (`change_field()`). Dates
    come as said. If code would have to read wording, add a field
    instead.
  - whether it needs a card (anything that changes setup) or acts at
    once (logging, questions, showing), and how the change is read back
    (`verify`).
  - its group in #commands (`purpose`) and what one might type (`say`,
    with placeholder names only).
- **Identity**: which fields make two items the same thing. None, if
  each is its own.
- **On repeat**: what asking to add one that is already there means:
  `update`, `add_to_amount`, `allow_another`, or `ask` (not available
  until cards can ask: `core/repeats.py`).
- **Rules**: limits, what can't be saved, what is fixed with a ⚠️ and
  what is asked, what is private (a name that must never show in a
  notification).
- **Card layouts**: each card as text, first line "icon Name · new |
  change | remove", a change as `field · old → new`, the buttons with
  their colours. Sketch one in `docs/mockups/<name>.txt` and post it
  with `dev mock <name>` if the layout is new.
- **Shown on request**: what its name on its own shows (the `show`
  action), as a Live list.
- **Typed words, reply words, reactions, buttons**: only what will be
  used daily; a typed word carries the task's name.
- **Unique logic**: whatever only this task does.

## 3. Check before writing

- **Overlap.** Read every loaded task's "only for" line and examples
  (`python -c "import tests; from tasks import registry; registry.load();
  from core import actions; [print(e.name, '|', e.only_for, '|',
  e.examples) for e in actions.catalogue()]"`). Name any phrase the new
  task and an existing one could both claim, and settle it in the two
  "only for" lines.
- **Core or task** (Scaling notes, in their order): how the bot behaves
  or talks → core; plumbing → core; knowledge about one subject → the
  task; a general tool → core if clearly general, otherwise a module of
  its own inside the task. Anything about time (when, how often, which
  days) comes from core (`core/schedule.py`, `core/occurrences.py`,
  `core/day.py`). List what would go into core and ask before adding it.
- **The standard.** Go through `docs/CONVERSATION.md` section by
  section against the design. Anything the design can't meet yet is
  named as a gap, not worked around.

## 4. Write the spec and wait

Write `docs/specs/<name>.md` (private: never committed, never quoted in
commits or public docs): purpose, the contract as settled, every action
with its fields and examples, rules, card layouts, the task's own golden
conversations (what I say or do → what should happen), what goes in
core, what is out of scope, and the build order with a pause for QA
after each stage.

Then stop. **Build nothing until the user approves the spec.** List
separately anything in it that the user didn't ask for.

## 5. Build

- `tasks/<name>/`: `__init__.py` (the `Task`: `icon`, `only_for`,
  `examples`, `identity`, `on_repeat`, `show`), `plain.py` (the
  `Action`s and their code, taking a `Request`, never a Context),
  `rules.py` (pure: decisions and every word), `store.py` (records,
  migrations; tables prefixed, every record with a `user_id`). No
  discord.py: cards are `core/cards.py`.
- Every action that saves has `prepare`, `apply` and `verify`. Matching
  what is already there goes through `core/repeats.py`.
- **Fixtures in the same change**: router and extraction fixtures in
  `evals/fixtures/<name>.json` (each phrase from the interview, and the
  traps from the overlap check), and the task's golden conversations in
  `tests/test_golden.py`. Record them live only at a pause, and ask
  first for a run over US$0.25.
- Tests for the logic (`tests/test_<name>_rules.py`, `_plain.py`);
  `tests/test_registry.py` (the loaded tasks) and the #commands test
  change with a new task.
- A new `.env` setting gets a placeholder in `.env.example`.

## 6. Check and close

- Run the `task-check` skill on the new task and fix what fails before
  asking for QA.
- Then the `end-of-task` skill.

## Extending a task

For a typed word, reply action, reaction, job, button or table on a task
that exists: read "How to add a task" in `docs/DEVELOPMENT.md`, keep the
logic apart from Discord, add tests in the same change, then run
`task-check` on that task and follow `end-of-task`. A new action in
plain words, or a new card, is a design change: go through steps 2 to 4
for that part.
