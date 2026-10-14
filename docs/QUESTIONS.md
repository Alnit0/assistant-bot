# Questions for Alex

One list, most important first, grouped by what each unblocks. Each can
be answered in a line, and each has a suggestion (→). Reply like:
"yes to all suggestions except 4 and 7", then a line for each
exception.

Gathered 2026-10-14 from `docs/STATUS.md`, the specs, the QA sheet and
"Decided overnight". Questions already answered are gone. New ones are
added here, nowhere else.

## The new hub tasks (2026-10-15)

Built and switched off in live: to-dos (`TODOS_ENABLED`), reminders you
set yourself (`NUDGES_ENABLED`) and personal routines (`HABITS_ENABLED`).
They were built to your defaults; these are what the build had to decide.
The cards are in the "New hub tasks preview" in the design-options post.

**To-dos**

51. A to-do with no day said is for any day: on the card every day until
    done, not "today" with ❓. → Keep.
52. An overdue to-do keeps its day ("from Tue 13 Oct") and stays at the
    top, amber, until done or moved; it is never moved on by itself. →
    Keep.
53. The same words twice: the second is not added, and the card says
    the one there is. → Keep.
54. Ticking off by words is done at once, as a pill taken is, with
    "undo that"; no card. → Keep.
55. The card lists twelve and counts the rest; to-dos for a later day
    are one small line ("1 more later, next Sat 17 Oct"). → Keep.

**Reminders**

56. The switch is `NUDGES_ENABLED` and the code's folder `tasks/nudges`,
    as `REMINDERS_ENABLED` is the pills' own. You only ever read
    "Reminders". → Keep.
57. A time with no day: today if it is still to come, otherwise
    tomorrow, marked ❓. → Keep.
58. What the lock screen shows is "⏰ Reminder · 5:00 pm", the words in
    the box under it, as for a pill. These are not private like a pill:
    show the words on the lock screen? → Keep neutral.
59. Done and Snooze take it out of the hub at once; one left alone goes
    at the next morning's tidy. → Keep.
60. Snooze offers 10 minutes, 1 hour and tomorrow at the same time. →
    Keep.

**Personal routines**

61. The switch is `HABITS_ENABLED` and the folder `tasks/habits`, so
    "routine" in the code stays the scheduler's; the word to see them is
    `my routines`. → Keep.
62. At most twelve steps a routine; what is ticked starts again at
    midnight. → Keep.
63. The card has one button a routine, for its next step; a step out of
    order is ticked by words ("did journal"). A button for every step
    instead? → Keep one: fewer buttons.

**All three**

64. The new cards have no page title (`##`): the box's card title says
    it ("### 📝 To-dos ●○ 1/2"), where the pills card has "💊 Today · Thu
    15 Oct" above its box. The same as pills, or as built? → As built,
    and the pills card the same once you have looked.
65. A card that has nothing in the morning and something later (the
    first to-do added at 2 pm) is posted then, at the bottom of the hub,
    until the next morning puts it in order. → Keep.
66. Which to switch on first? → To-dos, then personal routines, then
    reminders (the most moving parts).

## The last-chance nudge (2026-10-14)

43. The last-chance nudge for a pill with no latest time comes at
    11:30 pm, with sound, as every pill reminder gets through quiet
    hours. → Keep (it is the last moment the dose can be taken).
44. For a pill with a gap, "stops fitting the day" is taken as the
    first dose still to come that would no longer fit: for three
    doses three hours apart with no latest time, dose 1's last chance
    is at 5:30 pm ("take by 6:00 pm"), not at 11:30 pm. → Keep.

## The day's total as dots, and round 3 (2026-10-14)

45. The dots of the day's total: in the briefing's title ("## ☀️
    Today ●●●●●○○ 5/7", R3-A, as built) or as a line of normal text
    under the date (R3-B)? Both are in the design-options post. →
    The title, if it does not wrap on your phone with ten dots.
46. The old-look checklist's title still has its ▰▱ bar ("💊 Pills ·
    ▰▰▱▱▱ 2 of 5"). Dots there too, now? → No: it goes with the old
    look when `CARDS_V2` is on.

47. Round 3's type scale (one box a topic, `##` page title, `###` card
    title with dots, bold items, times in bold with a relative time,
    done collapsed to one small line): five sketches are in the
    design-options post. Build it as sketched? → Say what to change
    first; `docs/DESIGN.md` lists five things the sketches had to
    decide.
48. In that scale, with the date in the page title, the day's total
    is a line of its own under it (not in the title). → Yes: it
    settles 45 as R3-B if you pick the scale.

## From the week's messages (2026-10-14)

49. When what you say contradicts itself (three times given, "3 hours
    apart", and two of them 2½ hours apart), the card moves the later
    time and says so with ⚠️. The standard also says to ask when
    what you said contradicts itself. Keep the fix with a warning,
    or ask on the card which you meant? → Keep: it is one tap to
    accept and one line to correct.
50. Timers: "give tea more time" with two timers called tea changed
    both, and "give it 2 more" is marked as a guess though you said
    2. Both are known, and timers are frozen. → Leave until timers
    are kept or scrapped.

## Reminders and what reaches you

1. Something that goes wrong between 10:00 pm and 7:00 am posts
   nothing until one ping at 7:00 am. → Keep.
2. That 7:00 am ping repeats each morning while the "Needs a look"
   box is not empty. → Keep.
3. Dev mode left on, and the self-test's month being spent, are
   shown but never ping. → Keep.
4. Turn on the Sunday 7:00 pm weekly pills summary
   (`WEEKLY_SUMMARY`)? → Yes.
5. Turn on direct messages to the bot (`DMS_ENABLED`)? → Yes, after
   you have run QA block 54 once.
6. Phone alerts through ntfy stay off until you add
   `NTFY_BOT_TOPIC`. When on, pill reminders go to Discord and ntfy
   both. → Keep it so.
7. A dose of last night with no time said is proposed at its planned
   time, or 11:59 pm for a pill with no time. → Keep.
8. "No, 7pm" straight after Save corrects what was saved, for pills
   only. Do the same for schedules? → Yes, later (backlog).
9. A restart counts as unexpected only if the PC restarted or the bot
   crashed. A kill from Task Manager reads as planned. → Accept.
10. The "🟢 Bot started" card is gone with "Online and ready" (a card
    only if a task could not start). → Keep.
11. One check only you can do: what does your lock screen show for a
    pill reminder? → Tell me the exact words once.

## Design

12. Round 1: I only know "keep the rule between items" and "the thin
    question card". Which letter for the **checklist** and the
    **reminder**? → Tell me, or say "as round 2 shows".
13. Titles `##`, each item `###`, details small, a rule between items,
    for the briefing, the checklist and the confirm card (R2-A of
    each). → Yes.
14. A change written ~~old~~ → **new**, not in code blocks. → Yes.
15. The thin question card, also when two are stacked. → Yes.
21. Turn the new look on (`CARDS_V2`) once 13 to 18 are built? → Yes.
22. Cards not yet in the new look: a bug's forum post, the archived
    copy, the dev panel, #commands and `help`. → Leave all four.

## Gym (the six that a first build needs; 16 more are in its spec)

23. Kilograms for everything? → Yes.
24. The plan comes as a `.csv` file? → Yes.
25. Which workout is due: the next in turn after the last you did,
    not fixed weekdays? → Next in turn.
26. Today's workout is posted in the hub? → Yes.
27. Posted only when you ask, not by itself in the morning? → Only
    when asked, to begin with.
28. You log a whole exercise at once ("bench 60 for 10, 9, 8"), not
    set by set? → Whole exercise.

## Calendar (nothing is built; these four unblock stage 1)

29. Which calendar? → Google.
30. Read only to begin with? → Yes.
31. Let in by the calendar's private read-only link (nothing to sign
    in to, a little behind), not by signing in? → The link.
32. May event titles be given to Claude so "move the dentist" is
    understood? → No: matched by code after.

## Other

33. Merge `feature/pills` into `main` once you have read
    `docs/REVIEW.md` and run QA blocks 53 to 55? → Yes.
34. Then give live its own folder on `main` (the script is written)?
    → Yes.
35. Weather is for Auckland, fetched at 5:50 am and refreshed every
    3 hours to 8:00 pm. → Keep.
36. A failed exchange-rate fetch is not an alert (the last rate is
    used). → Keep.
37. The nightly self-test and the nightly backup both start at
    3:00 am. Move the self-test to 3:30 am? → Yes.
38. A watch on live itself: a Windows scheduled task that pings your
    phone if the service is down, rather than the dev bot always on?
    → The scheduled task, later.
39. Two golden conversations failed once just after midnight and
    passed minutes later. Chase it? → Yes, it is small.
40. Spend about NZ$0.70 on one live eval to shorten the router's
    rules (the cost audit's last open item)? → Not now.
41. #commands says Taken and Skip are "under today's checklist"; in
    the new look they are in the pill's own box. Reword when
    `CARDS_V2` goes on? → Yes.
42. Mornings as built: the same time at weekends, no briefing on a
    morning with nothing in it, yesterday's line as counts only, no
    buttons in the briefing. → Keep all four.
