from datetime import date, datetime

from core import design, timeinput
from core.occurrences import DONE, MISSED
from tasks.pills import rules, today
from tasks.pills.rules import PAUSED, Pill
from tasks.pills.sheet import MARKS, NOTHING, _groups, _which, row, status, title
from tasks.pills.today import Dose

# ---------------------------------------------------------------------------
# Pills: today's checklist in round 1 of the design (docs/DESIGN-LOG.md), as it
# was built before round 3: a box a pill in the colour of what is still to do,
# with the buttons of its next dose inside the box, and Paused in a section of
# its own. Drawn only with CARDS_V2 on and DESIGN_ROUND=1; kept as it was so
# "go back to round 1" is a setting. Pure. tasks/pills/sheet.py is round 3.
# ---------------------------------------------------------------------------


def _happened(dose: Dose) -> str:
    """What has happened to a dose that is no longer waiting, in a line."""
    state = dose.occurrence.state
    if state == DONE:
        at = dose.occurrence.actual_at
        return f"✅ {_which(dose)}{timeinput.format_moment(at)}" if at else f"✅ {_which(dose)}taken"
    if state == MISSED:
        due = today.shown_time(dose)
        return f"❌ {_which(dose)}missed" + (f" · was due {timeinput.format_moment(due)}" if due else "")
    if dose.occurrence.automatic and dose.occurrence.reason:
        return design.small(f"⏭️ {_which(dose)}skipped by the bot: {dose.occurrence.reason}")
    return f"⏭️ {_which(dose)}skipped"


def _next(dose: Dose) -> str:
    """The dose that is next, in a line. Nothing for one with no time: its box says "any time"."""
    when = today.shown_time(dose)
    if when is not None:
        shown = f"`{timeinput.format_moment(when)}`"
        return f"**Next:** dose {dose.number} · {shown}" if dose.of > 1 else f"Due {shown}"
    if dose.is_untimed:
        return ""
    return f"**Next:** dose {dose.number} · after dose {dose.number - 1}" if dose.number > 1 else ""


def box(doses: list[Dose], now: datetime, with_buttons: bool = True) -> design.Box:
    """One pill's box: its name and a mark a dose, its note, what has happened,
    what is next, a take-by warning, and the buttons of its next dose."""
    from tasks.pills import reminders  # it imports the checklist, which this module is used by

    pill = doses[0].pill
    waiting = next((dose for dose in doses if dose.is_pending), None)
    name = f"**{pill.plan.name}** · {''.join(MARKS[dose.occurrence.state] for dose in doses)}"
    if waiting is not None and waiting.is_untimed:
        name += " · any time"
    lines = [design.small(pill.plan.notes) if pill.plan.notes else ""]
    lines += [_happened(dose) for dose in doses if not dose.is_pending]
    if waiting is not None:
        lines += [_next(waiting), reminders._take_by(waiting, now) or ""]
    return design.item(status(doses), name, *lines, row=row(waiting) if waiting is not None and with_buttons else ())


def _paused(pills: list[Pill], day: date) -> list[design.Box]:
    paused = sorted((pill for pill in pills if rules.status_on(pill, day) == PAUSED), key=lambda pill: pill.plan.name.lower())
    if not paused:
        return []
    lines = [
        design.small(pill.plan.name + (f" · until {timeinput.format_date(pill.paused_until)}" if pill.paused_until else ""))
        for pill in paused
    ]
    return [design.item(design.QUIET, "⏸️ **Paused**", *lines)]


def _not_today(pills: list[Pill], day: date) -> list[design.Box]:
    """The pills that are not taken on this day of the week, with their days."""
    off = today.not_today(pills, day)
    if not off:
        return []
    return [design.item(design.QUIET, "🗓️ **Not today**", *(design.small(f"{pill.plan.name} · {rules.days_text(pill.plan.schedule.days)}") for pill in off))]


def _folded(groups: list[list[Dose]], limit: int) -> design.Box:
    """Pills with nothing left to do today, as one box of lines. Never drops
    one without saying how many more there are."""
    lines = [today.line(dose) for doses in groups for dose in doses]
    shown, used = [], 0
    for line in lines:
        if used + len(line) + 1 > limit:
            break
        shown.append(line)
        used += len(line) + 1
    if len(shown) < len(lines):
        shown.append(design.small(f"and {len(lines) - len(shown)} more"))
    return design.item(design.QUIET, "**Dealt with**", *shown)


def layout(listed: list[Dose], pills: list[Pill], day: date, now: datetime) -> tuple:
    """Today's checklist as a layout that fits one message. When it would not
    fit, buttons go first (only the next dose due keeps them), then the pills
    with nothing left to do are folded into one box of lines."""
    groups = _groups(listed)
    context = f"{day:%A} {day.day} {day:%B}"
    later = [*_paused(pills, day), *_not_today(pills, day)]

    def built(buttons_on: set[int], folded: bool) -> tuple:
        open_, closed = [], []
        for doses in groups:
            (open_ if any(dose.is_pending for dose in doses) or not folded else closed).append(doses)
        boxes = [box(doses, now, doses[0].pill.id in buttons_on) for doses in open_]
        if closed:
            boxes.append(_folded(closed, design.MAX_TEXT // 2))
        if not boxes:
            boxes = [design.Text(NOTHING)]
        return design.standing(title(listed), context, boxes, later)

    everyone = {doses[0].pill.id for doses in groups}
    pending = sorted(
        (dose for dose in listed if dose.is_pending),
        key=lambda dose: (dose.due.at is None, dose.due.at.timestamp() if dose.due.at else 0, dose.pill.plan.name.lower()),
    )
    first = {pending[0].pill.id} if pending else set()
    for buttons_on, folded in ((everyone, False), (first, False), (first, True), (set(), True)):
        pieces = built(buttons_on, folded)
        if not design.problem(pieces):
            return pieces
    # More pills still to take than one message has room for: a line each, and how many more
    waiting = [today.line(dose) for dose in pending]
    room = (design.MAX_TEXT // 2) // max(len(line) + 1 for line in waiting)
    lines = waiting[:room] + ([design.small(f"and {len(waiting) - room} more")] if len(waiting) > room else [])
    done = [doses for doses in groups if not any(dose.is_pending for dose in doses)]
    boxes = [design.item(design.DUE, "**Still to take**", *lines)] + ([_folded(done, design.MAX_TEXT // 4)] if done else [])
    return design.standing(title(listed), context, boxes, later)
