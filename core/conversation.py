import json
import logging
import time
from dataclasses import dataclass, field

import discord

from core import actions, cards, confirm, costs, database, extraction, llm, routing, timing
from core.actions import Entry, Request
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


async def act(request: Request, found: Extracted, turn: Turn, replaces: confirm.Stored | None = None) -> None:
    """Do what extraction found, in the task's own code, and show the result:
    a confirm card for an action that needs one, otherwise the task's reply."""
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
            await confirm.show(request, entry, action.name, proposal, found.guessed, replaces)
            turn.said.append(f"card: {entry.name} · {proposal.kind}: " + " / ".join(proposal.lines))
        else:
            await say(await action.run(request, found.data, found.guessed))
    except UserError as error:
        # The task's own words for a problem the user can fix
        turn.failed = True
        await say(f"⚠️ {error}")
    except Exception as error:
        turn.failed = True
        log.exception("Action %s failed", action.name)
        await log_error(f"Action failed: {action.name}", repr(error), request.text)
        await say(WENT_WRONG)


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
        replaces = None
        earlier = ""
        settled = False

        # About the open card? Then its task's extraction alone, without the router
        if open_card is not None and actions.entry(open_card.task) in entries:
            sticky = confirm.sticks(
                open_card,
                utc_now(),
                replied_to=ctx.reply_target_id,
                latest_bot_message_id=None if ctx.is_reply else await _latest_bot_message_id(ctx),
            )
            if sticky:
                entry = actions.entry(open_card.task)
                card = OpenCard(open_card.action, open_card.data, open_card.guessed, open_card.said)
                found = await extraction.extract(entry, ctx.text, await _state(entry, request), card)
                if found.not_this:
                    # A different task after all ("no, shopping"): what comes next takes the card's place
                    turn.extracted.append(found.as_log())
                    replaces, earlier = open_card, open_card.said
                else:
                    turn.route = costs.FOLLOW_UP
                    await act(request, found, turn, replaces=open_card if found.fitted and found.action.needs_card else None)
                    settled = True

        if not settled:
            routed = await routing.route(
                ctx.text,
                entries,
                on_screen=confirm.on_screen(open_card) if open_card is not None else "",
                exchanges=_exchanges(ctx.channel_id),
            )
            if routed.chat:
                if not chat_here:
                    return Handled(False, row_id)
                turn.route = costs.CHAT
                result = await llm.ask_claude(ctx.text, capabilities, ctx.channel_id, purpose=costs.PURPOSE_CHAT)
                turn.said.append(result.reply)
                await ctx.reply(result.reply)
            elif routed.tie:
                tied = [actions.entry(name) for name in routed.tasks]
                turn.tasks += [entry.name for entry in tied]
                await confirm.ask_which(request, tied)
                turn.said.append("asked which: " + " or ".join(entry.title for entry in tied))
            else:
                for index, name in enumerate(routed.tasks):
                    entry = actions.entry(name)
                    found = await extraction.extract(entry, ctx.text, await _state(entry, request), earlier=earlier)
                    takes_place = replaces if index == 0 and found.fitted and found.action.needs_card else None
                    await act(request, found, turn, replaces=takes_place)
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
