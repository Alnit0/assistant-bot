# Design

How a card looks. One style for every task, so it belongs to the core:
a task supplies what a card says, never how it is laid out. It is
written for Discord's Components V2 (text, boxes, separators and
buttons in one message). `docs/CONVERSATION.md` says what a card must
say and when; this file says how that is drawn, and where the two
touch, the standard wins.

**Status (2026-10-12):** the colours and the sketches are approved
(Alex, 2026-10-12); the lock screen waits for a check on the phone.
Nothing real is drawn this way yet: the sketches in `docs/mockups/` are
posted with `dev mock <name>`, and the bot's own cards are still plain
messages until each is converted.

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

A box's colour is its status, the same in every task.

| Status | Accent | Means |
|---|---|---|
| Due | amber | Something to do now or next, with a time |
| Any time, still to take | blue | To do today, with no time it is due at |
| Taken / done | green | Finished |
| Missed | red | Its time passed and nothing was done |
| Paused, to come, skipped, snoozed | grey | Nothing to do now |
| A decision (a confirm card, a question) | blurple | Waiting for me to choose |
| A card that asks first because something is risky (a late log, too soon) | amber | Waiting for me to choose, and the ⚠️ line says why |
| Destructive (a reset, delete for good) | red | Can't be undone |

A warning is a ⚠️ line inside a box and never a colour of its own: the
box keeps the colour of its status.

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

## The sketches

| Sketch | Shows |
|---|---|
| `checklist-v2` | Today's checklist: due, any time, taken, missed, skipped by the bot, paused |
| `reminder-v1`, `reminder-v1-first` | A reminder as it reads, and as it is first posted (the line the phone shows) |
| `confirm-card-v2` | A change to two things, with ❓ guesses, old → new and a part not included |
| `question-card-v1` | A card that asks, with an answer a button and no Save |
| `reset-card-v2` | A destructive card |
| `gym-workout-v1` | A workout: done, current, to come |

A new version of a sketch gets the next number in its name; the old one
stays until the new one is approved, and is then removed. Each ends
with a small 🧪 line saying its version and what was simplified to fit.

Six earlier sketches have no new version yet and are kept as they are:
`too-soon` (the amber card that asks first), `reminder-renudge`,
`reminder-missed`, `gym-import`, `gym-change` and `gym-logged-set`.
