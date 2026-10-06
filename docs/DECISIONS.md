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