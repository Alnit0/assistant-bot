import logging
from dataclasses import dataclass, field
from datetime import datetime

from core import confirmations, database, llm, pending, tools
from core.config import ASSISTANT_NAME, STRICT_TOOLS
from core.context import Context
from core.database import log_received, log_result
from core.discord_utils import log_error
from core.protection import protection
from core.clock import real_now
from tasks import registry
from tasks.base import Param

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Tool calls from Claude: deciding what may run, and when.
#
# Claude is given the registry's actions as tools (registry.tools_for). When it
# calls one, this file decides how it ends:
#   - a destructive action always waits for Confirm / Cancel buttons
#   - a proposal (something Claude suggests unasked) waits for a short "ok"
#   - an action on a message the user didn't reply to shows that message
#     quoted, with an Undo button if it can be taken back
#   - an action on a message found further back (search_messages) shows it
#     quoted and asks first: a match from weeks ago is easier to get wrong
#   - several messages that could be meant are offered as buttons
#   - calls marked as candidates (tools of different tasks that fit the request
#     equally) are held until the round ends, then offered as one button per
#     task; the one picked runs with the input Claude gave it
#   - everything else runs at once
#
# What is kept to run later (a proposal, a button) is always the call itself:
# the tool and its structured input, never the user's words. And the user is
# never shown a tool's name or its arguments: a word is shown as it would be
# typed (`timer 5m tea`), a task's own tool by its label ("add a pill").
# Running is the registry's job (registry.run_tool), down the same path as a
# typed word, so every call is logged the same way.
#
# This is not a task (no folder, no words of its own): it sits beside the
# registry because, unlike core/, it may use it.
# ---------------------------------------------------------------------------
RECENT = "recent_messages"
SEARCH = "search_messages"
PREVIEW_SECONDS = 15  # how long a confirmation that quotes its target stays

RECENT_SPEC = tools.ToolSpec(
    name=RECENT,
    description=(
        f"List the last {tools.LISTING_LIMIT} messages in this channel, newest first, each with a ref. "
        "Use it to find the message the user means when they did not reply to it, then pass its ref "
        f"as a target. If the message is not among them, {SEARCH} looks further back."
    ),
    schema=tools.build_schema(),
    kind=tools.HELPER,
    reads_only=True,
)
SEARCH_SPEC = tools.ToolSpec(
    name=SEARCH,
    description=(
        f"Look further back than {RECENT} for a message the user sent in this channel: their last "
        f"{tools.SEARCH_ROWS} messages, up to {tools.SEARCH_DAYS} days old. Use it when the message is not in "
        f"{RECENT}, or the user says to look further back. Give the words the message would contain, "
        'e.g. "capital Spain". It returns the best matches with refs to pass as a target; the user is '
        "shown the message quoted and asked to confirm before anything is done to it. Only the user's "
        "own messages are found, not the bot's replies."
    ),
    schema=tools.build_schema(
        [Param("query", "Words the message would contain, e.g. capital Spain. Not a sentence about it.")]
    ),
    kind=tools.HELPER,
    has_arguments=True,
    reads_only=True,
)

WAITING_FOR_CONFIRM = (
    "Not done yet: the user has been asked to confirm with Confirm / Cancel buttons. "
    "Tell them it is waiting for their confirmation; do not say it has been done."
)
WAITING_FOR_CHOICE = (
    "Not done yet: more than one message could be meant, so the user has been asked to pick one "
    "with buttons. Tell them to choose; do not say it has been done."
)


@dataclass
class Turn:
    """One chat message being answered: the tools on offer and what has been listed."""

    ctx: Context
    specs: dict[str, tools.ToolSpec]
    definitions: list[dict]  # as sent to the API
    strict: set[str]
    listing: dict[str, object] = field(default_factory=dict)  # ref -> message, from recent_messages
    older: set[str] = field(default_factory=set)  # the refs that came from search_messages
    acted: bool = False  # a tool has carried something out for this message (reading doesn't count)
    # Whether Claude still has to speak. A call that acted and showed the user its
    # own confirmation is settled; anything else (a read, a failure, a question
    # with buttons, a proposal) leaves the round open for Claude to put into words
    settled: list[llm.Closing] = field(default_factory=list)
    open: bool = False  # this round
    troubled: bool = False  # a call has failed at some point in the turn: Claude explains
    _shown: llm.Closing | None = None  # set by the call being run, if it settled itself
    # Calls Claude marked as candidates this round: held, then offered as buttons (end_round)
    candidates: list = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return list(self.specs)


@dataclass(frozen=True)
class Call:
    """A tool call that is ready to run (kept while it waits for an "ok")."""

    spec: tools.ToolSpec
    value: dict
    target: object = None  # the message a reply action acts on
    explicit: bool = True  # False if the user did not reply to the target themselves
    older: bool = False  # the target was found further back: ask before acting on it


_warned: set[tuple] = set()


async def prepare(ctx: Context) -> Turn:
    """Gather the tools Claude may use for this message."""
    specs = registry.tools_for(ctx.user, ctx.channel_id)
    if any(spec.kind == tools.REPLY_ACTION for spec in specs):
        # Message actions need a way to find the message when the user didn't reply to it
        specs = [*specs, SEARCH_SPEC, RECENT_SPEC]
    # Strict schemas are slow (core/config.py); input is checked in execute() regardless
    strict, overflow = tools.choose_strict(specs) if STRICT_TOOLS else (set(), [])
    definitions = [tools.api_definition(spec, spec.name in strict) for spec in specs]
    if definitions:
        # Cache everything up to and including the last tool definition
        definitions[-1] = {**definitions[-1], "cache_control": llm.CACHED}

    key = tuple(overflow)
    if overflow and key not in _warned:
        _warned.add(key)
        log.warning("More tools with arguments than can be strict: %s", ", ".join(overflow))
        await log_error(
            "Too many strict tools",
            f"{len(strict) + len(overflow)} tools with arguments are on offer here, and the API accepts "
            f"{tools.STRICT_LIMIT} strict ones per request. Sent without strict (their input is still "
            f"checked in code): {', '.join(overflow)}. Raise `tool_priority` on the ones that matter most.",
        )
    return Turn(ctx, {spec.name: spec for spec in specs}, definitions, strict)


# ---------------------------------------------------------------------------
# What the user is shown
# ---------------------------------------------------------------------------
def describe(call: Call) -> str:
    """A call in words the user knows: "`timer 5m tea`" (what they could type),
    "`archive` that message", or a task's own tool by its label ("add a pill").
    Never a tool's name or its arguments."""
    if call.spec.kind == tools.BESPOKE:
        return call.spec.item.label
    command = tools.command_text(call.spec.item.name, tools.to_args(call.spec.item.params, call.value))
    return f"`{command}`" + (" that message" if call.target is not None else "")


def candidate_label(call: Call) -> str:
    """A candidate on its button: the task, and what it would do ("Pills: add a pill")."""
    return f"{call.spec.task.capitalize()}: {describe(call).strip('`')}"[:80]


def _quote(message) -> tuple[str, str | None]:
    return tools.preview(getattr(message, "content", None)), getattr(message, "jump_url", None)


async def _tags(message) -> tuple[str, ...]:
    tags = []
    reason = protection(message)
    if reason:
        tags.append(reason)
    declared = await registry.declared_class(message.id)
    if declared is not None:
        tags.append({"Live": "timer or session card", "Alert": "alert"}.get(declared.value, declared.value))
    if getattr(message, "attachments", None):
        tags.append("has files")
    return tuple(tags)


async def _list_recent(turn: Turn) -> str:
    messages = await turn.ctx.recent_messages(tools.LISTING_LIMIT)
    recent = {f"m{number}": message for number, message in enumerate(messages, start=1)}
    # Anything already found further back keeps its ref
    turn.listing = {**recent, **{ref: turn.listing[ref] for ref in turn.older}}
    entries = [
        tools.Listed(ref, message.author.display_name, message.created_at, message.content, await _tags(message))
        for ref, message in recent.items()
    ]
    return tools.listing_text(entries, real_now())


async def _search(turn: Turn, query: str) -> str:
    """Look through the user's logged messages in this channel for ones the query
    fits, keep those that still exist, and list them with refs (s1, s2, ...)."""
    ctx = turn.ctx
    rows = [
        tools.Logged(message_id, content or "", datetime.fromisoformat(received_at))
        for message_id, content, received_at in await database.recent_log(ctx.channel_id, ctx.user.id, tools.SEARCH_ROWS)
    ]
    skip = frozenset({ctx.message_id} if ctx.message_id is not None else ())
    matches = tools.find_logged(rows, query, real_now(), skip=skip)

    found = []
    # A logged message may have been archived or deleted since: only offer what is there.
    # A few more than are shown get looked up, to allow for that
    for row in matches[: tools.SEARCH_RESULTS * 2]:
        message = await ctx.fetch_message(row.message_id)
        if message is not None:
            found.append(message)
        if len(found) == tools.SEARCH_RESULTS:
            break
    if not found:
        return (
            f"Nothing the user sent in this channel in the last {tools.SEARCH_DAYS} days fits those words "
            "(or it has since been archived or deleted). Say so; they can reply to the message itself instead."
        )
    turn.listing = {ref: message for ref, message in turn.listing.items() if ref not in turn.older}
    turn.older = {f"s{number}" for number in range(1, len(found) + 1)}
    turn.listing.update({f"s{number}": message for number, message in enumerate(found, start=1)})
    entries = [
        tools.Listed(ref, message.author.display_name, message.created_at, message.content, await _tags(message))
        for ref, message in turn.listing.items()
        if ref in turn.older
    ]
    return tools.listing_text(entries, real_now(), tools.OLDER_HEADER)


# ---------------------------------------------------------------------------
# Running a call, with whatever has to come first
# ---------------------------------------------------------------------------
async def _perform(ctx: Context, call: Call, turn: Turn | None = None) -> tuple[str, bool]:
    """Run a call now. Returns (what happened, whether it failed)."""
    quoted = call.target is not None and not call.explicit
    outcome = await registry.run_tool(ctx, call.spec, call.value, call.target, collect=quoted)
    if outcome.status != "ok":
        return outcome.text, True
    if turn is not None and not call.spec.reads_only:
        turn.acted = True
        if quoted or outcome.posted:
            # The user can see what happened: nothing more needs saying
            turn._shown = llm.Closing("", f"That ran: {outcome.text or describe(call)}.")
        elif outcome.told:
            # A task's own tool posts nothing: what it confirmed is the reply
            turn._shown = llm.Closing("\n".join(outcome.told), "\n".join(outcome.told))
    if quoted:
        # The user didn't point at the message themselves: show which one it was
        shown = outcome.confirmations[-1] if outcome.confirmations else f"✅ Done: {call.spec.item.name}"
        text = tools.confirmation_text(shown, *_quote(call.target))
        if call.spec.item.undo is not None:

            async def undo() -> str:
                undone = await registry.run_undo(ctx, call.spec, call.target)
                return undone.text if undone.status == "ok" else f"⚠️ {undone.text}"

            await confirmations.offer_undo(ctx.channel, ctx.user, text, undo)
        else:
            await ctx.note(text, PREVIEW_SECONDS)
    return outcome.text or "done", False


async def _confirmed(ctx: Context, call: Call) -> str:
    """What a Confirm or a candidate button runs: the short text to show afterwards."""
    text, failed = await _perform(ctx, call)
    if failed:
        return f"⚠️ {text}"
    return f"✅ Done: {describe(call)}"


async def _dispatch(ctx: Context, call: Call, turn: Turn | None = None) -> tuple[str, bool]:
    """Decide how a valid call ends: buttons, a proposal, or straight away."""
    item = call.spec.item
    if call.spec.destructive or call.older:
        quoted, link = _quote(call.target) if call.target is not None else (None, None)
        found = "" if call.spec.destructive else "Found further back. "
        question = tools.question_text(
            f"{found}{ASSISTANT_NAME} wants to run {describe(call)} ({item.description}).", quoted, link
        )

        async def confirmed() -> str:
            return await _confirmed(ctx, call)

        await confirmations.ask(ctx.channel, ctx.user, question, confirmed)
        return WAITING_FOR_CONFIRM, False

    if call.value.get(tools.PROPOSE):
        pending.propose(ctx.channel_id, ctx.user.id, call, describe(call))
        return (
            f"Proposed, not done: {describe(call)}. It runs if the user replies ok within "
            f"{pending.EXPIRY_SECONDS // 60} minutes. Tell them briefly what you propose and that "
            "they can reply ok.",
            False,
        )
    return await _perform(ctx, call, turn)


async def _ask_which(turn: Turn, spec: tools.ToolSpec, value: dict, refs: list[str]) -> None:
    lines = [f"Which message should I `{spec.item.name}`?"]
    options = []
    for number, ref in enumerate(refs, start=1):
        message = turn.listing[ref]
        quoted, link = _quote(message)
        lines.append(f"**{number}.** > {quoted}" + (f" · {link}" if link else ""))
        # Picking a message is the user's go-ahead, so a proposal needs no further "ok"
        chosen = {**value, tools.PROPOSE: False} if tools.PROPOSE in value else value
        call = Call(spec, chosen, message, explicit=False)

        async def picked(call: Call = call) -> str:
            # Picking a message is not agreeing to destroy it: that still asks
            text, failed = await _dispatch(turn.ctx, call)
            if failed:
                return f"⚠️ {text}"
            return "Asked you to confirm below." if call.spec.destructive else f"✅ Done: {describe(call)}"

        options.append((str(number), picked))
    await confirmations.choose(turn.ctx.channel, turn.ctx.user, "\n".join(lines), options)


HELD = (
    "Held, not done: once you have named every candidate, the user is shown a button for each task "
    "and the one they pick runs. Say nothing has been done."
)
ASKED_WHICH_TASK = "Asked which was meant: {names}. Nothing has been done; the one picked from the buttons runs."


async def execute(turn: Turn, name: str, value: dict) -> tuple[str, bool]:
    """Handle one tool call from Claude. Returns (the result for Claude, whether it is an error).

    Never raises for something Claude or the user can put right: the reason
    is the result, so Claude can explain it. Also notes whether the call
    settled itself or leaves Claude something to say (see closing()).
    """
    turn._shown = None
    held = len(turn.candidates)
    text, failed = await _execute(turn, name, value)
    if len(turn.candidates) > held:
        return text, failed  # decided when the round ends (end_round)
    if failed:
        turn.troubled = True
    if failed or turn._shown is None:
        turn.open = True
    else:
        turn.settled.append(turn._shown)
    return text, failed


def closing(turn: Turn) -> llm.Closing | None:
    """After a round of calls: can the turn end here, without asking Claude for a
    closing reply? Only if every call of the round acted and showed the user its
    own confirmation, and nothing has failed. Returns what to say (often
    nothing: the tool's own message is there) and what to remember, or None to
    carry on to Claude."""
    settled, was_open = turn.settled, turn.open
    turn.settled, turn.open = [], False
    if was_open or turn.troubled or not settled:
        return None
    return llm.Closing(
        "\n".join(entry.say for entry in settled if entry.say),
        "\n".join(entry.remember for entry in settled),
    )


async def end_round(turn: Turn) -> llm.Closing | None:
    """After a round of calls: deal with any candidates, then say whether the turn
    can end here (closing()).

    Two or more candidates become one question, a button per task; the pick
    runs that call with the input Claude gave it. A single one was no choice at
    all, so it simply runs.
    """
    held, turn.candidates = turn.candidates, []
    if len(held) == 1:
        turn._shown = None
        text, failed = await _dispatch(turn.ctx, held[0], turn)
        if failed:
            turn.troubled = True
            turn.settled.append(llm.Closing(f"⚠️ {text}", f"That didn't work: {text[:200]}"))
        else:
            turn.settled.append(turn._shown or llm.Closing(text, text))
    elif held:
        options = []
        for call in held:

            async def picked(call: Call = call) -> str:
                text, failed = await _dispatch(turn.ctx, call)
                if failed:
                    return f"⚠️ {text}"
                return "Asked you to confirm below." if call.spec.destructive else f"✅ {describe(call).strip('`')}"

            options.append((candidate_label(call), picked))
        names = " or ".join(label for label, _ in options)
        await confirmations.choose(turn.ctx.channel, turn.ctx.user, "Which do you mean?", options)
        turn.settled.append(llm.Closing("", ASKED_WHICH_TASK.format(names=names)))
    return closing(turn)


async def _execute(turn: Turn, name: str, value: dict) -> tuple[str, bool]:
    ctx = turn.ctx
    spec = turn.specs.get(name)
    if spec is None:
        return await _refused(ctx, name, value, f"There is no tool called `{name}` here.")
    if isinstance(value, dict):
        # A flag the tool doesn't take, set to "no", says nothing: a tool that asks
        # the user itself has no `propose` to be false
        value = {
            key: given
            for key, given in value.items()
            if not (key in (tools.PROPOSE, tools.CANDIDATE) and key not in spec.schema["properties"] and given is False)
        }
    checked = value
    if isinstance(value, dict) and tools.CANDIDATE in spec.schema["properties"]:
        checked = {tools.CANDIDATE: False, **value}  # left out means no
    problems = tools.validate(spec.schema, checked)
    if problems:
        return await _refused(ctx, name, value, "Invalid input: " + "; ".join(problems) + ".")
    if spec.kind == tools.HELPER:
        if name == SEARCH:
            return await _search(turn, value["query"]), False
        return await _list_recent(turn), False

    target, explicit, older = None, True, False
    if spec.kind == tools.REPLY_ACTION:
        resolution = tools.resolve_targets(ctx.is_reply, value.get(tools.TARGETS, []), set(turn.listing))
        if resolution.kind == tools.ERROR:
            return await _refused(ctx, name, value, resolution.error)
        if resolution.kind == tools.MANY:
            await _ask_which(turn, spec, value, resolution.refs)
            return WAITING_FOR_CHOICE, False
        if resolution.kind == tools.REPLY:
            # A reply always wins, whatever message Claude named
            target = await ctx.fetch_reply_target()
            if target is None:
                return await _refused(ctx, name, value, "I can't find the message the user replied to.")
        else:
            ref = resolution.refs[0]
            target, explicit, older = turn.listing[ref], False, ref in turn.older
    call = Call(spec, value, target, explicit, older)
    if value.get(tools.CANDIDATE):
        # Kept as it is, structured input and all, with the flag put down: picking it is the go-ahead
        turn.candidates.append(Call(spec, {**value, tools.CANDIDATE: False}, target, explicit, older))
        return HELD, False
    return await _dispatch(ctx, call, turn)


async def _refused(ctx: Context, name: str, value: dict, reason: str) -> tuple[str, bool]:
    """A call that can't run at all (unknown tool, bad input, no target): logged, then
    handed back to Claude as an error."""
    row_id = await log_received(f"tool: {name} {value}", "tool", ctx.message_id, ctx.channel_id, user_id=ctx.user.id)
    await log_result(row_id, status="error", error=reason)
    log.info("Tool call refused: %s: %s", name, reason)
    return reason, True


# ---------------------------------------------------------------------------
# "ok" to a proposal
# ---------------------------------------------------------------------------
async def answer_pending(ctx: Context) -> bool:
    """Deal with a short answer to something Claude proposed. Returns True if the
    message was that answer (so it should not go to Claude).

    Anything other than a clear yes or no drops the proposal: the user has
    moved on, and the message is ordinary chat.
    """
    answer = pending.classify(ctx.text)
    proposal = pending.take(ctx.channel_id, ctx.user.id)
    if proposal is None or answer is None:
        return False

    row_id = await log_received(ctx.text, "confirmation", ctx.message_id, ctx.channel_id, user_id=ctx.user.id)
    if answer == pending.NO:
        await ctx.note(f"👌 Left it: {proposal.summary}")
        await log_result(row_id, reply=f"declined: {proposal.summary}", status="ok")
        # Plain sentences: a bracketed note in its own voice is something Claude copies
        llm.remember(ctx.channel_id, ctx.text, f"Left it: I have not run {proposal.summary}.")
        return True

    text, failed = await _perform(ctx, proposal.call)
    if failed:
        await ctx.reply(f"⚠️ {text}")
    await log_result(row_id, reply=f"agreed: {proposal.summary}: {text}", status="error" if failed else "ok")
    said = f"That didn't work: {text[:200]}" if failed else f"You said ok, so I went ahead: {proposal.summary}."
    llm.remember(ctx.channel_id, ctx.text, said)
    return True
