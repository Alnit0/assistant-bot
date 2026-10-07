import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from core.config import (
    ANTHROPIC_API_KEY,
    ASSISTANT_NAME,
    CLAUDE_MODEL,
    MAX_HISTORY,
    MAX_TOKENS,
    MAX_TOOL_CALLS,
    MODEL_PRICING,
    now_nz,
)

log = logging.getLogger("assistant")

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Short-term conversation memory, one separate history per channel, so a chat
# in one channel never leaks into another. Cleared when the bot restarts.
# Only plain text is kept: tool calls live within one turn and are summed up
# in a line, so trimming can never split a call from its result.
_histories: dict[int | None, list[dict]] = {}

# Cached input is cheaper to read and dearer to write than ordinary input
CACHE_READ_PRICE, CACHE_WRITE_PRICE = 0.1, 1.25
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
            "happens until they do.\n"
            "- Never say that something has been done unless a tool result says so. A result that "
            "says it is waiting (for ok, for Confirm, or for the user to pick a message) means it "
            "has not happened yet: say so.\n"
            "- Never claim or offer to do something you have no tool for. If a word the user can "
            "type would do it, tell them what to type; otherwise say you can't.\n"
            "- If a tool fails, explain why in plain words and what they could do about it.\n"
            "- Tools that act on a message: if the user's message is a reply, leave targets empty "
            "and the message they replied to is used. Otherwise call recent_messages, then give "
            "the ref of the message they mean; if more than one fits, give each and the user is "
            "asked to pick. Never guess between them.\n"
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


def build_system_blocks(capabilities: str = "", has_tools: bool = False) -> list[dict]:
    """The system prompt as the API takes it: the stable part, marked for caching,
    then the time (which would otherwise spoil the cache every minute)."""
    return [
        {"type": "text", "text": _stable_prompt(capabilities, has_tools), "cache_control": CACHED},
        {"type": "text", "text": _time_line()},
    ]


def build_system_prompt(capabilities: str = "", has_tools: bool = False) -> str:
    """The system prompt as one text. `capabilities` is the list of things the bot
    itself can do for this user in this channel (from the skill registry), so Claude
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
    for name, (input_price, output_price) in MODEL_PRICING.items():
        if model.startswith(name):
            input_cost = (
                input_tokens + cache_read_tokens * CACHE_READ_PRICE + cache_write_tokens * CACHE_WRITE_PRICE
            ) * input_price
            return (input_cost + output_tokens * output_price) / 1_000_000
    return None


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
    input_tokens: int = 0  # not counting what was read from or written to the cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)


# `async (name, input) -> (text for Claude, is it an error)`
ToolRunner = Callable[[str, dict], Awaitable[tuple[str, bool]]]


def _text_of(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _actions_note(calls: list[ToolCall]) -> str:
    """One line for the history, so a later message knows what was done in this one."""
    parts = [f"{call.name} ({'failed' if call.is_error else 'result'}: {call.result[:120]})" for call in calls]
    return f"\n[Tool calls this turn: {'; '.join(parts)}]"


async def ask_claude(
    user_text: str,
    capabilities: str = "",
    channel_id: int | None = None,
    tools: list[dict] | None = None,
    run_tool: ToolRunner | None = None,
) -> ChatResult:
    """Send the message plus recent history to Claude, running any tools it calls.

    `capabilities` describes the bot's own shortcuts; see build_system_prompt.
    `channel_id` picks which channel's conversation this belongs to.
    `tools` are the API tool definitions it may use and `run_tool` runs one
    call. Claude may call several, over several rounds, up to MAX_TOOL_CALLS
    for the message; every result, failures included, goes back to it.
    """
    history = history_for(channel_id)
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    messages = [*history, {"role": "user", "content": user_text}]
    use_tools = bool(tools) and run_tool is not None

    request = dict(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=build_system_blocks(capabilities, has_tools=use_tools),
    )
    if use_tools:
        request["tools"] = tools

    result = ChatResult(reply="")
    # One round per call at most, plus the reply that closes the turn
    for _ in range(MAX_TOOL_CALLS + 2):
        response = await claude.messages.create(messages=messages, **request)
        usage = response.usage
        result.input_tokens += usage.input_tokens
        result.output_tokens += usage.output_tokens
        result.cache_read_tokens += getattr(usage, "cache_read_input_tokens", None) or 0
        result.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", None) or 0

        wanted = [block for block in response.content if block.type == "tool_use"]
        # Only a clean "tool_use" stop is acted on: a reply cut short (max_tokens)
        # or refused may carry half a call, which must never run
        if not use_tools or response.stop_reason != "tool_use" or not wanted:
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in wanted:
            call_input = dict(block.input) if isinstance(block.input, dict) else {}
            if len(result.tool_calls) >= MAX_TOOL_CALLS:
                text, is_error = LIMIT_REACHED, True
            else:
                try:
                    text, is_error = await run_tool(block.name, call_input)
                except Exception as error:
                    log.exception("Tool call failed: %s", block.name)
                    text, is_error = f"The tool failed unexpectedly: {error!r}", True
                result.tool_calls.append(ToolCall(block.name, call_input, text, is_error))
            entry = {"type": "tool_result", "tool_use_id": block.id, "content": text or "done"}
            if is_error:
                entry["is_error"] = True
            results.append(entry)
        # Every result of the round goes back in one message
        messages.append({"role": "user", "content": results})

    result.reply = _text_of(response)
    if not result.reply:
        if response.stop_reason == "tool_use":
            result.reply = "I ran out of steps for that message. Tell me what is still left to do."
        else:
            result.reply = "✅ Done." if result.tool_calls else "(No reply from Claude.)"

    history.append({"role": "user", "content": user_text})
    remembered = result.reply + (_actions_note(result.tool_calls) if result.tool_calls else "")
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
