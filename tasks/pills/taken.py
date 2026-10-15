from datetime import date, timedelta

from core import clock, database, design, occurrences, timeinput
from core import day as days
from core.actions import Request
from core.occurrences import DONE, MISSED, PENDING, SKIPPED
from tasks.pills import checklist, history, rules, today
from tasks.pills.today import ANSWER_ICON, TASK, Dose

# ---------------------------------------------------------------------------
# "When did I take my pills today?" (bug from live, 15 Oct: it was answered
# with what is left). A question about when or whether doses were taken, on
# today, yesterday or a named day, answered in place from the record: each
# taken dose and its time, and anything skipped or missed. Narrowed by a
# pill, a dose's number or a part of the day when the question names one;
# "when did I last take X" looks back over the days. What is left is
# `today.left_answer`'s; a question that asks both gets both (`also_left`).
# The first line names nothing of mine (a lock screen or a direct message's
# preview shows it). Which answer is said is Python's, from extraction's fields.
# ---------------------------------------------------------------------------
PARTS = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}
LOOK_BACK = timedelta(days=60)  # how far "when did I last take" looks


def _hour(dose: Dose) -> int | None:
    at = dose.occurrence.planned_time
    if at is not None:
        return at.hour
    moment = dose.occurrence.actual_at or dose.occurrence.due_at
    return days.local_time(moment).hour if moment is not None else None


def narrowed(listed: list[Dose], pill_id: int | None = None, number: int | None = None, part: str = "") -> list[Dose]:
    """The doses the question is about: of one pill, one dose number, one part of the day. Pure."""
    found = [dose for dose in listed if pill_id is None or dose.pill.id == pill_id]
    if number:
        found = [dose for dose in found if dose.number == number]
    if part in PARTS:
        start, end = PARTS[part]
        found = [dose for dose in found if (hour := _hour(dose)) is not None and start <= hour < end]
    return found


def _order(dose: Dose) -> tuple:
    at = dose.occurrence.actual_at or dose.occurrence.due_at
    return (at is None, at.timestamp() if at else 0, rules.plain(dose.pill.plan.name).lower(), dose.number)


def _named_day(day: date, now_day: date) -> str:
    return {now_day: "today", now_day - timedelta(days=1): "yesterday"}.get(day, f"on {history.day_name(day)}")


def answer(listed: list[Dose], day: date, now_day: date, narrowed_to: bool = False) -> str:
    """Each taken dose with its time, then what was skipped or missed, in time order. Doses still
    to take are said only when the question named which ("did I take dose 2?": not yet). Pure."""
    when = _named_day(day, now_day)
    if not listed:
        return f"{ANSWER_ICON} Nothing was to take {when}." if not narrowed_to else f"{ANSWER_ICON} No dose like that {when}."
    taken = [dose for dose in listed if dose.occurrence.state == DONE]
    closed = [dose for dose in listed if dose.occurrence.state in (SKIPPED, MISSED)]
    waiting = [dose for dose in listed if dose.occurrence.state == PENDING] if narrowed_to else []
    done, total = today.progress(listed)
    head = f"{ANSWER_ICON} **{len(taken)} taken {when}**" if taken else f"{ANSWER_ICON} **Nothing taken {when}" + (" yet**" if day == now_day else "**")
    lines = [f"{head} · {design.progress(done, total)}"]
    lines += [today.line(dose) for dose in sorted(taken, key=_order)]
    lines += [today.line(dose) for dose in sorted(closed, key=_order)]
    lines += [f"💊 {dose.label} · not taken yet" for dose in sorted(waiting, key=_order)]
    return "\n".join(lines)


def last_answer(dose: Dose | None, now_day: date) -> str:
    """ "When did I last take X": the latest dose of it taken, with its day. Pure."""
    if dose is None:
        return f"{ANSWER_ICON} Not taken in the last {LOOK_BACK.days} days."
    day = dose.occurrence.day
    head = f"{ANSWER_ICON} **Last taken {_named_day(day, now_day)}**"
    return "\n".join([head, today.line(dose)])


def _day(said, now_day: date) -> date:
    text = str(said or "").strip().lower()
    if not text or text == "today":
        return now_day
    return timeinput.parse_past_date(text, now_day)


async def _doses_on(user_id: int, day: date, now_day: date) -> tuple[list, list[Dose]]:
    """The pills and a day's doses: today as the checklist has them, a day gone by as recorded."""
    if day == now_day:
        pills, listed, _ = await checklist.view(user_id)
        return pills, listed
    pills = await database.run(history.db_names, user_id)
    found = await occurrences.for_day(user_id, TASK, day)
    return list(pills.values()), history._doses(pills, found)


async def show(request: Request, data: dict, guessed: frozenset) -> str:
    """ "when did I take my pills today?", "did I take dose 2?", "when did I last take Pill A?",
    "what did I take on Tuesday and what's left?": the answer, said where it was asked."""
    now = clock.now()
    now_day = days.today(now)
    pill = None
    if data.get("pill"):
        pills, _, _ = await checklist.view(request.user.id)
        pill = rules.find(pills, str(data["pill"]), request.text)
    if data.get("last") and pill is not None:
        found = await database.run(occurrences.db_between, request.user.id, TASK, now_day - LOOK_BACK, now_day)
        names = await database.run(history.db_names, request.user.id)
        doses = [each for each in history._doses(names, found) if each.pill.id == pill.id and each.occurrence.state == DONE]
        latest = max(doses, key=lambda each: each.occurrence.actual_at or days.start_of(each.occurrence.day), default=None)
        said = last_answer(latest, now_day)
    else:
        day = _day(data.get("day"), now_day)
        _, listed = await _doses_on(request.user.id, day, now_day)
        number = data.get("dose") if isinstance(data.get("dose"), int) else None
        part = str(data.get("part") or "")
        chosen = narrowed(listed, pill.id if pill else None, number, part)
        said = answer(chosen, day, now_day, narrowed_to=bool(pill or number or part in PARTS))
    if data.get("also_left"):
        _, listed, _ = await checklist.view(request.user.id)
        said += "\n" + today.left_answer(listed, now)
    return said
