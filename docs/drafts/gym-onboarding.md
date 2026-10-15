# Gym onboarding: three ways in (draft, 15 Oct)

Sketches only: nothing of gym is built, and nothing here is decided. The
mock cards are in the Design forum, "Design · Gym onboarding sketches"
(`python -m selftest.preview --gym`), one reply an option. They take the
answers of 15 Oct as given: kilograms throughout, the next workout in
turn, posted in the hub, only when asked, and a whole exercise logged at
once. The questions this raises are 76 to 79 in `docs/QUESTIONS.md`.

The plan in every sketch is made up: Push, Pull and Legs, four exercises
each.

## What all three share

- **Today's workout** comes when you type `gym` (or "what's my workout
  today?"): one card in the hub, by the relevance rule. The exercise you
  are on is in full with its buttons (**Done as planned**, green;
  **Different…**, blurple, a one-box form such as `62.5 x 10, 10, 9`),
  with last time's sets small under it; the next exercise in full with no
  button; the rest one small line. It is edited in place as you log.
- **Logging a whole exercise**: "bench 60 for 10, 10, 9", or Done as
  planned. One line back says what was logged against last time
  ("✅ Bench press · 60 kg × 10, 10, 9 · last time 10, 9, 8 ▲") and what
  is next. A reply to that line with other numbers corrects it.
- **Which workout**: the next in turn after the last one finished.
- **Never**: a card saved unseen, a number read by Claude (Python reads
  every set, rep and weight), an exercise or weight on a lock screen.

## A · Attach your spreadsheet

**What you do.** Attach the sheet as a `.csv` to a message in the hub or
#inbox, with any words or none. Or copy the rows in the sheet and paste
them into a message: pasted cells arrive as text with tabs between them,
which reads the same as a `.csv`.

**What you see.** One card, "🏋️ Gym · new": each workout and its
exercises as read (`Bench press · 3 × 8–12 · 60 kg · rest 2 min`), the
columns the bot did not use listed by name, a ❓ on a heading it was not
sure of ("Load ❓ → weight"). Save and Cancel. A cell it cannot read
("AMRAP") is marked ❔ and there is no Save until it is put right.

**Changing the plan later.** Send the sheet again: a change card shows
only what differs (`Bench press · weight · 60 kg → 62.5 kg`, ➕ a new
exercise, ➖ one gone). The sheet stays the one place the plan lives.

**What could go wrong.**
- Exporting a `.csv` on a phone is awkward (the Google Sheets app has no
  plain export); pasting the rows is the way round it, but a big paste
  can pass Discord's 2,000 characters (4,000 with Nitro).
- Headings the bot does not know (a "Load" column, a "Tempo" one) need a
  ❓ and a reply to fix.
- A layout with a tab a day, or merged cells, does not read as rows.
- Two places to change the plan (the sheet, and words if C is added later)
  can disagree.

## B · A short guided setup

**What you do.** Say "set up my gym plan". The bot asks one thing at a
time on a thin question card: how many workouts you rotate through
(buttons 2 to 5), what they are called (you type "push, pull, legs"),
then each workout's exercises, one line each ("bench 3x8-12 60kg").
Next moves on; Cancel stops and keeps nothing.

**What you see.** After each workout, its card with what was read; at the
end, one card of the whole plan with Save.

**Changing the plan later.** In words: "add face pulls to pull, 3 x 15 at
10" gives a change card with ➕; "bench is 62.5 now" a change card with
old → new.

**What could go wrong.**
- The most steps of the three: twelve exercises is twelve lines across
  four or five cards, on a phone.
- A setup left half way (a card expires after 30 minutes) loses what was
  typed unless it is kept as a draft.
- No sheet to look back at: the bot becomes the only copy of the plan
  (`show my gym plan` lists it).
- It is a kind of card the bot does not have yet (several steps in a
  row): new core work.

## C · Say it in words

**What you do.** One message: "my gym plan: push: bench 3x8-12 60, ohp
3x8-10 40, dips 3x10, pushdowns 3x12 20. pull: … legs: …". Claude splits
it into workouts and exercises as said; Python reads every number.

**What you see.** The same "🏋️ Gym · new" card as A, with ❓ on what was
guessed ("dips: no weight said, so bodyweight"). Save or a reply to fix
("dips are 10 kg").

**Changing the plan later.** In words, as in B.

**What could go wrong.**
- A long message to type on a phone, and easy to mistype.
- Short names ("ohp") are kept as typed: the bot never expands them, so
  the card says "Ohp" unless you say "overhead press".
- Splitting a long message into workouts is Claude's part, and a miss
  (an exercise under the wrong workout) is only caught on the card.
- Every new plan is typed again from scratch.

## Suggestion

A for the first setup (the sheet you already keep, by file or by
pasting its rows), with C's way of changing one thing in words added
later, once it is settled which of the sheet and the bot holds the plan
(question 77). B only if neither suits: it is the most work to build and
to use.
