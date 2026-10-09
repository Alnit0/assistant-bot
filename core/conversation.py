import json
import logging
import re
import time
from dataclasses import dataclass, field, replace

import discord

from core import actions, cards, confirm, costs, database, extraction, livelists, llm, routing, timing
from core.actions import LIST, ITEMS, Entry, LiveReply, Request
from core.cards import Card
from core.config import CHANNELS, INBOX_CHANNEL_ID
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import COLOUR_OK, log_error, send_log, truncate
from core.config import real_now_nz
from core.errors import UserError
from core.extraction import Extracted, OpenCard
from core.permissions import is_allowed
from core.scheduler import utc_now

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# A message in plain words: who deals with it, cheapest first.
#
#   a button, a form, a dropdown        Python (core/cards.py)        0 requests
#   an exact shortcut                   Python (tasks/registry.py)    0
#   about the open card                 extraction for its task       1
#   anything else                       the router, then extraction   2
#   not for a task                      the router, then plain chat   2
#   a task and a general question too   all three: every part is      3
#                                       dealt with
#
# The first two never get here. This file does the rest: it decides whether
# the message is a follow-up, asks the router, asks extraction for each task
# chosen, and hands what comes back to the task's own code. That code, never
# Claude, validates, saves, and writes every word of the answer: a confirm
# card for anything that changes setup, a reply for the rest.
#
# Everything is logged: the route, the tasks, what was extracted, the outcome
# and the cost of each request.
# ---------------------------------------------------------------------------
WENT_WRONG = "⚠️ That didn't work. Check #bot-log."


def listens_in(channel_id: int) -> bool:
    """Where plain words are read: #inbox and the hub."""
    return channel_id == INBOX_CHANNEL_ID or channel_id == CHANNELS.get("hub")


def entries_for(user) -> list[Entry]:
    """The tasks this user may be routed to."""
    return [entry for entry in actions.catalogue() if is_allowed(user, f"task:{entry.name}")]


@dataclass
class Turn:
    """What happened to one message, for the log."""

    route: str = costs.ROUTER
    tasks: list[str] = field(default_factory=list)
    extracted: list[dict] = field(default_factory=list)
    said: list[str] = field(default_factory=list)  # what the user was shown, in order
    failed: bool = False


def not_included(parts) -> str:
    """What the user asked for that couldn't be done, said in so many words: it
    goes on the card, or after the reply. Nothing is dropped without one."""
    return "Not included: " + ", ".join(parts)


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9']+", text.lower()) if len(word) > 2}


def _texts(value) -> list[str]:
    """Every piece of text in what was extracted, however deep."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for inner in value.values() for text in _texts(inner)]
    if isinstance(value, list):
        return [text for inner in value for text in _texts(inner)]
    return []


def uncovered(found: Extracted, others: list[Extracted], chat_part: str = "") -> Extracted:
    """What extraction reported as not included, less whatever something else
    is dealing with: another task's card, or the plain answer to the part of
    the message that was for no task. "Not included" is only for what nothing
    covers. Checked in code: each extraction sees only its own task."""
    if not found.not_included:
        return found
    handled = [text.lower() for other in others if other is not found and other.fitted for text in _texts(other.data)]
    answered = _words(chat_part)
    left = []
    for part in found.not_included:
        said = part.lower()
        words = _words(part)
        by_another_task = any(len(text) > 2 and text in said for text in handled)
        by_the_answer = bool(words) and len(words & answered) / len(words) >= 0.6
        if not by_another_task and not by_the_answer:
            left.append(part)
    return replace(found, not_included=tuple(left))


def _elsewhere(name: str, tasks, chat_part: str) -> str:
    """For one task's extraction: what else in the message is being dealt with, and by what."""
    parts = [f"the {other} task" for other in tasks if other != name]
    if chat_part:
        parts.append(f"a plain answer to: {chat_part}")
    return "; ".join(parts)


def nothing_fitted(entry: Entry) -> str:
    """Said when extraction found no action: Python's words, with the task's own hint."""
    return f"{entry.icon} I couldn't work that out for {entry.name}." + (f" {entry.hint}" if entry.hint else "")


async def _state(entry: Entry, request: Request) -> str:
    if entry.live_state is None:
        return ""
    try:
        return await entry.live_state(request)
    except Exception:
        log.exception("Task %s could not give its state for extraction", entry.name)
        return ""


async def act(
    request: Request,
    found: Extracted,
    turn: Turn,
    replaces: confirm.Stored | None = None,
    *,
    moved: bool = False,
    undone: bool = False,
) -> None:
    """Do what extraction found, in the task's own code, and show the result:
    a confirm card for an action that needs one, otherwise the task's reply.

    `replaces` is the open card this corrects or takes the place of. With
    `moved` it belonged to another task ("no, packing"); with `undone` the
    user's last change to it was a mistake, and `request.previous` is the card
    as it was before that change."""
    entry = found.entry
    turn.tasks.append(entry.name)
    turn.extracted.append(found.as_log())

    async def say(text: str) -> None:
        turn.said.append(text)
        await cards.send(request.channel_id, Card(text))

    if not found.fitted:
        await say(nothing_fitted(entry))
        return
    action = found.action
    if not is_allowed(request.user, f"action:{action.name}"):
        turn.failed = True
        await say("⚠️ You're not allowed to do that.")
        return
    try:
        if action.needs_card:
            proposal = await action.prepare(request, found.data, found.guessed)
            if found.not_included:
                proposal = replace(proposal, warnings=(*proposal.warnings, not_included(found.not_included)))
            await confirm.show(request, entry, action.name, proposal, found.guessed, replaces, moved=moved, undone=undone)
            shown = [*proposal.lines, *[f"{actions.WARNING_MARK} {warning}" for warning in proposal.warnings]]
            turn.said.append(f"card: {entry.name} · {proposal.kind}: " + " / ".join(shown))
        else:
            result = await action.run(request, found.data, found.guessed)
            left_out = f"{actions.WARNING_MARK} {not_included(found.not_included)}" if found.not_included else ""
            if isinstance(result, LiveReply):
                # A list shown on request: this copy is now the one kept up to date, and
                # what follows it is taken to be for this task
                turn.said.append(result.text)
                message_id = await cards.send(request.channel_id, Card(result.text))
                await livelists.placed(request.user.id, result.key, request.channel_id, message_id, entry.name)
                if left_out:
                    # Not on the list itself: that message is rewritten whenever the list changes
                    await say(left_out)
            else:
                await say(f"{result}\n{left_out}" if left_out else result)
    except UserError as error:
        # The task's own words for a problem the user can fix
        turn.failed = True
        await say(f"⚠️ {error}")
    except Exception as error:
        turn.failed = True
        log.exception("Action %s failed", action.name)
        await log_error(f"Action failed: {action.name}", repr(error), request.text)
        await say(WENT_WRONG)


def _in_common(entry_field, new, old) -> bool:
    """Whether a field's new value shares anything with the old: the same value,
    or, for a list, at least one item that was already there."""
    if entry_field.type not in (LIST, ITEMS) or not isinstance(new, list) or not isinstance(old, list):
        return new == old
    if entry_field.type == LIST:
        return bool(set(new) & set(old))
    # Items are the same thing if what names them (their required fields) matches
    names = [inner.name for inner in entry_field.item_fields if inner.required] or [inner.name for inner in entry_field.item_fields]

    def key(item: dict) -> tuple:
        return tuple(str(item.get(name, "")).strip().lower() for name in names)

    return bool({key(item) for item in new} & {key(item) for item in old})


def _item_names(action, data: dict) -> list[str]:
    """What each item in an action's lists of items is called (its required fields)."""
    names = []
    for entry_field in action.fields if action is not None else ():
        if entry_field.type != ITEMS or not isinstance(data.get(entry_field.name), list):
            continue
        keys = [inner.name for inner in entry_field.item_fields if inner.required]
        names += [" ".join(str(item.get(key, "")) for key in keys).strip() for item in data[entry_field.name]]
    return [name for name in names if name]


def _carried_over(card: confirm.Stored, target: Entry) -> Extracted | None:
    """A card's items as the same request for another task ("no, packing"),
    built in code: every item, by what names it. Only when it is plain how:
    the card's action has one list of items, and exactly one action of the
    other task that needs a card takes a list of items named the same way.
    None otherwise, and extraction reads it over instead."""
    source_entry = actions.entry(card.task)
    source = source_entry.action(card.action) if source_entry else None
    lists = [entry for entry in source.fields if entry.type == ITEMS] if source else []
    if len(lists) != 1 or not isinstance(card.data.get(lists[0].name), list):
        return None
    names = [inner.name for inner in lists[0].item_fields if inner.required]
    fits = [
        (action, entry)
        for action in target.actions
        if action.needs_card
        for entry in action.fields
        if entry.type == ITEMS and names and [inner.name for inner in entry.item_fields if inner.required] == names
    ]
    if len(fits) != 1:
        return None
    action, field_ = fits[0]
    # What was to be removed from the first list is not a thing to add to the other
    items = [{name: item[name] for name in names} for item in card.data[lists[0].name] if item.get(actions.CHANGE) != actions.REMOVE]
    if not items:
        return None
    return Extracted(target, action, {field_.name: items}, frozenset())


def _items_lost(card: confirm.Stored, found: Extracted) -> list[str]:
    """The items of a card that did not make it onto what replaces it for
    another task. Checked in code, whatever extraction returned."""
    entry = actions.entry(card.task)
    before = _item_names(entry.action(card.action) if entry else None, card.data)
    after = {name.lower() for name in _item_names(found.action, found.data)}
    return [name for name in before if name.lower() not in after]


def _exchanges(channel_id: int) -> list[tuple[str, str]]:
    """The last things said here, as (user, bot) pairs, for the router."""
    history = llm.history_for(channel_id)
    pairs = []
    for index in range(0, len(history) - 1, 2):
        said, answered = history[index]["content"], history[index + 1]["content"]
        if isinstance(said, str) and isinstance(answered, str):
            pairs.append((truncate(said, 200), truncate(answered, 200)))
    return pairs[-routing.EXCHANGES :]


async def _latest_bot_message_id(ctx: Context) -> int | None:
    """The id of the last thing the bot said in this channel before the user's message."""
    for message in await ctx.recent_messages(5):
        if getattr(message.author, "bot", False):
            return message.id
    return None


@dataclass(frozen=True)
class Handled:
    done: bool  # False: not for any migrated task; the caller carries on its own way
    row_id: int | None = None  # the message_log row, for a caller that carries on


async def handle(ctx: Context, capabilities: str = "", chat_here: bool = True) -> Handled:
    """Deal with a message that is no shortcut. `capabilities` is what the bot's
    shortcuts are, for chat to mention. With `chat_here` off, a message for no
    task is handed back (while tasks that aren't migrated still have the old way)."""
    entries = entries_for(ctx.user)
    if not entries:
        return Handled(False)

    # Log the raw input before anything is done with it
    row_id = await log_received(ctx.text, "chat", ctx.message_id, ctx.channel_id, user_id=ctx.user.id)
    started = time.perf_counter()
    spent = timing.current() or timing.start()
    request = Request(ctx.user, ctx.channel_id, ctx.text)
    turn = Turn()
    try:
        open_card = await confirm.latest_open(ctx.user.id, ctx.channel_id)
        if open_card is not None and actions.entry(open_card.task) not in entries:
            open_card = None
        earlier = ""
        settled = False

        # "No, 2 bread rolls" straight after a change: that change was the mistake.
        # It is undone first (the card goes back to what it was before it), and
        # the correction is applied to that, so nothing of the mistake is left
        undoing = open_card is not None and open_card.previous is not None and confirm.is_correction(ctx.text)
        on_card = None
        if open_card is not None:
            said = [line for line in open_card.said.split("\n") if line.strip()]
            on_card = OpenCard(
                open_card.action,
                open_card.previous if undoing else open_card.data,
                () if undoing else open_card.guessed,
                "\n".join(said[:-1] if undoing and len(said) > 1 else said),
                undone=said[-1] if undoing and said else "",
            )

        def corrects(found: Extracted) -> confirm.Stored | None:
            """The open card, if what was found is a correction of it: the same
            action again. That card is then replaced; anything else leaves it be."""
            if not (found.fitted and found.action.needs_card and found.action.name == open_card.action):
                return None
            # A list of items is merged into the card by the task (add, set, remove):
            # the same action again is always about that card
            if any(entry.type == ITEMS for entry in found.action.fields):
                return open_card
            # Otherwise a correction keeps what the card is about ("make it 9pm"); the
            # same action about something else altogether is a request of its own
            about = [entry for entry in found.action.fields if entry.required]
            if about and not any(_in_common(entry, found.data.get(entry.name), open_card.data.get(entry.name)) for entry in about):
                return None
            return open_card

        async def act_on_card(found: Extracted) -> None:
            """Act on what a message about the open card came to: a correction is
            built on the card as it stood (before the mistake, if one is being undone)."""
            card = corrects(found)
            if card is None:
                await act(request, found, turn)
                return
            await act(replace(request, previous=on_card.data), found, turn, replaces=card, undone=undoing)

        # "No, shopping": the request on the card was meant for another task. Only
        # the card is re-routed: the redirect's own words are never handed to
        # extraction, so they can't be saved as anything
        target = confirm.redirect(ctx.text, entries, open_card.task) if open_card is not None else None
        if target is not None:
            turn.route = costs.FOLLOW_UP
            moved = Request(ctx.user, ctx.channel_id, open_card.said)
            # As it stands on the card, corrections included: everything on it moves.
            # By code when the other task takes the same kind of item (nothing can go
            # astray, and it costs no request); otherwise extraction reads it over
            found = _carried_over(open_card, target)
            if found is None:
                standing = OpenCard(open_card.action, open_card.data, open_card.guessed, open_card.said)
                found = await extraction.extract(target, extraction.standing(standing), await _state(target, moved))
            if found.fitted:
                # Whatever was on the card and is not on the new one is said, never lost
                lost = _items_lost(open_card, found)
                if lost:
                    found = replace(found, not_included=(*found.not_included, *lost))
            takes_place = open_card if found.fitted and found.action.needs_card else None
            await act(moved, found, turn, replaces=takes_place, moved=True)
            settled = True

        # About the open card? Then its task's extraction alone, without the router
        if not settled and open_card is not None:
            latest = None if ctx.is_reply else await _latest_bot_message_id(ctx)
            sticky = confirm.sticks(open_card, utc_now(), replied_to=ctx.reply_target_id, latest_bot_message_id=latest)
            log.info(
                "Open card %s (message %s) %s: reply to %s, the bot's latest message is %s%s",
                open_card.id, open_card.message_id, "sticks" if sticky else "does not stick", ctx.reply_target_id, latest,
                "; the last change is being undone" if undoing else "",
            )
            if sticky:
                entry = actions.entry(open_card.task)
                found = await extraction.extract(entry, ctx.text, await _state(entry, request), on_card)
                if found.not_this:
                    # Not about the card after all: the router decides. The card stays as
                    # it is, and what it came from goes along in case this redirects it
                    turn.extracted.append(found.as_log())
                    earlier, on_card = open_card.said.split("\n")[0], None
                else:
                    turn.route = costs.FOLLOW_UP
                    await act_on_card(found)
                    settled = True

        # Straight after a list was shown? Then a short message is for that list's
        # task, without the router. (A card on screen comes first: it is newer.)
        shown_list = None
        if not settled and not ctx.is_reply:
            latest = await _latest_bot_message_id(ctx)
            shown_list = await livelists.by_message(latest)
            entry = actions.entry(shown_list.task) if shown_list is not None and shown_list.user_id == ctx.user.id else None
            if entry in entries and livelists.sticks(shown_list, ctx.text, utc_now(), latest):
                log.info("The %s list (message %s) is on screen: this goes to %s", shown_list.key, latest, entry.name)
                found = await extraction.extract(entry, ctx.text, await _state(entry, request), after_list=True)
                if found.not_this:
                    turn.extracted.append(found.as_log())
                else:
                    turn.route = costs.FOLLOW_UP
                    await act(request, found, turn)
                    settled = True
            else:
                shown_list = None

        if not settled:
            on_screen = confirm.on_screen(open_card) if open_card is not None else ""
            if not on_screen and shown_list is not None:
                on_screen = f"the {shown_list.task} list, just shown"
            routed = await routing.route(
                ctx.text,
                entries,
                on_screen=on_screen,
                exchanges=_exchanges(ctx.channel_id),
            )
            if routed.chat:
                if not chat_here:
                    return Handled(False, row_id)
                turn.route = costs.CHAT
                result = await llm.ask_claude(ctx.text, capabilities, ctx.channel_id, purpose=costs.PURPOSE_CHAT)
                turn.said.append(result.reply)
                await ctx.reply(result.reply)
            elif routed.chat_part:
                # The message also asked something that is for no task: every part
                # is dealt with. The answer goes first, so that a card stays the
                # last thing on screen and a correction still finds it
                result = await llm.ask_claude(routed.chat_part, capabilities, ctx.channel_id, purpose=costs.PURPOSE_CHAT)
                # The whole exchange is remembered once, at the end, not this part twice
                del llm.history_for(ctx.channel_id)[-2:]
                turn.said.append(result.reply)
                await ctx.reply(result.reply)

            if routed.chat:
                pass
            elif routed.tie:
                tied = [actions.entry(name) for name in routed.tasks]
                turn.tasks += [entry.name for entry in tied]
                await confirm.ask_which(request, tied)
                turn.said.append("asked which: " + " or ".join(entry.title for entry in tied))
            else:
                # Every task's reading first, then the cards: what one task couldn't
                # place may be exactly what another is dealing with
                readings: list[tuple[Extracted, bool]] = []
                for name in routed.tasks:
                    entry = actions.entry(name)
                    state = await _state(entry, request)
                    elsewhere = _elsewhere(name, routed.tasks, routed.chat_part)
                    # The router had the open card in view. If it chose that card's
                    # task, extraction needs the card too: "make it 2" means nothing
                    # without it. (Not if extraction has already said it isn't about it.)
                    card = on_card if open_card is not None and name == open_card.task else None
                    found = await extraction.extract(entry, ctx.text, state, card, earlier=earlier, elsewhere=elsewhere)
                    if found.not_this:
                        # A request of its own for the same task: read it afresh, and leave the card
                        turn.extracted.append(found.as_log())
                        card, found = None, await extraction.extract(entry, ctx.text, state, elsewhere=elsewhere)
                    readings.append((found, card is not None))
                everything = [found for found, _ in readings]
                for found, about_card in readings:
                    found = uncovered(found, everything, routed.chat_part)
                    if about_card:
                        await act_on_card(found)
                    else:
                        await act(request, found, turn)
    except Exception as error:
        turn.failed = True
        log.exception("Could not handle a message")
        await log_error("Message failed", repr(error), ctx.text)
        await cards.send(ctx.channel_id, Card(WENT_WRONG))

    await _finish(ctx, row_id, turn, spent, time.perf_counter() - started)
    return Handled(True, row_id)


async def _finish(ctx_or_request, row_id: int, turn: Turn, spent: timing.Turn, duration: float) -> None:
    """Record the outcome and the cost, remember the exchange, post the log card."""
    channel_id, text = ctx_or_request.channel_id, ctx_or_request.text
    reply = "\n".join(turn.said)
    calls = costs.calls_from(spent.claude_calls, costs.PURPOSE_CHAT)
    await log_result(
        row_id,
        reply=reply,
        status="error" if turn.failed else "ok",
        duration_s=duration,
        model=calls[0].model if calls else None,
        timing=json.dumps(timing.as_dict(spent, duration)),
        extracted=json.dumps(turn.extracted, ensure_ascii=False) if turn.extracted else None,
    )
    await database.record_cost(row_id, turn.route, turn.tasks, calls)
    if turn.route != costs.CHAT and text:
        # Chat remembers itself; the rest is remembered as what the bot's own code said
        llm.remember(channel_id, text, reply or "(nothing)")

    cost = sum(call.cost or 0 for call in calls)
    embed = discord.Embed(title="🧭 Message routed", colour=COLOUR_OK, timestamp=real_now_nz())
    embed.add_field(name="Input", value=truncate(text) or "(a button)", inline=False)
    embed.add_field(name="Shown", value=truncate(reply) or "(nothing)", inline=False)
    embed.add_field(name="Route", value=f"{turn.route} · {len(calls)} request(s)", inline=True)
    embed.add_field(name="Tasks", value=", ".join(dict.fromkeys(turn.tasks)) or "none", inline=True)
    embed.add_field(name="Cost", value=costs.money(cost), inline=True)
    embed.add_field(name="Time", value=f"{duration:.1f}s", inline=True)
    if turn.extracted:
        embed.add_field(name="Extracted", value=truncate(json.dumps(turn.extracted, ensure_ascii=False)), inline=False)
    await send_log(embed)


# ---------------------------------------------------------------------------
# The answer to "which is this for?"
# ---------------------------------------------------------------------------
async def on_pick(press: cards.Press) -> str | None:
    """A task was picked on a tie: extraction for that task, on what was said."""
    card_id, name = (press.arg.split(":") + [""])[:2]
    card = await database.run(confirm.db_get, int(card_id)) if card_id.isdigit() else None
    entry = actions.entry(name)
    if card is None or card.user_id != press.user.id or not card.is_open or entry is None:
        await press.update(Card(confirm.LAPSED))
        return "question had gone"
    await database.run(confirm.db_close, card.id, confirm.PICKED)
    await press.remove()

    started = time.perf_counter()
    spent = timing.start()
    request = Request(press.user, card.channel_id, card.said)
    turn = Turn(route=costs.FOLLOW_UP)
    found = await extraction.extract(entry, card.said, await _state(entry, request))
    await act(request, found, turn)
    timing.stop()
    # The press is logged by core/cards.py; what it cost goes on that row
    if press.row_id is not None:
        calls = costs.calls_from(spent.claude_calls, costs.PURPOSE_EXTRACTION)
        await database.record_cost(press.row_id, turn.route, turn.tasks, calls)
        await log_result(press.row_id, extracted=json.dumps(turn.extracted, ensure_ascii=False), duration_s=time.perf_counter() - started)
    llm.remember(card.channel_id, card.said, "\n".join(turn.said) or "(nothing)")
    return f"picked {name}: " + "\n".join(turn.said)


def setup() -> None:
    confirm.setup()
    cards.register(confirm.CARDS, "pick", on_pick)
