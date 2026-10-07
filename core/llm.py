import logging

from anthropic import AsyncAnthropic

from core.config import (
    ANTHROPIC_API_KEY,
    ASSISTANT_NAME,
    CLAUDE_MODEL,
    MAX_HISTORY,
    MAX_TOKENS,
    MODEL_PRICING,
    now_nz,
)

log = logging.getLogger("assistant")

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Short-term conversation memory, one separate history per channel, so a chat
# in one channel never leaks into another. Cleared when the bot restarts.
_histories: dict[int | None, list[dict]] = {}


def history_for(channel_id: int | None) -> list[dict]:
    """The conversation history for one channel (created empty on first use)."""
    return _histories.setdefault(channel_id, [])


def clear_history(channel_id: int | None) -> None:
    """Forget the conversation in one channel. Other channels are untouched."""
    history_for(channel_id).clear()


def build_system_prompt(capabilities: str = "") -> str:
    """The system prompt. `capabilities` is the list of things the bot itself can do
    for this user in this channel (from the skill registry), so Claude can answer
    "what can you do?" accurately."""
    now = now_nz().strftime("%A %d %B %Y, %I:%M %p")
    prompt = (
        f"You are {ASSISTANT_NAME}, a personal assistant for Alex, chatting through Discord. "
        "Alex lives in Auckland, New Zealand. "
        f"The current date and time in Auckland is {now}. "
        "Use UK spelling. Keep replies short and conversational, suited to reading on a phone. "
        "Use simple Discord markdown (bold, short bullet lists) only when it genuinely helps."
    )
    # Always said, list or no list: Claude has no tools until the tool-calling stage
    prompt += (
        "\n\nYou have no tools yet. You cannot run commands or take any action yourself: you "
        "cannot set timers or reminders, pin, archive or delete messages, look anything up "
        "or remember anything beyond this chat, and a message that reaches you did not "
        "trigger anything. Never offer to perform an action, and never say or imply that "
        "you have done one."
    )
    if capabilities:
        prompt += (
            "\n\nThe Discord bot you speak through does have built-in shortcuts, listed "
            "below, which the user triggers themselves. If the user asks what you can do, or "
            "asks for something on this list, tell them exactly what to type or do (and that "
            "`help` shows the full list). Do not claim abilities that are neither listed "
            "here nor part of ordinary conversation.\n\n"
            f"{capabilities}"
        )
    return prompt


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate the cost of a request in USD, or None if the model's price is unknown."""
    for name, (input_price, output_price) in MODEL_PRICING.items():
        if model.startswith(name):
            return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return None


def format_cost(cost: float | None) -> str:
    return f"US${cost:.4f}" if cost is not None else "Unknown"


async def ask_claude(
    user_text: str, capabilities: str = "", channel_id: int | None = None
) -> tuple[str, int, int]:
    """Send the message plus recent history to Claude. Returns (reply, input tokens, output tokens).

    `capabilities` describes the bot's own shortcuts; see build_system_prompt.
    `channel_id` picks which channel's conversation this belongs to.
    """
    history = history_for(channel_id)
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    history.append({"role": "user", "content": user_text})

    try:
        response = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(capabilities),
            messages=history,
        )
    except Exception:
        # Remove the failed message so history stays valid
        history.pop()
        raise

    reply = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if not reply:
        reply = "(No reply from Claude.)"

    history.append({"role": "assistant", "content": reply})

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    log.info("Claude usage: %s in, %s out (%s)", input_tokens, output_tokens, CLAUDE_MODEL)
    return reply, input_tokens, output_tokens
