import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic, Timeout

from core import costs, timing
from core.config import (
    ANTHROPIC_API_KEY,
    ASSISTANT_NAME,
    CLAUDE_CONNECT_TIMEOUT,
    CLAUDE_MODEL,
    CLAUDE_RETRIES,
    CLAUDE_TIMEOUT,
    MAX_HISTORY,
    MAX_TOKENS,
    MAX_TOOL_CALLS,
    MODEL_PRICING,
    now_nz,
)

log = logging.getLogger("assistant")

# A short timeout: a request that hangs is given up and retried, not waited ten
# minutes for (the SDK's default). Retries show in the log and on the #bot-log card
claude = AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=Timeout(CLAUDE_TIMEOUT, connect=CLAUDE_CONNECT_TIMEOUT),
    max_retries=CLAUDE_RETRIES,
)

# Short-term conversation memory, one separate history per channel, so a chat
# in one channel never leaks into another. Cleared when the bot restarts.
# Only plain text is kept, exactly as it was said: tool calls live within one
# turn, so trimming can never split a call from its result, and nothing is
# added to a reply that Claude could take for its own words and copy.
_histories: dict[int | None, list[dict]] = {}

# Cached input is cheaper to read and dearer to write than ordinary input
CACHE_READ_PRICE, CACHE_WRITE_PRICE = costs.CACHE_READ_PRICE, costs.CACHE_WRITE_PRICE
CACHED = {"type": "ephemeral"}

LIMIT_REACHED = (
    f"Not run: at most {MAX_TOOL_CALLS} tool calls are allowed per message. Tell the user what was "
    "done and what is left for them to ask for again."
)


def history_for(channel_id: int | None) -> list[dict]:
    """The conversation history for one channel (created empty on first use)."""
    return _histories.setdefault(channel_id, [])


def clear_history(channel_id: int | None) -> None:
    """Forget the conversation in one channel. Other channels are untouched."""
    history_for(channel_id).clear()


def remember(channel_id: int | None, user_text: str, assistant_text: str) -> None:
    """Add an exchange that didn't go through Claude (an "ok" that ran a proposal),
    so the conversation still makes sense to it afterwards."""
    history = history_for(channel_id)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})


# ---------------------------------------------------------------------------
# The system prompt. Everything that stays the same from message to message
# comes first, so it can be cached; the time, which changes, comes after.
# ---------------------------------------------------------------------------
def _stable_prompt(capabilities: str, has_tools: bool) -> str:
    prompt = (
        f"You are {ASSISTANT_NAME}, a personal assistant for Alex, chatting through Discord. "
        "Alex lives in Auckland, New Zealand. "
        "Use UK spelling. Keep replies short and conversational, suited to reading on a phone. "
        "Use simple Discord markdown (bold, short bullet lists) only when it genuinely helps."
    )
    if has_tools:
        prompt += (
            "\n\nYou can act through the tools you have been given: each one runs an action of the "
            "Discord bot you speak through. For every message, decide whether to simply answer, "
            "call one or more tools, ask a clarifying question, or propose something.\n"
            "- When the user clearly asks for something a tool does, call it straight away with "
            "propose set to false. Do not ask for permission first.\n"
            "- When you are unsure what they want, or an argument is missing, ask a short question "
            "instead of guessing.\n"
            "- When you are suggesting something they did not ask for, call the tool with propose "
            "set to true, tell them briefly what you propose and that they can reply ok. Nothing "
            "happens until they do. A proposal exists only if you made that call: never write "
            "\"I'm proposing\" or \"reply ok\" without it, and never for something the user asked for.\n"
            "- One confirmation, never two. A tool with no propose argument shows the user its own "
            "preview or question with buttons (Save, Confirm): call it straight away, whether they "
            "asked or you are suggesting, and let its buttons be the confirmation.\n"
            "- The candidate rule. Choose the task from the channel, the recent conversation, the "
            "user's existing data in the live state, and their wording. If tools of different tasks "
            "still fit equally (\"add milk\" could be a pill or something else) do not guess: call "
            "each of them once in the same response with candidate set to true and its full "
            "arguments. The user gets one button per task and the one they pick runs. Otherwise "
            "candidate is always false.\n"
            "- Never say that something has been done, started, changed or cancelled unless a tool "
            "you called for this very message returned success. Earlier messages are not evidence: "
            "if you did not call the tool this time, it has not happened. A result that says it is "
            "waiting (for ok, for Confirm, or for the user to pick a message) means it has not "
            "happened yet: say so.\n"
            "- To act, call the tool. Never write a tool call, a tool result or a bracketed note "
            "about tools as text in a reply, and never name a tool or its arguments to the user: "
            "they know what they can type and what the buttons say, nothing else.\n"
            "- Write times of day as 8:00 pm, never 20:00, whatever form the user used.\n"
            "- Each message from the user ends with a note from the bot, which the user did not "
            "write and cannot see: the time now, and the live state (what is running, how long is "
            "left, with ids), read at that moment. For anything that changes by itself, use that "
            "note: answer from it and take ids from it. Never use an earlier message for this, "
            "it is out of date. If what you need is not in the note, call the tool that reads it. "
            "Do not mention the note, or bring up what is in it, unless the user's message is "
            "about that; ids are for your tool calls, not for the user.\n"
            "- Put every action the user asked for in ONE response, as tool calls side by side. "
            "When they succeed, the user is shown each tool's own confirmation and the turn ends "
            "there: you get no further say and no further calls. Only if a call fails, waits, or "
            "just read something are you asked to reply.\n"
            "- Never claim or offer to do something you have no tool for. If a word the user can "
            "type would do it, tell them what to type; otherwise say you can't.\n"
            "- If a tool fails, explain why in plain words and what they could do about it.\n"
            "- Tools that act on a message: if the user's message is a reply, leave targets empty "
            "and the message they replied to is used. Otherwise call recent_messages, then give "
            "the ref of the message they mean; if more than one fits, give each and the user is "
            "asked to pick. Never guess between them. If it is not among those, call "
            "search_messages to look further back.\n"
            f"- You may make at most {MAX_TOOL_CALLS} tool calls for one message.\n"
            "The tool has usually shown its own result in the channel, so keep your reply to a "
            "line and do not repeat what it showed."
        )
    else:
        # Said whenever there are no tools: Claude can then only talk
        prompt += (
            "\n\nYou have no tools yet. You cannot run commands or take any action yourself: you "
            "cannot set timers or reminders, pin, archive or delete messages, look anything up "
            "or remember anything beyond this chat, and a message that reaches you did not "
            "trigger anything. Never offer to perform an action, and never say or imply that "
            "you have done one."
        )
    if capabilities and has_tools:
        prompt += (
            "\n\nThe user can also trigger the bot's built-in shortcuts themselves, as listed "
            "below. Mention them when they ask what you can do (`help` shows the full list). "
            "Reactions are theirs alone: you cannot add one, so say which to add.\n\n"
            f"{capabilities}"
        )
    elif capabilities:
        prompt += (
            "\n\nThe Discord bot you speak through does have built-in shortcuts, listed "
            "below, which the user triggers themselves. If the user asks what you can do, or "
            "asks for something on this list, tell them exactly what to type or do (and that "
            "`help` shows the full list). Do not claim abilities that are neither listed "
            "here nor part of ordinary conversation.\n\n"
            f"{capabilities}"
        )
    return prompt


def _time_line() -> str:
    return f"The current date and time in Auckland is {now_nz().strftime('%A %d %B %Y, %I:%M %p')}."


NOTE_OPENS = "[Note from the bot, not written by the user and not shown to them]"


def turn_note(state: str = "") -> str:
    """What changes from message to message, sent after the user's words in the
    latest turn only: the time, and the tasks' live state (registry.live_state).
    It is never part of the system prompt or the history, so those stay the
    same, byte for byte, and cached."""
    lines = [NOTE_OPENS, _time_line()]
    if state:
        lines += ["Live state, read just now:", state]
    return "\n".join(lines)


def build_system_blocks(capabilities: str = "", has_tools: bool = False) -> list[dict]:
    """The system prompt as the API takes it: one block, the same for every
    message, marked for caching. Nothing that changes goes in it (see turn_note)."""
    return [{"type": "text", "text": _stable_prompt(capabilities, has_tools), "cache_control": CACHED}]


def build_system_prompt(capabilities: str = "", has_tools: bool = False) -> str:
    """The system prompt as one text. `capabilities` is the list of things the bot
    itself can do for this user in this channel (from the task registry), so Claude
    can answer "what can you do?" accurately. `has_tools` says whether it has been
    given tools to act with."""
    return "\n\n".join(block["text"] for block in build_system_blocks(capabilities, has_tools))


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
def estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0, cache_write_tokens: int = 0
) -> float | None:
    """Estimate the cost of a request in USD, or None if the model's price is unknown."""
    return costs.price(model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)


def format_cost(cost: float | None) -> str:
    return f"US${cost:.4f}" if cost is not None else "Unknown"


_tool_tokens: dict[tuple, int | None] = {}


async def count_tool_tokens(tools: list[dict]) -> int | None:
    """How many input tokens a set of tool definitions adds to every request.

    Asked of the API once per distinct set (a free call), then remembered.
    None if it couldn't be counted.
    """
    if not tools:
        return 0
    key = tuple((tool["name"], bool(tool.get("strict"))) for tool in tools)
    if key not in _tool_tokens:
        probe = [{"role": "user", "content": "x"}]
        try:
            with_tools = await claude.messages.count_tokens(model=CLAUDE_MODEL, messages=probe, tools=tools)
            without = await claude.messages.count_tokens(model=CLAUDE_MODEL, messages=probe)
            _tool_tokens[key] = with_tools.input_tokens - without.input_tokens
        except Exception as error:
            log.warning("Could not count the tokens of the tool definitions: %s", error)
            return None
    return _tool_tokens[key]


# ---------------------------------------------------------------------------
# One request that must come back as a tool call (the router, extraction)
# ---------------------------------------------------------------------------
async def call_tool(
    system: list[dict],
    user: str,
    tools: list[dict],
    *,
    choice: dict,
    purpose: str,
    task: str = "",
    max_tokens: int = 600,
) -> tuple[str, dict] | None:
    """Send one message with tools Claude must choose from, and return the call
    it made as (tool name, input). None if it made none (cut short, refused).

    Nothing Claude writes as text is read, kept or shown. The request is
    timed and counted under `purpose` (and `task`), for the cost log.
    """
    asked, retried = time.perf_counter(), timing.claude_retries()
    response = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=tools,
        tool_choice=choice,
    )
    usage = response.usage
    timing.record_claude(
        time.perf_counter() - asked,
        CLAUDE_MODEL,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", None) or 0,
        getattr(usage, "cache_creation_input_tokens", None) or 0,
        retries=timing.claude_retries() - retried,
        purpose=purpose,
        task=task,
    )
    if response.stop_reason != "tool_use":
        # Cut short or refused: half a call must never be acted on
        log.warning("A %s request ended with %s and no tool call", purpose, response.stop_reason)
        return None
    for block in response.content:
        if block.type == "tool_use":
            return block.name, dict(block.input) if isinstance(block.input, dict) else {}
    return None


# ---------------------------------------------------------------------------
# Asking Claude, and running the tools it calls
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict
    result: str
    is_error: bool


@dataclass
class ChatResult:
    reply: str
    # Set when the reply said something was done and no tool had done it: what
    # Claude first wrote, before it was told so and answered again
    unbacked_claim: str = ""
    input_tokens: int = 0  # not counting what was read from or written to the cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)


    # The turn ended with the tools' own confirmations, without a closing reply from Claude
    closed_by_tools: bool = False


@dataclass(frozen=True)
class Closing:
    """How a turn ends when the tools have already told the user what happened."""

    say: str  # anything still to send (empty when the tool's own message is in the channel)
    remember: str  # what goes in the history as the assistant's turn, in plain words


# `async (name, input) -> (text for Claude, is it an error)`
ToolRunner = Callable[[str, dict], Awaitable[tuple[str, bool]]]


def _text_of(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


# ---------------------------------------------------------------------------
# Honesty. Claude must not say a thing was done when no tool did it. The
# prompt says so; these catch it when it happens anyway.
# ---------------------------------------------------------------------------
# A bracketed note about tools, written as if it were part of the reply
_TOOL_NOTE = re.compile(r"[ \t]*\[\s*tools?\b[^\]\n]*\]?[ \t]*", re.IGNORECASE)
# A reply that opens by saying it is done: "Done.", "✅ Done", "All done", "That's done"
_DONE_CLAIM = re.compile(
    r"^\W*(?:(?:all|that'?s|it'?s|that is|it is)\s+)?done\b|^\s*✅|^\W*that (?:ran|has run|was run)\b"
    r"|\bso I went ahead\b",
    re.IGNORECASE,
)
# A proposal written as words: "I'm proposing…", "Reply ok to save it"
_PROPOSAL_CLAIM = re.compile(
    r"\bI(?:'m|’m| am) proposing\b|\b(?:reply|say|answer|type|send)(?: with)? [`\"“'*]*ok\b", re.IGNORECASE
)

# A reply that says a change was made: in the first person ("I've paused"), or as
# news ("running again", "is now paused", "has been stopped", "all three paused").
# Saying how things are ("tea is paused, 9m left") is not one
_ACTIONS = (
    "paused|resumed|unpaused|started|restarted|cancelled|canceled|stopped|pinned|unpinned|archived|"
    "deleted|extended|added|dismissed|skipped|switched|turned|set|cleared|reset"
)
_CHANGE_CLAIM = re.compile(
    rf"\bI(?:'ve|’ve| have)? (?:just |now |already )?(?:{_ACTIONS})\b"
    r"|\b(?:running|going|paused|started|pinned|on|off) again\b"
    r"|(?:\b(?:is|are)|'s|’s|'re|’re) now (?:running|paused|going|pinned|unpinned|archived|cancelled|stopped|on|off)\b"
    rf"|(?:\b(?:has|have)|'s|’s|'ve|’ve) been (?:{_ACTIONS})\b"
    r"|\ball (?:\w+ )?(?:paused|resumed|cancelled|stopped|started)\b",
    re.IGNORECASE,
)

NOTHING_RAN = (
    "Check before this reaches the user: no tool has changed anything for this message. Reading "
    "the state is not changing it. If the user asked for an action, call the tool for it now. If "
    "you were describing something from an earlier message, say that it was earlier. Otherwise "
    "answer again without saying or implying that anything was done, and without bracketed notes."
)
NOT_DONE = "I haven't done that: no action ran. Tell me again what you'd like and I'll do it properly."
NOTHING_PROPOSED = (
    "Check before this reaches the user: you wrote a proposal as words, but nothing is waiting for "
    "their ok, so replying ok would do nothing. If the user asked for this, call the tool now. A "
    "tool with no propose argument shows its own preview with buttons: call it directly. Only if "
    "you are suggesting something they did not ask for, call the tool with propose set to true. "
    "Otherwise answer again without proposing anything."
)
NOT_PROPOSED = "I haven't set anything up to confirm, so “ok” wouldn't do anything. Tell me again what you'd like."
TOOL_SHOWN = (
    "Check before this reaches the user: your reply names a tool or shows a call. The user must "
    "never see tool names or arguments. If you meant to act, call the tool now; otherwise answer "
    "again in plain words."
)


def claims_proposal(reply: str) -> bool:
    """Whether a reply offers something for the user's "ok" ("I'm proposing…",
    "Reply ok to save it"). Only true to its word if a proposal is waiting."""
    return bool(_PROPOSAL_CLAIM.search(reply))


def _internal(names) -> list[str]:
    """The tool names that are no ordinary word: a user never types pill_add."""
    return sorted((name for name in names if "_" in name), key=len, reverse=True)


def shows_tools(reply: str, names) -> bool:
    """Whether a reply shows the user a tool's name ("`pill_add Course A …`")."""
    return any(re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", reply) for name in _internal(names))


def hide_tools(reply: str, names) -> str:
    """A reply with tool names taken out: a call written in backticks becomes
    "that", a bare name becomes ordinary words. The last line of defence; Claude
    is asked to answer again first."""
    for name in _internal(names):
        reply = re.sub(rf"`{re.escape(name)}\b[^`\n]*`", "that", reply)
        reply = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])\s*\([^)\n]*\)", "that", reply)
        reply = re.sub(rf"(?<![\w]){re.escape(name)}(?![\w])", name.replace("_", " "), reply)
    return reply


def scrub(reply: str) -> tuple[str, bool]:
    """A reply without any bracketed tool note ("[Tool calls this turn: ...]").
    Returns (the clean text, whether there was one to remove)."""
    cleaned = _TOOL_NOTE.sub("", reply)
    if cleaned == reply:
        return reply, False
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip(), True


def claims_done(reply: str) -> bool:
    """Whether a reply says, in so many words, that an action was carried out.

    Deliberately narrow (it opens with "Done" or ✅, or carries a made-up tool
    note): it only matters when nothing ran, and a wrong guess costs one more
    request.
    """
    return bool(_DONE_CLAIM.search(reply)) or scrub(reply)[1]


def claims_change(reply: str) -> bool:
    """Whether a reply reports a change as made ("Tea's running again", "I've
    paused it"), as opposed to describing how things stand.

    Wider than claims_done and so less sure: a true account of an earlier
    message reads the same. It is worth asking Claude about once, but never
    grounds for replacing what it says.
    """
    return bool(_CHANGE_CLAIM.search(reply))


async def ask_claude(
    user_text: str,
    capabilities: str = "",
    channel_id: int | None = None,
    tools: list[dict] | None = None,
    run_tool: ToolRunner | None = None,
    acted: Callable[[], bool] | None = None,
    note: str = "",
    closing: Callable[[], Closing | None] | None = None,
    proposed: Callable[[], bool] | None = None,
    purpose: str = "",
) -> ChatResult:
    """Send the message plus recent history to Claude, running any tools it calls.

    `capabilities` describes the bot's own shortcuts; see build_system_prompt.
    `channel_id` picks which channel's conversation this belongs to.
    `tools` are the API tool definitions it may use and `run_tool` runs one
    call. Claude may call several, over several rounds, up to MAX_TOOL_CALLS
    for the message; every result, failures included, goes back to it.
    `acted` says whether a tool has carried out an action for this message
    (looking something up doesn't count); without it, any call that didn't
    fail counts. A reply that says "done" when nothing was is sent back to
    Claude once, to act or to answer again (see ChatResult.unbacked_claim).
    `note` is what the bot adds for this turn only (turn_note: the time and
    the live state); it is sent after the user's words and never remembered.
    `closing` is asked after each round of calls whether the turn can end
    there: if the tools have shown the user what happened, no closing reply
    is requested (one round trip instead of two). It may be a coroutine.
    `proposed` says whether a proposal is waiting for the user's "ok": a reply
    that offers one when none is ("I'm proposing… reply ok") is sent back
    once, like an unbacked "done", and so is one that names a tool.
    """
    history = history_for(channel_id)
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    content = [{"type": "text", "text": user_text}, {"type": "text", "text": note}] if note else user_text
    messages = [*history, {"role": "user", "content": content}]
    use_tools = bool(tools) and run_tool is not None

    request = dict(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=build_system_blocks(capabilities, has_tools=use_tools),
    )
    if use_tools:
        request["tools"] = tools

    result = ChatResult(reply="")

    def none_succeeded() -> bool:
        return all(call.is_error for call in result.tool_calls)

    def nothing_done() -> bool:
        if acted is not None:
            return not acted()
        return none_succeeded()

    def unbacked(said: str) -> bool:
        """A flat "Done" needs an action behind it. The wider wording ("is now
        paused") also fits a true account of what a tool just read, so it is
        only questioned when no tool succeeded at all."""
        return (claims_done(said) and nothing_done()) or (claims_change(said) and none_succeeded())

    tool_names = [tool["name"] for tool in tools or []]

    def empty_offer(said: str) -> bool:
        return claims_proposal(said) and not (proposed is not None and proposed())

    def wrong_with(said: str) -> str | None:
        """What to tell Claude about a reply that must not reach the user as it is."""
        if unbacked(said):
            return NOTHING_RAN
        if empty_offer(said):
            return NOTHING_PROPOSED
        if shows_tools(said, tool_names):
            return TOOL_SHOWN
        return None

    closed: Closing | None = None
    # One round per call at most, plus the reply that closes the turn
    rounds = MAX_TOOL_CALLS + 2
    while rounds > 0:
        rounds -= 1
        asked, retried = time.perf_counter(), timing.claude_retries()
        response = await claude.messages.create(messages=messages, **request)
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        timing.record_claude(
            time.perf_counter() - asked,
            CLAUDE_MODEL,
            usage.input_tokens,
            usage.output_tokens,
            cache_read,
            cache_write,
            retries=timing.claude_retries() - retried,
            purpose=purpose,
        )
        result.input_tokens += usage.input_tokens
        result.output_tokens += usage.output_tokens
        result.cache_read_tokens += cache_read
        result.cache_write_tokens += cache_write

        wanted = [block for block in response.content if block.type == "tool_use"]
        # Only a clean "tool_use" stop is acted on: a reply cut short (max_tokens)
        # or refused may carry half a call, which must never run
        if not use_tools or response.stop_reason != "tool_use" or not wanted:
            said = _text_of(response)
            correction = wrong_with(said) if use_tools and not result.unbacked_claim and said else None
            if correction is not None:
                # It says it is done and nothing was (or offers an "ok" that would do
                # nothing, or shows a tool's name): tell it so, once
                result.unbacked_claim = said
                log.warning("Claude's reply was sent back to it, not to the user: %s", said)
                messages.append({"role": "assistant", "content": said})
                messages.append({"role": "user", "content": correction})
                rounds += 1  # the reply that was sent back doesn't use up a round
                continue
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in wanted:
            call_input = dict(block.input) if isinstance(block.input, dict) else {}
            if len(result.tool_calls) >= MAX_TOOL_CALLS:
                text, is_error = LIMIT_REACHED, True
            else:
                ran = time.perf_counter()
                try:
                    text, is_error = await run_tool(block.name, call_input)
                except Exception as error:
                    log.exception("Tool call failed: %s", block.name)
                    text, is_error = f"The tool failed unexpectedly: {error!r}", True
                timing.record_tool(block.name, time.perf_counter() - ran, is_error)
                result.tool_calls.append(ToolCall(block.name, call_input, text, is_error))
            entry = {"type": "tool_result", "tool_use_id": block.id, "content": text or "done"}
            if is_error:
                entry["is_error"] = True
            results.append(entry)
        # Every result of the round goes back in one message
        messages.append({"role": "user", "content": results})
        # If every call acted and showed the user its own confirmation, that is
        # the answer: asking Claude to say it again would double the wait
        closed = closing() if closing is not None and len(result.tool_calls) < MAX_TOOL_CALLS else None
        if inspect.isawaitable(closed):
            closed = await closed
        if closed is not None:
            break

    if closed is not None:
        result.reply, result.closed_by_tools = closed.say, True
        remembered = closed.remember or closed.say
    else:
        result.reply, _ = scrub(_text_of(response))
        if result.unbacked_claim and claims_done(result.reply) and nothing_done():
            # Told once and it still says so: the user gets the truth instead
            result.reply = NOT_DONE
        elif use_tools and empty_offer(result.reply):
            result.reply = NOT_PROPOSED
        # Never a tool's name. Times are not touched: "05:00 left" on a timer is a
        # length of time, and tools hand over times of day already formatted (8:00 pm)
        result.reply = hide_tools(result.reply, tool_names)
        if not result.reply:
            if response.stop_reason == "tool_use":
                result.reply = "I ran out of steps for that message. Tell me what is still left to do."
            else:
                result.reply = "(No reply from Claude.)" if nothing_done() else "✅ Done."
        remembered = result.reply

    # Only the words: the note for this turn is out of date by the next one
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": remembered})

    log.info(
        "Claude usage: %s in, %s out, cache %s read / %s written, %s tool call(s) (%s)",
        result.input_tokens,
        result.output_tokens,
        result.cache_read_tokens,
        result.cache_write_tokens,
        len(result.tool_calls),
        CLAUDE_MODEL,
    )
    return result
