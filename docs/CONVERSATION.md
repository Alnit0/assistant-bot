# How the bot should talk

**Status:** in use
**Applies to:** every task, now and in future. Code, prompts and QA are
judged against this page. When a change breaks a principle here, it is a
bug, not a matter of taste.

---

## 1. Purpose

A personal assistant I talk to naturally, the way I'd talk to a person.
When I'm specific, it gets it exactly right. When I'm brief, it uses
context to fill the gaps and shows me its guesses. It does nothing until
I agree, and keeps out of the way when there's nothing to do.

I'm happy to type more to be clear. In return, everything I say must be
understood and used.

---

## 2. Principles, in priority order

When two principles clash, the higher one wins.

1. **Never claim something happened that didn't.** A confirmation is
   only sent after the change is checked in the database.
2. **Specific in, exact out.** When I say where something goes ("to my
   pills") and give details (dose, times, notes), the card matches
   exactly: right task, every detail used, nothing dropped, no ❓ on
   anything I stated. This is the bot's most important skill
3. **Where I point beats what's newest.** A Discord reply to a message
   means that message, for everything.
4. **Fill gaps from context, like a person would.** Only for what I
   didn't say: what I'm pointing at, what I just looked at, what I just
   said. Context never overrides something I stated
5. **Show what you understood before acting.** Clear visual and text
   feedback, so I can agree or correct it at a glance. Guesses are
   flagged with ❓
6. **Guess when it's safe, ask when it matters.** Guess (with ❓) when
   one reading is clearly likely and easy to fix. Ask when the readings
   lead to meaningfully different results, when a needed detail has no
   sensible default, or when what I said contradicts itself. Questions
   go on the card, with buttons for the likely answers (see section 4)
7. **Fewest steps.** One tap to accept; one reply or tap to fix or
   answer.
8. **No clutter.** Reply in words only to questions and requests. A
   remark, a note to myself or a thank-you gets no reply. Reactions on
   my message are the status: 👀 while it is being worked on; when done
   it comes off, whether or not a card or reply was sent, and nothing is
   left for nothing-to-do. A 👀 that stays means the bot is stuck. If it
   went wrong, ⚠️ takes its place, with one short plain line only when I
   can act on it (try again, wait, rephrase); the error is kept for
   `dev why` and a 🐞 report. ✅ is not used to acknowledge. No links to
   the message right above. Old cards get replaced, not stacked.
9. **Consistent everywhere.** Every task looks and behaves the same
   way. Learn it once.
10. **Private.** Notifications never show sensitive names (e.g. pills).

---

## 3. Context rules

- **What I state wins.** "to my pills", "on the shopping list", "for
  packing" decides the task outright; a stated time, dose or amount is
  used as given. Context only fills in what I left out
- **A Discord reply wins** over newer messages. "that", "it", "make it 2", "pause",
  "dev why": all apply to the message I replied to
- **"that" / "it" without a reply** means the last thing I mentioned or
  my own newest message, never one of the bot's messages
- **An open card is the conversation.** "make it 3", "and jam", "no,
  packing" change the card I'm looking at
- **A list I've just asked to see is context.** "add milk" straight
  after "what am I packing?" means packing
- **Meaning beats keywords.** "how much milk should I drink?" is a
  question, not a shopping item
- **Everything I say counts.** Several items or requests in one message
  are all handled. Nothing is silently dropped

---

## 4. Cards

- First line: task icon, task name, kind of change (new, change, remove)
- Every interpretation written out; guesses flagged with ❓, warnings
  with ⚠️ and the sensible fix already applied
- Changes to existing things shown as **old → new** on one line
- **Questions live on the card.** The card shows everything it did
  understand, then the question with a button per likely answer; I can
  also just type the answer. Save stays unavailable until it's answered.
  One question at a time; most important first
  ```
  💊 Pills · new
  **Iron** · daily at ❔
  Is that 8 in the morning or the evening?
  [8:00 am] [8:00 pm]   [✖️ Cancel]
  ```
- **Save** / **Cancel**; destructive actions say they can't be undone
- **Correcting in chat replaces the card.** "no, I meant 9pm",
  "actually 2", "make it shopping": the old card is deleted and a fresh
  one posted with the correction. Works whether I answered a question,
  pressed nothing, or the bot guessed
- "No, …" undoes the mistake it corrects, and only that
- **Just after Save**, the same kind of correction ("no, I meant 9pm")
  becomes a change card for what was just saved: "8:00 pm → 9:00 pm"
- Cards expire after 30 minutes

---

## 5. Always / never

**Always**
- 12-hour times (8:00 pm)
- Same wording for the same confirmation, every time
- Quote what a reference points to when acting on it

**Never**
- Tool or action names in replies
- "Reply ok" or "I'm proposing…"
- A question as a separate message; questions go on the card. The one
  exception: choosing between tasks, when there is no signal at all which
  is meant, is asked before any card (a button per task)
- A question about something I already stated
- Saving a guess I haven't seen
- A reply when nothing needed doing
- Offering to do what I just asked, or ending a reply with "want me
  to…?" or "would you like…?". Do it instead
- An answer about my data from plain chat: anything about what I have
  (a list, my pills, my timers) comes from the task that owns it
- An internal label as text ("(nothing)", a route or action name)

---

## 6. Golden conversations

The acceptance test for the core. Every change must keep these passing.
Write them the way I'd really say them.

| # | I say or do | What should happen |
|---|---|---|
| 1 | "add vitamin D to my pills, 1 tablet, once a day at 8am with food" | 💊 Pills card exactly: Vitamin D · 1 tablet · daily at 8:00 am · with food. No ❓ anywhere |
| 1a | "add course A to my pills, 3 times a day at least 3 hours apart, with food, for 7 days starting tomorrow" | Every detail on the card: interval ≥3h, with food, tomorrow to 6 days later. No ❓ |
| 1b | "add vitamin D once a day" (brief) | Pills card, daily, any time; anything guessed has ❓ |
| 1c | "add iron to my pills at 8" | Card asks "8 in the morning or the evening?" with [8:00 am] [8:00 pm]; tapping one fills it in and enables Save |
| 1d | "add magnesium to my pills, twice a day at 8am" | Card asks for the second time (only one given); everything else filled in |
| 2 | …then "actually make it 8am" | The card is replaced with 8:00 am |
| 2a | Card asks 8am or 8pm; I tap 8:00 pm, then say "no, I meant 9pm" | Old card deleted; new card with 9:00 pm |
| 2b | Pill saved at 8:00 pm; straight after, "no, I meant 9pm" | Change card: 8:00 pm → 9:00 pm, with Save |
| 3 | "set a tea timer for 5" | Timer starts; no card |
| 4 | …then "give it 2 more" | Tea timer gets 2 more minutes |
| 5 | "what's the capital of France?" | Plain answer, no card |
| 6 | "add honey, jam and 5 eggs" | One card with all three, eggs × 5 |
| 7 | Reply to an older card with "make it 2" | That card changes, not the newest |
| 8 | Two timers running; reply to the older timer's card with "pause" | That timer pauses, not the newest |
| 9 | Reply to a bot message with `dev why` | The trace for that message |
| 10 | "what am I packing?" then "add milk" | A packing card |
| 10a | "what am I packing?" then "add milk to the shopping list" | A shopping card: what I stated beats context |
| 11 | Card with milk and bread rolls, "make it 2" | Bread rolls × 2 (last mentioned) |
| 12 | …then "no, 2 milk" | Milk × 2, bread rolls back to 1 |
| 13 | "delete zinc and its history", Delete for good | Zinc is gone; the reply only says so if it really is |
| 14 | A message with nothing to do | No reply. The 👀 comes off and no reaction is left |
| 15 | "shopping is boring" (a remark) | No reply: only questions and requests get words |
| 16 | "shopping list" (a list's name on its own; also "my pills", "timers") | The list itself, Live, from the bot's own code. No words about it, and no offer after it |
| 17 | "I've taken my Zinc today" | Zinc is ticked off on today's checklist, edited in place, and one line says so and what is left. Never silence: a message that names one of my pills or timers is never taken for a remark |
| 18 | | |
| 19 | | |
| 20 | | |

---

## 7. Not now

Deliberately out of scope until pills reminders work:
- Pin, archive or delete by words (reactions do this)
- Forms for setup
- `dev qa` step-through mode
- New tasks or dev tools