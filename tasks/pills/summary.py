from datetime import date, timedelta

from core import design, occurrences, timeinput
from core.actions import Summary
from core.occurrences import DONE, MISSED, SKIPPED
from tasks.pills import checklist, history, sheet, today
from tasks.pills.today import TASK, Dose

# ---------------------------------------------------------------------------
# Pills, in a few lines, for whatever shows summaries (the briefing). Written
# from what the checklist itself works out, so the two can never disagree.
# It only reads: no row is made or changed here (`checklist.read`). Today's
# rows are made at the end of the day before, and yesterday is closed then.
# ---------------------------------------------------------------------------


def status(listed: list[Dose]) -> str:
    """The colour of the whole section: that of what is still to do. A dose
    with a time comes before one with none; red only when a dose was missed
    and nothing is left."""
    pending = [dose for dose in listed if dose.is_pending]
    if any(not dose.is_untimed for dose in pending):
        return design.DUE
    if pending:
        return design.ANY_TIME
    states = {dose.occurrence.state for dose in listed}
    if MISSED in states:
        return design.MISSED
    return design.DONE if DONE in states else design.QUIET


def next_line(listed: list[Dose]) -> str:
    """The next dose with a time: "**Next:** Pill A, dose 2 · `12:00 pm`"."""
    timed = [(today.shown_time(dose), dose) for dose in listed if dose.is_pending and today.shown_time(dose) is not None]
    if not timed:
        return ""
    at, dose = min(timed, key=lambda each: each[0])
    which = f"{dose.pill.plan.name}, dose {dose.number}" if dose.of > 1 else dose.pill.plan.name
    return f"**Next:** {which} · `{timeinput.format_moment(at)}`"


def any_time(listed: list[Dose]) -> str:
    count = sum(1 for dose in listed if dose.is_pending and dose.is_untimed)
    return f"{count} to take any time" if count else ""


def yesterday(found: list) -> str:
    """Yesterday in one line, from the occurrence log: what was taken of what
    was mine to take, and what was missed. A dose the bot set aside (no longer
    in the plan, no room left) is not counted against me, as for a streak."""
    mine = [each for each in found if not (each.state == SKIPPED and each.automatic)]
    if not mine:
        return ""
    taken = sum(each.state == DONE for each in mine)
    missed = sum(each.state == MISSED for each in mine)
    skipped = sum(each.state == SKIPPED for each in mine)
    parts = [f"Yesterday: {taken} of {len(mine)} taken"]
    if missed:
        parts.append(f"{missed} missed")
    if skipped:
        parts.append(f"{skipped} skipped")
    return " · ".join(parts)


async def summary(user_id: int, day: date) -> Summary | None:
    """Today's pills in a few lines, or None with nothing to take today."""
    _, listed, _ = await checklist.read(user_id, day)
    if not listed:
        return None
    before = yesterday(await occurrences.for_day(user_id, TASK, day - timedelta(days=1)))
    glance = sheet.title(listed).partition(" · ")[2]  # the checklist's own count: "2 of 6 taken"
    # The streak, in days, one for all pills: said from two days up (tasks/pills/history.py)
    streak = history.streak_line(await history.streak_days(user_id, day))
    lines = tuple(line for line in (next_line(listed), streak) if line)
    # The checklist's own count of what is dealt with (taken or skipped), so the two never disagree
    done, total = today.progress(listed)
    return Summary(glance=glance, status=status(listed), lines=lines, hint=any_time(listed), before=before, done=done, total=total)
