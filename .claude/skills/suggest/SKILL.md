---
name: suggest
description: Rerun the brainstorm of what the bot could do for Alex (docs/BRAINSTORM.md) with the wishlist (what live could not do) and recent usage, then propose the next things to build. Run on Sundays, or when Alex types /suggest.
---

# Suggest

Mostly read only: the one file written is `docs/BRAINSTORM.md`, and the one
post a reply in "Design · Brainstorm". No restarts, self-tests or requests
to the bot's own Claude. Never print a token, a topic, a link, an id or a
bot's display name. No em dashes, UK spelling. Use the `.venv` Python and
read live's database read only (`file:...?mode=ro`).

1. **The wishlist.** From live's folder (`..\assistant-bot-live`), read the
   wishes since the last brainstorm: `SELECT created_at, task, why, summary
   FROM wishes ORDER BY id` (core/wishes.py). They hold the task and why in
   the code's own words, and Alex's own words only for one he added. Group
   them by task and why; count each.
2. **Recent usage.** From live's `message_log`, the last 14 days: how many
   messages each task took (`tasks`), and how many ended in a decline, a
   not understood or an error (`status`, `reply` starting with 🤔 or 🤷).
   Counts only: never copy a message's words into the brainstorm (the
   diary's are never there, and a pill's or an event's name must never be).
3. **The brainstorm.** Read `docs/BRAINSTORM.md` and `docs/ADVISOR.md`
   (sections 2, 3 and 9). For each group of wishes: does an idea cover it?
   Raise its value if so; add a new idea if not (what it does, how he
   would use it, value 1 to 5, effort S, M or L, what it needs from him).
   Drop or lower ideas Alex has said no to (his replies in "Design ·
   Brainstorm", read as the dev bot over HTTP, as `selftest/preview.py`
   reads a round's replies).
   Respect the limits at the top of the file: Discord, the EliteDesk,
   privacy, low cost, nothing that nags; no ideas inbox, no uni deadlines.
4. **The top 10** again, by value for effort, as the table at the end.
   Update "Written" at the top with today's date and what changed.
5. **Report** to Alex in a few lines: the wishes this time (counts by
   task), what moved in the top 10 and why, and one question: which to
   build next. Post the same as a reply in "Design · Brainstorm" only if
   he asked for it in this run.
6. Commit only when asked, after the full test run (docs are tested).
