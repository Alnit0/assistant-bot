# Development guide

## Environment

- **Server:** Windows 11 mini PC, always on, reachable over Tailscale
- **Access:** Remote Desktop for anything graphical, SSH for terminal work
- **Editor:** VS Code with Remote SSH, connected to the server
- **Repo location on server:** `C:\Users\<user>\projects\assistant-bot`

## First-time setup

1. Clone the repo
2. Create the virtual environment: `python -m venv .venv`
3. Activate it: `.\.venv\Scripts\Activate.ps1`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in real values
6. Run: `python main.py`

VS Code is configured (`.vscode/settings.json`) to activate `.venv`
automatically in new terminals. Check the prompt starts with `(.venv)`.

## Project layout

- `main.py`: entry point. Creates the Discord client, wires events, starts the bot
- `core/`: shared building blocks. Never imports from `tasks/`
  - `config.py`: paths, settings from `.env`, validation, constants, channel names
  - `logging_setup.py`: terminal and rotating file logging
  - `instance_lock.py`: makes sure only one copy of the bot runs
  - `database.py`: connections and the async database helpers
  - `migrations.py`: schema migrations, applied at startup
  - `users.py`, `permissions.py`: users and the `is_allowed` check
  - `router.py`: decides whether a message is a registered word (with typo tolerance)
  - `context.py`: the `Context` object handed to tasks
  - `interactions.py`: permission check and logging for slash commands and menus
  - `errors.py`: `UserError`, for problems the user can fix
  - `scheduler.py`: stored jobs that run at a moment in the future, with catch-up
  - `clock.py`: what time it is; the dev clock (dev database only)
  - `day.py`: the midnight day boundary and the job that runs when a day ends
  - `timeinput.py`: reading the times you type, and showing times (`8:04 am`)
  - `occurrences.py`: what is expected each day, its state, and every change to it
  - `backup.py`: nightly backup (a scheduler job) and pre-migration snapshots
  - `debounce.py`: waits for a quiet period, then handles events together
  - `devmode.py`: dev mode's state, and the values other code reads from it
  - `reactions.py`: what to apply or undo once reactions have settled
  - `cards.py`: buttons, dropdowns and forms for tasks, from plain records
  - `protection.py`, `confirmations.py`: pinned and 📌-marked messages, and
    asking before acting on them
  - `pins.py`: pinning and unpinning a message for tasks
  - `llm.py`: Claude client, system prompt, history, cost estimates
  - `discord_utils.py`: #bot-log embeds, message helpers, safe replies
- `tasks/`: one folder per feature
  - `base.py`: the `Task` base class and the `Keyword`, `ReplyAction`, `Reaction` records
  - `registry.py`: finds and loads tasks, dispatches to them, and knows everything
    the bot can do (for `help` and for Claude)
  - `builtin/`: ping, reset, buttons, stats, help
  - `archive/`: archive or delete a message (reply, 📦 / 🗑️ reaction, context
    menu), with a Restore button on archived copies
  - `keep/`: the 📌 reaction, which keeps and pins a message
  - `lab/`: `lab …` words for trying out Discord features
  - `pills/`: what you take and when (setting up so far)
  - `timers/`: short timers and Pomodoro sessions
  - `dev/`: the `dev …` words, the dev panel and the dev tools
- `tests/`: unit tests (`python -m pytest`)

Always run `main.py` (not the files in `core/` or `tasks/`). Paths are
worked out from the project root, so it runs correctly from any working
directory.

## How to talk to the bot

There are three main ways in, and one fallback. `help` lists what works in
the channel you are in; `help <task or word>` gives details.

| Way in | Example | Where |
|---|---|---|
| **A word on its own** | `stats`, `clear chat`, `lab chart 30` | Mostly #inbox; `lab …` and `help` anywhere |
| **Reply to a message with a word** | reply `archive`, `pin` or `delete` | Anywhere |
| **A reaction** | 📦, 🗑️ or 📌 on a message | Anywhere |
| Slash command (fallback) | `/lab chart`, Apps > Archive message | Anywhere |

- **The whole message must be the word or phrase.** `stats` runs stats;
  `stats please` is a message for Claude. Case and a full stop at the end
  don't matter.
- **Small typos are forgiven:** one wrong, missing, extra or swapped letter,
  in words of five letters or more (`statss`, `lab buttns`). The bot says
  `Read as: stats` when it has corrected something. Destructive words
  (`reset` and its aliases, `delete`) must be spelled exactly.
- **A reply may carry filler words:** `pin this`, `pin me`, `please archive
  it` and `delete this` are read as the action, since a reply is already
  aimed at a message. A word typed on its own still has to be the whole
  message.
- **Asking for what already exists shows it.** `pomo` while a session is
  running shows its card again; `dev off` when it is off just says so.
- **Anything else in #inbox goes to Claude.** Outside #inbox the bot only
  reacts to registered words, reply actions and reactions.
- **Words and reply actions tidy up after themselves.** When one works, the
  message you typed is deleted. If it had nothing lasting to show, you get a
  short confirmation ("📦 Archived: link") that deletes itself after 5
  seconds (`CONFIRMATION_SECONDS` in `.env`). Lasting output, such as the
  stats card or the help text, stays.
- **When one fails, your message stays and gets a ⚠️ reaction.** Nothing is
  said in the channel; the reason (including "Usage: …" for a wrong
  argument) is on a card in #bot-log.
- **What can't work is refused at once.** A reaction or reply action on a
  message it can't apply to (archiving something in #bot-log or already in
  the archive, say) gets ⚠️ and a one-line reason that deletes itself after
  5 seconds, with no 30-second wait. Take the reaction off and the ⚠️ goes.
- **Every message has a lifecycle class**, which decides whether it is
  ever tidied away:

  | Class | Examples | What happens |
  |---|---|---|
  | Kept | Chats with Claude and its replies, help, explanations, lists, stats, seed instructions | Never auto-deleted; only removed by you (archive, delete) |
  | Live | Dev panel, timer board, Pomodoro card | Edited in place; ends as a one-line summary (then Kept), or is removed if it has no lasting value |
  | Consumed | Your command words and reply actions | Deleted once actioned; kept with ⚠️ if it failed |
  | Transient | Short confirmations, invalid-action reasons | Delete themselves after a few seconds |
  | Alert | Timer done, Pomodoro phase change | Stay until acknowledged, then deleted, with the original updated |
  | Protected | 📌-reacted or pinned messages | Never auto-deleted; archive and delete ask first |

  A message is only deleted when its information now lives somewhere else.
  `dev cleanup off` stops all automatic deletion, and replying `dev
  inspect` to a message shows its class.
  `KEEP_CONFIRMATIONS` in `.env` (on by default) leaves every Transient
  message in the channel, so you can read back what the bot did. Your
  command words are still deleted. Set it to `false` to have confirmations
  tidy themselves away again.
- **Reporting a bug.** React 🐞 to a message, reply `bug` to it, or type
  `bug` on its own (the latest thing in that channel). It is logged at
  once and the channel gets "🐞 Logged as B4" ("D4", with a "dev" tag on
  the post, when the bot runs on the dev database), a link to the bug's post in
  the #bugs forum (`BUGS_CHANNEL_ID`, a forum channel where the bot may
  Create Posts, Send Messages in Threads and Manage Threads). The post has
  the message, the five before it, that turn's tool calls, timings and log
  errors, and the commit, then three questions (only on a bug you reported: one the bot or the self-test files itself has none). Whatever you write in the
  post is saved as a note (the count on its card goes up; no ✅); the bot never answers there and
  nothing is sent to Claude. The opening card counts the notes. **Fixed**
  and **Won't fix** tag the post and archive it, and leave a **Re-open**
  button on the card with the status and time. `bugs` lists the open ones, and `bugs export` writes them in
  full to `docs/BUGS.md` (not in git). `bug: some text` is not a command.
  In Claude Code, "fix B4" runs the `bug` skill, which leaves a "fix
  ready, needs retest" note; pressing Fixed stays with you.
- **Reactions wait 30 seconds** (`REACTION_DEBOUNCE` in `.env`). The bot
  then acts once, on where your reactions ended up: add one and remove it
  in time and nothing happens. Only your reactions count.
- **After a reaction is acted on** the message gets ✅, and taking your
  reaction away later undoes it and removes the ✅. Archive and delete are
  the exception: the message is gone, so they can only be cancelled within
  the 30 seconds. If a reaction fails, the message gets ⚠️ and the reason is
  in #bot-log. 🐞 is the one reaction that doesn't wait: it acts at once,
  adds no ✅, and taking it off does nothing.
- **📌 keeps a message.** After the 30 seconds it is pinned and gets ✅.
  Clean-ups leave it alone, and archiving or deleting it asks first. Take
  your 📌 off and, after the 30 seconds, it is unkept and unpinned (even if
  it was pinned by hand before you kept it). If the channel has as many
  pins as Discord allows, the message gets ⚠️ instead: unpin something
  there, then take your 📌 off and add it again.
- **Reply `pin` to pin at once** (also `keep`, `save`; `unpin` or `unkeep`
  to undo). No 📌 and no wait: the message is pinned natively, which
  protects it in the same way.
- **Reactions made while the bot is off are not seen.**
- **"X pinned a message" notices are deleted** wherever they appear.
- **Claude knows the list too.** The same list `help` shows is added to its
  instructions, so "what can you do?" gets an accurate answer.
- **Claude can run them for you.** In #inbox, ask in plain words ("set a
  timer for 5 minutes", "start a 50/10 pomodoro for writing") and it runs
  the same action the typed word does. Typed words still run directly and
  never go to Claude.
  - **A clear request runs at once.** If it isn't sure what you want it
    asks. If it is only suggesting something, it says so and waits: reply
    `ok` (or `yes`, `do it`) within 2 minutes to run it, `no` to drop it.
  - **Destructive actions always ask** with Confirm and Cancel (`reset`,
    `delete`, `dev off` and the other words that must be spelled exactly).
  - **Acting on a message:** reply to it ("file this away") and that
    message is used. Without a reply, describe it ("pin the message about
    rent") and Claude looks through the last 20 messages of the channel;
    the confirmation then quotes the message with a link, and has an
    **Undo** button for 30 seconds where the action can be taken back
    (pin, unpin, archive). If more than one message fits you get a button
    for each instead of a guess.
  - **Further back:** if it isn't in the last 20, say "look further
    back". It searches your own earlier messages in that channel (the
    last 500, up to 30 days), and before acting on one it shows it quoted
    with Confirm and Cancel. The bot's own replies can't be found this
    way: reply to those.
  - **Timers and the Pomodoro:** it reads them live ("show my timers",
    "how long left on my Pomodoro?") and acts on the one you name ("pause
    the tea timer", "unpause it", "skip this break", "10 more minutes on
    the eggs"), wherever its message is. If a label fits two timers it
    asks which. A Pomodoro asked for while one is going gets one reply,
    with an offer to restart at the lengths you asked for.
  - **What happened and when:** every start, pause, resume, extension,
    cancel and finish is recorded with the time left, so you can ask
    "what was on dinner when I paused it?" or "when did I resume tea?".
    The record starts from the restart that brought this in.
  - **Only the bot's own code says "done".** Claude works out which task
    a message is for and fills in the details; the task's code does it,
    reads the change back and writes every word. Claude runs nothing.
  - **Plain chat** answers general questions and nothing else: it has no
    tools and no access to your lists, pills or timers. Anything about
    your data is answered by the task that owns it. A remark or a
    thank-you gets no reply.
  - **What it costs:** one small request to choose the task and one to
    fill in the details; a task's name on its own ("pills") costs
    nothing. The "🧭 Message routed" card in #bot-log shows the route,
    the tasks and the cost, and `dev why` shows the rest.
- **The assistant's name** is `ASSISTANT_NAME` in `.env` (default Hive). It
  is what Claude calls itself and what the archive webhook and lab messages
  show. Restart the bot after changing it.

## How to add a task

1. Create a folder `tasks/<name>/` with an `__init__.py`. The folder name
   is the task's name (lower case, no spaces).
2. In it, subclass `Task`, set `name` (same as the folder) and
   `description`, and expose one instance called `task`:

```python
from core.context import Context
from tasks.base import Keyword, Task


async def hello(ctx: Context) -> None:
    await ctx.reply(f"👋 Hello, {ctx.user.display_name}!")


class GreeterTask(Task):
    name = "greeter"
    description = "Says hello"

    def keywords(self) -> list[Keyword]:
        return [
            Keyword(
                ["hello", "hi there"],          # the word, then any aliases
                "say hello",                    # description: required
                hello,
                examples=["hello"],
            ),
        ]


task = GreeterTask()
```

3. Restart the bot. The terminal and the log file (and, only if something is wrong, a "⚠️ Started with a problem" card in #bot-log)
   list the tasks that loaded, anything that was skipped and why, and any
   registration with no description. `help` picks up the new word
   automatically, and so does Claude.

**What a task can register.** Each one must describe itself:

| Hook | Record | The user… |
|---|---|---|
| `keywords()` | `Keyword(words, description, handler)` | types the word on its own. `handler(ctx)` |
| `reply_actions()` | `ReplyAction(words, description, handler)` | replies to a message with the word. `handler(ctx, target)` |
| `reactions()` | `Reaction(emoji, description, handler)` | adds the emoji to a message. `handler(payload, user)` |

Fields they share:

- **`description`** (required) and **`examples`**: shown by `help` and given
  to Claude. A missing description is reported in #bot-log at startup.
- **`channels`**: where it works. `"inbox"` (the default for keywords),
  `"any"` (the default for reply actions and reactions), or a list of names
  from `.env`: inbox, bot-log, archive, reminders, gym, admin, documents, dev, bugs.
- **`permission`**: the action name passed to `is_allowed`. Defaults to
  `keyword:<word>`, `reply:<word>` or `reaction:<emoji>`.

Keywords and reply actions also take:

- **`takes_args=True`** and **`usage="[days]"`**: accept extra words after
  the phrase; they arrive as `ctx.args`. Without it the message must be the
  phrase and nothing else.
- **`exact=True`**: no typo correction. Use it for anything destructive.
- **`accepts=`** (keywords): a function that looks at the arguments and can
  say "not mine", so the message goes to Claude instead. `help` uses it so
  that "help me write an email" isn't treated as a help request.
- **`keep_command=True`**: leave the user's message in place after the
  action works. By default the core deletes it.

Things to know:

- **The registry does the bookkeeping.** It logs the input, checks
  `is_allowed`, posts the #bot-log card and records the result. The handler
  only does the work. What it returns is recorded as the reply; return
  `None` to record what was sent.
- **How a handler ends is decided by the core**, the same for every word
  and reply action. On success the user's message is deleted (unless
  `keep_command`). If the result is something to keep, send it with
  `ctx.reply`. If there is nothing lasting to show, call
  `ctx.confirm("📦 Archived: <link>")`: it deletes itself after
  `CONFIRMATION_SECONDS`. A handler that shows nothing at all gets a plain
  "✅ Done: <word>" confirmation.
- **Raise `UserError("…")`** (`core/errors.py`) for problems the user can
  fix, such as bad arguments. Any failure leaves the user's message in
  place with a ⚠️ reaction; the message you raised goes on the #bot-log
  card, not in the channel.
- **Use the context**, not Discord: `ctx.reply(text)`,
  `ctx.reply_card(title, fields)`, `ctx.log(title, description)`,
  `ctx.user`, `ctx.args`, `ctx.channel_name`.
- **Database:** return migration functions from `migrations()`, in order,
  and only ever add to the end. Prefix table names with the task's name
  (`greeter_...`) and give every record a `user_id`. Query with
  `await ctx.db.run(func)`, where `func(conn)` does the SQLite work; it runs
  in a worker thread so the bot is never blocked.
- **Reactions that can be undone:** give the `Reaction` an `undo` handler;
  the core runs it when the user takes the reaction away, and looks after
  the ✅ and ⚠️ markers and the record of what is applied
  (`core/reactions.py`). Set `destructive=True` when the message won't
  exist afterwards. Never post a note in the channel about a failure.
- **Pinning:** `await core.pins.set_pinned(channel_id, message_id, True,
  reason)` (or `False` to unpin). It raises `UserError` with the reason if
  Discord refuses, for instance at the pin limit.
- **Before archiving, deleting or clearing a message**, check
  `core.protection.is_protected(message)` (pinned or 📌-marked) and, if so,
  ask with `core.confirmations.ask(channel, user, question, on_confirm)`.
  Call `ctx.shown(...)` so the core doesn't add a "Done" on top of the
  question.
- **Asking a question** (`actions.Question`): never send one as a
  message. Return it on the card: `Proposal(lines=…, data=…,
  question=Question("Which one?", (Choice("Vitamin C", data_with_c),
  Choice("Vitamin D", data_with_d))))`. The lines show everything that
  was understood (❔ where the answer will go); each `Choice.data` is the
  action's whole data as extraction would hand it over with that answer
  in it, and `settles` names the fields it decides. Core draws a blurple
  button an answer (four at most) beside Cancel, leaves Save off, and on
  a press calls your `prepare` again with that data, in place: return
  the next question, or none. An action with `card_if` that no longer
  needs a card is run at once and the card says what was done. No
  choices at all is allowed: the answer is typed. A typed answer is an
  ordinary follow-up to the open card. One question at a time, the most
  important first.
- **Being safe across a restart** (`core/restart.py`, and "What survives
  a restart" in `docs/ARCHITECTURE.md`): keep nothing in memory that
  matters, and make every job safe to run twice. If start-up does
  something late because the bot was off, say so with
  `restart.caught_up("…")`: the line goes in the start's one message in
  #bot-log, and is dropped when the bot is not starting. If a button of
  yours does something that must not be left half done, register
  `restart.on_cut_off(task, action, recover)`: `recover(cut, arg)` is
  called at start for a press the bot stopped in the middle of, puts it
  right without doing it twice, and returns its line.
- **Doing something later:** book a job with
  `await scheduler.add_job(self.name, "kind", due_at, payload, user_id)`
  (`core/scheduler.py`) and return `{"kind": handler}` from `job_handlers()`.
  The handler gets a `Job` (`payload`, `user_id`, `due_at`, `is_late`).
  Jobs are stored in `scheduled_jobs`, so they survive a restart; one that
  came due while the bot was off runs at the next start with `job.is_late`
  set, and the handler decides what to say about that. `cancel_job` and
  `reschedule_job` change a job that hasn't run. Keep the job's id with your
  own record and ignore a job that no longer matches it.
- **Replies that aren't fixed words:** give a `ReplyAction` a `pattern`
  (a regular expression; its groups become `ctx.args`), as `+10m` does.
- **Reply words that only sometimes apply:** give a `ReplyAction` an
  `applies_to` check. The timers task uses it so that `cancel` replied to
  an ordinary message is not treated as a command.
- **Messages an action can't be done to:** give a `ReplyAction` or a
  `Reaction` a `validate(message)` that raises `UserError` with the reason.
  The core runs it the moment the reply arrives or the reaction is added,
  marks ⚠️ and shows the reason briefly; a refused reaction is never
  debounced. Keep it quick and free of side effects, and still check in the
  handler (archive does both with `rules.check_archivable`).
- **Deleting a message by itself:** ask `core.lifecycle.deletes(MessageClass.X)`
  first, or pass `delete_after=lifecycle.delete_after()` for a note, so
  `dev cleanup off` is respected. `ctx.confirm`, `ctx.note` and the
  command clean-up already do. If your task owns a card edited in place or
  an alert, say so from `Task.message_class(message_id)` (Live or Alert),
  as timers does; `dev inspect` shows it.
- **The assistant's name** is `core.config.ASSISTANT_NAME`. Don't type it
  into a string.
- **Slash commands are a fallback.** Return `app_commands.Group` or context
  menu objects from `app_commands()`; they are synced to our server at
  startup. In the command's check, call `interactions.check_allowed` and
  `interactions.begin` (`core/interactions.py`); the core then logs how it
  ended. Have the typed word and the slash command call the same function
  (see `Run` in `tasks/lab/common.py`).
- **Other Discord events:** return `{"raw_reaction_add": handler, ...}` from
  `events()`. `startup(client)` runs once when the bot is connected.
- **Knowing what just happened:** ask for the `action_finished` event to be
  told after every word, reply action, reaction and chat, with a
  `registry.ActionResult` (kind, name, status, user, channel).
- **Waiting for an answer:** `registry.expect_message(channel_id, user_id,
  handler, timeout)` hands that user's next message in that channel to
  `handler(ctx)`, once, and keeps it away from Claude. Words and reply
  actions are still tried first. It is forgotten at restart.
- **Going through channels:** not every channel in `.env` holds messages
  (#bugs is a forum, with no pins or history). Loop over
  `core.channels.named()` instead of `CHANNELS`, and check
  `core.channels.holds_messages(channel)` before reading pins or history
  from a channel that no message came from.
- **Messages that are yours because of where they are:** override
  `Task.claim(ctx)` to return a handler for a message that is no word,
  reply action or awaited answer (`ctx.parent_channel_id` is the forum a
  post belongs to). It is asked before Claude, logged as `claimed`, and
  needs the permission `message:<task>`. `bugs` uses it for notes.
- **A reaction that can't wait:** `instant=True` on a `Reaction` skips the
  quiet period, the ✅ and the undo. 🐞 is the only one, by decision
  (`docs/DECISIONS.md`); a test fails if another appears.
- **Cards: buttons, a dropdown or a form without discord.py.** Write the
  card with the records in `core/cards.py` and register what each action
  does, once (in `setup`):

  ```python
  from core import cards
  from core.cards import Button, Card

  cards.register("greeter", "wave", on_wave)

  async def hello(ctx):
      await cards.post(ctx, Card("👋", ((Button("Wave back", "greeter", "wave", arg="7"),),)))

  async def on_wave(press: cards.Press) -> str:
      await press.update(Card("👋👋"))      # rewrite the message in place
      return "waved back"                   # recorded in message_log
  ```

  A row is a tuple of up to five `Button`s, or one `Select` (a dropdown;
  what was picked is `press.values`). `press.arg` is the button's `arg`:
  make it the id of your own record and keep the state in your tables, so
  the card still works after a restart. `press.say(text)` tells the presser
  alone, `press.remove()` deletes the message, and raising `UserError` shows
  the reason to the presser. For a form, register the action with
  `opens_form=True` and call `press.open_form(Form(...))`; the submission
  comes back to the same action with `press.fields` filled. The helper
  answers within 3 seconds, checks `is_allowed` (`card:<task>` unless you
  pass `permission`), and logs the press. `cards.send(channel_id, card,
  silent=True)`, `cards.edit` and `cards.delete` are for cards that answer
  no message (a daily card, a prompt). `cards.check(card)` refuses what
  Discord would (5 rows, 5 buttons a row, 25 options, 100-character ids).
- **Buttons that must survive a restart** (in a task that writes its own views)**:** give them a fixed `custom_id`, no
  timeout, and register the view with `client.add_view(...)` in
  `setup(client)`, which runs before the bot connects.
- **Answer every button, select and form within 3 seconds**, as the first
  thing the handler does; log to the database afterwards. Anything left
  unanswered after 2 seconds is logged, reported in #bot-log, and the user
  is told the button no longer works.
- **Don't pass `self.view` back from a `DynamicItem`.** It is discord.py's
  bare copy of the message, and its other buttons have no handlers. Build
  the full view again and send that (see `build_panel` in
  `tasks/lab/buttons.py`).
- **Plain words** are a task's `plain.py`: its `Action`s (`core/actions.py`)
  and the code that carries them out, taking a `Request`, never a
  Context. See "Routing and confirm cards" below, and `tasks/timers/plain.py`
  or `tasks/pills/plain.py` for a worked example. A task that takes plain
  words sets, on its `Task`: `icon`, `only_for`, `examples`, `show`, and
  what adding something that is already there means:
  - `identity`: the fields that make two items the same thing
    (`("name",)` for a pill; `()` when each is its own, like a timer).
  - `on_repeat`: `update` (it is a change to the one there),
    `add_to_amount` (more of it), `allow_another` (a second one),
    `show_existing` (the one there is shown and nothing is added: a bug
    report for a message that has one; its identity is
    `repeats.MESSAGE`, the message it is about), or `ask` (not available
    until cards can ask).
  `core/repeats.py` does the matching (`find`), says what a request comes
  to (`decide`) and writes the words (`already`, `there_line`,
  `change_line`). The bot won't route to a task that doesn't declare
  `on_repeat`, or whose identity names a field none of its actions take.
- **A reply to one of your task's messages comes to it first.** A Discord
  reply to a message the task posted goes to its extraction without the
  router, and the code resolves "it" from `request.replied_to`. A task
  owns whatever `message_class` knows; override `Task.owns_message` if
  it posts messages with no lifecycle class (timers does, for a card
  whose timer has ended). A line that says what was done to one of the
  task's things is its message too: return `actions.Answer(text,
  placed)` from the action and record the message in `placed` (timers:
  `plain.about`, `store.note_message`), so a reply to "⏸️ Paused:
  dinner" means dinner. A card's `apply` may return one too (pills:
  `plain.about`, `log_answer`, `log_saved`, `_recorded`). Never act on
  a thing that was only guessed: ask which (timers:
  `plain.which_timers`) or show the pick on a card (pills:
  `plain._unnamed`).
- **A new task starts with the `new-task` skill** (the interview, the
  contract, the spec, then the build), and every task is audited with
  `task-check`.
- **Turning tasks on and off:** `ENABLED_TASKS=builtin,greeter` in `.env`.
  Leave it empty to load everything. A disabled task keeps its data, and
  its words, slash commands and help entries disappear.
- A word, reply word or emoji can only belong to one task; the second one
  to claim it is skipped and reported at startup.

## Archive and delete

`tasks/archive/` moves messages out of the way. It only works for the
owner.

| Way in | What happens |
|---|---|
| Reply `archive` (or `box`, `file away`) | The message is copied to the archive channel under its author's name and avatar, with attachments, the original time and a link to where it was. Then the original and your reply are deleted, and "📦 Archived: link" shows for 5 seconds |
| Reply `delete` (or `remove`) | The message and your reply are deleted for good, and "🗑️ Deleted" shows for about 10 seconds. Must be spelled exactly |
| React 📦 | Same as replying `archive`, after 30 seconds. Remove the 📦 in time to cancel |
| React 🗑️ | Same as replying `delete`, after 30 seconds. Remove the 🗑️ in time to cancel |
| Apps > **Archive message** | Same as replying `archive` (fallback) |
| **Restore** button on an archived copy | Reposts the message to the channel it came from (author's name and avatar, attachments, original time), then removes the archived copy |

- **Undoing.** A 📦 or 🗑️ can be taken back by removing the reaction within
  the 30 seconds. After that an archived message comes back with its
  **Restore** button, which keeps working after a restart. A deleted
  message is gone.
- **Pinned and 📌-marked messages are asked about first**, whichever way you
  go about it: "⚠️ That message is pinned. Archive it anyway?" with
  **Confirm** and **Cancel**. Anyone's 📌 counts. The question removes itself
  if you cancel or don't answer within two minutes, and stops working if
  the bot restarts while it is waiting.
- **Otherwise there is no "are you sure?".** The word or the reaction is
  the confirmation. Archive only deletes the original after the copy, with
  every attachment, has been posted.
- **When it fails** nothing is moved or deleted. A reply gets ⚠️ on your
  reply; a reaction gets ⚠️ on the message itself. The reason is in
  #bot-log, never in the channel.
- **Restore without Manage Webhooks** in the original channel still works:
  the bot posts the message itself, headed "**Name** wrote:".
- **Where the Restore button sits:** on the archived copy if Discord accepts
  a button on the webhook message; otherwise on a small bot message
  directly beneath it.
- **It refuses** messages already in the archive channel, messages in
  #bot-log, and (for archive) messages with nothing to copy or a file too
  big to re-upload.
- **It needs** `ARCHIVE_CHANNEL_ID` in `.env`, Manage Webhooks in the archive
  channel, and Manage Messages wherever the original is.

## Pills

What you take and when, and today's checklist of it. Reminders at each
dose's time come in the next stage, so nothing notifies you yet.
Everything works in #inbox and in the hub.

| Type or say | What happens |
|---|---|
| `pills` (or `pill`) | A fresh copy of today's checklist at the bottom of the hub; the old one goes |
| "my pills", "show all my pills" | The list of every pill: in use, then ⏸️ Paused, then 🏁 Ended. Read-only |
| "took my zinc", "had pill A at 9", "skip magnesium today", "I didn't take zinc" | Today's dose is ticked off, skipped or put back, at once: "✅ **Zinc** · taken 8:04 am · still to take today: …" |
| "what pills do I have left today?" | The checklist, as `pills` |
| "add vitamin D, once a day" | A card "💊 Pills · new" with "**Vitamin D** · daily, any time", **Save** and **Cancel** |
| "add evening pill at 20:00" | "💊 **Evening pill** · daily at `8:00 pm`" |
| "add course A, 3 times a day, at least 3 hours apart, with food, for 7 days starting tomorrow" | "💊 **Course A** · 3× daily, at least 3h apart, first dose when ready · *with food* · 10 to 16 Oct" |
| "add pill A to my pills, 3 times a day at 8am, 11:30 and 3pm, at least 3 hours apart, not after 4pm, without food" | Two lines: "**Pill A** · 3× daily · `8:00 am`, `11:30 am`, `3:00 pm`" and "At least 3h apart · not after `4:00 pm` · *without food*", with no ❓ |
| "move the evening pill to 9pm" | A card: "schedule · daily at `8:00 pm` → daily at `9:00 pm`", with **Save** and **Cancel** |
| "pause iron", "pause iron until the 20th", "resume iron" | A card to save |
| "remove iron" | A card with **Remove** and **Cancel**; its history is kept |
| "delete iron and its history" | A separate card with **Delete for good** |

- **Today's checklist** is posted in the hub at 6:00 am without a
  notification (or when the bot starts later than that), as one message
  that is edited in place: "## 💊 Pills · ▰▰▱▱▱ 2 of 5", then a line a
  dose. Doses with no time come first, then the timed ones by when they
  are due today; paused pills have their own section and are not
  counted. Taken and skipped both count as dealt with.
- **A dose with no time** has a message of its own under the checklist,
  with **Taken** and **Skip**. Pressing one deletes that message and
  updates the checklist. A timed dose has no buttons yet (they come with
  its reminder): say "took …".
- **Today's times follow what you took.** With a gap, the next dose is
  shown at the later of its planned time and the dose before plus the
  gap; the plan itself never changes. A time never moves because a dose
  is overdue, and none is ever shown past the day's limit (the pill's
  latest time, or midnight).
- **A dose that can no longer be taken today is closed by the bot.** If
  it could never have been in time (the one before was taken too late,
  or still isn't taken), it is "⏭️ skipped automatically: not enough
  time before 4:00 pm", which breaks no streak. If it had its time and
  the latest time has passed, it is ❌ missed, shown a minute after that
  time without your asking. A correction that makes room brings a
  skipped dose back.
- **A pill that was guessed is shown first.** If nothing in what you
  said names the pill and Claude picks one, nothing is logged: a card
  shows the dose with ❓, **Save** and **Cancel**. An exact name, part of
  a name only one pill has, and "it" log at once.
- **A reply says which pill.** "took it" as a Discord reply to a dose's
  Taken / Skip message means that pill and that dose, whatever was
  logged last; a pill you name still wins. A reply to the checklist
  means its pill when only one is on it.
- **Logging late.** "Took my pill A" after its latest time asks first:
  "That's after the latest time, 4:00 pm. Log it anyway?" with **Log
  it** and **Cancel**.
- **Logging a dose that was missed** asks first too: "Dose 1 was
  missed (due 11:12 am). Log it as taken now?", and under the dose a
  small line when the next dose's time would move (`next: dose 2 ·
  11:30 am → 12:40 pm`). The same whether you say it, type `took
  <pill>` or press Taken.
- **Putting the dose right.** "That was dose 1" (or "no, that was my
  first dose") after a dose was logged moves that log to dose 1, with
  the time it has: a change card "**Pill A** · dose 2 → dose 1 · taken
  9:20 am" with a small line for what becomes of dose 2 ("dose 2 ·
  still to take · `12:20 pm`"), **Save** and **Cancel**. It never adds
  a second log. It is checked against what you logged, whether or not
  a card is open. Only today's logs are moved unasked: with nothing
  ticked off today the card says so and asks "Which day was it?", a
  button for each of the latest days with a log (or say the day:
  "that was dose 1 yesterday"). A correction never logs a dose.
- **A second dose within the hour is said in so many words.** When a
  card would add a dose and you logged one of that pill in the last
  hour, it reads "You already logged dose 1 at 9:20 am. That's 7m
  later. The gap is at least 3h. Add another dose?", never only "Log
  it anyway?".
- **Putting a time right.** A time said straight after logging ("I took
  it at 9am"), or one earlier than the dose last taken, corrects that
  dose: "✏️ **Pill A** (dose 1 of 3) · taken 10:57 pm → 9:00 am". "It"
  is the pill you logged last.
- **Changes during the day** show at once: a pill added, changed, paused
  or removed. A course that starts tomorrow is not on today.
- **At midnight** what nobody touched is marked ❌ missed, the single
  messages go, and the checklist is left as it ended.
- **Needs `HUB_CHANNEL_ID`** in `.env`. Without it nothing is posted by
  itself, and `pills` posts the checklist where you typed it.
- **One shape of schedule.** Every pill has doses a day, and may have a
  planned time for each dose (or for the first only), a minimum gap
  between doses ("at least 3 hours apart") and a latest time ("not after
  4pm"). Only what you say is filled in, and the card writes out each
  setting it filled in. With no time and no gap a dose is "any time".
  A dose will be due at the later of its planned time and the dose before
  it, taken, plus the gap (the checklist and reminders use this next).
- **Planned times closer together than the gap** are moved apart, and the
  card says which dose moved ("⚠️ 11:30 am to 2:00 pm is under 3h: the
  third dose moves to 2:30 pm"). A schedule that can't fit in a day, or a
  planned time after the latest time, is never saved or adjusted: the
  card shows it as read with "⚠️ … can't be saved yet: …" and has
  **Cancel** only, until a reply puts it right.
- **Courses.** A pill with dates is taken from the first to the last, both
  included ("for 7 days starting tomorrow" on the 9th is 10 to 16 Oct).
  It is listed with 🗓️ and "starts 10 Oct" until then, and under 🏁 Ended
  from the day after its last. A pill with no end has no dates: none are
  asked for or shown.
- **Nothing is saved until you press Save.** Every change is a confirm
  card with Save and Cancel, and Save is the only confirmation: the bot
  never asks "reply ok" first. Say what to change ("make it 9pm", "with
  food") and a fresh card replaces the old one. A card nobody saves
  disappears after 30 minutes. What is saved is read back from the
  database before "✅ Saved" is shown.
- **Times.** "At 8" is asked about on the card: "Is that 8 in the
  morning or the evening?" with a button for each, and no Save until it
  is answered. Press one, or just say "8pm". A time the others settle is not a guess: in "8am, 11:30
  and 3pm" the 11:30 can only be the morning. Times are always shown as
  `8:00 pm`, whatever you typed.
- **Adding a pill you already have** never makes a second one. With the
  same details: "💊 **Pill A** is already in your pills with these
  settings" and the pill, with no card. With other details: a card for
  that pill, "**Pill A** · already in your pills" and each change as old
  → new; Save changes it. A change that changes nothing ("move iron to
  8am" when it is at 8am) gets the same "already in your pills" line.
  A task gives this line through its `already_so(request, about)` hook
  and says the same one from its own code; without the hook core says
  "✅ That's already how it is".
- **What can't be read is shown, not refused.** A time, a gap, a number
  or a date the bot can't read is a line on the card ("❔ gap · I can't
  read …") beside everything it did understand, and the card has
  **Cancel** only until a reply gives it again.
- **Editing** applies from the next dose; what is already recorded stays.
  Give only what changes. "No notes", "no times" (any time), "no gap",
  "no latest time" and "no end date" take a value away.
- **Reminders** are off unless `REMINDERS_ENABLED=true` is in `.env`
  (then restart). On, a dose with a time gets a message in the hub at
  that time, with **Taken**, **Taken at…**, **Snooze 15m** and **Skip**.
  The phone shows only "💊 Dose due · 11:12 am". Left alone it comes
  again every 15 minutes, three times, and then it goes and nothing
  more is sent for that dose. The dose is still to take: it is missed
  only once it can no longer be taken today (the pill's latest time,
  or midnight). It gets **one last chance**: 30 minutes before the
  last moment it can be taken with every dose after it still fitting
  the day, a message that notifies ("💊 Last chance today · take by
  6:00 pm") with Taken, Taken at… and Skip. It goes at that moment.
  A reminder (or last chance) that Discord refuses is tried again
  after 1, 2 and 5 minutes, then every 5, while the dose can still be
  taken today; before each try the hub is read, so one that went
  through after all is finished and never posted twice. A dose with no time has its
  Taken / Skip message under the checklist and no reminder. Nothing is
  sent after a pill's latest time. Reminders go to the hub only: on
  with no hub that can be found, #bot-log says so once and nothing is
  sent. Switching the setting off and
  restarting removes any reminder that is up.
- **The new look** is off unless `CARDS_V2=true` is in `.env` (then
  restart). On, today's checklist is one message with a box a pill, in
  the colour of what is still to do, and **Taken**, **Taken at…** and
  **Skip** inside the box for its next dose (a dose with no time no
  longer gets a message of its own); the reminder, the confirm card,
  the card that asks a question and the "Log it anyway?" card are
  drawn as boxes too. What each says is unchanged. Off, everything
  looks as it always has. Colours and spacing are `core/design.py`.
- **`took <pill>`** is a typed shortcut: the word and the pill's exact
  name, nothing else ("took zinc"; any capitals). It ticks off the
  pill's next dose now, in the same words as saying it, with no request
  to Claude, so it is instant and free; too soon or too late still asks
  first on a card. Anything more ("took my zinc", "took zinc at 9",
  two pills, a pill with nothing left today) is not the shortcut and is
  read as it always was.
- **Pausing** stops a pill being asked for and leaves its streak alone.
  "Until the 20th" means it is taken again on the 20th, by itself.
- **Removing** hides the pill everywhere and keeps its history for stats.
  Deleting it with its history is only done when you ask for exactly
  that, and has its own question.
- **The list** (`pills`, "my pills", "show all my pills") is read-only
  and Live: it has no buttons, and it is rewritten in place when a pill
  changes. To change a pill, say so.

**What Claude hands over.** Times come in one fixed form (`8:00 pm`;
`8:00` when no am or pm was said, which the code then settles or marks
❓) and the gap as whole minutes (`min_gap_minutes`), so the code never
depends on how a time or a length was worded. Use `actions.TIME`,
`TIMES` and `MINUTES` for any new field that holds one, and
`actions.NUMBER` for a number that need not be whole (a weight of 62.5:
it arrives as a number, 60.0 as 60, and "62,5" typed as text is read
in code).

**Files sent with a message** reach a task's plain-words code as
`request.attachments`: each an `actions.Attachment` with its `name`,
`size`, `content_type`, `extension` and `await attachment.read()` for
the bytes. Nothing is downloaded until a task asks. The router is told
only the names ("Sent with the message, as a file: plan.csv"). A
message that is a file and no words is still ignored, as before.

**Which of my things a name means** is `core/names.py` (`names.find`):
the whole name wins over part of one, and a name that fits more than
one raises `names.Ambiguous` with the candidates, for the task to ask
about on its card. The task writes its own words for "there is none".

**In code.** The schedule itself is core: `core/schedule.py` has the
`Schedule` every pill's plan holds and `dues(schedule, day, so_far)`, which
says when each dose is due. `tasks/pills/rules.py` is pure:
`build(request, today, base)`
turns what was said into a `Plan` or raises (`TimeQuestion` for an unclear
time, `UserError` with the reason otherwise), `status_on(pill, day)` says
what a pill is on a day, and the wording is all there. `doses.py` has the
take-by time and whether a dose still fits before the day's limit.
`today.py` (pure) turns the pills and the day's occurrences into doses
and writes the checklist; `checklist.py` posts it, keeps it up to date,
marks doses and runs the 6:00 am job and the end of the day.
`store.py` holds
`pills_pills` and the change record. `plain.py` has the actions, their
cards and the read-back checks, with no discord.py. Doses will be
occurrences (`core/occurrences.py`) with task `pills` and the pill's id as
the item.

## Channel reset

Empties the channel you are in. It always asks first.

| Type or say | What happens |
|---|---|
| `reset channel` (any channel the bot can manage) | A card: "🧹 Channel · reset", "134 messages in #inbox, 3 of them pinned or 📌", "⚠️ This can't be undone", with **Delete all**, **Delete all unpinned** and **Cancel** |
| "reset this channel", "clean up this channel" (#inbox and the hub) | The same card |

- **Delete all** removes every message, pinned and 📌 ones included.
  **Delete all unpinned** leaves the pinned and 📌 ones.
- **What is live comes back**: today's pills checklist with its Taken /
  Skip messages, the cards of running timers and a Pomodoro session, the
  timers board and the dev panel are posted again, once each, and go on
  working. A card that was waiting for Save is gone for good.
- **Speed**: messages up to 14 days old go a hundred at a time; older
  ones one by one, and the card says roughly how long that will take.
- **A copy first**: before anything is deleted the whole channel is
  written to `data\exports\<channel>-<date>-<time>.txt`: who, when, what
  was said, whether it was pinned or 📌, and a link to each attachment
  (the files themselves are not downloaded, and Discord's links stop
  working once the message is gone). If the copy can't be written,
  nothing is deleted.
- **No trace of itself**: your `reset channel` (or the sentence you
  said) and the card are deleted with everything else, and on **Cancel**
  both go too.
- **When it is done**: "🧹 Channel reset: 131 messages deleted · a copy
  was saved", which deletes itself after 10 seconds (also while
  `KEEP_CONFIRMATIONS` is on), and a card in #bot-log.
- **Permissions**: the bot's role needs Read Message History and Manage
  Messages in the channel. If one is missing the card says which, and
  nothing is deleted.

**In code.** `tasks/channel/rules.py` is pure (what goes and how, the
words); `core/clearing.py` does the Discord work; a task puts its own
live messages back in `channel_cleared(channel_id, gone)`, where `gone`
is the ids that were deleted.

## Routing and confirm cards (being built)

**What is on it now.** Timers and the Pomodoro ("set a timer for 5
minutes", "pause the tea timer", "cancel all my timers", "start a
pomodoro"), bugs ("that's a bug", "show my open bugs"), pills setup ("add
iron at 8", "move iron to 9pm", "pause iron until the 20th", "remove
iron", "show all my pills"). Archive, pin and delete are not asked for in
plain words: use the reaction or the reply word. Each task's actions are in its
`plain.py` (bugs: `__init__.py`). What acts at once and what asks first:

| | At once | Asks first (a card) |
|---|---|---|
| Timers | start, pause, resume, add time, cancel one, the Pomodoro | cancelling several timers |
| Bugs | report, list | |
| Pills | the list | add, edit, pause, resume, remove, delete |

The way every task will take plain words. Nothing real uses it yet; two
demo tasks do, on the dev database only (`python main.py --dev`, #inbox or
the hub): a shopping list and a packing list.

| Say | What happens |
|---|---|
| "add milk to the shopping list" | A card: "🛒 Shopping · new", "milk · × 1", **Save** / **Cancel**. Nothing is saved until Save |
| "add honey, jam and 5 eggs" | One card with a line for each item and one Save |
| "make the eggs 6", "remove the jam", "add milk too" (with a card open) | That card is deleted and a new one shows the change |
| "add 144 eggs" | The card shows × 20 and "⚠️ eggs: 144 is more than the list takes, 20 at most" |
| "add a few eggs" | "eggs · × 3 ❓": a vague amount is a guess, and is marked. A plain "add eggs" is × 1 with no mark |
| "add milk, and remind me to call mum at 5" | The card says "⚠️ Not included: remind me to call mum at 5" |
| "got the milk", "what do I need to buy?" | Done or answered at once: these change no setup, so no card. The reply names what is left ("☑️ Ticked off **milk** × 3 · still to buy: eggs") |
| "what's the capital of France, and add milk" | Both: a plain answer, then the card |
| "clear my shopping list" | A card that says it can't be undone, with **Clear for good** |
| "pack my passport" | The packing list's card |
| "no, shopping" (after a card for the wrong list) | That card is replaced by one for the shopping list, for the same thing. The words "no, shopping" are never saved as anything |
| "what am I packing?" then "add milk" | A packing card: the list on screen says which task |
| "what's the capital of France?" | A plain answer |

- **How a message is handled, cheapest first:** a button or a shortcut
  never reaches Claude. A message about the open card costs one request
  (extraction). Anything else costs two: the router, then extraction for
  the task it chose (or a plain reply, if it is for no task).
- **A message is "about the open card"** if it is a Discord reply to it,
  or if the card is the last thing the bot said in the channel and is
  under five minutes old.
- **A card left for 24 hours expires** and nothing is saved; one in
  #guide, or pinned or 📌, waits a week at a time. What it becomes has
  Redo, which makes it again from what was said (one extraction).
- **A list you ask for is Live.** "What do I need to buy?" posts the
  list; saving, ticking off or clearing afterwards edits that message in
  place. Ask again and the new copy is the one kept up to date; the older
  one is left as it was. In code: return `actions.LiveReply(key, text)`
  from the action that shows the list, and call
  `livelists.changed(user_id, key, render)` wherever its data changes
  (`tasks/lab/demo.py` does both).
- **Set, add, remove.** "Make the eggs 7" sets the amount, "add 3 milk"
  adds to it, "remove the jam" takes it off: on an open card or on the
  saved list. A change to something already on the list shows before →
  after ("eggs · 5 → 7", "jam · × 1 → removed"). The bot does the sums.
- **"It" is the last thing mentioned**; when that isn't clear the guess is
  marked ❓. **"No, …" undoes the change before it** and applies the
  correction instead.
- **Names are kept as typed**, and singular and plural are the same item
  ("add 3 milk" adds to "milks", which then reads "milk").
- **Real tasks still go the old way** until they move: "set a timer for 5
  minutes" works as before (the router is asked first and says it is
  none of its tasks).

**In code.** `core/actions.py` is the contract: a task sets `icon`,
`only_for` and `examples` and returns `Action`s from `actions()`. Anything
that could be asked for in the plural is a list of items:
`Field("items", "…", ITEMS, required=True, item_fields=(Field("item", …,
required=True), Field("quantity", …, INTEGER)))`; `prepare` writes a line
for each and `apply` saves them all. Flag a value with
`flag(text, is_guessed(guessed, "items", index, "quantity"))`, never
because the field was absent: a default is not a guess. What Claude could
not place arrives as "Not included" on the card without the task doing
anything. A task that keeps a list adds `change_field()` to its item
fields, and in `prepare` merges the message into the open card with
`merge_items(request.previous["items"] if request.previous else [],
data["items"], same=…, exists=…, said=request.text)`: `request.previous` is the open card's
data when the message corrects one. `prepare` shows before → after for
what is already saved and `apply` does the sum against the list as it is
at Save. An action
that changes setup has `prepare(request, data, guessed) -> Proposal` (the
card) and `apply(request, data) -> str` (Save: do it and return what to
say); any other has `needs_card=False` and `run(request, data, guessed) ->
str`. `tasks/lab/demo.py` is the example. `core/routing.py` and
`core/extraction.py` make the two requests, `core/confirm.py` keeps the
cards, `core/conversation.py` ties them together. The full write-up of the
contract comes when the real tasks have moved.

**Fixtures and the live eval.** `evals/fixtures/*.json` holds, per task,
sentences for the router (which task, a tie, or chat) and for extraction
(which action, what data, what was guessed). `python -m pytest` replays
what the real API last returned for each through the checking code, with no
network. `python -m evals.live --live --dev` asks the real API (a few
cents; it prints the cost) and says how many it got right; add `--record`
to keep the answers for the tests, `--strict` to time strict schemas.
Add a fixture for every example in a task's spec and every bug QA finds.

## Timers and Pomodoro

`tasks/timers/` is for short timers and focus sessions. Everything is
typed (there are no slash commands), works in any channel, and survives a
restart. Date-based reminders are a separate, future task.

| Type | What happens |
|---|---|
| `timer 25m`, `timer 1h30 laundry`, `timer 2 hours` | Starts a timer. The label is optional and defaults to "Timer" |
| `timers` (or `timer` on its own) | Lists your active timers and the current Pomodoro, in every channel. The list is live: it updates whenever a timer changes, and asking again replaces it |
| `pause all`, `resume all` | Pauses (or sets going again) every timer and the Pomodoro, and lists each with its time left. `pause all except pomodoro` or `pause all timers only` leaves the Pomodoro alone. A timer that has already run out is left alone |
| `pomo` | Starts a session: 25 minutes of focus, 5-minute breaks, a 15-minute break after 4 rounds |
| `pomo 50/10`, `pomo 50/10/30` | Custom focus/break lengths; the third number sets the long break (otherwise 15) |
| `pomo deep work`, `pomo 50/10 writing` | Anything else is the label |
| `pomo auto`, `pomo manual` | Whether phases start by themselves, for this session |
| `pomo stats` | Completed focus time today and this week |

**Durations** are read by code, not by Claude: `90s`, `25m`, `1h30`,
`1h 30m`, `1.5h`, `2 hours`, `45 min`, `1:30` (hours and minutes). A bare
number is minutes. From 5 seconds to 24 hours.

**A timer** posts one message with a live "ends in…" time. Reply to it with
`pause`, `resume` (or `unpause`), `cancel` or `+10m` (also `+ 10 min`,
`extend 10m`). When
it finishes, that message is edited to say so and you are @mentioned in a
new message with **+5 min**, **Restart** and **Dismiss**. Pressing any of
them, or replying `ok` (or `done`, `dismiss`) to the alert, clears the alert
away; the original message stays as the record.

**A Pomodoro session** is one card, edited in place, showing the phase,
round, label and a live time, with **Pause/Resume**, **Skip** and **Stop**.

- **At each phase end** you are @mentioned with **Start** and **Skip**, and
  the next phase's clock only starts when you press **Start**. `pomo auto`
  (or `POMO_AUTO_CONTINUE=true` in `.env`) starts phases by themselves.
- **Each alert is cleared once you respond to it:** Start, Skip, the **OK**
  button on auto-mode alerts, or a reply of `ok` / `done`. Replying `ok`
  only acknowledges; it doesn't start the phase.
- **Skip** moves straight on to the next phase. A skipped focus round is
  not counted in the stats; only ones that run to the end are.
- **One session at a time.** Stop the current one before starting another.
  `pomo` while one is going shows its card again at the bottom of its
  channel (or, from another channel, a short pointer to it). With other
  lengths (`pomo 25/5` while 50/10 is going) it also asks "Restart it as
  `25/5`?": Confirm stops the session and starts one with those lengths
  and the same label.
- **The same reply words work on the card:** `pause`, `resume`, `stop`,
  `+10m` (adds to the current phase).
- **After a long break** the rounds start again from 1.

**The board.** Each channel where a timer has been started has one pinned
"Active timers" message, rewritten on every change and reading "No active
timers" when empty. Discord's "pinned a message" notice is deleted. The
board carries a 📌 reaction, which marks it as exempt from the (future)
nightly sweep.

**Restarts and downtime.** Timers, sessions and their due moments are in
the database, and the buttons are found again by their ids. If something
finished while the bot was off, you are told at the next start that it
finished late. After downtime a session always waits for **Start**, even
in auto mode.

**Things to know:**

- **Times use Discord's live timestamps**, so messages are only edited when
  something changes, not every second.
- **Nothing visible happens for `cancel`, `pause` and the like replied to a
  message that isn't a timer:** those words are only commands on timer
  messages, so elsewhere they are ordinary chat.
- **The bot needs Pin Messages** (or Manage Messages) to pin the board and
  to remove the pin notice. Without it the board still works, unpinned,
  and #bot-log says so.
- **`10 min walk`** is read as ten minutes labelled "walk", because "min"
  is a unit.
- **For a quick try-out** use seconds: `timer 10s tea`, `pomo 30s/10s`, or
  speed the clock up with `dev speed 60` (see "Dev mode").

## Dev mode

A switch for testing: shorter waits, debug cards in #bot-log, and tools for
looking inside the bot. Owner only (permission `dev`), typed in any channel,
no slash commands. `help dev` lists the words.

| Type | What happens |
|---|---|
| `dev on` | Switches it on with the dev defaults, for 1 hour |
| `dev off` | Switches it off and restores normal settings |
| `dev mode on`, `dev mode off` | The same two, by their longer name; this is also what Claude runs when asked |
| `dev` | Shows the panel again, at the bottom of the channel you are in |
| `dev reset` | Dev settings back to the dev defaults, with a fresh hour |
| `dev debounce <seconds>` | Quiet time before reactions are acted on. 0 acts at once |
| `dev speed <n>` | Timers and Pomodoro phases run n times faster |
| `dev verbose on\|off` | Debug cards in #bot-log |
| `dev quiet on\|off` | `on`: quiet hours apply as normal. `off`: alerts ignore them |
| `dev cleanup on\|off` | `off`: nothing is deleted automatically, so every command, confirmation and alert stays on screen |
| `dev expire <duration>` | Switches itself off after this long (`30m`, `2h`) |
| reply `dev inspect` | What the bot knows about the message you replied to |
| `dev jobs` | What the scheduler has booked, and how the last run of each kind of job ended, with its line |
| `dev mock [<name>]` | Posts the card sketched in `docs/mockups/<name>.txt` here as a Components V2 message; on its own, lists the sketches. See "Mock-ups" below |
| `dev run <handler>` | Runs one of the scheduler's handlers now, outside its schedule (`dev run backup`, `dev run checklist`). It is a run of its own in the log and never stands in for the scheduled one |
| `dev fire next` | Runs the next pending job now, whenever it was due |
| `dev seed <n>` | Posts n sample messages (up to 20), tagged as test data |
| `dev clean` | Deletes the tagged messages in this channel |
| `dev clock` | Shows the bot's clock, and how far ahead of the real time it is |
| `dev clock <time>` | Dev database only. Moves the clock ahead to the next time it reads that (`5:59am`, `20:00`, `noon`) |
| `dev clock +<duration>` | Dev database only. Moves it ahead by that much (`+2h`, `+15m`; up to 24h a go) |
| `dev clock reset` | Back to the real time |
| `dev cost` | What the messages in this database cost: today (against the daily limit), this month, the average per message and the most expensive task |
| `dev why [n]` | The trace of my last message, or my last n (up to 10), a copyable block each: said, route and why, the router's answer, each extraction, each check the code ran, the card before and after, what was shown, the cost per request. Leave a note from any code with `trace.note("…")` |
| `dev reset-db` | Dev database only. Asks, then wipes `data/dev.db` and starts it empty, with the clock back at the real time |

| Setting | Normal | Dev default |
|---|---|---|
| Reaction debounce | `REACTION_DEBOUNCE` (30s) | 2s |
| Speed | 1x | 1x |
| Verbose log | off | on |
| Quiet hours | respected | ignored |
| Clean-up | on | on |
| Expiry | none | 1 hour |

- **Each setting word switches dev mode on first** if it is off, with the
  other settings at their dev defaults.
- **The panel** is one pinned message in the channel where dev mode was
  switched on. It shows each setting against its normal value and a live
  expiry time, and is edited in place on every change. Its buttons are
  **+1 hour**, **Reset** and **Disable**. On `dev off`, Disable or expiry it
  is unpinned and deleted, and #bot-log says why dev mode ended.
- **In memory only.** A restart always comes back with dev mode off. A panel
  left pinned by the restart is removed at startup.
- **The bot's status** reads "🛠️ Dev mode" while it is on.
- **Speed applies when a clock is set.** A timer already running keeps its
  end time when the speed changes or dev mode ends. Cards still show the
  stated length (`25m`) with the real end time. Focus rounds that finish
  while the speed isn't 1x are not counted in `pomo stats`.
- **Verbose cards** (titles start with 🛠️) cover every word and reply action
  (trigger, outcome, time taken), every settled batch of reactions (where
  each ended up, what was applied or undone) and every scheduler job.
- **`dev cleanup off`** is for seeing exactly what was sent: confirmations
  and "Read as" notes stay, your command words stay, acknowledged alerts
  and pin notices stay, and a removed dev panel is only unpinned. It ends
  with `dev cleanup on`, `dev off` or the expiry. Deleting because you
  asked (`delete`, `archive`, `dev clean`) still works.
- **`dev inspect`** shows: the message's lifecycle class and what happens to
  it, pinned, protected from clean-up (pinned or 📌),
  the reactions on the message, the reaction actions applied to it
  (`reaction_state`) and its archive record, if it was archived or is an
  archived copy. "Kept" is yes once your 📌 on it has been acted on.
- **`dev fire next`** takes the earliest pending job, which may be the
  nightly backup (it books its successor as usual).
- **Test data** is anything the bot posted ending `-# 🧪 dev test data`:
  seeded messages, the "Seeded…" line that says how to remove them, and the
  output of `dev inspect` and `dev jobs`. `dev clean`
  looks through the last 200 messages of the channel and never removes one
  that is pinned or 📌-marked.
- **The dev database.** `python main.py --dev` (with the service
  stopped: it is the same bot, and only one copy may run) uses
  `data/dev.db` instead of `data/assistant.db`, and `data/dev-backups/`
  for its backups. Everything else is the same: the same Discord server
  and channels, the same `.env`. It is created empty on its first start.
  The bot's status reads "🧪 DEV DATABASE" for as long as it runs, the
  log file says so at start, and the dev panel has a
  "🧪 **DEV DATABASE**" line. `dev reset-db` wipes it (Confirm / Cancel
  first); cards already in Discord are left behind, so restart the bot
  if anything looks stale.
- **The dev clock** moves the bot's idea of the time, so a day of
  reminders can be run in minutes. It only works on the dev database: on
  the live one `dev clock <anything>` gets ⚠️ and the reason, and only
  plain `dev clock` (show it) works.
  - It only moves forward. `dev clock 6am` at 3pm is 6am tomorrow, by
    way of midnight; `dev clock reset` is the one way back.
  - It keeps ticking from where you put it, and stays there through
    `dev off`, dev mode's expiry and a restart (the offset is in
    `data/dev-clock.json`). Dev mode doesn't need to be on.
  - When it moves, every scheduler job that came due on the way runs at
    once, in due order, as if on time (`job.is_late` is false): a timer
    ends, midnight's rollover runs, the backup runs. To test the
    catching-up path, stop the bot, wait, and start it again.
  - A time that could be morning or evening is refused with "6am or
    6pm?": say which.
  - Times Discord renders itself (a timer's "ends in…") go by the real
    time and will look wrong after a move.
- **What the requests to Claude cost, and why**, is `docs/COSTS.md`:
  each kind of request measured, which prompts are long enough to be
  cached (Haiku 4.5 needs 4,096 tokens: only pills and timers
  extraction are), and what each is sent. When adding to a prompt, put
  what is the same for every request first, in a block marked
  `llm.CACHED`, and what changes after it. A rule that applies to every
  action is said once in extraction's `rules`, not in each schema.
- **Money is in NZ$.** Every cost you read (`dev cost`, a ping, the
  briefing, the status line) is NZ$; what is stored stays US$, which
  is what Anthropic bills. The rate is fetched once a day at 5:30 am
  ("Exchange rate" in `my schedule`, from Frankfurter, the European
  Central Bank's rates: free, no key). If that fails the last known
  rate goes on being used; with none yet, `USD_TO_NZD` in `.env`
  (1.70). The last line of `dev cost` says which rate and from when.
- **The daily spend line.** `DAILY_SPEND_LIMIT_NZD` in `.env` is what a
  day's requests to Claude may cost in NZ dollars (1.00 unless set; 0
  switches the note off). The first time a day's total passes it,
  #bot-log gets one card, "💰 Claude spend is over today's limit", and
  no more that day, whatever restarts in between. Nothing is stopped.
  `dev cost` shows today's spend against the limit.
- **`dev cost`** adds up the database the bot is running on (the live one
  for real figures; the dev one has its own). Every logged message has a
  route: `shortcut` (a typed word), `button`, `reaction`, or one that
  went to Claude (`router`, `follow-up` or `chat`; `tools` is the old
  way, in rows from before it was removed). For those it shows the cost,
  the requests and the seconds per message. A message for two tasks is
  charged half to each; chat is "no task". Days and months go by the real clock, not
  the dev clock. In code: `core/costs.py`; a message's cost is recorded
  with `database.record_cost(row_id, route, tasks, calls)`, and each
  request to Claude says what it was for through
  `timing.record_claude(..., purpose=, task=)`.
- **Not built yet:** quiet hours. `dev quiet` is stored and shown and
  changes nothing so far.

**In code.** `core/devmode.py` holds the state and is what other code asks:
`reaction_debounce()`, `speed()`, `real_seconds()`, `nominal_seconds()`,
`is_verbose()`, `quiet_hours_ignored()`. Each gives the normal value when
dev mode is off, so callers never check whether it is on. Add a debug card
with `await devmode.debug(title, lines)`; it does nothing unless verbose is
on. `dev run <name>` runs any handler the scheduler has
(`scheduler.register_handler`): there is no list of its own.
The words, panel and tools are in `tasks/dev/`.

**Time in code.** Never call `datetime.now()` or `time.time()` for
anything time-based: ask `scheduler.utc_now()` / `clock.now()` (a UTC
moment) or `config.now_nz()`, which follow the dev clock.
`clock.real_now()` is only for records of what really happened. Which day
it is comes from `core/day.py`: `day.today()`, `day.day_of(moment)`,
`day.at(day, time)` for "8pm today" as a moment, `day.end_of(day)` for
midnight. Work for the end of a day goes in the task's
`async def new_day(self, ended, started)`: it is called once per rollover,
and `started - ended` is more than a day if the bot was off over a
boundary. A time the user typed goes through `timeinput.parse_time`
(catch `AmbiguousTime` and offer its two `options`), a time something was
done at through `timeinput.actual_moment`, and every time shown through
`timeinput.format_time` or `format_moment`. In tests, pass `now` in where
a function takes it, or use the `dev_clock` fixture to move the clock.

**The occurrence log in code.** `core/occurrences.py` holds what is
expected on a day. Make today's with `db_ensure(conn, user_id, task,
item_id, day, seq, planned_time, due_at)`; it returns the existing one
untouched if there is one, so it is safe at every start. Change one with
`db_done`, `db_skip`, `db_miss`, `db_reopen`, `db_move` or `db_change`,
giving where the change came from (`BUTTON`, `FORM`, `MESSAGE`,
`AUTOMATIC`). Pass the same `change_id` (`new_change_id()`) to changes
that belong together, inside one `database.run`, and
`db_last_change` / `db_revert` will treat them as one.

### Days of the week, and a dose of last night

- **A pill on certain days only**: "add zinc on weekdays only", "iron
  is Mon Wed Fri", "make it weekends". The card and the lists show the
  days where "daily" would stand ("**Zinc** · Mon to Fri at `8:00 am`",
  "2× a day, Sat, Sun, any time"). On its other days no dose is
  expected, nothing reminds, and the streak is not touched; the
  checklist lists it at the bottom, uncounted, under "🗓️ Not today"
  with its days. "Zinc is every day again" takes the days away. Every
  day of the week is simply daily.
- **A dose of the day before, logged after midnight**: "took zinc last
  night at 11", "I took my evening pill yesterday at 9pm". Yesterday's
  dose (missed by then) is logged as taken at that time and the line
  ends "· yesterday". It is done at once when you say the day and the
  time reads one way ("last night at 11" is the evening). It **asks
  first, on a card with Log it**, when something had to be worked out:
  a time that has not come yet today, said before 4:00 am with no day
  ("I took it at 9pm" at half past midnight); a time that could be
  morning or evening ("yesterday at 8"); or no time at all (the planned
  time is used, or 11:59 pm for a pill with none). Only "taken" can be
  logged for yesterday, and only for the day before.

### Looking back: yesterday, the week, the streak

- **"What did I take yesterday?"** A reply from the record: "💊
  **Yesterday** · Mon 12 Oct · 4 of 5 taken · 1 missed", then a line a
  dose as the checklist words it. A pill paused, changed or removed
  since is still shown as it was that day.
- **"Show my week"**: the week today is in, Monday to Sunday, a line a
  day up to today: `` `Tue 13` ✅✅❌ 2 of 3 `` (✅ taken, ⏭️ skipped, ❌
  missed, ▫️ still to take), with the count for the week on the first
  line and the streak on the last.
- **The streak** is counted in days, one for all pills: a day counts
  when something was taken and nothing was missed. Only a missed dose
  breaks it; a skip, a pause and a day with nothing to take never do.
  It is said from two days up ("🔥 Streak · 5 days"): in the week, in
  the weekly summary, and in the briefing's pills section.
- **The weekly summary** is off unless `WEEKLY_SUMMARY=true` is in
  `.env` (then restart). On Sunday at 7:00 pm the week is posted in
  the hub ("💊 **Your week** · …"), without a notification; a newer
  one takes the older one's place. It is a schedule: `my schedule`
  shows it as "Weekly pills summary" and moves it ("move the weekly
  pills summary to 8pm", "make it notify"). A week with nothing to
  take posts nothing.

### Mock-ups: `dev mock`

A card is sketched in a text file in `docs/mockups/` and posted as a real
Components V2 message, so a design can be looked at in Discord before any
of it is built. A line at a time:

| In the file | Becomes |
|---|---|
| `┃ …` | A line inside a Container. Lines that follow each other are one Container; a blank line ends it |
| `┃ accent: amber` | That Container's accent colour (its first line): green, red, amber, yellow, blurple, blue, grey |
| `[✅ Taken: green] [⏭️ Skip: blurple]` | A row of buttons: green, red, blurple, or grey for `[↩️ Cancel: grey]` only. Pressed, they only say it is a mock-up |
| `---` | A separator |
| anything else | Text as Discord writes it: `# ` and `## ` headings, `-# ` subtext, `**bold**` |

Text, buttons and separators work inside a Container and outside one. A
mistake is said in a line with the number of the line it is on. The
reading is `tasks/dev/mock.py`; the real cards are not built from these
files.

### #commands, the nickname and the status

- **#commands** (`COMMANDS_CHANNEL_ID`) is written from the task
  registry every time the bot starts, and only touched when it would
  read differently, by editing its messages in place: one is added or
  deleted only when the number of sections changes
  (`tasks/builtin/commands.py`, `core/mirror.py`). A
  typed word says which group it goes in with `purpose=`
  (`actions.SET_UP`, `EACH_DAY`, `SEE`); a plain-words action with
  `purpose=` and `say=` (what one might type: placeholder names only); a
  task lists its buttons in `buttons()`. A registration that is
  `housekeeping` is listed with the housekeeping; a task marked
  `testing` (dev, lab) comes last.
- **The nickname and the status** are `core/identity.py`. A job that
  catches its own failure, or decides not to do its work, says so with
  `scheduler.report(job, scheduler.FAILED)` (or `SKIPPED`): the status
  then shows that job until one of its runs works.

## Lab commands

`tasks/lab/` is a test bench for Discord features. Type `lab …` in any
channel, or use `/lab …` as a fallback: both run the same code. It only
works for the owner, and every use is logged to `message_log` and #bot-log.
To switch it off, leave `lab` out of `ENABLED_TASKS`.

| Type | What it shows |
|---|---|
| `lab react` | Posts a message with 🔴 🟢 🔵 🟡 (plain colours, so they never trigger a real action). React on it; after 15 quiet seconds it shows the final state and a timeline, then adds ✅ |
| `lab buttons` | A counter, toggles, single and multi selects, a modal form, an ephemeral reply and a link button; plus persistent buttons that still work after a restart |
| `lab pin [start\|stop]` | Pins a status message that updates every minute (and resumes after a restart); `stop` unpins it. Pin changes anywhere are logged to #bot-log |
| `lab chart [quickchart\|matplotlib] [days]` | Messages per day and cost per day as two charts, drawn by QuickChart (a web service) or matplotlib (on the server) |
| `lab notify <normal\|silent\|mention\|dm\|all> [delay <seconds>]` | A normal, silent, @mention or direct message (the DM is a short pointer with a link back to a marker message in the channel, as real DMs will be). `all` sends the four in that order, 5 seconds apart. `delay 90` waits first (up to an hour), so you can lock your phone: `lab notify all delay 90` |
| `lab time` | Every dynamic timestamp style |
| `lab thread` | A message with a thread started on it |
| `lab poll [multiple]` | A native poll that runs for an hour |
| `lab file [days]` | Daily stats from `message_log` as a CSV file |
| `lab format` | Markdown, spoilers, ANSI colours, long message splitting |
| `lab layout` | Components v2 (containers, sections, thumbnails) |
| `lab countdown [seconds] [step]` | A self-editing message; reports rate limits |
| `lab tour [new\|stop]` | A guided run through the interactive tests on one card. Typed only; see below |
| `lab channels [delay <seconds>]` | Test messages across four channels, timing your reply in each. Typed only; see below |

Arguments in square brackets are optional; a wrong one gets a ⚠️ on your
message and the usage line in #bot-log. The slash versions take the same
options by name (`/lab chart renderer: days:`) and add a private "done"
note; the typed versions show the same note for 5 seconds.

A delayed `lab notify` is answered straight away and sent in the
background. It is held in memory only, so restarting the bot before it
fires cancels it. What was sent is logged when it finishes.

### Problems of the bot's own: a bug each, and its memory

- **A job that did not work files a bug by itself**: the nightly
  backup failing, the checklist with nowhere to post. One bug for each
  kind of job ("by the bot itself", in the forum like any other); when
  it happens again while that bug is open, the bug gets a note, never
  a second bug. The status line points at it ("⚠️ B14 · backup
  failed") until that job next works. When it does, the bug gets one
  note, "Worked again: …", and stays open until you press Fixed or
  Won't fix: the bot never closes one.
- **Memory**: `dev status` shows what the bot holds now, its peak
  since it started and how it moved over the last day. Every hour the
  figure is written in the log ("Memory: 95 MB (peak 101 MB since the
  start, 12 readings)"). Over `MEMORY_LIMIT_MB` (300 unless set), or
  after a day in which each quarter of the day was higher than the one
  before by 15 MB or more in all, it is a level 1 item ("⚠️ B9 ·
  memory 312 MB") and files its bug, with the last readings; while it
  lasts the bug gets a note a day.
- **Dev mode left on** on live shows as "🛠️ dev mode" at level 1.

### The status line

Live's status line is the top attention item ("💊 2/5 · 12pm", "⚠️
backup failed", blank with nothing to look at): see "Attention items"
above and `docs/DESIGN.md`. It no longer says "🟢 Live" or the uptime:
`dev status` shows how long the bot has been up.

### `lab tour`: the guided test run

Type `lab tour` (best in #inbox, since two steps need it). One card appears
and is edited in place as you go, with **Pass**, **Fail**, **Skip**,
**Back** and **Stop** buttons.

| Step | What you do | Passes by itself when… |
|---|---|---|
| 1. Plain-word shortcut | Type `ping` or `stats` in #inbox | a plain word runs |
| 2. Buttons | `lab buttons`, then press Count, flip a toggle, use a select, submit the Form | all four have been used |
| 3. Reactions and debounce | `lab react`, react, wait 15 seconds | the quiet period ends and the summary is posted |
| 4. Reply "archive" | Reply `archive` to a message | the archive worked and your reply was cleaned up |
| 5. 📦 reaction | React 📦 to a message | it is archived after the 30-second wait |
| 6. Pinned dashboard | `lab pin`, watch a minute tick, `lab pin stop` | never: it ticks the boxes, you press **Pass** |
| 7. Chart | `lab chart` | never: you judge whether it reads well |
| 8. Claude chat and reset | Message Claude in #inbox, then `reset` | Claude answered and then memory was cleared |

- **Steps tick themselves** as the bot notices each thing happen. Steps
  that are a matter of judgement (6 and 7) tick their boxes but wait for
  your verdict. **Back** reopens the previous step if you disagree with an
  automatic pass.
- **Fail** opens a small form for a short note; the note appears on the
  card and in the results.
- **The card gets buried** as you type test messages. Type `lab tour` again
  to bring it back down to the bottom.
- **It is resumable.** The run is saved after every change, so after a
  restart the buttons still work and `lab tour` carries on at the same
  step. `lab tour new` abandons the current run and starts again;
  `lab tour stop` ends it early.
- **Results** are saved in `lab_tour_runs` and `lab_tour_results`, the card
  turns into a summary, and the same summary is posted to #bot-log.

### `lab channels`: notifications across channels

`lab channels delay 60` waits a minute (lock your phone), then posts one
test message in each of four channels, 5 seconds apart, each asking you to
reply there:

| Channel | Style |
|---|---|
| #reminders | normal |
| #gym | @mention |
| #admin | silent |
| #inbox | cross-channel link: a link to the #reminders test, to tap and come back from |

- **Reply with anything in each channel.** Your next message there is the
  reply being timed: it gets a ✅ and is not passed on to Claude. Words such
  as `help` still work and don't count as the reply.
- **Results:** when you have replied everywhere, or 10 minutes after the
  last message, a card is posted where you typed the command (and logged to
  #bot-log) with each channel's response time, or "no reply".
- **Claude history check:** the card also reports whether Claude's
  conversation history is kept separately per channel. It is checked on the
  real history store. Claude only chats in #inbox today, so the other
  channels' histories are empty.
- **A channel that isn't set in `.env`** or that the bot can't see is
  reported on the card; the others still run.
- **One test at a time, and it is held in memory:** restarting the bot
  cancels a test in progress.

Slash commands are synced to the server the inbox channel is in, every time
the bot starts. The log file's "Started:" line says how many were synced.

**Permissions the bot's role needs** (a missing one gives a message, not a
crash): Send Messages, Embed Links, Attach Files, Read Message History,
Add Reactions, Create Public Threads, Send Messages in Threads, Create
Polls, Manage Messages, Pin Messages, Manage Webhooks.

**Troubleshooting:**

- **Your message got a ⚠️:** it was understood but failed. The reason is on
  the latest "Command failed" card in #bot-log.
- **A word does nothing:** check `help` in that channel. Plain words such as
  `stats` only work in #inbox; the message must be the word and nothing
  else; and only the owner is listened to.
- **A word went to Claude instead:** it wasn't an exact match or a
  one-letter typo of a word with five or more letters.
- **`/lab` doesn't appear:** check the "Slash commands" line on the start
  card. If the sync failed with "Missing Access", re-invite the bot with the
  `applications.commands` scope. Restarting Discord refreshes its list.
- **"The lab isn't for you":** your Discord ID isn't `OWNER_ID`.
- **`lab countdown 30 1`** is the easy way to see rate limiting: watch for
  "🚦 Rate limited" cards and the slow-edit count in the summary.
- **QuickChart fails:** it is a third-party web service
  (`quickchart.io`). It is sent dates, daily counts and daily cost only,
  never message text. Use `lab chart matplotlib` if it is down.
- **`lab react` message never updates:** it only watches messages posted
  since the bot last started, and only counts the owner's reactions.
- **The interactive `lab buttons` message stops working:** it expired
  (15 minutes) or the bot restarted. Only the second, persistent message is
  meant to survive. You get "⌛ That button or form no longer works" and an
  "Interaction not answered" card in #bot-log.

## Two bots: live and the dev bot

There are two Discord applications. **Live** is the assistant: the
service `assistant-bot`, `python main.py`, the database
`data/assistant.db`, the settings in `.env`. **The dev bot** is a
second application in the same server: `python main.py --dev` and the
self-test, the database `data/dev.db`, its token in `.env.dev`. They
run at the same time, from this one folder.

| | Live | The dev bot |
|---|---|---|
| Started by | the service, or `python main.py` | `python -m selftest`, or `python main.py --dev` |
| Settings | `.env` | `.env.dev` first, then `.env` for everything but channels |
| Database | `data/assistant.db` | `data/dev.db` (may be wiped; its clock may be moved) |
| Lock | `data/bot.lock` | `data/bot-dev.lock` |
| Log | `logs/bot.log` | `logs/dev-bot.log` |
| Channels | every channel in `.env`, and the rest of the server | only #selftest-inbox, #selftest-hub, #selftest-log and the forum #selftest-bugs |
| Bugs | B numbers, in #bugs | D numbers, in #selftest-bugs |

- **Every start proves which bot it is, first.** Before the lock, the
  database or the gateway, a start asks Discord (over HTTP, so the
  account does not even come online) which account its token belongs
  to, and compares that with `BOT_USER_ID`: live's id in `.env`,
  the dev bot's in `.env.dev`. Not that account, or no id set: it logs why
  ("Not started: this start is meant to be … but its token logs in as
  …") and exits with code 4, having posted, renamed and touched
  nothing. Once connected it looks once more and disconnects at once
  if the answer differs. Discord not answering is asked five times and
  then exits with code 1 (the service tries again); it is never taken
  for the right account.
- **Which bot a process is follows the token it will really use**, not
  what the files say, and the self-test's launcher hands each start
  the dev bot's token explicitly, in an environment with nothing of live's in
  it. (On 2026-10-13 a self-test ran as live's account beside live for eight
  minutes: its starts had inherited live's token from the launcher,
  which had read `.env`. Nothing reached a real channel; the guard
  above is what now makes that impossible.)
- **The lock is one a bot, not one a folder.** One copy of each may
  run; live and the dev bot never stop each other. `python -m
  core.instance_lock` says which are running.
- **Each keeps to its own channels.** Two bots in a server both see
  every message and reaction in it. The dev bot acts only in the
  channels `.env.dev` names, and their threads; it takes no channel
  from `.env`, so a channel left empty in `.env.dev` is one it does not
  have, and it can never post in a real one. Live acts everywhere
  except in the dev bot's channels. A button belongs to the bot that
  posted its message, so a press never reaches the other.
- **`.env.dev`** (never committed; copy `.env.dev.example`): the dev
  bot's `DISCORD_TOKEN`, and `INBOX_CHANNEL_ID`, `BOT_LOG_CHANNEL_ID`,
  `BOT_USER_ID` (its own account id), and `INBOX_CHANNEL_ID`,
  `BOT_LOG_CHANNEL_ID`, `HUB_CHANNEL_ID` and `BUGS_CHANNEL_ID` set to the self-test's
  channels (`python -m selftest --channels` checks they are there; it
  makes none). `ASSISTANT_NAME` there gives it a name
  of its own in what it says.
- **Setting the dev bot up** (done once, 2026-10-13): in the Discord
  Developer Portal, a second application with a bot, the Message
  Content and Server Members intents switched on, invited to the
  server; its token in `.env.dev`.
- **It registers no slash commands**, so the server shows only
  live's. (Each start of the dev bot also clears any it once had.)
  Typed words, replies and reactions work for it as for live.
- **The names**: in code, docs and messages they are "live" and "the
  dev bot", never a display name. Which is which is the account id
  (`BOT_USER_ID`). What each is called in Discord is `BOT_NAME` in its
  settings file: change it there (and restart that bot), since a bot
  takes that name again on every start. The dev bot is "<name> ·
  testing" while a self-test runs and its plain name after; live's
  name never changes (`docs/DESIGN.md`, "The bots' names").
- **Typing to the dev bot by hand**: start `python main.py --dev` and
  write in #selftest-inbox. Live does not answer there. The self-test
  empties those channels at the start of every run.

**Without a token in `.env.dev`** (or with no `.env.dev`) there is no
dev bot: `--dev` is live's own account on the dev database. It then
shares live's lock, cannot run beside live, uses live's channels, and
the self-test needs live stopped. That is the fallback, kept working.

### When live does stop

- **Its status says why**, when it is a self-test without a dev bot:
  "🧪 Self-test running · back about <time>", before anything else the
  status would say.
- **What you said meanwhile is asked about, never acted on.** When
  live starts, it reads back every channel in `.env` that holds
  messages (but #commands) to the last moment it knew it was running,
  and each message of yours it never saw gets a card in that channel:
  "📭 I was offline when you sent this", the time, a link, the message
  quoted, and **Handle it now** and **Ignore**. Handle it now takes the
  message exactly as if you had just sent it, and the card goes;
  Ignore removes the card and nothing else. A message gets one card
  ever, so another restart before you answer asks nothing twice. After
  a long stop only the latest 20 get a card, and one line says how
  many earlier ones did not.
- The bot notes that it is running twice a minute (in real time), so
  "while it was off" is known to the half minute; a message from that
  last half minute is looked up, not assumed. The first start on this
  code has no such note and reads nothing back.
- Reactions made while it was off are not read back (in the backlog).

## A folder of its own for live

Today the service runs from the folder the code is worked on in, so the
live bot runs whatever branch is checked out there.
`scripts\setup-live-folder.ps1` gives live a second folder on `main`.
It is prepared and has only ever been run with `-WhatIf`: run it
yourself, at the PC.

1. Make sure `main` has everything live needs. The script checks that
   the code on `main` knows the live database and stops, with nothing
   changed, if the database is newer (live runs `feature/pills` today:
   merge it into `main` first, or pass `-Branch`).
2. Open a Terminal as Administrator in this folder and look first:
   ```powershell
   .\scripts\setup-live-folder.ps1 -WhatIf
   ```
   It prints the service as it is, as it would be, and every step.
3. Run it for real (add `-Start` to start the service at the end):
   ```powershell
   .\scripts\setup-live-folder.ps1 -Start
   ```
   It stops the service, clones into `..\assistant-bot-live` (or
   `-Target`), copies `.env` and `data\` (not the lock, the dev
   database or its backups), makes the `.venv`, checks the database
   against the code, and points the service at the new folder. Each
   step is printed before it is done, and a failed step stops it.
4. To go back: `nssm stop assistant-bot`, run the lines in
   `service-before.txt` in the new folder, `nssm start assistant-bot`.

Afterwards: update live with `git pull` in the live folder and
`nssm restart assistant-bot`; in this folder use only
`python main.py --dev`. Each folder has its own `data\bot.lock`, so
live and a dev copy can both run: give dev a bot of its own first
(above), or the same bot answers twice.

## Day-to-day workflow

1. Stop the service (Terminal as Admin): `nssm stop assistant-bot`
2. Make changes and test: `python main.py`, or `python main.py --dev` to
   test on the dev database (see Dev mode) and leave the real one alone
3. Stop the test run: `Ctrl + C`
4. Review: `git status` then `git diff`
5. Commit and push:
```powershell
   git add .
   git commit -m "Describe the change"
   git push
```
6. Start the service: `nssm start assistant-bot`

**Never run the service and a test copy at the same time**, or every
message gets two replies. The bot now refuses: a second copy logs "Another
copy of the bot is already running (PID …)" and exits with code 3. The lock
is `data/bot.lock`; it frees itself when the bot stops, even after a crash,
so the file never needs deleting.

Run this once (Terminal as Admin), so the service stops instead of retrying
every few seconds when a test copy is already running:

```powershell
nssm set assistant-bot AppExit 3 Exit
```

To see what is running, ask the lock: it is the source of truth, because
only one process can hold it and the system lets go of it the moment that
process ends.

```powershell
python -m core.instance_lock
```

It prints "1 bot is running: PID …, started …" or "No bot is running",
and flags any other process running `main.py` without the lock. It doesn't
start the bot. `dev status` in Discord says the same.

By hand:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine
```

One bot shows as **two** `python.exe` lines with the same start time: the
`.venv` launcher and the real Python it starts. One line's ParentProcessId
is the other's ProcessId: that is one copy, not two, and the child is the
one whose PID is in `data/bot.lock`.

## Tests

```powershell
pip install -r requirements-dev.txt   # once: adds pytest
python -m pytest -q                   # everything (the routine run, about 40 seconds)
$env:TESTS_AS_ON_LIVE = "1"; python -m pytest -q; Remove-Item Env:TESTS_AS_ON_LIVE   # as live runs: threads, a connection each time (about 80 seconds)
python -m pytest tests/test_router.py # one file
python -m pytest -k archive           # tests with "archive" in the name
```

A test that hangs does not sit there: after a minute the run stops
with "TIMEOUT: <the test> ran for more than 60 seconds" and where each
thread was (`tests/watchdog.py`; exit code 70, so nothing that waits
for a pass goes ahead). `TEST_TIMEOUT` in the environment changes the
minute.

The tests in `tests/` cover the decision logic: the word router, duration
parsing, Pomodoro phases and pause arithmetic, which reactions count and
what to apply or undo, the debounce timer, protection, archive and delete
rules and records, permissions, the registry and `help`, lab arguments, dev
mode, the scheduler (including catch-up and the nightly backup), the
clock, the day boundary, typed times and dates, the occurrence log, cards
and pills. They
never start the bot or talk to Discord or Claude, they use made-up settings
instead of `.env`, and anything that needs a database gets a temporary one,
so they are safe to run while the bot is running.

- **Write logic so it can be tested.** A decision ("may this be archived?",
  "which reactions count?") goes in a module with no Discord calls and gets
  tests; the Discord-facing code calls it. `tasks/archive/` is the pattern:
  `rules.py` decides, `store.py` remembers, `messages.py` talks to Discord.
- **Why the run is quick** (`tests/conftest.py`, 2026-10-13: 10 min 55 s
  down to 56 s, same tests): each set of migrations is run once and
  every test starts from a copy of that empty database (`make_db`); a
  test's database doesn't wait for the disk after each write; and the
  two seconds a live message waits between edits (`live.MIN_INTERVAL`)
  are nothing in a test. Running in parallel (pytest-xdist) was tried
  and is not used: one run took 30 s and the next hung.
- **New tests are plain pytest functions** with `assert`. The older
  `unittest` classes are left as they are; pytest runs both.
- **Fixtures** are in `tests/conftest.py`: `make_db` / `db` (a temporary
  database), `dev_off`, `dev_clock` (a clock that may be moved, put back
  afterwards), `owner` and `stranger`. Stand-ins for Discord
  objects are `types.SimpleNamespace`.
- **Async code** is run with `asyncio.run(...)` inside the test, or from a
  `tests.helpers.DatabaseTestCase`. There is no pytest-asyncio.
- **`docs/TESTING.md`** lists every test: 🤖 Auto rows for what pytest
  covers, 👤 Manual rows for what only shows in Discord.

## A clean hub

Off unless `HUB_TIDY=true` is in `.env` (then restart). Off, nothing is
recorded and nothing is removed by it: the hub is as it always was.

- **What you say in the hub and the reply go once it is handled**: 2
  minutes after the reply. If the reply is a card, they wait for it:
  on Save your message goes at once and the confirmation 2 minutes
  later; on Cancel, or when the card expires, both go. A message that
  needed no reply goes after 2 minutes too. One that failed keeps its
  ⚠️ until the morning.
- **One of each**: a newer checklist takes the place of the older,
  yesterday's included; a newer briefing takes the place of the older.
- **Every morning, first thing in the routine, the tidy** removes what
  the bot posted in the hub on an earlier day, and a line that reported
  a change in another channel the day before. `my schedule` shows it
  as step 1 of the morning routine.
- **Pinned or 📌 is always kept.** Pin something inside its 2 minutes
  and it stays.
- **Only messages go.** Nothing a task keeps is changed. What a message
  said is written to `data/exports/tidy-<channel>-<day>.txt` first (in
  the nightly backup); if that can't be written, nothing is removed.
- **Nothing is said about it** in the channel. #bot-log hears only
  when something could not be removed.
- **What it never touches**: a message with no lifetime recorded. That
  is everything from before you switched it on, anything a timer, a
  bug, the archive or a dev tool posts, and what you say outside the
  hub. `reset channel` is still the way to clear those.
- `dev cleanup off` stops it, like every other clean-up.

For a task: after sending, `await messages.record(message_id,
channel_id, lifetime=messages.REPLACED, slot="mytask.thing")` for a
thing there is one of at a time, or `lifetime=messages.DAY` for a line
that reports a change. With nothing said, a message in the hub lasts
the day and one elsewhere is left alone.

## The briefing

Off unless `BRIEFING_ENABLED=true` is in `.env` (then restart). Off,
nothing of it exists.

- **One card that says what today holds**: a section from each task
  that has something to say. Today that is pills: how many are taken,
  the next dose with a time, how many can be taken any time, and one
  line about yesterday.
- **In the hub, once a day**, as the first step of the morning routine:
  the briefing, then the checklist under it, at 6:00 am, without a
  notification. With it on, the 6:00 am schedule is called "Morning
  routine" and `my schedule` shows its two steps; its time and days are
  still yours to change.
- **It always shows now.** When something changes (a dose ticked off,
  a pill added), the same message is rewritten in place. Nothing new is
  posted for a change.
- **`brief me`** (or `briefing`, or "what's on today?"): in the hub it
  brings the one there up to date and says so in a line that goes;
  anywhere else you get a copy there, kept up to date too.
- **The day's progress** (off unless `DAY_PROGRESS=true` is in `.env`,
  then restart): the whole day in the title as a dot a thing to do
  and the count ("☀️ Today ●●●●●○○ 5/7"), and under the date one
  small line a task ("💊 2/3"), kept up to date with the rest. How it
  looks, and the one value that moves the dots out of the title, is
  `docs/DESIGN.md`, "Progress".
- **Questions about your day** (off unless `DAY_QUESTIONS=true` is in
  `.env`, then restart), each answered in one message from what the
  tasks keep, in words from a template and never by chat:
  - "what's left today?": the day's dots and count, then each thing
    still to do, a line each ("💊 Pill A (dose 2 of 3) `12:00 pm`").
  - "how did I go yesterday?": yesterday's dots and count from the
    record of that day, and each task's line about it ("💊 Yesterday:
    2 of 3 taken · 1 missed").
  - "how's this week going?", or "and this week?" straight after:
    Monday to today, a line a day with its dots and count.
  A question never sticks to the task that just answered: straight
  after you log a pill, "what's left today?" still gets the day's
  answer and "will it rain?" the weather's. The pills' own lists are
  unchanged ("what did I take yesterday?", "show my week").
- The next morning's briefing takes the place of the one before.
- Things are ticked off on the checklist, not here: it has no buttons.

**For a task to appear in it**, give the task a `summary`:

```python
async def summary(self, user_id, day):
    return actions.Summary(glance="2 of 6 taken", status=design.DUE,
                           lines=("**Next:** …",), hint="…", before="Yesterday: …",
                           done=2, total=6)
```

`done` and `total` are what of the day is done out of what there is
to do: the day's progress adds them up across tasks. Leave both out
for a task with nothing to count. `left` is what is still to do, a
line each in the task's own words: "what's left today?" lists them.

An action that changes a thing already there can say what it means
while that thing is only on an open card and not saved:
`unsaved=("pill_add", edit_on_card)`, the action that sets one up and
`async (request, data, on_card) -> dict | None`, which gives the data
as that action takes it, or None when it is about saved things after
all. The core then treats the message as a correction of the card.

For looking back over days, a task may also give a `tally`:

```python
async def tally(self, user_id, day):
    return (2, 3)  # done, total: from the record of that day; None with nothing
```

It must come from the task's own record of that day, never from how
things are set up now (pills counts the occurrence log, so a pill
removed since still counts for the day it was taken). "How did I go
yesterday?" and "how's this week going?" are answered from it
(`summaries.tallies`); a task that fails is left out, never guessed.

Return `None` with nothing to say that day. It only reads: no row is
made or changed to answer it (pills reads with `checklist.read`; the
day's dose rows are made as the day before ends, in `new_day`). It
asks Claude nothing, and is in the task's own words; the icon and the name come
from the task. Call `summaries.changed(self.name, user_id)` whenever it
may read differently. No briefing code changes.

## Design options on your phone

Round 3 (`round-3/`, `--round 3`) is the day's total as dots, two ways,
and five sketches of the type scale. `--only name,name` posts just the
sketches named, for adding to a round that is already posted.
A later round (`docs/mockups/options/round-2/`, with an INDEX of its
own) is posted into the same post with `python -m selftest.options
--round 2` (`--check` first reads them without posting).

`python -m selftest.options` posts the sketches of
`docs/mockups/options/` as the dev bot, over HTTP only (no bot is
started, live is not touched): a new post "🎨 Design options · <date>"
in the dev bot's forum, with a summary first, then each sketch under
its label. `--check` only reads them. A sketch is a text file in the
format `dev mock` reads; `INDEX` in that folder lists each with its
label and what is different. To add a variant, add its file and its
line there. Reply in the post with a letter for each card.

## Attention items: what the status line shows

The status line under live's name is the top item of one ranking
(`core/attention.py`; how it reads is in `docs/DESIGN.md`, "The
status line"). To have your task's things on it, override
`Task.attention(user_id, now)` and return `attention.Item`s:

```python
Item("a dose is due", TIMED, when=due, can_act=True, short=(f"due {attention.short_time(due)}",))
Item("the next dose", TIMED, when=coming, can_act=True, short=("2/5", attention.short_time(coming)))
Item("doses to take any time", USEFUL, short=("2/5",))
Item("the import failed", PROBLEM, bug="B14", link=url, short=("import failed",))
```

- Say the urgency (`PROBLEM`, `TIMED`, `USEFUL`) and the time; the
  core says the rank. A timed item whose time has come is "due", one
  later today is "next", one for another day is not ranked.
- `short` is what the status line shows: numbers and short times.
  **Never one of my things' names** (a pill's): `what` may name it,
  for the briefing later.
- Only read; ask Claude nothing. Call `attention.changed()` whenever
  your items may be different (pills does when the checklist is
  brought up to date).
- A part of the core registers instead: `attention.provide(name, icon,
  provider)` (`core/health.py`: failed jobs, a failed self-test, the
  next morning routine).

`QUIET_HOURS` (default `22:00-06:00`) is read for pings, which are not
on the model yet: nothing uses it today.

## The new look for a card of your task

With `CARDS_V2=true` a `Card` that carries a `layout` is drawn as
Components V2; without one, or with the switch off, it is its text and
rows as before. To give a card a layout, build it from the shapes of
`core/design.py` and pass it as the card's third part:
`design.standing(title, context, boxes)` for a list or a standing
message (give a box an item, `design.item(status, name, *lines)`: in
round 3 they are drawn as one box with a rule between them),
`design.decision(heading, things, question=…, row=…)` for a card that
asks, and for a page of its own `design.page(top, boxes, foot)` with a
box a topic made by `design.topic(design.card_title(…, done, total),
entries, tail=…)` (an item an `design.Entry(text, status, row)`). Write
times with `design.time` or `design.when`, never in code marks, and a
change as `field · old → new` (drawn struck through and bold). Say a
status, never a colour. A shape that changes in a later round keeps the
old one under an `_rN` name and asks `design.current()` which to draw
(`docs/DESIGN-LOG.md`). A list shown on request returns
`LiveReply(key, card.text, card)`, and its `livelists.changed` render
returns the same card. Keep the text exactly what it was: it is what
is logged, what is shown with the switch off, and what the tests read.
`cards.check(card)` refuses a layout Discord would refuse; whatever is
sent is first made to fit (`cards.fitted`, `design.fit`), so a card
too big is cut down, never left unposted.

**A new task behind a switch** (as every new feature is): add the
setting to `core/config.py`, `.env.example` and `tests/__init__.py`, and
return it from the task's `switched_on()`. Off, the task is not loaded at
all (`tasks/registry.py`): not in help, #commands or the router, no jobs,
no card. Give it a `title` when its name would not do for a person
("Personal routines" for `habits`).

**A task's card in the hub** (`core/hubcard.py`): a `render` that returns
the day's `Card`, or None with nothing for today (no card at all). Join
the morning routine with `scheduler.join_routine(hub.MORNING, …,
order=hub.CARDS_ORDER + n)` (+10 reminders, +20 personal routines, +30
gym, +40 to-dos: under the pills checklist, in that order), whose step
calls `hubcard.post`; after any change call `hubcard.changed`, which
edits it in place, posts it when there was none, and takes it away when
there is nothing left today.

**What's new** (`core/whatsnew.py`): a line for one morning's briefing,
shown once in a box of its own and gone after the next tidy.
`await whatsnew.add(line, day)` from code, or at the end of a batch
`python -m core.whatsnew add "Round 3 of the design is live" --on
2026-10-16` (it writes to the database of the `.env` it runs with: live's).

## A correction straight after Save

"Add iron at 8pm", **Save**, then "no, I meant 9pm": the change is
about what was just saved, and the bot knows that; it does not guess.
Core remembers the card whose Save was the last thing a task did in
the channel (for five minutes, and only until that task does anything
else there) and hands it to the task with the next message
(`Request.just_saved`). The task uses it for an "it" that names
nothing: pills takes the pill mentioned last on that card, or the only
one it held, and shows a change card, old → new, with no ❓. With
several pills on the saved card and none mentioned last, or once
something else has been done, it falls back to the pill changed last
and marks it ❓ as before.

For a task: read `request.just_saved` (an `actions.Saved`: task,
action, data) when a reference has nothing else to point at; check it
is your own task's card.

## My schedule

What the bot does by itself, and when, is yours to see and change.

- **`my schedule`** (or `schedule`) shows the list: each schedule, the
  days and time, where it posts and whether it notifies, its next run
  and how the last one ended. It is kept up to date in place.
- **Change one by saying so**, and a card shows `field · old → new`
  and when it would next run; only **Save** writes it:
  "move the pills checklist to 7", "checklist on weekdays only", "also
  Saturdays", "not on Sundays", "pause the checklist until Monday",
  "turn it back on", "make it silent", "post it in #inbox".
- **Add another**: "also post the pills checklist at 6 pm". It is
  called after what it runs, with the part of the day when that name
  is taken ("Evening pills checklist"). With no time said, the card
  asks.
- **Remove one**: "remove the evening checklist". It stops running;
  what it did is kept, and adding it again brings the same one back.
- A name that fits two is asked about on the card. The bot's own (the
  nightly backup, the end of the day) are listed in a small line and
  are not changed here.
- **Moved after it has run today**, it runs at the new time from
  tomorrow: once a day.
- A pill's own dose times are not here: they belong to the pill.

## When things run: the scheduler

Nothing in a task knows what time it is for. A task says **what** to
do for a kind of job (a handler) and, if it should happen by itself,
**when a fresh database should start doing it** (a default schedule);
`core/scheduler.py` does the rest.

- **A schedule is a row** (`schedules`, `core/timetable.py`): a time on
  the wall clock in `Pacific/Auckland`, the days of the week, silent or
  notify, a channel by its role, on or off, and its steps. The three
  there are today: Nightly backup (3:00 am) and End of the day
  (midnight), which are the bot's own and follow the settings, and
  Pills checklist (6:00 am), which is yours. Changing one by words
  comes with the `schedule` task; until then the rows keep the times
  they always had.
- **Local time, always.** 6:00 am is when the wall clock reads 6:00
  am, summer and winter. On the night the clocks go forward a time that
  doesn't exist runs at the moment they jump to; on the night they go
  back a time that happens twice runs once, at the first.
- **One run, one key**: the schedule, the local date and time it stands
  for, and the step. The same occurrence is never booked or run twice,
  whatever restarts in between.
- **If the bot was off**: what came due runs at the next start, late,
  once. Of several mornings missed only the latest runs. A schedule can
  say "skip when more than so late" instead (none does yet).
- **To add something that runs by itself** in a task: return its
  function from `job_handlers()` and its name in words from
  `job_labels()`, and call `scheduler.default_schedule(task, kind,
  timetable.Default("Its name", time(6, 0)))` where the task registers
  its buttons. The handler does its work and says what it decided with
  `scheduler.note(job, "…")`. It never books anything for "next time".
- **A one-off** ("in 15 minutes") is `scheduler.add_job`, with a `key`
  when booking it twice would matter.
- `dev jobs` shows what is booked and how the last run of each ended;
  `dev run <handler>` runs one now; `dev fire next` runs the next
  booked one now. Neither stands in for the scheduled run.

## The self-test

`python -m selftest` runs the dev bot against real Discord and checks
what it does, in place of the parts of a QA run a bot can do. The
report is `docs/SELFTEST.md`, written again by every full run.

- **Live keeps running.** The run is the dev bot's (see "Two bots:
  live and the dev bot"): another Discord account, with its own lock,
  log (`logs/dev-bot.log`) and channels. It refuses to start only while
  the dev bot itself is running
- **Without a dev bot** (`.env.dev` has no token of its own) the dev
  bot is live's own account, so live must be stopped first (`nssm stop
  assistant-bot`), and the run refuses to start while live holds the
  lock. For as long as it lasts the bot's status reads "🧪 Self-test
  running · back about 4:15 pm". Start live again afterwards and check
  it is back (`nssm start assistant-bot`, `python -m
  core.instance_lock`)
- **Only what a change touches.** The run is one story in six starts
  of the dev bot, cut into three stages: `day` (starts 1 to 4: a pill
  day, the cards in both looks, reminders, the restart in the middle,
  the engine and `my schedule`; about 11 minutes), `briefing` (start
  5; about 2) and `tidy` (starts 5 and 6; about 5). With nothing said,
  `python -m selftest` runs the stages touched by what has changed
  since each last passed (committed or not), and says which and why;
  with nothing touched it runs nothing. `--stages day,tidy` names
  them; `--full` is everything, about fifteen minutes. What a file
  touches is `selftest/stages.py`: docs and tests nothing, the
  briefing's and the tidy's own files their stage, another task the
  day, and the bot's shared code all three. A stage that ran whole
  with nothing failed is noted with its commit in
  `data/selftest/passed.json`
- **Memory**: the PC has 8 GB, and a run has been stopped by it
  before. The run says how much is free before it starts, and with
  under 1.9 GB free it does not start (`--anyway` goes ahead). Measured
  on 2026-10-13: a full run's own processes peak at about 180 MB (the
  runner 63, the dev bot 121) and take at most 240 MB off what is
  free; the line is there because the rest of the PC ran short at 1.6
  GB free and a run was stopped
- **Channels of its own, found by id and never made**: the three it
  writes in (an inbox, a hub, a log) and a forum for its bugs are the
  ones `.env.dev` names (`INBOX_CHANNEL_ID`, `HUB_CHANNEL_ID`,
  `BOT_LOG_CHANNEL_ID`, `BUGS_CHANNEL_ID`). Rename them or move them
  to another category as you like: only the ids count, and nothing is
  ever looked for by name. If an id is not set, or its channel has
  gone, the run stops before it starts and says which; it never makes
  a channel in its place, and it refuses a channel that is also one of
  live's (it empties its channels). The three are emptied at the start
  of every run, but for the earlier runs' summaries; the forum never.
  `python -m selftest --channels` only checks they are there;
  `--clear` empties them; `--remove` deletes them
- **An empty database**: `data/dev.db` and the dev clock are moved
  aside for the run and put back after, so your own dev data is as it
  was. The run's database is kept in `data/selftest/run-<time>/`
- **Input is simulated, output is real.** A typed message is posted by
  the bot and handed to its own `on_message` as if you had sent it; a
  press calls the handler behind the button, which edits or deletes the
  real message. Then the message is read back from Discord, and the
  doses from the database, before a step passes
- **Requests to Claude**: recorded answers unless there is a reason to
  pay. With nothing said, a run uses real requests only when prompts,
  schemas or routing changed since the last real run; `--claude` asks
  for them whatever changed, `--recorded` refuses them. Real requests
  stop at `--budget` (US$0.20 unless given; about 16 cents a full run)
  and are never sent once the month's self-test spend is over
  `SELFTEST_MONTHLY_LIMIT_NZD` (NZ$3.50). `dev cost` shows the month's spend
- **What it runs**: a day of made-up pills on the dev clock (the 6:00
  am checklist, doses on time, too soon, late and missed, a correction,
  questions on the card, reminders), the bot cut off in the middle of a
  message and the catch-up after, every card in the old look and the
  new, and each look's messages edited under the other
- **What lasts of a run**, whatever kind it was and however it ended:
  - a line in `data/selftest/history.csv`, only ever added to: date,
    commit, what ran, steps, passed, failed, the failed steps' ids,
    spend, real or recorded answers, how long. The latest 15 are a
    table at the top of `docs/SELFTEST.md`, brought up to date by
    every run
  - one message in #selftest-log ("🧪 Self-test · …"): what ran, what
    failed, the spend, and the bugs touched. The emptying before a run
    leaves these, so the channel is a list of runs
  - **Discord unavailable**: a step that fails while Discord answers
    with a server error (5xx) or a rate limit (seen in the log while it
    ran, or raised) is run once more after 10 seconds; failing so again
    it is marked 📡 Discord unavailable, not a failure: no bug, and the
    run's summary line and report say which steps. A step is written
    `async for attempt in h.step(...):` with `async with attempt:` and
    its body under it, so it can be run again in place
  - **a bug for the first step that fails in a stage**, in the #bugs
    forum as a dev bug (D number, the "dev" tag), with what was
    expected and what was seen. The steps that failed after it in that
    stage are listed inside it as probably following from it, and get
    no bug of their own. Failing again adds a note to the same bug
    (and re-opens it if it had been marked Fixed; a Won't fix stays as
    you left it); passing again marks it Fixed with a note. Only a bug
    the self-test opened itself, about that step, is ever touched.
    Which step has which bug is `data/selftest/bugs.json`. They live
    in `data/dev.db`, so `dev reset-db` forgets them, and the next
    failure opens a new one
  - the run's own folder, `data/selftest/run-<time>/`: its database,
    each start's steps (`p1.json` …), its backups and exports. The
    last 10 folders are kept, and one with a failure in it (or that
    never finished) for 30 days; older ones are removed after a run
  - a run stopped before its end (the PC low on memory, a closed
    window) is put right by the next one: the dev database it had set
    aside goes back, and it gets its line, "did not finish"
- **No account is named in the report**: it is committed, and bots are
  renamed freely. A name with its id is written as "live", "the dev
  bot", "you" or "another account", and of an id at most the last
  four digits are shown (`report.masked`)
- **What it can't see** is listed at the end of the report: how
  anything looks, the lock screen, whether the phone buzzed, your own
  reactions, and a real tap

Its code is `selftest/`: `phases.py` holds the steps, each saying
which step of `docs/QA-TONIGHT.md` or block of `docs/QA-RUN.md` it
stands for; `harness.py` what a step can do; `discordside.py` the
stand-ins for a typed message and a press, and the reading back.
`stages.py` says which stages a change touches and whether there is
room on the PC; `record.py` writes the history and the summary's
words; `bugs.py` (a process of its own on the dev database, over HTTP
only) keeps the bugs. A run that begins at start 5 makes its own pills
first (`phases.seed`, recorded answers only). `docs/SELFTEST.md` is
written by a full run only: the report of part of one goes beside
the run's database (`data/selftest/run-<time>/SELFTEST-partial.md`).
`--only p1,p2` runs some of the starts while working on the test
itself.

## Phone notifications from Claude Code (ntfy)

Claude Code tells your phone when it has finished a response and when
it is waiting for you, through [ntfy](https://ntfy.sh). Nothing to do
with the bot: it is for working on this repository.

- **The topic** is in `.env.notify` (git ignores it): the topic alone
  on one line, or `NTFY_TOPIC=<topic>`. Anyone who has it can read and
  send your notifications, so it is never printed or committed.
  Subscribe to it in the ntfy app.
- **`scripts\notify.ps1`** posts to `https://ntfy.sh/<topic>`:
  `-Kind finished` is "✅ Claude Code finished" (with the first line
  of the summary), `-Kind waiting` is "⏸️ Claude Code needs you"; both
  are priority 5, and priority 2 (quiet) between 10:00 pm and 7:00 am.
  The hours are `NTFY_QUIET_HOURS=22:00-07:00` in `.env.notify`. It says nothing and exits 0 whatever goes wrong.
- **The hooks** are in `.claude\settings.local.json` (this machine
  only, ignored by git): `Stop` for finished; `Notification` for a
  permission prompt, and `PreToolUse` on a question, for waiting.
- **To turn them off**: add `"disableAllHooks": true` to
  `.claude\settings.local.json`, or delete the `hooks` part of it (or
  the file). Renaming `.env.notify` also silences it.
- **To test by hand**: `powershell -File scripts\notify.ps1 -Kind
  finished -Text "hello"`.

## Weather

On unless `WEATHER_ENABLED=false`. Set where it is for in `.env`:
`WEATHER_LAT` and `WEATHER_LON` (decimal numbers; never committed).

- The briefing gets a section: "🌤️ **Weather** · 14° to 20° ·
  drizzle", and under it "61% rain after 1pm · wind 15 km/h N".
- It is fetched from Open-Meteo (free, no key) at **5:50 am**, before
  the morning routine, and refreshed at **8:50 am** and then every 3
  hours until 8:00 pm; the briefing is edited in place. Both are in
  `my schedule` and can be moved.
- If the 5:50 am fetch fails the section says "Weather unavailable",
  and it counts as a failed job: it is in "⚠️ Needs a look". A later
  refresh that fails keeps the forecast it had.
- No request to Claude for its words: they are a template
  (`tasks/weather/rules.py`).
- **Questions** (off unless `DAY_QUESTIONS=true` is in `.env`, then
  restart): "will it rain?", "do I need an umbrella?", "what's the
  weather this afternoon?", "how warm does it get today?". The answer
  is read from the forecast that was kept (nothing is fetched to
  answer): the highest chance of rain in the hours still to come, or
  in the part of the day you named, and roughly when; for a part of
  the day, how warm it is then if the forecast has the temperature by
  the hour (it does from the first fetch after this was built). A
  part of the day that is over says so; "tomorrow" says only today's
  forecast is kept; with no forecast it says so and gives no number.

## The interface layer: no discord.py in new code

New tasks and new core code never import discord.py
(`docs/INTERFACE.md`; `tests/test_interface.py` fails if one does).

- **A card**: `core/cards.py`, as before (`cards.send`, `edit`,
  `delete`, `register`, a `Press`).
- **A reply to a typed word**: `ctx.reply`, `ctx.confirm`.
- **Anything else done to a channel or a message**: the door,
  `core/surface.py`, by ids:
  `await surface.send(channel_id, text)`,
  `await surface.delete(channel_id, message_id)`, `fetch`, `history`,
  `pin`, `react`, `edit`. First ask whether the place is there
  (`surface.place(channel_id)` is None when it is not). What goes
  wrong is `surface.Gone` (already gone) or `surface.Failed`
  (`.status`, `.code`): never catch `discord.HTTPException`.
- **In a test**: fake the client as before
  (`monkeypatch.setattr(discord_utils, "client", …)`) or the function
  of the door you call. `tests/conftest.py` binds Discord as the
  interface, as `main.py` does at start.
- **A new verb**: add it to `core/surface.py` (the signature, in plain
  values) and to `interfaces/discord/surface.py` (Discord's side); a
  test checks that Discord answers every verb the door has.

## Alerts: Discord, your phone, and quiet hours

Everything that has to tell you something now goes through one place,
the notify service (`core/notify.py`). Pill reminders are its first
user. Two switches, both off unless set in `.env` (then restart live):

- **`NOTIFY_NTFY=true`**, with **`NTFY_BOT_TOPIC=<a topic>`**: alerts
  are also pushed to your phone through ntfy. Use a topic of the bot's
  own, not the one Claude Code's notifications use (`.env.notify`), and
  subscribe to it in the ntfy app. The topic is a secret: anyone who
  knows it can read what is pushed.
  - What is pushed is neutral: a fixed title ("Reminder") and the one
    line the hub shows first ("💊 Dose due · 12:00 pm"). Never a
    pill's name.
  - Tapping it opens the Discord message, where the buttons are.
  - **Where each kind goes is one table**, `KINDS` in `core/notify.py`:
    `DISCORD` (Discord notifies, nothing is pushed), `NTFY` (posted in
    Discord without a sound, the push tells you) or `BOTH`. Pill
    reminders are `BOTH`. Change the word there and restart.
  - With the switch off, or no topic, nothing is pushed and Discord
    notifies as it always did, whatever the table says.
  - The dev bot never pushes, so a self-test never reaches your phone
    this way.
- **`QUIET_HOURS_ENABLED=true`** (on, on live, since 2026-10-13):
  between the times of `QUIET_HOURS` (10:00 pm to 7:00 am unless set)
  an alert is still posted, but without a sound and with no push, and
  the morning's briefing lists it under "🌙 Held back overnight" in
  the same neutral words, until it is dealt with. **A pill reminder
  always gets through, with its sound**: its kind says so in the table
  (`through=True`). Nothing else does, something wrong included. Off,
  nothing is ever held.

**What needs you** (a job that did not work, reminders that can't be
sent, spend over the day's limit, memory over its limit, a bug the bot
filed itself) reaches you three ways, all from the one ranking:

- the briefing's "⚠️ Needs a look" box, with the bug's id, until it is
  dealt with;
- the status line;
- a ping: by day, one line in the hub that mentions you ("⚠️ B14 ·
  backup failed at 3:00 am"), gone once dealt with. In quiet hours
  nothing is posted; at 7:00 am the "Needs-a-look check" (in `my
  schedule`, yours to move) pings once if the box is not empty.

What is worth knowing but not urgent (an unexpected restart, a
catch-up, a self-test that did not run) is a small "🗒️" line at the
foot of the briefing, and never a ping.

To add something that needs you: hand in an attention item with
`PROBLEM` (a task through its contract, the core with
`attention.provide`); the box, the status line and the ping follow
with no other code. `ping=False` for something to show but not ping.
For something only worth knowing: `await notify.worth_knowing("…")`.
Never rely on #bot-log to tell you.

For a new kind of alert: add a line to `KINDS`, and call
`notify.post(...)` with the attention item it is about in place of
`cards.send(...)`. When the thing it was about is dealt with, say so
(`notify.dealt_with(user_id, kind, key)`): a line held back overnight
then leaves the briefing. Never read the quiet hours or the ntfy settings in a
task.

The briefing takes its order from the same ranking as the status line:
"⚠️ Needs a look" on top when something is wrong (a job that did not
work, with its bug), then what was held back overnight, then a section
a task, the task with the most urgent thing first.

## Direct messages to the bot

Off unless `DMS_ENABLED=true` is in `.env` (then restart live). Off, a
direct message is not read for plain words, as always.

- **Only you**, and only live: a direct message from anyone else is
  ignored, and the dev bot never reads one.
- **It is read as #inbox**: the same plain words ("took zinc", "add
  iron at 8"), the same typed words that work in #inbox, the same
  cards with their buttons. The checklist and the briefing stay in the
  hub: a direct message gets the line that points there.
- **Replies are silent**: nothing buzzes for an answer you asked for.
- **No name of yours in a first line**: where a reply's first line
  would name a pill (or a timer), the task's own line goes first ("💊
  Pills") and the reply follows under it, so the list of conversations
  and a lock screen never show a pill's name. A card's heading ("💊
  Pills · new") names nothing and is left as it is.
- Not there: messages sent while the bot was off are not read back
  from a direct message, and after a restart a card left open in one
  may not be rewritten in place (the bot has to see the channel again:
  write to it once).

## The nightly self-test

Off unless `NIGHTLY_SELFTEST=true` is in `.env` (then restart live).
It needs the dev bot (a token of its own in `.env.dev`).

- **At 3:30 am** (half an hour after the 3:00 am backup) live starts a self-test as a process of its own. The
  dev bot runs it; live carries on and is never stopped. `my schedule`
  shows it as "Nightly self-test" and moves it like any schedule
  ("move the nightly self-test to 4am", "pause the nightly self-test").
- **What is run**: the stages touched by what changed since each last
  passed, and everything on a Sunday. On a night nothing changed,
  nothing is run.
- **A night with no new commits runs nothing**: when every stage last
  passed on the commit that is checked out, a weeknight leaves its
  line in the log channel and starts no bot. (The Sunday full run
  still happens.)
- **Recorded answers are the rule**: they cost nothing. A run sends
  real requests only on the Sunday full run, or when prompts, schemas
  or routing changed since the last run with real requests
  (`core/router.py`, `routing.py`, `extraction.py`, `llm.py`,
  `actions.py`, `conversation.py`, and a task's `plain.py` or
  `__init__.py`). The run's first lines say which, and why.
- **A month's cap**: `SELFTEST_MONTHLY_LIMIT_NZD` (NZ$3.50 unless set). Once
  the month's runs have spent it, every run uses recorded answers
  only, live's status line says "🧪 self-test spend · NZ$3.51" when it has nothing else to show (not a problem: nothing is to be done), and
  `dev cost` shows the month's figure. It starts again with the month.
- **What it leaves**: the run's summary in the self-test's log channel
  (a line there too on a night with nothing to run), a line in
  `data/selftest/history.csv` ("nightly, …"), and a bug for the first
  failing step of a stage, as after any run.
- **Your phone** is pinged (ntfy, priority 5, the topic in
  `.env.notify`) only if a step failed or the run did not finish. A
  night that passed is silent there.
- **A run that could not start** (no dev bot, under 1.9 GB of memory
  free, a channel in `.env.dev` gone) is said in #bot-log, and the
  schedule's last run reads as it ended. What the run printed is in
  `logs/selftest-nightly.log`.
- **If the bot was off at 3:30 am** the night is skipped once it is
  three hours late. Restarting live while a nightly run is going stops
  that run; the next one records it as not finished.

## Service commands (Terminal as Admin)

```powershell
nssm status assistant-bot
nssm start assistant-bot
nssm stop assistant-bot
nssm restart assistant-bot
nssm edit assistant-bot
```

Live runs from its own folder (`C:\Users\temp\projects\assistant-bot-live`,
on one pushed commit; `docs/LIVE-FOLDER.md`). `nssm restart` restarts it
on the commit it is on. To ship code, move it to a newer pushed commit,
which also restarts it; to undo, go back to the one before:

```powershell
.\scripts\update-live.ps1 -Ref <commit>
.\scripts\update-live.ps1 -Back
```

Live runs from its own folder (`C:\Users\temp\projects\assistant-bot-live`,
on one pushed commit; `docs/LIVE-FOLDER.md`). `nssm restart` restarts it
on the commit it is on. To ship code, move it to a newer pushed commit,
which also restarts it; to undo, go back to the one before:

```powershell
.\scripts\update-live.ps1 -Ref <commit>
.\scripts\update-live.ps1 -Back
```

## Dependencies

After installing a package, update the list:
```powershell
pip freeze > requirements.txt
```

## Troubleshooting

- **`ModuleNotFoundError`:** wrong Python. Check the prompt shows `(.venv)`,
  or run `python -c "import sys; print(sys.executable)"`
- **Scripts disabled when activating:**
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- **Double replies:** the service and a test copy are both running (only
  possible if one of them is older code from before the instance lock)
- **"Another copy of the bot is already running":** stop the other one first
  (`Ctrl + C` in its terminal, or `nssm stop assistant-bot`)
- **Errors 10062 "Unknown interaction" or 40060 "already been
  acknowledged":** two copies answered the same button or command, or the
  bot took over 3 seconds to answer. They are logged as warnings
- **Service won't start:**
  `Get-Content logs\service-err.log -Tail 30`
- **Stuck in a Git viewer (`less`):** press `q`; `Esc` cancels prompts