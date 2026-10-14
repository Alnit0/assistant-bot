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

68. An overdue routine (its window closed undone, with a nudge): the
    brief says level 2 and Needs a look, but the Needs a look box holds
    level 1 (problems) only. → Keep it level 2: it shows in the status
    line and on the Today card, and the box stays for things that are
    wrong. Or make it a problem that pings nothing, so it is in the box.
    (Built on `feature/routines`; see the Routines layout preview.)
69. Routines: Layout A (one Personal routines card) or Layout B (the
    Today card as the overview, and a card a routine from its time until
    it is done)? Both are in the "Routines layout preview" post of the
    Design forum. → B: the Today card already gives the overview, and a
    routine's own card is there only while it matters. Also: your
    message was cut off at "Also show the Today card with a…": what was
    the rest?

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
