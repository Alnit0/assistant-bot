# Interface audit: how much of the bot is Discord

Written 2026-10-13 as an audit and a proposal. Since then (2026-10-14)
the rule below is in force and stages 1 and 2 of section 4 are done.
Sections 1 and 2 are the audit **as it was found**: 2.2 and 2.3 are now
history, and section 0 says what is true today.

## 0. The rule, and where things stand

**The rule.** New tasks and new core code never import discord.py.
They produce plain data (a `Card`, text; a `Request` or a `Press` in)
and go through the interface layer:

- `core/cards.py` for a card,
- `Context` for a reply to a typed word,
- **the door, `core/surface.py`**, for everything else: `send`, `edit`,
  `delete`, `delete_many`, `fetch`, `history`, `pin`, `react`,
  `unreact`, `place`, `link`, `status`, `name`, `rename`, `who`.

The core never holds the client, never calls a method on one of the
interface's objects and never catches one of its errors: what goes
wrong comes back as `surface.Gone` (it is not there any more) or
`surface.Failed` (with the interface's status and code). Everything
that is Discord's lives in `interfaces/discord/`, which is bound when
the bot starts (`interfaces.discord.bind()`) and imported by neither
the core nor a task.

**Enforced** by `tests/test_interface.py` (part of every test run) and
by `task-check`: the files that still import discord.py are a list in
that test, and the list only gets shorter.

**Decided (2026-10-14).**

- **Timers are frozen**: they keep working, are never ported (stage 9
  is struck out), and are scrapped if the bot ever leaves Discord.
- **A read-only web page comes later**, reachable only over Tailscale
  (section 5.2, question 6: "a better view"). In the backlog.

**Done (2026-10-14): stages 1 and 2.**

- `core/cards.py` is the plain half only: the records, the checks, a
  `Press`, and what every press must do. How a card is drawn and how a
  press is answered moved to `interfaces/discord/render.py`.
- `core/surface.py` is the door; `interfaces/discord/surface.py` is
  Discord behind it.
- Eleven core files no longer import discord.py or hold the client:
  `cards`, `tidy`, `pins`, `mirror`, `channels`, `clearing`,
  `messages`, `restart`, `missed`, `identity`, `account`. **Core went
  from 16 files importing discord.py to 5.**
- Nothing you would see changed: the same calls reach Discord, in the
  same order.

**What stage 2 left as it was, on purpose.** `fetch` and `history`
hand back the interface's own message objects, read by attribute only
(`core/protection.py`, the transcript of `core/messages.py`,
`core/missed.py`). They become plain records with the typed-word
contract (stages 3 and 4), which is what reads them most.

**Still importing discord.py**, in the order they would go:

| Where | Stage |
|---|---|
| `core/context.py`, `core/discord_utils.py`, `core/interactions.py`, one line of `core/conversation.py`, `main.py`'s events | 3 |
| `tasks/base.py`, `tasks/registry.py` (the typed-word and reaction contract) | 4 |
| `core/confirmations.py` (the old confirm buttons) | 6 |
| `tasks/archive/` | 7 |
| `tasks/bugs/posts.py`, `tasks/builtin/views.py`, `tasks/dev/` | 8 |
| `tasks/lab/`, `tasks/timers/` | never |

The question: how much do `tasks/` and `core/` depend on Discord
directly (discord.py types, message objects, components, channels),
where is the clean line, what would it cost to get there, and what
would a second interface (a web app) then need.

Counted by searching the code for `import discord`, `discord.<name>`,
the shared client (`discord_utils.client`), fetches (`get_channel`,
`fetch_message`, `get_partial_message`), message attributes
(`.author`, `.jump_url`, `.reference`) and Discord's own markup in
strings (`<#…>`, `<t:…>`, `-# `). Numbers are occurrences, to show
weight, not exact to the line.

## 1. The short answer

- **The new half is already close.** Everything built on the router
  (pills, briefing, schedule, the confirm cards, live lists, the
  scheduler, attention, notify) speaks plain data: a `Request` in, a
  `Card` or text out, ids as numbers. **Pills, 5,000 lines, imports
  discord.py nowhere.** One file, `core/cards.py`, turns a `Card` into
  Discord.
- **The old half is Discord through and through.** `archive`,
  `timers`, `lab`, `dev`, `bugs/posts.py` and `builtin/views.py` build
  `discord.ui` views themselves and take `discord.Message` and
  `discord.Interaction` in their handlers. This is the list CLAUDE.md
  already allows "until the gateway layer exists".
- **The core has no single door.** 16 of its 63 files import
  discord.py. Most of them only catch `discord.HTTPException` around a
  call on the shared client: shallow, but it is a door in every room.
- **Three things are Discord without importing it**: the text itself
  (Discord's markdown and `<#channel>` mentions written by tasks),
  where a message is (`channel_id`, `message_id` in 19 places of the
  core's tables), and the typed-word and reaction contract in
  `tasks/base.py` (handlers are given `discord.Message` and
  `discord.RawReactionActionEvent`).

So: a boundary is realistic, and about a third of it exists. The
honest cost is in the old tasks, not in the core.

## 2. Every place, by how deep it goes

### 2.1 Clean: no discord.py, plain data only

| Where | Lines | Note |
|---|---|---|
| `tasks/pills/` | 5,063 | One `<#channel>` mention in a sentence (`plain.py`), and Discord's markdown in its words |
| `tasks/briefing/`, `tasks/schedule/`, `tasks/channel/`, `tasks/keep/` | 1,667 | `keep` writes `<#channel>` in four lines and is handed a reaction payload (see 2.4) |
| `tasks/bugs/` but `posts.py` | about 1,400 | `plain.py` and `__init__.py` ask `posts.py` for a message; `rules.py` reads `.author` and `.jump_url` off what it is given |
| `core/actions.py`, `conversation.py` (one `discord.Embed` for a log card), `router.py`, `routing.py`, `extraction.py`, `confirm.py`, `repeats.py`, `names.py`, `llm.py` | | The whole way in for plain words |
| `core/scheduler.py`, `timetable.py`, `clock.py`, `day.py`, `occurrences.py`, `attention.py`, `health.py`, `notify.py`, `summaries.py`, `livelists.py`, `live.py`, `lifecycle.py`, `outgoing.py`, `design.py`, `dms.py` | | Time, ranking, alerts, how a card looks: all records and text |

`core/design.py` deserves a line of its own: how a card looks is
already described as plain records (boxes, statuses, separators), and
only `cards.layout_view` turns those into Discord components.

### 2.2 The adapter that exists: plain data in, Discord out

| File | discord.py uses | What it is |
|---|---|---|
| `core/cards.py` | 40 | **The model for the boundary.** `Card`, `Button`, `Select`, `Field`, `Form` and `Press` are plain records; `view`, `layout_view`, `_CardButton`, `_CardSelect`, `_Modal`, `send`, `edit`, `delete`, `link` are the Discord side. Both halves live in one file |
| `core/context.py` | 20 | What a typed word's handler gets. `reply`, `confirm`, `note`, `log` are interface-neutral in meaning; but it is built from a `discord.Message`, `reply` takes a `discord.ui.View`, and `channel`, `author`, `fetch_reply_target`, `fetch_message`, `recent_messages` hand Discord objects straight to the task |
| `core/discord_utils.py` | 17 | The shared client, message splitting to Discord's 2,000 characters, the #bot-log embeds, interaction replies |
| `core/interactions.py` | 8 | Slash commands and context menus: begin, finish, fail |
| `core/channels.py` | 8 | Which channels hold messages, by Discord's channel types |
| `core/account.py`, `core/identity.py` | 6 | Which account a token is; nickname and status line |
| `main.py` | 24 | The events: `on_message`, raw reactions, interactions |

### 2.3 Core files that reach through the door for one thing

Each imports discord.py for `HTTPException` or `NotFound` around a
call on the shared client. None builds a view.

| File | Uses | What it does to Discord |
|---|---|---|
| `core/confirmations.py` | 24 | The **old** confirm buttons (a `discord.ui.View` with three buttons), still used by reactions and archive. The new cards do not use it |
| `core/missed.py` | 4 (+6 fetches) | Reads channel history on start for what was said while off |
| `core/messages.py` | 4 (+3) | Deletes by lifetime, saves a copy first |
| `core/clearing.py` | 5 (+4) | `reset channel`: bulk delete |
| `core/tidy.py` | 1 (+5) | Deletes a line later |
| `core/restart.py` | 2 (+3) | Rewrites a card left open |
| `core/pins.py`, `core/mirror.py` | 2 (+6) | Pin, unpin; mirror a message |

### 2.4 The contract that hands Discord objects to tasks

`tasks/base.py` (8 uses) and `tasks/registry.py` (14 uses, 9 fetches):

- `Keyword.handler(ctx)`: a `Context`. Neutral in spirit, Discord in
  its escape hatches (2.2).
- `ReplyAction.handler(ctx, message: discord.Message)` and its
  `validate(message)`.
- `Reaction.handler(payload: discord.RawReactionActionEvent, user)`,
  `undo`, `validate(message)`.
- `Task.setup(client)` and `Task.startup(client)`: every task is
  handed the Discord client.
- `Task.on_message`, `on_raw_reaction`: "the same arguments as
  discord.py's event".

By contrast the plain-words contract (`Action.run(request, data,
guessed)`) is clean: `Request` says so in its own docstring ("Not a
discord object").

### 2.5 Tasks that are Discord code

| Task | Lines | discord.py uses | What ties it |
|---|---|---|---|
| `tasks/lab/` | 2,866 | about 160 | Built to try Discord's features. Not worth porting: it is the Discord interface's own test bench |
| `tasks/timers/` | 3,102 | 45 (+12 fetches) | Its own views and dynamic buttons (`sessions.py`, `timers.py`), a board edited through channel objects (`board.py`), mentions |
| `tasks/archive/` | 759 | 48 (+8) | Moves a message: reads `discord.Message` in full (author, attachments, embeds), re-posts through a webhook, a Restore button of its own |
| `tasks/bugs/posts.py` | 294 | 38 (+13) | A forum post a bug, tags, three buttons on a view of its own |
| `tasks/dev/` | 1,328 | 40 | The pinned panel (own view), mock-ups (raw Components V2), tools that read messages |
| `tasks/builtin/views.py` | 79 | 12 | Buttons on the start card |

### 2.6 Discord that hides in plain text and plain numbers

- **Markdown.** Every task writes Discord's dialect: `**bold**`,
  `` `code` ``, `## heading`, and `-# small` (through `design.small`,
  used by nine files). A web page can render the first three; `-# ` is
  Discord's alone.
- **Mentions and timestamps in strings.** `<#channel>` in eleven
  files (pills and keep among the clean ones), `<t:…>` in nine (all in
  the old tasks), `<@user>` in two.
- **Limits.** 2,000 characters a message, 80 a button label, 5 rows
  of 5 buttons, 128 for a status line: checked in `cards.check`,
  `discord_utils.split_message`, `attention.MAX_LINE`.
- **Where a message is.** `channel_id` and `message_id` are in 19
  column definitions of the core's migrations and in most task tables
  (a prompt, a live list, a confirm card, a held alert). They are
  numbers, but they mean "a Discord message".
- **How things are said.** "Edit in place", "silent", "pinned",
  "reaction as status", "delete after" are the standard's own words
  (`docs/CONVERSATION.md`, the lifecycle classes). They are ideas
  another interface can honour, but they were shaped by Discord.
- **Channels as places with meaning.** #inbox, the hub, #bot-log,
  #bugs as a forum, #commands. `config.CHANNELS` and `registry.works_in`
  decide what works where.

## 3. The boundary proposed

One sentence: **tasks and core say what to show and what happened, as
plain data, to an interface they know only by a small set of verbs;
one package per interface turns that into its own world and turns its
own events back into plain data.**

### 3.1 What crosses, outward

Mostly what exists, named once:

- `Card` (text, rows of `Button` / `Select`, a layout of
  `design` records, a `Form`): as now.
- A **place**: not a channel id, a small record `Place(surface,
  conversation)` where the surface is "inbox", "hub", "log", "bugs"
  and the conversation is the interface's own key. For Discord it
  holds the channel id. Tasks already ask for "the hub"
  (`hub.channel_id()`): they would get a `Place`.
- A **message reference**: `Ref(interface, key)` in place of
  `(channel_id, message_id)`. In the database: the two existing
  columns stay and mean "the Discord key"; a text `ref` column is
  added only when a second interface exists.
- The verbs, one module (`core/surface.py`, say), which is what
  `cards.send / edit / delete / link`, `Context.reply / confirm /
  note`, `pins.set_pinned`, `identity` and `discord_utils.log_*`
  already are when put together:
  `send(place, card, silent=)`, `edit(ref, card)`, `delete(ref)`,
  `link(ref)`, `react(ref, emoji)`, `pin(ref, bool)`,
  `history(place, since)`, `log(title, body)`, `status(line)`.
  An interface may answer "not here" to any of them (a web page has no
  reactions): the caller is told, and the standard says what replaces
  it.
- **Text in one dialect.** Keep writing markdown, but only through
  helpers for what is not common markdown: `design.small(text)`
  exists; add `design.place(surface)` for `<#…>` and
  `design.moment(when)` for `<t:…>`. The Discord side renders them as
  now; another renders them its way. No string then holds `<#` or
  `-# ` by hand.

### 3.2 What crosses, inward

- `Request` (exists): who, where (a `Place`), the text, what it
  replies to (a `Ref`), attachments as plain records (exists:
  `request.attachments`).
- `Press` (exists): who pressed what on which card, with `update`,
  `remove`, `open_form` as verbs. It wraps a `discord.Interaction`
  today; its public face is already neutral.
- A **reaction event** as a record: `Reacted(ref, emoji, user,
  added)`, in place of `discord.RawReactionActionEvent`.
- A **message** as a record for the few tasks that act on messages
  (archive, keep, bugs): `Message(ref, author, text, attachments,
  pinned, created, link)`. Read-only; to change one, a verb.

### 3.3 Where the code would sit

```
core/            no discord.py at all. Cards, requests, the verbs' signatures
interfaces/
  discord/       everything that imports discord.py:
                 gateway.py   (main.py's events -> Request, Press, Reacted)
                 render.py    (Card and layout -> views; from core/cards.py)
                 surface.py   (the verbs, on the client)
                 context.py   (a typed word's Context, on a discord.Message)
                 identity.py, account.py, channels.py, interactions.py
                 confirmations.py (the old buttons, until they are gone)
tasks/           no discord.py, except tasks marked as Discord's own
tasks/lab/       stays Discord's own, loaded only by the Discord interface
```

The rule that would then be testable in one line: **`grep -r "import
discord" core tasks` finds only tasks on a short list**, where today
it finds 40 files. The test for it is ten lines and belongs with the
display-name test.

### 3.4 What stays Discord's, on purpose

- `lab`: it exists to try Discord.
- `dev`'s mock-ups (raw Components V2) and its pinned panel.
- The bugs forum (`bugs/posts.py`): "a post a bug" is an idea another
  interface can have, but tags and forum threads are Discord's. Behind
  three verbs (`open_post`, `note`, `close`) it becomes replaceable.
- Slash commands and context menus: a fallback there only.

## 4. The work to get there

In stages, each leaving the bot working and each provable by the
offline tests and one self-test. Sizes are in **sittings** (one item of
an unattended batch, as tonight's were: a few hours of work, its
tests, docs and a self-test). They are estimates from reading, not
from trying.

| # | Stage | What moves | Size | Risk |
|---|---|---|---|---|
| 1 ✅ | **Split `core/cards.py`** into the records (stay) and the renderer and senders (to `interfaces/discord/`). Add the verbs module; `cards.send` and friends become thin calls to it | 1 file into 3; about 30 call sites unchanged in meaning | 1 | Low: the tests already fake `cards.send / edit / delete` |
| 2 ✅ | **One door for the core.** `missed`, `messages`, `clearing`, `tidy`, `restart`, `pins`, `mirror`, `identity`, `channels`, `account` call the verbs, not the client; errors come back as the bot's own (`surface.Gone`, `surface.Failed`), not `discord.HTTPException` | 12 core files, about 60 lines each touched | 2 | Medium: restart and missed-message recovery are subtle; the self-test covers them |
| 3 | **`Context` without Discord objects.** `reply(view=)` goes (cards only); `channel`, `author`, `fetch_*`, `recent_messages` return the `Message` record. `main.py`'s events move to the gateway | `core/context.py`, `main.py`, about 20 callers | 2 | Medium: every typed word passes through it |
| 4 | **The typed-word and reaction contract** (`tasks/base.py`, `registry.py`): handlers get `Message` and `Reacted` records; `setup` and `startup` lose the client | 2 files and every task's `Reaction` / `ReplyAction` (archive, keep, bugs, timers, lab) | 2 | Medium |
| 5 | **Text helpers**: `design.place`, `design.moment`; replace `<#…>` and `<t:…>` by hand in the tasks that are staying | about 20 lines in 8 files | 0.5 | Low |
| 6 | **Old confirm buttons** (`core/confirmations.py`) onto cards | 1 file, its 6 users | 1 | Low: the new card path is the tested one |
| 7 | **Archive** onto records and verbs (it needs `repost(message, place)` and attachments) | 759 lines | 2 | Medium: webhooks, files, Restore after a restart |
| 8 | **Bugs' forum** behind three verbs; `builtin/views.py` and the dev panel onto cards | about 650 lines | 2 | Low to medium |
| ~~9~~ | **Timers: not to be done** (frozen 2026-10-14). As it was estimated: only if they are kept. Their views onto cards, the board onto the verbs | 3,102 lines | 3 to 4 | High for its value: frozen, perhaps to be scrapped |
| 10 | The grep test, ARCHITECTURE, CLAUDE.md's rule rewritten ("only `interfaces/discord/` and the listed tasks import discord.py") | | 0.5 | |

**Totals** (as estimated before any of it was done; stages 1, 2 and
10's test are done, and timers are out). Stages 1 to 6 and 10, which give a core and a contract
with no discord.py and leave the old tasks marked as Discord's own:
**about 9 sittings**. With archive and bugs (7, 8): **about 13**. With
timers: **16 to 17**. Lab is never ported.

**The order matters less than the first two.** Stages 1 and 2 are
cheap, change nothing you would see, and make everything after them
smaller. If only two sittings are ever spent on this, those are the
two.

**What it would not change**: a single word the bot says, a card's
look, the database (no migration until a second interface exists), the
standard.

**What I would not do**: an abstract "interface" class hierarchy
written before a second interface exists. The verbs as plain functions
in one module, with Discord as the only thing behind them, is enough
to keep the line; the second interface is what shows which verbs were
wrongly shaped.

## 5. What a web app would then need

Assuming stages 1 to 6: the core runs with no Discord. A web
interface is then a second package beside `interfaces/discord/`, in
the same process (the scheduler, the database and the lock are one).

### 5.1 To build

| Piece | What | Size |
|---|---|---|
| A server in the bot's process | A small async HTTP server on the event loop (aiohttp is already installed with discord.py), bound to the home network or behind a tunnel | 1 |
| Signing in | One user today, but `is_allowed(user, action)` wants a `User`: a login that maps to the owner's row. A passkey or a long random link is enough for one person; anything on the internet needs more care than the rest put together | 1 to 2 |
| Rendering | `Card` text (markdown) and `design` layout records to HTML: boxes, status colours, separators, buttons, selects, forms. The records are few (`item`, `standing`, `decision`, `notifying`) | 2 |
| Events in | A typed line -> `Request` -> `conversation.handle`; a button -> `Press` -> `cards.handle`. Both exist and take plain data | 1 |
| Live updates | "Edit in place" becomes a push to the open page (server-sent events or a websocket), keyed by `Ref`. `live.schedule` already batches edits | 1 to 2 |
| Its verbs | `send`, `edit`, `delete`, `link`, `history`, `log`, `status`; "not here" for `react` and `pin` unless drawn | 1 |
| Places | What "inbox", "hub", "log" and "bugs" are on a page: tabs, most likely. The hub (today's checklist, the briefing) is the natural front page | 1 |
| Tests | The same offline tests run against a fake surface already; a second self-test stage against the web interface | 1 to 2 |

**About 9 to 12 sittings** for a web app that does what #inbox and
the hub do: say something, get a card, press Save, see the checklist
and the briefing live.

### 5.2 Questions it raises that code does not answer

1. **Does the standard hold?** "Reactions are the status (👀, ⚠️)",
   "a remark gets no reply", "housekeeping leaves no trace" assume a
   chat. On a page 👀 is a spinner and "no trace" is free. The
   standard would need a short section on what each rule means
   outside a chat, before any of it is built.
2. **One conversation or two?** If you say something on the web, does
   it appear in #inbox? If a reminder is acknowledged on the web, the
   Discord message must go (`Alert`: deleted once acknowledged). A
   thing shown in two places needs both refs: this is the one real
   change to the database (`ref` rows, one to many), and the reason
   not to guess its shape now.
3. **Notifications.** A web page does not buzz. The notify service
   already has the answer (ntfy, with a link): the link would open the
   web page, not Discord, by kind, in its one table.
4. **Where it is reachable.** The PC is at home. On the home network
   only, it is a day's work; from the phone outside, it is a tunnel or
   a VPN, and signing in becomes the main risk of the whole bot (it
   holds health data).
5. **What Discord gives for free** and a web app must have built:
   history and search, attachments and their storage, the phone app
   and its push, presence, pins, offline delivery. Much of the bot's
   housekeeping exists because Discord keeps everything; a page shows
   only what it is told to.
6. **Is the goal a second interface, or a better view?** A read-only
   page (today's checklist, the week, the run log, costs, open bugs)
   needs none of sections 3 and 4: it reads the database and the
   `design` records, and is about 2 to 3 sittings. If that is most of
   what a web app is wanted for, it is the cheap first step and does
   not commit to anything.

## 6. Recommendation

1. Do stages 1 and 2 when there is a quiet sitting: they pay for
   themselves in tests (no more faking Discord errors in core tests)
   whether or not a web app ever exists.
2. Decide timers first (keep or scrap): it is a quarter of the port.
   (Decided 2026-10-14: frozen, never ported.)
3. Before any web work, answer 5.2's question 6. If "a better view",
   build the read-only page and stop there. (Decided 2026-10-14: a
   read-only page, later, over Tailscale only.)
4. Do not start a second interface before the standard has its
   section on what its rules mean outside a chat.
