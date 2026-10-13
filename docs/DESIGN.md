# Design

How a card looks. One style for every task, so it belongs to the core:
a task supplies what a card says, never how it is laid out. It is
written for Discord's Components V2 (text, boxes, separators and
buttons in one message). `docs/CONVERSATION.md` says what a card must
say and when; this file says how that is drawn, and where the two
touch, the standard wins.

**Status (2026-10-13): waiting for the check on the phone (block 39 of
`docs/QA-RUN.md`).** The colours below are the ones chosen so far and
are not final until Alex has looked at them on the phone; the lock
screen waits for the same check. Six cards are built this way, behind
`CARDS_V2` (off unless set in `.env`; off, every card looks as it
always has): today's pills checklist, the reminder, the confirm card,
the card that asks a question, the card that asks first because
something is risky, and the channel reset card. The list of my
schedule and the briefing (behind `BRIEFING_ENABLED`) are drawn this
way too. Everything else is still a plain message.

**Every colour and spacing value is in one file, `core/design.py`**
(its first block): after the phone check, a change is an edit there and
nowhere else. `dev mock` draws its sketches with the same values.

## The hub

The hub is a clean place to check in on what is relevant now
(`docs/CONVERSATION.md`, principle 8). It holds only live messages,
edited in place where possible: the briefing, today's checklist and any
reminder that is due. Anything finished, answered or out of date
leaves, and nothing from a past day stays, except as a summary in the
briefing. So in the hub:

- Every message is a standing message or one that notifies; a card
  that asks for a decision goes when it is answered
- A change is an edit of the message that is there, not a new one
  under it
- One of each: one briefing, one checklist for today, one prompt a
  dose that is due
- Yesterday is one small line in the briefing, never a message left
  behind
- The briefing is above today's checklist and is edited in place
  whenever a section changes, so it always shows now; the checklist is
  the newest message
- What I say there and the reply go once handled: 2 minutes after the
  reply, or when the card is saved, cancelled or expires. Pinned stays

The briefing is behind `BRIEFING_ENABLED` and the clean-up behind
`HUB_TIDY`, both off until turned on; with the clean-up off,
yesterday's checklist stays where it was.

## The bots' names

A bot is called what I named it: `BOT_NAME` in its settings file,
taken on every start. Its nickname changes only for a real state, and
then always as **Name · state**:

| Bot | Nickname | Where its states show |
|---|---|---|
| Live | its plain name, always | the status line ("🟢 Live · up 7h · next: …", "⚠️ … failed · see #bot-log") |
| The dev bot | its plain name; **Name · testing** while a self-test runs, plain again when it ends | the nickname, and the status line ("🧪 DEV database · clock +13h") |

Nothing else renames a bot: no marker for the dev database (the old
"· DEV" is gone), no state for live. With no `BOT_NAME` the nickname
is left as it is.

## The pieces

| Piece | Written | Used for |
|---|---|---|
| Heading | `# ` | The first line of a standing message (today's checklist, a workout): one a message |
| Card heading | `## ` | The first line of a card that asks for a decision, inside its box |
| Small text | `-# ` | Detail that is read second: the date, a note, "last time", a reason, a hint |
| Bold | `**…**` | The name of the thing a box is about, and the one question a card asks |
| Code | `` `8:00 pm` `` | A time or a value that is being set or shown as due |
| Box | a Container | One item, with an accent colour for its status |
| Separator | `---` | Between sections of a message, and between things inside one card's box |
| Buttons | a row | What can be done to the thing in the box, inside that box |

## The first line

- **A standing message** (shown every day, edited in place): `# icon
  Title · progress`, then one small line of context under it.
  `# 💊 Today · 2 of 5 taken` / `-# Sunday 12 October`.
- **A card that asks for a decision**: `## icon Task · kind`, the kind
  being new, change or remove (the standard's three), inside the box.
  `## 💊 Pills · change`. A small line under it may say what it is
  about (`-# #inbox`, `-# 2 pills`).
- **A message that notifies**: one plain line, outside any box, that is
  safe on a lock screen: what is due and when, never whose or what.
  `💊 Routine due · 11:12 am`. It is posted as that line alone; the box
  with the details is added by an edit, which notifies nobody.

## A box

One box an item (a pill, an exercise). In it, top to bottom:

1. **Name** · its state at a glance (`●○○`, one mark a dose or set)
2. small text: the plan or the note
3. what has happened (`✅ 9:00 am`)
4. what is next (`**Next:** dose 2 · 12:00 pm`)
5. small text: a warning or a hint
6. its buttons, in one row

Leave out any line there is nothing to say for. A box with nothing to
do has no buttons.

## Accent colours

A box's colour is its status, the same in every task. Not final:
waiting for the check on the phone (block 39).

| Status | Accent | Means |
|---|---|---|
| Due | amber | Something to do now or next, with a time |
| Any time, still to take | blue | To do today, with no time it is due at |
| Taken / done | green | Finished |
| Missed, and nothing left to take today | red | Its time passed and nothing was done |
| Paused, to come, skipped, snoozed | grey | Nothing to do now |
| A decision (a confirm card, a question) | blurple | Waiting for me to choose |
| A card that asks first because something is risky (a late log, too soon) | amber | Waiting for me to choose, and the ⚠️ line says why |
| Destructive (a reset, delete for good) | red | Can't be undone |

A warning is a ⚠️ line inside a box and never a colour of its own: the
box keeps the colour of its status.

A box with several doses (or sets) takes the colour of what is still to
do. A missed dose is a ❌ line in the box; the box is red only when a
dose was missed and nothing is left to take today. While a dose is
still to come it is amber (or blue, for any time).

Colour is never the only sign: every status also has its mark (✅ ❌ ⏸️
⏭️ ⚠️) and its words, since colours differ between themes and some
can't be told apart.

## Spacing and separators

- A blank line between boxes; nothing else between them
- A separator between sections of a message (today's items, then
  Paused; the exercises, then Finish)
- Inside a card's box, a separator between the heading and the things,
  between one thing and the next, and above the warning and the buttons
- Small text under the last box for a hint about the whole message
  ("❓ marks a guess · reply to this card to change it")

## Buttons

The rule of `docs/CONVERSATION.md` (section 4), unchanged, and checked
by code (`core/cards.py`: `check`, `colour_problem`):

- **green**: the positive main action (Save, Taken, Set done)
- **red**: destructive (Remove, Delete for good, Delete all)
- **blurple**: every other choice, the answers to a question included
- **grey**: Cancel only, written ↩️

Buttons sit inside the box of the thing they act on, the main action
first and Cancel last. Only what applies is offered.

## Limits

One message takes 40 components (every text, box, separator, row and
button counts) and 4,000 characters; a row takes 5 buttons. So:

- A box with a row of three buttons is 6 components; without buttons 2
- Buttons go only where something can be done now
- A message that would not fit drops buttons first (only the next thing
  due keeps them), then folds finished things into one box of lines.
  It never drops a thing without saying how many more there are
- A question offers at most four answers, in one row with Cancel

`dev mock` refuses a sketch that breaks a limit, with the reason.

## In code

- `core/design.py`: the values, the records a layout is made of
  (`Text`, `Box`, `Separator`, `Row`) and the shapes of this file
  (`item` for a box, `standing` for a standing message, `decision` for
  a card that asks, `notifying` for a message that notifies). Pure
- `core/cards.py`: a `Card` may carry a `layout` beside its text and
  rows. It is drawn only when `CARDS_V2` is on (`cards.designed`); the
  text is always there, for the log and for off
- A task says what a card holds and which status a box has, never a
  colour: `tasks/pills/sheet.py` is the checklist
- A message that is Components V2 can never go back to plain text:
  rewriting one with a plain card puts the same words and buttons in
  as a layout (`cards._drawn`), so switching `CARDS_V2` off again is
  safe

## The sketches

| Sketch | Shows |
|---|---|
| `checklist-v2` | Today's checklist: due, any time, taken, missed, skipped by the bot, paused |
| `reminder-v1`, `reminder-v1-first` | A reminder as it reads, and as it is first posted (the line the phone shows) |
| `reminder-renudge-v2` | A reminder asked again, and the same one while snoozed |
| `reminder-missed-v2` | A pill on the checklist with a missed dose |
| `too-soon-v2` | The amber card: it asks first because something is risky |
| `confirm-card-v2` | A change to two things, with ❓ guesses, old → new and a part not included |
| `question-card-v1` | A card that asks, with an answer a button and no Save |
| `reset-card-v2` | A destructive card |
| `gym-workout-v1` | A workout: done, current, to come |
| `gym-import-v2`, `gym-change-v2` | A plan as read from a file, and a change to it |
| `gym-logged-set-v2` | The line said after a set, and that exercise's box |
| `briefing-v2` | The briefing as it reads mid-morning: a box a task, always up to date, with the tasks to come as placeholders |
| `schedule-list-v2` | “my schedule”: what the bot posts by itself and when, the next to run, what is paused; the routine as tidy, briefing, checklist |
| `briefing-v1`, `schedule-list-v1` | The versions before the answers of 2026-10-13 (“as of 6:00 am”; the checklist before the briefing). They go when v2 is approved |
| `schedule-change-v1` | A change to two schedules, with when each would next run |
| `cleanup-v1` | What #bot-log is told about a tidy: only one where something went wrong |

A new version of a sketch gets the next number in its name; the old one
stays until the new one is approved, and is then removed. Each ends
with a small 🧪 line saying its version and what was simplified to fit.
