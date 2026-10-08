---
name: add-task
description: Add a new task (feature) to the bot, or add a word, reply action, reaction, job or table to an existing one. Use when creating or extending anything under tasks/.
---

# Add or extend a task

The walk-through with code is "How to add a task" in `docs/DEVELOPMENT.md`;
read that section rather than exploring. `tasks/keep/` is the smallest
complete example, `tasks/archive/` the pattern for anything with logic.

## Steps

1. **Folder:** `tasks/<name>/__init__.py` with a `Task` subclass (`name`
   equal to the folder name, a `description`) and one instance called
   `task`.
2. **Ways in**, in order of preference: a `Keyword` (typed word), a
   `ReplyAction`, a `Reaction`. Slash commands and menus are a fallback only.
   Every registration needs `description`, `examples`, `channels` and a
   `permission` (the default is fine). Use `exact=True` for anything
   destructive. Claude runs words and reply actions as tools, so write the
   description for it too, list the arguments of a word that takes any as
   `params` (`Param`, in typed order), and give a reversible reply action
   an `undo`.
3. **Split the logic from Discord:** decisions go in a module with no
   Discord calls (`rules.py`), records in `store.py`, and the handler calls
   them. Only `lab`, `archive`, `timers` and `dev` may use discord.py
   directly; other tasks use `Context` and core helpers such as
   `core/pins.py`.
4. **Handlers:** lasting output with `ctx.reply`, a "done" with
   `ctx.confirm`; raise `UserError` for problems the user can fix. Never
   post a failure note in the channel: the registry adds ⚠️ and logs it.
5. **Reactions:** give a non-destructive one an `undo`; set
   `destructive=True` when the message won't exist afterwards.
6. **Before archiving, deleting or clearing a message**, check
   `core.protection.is_protected` and ask with `core.confirmations.ask`.
7. **Database:** migrations from `Task.migrations()`, append only, tables
   prefixed with the task's name, every record with a `user_id`. Always
   `await` database calls (`ctx.db.run(func)`).
8. **Jobs:** book with `scheduler.add_job`, handle in `job_handlers()`,
   cope with `job.is_late`. Moments in UTC; schedules as local time +
   `Pacific/Auckland`.
9. **Buttons and forms:** answer within 3 seconds (defer first if slow),
   then log. Persistent buttons need stable `custom_id`s and are registered
   in `setup`. Reply from error handlers with `safe_reply` and
   `report_interaction_error`.
10. **Settings:** a new `.env` setting gets a placeholder in `.env.example`.
    If `ENABLED_TASKS` is set in `.env`, tell the user to add the new name.

## Before finishing

- Tests for the new logic in `tests/test_<name>.py` (plain pytest functions).
- A new task changes `tests/test_registry.py`: the loaded-tasks list and
  the `help` overview headings.
- `docs/TESTING.md`: 🤖 rows for the logic, 👤 rows as ⬜ Untested; add the
  manual ones to `docs/QA-RUN.md` (see the `qa` skill).
- `docs/ARCHITECTURE.md`: a line for each new file and table.
- `docs/DEVELOPMENT.md`: how to use the feature, if the user needs to know.
- Then follow the `end-of-task` skill.
