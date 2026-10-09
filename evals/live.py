"""The live eval: ask the real API every fixture and say how often it is right,
how long it takes and what it costs.

    python -m evals.live --live              run every fixture against the real API
    python -m evals.live --live --record     ...and keep what came back, for the ordinary tests
    python -m evals.live --live --strict     ...sending the schemas as strict, to compare the time
    python -m evals.live --live --only pills  one fixture file
    python -m evals.live                     say what it would run, and roughly what it would cost

It spends real money (a few cents), so nothing is sent without --live. It
uses the real .env, starts no bot, and reads and writes no database: a
fixture carries any state it needs. Add --dev to include the demo tasks,
which are only offered on the dev database.
"""
import argparse
import asyncio
import sys
import time

# Read before core.config looks at the command line for --dev
ARGS = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ARGS.add_argument("--live", action="store_true", help="really call the API (costs money)")
ARGS.add_argument("--record", action="store_true", help="save what Claude returned into the fixture files")
ARGS.add_argument("--strict", action="store_true", help="send action schemas as strict")
ARGS.add_argument("--only", default="", help="run one fixture file, by its name without .json")
ARGS.add_argument("--dev", action="store_true", help="include the demo tasks (dev database only)")

# Roughly what one request costs with the current model: for the estimate before running
ROUGH_COST_PER_REQUEST = 0.0015


def main() -> int:
    options = ARGS.parse_args()

    from core import actions, costs, extraction, routing, timing
    from core.config import CLAUDE_MODEL
    from evals import fixtures
    from tasks import registry

    registry.load()
    entries = actions.catalogue()
    routers, extractions = fixtures.load()
    known = {entry.name for entry in entries}
    if options.only:
        routers = [fixture for fixture in routers if fixture.file == options.only]
        extractions = [fixture for fixture in extractions if fixture.file == options.only]
    skipped = [fixture.name for fixture in routers if set(fixture.tasks) - known]
    skipped += [fixture.name for fixture in extractions if fixture.task not in known]
    routers = [fixture for fixture in routers if not set(fixture.tasks) - known]
    extractions = [fixture for fixture in extractions if fixture.task in known]

    requests = len(routers) + len(extractions)
    print(f"Tasks in the catalogue: {', '.join(sorted(known)) or 'none'}")
    print(f"{len(routers)} router and {len(extractions)} extraction fixtures: {requests} requests to {CLAUDE_MODEL}")
    if skipped:
        print(f"Skipped (their task isn't loaded; try --dev): {len(skipped)}")
    print(f"Roughly US${requests * ROUGH_COST_PER_REQUEST:.2f}")
    if not options.live:
        print("Nothing was sent. Add --live to run it.")
        return 0
    if not requests or not entries:
        return 0

    async def run() -> tuple[list, list]:
        failures, times = [], {"router": [], "extraction": []}
        for fixture in routers:
            began = time.perf_counter()
            called = await _call_router(fixture, entries)
            times["router"].append(time.perf_counter() - began)
            fixture.recorded = called[1] if called else None
            problem = fixtures.router_problem(fixture, routing.parse(fixture.recorded, [entry.name for entry in entries]))
            print(_mark(problem, fixture) + f"route    {fixture.message!r}" + (f"  -> {problem}" if problem else ""))
            if problem:
                (known if fixture.known_miss else failures).append(fixture.name)
        for fixture in extractions:
            entry = actions.entry(fixture.task)
            card = extraction.OpenCard(**fixture.card) if fixture.card else None
            began = time.perf_counter()
            called = await _call_extraction(entry, fixture, card, options.strict)
            times["extraction"].append(time.perf_counter() - began)
            fixture.recorded = list(called) if called else None
            problem = fixtures.extraction_problem(fixture, extraction.read(entry, called, follow_up=card is not None))
            print(_mark(problem, fixture) + f"extract  {fixture.message!r}" + (f"  -> {problem}" if problem else ""))
            if problem:
                (known if fixture.known_miss else failures).append(fixture.name)
        return failures, times

    known: list[str] = []

    def _mark(problem: str, fixture) -> str:
        if not problem:
            return "ok   "
        return "miss " if fixture.known_miss else "FAIL "

    async def _call_router(fixture, entries):
        from core import llm

        return await llm.call_tool(
            routing.system_blocks(entries),
            routing.user_turn(fixture.message, fixture.on_screen),
            [routing.tool(entries)],
            choice={"type": "tool", "name": routing.TOOL},
            purpose=costs.PURPOSE_ROUTER,
            max_tokens=routing.MAX_TOKENS,
        )

    async def _call_extraction(entry, fixture, card, strict):
        from core import llm

        return await llm.call_tool(
            extraction.system_blocks(entry, card is not None),
            extraction.user_turn(fixture.message, fixture.state, card),
            extraction.tools(entry, card is not None, strict=strict),
            choice={"type": "any"},
            purpose=costs.PURPOSE_EXTRACTION,
            task=entry.name,
            max_tokens=extraction.MAX_TOKENS,
        )

    turn = timing.start()
    failures, times = asyncio.run(run())
    timing.stop()
    calls = costs.calls_from(turn.claude_calls, "")

    print()
    for purpose in ("router", "extraction"):
        mine = [call for call in calls if call.purpose == purpose]
        if not mine:
            continue
        cost = sum(call.cost or 0 for call in mine)
        taken = times[purpose]
        print(
            f"{purpose}: {len(mine)} requests · US${cost:.4f} (US${cost / len(mine):.5f} each) · "
            f"{sum(taken) / len(taken):.2f}s each, slowest {max(taken):.2f}s · "
            f"{sum(call.input_tokens for call in mine)} in, {sum(call.cache_read_tokens for call in mine)} from cache, "
            f"{sum(call.cache_write_tokens for call in mine)} to cache, {sum(call.output_tokens for call in mine)} out"
        )
    total = sum(call.cost or 0 for call in calls)
    right = requests - len(failures) - len(known)
    print(f"Right: {right} of {requests} ({right / requests:.0%})" + ("  [strict schemas]" if options.strict else ""))
    print(f"Cost of this run: US${total:.4f}")
    for name in failures:
        print(f"  wrong: {name}")
    for name in known:
        print(f"  known miss: {name}")
    if options.record:
        fixtures.save_recorded(routers, extractions)
        print("Recorded what came back into evals/fixtures/.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
