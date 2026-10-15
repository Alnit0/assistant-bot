from dataclasses import dataclass
from datetime import date, datetime, time

from core import hub, schedule, timeinput
from core.occurrences import DONE, MISSED, PENDING, SKIPPED, Occurrence
from core.schedule import ANY_TIME, OPEN, OUT, WAITING, Due
from tasks.pills import rules
from tasks.pills.rules import PAUSED, Pill

# ---------------------------------------------------------------------------
# Pills: today. What is to be taken on a day, in what order, and the checklist
# as it is written. Pure: the pills, the day's occurrences and the time come
# in; no database, no Discord.
#
# A dose is one occurrence (core/occurrences.py) of a pill on a day. The plan
# says how many there are and their planned times; when each is due today is
# worked out every time from the plan and what was taken (core/schedule.py),
# never stored as the truth.
# ---------------------------------------------------------------------------
TASK = "pills"


@dataclass(frozen=True)
class Dose:
    pill: Pill
    occurrence: Occurrence
    due: Due  # when it is due today, and why

    @property
    def number(self) -> int:
        return self.occurrence.seq

    @property
    def of(self) -> int:
        return self.pill.plan.schedule.per_day

    @property
    def is_pending(self) -> bool:
        return self.occurrence.state == PENDING

    @property
    def is_untimed(self) -> bool:
        """No time today and nothing to wait for: it has its own Taken / Skip message."""
        return self.due.why == ANY_TIME

    @property
    def label(self) -> str:
        """ "**Course A** (dose 2 of 3)"; a pill taken once a day is just its name."""
        return f"**{self.pill.plan.name}**" + (f" (dose {self.number} of {self.of})" if self.of > 1 else "")


def wanted(pill: Pill, day: date) -> list[tuple[int, time | None]]:
    """The doses a pill should have on a day: (which, its planned time). None if
    it isn't taken that day (paused, not started, ended, removed)."""
    if not rules.is_taken_on(pill, day):
        return []
    plan = pill.plan.schedule
    return [(index + 1, plan.planned(index)) for index in range(plan.per_day)]


def doses(pills: list[Pill], found: list[Occurrence], day: date) -> list[Dose]:
    """The day's doses in the order the checklist shows them: those with no
    time first (by name), then the timed ones by when they are due today."""
    by_pill: dict[int, dict[int, Occurrence]] = {}
    for occurrence in found:
        by_pill.setdefault(occurrence.item_id, {})[occurrence.seq] = occurrence
    listed: list[Dose] = []
    for pill in pills:
        mine = by_pill.get(pill.id, {})
        if not rules.is_taken_on(pill, day) or not mine:
            continue
        plan = pill.plan.schedule
        so_far = []
        for index in range(plan.per_day):
            occurrence = mine.get(index + 1)
            if occurrence is None or occurrence.state == PENDING:
                so_far.append(OPEN)
            else:
                so_far.append(occurrence.actual_at if occurrence.state == DONE and occurrence.actual_at else OUT)
        due = schedule.dues(plan, day, so_far)
        listed += [Dose(pill, mine[index + 1], due[index]) for index in range(plan.per_day) if index + 1 in mine]

    def order(dose: Dose):
        if dose.due.at is None:
            return (0, dose.pill.plan.name.lower(), dose.number, 0)
        return (1, "", 0, dose.due.at.timestamp())

    return sorted(listed, key=order)


def next_pending(listed: list[Dose], pill_id: int) -> Dose | None:
    """The pill's next dose still to take today."""
    mine = sorted((dose for dose in listed if dose.pill.id == pill_id and dose.is_pending), key=lambda dose: dose.number)
    return mine[0] if mine else None


def next_to_log(listed: list[Dose], pill_id: int) -> Dose | None:
    """The dose that "I took it" is about: the next one still to take, or, when
    the bot has closed what was left (missed, or skipped for want of time),
    the first of those. Taking a dose late is still taking it."""
    mine = sorted((dose for dose in listed if dose.pill.id == pill_id), key=lambda dose: dose.number)
    closed = [dose for dose in mine if dose.occurrence.state in (MISSED, SKIPPED) and dose.occurrence.automatic]
    return next_pending(listed, pill_id) or (closed[0] if closed else None)


def before(listed: list[Dose], dose: Dose) -> Dose | None:
    """The dose of the same pill taken just before this one, if any."""
    earlier = [each for each in listed if each.pill.id == dose.pill.id and each.number < dose.number and each.occurrence.state == DONE]
    return max(earlier, key=lambda each: each.number) if earlier else None


def shown_time(dose: Dose) -> datetime | None:
    """When a dose still to take is shown as due: never a time past the day's
    limit, which nobody could act on."""
    if dose.due.at is None or dose.due.at > schedule.limit(dose.pill.plan.schedule, dose.occurrence.day):
        return None
    return dose.due.at


def last_dealt_with(listed: list[Dose], pill_id: int) -> Dose | None:
    """The pill's latest dose that was taken or skipped today by the user: what
    "undo that" or "I didn't take it" puts back. A skip by the bot is left."""
    mine = sorted(
        (dose for dose in listed if dose.pill.id == pill_id and (dose.occurrence.state == DONE or (dose.occurrence.state == SKIPPED and not dose.occurrence.automatic))),
        key=lambda dose: dose.number,
    )
    return mine[-1] if mine else None


def last_taken(listed: list[Dose], pill_id: int) -> Dose | None:
    """The pill's latest dose that was taken today."""
    mine = sorted((dose for dose in listed if dose.pill.id == pill_id and dose.occurrence.state == DONE), key=lambda dose: dose.number)
    return mine[-1] if mine else None


# ---------------------------------------------------------------------------
# In words
# ---------------------------------------------------------------------------
def _notes(dose: Dose) -> list[str]:
    return [f"*{dose.pill.plan.notes}*"] if dose.pill.plan.notes else []


def line(dose: Dose) -> str:
    """One dose on the checklist."""
    state = dose.occurrence.state
    if state == DONE:
        taken = f"taken {timeinput.format_moment(dose.occurrence.actual_at)}" if dose.occurrence.actual_at else "taken"
        return f"✅ {dose.label} · {taken}"
    if state == SKIPPED:
        if dose.occurrence.automatic and dose.occurrence.reason:
            return f"⏭️ {dose.label} · *skipped automatically: {dose.occurrence.reason}*"
        return f"⏭️ {dose.label} · skipped"
    if state == MISSED:
        return f"❌ {dose.label} · missed"
    if shown_time(dose) is not None:
        when = [f"`{timeinput.format_moment(dose.due.at)}`"]
    elif dose.due.why == WAITING:
        when = [f"*after dose {dose.number - 1}*"]
    else:
        when = []
    return " · ".join([f"💊 {dose.label}", *when, *_notes(dose)])


def dose_text(dose: Dose) -> str:
    """The message of its own that a dose with no time gets, under the checklist."""
    return " · ".join([f"💊 {dose.label}", *_notes(dose)])


def progress(listed: list[Dose]) -> tuple[int, int]:
    """(dealt with, all): taken and skipped doses count as dealt with."""
    return sum(dose.occurrence.state in (DONE, SKIPPED) for dose in listed), len(listed)


def checklist(listed: list[Dose], pills: list[Pill], day: date) -> str:
    """Today's checklist: the heading with its progress bar, a line a dose,
    and the paused pills in a section of their own (they are not counted)."""
    done, total = progress(listed)
    lines = [f"## 💊 Pills · {hub.progress_bar(done, total)}" if total else "## 💊 Pills", ""]
    lines += [line(dose) for dose in listed] or ["Nothing to take today."]
    paused = sorted((pill for pill in pills if rules.status_on(pill, day) == PAUSED), key=lambda pill: pill.plan.name.lower())
    if paused:
        lines += ["", "### ⏸️ Paused"]
        for pill in paused:
            until = f" until {timeinput.format_date(pill.paused_until)}" if pill.paused_until else ""
            lines.append(f"⏸️ **{pill.plan.name}** · paused{until}")
    off = not_today(pills, day)
    if off:
        lines += ["", "### 🗓️ Not today"]
        lines += [f"🗓️ **{pill.plan.name}** · {rules.days_text(pill.plan.schedule.days)}" for pill in off]
    return "\n".join(lines)


def not_today(pills: list[Pill], day: date) -> list[Pill]:
    """The pills in use that are simply not taken on this day of the week, by
    name: shown under the day's doses with their days, and never counted."""
    return sorted((pill for pill in pills if rules.is_off_day(pill, day)), key=lambda pill: pill.plan.name.lower())


def left_text(listed: list[Dose]) -> str:
    """What is still to take today, for a reply that reports a change:
    "still to take today: Magnesium, Evening pill `8:00 pm`"."""
    named = left_lines(listed)
    if not named:
        return "nothing left to take today"
    return "still to take today: " + ", ".join(named)


def left_moments(listed: list[Dose]) -> tuple:
    """When each of `left_lines` is due, None for one with no time: the same doses, in the same order."""
    return tuple(dose.due.at if shown_time(dose) is not None else None for dose in listed if dose.is_pending)


def left_lines(listed: list[Dose]) -> tuple[str, ...]:
    """Each dose still to take today, with its time if it has one: "Pill A (dose 2 of 3) `11:30 am`"."""
    named = []
    for dose in listed:
        if not dose.is_pending:
            continue
        name = rules.plain(dose.label)
        named.append(f"{name} `{timeinput.format_moment(dose.due.at)}`" if shown_time(dose) is not None else name)
    return tuple(named)



ANSWER_ICON = "💊"
NOTHING_TODAY = f"{ANSWER_ICON} Nothing to take today."


def left_answer(listed: list[Dose], now: datetime) -> str:
    """ "what pills are left?": the answer itself, said where it was asked. The
    first line names nothing of mine (it is what a lock screen and a direct
    message's preview show): the day's dots and count. Then each dose still to
    take, in time order: due or overdue first, then later today with how far
    off it is, then any time; and what was missed, small. Times in bold."""
    from core import design  # the dots and the bold time, as every card writes them

    if not listed:
        return NOTHING_TODAY
    done, total = progress(listed)
    pending = [dose for dose in listed if dose.is_pending]
    missed = [dose for dose in listed if dose.occurrence.state == MISSED]
    if not pending:
        head = f"{ANSWER_ICON} **Nothing left to take today** · {design.progress(done, total)}"
        return "\n".join([head, *([design.small(f"{len(missed)} missed today")] if missed else [])])

    def order(dose: Dose) -> tuple:
        at = shown_time(dose)
        return (at is None, at.timestamp() if at else 0, rules.plain(dose.pill.plan.name).lower(), dose.number)

    lines = [f"{ANSWER_ICON} **{len(pending)} left today** · {design.progress(done, total)}"]
    for dose in sorted(pending, key=order):
        at = shown_time(dose)
        which = f" · dose {dose.number} of {dose.of}" if dose.of > 1 else ""
        if at is None:
            when = "after the one before" if dose.due.why == WAITING else "any time"
        else:
            when = ("due " if at <= now else "") + design.time(timeinput.format_moment(at))  # exact only: pills have no countdown
        lines.append(f"**{dose.pill.plan.name}**{which} · {when}")
    if missed:
        lines.append(design.small(f"{len(missed)} missed today"))
    return "\n".join(lines)
