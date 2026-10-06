# Decisions

A short log of key decisions and why. Newest at the bottom.

- **Discord as the interface:** free bot API, buttons and channels, great
  mobile app. Gateway layer keeps other platforms (e.g. Telegram) possible.
- **Python:** strongest ecosystem for data, documents, voice and scheduling.
- **Claude API, not a local model:** the server can't run a capable model;
  Haiku keeps costs low. API billing is separate from the Pro plan.
- **SQLite:** zero maintenance, single file, enough for a handful of users.
  Move to PostgreSQL only if many users.
- **Self-hosted on a home mini PC:** free, private, always on. Docker and a
  VPS are the path if it ever needs to move.
- **NSSM for the Windows service:** simple, auto-start, auto-restart.
- **Core + skills architecture (modular monolith):** scales in features
  without distributed-system complexity.
- **Multi-user ready, single-user deployed:** `user_id` everywhere and one
  permission check, nothing more until real users arrive.
- **Notifications:** Discord first, three urgency levels, quiet hours,
  batching. Pushover considered later for must-not-miss nudges.
- **Inbox hygiene:** nightly sweep with transcripts and a journal summary;
  📌 reactions exempt messages. Reactions use a global 45s debounce.
- **Dates:** Claude interprets phrases; code calculates dates using
  recurrence rules (RRULE) and `Pacific/Auckland`.
- **Migrations as numbered Python functions with `PRAGMA user_version`:** no
  extra tool or tracking table, and Python can backfill data as well as
  change the schema. Each runs in its own transaction; a snapshot of the
  database is taken before any upgrade.
- **`asyncio.to_thread` with the standard `sqlite3`, not aiosqlite:**
  aiosqlite is a thread wrapper too, so this gives the same result with no
  new dependency. One connection per call keeps it thread-safe; revisit if
  query volume ever makes connection set-up noticeable.
- **`OWNER_ID` in `.env` is the source of truth for the owner:** the owner
  row is ensured at every startup and anyone else marked owner is demoted.
  All checks go through `is_allowed(user, action)`.
- **`message_log.user_id` is nullable in the schema:** SQLite cannot add a
  `NOT NULL` foreign key column without rebuilding the table. The code
  always fills it, and existing rows were backfilled with the owner.
- **Backups with SQLite's backup API, nightly at 3am NZ, keep 7:** safe
  while the bot is running, unlike copying the file. Same disk only, so it
  protects against mistakes and corruption, not against losing the server.
- **Small in-memory scheduler for now:** daily jobs at a fixed NZ time, no
  catch-up for runs missed while the bot is down. To be replaced by stored
  schedules with recurrence rules when reminders arrive.
- **A skill is a package in `skills/` exposing a `skill` object:** found by
  scanning the folder, so adding a feature needs no edits to the core.
  `ENABLED_SKILLS` in `.env` narrows the list; empty means all.
- **A skill that fails to load is skipped, not fatal:** the bot runs 24/7,
  so one broken feature should not take the rest down. Problems are shown
  in the terminal and on the start card in #bot-log.
- **Per-skill migration versions in a `skill_migrations` table:**
  `PRAGMA user_version` can only hold one number, which stays with the core.
  Skill tables are prefixed with the skill's name.
- **Skills get a `Context`, not a `discord.Message`:** first step towards
  the gateway layer. Buttons still use Discord's view class directly until
  the confirmations work.
- **Commands match the whole message exactly, for now:** keeps "ping me
  tomorrow" going to Claude. Arguments wait for the tool-calling stage.
- **Slash commands synced to one server, found from the inbox channel:**
  server commands update instantly (global ones can take an hour) and no
  extra setting is needed. Each start replaces the full list, so a disabled
  skill's commands disappear.
- **The lab skill may use discord.py directly:** its job is to try out what
  Discord can do before the gateway layer is designed, so hiding Discord
  from it would defeat the point. Real skills still go through the context.
- **One global debouncer per use, not one timer per message:** matches how
  reactions come in (a burst across several messages) and lets the handler
  see the whole burst at once. The delay is set where it is created.
- **Archiving reposts through a webhook, then deletes:** a webhook is the
  only way to show the original author's name and avatar. The gesture (menu
  item or 📦 from the owner) counts as the confirmation for the delete, and
  the delete only happens once the copy, with every attachment, is posted.
- **A watchdog for unanswered buttons:** discord.py silently drops a press
  it has no handler for, and Discord just says "interaction failed". After
  2 seconds without an answer we log it, post a card and tell the user,
  so a dead button is never a mystery.
- **Persistent views are registered in `setup_hook`, not `on_ready`:** it
  runs before the bot connects, and does not depend on the slash command
  sync succeeding first.
- **Two chart renderers kept side by side in the lab:** QuickChart needs no
  heavy dependency but sends the numbers to a third party and can be down;
  matplotlib is local and private but large. Pick one when a real skill
  needs charts. Two measures get two charts, never one chart with two axes.