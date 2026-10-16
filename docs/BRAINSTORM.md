# Brainstorm: what the bot could take off Alex's plate

Written 17 Oct 2026, overnight, by Claude Code. **Sources:** Claude's own
knowledge of what personal and executive assistants do, what planning,
habit, health, money and life-admin apps offer, and what people use AI
assistants for day to day. No web search was run for it (it was the
batch's lowest priority). Mapped to what `docs/ADVISOR.md` and the bot's
own data say of Alex: a full-time job, final-year study, freelance web
work, a flat with flatmates, the gym, pills and a calendar.

**What he asked for:** admin taken off his plate, turning what he gives
the bot into something useful. **Not wanted:** an ideas inbox, a uni
deadline tracker. **Limits kept:** Discord is the interface, it runs on
the EliteDesk, the privacy rules hold (no pill, event or diary words
where a phone or a log could show them), it costs little, and nothing
nags: anything timed is one line or one ping he asked for.

**Each idea:** what it does · how he would use it · value to him (1 to
5) · effort (S, M, L) · what it needs from him.

**Rerun it:** the `/suggest` skill (`.claude/skills/suggest/`) reruns
this brainstorm with the wishlist (what live could not do) and recent
usage. Run it on Sundays.

## Daily planning

1. **Plan my day.** One ordered list of the day across every task, with
   the free gaps between. · "plan my day" → "8:00 Pill B · 9:00 standup ·
   free 9:15 to 12:30 · …" · 4 · S · nothing
2. **Free time finder.** When he has a block free this week. · "when am I
   free for 2 hours this week?" → three slots · 4 · S · nothing
3. **Tomorrow at a glance.** One small line under the 9 pm diary ask: the
   first thing tomorrow and anything to bring. · seen, not asked · 3 · S ·
   a yes to the line
4. **After-work snooze.** Snooze a reminder to when work ends, read from
   the calendar. · Snooze → "after work" · 3 · S · his usual finish time
5. **Sunday reset card.** What slipped this week (to-dos over a week
   old), each with Move, Drop or Keep. · one card on Sunday evening · 4 ·
   M · nothing
6. **Leave-by time.** An event with a place gets a "leave by" line. ·
   "dentist Thursday 3pm at the clinic" → "leave by 2:35" · 3 · M · places
   in the database only, travel times

## Admin and paperwork

7. **Bills from a photo or PDF.** A bill becomes a reminder on its due day
   and a running monthly total. · a PDF in #inbox → card → Save · 4 · M ·
   nothing (the smart inbox does the first half)
8. **Receipts and warranties.** A receipt photo becomes an item, a date
   and a warranty end, kept as an expiry. · photo → "Laptop · warranty
   to Oct 2028" · 3 · S · nothing
9. **Draft the email.** A polite email or message drafted for him to copy
   (the landlord, a client, a refund). · "draft an email to the landlord
   about the leak" · 4 · S · nothing
10. **Forms helper.** Answers to a form's questions drafted from facts he
    has saved (his address, his IRD number never shown in full). · paste
    the questions → drafts · 3 · M · a short profile, kept private
11. **Documents index.** What documents he has, where they are and when
    each expires (passport, licence, insurance). · "where's my insurance
    policy?" → "email from Made-up Insurer, renews 1 March" · 3 · M · a
    list once
12. **Appointment prep.** The day before an appointment, one line of what
    to bring. · "for the dentist bring the referral" → shown the day
    before · 2 · S · nothing

## Health

13. **Pill refill countdown.** From how many he has, when to order more,
    one line in the briefing a week ahead. · "I have 60 of pill A" →
    "order more by 12 Nov" · 5 · M · the count on hand
14. **Prescription renewal.** A prescription's end as an expiry, with a
    nudge to book the GP. · "my prescription runs out 30 Nov" · 4 · S ·
    nothing
15. **Gym log in one message.** "squat 3x5 100" logged against the plan,
    with last time beside it. · typed after a set · 5 · L · the gym plan
    (the inbox keeps a CSV's rows already)
16. **Last checkup.** When his last dentist, eye test or blood test was,
    with a suggested next one (asked, never pushed). · "when was my last
    eye test?" · 3 · S · the dates once
17. **Notes for the doctor.** Symptoms noted in words become a short dated
    summary to show a GP. · "headache again today" → kept privately ·
    3 · M · nothing
18. **Sleep in the diary.** "slept badly" kept with the day's mood, a
    pattern in the week's summary. · seen on Sunday · 2 · S · nothing

## Money

19. **Subscriptions from a bank CSV.** Recurring charges found, each with
    its renewal day and the monthly total. · bank CSV in #inbox → card ·
    5 · M · a CSV export now and then
20. **Month of spending.** Categories and the top five from the same CSV,
    in NZ$. · "how did I spend in October?" · 4 · M · the CSV
21. **Freelance invoices.** "invoice Acme 6 hours at 80" makes the record,
    its due day and one reminder to chase. · card → Save · 5 · M · his
    rates, a client list
22. **Payday card.** On payday, what is due before the next one. · seen on
    payday · 4 · M · his pay day
23. **Flat expenses.** "I paid the power 180, split three ways" keeps who
    owes whom. · "who owes me?" · 5 · M · flatmates' first names
24. **Tax-time folder.** Freelance income and expenses tagged for the
    year's return (IR3). · "tax summary for this year" · 4 · M · nothing
    new once invoices exist

## Home and flat

25. **Bin day.** Rubbish and recycling on their own weeks, one reminder
    the evening before. · "bins Tuesday, recycling every other week" ·
    4 · S · nothing
26. **The usual.** "the usual" adds his staples to the shopping to-dos. ·
    "need the usual and eggs" · 4 · S · a list once
27. **Chores rota.** The flat's weekly rota, his part on the Today card. ·
    "whose week is bathrooms?" · 3 · M · flatmates and chores
28. **Meals for the week.** A short plan from what he likes, and its
    shopping. · "plan 4 dinners" · 3 · M · a few meals he likes
29. **Lease and rent.** Lease end, inspections and rent rises as dates. ·
    a lease PDF → expiry card · 3 · S · nothing
30. **Deliveries.** An order confirmation screenshot becomes the day it
    arrives. · screenshot → "parcel due Wed" · 3 · S · nothing
31. **Yearly house jobs.** Smoke alarm test, filter change, once a year.
    · "smoke alarm test every March" · 2 · S · nothing

## Work and freelance

32. **Hours by message.** "2h on the Acme site" logs time; the week's
    hours by client on Sunday. · typed when done · 5 · S · client names
33. **Client board.** Each client's next deliverable and hours this month,
    one card. · "clients" · 5 · M · the clients once
34. **Client renewals.** Domains and hosting he manages for clients, as
    expiries with the client's name. · "Acme domain expires 3 March" ·
    4 · S · nothing
35. **Quote drafts.** A quote drafted from past ones. · "quote for a
    5-page site" · 3 · M · two or three past quotes
36. **Meeting prep.** Before an event, the to-dos he tagged for it. ·
    "for standup: ask about the release" · 3 · M · nothing
37. **Shutdown line.** At his finish time, tomorrow's first meeting and
    what is open. · seen, not asked · 3 · S · his finish time

## People and social

38. **Birthdays.** A week before, one line, with his gift notes for that
    person. · "Sam's birthday 3 May" · 4 · S · the dates once
39. **Keep in touch.** A soft line in the week's summary for people he
    said he wants to keep up with. · "keep in touch with Mum weekly" · 3 ·
    S · the names
40. **Gift notes.** Ideas kept per person, shown with the birthday. · "gift
    idea for Sam: a book on climbing" · 2 · S · nothing
41. **Plans with friends.** "dinner with Sam Friday?" makes the event and
    drafts the message to send. · card → Save, text to copy · 3 · S ·
    nothing

## Learning

42. **Saved for later, read later.** The daily read's saved articles, one
    short digest on Sunday. · seen on Sunday · 3 · S · nothing
43. **Study blocks.** "block 2 hours Sunday for study" on the Bot calendar
    (time set aside, never a deadline list). · card → Save · 3 · S ·
    nothing
44. **One recall question.** One question a week from what he read, to
    keep it. · answered in words · 2 · M · nothing

## Fun

45. **Weekend ideas.** Free Saturday afternoon and sunny: two ideas from
    his own list. · "what should I do Saturday?" · 3 · M · a list of
    things he enjoys
46. **Watchlist.** Films and shows to watch; one picked for tonight. ·
    "add Made-up Film to watch", "pick one" · 3 · S · nothing
47. **Month in review.** Moods, gym, streaks and highlights of the month,
    one card. · on the 1st · 3 · M · nothing
48. **Personal bests.** One small line when a lift beats his best. · seen
    after the log · 3 · S · the gym log

## The top 10, by value for effort

Picked for value of 4 or 5 with the least effort: posted in the design
forum as "Design · Brainstorm", one reply each with a two-line sketch.

| # | Idea | Value | Effort |
|---|------|-------|--------|
| 32 | Hours by message | 5 | S |
| 1 | Plan my day | 4 | S |
| 2 | Free time finder | 4 | S |
| 25 | Bin day | 4 | S |
| 38 | Birthdays | 4 | S |
| 26 | The usual | 4 | S |
| 9 | Draft the email | 4 | S |
| 13 | Pill refill countdown | 5 | M |
| 23 | Flat expenses | 5 | M |
| 19 | Subscriptions from a bank CSV | 5 | M |

## The wishlist

Live keeps a wish, silently, each time it could not do what he asked: a
decline ("I can't do that yet"), a message not understood, a report no
task keeps ("I can't log that yet"), or a correction straight after a
change (a misread). Each wish is a date, the task (or none) and why, in
the code's own words: never his message, so no pill, event or diary word
is ever in one. He can add one himself: "add to my wishlist: …". The
week's summary shows the count in one small line. `/suggest` folds them
into the next brainstorm.
