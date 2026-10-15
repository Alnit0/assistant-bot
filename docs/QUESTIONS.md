# Questions for Alex

One list, most important first, grouped by what each unblocks. Each can
be answered in a line, and each has a suggestion (→). Reply like:
"yes to all suggestions except 4 and 7", then a line for each
exception.

Answered on 2026-10-15: every answer is a line under "Decided" in
`docs/STATUS.md`, and the question is gone from here. New ones are
added here, nowhere else.

## Open

11. One check only you can do: what does your lock screen show for a
    pill reminder? → Tell me the exact words once (a screenshot is on
    its way).

## The hub through a day (from the replay of 15 Oct, `python -m selftest.day`)

The post "Design · A day in the hub" in the Design forum shows each of
these at its moment. The clear bugs it found are fixed; these are
choices.

68. When a routine's window opens mid-day, its card is posted at the
    bottom of the hub, under the to-dos card and any lines of the
    moment: the fixed order (pills, reminders, routines, to-dos) breaks
    twice a day. → When a task card comes up after the morning, the
    cards that belong under it (to-dos) are posted again under it, so
    the order holds; the to-dos card jumps down once each time.
69. Two "Today" counts sit side by side and disagree: the briefing's
    "☀️ Today ●●●○… 5/18" and the Today card's "📅 Today ●●○○ 2/8"
    (they count different things). → The Today card loses its count;
    the briefing's is the day's.
70. The same thing is listed in full in three places: an overdue to-do
    in the briefing's to-dos box, the Today card and the to-dos card; a
    reminder in the briefing, the Today card and the reminders card. →
    With the Today card on, the briefing's boxes keep a count and the
    next thing only, and the Today card lists what has a time and the
    routines; to-dos stay on their own card.
71. A routine whose window closed undone (the evening one, "Read" left
    at 11 pm) keeps its card and dropdown until midnight, and the Today
    card says "not done yet". → Keep it until the morning tidy (it can
    still be ticked), its box amber; no nudge unless one was asked for.
72. The briefing's boxes change places through the day (at 6 am
    Reminders then Calendar, at noon Calendar then Reminders), because
    they follow the ranking. → A fixed order, as the task cards have:
    Needs a look, weather, pills, reminders, routines, calendar, to-dos.
73. A plain "I can't find that" in the hub ("⚠️ There is no to-do
    “power bill” on your list.") stays all day with your message, as a
    real failure does. → It goes 2 minutes after, like any answer; only
    a failure of the bot's own keeps its ⚠️ until the morning.
74. The reminders card goes once nothing is left to come, but the
    to-dos card stays when all are done (green, "✅ 3 done"). → The same
    for both: it stays with its "✅ N done" line until the morning tidy,
    as you chose for to-dos.
75. A missed dose holds the status line from when it is missed to
    midnight ("💊 missed 3:10pm" from 5 pm on, but for the hour Pill C
    was due), as built. → It stays until the evening, as "all taken"
    does (`STATUS_DONE_UNTIL`), then the line looks ahead; the checklist
    and the briefing keep saying it.

## Personal routines, to discuss (`HABITS_ENABLED` stays off)

63. You want personal routines reworked. The idea: steps can be grouped
    (a skincare group of four steps, say); the card shows every step,
    but a group has one button that ticks the whole group, and a step
    on its own keeps a button of its own. Things to settle: can a step
    in a group still be ticked by words on its own; does a group have
    dots of its own or count as its steps; are groups named in the
    routine ("morning: stretch, water, skincare (cleanse, tone,
    moisturise)"). → Talk it through first; nothing changes in the
    code until then.

## Gym onboarding, to design first (nothing of gym is built)

You want to design how a plan gets set up before anything is built:
how the plan comes in, the steps of setting it up, what is asked and
what is guessed. These stay open until then (23 is settled:
kilograms for everything).

24. The plan comes as a `.csv` file? → Yes.
25. Which workout is due: the next in turn after the last you did,
    not fixed weekdays? → Next in turn.
26. Today's workout is posted in the hub? → Yes.
27. Posted only when you ask, not by itself in the morning? → Only
    when asked, to begin with.
28. You log a whole exercise at once ("bench 60 for 10, 9, 8"), not
    set by set? → Whole exercise.
