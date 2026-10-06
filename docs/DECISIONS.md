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