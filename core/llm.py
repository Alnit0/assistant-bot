import logging

from anthropic import AsyncAnthropic

from core.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MAX_HISTORY,
    MAX_TOKENS,
    MODEL_PRICING,
    now_nz,
)

log = logging.getLogger("assistant")

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Short-term conversation memory (cleared when the bot restarts)
history: list[dict] = []


def build_system_prompt() -> str:
    now = now_nz().strftime("%A %d %B %Y, %I:%M %p")
    return (
        "You are Hive, a personal assistant for Alex, chatting through Discord. "
        "Alex lives in Auckland, New Zealand. "
        f"The current date and time in Auckland is {now}. "
        "Use UK spelling. Keep replies short and conversational, suited to reading on a phone. "
        "Use simple Discord markdown (bold, short bullet lists) only when it genuinely helps."
    )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate the cost of a request in USD, or None if the model's price is unknown."""
    for name, (input_price, output_price) in MODEL_PRICING.items():
        if model.startswith(name):
            return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return None


def format_cost(cost: float | None) -> str:
    return f"US${cost:.4f}" if cost is not None else "Unknown"


async def ask_claude(user_text: str) -> tuple[str, int, int]:
    """Send the message plus recent history to Claude. Returns (reply, input tokens, output tokens)."""
    # Keep only recent history; trimming before adding keeps it starting with a user message
    del history[:-MAX_HISTORY]
    history.append({"role": "user", "content": user_text})

    try:
        response = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(),
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
