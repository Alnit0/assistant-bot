import logging
from dataclasses import fields
from datetime import date, time, timedelta

from core import cards, database, day, lifecycle, occurrences, scheduler, timeinput
from core.cards import Button, Card, Option, Select
from core.context import Context
from core.errors import UserError
from core.lifecycle import MessageClass
from core.scheduler import utc_now
from tasks.pills import rules, store
from tasks.pills.rules import ACTIVE, ENDED, PAUSED, REMOVED, Pill, Plan, Request, TimeQuestion
from tasks.pills.store import Draft

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Setting pills up: adding, editing, pausing and removing them, by asking in
# plain words (Claude's tools) or from the `pills` list.
#
# The plan never changes unseen. Adding or editing makes a draft and shows a
# preview with Save and Edit; only Save writes it. Removing asks first.
# Pausing and resuming act at once: they change no plan and are undone in a
# word.
#
# No discord.py here: cards are core/cards.py's, and the decisions and the
# wording are rules.py's.
# ---------------------------------------------------------------------------
TASK = "pills"
JOB_DRAFT = "draft_expire"
DRAFT_MINUTES = 30  # how long a preview waits for Save

REQUEST_FIELDS = tuple(entry.name for entry in fields(Request))

EDIT_HINT = "✏️ Say what to change, e.g. “make it 9pm” or “add: with food”. Nothing is saved until you press Save."
LAPSED = "⌛ That preview has lapsed and nothing was saved. Ask again to start over."


# ---------------------------------------------------------------------------
# Cards (pure: values in, a Card out)
# ---------------------------------------------------------------------------
def _button(label: str, action: str, arg, emoji: str | None = None, style: str = cards.SECONDARY) -> Button:
    return Button(label, TASK, action, str(arg), emoji=emoji, style=style)


def preview_card(draft: Draft, base: Pill | None, today: date, hint: bool = False) -> tuple[Card, Plan | None]:
    """What a draft shows: the plan with Save and Edit, or, while one of its
    times could be morning or evening, that question with a button for each
    reading. Returns the plan too (None while the question is open)."""
    try:
        plan = rules.build(draft.request, today, base.plan if base else None)
    except TimeQuestion as question:
        name = draft.request.name.strip() or (base.plan.name if base else "This pill")
        asked = str(timeinput.AmbiguousTime(question.options))
        row = tuple(
            _button(timeinput.format_time(option), "time", f"{draft.id}:{question.index}:{option:%H%M}", style=cards.PRIMARY)
            for option in question.options
        )
        return Card(f"💊 **{name}** · at {question.typed}: **{asked}**", (row,)), None
    text = rules.describe(plan) if base is None else rules.change_text(base.plan, plan)
    if hint:
        text += f"\n{EDIT_HINT}"
    row = (
        _button("Save", "save", draft.id, "✅", cards.SUCCESS),
        _button("Edit", "edit", draft.id, "✏️"),
    )
    return Card(text, (row,)), plan


def list_card(pills: list[Pill], today: date) -> Card:
    """Every pill, and one dropdown to pick one to edit, pause or remove."""
    shown = rules.listed(pills)[: cards.MAX_OPTIONS]
    if not shown:
        return Card(rules.list_text(pills, today))
    options = tuple(
        Option(cards.truncate_label(pill.plan.name, cards.MAX_OPTION_TEXT), str(pill.id), rules.status_on(pill, today))
        for pill in shown
    )
    return Card(rules.list_text(pills, today), (Select(TASK, "pick", options, placeholder="Edit, pause or remove…"),))


def pill_card(pill: Pill, today: date) -> Card:
    """One pill, with what can be done to it."""
    state = rules.status_on(pill, today)
    row = [_button("Edit", "p_edit", pill.id, "✏️")]
    if state == PAUSED:
        row.append(_button("Resume", "p_resume", pill.id, "▶️"))
    elif state != ENDED:
        row.append(_button("Pause", "p_pause", pill.id, "⏸️"))
    row += [_button("Remove", "p_remove", pill.id, "🗑️", cards.DANGER), _button("Back", "list", "", "↩️")]
    return Card(rules.describe_pill(pill, today), (tuple(row),))


def remove_card(pill: Pill, for_good: bool) -> Card:
    """The question before a pill is removed, or deleted with its history."""
    if for_good:
        text = (
            f"Delete **{pill.plan.name}** and everything recorded about it, for good? "
            "Its history of doses goes too, and this can't be undone."
        )
        yes = _button("Delete for good", "delete_yes", pill.id, "🗑️", cards.DANGER)
    else:
        text = (
            f"Remove **{pill.plan.name}**? It disappears from every list and stops prompting. "
            "Its history is kept."
        )
        yes = _button("Remove", "remove_yes", pill.id, "🗑️", cards.DANGER)
    return Card(text, ((yes, _button("Cancel", "cancel", pill.id)),))


# ---------------------------------------------------------------------------
# Drafts and their previews
# ---------------------------------------------------------------------------
def _request(value: dict) -> Request:
    return Request(**{name: str(value.get(name, "") or "") for name in REQUEST_FIELDS})


async def _own_draft(ctx: Context, ref: str, pill_id: int | None) -> Draft | None:
    """The open draft a tool call names, if it is this user's and for the same thing."""
    wanted = store.draft_id(ref) if ref.strip() else None
    if wanted is None:
        return None
    found = await store.draft(wanted)
    if found is None or found.user_id != ctx.user.id or found.pill_id != pill_id:
        return None
    return found


async def _book_expiry(draft: Draft) -> Draft:
    await scheduler.cancel_job(draft.job_id)
    job_id = await scheduler.add_job(
        TASK, JOB_DRAFT, utc_now() + timedelta(minutes=DRAFT_MINUTES), {"draft": draft.id}, draft.user_id
    )
    return await store.update_draft(draft.id, job_id=job_id)


async def _show(ctx: Context, draft: Draft, base: Pill | None, previous: Draft | None) -> str:
    """Post a draft's preview as the answer (taking away the one it replaces),
    and say for Claude what the user is now looking at."""
    card, plan = preview_card(draft, base, day.today())
    if previous is not None and previous.channel_id and previous.message_id:
        # The new preview goes where the conversation is; the old one would only mislead
        await cards.delete(previous.channel_id, previous.message_id)
    message_id = await cards.post(ctx, card)
    draft = await store.update_draft(draft.id, channel_id=ctx.channel_id, message_id=message_id)
    await _book_expiry(draft)
    if plan is None:
        return (
            f"Asked the user, with a button for each, which time they mean (draft {draft.ref}). "
            "Nothing is saved. Do not answer for them."
        )
    return (
        f"Preview shown with Save and Edit buttons (draft {draft.ref}): {rules.plain(rules.describe(plan))}. "
        "It is NOT saved until the user presses Save: never say it has been added or changed."
    )


async def draft_expired(job: scheduler.Job) -> None:
    """Scheduler handler: a preview nobody saved lapses, so an old one can't be
    saved by accident later. Its message goes, as an unanswered question does."""
    draft = await store.draft(job.payload.get("draft", 0))
    if draft is None or draft.job_id != job.id:
        return  # saved, replaced or already gone
    await store.discard_draft(draft.id)
    if not draft.channel_id or not draft.message_id:
        return
    if lifecycle.deletes(MessageClass.TRANSIENT):
        await cards.delete(draft.channel_id, draft.message_id)
    else:
        await cards.edit(draft.channel_id, draft.message_id, Card(LAPSED))


# ---------------------------------------------------------------------------
# Claude's tools. Each returns what happened, for Claude to go on from.
# ---------------------------------------------------------------------------
async def add_tool(ctx: Context, value: dict) -> str:
    request = _request(value)
    previous = await _own_draft(ctx, value.get("draft", ""), None)
    if previous is None and request.name.strip():
        # Asked for again by name while its preview is open: that preview is the one meant
        same = [
            draft
            for draft in await store.drafts(ctx.user.id)
            if draft.pill_id is None and draft.request.name.strip().lower() == request.name.strip().lower()
        ]
        previous = same[-1] if same else None
    if previous is not None:
        request = previous.request.merged(request)
    pills = await store.pills(ctx.user.id)
    today = day.today()
    if request.name.strip():
        rules.check_name(Plan(request.name.strip()), pills)
    try:
        rules.build(request, today)  # refuse what can't be a plan before showing anything
    except TimeQuestion:
        pass  # the preview asks
    if previous is not None:
        draft = await store.update_draft(previous.id, request=request)
    else:
        draft = await store.add_draft(ctx.user.id, None, request)
    return await _show(ctx, draft, None, previous)


async def edit_tool(ctx: Context, value: dict) -> str:
    pills = await store.pills(ctx.user.id)
    pill = rules.find(pills, value.get("pill", ""))
    request = _request(value)
    # One preview at a time for a pill: asking again changes the one that is open
    previous = await ctx.db.run(store.db_draft_for_pill, pill.id)
    if previous is not None:
        request = previous.request.merged(request)
    today = day.today()
    try:
        plan = rules.build(request, today, pill.plan)
        rules.check_name(plan, pills, own_id=pill.id)
        if plan == pill.plan:
            return f"Nothing to change: {pill.plan.name} is already {rules.plain(rules.describe(pill.plan))}."
    except TimeQuestion:
        pass
    if previous is not None:
        draft = await store.update_draft(previous.id, request=request)
    else:
        draft = await store.add_draft(ctx.user.id, pill.id, request)
    return await _show(ctx, draft, pill, previous)


async def pause_tool(ctx: Context, value: dict) -> str:
    pill = rules.find(await store.pills(ctx.user.id), value.get("pill", ""))
    today = day.today()
    state = rules.status_on(pill, today)
    name = f"**{pill.plan.name}**"
    if value.get("action") == "resume":
        if state != PAUSED:
            said = f"▶️ {name} isn't paused."
        else:
            await store.set_status(pill.id, ACTIVE)
            said = f"▶️ {name} resumed."
        await ctx.confirm(said)
        return said
    if state == ENDED:
        raise UserError(f"{pill.plan.name} has ended: there is nothing to pause.")
    until = None
    if (value.get("until") or "").strip():
        until = timeinput.parse_date(value["until"], today)
        if until <= today:
            raise UserError("A pause ends on a later day than today. To take it again now, resume it.")
    await store.set_status(pill.id, PAUSED, until)
    said = f"⏸️ {name} paused" + (f" until {timeinput.format_date(until)}." if until else ". Say when to resume it.")
    await ctx.confirm(said)
    return said


async def remove_tool(ctx: Context, value: dict) -> str:
    pill = rules.find(await store.pills(ctx.user.id), value.get("pill", ""))
    for_good = value.get("history") == "delete"
    await cards.post(ctx, remove_card(pill, for_good))
    return (
        f"Asked the user to confirm with buttons before {pill.plan.name} is "
        f"{'deleted with its history' if for_good else 'removed'}. Not done yet: do not say it has been."
    )


async def live_state(ctx: Context) -> str:
    pills = await store.pills(ctx.user.id)
    today = day.today()
    by_id = {pill.id: pill for pill in pills}
    previews = []
    for draft in await store.drafts(ctx.user.id):
        base = by_id.get(draft.pill_id) if draft.pill_id else None
        try:
            shown = rules.describe(rules.build(draft.request, today, base.plan if base else None))
        except TimeQuestion as question:
            shown = f"{draft.request.name or (base.plan.name if base else 'new pill')}: waiting for the user to say whether {question.typed} is morning or evening"
        except UserError:
            continue
        previews.append((draft.ref, ("change to " if base else "new pill ") + shown))
    return rules.live_text(pills, previews, today)


# ---------------------------------------------------------------------------
# The `pills` word
# ---------------------------------------------------------------------------
async def show_list(ctx: Context) -> str:
    pills = await store.pills(ctx.user.id)
    today = day.today()
    await cards.post(ctx, list_card(pills, today))
    shown = rules.listed(pills)
    return f"listed {len(shown)} pill(s)" + (": " + ", ".join(pill.plan.name for pill in shown) if shown else "")


# ---------------------------------------------------------------------------
# What the buttons and the dropdown do
# ---------------------------------------------------------------------------
async def _pill_of(press: cards.Press, pill_id: str) -> Pill:
    pill = await store.pill(int(pill_id)) if pill_id.isdigit() else None
    if pill is None or pill.user_id != press.user.id or pill.status == REMOVED:
        raise UserError("That pill isn't there any more.")
    return pill


async def _draft_of(press: cards.Press, draft_id: str) -> tuple[Draft, Pill | None] | None:
    """The draft a preview's button belongs to and the pill it edits. None (and
    the card says so) if it lapsed or was replaced."""
    draft = await store.draft(int(draft_id)) if draft_id.isdigit() else None
    if draft is None or draft.user_id != press.user.id:
        await press.update(Card(LAPSED))
        return None
    base = None
    if draft.pill_id is not None:
        base = await store.pill(draft.pill_id)
        if base is None or base.status == REMOVED:
            await store.discard_draft(draft.id)
            await press.update(Card("⌛ That pill has been removed since. Nothing was changed."))
            return None
    return draft, base


async def on_save(press: cards.Press) -> str | None:
    found = await _draft_of(press, press.arg)
    if found is None:
        return "preview had lapsed"
    draft, base = found
    today = day.today()

    def save(conn) -> Pill:
        # Checked again here, in the same transaction as the write: the list may
        # have changed since the preview was shown
        plan = rules.build(draft.request, today, base.plan if base else None)
        rules.check_name(plan, store.db_pills(conn, draft.user_id), own_id=draft.pill_id)
        saved = store.db_add(conn, draft.user_id, plan) if base is None else store.db_edit(conn, base.id, plan)
        store.db_discard_draft(conn, draft.id)
        return saved

    pill = await press.db.run(save)
    await scheduler.cancel_job(draft.job_id)
    done = "Saved" if base is None else "Updated"
    await press.update(Card(f"✅ {done} · {rules.describe_pill(pill, today)}"))
    return f"{done.lower()} {pill.ref}: {rules.plain(rules.describe(pill.plan))}"


async def on_edit(press: cards.Press) -> str | None:
    found = await _draft_of(press, press.arg)
    if found is None:
        return "preview had lapsed"
    draft, base = found
    card, _ = preview_card(draft, base, day.today(), hint=True)
    await press.update(card)
    await _book_expiry(draft)  # a fresh half hour to say what changes
    return f"asked what to change in draft {draft.ref}"


async def on_time(press: cards.Press) -> str | None:
    """The answer to "8am or 8pm?": the draft's time is settled and the preview follows."""
    draft_id, index, chosen = (press.arg.split(":") + ["", ""])[:3]
    found = await _draft_of(press, draft_id)
    if found is None:
        return "preview had lapsed"
    draft, base = found
    today = day.today()
    try:
        rules.build(draft.request, today, base.plan if base else None)
    except TimeQuestion as question:
        if str(question.index) != index or len(chosen) != 4 or not chosen.isdigit():
            raise UserError("That question has changed. Use the buttons on the latest preview.")
        picked = time(int(chosen[:2]), int(chosen[2:]))
        if picked not in question.options:
            raise UserError("That question has changed. Use the buttons on the latest preview.")
        draft = await store.update_draft(draft.id, request=rules.answer(draft.request, question, picked))
    card, plan = preview_card(draft, base, today)  # the preview, or the next time to ask about
    await press.update(card)
    return f"draft {draft.ref}: " + (rules.plain(rules.describe(plan)) if plan else "another time to settle")


async def on_pick(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.values[0] if press.values else "")
    await press.update(pill_card(pill, day.today()))
    return f"showed {pill.ref}"


async def on_list(press: cards.Press) -> str | None:
    await press.update(list_card(await store.pills(press.user.id), day.today()))
    return "showed the list"


async def on_pill_edit(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    name = pill.plan.name
    await press.say(
        f"✏️ Tell me what to change about **{name}**, e.g. “move {name} to 9pm” or “{name} is now 2 tablets”. "
        "You get a preview to save."
    )
    return f"asked what to change about {pill.ref}"


async def on_pill_pause(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    pill = await store.set_status(pill.id, PAUSED)
    await press.update(pill_card(pill, day.today()))
    return f"paused {pill.ref}"


async def on_pill_resume(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    pill = await store.set_status(pill.id, ACTIVE)
    await press.update(pill_card(pill, day.today()))
    return f"resumed {pill.ref}"


async def on_pill_remove(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    await press.update(remove_card(pill, for_good=False))
    return f"asked before removing {pill.ref}"


async def on_remove_yes(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    await store.set_status(pill.id, REMOVED)
    await press.update(Card(f"🗑️ Removed **{pill.plan.name}**. Its history is kept."))
    return f"removed {pill.ref}"


async def on_delete_yes(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)

    def delete(conn) -> int:
        doses = occurrences.db_delete_item(conn, TASK, pill.id)
        store.db_delete(conn, pill.id)
        return doses

    doses = await press.db.run(delete)
    await press.update(Card(f"🗑️ Deleted **{pill.plan.name}** and its history."))
    return f"deleted {pill.ref} for good, with {doses} recorded dose(s)"


async def on_cancel(press: cards.Press) -> str | None:
    pill = await _pill_of(press, press.arg)
    await press.update(Card(f"👌 Left **{pill.plan.name}** as it is."))
    return f"left {pill.ref} alone"


ACTIONS = {
    "save": on_save,
    "edit": on_edit,
    "time": on_time,
    "pick": on_pick,
    "list": on_list,
    "p_edit": on_pill_edit,
    "p_pause": on_pill_pause,
    "p_resume": on_pill_resume,
    "p_remove": on_pill_remove,
    "remove_yes": on_remove_yes,
    "delete_yes": on_delete_yes,
    "cancel": on_cancel,
}


def register_actions() -> None:
    for action, handler in ACTIONS.items():
        cards.register(TASK, action, handler)


async def message_class(message_id: int) -> MessageClass | None:
    """An open preview is Live: edited in place, and one line once it is saved."""
    draft = await database.run(store.db_draft_by_message, message_id)
    return MessageClass.LIVE if draft is not None else None
