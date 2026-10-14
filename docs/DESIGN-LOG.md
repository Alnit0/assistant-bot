# Design log

One section a round of the hub's design: what it holds, what Alex said about
it word for word, what changed because of that, and where it stands. Newest
round last. How a card is drawn in detail is `docs/DESIGN.md`; this file is
the history and the loop.

## The loop

1. **Each round is posted as a preview** in the "🎨 Design options" post of
   the dev bot's forum, under a message titled "Round N", drawn by the real
   code from made-up data (`python -m selftest.preview`). No real pill
   names: the pills are Pill A to Pill E.
2. **Live only changes when Alex says "ship round N".** Shipping is
   `DESIGN_ROUND=N` (with `CARDS_V2=true`) in live's `.env` and one restart.
3. **At the start of any batch that touches the design**, Claude Code reads
   Alex's replies in that post since the last round (as the dev bot, over
   HTTP), copies them here word for word under the round they answer, and
   turns them into a numbered list of changes for the next round.
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
