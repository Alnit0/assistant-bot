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
screen waits for the same check. These are built this way, behind
`CARDS_V2` (off unless set in `.env`; off, every card looks as it
always has): today's pills checklist, the reminder, the confirm card,
the card that asks a question, the card that asks first because
something is risky, the channel reset card, the list of my schedule,
the briefing (behind `BRIEFING_ENABLED`), and since 2026-10-13 the
rest of the cards a task builds with `core/cards.py`: the list of my
pills, a day and the week looked back on, the weekly summary, the
list of open bugs, the card for a message sent while the bot was off,
and the "which task?" question.

**Still plain, and why** (each needs a pass of its own): a bug's post
in the forum, the archived copy with Restore, and the dev panel are
built with discord.py directly and rewritten in place by their own
buttons; #commands and `help` are pages of text; a line that reports
a change ("✅ Zinc · taken …") is a line, not a card; what goes to
#bot-log is an embed; timers are left as they are.

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

## What I need to know (the rule)

Anything I need to know reaches me through **the briefing or a ping**,
never only through #bot-log. #bot-log is a record kept just in case; I
do not read it.

| What | Where it shows | Does it ping? |
|---|---|---|
| Needs me: a job that did not work, reminders that can't be sent, spend over the day's limit, memory over its limit, a bug the bot filed | The briefing's red "⚠️ Needs a look" box, with its bug's id; the status line; gone once dealt with | By day, at once: one line in the hub that mentions me ("⚠️ B14 · backup failed at 3:00 am"). In quiet hours nothing, then one ping at 7:00 am if the box is not empty ("⚠️ 2 things need a look") |
| A pill reminder | The hub | Always, at any hour |
| Worth knowing, not urgent: an unexpected restart, a catch-up, a self-test that did not run | One small line at the foot of the briefing ("🗒️ 3:02 am · …"), three at most | Never |
| Everything else the bot does by itself | #bot-log only | Never |

A ping is one short line, the same words as the status line, and never
holds a pill's name. It is an Alert: it goes once the thing is dealt
with.

## The status line

Three words, used the same way everywhere: the **status line** is the
custom status text under a bot's name; the **presence** is the online
dot, which Discord sets and the bot never does; the **nickname** is
the name (below).

Live's status line is one thing: **the top item of the attention
model** (`core/attention.py`), in its short form.

- **Format**: the item's icon, then numbers and short 12-hour times
  joined by " · ": `💊 2/5 · 12pm`. A time is "12pm", "6am", "8:30am".
  Never a pill's name, never a sentence, never more than one item.
- **What is on it**, first that applies:

| Level | When | Reads |
|---|---|---|
| 1 | Something is wrong and needs me: a job that did not work, a self-test that failed, the bot's memory use, a bug to retest, dev mode left on. The bug's id first: a problem of the bot's own files its bug itself | `⚠️ B14 · backup failed`, `⚠️ D3 · self-test failed`, `⚠️ self-test spend · US$2.05`, `⚠️ B9 · memory 312 MB`, `⚠️ B4 · retest`, `🛠️ dev mode` |
| 2 | Something is due now or overdue; or a dose was missed and none is due now (until the next one falls due, or the day ends) | `💊 due 12pm`, `💊 missed 9am` |
| 3 | The next timed thing today | `💊 2/5 · 12pm` |
| 4 | Something useful that has no time: doses with no time still to take; a day with everything taken (or dealt with, some of it skipped), until 8:00 pm (`STATUS_DONE_UNTIL`); otherwise when the morning routine next runs | `💊 2/5`, `💊 all 5 taken`, `💊 4/5 · 1 skipped`, `🌅 6am` |
| 5 | Nothing | blank |

- Within a level, the soonest. When nothing timed is left today it
  falls to level 4, else it is blank.
- **No "🟢 Live" and no uptime**: the presence dot says it is on, and
  the uptime is in `dev status`.
- **It changes when a state changes** (a dose ticked off, a job that
  ends, the moment a timed thing falls due, the day ending), never on
  a timer, and is sent to Discord only when it reads differently.
- Dev mode left on is a level 1 item of its own on live ("🛠️ dev
  mode"), not a mark in front of the line.
- Among useful things a task's own comes before "🌅 6am".

Other bots, other lines:

| Bot | Status line |
|---|---|
| The dev bot during a self-test | `🧪 41/103 · 6m`: steps done of all, minutes left; `🧪 41/103 · 6m · ❌2` once steps have failed |
| The dev bot otherwise | `🧪 DEV database · clock +13h` |
| A self-test on live's own account (no dev bot) | `🧪 Self-test running · back about 4:15 pm` |

The status line is silent, so quiet hours never apply to it.

## The bots' names

A bot is called what I named it: `BOT_NAME` in its settings file,
taken on every start. Its nickname changes only for a real state, and
then always as **Name · state**:

| Bot | Nickname | Where its states show |
|---|---|---|
| Live | its plain name, always | the status line ("💊 2/5 · 12pm", "⚠️ backup failed") |
| The dev bot | its plain name; **Name · testing** while a self-test runs, plain again when it ends | the nickname, and the status line ("🧪 41/103 · 6m", "🧪 DEV database · clock +13h") |

Nothing else renames a bot: no marker for the dev database (the old
"· DEV" is gone), no state for live. With no `BOT_NAME` the nickname
is left as it is.

## Lists and looking back

A list shown on request is a standing message: `# icon Title · count`,
one small line of context, a box an item, and no buttons (a list is
changed by words).

| Message | A box is | Its colour |
|---|---|---|
| My pills | a pill in use; Paused and Ended are a box of small lines each, under a separator | grey: nothing in a list is waiting to be done (what is due is the checklist's to show) |
| A day looked back on | a dose, as the checklist words it | what became of it: green taken, red missed, grey skipped |
| The week, and the weekly summary | a day: **Tue 13** · ✅✅❌ 2 of 3 | red when a dose was missed that day, blue while one is still to take, green otherwise; the streak is the small line under the days |
| Open bugs | a bug: its id, linked, and what it is about | amber when a fix is ready and it is mine to retest, grey otherwise; green for "No open bugs." |

More items than fit a box each (twelve) share one box of lines: a
message never loses an item to fit.

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

## Options to pick from

`docs/mockups/options/` holds two or three sketched variants of each
main card (the checklist, the reminder, the briefing, the confirm
card, the question card). Option A of each is the card as it is built;
the others try one idea each (grouped, next first, shorter, the
question first…). `python -m selftest.options` posts them, as the dev
bot, in a post of its forum called "🎨 Design options", each under a
line saying which it is and what differs, with a summary to answer
with picks. They are sketches: nothing in a real card changes until a
pick is made and built.

## Drafts: round 2 (2026-10-14, nothing decided, nothing built)

From the feedback on round 1. The sketches are
`docs/mockups/options/round-2/` (each file ends `-v1`: a changed
sketch gets a new number, the old one stays), posted in the same
"🎨 Design options" post by `python -m selftest.options --round 2`.
Everything in this section is a **draft**: the rules above stand until
a pick is made (`docs/QUESTIONS.md`, under Design).

**Kept from round 1**: the horizontal rule between items; the thin
question card (the question as the heading, what was understood small
under it, the answers in one row). `r2-question-stacked-v1` shows two,
one above the other.

**Hierarchy (draft).** Three levels, the same on every card:

| Level | Written | Used for |
|---|---|---|
| The card's title | `## ` | "## ☀️ Today", "## 💊 Pills · change" |
| Each item | `### ` | each pill, each section of the briefing |
| Details | `-# ` | notes, hints, what happened, the foot |

A rule (`---`) between items, no box an item. Sketches:
`r2-briefing-hierarchy-v1`, `r2-checklist-hierarchy-v1`,
`r2-confirm-hierarchy-v1`. Today a title is `# ` or `## ` and an item
is a bold line in a box of its status's colour: with no box, the
colour of a status is lost, and the mark beside the name has to carry
it (●○○, ✕, ✅).

**A change (draft).** The old value struck through and the new one
bold, in place of code blocks: `schedule · daily at ~~8:00 pm~~ →
**9:00 pm**`. A time elsewhere (not a change) would then be plain too.

**Progress marks (draft).** For anything ticked off out of a number
(doses now; to-dos and gym sets later), four styles to pick from:

| Style | Looks like | For | Against |
|---|---|---|---|
| Squares | 🟩🟩⬜⬜⬜⬜ 2/6 | Clear at a glance, coloured | Wide: six is half a phone line at heading size; ⬜ is faint in light mode |
| Bars | ▰▰▱▱▱▱ 2/6 | Compact; what the hub's bar uses today; the same on every phone | No colour |
| Task icons | 💊💊⚪⚪⚪⚪ 2/6 | Says which task without a label | Busy; some icons (🏋️) are hard to tell from ⚪ when small |
| Custom emoji | one joined bar with rounded ends | The best looking | Six images to draw (listed in `r2-progress-custom-v1`); a phone that fails to load them shows `:bar_mid_full:` |

**A total for the day (draft).** The briefing's title carries the
whole day: "## ☀️ Today ▰▰▰▰▰▱▱▱ 5/8", and under it one small line a
task ("-# 💊 pills 2/5 · 📝 to-dos 2/2 · 🏋️ gym 1/1"). Built from each
task's done out of total: the summary contract (`actions.Summary`)
would gain two numbers, `done` and `total`, which a task with nothing
countable (weather) leaves out, and the briefing would add them up
without knowing any task. Sketch: `r2-briefing-total-v1`.

**A block bar (draft).** Ten cells and a percentage, solid for done
and light for not done: "███████░░░ 70%". Four ways, each shown as the
day's total at the top of the briefing and as one pill's progress:

| Way | Looks like | Note |
|---|---|---|
| Plain, a line of its own | ███████░░░ 70% | 14 characters: fits any phone |
| In a heading | ## ☀️ Today ███████░░░ 70% | 24 characters at heading size: the one that could wrap on a narrow phone |
| In inline code | `███████░░░` 70% | Every cell the same width whatever the font, on a grey patch |
| Partial blocks | ███████▎░░ 73% | Fills smoothly (▏▎▍▌▋▊▉); the part-filled cell has no light shade behind it, so there is a small gap in the track |

**Mobile widths.** Not looked at on a phone: I can post sketches but
not see them. What can be said from counting: a phone shows roughly 40
characters of ordinary text on a line, about 30 at `###` size and
about 24 at `##` size, and an emoji takes about two. So the bar in a
`##` title is at the limit, six squares in a `##` title are over it
with a count, and everything else has room. The block characters are
one width each in the fonts phones fall back to, but only inline code
makes that certain. Please check the four block bars and the squares
on your phone before picking.

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
