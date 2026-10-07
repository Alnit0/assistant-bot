# Backlog

Things found and not yet finished: failed manual tests (copied here by the
`qa` skill), and anything noticed during a task and left for later. Remove
an item once it is fixed and its tests pass.

## Fixed in code, waiting for a manual retest

From the QA findings of 2026-10-07. Each is done and unit tested; the rows
in `docs/TESTING.md` are ⬜ Untested until they are run in Discord.

| Finding | What changed | Retest |
|---|---|---|
| Useful messages (seed instructions) deleted themselves; no single rule for what is deleted | One lifecycle policy (`core/lifecycle.py`); `dev cleanup on\|off`; the class shown by `dev inspect` | J22, J28, J29 |
| An invalid reaction or reply action sat through the debounce before failing | Checked at once: ⚠️ plus a short self-deleting reason; only valid actions are debounced | C6, C12, D13, E12 |
| Replying `pin` (or `pin me`, `pin this`) did nothing | There was no `pin` reply action: `pin` / `unpin` added, and filler words accepted on every reply action | L9, L10, L11, D15 |
| "Hive" was hard-coded | `ASSISTANT_NAME` setting | K10 |
| `pomo` while a session runs was an error | It re-shows the card (or points to it from another channel); `dev off` when off and a second `lab channels` no longer fail either | H9, H17, J30, B21 |
| Claude offered to do things it has no tool for | Its instructions always say it has no tools and must never offer to act | A17 |

## Left for later

- **"Alex" and "Auckland, New Zealand" are still hard-coded** in Claude's
  system prompt (`core/llm.py`). They belong with the user record (name,
  time zone) once there is more than one user.
- **Unpinning by reply doesn't clear an applied 📌.** If a message was kept
  with 📌 and is then unpinned by replying `unpin`, the 📌 and its ✅ stay
  and `dev inspect` still says "Kept: yes". Removing the 📌 puts it right.
- **A refused reaction is forgotten by a restart.** The ⚠️ added when a
  reaction is refused is cleared when the reaction is taken off, but only
  while the bot remembers refusing it (in memory). After a restart the ⚠️
  has to be removed by hand.
- **Only archive and delete are checked at once.** Other reactions and
  reply actions have no `validate` yet (📌 at the pin limit still fails
  after the wait, since only Discord knows the channel is full).
- **`dev cleanup off` leaves working buttons behind.** Alerts and old
  Pomodoro cards that would have been deleted stay with their buttons;
  pressing one puts things right but can look odd. It also leaves a second,
  unpinned dev panel when the panel is re-shown.
- **Lab messages are outside the lifecycle.** Lab tests are exempt from the
  clean-up rules, so they don't declare a class and read as Kept.
- **`dev inspect` forgets Transient after a restart.** Which notes were
  self-deleting is held in memory (the last 500), so one left on screen by
  `dev cleanup off` reads as Kept after a restart.
- **The nightly sweep is not built.** Kept messages are never removed
  automatically until it is; when built it must skip Protected ones.

## Tool calling: left for later

Built on 2026-10-07 and unit tested with a mocked Claude. Not yet run
against the real API or in Discord: the N rows in `docs/TESTING.md` are
⬜ Untested.

- **The tool schemas have not been sent to the real API.** They follow the
  documented rules for `strict` (all required, no unions, nothing extra),
  and a test checks that, but only a real request proves they compile. The
  first chat message after the restart is that check: an API error card
  naming a schema means one needs changing.
- **Prompt caching may not take effect.** Haiku 4.5 only caches a prefix of
  4096 tokens or more, and the normal tool set plus system prompt may be
  smaller. The "Cache" field on the "Message handled" card shows whether
  anything was read; if it stays at 0 the breakpoints cost nothing but
  save nothing either.
- **Every chat message now carries the tools**, used or not ("Tool tokens"
  on the card). If that cost matters, the next step is to send them only
  when the message looks like a request.
- **A protected message deleted through Claude asks twice**: Claude's
  Confirm / Cancel, then the existing "That message is pinned" question.
- **Proposals and button questions are held in memory.** A restart forgets
  a pending "ok", an Undo button and a "Which message?" question.
- **Undo exists only where an action declares one**: pin, unpin, archive,
  pause and resume. Cancelling a timer or extending one cannot be undone.
- **Claude only chats in #inbox**, so the "dev tools in the dev channel"
  rule has no effect until chat is enabled there.
- **`Skill.tools()` and `Tool` are still unused.** Every tool is generated
  from a word or reply action; `recent_messages` is built into
  `skills/toolcalls.py`.
- **Reactions are not tools.** Claude tells you which one to add.
- **Recent messages go to the API when Claude looks for a target**: up to
  20 one-line previews from the channel, only when it calls
  `recent_messages`.
