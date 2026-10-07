# Changelog

What changed, newest first. One entry per task, as one to three bullets on
what changed for the user. Entries before 2026-10-07's last one were
backfilled from the git log.

## 2026-10-07

- **Claude can now do things.** Ask in plain words ("set a timer for 5
  minutes", "file that away") and it runs the same actions you can type:
  every word and reply action is offered to it as a tool, filtered by
  channel and permission (never the lab; dev tools only in dev mode).
  Typed words still run directly, without Claude.
- It acts at once on a clear request, asks when unsure, and when it is
  only suggesting it waits for your `ok` (2 minutes). Destructive actions
  always ask with Confirm / Cancel. A message you describe rather than
  reply to is shown quoted, with Undo where possible, and if several fit
  you pick with buttons. At most 5 tool calls per message.
- Every tool call is logged, and the "Message handled" card shows the
  tools sent, their token cost, cache use and each call's outcome.
- **QA findings.** Every message now has a lifecycle class (Kept, Live,
  Consumed, Transient, Alert, Protected) and one policy decides what is
  deleted; `dev cleanup off` stops all automatic deletion and `dev inspect`
  shows a message's class. Seed instructions now stay.
- Reactions and reply actions that can't work (archiving in #bot-log, say)
  are refused at once with ⚠️ and a short reason, instead of after the
  30-second wait. Reply `pin` / `unpin` are new, and replies accept filler
  words ("pin this", "please archive it").
- `pomo` while a session runs shows its card again instead of failing. The
  assistant's name is the `ASSISTANT_NAME` setting, and Claude is told it
  has no tools and must never offer to do something itself.
- Add `DEV_CHANNEL_ID`: a scratch channel for manual testing, known to the
  bot as `dev`. The QA run sheet now uses it instead of #documents.
- Add `docs/ARCHITECTURE.md` (a map of every file and the main data flows),
  trim `CLAUDE.md` to the essentials and move the procedures into project
  skills (`add-skill`, `qa`, `end-of-task`). Add this changelog.
- **Keep:** 📌 is now a reaction. It pins the message and protects it;
  taking it off unpins. A full channel gets ⚠️ with the reason in #bot-log.
  `dev inspect` shows "Kept".
- Add the QA run sheet (`docs/QA-RUN.md`): the manual tests in ordered
  blocks.
- **Dev mode:** `dev on` gives faster waits, debug cards in #bot-log, a
  pinned panel and inspection tools. Tests now run with pytest, and
  `docs/TESTING.md` tracks every Auto and Manual test.
- **Reactions and archive brought into line with the interaction rules:**
  reactions act on where they ended up, get ✅ when applied, are undone on
  removal and get ⚠️ on failure. Archive and delete ask before touching
  pinned or 📌-marked messages. New 🗑️ reaction, a Restore button on
  archived copies, and all pin notices are deleted. Timer and Pomodoro
  alerts clear when acknowledged.
- Add the interaction rules (input, reactions, cleanliness, notifications,
  interactions) that every skill follows.
- **Timers and Pomodoro:** `timer`, `timers`, `pomo` and `pomo stats`, with
  reply actions (`cancel`, `pause`, `resume`, `+10m`) and one pinned "Active
  timers" board per channel. They survive restarts and report late finishes.
- Reply actions can match a pattern (`+10m`) and decline messages that
  aren't theirs, so words like `cancel` only act where they apply.
- **Scheduler** is now database-backed: jobs survive restarts and are
  caught up after downtime.
- Lab: `lab tour` (a guided, resumable test run), `lab channels`
  (notifications across channels) and delayed `lab notify`.
- Commands tidy up after themselves: a word or reply that works is
  deleted, with a short self-deleting confirmation; one that fails stays
  and gets ⚠️.
- **Typed words, reply actions and reactions** replace slash commands as
  the main way in, with typo tolerance, debounced reactions and a `help`
  generated from what is registered.
- Only one copy of the bot can run (a lock on `data/bot.lock`); interaction
  error handling no longer raises.

## 2026-10-06

- Fix persistent lab buttons; report buttons and forms that nothing
  answered.
- **Archive:** move a message to the archive channel under its author's
  name and avatar, with attachments and a link back. Add `/lab chart`.
- **Lab:** a test bench for Discord features (reactions, buttons, forms,
  pinned status, notifications), with slash commands and a reusable
  debouncer in the core.
- **Skills system:** features live in `skills/`, are discovered by a
  registry and get a `Context` instead of a Discord message.
- Add schema migrations, the users table, one permission check, async
  database calls and nightly backups.
- Split `bot.py` into the `core` package.
- Add `CLAUDE.md`, the development guide and the decisions log.

## 2026-10-05

- Add placeholders for all planned channel ids.
- Connect the Claude API, with short-term conversation memory.
- First proof of concept: the bot replies in #inbox.
