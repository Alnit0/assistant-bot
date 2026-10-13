from datetime import datetime

from core import attention, config
from core import day as days
from core.attention import TIMED, USEFUL, Item
from core.occurrences import DONE, MISSED
from tasks.pills import checklist, today

# ---------------------------------------------------------------------------
# Pills' attention items (core/attention.py): what about today's doses may
# deserve a look now. Written from what the checklist itself works out, read
# only (`checklist.read`), and never with a pill's name in what the status
# line shows.
#
#   a dose with a time that has come and is not ticked off   timed   💊 due 12pm
#   the next dose with a time, later today                    timed   💊 2/5 · 12pm
#   only doses with no time are left                          useful  💊 2/5
#   a dose was missed, and none is due now                    timed   💊 missed 9am
#   everything is taken (until the evening, a setting)        useful  💊 all 5 taken
#   everything is dealt with, some of it skipped (the same)   useful  💊 4/5 · 1 skipped
#   after that, or with nothing to take                       nothing
#
# Whether a timed one is "due" or "next" is the core's to say, from its time.
# A missed dose is shown at its own time, so it stands with what is due: until
# the next dose falls due (that one is then what to look at) or the day ends.
# ---------------------------------------------------------------------------
DUE_WORD, MISSED_WORD = "due", "missed"


async def items(user_id: int, now: datetime) -> list[Item]:
    day = days.day_of(now)
    _, listed, _ = await checklist.read(user_id, day)
    if not listed:
        return []
    pending = [dose for dose in listed if dose.is_pending]
    taken = sum(dose.occurrence.state == DONE for dose in listed)
    progress = f"{taken}/{len(listed)}"
    missed = sorted(moment for dose in listed if dose.occurrence.state == MISSED and (moment := dose.due.at or dose.occurrence.due_at) is not None and moment <= now)
    if not pending:
        if missed:
            return [Item("a dose was missed", TIMED, when=missed[-1], can_act=True, short=(f"{MISSED_WORD} {attention.short_time(missed[-1])}",))]
        # The day is done: said until the evening, and then the line looks ahead
        skipped = len(listed) - taken
        said = (f"all {len(listed)} taken",) if not skipped else (progress, f"{skipped} skipped")
        return [Item("everything is dealt with", USEFUL, short=said, until=days.at(day, config.STATUS_DONE_UNTIL))]
    timed = sorted(((moment, dose) for dose in pending if (moment := today.shown_time(dose)) is not None), key=lambda each: each[0])
    found = []
    overdue = [moment for moment, _ in timed if moment <= now]
    coming = [moment for moment, _ in timed if moment > now]
    if overdue:
        # The earliest one whose time has come: what to do now
        found.append(Item("a dose is due", TIMED, when=overdue[0], can_act=True, short=(f"{DUE_WORD} {attention.short_time(overdue[0])}",)))
    elif missed:
        # Nothing is due now: the dose that was missed is what to know, until the next one falls due
        found.append(Item("a dose was missed", TIMED, when=missed[-1], can_act=True, short=(f"{MISSED_WORD} {attention.short_time(missed[-1])}",)))
    if coming:
        found.append(Item("the next dose", TIMED, when=coming[0], can_act=True, short=(progress, attention.short_time(coming[0]))))
    if not timed:
        found.append(Item("doses to take any time", USEFUL, can_act=True, short=(progress,)))
    return found
