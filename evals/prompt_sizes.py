"""How long each prompt the bot sends is, in tokens, and how much of it is the part that never changes (the
tools and the system text: the prefix the cache can hold). Asks Anthropic's token counter (free: it sends
nothing to a model and costs nothing); no message of Alex's is ever sent, only a made-up "x".

    python -m evals.prompt_sizes            every prompt, with live's switches on

For docs/drafts/prompt-caching.md. Haiku 4.5 caches a prefix of at least 4,096 tokens.
"""
import asyncio
import os
import sys

SWITCHES = ("BRIEFING_ENABLED", "WEATHER_ENABLED", "DAY_QUESTIONS", "TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED",
            "CALENDAR_ENABLED", "DIARY_ENABLED", "READING_ENABLED", "PLAN_MY_DAY", "BIRTHDAYS_ENABLED", "SMART_INBOX", "CALENDAR_WRITE")
MINIMUM = 4096


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    for name in SWITCHES:
        os.environ[name] = "true"
    os.environ.setdefault("CALENDAR_BOT_ID", "made-up-bot-calendar")
    import anthropic

    from core import actions, config, extraction, routing, smartinbox
    from tasks import registry
    from tasks.reading import pick

    registry.load()
    entries = actions.catalogue()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = [{"role": "user", "content": "x"}]

    def counted(system, tools) -> int:
        return client.messages.count_tokens(model=config.CLAUDE_MODEL, system=system, tools=tools, messages=message).input_tokens

    found = [("router", counted(routing.system_blocks(entries), [routing.tool(entries)]))]
    found.append(("smart inbox (sort)", counted(smartinbox.system_blocks(entries), [smartinbox.tool(entries)])))
    found.append(("daily read (pick and TL;DR)", counted([{"type": "text", "text": pick.SYSTEM}], [pick.tool(5)])))
    for entry in entries:
        found.append((f"extraction · {entry.name}", counted(extraction.system_blocks(entry), extraction.tools(entry))))
    print(f"{'prompt':<34} {'prefix tokens':>13}  cached?")
    for name, tokens in found:
        print(f"{name:<34} {tokens:>13}  {'yes' if tokens >= MINIMUM else 'no: under ' + str(MINIMUM)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
