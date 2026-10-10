import logging
import time
from dataclasses import dataclass

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
    now_nz,
)

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# The Claude client. Two kinds of request, and nothing else:
#
#   call_tool   one request that must come back as a tool call: the router
#               and extraction (core/routing.py, core/extraction.py). Nothing
#               Claude writes as text is read.
#   ask_claude  plain chat: an answer to a question that is for no task. It
#               has no tools and no access to the user's data, and is told
#               so. What a task's code said to the user is never shown to it.
#
# Claude never runs anything and never writes a confirmation: the tasks' own
# code does both (core/conversation.py).
# ---------------------------------------------------------------------------
# A short timeout: a request that hangs is given up and retried, not waited ten
# minutes for (the SDK's default). Retries show in the log and on the #bot-log card
claude = AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=Timeout(CLAUDE_TIMEOUT, connect=CLAUDE_CONNECT_TIMEOUT),
    max_retries=CLAUDE_RETRIES,
)

# Short-term memory, one per channel, cleared when the bot restarts. Two kinds,
# kept apart on purpose:
#   _histories  what was said in plain chat, and nothing else. It is all chat is
#               given, so chat can never answer about lists, pills or timers:
#               it has not seen them.
#   _exchanges  everything the user said and what the bot showed for it (a card,
#               a confirmation, a chat answer), as plain pairs. Only the router
#               reads these, to follow the conversation.
_histories: dict[int | None, list[dict]] = {}
_exchanges: dict[int | None, list[tuple[str, str]]] = {}
MAX_EXCHANGES = 20

CACHED = {"type": "ephemeral"}

# What chat answers, alone on a line, when the message is about the user's own
# data after all: the message is then routed to the task that owns it
ABOUT_DATA = "[[about-my-data]]"


def history_for(channel_id: int | None) -> list[dict]:
    """The plain-chat history for one channel (created empty on first use)."""
    return _histories.setdefault(channel_id, [])


def exchanges_for(channel_id: int | None) -> list[tuple[str, str]]:
    """What was said in a channel and what the bot showed for it, oldest first."""
    return _exchanges.setdefault(channel_id, [])


def clear_history(channel_id: int | None) -> None:
    """Forget the conversation in one channel. Other channels are untouched."""
    history_for(channel_id).clear()
    exchanges_for(channel_id).clear()


def remember(channel_id: int | None, user_text: str, bot_text: str) -> None:
    """Note an exchange for the router: what the user said or pressed, and what
    the bot's own code showed. Never given to chat. An exchange with nothing
    shown (a remark that got no reply) is not kept: there is nothing to follow."""
    if not bot_text.strip():
        return
    kept = exchanges_for(channel_id)
    kept.append((user_text, bot_text))
    del kept[:-MAX_EXCHANGES]


# ---------------------------------------------------------------------------
# The chat prompt: fixed text, so it can be cached
# ---------------------------------------------------------------------------
def _stable_prompt(capabilities: str) -> str:
    prompt = (
        f"You are {ASSISTANT_NAME}, a personal assistant for Alex, chatting through Discord. "
        "Alex lives in Auckland, New Zealand. "
        "Use UK spelling. Keep replies short and conversational, suited to reading on a phone. "
        "Use simple Discord markdown (bold, short bullet lists) only when it genuinely helps. "
        "Write times of day as 8:00 pm, never 20:00.\n\n"
        "You answer general questions and nothing else. You have no tools: you cannot run anything, "
        "and a message that reaches you did not trigger anything. Never say or imply that you have "
        "done something.\n\n"
        "You have NO access to the user's own data: their lists, pills, timers, notes, reminders, bug "
        "reports or anything else the bot keeps for them. You have not seen it, and nothing in this "
        "chat tells you what it holds. If the message asks about any of that, or asks for something "
        f"to be added, changed, shown or removed there, answer with exactly `{ABOUT_DATA}` and nothing "
        "else: the bot's own code will deal with it. Never guess what their data holds.\n\n"
        "Answer the question and stop. Never offer to do something, never offer further help, and never "
        "end with a question such as \"want me to…?\", \"would you like…?\" or \"anything else?\"."
    )
    if capabilities:
        prompt += (
            "\n\nThe Discord bot you speak through has built-in shortcuts, listed below, which the user "
            "triggers themselves. If the user asks what the bot can do, or how to do something on this "
            "list, tell them exactly what to type or do (`help` shows the full list). Do not claim "
            "abilities that are not listed here.\n\n"
            f"{capabilities}"
        )
    return prompt


def _time_line() -> str:
    return f"The current date and time in Auckland is {now_nz().strftime('%A %d %B %Y, %I:%M %p')}."


def build_system_blocks(capabilities: str = "") -> list[dict]:
    """The chat prompt as the API takes it: one block, the same for every
    message, marked for caching. Nothing that changes goes in it."""
    return [{"type": "text", "text": _stable_prompt(capabilities), "cache_control": CACHED}]


def build_system_prompt(capabilities: str = "") -> str:
    """The chat prompt as one text. `capabilities` is the list of the bot's
    shortcuts for this user in this channel (from the task registry), so chat
    can say what to type."""
    return "\n\n".join(block["text"] for block in build_system_blocks(capabilities))


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
# Plain chat
# ---------------------------------------------------------------------------
@dataclass
class ChatResult:
    reply: str
    about_data: bool = False  # chat said the message is about the user's data: it is to be routed to a task
    input_tokens: int = 0  # not counting what was read from or written to the cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def _text_of(response) -> str:
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


async def ask_claude(
    user_text: str,
    capabilities: str = "",
    channel_id: int | None = None,
    purpose: str = "",
) -> ChatResult:
    """A plain answer from Claude to a message that is for no task. No tools.

    It is sent the plain-chat history of the channel and the time, and
    nothing about the user's data. If it says the message is about that data
    after all (ABOUT_DATA), `about_data` is set, nothing is remembered, and
    the caller routes the message to a task instead.
    """
    history = history_for(channel_id)
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    content = [{"type": "text", "text": user_text}, {"type": "text", "text": f"[Note from the bot] {_time_line()}"}]
    asked, retried = time.perf_counter(), timing.claude_retries()
    response = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=build_system_blocks(capabilities),
        messages=[*history, {"role": "user", "content": content}],
    )
    usage = response.usage
    result = ChatResult(
        reply=_text_of(response),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
    )
    timing.record_claude(
        time.perf_counter() - asked, CLAUDE_MODEL, result.input_tokens, result.output_tokens,
        result.cache_read_tokens, result.cache_write_tokens,
        retries=timing.claude_retries() - retried, purpose=purpose,
    )
    if ABOUT_DATA in result.reply:
        result.reply, result.about_data = "", True
        return result
    # Only the words, and only chat's own: nothing a task's code said is ever in here
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": result.reply})
    log.info(
        "Claude usage: %s in, %s out, cache %s read / %s written (%s)",
        result.input_tokens, result.output_tokens, result.cache_read_tokens, result.cache_write_tokens, CLAUDE_MODEL,
    )
    return result
