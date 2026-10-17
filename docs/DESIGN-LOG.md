# Design log

One section a round of the hub's design: what it holds, what Alex said about
it word for word, what changed because of that, and where it stands. Newest
round last. How a card is drawn in detail is `docs/DESIGN.md`; this file is
the history and the loop.

## The loop

1. **Each round has its own post** in the Design forum (from 15 Oct),
   named "Round N", drawn by the real code from made-up data (`python -m
   selftest.preview --post-round N --tag preview`). It carries one tag:
   🟢 Live (what the hub shows), 🟡 Preview (built, not shipped) or ⚪
   Retired. No real pill names: the pills are Pill A to Pill F. Rounds 1
   to 4 were posted before that in one "🎨 Design options" post of the
   dev bot's bugs forum, which stays as it is with the feedback in it.
2. **Live only changes when Alex says "ship round N".** Shipping is
   `DESIGN_ROUND=N` (with `CARDS_V2=true`) in live's `.env`, one restart,
   and `python -m selftest.preview --ship N` (Round N Live, the round
   that was Live Retired).
3. **At the start of any batch that touches the design**, Claude Code reads
   Alex's replies in each round's post (`--replies-round N`, as the dev
   bot, over HTTP), copies them here word for word under the round they
   answer, and turns them into a numbered list of changes for the next
   round.
4. **Locked parts change only when his feedback names them.** Each round
   lists what is locked.
5. **Every round that was built stays selectable**: `DESIGN_ROUND` in
   `.env` picks it, and "go back to round N" is that setting and a
   restart. The rounds are `design.ROUNDS` in `core/design.py`; a round's
   own shapes keep its number in their name (`_standing_r1`,
   `tasks/pills/sheet_r1.py`) and are never restyled afterwards. With
   `CARDS_V2` off, every card is the plain look, whatever the round.

## Round 1 (built 2026-10-13)

The first Components V2 look, from the picks of the first design options.

- A box an item (a pill, a schedule, a bug), each in the colour of its
  status; `# icon Title · progress` on a standing message; a decision's
  `## heading` inside its box; times in code marks
- Selectable: `DESIGN_ROUND=1`

**Status**: built, never on in live (`CARDS_V2` stayed off). Kept as the
way back.

## Round 2 (2026-10-14, sketches only)

Sketches of a hierarchy, struck-through changes and progress marks
(`docs/mockups/options/round-2/`). Nothing was built: what Alex liked went
into round 3.

## Round 3 (built 2026-10-15)

The type scale, from Alex's screenshots of rounds 2 and 3 and his brief
(docs/ADVISOR.md, section 7).

**What it holds**

- A message is a page: `##` page title once a message; `###` card title
  with the topic's progress dots and count; **bold** item names; normal
  text for values; `-#` small text for details
- One box (container) a topic; a horizontal rule between items inside a
  box; the box's edge colour is the most urgent state in it
- Progress is dots with a count (`●●○○○○ 2/6`); over ten things, ten dots
  scaled and the exact count after; no bars, no percentages
- Times in bold, never code; a Discord timestamp ("in 2 hours") after a
  time still to come
- A change is `~~old~~ → **new**`
- Thin question cards (the question as the card title, the answers in one
  row), so two stack
- Buttons: green positive, red destructive, blurple other choices, grey
  only for Cancel with ↩️; only on what can be done now
- The pills card: due or overdue first, then coming up, then any time, a
  missed pill, then done, paused and not today in one small line
- The briefing: page title with the day's dots, then Needs a look (only
  when something is wrong, red), what was held back overnight, the
  weather, then each task's box
- A card too big for one message is made to fit (buttons go first, the
  next one due keeps its own), never refused

**Locked** (Alex liked them; they change only if his feedback names them)

1. Horizontal rules inside boxes
2. Boxes per topic
3. Progress dots with a count
4. Thin question cards
5. Changes as struck-through old value, then bold new value

**Open points the build had to decide** (say if any is wrong)

- The briefing's page title has the day's dots and the small line a task
  under it; with only pills counting, that repeats the pills box's own
  dots (question 45 still picks title or line)
- A one-card message (the checklist, a confirm card) has a `##` page title
  and the box's `###` card title, which can say nearly the same thing
- The weather comes first among the task boxes, as it counts nothing and
  sets the scene; the counted tasks follow in the ranking's order

**Status**: built 2026-10-15, behind `CARDS_V2` with `DESIGN_ROUND=3`. Preview posted the same day in the design options post, under "Round 3 built". Live: **on since 2026-10-15, 8:59 am** (`CARDS_V2=true`, `DESIGN_ROUND=3` in live's `.env`, one restart); the briefing and the pills checklist were redrawn in place. Waiting on Alex's look on his phone.

**Alex's feedback** (copied word for word, newest last)

- 2026-10-15, answering question 64: "task cards use a ### card title
  and no ## page title; ## appears once per message, in the briefing.
  Make the pills card match." Done the same day: the pills card is one
  box with no page title (round 3, not a new round: he asked for it).
  Read as about the hub's task cards; a card that asks and a list shown
  on request keep their `##` title (docs/STATUS.md, Decided).
- 2026-10-15, confirming that reading: "yes, cards and lists shown on
  request keep their ## page title. One ## per message as its page
  title; only the hub's task cards, which sit under the briefing, drop
  it." So: one `##` a message, as its page title; the hub's task cards
  (pills, reminders, personal routines, to-dos) have none.

- 2026-10-15, Alex and a friend of his, round 4: "we show a lot of
  information that is no longer relevant; paused and missed pills take up
  too much space; remove duplication with only one Taken button, perhaps
  a pop-up with the current time filled in that I can edit; less buttons
  the better."

**Changes for round 4** (from that feedback, and his brief of the same day)

1. The relevance rule, for every card (below)
2. One Taken button a dose that can be taken now, in place of Taken,
   Taken at… and Skip; Skip by words only, with undo
3. Two ways for Taken to work, a setting to compare them: a pop-up with
   the time filled in (variant 1), or at once with a line that a reply
   with a time corrects (variant 2)

## The relevance rule (locked: Alex's direction, 2026-10-15)

On every card (pills, to-dos, reminders, and the Today card and
personal routines later), each thing is shown by how much it matters now:

| What it is | How it shows |
|---|---|
| Due or overdue (can be done now) | A full line, with its button |
| The next thing coming up | A full line, no button |
| Everything later today | One small line, times only |
| Done | One small line, with a count |
| Missed | One small line, with a count and the time; the detail goes to the next morning's briefing |
| Paused | Not on the card; shown when asked ("show paused") |

The full card, everything listed, is there on request ("show all my
pills", "show all my to-dos"). This is locked: it changes only if Alex's
feedback names it.

## Round 4 (built and shipped 2026-10-15)

Built on `feature/round-4`, behind `DESIGN_ROUND=4`. Preview posted on 15
Oct as "Round 4 preview" in the design-options post, with question 67
(variant 1 or 2). Alex answered the same day and said ship it: merged into
`feature/pills` and live at that evening's restart (`DESIGN_ROUND=4`).
Going back is `DESIGN_ROUND=3` and a restart.

- **The relevance rule** (`design.relevant`, `design.Thing`) on the pills
  card, the reminders card and the to-dos card. On the pills card for a
  morning with nothing taken: 5 lines and 2 buttons, where round 3 has 13
  and 15; midday (2 taken, 1 missed, 1 paused, 1 due, 2 later): 7 and 1,
  where round 3 has 9 and 6.
- **One Taken** a dose that can be taken now, on the checklist and on a
  reminder (with Snooze): taken at once, and a line "reply to this with a
  time to put it right", recorded so that a reply corrects it (variant 2,
  Alex's answer to question 67; the pop-up of variant 1 and its setting
  `TAKEN_BUTTON` are gone).
- **The list rule** (Alex's answer, 15 Oct), for the to-dos card and any
  list card to come (`design.listed`): the first three open things in
  full (overdue first, then today's, then any day's), the rest one small
  line ("+4 more"), and one Done dropdown for every open one, a later
  day's too, in place of a button each. The dropdown holds Discord's most
  (25), the most pressing first; beyond that a small line says to use
  words. Done by words and "undo that" work as before.
- **Skip is said in words**, and "undo that" puts a skipped dose back.
- Paused pills are not on the card; "my pills" shows them, and every pill
  in full. Missed: a count and its time; the briefing's line about the day
  before has the rest.
- Tests: `tests/test_round4.py`; self-test start 8 (stage `round4`): the
  card, Taken at once and corrected by a reply, Skip and undo in words,
  the to-dos card and a pick in its dropdown; recorded answers.

**Alex's feedback** (copied word for word, newest last)

On the preview, 15 Oct (his decisions, as relayed):
- "67: version 2 (Taken logs at once; reply with a time to correct).
  Remove version 1 and its setting."
- "To-dos in round 4, not round 5: the card shows the first 3 open
  to-dos (overdue first, then today, then any day) and a small line for
  the rest (+4 more). Replace the per-to-do Done buttons with one Done
  select menu listing every open to-do (up to Discord's limit; beyond
  that, the 25 most relevant and a note to say done by words). Done by
  words and undo still work. Same rule for any future list card."
- "Ship round 4."

**Changes for round 5**

(none yet)

## A day in the hub (2026-10-15, evening)

Not a round: the hub as it is (round 4) through one made-up day, read back
at eight moments by `python -m selftest.day` and posted as "Design · A day
in the hub" in the Design forum, a reply a moment with the status line and
what changed. Alex's replies in the round 3 and 4 posts before it: none.
What it found that was plainly wrong is fixed (the status line held by
overdue to-dos, the line after Taken left all day, the briefing's reminders
and calendar boxes stuck on the morning, "Next" for a dose long due); the
choices are questions 68 to 75 in `docs/QUESTIONS.md`. Run it again for
each round: it is the same day every time, set up in words with recorded
answers.

## Round 5 (built 2026-10-15, late; Preview, waiting on Alex)

**His feedback on the live hub (round 4), word for word:** "there's a
little bit of overlap with pills and calendar"

**The changes it led to, and his suggested answers applied** (each
marked in the post "Design · Round 5" for a yes or no):

1. R5.1 The briefing is the morning overview: Needs a look and Weather
   keep their boxes; every task with its own card is one line in one
   overview box ("🗓️ The day"), with no progress.
2. R5.2 Its page title is the date with the day's dots: "Today" is only
   the Today card.
3. R5.3 A task card whose items are all done leaves the hub; something
   new brings it back (the pills checklist too, unless a dose was missed).
4. R5.4 No footer: the how-to is in `help briefing`.
5. Questions 68 (order kept when a card comes up mid-day), 69 (no count
   on the Today card), 70 (to-dos off the Today card), 72 (the overview
   in one fixed order), 73 (a "can't find that" goes like any answer),
   75 (a missed dose on the status line until the evening). 71 was
   already so; 74 is replaced by R5.3.

Behind `DESIGN_ROUND=5`. The day in the hub was run in round 4 and in
round 5 and posted side by side in the same post.

## Pills show exact times only (2026-10-16, midday)

Alex: "Live pills card at 11:43 showed dose 2 · 11:51 am · in 10 minutes
(the Discord relative timestamp). It should have said 8 minutes."

The timestamp was right (the dose's own due moment, 11:51 am); the card
had been drawn at 11:22 and the phone app had not brought "in …" up to
date. Discord's relative timestamps don't reliably refresh on the phone.

**Alex's rule, pills only:** exact times, no relative countdown anywhere
a pill appears: the pills card, pill reminders and the "what's left
today?" answer. Every other countdown stays as it is (the briefing, the
Today card, reminders).


## Alex's design decisions, 17 Oct (evening)

Sent during the evening batch, recorded here word for word in their parts.

**The diary:** "The 9pm ask: 📔 How was today? with a ✍️ Write button
(opens a Discord modal with a multi-line text box) and the three mood
buttons. Replying to the ask also saves the reply as the entry. Tapping a
mood saves it, then shows one small follow-up offering ✍️ Add a few words,
never repeated. Writing any time still works; a Write on a day with an
entry appends." And: "Show only the streak: the diary has exactly one
line, in the briefing's The day only: 📔 streak N, plus · not yet from 6pm
or · written today. Never in the Today card. Remove yesterday's mood and
any past-day mood or content from every surface, including the weekly
summary (replace the moods line with days written out of 7). Past entries
only when Alex asks. Keep all stored data."

**The week view:** "One message, pinned, edited in place as things change
(coalesced, at most one edit a minute): one box per day Monday to Sunday
of the current week. Each day lists the notable items in time order
(calendar events with times, timed reminders, birthdays, expiries and
renewals due, gym days when gym exists); daily repeats folded into one
small line (💊 3 doses · 🔁 2 routines). Today highlighted, past days
faint. Rolls over each Monday at 12:01am." "A second message below, also
kept up to date: next week, same layout, collapsed to one line per day."
"my week, this week, next week, what's on Thursday answered in place
anywhere with the same layout." "Lock-screen rules unchanged; edits never
ping."

**Round 6, a preview:** "Header (the briefing): date with the day's dots;
one small line with weather and what's next; one faint line listing what
is done today (name and time); Needs a look only for real problems. No
other boxes." "Below it, one card per item in time order: pills, personal
routines, calendar events, timed reminders, to-dos with a planned time,
the diary (from 6pm), expiries or birthdays due today, and free time gaps
of 90 minutes or more outside events (with how many to-dos could fit).
Each card: emoji, title and time; one or two detail lines; its own button
only if it can be acted on now." "Pills: one card per dose at its planned
time; later doses marked planned; when a dose is taken or skipped,
recalculate later doses with the existing rules and update their cards in
place, moving them if needed, showing a change as struck-through old time
then bold new time with why (dose 1 was taken at 9:15am). Only the due
dose shows Taken. Also show the one-moving-card variant for comparison,
labelled." "Long events (work 8am to 5pm): placed at the start time;
while on, shown as on now · until 5:00pm with time left; items during it
appear below it in time order; free time never shown inside an event;
when finished, joins the done line." "Finished items leave their card and
join the done line. Untimed to-dos in one card at the end. Order kept by
rewriting cards in fixed message slots, not reposting." "Conversation
tidy (preview it too): Alex's messages in the hub and the bot's replies
deleted 10 minutes after the exchange is finished; replies to deleted
messages deleted with them; What's new and restart notes gone by noon,
and restart notes only when something was missed."

**What was done with them:** the diary and the week view are built and
ship tonight (STATUS, "Evening batch, 17 Oct"). Round 6 is a layout
(`core/timeline.py`, `DESIGN_ROUND=6` a preview round in
`design.PREVIEW_ROUNDS`), drawn from the made-up day beside round 5's real
hub in "Design · Round 6 timeline"; the hub's own messages are not
switched to it, and the conversation tidy is shown, not built, until Alex
picks round 6. Live stays on round 5.
