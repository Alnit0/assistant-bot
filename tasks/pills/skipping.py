from datetime import datetime

from core import cards, clock, database, llm, occurrences, timeinput
from core.actions import Answer, Choice, Proposal, Question, Request, is_reference
from core.cards import Button, Card
from core.errors import UserError
from tasks.pills import checklist, rules, store, today
from tasks.pills.today import TASK, Dose

# ---------------------------------------------------------------------------
# Pills: "skip all". "skip all of Pill A", "skip all Pill A today": every dose
# of that pill still to take today; "skip all my pills", "skip all": every
# dose of every pill still to take today. Doses taken (or skipped, or missed)
# are left alone. Which doses "all" covers is worked out here, from today's
# doses as the plan makes them: Claude only says which pills were named.
#
# Several doses at once is a change to look over first: a confirm card lists
# each by its time (the card is a reply, never a notification), Save skips
# them all, and the line it leaves has Undo, which brings them all back to
# take, with their reminders. Nothing left to skip is said in one line.
#
# Plain data only (core/cards.py): no discord.py.
# ---------------------------------------------------------------------------
UNDO = "skip_all_undo"
NOTHING = "💊 Nothing is left to take today: there is nothing to skip."


def _order(dose: Dose) -> tuple:
    """By its time today, then the pill's name: a dose with no time comes last."""
    at = dose.due.at
    return (at is None, at or datetime.min, dose.pill.plan.name.lower(), dose.number)


def left(listed: list[Dose], pill_ids: set[int] | None = None) -> list[Dose]:
    """What "skip all" covers: every dose still to take today, of these pills
    (of every pill when None), in the order of the day."""
    return sorted((dose for dose in listed if dose.is_pending and (pill_ids is None or dose.pill.id in pill_ids)), key=_order)


def when(dose: Dose) -> str:
    """A dose's time on the card: when it is due, or "any time"."""
    shown = today.shown_time(dose)
    return f"`{timeinput.format_moment(shown)}`" if shown is not None else "any time"


def line(dose: Dose) -> str:
    return f"⏭️ {when(dose)} · {dose.label}"


def _code(occurrence_id: int) -> str:
    """An id, short: base 36, so a button holds a day's doses."""
    digits, out = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        occurrence_id, rest = divmod(occurrence_id, 36)
        out = digits[rest] + out
        if not occurrence_id:
            return out


def undo_arg(ids: list[int]) -> str:
    return ".".join(_code(each) for each in ids)


def from_undo_arg(arg: str) -> list[int]:
    try:
        return [int(each, 36) for each in arg.split(".") if each]
    except ValueError:
        return []


def undo_button(ids: list[int]) -> Button | None:
    """Undo for the doses Save skipped; none if they would not fit in one button's id."""
    arg = undo_arg(ids)
    if len(cards.make_id("b", TASK, UNDO, arg)) > cards.MAX_ID:
        return None
    return Button("Undo", TASK, UNDO, arg, emoji="↩️", style=cards.PRIMARY)


class _Which:
    """What the message names: the pills meant (None: every pill), what could not
    be found, and a pill that could be more than one, to ask about."""

    def __init__(self, ids: set[int] | None, warnings: list[str], unclear: tuple[str, tuple] | None):
        self.ids, self.warnings, self.unclear = ids, warnings, unclear


async def _which(request: Request, data: dict) -> tuple[_Which, list[Dose]]:
    pills, listed, _ = await checklist.view(request.user.id)
    named = [str(item.get("pill") or "").strip() for item in data.get("pills") or []]
    named = [each for each in named if each]
    if not named:
        return _Which(None, [], None), listed
    ids: set[int] = set()
    warnings: list[str] = []
    unclear = None
    for each in named:
        if is_reference(each):
            from tasks.pills import plain  # plain imports the checklist, and this module through the task

            last, _ = await plain._unnamed(request, listed, None, clock.now(), checklist.SKIP)
            if last is None:
                warnings.append("Which pill? Say its name.")
            else:
                ids.add(last)
            continue
        try:
            ids.add(rules.find(pills, each, request.text).id)
        except rules.Ambiguous as error:
            unclear = unclear or (each, tuple(error.candidates))
        except UserError as error:
            warnings.append(str(error).removeprefix("⚠️ "))
    return _Which(ids, warnings, unclear), listed


async def asks(request: Request, data: dict, guessed: frozenset = frozenset()) -> bool:
    """A card whenever there is anything to skip (several doses at once are looked
    over first) or a pill to ask about; with nothing left, a line (`said`)."""
    which, listed = await _which(request, data)
    if which.unclear is not None:
        return True
    return bool(which.ids is None or which.ids) and bool(left(listed, which.ids))


async def said(request: Request, data: dict, guessed: frozenset) -> str:
    """Nothing left to skip, in one line."""
    which, listed = await _which(request, data)
    if which.ids:
        names = sorted({dose.pill.plan.name for dose in listed if dose.pill.id in which.ids}) or sorted(
            pill.plan.name for pill in await store.pills(request.user.id) if pill.id in which.ids
        )
        named = " or ".join(f"**{name}**" for name in names)
        return f"💊 {named} {'has' if len(names) == 1 else 'have'} nothing left to take today: there is nothing to skip."
    if which.warnings:
        return "⚠️ " + "; ".join(which.warnings)
    return NOTHING


async def card(request: Request, data: dict, guessed: frozenset) -> Proposal:
    """The card: each dose that will be skipped, by its time. Save skips them all."""
    which, listed = await _which(request, data)
    if which.unclear is not None:
        said_as, candidates = which.unclear
        items = data.get("pills") or []
        return Proposal(
            lines=(), data=data, kind="change", warnings=tuple(which.warnings),
            question=Question(f"Which pill is “{said_as}”?", tuple(
                Choice(pill.plan.name, {"pills": [{"pill": pill.ref} if str(item.get("pill") or "").strip() == said_as else dict(item) for item in items]}, ("pill",))
                for pill in candidates
            )),
        )
    doses = left(listed, which.ids)
    if not doses:
        raise UserError((await said(request, data, guessed)).removeprefix("⚠️ "))
    return Proposal(
        lines=(f"Skip {'this dose' if len(doses) == 1 else f'these {len(doses)} doses'} today:", *(line(dose) for dose in doses)),
        data={"doses": [dose.occurrence.id for dose in doses]}, warnings=tuple(which.warnings), kind="change",
    )


async def save(request: Request, data: dict) -> Answer:
    """Save: every dose on the card still to take is skipped; the line says
    which, with Undo."""
    _, listed, _ = await checklist.view(request.user.id)
    by_id = {dose.occurrence.id: dose for dose in listed}
    done: list[Dose] = []
    for occurrence_id in data["doses"]:
        dose = by_id.get(occurrence_id)
        if dose is None or not dose.is_pending:
            continue  # taken or changed since the card was made: left as it is
        done.append(await checklist.mark(dose, checklist.SKIP, clock.now(), occurrences.MESSAGE))
    if not done:
        raise UserError("Those doses have changed since the card was made: nothing was skipped.")
    checklist.changed(request.user.id)
    _, listed, _ = await checklist.view(request.user.id)
    text = "\n".join([f"⏭️ Skipped {'1 dose' if len(done) == 1 else f'{len(done)} doses'} today", *(line(dose) for dose in done), f"-# {today.left_text(listed)}"])
    ids = [dose.occurrence.id for dose in done]
    button = undo_button(ids)

    async def placed(message_id: int) -> None:
        await database.run(store.db_add_lines, request.user.id, message_id, [(dose.pill.id, dose.occurrence.id) for dose in done])
        if button is not None and request.channel_id is not None:
            await cards.edit(request.channel_id, message_id, Card(text, ((button,),)))

    return Answer(text, placed)


async def check(request: Request, data: dict) -> str:
    """Read back: no dose on the card is still to take."""
    _, listed, _ = await checklist.view(request.user.id)
    still = [dose for dose in listed if dose.occurrence.id in set(data["doses"]) and dose.is_pending]
    return "; ".join(f"{rules.plain(dose.label)} is still to take" for dose in still)


async def on_undo(press: cards.Press) -> str:
    """Undo: every dose that Save skipped, and that is still skipped, is to take
    again, and its reminders come back. The line says so; the button goes."""
    ids = set(from_undo_arg(press.arg))
    _, listed, _ = await checklist.view(press.user.id)
    back = []
    for dose in sorted((each for each in listed if each.occurrence.id in ids), key=_order):
        if dose.occurrence.state == occurrences.SKIPPED and not dose.occurrence.automatic:
            back.append(await checklist.mark(dose, checklist.NOT_TAKEN, clock.now(), occurrences.BUTTON))
    if not back:
        await press.update(Card("↩️ Nothing to undo: those doses have changed since."))
        return "nothing to undo"
    checklist.changed(press.user.id)
    _, listed, _ = await checklist.view(press.user.id)
    shown = {dose.occurrence.id: dose for dose in listed}
    text = "\n".join([
        f"↩️ Not skipped after all: {'1 dose' if len(back) == 1 else f'{len(back)} doses'} to take again",
        *(f"💊 {when(shown.get(dose.occurrence.id, dose))} · {dose.label}" for dose in back),
        f"-# {today.left_text(listed)}",
    ])
    await press.update(Card(text))
    llm.remember(press.channel_id, "(pressed Undo on the skipped doses)", text)
    llm.task_answered(press.channel_id, TASK)
    return text


def register() -> None:
    cards.register(TASK, UNDO, on_undo)
