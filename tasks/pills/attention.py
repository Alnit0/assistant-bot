from datetime import datetime

from core import attention
from core import day as days
from core.attention import TIMED, USEFUL, Item
from core.occurrences import DONE
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
#   everything is dealt with                                  nothing
#
# Whether a timed one is "due" or "next" is the core's to say, from its time.
# A missed dose is the day's record, not a problem to raise.
# ---------------------------------------------------------------------------
DUE_WORD = "due"


async def items(user_id: int, now: datetime) -> list[Item]:
    _, listed, _ = await checklist.read(user_id, days.day_of(now))
    pending = [dose for dose in listed if dose.is_pending]
    if not pending:
        return []
    progress = f"{sum(dose.occurrence.state == DONE for dose in listed)}/{len(listed)}"
    timed = sorted(((moment, dose) for dose in pending if (moment := today.shown_time(dose)) is not None), key=lambda each: each[0])
    found = []
    overdue = [moment for moment, _ in timed if moment <= now]
    coming = [moment for moment, _ in timed if moment > now]
    if overdue:
        # The earliest one whose time has come: what to do now
        found.append(Item("a dose is due", TIMED, when=overdue[0], can_act=True, short=(f"{DUE_WORD} {attention.short_time(overdue[0])}",)))
    if coming:
        found.append(Item("the next dose", TIMED, when=coming[0], can_act=True, short=(progress, attention.short_time(coming[0]))))
    if not timed:
        found.append(Item("doses to take any time", USEFUL, can_act=True, short=(progress,)))
    return found
