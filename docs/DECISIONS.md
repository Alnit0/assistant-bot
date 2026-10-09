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
- **Core + tasks architecture (modular monolith):** scales in features
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
- **Specs are private, and the backup is their second copy:** `docs/specs/`
  is gitignored, so nothing else holds it. The nightly backup zips it
  beside the database copy and keeps the newest 7; a failed specs copy is
  reported without undoing the database's.
- **Backups with SQLite's backup API, nightly at 3am NZ, keep 7:** safe
  while the bot is running, unlike copying the file. Same disk only, so it
  protects against mistakes and corruption, not against losing the server.
- **Small in-memory scheduler for now:** daily jobs at a fixed NZ time, no
  catch-up for runs missed while the bot is down. To be replaced by stored
  schedules with recurrence rules when reminders arrive.
- **A task is a package in `tasks/` exposing a `task` object:** found by
  scanning the folder, so adding a feature needs no edits to the core.
  `ENABLED_TASKS` in `.env` narrows the list; empty means all.
- **Features are "tasks", not "skills" (2026-10-09):** "skill" now means
  one thing only, a Claude Code Skill in `.claude/skills/`; the two were
  being confused. So `tasks/`, the `Task` base class, `ENABLED_TASKS` (the
  old `ENABLED_SKILLS` is still read when the new one is empty). The
  planned list of things to do is "to-dos", never "tasks". What `dev run`
  runs became "routines", and nothing that holds an `asyncio.Task` is
  named `task`. Names already in the database (`skill_migrations`, the
  `skill` column of `scheduled_jobs`) stay: renaming them means a
  migration for no change in behaviour.
- **A task that fails to load is skipped, not fatal:** the bot runs 24/7,
  so one broken feature should not take the rest down. Problems are shown
  in the terminal and on the start card in #bot-log.
- **Per-task migration versions in a `skill_migrations` table:**
  `PRAGMA user_version` can only hold one number, which stays with the core.
  Task tables are prefixed with the task's name.
- **Tasks get a `Context`, not a `discord.Message`:** first step towards
  the gateway layer. Buttons still use Discord's view class directly until
  the confirmations work.
- **Commands match the whole message exactly, for now:** keeps "ping me
  tomorrow" going to Claude. Arguments wait for the tool-calling stage.
- **Slash commands synced to one server, found from the inbox channel:**
  server commands update instantly (global ones can take an hour) and no
  extra setting is needed. Each start replaces the full list, so a disabled
  task's commands disappear.
- **The lab task may use discord.py directly:** its job is to try out what
  Discord can do before the gateway layer is designed, so hiding Discord
  from it would defeat the point. Real tasks still go through the context.
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
- **Archive is its own task, and delete has no confirmation prompt:** they
  are real features, so they shouldn't vanish when the lab is switched off.
  A typed reply or a 📦 from the owner is the confirmation; `delete` must be
  spelled exactly. The task uses discord.py directly until the gateway
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
  server. This refines "Notifications" above; no task sends real
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
  recurrence rules wait for the reminders task.
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
- **Interaction rules written down once, for every task:** `CLAUDE.md` now
  has an "Interaction rules" section (input, reactions, cleanliness,
  notifications, interactions). New work follows it, and it wins over
  earlier entries here where they differ.
- **Rules amended after auditing the existing tasks:** the reaction
  debounce is 30 seconds by default (not the 15 or 45 above), as a
  `REACTION_DEBOUNCE` setting. Archive and delete can only be undone by
  removing the reaction within that window; after it, archived copies have
  a Restore button instead. Alerts that must notify may post a new message,
  deleted once acknowledged. Lab tests are exempt from the clean-up rules.
- **Dev mode is held in memory and split in two:** a test setting must not
  outlive the session it was for, so nothing is stored, a restart means off,
  and it expires by itself after an hour. The state is in `core/devmode.py`
  because the registry, scheduler and timers read it; the words, panel and
  tools are a task (`tasks/dev/`) because `help` is generated from tasks
  and the core never imports from `tasks/`. Callers ask for a value
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
  matplotlib is local and private but large. Pick one when a real task
  needs charts. Two measures get two charts, never one chart with two axes.
- **One lifecycle policy decides what is deleted:** deletion was scattered
  (confirmations, command messages, alerts, the panel), so text worth
  keeping could vanish and there was no way to see what had been sent.
  Every message now has one of six classes (`core/lifecycle.py`; the table
  is in `CLAUDE.md`), and the rule is to delete only when the information
  lives somewhere else. Code that deletes by itself asks the policy, which
  is what lets `dev cleanup off` stop all of it. Classes are worked out
  when asked (protection, what the owning task declares, a short in-memory
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
- **No tool is sent as strict (2026-10-09), which replaces the choice
  above:** measured with the real tools and prompt on 2026-10-07, ten
  strict tools made every request about 3.3s against 1.2s without, and
  the first request after the set of tools changed in any way (a new
  word, `dev mode on`) took about 40s while the API compiled the
  schemas. That was the "30 seconds to set a timer". Input was always
  validated in code, so nothing is lost. `STRICT_TOOLS` in
  `core/config.py` turns it back on; the choosing code stays.
- **What changes goes in the user turn, not the system prompt:** the
  time and each task's live state (`Task.live_state`) are a note after
  the user's words, in the latest turn only and never in the history.
  The system prompt and tools are then the same bytes for every message
  (cached), and "pause the tea timer" needs no read first: the ids are
  already there. This replaces "read anything that changes with a tool,
  every time"; the read tools stay for looking again within a turn.
- **A confirmed action ends the turn:** when every call of a round acted
  and the user has been shown its confirmation (the tool's own message,
  or what a control tool confirmed, sent as the reply), Claude is not
  asked for a closing line. One request instead of two. The cost: a
  request whose second step needs the first one's result ("start a timer
  and pin it") stops after the first. Claude is told to put every action
  in one response. A read, a failure, a proposal or a question with
  buttons still goes back to Claude to put into words.
- **Live messages are updated after the reply, not before it:** board,
  lists, timer messages and session cards go through `core/live.py`:
  one edit per message however many changes asked for it, at most one
  every 2 seconds, written from the database when it runs. Editing them
  first made every action wait 2 to 4 seconds and got rate-limited when
  several timers changed at once. The card may trail the reply by a
  moment; the database is always right.
- **One call for many timers:** `timer_control` takes several ids or
  `all`, with an optional label, instead of one call per timer. A bulk
  request can then never run into the limit of 5 calls per message, and
  "all timers called tea" is matched in code (whole words, any case),
  not by Claude picking from a list.
- **The wider honesty check gives way after a successful read:** a flat
  "Done" or ✅ still needs an action behind it. Wording such as "is now
  paused" is only sent back when no tool succeeded at all, because a
  true account of what a tool had just read was being questioned and
  cost a request each time. The cost: a false "it's running again"
  straight after a read is no longer caught (see `BACKLOG.md`).
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
- **The history holds what was said and nothing else:** this amends "tool
  exchanges stay out of the history" above, which kept a one-line note of
  the calls on the end of Claude's reply. Claude took the note for its own
  words: it began writing "[Tool calls this turn: …]" itself instead of
  calling the tool, and saying "Done" for things that never ran. Nothing
  is added now, in brackets or otherwise. The cost is that Claude knows
  what it said earlier, not what it ran; it is told to read anything that
  changes with a tool rather than trust the conversation.
- **"Done" is checked in code, not only asked for:** the instruction not to
  claim an action without a tool result was there when the false "Done"s
  happened. So a reply that opens by saying it is done, in a turn where no
  tool carried anything out, goes back to Claude once (to call the tool or
  answer again) and is replaced if it insists. Reading, proposing, waiting
  for a button and failing don't count as doing. The check is deliberately
  narrow, costs a request only when it fires, and each time it fires there
  is a card in #bot-log.
- **Tasks may give Claude tools that aren't words:** `Task.tools()` is in
  use, for two things a typed word can't do: report state for Claude to put
  into words (posting it in the channel as well would say it twice), and
  act on a record by id. They run through `registry.run_tool` like every
  other call. A word or reply action is still the first choice.
- **Timers and the Pomodoro are found by id, never in the chat:** Claude
  reads them with `list_timers` / `get_pomodoro_status` and acts with
  `timer_control` / `pomodoro_control` (one tool each, with an action,
  rather than a tool per action: fewer strict schemas and less to choose
  between). The timer reply actions are no longer offered to it, because
  finding a timer's message among the last 20 failed whenever it had
  scrolled away. This is an exception to "a message is only acted on if you
  replied to it or Claude named it from a listing", which still holds for
  messages.
- **Looking further back uses `message_log`, and asks first:** when the
  message isn't in the last 20, `search_messages` matches words against
  the user's own logged messages in that channel (500 rows, 30 days) and
  checks each match still exists. A recent message is acted on at once and
  shown quoted with Undo; an older match is shown quoted with Confirm /
  Cancel before anything happens, since a match from weeks ago is easier to
  get wrong. Only the user's messages are logged with their ids, so the
  bot's own replies can't be found this way.
- **Claude always has the dev mode switch, and it runs without a Confirm:**
  with every dev tool hidden while dev mode is off, it could never be
  asked to switch it on. `dev mode on|off` is one word, typed or as a tool,
  offered whatever the mode; typed `dev off` stays exact against typos,
  but switching dev mode off loses nothing, so it isn't treated as
  destructive.
- **A Pomodoro asked for while one is going is a "not done" for Claude:**
  the typed word shows the card again, which suits typing. Through Claude
  that made four messages (card, note, alert, reply), so the tool posts
  nothing and returns the session's state as a failure: nothing was
  started, and Claude says so once, offering a restart if other lengths
  were asked for.
- **Each clock keeps the speed it was started at:** this amends "dev speed
  changes the real wait" above. Pausing and extending converted with dev
  mode's speed of the moment, so a timer started at 1x and paused at 60x
  gained sixty times its time left (and lost it the other way round).
  `speed` is now a column on the timer and the session, set when the clock
  is set going; time left is always (end - now) x that speed. Resuming
  takes the speed in force then, as starting does.
- **A tool reports what was saved, not what it meant to do:** after a
  control tool changes a timer or session it reads the record back, and the
  result ends with that state; if the state isn't what the action should
  leave, the call fails. Claude is told to report that line. A wrong
  "running again" then has to contradict the result in front of it.
- **The honesty check has a second, softer pattern:** a reply that reports
  a change as news ("running again", "I've paused", "has been stopped")
  when nothing ran goes back to Claude once, like "Done". But a true
  account of an earlier message reads the same, so unlike "Done" it is
  never replaced if Claude repeats it. Read tools also end their result by
  saying nothing was changed, since the false report followed a read.
- **`timers_events`, not `timer_events`:** task tables carry the task's
  name. One table for timers and sessions (`kind`, `record_id`), with the
  label and the time left copied in, so the history reads on its own after
  the timer has gone. Appended to, never edited; nothing prunes it yet.
- **The "Your timers" list is Live, one per channel:** Discord's countdown
  timestamps keep running whatever happens to the timer, so a list left
  behind after a pause was wrong and looked right. It is tracked like the
  board and rewritten on every change; asking again replaces it. When
  nothing is left it says so and stops being tracked.
- **`pause all` and `resume all` are words:** a clear request for all of
  them shouldn't need one call per timer, or Claude at all when typed. They
  include the Pomodoro unless told `except pomodoro`, skip a timer that has
  already run out, and reply with each one's saved time left. They are not
  destructive: nothing is lost by pausing.
- **A bug gets a forum post, not a note in the channel:** the first design
  took the note where the bug was reported (`bug: text`, or a prompt after
  🐞). That put the report's detail in the channel it was about and needed
  a waiter that could swallow the next message. Now the channel gets one
  line with a link, and everything else (context, notes, closing) lives in
  the bug's own post in a forum channel, where tags and archiving come
  free. `bug: text` is not a command.
- **🐞 is instant, and removing it does nothing:** a report destroys
  nothing, and waiting 30 seconds to learn it was logged is worse than a
  report made by mistake, which costs one press of Won't fix. So
  `Reaction.instant` skips the debounce, records nothing in
  `reaction_state` and adds no ✅ (the "Logged as" line says it). It is the
  one stated exception to "debounced" and "reversible"; a test holds that
  no other reaction is instant.
- **No Claude in #bugs:** the questions are a fixed template and a reply
  is saved and ticked. A bug post is a record for later, and an assistant
  answering in it would put its own guesses among the facts, at an API
  call a message. `Task.claim` takes those messages before Claude is
  reached.
- **Claude Code never closes a bug:** it leaves a "fix ready, needs
  retest" note (`tasks/bugs/cli.py` has `show`, `list` and `note`, and no
  `close`). A fix is only known to work once it has been tried in Discord,
  so Fixed and Won't fix are buttons on the post, pressed by the owner.
- **A turn's timings are stored (`message_log.timing`):** they were only
  on the #bot-log card and in `bot.log`. A report quotes the turn it is
  about, perhaps much later, so the breakdown is kept as JSON with the
  chat row. Tool calls were already rows of their own against the same
  message.
- **Which turn a bot message belongs to goes by time:** the bot's replies
  have no row in `message_log`, so a reported bot message is matched to
  the latest thing the user sent in that channel before it (5 seconds'
  grace for the two clocks). The user's own messages are matched by id.
- **The commit in a report is the one the bot started on:** read once at
  startup, because that is the code that is running, whatever has been
  checked out since.
- **`KEEP_CONFIRMATIONS` is on by default:** while the bot is being
  built, seeing what it did matters more than a tidy channel. It is asked
  in `lifecycle.delete_after()`, so every Transient message obeys it and
  nothing else changes (commands are still Consumed). Unlike `dev cleanup
  off` it survives a restart and leaves the rest of the tidying alone.
- **One clock, and it can only be moved on a database of its own:** a
  day of reminders has to be testable in minutes, so everything time-based
  reads `core/clock.py`, which `dev clock` can move ahead. Moving it on the
  live database would leave real history with made-up times, so
  `python main.py --dev` runs the same bot on `data/dev.db` (its own
  backups folder too) and the clock refuses to move anywhere else. The
  dev database can be wiped with `dev reset-db`; the live one can't be.
- **The dev clock only moves forward; `reset` is the one way back:**
  going back would leave jobs already run and things "done in the
  future". `dev clock 6am` therefore means the next 6am, by way of
  midnight. For the same reason the offset is not part of dev mode: it
  is kept in `data/dev-clock.json`, survives `dev off`, the expiry and a
  restart, and only `dev clock reset` or `dev reset-db` clears it.
- **Time the clock jumped over is not lateness:** `job.is_late` means the
  bot wasn't there (catch-up after being off). A jump runs what came due
  in order as if on time, so testing with the clock shows the normal
  path; restart the bot to test the late one.
- **What stays on the real clock:** log lines and cards, `message_log`,
  the instance lock, bug reports (they are matched to `bot.log` by time),
  the two-minute "ok" and dev mode's expiry (or `dev clock +2h` would
  switch dev mode off).
- **The day boundary is one setting, and its work is one job:**
  `DAY_BOUNDARY` (midnight NZ) in `core/day.py`. Tasks override
  `new_day(ended, started)` instead of booking their own midnight jobs,
  so there is one order, one catch-up rule and one place to change it.
- **A time that could be morning or evening is asked about, except when
  only one reading is possible:** `parse_time("8")` raises
  `AmbiguousTime`. For a time something was done at, the reading that
  fails the checks is ruled out ("at 9", said at 2pm, is 9 am): that is
  arithmetic, not a guess. Bare `1` to `12` and `8:30` are ambiguous;
  `08:30`, `2030`, `20` and anything with am or pm are not.
- **The occurrence log is core, and append-only in spirit:** pills,
  reminders and routines all need "expected today, and what became of
  it". Every change writes an event with the values before and after, so
  a correction is itself history, and "undo that" is `db_revert` of the
  last change id. A revert is refused if anything was changed again
  since, because putting old values back would lose the newer ones.
- **Cards are a core helper, not a sixth exception:** pills needs buttons,
  a dropdown and (from stage 4) a form, and so will reminders and the hub.
  `core/cards.py` gives every task those from plain records, and does the
  parts that are easy to get wrong once: answering in time, permission,
  logging, errors, surviving a restart. Everything a press needs is in
  the component's id, so nothing is held in memory.
- **A pill's plan changes only through a saved preview:** adding and
  editing write a draft and show it; only Save writes the plan. Drafts are
  rows, not memory, so a preview's buttons work after a restart, and they
  lapse after 30 minutes so an old one can't be saved by accident.
- **Editing a preview is done by saying what to change:** the Edit button
  asks, and the words go to Claude, which calls the tool again with the
  draft's id. A form was built after the first QA (2026-10-09) and taken
  out again the same day: setup is rare, it is to be by conversation
  only, and no setup features are added until it is rebuilt.
- **One confirmation, never two (2026-10-09):** in QA, "add evening pill
  at 20:00" got "I'm proposing… reply ok", then the preview, then Save.
  A tool that shows its own preview or Confirm card now sets
  `confirms_itself` and simply has no `propose` argument. The "ok" is
  only for actions with no preview, and only for Claude's own
  suggestions.
- **A proposal is a stored call, and Claude's words are checked against
  it (2026-10-09):** for the course sentence Claude wrote the proposal as
  text with no tool call, then on "ok" invented "That ran… `pill_add …`".
  Nothing had run. A reply that offers an "ok" when none is waiting, says
  "that ran" with nothing run, or names a tool is sent back once; what is
  finally sent has tool names removed. What is remembered about a run
  uses the tool's `label`, so the history gives it nothing to imitate.
- **Shortcuts are namespaced, and Claude asks between tasks:** as tasks
  multiply, "add milk" could be a pill, a to-do or shopping. No shortcut
  may be a bare generic verb, every tool says what it is `only_for`, and
  when tools of different tasks still fit equally Claude marks each call
  `candidate`: they are held and offered as a button per task, and the
  pick runs with the input Claude gave.
- **Times in Claude's replies are not rewritten:** a rewrite of 24-hour
  times in every reply was tried and dropped the same day (2026-10-09),
  because "05:00 left" on a timer is a length of time and would have
  become "5:00 am". Times of day are right at the source instead: every
  tool and card formats them with `timeinput.format_time` (`8:00 pm`), and
  the prompt tells Claude to write them that way.
- **Claude passes times and dates as they were said:** `pill_add` gets
  "8", not "8pm", and "tomorrow", not a date. Code reads them
  (`core/timeinput.py`) and asks "8am or 8pm?" with buttons. That keeps
  the never-guess rule out of the model's hands.
- **Pause and resume act at once; remove asks:** a pause changes no plan
  and is undone in a word. "Paused until the 20th" means it is taken
  again on the 20th. A pause with a date ends by itself, and a course is
  over the day after its last day, without any job: `rules.status_on`
  works both out from the day.
- **With dev mode on there are more tools with arguments than can be
  strict (20):** the dev words go without first, by priority. It only
  matters if `STRICT_TOOLS` is ever switched back on.
- **Cost is logged per message before the way messages are handled is
  changed (2026-10-09):** every logged input gets a route (how it was
  handled), and every request to Claude a row of its own with what it was
  for, so the old way (every tool with every message, route `tools`) can
  be compared with what replaces it. What was already logged was given a
  route by the migration. On 2026-10-09 the live database stood at
  US$0.0032 and 5.5s a message to Claude this month (113 of them).
- **Costs go by the real clock and the running database:** a day of
  testing under the dev clock still cost what it cost today, and
  `dev cost` on the dev database reports the dev database.
- **A message for two tasks is charged half to each**, and one for no
  task (chat) to "no task", so the tasks add up to the total.
- **`bugs` uses discord.py, in `posts.py` only:** forum posts, tags and
  persistent buttons have no core helper yet, and one user of them is not
  enough to design one. To be promoted to core when a second task needs a
  forum (in the backlog).
