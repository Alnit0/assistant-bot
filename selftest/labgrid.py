"""The lab's animated grid on the dev bot: `python -m selftest.labgrid`.

"lab grid" is typed as the owner in the self-test's #inbox, once at 1.0 seconds a frame and once at 0.5,
and each run's measurements are read back (the gap between frames, the slowest, any edit rate-limited or
failed). Both grids are left in the channel for Alex to compare on his phone. As the dev bot only, live
left up, never between 3:15 and 4:30 am, only with enough free memory; the dev database is set aside and
put back as a self-test does, and the channel is not purged first. No request goes to Claude.
"""
import asyncio
import json
import sys
from datetime import datetime

NAME = "lab_grid"
RUNS = (("lab grid", 1.0), ("lab grid 0.5", 0.5))


async def story(h) -> None:
    from tasks.lab import animate, grid

    h.memo["grids"] = []
    for said, seconds in RUNS:
        async for attempt in h.step(f"g.{seconds}", f"“{said}”", "one message of squares, edited through 10 frames, ending all green", "the lab's grid"):
            async with attempt:
                await h.say(said, channel=h.inbox, wait=0.5)
                for _ in range(int(grid.LAST * (seconds + 3)) + 10):  # the whole run, and some
                    if not animate.lock.running:
                        break
                    await asyncio.sleep(0.5)
                run = animate.last
                h.check(run is not None and run.seconds == seconds, f"no run at {seconds}s")
                h.memo["grids"].append({"seconds": seconds, "frames": run.frames, "average": round(run.average, 3), "slowest": round(run.slowest, 3),
                                        "limited": run.limited, "failed": run.failed, "gaps": [round(each, 3) for each in run.gaps]})
                h.saw(run.line())
                shown = await h.find(h.inbox, grid.frame_text(grid.LAST))
                h.check(shown is not None, "the last frame (all green) is not in #inbox")
                h.check(run.finished, f"stopped early: {run.line()}")
        await asyncio.sleep(2)  # the second starts once the first is well done


PHASES = {NAME: story}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from selftest import __main__ as launcher
    from selftest import day, stages
    from core import instance_lock

    if not launcher.separate():
        print("There is no dev bot (.env.dev needs its own token): the grid runs only as the dev bot.")
        return 3
    if instance_lock.holder(instance_lock.TEST_LOCK) is not None:
        print("The dev bot is already running: stop it first.")
        return 3
    why = day.may_run(datetime.now())
    if why:
        print(f"Not started: {why}.")
        return 3
    low, line = stages.memory_line(stages.free_memory())
    print(f"--- {line}", flush=True)
    if low:
        print("--- not started: too little free memory.")
        return 3
    for each in launcher.recover():
        print(f"--- an earlier run had left the dev database aside: put back ({each['date']})", flush=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    channels = asyncio.run(launcher.prepare_channels(purge=False))
    saved = launcher.set_aside(stamp)
    try:
        found = launcher.run_phase(NAME, {"LAB_GRID": "true"}, channels, False, 0.0, {}, stamp)
    finally:
        launcher.put_back(saved, stamp)
        try:
            print(f"--- the dev bot's name: {asyncio.run(launcher.plain_name(channels['inbox']))}", flush=True)
        except Exception as error:
            print(f"--- the dev bot's name could not be put back ({type(error).__name__})", flush=True)
    for each in found["results"]:
        print(f"[{each['status']}] {each['key']} {each['title']} :: {each['saw'][:300]}")
    grids = found.get("memo", {}).get("grids", [])
    out = launcher.WORK / f"labgrid-{stamp}.json"
    out.write_text(json.dumps({"stamp": stamp, "exit": found.get("exit"), "grids": grids, "results": found["results"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [each for each in found["results"] if each["status"] in ("fail", "error")]
    print(f"--- {len(found['results'])} steps, {len(bad)} failed, exit {found.get('exit')}. Kept: {out}")
    return 0 if not bad and found.get("exit") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
