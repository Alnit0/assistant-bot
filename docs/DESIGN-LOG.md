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


## The gym (18 Oct, overnight)

Alex's goals for it, word for word: "help upkeep data entry, data
retrieval, create consistency, lower administration, see progress, easy
access to notes, make life easier. Flexible, never naggy." And: "describe
a workout in plain words as full data entry, as an equal to the buttons."

Built to round 5's rules and round 6-ready (one card a session, a box an
exercise, its button only while it can be acted on): "Design · Gym" shows
the import card, the workout card, the Log form, a summary with a best
and a session described in words, from a made-up logbook.

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

## Birthdays reworked (19 Oct)

**Alex's words:** "they only really need to be a calendar notification and
somewhere else they need to be listed; a heads-up 14 days in advance, up
until the birthday, but subtle." Then: "instead of a line in The day, show
its own small box in the briefing titled 🎂 Upcoming birthdays, only when
at least one birthday is within 14 days. Subtle: grey edge (no colour),
each birthday on its own line in small text (Sam · Thu 29 Oct · 10 days;
on the day, Sam · today), soonest first, placed low in the briefing below
the day's items. No buttons, never red or amber, never on the status line
or lock screen." And: "the yearly birthday events the bot puts on the Bot
calendar are never shown as calendar items in the hub, the Today card, the
timeline or #calendar's day lists; birthdays appear only through the
Upcoming birthdays box and the pinned 🎂 Birthdays list (and Google
Calendar itself). Identify them by the bot's own marker on the event, not
by title."

**What was done with them:** the 3-day and on-the-day posts are gone (an
old post's buttons take it away). The briefing's box is a section placed
low (`Summary.low`, its own `heading`), drawn after The day with the grey
(quiet) edge. The list is one pinned message in #calendar, edited in
place. Each event carries a private extended property
(`assistant_hidden`), and the calendar reader leaves any event with it
out, so a birthday is never a calendar item in the hub, the Today card,
the timeline or the week view. The plan no longer lists birthdays either.
Preview: `selftest/tonight.py --plan` draws the box and the list.

## Round 7: the briefing as two messages of embeds (21 Oct)

**What Alex asked, word for word (the heart of it):** "Redesign it to send
two messages with Discord embeds, using the border colour to signal what
each card means." Message 1: the date as the message's text
(`🗓️ **Wednesday 21 October**`), then an embed a thing in time order: blue
routine (work, personal routines), green done or taken, red due now,
yellow a notable event (coming up, or all day), grey later. Events on one
line (`9:00 am · Work · until 5:00 pm`), all-day ones with a title
(`🎉 Hen do`) and their days; a dose a line with its square (⬜ Later,
🟥 Due, 🟩 Taken with the time); a routine `10:00 pm · 🌙 Evening`. At one
time: events, doses, routines. Message 2, no text: the to-dos in pink
(☐ and ☑), the diary's streak in blue; not sent with neither. "The existing
hub that shows counts and summary text is replaced entirely." Behind
`DESIGN_ROUND=7`; round 5 stays the default, round 6 as it is.

**What was done:** `tasks/briefing/embeds.py` lays the two messages out
from each task's `day_items` (a new part of the task contract,
`actions.DayItem`: a kind and a state, never a task's name), and
`interfaces/discord/render.py` draws `cards.Embed`s as Discord's embeds (no
discord.py outside the interface layer). Each message is kept up to date
in place, as the briefing was. Choices made where the ask was silent, to
look at: a skipped or missed dose is grey (⏭️ Skipped, ⬛ Missed); a dose
with no time says "any time"; a routine once done is green with 🟩 Done;
one-off events in the next 7 days are in message 1 as coming up, last;
over ten things (Discord's limit for a message) the tenth embed is a grey
one of the rest. Not done: an emoji by the kind of event (💼 for work),
which needs a word list on the title (CLAUDE.md: never); an event's own
emoji in its title shows. Needs a look, the weather and the spend line are
not in round 7's briefing (the ask replaces the hub entirely); a problem
still reaches the status line and a ping.

## The morning news (21 Oct)

**What Alex decided, word for word where quoted:** the daily read and the planned News headlines become one feature: "it
makes sense to only have one set of news generated". Topics, a fixed slot each: world politics, NZ politics, world news,
tech, AI, and NZ housing and money (house prices, interest rates, the OCR, the economy, in the spirit of a bank's morning
market brief). Web development and programming a wildcard, only on a day with something notable. 7 or 8 stories a day:
one a topic, then 1 or 2 extras for the biggest news. Each story a bold headline that is the link, the topic in italics,
a TL;DR of about 30 words (never more than 40). Compact: one purple embed, numbered, in round 7's message 2 after the
to-dos and the diary's streak. 👍 on it means "good set today"; no per-story 👍 or 👎. Steering in words: "more like 3",
"less AI", "skip housing tomorrow", "more NZ politics", "another one". Then, resumed: a paywalled article is dropped,
never summarised from its feed snippet; at most one US-only politics story a day unless he asks for more.

**What was done:** tasks/reading rebuilt as the morning news (tasks/reading/news.py, pick.py, plain.py), 39 feeds;
message 2 now also sent with the news alone. Preview: "Design · Morning news" (a weekday, a Monday, a quiet day, a day
with a topic empty), with a note asking him to look on his phone. Waiting on his look, and "turn on the morning news".

### The morning news: the hierarchy version (21 Oct, evening)

**What Alex said, word for word, after looking on his phone:** "It's too cluttered in its ordered list layout, it needs
more hierarchy".

**What was done:** the numbered list went. Still one purple embed in round 7's message 2, now a full-width field a topic
that has a story, named in plain words with no emoji (NZ politics, Housing and money, World news, World politics, Tech,
AI, Web dev), in that fixed order; a topic with nothing that day has no field. In each field a story is its headline in
bold as the link and its TL;DR under it as Discord's subtext; a topic with two has both, the bigger first (more outlets),
a blank line between. Steering has no numbers: "more like the housing one", "more like the one about the water reform";
"more like 3" asks which, by topic. Reposted as a reply in "Design · Morning news" (the same four days). Waiting on his
look on his phone, and his eyes on the subtext (below).

### The morning news: the card version (21 Oct, night)

**What Alex said, word for word, on the hierarchy version:** "I don't like the layout, could each news article be its
own card? I can thumb it if I liked it or read it, the hierarchy is poor too."

**What was done:** the news left the hub for #news, a channel of its own beside it (live makes it if it is missing). At
6 am, after the 5:30 pick, each story is its own message with one purple embed: "<topic> · <outlet>" as its author
line, the headline as its title linked to the article, the TL;DR as its description (about 30 words, never more than
40); no fields, no footer, no numbers. In a fixed topic order (NZ politics, Housing and money, World news, World
politics, Tech, AI, Web dev), an extra straight after its topic's first. Yesterday's cards are deleted first. 👍 on a
card is "liked or read", silent, kept for later picks. The hub's message 2 has one purple line, "📰 8 stories in
#news", that opens the first card. Steering in #news, #inbox or a direct message, and by replying to a card ("more
like this", "less of this"). Posted as a reply in "Design · Morning news", headed "The card version". Waiting on his
look on his phone.

### The morning news: the one-message version (21 Oct, night)

**What Alex said, word for word, on the card version:** "There's a gap here that looks bad because each card is its own
message. Can we simply combine the cards into one message?" and "Perhaps we disregard the thumb system for news?"

**What was done:** the day's stories post in #news at 6 am as one message, an embed a story (the same card: "<topic> ·
<outlet>", the headline as the title linked to the article, the TL;DR), 8 at most, in the topic order. Discord's 6,000
characters count for the message's embeds together: on a day that would go over, the longest TL;DRs are shortened, a
headline never. Yesterday's message is deleted first. No 👍 for the news at all: the picks learn from words alone.
"Another one" is a one-story message of its own. A story is named by its words and Python finds it among today's
headlines, asking which when none or several fit. The preview's TL;DRs sat under the wrong headlines (its made-up data
gave a topic's second story the first one's first sentence); the real code now ties each TL;DR to its story by id.
Posted as a reply in "Design · Morning news", headed "The one-message version". Waiting on his look on his phone.

### An animated grid, a proof of concept (21 Oct, night)

**What Alex said:** he asked whether the bot can animate things by editing a message over and over, and for a proof of
concept: "let's get a basic command that displays something". The later real use is a progress grid that fills while
the bot works on something slow (the smart inbox reading a file, the gym logbook import) and then becomes the answer.

**What was done:** "lab grid" (and "lab grid 0.5": the seconds between frames, 0.5 to 3), behind `LAB_GRID`, on in
the dev bot's settings only. One message of 5 by 5 square emoji and nothing else, so Discord draws them large: all
black, then an eight-frame diagonal rainbow wave (🟥 🟧 🟨 🟩 🟦 🟪 rolling across), then all green, and it stops. Each
frame is one edit of the same message; one grid at a time across the bot. Both runs left in the dev bot's #inbox for
him to compare on his phone.

**What Alex said, word for word, after trying it on live:** "It works, the animation isn't really anywhere as good as I had hoped. It may have applications for notifying or changing things but not animating".

**What follows:** no animation by editing; the grid's code stays in the lab, and `LAB_GRID` goes off in live at the
next ship. Short state changes by edit (a square turning green) are kept in mind, only when he asks.
