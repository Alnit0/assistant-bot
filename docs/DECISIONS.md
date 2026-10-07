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
- **Single-instance lock is an OS file lock, not a PID file or a port:** the
  system releases it when the process ends, however it ends, so there is
  never a stale lock to clean up and a reused PID can't fool it. A port
  could clash with other software. Exit code 3 lets NSSM be told not to
  retry.
- **10062 and 40060 are warnings, not errors:** they mean an interaction
  expired or was answered elsewhere, not that our code is broken. Error
  handlers reply through `safe_reply`, which cannot raise.
- **Words first, slash commands as a fallback:** the `/` key is awkward on
  a phone and the Apps menu is hard to find on desktop. Plain words, reply
  actions and reactions are the main ways in; slash commands stay
  registered and run the same code.
- **The whole message must be the word:** so chat is never mistaken for a
  command ("ping me tomorrow" goes to Claude). This replaces the earlier
  "commands match exactly" rule, adding aliases and arguments.
- **Typos: one letter, words of five or more, never for destructive
  words:** forgiving enough for a phone keyboard, strict enough that `rest`
  can't become `reset`. A corrected match always says what it was read as.
- **Registrations describe themselves; help and Claude read the registry:**
  one source of truth, so `help`, "what can you do?" and the code can't
  drift apart. The cost is a few hundred extra input tokens per chat
  message for the capability list.
- **Reactions are debounced at 15 seconds, not 45:** this supersedes the
  45s in "Inbox hygiene" above. Long enough to undo a mis-tap by removing
  the reaction, short enough that 📦 doesn't feel broken.
- **Archive is its own skill, and delete has no confirmation prompt:** they
  are real features, so they shouldn't vanish when the lab is switched off.
  A typed reply or a 📦 from the owner is the confirmation; `delete` must be
  spelled exactly. The skill uses discord.py directly until the gateway
  layer exists.
- **Commands clean up after themselves, and failures are quiet:** a typed
  word or reply that works is deleted, with a confirmation that removes
  itself, so channels hold content rather than commands. A failure keeps
  the message and marks it ⚠️, with the reason in #bot-log; the cost is
  that a usage mistake has to be looked up there.
- **DMs are reserved for critical alerts and escalation:** a DM is only
  sent for a critical alert, or when a high-priority nudge in the server
  has been ignored. Urgent items use an @mention in their own channel
  instead. A DM is a short pointer with a jump link to the related server
  message, never the content itself, so actions and history stay in the
  server. This refines "Notifications" above; no skill sends real
  notifications yet, so it applies from the reminders work onwards.
- **Claude's conversation history is per channel:** it was one shared list,
  which only worked because Claude chats in a single channel. Keyed by
  channel now, so a future channel with its own chat can't leak into
  another, and `reset` clears just the channel it is typed in.
- **The lab tour and channel test are typed only:** they are driven from a
  phone, where the `/` key is the awkward part, so they get no slash
  command.
- **The scheduler stores its jobs and catches up:** this replaces the
  "small in-memory scheduler" above. Jobs are rows in `scheduled_jobs`, a
  ticker checks every 15 seconds and also wakes exactly for the next due
  job (so a 90-second timer isn't up to 15 seconds late), and anything that
  came due while the bot was off runs at the next start, flagged late. The
  nightly backup is now such a job, so a backup missed at 3am runs at the
  next start. Recurrence is done by a job booking its successor; proper
  recurrence rules wait for the reminders skill.
- **Pomodoro phases wait for Start by default:** a break or focus round
  shouldn't be counted while you're away from the desk. `pomo auto` and
  `POMO_AUTO_CONTINUE` change that; after downtime it always waits.
- **Only completed focus rounds are logged:** a skipped round isn't focus
  time. Stats use NZ days, with weeks starting on Monday.
- **Timers use Discord's live timestamps, not per-second edits:** no rate
  limits to fight, and nothing to keep running between changes.
- **The timers board is exempt from the sweep by being pinned and carrying
  📌:** the sweep doesn't exist yet. When it does it must skip pinned
  messages as well as 📌-reacted ones.
- **Unit tests use the standard library's `unittest`:** no new dependency,
  and logic worth testing is kept in modules that don't need Discord.
- **Interaction rules written down once, for every skill:** `CLAUDE.md` now
  has an "Interaction rules" section (input, reactions, cleanliness,
  notifications, interactions). New work follows it, and it wins over
  earlier entries here where they differ.
- **Rules amended after auditing the existing skills:** the reaction
  debounce is 30 seconds by default (not the 15 or 45 above), as a
  `REACTION_DEBOUNCE` setting. Archive and delete can only be undone by
  removing the reaction within that window; after it, archived copies have
  a Restore button instead. Alerts that must notify may post a new message,
  deleted once acknowledged. Lab tests are exempt from the clean-up rules.
- **Dev mode is held in memory and split in two:** a test setting must not
  outlive the session it was for, so nothing is stored, a restart means off,
  and it expires by itself after an hour. The state is in `core/devmode.py`
  because the registry, scheduler and timers read it; the words, panel and
  tools are a skill (`skills/dev/`) because `help` is generated from skills
  and the core never imports from `skills/`. Callers ask for a value
  (`devmode.reaction_debounce()`) and get the normal one when it is off.
- **Dev speed changes the real wait, not the stated length:** a `25m` timer
  at 60x still says 25m and ends in 25 seconds. Focus rounds finished at any
  speed other than 1x are left out of the stats.
- **pytest runs the tests:** this replaces "unit tests use the standard
  library's `unittest`" above. pytest is one development-only dependency
  (`requirements-dev.txt`, so the server's `requirements.txt` is unchanged),
  and gives parametrised cases, fixtures and plain `assert`. The existing
  `unittest` classes were not rewritten, since pytest runs them as they are.
  No pytest-asyncio: async code is run with `asyncio.run` in the test.
- **Decisions are kept apart from Discord calls:** what can be decided
  without Discord lives in modules that don't call it and is unit tested;
  manual tests in `docs/TESTING.md` are only for what shows in Discord.
  Archive was split into `rules.py`, `store.py` and `messages.py` for this.
- **Two chart renderers kept side by side in the lab:** QuickChart needs no
  heavy dependency but sends the numbers to a third party and can be down;
  matplotlib is local and private but large. Pick one when a real skill
  needs charts. Two measures get two charts, never one chart with two axes.
- **One lifecycle policy decides what is deleted:** deletion was scattered
  (confirmations, command messages, alerts, the panel), so text worth
  keeping could vanish and there was no way to see what had been sent.
  Every message now has one of six classes (`core/lifecycle.py`; the table
  is in `CLAUDE.md`), and the rule is to delete only when the information
  lives somewhere else. Code that deletes by itself asks the policy, which
  is what lets `dev cleanup off` stop all of it. Classes are worked out
  when asked (protection, what the owning skill declares, a short in-memory
  list of transient notes, `message_log`) rather than stored per message:
  no new table, at the cost of `dev inspect` forgetting Transient after a
  restart.
- **Invalid actions are refused at once, with the reason in the channel:**
  this amends "failures are quiet" above. Waiting 30 seconds to learn that
  a 📦 in #bot-log can never work felt broken, and the reason was a trip to
  #bot-log away. A registration may carry a `validate` check; it runs when
  the reaction is added or the reply arrives, and a refusal gets ⚠️ plus a
  short self-deleting reason. Only valid actions are debounced. Failures
  when the action actually runs are still quiet, with the reason in
  #bot-log. The handler checks again, since things can change in the wait.
- **Replies accept filler words; typed words don't:** a reply is already
  aimed at a message, so "pin this" or "please archive it" can only mean
  the action. A word typed on its own must still be the whole message, so
  "ping me tomorrow" keeps going to Claude. Fillers are only tried when the
  message matches nothing as it stands, and never loosen an exact word.
- **Reply `pin` pins natively, without the 📌:** a pinned message is
  already Protected, so nothing more is needed, and a reply should act at
  once rather than wait out a debounce. The 📌 reaction stays as the
  undoable, recorded way to keep a message.
- **Asking for what already exists shows it:** `pomo` with a session
  running re-shows its card rather than failing. An error taught nothing
  the card doesn't, and left a ⚠️ message to clear up by hand.
- **Claude is told it has no tools, every time:** it sometimes offered to
  set a timer or pin something. Until tool calling exists the system
  prompt says so whether or not there is a capability list, and tells it
  to say what to type instead.
- **Tools are generated from the registry, one per action:** this replaces
  "Claude is told it has no tools" above. Every word and reply action
  already describes itself, so each becomes a tool with no second list to
  keep in step; a word adds `params` to say what its arguments are. A tool
  call is turned back into the words a typed command would have and runs
  the same handler through the same `_run`, so logging, permissions and the
  lifecycle rules apply without being written twice.
- **Strict schemas only where they matter, and checked in code anyway:**
  the API takes at most 20 strict tools per request, 24 optional
  parameters and 16 union-typed ones across them. So every argument is a
  required string (empty means "not given"), `strict` goes on the tools
  that take arguments, by `tool_priority`, and every input is validated
  against its schema before it runs whether or not it was strict.
- **Fewer tools per request, by filtering:** the lab is never offered (a
  test bench), dev tools only while dev mode is on or in the dev channel,
  and the rest by channel and permission as `help` is. Fewer tools cost
  less on every message and give Claude less to confuse.
- **Act on a clear request; propose only when suggesting; buttons for
  anything destructive:** two messages for every action would make plain
  speech slower than typing the word. A proposal is a flag on the tool call
  (`propose`), remembered for two minutes and run by a short "ok" without
  another API call. Destructive actions (the `exact` ones) never run on
  Claude's say or on an "ok": only on a Confirm button.
- **A message is only acted on if you replied to it or Claude named it from
  a listing:** a reply always wins. Otherwise Claude must call
  `recent_messages` (the last 20 in the channel) and pass a ref from it, so
  it can't invent a message id; the action then shows the message quoted,
  with Undo where the action declares one, and several possible messages
  become buttons rather than a guess.
- **Five tool calls per message, and tool exchanges stay out of the
  history:** the cap bounds cost and runaway loops. Only plain text is kept
  between messages (with a one-line note of what was done), so trimming the
  history can never separate a call from its result.
- **A manual loop, not the SDK's tool runner:** the runner is a beta helper
  and the loop here is thirty lines; owning it keeps the cap, the logging
  and the "never run a truncated call" rule in plain sight.
