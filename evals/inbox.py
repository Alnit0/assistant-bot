"""The smart inbox's checks against the real API: each conversation of evals/fixtures/inbox.json is asked as
the bot asks it (the router, then `sort`, then each item's own extraction; files straight to `sort`), judged
against what it should come to, and with --record kept for tests/test_golden_inbox.py to replay.

    python -m evals.inbox                    say what it would ask, and roughly what it would cost
    python -m evals.inbox --live             ask the real API (costs money: a few cents)
    python -m evals.inbox --live --record    ...and keep what came back
    python -m evals.inbox --live --only i1,f2

The files are made up and drawn by evals/inbox_files.py. Nothing here reads or writes a database.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ARGS = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ARGS.add_argument("--live", action="store_true")
ARGS.add_argument("--record", action="store_true")
ARGS.add_argument("--only", default="")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "inbox.json"
ROUGH_COST = 0.004  # US$ a request, roughly


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def problem(conversation: dict, route, found, extracted: list) -> str:
    """What is wrong with what came back, or ""."""
    expect = conversation["expect"]
    if "several" in expect and route is not None and route.several != expect["several"]:
        return f"expected several={expect['several']}, got {route.several}"
    if found is None:
        return "" if not expect.get("items") else "nothing was sorted"
    tasks = [task for _, task in found.items]
    if "items" in expect and sorted(tasks) != sorted(expect["items"]):
        return f"expected items for {sorted(expect['items'])}, got {sorted(tasks)}"
    if expect.get("saw") and not found.saw:
        return "expected a line saying what the file shows"
    actions_ = [called[0] for called in extracted if called]
    for wanted in expect.get("actions", []):
        if wanted not in actions_:
            return f"expected {wanted} among {actions_}"
    return ""


def main() -> int:
    options = ARGS.parse_args()
    # Every task the inbox sorts into, whatever the work folder's settings say
    for name in ("TODOS_ENABLED", "NUDGES_ENABLED", "HABITS_ENABLED", "DIARY_ENABLED", "CALENDAR_ENABLED", "CALENDAR_WRITE", "BRIEFING_ENABLED", "DAY_QUESTIONS", "WEATHER_ENABLED", "NUDGES_ENABLED", "BIRTHDAYS_ENABLED"):
        os.environ[name] = "true"
    # Writing to a Bot calendar, as live has it (a made-up id: nothing is ever written from here)
    os.environ["CALENDAR_BOT_ID"] = "made-up-bot-calendar"
    from core import actions, costs, extraction, llm, routing, smartinbox, timing
    from evals import inbox_files
    from tasks import registry

    registry.load()
    entries = actions.catalogue()
    content = load()
    conversations = content["inbox"]
    if options.only:
        wanted = {each.strip() for each in options.only.split(",")}
        conversations = [each for each in conversations if each["golden"] in wanted]
    print(f"Tasks: {', '.join(sorted(entry.name for entry in entries))}")
    print(f"{len(conversations)} conversations, roughly US${len(conversations) * 4 * ROUGH_COST:.2f}")
    if not options.live:
        print("Nothing was sent. Add --live to run it.")
        return 0
    by_golden = {each["golden"]: each for each in content["inbox"]}

    async def one(conversation: dict):
        route = found = None
        recorded: dict = {"extract": []}
        read = None
        if conversation.get("file"):
            name, data, kind = inbox_files.FILES[conversation["file"]]()

            async def fetch(data=data):
                return data

            read = await smartinbox.read_files((actions.Attachment(name, len(data), kind, fetch),))
        on_card = None
        if conversation.get("after"):
            earlier = by_golden[conversation["after"]]["recorded"]["sort"]
            on_card = [{"words": each["words"], "task": each["task"]} for each in earlier["items"]]
        if read is None and on_card is None:
            called = await llm.call_tool(
                routing.system_blocks(entries), routing.user_turn(conversation["message"]), [routing.tool(entries)],
                choice={"type": "tool", "name": routing.TOOL}, purpose=costs.PURPOSE_ROUTER, max_tokens=routing.MAX_TOKENS,
            )
            recorded["route"] = called[1] if called else None
            route = routing.parse(recorded["route"], [entry.name for entry in entries])
            if not route.several:
                return route, None, recorded
        called = await llm.call_tool(
            smartinbox.system_blocks(entries), smartinbox.user_turn(conversation["message"], read, on_card), [smartinbox.tool(entries)],
            choice={"type": "tool", "name": smartinbox.TOOL}, purpose=smartinbox.PURPOSE, max_tokens=smartinbox.MAX_TOKENS,
        )
        recorded["sort"] = called[1] if called else None
        found = smartinbox.parse(recorded["sort"], [entry.name for entry in entries])
        unchanged = {(each["words"], each["task"]) for each in on_card or []}
        for words, task in found.items:
            entry = next((each for each in entries if each.name == task), None)
            if entry is None or (words, task) in unchanged:
                continue
            got = await llm.call_tool(
                extraction.system_blocks(entry), extraction.user_turn(words, elsewhere="the rest of the message, sorted separately"),
                extraction.tools(entry), choice={"type": "any"}, purpose=costs.PURPOSE_EXTRACTION, task=entry.name, max_tokens=extraction.MAX_TOKENS,
            )
            recorded["extract"].append([words, task, list(got) if got else None])
        return route, found, recorded

    async def every():
        wrong = []
        for conversation in conversations:
            route, found, recorded = await one(conversation)
            said = problem(conversation, route, found, [each[2] for each in recorded["extract"]])
            print(("ok   " if not said else "FAIL ") + f"{conversation['golden']} {conversation['message'][:60]!r}" + (f" -> {said}" if said else ""))
            if said:
                wrong.append(conversation["golden"])
            if options.record:
                by_golden[conversation["golden"]]["recorded"] = recorded
        return wrong

    turn = timing.start()
    wrong = asyncio.run(every())
    timing.stop()
    calls = costs.calls_from(turn.claude_calls, "")
    total = sum(call.cost or 0 for call in calls)
    print(f"{len(calls)} requests, US${total:.4f}; right {len(conversations) - len(wrong)} of {len(conversations)}")
    if options.record:
        FIXTURE.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Recorded into evals/fixtures/inbox.json")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
